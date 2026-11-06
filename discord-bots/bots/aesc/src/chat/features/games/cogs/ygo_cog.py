# -*- coding: utf-8 -*-
"""Discord entrance for the independent Aesc YGO service.

No bot token is read here, no commands are synced, and no database is shared
with existing games. Results edit the original challenge message idempotently.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import discord
import httpx
from discord import app_commands
from discord.ext import commands, tasks

log = logging.getLogger(__name__)
LIVE = {"waiting", "queued", "preparing", "playing"}
STATES = {"waiting": "等待应战", "queued": "排队中", "preparing": "等待入场", "playing": "对战中", "finished": "对局结束", "cancelled": "已取消", "expired": "已过期", "interrupted": "对局中断"}


class GatewayError(Exception):
    pass


class Gateway:
    def __init__(self, url: str, secret: str, client: httpx.AsyncClient | None = None):
        self.url = url.rstrip("/")
        self.secret = secret
        self.client = client or httpx.AsyncClient(timeout=8.0)

    async def request(self, method: str, path: str, data: dict | None = None) -> Any:
        if not self.secret:
            raise GatewayError("游戏王服务尚未配置")
        try:
            response = await self.client.request(method, self.url + path, json=data, headers={"X-Ygo-Secret": self.secret})
            if response.is_error:
                detail = response.json().get("error", "游戏服务暂不可用")
                raise GatewayError(str(detail)[:200])
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GatewayError("游戏服务暂不可用，请稍后重试；已接受的约战不会重复创建") from exc

    async def close(self):
        await self.client.aclose()


def render_room(room: dict) -> discord.Embed:
    state = room["state"]
    title = f"游戏王 · 双人单局 · {STATES.get(state, state)}"
    lines = ["现行 OCG 规则 · 导入 YDK 卡组 · 网页自动裁定"]
    if state == "waiting":
        lines.append(f"等待 <@{room['targetId']}> 接受挑战。" if room.get("targetId") else "点击「加入」应战，先到先得。")
    elif state == "queued":
        lines.append("双方已锁定，空出房间后会自动安排入场。")
    elif state == "preparing":
        lines.append("点击「进入我的牌桌」，使用本人 Discord 账号登录并导入卡组。")
    elif state == "playing":
        lines.append("短时断线可重新进入原牌桌；正在对战时不能更换卡组。")
    elif state == "finished":
        lines.append(f"胜者：<@{room['winnerId']}>" if room.get("winnerId") else "本局为平局。")
    if room.get("reason"):
        lines.append(discord.utils.escape_markdown(room["reason"]))
    if state in {"waiting", "queued", "preparing"}:
        lines.append(f"等待截止：<t:{room['expiresAt'] // 1000}:R>")
    embed = discord.Embed(title=title, description="\n".join(lines), color=0x617FA6 if state in LIVE else 0x77A883)
    players = "\n".join(f"<@{p['id']}> · {'卡组已导入' if p.get('hasDeck') else '尚未导入卡组'}" for p in room["players"])
    embed.add_field(name="参与者", value=players or "暂无", inline=False)
    embed.set_footer(text="游戏王约战 · 不涉及押注")
    return embed


class ActionButton(discord.ui.Button):
    def __init__(self, room_id: str, action: str, label: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, custom_id=f"aesc:ygo:{room_id}:{action}")
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await self.view.cog.handle_action(interaction, self.view.room_id, self.action)


class RoomView(discord.ui.View):
    def __init__(self, cog: "YgoCog", room: dict):
        super().__init__(timeout=None)
        self.cog, self.room_id = cog, room["id"]
        state = room["state"]
        if state == "waiting":
            self.add_item(ActionButton(room["id"], "join", "接受挑战" if room.get("targetId") else "加入", discord.ButtonStyle.primary))
            if room.get("targetId"):
                self.add_item(ActionButton(room["id"], "reject", "拒绝", discord.ButtonStyle.secondary))
        if state in {"queued", "preparing", "playing"}:
            self.add_item(ActionButton(room["id"], "open", "进入我的牌桌", discord.ButtonStyle.success))
        elif state in {"finished", "interrupted"}:
            # A URL button survives bot restarts without retaining an unbounded
            # collection of terminal Views. The website still verifies identity.
            self.add_item(discord.ui.Button(label="查看对局", url=f"{cog.public_origin}/r/{room['id']}"))
        if state in {"waiting", "queued", "preparing"}:
            self.add_item(ActionButton(room["id"], "cancel", "取消约战", discord.ButtonStyle.secondary))


class YgoCog(commands.Cog):
    ygo = app_commands.Group(name="ygo", description="游戏王双人网页对战", guild_only=True)

    def __init__(self, bot: commands.Bot, gateway: Gateway | None = None, public_origin: str | None = None):
        self.bot = bot
        self.gateway = gateway or Gateway(os.getenv("YGO_SERVICE_URL", "http://aesc_ygo_gateway:15174"), os.getenv("YGO_INTERNAL_SECRET", ""))
        self.public_origin = (public_origin or os.getenv("YGO_PUBLIC_ORIGIN", "")).rstrip("/")
        self.views: dict[str, RoomView] = {}
        self.retries: dict[str, tuple[int, float]] = {}

    async def cog_load(self):
        if self.gateway.secret and self.public_origin:
            self.sync_rooms.start()
        else:
            log.info("YGO 未配置，命令保留但不会连接外部服务")

    async def cog_unload(self):
        self.sync_rooms.cancel()
        for view in self.views.values():
            view.stop()
        await self.gateway.close()

    def remember_view(self, room: dict) -> RoomView:
        old = self.views.pop(room["id"], None)
        if old:
            old.stop()
        view = RoomView(self, room)
        if any(getattr(button, "custom_id", None) for button in view.children):
            self.views[room["id"]] = view
            self.bot.add_view(view, message_id=int(room["messageId"]) if room.get("messageId") else None)
        return view

    async def create_challenge(self, interaction: discord.Interaction, target: discord.Member | None = None):
        if not interaction.guild_id or not interaction.channel_id:
            await interaction.response.send_message("请在服务器频道中发起约战。", ephemeral=True)
            return
        if target and (target.bot or target.id == interaction.user.id):
            await interaction.response.send_message("请选择另一位真实成员。", ephemeral=True)
            return
        if not self.public_origin:
            await interaction.response.send_message("游戏王网页入口尚未配置。", ephemeral=True)
            return
        await interaction.response.defer()
        published = False
        try:
            room = await self.gateway.request("POST", "/internal/rooms", {
                "requestId": str(interaction.id), "guildId": str(interaction.guild_id), "channelId": str(interaction.channel_id),
                "creator": {"id": str(interaction.user.id), "name": interaction.user.display_name},
                "target": {"id": str(target.id), "name": target.display_name} if target else None,
            })
            view = self.remember_view(room)
            mentions = discord.AllowedMentions(everyone=False, roles=False, users=[target] if target else False, replied_user=False)
            message = await interaction.edit_original_response(content=target.mention if target else None, embed=render_room(room), view=view, allowed_mentions=mentions)
            published = True
            room = await self.gateway.request("POST", f"/internal/rooms/{room['id']}/bind", {"guildId": str(interaction.guild_id), "channelId": str(interaction.channel_id), "messageId": str(message.id)})
            self.remember_view(room)
        except GatewayError as exc:
            if published:
                await interaction.followup.send(str(exc), ephemeral=True)
            else:
                await interaction.edit_original_response(content=str(exc), embed=None, view=None, allowed_mentions=discord.AllowedMentions.none())

    @ygo.command(name="challenge", description="向指定成员发起游戏王双人单局挑战")
    @app_commands.describe(target="被挑战的成员")
    async def challenge(self, interaction: discord.Interaction, target: discord.Member):
        await self.create_challenge(interaction, target)

    @ygo.command(name="recruit", description="公开招募一位游戏王对手")
    async def recruit(self, interaction: discord.Interaction):
        await self.create_challenge(interaction)

    async def handle_action(self, interaction: discord.Interaction, room_id: str, action: str):
        await interaction.response.defer(ephemeral=True)
        try:
            room = await self.gateway.request("GET", f"/internal/rooms/{room_id}")
            if str(interaction.guild_id) != room["guildId"] or str(interaction.channel_id) != room["channelId"]:
                raise GatewayError("请在原约战频道操作。")
            if room.get("messageId") and str(interaction.message.id) != room["messageId"]:
                raise GatewayError("请使用原约战消息的按钮。")
            if not room.get("messageId"):
                room = await self.gateway.request("POST", f"/internal/rooms/{room_id}/bind", {"guildId": str(interaction.guild_id), "channelId": str(interaction.channel_id), "messageId": str(interaction.message.id)})
            if action == "open":
                if not any(p["id"] == str(interaction.user.id) for p in room["players"]):
                    raise GatewayError("你不是这一局的参与者。")
                await interaction.followup.send(f"你的牌桌：{self.public_origin}/r/{room_id}\n请使用本人 Discord 账号登录。", ephemeral=True)
                return
            payload = {"guildId": str(interaction.guild_id), "actorId": str(interaction.user.id)}
            if action == "join":
                if interaction.user.bot:
                    raise GatewayError("机器人不能加入牌局。")
                payload["actor"] = {"id": str(interaction.user.id), "name": interaction.user.display_name}
            if action not in {"join", "cancel", "reject"}:
                raise GatewayError("未知操作。")
            room = await self.gateway.request("POST", f"/internal/rooms/{room_id}/{action}", payload)
            await interaction.message.edit(content=None, embed=render_room(room), view=self.remember_view(room), allowed_mentions=discord.AllowedMentions.none())
            await interaction.followup.send("已更新约战。" if room["state"] != "queued" else "对手已确定，正在排队；空出房间会更新此消息。", ephemeral=True)
        except GatewayError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

    async def restore_views(self):
        for room in await self.gateway.request("GET", "/internal/rooms"):
            self.remember_view(room)

    async def flush_notifications(self):
        rooms = await self.gateway.request("GET", "/internal/notifications")
        for room in rooms:
            attempts, retry_at = self.retries.get(room["id"], (0, 0))
            if time.monotonic() < retry_at:
                continue
            try:
                channel = self.bot.get_channel(int(room["channelId"]))
                if channel is None:
                    channel = await self.bot.fetch_channel(int(room["channelId"]))
                message = channel.get_partial_message(int(room["messageId"]))
                # Editing the same original message is idempotent even if an ACK is lost.
                await message.edit(content=None, embed=render_room(room), view=self.remember_view(room), allowed_mentions=discord.AllowedMentions.none())
                await self.gateway.request("POST", f"/internal/rooms/{room['id']}/ack", {"revision": room["revision"]})
                self.retries.pop(room["id"], None)
            except (discord.HTTPException, GatewayError, AttributeError) as exc:
                attempts += 1
                self.retries[room["id"]] = (attempts, time.monotonic() + min(300, 2 ** min(attempts, 8)))
                log.warning("YGO 原消息更新待重试：room=%s error=%s", room["id"], type(exc).__name__)

    @tasks.loop(seconds=4)
    async def sync_rooms(self):
        try:
            await self.flush_notifications()
        except GatewayError:
            log.warning("YGO 网关暂不可用，保留未通知结果")

    @sync_rooms.before_loop
    async def before_sync_rooms(self):
        await self.bot.wait_until_ready()
        # Restore persistent button handlers after a bot restart. Retry instead
        # of permanently killing the notification task on a startup outage.
        import asyncio
        while True:
            try:
                await self.restore_views()
                return
            except GatewayError:
                await asyncio.sleep(5)


async def setup(bot: commands.Bot):
    await bot.add_cog(YgoCog(bot))
