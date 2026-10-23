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
FOCUS = "resource:core.martial_focus"
_PATH_POOLS = ("resource:path.cp", "resource:core.cp", "resource:core.qi")
_ABILITY_MOD = {"CON": "con_mod", "STR": "str_mod", "DEX": "dex_mod"}

# The engine's own Coordinated Movement Focus grant (combat/motion.py after_action) and the shared typed
# condition ids these riders reuse. No new hook point: state_event, event, attack_mode, attack_damage,
# attack_damage_bonus, falling_damage, speed and the guard-zero event are all documented seams.
COORDINATED_FOCUS_SOURCE = "passive:ATHLETICS_BASE_COORDINATED_MOVEMENT"
STAMINA_SPENT_FLAG = "br_stamina_spent_turn"
TEMPERED_SPEED_FLAG = "br_tempered_speed_turn"
FALLING_CONDITION = "condition:typed.br_falling_reduction"
BATTER_CONDITION = "condition:typed.br_batter_advantage"
CHECK_CONDITION = "condition:typed.check_mode"


def _owned(engine: Any, actor_id: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, [])
            if row.get("block") == BLOCK]


def _riders(engine: Any, actor_id: str, kind: str | None = None) -> list[dict[str, Any]]:
    return [rider for row in _owned(engine, actor_id) for rider in row.get("riders") or []
            if kind is None or rider.get("kind") == kind]


def _row_of_rider(engine: Any, actor_id: str, rider: dict[str, Any]) -> dict[str, Any]:
    return next(row for row in _owned(engine, actor_id) if rider in (row.get("riders") or []))


def _source_matches(source: Any, wanted: Any) -> bool:
    """A compiled talent id, an option copy of it, or a display-name word list."""
    text = str(source or "")
    for word in wanted or ():
        word = str(word)
        if not word:
            continue
        if text == word or text.startswith(word + "#") or text.startswith(word + ".") or text.endswith("." + word):
            return True
    return False


def _nearest_hostile(engine: Any, actor: Any, radius_ft: int) -> Any | None:
    """The closest active creature of another team within the printed radius, or None."""
    best = None
    for other in (getattr(engine.state, "actors", {}) or {}).values():
        if other is actor or not getattr(other, "active", False) or other.team_id == actor.team_id:
            continue
        if engine._distance_actor_to_actor(actor, other) > int(radius_ft):
            continue
        key = (engine._distance_actor_to_actor(actor, other), other.entity_id)
        if best is None or key < best[0]:
            best = (key, other)
    return best[1] if best else None


def _has_condition(actor: Any, condition_id: str) -> bool:
    return any(c.condition_id == condition_id for c in actor.conditions.values())


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
    # A chosen printed option: the condition names the save categories it covers.
    for held in subject.conditions.values():
        data = held.data or {}
        if held.condition_id != SAVE_CONDITION:
            continue
        wanted = {str(word).casefold() for word in data.get("on") or []}
        if wanted and not wanted.intersection(tags):
            continue
        if (data.get("rule") or {}).get("save_mode", {}).get(str(ability).upper()) == "ADVANTAGE":
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
    total = sum(int(rider.get("feet") or 0) for rider in _riders(ctx.engine, subject.entity_id, "forced_movement_reduction")
                if _rider_when(ctx.engine, subject, rider, {}))
    # A chosen printed option ("reduce forced movement by 5/10 feet") lives in a timed condition.
    total += sum(int((held.data or {}).get("feet") or 0) for held in subject.conditions.values()
                 if held.condition_id == FORCED_CONDITION)
    return total or 0


