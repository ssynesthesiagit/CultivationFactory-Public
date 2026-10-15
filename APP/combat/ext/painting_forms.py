"""Living Painting forms (Painting Cultivator, CL6; Qi Subpath Compendium R19, "Living Painting Forms").

The forms are summoned creatures (combat/summons.py, combat/rules/summons.json: one creature per form, sharing the family
"living_painting" -- "You may maintain one Living Painting"); what each form adds to Painted Strike or does instead of it is here.

  Tiger, Pouncing Stroke: "If the Tiger moves at least 20 feet straight toward a creature before hitting it with Painted Strike,
    the target makes a Strength saving throw. Failed Save: Knocked Prone. A creature is tested once per turn."  Worked out as:
    the Tiger's own movement this turn closed at least 20 feet on that creature (a straight approach closes exactly what it
    moves; a bent one closes less).  The save DC is the summoner's Cultivation Save DC.
  Serpent, Coiling Stroke: "After hitting a Large or smaller creature, it makes a Strength saving throw. Failed Save: Grappled
    by the Serpent until the start of your next turn. While Grappling: the Serpent cannot use Painted Strike against another
    target. The target may use its Action to repeat the saving throw, ending the Grapple on a success."  The grip is a Grappled
    condition that ends at the start of the summoner's next turn and is escaped with a Strength saving throw
    (typed_executor.block_escape_grapple reads its ``escape_save``).
  Tortoise, Shell Ward: the summon row's innate reaction (ally_damaged) reduces the damage by the summoner's Proficiency Bonus;
    the ``shell_ward_cover`` effect gives the ally Half Cover until the start of its next turn (the ``cover`` hook: like every
    cover on this table it counts against ranged attacks only, Gate4ControllerEngine._cover_bonus_actor_to_actor).
  Crane, Painted Passage: see ``painted_passage`` below.

Not modeled: the Tortoise is Large (the summons place every creature on one square); the Crane's Fly Speed and Hover and the
Serpent's Climb and Swim Speeds (the map has no altitude, climbing or swimming: their Speeds are their walking Speeds); the
damage type of Painted Strike is chosen "when created" -- the strike deals whichever of Bludgeoning, Piercing, Slashing or
Force lands hardest (summons.json, as the Paper Dragon's Slashing or Force).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

FAMILY = "living_painting"
GRAPPLED = "condition:typed.grappled"
SHELL_WARD = "condition:typed.shell_ward"
POUNCE_FEET = 20


def _form(actor: Any) -> str | None:
    record = getattr(actor, "summon", None) or {}
    return str(record["group"]).rsplit("_", 1)[-1] if record.get("family") == FAMILY else None


# What each form's own rider does, in the words the player reads on a button. Also used by
# combat/ext/summon_ability_costs.py, which rewrites a summon button's whole help text and must not
# drop the form's effect when it does: the rider is part of what the attack does on a hit.
RIDER_TEXT = {
    "tiger": ("Pouncing Stroke: if it moved at least 20 feet straight toward the target before this hit, the "
              "target makes a Strength saving throw; on a failure the target is knocked Prone. Each target is "
              "tested only once per turn."),
    "serpent": ("Coiling Stroke: after hitting a Large or smaller creature, that creature makes a Strength saving "
                "throw; on a failure it is Grappled by the Serpent until the start of your next turn, and it may "
                "use its Action to repeat the saving throw to escape. While it Grapples one creature, the "
                "Serpent cannot use Painted Strike against another."),
}


def rider_text(form: str) -> str | None:
    """The plain sentence for a form's on-hit rider, or None when the form has none."""
    return RIDER_TEXT.get(str(form or "").strip().lower())


