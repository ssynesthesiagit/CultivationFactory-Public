"""Phoenix Rebirth Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Phoenix Rebirth Body (Rebirth Embers and the five features, with their Normalized
Procedures). Rebirth Embers (resource:named.rebirth_ember, maximum PB) are gained by combat/ext/subpath_pools.py; Ash-Shedding
Reversal is a d20 rewrite rule (combat/ext/d20_rewrite_rules.py). Owned rows: ``{"type": "path_passive", "kind": "phoenix",
"role": "cinder" | "flame_wing"}``; Rebirth from Cinders' Reaction runs ``rebirth_from_cinders``.

Cinder Blood       at the start of your turn (not at 0 HP), 1 Ember (asked) for 1d8 + CON Hit Points (2d8 at CL11, 3d8 at CL17).
Flame-Wing Rush    after that healing restores Hit Points: a move of up to half your Speed without provoking (asked), and the first
                   unarmed hit this turn deals + 2d8 Fire or Radiant.
Rebirth from Cinders  its Reaction (6 Stamina, at least 3 Embers, once per fight) holds you at 1 HP and then: every Ember is
                   consumed, you stand, Blinded, Deafened, Frightened, Paralyzed, Poisoned, Restrained and Stunned end, each
                   hostile creature within 20 feet makes a Dexterity save (8d8 Fire or Radiant and pushed 10 feet, or half), you may
                   move up to your Speed without provoking, and once the packet lands your Hit Points are half your maximum.
Every hook returns early for a creature without these rows.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.phoenix_rebirth_body.feature."
EMBER = "resource:named.rebirth_ember"
WING = "condition:typed.flame_wing_charge"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "phoenix"}


def _cl(engine: Any, actor: Any) -> int:
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor.entity_id), None)
    return int((bundle or {}).get("cl") or 1)


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _move(engine: Any, intent: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(engine, mover, feet) if feet > 0 else {}
    if not paths:
        return
    picked = ask(engine, intent, checkpoint_id(engine, "phoenix_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        step(engine, mover, paths[picked[0]], PREFIX + "phoenix")


@hook("turn_start_choice")
def cinder_blood(engine: Any, actor: Any) -> None:
    roles = _roles(engine, actor)
    if "cinder" not in roles or not actor.active or actor.current_hp <= 0 or int(actor.resources.get(EMBER, 0) or 0) < 1:
        return
    if actor.current_hp >= actor.maximum_hp and "flame_wing" not in roles:
        return
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .states import context

    cl = _cl(engine, actor)
    dice = 3 if cl >= 17 else 2 if cl >= 11 else 1
    intent = _intent(engine)
    picked = ask(engine, intent, checkpoint_id(engine, "cinder_blood", actor.entity_id), actor, "choice:needle.cinder_blood", ["heal"],
                 labels={"heal": f"Spend 1 Rebirth Ember: regain {dice}d8 + Constitution modifier Hit Points"}, allow_decline=True,
                 target_id=actor.entity_id, name="Cinder Blood", prompt="Cinder Blood: spend a Rebirth Ember to heal?")
    if not picked:
        return
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, actor, PREFIX + "cinder_blood", independent=True):
        engine._spend_resource(actor, EMBER, 1, PREFIX + "cinder_blood")
        before = actor.current_hp
        ctx = context(engine, actor, PREFIX + "cinder_blood", [actor], {"pb": int(actor.proficiency_bonus or 2), "cl": cl})
        ctx.intent = intent
        con = next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") or 0)
                    for a in engine.action_catalog.values() if a.owner_id == actor.entity_id and (((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") is not None), 0)
        te.run_effects(ctx, [{"type": "healing", "applies_to": "self", "dice": {"count": dice, "sides": 8}, "flat": con,
                              "evidence": "Cinder Blood"}])
        if "flame_wing" in roles and actor.current_hp > before:
            _move(engine, intent, actor, int(engine._effective_speed(actor)) // 2, "choice:needle.flame_wing_move", "Flame-Wing Rush")
            engine._apply_condition(actor, WING, PREFIX + "flame_wing_rush", actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                    data={"label": "Flame-Wing Rush: the first unarmed hit this turn deals + 2d8 Fire or Radiant"})


@hook("after_hit")
def flame_wing_hit(ctx: Any, target: Any, kind: str) -> None:
    held = next((c for c in ctx.actor.conditions.values() if c.condition_id == WING), None)
    if held is None or kind != "unarmed" or target is None or not target.active:
        return
    ctx.actor.conditions.pop(held.instance_id)
    ctx.engine._append_event("CONDITION_REMOVED", PREFIX + "flame_wing_rush", actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                             payload={"condition_id": WING, "instance_id": held.instance_id, "reason": "CONSUMED"})
    from .. import typed_executor as te

    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
                   [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["fire", "radiant"],
                     "evidence": "Flame-Wing Rush: + 2d8"}])


@effect("rebirth_from_cinders")
def rebirth_from_cinders(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    left = int(actor.resources.get(EMBER, 0) or 0)
    if left:
        engine._spend_resource(actor, EMBER, left, PREFIX + "rebirth_from_cinders")  # "Consume all Embers" (3 were the cost)
    actor.turn_flags["_round_rebirth_pending"] = int(engine.state.event_sequence)
    for iid, held in list(actor.conditions.items()):
        if held.condition_id.rsplit(".", 1)[-1] in ("prone", "blinded", "deafened", "frightened", "paralyzed", "poisoned", "restrained", "stunned"):
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", PREFIX + "rebirth_from_cinders", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "REBIRTH"})
    foes = [c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.team_id != actor.team_id
            and engine._distance_actor_to_actor(actor, c) <= 20]
    if foes:
        from ..gate2_runtime_models import ActionDefinition, EconomyKind

        action = ActionDefinition(source_definition_id=PREFIX + "rebirth_from_cinders", display_name="Rebirth from Cinders", owner_id=actor.entity_id,
                                  economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
        numbers = dict(ctx.numbers)
        burst = te.Context(engine, actor, action, ctx.intent, {"effects": [], "numbers": numbers, "duration": {"kind": "instant"}, "riders": [],
                                                               "_area_centre": (actor.position.x, actor.position.y)}, foes, None, {})
        te.run_effects(burst, [{"type": "save", "ability": "dex", "evidence": "Rebirth from Cinders: Dexterity saving throw",
                                "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 8, "sides": 8}, "damage_types": ["fire", "radiant"]},
                                            {"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away_center"}],
                                "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["fire", "radiant"]}]}])
    _move(engine, ctx.intent, actor, int(engine._effective_speed(actor)), "choice:needle.rebirth_move", "Rebirth from Cinders")
    note(engine, PREFIX + "rebirth_from_cinders", actor, f"Rebirth from Cinders: {actor.display_name} rises from the ashes.")


@hook("event")
def rebirth_restores(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is None or not actor.turn_flags.get("_round_rebirth_pending"):
            continue
        actor.turn_flags.pop("_round_rebirth_pending", None)
        half = max(1, int(actor.maximum_hp) // 2)
        if actor.current_hp < half:
            before = actor.current_hp
            actor.current_hp = half
            engine._append_event("HEALING_APPLIED", PREFIX + "rebirth_from_cinders", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"offered": half - before, "before": before, "after": half})
