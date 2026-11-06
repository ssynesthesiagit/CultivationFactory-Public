"""Bounded compiler hints for executable typed riders, in policy points.

This is deliberately not damage or an expected-value calculation. It considers
one recipient and one forthcoming opportunity, never multiplies by duration,
attack count or repeat count, and keeps the strongest contribution per family.
The controller must still establish whether a particular recipient needs the
benefit. No engine state or typed data is changed.

Only the schemas handled below earn credit. In particular, evidence, names,
manual riders, deferred text triggers and direct damage/healing/temp HP are not
read. The existing damage estimator already includes some deferred extra_damage.
Reaction preparation earns a small option value, never the prepared attack's
damage. The existing reliable-replacement value must be combined with this hint
using max(), not addition.

Movement credit is held per creature, and the deduplication that cancels it is
resolved once for each complete outcome rather than once per gate. A creature whose
Speed an outcome definitely removes -- a speed-zero condition in the activation
itself, or in a gate both of whose outcomes take it -- cannot also earn separate
movement credit from that outcome, wherever in the activation the stop and the
movement row were written. What only one of two exclusive outcomes removes stays
inside that outcome, so a save that grapples on failure and shoves on success is
worth both.

Each complete outcome is therefore valued as a whole -- its strongest movement
contribution, with the creatures it stops left out -- and only then are the outcomes
averaged. A save that shoves the target on failure and steps the caster on success is
worth both consequences: they are two different creatures in two different outcomes, so
each outcome keeps its own full credit. Averaging each creature's credit first would
report halves of a consequence no single outcome produces.

Several nested gates can describe more complete outcomes than a hint may hold, so the
retained list is bounded. When it is, the outcomes left out have their chance of
happening discarded outright rather than divided among the ones kept, so the published
figure can fall short of the activation's real worth but can never exceed it.

Recovering a resource pool earns nothing here. Refilling a pool that is already
full recovers nothing, and a compile-time hint cannot read how much supply the
caster has left; the controller adds this hint without a capacity check, so a
published refill would outrank a useful alternative while wasting its action.
Pool value returns with the state-aware projection described in
docs/plans/AI_ABILITY_VALUE_P20261005-16.md, which needs pool maxima the
controller's own context does not yet carry.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Any

from .roll_mode_semantics import roll_mode_target


MAX_RIDER_UTILITY = 16
MAX_EFFECT_DEPTH = 12
MAX_EFFECT_ROWS = 256
# Distinct complete outcomes kept while reading gates; see bounded() below.
MAX_MOVEMENT_OUTCOMES = 16
FAMILY_CAPS = {"condition_or_mode": 8, "next_bonus": 6, "movement": 4,
               "reaction_setup": 4}
# Admission estimates, not measured hit/save/trigger probabilities.
BRANCH_CHANCE = Fraction(1, 2)
NEXT_OPPORTUNITY = Fraction(1, 2)
ACTION_PREPARATION = Fraction(1, 2)
_DISABLED = ("inert", "gm_only", "manual", "setting_only", "player_only")
_NO_STOP: frozenset[str] = frozenset()
_FRIENDLY_TARGETS = {"SELF", "ALLY_OR_SELF"}
_ABILITY_CODES = {"STR", "DEX", "CON", "INT", "WIS", "CHA"}
_ALLOWED_FORMULAS = {"pb", "cl", "half_pb", "double_pb", "triple_pb", "cl_x5",
                     "key_ability_modifier", "attack_ability_modifier", "none"}


def _integer(value: Any) -> int:
    # Authored numeric fields are integers; booleans and prose are not amounts.
    return max(-10000, min(value, 10000)) if type(value) is int else 0


def _formula(value: Any, numbers: dict[str, int]) -> int:
    if not isinstance(value, str) or (value not in _ALLOWED_FORMULAS and not value.startswith("mod:")):
        return 0
    from .typed_amounts import formula_value

    return _integer(formula_value(value, numbers, unknown=0, attack_ability_modifier=numbers.get("_weapon_mod"))[0])


def _recipient(effect: dict[str, Any], target_kind: str, *, defaults_to_target: bool) -> str | None:
    """Polarity of the executor's declared recipient; mixed/unknown areas abstain."""
    applies = effect.get("applies_to")
    if applies == "self":
        return "friend"
    if applies in ("ally", "allies"):
        # Harmful dispatch precedes the executor's ally handler. A condition
        # always uses that dispatch even when the condition is a benefit.
        # Abstain when its declared ally conflicts with the actual aim.
        if defaults_to_target and target_kind not in _FRIENDLY_TARGETS:
            return None
        return "friend"
    if applies == "enemies_in_area":
        return "foe"
    if applies == "creatures_in_area" or applies == "attacker":
        return None  # an interrupted actor is not necessarily hostile
    if applies is not None and applies != "target":
        return None
    if applies is None and not defaults_to_target:
        return "friend"
    if target_kind == "HOSTILE_ENTITY":
        return "foe"
    if target_kind in _FRIENDLY_TARGETS:
        return "friend"
    return None


