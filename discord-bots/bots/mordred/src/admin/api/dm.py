import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from src.admin.auth import require_dm_operator
from src.admin.services.audit_log_service import audit_log_service
from src.chat.services.config_override_service import config_override_service
from src.chat.services.dm_service import DM_CONFIG_DEFAULT, DM_CONFIG_KEY
from src.database.database import AsyncSessionLocal
from src.database.models import DmCampaign, DmDelivery, DmUserPreference

router = APIRouter(prefix="/api/dm", dependencies=[Depends(require_dm_operator)])


class SettingsBody(BaseModel):
    enabled: bool = True
    daily_limit: int = Field(default=10, ge=1, le=100)
    timezone: str = "Asia/Shanghai"


class ManualBody(BaseModel):
    user_id: int
    content: str = Field(min_length=1, max_length=1800)


class HolidayBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=1800)
    scheduled_at: dt.datetime


class StatusBody(BaseModel):
    status: str


def _utc_naive(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(dt.timezone.utc).replace(tzinfo=None)


@router.get("/settings")
async def get_settings():
    value = await config_override_service.get_json(DM_CONFIG_KEY, DM_CONFIG_DEFAULT)
    return {**DM_CONFIG_DEFAULT, **(value if isinstance(value, dict) else {})}


@router.put("/settings")
async def update_settings(body: SettingsBody, operator: int = Depends(require_dm_operator)):
    value = body.model_dump()
    await config_override_service.set(DM_CONFIG_KEY, value)
    await audit_log_service.log(operator, "update", "dm_settings", DM_CONFIG_KEY, value)
    return value


@router.get("/users")
async def list_users():
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(DmUserPreference).order_by(DmUserPreference.updated_at.desc()).limit(500)
        )).scalars().all()
    return {"items": [
        {
            "user_id": row.user_id,
            "greetings_opt_in": row.greetings_opt_in,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]}


@router.post("/manual")
async def create_manual(body: ManualBody, operator: int = Depends(require_dm_operator)):
    async with AsyncSessionLocal() as session:
        if await session.get(DmUserPreference, body.user_id) is None:
            raise HTTPException(status_code=400, detail="该用户尚未主动与 Bot 建立私信会话")
        campaign = DmCampaign(
            kind="manual",
            name=f"给用户 {body.user_id} 的留言",
            content=body.content.strip(),
            scheduled_at=dt.datetime.utcnow(),
            status="scheduled",
            target_user_id=body.user_id,
            created_by=operator,
        )
        session.add(campaign)
        await session.commit()
        await session.refresh(campaign)
    await audit_log_service.log(operator, "create", "dm_manual", str(campaign.id), {"user_id": str(body.user_id)})
    return {"id": campaign.id, "status": campaign.status}


@router.post("/campaigns")
async def create_holiday(body: HolidayBody, operator: int = Depends(require_dm_operator)):
    scheduled_at = _utc_naive(body.scheduled_at)
    if scheduled_at < dt.datetime.utcnow() - dt.timedelta(minutes=1):
        raise HTTPException(status_code=400, detail="发送时间不能早于当前时间")
    async with AsyncSessionLocal() as session:
        campaign = DmCampaign(
            kind="holiday",
            name=body.name.strip(),
            content=body.content.strip(),
            scheduled_at=scheduled_at,
            status="scheduled",
            created_by=operator,
        )
        session.add(campaign)
        await session.commit()
        await session.refresh(campaign)
    await audit_log_service.log(operator, "create", "dm_campaign", str(campaign.id), {"name": campaign.name, "scheduled_at": campaign.scheduled_at.isoformat()})
    return {"id": campaign.id, "status": campaign.status}


@router.get("/campaigns")
async def list_campaigns():
    async with AsyncSessionLocal() as session:
        campaigns = (await session.execute(
            select(DmCampaign).order_by(DmCampaign.id.desc()).limit(100)
        )).scalars().all()
        result = []
        for row in campaigns:
            counts = dict((await session.execute(
                select(DmDelivery.status, func.count()).where(DmDelivery.campaign_id == row.id).group_by(DmDelivery.status)
            )).all())
            result.append({
                "id": row.id, "kind": row.kind, "name": row.name,
                "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
                "status": row.status, "target_user_id": row.target_user_id,
                "deliveries": counts,
            })
    return {"items": result}


@router.put("/campaigns/{campaign_id}/status")
async def update_campaign_status(campaign_id: int, body: StatusBody, operator: int = Depends(require_dm_operator)):
    if body.status not in {"paused", "scheduled", "cancelled"}:
        raise HTTPException(status_code=400, detail="不支持的状态")
    async with AsyncSessionLocal() as session:
        campaign = await session.get(DmCampaign, campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="活动不存在")
        if campaign.status in {"completed", "completed_with_errors", "cancelled"}:
            raise HTTPException(status_code=409, detail="活动已经结束")
        if body.status == "scheduled" and campaign.scheduled_at < dt.datetime.utcnow():
            campaign.scheduled_at = dt.datetime.utcnow()
        campaign.status = body.status
        await session.commit()
    await audit_log_service.log(operator, "update", "dm_campaign", str(campaign_id), {"status": body.status})
    return {"id": campaign_id, "status": body.status}
