"""Pure summon rules with injectable randomness for deterministic tests."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol

from .catalog import INITIAL_RELEASE_SERVANTS, SERVANTS


class RandomSource(Protocol):
    def randbelow(self, upper: int) -> int: ...


class SecureRandom:
    def randbelow(self, upper: int) -> int:
        return secrets.randbelow(upper)


@dataclass(frozen=True)
class SummonResult:
    servant_ids: tuple[str, ...]
    new_pity: int


def _pool_for_bucket(bucket: int) -> list[str]:
    released = {
        servant_id: SERVANTS[servant_id]
        for servant_id in INITIAL_RELEASE_SERVANTS
    }
    if bucket == 3:
        return [sid for sid, item in released.items() if item["rarity"] <= 3]
    return [sid for sid, item in released.items() if item["rarity"] == bucket]


def summon(count: int, pity: int, rng: RandomSource | None = None) -> SummonResult:
    if count not in (1, 11):
        raise ValueError("Summon count must be 1 or 11")
    if pity < 0:
        raise ValueError("Pity counter cannot be negative")

    rng = rng or SecureRandom()
    results: list[str] = []
    current_pity = pity

    for index in range(count):
        force_five = current_pity >= 59
        roll = rng.randbelow(10_000)
        if force_five or roll < 300:
            bucket = 5
        elif roll < 1_500:
            bucket = 4
        else:
            bucket = 3

        # The final card of an eleven-pull guarantees at least one SR.
        if index == count - 1 and count == 11:
            has_sr = any(SERVANTS[sid]["rarity"] >= 4 for sid in results)
            if not has_sr and bucket < 4:
                bucket = 4

        pool = _pool_for_bucket(bucket)
        servant_id = pool[rng.randbelow(len(pool))]
        results.append(servant_id)

        if SERVANTS[servant_id]["rarity"] == 5:
            current_pity = 0
        else:
            current_pity += 1

    return SummonResult(tuple(results), current_pity)