def closed_ft(engine: Any, actor: Any, target: Any) -> int:
    """Feet the actor's own movement since its turn began has closed on ``target`` (its distance from the target where it
    started moving this turn, less its distance now)."""
    from ..gate2_runtime_models import Position

    start = None
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED" and event.actor_id == actor.entity_id:
            break
        payload = event.payload or {}
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and not payload.get("forced"):
            path = [Position(**cell) for cell in payload.get("path") or [] if isinstance(cell, dict)]
            if path:
                start = path[0]  # walking back through the turn: the last one seen is the first move
    if start is None:
        return 0
    return engine.grid.distance_ft(start, target.position) - engine.grid.distance_ft(actor.position, target.position)


def grappling(engine: Any, actor: Any) -> list[Any]:
    """The creatures this one grips with Coiling Stroke."""
    return sorted((other for other in engine.state.actors.values() if other.active and other.entity_id != actor.entity_id
                   and any(c.condition_id == GRAPPLED and c.source_actor_id == actor.entity_id and c.data.get("escape_save")
                           for c in other.conditions.values())), key=lambda other: other.entity_id)


@effect("form_rider")
def form_rider(ctx: Any, eff: dict[str, Any]) -> None:
    """What a form adds when its Painted Strike hits (summons.py puts it on the strike's hit effects)."""
    from .. import typed_executor

    target, form = ctx.target, str(eff.get("form") or "")
    if target is None or not target.active:
        return
    if form == "tiger":
        key = f"pounce_tested:{target.entity_id}"
        if ctx.actor.turn_flags.get(key) or closed_ft(ctx.engine, ctx.actor, target) < POUNCE_FEET:
            return
        ctx.actor.turn_flags[key] = True  # "A creature is tested once per turn"
        ctx.rider("Pouncing Stroke: the Tiger moved at least 20 feet toward the target before it hit.")
        typed_executor.block_save(ctx, {"type": "save", "ability": "STR", "on_success": [],
                                        "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target"}]})
    elif form == "serpent":
        if grappling(ctx.engine, ctx.actor):
            return  # already holding one (and it cannot strike another: candidate_allowed)
        typed_executor.block_save(ctx, {"type": "save", "ability": "STR", "max_size_larger": 1, "on_success": [],
                                        "on_fail": [{"type": "coiling_grip"}]})


@effect("coiling_grip")
def coiling_grip(ctx: Any, eff: dict[str, Any]) -> None:
    """Grappled by the Serpent until the start of the summoner's next turn."""
    from .. import typed_executor, typed_reactions
    from . import effect_durations

    subject = ctx.target
    owner = ctx.engine.state.actors.get((getattr(ctx.actor, "summon", None) or {}).get("owner") or "")
    if subject is None or owner is None or typed_executor.condition_immune(ctx.engine, subject, "grappled"):
        return
    if typed_reactions.offer_condition_gained(ctx.engine, subject, ctx.actor, "grappled"):
        return
    ctx.engine._apply_condition(
        subject, GRAPPLED, ctx.source, ctx.actor.entity_id,
        expires_on=effect_durations.token("start", owner.entity_id, int(owner.turns_started) + 1),
        data={"escape_dc": int(ctx.numbers.get("save_dc") or 10), "reach_ft": int(ctx.action.range_ft or 10), "escape_save": "STR",
              "label": "Grappled by the Serpent"})


@hook("candidate_allowed")
def serpent_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """"While Grappling, the Serpent cannot use Painted Strike against another target.\""""
    if _form(actor) != "serpent" or action is None or getattr(action, "target_kind", "") != "HOSTILE_ENTITY":
        return None
    held = grappling(engine, actor)
    if held and any(target_id not in {other.entity_id for other in held} for target_id in getattr(candidate, "target_ids", ())):
        return False
    return None


