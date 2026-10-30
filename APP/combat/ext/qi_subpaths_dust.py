"""Dust Cultivator's sealed Choking Dust modes, using native saves and damage.

No physiology comes from names: explicit breath/body traits and printed
incorporeal kinds gate recipients. Ordinary unlabelled bodies remain eligible.
The cloud penalty is rolled once for this target in this activation, before
its save, and travels only in the child Context; no engine-global save state.
"""
from dataclasses import replace
from typing import Any

from . import effect, hook

CLOUD = 'tianxia.subpath.qi.dust_cultivator.feature.dust_cloud'
CHOKING = 'tianxia.subpath.qi.dust_cultivator.feature.choking_dust'


def eligible(target: Any, mode: str) -> bool:
    from ..physiology import trait
    from .creature_kinds import matches
    if mode == 'breathing':
        return trait(target, 'breath_dependent') is not False
    return trait(target, 'has_body') is not False and not matches(target, ['incorporeal', 'incorporeal undead'])


@effect('dust_choking_save', harmful=True)
def choking_save(ctx: Any, row: dict[str, Any]) -> None:
    from .. import zones, typed_executor as te
    from ..gate2_runtime_models import DiceSpec
    for target in te.effect_subjects(ctx, {'applies_to': 'target'}, harmful=True):
        if not eligible(target, str(row['mode'])):
            ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=ctx.actor.entity_id,
                target_ids=(target.entity_id,), payload={'log': 'Choking Dust requires a breathing creature' if row['mode']=='breathing' else 'Eroding Dust requires a corporeal creature'})
            continue
        inside = any(z.active and z.owner_id == ctx.actor.entity_id and CLOUD in z.source_definition_id
                     and zones._inside(ctx.engine, target, z) for z in zones.typed_zones(ctx.engine))
        penalty = te._roll(ctx, DiceSpec(count=1, sides=4), 'DUST_CLOUD_PENALTY') if inside else 0
        sub = replace(ctx, target=target, targets=[target],
                      typed={**ctx.typed, 'dust_cloud_save_penalty': int(penalty)})
        # Keep the nested save in the ordinary typed ``effects`` branch. The
        # compiler, modifier composer, and executor all traverse that contract.
        te.run_effects(sub, row.get('effects') or [])


@hook('save')
def cloud_penalty(ctx: Any, target: Any, ability: str, named: Any) -> dict[str, int] | None:
    penalty = ctx.typed.get('dust_cloud_save_penalty')
    return {'bonus': -int(penalty)} if penalty else None


@effect('dust_eroding_ac', harmful=True)
def eroding_ac(ctx: Any, row: dict[str, Any]) -> None:
    """The printed reduction does not stack, including another caster's use."""
    from .. import typed_executor as te
    te.run_effects(ctx.with_source(CHOKING), [{**row, 'type': 'ac_bonus', 'source_owned': True,
                                            'refresh_across_owners': True}])


@hook('ai_candidate_allowed')
def choking_ai_recipient(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or (action.parameters.get('typed') or {}).get('source') != CHOKING:
        return None
    from ..relations import relation, ENEMY
    return bool(candidate.target_ids) and all(relation(engine, actor, engine.state.actors[aid]) == ENEMY
                                            for aid in candidate.target_ids)


@hook('compile_actions')
def cloud_move_action(info: dict[str, Any]) -> list[Any] | None:
    if CLOUD not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.dust_cloud.move",
        display_name='Dust Cloud: move', owner_id=info['actor_id'], economy='NONE',
        resolution_kind='TYPED', target_kind='CELL', range_ft=60,
        parameters={'typed': {'source': CLOUD, 'numbers': info['numbers'], 'duration': {'kind':'instant'},
            'effects':[{'type':'move_zone', 'zone_name':'Dust Cloud', 'max_ft':20, 'range_ft':60}], 'riders':[]},
            'dust_cloud_move': True, 'any_cell': True, 'ai_allow_empty_area': True,
            'ai_requires_perceived_destination': True,
            'description':'Once during your turn, move your Dust Cloud up to 20 feet, keeping it within 60 feet of you.'})]


@hook('candidate_allowed')
def cloud_move_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not action.parameters.get('dust_cloud_move'):
        return None
    from .tabik_dark import movable
    aim = candidate.destination
    return aim is not None and not actor.turn_flags.get('moved_zone:Dust Cloud') and any(
        engine.grid.distance_ft(z.center, aim) <= 20
        and not any(tuple(c) in engine.grid.blocked for c in engine.grid.ray_cells(z.center, aim))
        for z in movable(engine, actor, 'Dust Cloud'))
