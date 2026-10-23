"""S1/S2a Body Refining versions: printed key abilities, Stamina payment and combat riders.

Ownership is derived from the character's Paths, owned spheres and upgrade
Insights by ``factory_authoring.body_refining_variants`` and sealed here as one
passive row per owned sphere. Everything else is *data*: the generated authority
carries each variant's printed key ability, its CP->Stamina payment and a
flattened ``riders`` list. This module implements a small, general rider engine
(AC, save/check Advantage, Resistance, forced-movement reduction, Speed, prone
stand, Stamina-Guard-zero rewards, a start-of-turn Temporary HP grant and free
uses of an ability during Attack or Dash). Each rider is inert unless the actor
owns the variant row, so characters without the variant compile and fight
byte-identically.

The character's sheet-wide key ability is never changed, and the plug-in never
rewrites a talent's own options: it only supplies the numbers and the riders the
print names.
"""
from __future__ import annotations

from typing import Any

from . import hook
from .passive_rows import row_of
from factory_authoring import body_refining_variants as authority

BLOCK = "br_variant"
STAMINA = "resource:core.stamina"
_PATH_POOLS = ("resource:path.cp", "resource:core.cp", "resource:core.qi")
_ABILITY_MOD = {"CON": "con_mod", "STR": "str_mod", "DEX": "dex_mod"}


def _owned(engine: Any, actor_id: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, [])
            if row.get("block") == BLOCK]


def _riders(engine: Any, actor_id: str, kind: str | None = None) -> list[dict[str, Any]]:
    return [rider for row in _owned(engine, actor_id) for rider in row.get("riders") or []
            if kind is None or rider.get("kind") == kind]


def _cl(engine: Any, actor_id: str) -> int:
    rows = _owned(engine, actor_id)
    return int((rows[0].get("numbers") or {}).get("cl") or 1) if rows else 1


def _pb(engine: Any, actor_id: str) -> int:
    rows = _owned(engine, actor_id)
    return int((rows[0].get("numbers") or {}).get("pb") or 2) if rows else 2


# --------------------------------------------------------------------------- conditions
def _condition(actor: Any, name: str) -> bool:
    wanted = name.casefold()
    for condition in actor.conditions.values():
        data = condition.data or {}
        if str(data.get("name") or data.get("label") or "").casefold() == wanted:
            return True
        suffix = condition.condition_id.rsplit(".", 1)[-1]
        if suffix == wanted.replace(" ", "_"):
            return True
    return False


def _state(engine: Any, actor: Any, name: str) -> bool:
    from . import states

    return bool(states.active(engine, actor, name)) or _condition(actor, name)


def _zone(engine: Any, actor: Any, spec: str) -> bool:
    """A named area the actor stands in: "current:own", "fire", "ash", "sand:own", "darkness:own"."""
    from .. import zones

    words = spec.split(":")
    wanted, own = words[0], "own" in words[1:]
    for zone in (getattr(engine.state, "zones", {}) or {}).values():
        if not zone.active or not zones.actor_inside_zone(engine, actor, zone):
            continue
        if own and zone.owner_id != actor.entity_id:
            continue
        profile = zone.trigger_profile or {}
        text = " ".join([str(profile.get("name") or ""), *(str(t) for t in profile.get("terrain") or []),
                         str(profile.get("kind") or "")]).casefold()
        if wanted == "ash" and ("ash" in text or "smoke" in text or "burn" in text or "cinder" in text):
            return True
        if wanted in text:
            return True
    return False


