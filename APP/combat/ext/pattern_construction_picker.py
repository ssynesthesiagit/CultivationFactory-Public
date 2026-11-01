"""Complete staged journey choices for physical Trap and Prepared Array.

Uses pattern_construction's source validation and ordinary payload stock. Each
stage offers every legal value, without enumerating their Cartesian product.
Manual and LOCAL_AUTO seats submit the identical offered command payloads;
drafts spend no time, resources or stock and remain private to their owner.
"""
from copy import deepcopy
from hashlib import sha256
import json

from . import hook
from .pattern_construction import (
    available_site, component_spaces, components, damage_permissions, expiry, position, profile, source_clock, usable_patterns,
)
from ..gate2_runtime_models import Position
from ..journey import require


def point(raw):
    return Position.model_validate(raw)


def square(raw):
    p = point(raw)
    return f'({p.x}, {p.y}), {p.z * 5} feet high'


def reachable(session, aid):
    """Supported, visible squares within natural Touch reach, including here."""
    actor = session.state['actors'][aid]
    here = point(actor['position'])
    for raw in [actor['position'], *session.adjacent(aid)]:
        try:
            p = position(session, raw)
        except ValueError:
            continue
        if session.grid.distance_ft(here, p) <= 5 and session.grid.line_of_sight(here, p):
            yield dict(raw)