def _useful(effect: dict[str, Any], target_kind: str, *, harmful: bool,
            defaults_to_target: bool | None = None) -> bool:
    recipient = _recipient(effect, target_kind, defaults_to_target=harmful if defaults_to_target is None else defaults_to_target)
    return recipient == ("foe" if harmful else "friend")


def _condition_rule(effect: dict[str, Any]) -> dict[str, Any]:
    from .typed_executor import rules

    name = effect.get("condition")
    table = rules().get("conditions") or {}
    rule = table.get(name.lower()) if isinstance(name, str) else None
    if not isinstance(rule, dict):
        return {}
    own = effect.get("condition_data")
    if own is not None:
        if not isinstance(own, dict) or (own.get("rule") is not None and not isinstance(own["rule"], dict)):
            return {}
        if own.get("suppressed"):
            return {}
        rule = {**rule, **(own.get("rule") or {})}
    return rule


def _condition_value(effect: dict[str, Any], target_kind: str, rule: dict[str, Any]) -> int:
    from .typed_executor import _SKILLS

    # These are executable flags. Presentation-only pill_tone/effect_kind and
    # the prose _rule do not demonstrate an implemented combat benefit.
    harm = max((points for key, points in (("no_actions", 8), ("speed_zero", 4), ("no_reactions", 3),
                ("no_dash", 1), ("no_teleport", 1), ("cant_hear", 1), ("no_cp_regain", 2),
                ("healing_halved", 2)) if rule.get(key) is True), default=0)
    benefit = 1 if rule.get("ignore_difficult") is True else 0
    # attacks_others_have is read from the base table only; arbitrary condition
    # data does not implement it. Leave that narrower rule unvalued here.
    for key in ("attacks_have", "attacked_with", "attacked_with_if_attacker_visible"):
        mode = rule.get(key)
        if mode not in ("ADVANTAGE", "DISADVANTAGE"):
            continue
        bad = mode == ("ADVANTAGE" if key.startswith("attacked") else "DISADVANTAGE")
        harm, benefit = (max(harm, 3), benefit) if bad else (harm, max(benefit, 3))
    for key in ("save_mode", "check_mode"):
        modes = rule.get(key)
        if not isinstance(modes, dict):
            continue
        points = 3 if key == "save_mode" else 1
        keys = _ABILITY_CODES if key == "save_mode" else _ABILITY_CODES | {"ALL", *_SKILLS}
        values = [mode for scope, mode in modes.items() if scope in keys]
        harmful_modes = ("DISADVANTAGE", "AUTO_FAIL") if key == "save_mode" else ("DISADVANTAGE",)
        harm = max(harm, points if any(mode in harmful_modes for mode in values) else 0)
        benefit = max(benefit, points if "ADVANTAGE" in values else 0)
    if rule.get("concentration_mode") == "DISADVANTAGE":
        harm = max(harm, 2)
    elif rule.get("concentration_mode") == "ADVANTAGE":
        benefit = max(benefit, 2)
    # Mixed harmful/beneficial conditions are not a self-buff opportunity. The
    # strongest adverse flag sets the value when imposed on an enemy.
    if harm:
        return harm if _useful(effect, target_kind, harmful=True) else 0
    if benefit and _useful(effect, target_kind, harmful=False, defaults_to_target=True):
        # The condition executor does not fall back to its caster for target rows.
        if target_kind == "SELF" and effect.get("applies_to") != "self":
            return 0
        return benefit
    return 0


