# -*- coding: utf-8 -*-
"""吹牌端到端自检：在容器里起一个真服务，用三条 WebSocket 打完一整局。

这是上线前的验收证据，也可以在出问题时当诊断工具单独跑：
    docker exec aesc_bluff python3 -m src.chat.features.games.bluff-web.selftest

重点检查：
  * 开房接口的密钥校验（无密钥 / 错密钥必须被拒）
  * 三条连接各自只能看到自己的手牌，收到的任何一条报文都不得出现他人手牌
  * 不是自己的回合时操作会被拒绝，且不影响牌局
  * 一整局能正常打到分出胜负
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import socket
import subprocess
import sys
import time
from typing import Any

import httpx
import websockets

SECRET = "selftest-" + os.urandom(8).hex()
RNG = random.Random(7)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Result:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, ok: bool, label: str) -> None:
        print(f"  [{'ok' if ok else 'FAIL'}] {label}", flush=True)
        if not ok:
            self.failures.append(label)


async def _wait_healthy(base: str, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    async with httpx.AsyncClient(timeout=3.0) as client:
        while time.time() < deadline:
            try:
                r = await client.get(f"{base}/healthz")
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.4)
    return False


async def run(base: str, ws_base: str, res: Result) -> None:
    players = [
        {"id": "1001", "name": "阿一"},
        {"id": "1002", "name": "阿二"},
        {"id": "1003", "name": "阿三"},
    ]

    async with httpx.AsyncClient(timeout=10.0) as client:
        # --- 密钥校验 ---
        r = await client.post(f"{base}/internal/rooms", json={"players": players})
        res.check(r.status_code == 403, f"无密钥开房被拒（收到 {r.status_code}）")
        r = await client.post(
            f"{base}/internal/rooms", json={"players": players},
            headers={"X-Internal-Secret": "wrong"},
        )
        res.check(r.status_code == 403, f"错误密钥开房被拒（收到 {r.status_code}）")
        # 人数必须是 3
        r = await client.post(
            f"{base}/internal/rooms", json={"players": players[:2]},
            headers={"X-Internal-Secret": SECRET},
        )
        res.check(r.status_code == 422, f"两人开房被拒（收到 {r.status_code}）")

        # --- 正常开房 ---
        r = await client.post(
            f"{base}/internal/rooms", json={"players": players},
            headers={"X-Internal-Secret": SECRET},
        )
        res.check(r.status_code == 200, f"开房成功（收到 {r.status_code}）")
        if r.status_code != 200:
            return
        room = r.json()
        urls = [p["url"] for p in room["players"]]
        res.check(len(set(urls)) == 3, "三个玩家拿到三条不同的链接")

    room_id = room["room_id"]
    tokens = {p["user_id"]: p["url"].split("t=")[-1] for p in room["players"]}

    # --- 无效令牌必须被拒 ---
    async with websockets.connect(f"{ws_base}/ws?room={room_id}&t=bogus") as sock:
        msg = json.loads(await asyncio.wait_for(sock.recv(), 5))
        res.check(msg.get("type") == "fatal", "伪造令牌被拒绝进入")

    # --- 三人入桌 ---
    conns: dict[str, Any] = {}
    latest: dict[str, dict] = {}
    seen_blobs: dict[str, list[str]] = {pid: [] for pid in tokens}
    for pid, tok in tokens.items():
        conns[pid] = await websockets.connect(f"{ws_base}/ws?room={room_id}&t={tok}")

    async def pump(pid: str, expect: int = 1) -> None:
        """收干当前可读的报文，记下最新状态与原始报文（供泄露检查）。"""
        got = 0
        while True:
            try:
                raw = await asyncio.wait_for(conns[pid].recv(), 0.25)
            except asyncio.TimeoutError:
                if got >= expect:
                    return
                return
            seen_blobs[pid].append(raw)
            msg = json.loads(raw)
            if msg.get("type") == "state":
                latest[pid] = msg["state"]
            got += 1

    for pid in tokens:
        await pump(pid)
    res.check(len(latest) == 3, "三条连接都收到了初始状态")
    if len(latest) != 3:
        return

    hands = {pid: {c["id"] for c in latest[pid]["you"]["hand"]} for pid in tokens}
    res.check(all(len(h) == 18 for h in hands.values()), "每人 18 张手牌")
    all_ids = set().union(*hands.values())
    res.check(len(all_ids) == 54, f"三人手牌合计 54 张互不重复（实得 {len(all_ids)}）")

    # --- 不是自己的回合不能动 ---
    turn = latest[next(iter(tokens))]["turn_player_id"]
    other = next(p for p in tokens if p != turn)
    await conns[other].send(json.dumps({"action": "pass"}))
    raw = await asyncio.wait_for(conns[other].recv(), 5)
    seen_blobs[other].append(raw)
    res.check(json.loads(raw).get("type") == "error", "非当前回合的操作被拒绝")

    # --- 打完一整局 ---
    steps = 0
    winner = None
    while steps < 4000:
        state = latest[turn]
        me = state["you"]
        acts = me["legal_actions"]
        if not acts:
            break
        action = RNG.choice(acts)
        if action in ("lead", "follow"):
            # max_cards_per_play 为 null 表示不限张数
            lim = state["max_cards_per_play"] or len(me["hand"])
            n = RNG.randint(1, min(lim, len(me["hand"])))
            cards = [c["id"] for c in RNG.sample(me["hand"], n)]
            payload = {"action": action, "cards": cards}
            if action == "lead":
                payload["rank"] = RNG.choice(state["ranks"])
        else:
            payload = {"action": action}
        await conns[turn].send(json.dumps(payload))

        for pid in tokens:
            await pump(pid)
        steps += 1

        state = latest[turn]
        if state["phase"] == "finished":
            winner = state["winner_id"]
            break
        turn = state["turn_player_id"]
        if turn is None:
            break

    res.check(winner is not None, f"一整局正常分出胜负（{steps} 步）")

    # --- 最关键：手牌是否越界泄露 ---
    leaked: list[str] = []
    for pid in tokens:
        blob = "\n".join(seen_blobs[pid])
        own = hands[pid]
        for other_pid in tokens:
            if other_pid == pid:
                continue
            # 只检查全程从未到过 pid 手上的牌——被抓包后牌会合法地转移
            never_mine = hands[other_pid] - own
            for cid in never_mine:
                if f'"{cid}"' in blob:
                    # 可能是摊牌时合法公开的，进一步确认是否出现在 revealed 之外
                    leaked.append(f"{pid} 看到了 {other_pid} 的 {cid}")
                    break
    # 摊牌公开是规则允许的，所以这里只报告，由下面的严格检查裁定
    strict_leak: list[str] = []
    leak_paths: dict[str, int] = {}
    for pid in tokens:
        for raw in seen_blobs[pid]:
            msg = json.loads(raw)
            if msg.get("type") != "state":
                continue
            st = msg["state"]
            mine = {c["id"] for c in st["you"]["hand"]}
            revealed = {c["id"] for c in ((st.get("last_resolution") or {}).get("revealed") or [])}
            # 报文里出现的每一张牌，要么是我的手牌，要么是本次合法摊开的
            for path, cid in _card_ids_in(st):
                if cid not in mine and cid not in revealed:
                    strict_leak.append(f"{pid}:{cid}@{path}")
                    # 把路径里的数组下标归一化，便于统计来源
                    key = "".join(c if not c.isdigit() else "#" for c in path)
                    leak_paths[key] = leak_paths.get(key, 0) + 1
    res.check(not strict_leak, f"报文中不含任何越界牌（越界 {len(strict_leak)} 处）")
    if strict_leak:
        print("    泄露来源路径统计:")
        for key, n in sorted(leak_paths.items(), key=lambda kv: -kv[1]):
            print(f"      {n:5d}  {key}")

    for sock in conns.values():
        await sock.close()


def _card_ids_in(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """递归找出状态里所有形如牌的对象，返回 (json 路径, 牌 id)。

    带上路径才能判断泄露是从哪个字段漏出去的，而不是只知道"漏了"。
    """
    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        if "id" in obj and "rank" in obj and "suit" in obj:
            found.append((path, obj["id"]))
        for k, v in obj.items():
            found.extend(_card_ids_in(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(_card_ids_in(v, f"{path}[{i}]"))
    return found


def main() -> int:
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    ws_base = f"ws://127.0.0.1:{port}"

    env = dict(os.environ)
    env["BLUFF_INTERNAL_SECRET"] = SECRET
    env["BLUFF_PUBLIC_BASE_URL"] = base

    print(f"启动自检服务 :{port} …", flush=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn",
         "src.chat.features.games.bluff-web.app:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd="/app", env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    res = Result()
    try:
        if not asyncio.run(_wait_healthy(base)):
            out = ""
            try:
                proc.terminate()
                out = (proc.stdout.read() or "")[-3000:] if proc.stdout else ""
            except Exception:
                pass
            print("服务未能启动，日志：\n" + out)
            return 1
        print("== 端到端自检 ==", flush=True)
        asyncio.run(run(base, ws_base, res))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if res.failures:
        print(f"自检未通过，失败 {len(res.failures)} 项：")
        for f in res.failures:
            print("  -", f)
        return 1
    print("自检全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