def choices(session, aid):
    actor = session.state['actors'][aid]
    p = profile(session, aid)
    if not p or session.state['phase'] != 'travel' or actor['incapacitated']:
        return []
    from .formations import PATTERNS, load_of, construction_radius
    from .consumable_payloads import journey_available
    from .trap import AIMS
    rows = []

    def offer(field, value, label):
        payload = {'field': field, 'value': deepcopy(value)}
        key = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
        rows.append({'id': 'construction:' + key, 'kind': 'construction_choice',
                     'payload': payload, 'auto_select': 0, 'label': label})

    draft = actor.get('construction_draft', {})
    known = usable_patterns(p, actor)
    known = [k for k in known if k in PATTERNS]
    if not draft:
        if p.get('array') and known and components(actor['bundle'], 'array', journey_actor=actor):
            offer('family', 'array', 'Plan a Prepared Array: choose its pattern, location and Nodes; 3 Cultivation Points, '
                  'plus 2 for a permitted second layer; 10 minutes (1 with Rapid Array), lasts 8 hours.')
        if (p.get('trap') and components(actor['bundle'], 'trap', journey_actor=actor)
                and (p.get('trap_key') or actor.get('construction_learning', {}).get('trap_key'))):
            offer('family', 'trap', 'Plan a ritual trap: choose its pattern, footprint and loads; 1 minute, '
                  'no resource cost, lasts 1 hour.')
        return rows
    offer('cancel', '', 'Cancel construction planning; no time, resource or item cost.')
    data = draft.get('data', {})
    family = draft['family']
    if not components(actor['bundle'], family, journey_actor=actor):
        return rows
    if family == 'array':
        if 'pattern' not in data:
            for key in known:
                offer('pattern', key, 'Prepared Array: choose ' + PATTERNS[key]['name'] + ' as the first layer.')
            return rows
        if 'layers' not in data:
            offer('layers', [data['pattern']], 'Prepared Array: use one Pattern Layer, costing 3 Cultivation Points.')
            if 'layered_pattern' in p['formation_talents'] and int(p['numbers']['cl']) >= 5:
                for key in known:
                    if key != data['pattern']:
                        offer('layers', [data['pattern'], key], 'Prepared Array: also install ' + PATTERNS[key]['name']
                              + '; total cost 5 Cultivation Points.')
            return rows
        if 'damage_type' not in data:
            for key in damage_permissions(session, aid) if 'killing_line' in data['layers'] else ['force']:
                offer('damage_type', key, 'Prepared Array: ' + (key.title() + ' damage, using your GM-approved source.'
                      if 'killing_line' in data['layers'] else 'Continue; these layers need no damage-type declaration.'))
            return rows
        if 'center' not in data:
            for raw in reachable(session, aid):
                offer('center', raw, 'Prepared Array: place the Array Eye at ' + square(raw) + ' (Touch range).')
            return rows
        center = point(data['center'])
        if 'site' not in data:
            offer('site', '', 'Prepared Array: use a 20-foot-radius circle (larger with an acquired radius feature).')
            for key, site in session.state.get('construction_sites', {}).items():
                if len(site['cells']) >= 3 and available_site(session, aid, site, center):
                    offer('site', key, 'Prepared Array: cover the known bounded site, ' + site['name'] + '.')
            return rows
        if data['site']:
            site = session.state.get('construction_sites', {}).get(data['site'])
            if not available_site(session, aid, site, center):
                return rows
            cells = site['cells']
        else:
            radius = construction_radius({'formation_talents': p['formation_talents']}, mode='prepared')
            cells = [Position(x=x, y=y, z=center.z).model_dump(mode='json')
                     for x in range(session.grid.width) for y in range(session.grid.height)
                     if session.grid.distance_ft(center, Position(x=x, y=y, z=center.z)) <= radius]
        cells = component_spaces(session, cells)
        if len(cells) < 3:
            return rows
        nodes = data.get('nodes', [])
        if len(nodes) < 3:
            for raw in cells:
                if not any(point(raw) == point(n) for n in nodes):
                    offer('node', raw, f'Prepared Array: install Node {len(nodes) + 1} at ' + square(raw) + '.')
            return rows
    else:
        if 'form' not in data:
            for key, label in [('dart', 'Dart Mechanism'), ('tripwire', 'Tripwire'), ('activation', 'Activation Trap')]:
                if key != 'activation' or journey_available(actor):
                    offer('form', key, 'Ritual trap: choose ' + label + '.')
            return rows
        if not draft.get('footprint_done'):
            cells = data.get('cells', [])
            cap = 1 + sum(int(p['numbers']['cl']) >= n for n in (5, 10, 15))
            live = [r for r in actor.get('constructed_patterns', ()) if r['family'] == 'trap'
                    and r.get('map_id') == session.state['battlefield'].get('stable_id', '')
                    and expiry(r) > source_clock(session, aid)]
            if len(cells) < cap:
                for raw in reachable(session, aid):
                    pos = point(raw)
                    if (any(pos == point(a['position']) for a in session.state['actors'].values())
                            or any(pos == point(c) for c in cells)
                            or any(pos == point(c) for r in live for c in r['cells'])):
                        continue
                    if not cells or any(max(abs(pos.x-point(c).x), abs(pos.y-point(c).y), abs(pos.z-point(c).z)) == 1 for c in cells):
                        offer('cell', raw, 'Ritual trap: add footprint space ' + square(raw) + f' ({len(cells)+1} of at most {cap}).')
            if cells:
                offer('footprint_done', 1, f'Ritual trap: finish this {len(cells)}-space footprint.')
            return rows
        if 'aim' not in data:
            for key, (label, _) in AIMS.items():
                if key != 'auto':
                    offer('aim', key, 'Ritual trap: set the firing direction ' + label + '.')
            return rows
        if data['form'] == 'activation':
            if 'payload_key' not in data:
                for item, spec, amount in journey_available(actor):
                    offer('payload_key', item['key'], f"Activation Trap: load {spec['name']} ({amount} copies available).")
                return rows
            if 'payload_count' not in data:
                amount = next((n for item, _, n in journey_available(actor) if item['key'] == data['payload_key']), 0)
                for n in range(1, amount + 1):
                    offer('payload_count', n, f'Activation Trap: load {n} copies; each trigger activates one copy.')
                return rows
            if 'origin' not in data:
                for raw in data['cells']:
                    offer('origin', raw, 'Activation Trap: fix the item area origin at ' + square(raw) + '.')
                return rows
    live = [r for r in actor.get('constructed_patterns', ()) if r['family'] == family
            and expiry(r) > source_clock(session, aid)]
    if family == 'array':
        limit = load_of(p['numbers'])
    else:
        from .trap import active_trap_limit
        limit = active_trap_limit(p['numbers'], p.get('trap_talents', []))
    if len(live) >= limit and 'replace' not in data:
        for r in live:
            offer('replace', r['id'], 'Replace your active ' + ('array' if family == 'array' else 'trap')
                  + ' at ' + square(r['center']) + '; it ends when construction completes.')
        return rows
    cost = 3 + 2 * (len(data['layers']) - 1) if family == 'array' else 0
    if family == 'array' and actor['resources'].get(p['pool'], 0) < cost:
        return rows
    rows.append({'id': 'construction:build', 'kind': 'prepare_array' if family == 'array' else 'construct_trap',
                 'payload': deepcopy(data), 'auto_select': 0,
                 'label': (f'Complete Prepared Array: {cost} Cultivation Points, '
                           + ('1 minute' if 'rapid_array' in p['formation_talents'] else '10 minutes') + '; lasts 8 hours.'
                           if family == 'array' else 'Complete ritual trap: 1 minute, no resource cost; lasts 1 hour.')})
    return rows


@hook('journey_options')
def menu(session, aid):
    return choices(session, aid)


@hook('journey_command')
def choose(session, aid, kind, payload):
    if kind != 'construction_choice':
        return None
    require(any(row['kind'] == kind and row['payload'] == payload for row in choices(session, aid)),
            'Choose a currently offered construction decision.')
    actor = session.state['actors'][aid]
    field, value = payload['field'], deepcopy(payload['value'])
    if field == 'cancel':
        actor.pop('construction_draft', None)
    elif field == 'family':
        actor['construction_draft'] = {'family': value, 'data': {}}
    else:
        draft = actor['construction_draft']
        if field == 'footprint_done':
            draft[field] = value
        elif field in ('node', 'cell'):
            draft['data'].setdefault('nodes' if field == 'node' else 'cells', []).append(value)
        else:
            draft['data'][field] = value
    session.emit('CONSTRUCTION_PLANNING', aid)
    return True
