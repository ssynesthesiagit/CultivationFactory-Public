"""Pure typed amounts shared by typed_executor and support_estimates.

Execution keeps deterministic rolling and narration; queries use the same
formula, CL dice and additive terms without those side effects.
"""
from __future__ import annotations
import re
from typing import Any
from factory_authoring.typed_mechanics import dice_for_cl


_FORMULA_TERM = re.compile(r"(?:(twice|three times|\d+)\s*(?:[x×*]\s*)?)?(?:your\s+)?(proficiency bonus|pb|cultivation level|cl|"
                           r"(?:path |qi cultivation |cultivation |source )?key ability modifier)", re.I)


def text_formula(text: str, numbers: dict[str, Any]) -> tuple[int | None, str]:
    """A printed amount the typing kept as text (owner 2026-09-29: "twice your proficiency bonus", "your proficiency bonus +
    your path key ability modifier", "`5 × pb`"): the leading sum of PB, CL and the key ability modifier, each optionally
    multiplied; (None, text) when it doesn't start with one. What follows the sum ("and may move 5 feet ...") is returned."""
    rest = text.strip().strip("`").strip()
    total, found = 0, False
    while True:
        match = _FORMULA_TERM.match(rest)
        if not match:
            break
        factor = {"twice": 2, "three times": 3}.get((match.group(1) or "").lower()) or int(match.group(1) or 1)
        term = match.group(2).lower()
        base = int(numbers.get("pb", 0)) if term in ("proficiency bonus", "pb") else int(numbers.get("cl", 0)) if term in ("cultivation level", "cl") \
            else int(numbers.get("key_mod", 0))
        total += factor * base
        found = True
        rest = rest[match.end():].strip().strip("`").strip()
        if rest.startswith("+"):
            rest = rest[1:].strip()
            continue
        break
    if not found:
        return None, text
    rest = re.sub(r"^,?\s*minimum 1\b", "", rest).strip(" ,.")
    return max(total, 1) if "minimum 1" in text else total, rest



def dice_from_text(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    parts = str(text).lower().split("d")
    if len(parts) != 2:
        return None
    count, sides = parts
    return {"count": int(count) if count.isdigit() else None, "count_formula": None if count.isdigit() else "pb",
            "sides": int(sides) if sides.isdigit() else 0}


def formula_value(name, numbers, *, trigger_damage=0, unknown=0, attack_ability_modifier=None):
    """Return an integer and optional narration; never mutate state or roll."""
    if not name or name == 'none':
        return 0, None
    if name in {'pb', 'cl'}:
        return int(numbers.get(name, 0)), None
    if name == 'half_pb':
        return int(numbers.get('pb', 0)) // 2, None
    if name in {'double_pb', 'triple_pb'}:
        return int(numbers.get('pb', 0)) * (2 if name == 'double_pb' else 3), None
    if name == 'cl_x5':
        return int(numbers.get('cl', 0)) * 5, None
    if name == 'attack_ability_modifier':
        # Weapon techniques pass their delivered weapon's ability; callers
        # without one retain the printed key-ability fallback.
        return int(numbers.get('key_mod', 0) if attack_ability_modifier is None else attack_ability_modifier), None
    if name.startswith('mod:') or name == 'key_ability_modifier':
        return int(numbers.get('key_mod', 0)), None
    if name == 'half_trigger_damage':
        return min(int(trigger_damage or 0) // 2, 5 * int(numbers.get('cl', 1) or 1)), None
    if name.startswith('text:'):
        value, rest = text_formula(name[5:], numbers)
        if value is not None:
            return value, f'Also: {rest}' if re.match(r'(?:and|or)\b', rest) else None
    # ``unknown=None`` means the caller has no default to offer: the value is None, so a
    # display that cannot resolve a formula says nothing rather than inventing a number
    # (typed_executor.static_formula). Every other caller passes its own default.
    return (None if unknown is None else int(unknown)), f'Formula not typed: {name}'


def dice_terms(spec, *, flat=0, formula=None, resolve):
    """Shared dice count, sides and modifier for execution and mean estimates."""
    spec = spec or {}
    count = spec.get('count')
    if count is None and spec.get('count_formula'):
        count = resolve(spec['count_formula'])
    modifier = int(spec.get('bonus') or 0) + resolve(spec.get('bonus_formula')) + int(flat or 0) + resolve(formula)
    return int(count or 0), int(spec.get('sides') or 0), modifier


def effect_dice(effect, numbers):
    """Select the same CL-scaled dice used by typed execution."""
    base = effect.get('dice') if isinstance(effect.get('dice'), dict) else dice_from_text(effect.get('dice'))
    scaled = dice_for_cl(effect.get('dice_by_cl'), numbers.get('cl'))
    if scaled:
        return {**(base or {}), **scaled}
    return base


def effect_flat(effect, numbers):
    """Only Temporary HP currently supports a level-specific flat grant."""
    if effect.get('type') == 'temp_hp':
        return next((int(value) for low, high, value in effect.get('flat_by_cl') or []
                     if low <= int(numbers.get('cl') or 1) <= high), int(effect.get('flat') or 0))
    return int(effect.get('flat') or 0)


def average_amount(effect, numbers, *, trigger_damage=0, unknown=0):
    resolve = lambda name: formula_value(name, numbers, trigger_damage=trigger_damage, unknown=unknown)[0]
    count, sides, modifier = dice_terms(effect_dice(effect, numbers), flat=effect_flat(effect, numbers),
                                        formula=effect.get('formula'), resolve=resolve)
    return max(0, modifier + (count * (sides + 1) // 2 if count > 0 and sides >= 2 else 0))
