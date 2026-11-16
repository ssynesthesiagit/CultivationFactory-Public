"""Ash sphere talent riders the table now runs (AUTO75, 2026-10-05; owner: "automate everything").

Three general effect types, each usable by any ability that owns the printed line, plus the Ash
records that carry them. Nothing here names a talent in code: every row decides what happens, and a
character that owns no such row pays nothing.

``periodic_damage_state`` -- a printed "... takes <dice> damage at the start of each of its turns"
state that outlives the activation that made it (Ashen Burial "Restrained by accumulated ash. At the
start of each of its turns, take 2d8 Fire, Necrotic, or Psychic damage"; Cremation Prison "take 2d8
Fire damage and 2d8 Necrotic damage at the start of each turn"). The state is an ordinary typed
condition carrying only the printed dice and damage-type names, so it survives a table commit and
reload, and it ends with the condition it belongs to (its own expiry, the repeat saving throw that
ends it, or the caster's Concentration).

The damage is delivered through the ordinary typed path (a Context built on the state, exactly as
``rider_damage_states`` does for its own turn-start riders), so everything a printed damage row gets
anywhere else also happens here: the creature's own damage reactions and Ash Ward answer it, the
attack/defence type is chosen by ``choose_damage_type`` rather than the first name in the list, the
``damage_dealt`` subscribers are notified, and a creature that dies to it dies the ordinary way. A
``requires_condition`` on the row is the printed prerequisite that anchors the state ("Restrained by
accumulated ash"), checked from the holder's own conditions by the same source and caster, so a
prevented or already-ended anchor means no damage.

``move_typed_area`` -- a printed "move one of your <areas> up to N feet" line (Rolling Ashfall's "As a
Bonus Action, move one of your Ashfall areas up to 20 feet"). The area is found by the base ability
the row names, among the caster's own active areas (including the variants a modifier produced), so a
creature with no such area is never asked. The caster picks the area, then the square it lands on;
**every** legal centre within the printed reach is offered (an area moves, so nothing has to be
standing there), each option labelled with the distance the area will travel, and the question is
picked by clicking a highlighted square. The area keeps its identity, cells and printed rules, and
anything that required a creature to remain inside ends normally when it leaves (the engine's own
zone accounting).

Both questions of a move may be **declined**, and declining either one leaves every area exactly where
it was and says so in words -- the way out the map picker's "Leave it here" button advertises. An AI
(``automatic_use``) still answers both by itself and still takes its standing preference, so a fight
nobody is answering moves the area as before. Which of the caster's own areas moves is told apart by
**where it is** ("Ashfall centred on 4,6"), because two areas of one kind share a printed name.

One hook: ``damage_reduction_bonus`` adds Ash Ward's printed Proficiency Bonus when the creature it
protects is standing in Ash Terrain, Smoke or a Fire effect. An area's printed line is read from the
area's own name and terrain (the same reading Jigoku's Hellwalker uses). A second hook,
``choice_map_pick``, lets the destination question above be answered by clicking the map.

Sources: APP/authority/typed_mechanics/rules_text.json (tianxia.sphere.ash.*, ASH_TAL_*).
"""

from __future__ import annotations

import copy
import re
from typing import Any

from . import effect, hook
from .owned_effects import remove_conditions

PERIODIC = "condition:typed.periodic_damage_state."


# ------------------------------------------------------------------ periodic damage at the start of its turns
def _states(holder: Any) -> list[Any]:
    return [row for row in holder.conditions.values() if str(row.condition_id).startswith(PERIODIC)]


@effect("periodic_damage_state")
def periodic_damage_state(ctx: Any, eff: dict[str, Any]) -> None:
    """Store the printed turn-start damage on its subject; ``turn_start`` below delivers it."""
    from .. import typed_executor as te

    rows = copy.deepcopy(eff.get("damage") or ([eff] if eff.get("dice") else []))
    rows = [row for row in rows if row.get("dice") or row.get("flat")]
    if not rows:
        return
    for holder in te._default_subject(ctx, eff, harmful=True):
        name = PERIODIC + te._mark_slug(str(eff.get("name") or "turn-start damage"))
        remove_conditions(ctx.engine, holder, ctx.source, ctx.actor.entity_id, name)
        ctx.engine._apply_condition(holder, name, ctx.source, ctx.actor.entity_id,
                                    expires_on=te.effect_expiry(ctx, eff, holder, condition=True),
                                    data={"rows": rows, "numbers": dict(ctx.numbers),
                                          "requires_condition": str(eff.get("requires_condition") or ""),
                                          "label": str(eff.get("label") or "damaged at the start of each of its turns")})


