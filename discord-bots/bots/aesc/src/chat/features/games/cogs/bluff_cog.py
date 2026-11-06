# -*- coding: utf-8 -*-
"""吹牌（Bluff / Cheat）三人牌局的 Discord 入口。

流程：
    /bluff  ->  发一条带「加入」按钮的公开消息（发起人自动占一个座）
            ->  凑满 3 人后调用 bluff 服务开房
            ->  每人点「打开我的牌桌」拿到只属于自己的一次性链接（ephemeral）
                同时尽力私信一份；私信失败不影响进场。

本 Cog 不碰数据库、不涉及押注，只负责撮合和发链接。
"""

from __future__ import annotations

import logging
import os

import discord
import httpx
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

PLAYERS_REQUIRED = 3
LOBBY_TIMEOUT = 300          # 组队等待 5 分钟
TABLE_VIEW_TIMEOUT = 3600    # 开局后按钮 1 小时内可用
HTTP_TIMEOUT = 10.0

SERVICE_URL = os.getenv("BLUFF_SERVICE_URL", "http://bluff:8005").rstrip("/")


def _internal_secret() -> str:
    return os.getenv("BLUFF_INTERNAL_SECRET", "")


async def _create_room(players: list[discord.abc.User]) -> dict:
    """调用 bluff 服务开房，返回 {room_id, players:[{user_id,name,url}]}。"""
    secret = _internal_secret()
    if not secret:
        raise RuntimeError("BLUFF_INTERNAL_SECRET 未配置")

    payload = {
        "players": [
            {"id": str(u.id), "name": (u.display_name or u.name)[:24]} for u in players
        ]
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{SERVICE_URL}/internal/rooms",
            json=payload,
            headers={"X-Internal-Secret": secret},
        )
        resp.raise_for_status()
        return resp.json()


def _lobby_embed(players: list[discord.abc.User], closed: bool = False) -> discord.Embed:
    names = "\n".join(f"{i + 1}. {u.mention}" for i, u in enumerate(players)) or "（还没人）"
    empty = PLAYERS_REQUIRED - len(players)
    embed = discord.Embed(
        title="吹牌 · 三人局",
        description=(
            "盖着出牌，自己报点数——可以真，也可以假。\n"
            "下家只能**跟同一个点数**、**质疑**，或者**过**。\n"
            "抓到撒谎，牌全回说谎的人手上；质疑错了，牌归你。\n"
            "大小王是百搭，摊开算合法。先出完手牌的人赢。"
        ),
        color=0xE3B869,
    )
    embed.add_field(name=f"座位（{len(players)}/{PLAYERS_REQUIRED}）", value=names, inline=False)
    if closed:
        embed.set_footer(text="人已满，点下面的按钮进桌")
    else:
        embed.set_footer(text=f"还差 {empty} 人 · 5 分钟内有效")
    return embed


class TableView(discord.ui.View):
    """开局后的取链接按钮：每人只能拿到自己那一份。"""

    def __init__(self, room: dict):
        super().__init__(timeout=TABLE_VIEW_TIMEOUT)
        self.room_id: str = room["room_id"]
        self.links: dict[str, str] = {p["user_id"]: p["url"] for p in room["players"]}

    @discord.ui.button(label="打开我的牌桌", style=discord.ButtonStyle.success, emoji="🎴")
    async def open_table(self, interaction: discord.Interaction, _: discord.ui.Button):
        url = self.links.get(str(interaction.user.id))
        if not url:
            await interaction.response.send_message(
                "你不在这一局里。等下一局开的时候点「加入」就行。", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"这是**只属于你**的牌桌链接，别转发给别人——拿到链接就能看到你的手牌：\n{url}",
            ephemeral=True,
        )


class LobbyView(discord.ui.View):
    """组队面板。按钮可反悔：已加入的人再点一次就退出。"""

    def __init__(self, initiator: discord.abc.User):
        super().__init__(timeout=LOBBY_TIMEOUT)
        self.players: list[discord.abc.User] = [initiator]
        self.message: discord.Message | None = None
        self.started = False

    async def on_timeout(self) -> None:
        if self.started or self.message is None:
            return
        for item in self.children:
            item.disabled = True
        embed = _lobby_embed(self.players)
        embed.set_footer(text="组队超时，这一局取消了")
        embed.color = 0x6B7B75
        try:
            await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="加入", style=discord.ButtonStyle.primary, emoji="🃏")
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.started:
            await interaction.response.send_message("这一局已经开始了。", ephemeral=True)
            return

        user = interaction.user
        existing = next((u for u in self.players if u.id == user.id), None)
        if existing is not None:
            self.players.remove(existing)
            await interaction.response.edit_message(embed=_lobby_embed(self.players), view=self)
            return

        self.players.append(user)
        if len(self.players) < PLAYERS_REQUIRED:
            await interaction.response.edit_message(embed=_lobby_embed(self.players), view=self)
            return

        # --- 人满，开房 ---
        self.started = True
        await interaction.response.defer()
        try:
            room = await _create_room(self.players)
        except Exception as exc:
            self.started = False
            self.players.remove(user)
            log.exception("吹牌开房失败")
            detail = "游戏服务没有响应" if isinstance(exc, httpx.HTTPError) else str(exc)
            await interaction.followup.send(
                f"开局失败：{detail}。座位已退回，可以再试一次。", ephemeral=True
            )
            try:
                await interaction.message.edit(embed=_lobby_embed(self.players), view=self)
            except discord.HTTPException:
                pass
            return

        table = TableView(room)
        embed = _lobby_embed(self.players, closed=True)
        embed.color = 0x5FBF8F
        try:
            await interaction.message.edit(embed=embed, view=table)
        except discord.HTTPException:
            log.warning("吹牌：更新组队消息失败，房间 %s", room["room_id"])

        # 私信只是锦上添花，失败不拦路——按钮那条路始终可用。
        for entry in room["players"]:
            member = next((u for u in self.players if str(u.id) == entry["user_id"]), None)
            if member is None:
                continue
            try:
                await member.send(
                    f"吹牌开局了，这是你的专属牌桌链接（别转发）：\n{entry['url']}"
                )
            except (discord.Forbidden, discord.HTTPException):
                log.info("吹牌：无法私信 %s，该玩家可用按钮取链接", member.id)

        self.stop()


class BluffCog(commands.Cog):
    """吹牌：三人诈唬牌局。"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="bluff", description="开一局吹牌（三人诈唬牌局）")
    @app_commands.guild_only()
    async def bluff(self, interaction: discord.Interaction):
        if not _internal_secret():
            log.error("BLUFF_INTERNAL_SECRET 未配置，/bluff 无法开局")
            await interaction.response.send_message(
                "吹牌还没配置好，管理员需要设置 BLUFF_INTERNAL_SECRET。", ephemeral=True
            )
            return

        view = LobbyView(interaction.user)
        await interaction.response.send_message(embed=_lobby_embed(view.players), view=view)
        try:
            view.message = await interaction.original_response()
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(BluffCog(bot))
