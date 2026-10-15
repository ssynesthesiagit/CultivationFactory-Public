"""Printed, acquired movement exceptions shared by choreography consumers.

Permissions are reviewed typed rules, not GM fact declarations or damage tags.
No current broadly applicable lethal-movement exception is invented here.
Future sources opt in through the normal owned feature-block compilation.
"""
from . import hook


@hook('compile_block')
def compile_permission(block, spec, row, numbers):
    if block == 'forced_movement_permission':
        return [{**row, 'block': block, 'lethal': int(spec.get('lethal') == 1),
                 'for_sources': list(spec.get('for_sources') or [])}]
    return None


@hook('forced_hazard_permission')
def permitted(engine, actor, subject, source, destination):
    for row in engine.typed_passive_rows.get(actor.entity_id, []):
        if row.get('block') != 'forced_movement_permission' or row.get('lethal') != 1:
            continue
        if source in (row.get('for_sources') or []):
            return True
    return None
