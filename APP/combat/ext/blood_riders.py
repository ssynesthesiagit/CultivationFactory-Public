"""Blood sphere lines that were GM riders (rider lane C5, owner 2026-09-30: "i want everything we can automated"). The if_bloodied
gate is combat/ext/blood_bloodied.py; Vital Transfusion is combat/ext/blood_transfusion.py.

Shared public helpers (any Blood plug-in or typed row may use them):
  effect_marker(typed, name)  the existing flat/nested marker lookup, shared with blood_court_healing's legacy policy.
  bears_thread(engine, owner, creature)  the creature bears the owner's Blood Thread mark, or stands Bloodied inside the owner's
                                         Rivers Run Red ("A Bloodied creature inside also counts as bearing your Blood Thread").
  lose_hp(engine, actor, amount, source, floor=0)  HP loss that ignores Resistance, reductions and Temporary HP (evented).
  thread_mark(owner)  the condition id the owner's own Blood Thread is stored under (Scarlet Mist Form reads back the
                 Thread it just applied).
  thread_bearer_agrees(engine, intent, ctx, target)  asks the creature the Thread just landed on whether it will bear
                 Crimson Mark's paid hour for 1 hour; its answer is what decides if that hour needs the printed
                 Constitution saving throw (an unwilling creature resists the hour with the save).
Effect types (inert unless an ability's own typed row names them):
  hp_cost        {"amount": n}: "Cost: ... N HP" -- HP loss that cannot be reduced, transferred or paid with Temporary HP (the
                 action is offered only while the user has more HP than that).
  requires_thread {"bloodied": bool}: marker -- the ability is offered only against a creature bearing the user's Blood Thread
                 (and Bloodied, when set).
  thread_passage marker -- Blood River Passage lands only next to a creature bearing the user's Blood Thread.
  rivers_run_red marker on Rivers Run Red (bears_thread).
  bloodletting   Bloodletting Strike's failed save: Necrotic damage equal to your PB at the start of its next turn; only one from you.
  regain_half_dealt  after a failed branch's damage row: the user regains half of what it just dealt (Crimson Aura).
  rolled_burn    {"name", "dice": {"count", "sides"}, "damage_type", "duration"}: damage at the start of each of the holder's turns,
                 rolled fresh each turn (the engine's Burn; Heart-Seizing Grip).
  heal_to_half   {"formula": "pb"}: healing that cannot take the user above half its maximum HP (Crimson Feast).
  ac_becomes     {"amount": 15}: "AC becomes 15" for the effect's duration (Heartblood Rebirth).
  heartblood_return  the cocoon: at the start of your next turn, CP equal to your PB and 2d10 Temporary HP.
  court_heal_bonus  marker on Crimson Court: you and allies inside receive PB more healing once per turn (event hook).
  open_the_veins, crimson_sacrifice_setting  Open the Veins and the "Crimson Sacrifice: ..." free buttons.
Hooks: candidate_allowed (hp_cost, requires_thread, Blood River Passage destinations); attack_damage (Blood Emperor Incarnation's
6d10 Blood Thread); after_hit_choice (Bloodletting Strike); mark_applied (Crimson Mark's extension choice);
mark_apply (preserve an existing extended Thread); damage_dealt (Crimson Feast, kind "crimson_feast"); event (Crimson Court healing); turn_start_choice (Blood
Puppet's command, from its anchor condition "blood_puppet"); turn_start (Heartblood Rebirth's return); turn_end (Open the Veins'
save; the next rolled_burn roll); payment_substitution / payment_shortfall_paid (Crimson Sacrifice, lock round 7's port); compile_block; compile_actions (every Blood cultivator: "Blood Thread: willing
creature" and the Crimson Sacrifice settings).
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

BLOOD = "tianxia.sphere.blood"
THREAD = "Blood Thread"
THREAD_ID = "BLOOD_BASE_BLOOD_THREAD"
PUPPET = "blood_puppet"
SACRIFICE = "condition:typed.crimson_sacrifice_setting"
CP_POOLS = ("resource:core.qi", "resource:core.stamina", "resource:core.resonance")


def _rows(engine: Any, actor_id: str) -> list[dict[str, Any]]:
    from ..typed_reactions import _rows as rows

    return list(rows(engine, actor_id, "blood_rider"))


def owns(engine: Any, actor: Any, kind: str) -> bool:
    return any(row.get("kind") == kind for row in _rows(engine, actor.entity_id))


@hook("compile_block")
def blood_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": "blood_rider", "kind": spec.get("kind")}] if block == "blood_rider" else None


def _typed(engine: Any, source: str) -> dict[str, Any]:
    action = engine.action_catalog.get(str(source or ""))
    return ((action.parameters or {}).get("typed") or {}) if action is not None else {}


def _marker(typed: dict[str, Any], name: str) -> dict[str, Any] | None:
    stack = list(typed.get("effects") or [])
    while stack:
        row = stack.pop()
        if isinstance(row, dict):
            if row.get("type") == name:
                return row
            for key in ("on_hit", "on_fail", "on_success", "effects"):
                stack.extend(row.get(key) or [])
    return None


def effect_marker(typed: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Shared lookup for flat/nested legacy Court markers, using the existing Blood rider traversal."""
    return _marker(typed, name)


