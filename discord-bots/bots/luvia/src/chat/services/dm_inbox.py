"""Two allowlisted inboxes; no lifetime/daily message cap or shared context."""
import asyncio
import logging
from src.chat.services.access_policy import dm_allowed
log=logging.getLogger(__name__)
class DMInboxMixin:
 async def _enqueue_dm(self,message):
  if not dm_allowed(message.author) or not await self._can_chat(message):return
  if not hasattr(self,'dm_queues'):self.dm_queues={};self.dm_workers={}
  key=(message.channel.id,message.author.id)
  queue=self.dm_queues.setdefault(key,asyncio.Queue(maxsize=16))
  if queue.full():
   await message.reply('我还在回复前面的消息，稍等一下再发给我好吗？',mention_author=False);return
  queue.put_nowait(message)
  if key not in self.dm_workers or self.dm_workers[key].done():
   task=asyncio.create_task(self._drain_dm(key));self.dm_workers[key]=task;self.background.add(task);task.add_done_callback(self.background.discard)
 async def _drain_dm(self,key):
  queue=self.dm_queues[key]
  try:
   while not queue.empty():
    message=queue.get_nowait()
    try:
     if not dm_allowed(message.author) or not await self._can_chat(message):continue
     self.context.add(message.channel.id,message.id,message.author.id,message.author.display_name,message.content or '[非文字消息]',False)
     reference=await self._reference(message) if message.reference else None
     await self._respond(message,'direct',reference)
    except asyncio.CancelledError:raise
    except Exception as exc:log.warning('dm_reply_failed type=%s',type(exc).__name__)
    finally:queue.task_done()
  finally:
   self.dm_workers.pop(key,None)
   if queue.empty():self.dm_queues.pop(key,None)