def _when(engine: Any, actor: Any, tokens: Any, numbers: dict[str, Any]) -> bool:
    """Evaluate a rider's printed condition.

    Different kinds are ANDed; several ``state:``/``condition:``/``zone:``/
    ``light:`` entries are the printed alternatives ("Obsidian Skin, Furnace
    Mantle or Magma Armor", "inside Dim Light or your Darkness"), so any one of
    them is enough.
    """
    tokens = list(tokens or ("always",))
    required = True
    alternatives: list[bool] = []
    for token in tokens:
        if token == "always":
            continue
        if token == "focus":
            from .needle import FOCUS

            required = required and int(actor.resources.get(FOCUS) or 0) >= 1
        elif token == "below_half":
            required = required and int(actor.current_hp) * 2 < int(actor.maximum_hp)
        elif token.startswith("light:"):
            from . import light_level

            alternatives.append(light_level.level(engine, actor) == token[6:])
        elif token.startswith("state:"):
            alternatives.append(_state(engine, actor, token[6:]))
        elif token.startswith("condition:"):
            alternatives.append(_condition(actor, token[10:]))
        elif token.startswith("zone:"):
            alternatives.append(_zone(engine, actor, token[5:]))
        else:
            required = False
    return required and (any(alternatives) if alternatives else True)


def _rider_when(engine: Any, actor: Any, rider: dict[str, Any], numbers: dict[str, Any]) -> bool:
    if rider.get("min_cl") and _cl(engine, actor.entity_id) < int(rider["min_cl"]):
        return False
    return _when(engine, actor, rider.get("when"), numbers)


# --------------------------------------------------------------------------- ownership rows
@hook("compile_passives")
def seal_versions(passives, info):
    versions = authority.owned(info.get("owner_sheet") or {})
    if not versions:
        return passives
    numbers = dict(info.get("numbers") or {})
    sheet = info.get("owner_sheet") or {}
    rows = []
    for row in versions:
        rule = row.get("key_ability")
        chosen = authority.chosen_ability(row["sphere_id"], sheet)
        rekeyed = _numbers(dict(numbers), rule, sheet, chosen) if rule else None
        rows.append({"feature_id": row["id"], "block": BLOCK, "kind": row["sphere_id"], "ownership_only": True,
                     "key_ability": rule, "chosen_ability": chosen,
                     "named_dc": int((rekeyed or numbers).get("save_dc") or 0),
                     "payment": row.get("payment") or {},
                     "riders": [dict(rider) for rider in row.get("riders") or []],
                     "numbers": numbers,
                     "key_baseline": _baseline(numbers, rule, sheet)})
    return [*passives, *rows]


@hook("compile_bundle")
def seal_actor_numbers(bundle, info):
    if not authority.owned(info.get("owner_sheet") or {}):
        return None
    # Global queries must never infer the actor's key from the first re-keyed talent.
    return {**bundle, "actor_numbers": dict(info.get("numbers") or {})}


# --------------------------------------------------------------------------- key ability
def _applies(rule, mechanic, source=None):
    if not rule or rule.get("expression"):
        return False
    tags, names = set(rule.get("tags") or []), set(rule.get("names") or [])
    if tags or names:
        return (source in (rule.get("source_ids") or [])
                or bool(tags.intersection(mechanic.get("tags") or [])) or mechanic.get("name") in names)
    return True


def _baseline(numbers, rule, sheet):
    if (rule or {}).get("higher_than"):
        from combat.table_advance import current_scores
        scores = current_scores(sheet or {})
        return (int(scores.get(rule["higher_than"], 10)) - 10) // 2
    return int(numbers.get("key_mod") or 0)


def _ability_mod(numbers, ability, sheet):
    """The printed ability's modifier, preferring the compiled numbers then the sheet."""
    field = _ABILITY_MOD.get(str(ability).upper())
    if field and field in numbers:
        return int(numbers[field] or 0)
    from combat.table_advance import current_scores

    score = int(current_scores(sheet or {}).get(str(ability).upper(), 10))
    return (score - 10) // 2