def bears_thread(engine: Any, owner: Any, creature: Any) -> bool:
    from ..typed_executor import mark_condition_id

    if any(c.condition_id == mark_condition_id(THREAD, owner.entity_id) for c in creature.conditions.values()):
        return True
    if creature.current_hp * 2 > creature.maximum_hp:
        return False
    for zone in engine.state.zones.values():  # Rivers Run Red
        if zone.active and zone.owner_id == owner.entity_id and _marker(_typed(engine, zone.source_definition_id), "rivers_run_red"):
            if any(cell.x == creature.position.x and cell.y == creature.position.y for cell in zone.affected_cells):
                return True
    return False


@effect("rivers_run_red")
def rivers_run_red(ctx: Any, eff: dict[str, Any]) -> None:
    """Marker: a Bloodied creature inside counts as bearing your Blood Thread (bears_thread)."""


# ------------------------------------------------------------------------------------------------ costs and targets
def _hp_cost(action: Any) -> int:
    return int((_marker(((getattr(action, "parameters", None) or {}).get("typed") or {}), "hp_cost") or {}).get("amount") or 0)


def lose_hp(engine: Any, actor: Any, amount: int, source: str, *, floor: int = 0) -> int:
    """HP loss that ignores Resistance, reductions and Temporary HP (the same evented shape as Vital Transfusion)."""
    amount = max(0, min(int(amount), actor.current_hp - floor))
    if amount <= 0:
        return 0
    actor.current_hp -= amount
    engine._append_event("DAMAGE_COMMITTED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,), payload={
        "rolled_or_pending_damage": amount, "reduced_to": amount, "temporary_hp_absorbed": 0, "hp_damage": amount,
        "damage_type": "SELF", "remaining_hp": actor.current_hp})
    if actor.concentration is not None and actor.active:
        engine._concentration_check(actor, amount)
    return amount


@effect("hp_cost")
def hp_cost(ctx: Any, eff: dict[str, Any]) -> None:
    lose_hp(ctx.engine, ctx.actor, int(eff.get("amount") or 0), f"{ctx.source}.hp_cost")


@effect("requires_thread")
def requires_thread(ctx: Any, eff: dict[str, Any]) -> None:
    """Marker read by candidate_allowed below."""


@hook("candidate_allowed")
def blood_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("sphere") != BLOOD:
        return None
    cost = _hp_cost(action)
    if cost and actor.current_hp <= cost:
        return False
    row = _marker(typed, "requires_thread")
    if row is not None:
        targets = [engine.state.actors.get(target_id) for target_id in getattr(candidate, "target_ids", None) or ()]
        if not targets or not all(t is not None and bears_thread(engine, actor, t) and (not row.get("bloodied") or t.current_hp * 2 <= t.maximum_hp)
                                  for t in targets):
            return False
    if _marker(typed, "thread_passage") is not None and getattr(candidate, "destination", None) is not None:
        spot = candidate.destination
        return any(other.active and other.entity_id != actor.entity_id and bears_thread(engine, actor, other)
                   and max(abs(other.position.x - spot.x), abs(other.position.y - spot.y)) <= 1 for other in engine.state.actors.values())
    return None


@effect("thread_passage")
def thread_passage(ctx: Any, eff: dict[str, Any]) -> None:
    """Marker: Blood River Passage lands only next to a creature bearing your Blood Thread (blood_candidates)."""


# ------------------------------------------------------------------------------------------------ damage and healing
@effect("bloodletting")
def bloodletting(ctx: Any, eff: dict[str, Any]) -> None:
    """"At the start of its next turn, it takes additional Necrotic damage equal to your Proficiency Bonus. ... A creature can suffer
    only one Bloodletting Strike from you at a time" (the engine's own start-of-turn burn, gone after that turn)."""
    target = ctx.target
    if target is None or not target.active:
        return
    name = "condition:typed.bloodletting"
    for iid, condition in list(target.conditions.items()):
        if condition.condition_id == name and condition.source_actor_id == ctx.actor.entity_id:
            target.conditions.pop(iid)
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                     payload={"condition_id": name, "instance_id": iid})
    ctx.engine._apply_condition(target, name, ctx.source, ctx.actor.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                                data={"burn": int(ctx.numbers.get("pb") or 2), "type": "NECROTIC",
                                      "label": f"Bloodletting: {int(ctx.numbers.get('pb') or 2)} Necrotic damage at the start of its next turn"})


def _emperor(actor: Any) -> bool:
    from .. import stances

    return any(c.condition_id == stances.PREFIX + "blood_emperor_incarnation" for c in actor.conditions.values())


@hook("attack_damage")
def emperor_thread(ctx: Any, dice: Any) -> Any:
    """Blood Emperor Incarnation: "Blood Thread damage becomes 6d10 Necrotic or Piercing damage" (Blood Thread's own dice, replaced
    only while its user holds the Incarnation)."""
    if dice is None or ctx.typed.get("source") != THREAD_ID or not _emperor(ctx.actor):
        return None
    from ..gate2_runtime_models import DiceSpec

    return DiceSpec(count=6, sides=10, modifier=int(getattr(dice, "modifier", 0) or 0))


