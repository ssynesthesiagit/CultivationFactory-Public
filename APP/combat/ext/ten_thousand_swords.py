"""Ten-Thousand Sword Array: source-owned bonds, commands, intents and fields.

Uses the native source-acquisition/consent ledger, Artifact inventory identity,
equipment hands, action_geometry, typed attack/save packets, movement and zones.
Swords are implements, never actors or independently collectible projections.
All runtime subscribers require this family's compiled ownership.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
import json

from . import hook, effect
from .needle import ask, checkpoint_id, condition, incapacitated
from ..journey import require
from ..gate2_runtime_models import ActionDefinition, EconomyKind, Position
from .. import action_geometry, zones

FAMILY = 'tianxia.subpath.qi.ten_thousand_sword_array_cultivator'
PREFIX = FAMILY + '.feature.'
LEVELS = {'sword_seed': 3, 'sword_intent': 6, 'sword_array_field': 10,
          'twin_sword_refinement': 14, 'ten_thousand_swords_return_to_origin': 18}
SEED, INTENT, ARRAY, TWIN, RETURN = [PREFIX + k for k in LEVELS]
QI = 'resource:core.qi'
STATE = 'condition:typed.ten_thousand_swords'
MARK = 'condition:typed.array_sword_intent'
TURN = 'START_OF_SOURCE_NEXT_TURN'
PATH = 'tianxia.path.qi_cultivation'
INTENTS = ('Dread', 'Severing', 'Arresting', 'Displacing', 'Exposing')


def turn_stamp(engine):
    """One actual turn, including off-turn hits; separate from the owner's turn."""
    return f'{engine.state.round_number}:{engine.state.current_slot_index}'


def owned(engine, actor, source=SEED):
    return any(r.get('block') == 'ten_thousand_swords' and r.get('feature_id') == source
               for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, ()))


def numbers(engine, actor):
    return next((r['numbers'] for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, ())
                 if r.get('block') == 'ten_thousand_swords'), {})


def state(actor):
    c = condition(actor, STATE)
    result = json.loads(c.data['state']) if c else {'swords': []}
    from .qi_path import armament_condition
    primary = armament_condition(actor)
    if primary and (primary.data or {}).get('sword_family') == FAMILY and result['swords']:
        result['swords'][0].update(x=primary.data['ax'], y=primary.data['ay'], mode=primary.data['mode'])
    from ..acquisition_inventory import read
    items = read(actor)
    for sword in result['swords']:
        item = items.get(sword['item_uid'])
        if item:
            sword['suppressed'] = int(bool(item['profile']['flags'].get('suppressed')))
            sword['destroyed'] = int(bool(item['profile']['flags'].get('broken') or item['profile']['flags'].get('consumed')))
            sword['restrained'] = int(item['location'] not in ('floating', 'hand', 'carried'))
    return result


def save(engine, actor, data, source=SEED):
    from .condition_ownership import remove_instance
    c = condition(actor, STATE)
    if c:
        remove_instance(engine, actor, c.instance_id, source)
    engine._apply_condition(actor, STATE, source, actor.entity_id, expires_on='UNTIL_REMOVED',
                            data={'state': json.dumps(data, sort_keys=True), 'label': 'Cultivated Sword Seed'})
    # The primary sword IS the existing Qi Path Armament. Public Qi Path field
    # consumers/movers therefore operate on this identity, rather than a second
    # independently manifestable weapon. Only this source owns this opt-in row.
    from .qi_path import ARMED, armament_condition
    primary = armament_condition(actor)
    first = data['swords'][0] if data['swords'] else None
    if int(numbers(engine, actor).get('cl', 0)) >= 9:
        if primary:
            remove_instance(engine, actor, primary.instance_id, source)
        if first and first['location'] == 'floating' and not first.get('destroyed'):
            engine._apply_condition(actor, ARMED, source, actor.entity_id, expires_on='UNTIL_REMOVED',
                data={'sword_family': FAMILY, 'mode': first['mode'], 'ax': first['x'], 'ay': first['y'],
                      'reach_ft': 60 if int(numbers(engine, actor)['cl']) >= 13 else 30,
                      'item_uid': first['item_uid'], 'label': 'Sword Domain Armament'})


def point(sword):
    return Position(x=sword['x'], y=sword['y'], z=sword.get('z', 0))


def fields(engine, actor):
    return [z for z in engine.state.zones.values() if z.active and z.owner_id == actor.entity_id
            and (z.trigger_profile.get('profile') or {}).get('sword_family') == FAMILY]


