class WebfingerHandler:

  def __init__(self, client, queue, graph):
    self.client = client
    self.queue = queue
    self.graph = graph

  async def handle(self, wf):
    actor_id = await self.client.get_actor_id(wf)
    self.graph.add_node(actor_id)