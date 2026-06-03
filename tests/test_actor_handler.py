"""Tests for ActorHandler (step 3) — fetch an actor, stamp the node.

Step-3 contract: handle fetches the actor via the (signed) ActivityPub client,
adds/enriches the graph node with scalar metadata + a last_fetch_date stamp, and
does NOT enqueue collections yet (a later step adds that). Dedup: a node that
already has a last_fetch_date is skipped (not re-fetched).

Pure DI unit tests: a fake async client, a real asyncio.Queue (asserted empty),
a real networkx DiGraph. No HTTP.

Assumed contract (flag if different):
  ActorHandler(activitypub_client, queue, graph, max_depth).handle(job):
    job = {"job_type": "actor", "actor_id": ..., "depth": ...}  # packed dict
    if node has last_fetch_date -> return (skip)
    actor = await client.get(actor_id)
    graph.add_node(actor_id, type=..., preferredUsername=..., last_fetch_date=<iso str>)
    (no enqueue yet)
  Node attrs must be GML-serializable scalars (no datetime objects, no nested
  actor sub-objects like publicKey).
"""

import asyncio

import networkx as nx
import pytest

from pub_crawler.actor_handler import ActorHandler

ACTOR_ID = "https://cosocial.ca/users/evan"
ACTOR = {
    "id": ACTOR_ID,
    "type": "Person",
    "preferredUsername": "evan",
    "name": "Evan Prodromou",
    "followers": "https://cosocial.ca/users/evan/followers",
    "following": "https://cosocial.ca/users/evan/following",
}
MAX_DEPTH = 2


def actor_job(actor_id, depth):
    # Packed job dict, parallel to main.py's webfinger job shape.
    return {"job_type": "actor", "actor_id": actor_id, "depth": depth}


class FakeActivityPubClient:
    def __init__(self, actor=ACTOR, error=None):
        self.actor = actor
        self.error = error
        self.calls = []

    async def get(self, url):
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return self.actor


def make_handler(client, graph, queue=None, max_depth=MAX_DEPTH):
    return ActorHandler(client, queue if queue is not None else asyncio.Queue(),
                        graph, max_depth)


async def test_fetches_actor_and_stamps_node():
    client = FakeActivityPubClient()
    graph = nx.DiGraph()
    queue = asyncio.Queue()

    await make_handler(client, graph, queue).handle(actor_job(ACTOR_ID, 0))

    assert client.calls == [ACTOR_ID]
    node = graph.nodes[ACTOR_ID]
    assert node["type"] == "Person"
    assert node["preferredUsername"] == "evan"
    # Stamped, and GML-serializable (a string, not a datetime object).
    assert isinstance(node["last_fetch_date"], str)
    assert node["last_fetch_date"]
    # Step 3 does not enqueue collections yet.
    assert queue.empty()


async def test_enriches_an_existing_bare_node():
    client = FakeActivityPubClient()
    graph = nx.DiGraph()
    graph.add_node(ACTOR_ID)  # bare node from WebfingerHandler / PageHandler

    await make_handler(client, graph).handle(actor_job(ACTOR_ID, 1))

    # A bare node (no last_fetch_date) is fetched and enriched in place.
    assert client.calls == [ACTOR_ID]
    assert graph.nodes[ACTOR_ID]["type"] == "Person"
    assert "last_fetch_date" in graph.nodes[ACTOR_ID]


async def test_skips_an_already_fetched_node():
    client = FakeActivityPubClient()
    graph = nx.DiGraph()
    graph.add_node(ACTOR_ID, type="Person", last_fetch_date="2026-06-01T00:00:00")

    await make_handler(client, graph).handle(actor_job(ACTOR_ID, 0))

    # Already stamped -> no re-fetch.
    assert client.calls == []


async def test_fetch_failure_propagates_and_leaves_node_unstamped():
    client = FakeActivityPubClient(error=RuntimeError("boom"))
    graph = nx.DiGraph()
    graph.add_node(ACTOR_ID)  # bare

    with pytest.raises(RuntimeError):
        await make_handler(client, graph).handle(actor_job(ACTOR_ID, 0))

    # Not stamped -> not marked fetched (the runner's try/except swallows the raise).
    assert "last_fetch_date" not in graph.nodes[ACTOR_ID]