def inside(engine, zone, p):
    # Reuse native cylinder cells/height, including an elevated center.
    return any(c.x == p.x and c.y == p.y for c in zone.affected_cells) and (
        zone.center.z <= p.z < zone.center.z + int(zone.trigger_profile.get('height_ft', 20)) // 5)


def perfected(engine, actor):
    return any((z.trigger_profile.get('profile') or {}).get('perfected') for z in fields(engine, actor))


@hook('compile_passives')
def passives(rows, info):
    from ..activation_settlement import path_numbers
    n = path_numbers(info, PATH)
    additions = [{'block': 'ten_thousand_swords', 'feature_id': mid, 'numbers': n}
                 for key, level in LEVELS.items() if (mid := PREFIX + key) in info['owned_ids']
                 and int(n['cl']) >= level]
    return [*(r for r in rows if r.get('block') != 'ten_thousand_swords'), *additions] if additions or any(r.get('block') == 'ten_thousand_swords' for r in rows) else None


def journey_level(actor):
    return int(next((a['parameters']['typed']['numbers'].get('cl', 0) for a in actor['bundle']['action_catalog']
                    if a.get('parameters', {}).get('typed', {}).get('numbers')), 0))


@hook('fact_admission_schema')
def schemas(session, source, subject, kind):
    if source != FAMILY:
        return None
    if kind in ('scripture_access', 'binding_admission'):
        return {'value_type': 'document', 'authority': 'table_owner', 'maximum_seconds': 86400,
                'description': 'Source-scoped Restricted Scripture instruction/access, or exact real-sword touch, sentience, binding and prerequisite facts. Native items, CL and balances are checked separately.'}
    if kind == 'item_permission':
        return {'value_type': 'flag', 'maximum_seconds': 86400,
                'description': 'The actual owner permits this cultivator to bind this exact sword.'}


@hook('journey_source_sheet')
def source_sheet(sheet, session, aid):
    learned = session.state['actors'][aid].get('source_states', {}).get(FAMILY, {}).get('learned', [])
    if not learned:
        return None
    result = deepcopy(sheet)
    ids = result.setdefault('path_and_subpath', {}).setdefault('path_feature_record_ids', [])
    ids.extend(mid for mid in learned if mid not in ids)
    return result


def fact(session, aid, kind, scope, *, subject=None, seconds=0):
    from ..fact_consent_admission import read
    receipt = read(session, FAMILY, subject or aid, kind, scope, aid)
    require(receipt is not None and receipt['expires_at'] >= session.clock() + seconds,
            'Collect the source-scoped authority or consent for the entire procedure first.')
    return receipt


@hook('journey_acquisition')
def acquire(session, aid, source, payload, sheet):
    if source not in (FAMILY, SEED, TWIN):
        return None
    actor = session.state['actors'][aid]
    require(not actor['incapacitated'], 'Cultivation requires an uninterrupted conscious procedure.')
    states = actor.setdefault('source_states', {})
    held = deepcopy(states.get(FAMILY, {'learned': [], 'swords': []}))
    if source == FAMILY:
        paths = (sheet.get('path_and_subpath') or {}).get('paths') or []
        require(QI in actor['resources'] and (any(p.get('path_id') == PATH for p in paths if isinstance(p, dict))
                or (sheet.get('identity') or {}).get('path') == 'Qi Cultivation'),
                'This Restricted Scripture requires an actual Qi Cultivation Path and its native Qi pool.')
        require(set(payload) == {'access_scope'}, 'Choose the recorded Restricted Scripture instruction.')
        admission = fact(session, aid, 'scripture_access', payload['access_scope'])
        value = admission['value']
        require(set(value) == {'source_rule', 'instruction', 'access_category', 'instructor_authority'}
                and value['source_rule'] == FAMILY and value['access_category'] == 'Restricted Scripture'
                and all(type(value[k]) is str and value[k].strip() for k in ('instruction', 'instructor_authority')),
                'Record this exact Restricted Scripture, actual instruction and the instructor’s authority.')
        # Only printed progression at actual effective Qi CL; never grant siblings.
        # The already compiled bundle is authoritative for the present build.
        n = next((a['parameters']['typed']['numbers'] for a in actor['bundle']['action_catalog']
                  if a.get('parameters', {}).get('typed', {}).get('numbers')), {})
        from ..activation_settlement import path_numbers
        n = path_numbers({'numbers': n, 'owner_sheet': sheet}, PATH)
        cl = int(n.get('cl', 0))
        require(cl >= 3, 'Sword Seed requires effective Qi Cultivation Level 3.')
        held['learned'] = [PREFIX + k for k, minimum in LEVELS.items() if cl >= minimum]
        held['access_receipt'] = admission['receipt_id']
        states[FAMILY] = held
        session.emit('SWORD_SCRIPTURE_LEARNED', aid, source=FAMILY, record_ids=held['learned'],
                     access_receipt=admission['receipt_id'])
        return {'sheet': source_sheet(sheet, session, aid), 'acquisition_id': admission['receipt_id']}
    learned = set(held['learned']) | set((sheet.get('path_and_subpath') or {}).get('path_feature_record_ids') or [])
    require(SEED in learned, 'Learn Sword Seed before cultivating a sword.')
    if payload == {'end_bond': 1}:
        held['swords'] = []
        states[FAMILY] = held
        session.emit('SWORD_SEED_ENDED', aid, source=SEED)
        return {'sheet': None, 'acquisition_id': 'sword-end:' + str(len(session.state['events']))}
    require(set(payload) <= {'slot', 'form', 'damage_type', 'item_uid', 'owner_id', 'admission_scope'}
            and set(payload) >= {'slot', 'form', 'damage_type'}, 'Declare the sword slot, projected or real form and damage type.')
    slot = payload['slot']
    require(type(slot) is int and slot in (0, 1) and (slot == 0 or TWIN in learned),
            'Only Twin Sword Refinement permits a second different sword.')
    require(slot <= len(held['swords']), 'Cultivate the first Seed Sword before the second.')
    form = payload['form']
    require(form in ('projected', 'real') and payload['damage_type'] in ('slashing', 'force'),
            'A Seed Sword is projected or a bound real sword; choose Slashing or Force for projections.')
    sword = {'slot': slot, 'form': form, 'damage_type': payload['damage_type'], 'item_uid': '', 'location': 'carried',
             'mode': 'assault', 'x': actor['position']['x'], 'y': actor['position']['y'], 'z': actor['position'].get('z', 0)}
    if form == 'real':
        require(set(payload) == {'slot', 'form', 'damage_type', 'item_uid', 'owner_id', 'admission_scope'},
                'Select one actual inventory sword and its binding admission.')
        owner = payload['owner_id']
        require(owner in session.state['actors'] and (owner == aid or session.near_visible(aid, owner)),
                'Touch the actual present sword throughout the ritual.')
        rows = session.source_inventory.get(owner, [])
        indexed = next(((i, r) for i, r in enumerate(rows) if r['item_uid'] == payload['item_uid']), None)
        require(indexed is not None, 'The exact sword is absent from native inventory.')
        index, item = indexed
        record = item.get('record') or {}
        from factory_authoring.starting_kits import item_definition
        definition = item_definition(str((record.get('chassis') or {}).get('item_id') or '')) or {}
        admission = fact(session, aid, 'binding_admission', payload['admission_scope'], seconds=600)
        v = admission['value']
        require(set(v) == {'item_uid', 'source_rule', 'sword_classification', 'touching', 'external_bonds_clear',
                           'prerequisites_met', 'sentient', 'sentient_consent', 'restraint_clear'}
                and v['item_uid'] == item['item_uid'] and type(v['source_rule']) is str and v['source_rule'].strip()
                and v['sword_classification'] == 'sword'
                and all(type(v[k]) is int and v[k] in (0, 1) for k in
                        ('touching', 'external_bonds_clear', 'prerequisites_met', 'sentient', 'sentient_consent', 'restraint_clear'))
                and all(v[k] for k in ('touching', 'external_bonds_clear', 'prerequisites_met', 'restraint_clear'))
                and (not v['sentient'] or v['sentient_consent']),
                'The actual Source Rule must classify it as a sword and all real binding requirements must hold.')
        # A native known non-sword cannot be relabelled by an admission.
        family = str(definition.get('weapon_family', '')).lower()
        require(not family or any(w in family for w in ('sword', 'jian', 'saber', 'sabre', 'dao')),
                'This actual weapon’s Source Rule does not classify it as a sword.')
        carrying = session.state['actors'][owner]['bundle'].get('carrying', {}).get('items', [])
        physical = next((r for r in carrying if r['key'] == 'given.' + str(index)), None)
        require(physical is not None, 'The sword must actually be carried, not stored elsewhere.')
        uid = item['item_uid']
        require(not any(s['item_uid'] == uid for i, s in enumerate(held['swords']) if i != slot),
                'The same physical sword cannot be bound twice.')
        known = {**getattr(session, 'source_state_records', {}),
                 **{who: a.get('source_states', {}) for who, a in session.state['actors'].items()}}
        require(not any(who != aid and (any(s.get('item_uid') == uid for s in sources.get(FAMILY, {}).get('swords', []))
                        or sources.get('tianxia.path.qi_cultivation.feature.domain_armament', {}).get('item_uid') == uid)
                        for who, sources in known.items()),
                'That exact sword is already another creature’s Armament.')
        if owner != aid:
            require(fact(session, aid, 'item_permission', aid + '|' + uid, subject=owner, seconds=600)['value'] == 1,
                    'The actual sword owner must permit binding.')
        minimum = record.get('minimum_cl', record.get('min_cl', 0))
        require(type(minimum) is int and journey_level(actor) >= minimum, 'Meet the real sword’s cultivation prerequisite.')
        slots = record.get('attunement_slots', 0)
        require(type(slots) is int and (not slots or owner == aid and physical['key'] in actor['bundle'].get('carrying', {}).get('attunement', {}).get('attuned', [])),
                'Meet the real sword’s actual attunement prerequisites.')
        from ..canonical import canonical_sha256
        from ..factory_compiler import compile_native_enchantment_hits
        sword.update(item_uid=uid, owner_id=owner, item_key=physical['key'],
                     weapon_action=physical.get('weapon_action', ''), record_sha256=canonical_sha256(record),
                     automatic_hits=json.dumps(compile_native_enchantment_hits(record.get('enchantments', [])), sort_keys=True),
                     binding_receipt=admission['receipt_id'])
    cost = 1 if slot == 0 else 0
    seconds = 600 if slot == 0 or form == 'real' else 0
    require(actor['resources'].get(QI, 0) >= cost, 'Cultivate Sword Seed takes 10 minutes and costs 1 Qi.')
    actor['resources'][QI] -= cost
    if seconds:
        session.tick(seconds)
    held['swords'][slot:slot+1] = [sword]
    states[FAMILY] = held
    session.emit('SWORD_SEED_CULTIVATED', aid, source=SEED, slot=slot, form=form, item_uid=sword['item_uid'],
                 seconds=seconds, qi_cost=cost)
    return {'sheet': None, 'acquisition_id': 'sword-seed:' + str(len(session.state['events']))}


@hook('journey_combat_setup')
def combat_setup(session, aid):
    s = session.state['actors'][aid].get('source_states', {}).get(FAMILY)
    return {'sword_seed': deepcopy(s)} if s and s.get('swords') else None


@hook('match_initialize')
def initialize(engine):
    for bundle in engine.typed_bundle_documents:
        s = (bundle.get('journey_setup') or {}).get('sword_seed')
        actor = engine.state.actors.get(bundle['actor_id'])
        if s and actor and owned(engine, actor):
            save(engine, actor, deepcopy(s))


@hook('compile_block')
def block(block, spec, row, numbers):
    if block == 'ten_thousand_swords':
        return [{**row, 'block': block}]


def make(info, key, name, economy, source, effects, *, target='SELF', reach=None, cost=0, **params):
    from ..activation_settlement import path_numbers
    n = path_numbers(info, PATH)
    duration = {'kind': 'minutes', 'amount': 1, 'concentration': True} if key in ('array', 'origin') else {'kind': 'instant'}
    return ActionDefinition(source_definition_id='action:typed.' + info['short'] + '.sword_array.' + key,
        display_name=name, owner_id=info['actor_id'], economy=economy, resolution_kind='TYPED',
        target_kind=target, range_ft=reach, costs=((QI, cost),) if cost else (),
        concentration=bool(duration.get('concentration')),
        parameters={'sword_array': key, 'typed': {'source': source, 'numbers': n, 'effects': effects,
                    'riders': [], 'duration': duration, 'qi_powered': True}, **params})


@hook('compile_actions')
def actions(info):
    owned_ids = set(info['owned_ids'])
    if not owned_ids.intersection(PREFIX + k for k in LEVELS):
        return None
    from ..activation_settlement import path_numbers
    n = path_numbers(info, PATH)
    cl = int(n['cl'])
    out = []
    def add(key, name, economy, source=SEED, *, target='SELF', reach=None, cost=0, **params):
        out.append(make(info, key, name, economy, source, [{'type': 'sword_array_command', 'command': key}],
                        target=target, reach=reach, cost=cost, **params))
    if SEED in owned_ids and cl >= 3:
        for slot in range(2 if TWIN in owned_ids and cl >= 14 else 1):
            suffix = '' if slot == 0 else ' (second sword)'
            for do, label, economy in [('release', 'Release the Seed Sword', EconomyKind.BONUS_ACTION),
                                       ('call', 'Call the Seed Sword', EconomyKind.BONUS_ACTION),
                                       ('move', 'Move the Seed Sword', EconomyKind.NONE),
                                       ('assault', 'Sword Armament: Assault Mode', EconomyKind.NONE),
                                       ('guard', 'Sword Armament: Guard Mode', EconomyKind.NONE)]:
                if do in ('assault', 'guard') and cl < 9:
                    continue
                add(do + ':' + str(slot), label + suffix, economy, slot=slot)
            add('attack:' + str(slot), ('Sword Seed' if cl < 9 else 'Sword Domain Armament Attack') + suffix,
                EconomyKind.BONUS_ACTION, target='SINGLE_ENEMY', reach=65, slot=slot)
            if cl >= 18 and RETURN in owned_ids:
                add('return:' + str(slot), 'Return to the Hand' + suffix, EconomyKind.NONE, RETURN, slot=slot)
    if ARRAY in owned_ids and cl >= 10:
        add('array', 'Sword Array Field', EconomyKind.ACTION, ARRAY, target='CELL', reach=60, cost=5)
    if TWIN in owned_ids and cl >= 14:
        add('twins', 'Manifest Twin Swords', EconomyKind.BONUS_ACTION, TWIN, cost=2)
        add('twin_command', 'Twin-Sword Command', EconomyKind.BONUS_ACTION, TWIN)
    if RETURN in owned_ids and cl >= 18:
        add('origin', 'Ten Thousand Swords Return to Origin', EconomyKind.ACTION, RETURN, target='CELL', reach=90, cost=8)
    return out


@hook('compile_zone_spec')
def native_field_profile(spec, action, mechanic):
    if action.parameters.get('sword_array') not in ('array', 'origin'):
        return None
    # The source record's legacy auto-zone is replaced by the complete native
    # command, which installs the same single concentration-linked cylinder.
    return False


def control(engine, actor, sword):
    if any(inside(engine, z, point(sword)) for z in fields(engine, actor)):
        return 60, 40
    from .qi_path import armament_control_range
    cl = int(numbers(engine, actor).get('cl', 0))
    reach = max(60 if cl >= 13 else 30, armament_control_range(engine, actor)) if cl >= 9 else 30
    return reach, (30 if reach >= 60 else 20)


def destinations(engine, actor, sword, *, move=False, release=False, call=False):
    old = point(sword)
    reach, feet = control(engine, actor, sword)
    result = []
    for x in range(engine.grid.width):
        for y in range(engine.grid.height):
            p = Position(x=x, y=y, z=old.z)
            if call and p != actor.position:
                continue
            if not engine.grid.placement_legal(p, occupied_cells=()):
                continue
            if not call and any(other.active and (other.position.x, other.position.y, other.position.z) == (x, y, p.z)
                                for other in engine.state.actors.values()):
                continue
            if engine.grid.distance_ft(actor.position, p) > (30 if release else reach):
                continue
            field_move = move and any(inside(engine, z, old) and inside(engine, z, p) for z in fields(engine, actor))
            if move and not field_move and engine.grid.distance_ft(old, p) > feet:
                continue
            if field_move and not engine.grid.line_of_sight(actor.position, p):
                continue
            if sword['form'] == 'real' or move and not field_move:
                route = engine.grid.shortest_path(old, p, max_cost_ft=None if call or field_move else feet)
                if route is None or not all(engine.grid.line_of_physical_transmission(a, b) for a, b in zip(route[0], route[0][1:])):
                    continue
                if sword.get('restrained'):
                    continue
            result.append(p)
    return result


def choose(ctx, key, options, labels, prompt, *, maximum=1, decline=False, chooser=None):
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'sword_array', ctx.action.source_definition_id,
               key, (chooser or ctx.actor).entity_id), chooser or ctx.actor, 'choice:needle.sword_array.' + key,
               options, labels=labels, prompt=prompt, minimum=0 if decline else 1, maximum=maximum,
               allow_decline=decline, default='decline' if decline else 'first', name='Sword Array',
               feature_id=ctx.typed.get('source', SEED))