@effect("regain_half_dealt")
def regain_half_dealt(ctx: Any, eff: dict[str, Any]) -> None:
    """Crimson Aura's failed save: "Take 4d8 Necrotic damage and you regain HP equal to half the damage dealt" -- the damage the
    failed branch just dealt this creature (after its save roll); a success regains nothing (the row sits in on_fail only)."""
    from ..typed_executor import block_healing

    target = ctx.target
    if target is None or not ctx.actor.active:
        return
    events = ctx.engine.events
    start = next((i for i in range(len(events) - 1, -1, -1) if events[i].event_type == "SAVE_ROLLED" and events[i].actor_id == target.entity_id), None)
    if start is None:
        return
    dealt = sum(int(e.payload.get("hp_damage") or 0) + int(e.payload.get("temporary_hp_absorbed") or 0) for e in events[start:]
                if e.event_type == "DAMAGE_COMMITTED" and target.entity_id in (e.target_ids or ()) and e.actor_id == ctx.actor.entity_id)
    if dealt // 2 > 0:
        block_healing(ctx, {"type": "healing", "applies_to": "self", "flat": dealt // 2, "evidence": "you regain HP equal to half the damage dealt"})


@effect("heal_to_half")
def heal_to_half(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import block_healing

    actor = ctx.actor
    room = max(0, actor.maximum_hp // 2 - actor.current_hp)
    amount = min(int(ctx.formula(eff.get("formula") or "pb") or 0), room)
    if amount > 0:
        block_healing(ctx, {"type": "healing", "applies_to": "self", "flat": amount, "evidence": str(eff.get("evidence") or "")})


@effect("ac_becomes")
def ac_becomes(ctx: Any, eff: dict[str, Any]) -> None:
    """"AC becomes 15": the difference to 15 from the AC it has now, for the effect's duration."""
    from ..typed_executor import block_ac_bonus
    from . import run

    actor = ctx.actor
    current = int(actor.armor_class) + int(ctx.engine._ac_modifier(actor)) + sum(int(v) for v in run("ac", ctx.engine, actor) if isinstance(v, int))
    delta = int(eff.get("amount") or 0) - current
    if delta:
        block_ac_bonus(ctx, {**{k: v for k, v in eff.items() if k != "amount"}, "type": "ac_bonus", "applies_to": "self", "flat": delta})


# ------------------------------------------------------------------------------------------------ damage at the start of each turn
def _roll(engine: Any, actor_id: str, dice: str, reason: str) -> int:
    from ..gate2_runtime_models import DiceSpec

    count, sides = (int(part) for part in dice.split("d"))
    roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=0), actor_id=actor_id, reason=reason)
    engine._record_roll(roll)
    return int(roll.total)


@effect("rolled_burn")
def rolled_burn(ctx: Any, eff: dict[str, Any]) -> None:
    """"Take 3d8 Necrotic damage at the start of each turn" (Heart-Seizing Grip): the engine's own start-of-turn Burn, its dice rolled
    fresh for each turn (the next turn's roll is made when the holder's turn ends). Turn-start plug-in hooks may not deal damage
    (combat/ext/event_rider_damage.py), the Burn may."""
    from ..typed_executor import effect_expiry
    from .. import stances

    target = ctx.target
    dice = f"{int(eff['dice']['count'])}d{int(eff['dice']['sides'])}"
    if target is None or not target.active:
        return
    name = f"condition:typed.{stances.slug(eff.get('name') or ctx.action.display_name)}"
    ctx.engine._apply_condition(target, name, ctx.source, ctx.actor.entity_id, expires_on=effect_expiry(ctx, eff, target, condition=True),
                                data={"burn": _roll(ctx.engine, ctx.actor.entity_id, dice, f"BURN:{ctx.source}"), "burn_dice": dice,
                                      "type": str(eff.get("damage_type") or "necrotic").upper(),
                                      "label": f"{eff.get('name') or ctx.action.display_name}: {dice} {str(eff.get('damage_type') or 'necrotic').title()} damage at the start of each of its turns"})


@hook("turn_end")
def reroll_burns(engine: Any, actor: Any) -> None:
    """The next turn's roll, re-announced as the same condition instance (a saved fight replays the new roll; the repeat-save group
    that owns the instance keeps it)."""
    for iid, condition in list(actor.conditions.items()):
        dice = (condition.data or {}).get("burn_dice")
        if not dice:
            continue
        roll = _roll(engine, condition.source_actor_id or actor.entity_id, str(dice), f"BURN:{condition.source_definition_id}")
        actor.conditions[iid] = condition.model_copy(update={"data": {**condition.data, "burn": roll}})
        from .retained_updates import record_instance_update

        record_instance_update(engine, actor, "condition", iid, actor.conditions[iid])


# ------------------------------------------------------------------------------------------------ Crimson Court
@effect("court_heal_bonus")
def court_heal_bonus(ctx: Any, eff: dict[str, Any]) -> None:
    """Legacy marker; the shared blood_court_healing provider owns delivery."""


# ------------------------------------------------------------------------------------------------ Blood Puppet
PUPPET_COMMANDS = {
    "prone": ("Force it to fall Prone", [{"type": "condition", "condition": "prone", "applies_to": "target"}]),
    "no_reactions": ("Prevent it from taking Reactions", [{"type": "condition", "condition": "reaction_denied", "applies_to": "target",
                                                          "expires_on": "START_OF_TARGET_NEXT_TURN"}]),
    "speed_zero": ("Reduce its Speed to 0 until the end of the turn", [{"type": "speed", "applies_to": "target", "becomes": 0,
                                                                        "expires_on": "END_OF_CURRENT_TURN"}]),
    "drop": ("Force it to drop one held object", [{"type": "condition", "condition": "disarmed", "applies_to": "target"}]),
    "pull": ("Move it up to half its Speed toward you", [{"type": "forced_movement", "applies_to": "target", "distance_ft": "half_speed",
                                                         "direction": "toward"}]),
    "push": ("Move it up to half its Speed away from you", [{"type": "forced_movement", "applies_to": "target", "distance_ft": "half_speed",
                                                            "direction": "away"}]),
}


@hook("turn_start_choice")
def puppet_command(engine: Any, actor: Any) -> None:
    """"Failed Save: At the start of each of its turns, choose one: move it up to half its Speed; force it to drop one held object;
    prevent it from taking Reactions; force it to fall Prone; reduce its Speed to 0 until the end of the turn." The puppeteer
    chooses (asked; the AI knocks it Prone)."""
    anchor = next((c for c in actor.conditions.values() if c.condition_id == f"condition:typed.{PUPPET}"), None)
    if anchor is None or not actor.active:
        return
    owner = engine.state.actors.get(anchor.source_actor_id or "")
    source = anchor.source_definition_id
    if owner is None or not owner.active or source not in engine.action_catalog:
        return
    from ..typed_executor import Context, run_effects
    from .needle import CHOICE, ask, checkpoint_id

    ids = list(PUPPET_COMMANDS)
    picked = ask(engine, None, checkpoint_id(engine, "BLOOD_PUPPET", actor.entity_id), owner, CHOICE + "blood_puppet", ids,
                 labels={key: f"{label} ({actor.display_name})" for key, (label, _rows) in PUPPET_COMMANDS.items()}, name="Blood Puppet",
                 prompt=f"Blood Puppet: {actor.display_name} starts its turn. Choose one command.")
    key = (picked or ["prone"])[0]
    label, rows = PUPPET_COMMANDS[key]
    rows = copy.deepcopy(rows)
    action = engine.action_catalog[source]
    typed = copy.deepcopy((action.parameters or {}).get("typed") or {})
    speed = engine._effective_speed(actor)
    for row in rows:
        if row.get("distance_ft") == "half_speed":
            row["distance_ft"] = max(0, (speed // 2) // 5 * 5)
    run_effects(Context(engine, owner, action, None, typed, [actor], actor, {}), rows)
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=owner.entity_id, target_ids=(actor.entity_id,),
                         payload={"trigger": f"Blood Puppet: {label.lower()} ({actor.display_name})."})


# ------------------------------------------------------------------------------------------------ Heartblood Rebirth
REBIRTH = "condition:typed.heartblood_cocoon"


@effect("heartblood_return")
def heartblood_return(ctx: Any, eff: dict[str, Any]) -> None:
    """"Until the start of your next turn: ... AC becomes 15; gain Resistance to all damage except Radiant and Psychic; cannot move
    voluntarily" (its nested "effects": run here, so the reaction path does not read the Resistance as a cut to the killing blow) and
    "At the start of your next turn: return with 1 HP; regain CP equal to your Proficiency Bonus; gain 2d10 Temporary HP"."""
    from ..typed_executor import run_effects

    run_effects(ctx, copy.deepcopy(eff.get("effects") or []))
    ctx.engine._apply_condition(ctx.actor, REBIRTH, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"pb": int(ctx.numbers.get("pb") or 2), "label": "Blood cocoon: at the start of your next turn you "
                                      "return with 1 HP, regain CP equal to your Proficiency Bonus and gain 2d10 Temporary HP"})


@hook("turn_start")
def heartblood_wakes(engine: Any, actor: Any) -> None:
    cocoon = next(((iid, c) for iid, c in actor.conditions.items() if c.condition_id == REBIRTH), None)
    if cocoon is None:
        return
    iid, condition = cocoon
    actor.conditions.pop(iid)
    engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"condition_id": REBIRTH, "instance_id": iid})
    pool = next((pool for pool in CP_POOLS if pool in actor.resources), None)
    if pool is not None:
        room = int(actor.resource_maximums.get(pool, 0)) - int(actor.resources.get(pool, 0))
        if room > 0:
            engine._gain_resource(actor, pool, min(room, int((condition.data or {}).get("pb") or 2)), condition.source_definition_id)
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=2, sides=10, modifier=0), actor_id=actor.entity_id, reason=f"TEMP_HP:{condition.source_definition_id}")
    engine._record_roll(roll)
    engine._grant_temp_hp(actor, int(roll.total), condition.source_definition_id, actor.entity_id)


