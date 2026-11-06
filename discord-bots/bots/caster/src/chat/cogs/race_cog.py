"""racegame Discord cog：/race 报名制卡丁车比赛。

流程：/race 发报名 embed（带按钮）→ 玩家点"报名/退出"→ 发起者点"开始比赛"
→ 生成房间链接并 @所有报名者 → 后台轮询成绩 → 完赛后在频道发榜。

独立模块：仅依赖 discord.py 2.x 与 aiohttp，不 import 宿主项目任何模块。
环境变量：
  RACEGAME_API_BASE    游戏服务器 API 地址（默认 http://racegame_server:8080）
  RACEGAME_PUBLIC_URL  游戏对外地址（默认 https://race.43-108-100-78.sslip.io）
"""
import asyncio
import logging
import os
import secrets
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands

log = logging.getLogger(__name__)

RACEGAME_API_BASE = os.environ.get("RACEGAME_API_BASE", "http://racegame_server:8080").rstrip("/")
RACEGAME_PUBLIC_URL = os.environ.get(
    "RACEGAME_PUBLIC_URL", "https://race.43-108-100-78.sslip.io"
).rstrip("/")

POLL_INTERVAL_S = 5          # 轮询间隔
POLL_TIMEOUT_S = 5           # 单次请求超时
NEVER_SEEN_GIVE_UP_S = 600   # 从未见到房间（一直 404）时 10 分钟放弃
MAX_TRACK_S = 1800           # 全程最长 30 分钟
SIGNUP_TIMEOUT_S = 600       # 报名 10 分钟未开始自动过期
MAX_PLAYERS = 6
FOOTER_NOTE = "游戏无法验证 Discord 身份，链接理论上任何人可进"
TRACK_NAMES = {"sunny": "阳光环道", "canyon": "峡谷回旋", "beach": "海滨发卡"}


def fmt_ms(ms):
    """毫秒 -> mm:ss.cs"""
    if not ms or ms <= 0:
        return "—"
    total_cs = int(round(ms / 10))
    m, rem = divmod(total_cs, 6000)
    s, cs = divmod(rem, 100)
    return f"{m:02d}:{s:02d}.{cs:02d}"