def move_to(ctx, sword, *, move=False, release=False, call=False):
    legal = destinations(ctx.engine, ctx.actor, sword, move=move, release=release, call=call)
    require(legal, 'No legal sword path or free destination is available.')
    keys = [str(i) for i in range(len(legal))]
    picks = choose(ctx, 'point:' + str(sword.get('slot', 0)) + ':' + str(move) + ':' + str(release), keys,
                   {str(i): f"({p.x}, {p.y}), {p.z * 5} feet high" for i, p in enumerate(legal)},
                   'Choose a legal visible sword destination; a real sword travels through open space.')
    p = legal[int(picks[0])]
    sword.update(x=p.x, y=p.y, z=p.z)
    return p


@hook('candidate_allowed')
def candidates(engine, actor, candidate, action):
    if action and action.parameters.get('armament') and owned(engine, actor):
        return False  # Seed merges with Domain Armament; never grant another copy.
    key = (action.parameters or {}).get('sword_array') if action else None
    if key is None:
        return None
    if not owned(engine, actor, action.parameters['typed']['source']):
        return False
    s = state(actor)
    if key == 'origin':
        return not s.get('origin_used')
    if key == 'array':
        return True
    if key == 'twins':
        return bool(s['swords'])
    if key == 'twin_command':
        return len(s['swords']) == 2 and all(w.get('location') == 'floating' and w['mode'] == 'assault' for w in s['swords'])
    do, _, slot = key.partition(':')
    if not slot or int(slot) >= len(s['swords']):
        return False
    sword = s['swords'][int(slot)]
    if sword.get('suppressed') or sword.get('destroyed') or incapacitated(actor):
        return False
    if do == 'release':
        return sword['location'] != 'floating'
    if do in ('call', 'return'):
        from .hand_occupancy import free_hands
        return sword['form'] == 'real' and sword['location'] == 'floating' and bool(free_hands(engine, actor)) and (
            do != 'return' or perfected(engine, actor) and not actor.turn_flags.get('sword_return')
            and any(inside(engine, z, point(sword)) for z in fields(engine, actor)))
    if do == 'move':
        return sword['location'] == 'floating' and not actor.turn_flags.get('sword_move:' + slot)
    if do in ('assault', 'guard'):
        return sword['location'] == 'floating' and sword['mode'] != do and not actor.turn_flags.get('sword_mode:' + slot)
    if do == 'attack':
        if sword['location'] != 'floating' or sword['mode'] != 'assault':
            return False
        targets = [engine.state.actors[t] for t in candidate.target_ids if t in engine.state.actors]
        return any(engine.grid.distance_ft(point(sword), t.position) <= control(engine, actor, sword)[1] + 5 for t in targets)
    return None


