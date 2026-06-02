"""Step-1 contract tests for ActorServer.

These pin the discovery flow a remote Mastodon performs against the crawler's
actor: webfinger -> actor -> collections, with the AS2 / JRD content types and
FEP-5711 inverse properties that make the actor acceptable as an HTTP-Signature
signer. The crawler signs requests locally; this server only has to serve a
correct, dereferenceable public identity.
"""

import httpx
import pytest

from support import (
    AS2_CONTEXT,
    AS2_TYPE,
    COLLECTIONS,
    FEP_5711_CONTEXT,
    JRD_TYPE,
    LD_JSON_TYPE,
    ORIGIN,
    PUBLIC_KEY_PEM,
    SECURITY_CONTEXT,
    USERNAME,
    as_list,
    discover_actor,
    host_of,
    media_type,
    webfinger_resource,
)

# ---------------------------------------------------------------------------
# Webfinger
# ---------------------------------------------------------------------------


async def test_webfinger_returns_jrd(client):
    r = await client.get(
        "/.well-known/webfinger", params={"resource": webfinger_resource()}
    )
    assert r.status_code == 200
    assert media_type(r) == JRD_TYPE
    assert r.json()["subject"] == webfinger_resource()


async def test_webfinger_advertises_activitypub_and_ld_json(client):
    r = await client.get(
        "/.well-known/webfinger", params={"resource": webfinger_resource()}
    )
    links = r.json()["links"]

    self_links = [link for link in links if link.get("rel") == "self"]
    by_type = {link.get("type"): link for link in self_links}

    # The plain AS2 representation...
    assert AS2_TYPE in by_type

    # ...and a separate link for the ld+json representation carrying the AS2
    # profile parameter, pointing at the same actor.
    ld_links = [t for t in by_type if t and t.startswith(LD_JSON_TYPE)]
    assert ld_links, "expected an application/ld+json self link"
    ld_type = ld_links[0]
    assert "profile=" in ld_type and AS2_CONTEXT in ld_type

    assert by_type[AS2_TYPE]["href"] == by_type[ld_type]["href"]


async def test_webfinger_self_link_points_at_origin_actor(client):
    r = await client.get(
        "/.well-known/webfinger", params={"resource": webfinger_resource()}
    )
    self_link = next(
        link
        for link in r.json()["links"]
        if link.get("rel") == "self" and link.get("type") == AS2_TYPE
    )
    assert self_link["href"] == f"{ORIGIN}/actor"


async def test_webfinger_missing_resource_is_400(client):
    r = await client.get("/.well-known/webfinger")
    assert r.status_code == 400


async def test_webfinger_unknown_account_is_404(client):
    r = await client.get(
        "/.well-known/webfinger",
        params={"resource": f"acct:nobody@{host_of(ORIGIN)}"},
    )
    assert r.status_code == 404


async def test_webfinger_accepts_actor_id_as_resource(client):
    """A remote may webfinger the actor URI itself, not just the acct: form."""
    actor_url = f"{ORIGIN}/actor"

    r = await client.get(
        "/.well-known/webfinger", params={"resource": actor_url}
    )
    assert r.status_code == 200
    assert media_type(r) == JRD_TYPE

    self_link = next(
        link
        for link in r.json()["links"]
        if link.get("rel") == "self" and link.get("type") == AS2_TYPE
    )
    assert self_link["href"] == actor_url

    # Querying by id resolves the same record as querying by acct: same links.
    by_acct = await client.get(
        "/.well-known/webfinger", params={"resource": webfinger_resource()}
    )
    assert r.json()["links"] == by_acct.json()["links"]


# ---------------------------------------------------------------------------
# Actor
# ---------------------------------------------------------------------------


async def test_actor_discoverable_at_clean_path(actor):
    actor_url, _ = actor
    assert actor_url == f"{ORIGIN}/actor"


async def test_actor_content_type_is_activitypub(client):
    r = await client.get("/actor", headers={"accept": AS2_TYPE})
    assert r.status_code == 200
    assert media_type(r) == AS2_TYPE


async def test_actor_core_properties(actor):
    actor_url, doc = actor
    assert doc["id"] == actor_url
    assert doc["type"] == "Application"
    assert doc["preferredUsername"] == USERNAME
    for prop in COLLECTIONS:
        assert doc[prop] == f"{ORIGIN}/{prop}"


async def test_actor_context_includes_as2_and_security(actor):
    _, doc = actor
    context = as_list(doc["@context"])
    assert AS2_CONTEXT in context
    assert SECURITY_CONTEXT in context


async def test_actor_public_key(actor):
    actor_url, doc = actor
    key = doc["publicKey"]
    assert key["id"] == f"{actor_url}#main-key"
    assert key["owner"] == actor_url
    # The server publishes exactly the key it was handed — not one of its own.
    assert key["publicKeyPem"] == PUBLIC_KEY_PEM


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prop,inverse", COLLECTIONS.items())
async def test_collection_document(client, actor, prop, inverse):
    actor_url, _ = actor
    collection_url = f"{ORIGIN}/{prop}"

    r = await client.get(collection_url, headers={"accept": AS2_TYPE})
    assert r.status_code == 200
    assert media_type(r) == AS2_TYPE

    doc = r.json()
    assert doc["id"] == collection_url
    assert doc["type"] == "OrderedCollection"
    assert doc["totalItems"] == 0
    assert doc["attributedTo"] == actor_url

    # FEP-5711 inverse property points back at the actor...
    assert doc[inverse] == actor_url
    # ...and only the one inverse property is present on a given collection.
    present = [v for v in COLLECTIONS.values() if v in doc]
    assert present == [inverse]

    # The inverse term is only defined if the fep/5711 context is present.
    context = as_list(doc["@context"])
    assert AS2_CONTEXT in context
    assert FEP_5711_CONTEXT in context


# ---------------------------------------------------------------------------
# Link integrity
# ---------------------------------------------------------------------------


async def test_every_actor_link_resolves(client, actor):
    actor_url, doc = actor
    urls = [actor_url] + [doc[prop] for prop in COLLECTIONS]
    for url in urls:
        r = await client.get(url, headers={"accept": AS2_TYPE})
        assert r.status_code == 200, f"{url} did not resolve"


# ---------------------------------------------------------------------------
# Identity is the server's, not the client's
# ---------------------------------------------------------------------------


async def test_origin_is_not_client_controlled(server):
    """A request arriving on a spoofed host must not change the emitted ids.

    The server generates URLs from its configured origin, so reaching it as some
    other host (as a malicious caller might) still yields origin-based ids.
    """
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://evil.example"
    ) as c:
        actor = await c.get("/actor", headers={"accept": AS2_TYPE})
        assert actor.json()["id"] == f"{ORIGIN}/actor"

        wf = await c.get(
            "/.well-known/webfinger",
            params={"resource": webfinger_resource()},
            headers={"host": "evil.example"},
        )
        self_link = next(
            link
            for link in wf.json()["links"]
            if link.get("rel") == "self" and link.get("type") == AS2_TYPE
        )
        assert self_link["href"] == f"{ORIGIN}/actor"
