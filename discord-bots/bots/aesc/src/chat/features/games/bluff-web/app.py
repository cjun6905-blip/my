# -*- coding: utf-8 -*-
"""吹牌 Web 服务。

对外（经 Caddy `handle_path /bluff/*`，前缀已被剥掉）：
    GET  /healthz            健康检查
    GET  /r/{room_id}        牌桌页面
    WS   /ws?room=&t=        实时对局通道
对内（仅限 aesc_private 网络内的 bot 调用，需共享密钥）：
    POST /internal/rooms     开一局，返回三个一次性链接

不依赖数据库、不依赖 Discord OAuth、不做押注。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .engine import RuleError
from .room import RoomManager

log = logging.getLogger(__name__)

SERVICE_NAME = "bluff"
HERE = Path(__file__).resolve().parent
INDEX_FILE = HERE / "static" / "index.html"

app = FastAPI(title="吹牌", docs_url=None, redoc_url=None, openapi_url=None)


def _public_base_url() -> str:
    explicit = os.getenv("BLUFF_PUBLIC_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = os.getenv("PUBLIC_HOST", "").strip()
    return f"https://{host}" if host else ""


manager = RoomManager(public_base_url=_public_base_url())


@app.on_event("startup")
async def _startup() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")
    manager.start()
    if not os.getenv("BLUFF_INTERNAL_SECRET"):
        log.error("BLUFF_INTERNAL_SECRET 未设置，开房接口将拒绝所有请求")
    log.info("吹牌服务已启动，公开地址前缀=%s", manager.public_base_url or "(未配置)")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await manager.stop()


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "rooms": len(manager.rooms),
    }


# --- 内部接口：bot 开房 -------------------------------------------------------


class PlayerIn(BaseModel):
    id: str
    name: str


class CreateRoomIn(BaseModel):
    players: list[PlayerIn] = Field(min_length=3, max_length=3)


def _check_internal_secret(provided: str | None) -> None:
    import secrets as _secrets

    expected = os.getenv("BLUFF_INTERNAL_SECRET", "")
    if not expected:
        raise HTTPException(status_code=503, detail="服务未配置内部密钥")
    if not provided or not _secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="内部密钥不匹配")


@app.post("/internal/rooms")
async def create_room(
    body: CreateRoomIn,
    x_internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
) -> JSONResponse:
    _check_internal_secret(x_internal_secret)
    try:
        result = manager.create_room([p.model_dump() for p in body.players])
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)


# --- 牌桌页面 -----------------------------------------------------------------


@app.get("/r/{room_id}", response_class=HTMLResponse, include_in_schema=False)
async def table_page(room_id: str) -> HTMLResponse:
    if not INDEX_FILE.is_file():
        raise HTTPException(status_code=500, detail="前端页面缺失")
    # 房间是否存在交给 WebSocket 去判定，页面本身总是可以打开，
    # 这样过期链接也能看到一句人话的提示而不是 404。
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))


@app.get("/", include_in_schema=False)
async def root() -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<title>吹牌</title>"
        "<body style='font:16px/1.7 system-ui;padding:3rem;max-width:34rem;margin:auto'>"
        "<h1>吹牌</h1><p>这个页面需要从 Discord 里的对局邀请进入。"
        "在服务器里用 <code>/bluff</code> 开一局，凑齐三个人后点「打开我的牌桌」即可。</p>"
        "</body>"
    )


# --- 实时通道 -----------------------------------------------------------------


@app.websocket("/ws")
async def game_socket(websocket: WebSocket) -> None:
    room_id = websocket.query_params.get("room", "")
    token = websocket.query_params.get("t", "")

    room = manager.get(room_id)
    if room is None:
        await websocket.accept()
        await websocket.send_json({"type": "fatal", "message": "房间不存在或已过期"})
        await websocket.close()
        return

    seat = room.seat_by_token(token)
    if seat is None:
        await websocket.accept()
        await websocket.send_json({"type": "fatal", "message": "链接无效——请用机器人私信给你的那条"})
        await websocket.close()
        return

    await websocket.accept()
    manager.attach(room, seat.user_id, websocket)
    log.info("房间 %s：%s 已连接", room.id, seat.name)
    await manager.broadcast(room)

    try:
        while True:
            message = await websocket.receive_json()
            action = str(message.get("action", ""))
            if action == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if action == "sync":
                await manager.broadcast(room)
                continue

            error = await manager.apply_action(room, seat.user_id, action, message)
            if error:
                await manager.send_error(websocket, error)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("房间 %s：%s 的连接异常", room.id, seat.name)
    finally:
        manager.detach(room, seat.user_id, websocket)
        log.info("房间 %s：%s 已断开", room.id, seat.name)
        try:
            await manager.broadcast(room)
        except Exception:
            pass


@app.exception_handler(RuleError)
async def _rule_error_handler(_: Request, exc: RuleError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})
