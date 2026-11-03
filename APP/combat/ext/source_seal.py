"""Source Seal's Fetter Seal (rider lane C13, 2026-09-30; owner: "i want everything we can automated, keep going until its only the
non-combat ones left"). Printed (Sphere Compendium, Source, "Source Seal"): "Fetter Seal. This option can be placed only on a 5-foot
section of mineral surface. The first time a creature of your choice enters that section or starts its turn there before the seal
ends, you may end the seal. If you do, that creature's Speed is reduced by 10 feet until the end of that turn." / "You can maintain a
number of active Source Seals equal to your Proficiency Bonus. If you create another Source Seal beyond this limit, choose one existing
Source Seal you created to end."

The seal is the typed zone Source Seal leaves (authority/typed_mechanics/reviewed_final.d/riders_c13.json: one 5-foot square within
touch, 1 minute, an enter/start trigger running ``source_fetter``). ``source_fetter`` asks the seal's maker whether to spend it on the
creature (the built-in AI spends it on a hostile creature, never on its own side); spending it gives that creature -10 feet Speed until
the end of its current turn and ends the seal. ``source_seal_limit`` (on the same activation) enforces
its Proficiency Bonus, asking the owner which existing seal to end (AI ends the oldest).
Which squares are mineral is not on the map: the GM confirms it (a rider).

Hooks: none. Default-inert: only Source Seal's own zone runs these effects.
"""

from __future__ import annotations

from typing import Any

from . import effect, note

SOURCE = "SOURCE_BASE_SOURCE_SEAL"


def _seals(engine: Any, owner: Any) -> list[Any]:
    from .. import zones

    rows = [z for z in zones.typed_zones(engine) if z.active and z.owner_id == owner.entity_id and SOURCE in z.source_definition_id]
    return sorted(rows, key=lambda z: (z.created_round, int(z.zone_id.rsplit(":", 1)[-1]) if z.zone_id.rsplit(":", 1)[-1].isdigit() else 0))


@effect("source_seal_limit")
def seal_limit(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import zones
    from .rider_choices import pick

    seals = _seals(ctx.engine, ctx.actor)
    cap = max(1, int(ctx.numbers.get("pb") or 2))
    for _ in range(max(0, len(seals) - cap)):
        existing = seals[:-1]  # the newly created seal is not an existing seal
        labels = {z.zone_id: f"End your Source Seal at {z.center.x},{z.center.y}" for z in existing}
        chosen = pick(ctx.engine, ctx.actor, "source_seal_end", "Source Seal", list(labels), subject=ctx.actor,
                      labels=labels, preferred=[existing[0].zone_id], optional=False,
                      trigger="creating a new seal exceeds your Proficiency Bonus limit; choose an existing seal to end")
        if chosen:
            zone = next(z for z in existing if z.zone_id == chosen[0])
            zones.remove(ctx.engine, zone, "SOURCE_SEAL_LIMIT")
            seals.remove(zone)


@effect("source_fetter")
def fetter(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import zones
    from .rider_choices import pick

    engine, owner, creature = ctx.engine, ctx.actor, ctx.target
    if creature is None or not creature.active or creature is owner:
        return
    spots = {tuple(cell) if not hasattr(cell, "x") else (cell.x, cell.y)
             for cell in engine.grid.footprint_cells(creature.position, engine._footprint(creature.entity_id))}
    zone = next((z for z in _seals(engine, owner) if any((c.x, c.y) in spots for c in z.affected_cells)), None)
    if zone is None:
        return
    hostile = creature.team_id != owner.team_id
    chosen = pick(engine, owner, "source_fetter", "Fetter Seal", ["fetter"], subject=creature, preferred=["fetter"], automatic=hostile,
                  labels={"fetter": f"End your Fetter Seal: {creature.display_name}'s Speed is 10 feet lower until the end of this turn"},
                  trigger=f"{creature.display_name} is on your Fetter Seal")
    if not chosen:
        return
    from ..typed_executor import run_effects

    run_effects(ctx, [{"type": "speed", "applies_to": "target", "flat": -10, "expires_on": "END_OF_CURRENT_TURN",
                       "evidence": "that creature's Speed is reduced by 10 feet until the end of that turn"}])
    zones.remove(engine, zone, "FETTER_SEAL_USED")
    note(engine, ctx.source, owner, f"Fetter Seal: {creature.display_name}'s Speed is reduced by 10 feet until the end of this turn; the seal ends.",
         (creature,))
