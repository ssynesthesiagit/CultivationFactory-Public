"""Native activation provenance, shared by mutable techniques and observers
which learn only the activated source (never an actor's catalog).

``profile(engine, actor, action)`` returns source_id, source_cl, source_kind,
qi_powered and weapon_delivery. Explicit compiled provenance wins; resource
cost and canonical source namespaces are mechanical fallbacks. Unknown sources
remain unknown, rather than acquiring a category from their display name.
Heavenly Body's source observer is the only caller.
"""
from __future__ import annotations


def profile(engine, actor, action):
    typed = (action.parameters or {}).get('typed') or {}
    source = str(typed.get('option_of') or typed.get('source') or action.source_definition_id)
    explicit = typed.get('activation_profile') or {}
    kinds = (('tianxia.path.', 'Path'), ('tianxia.subpath.', 'Subpath'),
             ('tianxia.talent.', 'Sphere'), ('TAL_', 'Sphere'),
             ('tianxia.recorded_art.', 'Recorded'), ('tianxia.forged_technique.', 'Forged'),
             ('tianxia.immortal_art.', 'Immortal'), ('tianxia.item.', 'item'),
             ('tianxia.formation.', 'Formation'))
    category = explicit.get('source_kind') or ('Sphere' if typed.get('sphere') else '') or next((k for prefix, k in kinds if source.startswith(prefix)), '')
    numbers = typed.get('numbers') or {}
    level = explicit.get('source_cl', numbers.get('cl'))
    if level is None and category in ('Path', 'Subpath', 'Sphere', 'Recorded', 'Forged', 'Immortal'):
        from .ext.passive_rows import known_level
        level = known_level(engine, actor)
    qi = explicit.get('qi_powered', typed.get('qi_powered'))
    if type(qi) is not bool:
        qi = any(pool == 'resource:core.qi' and amount > 0 for pool, amount in action.costs) or source.startswith(
            ('tianxia.path.qi_cultivation.', 'tianxia.subpath.qi.'))
    return {'source_id': source, 'source_cl': int(level) if type(level) is int else 0,
            'source_kind': str(category), 'qi_powered': int(qi),
            'weapon_delivery': int(explicit.get('weapon_delivery') is True or typed.get('qi_weapon_delivery') is True)}