def _anchored(holder: Any, condition: Any, data: dict[str, Any]) -> bool:
    """Whether the printed condition this damage hangs on is still on the holder ("Restrained by
    accumulated ash. At the start of each of its turns, take ..."). Same source, same caster, so one
    creature's own Restrained never satisfies another's. Mirrors rider_damage_states._fire."""
    from .. import typed_executor as te

    wanted = str(data.get("requires_condition") or "")
    if not wanted:
        return True
    return any(row.condition_id == te.CONDITION_PREFIX + wanted
               and row.source_definition_id == condition.source_definition_id
               and row.source_actor_id == condition.source_actor_id
               for row in holder.conditions.values())


@hook("turn_start")
def periodic_damage(engine: Any, actor: Any) -> None:
    """"At the start of each of its turns, take <dice> damage": real damage, rolled and delivered here.

    A creature's printed anchor ("Restrained by accumulated ash") must still be on it, and the damage
    goes through the ordinary typed path, so its own damage reactions, Ash Ward, the best of a listed
    choice of damage types and the damage-dealt riders all answer exactly as they would to a spell."""
    from .. import typed_executor as te
    from ..gate2_runtime_models import ActionIntent

    for instance_id, condition in list(actor.conditions.items()):
        data = condition.data or {}
        if (not str(condition.condition_id).startswith(PERIODIC) or not actor.active
                or instance_id not in actor.conditions or not _anchored(actor, condition, data)):
            continue
        rows = data.get("rows") or []
        source = engine.state.actors.get(condition.source_actor_id)
        action = engine.action_catalog.get(condition.source_definition_id)
        if not rows or source is None or action is None:
            continue
        # The damage belongs to the ability that put the state on, so its save DC, key modifier and
        # CL stay the ones it was cast with; the intent is the turn-boundary packet that lets the
        # holder's own reactions answer (rider_damage_states._fire builds the same one).
        intent = ActionIntent(intent_id=f"periodic-damage:{engine.state.event_sequence}",
                              actor_id=source.entity_id, decision_id="periodic-damage",
                              candidate_id=action.source_definition_id,
                              state_version=engine.state.state_version, target_ids=(actor.entity_id,))
        te.run_effects(te.Context(engine, source, action, intent, {"numbers": data.get("numbers") or {}},
                                  [actor], actor, {}), rows)
        if not actor.active:
            return


# ------------------------------------------------------------------ move one of your own areas
# The two questions a move asks are namespaced under one prefix, so any ``move_typed_area`` row in the
# game is asked the same way and ``destination_map_pick`` can recognise its destination question
# without naming an ability. ".which_area" is the "which area moves" question; the rest is the square.
MOVE_QUESTION = "move_area_to:"
AREA_QUESTION = MOVE_QUESTION + "which_area:"
MAP_PICK = "choice:needle." + MOVE_QUESTION


def _areas_of(engine: Any, owner: Any, base_id: str) -> list[Any]:
    """The owner's own active areas created by ``base_id`` (every modifier variant of it included)."""
    from .. import zones

    made = {aid for aid, action in engine.action_catalog.items()
            if str((((action.parameters or {}).get("typed") or {}).get("source")) or "") == base_id}
    return [zone for zone in zones.typed_zones(engine)
            if zone.owner_id == owner.entity_id and zone.active and zone.source_definition_id in made]


def _legal_center(engine: Any, cell: Any) -> bool:
    """Whether an area may be centred on this square: on the map and not inside a wall. An area moves,
    so nothing standing there refuses it -- only the battlefield does."""
    grid = engine.grid
    return 0 <= cell.x < grid.width and 0 <= cell.y < grid.height and (cell.x, cell.y) not in grid.blocked


