from pub_crawler.handler import Handler
from datetime import datetime, timezone

class ActorHandler(Handler):

  def __init__(self, client, queue, graph, max_depth):
    self.client = client
    self.queue = queue
    self.graph = graph
    self.max_depth = max_depth

  async def handle(self, job):
    actor_id = job["actor_id"]
    depth = job["depth"]
    if actor_id not in self.graph.nodes:
      self.graph.add_node(actor_id)
    node = self.graph.nodes[actor_id]
    if "last_fetch_date" in node:
      return
    json = await self.client.get(actor_id)
    node["last_fetch_date"] = datetime.now(timezone.utc).isoformat()
    self._set_prop(node, json, "preferredUsername")
    self._set_prop(node, json, "name")
    self._set_prop(node, json, "published")
    self._set_prop(node, json, "type")
    self._set_prop(node, json, "followers")
    self._set_prop(node, json, "following")

  def _set_prop(self, node, json, prop):
    value = json.get(prop, None)
    if value:
      node[prop] = value
