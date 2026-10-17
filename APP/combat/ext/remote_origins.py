"""Remote-origin providers for Marked Origin and Flow Line Strike.

Shared engine geometry is in combat/action_geometry.py. Providers are pure and
return only current owned anchors. Other remote-origin rider lanes can register
effect_origins without duplicating geometry or moving the caster.
"""
from . import effect, hook


@hook('effect_origins')
def formation_relay_origins(engine, actor, action):
    """Live array anchors for the ally's one granted Cultivation Attack."""
    from .formation_talents import RELAY
    from . import formations as F
    typed = action.parameters.get('typed') or {}
    if typed.get('weapon') or not any(e.get('type') == 'attack' and str(e.get('attack_kind', '')).startswith('cultivation')
                                     for e in typed.get('effects', [])):
        return None
    out = []
    for condition in actor.conditions.values():
        if not condition.condition_id.startswith(RELAY + '.'):
            continue
        zone = engine.state.zones.get(condition.data.get('zone_id'))
        if zone is None or not zone.active or zone.owner_id != condition.source_actor_id:
            continue
        out.extend({'id': 'relay:' + condition.instance_id + '|' + obj.object_id,
                    'label': 'Formation Thread Relay: ' + ('Array Eye' if obj.component.get('role') == 'eye' else 'Node'),
                    'position': obj.position.model_dump(mode='json')}
                   for obj in F.objects_of(engine, zone) if not obj.destroyed and not F.disrupted(obj))
    return out or None


@hook('candidate_allowed')
def relay_target_perceived(engine, actor, candidate, action):
    origin = candidate.metadata.get('effect_origin') or {}
    if not str(origin.get('id', '')).startswith('relay:'):
        return None
    from ..action_geometry import activate
    from ..target_knowledge import located
    with activate(engine, actor, action.source_definition_id, None):
        return all((target := engine.state.actors.get(tid)) is not None and located(engine, actor, target)
                   for tid in candidate.target_ids)


@effect('remote_origin')
def remote_origin_marker(ctx, row):
    """Variant marker; the bound engine origin already governs this activation."""
    return None


@hook('candidate_allowed')
def bound_origin_allowed(engine, actor, candidate, action):
    if action is None:
        return None
    record = candidate.metadata.get('effect_origin')
    if record and action.parameters.get('pattern') == 'killing_line':
        from . import formations as F
        victim = engine.state.actors.get(next(iter(candidate.target_ids), ''))
        zone = F.pulse_source(engine, actor, 'killing_line', victim, action.parameters.get('variant')) if victim else None
        return zone is not None and record['id'] in {o.object_id for o in F.objects_of(engine, zone)}
    return None


@hook('effect_origins')
def ink_and_formation_origins(engine, actor, action):
    typed = action.parameters.get('typed') or {}
    owns_ink_origin = any(row.get('type') == 'remote_origin'
                         and row.get('source_modifier') == 'tianxia.talent.ink.marked_origin'
                         for row in typed.get('effects', []))
    if typed.get('source') == 'INK_BASE_INK_LASH' and owns_ink_origin:
        from ..typed_executor import bears_mark
        from ..target_knowledge import can_see
        return [{'id': 'ink:' + target.entity_id, 'label': f'Ink Mark on {target.display_name}',
                 'position': target.position.model_dump(mode='json')}
                for target in engine.state.actors.values() if target.active
                and bears_mark(target, actor.entity_id, 'ink_mark')
                and engine._distance_actor_to_actor(actor, target) <= 60
                and can_see(engine, actor, target)]
    if action.parameters.get('pattern') != 'killing_line':
        return None
    from . import formations as F
    if 'flow_line_strike' not in F.talents_of(typed.get('numbers')):
        return None
    return [{'id': obj.object_id, 'label': 'Array Eye' if obj.component.get('role') == 'eye' else 'Formation Node',
             'position': obj.position.model_dump(mode='json')}
            for zone in F.arrays(engine, actor.entity_id) if 'killing_line' in F.record(zone).get('layers', [])
            for obj in F.objects_of(engine, zone) if not obj.destroyed and not F.disrupted(obj)]
