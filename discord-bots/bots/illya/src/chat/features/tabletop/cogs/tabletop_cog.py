"""Standalone game launches and durable public recruitment buttons."""
import asyncio
import logging
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import dotenv_values

log = logging.getLogger(__name__)
TITLES = {"mahjong": "四人麻将", "doudizhu": "斗地主"}


class BridgeError(Exception):
    pass


class TabletopButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tabletop:(?P<action>join|resume):(?P<game>mahjong|doudizhu):(?P<code>[A-Z2-9]{7})"):
    def __init__(self, action, game, code, disabled=False):
        super().__init__(discord.ui.Button(label="加入牌桌" if action == "join" else "回到牌桌",
            style=discord.ButtonStyle.success if action == "join" else discord.ButtonStyle.secondary,
            custom_id=f"tabletop:{action}:{game}:{code}", disabled=disabled))
        self.action, self.game, self.code = action, game, code

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], match["game"], match["code"])

    async def callback(self, interaction):
        cog = interaction.client.get_cog("TabletopCog")
        if cog is None:
            await interaction.response.send_message("牌桌正在更新，请稍后再试。", ephemeral=True)
            return
        await cog.launch(interaction, self.game, self.code, self.action == "resume")


def recruitment_card(data):
    game = data.get("game") or "mahjong"
    phase = data["phase"]
    players = data["players"]
    full = len(players) >= data["capacity"]
    label = {"waiting": "已满员 · 等待准备" if full else "公开招募中",
             "bidding": "对局进行中", "playing": "对局进行中",
             "finished": "本局结束", "closed": "牌桌已关闭"}[phase]
    title = f"{TITLES[game]} · {label}" if phase != "closed" else "牌桌已关闭"
    description = "点击下方按钮即可进入同一张牌桌，凑齐后全员准备，由房主开局。"
    if phase == "closed":
        description = "所有玩家已离开。可使用 /mahjong 或 /doudizhu 开新桌。"
    elif phase in ["playing", "bidding"]:
        description = "本局已开始，入座玩家可点击「回到牌桌」继续。"
    elif phase == "finished":
        description = "玩家可返回牌桌继续下一局，或离桌后开新桌。"
    embed = discord.Embed(title=title, description=description,
        color=0x26A879 if phase == "waiting" and not full else 0xBF9A55)
    if phase != "closed":
        names = "\n".join("✦ " + discord.utils.escape_markdown(p["name"]) + (" · 房主" if p["id"] == data["host"] else "") for p in players)
        embed.add_field(name=f"已入座 {len(players)}/{data['capacity']}", value=names or "暂无玩家", inline=False)
        embed.add_field(name="剩余空位", value=str(max(0, data["capacity"] - len(players))), inline=True)
        embed.add_field(name="房间码", value=data["code"], inline=True)
    embed.set_footer(text="伊莉雅牌桌 · 真人多人游戏 · 积分仅在本桌累计")
    view = discord.ui.View(timeout=None)
    view.add_item(TabletopButton("join", game, data["code"], phase != "waiting" or full))
    view.add_item(TabletopButton("resume", game, data["code"], phase == "closed"))
    return embed, view


class TabletopCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        values = dotenv_values(os.environ.get("TABLETOP_BOT_CONFIG", "/run/tabletop-config/bot.env"))
        self.url = values.get("TABLETOP_API_URL", "http://ody-tabletop:8010").rstrip("/")
        self.secret = values.get("TABLETOP_BOT_SECRET", "")
        self.session = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4))
        self.bot.add_dynamic_items(TabletopButton)
        self.publish.start()

    async def cog_unload(self):
        self.publish.cancel()
        self.bot.remove_dynamic_items(TabletopButton)
        if self.session:
            await self.session.close()

    async def bridge(self, method, path, body=None, timeout=4):
        if not self.secret:
            raise BridgeError("游戏服务尚未配置，请联系管理员。")
        async with self.session.request(method, self.url + path, json=body,
            headers={"X-Tabletop-Secret": self.secret}, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
            try:
                data = await response.json()
            except Exception:
                raise BridgeError("牌桌服务暂时不可用，请稍后再试。")
            if response.status >= 400:
                detail = data.get("detail")
                raise BridgeError(detail if isinstance(detail, str) else "牌桌操作失败，请稍后再试。")
            return data

    async def error(self, interaction, message):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(message, ephemeral=True)
            else:
                await interaction.followup.send(message, ephemeral=True)
        except discord.HTTPException as exc:
            log.warning("Tabletop response unavailable (Discord code %s)", exc.code)

    async def launch(self, interaction, game, code=None, resume=False):
        if interaction.guild_id is None or interaction.channel_id is None:
            await self.error(interaction, "请在服务器频道使用这款多人游戏，招募消息会发到当前频道。")
            return
        permissions = interaction.app_permissions
        can_send = permissions.send_messages_in_threads if isinstance(interaction.channel, discord.Thread) else permissions.send_messages
        if not permissions.view_channel or not can_send or not permissions.embed_links:
            await self.error(interaction, "请允许 bot 在当前频道查看频道、发送消息和嵌入链接，以发布招募卡。")
            return
        from src.chat.utils.database import chat_db_manager
        try:
            await self.bridge("POST", "/internal/launch", {"game": game, "user_id": str(interaction.user.id),
                "name": interaction.user.display_name[:48], "guild_id": str(interaction.guild_id),
                "channel_id": str(interaction.channel_id), "code": code, "resume": resume}, timeout=1.25)
            await asyncio.wait_for(chat_db_manager.set_global_setting(f"user_intent:{interaction.user.id}", game), timeout=.5)
            await interaction.response.launch_activity()
        except BridgeError as exc:
            await self.error(interaction, str(exc))
        except discord.HTTPException as exc:
            log.warning("Tabletop launch failed (Discord code %s)", exc.code)
            message = "当前客户端平台尚未启用活动支持，请联系管理员。" if exc.code == 50231 else "活动启动失败，请稍后重新执行命令。"
            await self.error(interaction, message)
        except (asyncio.TimeoutError, aiohttp.ClientError):
            await self.error(interaction, "牌桌服务响应较慢，请稍后重试；已创建的牌桌会自动重连。")
        except Exception:
            log.exception("Tabletop launch failed")
            await self.error(interaction, "牌桌启动失败，请稍后再试。")

    @tasks.loop(seconds=5)
    async def publish(self):
        try:
            changes = await self.bridge("GET", "/internal/recruitments")
            for data in changes:
                await self.publish_one(data)
        except (BridgeError, aiohttp.ClientError, asyncio.TimeoutError):
            log.warning("Tabletop recruitment bridge unavailable; retrying")
        except Exception:
            log.exception("Tabletop recruitment worker failed")

    @publish.before_loop
    async def wait_ready(self):
        await self.bot.wait_until_ready()

    async def publish_one(self, data):
        try:
            channel = self.bot.get_channel(int(data["channel_id"])) or await self.bot.fetch_channel(int(data["channel_id"]))
            if not getattr(channel, "guild", None) or str(channel.guild.id) != data["guild_id"]:
                raise BridgeError("招募频道不可用，请联系管理员。")
            embed, view = recruitment_card(data)
            if data["message_id"]:
                message = channel.get_partial_message(int(data["message_id"]))
                await message.edit(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            else:
                message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none(),
                    nonce=int.from_bytes(data["code"].encode(), "big") % (2 ** 63))
            await self.bridge("POST", f"/internal/recruitments/{data['code']}/receipt", {
                "message_id": str(message.id), "fingerprint": data["fingerprint"]})
        except (discord.Forbidden, discord.NotFound):
            await self.bridge("POST", f"/internal/recruitments/{data['code']}/failure", {"reason": "招募消息不可用，请检查频道权限或消息是否被删除。"})
        except BridgeError as exc:
            await self.bridge("POST", f"/internal/recruitments/{data['code']}/failure", {"reason": str(exc)[:80]})

    @app_commands.command(name="mahjong", description="独立四人麻将牌桌，在当前频道公开招募玩家")
    @app_commands.guild_only()
    async def mahjong(self, interaction: discord.Interaction):
        await self.launch(interaction, "mahjong")

    @app_commands.command(name="doudizhu", description="独立三人斗地主牌桌，在当前频道公开招募玩家")
    @app_commands.guild_only()
    async def doudizhu(self, interaction: discord.Interaction):
        await self.launch(interaction, "doudizhu")


async def setup(bot):
    await bot.add_cog(TabletopCog(bot))