@hook("speed")
def rider_speed(engine: Any, actor: Any) -> int | None:
    total = sum(int(rider.get("feet") or 0) for rider in _riders(engine, actor.entity_id, "speed")
                if _rider_when(engine, actor, rider, {}))
    # Athletics Tempered Motion: "if you spend at least 1 Stamina during the same turn, increase land
    # Speed by 5 feet until the end of the turn." Both halves are the same turn key, so the benefit
    # cannot leak into another turn.
    key = _turn_key(engine, actor)
    if (actor.turn_flags.get(TEMPERED_SPEED_FLAG) == key
            and actor.turn_flags.get(STAMINA_SPENT_FLAG) == key):
        total += sum(int(rider.get("feet") or 5) for rider in _riders(engine, actor.entity_id, "tempered_motion")
                     if rider.get("effect") == "speed_on_stamina" and _rider_when(engine, actor, rider, {}))
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
        # "cannot gain them again until completing a short rest": a rest-scoped marker the engine's
        # short_rest seam ends (combat/gate2_engine.py), never a fight-lifetime one.
        engine._apply_condition(actor, marker, row["feature_id"], actor.entity_id, expires_on="UNTIL_SHORT_REST",
                                data={"label": "Body Refining Temporary HP used (restored by a short rest)"})


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
        elif effect == "next_attack_advantage":
            # Berserker: "gain Advantage on your next Batter attack before the end of your next turn."
            # The condition names the Batter talents; attack_mode consumes it on that attack only.
            engine._apply_condition(actor, BATTER_CONDITION, row["feature_id"], actor.entity_id,
                                    expires_on="END_OF_HOLDER_NEXT_TURN",
                                    data={"label": rider.get("label") or "Advantage on your next Batter attack",
                                          "sources": list(rider.get("sources") or [])})
        elif effect == "apply_condition":
            target = _nearest_hostile(engine, actor, int(rider.get("radius_ft") or 5))
            if target is not None:
                engine._apply_condition(target, str(rider["condition"]), row["feature_id"], actor.entity_id,
                                        expires_on=str(rider.get("expires_on") or "END_OF_HOLDER_NEXT_TURN"),
                                        data={"label": rider.get("label") or str(rider["condition"])})
        elif effect == "save_pulse":
            target = _nearest_hostile(engine, actor, int(rider.get("radius_ft") or 10))
            if target is not None:
                dc = int(row.get("named_dc") or (row.get("numbers") or {}).get("save_dc") or 10)
                roll = engine._roll_save(target, str(rider.get("ability") or "CON"), dc, row["feature_id"])
                if int(getattr(roll, "total", 0)) < dc:
                    from ..typed_executor import mark_condition_id

                    engine._apply_condition(target, mark_condition_id(str(rider.get("mark") or "Resonance"),
                                                                      actor.entity_id),
                                            row["feature_id"], actor.entity_id,
                                            expires_on="START_OF_SELF_NEXT_TURN",
                                            data={"label": rider.get("label") or f"{rider.get('mark')} until the start of your next turn"})
        elif effect == "free_move":
            feet = int(rider.get("feet") or 5)
            actor.movement_remaining_ft = int(getattr(actor, "movement_remaining_ft", 0) or 0) + feet
            actor.turn_flags["oa_free_ft"] = int(actor.turn_flags.get("oa_free_ft") or 0) + feet
            engine._append_event("MOVEMENT_GRANTED", row["feature_id"], actor_id=actor.entity_id,
                                 payload={"distance_ft": feet})
        elif effect == "remnant":
            _leave_remnant(engine, actor, row)
        elif effect == "free_attack":
            # The compiled no-Action copy is offered for this round and spent by action_completed.
            actor.turn_flags[f"{GUARD_ATTACK}_{rider.get('clause')}"] = engine.state.round_number
        else:
            continue
        if rider.get("limit") == "round":
            actor.turn_flags[flag] = engine.state.round_number


def _leave_remnant(engine: Any, actor: Any, row: dict[str, Any]) -> None:
    """Ash: "create one Remnant in your space" -- the Ash sphere's own placed Ash Terrain marker."""
    from .. import zones
    from . import ash_core, placed

    terrain = (zones.terrain_rules().get("terrains") or {}).get("ash terrain") or {}
    placed.place(engine, actor, source=row["feature_id"], tag=ash_core.TAG, cells=[actor.position],
                 name="Remnant (Ash Terrain)", duration_rounds=10, color=terrain.get("color"),
                 material=terrain.get("material") or "ash", terrain=["ash terrain"], difficult="hostile",
                 obscured=terrain.get("obscured") or "light", numbers=dict(row.get("numbers") or {}),
                 extra={"move_through": dict(terrain.get("move_through") or {}) or None})
    mine = placed.of(engine, ash_core.TAG, owner_id=actor.entity_id)
    while len(mine) > _pb(engine, actor.entity_id):
        placed.drop(engine, mine.pop(0), "REMNANT_LIMIT")


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


