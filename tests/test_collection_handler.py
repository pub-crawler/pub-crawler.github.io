"""Tests for CollectionHandler — save the count, and (now) enqueue the first page.

handle fetches the collection (followers/following), stores its totalItems on
the owner's node keyed by direction (followers_count / following_count), and —
now — enqueues a page job for the collection's `first`, gated by
depth < max_depth (so a leaf collection at depth == max_depth gets counted but
not walked).

NOTE: inline-item collections (orderedItems on the collection itself, no
`first`) are NOT handled here yet — that branch is deferred. These tests use the
paginated shape (a `first` link).

Pure DI unit tests: a fake async client, a real asyncio.Queue, a real DiGraph.

Assumed contract (flag if different):
  CollectionHandler(client, queue, graph, max_depth).handle(job)
    job = {job_type:'collection', collection_id, owner_id, direction, depth}
    coll = await client.get(collection_id)
    graph.nodes[owner_id][f"{direction}_count"] = coll["totalItems"]
    if depth < max_depth and coll has 'first':
        enqueue {job_type:'page', page_id:first, owner_id, direction, depth}
"""

import asyncio

import networkx as nx
import pytest

from pub_crawler.collection_handler import CollectionHandler

OWNER_ID = "https://example.com/foo"
FOLLOWERS_ID = "https://example.com/foo/followers"
FOLLOWING_ID = "https://example.com/foo/following"
TOTAL = 42
MAX_DEPTH = 2


def collection(collection_id, total=TOTAL):
    return {
        "id": collection_id,
        "type": "OrderedCollection",
        "totalItems": total,
        "first": f"{collection_id}?page=1",
    }


def collection_job(collection_id, direction, depth):
    return {
        "job_type": "collection",
        "collection_id": collection_id,
        "owner_id": OWNER_ID,
        "direction": direction,
        "depth": depth,
    }


def page_job(page_id, direction, depth):
    return {
        "job_type": "page",
        "page_id": page_id,
        "owner_id": OWNER_ID,
        "direction": direction,
        "depth": depth,
    }


def drain(queue):
    jobs = []
    while not queue.empty():
        jobs.append(queue.get_nowait())
    return jobs


class FakeActivityPubClient:
    def __init__(self, doc=None, error=None):
        self.doc = doc
        self.error = error
        self.calls = []

    async def get(self, url):
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return self.doc


def make_handler(client, queue, graph, max_depth=MAX_DEPTH):
    return CollectionHandler(client, queue, graph, max_depth)


# ---------------------------------------------------------------------------
# Count (unconditional)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "direction, collection_id",
    [("followers", FOLLOWERS_ID), ("following", FOLLOWING_ID)],
)
async def test_saves_count_on_owner_node_keyed_by_direction(direction, collection_id):
    client = FakeActivityPubClient(doc=collection(collection_id))
    queue = asyncio.Queue()
    graph = nx.DiGraph()
    graph.add_node(OWNER_ID)

    await make_handler(client, queue, graph).handle(
        collection_job(collection_id, direction, 0)
    )

    assert client.calls == [collection_id]
    assert graph.nodes[OWNER_ID][f"{direction}_count"] == TOTAL


async def test_count_does_not_clobber_owner_metadata():
    client = FakeActivityPubClient(doc=collection(FOLLOWERS_ID))
    queue = asyncio.Queue()
    graph = nx.DiGraph()
    graph.add_node(OWNER_ID, type="Person", followers=FOLLOWERS_ID)

    await make_handler(client, queue, graph).handle(
        collection_job(FOLLOWERS_ID, "followers", 0)
    )

    node = graph.nodes[OWNER_ID]
    assert node["followers_count"] == TOTAL    # count under a distinct key...
    assert node["followers"] == FOLLOWERS_ID   # ...so the URL attribute survives
    assert node["type"] == "Person"


async def test_fetch_failure_propagates():
    client = FakeActivityPubClient(error=RuntimeError("boom"))
    queue = asyncio.Queue()
    graph = nx.DiGraph()
    graph.add_node(OWNER_ID)

    with pytest.raises(RuntimeError):
        await make_handler(client, queue, graph).handle(
            collection_job(FOLLOWERS_ID, "followers", 0)
        )

    assert queue.empty()


# ---------------------------------------------------------------------------
# Enqueue the first page, gated by depth < max_depth
# ---------------------------------------------------------------------------


async def test_enqueues_the_first_page_below_max_depth():
    client = FakeActivityPubClient(doc=collection(FOLLOWERS_ID))
    queue = asyncio.Queue()
    graph = nx.DiGraph()
    graph.add_node(OWNER_ID)

    # depth 0 < MAX_DEPTH
    await make_handler(client, queue, graph).handle(
        collection_job(FOLLOWERS_ID, "followers", 0)
    )

    page_jobs = [j for j in drain(queue) if j["job_type"] == "page"]
    # First page carries the collection's owner/direction/depth.
    assert page_jobs == [page_job(f"{FOLLOWERS_ID}?page=1", "followers", 0)]


async def test_does_not_enqueue_the_page_at_max_depth():
    client = FakeActivityPubClient(doc=collection(FOLLOWERS_ID))
    queue = asyncio.Queue()
    graph = nx.DiGraph()
    graph.add_node(OWNER_ID)

    await make_handler(client, queue, graph).handle(
        collection_job(FOLLOWERS_ID, "followers", MAX_DEPTH)
    )

    # Leaf collection: counted, but not walked.
    assert graph.nodes[OWNER_ID]["followers_count"] == TOTAL
    assert queue.empty()
