"""Default-inert Action mechanisms on native Asset/Anchor objects.

A physical object's component.mechanism={name, open: 0|1} declares an adjacent
Action to open/close it. Sources opt into installation with a compiled passive
block=asset_mechanisms, or an existing mechanism object on cold reload.
Only the source creates mechanisms; no door is inferred from an object's name.
"""
from . import hook

PREFIX='system:asset_mechanism.'


@hook('match_start')
def install(engine):
    enabled=any(r.get('block')=='asset_mechanisms' for rows in getattr(engine,'typed_passive_rows',{}).values() for r in rows)
    if not enabled and not any((o.component or {}).get('mechanism') for o in engine.state.objects.values()):return
    from ..gate2_runtime_models import ActionDefinition
    for operation in ('open','close'):
        source=PREFIX+operation
        engine.action_catalog[source]=ActionDefinition(source_definition_id=source,display_name=operation.title()+' structure gate (Action)',
            owner_id='*',economy='ACTION',resolution_kind='TYPED',target_kind='OBJECT',range_ft=5,
            parameters={'asset_mechanism':operation,'expected_damage':0,
                'description':operation.title()+' one gate by its adjacent mechanism, using your Action.'})


@hook('additional_actions')
def mechanism_actions(engine,actor):
    return [k for k in (PREFIX+'open',PREFIX+'close') if k in engine.action_catalog and targets(engine,actor,engine.action_catalog[k])]


@hook('object_targets')
def targets(engine,actor,action):
    operation=(action.parameters or {}).get('asset_mechanism')
    if not operation:return []
    return [o.object_id for o in engine.state.objects.values() if not o.destroyed and
        isinstance((o.component or {}).get('mechanism'),dict) and
        bool(o.component['mechanism']['open'])!=(operation=='open')]


@hook('object_action')
def operate(engine,actor,action,obj,candidate,intent):
    operation=(action.parameters or {}).get('asset_mechanism')
    if not operation:return
    if obj.object_id not in targets(engine,actor,action):raise ValueError('This gate mechanism is not available.')
    if operation=='close':
        from .door_state import closing_blocked
        if closing_blocked(engine,obj):raise ValueError('A creature or solid object is in the closing gate.')
    opened=int(operation=='open')
    comp={**obj.component,'blocks':not bool(opened),'mechanism':{**obj.component['mechanism'],'open':opened}}
    engine._update_object(obj.model_copy(update={'component':comp}),action.source_definition_id,actor.entity_id)
    from ..asset_anchor_runtime import refresh
    refresh(engine)
    return True