def strike(ctx, sword, target, *, second=False, pursuit=False):
    from ..typed_executor import run_effects
    if not target.active:
        return
    from ..gate2_runtime_models import DiceSpec
    n = dict(numbers(ctx.engine, ctx.actor))
    cl = int(n['cl'])
    count, sides = ((3 if cl >= 17 else 2 if cl >= 13 else 1), 8) if cl >= 9 else (1, 6)
    if second:
        count, sides = (3 if cl >= 17 else 2), 8
    bonus = int(n.get('key_mod', 0)) if not second or perfected(ctx.engine, ctx.actor) else 0
    types = [sword['damage_type']]
    extra = []
    if sword['form'] == 'real':
        weapon = ctx.engine.action_catalog.get(sword.get('weapon_action'))
        require(weapon is not None, 'The bound sword’s actual weapon profile is unavailable.')
        t = weapon.parameters.get('typed') or {}
        w = t.get('weapon') or {}
        damage = w.get('damage') or {}
        dice = damage
        if not second and int(dice.get('count', 0)) * (int(dice.get('sides', 0)) + 1) > count * (sides + 1):
            count, sides = int(dice['count']), int(dice['sides'])
        enhancement = int(t.get('magic_bonus') or 0)
        n['attack_bonus'] = int(n.get('attack_bonus', 0)) + enhancement
        bonus += enhancement
        types = [str(w.get('damage_type') or sword['damage_type'])]
        # Item property executors enforce their own trigger/cost via the actual
        # weapon profile. Never copy an unrelated item into a projected packet.
        if not second:
            extra = json.loads(sword.get('automatic_hits') or '[]')
    n['key_mod'] = bonus
    damage = {'type': 'damage', 'applies_to': 'target', 'dice': {'count': count, 'sides': sides},
              'formula': 'key_ability_modifier', 'damage_types': types}
    attack = {'type': 'attack', 'attack_kind': 'cultivation_melee', 'count': 1,
              'on_hit': [damage, *extra], 'sword_array_strike': 1, 'second_sword': int(second),
              'no_extra_attacks': int(second)}
    typed = {**ctx.typed, 'numbers': n, 'effects': [attack], 'sword_array_delivery': 1,
             'sword_array_second': int(second), 'sword_real_uid': sword['item_uid']}
    if second:
        typed['granted_attack'] = True
        attack['granted_attack_root'] = True
    action = ctx.action
    if sword['form'] == 'real':
        action = action.model_copy(update={'parameters': {**action.parameters,
            'weapon_source_id': sword['weapon_action'], 'artifact_real_armament': True}})
    flags = {key: value for key, value in ctx.damage_cache.items() if isinstance(key, str)}
    child = replace(ctx, action=action, typed=typed, targets=[target], target=target, damage_cache=flags)
    require(ctx.engine.grid.distance_ft(point(sword), target.position) <= 5,
            'The sword must reach within 5 feet before its attack is resolved.')
    origin = {'id': 'sword:packet', 'label': 'Sword Armament', 'position': point(sword).model_dump(mode='json')}
    with action_geometry.activate(ctx.engine, ctx.actor, ctx.action.source_definition_id, origin):
        run_effects(child, [attack])
    ctx.damage_cache.update({key: value for key, value in flags.items() if isinstance(key, str)})


