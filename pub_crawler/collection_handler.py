from pub_crawler.handler import Handler

class CollectionHandler(Handler):

  def __init__(self, client, queue, graph):
    self.client = client
    self.queue = queue
    self.graph = graph

  async def handle(self, job):
    collection_id = job["collection_id"]
    owner_id = job["owner_id"]
    direction = job["direction"]
    if owner_id not in self.graph.nodes:
      self.graph.add_node(owner_id)
    node = self.graph.nodes[owner_id]
    json = await self.client.get(collection_id)
    self._set_prop(node, json, f"{direction}_count", "totalItems")

  def _set_prop(self, node, json, prop, prop2):
    value = json.get(prop2, None)
    if value:
      node[prop] = value