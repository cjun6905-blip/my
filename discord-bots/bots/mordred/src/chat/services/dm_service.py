import datetime as dt
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert

from src.chat.services.config_override_service import config_override_service
from src.database.database import AsyncSessionLocal
from src.database.models import DmDailyUsage, DmUserPreference

log = logging.getLogger(__name__)
DM_CONFIG_KEY = "dm.config"
DM_CONFIG_DEFAULT = {"enabled": True, "daily_limit": 10, "timezone": "Asia/Shanghai"}


class DmService:
    async def get_config(self) -> dict:
        raw = await config_override_service.get_json(DM_CONFIG_KEY, DM_CONFIG_DEFAULT)
        result = dict(DM_CONFIG_DEFAULT)
        if isinstance(raw, dict):
            result.update(raw)
        result["daily_limit"] = max(1, min(int(result["daily_limit"]), 100))
        try:
            ZoneInfo(str(result["timezone"]))
        except Exception:
            result["timezone"] = DM_CONFIG_DEFAULT["timezone"]
        return result

    async def ensure_user(self, user_id: int) -> None:
        stmt = insert(DmUserPreference).values(user_id=user_id).on_conflict_do_nothing(
            index_elements=[DmUserPreference.user_id]
        )
        async with AsyncSessionLocal() as session:
            await session.execute(stmt)
            await session.commit()

    async def reserve(self, user_id: int) -> tuple[bool, int, int, dt.date]:
        config = await self.get_config()
        limit = config["daily_limit"]
        day = dt.datetime.now(ZoneInfo(config["timezone"])).date()
        await self.ensure_user(user_id)
        stmt = (
            insert(DmDailyUsage)
            .values(user_id=user_id, usage_date=day, used_count=1)
            .on_conflict_do_update(
                index_elements=[DmDailyUsage.user_id, DmDailyUsage.usage_date],
                set_={
                    "used_count": DmDailyUsage.used_count + 1,
                    "updated_at": func.now(),
                },
                where=DmDailyUsage.used_count < limit,
            )
            .returning(DmDailyUsage.used_count)
        )
        async with AsyncSessionLocal() as session:
            used = (await session.execute(stmt)).scalar_one_or_none()
            reserved = used is not None
            await session.commit()
            if used is None:
                used = await session.scalar(
                    select(DmDailyUsage.used_count).where(
                        DmDailyUsage.user_id == user_id,
                        DmDailyUsage.usage_date == day,
                    )
                ) or limit
        return reserved, max(0, limit - used), limit, day

    async def refund(self, user_id: int, day: dt.date) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(DmDailyUsage)
                .where(
                    DmDailyUsage.user_id == user_id,
                    DmDailyUsage.usage_date == day,
                    DmDailyUsage.used_count > 0,
                )
                .values(used_count=DmDailyUsage.used_count - 1, updated_at=func.now())
            )
            await session.commit()

    async def status(self, user_id: int) -> dict:
        config = await self.get_config()
        day = dt.datetime.now(ZoneInfo(config["timezone"])).date()
        await self.ensure_user(user_id)
        async with AsyncSessionLocal() as session:
            used = await session.scalar(
                select(DmDailyUsage.used_count).where(
                    DmDailyUsage.user_id == user_id,
                    DmDailyUsage.usage_date == day,
                )
            ) or 0
            pref = await session.get(DmUserPreference, user_id)
        return {
            "used": used,
            "remaining": max(0, config["daily_limit"] - used),
            "limit": config["daily_limit"],
            "greetings_opt_in": bool(pref and pref.greetings_opt_in),
            "timezone": config["timezone"],
        }

    async def set_greetings(self, user_id: int, enabled: bool) -> None:
        await self.ensure_user(user_id)
        now = dt.datetime.utcnow()
        values = {
            "greetings_opt_in": enabled,
            "updated_at": func.now(),
            "opted_in_at" if enabled else "opted_out_at": now,
        }
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(DmUserPreference)
                .where(DmUserPreference.user_id == user_id)
                .values(**values)
            )
            await session.commit()


dm_service = DmService()
