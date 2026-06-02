"""Fixtures for driving the ActorServer in-process via httpx ASGITransport."""

import httpx
import pytest
import pytest_asyncio

from actor_server import ActorServer

from support import ORIGIN, PUBLIC_KEY_PEM, discover_actor


@pytest.fixture
def server():
    return ActorServer(origin=ORIGIN, public_key_pem=PUBLIC_KEY_PEM)


@pytest_asyncio.fixture
async def client(server):
    """An httpx client mounted directly on the ASGI app (no socket).

    base_url is the configured origin so discovered absolute URLs route back to
    the same app. Tests that need to prove origin independence build their own
    client against a different base_url using server.app.
    """
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as c:
        yield c


@pytest_asyncio.fixture
async def actor(client):
    """(actor_url, actor_document) discovered the way Mastodon would."""
    return await discover_actor(client)