# ------------------------------------------------------------------------------------------------ Crimson Feast
@hook("damage_dealt")
def crimson_feast(ctx: Any, target: Any, amount: int) -> None:
    """"Trigger: You damage a Bloodied creature bearing your Blood Thread. Cost: 2 CP. Use Limit: Once per turn." Extra Necrotic
    damage by CL (2d6/3d6/4d6), then you regain HP equal to your PB, never above half your maximum HP. A player is asked."""
    engine, actor = ctx.engine, ctx.actor
    if amount <= 0 or not target.active or target.team_id == actor.team_id or not owns(engine, actor, "crimson_feast") \
            or target.current_hp * 2 > target.maximum_hp or not bears_thread(engine, actor, target) or actor.turn_flags.get("crimson_feast_used"):
        return
    pool = next((pool for pool in CP_POOLS if int(actor.resources.get(pool, 0)) >= 2), None)
    if pool is None:
        return
    from .choice_costs import payable
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    # One quoted payment: the prompt names it and the same object spends it, so the
    # 2 points the player is shown are the 2 points the table takes. The attack that
    # triggered this already cost its own price and is quoted separately by ask().
    price = payable(actor, pool, 2)
    cl = int(ctx.numbers.get("cl") or 1)
    count = 4 if cl >= 17 else 3 if cl >= 11 else 2
    pb = int(ctx.numbers.get("pb") or 2)
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "CRIMSON_FEAST", ctx.source, target.entity_id), actor, CHOICE + "crimson_feast",
                 ["feast", "skip"], labels={"feast": f"Spend 2 CP (Cultivation Points): {count}d6 extra Necrotic damage to {target.display_name}; "
                                                    f"regain {pb} HP, up to half your maximum HP (once per turn)", "skip": "Not now"},
                 name="Crimson Feast", prompt=f"Crimson Feast: {ctx.action.display_name} damaged {target.display_name}, Bloodied and bearing your Blood Thread.",
                 prompt_context=action_context(engine, actor, ctx.source, target), payment=price)
    if (picked or ["feast"])[0] != "feast":
        return
    actor.turn_flags["crimson_feast_used"] = True
    price.pay(engine, actor, "tianxia.talent.blood.crimson_feast")
    from ..typed_executor import Context, run_effects

    feast = Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    run_effects(feast, [{"type": "damage", "applies_to": "target", "dice": {"count": count, "sides": 6}, "damage_types": ["necrotic"],
                         "evidence": "Deal extra Necrotic damage based on your CL."},
                        {"type": "heal_to_half", "formula": "pb", "evidence": "Regain HP equal to your Proficiency Bonus (never above half your maximum HP)."}])


