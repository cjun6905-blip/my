# -*- coding: utf-8 -*-
"""吹牌（Bluff / Cheat）核心状态机。

纯逻辑：不依赖 FastAPI、数据库、网络或 asyncio，可以单独跑测试。

规则以驾驶员确认的三条裁决为准：
  1. 大小王是百搭，摊开时算合法出牌，不构成撒谎；
  2. 只能质疑「最后出牌的那个人」；
  3. 质疑结算后，赢的一方拿到下一轮的出牌权。

其余细则（本文件顶部常量可调）：
  - 三人局，一副 54 张（含双王）平均分，每人 18 张；
  - 每次出 1~3 张，盖着出；张数是公开的，只有点数可以撒谎；
  - 领出方指定本轮点数，后续只能跟同一点数；
  - 其余两人都过牌 -> 牌堆弃掉，最后出牌的人继续领出；
  - 先出完手牌、且该轮结算后手牌仍为 0 的人获胜。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# --- 可调参数 ---------------------------------------------------------------
PLAYERS_REQUIRED = 3
# None = 不限张数，想出多少张都行（最多就是手上全部）。
# 设成整数则是每次出牌的张数上限。
MAX_CARDS_PER_PLAY = None
RANKS: tuple[str, ...] = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
SUITS: tuple[str, ...] = ("S", "H", "D", "C")
JOKER_RANK = "JOKER"
LOG_LIMIT = 40

_rng = random.SystemRandom()


class Phase(str, Enum):
    WAITING = "waiting"      # 人没齐
    LEADING = "leading"      # 当前玩家必须领出并指定点数
    FOLLOWING = "following"  # 本轮点数已定，可跟牌 / 质疑 / 过牌
    FINISHED = "finished"


class RuleError(Exception):
    """非法操作。message 直接给玩家看，所以写中文。"""


@dataclass(frozen=True)
class Card:
    id: str
    rank: str
    suit: str

    @property
    def is_joker(self) -> bool:
        return self.rank == JOKER_RANK

    def matches(self, declared_rank: str) -> bool:
        """王是百搭，永远算合法。"""
        return self.is_joker or self.rank == declared_rank

    def to_dict(self) -> dict:
        return {"id": self.id, "rank": self.rank, "suit": self.suit}


def build_deck() -> list[Card]:
    deck = [Card(f"{suit}{rank}", rank, suit) for rank in RANKS for suit in SUITS]
    deck.append(Card("JOKER_R", JOKER_RANK, "R"))
    deck.append(Card("JOKER_B", JOKER_RANK, "B"))
    return deck


@dataclass
class Play:
    """一次出牌。declared_rank 是本轮点数，张数公开、点数可能是假的。"""

    player_id: str
    cards: list[Card]
    declared_rank: str

    @property
    def count(self) -> int:
        return len(self.cards)

    @property
    def is_honest(self) -> bool:
        return all(card.matches(self.declared_rank) for card in self.cards)


@dataclass
class Player:
    id: str
    name: str
    seat: int
    hand: list[Card] = field(default_factory=list)
    connected: bool = False

    @property
    def hand_count(self) -> int:
        return len(self.hand)


class Game:
    """一局三人吹牌。

    所有状态变更都走 lead / follow / challenge / passing 四个入口，
    每个入口都先校验合法性再改状态，失败时抛 RuleError 且不留副作用。
    """

    def __init__(self, room_id: str, seats: list[tuple[str, str]]):
        if len(seats) != PLAYERS_REQUIRED:
            raise RuleError(f"需要 {PLAYERS_REQUIRED} 名玩家，收到 {len(seats)} 名")

        self.room_id = room_id
        self.players: list[Player] = [
            Player(id=pid, name=name, seat=i) for i, (pid, name) in enumerate(seats)
        ]
        self.phase: Phase = Phase.LEADING
        self.turn: int = 0
        self.current_rank: Optional[str] = None
        self.pile: list[Play] = []
        self.passes: set[str] = set()
        self.discarded_total: int = 0
        self.winner_id: Optional[str] = None
        self.round_no: int = 1
        self.last_resolution: Optional[dict] = None
        self.log: list[dict] = []
        self.version: int = 0

        self._deal()
        self._append_log("game_start", text=f"开局，{self.current_player.name} 先出牌")

    # --- 初始化 -------------------------------------------------------------

    def _deal(self) -> None:
        deck = build_deck()
        _rng.shuffle(deck)
        per_player = len(deck) // len(self.players)
        for i, player in enumerate(self.players):
            player.hand = sorted(
                deck[i * per_player : (i + 1) * per_player], key=self._sort_key
            )
        self.turn = _rng.randrange(len(self.players))

    @staticmethod
    def _sort_key(card: Card) -> tuple[int, str]:
        if card.is_joker:
            return (len(RANKS), card.suit)
        return (RANKS.index(card.rank), card.suit)

    # --- 便捷访问 -----------------------------------------------------------

    @property
    def current_player(self) -> Player:
        return self.players[self.turn]

    def player(self, player_id: str) -> Player:
        for p in self.players:
            if p.id == player_id:
                return p
        raise RuleError("你不在这一局里")

    @property
    def last_play(self) -> Optional[Play]:
        return self.pile[-1] if self.pile else None

    @property
    def pile_size(self) -> int:
        return sum(play.count for play in self.pile)

    @staticmethod
    def _is_card_like(value: object) -> bool:
        if isinstance(value, dict):
            return {"id", "rank", "suit"} <= set(value.keys())
        if isinstance(value, list):
            return any(Game._is_card_like(v) for v in value)
        return False

    def _append_log(self, kind: str, **payload) -> None:
        """日志会原样广播给所有人，所以这里强制剔除任何牌面数据。

        摊开的牌只在当次 last_resolution 里出现一次，不留存进历史记录——
        否则「状态里只能有自己的手牌 + 当次摊牌」这条不变量就破了。
        """
        clean = {k: v for k, v in payload.items() if not self._is_card_like(v)}
        self.log.append({"kind": kind, **clean})
        del self.log[:-LOG_LIMIT]

    def _advance_turn(self) -> None:
        self.turn = (self.turn + 1) % len(self.players)

    def _require_turn(self, player_id: str) -> Player:
        if self.phase is Phase.FINISHED:
            raise RuleError("这一局已经结束了")
        player = self.player(player_id)
        if player.id != self.current_player.id:
            raise RuleError("还没轮到你")
        return player

    def _take_cards(self, player: Player, card_ids: list[str]) -> list[Card]:
        """按 id 从手牌取出，校验重复与归属。不改手牌，返回取出的牌。"""
        if not card_ids:
            raise RuleError("至少要出一张牌")
        if MAX_CARDS_PER_PLAY is not None and len(card_ids) > MAX_CARDS_PER_PLAY:
            raise RuleError(f"一次最多出 {MAX_CARDS_PER_PLAY} 张")
        if len(set(card_ids)) != len(card_ids):
            raise RuleError("同一张牌不能出两次")

        by_id = {card.id: card for card in player.hand}
        picked: list[Card] = []
        for cid in card_ids:
            card = by_id.get(cid)
            if card is None:
                raise RuleError("你手上没有这张牌")
            picked.append(card)
        return picked

    # --- 动作：领出 ---------------------------------------------------------

    def lead(self, player_id: str, card_ids: list[str], declared_rank: str) -> None:
        player = self._require_turn(player_id)
        if self.phase is not Phase.LEADING:
            raise RuleError("本轮点数已经定了，只能跟牌、质疑或过牌")
        if declared_rank not in RANKS:
            raise RuleError("只能声明 2~A，大小王不能作为本轮点数")

        picked = self._take_cards(player, card_ids)
        self._commit_play(player, picked, declared_rank)
        self.current_rank = declared_rank
        self.phase = Phase.FOLLOWING
        self.passes.clear()
        self._append_log(
            "lead",
            player_id=player.id,
            name=player.name,
            count=len(picked),
            rank=declared_rank,
            text=f"{player.name} 领出 {len(picked)} 张「{declared_rank}」",
        )
        self._advance_turn()

    # --- 动作：跟牌 ---------------------------------------------------------

    def follow(self, player_id: str, card_ids: list[str]) -> None:
        player = self._require_turn(player_id)
        if self.phase is not Phase.FOLLOWING or self.current_rank is None:
            raise RuleError("现在该你领出，需要自己指定点数")

        picked = self._take_cards(player, card_ids)
        self._commit_play(player, picked, self.current_rank)
        self.passes.clear()
        self._append_log(
            "follow",
            player_id=player.id,
            name=player.name,
            count=len(picked),
            rank=self.current_rank,
            text=f"{player.name} 跟了 {len(picked)} 张「{self.current_rank}」",
        )
        self._advance_turn()

    def _commit_play(self, player: Player, picked: list[Card], rank: str) -> None:
        picked_ids = {c.id for c in picked}
        player.hand = [c for c in player.hand if c.id not in picked_ids]
        self.pile.append(Play(player_id=player.id, cards=picked, declared_rank=rank))
        self.version += 1

    # --- 动作：质疑 ---------------------------------------------------------

    def challenge(self, player_id: str) -> dict:
        """只能质疑最后出牌的人。返回结算摘要（含被翻开的牌）。"""
        challenger = self._require_turn(player_id)
        target_play = self.last_play
        if self.phase is not Phase.FOLLOWING or target_play is None:
            raise RuleError("现在没有可以质疑的出牌")
        if target_play.player_id == challenger.id:
            raise RuleError("不能质疑自己")

        target = self.player(target_play.player_id)
        honest = target_play.is_honest
        loser = challenger if honest else target

        revealed = [card.to_dict() for card in target_play.cards]
        pile_cards = [card for play in self.pile for card in play.cards]
        loser.hand = sorted(loser.hand + pile_cards, key=self._sort_key)

        resolution = {
            "type": "challenge",
            "challenger_id": challenger.id,
            "challenger_name": challenger.name,
            "target_id": target.id,
            "target_name": target.name,
            "declared_rank": target_play.declared_rank,
            "revealed": revealed,
            "honest": honest,
            "loser_id": loser.id,
            "loser_name": loser.name,
            "cards_taken": len(pile_cards),
        }
        if honest:
            text = (
                f"{challenger.name} 质疑失败——{target.name} 说的是真的，"
                f"{len(pile_cards)} 张牌归 {challenger.name}"
            )
        else:
            text = (
                f"{challenger.name} 抓到了！{target.name} 撒谎，"
                f"{len(pile_cards)} 张牌全部回到 {target.name} 手上"
            )
        self._append_log("challenge", text=text, **resolution)

        # 裁决 3：赢的一方拿到下一轮出牌权。
        winner_of_challenge = target if honest else challenger
        self._start_new_round(resolution, lead_player=winner_of_challenge)
        return resolution

    # --- 动作：过牌 ---------------------------------------------------------

    def passing(self, player_id: str) -> None:
        player = self._require_turn(player_id)
        last = self.last_play
        if self.phase is not Phase.FOLLOWING or last is None:
            raise RuleError("领出方不能过牌，必须出牌")
        if last.player_id == player.id:
            raise RuleError("你是最后出牌的人，不需要过牌")

        self.passes.add(player.id)
        self._append_log(
            "pass", player_id=player.id, name=player.name, text=f"{player.name} 过"
        )

        # 除最后出牌者外全部过牌 -> 弃掉牌堆，最后出牌的人继续领出。
        others = {p.id for p in self.players if p.id != last.player_id}
        if others.issubset(self.passes):
            discarded = self.pile_size
            self.discarded_total += discarded
            resolution = {
                "type": "discard",
                "last_player_id": last.player_id,
                "last_player_name": self.player(last.player_id).name,
                "cards_discarded": discarded,
            }
            self._append_log(
                "discard",
                text=f"两家都过，{discarded} 张牌被弃掉",
                **resolution,
            )
            self._start_new_round(resolution, lead_player=self.player(last.player_id))
        else:
            self._advance_turn()

    # --- 回合结算 -----------------------------------------------------------

    def _start_new_round(self, resolution: dict, lead_player: Player) -> None:
        self.pile = []
        self.passes.clear()
        self.current_rank = None
        self.last_resolution = resolution
        self.version += 1

        winner = self._find_winner()
        if winner is not None:
            self.winner_id = winner.id
            self.phase = Phase.FINISHED
            self._append_log(
                "win", player_id=winner.id, name=winner.name, text=f"{winner.name} 出完了所有手牌，获胜！"
            )
            return

        self.round_no += 1
        self.phase = Phase.LEADING
        self.turn = lead_player.seat
        self._append_log(
            "new_round",
            player_id=lead_player.id,
            text=f"第 {self.round_no} 轮，{lead_player.name} 领出",
        )

    def _find_winner(self) -> Optional[Player]:
        """结算后手牌为 0 的人获胜。多人同时为 0 时按座位序取第一个（实际不会发生）。"""
        for player in self.players:
            if player.hand_count == 0:
                return player
        return None

    # --- 视图 ---------------------------------------------------------------

    def legal_actions(self, player_id: str) -> list[str]:
        if self.phase is Phase.FINISHED or player_id != self.current_player.id:
            return []
        player = self.player(player_id)
        if self.phase is Phase.LEADING:
            return ["lead"] if player.hand_count else []
        actions: list[str] = []
        last = self.last_play
        if player.hand_count:
            actions.append("follow")
        if last and last.player_id != player.id:
            actions.extend(["challenge", "pass"])
        return actions

    def public_state(self) -> dict:
        """所有人都能看到的信息。绝不包含任何人的手牌内容。"""
        return {
            "room_id": self.room_id,
            "version": self.version,
            "phase": self.phase.value,
            "round_no": self.round_no,
            "current_rank": self.current_rank,
            "turn_player_id": None if self.phase is Phase.FINISHED else self.current_player.id,
            "winner_id": self.winner_id,
            "max_cards_per_play": MAX_CARDS_PER_PLAY,
            "ranks": list(RANKS),
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "seat": p.seat,
                    "hand_count": p.hand_count,
                    "connected": p.connected,
                    "passed": p.id in self.passes,
                }
                for p in self.players
            ],
            "discarded_total": self.discarded_total,
            "pile": {
                "total": self.pile_size,
                # 只暴露「谁出了几张」，不暴露出的是什么。
                "plays": [
                    {"player_id": play.player_id, "count": play.count} for play in self.pile
                ],
                "last_player_id": self.last_play.player_id if self.last_play else None,
            },
            "last_resolution": self.last_resolution,
            "log": self.log[-12:],
        }

    def view_for(self, player_id: str) -> dict:
        """发给单个玩家的完整视图 = 公共状态 + 他自己的手牌。"""
        player = self.player(player_id)
        state = self.public_state()
        state["you"] = {
            "id": player.id,
            "name": player.name,
            "seat": player.seat,
            "hand": [card.to_dict() for card in player.hand],
            "legal_actions": self.legal_actions(player_id),
        }
        return state
