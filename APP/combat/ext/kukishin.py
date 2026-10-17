"""Kukishin Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Kukishin (the five features and their Normalized Procedures). Empty Strike and Soul
Severance are paid unarmed-hit riders (path_riders ``paid_hit``); Phase Flesh is a compiled Reaction whose effects add
``phase_flesh``; Hollow Step's action runs ``hollow_step``; Hollow Immortal carries ``{"type": "path_passive", "kind":
"kukishin", "role": "hollow_immortal"}`` and its Empty-World Incarnation action runs ``empty_world``.

Empty Strike     + 2d8 Psychic or Force (3d8 during Empty-World Incarnation) and the asked result.
Phase Flesh      after the halved damage: until the start of your next turn, Advantage on checks and saves to escape Grappled or
                 Restrained, and the map's own (nonmagical) Difficult Terrain does not slow you.
Hollow Step      until the start of your next turn you are Invisible, and a creature that cannot perceive you makes no
                 Opportunity Attack against you; on your next turn, your first attack roll has Advantage and, if it hits, + 2d8
                 Psychic or Force (both used by that attack).
Soul Severance   Charisma save: failure, Stunned, no Reactions, no willing teleport, Disadvantage on Concentration saves until the
                 end of your next turn; success, no Reactions until the start of its next turn. One at a time from you.
Hollow Immortal  Advantage on saves and escapes against Grappled and Restrained. Empty-World Incarnation (1 minute): Resistance to
                 all but Force, Radiant and Void (typed), no Grapple or Restraint from a physical effect of your Source CL or lower
                 (new ones fail, current ones end), Hollow Step once per turn without its Stamina ("Hollow Step (Empty-World)"),
                 Empty Strike 3d8.
Every hook returns early for a creature without these rows or states.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.kukishin.feature."
PHASE = "condition:typed.phase_flesh"
HOLLOW_AFTER = "condition:typed.hollow_step_strike"
EMPTY_WORLD = "empty_world_incarnation"
HOLLOW_STEP = "hollow_step"
SEVERED = "condition:typed.soul_severance"


def _state(engine: Any, actor: Any, name: str) -> bool:
    from .states import active

    return actor is not None and bool(active(engine, actor, name))


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "kukishin"}


@effect("gm_line")
def gm_line(ctx: Any, row: dict[str, Any]) -> None:
    """A chosen result the table cannot run by itself: the GM's line in the log."""
    ctx.rider(str(row.get("text") or row.get("evidence") or ""))


# ------------------------------------------------------------------------------------------------- Empty Strike
@effect("empty_strike_damage")
def empty_strike_damage(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    if ctx.target is None or not ctx.target.active:
        return
    count = 3 if _state(ctx.engine, ctx.actor, EMPTY_WORLD) else 2
    te.run_effects(ctx, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": count, "sides": 8}, "damage_types": ["psychic", "force"],
                          "evidence": f"Empty Strike: + {count}d8 Psychic or Force"}])


# -------------------------------------------------------------------------------------------------- Phase Flesh
@effect("phase_flesh")
def phase_flesh(ctx: Any, row: dict[str, Any]) -> None:
    for iid in [iid for iid, c in ctx.actor.conditions.items() if c.condition_id == PHASE]:
        ctx.actor.conditions.pop(iid)
    ctx.engine._apply_condition(ctx.actor, PHASE, PREFIX + "phase_flesh", ctx.actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                                data={"label": "Phase Flesh: Advantage to escape Grappled or Restrained; nonmagical Difficult Terrain ignored"})


def _phased(actor: Any) -> bool:
    return any(c.condition_id == PHASE for c in actor.conditions.values())


