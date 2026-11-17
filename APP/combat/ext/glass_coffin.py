"""The caster's printed touch Action to open Glass Coffin Without Death.

Uses bound_objects' exact guarded instance ledger. Opening removes those
instances and its shell; unrelated incapacitation and other owners' shells stay.
"""
from typing import Any
from . import effect, hook
from .bound_objects import bound
from .condition_ownership import remove_instance

COFFIN = 'TAL_GLASS_GLASS_COFFIN_WITHOUT_DEATH'


def shells(engine: Any, owner: Any, holder: Any) -> list[Any]:
    out = []
    for obj in engine.state.objects.values():
        record = bound(obj)
        if obj.destroyed or not record or record.get('owner') != owner.entity_id \
                or record.get('holder') != holder.entity_id:
            continue
        action = engine.action_catalog.get(record.get('source'))
        if action and ((action.parameters or {}).get('typed') or {}).get('source') == COFFIN:
            out.append(obj)
    return out


@hook('compile_actions')
def open_action(info: dict) -> list[Any] | None:
    if COFFIN not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition

    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.glass_open_coffin",
                             display_name='Open Glass Coffin', owner_id=info['actor_id'], economy='ACTION',
                             resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=5,
                             parameters={'typed': {'source': COFFIN, 'effects': [{'type': 'glass_open_coffin'}],
                                                     'numbers': info['numbers'], 'duration': {'kind': 'instant'},
                                                     'riders': []}, 'player_only': True})]


@hook('candidate_allowed')
def open_target(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not any(r.get('type') == 'glass_open_coffin'
                                 for r in ((action.parameters or {}).get('typed') or {}).get('effects') or []):
        return None
    return any(shells(engine, actor, engine.state.actors[tid]) for tid in candidate.target_ids
               if tid in engine.state.actors)


@effect('glass_open_coffin')
def open_coffin(ctx: Any, row: dict) -> None:
    for target in ctx.targets or []:
        for obj in shells(ctx.engine, ctx.actor, target):
            for iid in list(bound(obj).get('conditions') or []):
                if iid in target.conditions:
                    remove_instance(ctx.engine, target, iid, ctx.source)
