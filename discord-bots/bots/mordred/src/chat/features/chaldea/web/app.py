from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Literal, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.chat.features.chaldea.battle_engine import public_view, spectator_view, upgrade_battle_state
from src.chat.features.chaldea.auth_ticket import TicketError, verify_browser_ticket_claims
from src.chat.features.chaldea.catalog import SERVANTS, public_catalogue
from src.chat.features.chaldea.tactics import MASTER_TEMPLATES
from src.chat.features.chaldea.services.chaldea_service import (
    ChaldeaError,
    chaldea_service,
)


log = logging.getLogger(__name__)
mimetypes.add_type("image/webp", ".webp")
app = FastAPI(title="Chaldea Battle Activity", version="0.1.0")
auth_scheme = HTTPBearer(auto_error=False)


class ActionRequest(BaseModel):
    battle_id: str
    expected_version: int
    skills: list[dict[str, Any]] = Field(default_factory=list)
    commands: list[dict[str, Any]]


class AbandonRequest(BaseModel):
    battle_id: str


class SkillRequest(BaseModel):
    battle_id: str
    expected_version: int
    skill: dict[str, Any]


class TacticRequest(BaseModel):
    battle_id: str
    expected_version: int
    tactic: dict[str, Any]


class TeamRequest(BaseModel):
    servant_ids: list[str]


class MasterTemplateRequest(BaseModel):
    template_id: str


class TrainRequest(BaseModel):
    servant_id: str
    levels: int = Field(default=1, ge=1, le=10)


class AdminGrantRequest(BaseModel):
    user_id: str
    resource: Literal["quartz", "qp", "training_exp"]
    amount: int = Field(ge=1, le=10_000_000)
    reason: str = Field(default="网页管理员活动奖励", max_length=255)
    request_id: str = Field(min_length=8, max_length=100)


class AdminServantRequest(BaseModel):
    user_id: str
    servant_id: str


class CommentRequest(BaseModel):
    battle_id: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=60)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "public, max-age=300"
    return response


async def get_current_auth(
    token: Optional[HTTPAuthorizationCredentials] = Depends(auth_scheme),
) -> dict[str, int | str]:
    if token is None:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    if token.credentials.startswith("chaldea."):
        try:
            return verify_browser_ticket_claims(token.credentials)
        except TicketError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired browser ticket") from exc
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://discord.com/api/users/@me",
                headers={"Authorization": f"Bearer {token.credentials}"},
            )
        response.raise_for_status()
        return {"user_id": int(response.json()["id"]), "scope": "player"}
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        log.warning("Discord user validation failed: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Invalid or expired Discord token") from exc


async def get_current_user_id(auth: dict[str, int | str] = Depends(get_current_auth)) -> int:
    if auth.get("scope") != "player":
        raise HTTPException(status_code=403, detail="Player ticket required")
    return int(auth["user_id"])


async def get_current_admin_id(auth: dict[str, int | str] = Depends(get_current_auth)) -> int:
    if auth.get("scope") != "admin":
        raise HTTPException(status_code=403, detail="Administrator ticket required")
    return int(auth["user_id"])


async def _management_payload(user_id: int | str) -> dict[str, Any]:
    profile = await chaldea_service.get_profile(user_id)
    roster = await chaldea_service.get_roster(user_id)
    battle = await chaldea_service.get_battle(user_id)
    return {
        "user_id": str(user_id),
        "profile": profile,
        "roster": roster,
        "battle": battle,
        "catalogue": public_catalogue(),
        "master_templates": list(MASTER_TEMPLATES.values()),
    }


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "chaldea"}


@app.get("/api/catalogue")
async def catalogue(user_id: int = Depends(get_current_user_id)):
    return {"items": public_catalogue(), "viewer": str(user_id)}


@app.get("/api/me")
async def me(user_id: int = Depends(get_current_user_id)):
    profile = await chaldea_service.get_profile(user_id)
    roster = await chaldea_service.get_roster(user_id)
    battle = await chaldea_service.get_battle(user_id)
    payload: dict[str, Any] = {
        "user_id": str(user_id),
        "profile": profile,
        "roster": roster,
        "battle": None,
    }
    if battle:
        payload["battle"] = {
            "id": battle["id"],
            "status": battle["status"],
            "challenger_id": battle["challenger_id"],
            "opponent_id": battle["opponent_id"],
        }
        if battle.get("state"):
            payload["battle"].update(public_view(dict(battle["state"]), str(user_id)))
    return JSONResponse(payload)


@app.get("/api/manage/me")
async def manage_me(user_id: int = Depends(get_current_user_id)):
    return await _management_payload(user_id)


@app.post("/api/manage/team")
async def manage_team(request: TeamRequest, user_id: int = Depends(get_current_user_id)):
    try:
        team = await chaldea_service.set_team(user_id, request.servant_ids)
        return {"team": team}
    except ChaldeaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/manage/master-template")
async def manage_master_template(
    request: MasterTemplateRequest, user_id: int = Depends(get_current_user_id)
):
    try:
        return {"template": await chaldea_service.set_master_template(user_id, request.template_id)}
    except ChaldeaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/manage/train")
async def manage_train(request: TrainRequest, user_id: int = Depends(get_current_user_id)):
    try:
        return await chaldea_service.train_servant(user_id, request.servant_id, request.levels)
    except ChaldeaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/admin/player/{target_user_id}")