# ------------------------------------------------------------------------------------------------ Thread augments on a hit
def _pool(actor: Any, amount: int) -> str | None:
    return next((pool for pool in CP_POOLS if int(actor.resources.get(pool, 0)) >= amount), None)


@hook("after_hit_choice")
def thread_augments(ctx: Any, target: Any, kind: str) -> None:
    """Bloodletting Strike: "Trigger: You hit with a melee attack or Blood Thread. Cost: 1 CP. Add 1d6 Necrotic damage to the
    triggering hit or Blood Thread damage. The target makes a Constitution saving throw. Failed Save: At the start of its next turn,
    it takes additional Necrotic damage equal to your Proficiency Bonus." Asked of a player; the AI pays when it can.
    Crimson Mark uses mark_applied below, because the hit-choice hook precedes the actual Thread placement.
    """
    from ..typed_executor import Context, ranged_attack_now, run_effects
    from .choice_costs import payable
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    # The printed trigger is any melee/Blood Thread hit, including a Reaction.
    # Keep reaction provenance for Action-only benefits in their own hooks.
    if not target.active or target.entity_id == actor.entity_id:
        return
    thread = ctx.typed.get("source") == THREAD_ID
    offers = []
    if owns(engine, actor, "bloodletting_strike") and (thread or (kind in ("weapon", "unarmed") and not ranged_attack_now(ctx))):
        offers.append(("bloodletting", 1, "Bloodletting Strike", f"spend 1 CP: +1d6 Necrotic, and {target.display_name} saves or bleeds next turn", [
            {"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 6}, "damage_types": ["necrotic"],
             "evidence": "Add 1d6 Necrotic damage to the triggering hit or Blood Thread damage."},
            {"type": "save", "ability": "con", "applies_to": "target", "evidence": "The target makes a Constitution saving throw.",
             "on_fail": [{"type": "bloodletting", "evidence": "At the start of its next turn, it takes additional Necrotic damage equal to your Proficiency Bonus."}],
             "on_success": []}]))
    for key, cost, name, label, rows in offers:
        pool = _pool(actor, cost)
        if pool is None or not target.active:
            continue
        # One quoted payment (1 point), shown by the prompt and spent by the same object;
        # the melee attack that hit, and whatever it cost, is quoted separately by ask().
        price = payable(actor, pool, cost)
        picked = ask(engine, ctx.intent, checkpoint_id(engine, key.upper(), ctx.source, target.entity_id), actor, CHOICE + key, [key, "skip"],
                     labels={key: label, "skip": "Not now"}, name=name,
                     prompt=f"{name}: {ctx.action.display_name} hit {target.display_name}.",
                     prompt_context=action_context(engine, actor, ctx.source, target), payment=price)
        if (picked or [key])[0] != key:
            continue
        price.pay(engine, actor, f"tianxia.talent.blood.{'bloodletting_strike' if key == 'bloodletting' else key}")
        run_effects(Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}), copy.deepcopy(rows))


