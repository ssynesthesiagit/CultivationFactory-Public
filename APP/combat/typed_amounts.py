"""Pure typed amounts shared by typed_executor and support_estimates.

Execution keeps deterministic rolling and narration; queries use the same
formula, CL dice and additive terms without those side effects.
"""
from __future__ import annotations
import ast
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


_EXPRESSION = re.compile(r"[0-9a-z_+*\-() ]+")


def static_bonus(effect, numbers=None, *, ability_mods=None, weapon=None):
    """The roll-free part of a generic amount: its ``formula`` (typed_executor's table plus the
    ``pb``/``cl``/``key`` arithmetic expressions a typed row may carry) and its ``flat``.

    The same table ``combat/typed_reactions._generic_amount`` resolves, split out so a caller that
    must judge an amount *without rolling it* -- an admission gate asking "is this a penalty?" --
    reads the engine's own vocabulary instead of re-guessing it from whichever key happens to be
    present. Pure: no roller, no events, no state. ``None`` means the formula is not one this
    engine knows, which is "no roll-free bonus", never a crash.
    """
    numbers = numbers or {}
    weapon = weapon or {}
    formula = str(effect.get('formula') or 'none')
    if formula in {'pb', 'cl'}:
        bonus = int(numbers.get(formula, 0))
    elif formula == 'half_pb':
        bonus = int(numbers.get('pb', 0)) // 2
    elif formula == 'key_ability_modifier':
        bonus = int(numbers.get('key_mod', 0))
    elif formula == 'attack_ability_modifier':
        modifier = weapon.get('ability_modifier')
        bonus = int(numbers.get('key_mod', 0) if modifier is None else modifier)
    elif formula != 'none' and _EXPRESSION.fullmatch(formula):
        names = {'pb': int(numbers.get('pb', 0)), 'cl': int(numbers.get('cl', 0)), 'key': int(numbers.get('key_mod', 0)),
                 **{str(ability).lower(): int(value) for ability, value in (ability_mods or {}).items()}}
        try:
            bonus = int(eval(formula.replace(' ', ''), {'__builtins__': {}}, names))  # noqa: S307 -- digits, + - * ( ) and those names
        except Exception:  # noqa: BLE001 -- an unknown name is no bonus, never a crashed fight
            bonus = 0
    else:
        bonus = 0
    return bonus + int(effect.get('flat') or 0)


# --- Query-side intervals over inputs the caller did not supply ----------------------
#
# Execution (``static_bonus`` above) resolves an absent input to zero because it must produce a
# number to apply. A gate that must *classify* a row before anything is rolled cannot do that: the
# absent input is not zero, it is a domain the gate has not been told. Substituting one invented
# reading of it (PB = 1) makes the sign of the whole row a guess -- ``half_pb`` floors to 0 at the
# invented value while execution reduces an attack at PB 2, and ``pb`` with ``flat: -2`` reads as a
# penalty at the invented value while execution grants an attack bonus at PB 3. So the query side
# bounds each absent input instead, using only what the rules fix.
_LEVEL_INPUTS = frozenset({'pb', 'cl'})
"""Progression inputs: a Proficiency Bonus and a Cultivation Level are derived from level and are
never negative (spheres5e, D&D 5.5e). ``[0, +inf)`` is that rule, not an invented magnitude."""


def _sum(left, right):
    return None if left is None or right is None else left + right


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _name_values(numbers=None, ability_mods=None, weapon=None):
    """Every name an arithmetic expression may read, matching ``static_bonus``'s table exactly.

    ``key`` is the expression spelling of the key ability modifier, which execution reads from
    ``key_mod``; ``ability_mods`` rides on the row and wins over both, as it does there.
    """
    numbers = numbers or {}
    values = {'pb': _as_int(numbers.get('pb')), 'cl': _as_int(numbers.get('cl')),
              'key': _as_int(numbers.get('key_mod'))}
    for ability, value in (ability_mods or {}).items():
        values[str(ability).lower()] = _as_int(value)
    return values


def _input_bounds(name, values):
    """``(low, high)`` for one formula input. A supplied value is exact; ``pb``/``cl`` keep their
    rule floor; anything else (an ability modifier, an unknown name) has no rule-fixed sign, so no
    bound is proved and both ends stay open."""
    value = values.get(name)
    if value is not None:
        return value, value
    if name in _LEVEL_INPUTS:
        return 0, None
    return None, None


def _scale(bounds, factor):
    low, high = bounds
    return None if low is None else low * factor, None if high is None else high * factor


def _floor_half(bounds):
    """``pb // 2`` at both ends: pb is nonnegative, so flooring each bound keeps the interval."""
    low, high = bounds
    return (None if low is None else low // 2, None if high is None else high // 2)


# Only arithmetic over named inputs is understood. Division, power, calls and attribute access are
# rejected whole: this answers "what can this row do", never "run this row".
_EXPRESSION_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
                     ast.Add, ast.Sub, ast.Mult, ast.UAdd, ast.USub, ast.Load)