async def admin_player(target_user_id: str, _admin_id: int = Depends(get_current_admin_id)):
    if not target_user_id.isdigit():
        raise HTTPException(status_code=422, detail="Discord user ID must be numeric")
    return await _management_payload(target_user_id)


@app.post("/api/admin/grant")
async def admin_grant(request: AdminGrantRequest, admin_id: int = Depends(get_current_admin_id)):
    if not request.user_id.isdigit():
        raise HTTPException(status_code=422, detail="Discord user ID must be numeric")
    key = f"web-admin:{admin_id}:{request.request_id}:{request.resource}"
    try:
        if request.resource == "quartz":
            balance = await chaldea_service.grant_quartz(request.user_id, request.amount, request.reason, key)
        elif request.resource == "qp":
            balance = await chaldea_service.grant_qp(request.user_id, request.amount, request.reason, key)
        else:
            balance = await chaldea_service.grant_training_exp(request.user_id, request.amount, request.reason, key)
        return {"resource": request.resource, "balance": balance}
    except ChaldeaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/admin/servant")
async def admin_servant(request: AdminServantRequest, _admin_id: int = Depends(get_current_admin_id)):
    if not request.user_id.isdigit():
        raise HTTPException(status_code=422, detail="Discord user ID must be numeric")
    try:
        return await chaldea_service.grant_event_servant(request.user_id, request.servant_id)
    except ChaldeaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/admin/unlock-standard/{target_user_id}")
async def admin_unlock_standard(target_user_id: str, _admin_id: int = Depends(get_current_admin_id)):
    if not target_user_id.isdigit():
        raise HTTPException(status_code=422, detail="Discord user ID must be numeric")
    return await chaldea_service.unlock_all_servants(target_user_id)


@app.get("/api/battle/state")
async def battle_state(user_id: int = Depends(get_current_user_id)):
    battle = await chaldea_service.get_battle(user_id)
    if not battle or not battle.get("state"):
        raise HTTPException(status_code=404, detail="No battle found")
    state = upgrade_battle_state(dict(battle["state"]))
    return {
        "id": battle["id"],
        "status": battle["status"],
        **public_view(state, str(user_id)),
        "catalogue": SERVANTS,
    }


@app.get("/api/spectate/state")
async def spectate_state(auth: dict[str, int | str] = Depends(get_current_auth)):
    if auth.get("scope") != "spectator" or not auth.get("battle_id"):
        raise HTTPException(status_code=403, detail="Spectator ticket required")
    battle = await chaldea_service.get_public_battle(str(auth["battle_id"]))
    if not battle or not battle.get("state"):
        raise HTTPException(status_code=404, detail="Battle is unavailable")
    state = upgrade_battle_state(dict(battle["state"]))
    return {
        "id": battle["id"],
        "status": battle["status"],
        **spectator_view(state),
        "catalogue": SERVANTS,
        "viewer_id": str(auth["user_id"]),
    }


async def _comment_battle(auth: dict[str, int | str], battle_id: str) -> dict[str, Any]:
    scope = str(auth.get("scope", ""))
    if scope == "spectator":
        if str(auth.get("battle_id", "")) != battle_id:
            raise HTTPException(status_code=403, detail="Spectator ticket belongs to another battle")
        battle = await chaldea_service.get_public_battle(battle_id)
    elif scope == "player":
        battle = await chaldea_service.get_battle(auth["user_id"], battle_id)
    elif scope == "admin":
        battle = await chaldea_service.get_public_battle(battle_id)
    else:
        battle = None
    if not battle:
        raise HTTPException(status_code=403, detail="Battle access denied")
    return battle


@app.get("/api/battle/comments")
async def battle_comments(
    battle_id: str,
    after_id: int = 0,
    auth: dict[str, int | str] = Depends(get_current_auth),
):
    await _comment_battle(auth, battle_id)
    items = await chaldea_service.get_battle_comments(battle_id, after_id=after_id)
    return {"items": items}


@app.post("/api/battle/comments")
async def post_battle_comment(
    request: CommentRequest,
    auth: dict[str, int | str] = Depends(get_current_auth),
):
    await _comment_battle(auth, request.battle_id)
    try:
        return await chaldea_service.add_battle_comment(
            request.battle_id, auth["user_id"], request.content
        )
    except ChaldeaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/battle/action")
async def battle_action(
    request: ActionRequest, user_id: int = Depends(get_current_user_id)
):
    try:
        result = await chaldea_service.submit_action(
            request.battle_id,
            user_id,
            {
                "expected_version": request.expected_version,
                "skills": request.skills,
                "commands": request.commands,
            },
        )
        return result
    except (ChaldeaError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/battle/abandon")
async def battle_abandon(
    request: AbandonRequest, user_id: int = Depends(get_current_user_id)
):
    try:
        battle_id = await chaldea_service.abandon_battle(user_id, request.battle_id)
        return {"id": battle_id, "status": "abandoned"}
    except ChaldeaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/battle/skill")
async def battle_skill(
    request: SkillRequest, user_id: int = Depends(get_current_user_id)
):
    try:
        return await chaldea_service.submit_skill(
            request.battle_id, user_id, request.expected_version, request.skill
        )
    except (ChaldeaError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/battle/tactic")
async def battle_tactic(
    request: TacticRequest, user_id: int = Depends(get_current_user_id)
):
    try:
        return await chaldea_service.submit_tactic(
            request.battle_id, user_id, request.expected_version, request.tactic
        )
    except (ChaldeaError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


static_path = Path(__file__).with_name("dist")
if static_path.is_dir():
    app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