def thread_mark(owner: Any) -> str:
    """The condition id ``owner``'s own Blood Thread is stored under.

    Public: any Blood plug-in that has just placed (or is about to place) the Thread needs to
    find it again -- Scarlet Mist Form's crossing announcement (blood_scarlet_mist.py) reads the
    Thread it applied to state the mark's real deadline.
    """
    from ..typed_executor import mark_condition_id

    return mark_condition_id(THREAD, owner.entity_id)


def thread_bearer_agrees(engine: Any, intent: Any, ctx: Any, target: Any) -> bool:
    """Whether the creature the Thread just landed on is a willing bearer of the paid hour.

    Crimson Mark prints "An unwilling creature makes a Constitution saving throw", so willingness is
    the creature's own answer and never the Thread owner's: an ally can refuse the hour (and then has to
    save against it), and a creature that has no quarrel with its owner can accept it without a save
    (combat/ext/willing_targets.py asks the recipient the same way, and uses side membership only as the
    answer the AI gives when nobody is answering).

    Asked through the shared choice transport, so it pauses the table for that creature's own controller
    on manual and Ask-me turns as well as during an AI action; an AI recipient answers automatically with
    the side-based default it would have chosen anyway. Anything that is not an acceptance -- a refusal, a
    declined question, or an off-turn trigger with no intent to ask on -- counts as unwilling, which is
    what the printed save is for.

    The ordinary Thread is placed either way: this answers only the hour Crimson Mark adds on top of it.
    The owner's own Thread needs no question -- there is nobody else to ask, and a creature is not
    unwilling about its own action.
    """
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    if target.entity_id == ctx.actor.entity_id:
        return True
    same_side = str(target.team_id) == str(ctx.actor.team_id)
    agreed = ask(engine, intent, checkpoint_id(engine, "CRIMSON_MARK_WILLING", ctx.source, target.entity_id),
                 target, CHOICE + "crimson_mark_willing", ["accept", "refuse"],
                 labels={"accept": f"Accept: let {ctx.actor.display_name}'s Blood Thread on you last 1 hour",
                         "refuse": "Refuse: resist the longer Thread with a Constitution saving throw"},
                 prompt=f"Crimson Mark: {ctx.actor.display_name} spent 1 CP to extend the Blood Thread on you to "
                        f"1 hour. Accept it, or refuse and make a Constitution saving throw?",
                 preferred=["accept" if same_side else "refuse"], allow_decline=True, automatic=True,
                 name="Crimson Mark", feature_id=ctx.source, target_id=target.entity_id,
                 prompt_context=action_context(engine, ctx.actor, ctx.source, target))
    return bool(agreed) and agreed[0] == "accept"


@hook("mark_apply")
def preserve_extended_thread(ctx: Any, eff: dict[str, Any], subject: Any, expires: str, data: Any) -> bool | None:
    """A new ordinary Thread cannot revoke an existing Crimson Mark's one-hour extension.

    Retain counted-hour deadlines and historical UNTIL_REMOVED instances without
    refreshing their original deadline. New hourly extensions use the shared clock.
    An ordinary counted refresh may lengthen the deadline, but cannot shorten it;
    a paid one-hour extension still refreshes normally.
    Other owners, marks, and characters without Crimson Mark keep ordinary refresh.
    """
    from .effect_durations import parse_round

    if (eff.get("mark") != THREAD or expires == "UNTIL_REMOVED"
            or (eff.get("duration") or {}).get("kind") == "hours"
            or not owns(ctx.engine, ctx.actor, "crimson_mark")):
        return None
    incoming_deadline = parse_round(expires)
    if not any(c.condition_id == thread_mark(ctx.actor)
               and (c.expires_on == "UNTIL_REMOVED"
                    or (parse_round(c.expires_on) is not None
                        and (incoming_deadline is None or parse_round(c.expires_on) > incoming_deadline)))
               for c in subject.conditions.values()):
        return None
    from . import run_strict

    run_strict("mark_applied", ctx, THREAD, subject)
    return True


