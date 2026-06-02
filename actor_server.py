from fastapi import FastAPI, Request, Response
import json
from urllib.parse import urlsplit

AS2 = "application/activity+json"
JRD = "application/jrd+json"
PROBLEM = "application/problem+json"
LD_WITH_PROFILE = 'application/ld+json; profile="https://www.w3.org/ns/activitystreams"'

class ActorServer:

    def __init__(self, origin='http://localhost:42069', public_key_pem=None):
        self.origin = origin
        self.public_key_pem = public_key_pem
        self.app = FastAPI()
        self.app.add_api_route('/actor', self.actor, methods=["GET"])
        self.app.add_api_route('/.well-known/webfinger', self.webfinger, methods=["GET"])
        self.app.add_api_route('/inbox', self.inbox, methods=["GET"])
        self.app.add_api_route('/outbox', self.outbox, methods=["GET"])
        self.app.add_api_route('/followers', self.followers, methods=["GET"])
        self.app.add_api_route('/following', self.following, methods=["GET"])
        self.app.add_api_route('/liked', self.liked, methods=["GET"])

    @property
    def netloc(self):
        return urlsplit(self.origin).netloc

    @property
    def acct(self):
        return f"acct:bot@{self.netloc}"

    @property
    def actor_id(self):
        return self._id("/actor")

    def actor(self):
        actor = {
            "@context": [
                "https://www.w3.org/ns/activitystreams",
                "https://w3id.org/security/v1",
                "https://purl.archive.org/socialweb/webfinger"
            ],
            "id": self.actor_id,
            "type": "Application",
            "preferredUsername": "bot",
            "webfinger": self.acct,
            "inbox": self._id("/inbox"),
            "outbox": self._id("/outbox"),
            "followers": self._id("/followers"),
            "following": self._id("/following"),
            "liked": self._id("/liked"),
            "to": "as:Public"
        }
        if self.public_key_pem is not None:
            actor['publicKey'] = {
                "id": self.actor_id + "#main-key",
                "type": "CryptographicKey",
                "owner": self.actor_id,
                "publicKeyPem": self.public_key_pem
            }
        return Response(json.dumps(actor), media_type=AS2)

    def webfinger(self, resource=None):
        if resource is None:
            problem = {
                "type": "about:blank",
                "title": "No 'resource' parameter",
                "status": 400,
                "detail": "No 'resource' parameter",
            }
            return Response(
                json.dumps(problem),
                status_code=400,
                media_type=PROBLEM)
        if resource != self.acct and resource != self.actor_id:
            problem = {
                "type": "about:blank",
                "title": "Unknown 'resource' parameter",
                "status": 404,
                "detail": f"No 'resource' with id {resource} on this server",
            }
            return Response(
                json.dumps(problem),
                status_code=404,
                media_type=PROBLEM)
        jrd = {
            "subject": self.acct,
            "aliases": [self.actor_id],
            "links": [
                {
                    "rel": "self",
                    "type": AS2,
                    "href": f"{self.origin}/actor"
                },
                {
                    "rel": "self",
                    "type": LD_WITH_PROFILE,
                    "href": f"{self.origin}/actor"
                }
            ]
        }
        return Response(json.dumps(jrd), media_type=JRD)

    def inbox(self):
        return self._collection('inbox', 'inboxOf')

    def outbox(self):
        return self._collection('outbox', 'outboxOf')

    def followers(self):
        return self._collection('followers', 'followersOf')

    def following(self):
        return self._collection('following', 'followingOf')

    def liked(self):
        return self._collection('liked', 'likedOf')

    def _id(self, path):
        return f"{self.origin}{path}"

    def _collection(self, coll, inv):
        collection = {
            "@context": [
                "https://www.w3.org/ns/activitystreams",
                "https://w3id.org/fep/5711",
            ],
            "id": self._id(f"/{coll}"),
            "type": "OrderedCollection",
            "totalItems": 0,
            "attributedTo": self.actor_id,
            inv: self.actor_id,
            "to": "as:Public"
        }
        return Response(json.dumps(collection), media_type=AS2)

    def serve(self, port=42069, host='127.0.0.1'):
        pass