@effect('sword_array_command')
def command(ctx, eff):
    key = eff['command']
    s = state(ctx.actor)
    if key in ('array', 'origin'):
        return create_field(ctx, key == 'origin')
    if key == 'twins':
        require(s['swords'], 'Cultivate Sword Seed before manifesting its paired armaments.')
        if len(s['swords']) == 1:
            s['swords'].append({'slot': 1, 'form': 'projected', 'damage_type': 'force', 'item_uid': '',
                                'location': 'carried', 'mode': 'assault',
                                'x': ctx.actor.position.x, 'y': ctx.actor.position.y, 'z': ctx.actor.position.z})
        for index, sword in enumerate(s['swords']):
            move_to(ctx, sword, release=True)
            sword['location'] = 'floating'
            sword['expires_round'] = ctx.engine.state.round_number + 600
            pick = choose(ctx, 'manifest-type:' + str(index), ['slashing', 'force'],
                          {'slashing': 'Slashing damage', 'force': 'Force damage'}, 'Choose this sword’s damage type.')
            sword['damage_type'] = pick[0]
            mode = choose(ctx, 'manifest-mode:' + str(index), ['assault', 'guard'],
                          {'assault': 'Assault Mode: command this sword to attack',
                           'guard': 'Guard Mode: protect one creature within 5 feet against ranged attacks'},
                          'Manifest Twin Swords: choose this sword’s initial mode, without using its turn’s mode change.')
            sword['mode'] = mode[0]
        save(ctx.engine, ctx.actor, s, TWIN)
        return
    if key == 'twin_command':
        declarations = []
        for index in range(2):
            # Separate paid attacks and target declarations; all legal recipients
            # remain present, including choosing the same creature twice.
            sword = s['swords'][index]
            from ..senses import perceives
            points = [point(sword), *destinations(ctx.engine, ctx.actor, sword, move=True)]
            legal = [t for t in ctx.engine.state.actors.values() if t.active and t.team_id != ctx.actor.team_id
                     and perceives(ctx.engine, ctx.actor, t)
                     and any(ctx.engine.grid.distance_ft(p, t.position) <= 5
                             and ctx.engine.grid.line_of_sight(p, t.position) for p in points)]
            require(legal, 'Each floating sword needs a legal target within 5 feet.')
            picks = choose(ctx, 'twin-target:' + str(index), [t.entity_id for t in legal],
                           {t.entity_id: t.display_name for t in legal}, 'Twin-Sword Command: choose the creature for this separate sword attack.')
            target = ctx.engine.state.actors[picks[0]]
            points = [p for p in points if ctx.engine.grid.distance_ft(p, target.position) <= 5
                      and ctx.engine.grid.line_of_sight(p, target.position)]
            pick = choose(ctx, 'twin-point:' + str(index), [str(i) for i in range(len(points))],
                          {str(i): f'({p.x}, {p.y}), {p.z * 5} feet high' for i, p in enumerate(points)},
                          f'Twin-Sword Command: declare this sword’s position before attacking {target.display_name}.')
            declarations.append((index, target.entity_id, points[int(pick[0])]))
        for index, tid, p in declarations:
            s['swords'][index].update(x=p.x, y=p.y, z=p.z)
        save(ctx.engine, ctx.actor, s, TWIN)
        for index, tid, p in declarations:
            target = ctx.engine.state.actors[tid]
            if target.active and ctx.engine.grid.distance_ft(p, target.position) <= 5 and ctx.engine.grid.line_of_sight(p, target.position):
                strike(ctx, s['swords'][index], target, second=index == 1)
        ctx.actor.turn_flags['twin_commanded'] = True
        return
    do, _, slot_text = key.partition(':')
    slot = int(slot_text)
    sword = s['swords'][slot]
    if do == 'attack':
        require(ctx.targets, 'Choose the creature attacked by this sword.')
        legal = destinations(ctx.engine, ctx.actor, sword, move=True)
        target = ctx.targets[0]
        legal = [p for p in [point(sword), *legal] if ctx.engine.grid.distance_ft(p, target.position) <= 5
                 and ctx.engine.grid.line_of_sight(p, target.position)]
        require(legal, 'The sword cannot legally reach within 5 feet of that creature.')
        picks = choose(ctx, 'attack-point:' + slot_text, [str(i) for i in range(len(legal))],
                       {str(i): f'({p.x}, {p.y}), {p.z * 5} feet high' for i, p in enumerate(legal)},
                       f'Choose where your sword moves before attacking {target.display_name}, within 5 feet of it.')
        p = legal[int(picks[0])]
        sword.update(x=p.x, y=p.y, z=p.z)
        save(ctx.engine, ctx.actor, s)
        strike(ctx, sword, target)
        ctx.actor.turn_flags['sword_commanded:' + slot_text] = True
        return
    if do in ('call', 'return'):
        from .hand_occupancy import free_hands
        from .equipment_hands import set_weapon_readiness
        require(sword['form'] == 'real' and free_hands(ctx.engine, ctx.actor), 'Calling a real sword requires a legal free hand.')
        require(ctx.actor.position in destinations(ctx.engine, ctx.actor, sword, call=True), 'A barrier or restraint blocks this real sword’s call.')
        set_weapon_readiness(ctx.engine, ctx.actor, sword['weapon_action'], True, source=SEED,
                             source_actor_id=ctx.actor.entity_id, hand=free_hands(ctx.engine, ctx.actor)[0])
        sword.update(x=ctx.actor.position.x, y=ctx.actor.position.y, z=ctx.actor.position.z, location='wielded')
        if do == 'return':
            ctx.actor.turn_flags['sword_return'] = True
    elif do in ('release', 'move'):
        move_to(ctx, sword, release=do == 'release', move=do == 'move')
        sword['location'] = 'floating'
        if do == 'release' and int(numbers(ctx.engine, ctx.actor).get('cl', 0)) >= 9:
            pick = choose(ctx, 'release-mode:' + slot_text, ['assault', 'guard'],
                          {'assault': 'Assault Mode: make sword attacks', 'guard': 'Guard Mode: protect against ranged attacks'},
                          'Release the Seed Sword: choose its initial mode.')
            sword['mode'] = pick[0]
        if do == 'move':
            ctx.actor.turn_flags['sword_move:' + slot_text] = True
        if sword['form'] == 'real':
            from .equipment_hands import set_weapon_readiness
            set_weapon_readiness(ctx.engine, ctx.actor, sword['weapon_action'], False, source=SEED,
                                 source_actor_id=ctx.actor.entity_id)
    elif do in ('assault', 'guard'):
        sword['mode'] = do
        ctx.actor.turn_flags['sword_mode:' + slot_text] = True
    save(ctx.engine, ctx.actor, s)


