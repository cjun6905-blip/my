"""Transactional application service for the Chaldea game."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from src.database.database import AsyncSessionLocal

from ..battle_engine import (
    create_battle_state,
    public_view,
    resolve_phase,
    resolve_skill,
    resolve_tactic,
    upgrade_battle_state,
    validate_action,
)
from ..catalog import EVENT_SERVANT_IDS, SERVANTS, STARTER_SERVANTS
from ..gacha import summon as run_summon
from ..tactics import DEFAULT_MASTER_TEMPLATE_ID, MASTER_TEMPLATES
from ..tables import (
    battle_actions,
    battle_comments,
    battles,
    currency_ledger,
    daily_claims,
    owned_servants,
    profiles,
    summon_rolls,
    teams,
)


class ChaldeaError(RuntimeError):
    pass


class ChaldeaService:
    DAILY_REWARD = 3
    DAILY_QP = 500
    DAILY_EXP = 80
    WIN_QP = 300
    LOSS_QP = 200
    WIN_EXP = 60
    LOSS_EXP = 45
    CHALLENGE_TTL = dt.timedelta(minutes=30)

    async def _expire_pending_challenges(self, session) -> None:
        cutoff = dt.datetime.utcnow() - self.CHALLENGE_TTL
        await session.execute(
            update(battles)
            .where(
                battles.c.status == "pending",
                battles.c.created_at < cutoff,
            )
            .values(status="expired", updated_at=dt.datetime.utcnow())
        )

    async def _ensure_player(self, session, user_id: int | str) -> str:
        uid = str(user_id)
        await session.execute(
            insert(profiles)
            .values(
                user_id=uid,
                quartz=30,
                qp=2000,
                training_exp=300,
                pity_counter=0,
                master_template_id=DEFAULT_MASTER_TEMPLATE_ID,
            )
            .on_conflict_do_nothing(index_elements=[profiles.c.user_id])
        )
        for servant_id in STARTER_SERVANTS:
            await session.execute(
                insert(owned_servants)
                .values(user_id=uid, servant_id=servant_id, level=1, np_level=1, shards=0)
                .on_conflict_do_nothing(
                    index_elements=[owned_servants.c.user_id, owned_servants.c.servant_id]
                )
            )
        await session.execute(
            insert(teams)
            .values(user_id=uid, servant_ids=list(STARTER_SERVANTS))
            .on_conflict_do_nothing(index_elements=[teams.c.user_id])
        )
        return uid

    async def get_profile(self, user_id: int | str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                uid = await self._ensure_player(session, user_id)
                profile = (
                    await session.execute(select(profiles).where(profiles.c.user_id == uid))
                ).mappings().one()
                team = (
                    await session.execute(select(teams.c.servant_ids).where(teams.c.user_id == uid))
                ).scalar_one()
        return {**dict(profile), "team": team}

    async def set_master_template(self, user_id: int | str, template_id: str) -> dict[str, Any]:
        template = MASTER_TEMPLATES.get(template_id)
        if template is None:
            raise ChaldeaError("未知的御主礼装")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                uid = await self._ensure_player(session, user_id)
                await session.execute(
                    update(profiles)
                    .where(profiles.c.user_id == uid)
                    .values(master_template_id=template_id, updated_at=dt.datetime.utcnow())
                )
        return template

    async def claim_daily(self, user_id: int | str) -> dict[str, int | bool]:
        today = dt.datetime.now(ZoneInfo("Asia/Shanghai")).date()
        async with AsyncSessionLocal() as session:
            async with session.begin():
                uid = await self._ensure_player(session, user_id)
                inserted = await session.execute(
                    insert(daily_claims)
                    .values(user_id=uid, claim_date=today, amount=self.DAILY_REWARD)
                    .on_conflict_do_nothing(
                        index_elements=[daily_claims.c.user_id, daily_claims.c.claim_date]
                    )
                    .returning(daily_claims.c.user_id)
                )
                if inserted.scalar_one_or_none() is None:
                    current = (
                        await session.execute(select(profiles).where(profiles.c.user_id == uid))
                    ).mappings().one()
                    return {
                        "granted": False,
                        "quartz": int(current["quartz"]),
                        "qp": int(current["qp"]),
                        "training_exp": int(current["training_exp"]),
                    }
                updated = (
                    await session.execute(
                        update(profiles)
                        .where(profiles.c.user_id == uid)
                        .values(
                            quartz=profiles.c.quartz + self.DAILY_REWARD,
                            qp=profiles.c.qp + self.DAILY_QP,
                            training_exp=profiles.c.training_exp + self.DAILY_EXP,
                            updated_at=dt.datetime.utcnow(),
                        )
                        .returning(profiles.c.quartz, profiles.c.qp, profiles.c.training_exp)
                    )
                ).mappings().one()
                await session.execute(insert(currency_ledger).values([
                    {
                        "user_id": uid, "amount": self.DAILY_REWARD,
                        "balance_after": int(updated["quartz"]), "resource_type": "quartz",
                        "reason": "每日签到", "idempotency_key": f"daily:{uid}:{today.isoformat()}",
                    },
                    {
                        "user_id": uid, "amount": self.DAILY_QP,
                        "balance_after": int(updated["qp"]), "resource_type": "qp",
                        "reason": "每日签到", "idempotency_key": f"daily:qp:{uid}:{today.isoformat()}",
                    },
                    {
                        "user_id": uid, "amount": self.DAILY_EXP,
                        "balance_after": int(updated["training_exp"]), "resource_type": "training_exp",
                        "reason": "每日签到", "idempotency_key": f"daily:exp:{uid}:{today.isoformat()}",
                    },
                ]))
                return {
                    "granted": True,
                    "quartz": int(updated["quartz"]),
                    "qp": int(updated["qp"]),
                    "training_exp": int(updated["training_exp"]),
                }

    async def summon(self, user_id: int | str, count: int, interaction_id: str) -> dict[str, Any]:
        cost = 3 if count == 1 else 30 if count == 11 else None
        if cost is None:
            raise ChaldeaError("只能选择单抽或十一连")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                uid = await self._ensure_player(session, user_id)
                existing = (
                    await session.execute(
                        select(summon_rolls.c.results, summon_rolls.c.cost)
                        .where(summon_rolls.c.interaction_id == str(interaction_id))
                    )
                ).mappings().one_or_none()
                if existing:
                    balance = (
                        await session.execute(select(profiles.c.quartz).where(profiles.c.user_id == uid))
                    ).scalar_one()
                    return {"results": existing["results"], "balance": int(balance), "replayed": True}

                profile = (
                    await session.execute(
                        select(profiles).where(profiles.c.user_id == uid).with_for_update()
                    )
                ).mappings().one()
                if int(profile["quartz"]) < cost:
                    raise ChaldeaError(f"圣晶石不足，需要 {cost}，当前 {profile['quartz']}")
                result = run_summon(count, int(profile["pity_counter"]))
                new_balance = int(profile["quartz"]) - cost
                await session.execute(
                    update(profiles)
                    .where(profiles.c.user_id == uid)
                    .values(quartz=new_balance, pity_counter=result.new_pity, updated_at=dt.datetime.utcnow())
                )
                for servant_id in result.servant_ids:
                    owned = (
                        await session.execute(
                            select(owned_servants)
                            .where(
                                owned_servants.c.user_id == uid,
                                owned_servants.c.servant_id == servant_id,
                            )
                            .with_for_update()
                        )
                    ).mappings().one_or_none()
                    if not owned:
                        await session.execute(
                            insert(owned_servants).values(
                                user_id=uid, servant_id=servant_id, level=1, np_level=1, shards=0
                            )
                        )
                    elif int(owned["np_level"]) < 5:
                        await session.execute(
                            update(owned_servants)
                            .where(owned_servants.c.id == owned["id"])
                            .values(np_level=int(owned["np_level"]) + 1)
                        )
                    else:
                        shard_gain = max(1, int(SERVANTS[servant_id]["rarity"]) * 3)
                        await session.execute(
                            update(owned_servants)
                            .where(owned_servants.c.id == owned["id"])
                            .values(shards=int(owned["shards"]) + shard_gain)
                        )
                result_ids = list(result.servant_ids)
                await session.execute(
                    insert(summon_rolls).values(
                        user_id=uid,
                        banner_id="story",
                        interaction_id=str(interaction_id),
                        draw_count=count,
                        cost=cost,
                        results=result_ids,
                    )
                )
                await session.execute(
                    insert(currency_ledger).values(
                        user_id=uid,
                        amount=-cost,
                        balance_after=new_balance,
                        resource_type="quartz",
                        reason=f"常驻召唤 {count} 次",
                        idempotency_key=f"summon:{interaction_id}",
                    )
                )
                return {"results": result_ids, "balance": new_balance, "replayed": False}

    async def get_roster(self, user_id: int | str) -> list[dict[str, Any]]:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                uid = await self._ensure_player(session, user_id)
                rows = (
                    await session.execute(
                        select(owned_servants)
                        .where(owned_servants.c.user_id == uid)
                        .order_by(owned_servants.c.id)
                    )
                ).mappings().all()
        return [
            {**dict(row), "servant": SERVANTS[row["servant_id"]]}
            for row in rows
        ]

    async def set_team(self, user_id: int | str, servant_ids: list[str]) -> list[str]:
        if len(servant_ids) != 3 or len(set(servant_ids)) != 3:
            raise ChaldeaError("编队必须包含三名不同从者")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                uid = await self._ensure_player(session, user_id)
                owned = set(
                    (
                        await session.execute(
                            select(owned_servants.c.servant_id).where(
                                owned_servants.c.user_id == uid,
                                owned_servants.c.servant_id.in_(servant_ids),
                            )
                        )
                    ).scalars()
                )
                if owned != set(servant_ids):
                    raise ChaldeaError("编队中包含尚未拥有的从者")
                await session.execute(
                    update(teams)
                    .where(teams.c.user_id == uid)
                    .values(servant_ids=servant_ids, updated_at=dt.datetime.utcnow())
                )
        return servant_ids

    async def create_challenge(self, challenger_id: int, opponent_id: int) -> str:
        if challenger_id == opponent_id:
            raise ChaldeaError("不能挑战自己")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                challenger = await self._ensure_player(session, challenger_id)
                opponent = await self._ensure_player(session, opponent_id)
                await self._expire_pending_challenges(session)
                busy = (
                    await session.execute(
                        select(battles.c.id).where(
                            battles.c.status.in_(["pending", "active"]),
                            or_(
                                battles.c.challenger_id.in_([challenger, opponent]),
                                battles.c.opponent_id.in_([challenger, opponent]),
                            ),
                        )
                    )
                ).first()
                if busy:
                    raise ChaldeaError("其中一名玩家已有待处理或进行中的战斗")
                battle_id = str(uuid.uuid4())
                await session.execute(
                    insert(battles).values(
                        id=battle_id,
                        challenger_id=challenger,
                        opponent_id=opponent,
                        status="pending",
                        turn=0,
                        state=None,
                    )
                )
        return battle_id

    async def accept_challenge(self, battle_id: str, user_id: int | str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                uid = await self._ensure_player(session, user_id)
                await self._expire_pending_challenges(session)
                battle = (
                    await session.execute(
                        select(battles).where(battles.c.id == battle_id).with_for_update()
                    )
                ).mappings().one_or_none()
                if not battle or battle["status"] != "pending":
                    raise ChaldeaError("挑战不存在或已被处理")
                if battle["opponent_id"] != uid:
                    raise ChaldeaError("只有被挑战者可以接受")
                team_rows = (
                    await session.execute(
                        select(teams.c.user_id, teams.c.servant_ids).where(
                            teams.c.user_id.in_([battle["challenger_id"], battle["opponent_id"]])
                        )
                    )
                ).mappings().all()
                team_ids = {
                    str(row["user_id"]): list(row["servant_ids"])
                    for row in team_rows
                }
                roster_rows = (
                    await session.execute(
                        select(
                            owned_servants.c.user_id,
                            owned_servants.c.servant_id,
                            owned_servants.c.level,
                            owned_servants.c.np_level,
                        ).where(
                            owned_servants.c.user_id.in_(team_ids),
                        )
                    )
                ).mappings().all()
                roster = {
                    (str(row["user_id"]), str(row["servant_id"])): dict(row)
                    for row in roster_rows
                }
                prepared_teams = {
                    user: [
                        {
                            "servant_id": servant_id,
                            "level": int(roster[(user, servant_id)]["level"]),
                            "np_level": int(roster[(user, servant_id)]["np_level"]),
                        }
                        for servant_id in servant_ids
                    ]
                    for user, servant_ids in team_ids.items()
                }
                profile_rows = (
                    await session.execute(
                        select(profiles.c.user_id, profiles.c.master_template_id).where(
                            profiles.c.user_id.in_(team_ids)
                        )
                    )
                ).mappings().all()
                master_templates = {
                    str(row["user_id"]): str(row["master_template_id"])
                    for row in profile_rows
                }
                state = create_battle_state(
                    battle_id,
                    prepared_teams,
                    master_templates=master_templates,
                )
                await session.execute(
                    update(battles)
                    .where(battles.c.id == battle_id)
                    .values(status="active", turn=1, state=state, updated_at=dt.datetime.utcnow())
                )
        return state

    async def _close_pending_challenge(
        self,
        user_id: int | str,
        battle_id: str | None,
        participant_column,
        next_status: str,
        missing_message: str,
    ) -> str:
        uid = str(user_id)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await self._expire_pending_challenges(session)
                condition = and_(
                    battles.c.status == "pending",
                    participant_column == uid,
                )
                if battle_id:
                    condition = and_(condition, battles.c.id == battle_id)
                battle = (
                    await session.execute(
                        select(battles.c.id)
                        .where(condition)
                        .order_by(battles.c.created_at.desc())
                        .limit(1)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if battle is None:
                    raise ChaldeaError(missing_message)
                await session.execute(
                    update(battles)
                    .where(battles.c.id == battle, battles.c.status == "pending")
                    .values(status=next_status, updated_at=dt.datetime.utcnow())
                )
                return str(battle)

    async def cancel_challenge(
        self, user_id: int | str, battle_id: str | None = None
    ) -> str:
        return await self._close_pending_challenge(
            user_id,
            battle_id,
            battles.c.challenger_id,
            "cancelled",
            "没有可撤销的待接受决斗",
        )

    async def decline_challenge(
        self, user_id: int | str, battle_id: str | None = None
    ) -> str:
        return await self._close_pending_challenge(
            user_id,
            battle_id,
            battles.c.opponent_id,
            "declined",
            "没有可拒绝的待接受决斗",
        )

    async def abandon_battle(
        self, user_id: int | str, battle_id: str | None = None
    ) -> str:
        uid = str(user_id)
        condition = and_(
            battles.c.status == "active",
            or_(battles.c.challenger_id == uid, battles.c.opponent_id == uid),
        )
        if battle_id:
            condition = and_(condition, battles.c.id == battle_id)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                battle = (
                    await session.execute(
                        select(battles.c.id)
                        .where(condition)
                        .order_by(battles.c.updated_at.desc())
                        .limit(1)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if battle is None:
                    raise ChaldeaError("没有可结束的进行中战斗")
                await session.execute(
                    update(battles)
                    .where(battles.c.id == battle, battles.c.status == "active")
                    .values(status="abandoned", updated_at=dt.datetime.utcnow())
                )
                return str(battle)

    async def get_battle(self, user_id: int | str, battle_id: str | None = None) -> dict[str, Any] | None:
        uid = str(user_id)
        condition = and_(
            battles.c.status.in_(["pending", "active", "finished"]),
            or_(battles.c.challenger_id == uid, battles.c.opponent_id == uid),
        )
        if battle_id:
            condition = and_(condition, battles.c.id == battle_id)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await self._expire_pending_challenges(session)
                row = (
                    await session.execute(
                        select(battles).where(condition).order_by(battles.c.updated_at.desc()).limit(1)
                    )
                ).mappings().one_or_none()
        return dict(row) if row else None

    async def get_public_battle(self, battle_id: str) -> dict[str, Any] | None:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(battles)
                    .where(
                        battles.c.id == battle_id,
                        battles.c.status.in_(["active", "finished"]),
                    )
                    .limit(1)
                )
            ).mappings().one_or_none()
        return dict(row) if row else None

    async def get_battle_comments(
        self, battle_id: str, *, after_id: int = 0, limit: int = 50
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(battle_comments)
                    .where(
                        battle_comments.c.battle_id == battle_id,
                        battle_comments.c.id > max(0, int(after_id)),
                    )
                    .order_by(battle_comments.c.id)
                    .limit(safe_limit)
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    async def add_battle_comment(
        self, battle_id: str, user_id: int | str, content: str
    ) -> dict[str, Any]:
        cleaned = " ".join(content.replace("\x00", "").split()).strip()
        if not cleaned:
            raise ChaldeaError("弹幕不能为空")
        if len(cleaned) > 60:
            raise ChaldeaError("弹幕最多 60 个字符")
        uid = str(user_id)
        now = dt.datetime.utcnow()
        async with AsyncSessionLocal() as session:
            async with session.begin():
                battle = (
                    await session.execute(
                        select(battles.c.status).where(battles.c.id == battle_id).with_for_update()
                    )
                ).scalar_one_or_none()
                if battle not in ("active", "finished"):
                    raise ChaldeaError("该对局不可评论")
                latest = (
                    await session.execute(
                        select(battle_comments.c.created_at)
                        .where(
                            battle_comments.c.battle_id == battle_id,
                            battle_comments.c.user_id == uid,
                        )
                        .order_by(battle_comments.c.id.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if latest and (now - latest).total_seconds() < 2:
                    raise ChaldeaError("弹幕发送太快，请稍等 2 秒")
                row = (
                    await session.execute(
                        insert(battle_comments)
                        .values(battle_id=battle_id, user_id=uid, content=cleaned, created_at=now)
                        .returning(battle_comments)
                    )
                ).mappings().one()
        return dict(row)

    async def _grant_battle_rewards(self, session, battle: dict[str, Any], state: dict[str, Any]) -> None:
        winner = state.get("winner_id")
        for uid in (str(battle["challenger_id"]), str(battle["opponent_id"])):
            won = winner is not None and str(winner) == uid
            qp_gain = self.WIN_QP if won else self.LOSS_QP
            exp_gain = self.WIN_EXP if won else self.LOSS_EXP
            updated = (
                await session.execute(
                    update(profiles)
                    .where(profiles.c.user_id == uid)
                    .values(
                        qp=profiles.c.qp + qp_gain,
                        training_exp=profiles.c.training_exp + exp_gain,
                        updated_at=dt.datetime.utcnow(),
                    )
                    .returning(profiles.c.qp, profiles.c.training_exp)
                )
            ).mappings().one()
            await session.execute(insert(currency_ledger).values([
                {
                    "user_id": uid,
                    "amount": qp_gain,
                    "balance_after": int(updated["qp"]),
                    "resource_type": "qp",
                    "reason": "迦勒底对战奖励",
                    "idempotency_key": f"battle:{battle['id']}:{uid}:qp",
                },
                {
                    "user_id": uid,
                    "amount": exp_gain,
                    "balance_after": int(updated["training_exp"]),
                    "resource_type": "training_exp",
                    "reason": "迦勒底对战奖励",
                    "idempotency_key": f"battle:{battle['id']}:{uid}:exp",
                },
            ]))

    async def submit_action(self, battle_id: str, user_id: int | str, action: dict[str, Any]) -> dict[str, Any]:
        uid = str(user_id)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                battle = (
                    await session.execute(
                        select(battles).where(battles.c.id == battle_id).with_for_update()
                    )
                ).mappings().one_or_none()
                if not battle or battle["status"] != "active" or not battle["state"]:
                    raise ChaldeaError("战斗不存在或已经结束")
                if uid not in (battle["challenger_id"], battle["opponent_id"]):
                    raise ChaldeaError("你不是这场战斗的参与者")
                state = upgrade_battle_state(dict(battle["state"]))
                expected_version = action.pop("expected_version", None)
                if expected_version is None or int(expected_version) != int(state["state_version"]):
                    raise ChaldeaError("战斗状态已经更新，请刷新后重新确认行动")
                if state["active_player_id"] != uid:
                    raise ChaldeaError("当前是对方的行动阶段")
                validate_action(state, uid, action)
                await session.execute(
                    insert(battle_actions)
                    .values(battle_id=battle_id, turn=state["phase_no"], user_id=uid, payload=action)
                    .on_conflict_do_update(
                        constraint="uq_chaldea_action_battle_turn_user",
                        set_={"payload": action, "created_at": dt.datetime.utcnow()},
                    )
                )
                next_state = resolve_phase(state, uid, action)
                if next_state["status"] == "finished":
                    await self._grant_battle_rewards(session, dict(battle), next_state)
                await session.execute(
                    update(battles)
                    .where(battles.c.id == battle_id)
                    .values(
                        status=next_state["status"],
                        turn=next_state["turn"],
                        state=next_state,
                        winner_id=next_state.get("winner_id"),
                        updated_at=dt.datetime.utcnow(),
                    )
                )
                return {"resolved": True, "state": public_view(next_state, uid)["state"]}

    async def submit_skill(
        self, battle_id: str, user_id: int | str, expected_version: int, skill: dict[str, Any]
    ) -> dict[str, Any]:
        uid = str(user_id)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                battle = (
                    await session.execute(
                        select(battles).where(battles.c.id == battle_id).with_for_update()
                    )
                ).mappings().one_or_none()
                if not battle or battle["status"] != "active" or not battle["state"]:
                    raise ChaldeaError("战斗不存在或已经结束")
                if uid not in (battle["challenger_id"], battle["opponent_id"]):
                    raise ChaldeaError("你不是这场战斗的参与者")
                state = upgrade_battle_state(dict(battle["state"]))
                if int(expected_version) != int(state["state_version"]):
                    raise ChaldeaError("战斗状态已经更新，请刷新后重新确认技能")
                if state["active_player_id"] != uid:
                    raise ChaldeaError("当前是对方的行动阶段")
                next_state = resolve_skill(state, uid, skill)
                await session.execute(
                    update(battles)
                    .where(battles.c.id == battle_id)
                    .values(state=next_state, updated_at=dt.datetime.utcnow())
                )
                return {"resolved": True, "state": public_view(next_state, uid)["state"]}

    async def submit_tactic(
        self, battle_id: str, user_id: int | str, expected_version: int, tactic: dict[str, Any]
    ) -> dict[str, Any]:
        uid = str(user_id)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                battle = (
                    await session.execute(
                        select(battles).where(battles.c.id == battle_id).with_for_update()
                    )
                ).mappings().one_or_none()
                if not battle or battle["status"] != "active" or not battle["state"]:
                    raise ChaldeaError("战斗不存在或已经结束")
                if uid not in (battle["challenger_id"], battle["opponent_id"]):
                    raise ChaldeaError("你不是这场战斗的参与者")
                state = upgrade_battle_state(dict(battle["state"]))
                if int(expected_version) != int(state["state_version"]):
                    raise ChaldeaError("战斗状态已经更新，请刷新后重新确认战术")
                if state["active_player_id"] != uid:
                    raise ChaldeaError("当前是对方的行动阶段")
                next_state = resolve_tactic(state, uid, tactic)
                await session.execute(
                    update(battles)
                    .where(battles.c.id == battle_id)
                    .values(
                        state=next_state,
                        status=next_state["status"],
                        winner_id=next_state.get("winner_id"),
                        updated_at=dt.datetime.utcnow(),
                    )
                )
                return {"resolved": True, "state": public_view(next_state, uid)["state"]}

    async def _grant_resource(
        self,
        user_id: int | str,
        resource_type: str,
        amount: int,
        reason: str,
        idempotency_key: str,
    ) -> int:
        columns = {
            "quartz": profiles.c.quartz,
            "qp": profiles.c.qp,
            "training_exp": profiles.c.training_exp,
        }
        column = columns.get(resource_type)
        if column is None:
            raise ChaldeaError("未知资源类型")
        if amount <= 0 or amount > 10_000_000:
            raise ChaldeaError("发放数量必须在 1 到 10000000 之间")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                uid = await self._ensure_player(session, user_id)
                existing = (
                    await session.execute(
                        select(currency_ledger.c.balance_after).where(
                            currency_ledger.c.idempotency_key == idempotency_key
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return int(existing)
                balance = (
                    await session.execute(
                        update(profiles)
                        .where(profiles.c.user_id == uid)
                        .values({
                            column.key: column + amount,
                            "updated_at": dt.datetime.utcnow(),
                        })
                        .returning(column)
                    )
                ).scalar_one()
                await session.execute(
                    insert(currency_ledger).values(
                        user_id=uid,
                        amount=amount,
                        balance_after=balance,
                        resource_type=resource_type,
                        reason=reason[:255],
                        idempotency_key=idempotency_key,
                    )
                )
                return int(balance)

    async def grant_quartz(
        self, user_id: int | str, amount: int, reason: str, idempotency_key: str
    ) -> int:
        return await self._grant_resource(
            user_id, "quartz", amount, reason, idempotency_key
        )

    async def grant_qp(
        self, user_id: int | str, amount: int, reason: str, idempotency_key: str
    ) -> int:
        return await self._grant_resource(user_id, "qp", amount, reason, idempotency_key)

    async def grant_training_exp(
        self, user_id: int | str, amount: int, reason: str, idempotency_key: str
    ) -> int:
        return await self._grant_resource(
            user_id, "training_exp", amount, reason, idempotency_key
        )

    @staticmethod
    def _level_cost(level: int) -> tuple[int, int]:
        return 40 + int(level) * 10, 150 + int(level) * 35

    async def train_servant(
        self, user_id: int | str, servant_id: str, levels: int = 1
    ) -> dict[str, int]:
        if servant_id not in SERVANTS:
            raise ChaldeaError("英灵 ID 不存在")
        if levels < 1 or levels > 10:
            raise ChaldeaError("每次可提升 1 到 10 级")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                uid = await self._ensure_player(session, user_id)
                owned = (
                    await session.execute(
                        select(owned_servants)
                        .where(
                            owned_servants.c.user_id == uid,
                            owned_servants.c.servant_id == servant_id,
                        )
                        .with_for_update()
                    )
                ).mappings().one_or_none()
                if owned is None:
                    raise ChaldeaError("你尚未拥有这名英灵")
                current_level = int(owned["level"])
                target_level = min(80, current_level + levels)
                if target_level == current_level:
                    raise ChaldeaError("该英灵已经达到 80 级")
                exp_cost = sum(self._level_cost(level)[0] for level in range(current_level, target_level))
                qp_cost = sum(self._level_cost(level)[1] for level in range(current_level, target_level))
                profile = (
                    await session.execute(
                        select(profiles).where(profiles.c.user_id == uid).with_for_update()
                    )
                ).mappings().one()
                if int(profile["training_exp"]) < exp_cost:
                    raise ChaldeaError(
                        f"战斗经验不足，需要 {exp_cost}，当前 {profile['training_exp']}"
                    )
                if int(profile["qp"]) < qp_cost:
                    raise ChaldeaError(f"QP 不足，需要 {qp_cost}，当前 {profile['qp']}")
                await session.execute(
                    update(owned_servants)
                    .where(owned_servants.c.id == owned["id"])
                    .values(level=target_level)
                )
                balances = (
                    await session.execute(
                        update(profiles)
                        .where(profiles.c.user_id == uid)
                        .values(
                            qp=profiles.c.qp - qp_cost,
                            training_exp=profiles.c.training_exp - exp_cost,
                            updated_at=dt.datetime.utcnow(),
                        )
                        .returning(profiles.c.qp, profiles.c.training_exp)
                    )
                ).mappings().one()
                key = f"train:{uid}:{servant_id}:{current_level}:{target_level}:{uuid.uuid4()}"
                await session.execute(insert(currency_ledger).values([
                    {
                        "user_id": uid, "amount": -qp_cost,
                        "balance_after": int(balances["qp"]), "resource_type": "qp",
                        "reason": f"培养 {servant_id} 至 Lv.{target_level}",
                        "idempotency_key": f"{key}:qp",
                    },
                    {
                        "user_id": uid, "amount": -exp_cost,
                        "balance_after": int(balances["training_exp"]),
                        "resource_type": "training_exp",
                        "reason": f"培养 {servant_id} 至 Lv.{target_level}",
                        "idempotency_key": f"{key}:exp",
                    },
                ]))
        return {
            "level": target_level,
            "exp_cost": exp_cost,
            "qp_cost": qp_cost,
            "qp": int(balances["qp"]),
            "training_exp": int(balances["training_exp"]),
        }

    async def unlock_all_servants(self, user_id: int | str) -> dict[str, int]:
        """Grant every standard servant without changing existing or event copies."""
        servant_ids = [
            servant_id
            for servant_id, servant in SERVANTS.items()
            if servant.get("released", False) and not servant.get("event_only", False)
        ]
        async with AsyncSessionLocal() as session:
            async with session.begin():
                uid = await self._ensure_player(session, user_id)
                inserted = await session.execute(
                    insert(owned_servants)
                    .values(
                        [
                            {
                                "user_id": uid,
                                "servant_id": servant_id,
                                "level": 1,
                                "np_level": 1,
                                "shards": 0,
                            }
                            for servant_id in servant_ids
                        ]
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            owned_servants.c.user_id,
                            owned_servants.c.servant_id,
                        ]
                    )
                    .returning(owned_servants.c.servant_id)
                )
                added = len(list(inserted.scalars()))
                total = (
                    await session.execute(
                        select(owned_servants.c.servant_id).where(
                            owned_servants.c.user_id == uid,
                            owned_servants.c.servant_id.in_(servant_ids),
                        )
                    )
                ).scalars().all()
        return {"added": added, "total": len(total)}

    async def grant_event_servant(
        self,
        user_id: int | str,
        servant_id: str,
    ) -> dict[str, Any]:
        """Grant one administrator-only event servant, idempotently."""
        if servant_id not in EVENT_SERVANT_IDS:
            raise ChaldeaError("该英灵不是可发放的活动英灵。")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                uid = await self._ensure_player(session, user_id)
                inserted = await session.execute(
                    insert(owned_servants)
                    .values(
                        user_id=uid,
                        servant_id=servant_id,
                        level=1,
                        np_level=1,
                        shards=0,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            owned_servants.c.user_id,
                            owned_servants.c.servant_id,
                        ]
                    )
                    .returning(owned_servants.c.servant_id)
                )
                added = inserted.scalar_one_or_none() is not None
        return {
            "added": added,
            "servant_id": servant_id,
            "name": SERVANTS[servant_id]["name"],
        }


chaldea_service = ChaldeaService()
