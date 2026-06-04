from pathlib import Path
import asyncio
from pub_crawler.webfinger_client import WebfingerClient
from pub_crawler.webfinger_handler import WebfingerHandler
from pub_crawler.activity_pub_client import ActivityPubClient
from pub_crawler.actor_handler import ActorHandler
from pub_crawler.collection_handler import CollectionHandler
from pub_crawler.page_handler import PageHandler
from pub_crawler.fixed_window_counter import FixedWindowCounter
import networkx as nx
import logging

MAX_WORKERS = 25
MAX_DEPTH = 1
KEY_ID = 'https://crawler.pub/actor#main-key'

async def worker(name, q, wfh, ah, ch, ph):
    while True:
        job = await q.get()
        try:
            logging.debug(job)
            if job['job_type'] == 'webfinger':
                await wfh.handle(job)
            elif job['job_type'] == 'actor':
                await ah.handle(job)
            elif job['job_type'] == 'collection':
                await ch.handle(job)
            elif job['job_type'] == 'page':
                await ph.handle(job)
            else:
                raise Exception(f"Unrecognized job type {job['job_type']}")
        except Exception as e:
            logging.debug(e)
            pass
        q.task_done()

async def crawl_graph(inputfile, outputfile, *, transport=None):
    private_key_pem = Path("private.pem").read_text()   # CLI default
    general = FixedWindowCounter(300, 5 * 60 * 1000)
    paged = FixedWindowCounter(300, 15 * 60 * 1000)
    wfc = WebfingerClient(general, transport=transport)
    ac = ActivityPubClient(KEY_ID, private_key_pem, general, paged, transport=transport)
    G = nx.DiGraph()
    q = asyncio.Queue()
    wfh = WebfingerHandler(wfc, q, G)
    ah = ActorHandler(ac, q, G)
    ch = CollectionHandler(ac, q, G, MAX_DEPTH)
    ph = PageHandler(ac, q, G)

    workers = []
    for i in range(MAX_WORKERS):
        workers.append(asyncio.create_task(worker(f'wfw-{i}', q, wfh, ah, ch, ph)))

    try:

        with open(inputfile) as f:
            for line in f:
                wf = line.strip()
                if not wf:
                    continue
                job = {
                    "job_type": "webfinger",
                    "webfinger": wf
                }
                await q.put(job)

        await q.join()

        for w in workers:
            w.cancel()

        await asyncio.gather(*workers, return_exceptions=True)

    finally:
        await wfc.aclose()
        await ac.aclose()

    nx.write_gml(G, outputfile)

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    import sys
    input = sys.argv[1]
    output = sys.argv[2]
    asyncio.run(crawl_graph(input, output))