def _numbers(numbers, rule, sheet=None, ability=None):
    ability = str(ability or rule.get("ability") or "CON").upper()
    target = _ability_mod(numbers, ability, sheet)
    key = int(numbers.get("key_mod") or 0)
    baseline = _baseline(numbers, rule, sheet)
    if rule.get("if_higher") and target <= baseline:
        return None
    new = dict(numbers)
    # Replace the ability component, not any recorded DC bonuses (same
    # semantics as Battle Musician). Ordinary unmodified DCs are 8 + PB + key.
    new["save_dc"] = int(numbers.get("save_dc") or 8 + int(numbers.get("pb") or 2) + key) - key + target
    if rule["scope"] != "save_dc_only":
        new["key_mod"] = target
        new["attack_bonus"] = int(numbers.get("attack_bonus") or 0) - key + target
    return new if new != numbers else None


def _row(source, info):
    mechanic = (info.get("mechanics") or {}).get(source) or info.get("mechanic") or {}
    sid = mechanic.get("sphere_id")
    if not sid or mechanic.get("kind") not in ("talent", "base_ability"):
        return None
    sheet = info.get("owner_sheet") or {}
    row = authority.selected(sid, sheet, require_owned=True)
    if row is None:
        return None
    return row, authority.chosen_ability(sid, sheet)


@hook("compile_action")
def talent_key(action, info):
    typed = (action.parameters or {}).get("typed") or {}
    source = typed.get("source")
    found = _row(source, info)
    if not found:
        return None
    row, ability = found
    mechanic = (info.get("mechanics") or {}).get(source) or {}
    rule = row["key_ability"]
    if not _applies(rule, mechanic, source):
        return None
    numbers = _numbers(dict(typed.get("numbers") or info.get("numbers") or {}), rule, info.get("owner_sheet"), ability)
    if numbers is None:
        return None
    return action.model_copy(update={"parameters": {**action.parameters, "typed": {**typed, "numbers": numbers}}})


@hook("compile_reaction")
def reaction_key(row, info):
    found = _row(row.get("feature_id"), info)
    if not found:
        return None
    version, ability = found
    if not _applies(version["key_ability"], info.get("mechanic") or {}, row.get("feature_id")):
        return None
    numbers = _numbers(dict(row.get("numbers") or info.get("numbers") or {}), version["key_ability"],
                       info.get("owner_sheet"), ability)
    return {**row, "numbers": numbers} if numbers is not None else None


@hook("named_save_dc")
def sphere_dc(engine, actor, sphere_id):
    """Only an owned, unconditional named-sphere rule can replace this DC.

    The value is sealed at compilation with the character's printed key choice,
    so a table commit/reload asks the same question and gets the same number.
    """
    row = row_of(engine, actor.entity_id, BLOCK, sphere_id)
    if row is None:
        return None
    rule = row.get("key_ability")
    if not _applies(rule, {}) or rule.get("tags") or rule.get("names"):
        return None
    sealed = row.get("named_dc")
    if sealed is None:
        numbers = row.get("numbers") or {}
        key = int(numbers.get("key_mod") or 0)
        con = int(numbers.get("con_mod") or 0)
        if rule.get("if_higher") and con <= int(row.get("key_baseline", key)):
            con = key
        return int(numbers.get("save_dc") or 8 + int(numbers.get("pb") or 2) + key) - key + con
    return int(sealed)


# --------------------------------------------------------------------------- CP -> Stamina
@hook("payment_substitution")
def variant_payment(engine: Any, actor: Any, source: str, costs: Any, missing: Any) -> Any:
    """Spend Stamina instead of the Path pool for an owned variant's sphere talents."""
    from ..alternative_payments import PaymentAlternative
    from ..factory_compiler import PATH_POOLS

    rows = _owned(engine, actor.entity_id)
    if not rows:
        return None
    action = engine.action_catalog.get(source)
    if action is None or action.owner_id != actor.entity_id:
        return None
    typed = (action.parameters or {}).get("typed") or {}
    sphere = typed.get("sphere")
    row = next((r for r in rows if r.get("kind") == sphere and (r.get("payment") or {}).get("with") == STAMINA), None)
    if row is None:
        return None
    stamina = int(actor.resources.get(STAMINA) or 0)
    covered: dict[str, int] = {}
    for resource, amount in (costs or {}).items():
        # A CP cost is the character's Path pool; Stamina may not pay for itself.
        if resource in PATH_POOLS and resource != STAMINA and int(amount) > 0 and stamina >= int(amount):
            covered[resource] = int(amount)
    if not covered or any(resource not in covered for resource in (missing or ())):
        return None
    return PaymentAlternative(row["feature_id"], f"Body Refining: spend Stamina instead of CP",
                              tuple(covered.items()), costs=((STAMINA, sum(covered.values())),))


