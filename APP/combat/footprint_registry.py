from __future__ import annotations

from .footprints import ActorFootprintDefinition, standard_actor_footprint
from .gate2_runtime_content import AN, BAI, CUI, LEE, LING

# R6.6.8 E1 exact compiled-combatant footprint registry. Existing accepted
# combatants are explicitly one-cell; missing legacy actor IDs may use the
# bounded compatibility resolver below, but a declared larger size must never
# be inferred from display labels, images, or prose.
ACTOR_FOOTPRINTS: dict[str, ActorFootprintDefinition] = {
    actor_id: standard_actor_footprint().model_copy(
        update={
            "footprint_id": f"footprint:{actor_id}.1x1",
            "source_definition_id": f"system:combat.actor_footprint:{actor_id}",
        }
    )
    for actor_id in (AN, LEE, LING, BAI, CUI)
}


def resolve_actor_footprint(actor_id: str) -> tuple[ActorFootprintDefinition, str]:
    definition = ACTOR_FOOTPRINTS.get(actor_id)
    if definition is not None:
        return definition, "TYPED"
    return standard_actor_footprint(), "LEGACY_SINGLE_CELL"