# =========================================================================== S2b printed combat riders
# Every rider below is data from authority/body_refining/variant_riders.json. Each subscriber reads an
# owned variant row first, so characters without the variant compile and fight byte-identically.
def _sheet_riders(info: dict[str, Any], kind: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(row, rider) pairs of one kind from the sheet being compiled; no engine state needed."""
    return [(row, rider) for row in authority.owned(info.get("owner_sheet") or {})
            for rider in row.get("riders") or [] if rider.get("kind") == kind]


# --------------------------------------------------------------- Athletics: Tempered Motion (clauses 0-3)
@hook("state_event")
def tempered_motion_focus(engine: Any, event: Any) -> None:
    """Coordinated Movement regained Martial Focus: apply the three printed timed benefits.

    ``state_event`` is the documented lifecycle seam; the event is the engine's own RESOURCE_GAINED, so
    no second grant path exists. Benefits are conditions with engine-removed expiry names.
    """
    if getattr(event, "event_type", "") != "RESOURCE_GAINED" \
            or getattr(event, "source_definition_id", "") != COORDINATED_FOCUS_SOURCE:
        return
    payload = event.payload or {}
    if payload.get("resource_id") != FOCUS or int(payload.get("gained") or 0) <= 0:
        return
    actor = engine.state.actors.get(getattr(event, "actor_id", ""))
    if actor is None or not _owned(engine, actor.entity_id):
        return
    key = _turn_key(engine, actor)
    if actor.turn_flags.get(TEMPERED_SPEED_FLAG) == key:
        return  # one printed regain per turn (Focus is regained only when absent)
    for rider in _riders(engine, actor.entity_id, "tempered_motion"):
        if not _rider_when(engine, actor, rider, {}):
            continue
        row = _row_of_rider(engine, actor.entity_id, rider)
        effect = rider.get("effect")
        if effect == "falling_reduction":
            engine._apply_condition(actor, FALLING_CONDITION, row["feature_id"], actor.entity_id,
                                    expires_on="START_OF_SELF_NEXT_TURN",
                                    data={"label": "Tempered Motion: falling damage reduced until the start of your next turn",
                                          "reduction": int(rider.get("per_pb") or 5) * _pb(engine, actor.entity_id)})
        elif effect == "check_advantage":
            engine._apply_condition(actor, CHECK_CONDITION, row["feature_id"], actor.entity_id,
                                    expires_on="END_OF_HOLDER_NEXT_TURN",
                                    data={"rule": {"check_mode": {"Athletics": "ADVANTAGE"}}, "br_variant_check": True,
                                          "used": False,
                                          "label": "Tempered Motion: Advantage on one Strength (Athletics) check before the end of your next turn"})
        elif effect == "speed_on_stamina":
            actor.turn_flags[TEMPERED_SPEED_FLAG] = key


@hook("event")
def note_stamina_spend(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Remember that this turn spent Stamina (Tempered Motion's Speed benefit reads it)."""
    if event_type != "RESOURCE_SPENT":
        return
    payload = kwargs.get("payload") or {}
    if payload.get("resource_id") != STAMINA or int(payload.get("amount") or 0) <= 0:
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None or not any(rider.get("effect") == "speed_on_stamina"
                               for rider in _riders(engine, actor.entity_id, "tempered_motion")):
        return
    actor.turn_flags[STAMINA_SPENT_FLAG] = _turn_key(engine, actor)


@hook("falling_damage")
def tempered_falling_damage(engine: Any, target: Any, defended: int, fall: Any, intent: Any) -> dict[str, Any] | None:
    """Tempered Motion: "reduce falling damage by 5 x Proficiency Bonus until the start of your next turn"."""
    held = next((c for c in target.conditions.values() if c.condition_id == FALLING_CONDITION), None)
    if held is None:
        return None
    reduction = int((held.data or {}).get("reduction") or 0)
    return {"amount": max(0, int(defended) - reduction)} if reduction else None


@hook("event")
def consume_tempered_check(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The printed "one Strength (Athletics) check": spend the Advantage when that check is rolled."""
    if event_type != "CHECK_ROLLED":
        return
    from .roll_context import check_skill_receipts

    for actor_id, _roll, skill in check_skill_receipts(kwargs):
        actor = engine.state.actors.get(actor_id)
        if actor is None or str(skill or "").replace("_", " ").casefold() != "athletics":
            continue
        for held in list(actor.conditions.values()):
            data = held.data or {}
            if held.condition_id != CHECK_CONDITION or not data.get("br_variant_check") or data.get("used"):
                continue
            engine._remove_condition_instance(actor, held.instance_id, "br_variants:check_used")
            engine._apply_condition(actor, CHECK_CONDITION, held.source_definition_id, held.source_actor_id,
                                    expires_on=held.expires_on, data={**data, "used": True, "rule": {}})


# --------------------------------------------------------------- Berserker: Batter Advantage (clause 3)
@hook("attack_mode")
def batter_advantage(ctx: Any, target: Any) -> str | None:
    """Berserker: the armed Advantage applies to the next Batter attack only, then is spent."""
    actor = ctx.actor
    held = next((c for c in actor.conditions.values() if c.condition_id == BATTER_CONDITION), None)
    if held is None:
        return None
    sources = (held.data or {}).get("sources") or []
    source = (ctx.typed or {}).get("source") or (ctx.typed or {}).get("option_of")
    if not _source_matches(source, sources):
        return None
    ctx.engine._remove_condition_instance(actor, held.instance_id, held.source_definition_id)
    return "ADVANTAGE"


# --------------------------------------------------------------- once-per-turn talent damage riders
@hook("attack_damage_bonus")
def talent_damage_bonus(ctx: Any, target: Any, effect: dict[str, Any]) -> int | None:
    """Dream Needle / Glass Shard / Monkey Link: "once per turn, add your Constitution modifier"."""
    source = (ctx.typed or {}).get("source") or (ctx.typed or {}).get("option_of")
    numbers = ctx.numbers or {}
    for rider in _riders(ctx.engine, ctx.actor.entity_id, "talent_damage_bonus"):
        if not _source_matches(source, rider.get("sources")) or not _rider_when(ctx.engine, ctx.actor, rider, {}):
            continue
        if rider.get("if_included") == "skip" and int(numbers.get("key_mod") or 0) == int(numbers.get("con_mod") or 0):
            return None  # "if it is not already included"
        key = f"br_damage_{rider.get('clause')}"
        if rider.get("once") == "turn" and ctx.actor.turn_flags.get(key) == _turn_key(ctx.engine, ctx.actor):
            return None
        if rider.get("amount") == "pb":
            amount = _pb(ctx.engine, ctx.actor.entity_id)
        elif rider.get("amount") == "con_mod":
            amount = int(numbers.get("con_mod") if numbers.get("con_mod") is not None else numbers.get("key_mod") or 0)
        else:
            amount = int(numbers.get("key_mod") or 0)
        if amount <= 0:
            return None
        ctx.actor.turn_flags[key] = _turn_key(ctx.engine, ctx.actor)
        return amount
    return None


@hook("attack_damage")
def talent_damage_die(ctx: Any, dice: Any) -> Any:
    """Monkey Style Vaulting Strike: "deals 1d10 extra damage instead of 1d8" (its own bonus row)."""
    from ..gate2_runtime_models import DiceSpec

    if not isinstance(dice, DiceSpec) or getattr(ctx, "weapon_damage_dice", False):
        return None
    source = (ctx.typed or {}).get("source") or (ctx.typed or {}).get("option_of")
    for rider in _riders(ctx.engine, ctx.actor.entity_id, "talent_damage_die"):
        if not _source_matches(source, rider.get("sources")) or not _rider_when(ctx.engine, ctx.actor, rider, {}):
            continue
        if int(dice.count) != int(rider.get("from_count") or 1) or int(dice.sides) != int(rider.get("from_sides") or 8):
            continue
        return dice.model_copy(update={"sides": int(rider.get("to_sides") or 10)})
    return None


# --------------------------------------------------------------- printed "choose one benefit" riders
# A single general prompt: the rider names its trigger, the talents it answers and up to four typed
# options. Humans and AI seats use the shared needle.ask chooser (rule 9/15); the choice is journaled
# and once per turn, and every option is a real engine effect, never a note.
FORCED_CONDITION = "condition:typed.br_forced_reduction"
SAVE_CONDITION = "condition:typed.br_save_advantage"
_OPTION_EFFECTS = frozenset({"temp_hp", "falling_reduction", "save_advantage", "forced_movement_reduction",
                             "check_advantage", "ac", "speed", "free_step", "stand", "arm"})


def _apply_choice(engine: Any, actor: Any, row: dict[str, Any], rider: dict[str, Any], option: dict[str, Any]) -> None:
    effect = str(option.get("effect") or "")
    source = row["feature_id"]
    label = str(option.get("label") or effect)
    if effect == "temp_hp":
        engine._grant_temp_hp(actor, _pb(engine, actor.entity_id), source, actor.entity_id)
    elif effect == "falling_reduction":
        engine._apply_condition(actor, FALLING_CONDITION, source, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                                data={"label": label, "reduction": int(option.get("per_pb") or 5) * _pb(engine, actor.entity_id)})
    elif effect == "save_advantage":
        abilities = [str(a).upper() for a in option.get("abilities") or ["STR", "DEX", "CON"]]
        engine._apply_condition(actor, SAVE_CONDITION, source, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                                data={"rule": {"save_mode": {ability: "ADVANTAGE" for ability in abilities}},
                                      "on": list(option.get("on") or []), "label": label})
    elif effect == "forced_movement_reduction":
        engine._apply_condition(actor, FORCED_CONDITION, source, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                                data={"feet": int(option.get("feet") or 5), "label": label})
    elif effect == "check_advantage":
        skill = str(option.get("skill") or "Athletics")
        engine._apply_condition(actor, CHECK_CONDITION, source, actor.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                                data={"rule": {"check_mode": {skill: "ADVANTAGE"}}, "br_variant_check": True,
                                      "used": False, "label": label})
    elif effect == "ac":
        engine._add_modifier(actor, source, "armor_class", "ADD", int(option.get("amount") or 1), "ALL_ATTACKS",
                             expires_on="START_OF_SELF_NEXT_TURN")
    elif effect == "speed":
        engine._add_modifier(actor, source, "speed_ft", "ADD", int(option.get("feet") or 5), "ALL_MOVEMENT",
                             expires_on="END_OF_CURRENT_TURN")
    elif effect == "free_step":
        feet = int(option.get("feet") or 5)
        actor.movement_remaining_ft = int(getattr(actor, "movement_remaining_ft", 0) or 0) + feet
        actor.turn_flags["oa_free_ft"] = int(actor.turn_flags.get("oa_free_ft") or 0) + feet
        engine._append_event("MOVEMENT_GRANTED", source, actor_id=actor.entity_id, payload={"distance_ft": feet})
    elif effect == "stand":
        from .. import posture

        posture.stand_up(engine, actor, cost=0, source_id=source)
    elif effect == "arm":
        actor.turn_flags[f"br_pick_{rider.get('clause')}"] = str(option.get("key") or "")
    else:
        return
    if effect not in ("arm", "stand"):  # both already write their own log/state
        from . import note

        note(engine, source, actor, f"{actor.display_name}: {label}.")


def _offer_choice(engine: Any, actor: Any, row: dict[str, Any], rider: dict[str, Any], *, action_name: str = "") -> None:
    key = f"br_choice_{rider.get('clause')}"
    if actor.turn_flags.get(key) == _turn_key(engine, actor):
        return
    options = [o for o in rider.get("options") or [] if str(o.get("effect") or "") in _OPTION_EFFECTS]
    if not options:
        return
    from .needle import ask, checkpoint_id

    names = [str(o.get("key") or o.get("effect")) for o in options]
    labels = {str(o.get("key") or o.get("effect")): str(o.get("label") or o.get("effect")) for o in options}
    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, key, actor.entity_id), actor, "choice:br_variant." + key, names,
                 labels=labels, preferred=names[:1],
                 prompt=(f"{row.get('feature_id', '').split('.')[-1].replace('-', ' ').title()}: choose one benefit"
                         + (f" after {action_name}" if action_name else "") + "."),
                 name=str(rider.get("name") or row.get("feature_id", "").split(".")[-1].replace("-", " ").title()),
                 feature_id=row["feature_id"])
    actor.turn_flags[key] = _turn_key(engine, actor)
    actor.turn_flags[f"br_pick_{rider.get('clause')}"] = ""
    picked = next((o for o in options if str(o.get("key") or o.get("effect")) == (chosen[0] if chosen else None)), None)
    if picked is not None:
        _apply_choice(engine, actor, row, rider, picked)


@hook("technique_used")
def choice_after_technique(ctx: Any) -> None:
    source = (ctx.typed or {}).get("source") or (ctx.typed or {}).get("option_of")
    for rider in _riders(ctx.engine, ctx.actor.entity_id, "choice"):
        if rider.get("trigger") != "technique" or not _source_matches(source, rider.get("sources")):
            continue
        if not _rider_when(ctx.engine, ctx.actor, rider, {}):
            continue
        if rider.get("moved_max_ft") is not None:
            from .beauty_motion import moved_this_turn

            if moved_this_turn(ctx.engine, ctx.actor) > int(rider["moved_max_ft"]):
                continue
        _offer_choice(ctx.engine, ctx.actor, _row_of_rider(ctx.engine, ctx.actor.entity_id, rider), rider,
                      action_name=str(getattr(ctx.action, "display_name", "") or ""))


@hook("turn_start")
def choice_at_turn_start(engine: Any, actor: Any) -> None:
    for rider in _riders(engine, actor.entity_id, "choice"):
        if rider.get("trigger") != "turn_start" or not _rider_when(engine, actor, rider, {}):
            continue
        if rider.get("requires_claim_on_body"):
            from . import verdant_chassis

            if not any((obj.component or {}).get("on") == actor.entity_id
                       for obj in verdant_chassis.claims(engine, actor)):
                continue
        _offer_choice(engine, actor, _row_of_rider(engine, actor.entity_id, rider), rider)


@hook("forced_movement_distance")
def force_choice_push(ctx: Any, subject: Any, effect: dict[str, Any], maximum_ft: int) -> int | None:
    """Force-Tempered: the chosen "+5 feet" of Body-Conducted Impact's push."""
    source = (ctx.typed or {}).get("source") or (ctx.typed or {}).get("option_of")
    for rider in _riders(ctx.engine, ctx.actor.entity_id, "choice"):
        if rider.get("trigger") != "technique" or not _source_matches(source, rider.get("sources")):
            continue
        if ctx.actor.turn_flags.get(f"br_choice_{rider.get('clause')}") != _turn_key(ctx.engine, ctx.actor):
            continue
        if ctx.actor.turn_flags.get(f"br_pick_{rider.get('clause')}") != str(rider.get("push_option") or "push"):
            continue
        return int(maximum_ft) + int(rider.get("push_feet") or 5)
    return None


@hook("deal_bonus")
def force_choice_damage(ctx: Any, subject: Any, amount: int) -> int | None:
    """Force-Tempered: the chosen "+ Constitution modifier to one damage roll"."""
    source = (ctx.typed or {}).get("source") or (ctx.typed or {}).get("option_of")
    for rider in _riders(ctx.engine, ctx.actor.entity_id, "choice"):
        if rider.get("trigger") != "technique" or not _source_matches(source, rider.get("sources")):
            continue
        if ctx.actor.turn_flags.get(f"br_choice_{rider.get('clause')}") != _turn_key(ctx.engine, ctx.actor):
            continue
        if ctx.actor.turn_flags.get(f"br_pick_{rider.get('clause')}") != str(rider.get("damage_option") or "damage"):
            continue
        # "to one damage roll": this delivery is that one roll.
        ctx.actor.turn_flags[f"br_pick_{rider.get('clause')}"] = "spent"
        return int((ctx.numbers or {}).get("con_mod") or 0) or None
    return None


# --------------------------------------------------------------- guard-zero free attack
# "once per round when Stamina Guard reduces damage to 0, make one ranged weapon attack ..." (Barrage) and
# "make one Unarmed Strike against the attacker if it is within reach" (Iron Fist). The compiled copy keeps
# the attack's own dice, weapon and bonuses and only removes its Action cost; candidate_allowed offers it
# solely while the round's guard reward is unspent, and action_completed spends it. Nothing is truncated:
# the actor's ordinary attacks stay in the catalog.
GUARD_ATTACK = "br_guard_attack"


def _is_guard_attack(action: Any, kind: str) -> bool:
    typed = (action.parameters or {}).get("typed") or {}
    effects = [row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "attack"]
    if not effects:
        return False
    if kind == "unarmed":
        return any(row.get("attack_kind") == "unarmed" for row in effects)
    weapon = bool(typed.get("weapon"))
    if kind == "ranged":
        return weapon and bool(typed.get("range_ft"))
    return weapon and not typed.get("range_ft")


@hook("compile_actions")
def compile_guard_attacks(info: dict[str, Any]) -> list[Any] | None:
    """One no-Action copy of the printed weapon attack per guard-zero free-attack rider."""
    from ..gate2_runtime_models import EconomyKind

    declared = [(row, rider) for row in authority.owned(info.get("owner_sheet") or {})
                for rider in row.get("riders") or []
                if rider.get("kind") == "guard_zero" and rider.get("effect") == "free_attack"]
    if not declared:
        return None
    made = []
    for row, rider in declared:
        key = f"{GUARD_ATTACK}_{rider.get('clause')}"
        for action in info["actions"]:
            if action.economy == EconomyKind.NONE or not _is_guard_attack(action, str(rider.get("weapon") or "ranged")):
                continue
            typed = dict((action.parameters or {}).get("typed") or {})
            made.append(action.model_copy(update={
                "source_definition_id": f"{action.source_definition_id}+brguard",
                "display_name": f"{action.display_name} (free guard reward)",
                "economy": EconomyKind.NONE, "costs": (),
                "parameters": {**action.parameters, "typed": {**typed, GUARD_ATTACK: key}}}))
    return made or None


@hook("candidate_allowed")
def guard_attack_available(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    key = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get(GUARD_ATTACK)
    if not key:
        return None
    return actor.turn_flags.get(key) == engine.state.round_number


@hook("action_completed")
def spend_guard_attack(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    action = (getattr(engine, "action_catalog", None) or {}).get(source_definition_id)
    key = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get(GUARD_ATTACK)
    if key:
        actor.turn_flags[key] = -1


# --------------------------------------------------------------- Air: Gather Current range (clause 4)
@hook("compile_action")
def reduce_talent_range(action: Any, info: dict[str, Any]) -> Any:
    """Air: "your Gather Current range is reduced by 10 feet unless the Current is centered on you or a
    physical object you are touching." A self- or touch-centred Current is at distance 0, so the printed
    maximum range of every non-self expression is the talent's range minus 10."""
    typed = (action.parameters or {}).get("typed") or {}
    source = typed.get("source") or typed.get("option_of")
    for row, rider in _sheet_riders(info, "range_reduction"):
        if not _source_matches(source, rider.get("sources")):
            continue
        feet = int(rider.get("feet") or 10)
        current = int(getattr(action, "range_ft", 0) or typed.get("range_ft") or 0)
        if current <= 0:
            return None
        reduced = max(0, current - feet)
        if reduced == current:
            return None
        parameters = {**action.parameters, "typed": {**typed, "range_ft": reduced}
                      } if typed.get("range_ft") is not None else action.parameters
        return action.model_copy(update={"range_ft": reduced, "parameters": parameters})
    return None