def _node_bounds(node, values):
    if isinstance(node, ast.Constant):
        return (node.value, node.value) if isinstance(node.value, int) else (None, None)
    if isinstance(node, ast.Name):
        return _input_bounds(node.id, values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        low, high = _node_bounds(node.operand, values)
        return (low, high) if isinstance(node.op, ast.UAdd) else \
            (None if high is None else -high, None if low is None else -low)
    if isinstance(node, ast.BinOp):
        low1, high1 = _node_bounds(node.left, values)
        low2, high2 = _node_bounds(node.right, values)
        if isinstance(node.op, ast.Add):
            return _sum(low1, low2), _sum(high1, high2)
        if isinstance(node.op, ast.Sub):
            return _sum(low1, None if high2 is None else -high2), _sum(high1, None if low2 is None else -low2)
        if isinstance(node.op, ast.Mult):
            if None in (low1, high1, low2, high2):
                return None, None  # an unbounded operand can carry the product either way
            corners = (low1 * low2, low1 * high2, high1 * low2, high1 * high2)
            return min(corners), max(corners)
    return None, None


def _expression_bounds(formula, values):
    try:
        tree = ast.parse(formula.strip(), mode='eval')
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None, None
    if any(not isinstance(child, _EXPRESSION_NODES) for child in ast.walk(tree)):
        return None, None
    return _node_bounds(tree.body, values)


def formula_bounds(name, numbers=None, *, ability_mods=None, weapon=None):
    """The smallest and largest a formula ``name`` can resolve to, as ``(low, high)``.

    The same vocabulary ``static_bonus`` and execution resolve, read as an interval instead of one
    number. Each input the caller supplied is exact; each one it did not supply is bounded by what
    the rules fix about it (``pb``/``cl`` nonnegative, unbounded above) or left open when its sign is
    the creature's own rather than the rule's (an ability modifier, a delivered weapon's ability).
    ``None`` for an end means no bound is proved that way -- the caller must read the row's meaning
    as unresolved and choose its own conservative answer, never as zero.
    """
    name = str(name or 'none')
    if name in ('', 'none'):
        return 0, 0
    values = _name_values(numbers, ability_mods, weapon)
    if name in values or name in _LEVEL_INPUTS:
        return _input_bounds(name, values)
    if name == 'half_pb':
        # ``//`` floors, and pb is nonnegative, so each end floors with it.
        return _floor_half(_input_bounds('pb', values))
    if name in {'double_pb', 'triple_pb'}:
        return _scale(_input_bounds('pb', values), 2 if name == 'double_pb' else 3)
    if name == 'cl_x5':
        return _scale(_input_bounds('cl', values), 5)
    if name == 'key_ability_modifier' or name.startswith('mod:'):
        return _input_bounds('key', values)
    if name == 'attack_ability_modifier':
        # Execution reads the delivered weapon's ability first and falls back to the key modifier.
        modifier = _as_int((weapon or {}).get('ability_modifier'))
        return (modifier, modifier) if modifier is not None else _input_bounds('key', values)
    if name.startswith('text:'):
        # A printed sum is read by ``text_formula`` at execution; nothing here can bound its parts.
        return None, None
    if _EXPRESSION.fullmatch(name):
        return _expression_bounds(name, values)
    return None, None


def amount_bounds(effect, numbers=None, *, ability_mods=None, weapon=None):
    """The smallest and largest a generic amount can resolve to, as ``(low, high)``.

    One reading of "how big is this effect", shared by every gate that must classify a row before
    anything is rolled. ``static_bonus`` gives the fixed part; a ``dice``/``dice_by_cl`` term
    contributes ``count`` at its minimum (every die counts at least 1) and ``count * sides`` at its
    maximum. Nothing here rolls, records an event or touches the engine, so an admission gate can
    read it without spending state or revealing an outcome the player has not seen.

    An input the caller did not supply widens the interval instead of being read as zero: the
    bounds cover the whole domain such an input may take, so an offset that can push the amount
    across zero at one level and not another is reported as such. See ``formula_bounds`` for the
    two domains. ``None`` for an end means *no bound is proved in that direction*.

    A caller reads ``low`` when it needs certainty the amount *reaches* a magnitude -- "this row
    can only ever help" is ``low is not None and low >= 0`` -- and ``high`` when it needs certainty
    the amount *stays under* one: ``high is None or high <= 0`` is the only safe reading for "can
    this ever be a penalty", because a die that might land high, or an input whose size is unknown,
    is a penalty that might happen.
    """
    low, high = formula_bounds(effect.get('formula'), numbers, ability_mods=ability_mods, weapon=weapon)
    flat = int(effect.get('flat') or 0)
    low = _sum(low, flat)
    high = _sum(high, flat)
    dice = effect_dice(effect, numbers or {})
    if isinstance(dice, dict):
        count, sides = int(dice.get('count') or 0), int(dice.get('sides') or 0)
        if count > 0 and sides > 1:
            low = _sum(low, count)
            high = _sum(high, count * sides)
    return low, high


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