@hook("escape_mode")
def phase_escape(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if _phased(escaper) or "hollow_immortal" in _roles(engine, escaper) else None


@hook("escape_save_mode")
def phase_escape_save(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if _phased(escaper) or "hollow_immortal" in _roles(engine, escaper) else None


@hook("difficult_exempt")
def phase_ground(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    if not _phased(actor):
        return None
    from .. import zones

    cells = {(cell.x, cell.y) for zone in zones.map_zones(engine) if (zone.trigger_profile or {}).get("difficult") for cell in zone.affected_cells}
    return cells or None


# -------------------------------------------------------------------------------------------------- Hollow Step
@effect("hollow_step")
def hollow_step(ctx: Any, row: dict[str, Any]) -> None:
    from .effect_durations import token

    engine, actor = ctx.engine, ctx.actor
    for iid in [iid for iid, c in actor.conditions.items() if c.condition_id in (HOLLOW_AFTER,) and c.source_actor_id == actor.entity_id]:
        actor.conditions.pop(iid)
    engine._apply_condition(actor, "condition:typed.invisible", PREFIX + HOLLOW_STEP, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                            data={"label": "Hollow Step: Invisible"})
    engine._apply_condition(actor, "condition:typed.state." + HOLLOW_STEP, PREFIX + HOLLOW_STEP, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                            data={"label": "Hollow Step", "name": HOLLOW_STEP})
    turn = int(actor.turns_started) + 1
    engine._apply_condition(actor, HOLLOW_AFTER, PREFIX + HOLLOW_STEP, actor.entity_id, expires_on=token("end", actor.entity_id, turn),
                            data={"turn": turn, "label": "Hollow Step: your first attack roll next turn has Advantage and + 2d8 on a hit"})
    if row.get("free"):
        actor.turn_flags["_round_empty_world_step"] = f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _after(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == HOLLOW_AFTER and int((c.data or {}).get("turn") or 0) == int(actor.turns_started)), None)


@hook("attack_mode")
def hollow_first_attack(ctx: Any, target: Any) -> str | None:
    held = _after(ctx.actor)
    if held is None or target is None or ctx.engine.state.current_actor_id != ctx.actor.entity_id:
        return None
    held.data["armed"] = True  # this is the attack the benefit rides on
    return "ADVANTAGE"


@hook("after_hit")
def hollow_first_hit(ctx: Any, target: Any, kind: str) -> None:
    held = _after(ctx.actor)
    if held is None or not (held.data or {}).get("armed") or target is None or not target.active:
        return
    from .. import typed_executor as te

    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
                   [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["psychic", "force"],
                     "evidence": "Hollow Step: the first hit after it deals + 2d8"}])


@hook("attack_resolved")
def hollow_spent(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    held = _after(ctx.actor)
    if held is not None and (held.data or {}).get("armed"):
        ctx.actor.conditions.pop(held.instance_id, None)
        ctx.engine._append_event("CONDITION_REMOVED", PREFIX + HOLLOW_STEP, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                 payload={"condition_id": HOLLOW_AFTER, "instance_id": held.instance_id, "reason": "CONSUMED"})


@hook("opportunity_allowed")
def unseen_step(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """"Creatures unable to perceive you cannot make Opportunity Attacks against you" (while Hollow Step lasts)."""
    if not _state(engine, mover, HOLLOW_STEP):
        return None
    from .. import senses

    return None if senses.sees_hidden(engine, reactor, mover) else False


# ----------------------------------------------------------------------------------------------- Soul Severance
@effect("soul_severance")
def soul_severance(ctx: Any, row: dict[str, Any]) -> None:
    """Failed Charisma save: every printed restriction until the end of your next turn (one Soul Severance from you at a time)."""
    from .. import typed_executor as te
    from .effect_durations import token

    target, engine, owner = ctx.target, ctx.engine, ctx.actor
    if target is None or not target.active:
        return
    for iid, held in list(target.conditions.items()):
        if held.source_definition_id == PREFIX + "soul_severance" and held.source_actor_id == owner.entity_id:
            del target.conditions[iid]
            engine._append_event("CONDITION_REMOVED", PREFIX + "soul_severance", actor_id=owner.entity_id, target_ids=(target.entity_id,),
                                 payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "REFRESHED"})
    until = token("end", owner.entity_id, int(owner.turns_started) + 1)
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    action = ActionDefinition(source_definition_id=PREFIX + "soul_severance", display_name="Soul Severance", owner_id=owner.entity_id,
                              economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    sub = te.Context(engine, owner, action, ctx.intent, {**ctx.typed, "effects": []}, [target], target, {})
    te.run_effects(sub, [{"type": "condition", "applies_to": "target", "condition": "stunned", "expires_on": until},
                         {"type": "reaction_denied", "applies_to": "target", "expires_on": until},
                         {"type": "disadvantage", "applies_to": "target", "on": "Concentration saving throws", "expires_on": until}])
    engine._apply_condition(target, SEVERED, PREFIX + "soul_severance", owner.entity_id, expires_on=until,
                            data={"label": "Soul Severance: cannot willingly teleport or become Incorporeal"})


@hook("teleport_check")
def severed_no_teleport(engine: Any, actor: Any, start: Any, destination: Any) -> bool | None:
    return False if any(c.condition_id == SEVERED for c in actor.conditions.values()) else None


# ---------------------------------------------------------------------------------------------- Hollow Immortal
@hook("save")
def hollow_immortal_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is not None and "hollow_immortal" in _roles(ctx.engine, subject) and {"grappled", "restrained"} & set(named or ()):
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


def _cl(engine: Any, actor: Any) -> int:
    """The fighter's Cultivation Level (its compiled bundle's)."""
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor.entity_id), None)
    return int((bundle or {}).get("cl") or 1)


