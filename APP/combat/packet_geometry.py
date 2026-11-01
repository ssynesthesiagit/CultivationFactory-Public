"""Opt-in, committed physical paths for native creature and object attacks.

Native targeting owns permission, origin, accepted routes and occupied volumes.
This helper snapshots one legal least-covered path at the final pre-draw
checkpoint and publishes it only with its actual committed attack roll. Source
consumers never reconstruct a centre ray or declare a collision themselves.
"""
from fractions import Fraction
from copy import deepcopy
from . import ext

KEY = '_packet_geometry'


def identity(target):
    return getattr(target, 'entity_id', None) or target.object_id


def encoded_point(value):
    from .space import point
    x, y, z = point(value)
    x, y = Fraction(x), Fraction(y)
    return [x.numerator, x.denominator, y.numerator, y.denominator, int(z)]


def segment(engine, start, end):
    from .space import SurfacePoint, surface_ray, ray, point
    if isinstance(start, SurfacePoint) or isinstance(end, SurfacePoint):
        cells = surface_ray(start, end)
    elif start.z or end.z:
        cells = ray(start, end)
    else:
        cells = engine.grid.ray_cells(start, end)
    return {'start': encoded_point(start), 'end': encoded_point(end),
        'cells': [list(point(cell)) for cell in cells]}


def prepare(engine, actor, target, spec, source):
    """Transient geometry only; absent source tracking creates no entry/event."""
    spec.pop(KEY, None)
    requests = ext.run_strict('packet_geometry_tracking', engine, actor, target, spec, source)
    consumers = []
    for values in requests:
        if (not isinstance(values, (list, tuple))
                or any(type(value) is not str or not value for value in values)
                or len(set(values)) != len(values) or set(consumers).intersection(values)):
            raise ValueError('Packet geometry consumers require distinct nonempty namespace strings.')
        consumers.extend(values)
    if not consumers:
        return
    geometry = {'actor_id': actor.entity_id, 'target_id': identity(target), 'source_id': source,
        'target_kind': 'creature' if hasattr(target, 'entity_id') else 'object',
        'segments': [], 'surface_contacts': [], 'consumers': sorted(consumers)}
    if geometry['target_kind'] == 'creature':
        from .shot_geometry import route, contact_path
        accepted = route(engine, actor, target)
        if accepted:
            points = contact_path(accepted)
            geometry['segments'] = [segment(engine, a, b) for a, b in zip(points, points[1:])]
            geometry['surface_contacts'] = deepcopy(accepted.get('surface_contacts') or [])
            geometry['route_source_id'] = accepted['source_id']
        else:
            from .directional_cover import sight_rays, cover_bonus, crossed_edges
            from .effect_cover import rays, ray_bonus
            from .attack_provenance import describe
            candidates = list(sight_rays(engine, actor, target))
            if not candidates:
                # Obscurement can conceal a real physical attack. It does not
                # create a solid obstacle or erase its actual occupied volumes.
                from .shot_geometry import source_cells
                candidates = [(a, b, {'start': list((a.x, a.y, a.z)),
                    'end': list((b.x, b.y, b.z)),
                    'crossed_edges': crossed_edges((a.x, a.y, a.z), (b.x, b.y, b.z))})
                    for a, b, cells in rays(engine, source_cells(engine, actor, target),
                        engine._actor_volume(target), purpose='effect')]
            rated = []
            for a, b, context in candidates:
                data = segment(engine, a, b)
                cover = cover_bonus(engine, actor, target, ranged=spec.get('range_ft') is not None,
                    base=ray_bonus(engine, data['cells'], deep=True) if spec.get('range_ft') is not None else 0,
                    attack=describe(engine, actor, spec, source), ray_paths=[(a, b, context)])
                rated.append((cover, encoded_point(a), encoded_point(b), data))
            if rated:
                geometry['segments'] = [min(rated, key=lambda row: row[:3])[3]]
    else:
        from .object_geometry import aim_cells
        from .effect_cover import rays
        from .asset_anchor_runtime import without_objects
        shadow = without_objects(engine, (target.object_id,))
        candidates = list(rays(shadow, engine._effect_volume(actor), aim_cells(engine, target), purpose='effect'))
        if candidates:
            a, b, cells = min(candidates, key=lambda row: (encoded_point(row[0]), encoded_point(row[1])))
            geometry['segments'] = [segment(engine, a, b)]
    relevant = {}
    for answer in ext.run_strict('packet_geometry_relevant', engine, actor, target, source, geometry):
        if (not isinstance(answer, dict) or set(answer) - set(consumers)
                or relevant.keys() & answer.keys() or any(type(value) is not bool for value in answer.values())):
            raise ValueError('Packet geometry relevance must uniquely name its requested consumer namespaces.')
        relevant.update(answer)
    geometry['consumers'] = [key for key in sorted(consumers) if relevant.get(key, True)]
    if not geometry['consumers']:
        return
    spec[KEY] = geometry


def commit(engine, actor, target, spec, source, roll):
    """Publish only the actual prepared actor/target/source and native roll."""
    geometry = spec.pop(KEY, None)
    if geometry is None:
        return
    if (geometry['actor_id'], geometry['target_id'], geometry['source_id']) != (
            actor.entity_id, identity(target), source):
        raise ValueError('Prepared packet geometry does not match the actual attack.')
    event = next((e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED'
        and e.actor_id == actor.entity_id and e.source_definition_id == source
        and e.target_ids == (identity(target),) and e.payload.get('roll_id') == roll.roll_id), None)
    if event is None:
        raise ValueError('Packet geometry requires its actual committed attack roll.')
    engine._append_event('PASSIVE_TRIGGERED', source, actor_id=actor.entity_id,
        target_ids=(identity(target),), payload={'checkpoint': 'PACKET_GEOMETRY_COMMITTED',
            'attack_roll_id': roll.roll_id, 'attack_sequence': event.sequence, 'geometry': geometry})
    ext.run_strict('packet_geometry_committed', engine, actor, target, source, geometry, roll)