def area_destinations(engine: Any, zone: Any, feet: int) -> tuple[list[Any], dict[Any, int]]:
    """Every legal square ``zone`` may be moved to within ``feet``, and how far each one is.

    "Move one of your Ashfall areas up to 20 feet" is a choice of *any* square within 20 feet, so this
    is the whole square neighbourhood of that reach (20 feet is four 5-foot steps on this grid, which
    includes the 10-, 15- and 20-foot reaches and the off-ray offsets), not the first square along each
    of eight rays. Ordered nearest first, then north to south and west to east, so a table reads it as a
    list and an AI takes the first."""
    reach = max(0, int(feet) // max(1, int(engine.grid.square_size_ft)))
    cells = [cell for cell in engine.grid.cells_in_radius(zone.center, reach)
             if (cell.x, cell.y) != (zone.center.x, zone.center.y) and _legal_center(engine, cell)]
    return sorted(cells, key=lambda cell: (engine.grid.distance_ft(zone.center, cell), cell.y, cell.x)), {
        cell: engine.grid.distance_ft(zone.center, cell) for cell in cells}


def _best_destination(engine: Any, owner: Any, zone: Any, cells: list[Any], *, perceived_only: bool = False) -> Any:
    """Where an unanswered Rolling Ashfall puts the area: over as many enemies as the printed reach
    allows, otherwise the nearest legal square. An AI's standing preference, never a rule."""
    from .. import zones, senses

    def enemies(cell: Any) -> int:
        covered = {(c.x, c.y) for c in zones._cells(engine, cell, {"size_ft": zone.trigger_profile.get("size_ft"),
                                                                   "shape": zone.trigger_profile.get("shape"),
                                                                   "spreads": zone.trigger_profile.get("spreads")})}
        return sum(1 for other in engine.state.actors.values()
                   if other.active and other.team_id != owner.team_id
                   and (not perceived_only or senses.perceives(engine, owner, other))
                   and covered & set(engine._actor_cells(other)))

    return max(cells, key=lambda cell: (enemies(cell), -engine.grid.distance_ft(zone.center, cell))) if cells else None


@effect("move_typed_area")
def move_typed_area(ctx: Any, eff: dict[str, Any]) -> None:
    """"As a Bonus Action, move one of your <areas> up to N feet." Either question may be declined, and
    declining either one leaves the area where it is."""
    from .. import zones
    from . import needle
    from .rider_choices import pick
    from . import tabik_dark

    engine, owner = ctx.engine, ctx.actor
    mine = _areas_of(engine, owner, str(eff.get("area_source") or ""))
    feet = int(eff.get("distance_ft") or 0)
    if not mine or feet <= 0:
        ctx.rider(f"{ctx.action.display_name}: you have no area of that kind to move.")
        return
    zone = mine[0]
    key = MOVE_QUESTION + str(eff.get("choice") or "area")
    if len(mine) > 1:  # more than one area of that kind: which one moves is the owner's first choice
        named = {area.zone_id: _area_label(area, where=True) for area in mine}
        chosen_area = pick(engine, owner, AREA_QUESTION + str(eff.get("choice") or "area"),
                           str(eff.get("label") or ctx.action.display_name), list(named), subject=owner,
                           labels=named, preferred=list(named)[:1], optional=True,
                           trigger=f"{ctx.action.display_name}: which of your areas to move up to {feet} feet")
        if not chosen_area:
            ctx.rider(f"{ctx.action.display_name}: you leave your {_area_label(mine[0])} areas where they are.")
            return
        zone = next(area for area in mine if area.zone_id == chosen_area[0])
    cells, distances = area_destinations(engine, zone, feet)
    if not cells:
        ctx.rider(f"{ctx.action.display_name}: there is nowhere within {feet} feet to move that area to.")
        return
    options = [needle.cell_id(cell) for cell in cells]
    name = _area_label(zone)
    label = _area_label(zone, where=True)
    labels = {needle.cell_id(cell): f"Move {label} to {cell.x},{cell.y} ({distances[cell]} feet)" for cell in cells}
    best = _best_destination(engine, owner, zone, cells, perceived_only=bool(eff.get("perceived_aim")))
    chosen = pick(engine, owner, key, str(eff.get("label") or ctx.action.display_name),
                  options, subject=owner, labels=labels,
                  preferred=[needle.cell_id(best)] if best is not None else None, optional=True,
                  trigger=f"{ctx.action.display_name}: move {label} up to {feet} feet",
                  prompt_context={"action_name": ctx.action.display_name})
    if not chosen:
        ctx.rider(f"{ctx.action.display_name}: you leave {label} where it is.")
        return
    cell = next(one for one in cells if needle.cell_id(one) == chosen[0])
    before = (zone.center.x, zone.center.y)
    zone.center = cell
    zone.affected_cells = zones._cells(engine, cell, {"size_ft": zone.trigger_profile.get("size_ft"),
                                                       "shape": zone.trigger_profile.get("shape"),
                                                       "spreads": zone.trigger_profile.get("spreads")})
    tabik_dark.republish(engine, zone, ctx.source)
    from . import note

    note(engine, ctx.source, owner, f"{owner.display_name} moves {name} from {before[0]},{before[1]} to "
                                   f"{cell.x},{cell.y} ({distances[cell]} feet).")


def _area_label(zone: Any, where: bool = False) -> str:
    """The area's printed name, for a prompt that never shows an internal id.

    ``where`` adds the square the area covers. Two of one caster's own areas of a kind share a printed
    name, so a menu of them can only be told apart by where each one is.
    """
    name = str((zone.trigger_profile or {}).get("name") or "the area")
    return f"{name} centred on {zone.center.x},{zone.center.y}" if where else name


@hook("choice_map_pick")
def destination_map_pick(engine: Any, choice: dict, context: dict) -> dict[str, Any] | None:
    """The square a ``move_typed_area`` row moves its area to is a place, so it is picked by clicking
    the map (owner, round 24: "you can just click on an available square on the grid"). Presentation
    only: the squares, their option ids and their labels are the transport's. Inert for every other
    question in the game, for an AI combatant and for a fight nobody is answering."""
    if not str((context or {}).get("reaction_source_id") or "").startswith(MAP_PICK):
        return None
    if not choice.get("options") or int(choice.get("maximum") or 0) > 1:
        return None
    return {"instruction": "Click a highlighted square to move the area there, or press Esc to leave it where it is.",
            "cancel_label": "Leave it here"}


# ------------------------------------------------------------------ Ash Ward's printed terrain bonus
WARD = "tianxia.talent.ash.ash_ward"
ASHY = re.compile(r"ash|smoke|fire|flame|ember|burn|magma|lava|inferno", re.I)


def in_ash_or_fire(engine: Any, creature: Any) -> bool:
    """Whether ``creature`` stands in Ash Terrain, Smoke or a Fire effect (an active area whose printed name or
    terrain says so -- the same reading Jigoku's Hellwalker uses for fire, smoke, magma and ash)."""
    from .. import zones

    cells = {tuple(cell)[:2] for cell in engine._actor_cells(creature)}
    for zone in zones.typed_zones(engine):
        profile = zone.trigger_profile or {}
        words = " ".join([str(profile.get("name") or ""), " ".join(str(name) for name in profile.get("terrain") or []),
                          str(zone.source_definition_id)])
        if zone.active and ASHY.search(words) and cells & {(cell.x, cell.y) for cell in zone.affected_cells}:
            return True
    return False


@hook("damage_reduction_bonus")
def ward_terrain_bonus(engine: Any, owner: Any, protected: Any, attacker: Any, reaction_row: dict[str, Any]) -> int | None:
    """"If the protected creature stands inside Ash Terrain, Smoke, or a Fire effect, add your Proficiency Bonus to the
    reduction." (Ash Ward)"""
    if str((reaction_row or {}).get("feature_id") or "") != WARD or protected is None:
        return None
    if not in_ash_or_fire(engine, protected):
        return None
    return max(1, int(getattr(owner, "proficiency_bonus", 0) or 2))