def field_save(cl, *, storm=False):
    dice = 10 if storm else 4 if cl >= 17 else 3
    denied = {'type': 'condition', 'condition': 'reaction_denied', 'applies_to': 'target',
              'duration': {'kind': 'until_end_of_next_turn' if storm else 'until_start_of_next_turn'}}
    if not storm:
        denied['expires_on'] = 'START_OF_TARGET_NEXT_TURN'
    return {'type': 'save', 'ability': 'dex', 'dc': 'technique_save_dc', 'applies_to': 'target',
            'on_fail': [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': dice, 'sides': 8},
                         'damage_types': ['slashing', 'force']}, denied],
            'on_success': [{'type': 'half_damage', 'applies_to': 'target'},
                           *([{'type': 'condition', 'condition': 'reaction_denied', 'applies_to': 'target',
                               'expires_on': 'START_OF_TARGET_NEXT_TURN',
                               'duration': {'kind': 'until_start_of_next_turn'}}] if storm else [])]}


def create_field(ctx, ultimate):
    from ..typed_executor import run_effects
    n = numbers(ctx.engine, ctx.actor)
    old = fields(ctx.engine, ctx.actor)
    s = state(ctx.actor)
    if ultimate:
        require(not s.get('origin_used'), 'Ten Thousand Swords Return to Origin is once per scene.')
    duration = {'kind': 'minutes', 'amount': 1, 'concentration': True}
    spec = {'name': 'Ten Thousand Swords Return to Origin' if ultimate else 'Sword Array Field',
            'shape': 'cylinder', 'size_ft': 30 if ultimate else 20, 'height_ft': 30 if ultimate else 20,
            'duration': duration, 'profile': {'sword_family': FAMILY, 'perfected': int(ultimate)},
            'triggers': [{'id': 'sword_array_entry_start', 'on': ['enter', 'start'], 'who': 'hostile',
                          'effects': [field_save(int(n['cl']))]}]}
    # The native concentration/zone lifecycle retains one field after merging.
    center = ctx.intent.destination or ctx.actor.position
    for zone in old:
        if not ultimate and not (zone.trigger_profile.get('profile') or {}).get('perfected') or ultimate and zone.center == center:
            zones.remove(ctx.engine, zone, 'SWORD_FIELDS_MERGED' if ultimate else 'REPLACED')
    zone = zones.create(ctx, spec)
    if ultimate:
        s['origin_used'] = 1
        save(ctx.engine, ctx.actor, s, RETURN)
        legal = [t for t in ctx.engine.state.actors.values() if t.active and inside(ctx.engine, zone, t.position)]
        chosen = choose(ctx, 'storm-targets', [t.entity_id for t in legal],
                        {t.entity_id: t.display_name for t in legal},
                        'Returning Swordstorm: choose any number of creatures in the field. Each makes a Dexterity save against 10d8 Slashing or Force damage and loses Reactions.',
                        maximum=len(legal), decline=True) if legal else []
        for tid in chosen:
            target = ctx.engine.state.actors[tid]
            run_effects(replace(ctx, target=target, targets=[target], damage_cache={}), [field_save(int(n['cl']), storm=True)])


def qualifies(ctx):
    if ctx.typed.get('sword_array_delivery'):
        return True
    from .weapon_hits import weapon_identity, weapon_has_family
    identity = weapon_identity(ctx)
    if any(s.get('weapon_action') == identity for s in state(ctx.actor)['swords'] if s['form'] == 'real'):
        return True
    from ..activation_settlement import profile
    return bool(profile(ctx.engine, ctx.actor, ctx.action)['qi_powered'] and (
        ctx.typed.get('sword_technique') is True or weapon_has_family(ctx, 'sword')))


@hook('after_hit_choice')
def sword_intent(ctx, target, kind):
    from ..typed_executor import run_effects
    if not owned(ctx.engine, ctx.actor, INTENT) or not qualifies(ctx) or ctx.actor.turn_flags.get('array_sword_intent') == turn_stamp(ctx.engine):
        return
    cost = 0 if perfected(ctx.engine, ctx.actor) else 1
    if ctx.actor.resources.get(QI, 0) < cost:
        return
    picks = choose(ctx, 'intent:' + target.entity_id, list(INTENTS), {s: s + ' Intent' for s in INTENTS},
                   f"Sword Intent after {ctx.action.display_name} hits {target.display_name}: choose one intent for {cost} Qi; once per turn, until the start of your next turn.",
                   decline=True)
    if not picks:
        return
    name = picks[0]
    if cost:
        ctx.engine._spend_resource(ctx.actor, QI, cost, INTENT)
    ctx.actor.turn_flags['array_sword_intent'] = turn_stamp(ctx.engine)
    from .condition_ownership import remove_instance
    for c in list(target.conditions.values()):
        if c.source_actor_id == ctx.actor.entity_id and c.source_definition_id == INTENT:
            remove_instance(ctx.engine, target, c.instance_id, INTENT)
    for mid, modifier in list(target.modifiers.items()):
        if modifier.source_definition_id == INTENT and modifier.source_actor_id == ctx.actor.entity_id:
            ctx.engine._remove_modifier_instance(target, mid, INTENT)
    ctx.engine._apply_condition(target, MARK, INTENT, ctx.actor.entity_id, expires_on=TURN,
                               data={'intent': name, 'label': name + ' Sword Intent'})
    child = replace(ctx, targets=[target], target=target, effect_source=INTENT)
    from ..typed_executor import condition_immune
    if name == 'Dread' and condition_immune(ctx.engine, target, 'frightened'):
        run_effects(child, [{'type': 'sword_intent_result', 'intent': name, 'failed': 0}])
        return
    run_effects(child,
                [{'type': 'save', 'ability': 'wis', 'dc': 'technique_save_dc', 'applies_to': 'target',
                  'on_fail': [{'type': 'sword_intent_result', 'intent': name, 'failed': 1}],
                  'on_success': [{'type': 'sword_intent_result', 'intent': name, 'failed': 0}]}])


