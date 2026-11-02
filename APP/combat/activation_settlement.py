"""Native activation provenance and settlement, shared by mutable techniques
and observers which learn only the activated source (never an actor's catalog).

``profile(engine, actor, action)`` returns source_id, source_cl, source_kind,
qi_powered and weapon_delivery. Explicit compiled provenance wins; resource
cost and canonical source namespaces are mechanical fallbacks. Unknown sources
remain unknown, rather than acquiring a category from their display name.
``settle(ctx, first_event)`` delivers activation_settlement(ctx, receipt) after
effects, before aftermath. The receipt contains only this actor/action's actual
DAMAGE_COMMITTED events and their types/recipients. Nested foreign sources are
excluded. No subscribers means no change; pauses roll back with the table intent.
"""
from __future__ import annotations


def path_numbers(info, path_id):
    """Project a source's explicit owning-Path profile; preserve legacy sheets.

    Shared compile_passives/compile_actions input may carry owner_sheet. An
    explicit multi-Path row supplies effective CL, key and suppressed PB instead
    of borrowing another Path's chassis. No explicit rows means no change.
    """
    numbers = dict(info['numbers'])
    sheet = info.get('owner_sheet') or {}
    rows = (sheet.get('path_and_subpath') or {}).get('paths') or []
    matches = [p for p in rows if isinstance(p, dict) and p.get('path_id') == path_id]
    if not matches:
        return numbers
    if len(matches) != 1 or type(matches[0].get('effective_cl')) is not int:
        raise ValueError('An explicit owning Path requires one integer effective CL profile')
    path = matches[0]
    cl = path['effective_cl']
    if not 0 <= cl <= 20:
        raise ValueError('The owning Path effective CL must be from 0 through 20')
    numbers['cl'] = cl
    numbers['pb'] = int(path.get('proficiency_bonus') or (2 + max(0, cl - 1) // 4))
    key = str(path.get('key_ability') or '').upper()[:3]
    abilities = (sheet.get('ability_scores_and_statistics') or {}).get('abilities') or []
    ability = next((a for a in abilities if str(a.get('ability') or '').upper()[:3] == key), None)
    if ability is not None:
        numbers['key_mod'] = int(ability['modifier']) if 'modifier' in ability else (int(ability['score']) - 10) // 2
        numbers['attack_bonus'] = numbers['pb'] + numbers['key_mod']
        numbers['save_dc'] = 8 + numbers['attack_bonus']
    return numbers


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


def receipt(ctx, first_event):
    """Project committed packets for one activation, without publishing knowledge."""
    packets = [event for event in ctx.engine.events[first_event:]
               if event.event_type == 'DAMAGE_COMMITTED' and event.actor_id == ctx.actor.entity_id
               and event.source_definition_id == ctx.action.source_definition_id]
    return {**profile(ctx.engine, ctx.actor, ctx.action),
               'action_id': ctx.action.source_definition_id,
               'damage_types': sorted({str(e.payload.get('damage_type') or 'UNTYPED').upper() for e in packets}),
               'recipient_ids': list(dict.fromkeys(tid for e in packets for tid in e.target_ids)),
               'damaged_ids': list(dict.fromkeys(tid for e in packets
                   if int(e.payload.get('hp_damage') or 0) + int(e.payload.get('temporary_hp_absorbed') or 0) > 0
                   for tid in e.target_ids)),
               'first_sequence': first_event, 'last_sequence': len(ctx.engine.events)}


def settle(ctx, first_event):
    from . import ext
    if ext.has('activation_effects_resolved'):
        for reply in ext.iter_strict_all('activation_effects_resolved', ctx, receipt(ctx, first_event)):
            if reply is not None:
                raise ValueError('activation_effects_resolved must return None')
    if ext.has('activation_settlement'):
        for reply in ext.iter_strict_all('activation_settlement', ctx, receipt(ctx, first_event)):
            if reply is not None:
                raise ValueError('activation_settlement must return None')
