"""Tests for CollectionHandler (build step) — fetch a collection, save its count.

Build-step contract: handle fetches the followers/following collection via the
ActivityPub client and stores its totalItems on the OWNER's node, keyed by
direction (followers_count / following_count). It does NOT enqueue the first
page yet (a later step adds that). The owner node already exists, since
ActorHandler creates it before enqueuing the collection.

Pure DI unit tests: a fake async client, a real asyncio.Queue (asserted empty),
a real networkx DiGraph. No HTTP.

Assumed contract (flag if different):
  CollectionHandler(client, queue, graph).handle(job)
    job = {job_type:'collection', collection_id, owner_id, direction, depth}
    coll = await client.get(collection_id)
    graph.nodes[owner_id][f"{direction}_count"] = coll["totalItems"]
    (no enqueue yet)
"""

import asyncio

import networkx as nx
import pytest

from pub_crawler.collection_handler import CollectionHandler

OWNER_ID = "https://example.com/foo"
FOLLOWERS_ID = "https://example.com/foo/followers"
FOLLOWING_ID = "https://example.com/foo/following"
TOTAL = 42


def collection(collection_id, total=TOTAL):
    return {
        "id": collection_id,
        "type": "OrderedCollection",
        "totalItems": total,
        "first": f"{collection_id}?page=1",
    }


def collection_job(collection_id, direction, depth=1):
    return {
        "job_type": "collection",
        "collection_id": collection_id,
        "owner_id": OWNER_ID,
        "direction": direction,
        "depth": depth,
    }


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


@pytest.mark.parametrize(
    "direction, collection_id",
    [("followers", FOLLOWERS_ID), ("following", FOLLOWING_ID)],
)
async def test_saves_count_on_owner_node_keyed_by_direction(direction, collection_id):
    client = FakeActivityPubClient(doc=collection(collection_id))
    queue = asyncio.Queue()
    graph = nx.DiGraph()
    graph.add_node(OWNER_ID)  # ActorHandler created it before enqueuing the collection

    await CollectionHandler(client, queue, graph).handle(
        collection_job(collection_id, direction)
    )

    assert client.calls == [collection_id]
    assert graph.nodes[OWNER_ID][f"{direction}_count"] == TOTAL
    # Build step: no page enqueue yet.
    assert queue.empty()


async def test_count_does_not_clobber_owner_metadata():
    client = FakeActivityPubClient(doc=collection(FOLLOWERS_ID))
    queue = asyncio.Queue()
    graph = nx.DiGraph()
    # Owner node as ActorHandler leaves it: type + the followers *URL* attribute.
    graph.add_node(OWNER_ID, type="Person", followers=FOLLOWERS_ID)

    await CollectionHandler(client, queue, graph).handle(
        collection_job(FOLLOWERS_ID, "followers")
    )

    node = graph.nodes[OWNER_ID]
    assert node["followers_count"] == TOTAL    # count lives under a distinct key...
    assert node["followers"] == FOLLOWERS_ID   # ...so the URL attribute survives
    assert node["type"] == "Person"


async def test_fetch_failure_propagates():
    client = FakeActivityPubClient(error=RuntimeError("boom"))
    queue = asyncio.Queue()
    graph = nx.DiGraph()
    graph.add_node(OWNER_ID)

    with pytest.raises(RuntimeError):
        await CollectionHandler(client, queue, graph).handle(
            collection_job(FOLLOWERS_ID, "followers")
        )

    assert queue.empty()