@effect('sword_intent_result')
def intent_result(ctx, eff):
    from ..typed_executor import run_effects
    name, failed = eff['intent'], bool(eff['failed'])
    t = ctx.target or ctx.targets[0]
    duration = {'kind': 'until_start_of_your_next_turn'}
    effects = []
    if name in ('Dread', 'Severing'):
        from ..typed_executor import condition_immune
        if name == 'Dread' and condition_immune(ctx.engine, t, 'frightened'):
            failed = False
        effects.append({'type': 'condition', 'applies_to': 'target', 'condition': 'frightened' if name == 'Dread' and failed else 'reaction_denied',
                        'duration': duration})
        if name == 'Severing' and failed:
            effects.append({'type': 'disadvantage', 'applies_to': 'target', 'on': 'its next Concentration saving throw', 'duration': duration})
    elif name == 'Arresting':
        effects.append({'type': 'speed', 'applies_to': 'target', 'amount': -15 if failed else -5, 'duration': duration})
    elif name == 'Displacing':
        distance = 10 if failed else 5
        if failed:
            picked = choose(ctx, 'displace-distance:' + t.entity_id, ['10', '5', '0'],
                            {'10': 'Move up to 10 feet', '5': 'Move 5 feet', '0': 'Leave this creature in place'},
                            f'Displacing Intent: choose how far to move {t.display_name}, up to 10 feet.')
            distance = int(picked[0])
            if not distance:
                return
        pick = choose(ctx, 'displace:' + t.entity_id, ['push', 'pull'], {'push': 'Push away', 'pull': 'Pull closer'},
                      f"Displacing Intent: push or pull {t.display_name} up to {distance} feet.")
        effects.append({'type': 'forced_movement', 'applies_to': 'target', 'direction': pick[0], 'distance_ft': distance})
    elif name == 'Exposing':
        ctx.engine._apply_condition(t, 'condition:typed.array_exposing', INTENT, ctx.actor.entity_id, expires_on=TURN,
            data={'failed': int(failed), 'next_sword': int(failed), 'label': 'Exposed to the sword cultivator'})
    run_effects(ctx, effects)


@hook('turn_end')
def twin_guard(engine, actor):
    if not owned(engine, actor, TWIN):
        return
    swords = state(actor)['swords']
    if any(w['location'] == 'floating' and (w['mode'] == 'guard' or w['mode'] == 'assault'
           and not actor.turn_flags.get('twin_commanded') and not actor.turn_flags.get('sword_commanded:' + str(i)))
           for i, w in enumerate(swords)):
        engine._apply_condition(actor, 'condition:typed.twin_sword_guard', TWIN, actor.entity_id, expires_on=TURN,
                                data={'label': 'Twin Guard: +1 AC against melee attacks'})
        engine._add_modifier(actor, TWIN, 'armor_class_vs_melee', 'ADD', 1, 'SELF', expires_on=TURN,
                             source_actor_id=actor.entity_id)


def pursue(engine, mover, previous, nxt, intent):
    from ..typed_executor import Context
    if intent is None:
        return
    for actor in engine.state.actors.values():
        if not actor.active or actor.team_id == mover.team_id or not owned(engine, actor, ARRAY):
            continue
        s = state(actor)
        if s.get('pursuit_round') == engine.state.round_number and s.get('pursuit_match') == engine.state.match_id:
            continue
        ultimate = perfected(engine, actor)
        if not ultimate and not actor.reaction_available:
            continue
        field = next((z for z in fields(engine, actor) if inside(engine, z, previous) and not inside(engine, z, nxt)), None)
        if field is None:
            continue
        action = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id and a.parameters.get('sword_array') == 'array'), None)
        if action is None:
            continue
        ctx = Context(engine=engine, actor=actor, action=action, intent=intent,
                      typed=action.parameters['typed'], targets=[mover], target=mover)
        selected = choose(ctx, 'pursuit:' + mover.entity_id, ['attack'], {'attack': 'Make the Array Pursuit sword attack'},
                          f"Array Pursuit: {mover.display_name} is leaving your field. Attack before it leaves; once per round, "
                          + ('without spending your Reaction.' if ultimate else 'spending your Reaction.'), decline=True)
        if not selected:
            continue
        s['pursuit_round'] = engine.state.round_number
        s['pursuit_match'] = engine.state.match_id
        save(engine, actor, s, ARRAY)
        if not ultimate:
            from ..typed_reactions import spend_reaction
            spend_reaction(engine, actor, {'feature_id': ARRAY})
            engine._append_event('REACTION_SPENT', ARRAY, actor_id=actor.entity_id)
        from ..activation_payments import reaction_completed
        if not reaction_completed(engine, actor, ARRAY, consumes_reaction=not ultimate):
            continue
        sword = next((w for w in s['swords'] if w['location'] == 'floating'), None)
        if sword is None:
            sword = {'form': 'projected', 'damage_type': 'force', 'item_uid': '', 'x': previous.x, 'y': previous.y, 'z': previous.z}
        else:
            legal = [p for p in [point(sword), *destinations(engine, actor, sword, move=True)]
                     if engine.grid.distance_ft(p, previous) <= 5 and engine.grid.line_of_sight(p, previous)]
            if not legal:
                continue
            picked = choose(ctx, 'pursuit-point:' + mover.entity_id, [str(i) for i in range(len(legal))],
                            {str(i): f'({p.x}, {p.y})' for i, p in enumerate(legal)},
                            f'Array Pursuit: choose the sword position within 5 feet of {mover.display_name} before it leaves.')
            p = legal[int(picked[0])]
            sword.update(x=p.x, y=p.y, z=p.z)
            save(engine, actor, s, ARRAY)
        strike(ctx, sword, mover, pursuit=True)


@hook('movement_attempt')
def pursuit_walk(engine, mover, previous, nxt, intent):
    pursue(engine, mover, previous, nxt, intent)


@hook('teleport_gate')
def pursuit_teleport(ctx, start, destination):
    pursue(ctx.engine, ctx.actor, start, destination, ctx.intent)
    return None


