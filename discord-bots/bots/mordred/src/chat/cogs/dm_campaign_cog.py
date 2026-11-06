import datetime as dt
import logging

import discord
from discord.ext import commands, tasks
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from src.chat.utils.message_utils import safe_send
from src.database.database import AsyncSessionLocal
from src.database.models import DmCampaign, DmDelivery, DmUserPreference

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


class DmCampaignCog(commands.Cog):
    """Consumes the admin-created outbound queue without exposing the bot token."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.worker.start()

    def cog_unload(self):
        self.worker.cancel()

    @tasks.loop(seconds=15)
    async def worker(self):
        await self._materialize_due_campaigns()
        for delivery_id in await self._claim_batch(3):
            await self._deliver(delivery_id)

    @worker.before_loop
    async def before_worker(self):
        await self.bot.wait_until_ready()

    @worker.error
    async def worker_error(self, error: Exception):
        log.error("私信活动队列发生错误: %s", error, exc_info=error)

    async def _materialize_due_campaigns(self) -> None:
        now = dt.datetime.utcnow()
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DmCampaign)
                .where(DmCampaign.status == "scheduled", DmCampaign.scheduled_at <= now)
                .with_for_update(skip_locked=True)
                .limit(10)
            )
            campaigns = list(result.scalars())
            for campaign in campaigns:
                if campaign.kind == "manual" and campaign.target_user_id:
                    user_ids = [campaign.target_user_id]
                else:
                    users = await session.execute(
                        select(DmUserPreference.user_id).where(
                            DmUserPreference.greetings_opt_in.is_(True)
                        )
                    )
                    user_ids = list(users.scalars())
                for user_id in user_ids:
                    await session.execute(
                        insert(DmDelivery)
                        .values(
                            campaign_id=campaign.id,
                            user_id=user_id,
                            status="pending",
                            attempts=0,
                            next_attempt_at=now,
                        )
                        .on_conflict_do_nothing(
                            constraint="uq_dm_delivery_campaign_user"
                        )
                    )
                campaign.status = "sending" if user_ids else "completed"
            await session.commit()

    async def _claim_batch(self, size: int) -> list[int]:
        now = dt.datetime.utcnow()
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                select(DmDelivery)
                .where(
                    DmDelivery.status.in_(["pending", "retry"]),
                    DmDelivery.next_attempt_at <= now,
                )
                .order_by(DmDelivery.id)
                .with_for_update(skip_locked=True)
                .limit(size)
            )
            deliveries = list(rows.scalars())
            for delivery in deliveries:
                delivery.status = "sending"
                delivery.attempts += 1
            await session.commit()
            return [d.id for d in deliveries]

    async def _deliver(self, delivery_id: int) -> None:
        async with AsyncSessionLocal() as session:
            delivery = await session.get(DmDelivery, delivery_id)
            if not delivery or delivery.status != "sending":
                return
            campaign = await session.get(DmCampaign, delivery.campaign_id)
            if not campaign or campaign.status in {"cancelled", "paused"}:
                delivery.status = "cancelled"
                await session.commit()
                return
            try:
                user = self.bot.get_user(delivery.user_id) or await self.bot.fetch_user(
                    delivery.user_id
                )
                content = campaign.content.replace("{display_name}", user.display_name)
                prefix = (
                    "**来自 aireck 的留言**\n\n"
                    if campaign.kind == "manual"
                    else "**Mordred 的节日祝福**\n\n"
                )
                await safe_send(user, prefix + content)
                delivery.status = "sent"
                delivery.sent_at = dt.datetime.utcnow()
                delivery.last_error = None
            except discord.Forbidden:
                delivery.status = "blocked"
                delivery.last_error = "recipient_forbids_dm"
            except discord.NotFound:
                delivery.status = "failed"
                delivery.last_error = "recipient_not_found"
            except Exception as error:
                delivery.last_error = type(error).__name__[:200]
                if delivery.attempts < MAX_ATTEMPTS:
                    delivery.status = "retry"
                    delivery.next_attempt_at = dt.datetime.utcnow() + dt.timedelta(
                        minutes=2 ** delivery.attempts
                    )
                else:
                    delivery.status = "failed"
                log.warning("私信投递 %s 失败: %s", delivery_id, type(error).__name__)
            await session.commit()
            await self._refresh_campaign(campaign.id)

    async def _refresh_campaign(self, campaign_id: int) -> None:
        async with AsyncSessionLocal() as session:
            counts = dict(
                (await session.execute(
                    select(DmDelivery.status, func.count())
                    .where(DmDelivery.campaign_id == campaign_id)
                    .group_by(DmDelivery.status)
                )).all()
            )
            active = sum(counts.get(s, 0) for s in ("pending", "retry", "sending"))
            if active == 0:
                failures = counts.get("failed", 0) + counts.get("blocked", 0)
                await session.execute(
                    update(DmCampaign)
                    .where(DmCampaign.id == campaign_id, DmCampaign.status == "sending")
                    .values(status="completed_with_errors" if failures else "completed")
                )
                await session.commit()


async def setup(bot: commands.Bot):
    await bot.add_cog(DmCampaignCog(bot))