# --------------------------------------------------------------------------- riders
@hook("ac")
def rider_ac(engine: Any, target: Any) -> int | None:
    total = sum(int(r.get("amount") or 0) for r in _riders(engine, target.entity_id, "ac")
                if _rider_when(engine, target, r, {}))
    return total or None


@hook("save")
def rider_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    modes = []
    tags = {str(tag).casefold() for tag in named or ()}
    for rider in _riders(ctx.engine, subject.entity_id, "save_advantage"):
        on = {str(word).casefold() for word in rider.get("on") or []}
        if on.intersection(tags) or str(ability).casefold() in on:
            if _rider_when(ctx.engine, subject, rider, {}):
                modes.append("ADVANTAGE")
    return {"bonus": 0, "modes": modes} if modes else None


@hook("ability_check_mode")
def rider_checks(engine: Any, actor: Any, ability: str, skill: str, against_creature: Any) -> str | None:
    words = {str(ability or "").casefold(), str(skill or "").casefold()}
    for rider in _riders(engine, actor.entity_id, "check_advantage"):
        on = {str(word).casefold() for word in rider.get("on") or []}
        if on.intersection(words) and _rider_when(engine, actor, rider, {}):
            return "ADVANTAGE"
    return None


@hook("damage_defenses")
def rider_resistance(engine: Any, target: Any, damage_type: Any, typed: Any, source_actor_id: Any) -> list | None:
    kind = str(damage_type or "").upper()
    for rider in _riders(engine, target.entity_id, "resistance"):
        if kind in {str(t).upper() for t in rider.get("types") or []} and _rider_when(engine, target, rider, {}):
            return [{"kind": "resistance", "damage_types": [kind]}]
    return None


@hook("forced_movement_reduction")
def rider_forced_movement(ctx: Any, subject: Any) -> int:
    return sum(int(rider.get("feet") or 0) for rider in _riders(ctx.engine, subject.entity_id, "forced_movement_reduction")
               if _rider_when(ctx.engine, subject, rider, {})) or 0


@hook("speed")
def rider_speed(engine: Any, actor: Any) -> int | None:
    total = sum(int(rider.get("feet") or 0) for rider in _riders(engine, actor.entity_id, "speed")
                if _rider_when(engine, actor, rider, {}))
    return total or None


@hook("stand_cost")
def rider_stand(engine: Any, actor: Any, normal_cost: int) -> int | None:
    if any(_rider_when(engine, actor, rider, {}) for rider in _riders(engine, actor.entity_id, "stand_cost_zero")):
        return 0
    return None