def _mode_value(effect: dict[str, Any], target_kind: str) -> int:
    from .typed_executor import _check_keys, _names_a_save

    if not isinstance(effect.get("on"), str):
        return 0
    on, incoming = roll_mode_target(effect)
    # Reuse the executor's typed 'on' semantics. Generic 'saving throws' without
    # named coverage is a manual rider there, not an automated save bonus.
    if "attack roll" in on:
        points = 4
    elif ("concentration" in on and any(word in on for word in ("saving throw", "save", "check"))) or _names_a_save(on):
        points = 4
    elif "check" in on and _check_keys(on):
        points = 2
    else:
        return 0
    harmful = effect["type"] == ("advantage" if incoming else "disadvantage")
    return points if _useful(effect, target_kind, harmful=harmful) else 0


def _level_eligible(effect: dict[str, Any], numbers: dict[str, int]) -> bool:
    cl = numbers.get("cl", 1) or 1
    for key in ("min_cl", "max_cl"):
        if effect.get(key) is not None and type(effect[key]) is not int:
            return False
    return not ((effect.get("min_cl") and cl < effect["min_cl"]) or
                (effect.get("max_cl") is not None and cl > effect["max_cl"]))


def _mode_signature(effect: dict[str, Any], aimed: str) -> tuple | None:
    if effect.get("type") not in ("advantage", "disadvantage") or not isinstance(effect.get("on"), str):
        return None
    on, incoming = roll_mode_target(effect)
    harmful = effect["type"] == ("advantage" if incoming else "disadvantage")
    recipient = _recipient(effect, aimed, defaults_to_target=harmful)
    # The executor applies all outgoing attack-roll wording to NEXT_ATTACK.
    return (recipient, incoming, "attack" if "attack roll" in on else on.strip()) if recipient else None