@hook("condition_attempt")
def empty_world_holds(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    """Empty-World Incarnation: a physical Grapple or Restraint of your Source CL or lower cannot be established."""
    if subject is None or str((effect_row or {}).get("condition") or "").lower() not in ("grappled", "restrained") or not _state(ctx.engine, subject, EMPTY_WORLD):
        return None
    source_cl = int(ctx.numbers.get("cl") or 0)
    return False if source_cl <= _cl(ctx.engine, subject) else None


@effect("empty_world")
def empty_world(ctx: Any, row: dict[str, Any]) -> None:
    """Current physical Grapples and Restraints on you of your Source CL or lower become ineffective: they end."""
    engine, actor = ctx.engine, ctx.actor
    mine = _cl(engine, actor)
    from .physical_holds import source

    for iid, held in list(actor.conditions.items()):
        if not (held.condition_id.endswith(".grappled") or held.condition_id.endswith(".restrained")):
            continue
        physical, cl = source(engine, held)
        if physical and (cl is None or int(cl) <= mine):
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", PREFIX + "hollow_immortal", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "EMPTY_WORLD"})


@hook("compile_actions")
def empty_world_step(info: dict[str, Any]) -> list[Any] | None:
    """"Use Hollow Step once per turn without paying its Stamina cost" during Empty-World Incarnation."""
    if PREFIX + "hollow_immortal" not in info["owned_ids"]:
        return None
    base = next((a for a in info["actions"] if a.source_definition_id.endswith(PREFIX + HOLLOW_STEP) and "#" not in a.source_definition_id), None)
    if base is None:
        return None
    typed = (base.parameters or {}).get("typed") or {}
    effects = [{**e, "free": True} if isinstance(e, dict) and e.get("type") == "hollow_step" else e for e in typed.get("effects") or []]
    return [base.model_copy(update={"source_definition_id": base.source_definition_id + "#empty_world", "display_name": base.display_name + " (Empty-World)",
                                    "costs": tuple((r, a) for r, a in base.costs if r != "resource:core.stamina"),
                                    "parameters": {**base.parameters, "empty_world_step": True, "typed": {**typed, "effects": effects}}})]


@hook("candidate_allowed")
def empty_world_step_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not (getattr(action, "parameters", None) or {}).get("empty_world_step"):
        return None
    if not _state(engine, actor, EMPTY_WORLD) or actor.turn_flags.get("_round_empty_world_step") == f"{engine.state.round_number}:{engine.state.current_actor_id}":
        return False
    return None
