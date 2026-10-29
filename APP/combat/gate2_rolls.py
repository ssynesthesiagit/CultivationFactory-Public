from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

from .gate2_runtime_models import DiceSpec, RollRecord


@dataclass
class DeterministicRollAuthority:
    seed: str
    counter: int = 0
    after_d20: Callable[[RollRecord], RollRecord] | None = field(default=None, repr=False, compare=False)
    before_d20: Callable[[dict], RollRecord | None] | None = field(default=None, repr=False, compare=False)

    def _die(self, sides: int) -> tuple[int, int]:
        if sides < 2:
            raise ValueError("die requires at least two sides")
        limit = (1 << 256) - ((1 << 256) % sides)
        while True:
            current = self.counter
            block = hashlib.sha256(
                self.seed.encode("utf-8") + b"\x00" + current.to_bytes(16, "big")
            ).digest()
            self.counter += 1
            value = int.from_bytes(block, "big")
            if value < limit:
                return value % sides + 1, current

    def roll(
        self,
        dice: DiceSpec,
        *,
        actor_id: str,
        reason: str,
        mode: str = "NORMAL",
        critical: bool = False,
        fixed_damage: int | None = None,
    ) -> RollRecord:
        counter_start = self.counter
        count = dice.count * (2 if critical else 1)
        values: list[int] = []
        if fixed_damage is None:
            for _ in range(count):
                value, _ = self._die(dice.sides)
                values.append(value)
            total = sum(values) + dice.modifier
        else:
            total = fixed_damage + dice.modifier
        return RollRecord(
            roll_id=f"roll:{counter_start:08d}",
            counter_start=counter_start,
            counter_end=self.counter,
            expression=f"{count}d{dice.sides}{dice.modifier:+d}",
            actor_id=actor_id,
            reason=reason,
            dice=tuple(values),
            modifier=dice.modifier,
            total=total,
            natural_result=None,
            mode="NORMAL",
        )

    def d20(
        self,
        *,
        modifier: int,
        actor_id: str,
        reason: str,
        mode: str = "NORMAL",
    ) -> RollRecord:
        request = dict(modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
        roll = self.before_d20(request) if self.before_d20 is not None else None
        if roll is None:
            roll = self.raw_d20(**request)
        result = self.after_d20(roll) if self.after_d20 is not None else roll
        if getattr(mode, 'mode_sources', None):
            from .roll_reasons import unique_sources
            rows = list(mode.mode_sources)
            known = {row['kind'] for row in rows}
            rows.extend(row for row in result.mode_sources if row not in rows
                        and not (row['effect'] == 'Roll-specific effect' and row['kind'] in known))
            result = result.model_copy(update={'mode_sources': unique_sources(rows)})
        return result

    def raw_d20(self, *, modifier: int, actor_id: str, reason: str, mode: str = "NORMAL") -> RollRecord:
        """One deterministic draw; rewrites use this to avoid recursively opening the hook."""
        if mode not in {"NORMAL", "ADVANTAGE", "DISADVANTAGE"}:
            raise ValueError(f"unsupported d20 mode {mode}")
        counter_start = self.counter
        first, _ = self._die(20)
        discarded: tuple[int, ...] = ()
        chosen = first
        dice = [first]
        if mode != "NORMAL":
            second, _ = self._die(20)
            dice.append(second)
            if mode == "ADVANTAGE":
                chosen = max(first, second)
                discarded = (min(first, second),)
            else:
                chosen = min(first, second)
                discarded = (max(first, second),)
        return RollRecord(
            roll_id=f"roll:{counter_start:08d}",
            counter_start=counter_start,
            counter_end=self.counter,
            expression=f"1d20{modifier:+d}",
            actor_id=actor_id,
            reason=reason,
            dice=tuple(dice),
            modifier=modifier,
            total=chosen + modifier,
            natural_result=chosen,
            mode=mode,
            discarded=discarded,
        )