@hook("mark_applied")
def crimson_mark_extension(ctx: Any, name: str, target: Any) -> None:
    """Offer the printed +1 CP extension after the Thread actually lands, however it was applied.

    The printed trigger is "When you apply Blood Thread", so every application qualifies: the
    unwilling attack, the willing action, Scarlet Mist Form's crossing, an aura that threads a
    Bloodied enemy. The creature the Thread landed on is then asked whether it will bear the paid
    hour (thread_bearer_agrees), because "An unwilling creature makes a Constitution saving throw"
    is that creature's own choice to make: the ordinary Thread is placed exactly as printed in every
    case, and only the hour -- the augment this talent adds -- is what an unwilling creature can
    defeat. The application keeps its own action for the prompt, so the table names what applied
    the Thread.

    An activation-local guard prevents the extension's own mark row from offering
    another extension. Choices remain transactional on manual and AI turns.
    """
    if name != THREAD or not target.active or not owns(ctx.engine, ctx.actor, "crimson_mark"):
        return
    key = "_crimson_mark_offered"
    offered = ctx.damage_cache.setdefault(key, [])
    if target.entity_id in offered:
        return
    offered.append(target.entity_id)
    pool = _pool(ctx.actor, 1)
    if pool is None:
        return
    from ..typed_executor import Context, run_effects
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    label = (f"Spend 1 CP (Cultivation Point): extend your Blood Thread on {target.display_name} to 1 hour"
             f"; {target.display_name} accepts it or resists it with a Constitution saving throw")
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "CRIMSON_MARK", ctx.source, target.entity_id),
                 ctx.actor, CHOICE + "crimson_mark", ["crimson_mark", "skip"],
                 labels={"crimson_mark": label, "skip": "Not now"}, name="Crimson Mark",
                 prompt=f"Crimson Mark: {ctx.action.display_name} applied your Blood Thread to {target.display_name}.",
                 prompt_context={**action_context(ctx.engine, ctx.actor, ctx.source, target), "cost": "1 CP", "paying_pool": pool})
    if (picked or ["crimson_mark"])[0] != "crimson_mark":
        return
    ctx.engine._spend_resource(ctx.actor, pool, 1, "tianxia.talent.blood.crimson_mark")
    willing = thread_bearer_agrees(ctx.engine, ctx.intent, ctx, target)
    extension = [{"type": "mark", "mark": THREAD, "applies_to": "target", "duration": {"kind": "hours", "amount": 1},
                  "evidence": "When you apply Blood Thread, extend its duration to 1 hour."}]
    rows = extension if willing else [{"type": "save", "ability": "con", "applies_to": "target",
                                       "evidence": "An unwilling creature makes a Constitution saving throw.",
                                       "on_fail": extension, "on_success": []}]
    # The hour is the extension's own printed duration. It must not inherit the duration of whatever
    # applied the Thread, or a concentrating application (Scarlet Mist Form) would cut the paid hour
    # short at its own Concentration ending.
    run_effects(Context(ctx.engine, ctx.actor, ctx.action, ctx.intent,
                        {**ctx.typed, "duration": {"kind": "hours", "amount": 1}}, [target], target, ctx.damage_cache), rows)


# ------------------------------------------------------------------------------------------------ Blood actions every Blood cultivator has
@hook("compile_actions")
def blood_actions(info: dict[str, Any]) -> list[Any] | None:
    """Blood Thread's "Willing Creature: Apply Blood Thread automatically. The Thread lasts for 1 minute" (its own button; the
    Blood Thread action is the unwilling attack), and the sphere's Crimson Sacrifice settings."""
    if BLOOD not in (info.get("spheres") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    out = [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.blood_thread_willing", display_name="Blood Thread: willing creature",
        owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF", range_ft=60,
        parameters={"typed": {"effects": [{"type": "choose_willing", "target_only": True, "allow_hostile_target": True,
                                           "range_ft": 60, "variant_suffix": " (any creature)",
                                           "consent_text": "Accept Blood Thread for 1 minute, without damage or an attack roll. No CP cost.",
                                           "effects": [{"type": "mark", "mark": THREAD, "applies_to": "target", "duration": {"kind": "minutes", "amount": 1},
                                           "evidence": "Willing Creature: Apply Blood Thread automatically. The Thread lasts for 1 minute."}]}],
                              "numbers": info["numbers"], "duration": {"kind": "minutes", "amount": 1}, "riders": [], "source": THREAD_ID + ".willing",
                              "sphere": BLOOD},
                    "expected_damage": 0,
                    "description": "Use an Action, with no CP (Cultivation Point) cost, to place your Blood Thread on yourself or a "
                                   "willing creature within 60 feet for 1 minute, without damage or an attack roll. This link lets "
                                   "your known Blood talents affect that creature: for example, Coagulate can grant Temporary HP, "
                                   "stop bleeding, or stabilize it, and Vital Transfusion can heal it. Each talent pays its own costs."})]
    # This action is supplied by this hook, after the generic willing-target
    # hook's original catalog snapshot. Reuse its public any-creature builder.
    from .willing_targets import willing_non_allies
    out.extend(willing_non_allies({**info, "actions": out}) or [])
    for amount, label in ((0, "pay cultivation resources only (no HP)"), (1, "pay 1 CP with HP"), (2, "pay 2 CP with HP"), (99, "pay all the CP you may with HP")):
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.crimson_sacrifice.{amount}", display_name=f"Crimson Sacrifice: {label}",
            owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"setting_only": True, "typed": {"effects": [{"type": "crimson_sacrifice_setting", "amount": amount}], "numbers": info["numbers"],
                                                        "duration": {"kind": "instant"}, "riders": []},
                        "expected_damage": 0, "player_only": True,
                        "description": "Free setting for your Blood talents: pay 5 Hit Points for each replaced point of Qi, "
                                       "Stamina or Resonance (CP, Cultivation Points), without falling below 1 Hit Point. Once per "
                                       "turn, up to twice your Proficiency Bonus in points; it also covers CP you lack. Open the Veins "
                                       "allows several payments this turn at 4 HP per point; Blood Emperor Incarnation also lowers the "
                                       "rate to 4 HP. You confirm the payment before use. The setting lasts until changed; turn it off "
                                       "to pay only cultivation resources."}))
    return out