def exposing(target, owner=None):
    return next((c for c in target.conditions.values()
                 if c.condition_id == 'condition:typed.array_exposing'
                 and (owner is None or c.source_actor_id == owner.entity_id)), None)


@hook('masked_conditions')
def exposed_visibility(engine, viewer, target):
    mark = exposing(target, viewer)
    if mark is None or not owned(engine, viewer, INTENT):
        return None
    ids = {iid for iid, c in target.conditions.items()
           if c.condition_id == 'condition:typed.invisible'
           or mark.data.get('failed') and (c.data or {}).get('ordinary_visual_concealment') == 1}
    return {target.entity_id: ids} if ids else None


@hook('obscurement_ignored')
@hook('zone_obscuration_ignored')
def exposed_ordinary_area(engine, zone, viewer, target):
    mark = exposing(target, viewer)
    if mark is None or not mark.data.get('failed') or not owned(engine, viewer, INTENT):
        return None
    # Authored mundane terrain, never an inference from a named supernatural
    # effect, damage type or absence of Source CL.
    return True if zone.trigger_profile.get('ordinary_visual_concealment') == 1 else None


def sword_action(engine, action):
    if action is None:
        return False
    if action.parameters.get('sword_array') in ('twin_command',) or str(action.parameters.get('sword_array', '')).startswith('attack:'):
        return True
    from ..weapon_delivery import weapon_identity
    from .integrated_weapons import in_group
    typed = action.parameters.get('typed') or {}
    identity = weapon_identity(engine, action.source_definition_id, typed, action.parameters, owner_id=action.owner_id)
    weapon = engine.action_catalog.get(identity)
    return bool(weapon and in_group(weapon.parameters.get('typed') or {}, 'sword'))


@hook('attack_mode')
def exposed_sword_advantage(ctx, target):
    return 'ADVANTAGE' if sword_action(ctx.engine, ctx.action) and any(
        c.condition_id == 'condition:typed.array_exposing' and c.data.get('next_sword')
        for c in target.conditions.values()) else None


@hook('event', nested=True)
def consume_exposing(engine, event_type, kwargs):
    if event_type != 'ATTACK_ROLLED':
        return
    action = engine.action_catalog.get(kwargs.get('source_definition_id'))
    if not sword_action(engine, action):
        return
    from .condition_ownership import remove_instance
    for tid in kwargs.get('target_ids') or ():
        target = engine.state.actors.get(tid)
        if target is None:
            continue
        for c in list(target.conditions.values()):
            if c.condition_id != 'condition:typed.array_exposing' or not c.data.get('next_sword'):
                continue
            data = {**c.data, 'next_sword': 0}
            remove_instance(engine, target, c.instance_id, INTENT)
            # Preserve the exact previously journalled expiry, including source
            # actor and turn count; consuming advantage does not renew sight.
            engine._apply_condition(target, c.condition_id, INTENT, c.source_actor_id,
                                    expires_on=c.expires_on, data=data)


@hook('journey_encounter_settled')
def source_continuation(session, aid, engine, actor):
    if not owned(engine, actor):
        return
    held = state(actor)
    session.state['actors'][aid].setdefault('source_states', {})[FAMILY] = held


@hook('journey_scene_end')
def new_scene(session, previous, current):
    for actor in session.state['actors'].values():
        data = actor.get('source_states', {}).get(FAMILY)
        if data:
            data.pop('origin_used', None)
            data.pop('pursuit_round', None)


@hook('armament_control_range')
def source_control_range(engine, actor):
    if not owned(engine, actor):
        return None
    from .qi_path import base_armament_control_range
    data = state(actor)
    if data['swords'] and any(inside(engine, z, point(data['swords'][0])) for z in fields(engine, actor)):
        return 60
    return max(60 if int(numbers(engine, actor).get('cl', 0)) >= 13 else 30,
               base_armament_control_range(engine, actor))


@hook('armament_relocation_allowed')
def real_armament_route(engine, actor, armed, destination, feet):
    if not owned(engine, actor) or armed.data.get('sword_family') != FAMILY:
        return None
    swords = state(actor)['swords']
    if not swords or swords[0]['form'] != 'real':
        return None
    sword = swords[0]
    if sword.get('restrained') or sword.get('destroyed'):
        return False
    route = engine.grid.shortest_path(point(sword), destination, max_cost_ft=feet)
    return bool(route and all(engine.grid.line_of_physical_transmission(a, b)
                              for a, b in zip(route[0], route[0][1:])))


def item_placement(engine, actor, sword, location):
    """Update the existing Artifact ledger, never allocate another real item."""
    if sword['form'] != 'real':
        return
    from .. import acquisition_inventory as inventory
    items = inventory.read(actor)
    if sword['item_uid'] not in items:
        return
    item = items[sword['item_uid']]
    item.update(location=location, holder=actor.entity_id if location != 'space' else '',
                placement_declared=1, placement_revision=int(item.get('placement_revision', 0)) + 1)
    if location in ('space', 'floating'):
        item['position'] = point(sword).model_dump(mode='json')
        item['point'] = [sword['x'], sword['y'], sword.get('z', 0)]
    else:
        item.pop('position', None)
        item.pop('point', None)
    inventory.write(engine, actor, items, SEED)


@hook('event', priority=-100)
def tethered_swords(engine, event_type, kwargs):
    if event_type != 'MOVEMENT_COMMITTED':
        return
    from .qi_path import nearest_armament_point
    for actor in engine.state.actors.values():
        if not owned(engine, actor):
            continue
        data = state(actor)
        changed = False
        for sword in data['swords']:
            if sword['location'] != 'floating':
                continue
            reach, _ = control(engine, actor, sword)
            if engine.grid.distance_ft(actor.position, point(sword)) <= reach:
                continue
            if sword['form'] == 'real':
                sword['location'] = 'fallen'
                item_placement(engine, actor, sword, 'space')
            else:
                legal = nearest_armament_point(engine, actor, (sword['x'], sword['y']))
                if legal is None:
                    sword['location'] = 'carried'
                else:
                    sword.update(x=legal[0], y=legal[1])
            changed = True
        if changed:
            save(engine, actor, data)


@hook('turn_start')
def manifestation_clock(engine, current):
    for actor in engine.state.actors.values():
        if not owned(engine, actor):
            continue
        data = state(actor)
        changed = False
        for sword in data['swords']:
            if sword.get('expires_round', engine.state.round_number + 1) <= engine.state.round_number and sword['location'] == 'floating':
                sword['location'] = 'fallen' if sword['form'] == 'real' else 'carried'
                item_placement(engine, actor, sword, 'space')
                changed = True
        if changed:
            save(engine, actor, data)
