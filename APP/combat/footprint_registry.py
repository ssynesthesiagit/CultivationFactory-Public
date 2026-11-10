from __future__ import annotations

from .footprints import ActorFootprintDefinition, standard_actor_footprint
from .gate2_runtime_content import AN, BAI, CUI, LEE, LING

# R6.6.8 E1 exact compiled-combatant footprint registry. Existing accepted
# combatants are explicitly one-cell; missing legacy actor IDs may use the
# bounded compatibility resolver below, but a declared larger size must never
# be inferred from display labels, images, or prose.
# Summon footprints belong to the bound engine (summons.add_to_match), never
# this process-wide registry: actor IDs can recur in unrelated saved fights.
ACTOR_FOOTPRINTS: dict[str, ActorFootprintDefinition] = {
    actor_id: standard_actor_footprint().model_copy(
        update={
            "footprint_id": f"footprint:{actor_id}.1x1",
            "source_definition_id": f"system:combat.actor_footprint:{actor_id}",
        }
    )
    for actor_id in (AN, LEE, LING, BAI, CUI)
}


def resolve_actor_footprint(actor_id: str, *, summon_record: dict | None = None) -> tuple[ActorFootprintDefinition, str]:
    """Resolve stock actors or a fight's bound summon record for engine/presentation.

    Size and the explicit footprint alias are authority from this bound record.
    A saved summon lacking both keeps one cell; current rules and other fights
    cannot supply missing geometry. The caller must pass its own bound record.
    """
    if summon_record is not None:
        size = summon_record.get("size") or summon_record.get("footprint")
        cells = {"large": 2, "huge": 3, "gargantuan": 4}.get(size, 1)
        return ActorFootprintDefinition.rectangle(
            cells, cells, footprint_id=f"footprint:{actor_id}.{cells}x{cells}",
            source_definition_id=f"system:combat.actor_footprint:{actor_id}"
        ), "TYPED" if size else "LEGACY_SINGLE_CELL"
    definition = ACTOR_FOOTPRINTS.get(actor_id)
    if definition is not None:
        return definition, "TYPED"
    return standard_actor_footprint(), "LEGACY_SINGLE_CELL"
