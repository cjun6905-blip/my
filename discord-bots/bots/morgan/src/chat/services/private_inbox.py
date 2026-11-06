"""Authenticated private inbox with bounded work and no per-day/lifetime quota."""
import asyncio,json,logging
from functools import lru_cache
from pathlib import Path
import discord
log=logging.getLogger(__name__)
@lru_cache(maxsize=8)
def policy(path="config/private_chat.json"):
    p=Path(path)
    if p.stat().st_size>65536:raise ValueError("Private policy is too large")
    return json.loads(p.read_text(encoding="utf-8"))
def private_user_ids(path="config/private_chat.json"):
    return frozenset(int(v) for v in policy(path)["allowed_user_ids"])
class PrivateInbox:
    def __init__(self,handler,sender,config_path="config/private_chat.json"):
        self.users=private_user_ids(config_path)
        self.handler,self.sender=handler,sender
        self.queue=asyncio.Queue(maxsize=max(1,min(16,int(policy(config_path).get("pending_limit",16)))))
        self.worker=None
    def allowed(self,message):
        if (message.guild is not None or not isinstance(message.channel,discord.DMChannel)
                or getattr(message.author,"bot",False) or getattr(message,"webhook_id",None)
                or type(message.author.id) is not int or message.author.id not in self.users):return False
        # MESSAGE_CREATE constructs DMChannel with no recipient; its author is authenticated.
        # Reject contradictory cached metadata, but never require a channel-cache warmup.
        recipient=message.channel.recipient
        return recipient is None or recipient.id==message.author.id
    async def offer(self,message):
        if not self.allowed(message):return False
        if (message.content or "").strip().casefold() in {"私信状态","剩余次数","dm status","私信帮助","dm help"}:
            await self.sender(message.channel,"你可直接私聊，没有每日或累计次数限制；消息较多时会依次回复。")
            return True
        try:self.queue.put_nowait(message)
        except asyncio.QueueFull:
            await self.sender(message.channel,"正在依次回复前面的消息，稍后再发这一条吧；私聊没有每日条数上限。")
            return True
        log.info("private_inbox_accepted user=%s channel=%s message=%s",message.author.id,message.channel.id,message.id)
        if self.worker is None or self.worker.done():self.worker=asyncio.create_task(self._run())
        return True
    async def _run(self):
        while True:
            m=await self.queue.get()
            try:await asyncio.wait_for(self.handler(m),240)
            except asyncio.CancelledError:raise
            except Exception as exc:
                log.warning("private_reply_failed type=%s",type(exc).__name__)
                try:await self.sender(m.channel,"这次回复没有完成，请稍后重发这一条。")
                except Exception:pass
            finally:self.queue.task_done()
    async def close(self):
        if self.worker is not None:
            self.worker.cancel();await asyncio.gather(self.worker,return_exceptions=True)