@effect("shell_ward_cover")
def shell_ward_cover(ctx: Any, eff: dict[str, Any]) -> None:
    """The Tortoise's Shell Ward: Half Cover for the ally it shielded, until the start of that ally's next turn."""
    from . import effect_durations

    ally = ctx.engine.state.actors.get(ctx.typed.get("protects") or "")
    if ally is None or not ally.active:
        return
    for iid, old in list(ally.conditions.items()):
        if old.condition_id == SHELL_WARD and old.source_actor_id == ctx.actor.entity_id:
            ctx.engine._remove_condition(ally, SHELL_WARD, old.source_definition_id)  # a fresh one replaces it
    ctx.engine._apply_condition(ally, SHELL_WARD, ctx.source, ctx.actor.entity_id,
                                expires_on=effect_durations.token("start", ally.entity_id, int(ally.turns_started) + 1),
                                data={"label": "Shell Ward (Half Cover)", "cover": 2})


@hook("cover")
def shell_ward_cover_bonus(engine: Any, attacker: Any, target: Any) -> int | None:
    for condition in target.conditions.values():
        if condition.condition_id == SHELL_WARD:
            return int(condition.data.get("cover") or 2)
    return None


def _passage_subject(engine: Any, crane: Any) -> Any | None:
    """The willing creature the Crane carries: an ally within 5 feet of it (its summoner first, then by name)."""
    owner_id = (getattr(crane, "summon", None) or {}).get("owner")
    near = [other for other in engine.state.actors.values() if other.active and other.entity_id != crane.entity_id
            and other.team_id == crane.team_id and engine._distance_actor_to_actor(crane, other) <= 5]
    return min(near, key=lambda other: (other.entity_id != owner_id, other.entity_id), default=None)


def _passage_legal(engine: Any, crane: Any, destination: Any, feet: int) -> Any | None:
    """The creature the Crane could carry to ``destination`` ("a legal unoccupied space", up to ``feet`` from it, that the
    Crane can perceive, the way there open air or floor and not a solid barrier), or None."""
    ally = _passage_subject(engine, crane)
    if ally is None or destination == ally.position or engine.grid.distance_ft(ally.position, destination) > feet:
        return None
    if not engine.grid.placement_legal(destination, footprint=engine._footprint(ally), occupied_cells=engine._occupied_cells_except(ally.entity_id)):
        return None
    if any(cell in engine.grid.blocked for cell in engine.grid.ray_cells(ally.position, destination)[1:]):
        return None  # cannot cross solid barriers (Total Cover, sealed Formations and spatial locks are for the GM)
    return ally


@hook("candidate_allowed")
def passage_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    feet = int(((getattr(action, "parameters", None) or {}) if action is not None else {}).get("painted_passage") or 0)
    if not feet:
        return None
    destination = getattr(candidate, "destination", None)
    return False if destination is None or _passage_legal(engine, actor, destination, feet) is None else None


@hook("button_description")
def passage_description(row: dict[str, Any]) -> str | None:
    if any(eff.get("type") == "painted_passage" for eff in ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []):
        return "Instead of Painted Strike, carry one willing creature within 5 feet up to 20 feet to a legal space, without opportunity attacks or crossing solid barriers."
    return None


@effect("painted_passage")
def painted_passage(ctx: Any, eff: dict[str, Any]) -> None:
    """Painted Passage: move a willing creature within 5 feet up to 20 feet, without Opportunity Attacks."""
    from .. import zones

    destination = getattr(ctx.intent, "destination", None)  # the cell the Crane was aimed at (as zones.py reads it)
    ally = _passage_legal(ctx.engine, ctx.actor, destination, int(eff.get("distance_ft") or 20)) if destination is not None else None
    if ally is None:
        ctx.rider("Painted Passage: no willing creature within 5 feet could be carried to that space.")
        return
    start = ally.position
    ally.position = destination
    ctx.engine._append_event("MOVEMENT_COMMITTED", ctx.source, actor_id=ally.entity_id,
                             payload={"destination": destination.model_dump(mode="json"),
                                      "path": [start.model_dump(mode="json"), destination.model_dump(mode="json")], "cost_ft": 0,
                                      "teleport": True, "forced": True})
    zones.on_moved(ctx.engine, ally, start, destination, forced=True)
    ctx.rider(f"Painted Passage: {ally.display_name} is carried to that space (no Opportunity Attacks).")