class RaceSignupView(discord.ui.View):
    """报名 View：报名/退出、开始（仅发起者）、取消（仅发起者）。不持久化，重启后旧按钮失效。"""

    def __init__(self, cog, owner, track=""):
        super().__init__(timeout=SIGNUP_TIMEOUT_S)
        self.cog = cog
        self.owner_id = owner.id
        self.track = track if track in TRACK_NAMES else ""  # "" = 随机
        self.players = []          # 报名者 user id（按报名顺序）
        self.display_names = {}    # user id -> display_name
        self.message = None
        self.closed = False
        # 发起者自动报名
        self.players.append(owner.id)
        self.display_names[owner.id] = owner.display_name

    def _disable_all(self):
        for item in self.children:
            item.disabled = True

    def signup_embed(self):
        names = [self.display_names.get(uid, str(uid)) for uid in self.players]
        roster = "\n".join(f"{i}. {discord.utils.escape_markdown(n)}" for i, n in enumerate(names, 1))
        track_label = TRACK_NAMES.get(self.track, "随机赛道")
        embed = discord.Embed(
            title="🏁 卡丁车竞速 · 报名中",
            description=(
                "点击 **✅ 报名 / ↩️ 退出** 加入或退出，"
                "人满或由发起者点击 **🏁 开始比赛** 后统一开赛。\n"
                "玩法：2-6 人，跑 3 圈，漂移集气 + 氮气 + 道具。"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name=f"报名名单（{len(self.players)}/{MAX_PLAYERS}）",
            value=roster or "虚位以待",
            inline=False,
        )
        embed.add_field(name="地图", value=track_label, inline=False)
        embed.set_footer(text=f"10 分钟未开始自动过期 ｜ {FOOTER_NOTE}")
        return embed

    @discord.ui.button(label="✅ 报名 / ↩️ 退出", style=discord.ButtonStyle.success)
    async def toggle_signup(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            uid = interaction.user.id
            if uid in self.players:
                self.players.remove(uid)
            else:
                if len(self.players) >= MAX_PLAYERS:
                    await interaction.response.send_message("报名已满（6 人）", ephemeral=True)
                    return
                self.players.append(uid)
                self.display_names[uid] = interaction.user.display_name
            await interaction.response.edit_message(embed=self.signup_embed())
        except Exception:
            log.exception("toggle_signup failed")
            if not interaction.response.is_done():
                await interaction.response.send_message("操作失败，请重试", ephemeral=True)

    @discord.ui.button(label="🏁 开始比赛", style=discord.ButtonStyle.primary)
    async def start_race(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("只有发起者可以开始比赛", ephemeral=True)
                return
            if len(self.players) < 2:
                await interaction.response.send_message("至少 2 人才能开赛", ephemeral=True)
                return
            self.closed = True
            self._disable_all()
            code = f"d{interaction.channel_id:x}-{secrets.token_hex(3)}"
            link = f"{RACEGAME_PUBLIC_URL}/?room={code}"
            if self.track:
                link += f"&track={self.track}"
            track_label = TRACK_NAMES.get(self.track, "随机赛道")
            embed = discord.Embed(
                title="🏁 比赛已开始！",
                description=(
                    f"**加入链接**：{link}\n**房间代码**：`{code}`\n**地图**：{track_label}\n\n"
                    "进游戏输入昵称后点「开始匹配」即可同场竞技。完赛后我会在这里公布成绩。"
                ),
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text=FOOTER_NOTE)
            await interaction.response.edit_message(embed=embed, view=self)
            mentions = " ".join(f"<@{uid}>" for uid in self.players)
            await interaction.followup.send(f"🏁 开赛啦！{mentions}\n加入链接：{link}")
            self.stop()
            if interaction.channel is not None:
                self.cog.start_tracker(code, interaction.channel)
            log.info("race room %s started by %s with %d players", code, interaction.user, len(self.players))
        except Exception:
            log.exception("start_race failed")
            if not interaction.response.is_done():
                await interaction.response.send_message("开赛失败，请重试", ephemeral=True)

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.danger)
    async def cancel_race(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("只有发起者可以取消", ephemeral=True)
                return
            self.closed = True
            self._disable_all()
            embed = discord.Embed(
                title="🏁 卡丁车竞速 · 已取消",
                description="发起者取消了这场比赛。",
                color=discord.Color.dark_grey(),
                timestamp=datetime.now(timezone.utc),
            )
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
            log.info("race signup cancelled by %s", interaction.user)
        except Exception:
            log.exception("cancel_race failed")
            if not interaction.response.is_done():
                await interaction.response.send_message("操作失败，请重试", ephemeral=True)

    async def on_timeout(self):
        if self.closed:
            return
        self.closed = True
        self._disable_all()
        if self.message is not None:
            embed = discord.Embed(
                title="🏁 卡丁车竞速 · 已过期",
                description="报名超过 10 分钟未开始，已自动过期。可重新 /race 发起。",
                color=discord.Color.dark_grey(),
                timestamp=datetime.now(timezone.utc),
            )
            try:
                await self.message.edit(embed=embed, view=self)
            except Exception:
                log.exception("failed to edit expired signup message")


class RaceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._tasks = set()

    def cog_unload(self):
        for task in self._tasks:
            task.cancel()

    @discord.app_commands.command(name="race", description="发起一场卡丁车竞速比赛")
    @discord.app_commands.rename(track="地图")
    @discord.app_commands.describe(track="选择赛道（默认随机）")
    @discord.app_commands.choices(track=[
        discord.app_commands.Choice(name="随机", value=""),
        discord.app_commands.Choice(name="阳光环道", value="sunny"),
        discord.app_commands.Choice(name="峡谷回旋", value="canyon"),
        discord.app_commands.Choice(name="海滨发卡", value="beach"),
    ])
    async def race(self, interaction: discord.Interaction, track: str = ""):
        try:
            view = RaceSignupView(self, interaction.user, track)
            await interaction.response.send_message(embed=view.signup_embed(), view=view)
            try:
                view.message = await interaction.original_response()
            except Exception:
                log.exception("failed to capture signup message reference")
        except Exception:
            log.exception("race command failed")

    def start_tracker(self, code, channel):
        task = asyncio.create_task(self._track_room(code, channel))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _track_room(self, code, channel):
        """后台轮询房间状态，完赛后在频道公布成绩。绝不抛出未处理异常。"""
        url = f"{RACEGAME_API_BASE}/api/room/{code}"
        start = datetime.now(timezone.utc)
        seen_room = False
        try:
            timeout = aiohttp.ClientTimeout(total=POLL_TIMEOUT_S)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                while True:
                    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
                    if elapsed > MAX_TRACK_S:
                        log.info("room %s: tracking timed out after 30min, giving up", code)
                        return
                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                seen_room = True
                                if data.get("status") == "finished" and data.get("results"):
                                    await self._post_results(channel, code, data["results"])
                                    return
                            elif resp.status == 404:
                                if not seen_room and elapsed > NEVER_SEEN_GIVE_UP_S:
                                    log.info(
                                        "room %s: never appeared (404) after 10min, giving up",
                                        code,
                                    )
                                    return
                            else:
                                log.warning("room %s: unexpected status %s", code, resp.status)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        log.exception("room %s: poll error", code)
                    await asyncio.sleep(POLL_INTERVAL_S)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("room %s: tracker crashed", code)

    async def _post_results(self, channel, code, results):
        lines = []
        for i, row in enumerate(results, 1):
            name = discord.utils.escape_markdown(str(row.get("name", "?")))
            best = fmt_ms(row.get("bestLapMs"))
            if row.get("dnf"):
                lines.append(f"`DNF` **{name}** — 未完赛（最快圈 {best}）")
            else:
                lines.append(
                    f"`P{i}` **{name}** — 总时间 {fmt_ms(row.get('totalMs'))} ｜ 最快圈 {best}"
                )
        embed = discord.Embed(
            title="🏁 比赛成绩",
            description="\n".join(lines) or "暂无成绩",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"房间 {code}")
        try:
            await channel.send(embed=embed)
        except Exception:
            log.exception("room %s: failed to post results", code)


async def setup(bot):
    await bot.add_cog(RaceCog(bot))
