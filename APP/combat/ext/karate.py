"""Karate Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Karate (the five features and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "karate", "role": "focused" | "perfect_breath" | "mushin"}``; Precision Strike is a paid
unarmed-hit rider (path_riders ``paid_hit``) whose asked option is the target area; Isshun Sengeki is a typed action.

Focused Strike   once per turn on an unarmed hit, one Iron Fist damage die is rolled twice and the higher counts: the table
                 rolls the second die after the strike's damage roll and, when it beats the strike's first die, deals the
                 difference as more damage of the strike's type (same distribution; the other dice are untouched).
Perfect Breath   after Stomping Step, your first unarmed attack before the end of the turn ignores one source of
                 Disadvantage on its roll (one condition or Dodge behind it is left out of that one reading, masked_conditions);
                 on its hit, once per turn, + Proficiency Bonus damage and one choice (asked): move 5 feet without provoking,
                 push the target 5 feet, or +1 AC against that target until the start of your next turn (hit_response).
Mushin           Advantage on your first attack roll in the first round of the fight; when the fight starts, regain 2 Stamina
                 (no more than your maximum). Initiative and Surprise happen before the table's fight begins.
Every hook returns early for a creature without these rows.
"""

from __future__ import annotations

from typing import Any

from . import hook, note

PREFIX = "tianxia.subpath.body.karate.feature."
READY = "condition:typed.perfect_breath_ready"
GUARD = "condition:typed.perfect_breath_guard"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "karate"}


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _unarmed(ctx: Any) -> bool:
    return ".natural." in ctx.source or any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                            for e in ctx.typed.get("effects") or [])


def _kinds(ctx: Any) -> list[str]:
    weapon = ctx.typed.get("weapon") or {}
    return [str(k).lower() for k in (weapon.get("damage_types") or [weapon.get("damage_type") or "bludgeoning"])]


# ------------------------------------------------------------------------------------------------ Focused Strike
@hook("after_hit")
def karate_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if kind != "unarmed" or target is None or not target.active or target.team_id == actor.team_id:
        return
    roles = _roles(engine, actor)
    if "focused" in roles and actor.turn_flags.get("_round_focused_strike") != _stamp(engine) and "iron_fist" in ctx.source:
        actor.turn_flags["_round_focused_strike"] = _stamp(engine)
        _focused(ctx, target)
    if "perfect_breath" in roles and target.active and any(c.condition_id == READY for c in actor.conditions.values()) \
            and actor.turn_flags.get("_round_perfect_breath") != _stamp(engine):
        actor.turn_flags["_round_perfect_breath"] = _stamp(engine)
        _perfect_breath(ctx, target)


def _focused(ctx: Any, target: Any) -> None:
    from .. import typed_executor as te
    from ..gate2_runtime_models import DiceSpec

    engine = ctx.engine
    roll = next((r for r in reversed(engine.rolls) if str(r.reason).startswith("DAMAGE:" + ctx.source) and r.dice), None)
    if roll is None or "d" not in str(roll.expression):
        return
    sides = int(str(roll.expression).split("d", 1)[1].split("+", 1)[0].split("-", 1)[0])
    again = engine.roller.roll(DiceSpec(count=1, sides=sides, modifier=0), actor_id=ctx.actor.entity_id, reason=f"FOCUSED_STRIKE:{ctx.source}")
    engine._record_roll(again)
    gain = int(again.total) - int(roll.dice[0])
    note(engine, PREFIX + "focused_strike", ctx.actor, f"Focused Strike: the second die rolls {again.total} against {roll.dice[0]}.", (target,))
    if gain > 0:
        te.run_effects(te.Context(engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}),
                       [{"type": "extra_damage", "applies_to": "target", "flat": gain, "damage_types": _kinds(ctx)[:1], "evidence": "Focused Strike"}])


# ------------------------------------------------------------------------------------------------ Perfect Breath
@hook("action_completed")
def stomping_step(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    if "perfect_breath" not in _roles(engine, actor) or "tianxia.path.body_refining.feature.stomping_step" not in str(source_definition_id):
        return
    for iid, held in list(actor.conditions.items()):
        if held.condition_id == READY:
            engine._remove_condition_instance(actor, iid, PREFIX + "perfect_breath", expected=held)
    engine._apply_condition(actor, READY, PREFIX + "perfect_breath", actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"label": "Perfect Breath: your next unarmed attack this turn ignores one source of Disadvantage"})