@hook("turn_start")
def rider_turn_start(engine: Any, actor: Any) -> None:
    """A start-of-turn Temporary HP grant with a once-per-fight marker (printed once per short rest)."""
    for rider in _riders(engine, actor.entity_id, "temp_hp"):
        if rider.get("trigger") != "turn_start" or not _rider_when(engine, actor, rider, {}):
            continue
        marker = "condition:typed.br_variant_temp"
        if any(c.condition_id == marker for c in actor.conditions.values()):
            continue
        amount = _pb(engine, actor.entity_id) if rider.get("formula") == "pb" else int(rider.get("amount") or 0)
        if amount <= 0:
            continue
        row = next(row for row in _owned(engine, actor.entity_id) if rider in (row.get("riders") or []))
        engine._grant_temp_hp(actor, amount, row["feature_id"], actor.entity_id)
        engine._apply_condition(actor, marker, row["feature_id"], actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Body Refining Temporary HP used"})


def _regain_focus(engine: Any, actor: Any, source: str) -> None:
    from .needle import regain_focus

    regain_focus(engine, actor, source, "Body Refining guard reward")


@hook("event")
def rider_guard_zero(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Stamina Guard reduced a real packet to 0: printed second benefits."""
    if event_type != "REACTION_RESOLVED":
        return
    payload = kwargs.get("payload") or {}
    if payload.get("pending_after") != 0 or "spend" not in payload:
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None or not actor.active:
        return
    for rider in _riders(engine, actor.entity_id, "guard_zero"):
        if not _rider_when(engine, actor, rider, {}):
            continue
        row = next(row for row in _owned(engine, actor.entity_id) if rider in (row.get("riders") or []))
        flag = f"br_guard_{rider['clause']}"
        if rider.get("limit") == "round" and actor.turn_flags.get(flag) == engine.state.round_number:
            continue
        effect = rider.get("effect")
        if effect == "regain_martial_focus":
            _regain_focus(engine, actor, row["feature_id"])
        elif effect == "temp_hp":
            engine._grant_temp_hp(actor, _pb(engine, actor.entity_id), row["feature_id"], actor.entity_id)
        elif effect == "regain_hp":
            amount = _pb(engine, actor.entity_id)
            actor.current_hp = min(int(actor.maximum_hp), int(actor.current_hp) + amount)
            engine._append_event("HEALING_APPLIED", row["feature_id"], actor_id=actor.entity_id,
                                 payload={"amount": amount, "hp_after": int(actor.current_hp)})
        elif effect == "regain_stamina":
            pool = int(actor.resources.get(STAMINA) or 0)
            actor.resources[STAMINA] = pool + _pb(engine, actor.entity_id)
            engine._append_event("RESOURCE_GAINED", row["feature_id"], actor_id=actor.entity_id,
                                 payload={"resource_id": STAMINA, "amount": _pb(engine, actor.entity_id)})
        else:
            continue
        if rider.get("limit") == "round":
            actor.turn_flags[flag] = engine.state.round_number


# --------------------------------------------------------------------------- Bone-Axe Body: Hewing Strike follow-up
# Clause 5: "when you use Hewing Strike after moving at least 10 feet, you may add your Proficiency Bonus to one
# Strength (Athletics) check made before the start of your next turn to shove, drag, climb, hold, break, or contest
# a target bearing Bite". The trigger is the Hewing Strike technique after 10 feet of committed movement this turn
# (beauty_motion). The armed flag is keyed to this turn, so it ends when the next turn starts. The bonus is granted
# once: the d20_bonus hook spends the flag when it adds the bonus.
HEWING = "TAL_AXES_HEWING_STRIKE"
HEWING_FLAG = "br_hewing_athletics"


def _hewing_rider(engine: Any, actor_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for row in _owned(engine, actor_id):
        for rider in row.get("riders") or []:
            if rider.get("kind") == "hewing_athletics":
                return row, rider
    return None


@hook("technique_used")
def arm_hewing_follow_up(ctx: Any) -> None:
    from .beauty_motion import moved_this_turn

    if (ctx.typed or {}).get("source") != HEWING:
        return
    found = _hewing_rider(ctx.engine, ctx.actor.entity_id)
    if found is None:
        return
    if moved_this_turn(ctx.engine, ctx.actor) >= int(found[1].get("feet") or 10):
        ctx.actor.turn_flags[HEWING_FLAG] = _turn_key(ctx.engine, ctx.actor)


@hook("d20_bonus")
def hewing_athletics_bonus(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    from ..typed_executor import bears_mark

    context = engine.d20_context(roll) or {}
    if context.get("kind") != "check" or context.get("skill") != "Athletics" or context.get("ability") != "STR":
        return None
    actor = engine.state.actors.get(roll.actor_id)
    found = _hewing_rider(engine, roll.actor_id) if actor is not None else None
    if found is None or actor.turn_flags.get(HEWING_FLAG) != _turn_key(engine, actor):
        return None
    target = engine.state.actors.get(context.get("target_id") or "")
    if target is None or not bears_mark(target, actor.entity_id, str(found[1].get("mark") or "Bite")):
        return None
    bonus = _pb(engine, actor.entity_id)
    actor.turn_flags[HEWING_FLAG] = "spent"
    return {"source_id": found[0]["feature_id"], "bonus": bonus} if bonus else None


# --------------------------------------------------------------------------- free uses
# "When you take the Attack action or Dash action, you may use Gather Current as
# part of the same action once per turn" (Air) and the same clause for Gather
# Charge (Lightning). combat/ext/free_uses.py owns sibling-action building and
# the once-per-turn spend; this plug-in only declares the printed grant and the
# "after Attack or Dash" gate.
ATTACK_OR_DASH = "br_variant_attack_or_dash"
ATTACK_MARK = "br_variant_attacked"
_ATTACK_OR_DASH_SOURCES = frozenset({"system:combat.dash", "action:core.dash", "action:core.attack", "system:combat.attack"})


def _turn_key(engine: Any, actor: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_slot_index}:{actor.entity_id}"


def _attack_or_dash_taken(engine: Any, actor: Any) -> bool:
    return str(actor.turn_flags.get(ATTACK_MARK) or "") == _turn_key(engine, actor)


def _free_use_declarations(info: dict[str, Any]) -> list[dict[str, Any]]:
    sheet = info.get("owner_sheet") or {}
    out = []
    for row in authority.owned(sheet):
        for rider in row.get("riders") or []:
            if rider.get("kind") == "free_use":
                out.append({"state": f"br_variant:{row['id']}", "title": row.get("picker_label") or "Body Refining variant",
                            "always": True,
                            "requires": ATTACK_OR_DASH, "once": rider.get("once") or "turn",
                            "of": list(rider.get("of") or []),
                            "key": f"{row['id']}:{rider['clause']}",
                            "label": rider.get("label") or f"Use {' or '.join(rider.get('of') or [])}"})
    return out


@hook("action_completed")
def mark_attack_or_dash(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    """Remember that this turn has taken the Attack or Dash action (the free-use gate reads it).

    Ordinary Attack and Dash are economy Actions, not typed techniques, so they never reach
    ``technique_used``; ``action_completed`` is the general seam that runs after them (review BRS1F7R finding 1).
    """
    action = (getattr(engine, "action_catalog", None) or {}).get(source_definition_id)
    name = str(getattr(action, "display_name", "") or "").casefold()
    source = str(source_definition_id or "").casefold()
    if name in ("attack", "dash") or source in _ATTACK_OR_DASH_SOURCES:
        actor.turn_flags[ATTACK_MARK] = _turn_key(engine, actor)


def free_use_available(engine: Any, actor: Any, rule: dict[str, Any]) -> bool:
    """Public: read whether the compiled free-use copy is offered (used by tests)."""
    from . import free_uses

    return free_uses.available(engine, actor, rule)


def mark_free_use_spent(engine: Any, actor: Any, grant: dict[str, Any]) -> None:
    """Public: record the once-per-turn free use as spent (used by tests)."""
    from . import free_uses

    free_uses.mark_spent(engine, actor, grant)


def _install_free_uses() -> None:
    from . import free_uses

    free_uses.register_predicate(ATTACK_OR_DASH, _attack_or_dash_taken)
    free_uses.register(_free_use_declarations)


_install_free_uses()