def estimate_rider_utility(typed: Any, *, target_kind: str, economy: str = "action",
                           setting_only: bool = False) -> int:
    """Return 0..MAX_RIDER_UTILITY using only supported compiled typed semantics.

    Call after action/weapon/augment transforms. Pass the action's target_kind
    and economy; never send setting/manual/inert rows to the controller. This
    function also rejects those flags when present on typed data or effects.
    Rows/depth are bounded and malformed rows abstain. Unknown wrappers are not
    traversed: nesting an effect in a manual container cannot earn value.
    """
    if not isinstance(typed, dict) or setting_only or any(typed.get(key) for key in _DISABLED):
        return 0
    numbers_raw = typed.get("numbers")
    number_keys = ("pb", "key_mod", "cl")
    if isinstance(numbers_raw, dict) and any(key in numbers_raw and type(numbers_raw[key]) is not int for key in number_keys):
        return 0
    numbers = {key: _integer(numbers_raw[key]) for key in number_keys if key in numbers_raw} if isinstance(numbers_raw, dict) else {}
    weapon = typed.get("weapon")
    if isinstance(weapon, dict) and weapon.get("ability_modifier") is not None:
        if type(weapon["ability_modifier"]) is not int:
            return 0
        numbers["_weapon_mod"] = _integer(weapon["ability_modifier"])
    target_kind = target_kind if isinstance(target_kind, str) else ""
    economy = str(economy).lower().rsplit(".", 1)[-1]
    area = typed.get("area")
    has_area = isinstance(area, dict) and _integer(area.get("size_ft")) > 0
    visited = 0
    truncated = False
    removed_conditions: set[str] = set()

    def eligible(effect: Any) -> bool:
        return (isinstance(effect, dict) and isinstance(effect.get("type"), str) and not effect.get("deferred")
                and not any(effect.get(key) for key in _DISABLED) and _level_eligible(effect, numbers)
                and not (effect.get("menu") and effect.get("option")))

    def invalidations(effects: Any, depth: int = 0) -> None:
        # A same-activation removal can undo an apparent benefit. Without
        # executing branches, abstain on that benefit.
        nonlocal visited, truncated
        if not isinstance(effects, (list, tuple)):
            return
        if depth >= MAX_EFFECT_DEPTH:
            truncated |= bool(effects)
            return
        for effect in effects:
            visited += 1
            if visited > MAX_EFFECT_ROWS:
                truncated = True
                break
            if not eligible(effect):
                continue
            kind = effect["type"]
            if kind == "remove_condition" and isinstance(effect.get("condition"), str):
                removed_conditions.add(effect["condition"].strip().lower().removeprefix("condition:typed."))
            keys = {"attack": ("on_hit", "on_miss"), "save": ("on_fail", "on_success"),
                    "if_marked": ("effects",), "if_not_marked": ("effects",), "weapon_method": ("effects",)}.get(kind, ())
            for key in keys:
                invalidations(effect.get(key), depth + 1)

    invalidations(typed.get("effects"))
    if truncated:
        return 0  # omitted rows could remove a benefit seen earlier
    visited = 0

    def merge(left: dict[str, Fraction], right: dict[str, Fraction]) -> dict[str, Fraction]:
        return {key: max(left.get(key, Fraction()), right.get(key, Fraction())) for key in left.keys() | right.keys()}

    def outcome_key(stopped: frozenset[str], mobility: dict[str, Fraction]) -> tuple:
        """One complete outcome as a hashable key: whom it stops, how each moves."""
        return (stopped, tuple(sorted(mobility.items())))

    def outcome_value(key: tuple) -> Fraction:
        """What one complete outcome is worth: the movement it survives, strongest first.

        The same reading the average below uses, so the bound can rank the
        outcomes it keeps without restating it."""
        stopped, mobility = key
        return max((points for who, points in mobility if who not in stopped),
                   default=Fraction())

    def add_weight(outcomes: dict[tuple, Fraction], key: tuple, weight: Fraction) -> None:
        outcomes[key] = outcomes.get(key, Fraction()) + weight

    def credit(outcomes: dict[tuple, Fraction], who: str, points: Fraction) -> dict[tuple, Fraction]:
        """One creature's movement row, which happens in every outcome of this list."""
        credited: dict[tuple, Fraction] = {}
        for (stopped, mobility), weight in outcomes.items():
            held = dict(mobility)
            if points > held.get(who, Fraction()):
                held[who] = points
                add_weight(credited, outcome_key(stopped, held), weight)
            else:
                add_weight(credited, (stopped, mobility), weight)
        return credited

    def stop(outcomes: dict[tuple, Fraction], who: str) -> dict[tuple, Fraction]:
        """A Speed this subtree certainly removes, in every outcome of this list."""
        stopped: dict[tuple, Fraction] = {}
        for (already, mobility), weight in outcomes.items():
            add_weight(stopped, outcome_key(already | {who}, dict(mobility)), weight)
        return stopped

    def bounded(outcomes: dict[tuple, Fraction]) -> dict[tuple, Fraction]:
        """Hold the retained outcomes to a documented bound, without inventing value.

        Distinct outcomes only multiply with several nested gates. When there are
        more than MAX_MOVEMENT_OUTCOMES, this keeps the outcomes worth the most
        expected movement and DISCARDS the rest of the probability mass: the
        retained weights are never divided up to make them add back up to one.
        Renormalising would average over the retained outcomes alone, and dropping
        the least likely outcomes raises that average, so the hint could report more
        movement than the activation is worth.

        Dropping mass cannot, on the other hand, overstate anything. Every weight
        stays a non-negative fraction summing to at most one, and the movement
        family is a maximum taken inside one outcome, so the final figure is a
        non-negative weighted sum over a subset of the outcomes the activation has.
        Each later step reads an outcome on its own -- together() pairs two lists and
        keeps the stronger of each creature, credit() raises one creature, stop()
        cancels another -- so no later step can raise a retained outcome above what
        the unbounded reading would give it either. The bound therefore costs
        movement credit, which is the safe direction for a hint that must never
        invent value."""
        if len(outcomes) <= MAX_MOVEMENT_OUTCOMES:
            return outcomes
        # Keep the outcomes carrying the most expected movement; str() is the
        # tie-break because an outcome key holds an unordered frozenset.
        kept = sorted(outcomes.items(),
                      key=lambda row: (-row[1] * outcome_value(row[0]), str(row[0])))
        return dict(kept[:MAX_MOVEMENT_OUTCOMES])

    class Bundle:
        """What one subtree of effects is worth, before it is reduced to one number.

        ``families`` holds the non-movement families, already averaged over the
        exclusive branches read so far. ``moves`` holds what the movement family is
        worth in each *complete outcome* of this subtree: every outcome is a
        ``(creatures this outcome stops, movement value per creature)`` key with the
        chance of that outcome happening. Movement therefore stays separate per
        outcome until the whole activation has been read, whichever side of a gate
        declared a stop, and the family maximum is taken inside one outcome before
        the outcomes are averaged -- so two creatures moved in two different
        outcomes keep both credits, and a speed-zero that only one of two exclusive
        outcomes takes cancels only that outcome's movement.
        """
        __slots__ = ("families", "moves")

        def __init__(self, families: dict[str, Fraction] | None = None,
                     moves: dict[tuple, Fraction] | None = None) -> None:
            self.families = {} if families is None else families
            self.moves = {(_NO_STOP, ()): Fraction(1)} if moves is None else moves

    def alternatives(left: "Bundle", right: "Bundle") -> "Bundle":
        """Two mutually exclusive outcomes of one gate, then averaged.

        Each outcome keeps its own stops and its own movement: a creature that is
        grappled in one outcome and shoved in the other keeps both consequences."""
        families = {key: (left.families.get(key, Fraction()) + right.families.get(key, Fraction())) * BRANCH_CHANCE
                    for key in left.families.keys() | right.families.keys()}
        outcomes: dict[tuple, Fraction] = {}
        for source in (left.moves, right.moves):
            for key, weight in source.items():
                add_weight(outcomes, key, weight * BRANCH_CHANCE)
        return Bundle(families, bounded(outcomes))

    def together(left: "Bundle", right: "Bundle") -> "Bundle":
        """Two subtrees that happen in the same outcome (a plain wrapper's rows).

        Every outcome of one pairs with every outcome of the other. The strongest of
        each family and of each creature's movement stands, and a stop either side
        takes is definite for the outcome they share."""
        outcomes: dict[tuple, Fraction] = {}
        for (stopped_here, mobility_here), weight_here in left.moves.items():
            for (stopped_there, mobility_there), weight_there in right.moves.items():
                mobility = dict(mobility_here)
                for who, points in mobility_there:
                    if points > mobility.get(who, Fraction()):
                        mobility[who] = points
                add_weight(outcomes, outcome_key(stopped_here | stopped_there, mobility),
                           weight_here * weight_there)
        return Bundle(merge(left.families, right.families), bounded(outcomes))

    def fold(gate: "Bundle", families: dict[str, Fraction],
             moves: dict[tuple, Fraction]) -> tuple[dict[str, Fraction], dict[tuple, Fraction]]:
        """Take one gate's Bundle into the rows read so far, in this same outcome."""
        merged = together(Bundle(families, moves), gate)
        return merged.families, merged.moves

    def walk(effects: Any, depth: int = 0, aimed: str = target_kind) -> "Bundle":
        """The Bundle of one effect list, and of every gate inside it.

        Movement credit stays per outcome rather than being folded into a family
        here, so that the enclosing outcome can still cancel it once the whole
        activation has been read, whichever side of the gate declared the stop."""
        nonlocal visited
        families: dict[str, Fraction] = {}
        moves: dict[tuple, Fraction] = {(_NO_STOP, ()): Fraction(1)}
        if not isinstance(effects, (list, tuple)) or depth >= MAX_EFFECT_DEPTH:
            return Bundle(families, moves)
        modes: dict[tuple, set[str]] = {}
        for effect in effects[:max(0, MAX_EFFECT_ROWS - visited)]:
            if eligible(effect):
                signature = _mode_signature(effect, aimed)
                if signature is not None:
                    modes.setdefault(signature, set()).add(effect["type"])
        for effect in effects:
            visited += 1
            if visited > MAX_EFFECT_ROWS:
                break
            if not eligible(effect):
                continue
            kind = effect["type"]
            if effect.get("applies_to") == "enemies_in_area" and not has_area and aimed != "HOSTILE_ENTITY":
                continue  # filtering a lone friendly recipient leaves nobody
            if kind == "attack":
                if aimed == "SELF" and not has_area:
                    continue  # block_attack iterates ctx.targets, not the caster
                count = effect.get("count", 1)
                if type(count) is not int or count <= 0:
                    continue
                table = effect.get("count_by_cl") or []
                if not isinstance(table, list) or any(not isinstance(row, (list, tuple)) or len(row) != 3 or
                        any(type(value) is not int for value in row) for row in table):
                    continue
                count = next((value for low, high, value in table if low <= numbers.get("cl", 1) <= high), count)
                if count > 0:
                    gate = alternatives(walk(effect.get("on_hit"), depth + 1, aimed),
                                        walk(effect.get("on_miss"), depth + 1, aimed))
                    families, moves = fold(gate, families, moves)
                continue
            if kind == "save":
                if aimed == "SELF" and not has_area and effect.get("applies_to") != "self":
                    continue
                if effect.get("ability") is not None and (not isinstance(effect["ability"], str) or
                        any(code not in _ABILITY_CODES for code in effect["ability"].upper().split("_OR_"))):
                    continue
                recipient = _recipient(effect, aimed, defaults_to_target=True)
                nested = {"foe": "HOSTILE_ENTITY", "friend": "ALLY_OR_SELF"}.get(recipient, "")
                gate = alternatives(walk(effect.get("on_fail"), depth + 1, nested),
                                    walk(effect.get("on_success"), depth + 1, nested))
                families, moves = fold(gate, families, moves)
                continue
            if kind in ("if_marked", "if_not_marked"):
                if aimed == "SELF" and not has_area and effect.get("applies_to") != "self":
                    continue
                mark = effect.get("mark")
                names = mark if isinstance(mark, list) else [mark]
                if not any(isinstance(name, str) and name.strip() for name in names):
                    continue
                nested = "SELF" if effect.get("applies_to") == "self" else aimed
                # A mark gate is one side of a coin: it is averaged against the
                # "not marked" reading, so a stop only it takes is not definite.
                gate = alternatives(walk(effect.get("effects"), depth + 1, nested), Bundle())
                families, moves = fold(gate, families, moves)
                continue
            if kind == "weapon_method":
                families, moves = fold(walk(effect.get("effects"), depth + 1, aimed),
                                       families, moves)
                continue
            family, value, opportunity, who = "", 0, False, ""
            if kind == "condition":
                if isinstance(effect.get("condition"), str) and effect["condition"].lower() in removed_conditions:
                    continue
                rule = _condition_rule(effect)
                family, value = "condition_or_mode", _condition_value(effect, aimed, rule)
                if value > 0 and rule.get("speed_zero") is True:
                    who = _recipient(effect, aimed, defaults_to_target=True)
                    if who:
                        moves = stop(moves, who)
            elif kind in ("advantage", "disadvantage"):
                if len(modes.get(_mode_signature(effect, aimed), ())) > 1:
                    continue  # opposing modes for this same forthcoming roll cancel
                family, value, opportunity = "condition_or_mode", _mode_value(effect, aimed), True
            elif kind == "reaction_denied":
                # The executor's text qualifier can narrow this to opportunity
                # attacks only, so score only that conservative floor.
                family, value = "condition_or_mode", 1 if _useful(effect, aimed, harmful=True) else 0
            elif kind == "expose" and _useful(effect, aimed, harmful=True):
                amount = numbers.get("pb", 0) if effect.get("bonus") == "pb" else _integer(effect.get("bonus"))
                family, value, opportunity = "next_bonus", 2 * max(0, amount), True
            elif kind == "next_damage_taken_bonus" and _useful(effect, aimed, harmful=True):
                amount = _integer(effect.get("amount")) + _formula(effect.get("formula"), numbers)
                family, value, opportunity = "next_bonus", max(0, amount), True
            elif kind == "save_bonus" and _useful(effect, aimed, harmful=False):
                # This block accepts flat/amount, not formula or dice.
                abilities = effect.get("abilities")
                if abilities and (not isinstance(abilities, list) or not all(isinstance(code, str) and code.upper() in _ABILITY_CODES for code in abilities)):
                    continue
                if effect.get("against") and not isinstance(effect.get("against"), list):
                    continue
                amount = _integer(effect.get("flat") or effect.get("amount"))
                family, value, opportunity = "next_bonus", 2 * max(0, amount), True
            elif kind == "forced_movement" and _useful(effect, aimed, harmful=True):
                family, who = "movement", _recipient(effect, aimed, defaults_to_target=True)
                value = max(0, _integer(effect.get("distance_ft"))) // 5
            elif kind == "movement" and effect.get("applies_to") in (None, "self") and effect.get("mode") != "teleport":
                distance = effect.get("distance_ft")
                value = 1 if distance in ("speed", "half_speed") else max(0, _integer(distance)) // 10
                if effect.get("no_opportunity_attacks") is True and (value > 0 or distance in (None, 0)):
                    value = max(1, value)
                family, who = "movement", _recipient(effect, aimed, defaults_to_target=False)
            elif kind == "speed":
                if effect.get("halved") is True or (type(effect.get("becomes")) is int and effect["becomes"] == 0):
                    family, amount, harmful = "movement", 4, True
                elif effect.get("becomes") is None:
                    amount = _integer(effect.get("amount") if effect.get("amount") is not None else effect.get("flat"))
                    harmful, amount = amount < 0, abs(amount) // 5
                    family = "movement"
                else:
                    continue
                who = _recipient(effect, aimed, defaults_to_target=harmful)
                value = amount if _useful(effect, aimed, harmful=harmful) else 0
            elif kind == "ready_counterstrike" and effect.get("applies_to") in (None, "self"):
                family, value, opportunity = "reaction_setup", 4, True
            if family and value > 0:
                points = Fraction(min(value, FAMILY_CAPS[family]))
                if opportunity:
                    points *= NEXT_OPPORTUNITY
                if family == "reaction_setup" and economy == "action":
                    points *= ACTION_PREPARATION
                if family == "movement":
                    moves = credit(moves, who or "", points)
                else:
                    families = merge(families, {family: points})
        return Bundle(families, moves)

    bundle = walk(typed.get("effects"), 0, target_kind)
    # One complete outcome at a time: a creature whose Speed a stop in that outcome
    # already removed cannot also earn movement credit from it, wherever in the
    # activation the stop and the movement row were written, and the family keeps
    # that outcome's strongest remaining movement. The outcomes are then averaged,
    # so two creatures moved in two exclusive outcomes each keep their own credit.
    mobility = sum((weight * outcome_value(key) for key, weight in bundle.moves.items()), Fraction())
    families = merge(bundle.families, {"movement": mobility}) if mobility else bundle.families
    return min(MAX_RIDER_UTILITY, int(sum(families.values(), Fraction())))
