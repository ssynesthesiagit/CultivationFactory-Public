"""Elbow in the Door's chosen terrain square, for ordinary and reaction Forms.
Shared public helpers serve Iron Fist riders, Forms, Diagnosis and their placement/menu consumers.

Uses public iron_forms.strike_damaged, Needle choices and placed zone storage.
The zone's difficult_target_ids scopes cost to the damaged creature; turn_start
removes it at the striker's very next turn, including reactions on AI turns.
The optional Opened movement seal still needs actor-specific path blocking and
a save at attempted willing passage; candidate vetoes cannot reroute paths.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook, placed
from .needle import ask, checkpoint_id


def shared_spaces(engine: Any, actor: Any, target: Any) -> list[tuple[int, int]]:
    """In-bounds, traversable squares adjacent to both actual footprints."""
    def adjacent(subject: Any) -> set[tuple[int, int]]:
        cells = set(engine.grid.footprint_cells(subject.position, engine._footprint(subject)))
        return {(x + dx, y + dy) for x, y in cells for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if (dx or dy) and (x + dx, y + dy) not in cells}

    return sorted(cell for cell in adjacent(actor) & adjacent(target)
                  if engine.grid.in_bounds(cell) and cell not in engine.grid.blocked)


@effect("iron_elbow_space")
def elbow_space(ctx: Any, row: dict[str, Any]) -> None:
    from .iron_forms import strike_damaged

    target = ctx.target
    if target is None or ctx.engine._distance_actor_to_actor(ctx.actor, target) > 5 or not strike_damaged(ctx, target):
        return
    cells = {f"{x},{y}": (x, y) for x, y in shared_spaces(ctx.engine, ctx.actor, target)}
    selected = ask(ctx.engine, ctx.intent,
                   checkpoint_id(ctx.engine, "Elbow in the Door space", ctx.actor.entity_id, target.entity_id), ctx.actor,
                   "choice:needle.iron_elbow", list(cells), target_id=target.entity_id,
                   name="Elbow in the Door", feature_id="TAL_IRON_FIST_ELBOW_IN_THE_DOOR",
                   labels={key: f"Space {key}: difficult terrain for {target.display_name} until the start of your next turn"
                           for key in cells},
                   prompt_context={"cost": "No additional action or resource cost"},
                   prompt=f"Elbow in the Door after {ctx.action.display_name} damages {target.display_name}: "
                          "choose a shared adjacent space. It costs that creature twice the movement to enter until the start of your next turn.")
    if not selected:
        return
    placed.place(ctx.engine, ctx.actor, source=ctx.source, tag="iron_elbow", cells=[cells[selected[0]]],
                 name=f"Elbow in the Door: difficult terrain for {target.display_name}", difficult="all",
                 placed={"expires_turn": ctx.actor.turns_started + 1},
                 extra={"difficult_target_ids": [target.entity_id]})


@hook("turn_start")
def expire_elbow(engine: Any, actor: Any, *, nominal: bool = False) -> None:
    from .effect_durations import custom_turn_due
    for zone in placed.of(engine, "iron_elbow", owner_id=actor.entity_id):
        if custom_turn_due(actor, placed.data(zone)["expires_turn"], zone.per_turn_triggered, "elbow", nominal=nominal):
            placed.drop(engine, zone, "DURATION_ENDED")


@hook("nominal_slot_boundary")
def nominal_elbow(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint == "START_OF_TURN":
        expire_elbow(engine, actor, nominal=True)