@effect("crimson_sacrifice_setting")
def crimson_sacrifice_setting(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, SACRIFICE, ctx.source)
    amount = int(eff.get("amount") or 0)
    if amount not in (0, 1, 2, 99):
        raise ValueError("invalid Crimson Sacrifice setting")
    if amount:
        ctx.engine._apply_condition(ctx.actor, SACRIFICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
            data={"amount": amount, "label": "Crimson Sacrifice: confirm HP payment for Blood talents; "
                  "5 HP per cultivation point (4 with an active discount), keep at least 1 HP; until turned off"})


VEINS = "condition:typed.open_the_veins"


def _active(actor: Any, condition_id: str) -> bool:
    return any(c.condition_id == condition_id and c.source_actor_id == actor.entity_id and c.source_definition_id
               for c in actor.conditions.values())


@hook("payment_substitution")
def crimson_sacrifice(engine: Any, actor: Any, source: str, costs: Any, missing: Any) -> Any:
    """"Once per turn, when activating a Blood talent that costs CP, you may replace some of that CP cost with HP. Each replaced CP
    costs 5 HP ... cannot reduce you below 1 HP." Open the Veins: several times this turn, 4 HP each, at most 2 x PB CP in the turn;
    Blood Emperor Incarnation: 4 HP each. Lock round 7's port (codex/lock7-crimson-sacrifice): the owning payment_substitution quote
    covers both an insufficient pool and an affordable talent; native payment commits HP and the remaining CP atomically."""
    from ..alternative_payments import PaymentAlternative
    from .. import stances

    setting = next((c for c in actor.conditions.values() if c.condition_id == SACRIFICE
                    and c.source_actor_id == actor.entity_id), None)
    action = engine.action_catalog.get(source)
    typed = (action.parameters.get("typed") or {}) if action is not None else {}
    if setting is None or typed.get("sphere") != BLOOD or action.owner_id != actor.entity_id:
        return None
    paid = [(r, n) for r, n in costs.items() if r in CP_POOLS and n > 0]
    if not paid or any(r not in CP_POOLS for r in missing):
        return None
    veins = _active(actor, VEINS)
    if actor.turn_flags.get("crimson_sacrifice_used") and not veins:
        return None
    pb = int((typed.get("numbers") or {}).get("pb") or actor.proficiency_bonus)
    left = max(0, 2 * pb - int(actor.turn_flags.get("crimson_sacrifice_cp") or 0))
    per = 4 if veins or _active(actor, stances.PREFIX + "blood_emperor_incarnation") else 5
    want = min(int(setting.data.get("amount") or 0), sum(n for _, n in paid), left, max(0, (actor.current_hp - 1) // per))
    if want <= 0 or sum(missing.values()) > want:
        return None
    covered = dict(missing)
    extra = want - sum(covered.values())
    for resource, amount in paid:
        replace = min(extra, amount - covered.get(resource, 0))
        if replace:
            covered[resource] = covered.get(resource, 0) + replace
            extra -= replace
    return PaymentAlternative(setting.source_definition_id, "Crimson Sacrifice", tuple(covered.items()), hp_cost=per * want)


@hook("payment_shortfall_paid")
def crimson_sacrifice_paid(engine: Any, actor: Any, source: str, plan: Any, intent: Any) -> Any:
    action = engine.action_catalog.get(plan.source_id)
    if action is None or not any(row.get("type") == "crimson_sacrifice_setting"
                                for row in action.parameters.get("typed", {}).get("effects", [])):
        return None
    actor.turn_flags["crimson_sacrifice_used"] = True
    actor.turn_flags["crimson_sacrifice_cp"] = int(actor.turn_flags.get("crimson_sacrifice_cp") or 0) + sum(n for _, n in plan.covered)
    return None


@effect("open_the_veins")
def open_the_veins(ctx: Any, eff: dict[str, Any]) -> None:
    """"Until the end of your turn" -- ended by its own save at the end of the turn (veins_close); the start of your next turn is only a
    backstop."""
    ctx.engine._apply_condition(ctx.actor, VEINS, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"dc": int(ctx.numbers.get("save_dc") or 10), "label": "Open the Veins: Crimson Sacrifice several times this "
                                      "turn at 4 HP per CP; a Constitution save at the end of the turn"})


@hook("turn_end")
def veins_close(engine: Any, actor: Any) -> None:
    """"At the end of your turn, make a Constitution saving throw against your own Cultivation Save DC. Failed Save: Become Bloodied if
    you were not already Bloodied and gain one level of Exhaustion." It cannot take you below 1 HP."""
    found = next(((iid, c) for iid, c in actor.conditions.items() if c.condition_id == VEINS), None)
    if found is None:
        return
    iid, veins = found
    actor.conditions.pop(iid)
    engine._append_event("CONDITION_REMOVED", veins.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"condition_id": VEINS, "instance_id": iid})
    if not actor.active:
        return
    dc = int((veins.data or {}).get("dc") or 10)
    roll = engine._roll_save(actor, "CON", dc, veins.source_definition_id)
    if roll is None or roll.total >= dc:
        return
    half = actor.maximum_hp // 2
    if actor.current_hp > half:
        lose_hp(engine, actor, actor.current_hp - half, f"{veins.source_definition_id}.bloodied", floor=1)
    from . import forged_exhaustion

    forged_exhaustion.add(engine, actor, 1, veins.source_definition_id)