@hook("masked_conditions")
def breath_ignores_one(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    if not any(c.condition_id == READY for c in attacker.conditions.values()) or "perfect_breath" not in _roles(engine, attacker):
        return None
    from .attack_scope import current

    frame = current(engine)
    if frame is None or frame.get("actor_id") != attacker.entity_id or (frame.get("effect") or {}).get("attack_kind") != "unarmed":
        return None
    from ..typed_executor import CONDITION_PREFIX, rules

    table = rules()["conditions"]

    def rule(condition: Any) -> dict[str, Any]:
        return table.get(condition.condition_id[len(CONDITION_PREFIX):], {}) if condition.condition_id.startswith(CONDITION_PREFIX) else {}
    for iid, condition in sorted(attacker.conditions.items()):
        row = rule(condition)
        if row.get("attacks_have") == "DISADVANTAGE" or (row.get("attacks_others_have") == "DISADVANTAGE" and condition.source_actor_id != target.entity_id):
            return {attacker.entity_id: {iid}}
    for iid, condition in sorted(target.conditions.items()):
        row = rule(condition)
        near = engine._distance_actor_to_actor(attacker, target) <= 5
        if condition.condition_id == "condition:core.dodge" or row.get("attacked_with") == "DISADVANTAGE" \
                or (row.get("attacked_beyond_5ft") == "DISADVANTAGE" and not near) or (row.get("attacked_within_5ft") == "DISADVANTAGE" and near):
            return {target.entity_id: {iid}}
    return None


@hook("attack_resolved")
def breath_spent(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    if not _unarmed(ctx):
        return
    for iid in [iid for iid, c in ctx.actor.conditions.items() if c.condition_id == READY]:
        ctx.actor.conditions.pop(iid)
        ctx.engine._append_event("CONDITION_REMOVED", PREFIX + "perfect_breath", actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                 payload={"condition_id": READY, "instance_id": iid, "reason": "CONSUMED"})


def _perfect_breath(ctx: Any, target: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": int(actor.proficiency_bonus or 2), "damage_types": _kinds(ctx),
                          "evidence": "Perfect Breath: + Proficiency Bonus"}])
    labels = {"guard": f"+1 AC against {target.display_name} until your next turn", "push": f"Push {target.display_name} 5 feet",
              "move": "Move 5 feet without provoking"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "perfect_breath", target.entity_id), actor, "choice:needle.perfect_breath", list(labels),
                 labels=labels, target_id=target.entity_id, name="Perfect Breath", prompt=f"Perfect Breath: your strike hit {target.display_name}. Choose one.")
    choice = picked[0] if picked else "guard"
    if choice == "push" and target.active:
        te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])
    elif choice == "move":
        from .rider_movement import routes, step

        paths = routes(engine, actor, 5)
        pick = ask(engine, ctx.intent, checkpoint_id(engine, "perfect_breath_move", actor.entity_id), actor, "choice:needle.perfect_breath_move",
                   sorted(paths), labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, allow_decline=True, default="decline",
                   target_id=actor.entity_id, prompt="Perfect Breath: move up to 5 feet without provoking.") if paths else None
        if pick and pick[0] in paths:
            step(engine, actor, paths[pick[0]], PREFIX + "perfect_breath")
    else:
        for iid, held in list(actor.conditions.items()):
            if held.condition_id == GUARD:
                engine._remove_condition_instance(actor, iid, PREFIX + "perfect_breath", expected=held)
        engine._apply_condition(actor, GUARD, PREFIX + "perfect_breath", actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                                data={"against": target.entity_id, "label": f"Perfect Breath: +1 AC against {target.display_name}"})


@hook("hit_response")
def breath_guard(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    held = next((c for c in target.conditions.values() if c.condition_id == GUARD and (c.data or {}).get("against") == attacker.entity_id), None)
    if held is None or natural == 20 or total >= effective_ac + 1:
        return None
    note(engine, PREFIX + "perfect_breath", target, f"Perfect Breath: +1 AC turns {attacker.display_name}'s attack into a miss.", (attacker,))
    return effective_ac + 1, False


# --------------------------------------------------------------------------------------------------------- Mushin
@hook("attack_mode")
def mushin_first_attack(ctx: Any, target: Any) -> str | None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or int(engine.state.round_number) != 1 or "mushin" not in _roles(engine, actor) or actor.turn_flags.get("_round_mushin_first"):
        return None
    actor.turn_flags["_round_mushin_first"] = 1
    return "ADVANTAGE"


@hook("turn_start")
def mushin_breath(engine: Any, actor: Any) -> None:
    """"When Initiative is rolled at the start of a new scene, regain 2 Stamina" (once, when the fight's first turn begins)."""
    if int(engine.state.round_number) != 1:
        return
    for owner in engine.state.actors.values():
        if owner.active and "mushin" in _roles(engine, owner) and not owner.turn_flags.get("_round_mushin_stamina"):
            owner.turn_flags["_round_mushin_stamina"] = 1
            room = int(owner.resource_maximums.get("resource:core.stamina", 0) or 0) - int(owner.resources.get("resource:core.stamina", 0) or 0)
            if room > 0:
                engine._gain_resource(owner, "resource:core.stamina", min(2, room), PREFIX + "mushin")
