# -*- coding: utf-8 -*-

import discord
import logging
import sqlite3
from typing import Optional, Mapping, Any

from .base_view import BaseTableView
from ..modals.edit_modals import EditWorkEventModal
from ..modals.search_modals import SearchWorkEventModal

log = logging.getLogger(__name__)


class WorkEventsView(BaseTableView):
    def __init__(
        self, author_id: int, message: discord.Message, parent_view: discord.ui.View
    ):
        super().__init__(author_id, message, parent_view)
        self.current_table = "work_events"

    def _get_db_connection(self):
        # 工作事件使用 chat.db
        db_path_to_use = self.chat_db_path
        try:
            conn = sqlite3.connect(db_path_to_use)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            log.error(f"连接到数据库 {db_path_to_use} 失败: {e}", exc_info=True)
            return None

    def _get_primary_key_column(self) -> str:
        return "event_id"

    def _get_entry_title(self, entry: Mapping[str, Any]) -> str:
        try:
            return entry["name"]
        except (KeyError, TypeError):
            return f"ID: #{entry['event_id']}"

    def _add_search_buttons(self):
        if not self.search_mode:
            self.search_button = discord.ui.Button(
                label="关键词搜索",
                emoji="🔍",
                style=discord.ButtonStyle.primary,
                row=1,
            )
            self.search_button.callback = self.search_work_event
            self.add_item(self.search_button)

    async def search_work_event(self, interaction: discord.Interaction):
        modal = SearchWorkEventModal(self)
        await interaction.response.send_modal(modal)

    async def edit_item(self, interaction: discord.Interaction):
        if not self.current_item_id:
            return

        current_item = self._get_item_by_id(self.current_item_id)
        if not current_item:
            await interaction.response.send_message("找不到该条目。", ephemeral=True)
            return

        modal = EditWorkEventModal(self, self.current_item_id, current_item)
        await interaction.response.send_modal(modal)

    def _get_item_by_id(self, item_id: str) -> Optional[sqlite3.Row]:
        conn = self._get_db_connection()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM work_events WHERE event_id = ?", (item_id,))
            return cursor.fetchone()
        finally:
            if conn:
                conn.close()

    async def _build_list_embed(self) -> discord.Embed:
        conn = self._get_db_connection()
        if not conn:
            return discord.Embed(title="错误", description="数据库连接失败。")

        try:
            cursor = conn.cursor()
            if self.search_mode:
                start_idx = self.current_page * self.items_per_page
                end_idx = start_idx + self.items_per_page
                page_items = self.current_list_items[start_idx:end_idx]
                embed = discord.Embed(
                    title=f"搜索工作事件 (关键词: '{self.search_keyword}')",
                    color=discord.Color.gold(),
                )
            else:
                cursor.execute("SELECT COUNT(*) FROM work_events")
                total_rows = cursor.fetchone()[0]
                self.total_pages = (
                    total_rows + self.items_per_page - 1
                ) // self.items_per_page
                offset = self.current_page * self.items_per_page
                cursor.execute(
                    "SELECT * FROM work_events ORDER BY event_id DESC LIMIT ? OFFSET ?",
                    (self.items_per_page, offset),
                )
                page_items = cursor.fetchall()
                self.current_list_items = page_items
                embed = discord.Embed(
                    title="浏览：工作事件", color=discord.Color.green()
                )

            if not page_items:
                embed.description = "没有找到任何工作事件。"
            else:
                pk = self._get_primary_key_column()
                list_text = "\n".join(
                    [
                        f"**`#{item[pk]}`** - {self._get_entry_title(dict(item))}"
                        for item in page_items
                    ]
                )
                embed.description = list_text

            total_display = (
                f"(共 {len(self.current_list_items)} 条结果)"
                if self.search_mode
                else ""
            )
            embed.set_footer(
                text=f"第 {self.current_page + 1} / {self.total_pages or 1} 页 {total_display}"
            )
            return embed
        finally:
            if conn:
                conn.close()

    async def _build_detail_embed(self) -> discord.Embed:
        if not self.current_item_id:
            return await self._build_list_embed()

        current_item = self._get_item_by_id(self.current_item_id)
        if not current_item:
            self.view_mode = "list"
            return await self._build_list_embed()

        title = self._get_entry_title(dict(current_item))
        embed = discord.Embed(
            title=f"查看详情: {title}",
            description=f"表: `work_events` | ID: `#{self.current_item_id}`",
            color=discord.Color.blue(),
        )

        for col in current_item.keys():
            value = current_item[col]
            if value is None or str(value).strip() == "":
                value = "_(空)_"

            embed.add_field(
                name=col.replace("_", " ").title(),
                value=self._truncate_field_value(value),
                inline=False,
            )
        return embed
