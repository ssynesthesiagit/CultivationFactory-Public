"""Run effects on the hostile creatures near you or near the target (rider lane 3, 2026-09-29).

  hostiles_within  {"radius_ft": 30, "from": "self" | "target", "sight": true, "effects": [...]}

"Hostile creatures of your choice within 30 feet that saw the blow must succeed on a Wisdom saving throw or be Frightened",
"hostile creatures within 30 feet of one affected object cannot take Reactions". The nested effects run once with every
active creature on another team within ``radius_ft`` of the actor (``from: "self"``, the default) or of the current target
(``from: "target"``) as their targets, so a nested ``save`` rolls for each of them. ``sight`` (default true) keeps only the
ones with line of sight to the creature the reach is measured from -- "that saw the blow". Nothing runs when nobody qualifies.
The caster selects creatures through the bounded choice transport and can
exclude any or all, including when only one creature qualifies.
"""
import copy
from dataclasses import replace
from typing import Any

from . import effect


@effect("hostiles_within")
def hostiles_within(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    engine = ctx.engine
    origin = ctx.actor if row.get("from") in (None, "self") else (ctx.target or ctx.actor)
    radius = int(row.get("radius_ft") or 30)
    near = sorted((other for other in engine.state.actors.values()
                   if other.active and other.team_id != ctx.actor.team_id and other.entity_id != origin.entity_id
                   and engine._distance_actor_to_actor(origin, other) <= radius
                   and (row.get("sight") is False or engine._line_of_sight_actor_to_actor(origin, other))),
                  key=lambda other: (engine._distance_actor_to_actor(origin, other), other.entity_id))
    if not near:
        return
    from . import needle

    chosen = needle.ask(engine, ctx.intent,
        needle.checkpoint_id(engine, 'HOSTILES_WITHIN', ctx.source), ctx.actor,
        'choice:needle.hostiles_within', [other.entity_id for other in near],
        labels={other.entity_id: other.display_name for other in near},
        prompt=f"Headsman's Mandate: after {ctx.action.display_name} fells {ctx.target.display_name if ctx.target else 'the target'}, choose affected creatures",
        name="Headsman's Mandate", preferred=[other.entity_id for other in near],
        minimum=0, maximum=len(near), allow_decline=True)
    targets = [other for other in near if other.entity_id in chosen]
    if targets:
        run_effects(replace(ctx, targets=targets, target=targets[0]), copy.deepcopy(row.get("effects") or []))
