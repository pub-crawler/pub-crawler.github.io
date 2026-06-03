import asyncio
from pub_crawler.webfinger_client import WebfingerClient
from pub_crawler.webfinger_handler import WebfingerHandler
import networkx as nx

MAX_WORKERS = 3

async def worker(name, wfq, wfh):
    while True:
        job = await wfq.get()
        try:
            if job['job_type'] == 'webfinger':
                await wfh.handle(job)
            else:
                raise Exception(f"Unrecognized job type {job['job_type']}")
        except Exception:
            pass
        wfq.task_done()

async def crawl_graph(inputfile, outputfile, *, transport=None):
    wfc = WebfingerClient(transport=transport)
    G = nx.DiGraph()
    wfq = asyncio.Queue()
    wfh = WebfingerHandler(wfc, None, G)

    tasks = []
    for i in range(MAX_WORKERS):
        task = asyncio.create_task(worker(f'wfw-{i}', wfq, wfh))
        tasks.append(task)

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
                await wfq.put(job)

        await wfq.join()

        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

    finally:
        await wfc.aclose()

    nx.write_gml(G, outputfile)

if __name__ == "__main__":

    import sys
    input = sys.argv[1]
    output = sys.argv[2]
    asyncio.run(crawl_graph(input, output))
