"""Ten-Thousand Sword Array: source-owned bonds, commands, intents and fields.

Uses the native source-acquisition/consent ledger, Artifact inventory identity,
equipment hands, action_geometry, typed attack/save packets, movement and zones.
Swords are implements, never actors or independently collectible projections.
All runtime subscribers require this family's compiled ownership.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
import math
from contextvars import ContextVar

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
# Guard Mode: the protected creature gains this AC against ranged attacks. The effect, the choice prompt and
# the player-facing mode text all read this one value, so the text cannot drift from the mechanic.
GUARD_AC_BONUS = 2
GUARD_TEXT = f'Guard Mode: protect one creature within 5 feet; it gains +{GUARD_AC_BONUS} AC against ranged attacks'


def native_sword_record(record):
    """Whether a real owned item is a sword: its native chassis is a sword proficiency group member, or its
    runtime profile declares the weapon classification. The chassis definition must be passed as the weapon,
    or the group lookup (which needs a weapon) can never match a real sword."""
    from factory_authoring.starting_kits import item_definition
    from .integrated_weapons import in_group
    item_id = str((((record or {}).get('chassis')) or {}).get('item_id') or '')
    definition = item_definition(item_id) or {}
    native = bool(definition) and in_group({'source': item_id, 'weapon': definition}, 'sword')
    declared = ((((record or {}).get('runtime_profile')) or {}).get('facts') or {}).get('weapon_classification') == 'sword'
    return native or declared
PATH = 'tianxia.path.qi_cultivation'
INTENTS = ('Dread', 'Severing', 'Arresting', 'Displacing', 'Exposing')
_PACKET_ORIGIN = ContextVar('ten_thousand_swords_packet_origin', default=None)
INTENT_LABELS = {
    'Dread': 'Dread Intent: failed Wisdom save frightens the creature until the start of your next turn; success stops its Reactions until the start of its next turn. Frightened immunity counts as success.',
    'Severing': 'Severing Intent: stop the creature’s Reactions until the start of its next turn; a failed Wisdom save also gives Disadvantage on its next Concentration save before the start of its next turn.',
    'Arresting': 'Arresting Intent: reduce the creature’s Speed by 15 feet on a failed Wisdom save, or 5 feet on success, until the start of your next turn.',
    'Displacing': 'Displacing Intent: push or pull the creature up to 10 feet on a failed Wisdom save, or 5 feet on success.',
    'Exposing': 'Exposing Intent: the creature cannot use Invisible against you until your next turn. A failed Wisdom save also defeats ordinary visual concealment and gives the next sword attack against it Advantage.',
}


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


def bound_action(engine, actor, sword):
    """The native attack action for this bound sword, as the creature actually wielding it.

    A sword bound to its own owner uses that weapon's compiled attack. A borrower's sword is the same physical item
    lent with its owner's permission: the compiler publishes it into the borrower's catalog as a held copy
    (``requires_held_weapon`` names the owner's action), so every normal wielded attack, item property and readiness
    change reads the borrower's own training rather than another creature's action.
    """
    source = str(sword.get('weapon_action') or '')
    if not source:
        return ''
    catalog = (getattr(engine, 'action_catalog', {}) or {})
    action = catalog.get(source)
    if action is not None and action.owner_id == actor.entity_id:
        return source
    return next((row.source_definition_id for row in catalog.values()
                 if row.owner_id == actor.entity_id
                 and (row.parameters or {}).get('requires_held_weapon') == source), source)


def borrower(sword, actor):
    """Whether this actor wields another creature's sword with its permission (one item, one puller)."""
    return bool(sword.get('owner_id')) and sword['owner_id'] != actor.entity_id


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
        lent = any(borrower(s, actor) for s in held['swords'])
        held['swords'] = []
        states[FAMILY] = held
        session.emit('SWORD_SEED_ENDED', aid, source=SEED)
        # Ending a bond to a lent sword recompiles the borrower without the held copy of its owner's weapon.
        return {'sheet': (source_sheet(sheet, session, aid) or deepcopy(sheet)) if lent else None,
                'acquisition_id': 'sword-end:' + str(len(session.state['events']))}
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
    lent = None
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
        require(native_sword_record(record),
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
        if owner != aid:
            # The owner's own compiled attack is the actual item. The borrower's bundle gains the same weapon as a
            # held copy (requires_held_weapon), so the printed Wielded Sword rules use the borrower's own training
            # while the physical sword remains one item.
            lent = next((row for row in session.state['actors'][owner]['bundle'].get('weapons') or ()
                         if row.get('owner_action') == sword['weapon_action']), None)
            require(lent is not None, 'The lent sword has no compiled native attack to hold.')
            sword['lent_weapon'] = deepcopy(lent)
    cost = 1 if slot == 0 else 0
    seconds = 600 if slot == 0 or form == 'real' else 0
    require(actor['resources'].get(QI, 0) >= cost, 'Cultivate Sword Seed takes 10 minutes and costs 1 Qi.')
    actor['resources'][QI] -= cost
    if seconds:
        session.tick(seconds)
    held['swords'][slot:slot+1] = [sword]
    states[FAMILY] = held
    session.emit('SWORD_SEED_CULTIVATED', aid, source=SEED, slot=slot, form=form, item_uid=sword['item_uid'],
                 seconds=seconds, qi_cost=cost, owner_id=sword.get('owner_id') or aid)
    return {'sheet': (source_sheet(sheet, session, aid) or deepcopy(sheet)) if lent else None,
            'acquisition_id': 'sword-seed:' + str(len(session.state['events']))}


@hook('journey_held_weapons')
def held_weapons(session, aid):
    """The compiled weapon rows of swords this creature lawfully holds from another creature.

    Consumers: any native recompile of the holder (the acquisition service passes them to
    compile_character(held_weapons=...)). They are the lender's own bundle rows, so the held copy is the same
    physical item and the holder's own compiled attack. None when nothing is lent.
    """
    data = (session.state['actors'].get(aid) or {}).get('source_states', {}).get(FAMILY) or {}
    rows = [dict(s['lent_weapon']) for s in data.get('swords') or () if isinstance(s.get('lent_weapon'), dict)]
    return rows or None


@hook('journey_combat_setup')
def combat_setup(session, aid):
    s = session.state['actors'][aid].get('source_states', {}).get(FAMILY)
    return {'sword_seed': deepcopy(s)} if s else None


MANIFEST_PREFIX = 'condition:typed.twin_sword_manifest_'
LENT = 'condition:typed.sword_bound_elsewhere'
ROUND_SECONDS = 6


def manifest_seconds(data):
    # Exact remaining seconds per floating sword, persisted as "num/den" strings.
    clocks = {str(k): Fraction(str(v)) for k, v in (data.get('manifest_seconds') or {}).items()}
    for k, rounds in (data.get('manifest_rounds') or {}).items():
        clocks.setdefault(str(k), Fraction(int(rounds) * ROUND_SECONDS))
    return clocks


def restore_manifests(engine, actor, data):
    # Re-apply each manifested sword's remaining one-hour clock imported from the last settled journey fight.
    from .effect_durations import round_token
    current = state(actor)
    for index, seconds in manifest_seconds(data).items():
        i = int(index)
        rounds = math.ceil(seconds / ROUND_SECONDS)
        if i >= len(current['swords']) or current['swords'][i]['location'] != 'floating' or seconds <= 0:
            continue
        marker = 'condition:typed.twin_sword_manifest_' + str(i)
        engine._apply_condition(actor, marker, TWIN, actor.entity_id, expires_on=round_token(engine, int(rounds)),
                                data={'slot': i, 'label': 'Manifest Twin Swords: one hour'})
        current['swords'][i]['manifest_condition'] = marker
    save(engine, actor, current)


@hook('match_initialize')
def initialize(engine):
    for bundle in engine.typed_bundle_documents:
        s = (bundle.get('journey_setup') or {}).get('sword_seed')
        actor = engine.state.actors.get(bundle['actor_id'])
        if s and actor and owned(engine, actor):
            save(engine, actor, deepcopy(s))
            restore_manifests(engine, actor, s)
            custody(engine, actor, s)


def custody(engine, actor, data):
    """One bound sword, one natural holder: the owner loses simultaneous use of a sword it lent.

    The printed binding accepts "a real sword ... used with the owner's permission", so the physical item goes to
    the borrower; the owner cannot keep attacking with it at the same time. This is the engine's existing held-object
    custody record (``disables_action`` + ``held_by``), the same one a taken weapon uses, so the Gate2 weapon gate,
    ``weapon_delivery.available_weapons`` and the borrower's held copy all read one physical possession.
    """
    for sword in data.get('swords') or ():
        owner = engine.state.actors.get(str(sword.get('owner_id') or ''))
        if sword.get('form') != 'real' or owner is None or owner is actor:
            continue
        if any((c.data or {}).get('disables_action') == sword.get('weapon_action')
               and (c.data or {}).get('held_by') == actor.entity_id for c in owner.conditions.values()):
            continue
        engine._apply_condition(owner, LENT, SEED, actor.entity_id, expires_on='UNTIL_REMOVED',
                                data={'disables_action': str(sword.get('weapon_action') or ''),
                                      'held_by': actor.entity_id, 'item_uid': str(sword.get('item_uid') or ''),
                                      'label': 'Bound and wielded by ' + actor.display_name})


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
                EconomyKind.BONUS_ACTION, target='HOSTILE_ENTITY', reach=65, slot=slot)
            # Printed Call the Seed Sword: "at the beginning or end of your Attack action" -- a free call taken in
            # the window the completed Attack action opens (see attack_action_window), not a Bonus Action.
            add('attack_call:' + str(slot), 'Call the Seed Sword during the Attack action' + suffix,
                EconomyKind.NONE, target='SELF', slot=slot)
            if cl >= 18 and RETURN in owned_ids:
                add('return:' + str(slot), 'Return to the Hand' + suffix, EconomyKind.NONE, RETURN, slot=slot)
    if ARRAY in owned_ids and cl >= 10:
        add('array', 'Sword Array Field', EconomyKind.ACTION, ARRAY, target='CELL', reach=60, cost=5)
    if TWIN in owned_ids and cl >= 14:
        add('twins', 'Manifest Twin Swords', EconomyKind.BONUS_ACTION, TWIN, cost=2)
        add('twin_command', 'Twin-Sword Command', EconomyKind.BONUS_ACTION, TWIN)
        for slot in range(2):
            # Printed Twin Sword Refinement: once during each turn, free switch
            # between floating and wielded states (a legal free hand for real swords).
            add('switch:' + str(slot), 'Switch Sword Armament floating and wielded' + (' (second sword)' if slot else ''),
                EconomyKind.NONE, TWIN, slot=slot)
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
    levels = sorted({0, old.z, actor.position.z} | {o.position.z for o in engine.state.actors.values() if o.active})
    for x, y, z in [(x, y, z) for x in range(engine.grid.width) for y in range(engine.grid.height) for z in levels]:
            p = Position(x=x, y=y, z=z)
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


ATTACK_WINDOW = '_sword_attack_call_window'


def attack_window_open(engine, actor):
    return actor.turn_flags.get(ATTACK_WINDOW) == f'{engine.state.round_number}:{engine.state.current_actor_id}'


@hook('action_completed')
def attack_action_window(engine, actor, economy, source_definition_id):
    # An ACTION-economy Attack action opens the free Call window; any other completed ACTION or Bonus Action closes it.
    if engine.state.current_actor_id != actor.entity_id:
        return
    action = engine.action_catalog.get(source_definition_id)
    typed = ((getattr(action, 'parameters', None) or {}).get('typed') or {}) if action is not None else {}
    kind = str(getattr(economy, 'value', economy))
    if action is not None and kind == 'ACTION' and typed.get('attack_action') and not typed.get('reaction_attack')             and not typed.get('opportunity_of') and owned(engine, actor, SEED):
        actor.turn_flags[ATTACK_WINDOW] = f'{engine.state.round_number}:{engine.state.current_actor_id}'
    elif kind in ('ACTION', 'BONUS_ACTION'):
        actor.turn_flags.pop(ATTACK_WINDOW, None)


@hook('candidate_allowed')
def candidates(engine, actor, candidate, action):
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
    if do == 'attack_call':
        from .hand_occupancy import free_hands
        return (attack_window_open(engine, actor) and sword['form'] == 'real' and sword['location'] == 'floating'
                and bool(free_hands(engine, actor)))
    if do in ('call', 'return'):
        from .hand_occupancy import free_hands
        return sword['form'] == 'real' and sword['location'] == 'floating' and bool(free_hands(engine, actor)) and (
            do != 'return' or perfected(engine, actor) and not actor.turn_flags.get('sword_return')
            and any(inside(engine, z, point(sword)) for z in fields(engine, actor)))
    if do == 'switch':
        from .hand_occupancy import free_hands
        if (not owned(engine, actor, TWIN) or int(numbers(engine, actor).get('cl', 0)) < 14
                or actor.turn_flags.get('sword_switch:' + slot)):
            return False
        if sword['location'] == 'wielded':
            return True
        return sword['location'] == 'floating' and sword['form'] == 'real' and bool(free_hands(engine, actor))
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
        weapon = ctx.engine.action_catalog.get(bound_action(ctx.engine, ctx.actor, sword))
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
    if sword['form'] == 'real':
        typed['magic_bonus'] = enhancement  # already included; native item deltas must not pay it twice
    if second:
        typed['granted_attack'] = True
        attack['granted_attack_root'] = True
    action = ctx.action
    if sword['form'] == 'real':
        action = action.model_copy(update={'parameters': {**action.parameters,
            'weapon_source_id': sword['weapon_action'], 'artifact_real_armament': True}})
    flags = {key: value for key, value in ctx.damage_cache.items() if isinstance(key, str)}
    action = action.model_copy(update={'range_ft': 5, 'parameters': {**action.parameters, 'typed': typed}})
    child = replace(ctx, action=action, typed=typed, targets=[target], target=target, damage_cache=flags)
    require(ctx.engine.grid.distance_ft(point(sword), target.position) <= 5,
            'The sword must reach within 5 feet before its attack is resolved.')
    origin = {'id': 'sword:packet', 'label': 'Sword Armament', 'position': point(sword).model_dump(mode='json')}
    token = _PACKET_ORIGIN.set((ctx.engine, ctx.actor.entity_id, ctx.action.source_definition_id,
                               origin, sword.get('slot')))
    try:
        with action_geometry.activate(ctx.engine, ctx.actor, ctx.action.source_definition_id, origin):
            run_effects(child, [attack])
    finally:
        _PACKET_ORIGIN.reset(token)
    ctx.damage_cache.update({key: value for key, value in flags.items() if isinstance(key, str)})


@hook('effect_origins')
def committed_packet_origin(engine, actor, action):
    """Validate only the real command's scoped attack origin, not a menu anchor.

    The normal geometry contract revalidates packet origins during attack and
    reaction checkpoints. The scope contains the actual committed sword slot,
    or the active field's printed pursuit fallback; it grants no remote origin
    to unrelated techniques and never rewrites the actor's position.
    """
    active = _PACKET_ORIGIN.get()
    if active is None or active[:3] != (engine, actor.entity_id, action.source_definition_id):
        return _technique_origins(engine, actor, action)
    _, _, _, origin, slot = active
    p = Position.model_validate(origin['position'])
    if slot is not None and owned(engine, actor):
        swords = state(actor)['swords']
        if 0 <= slot < len(swords):
            sword = swords[slot]
            if sword['location'] == 'floating' and point(sword) == p and not sword.get('destroyed') and not sword.get('suppressed'):
                return [origin]
    if slot is None and owned(engine, actor, ARRAY) and any(inside(engine, z, p) for z in fields(engine, actor)):
        return [origin]
    return []


def sword_technique(engine, actor, action):
    """Whether this Qi-powered technique is a sword technique, by its own native delivery.

    A provider may classify one explicitly (typed.sword_technique). Otherwise the compiled delivery is the test: the
    technique's actual weapon is a sword, which weapon_hits.weapon_has_family resolves from the catalog. No action
    name, damage type or label is read, so every compiled qualifying technique uses the same route.
    """
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('sword_technique') is True or typed.get('sword_array_delivery'):
        return True
    from types import SimpleNamespace
    from .weapon_hits import weapon_has_family
    return weapon_has_family(SimpleNamespace(engine=engine, actor=actor, action=action, typed=typed), 'sword')


def weapon_hit_technique(action):
    """Whether the printed technique requires a real weapon attack (its compiled delivery names a weapon)."""
    typed = (action.parameters or {}).get('typed') or {}
    return bool(typed.get('delivered_by') or typed.get('weapon_source_id') or typed.get('weapon_delivery'))


def _technique_origins(engine, actor, action):
    # Printed Sword-Qi Origin: a Qi-powered sword technique that does not require a physical weapon hit may
    # originate from the cultivator, a Seed Sword / Sword Domain Armament, or one visible sword-path point of the
    # Array. A technique that requires a real weapon attack must use an actual sword, never a projected path.
    if action is None or not owned(engine, actor):
        return None
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('sword_array_delivery'):
        return None
    from ..activation_settlement import profile
    if not profile(engine, actor, action)['qi_powered'] or not sword_technique(engine, actor, action):
        return None
    weapon_hit = weapon_hit_technique(action)
    origins = []
    for index, sword in enumerate(state(actor)['swords']):
        if sword['location'] not in ('floating', 'wielded') or sword.get('destroyed') or sword.get('suppressed'):
            continue
        if weapon_hit and sword['form'] != 'real':
            continue
        origins.append({'id': 'sword:technique:' + str(index), 'label': 'Sword Armament',
                        'position': point(sword).model_dump(mode='json')})
    if not weapon_hit:
        # The field is one network of sword paths: each visible point inside it is a legal origin. Projected
        # points never copy a bound artifact sword's properties, so they only serve techniques that need no weapon hit.
        for index, zone in enumerate(fields(engine, actor)):
            for cell in zone.affected_cells:
                p = Position(x=cell.x, y=cell.y, z=zone.center.z)
                if not engine.grid.in_bounds((cell.x, cell.y)) or not engine.grid.line_of_sight(actor.position, p):
                    continue
                origins.append({'id': f'sword:path:{index}:{cell.x}:{cell.y}',
                                'label': f'Sword path ({cell.x}, {cell.y})',
                                'position': p.model_dump(mode='json')})
    return origins


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
            from ..typed_executor import clock_expiry
            clock = clock_expiry(ctx.engine, 'hours', 1)
            clock_condition = 'condition:typed.twin_sword_manifest_' + str(index)
            ctx.engine._apply_condition(ctx.actor, clock_condition, TWIN, ctx.actor.entity_id,
                                        expires_on=clock, data={'slot': index, 'label': 'Manifest Twin Swords: one hour'})
            sword['manifest_condition'] = clock_condition
            pick = choose(ctx, 'manifest-type:' + str(index), ['slashing', 'force'],
                          {'slashing': 'Slashing damage', 'force': 'Force damage'}, 'Choose this sword’s damage type.')
            sword['damage_type'] = pick[0]
            mode = choose(ctx, 'manifest-mode:' + str(index), ['assault', 'guard'],
                          {'assault': 'Assault Mode: command this sword to attack',
                           'guard': GUARD_TEXT},
                          'Manifest Twin Swords: choose this sword’s initial mode, without using its turn’s mode change.')
            sword['mode'] = mode[0]
            item_placement(ctx.engine, ctx.actor, sword, 'floating')
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
            item_placement(ctx.engine, ctx.actor, s['swords'][index], 'floating')
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
    if do == 'attack_call':
        # Same travel and hand rules as the Bonus Action call; the window is spent by using it.
        require(attack_window_open(ctx.engine, ctx.actor), 'Call the Seed Sword during an Attack action only after taking that action.')
        ctx.actor.turn_flags[ATTACK_WINDOW] = None
        do = 'call'
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
        item_placement(ctx.engine, ctx.actor, sword, 'floating')
        save(ctx.engine, ctx.actor, s)
        strike(ctx, sword, target)
        ctx.actor.turn_flags['sword_commanded:' + slot_text] = True
        return
    if do in ('call', 'return'):
        from .hand_occupancy import free_hands
        from .equipment_hands import set_weapon_readiness
        require(sword['form'] == 'real' and free_hands(ctx.engine, ctx.actor), 'Calling a real sword requires a legal free hand.')
        require(ctx.actor.position in destinations(ctx.engine, ctx.actor, sword, call=True), 'A barrier or restraint blocks this real sword’s call.')
        set_weapon_readiness(ctx.engine, ctx.actor, bound_action(ctx.engine, ctx.actor, sword), True, source=SEED,
                             source_actor_id=ctx.actor.entity_id, hand=free_hands(ctx.engine, ctx.actor)[0])
        sword.update(x=ctx.actor.position.x, y=ctx.actor.position.y, z=ctx.actor.position.z, location='wielded')
        if do == 'return':
            ctx.actor.turn_flags['sword_return'] = True
    elif do in ('release', 'move'):
        move_to(ctx, sword, release=do == 'release', move=do == 'move')
        sword['location'] = 'floating'
        if do == 'release' and int(numbers(ctx.engine, ctx.actor).get('cl', 0)) >= 9:
            pick = choose(ctx, 'release-mode:' + slot_text, ['assault', 'guard'],
                          {'assault': 'Assault Mode: make sword attacks', 'guard': GUARD_TEXT},
                          'Release the Seed Sword: choose its initial mode.')
            sword['mode'] = pick[0]
        if do == 'move':
            ctx.actor.turn_flags['sword_move:' + slot_text] = True
        if sword['form'] == 'real':
            from .equipment_hands import set_weapon_readiness
            set_weapon_readiness(ctx.engine, ctx.actor, bound_action(ctx.engine, ctx.actor, sword), False, source=SEED,
                                 source_actor_id=ctx.actor.entity_id)
    elif do == 'switch':
        from .hand_occupancy import free_hands
        from .equipment_hands import set_weapon_readiness
        if sword['location'] == 'wielded':
            set_weapon_readiness(ctx.engine, ctx.actor, bound_action(ctx.engine, ctx.actor, sword), False, source=SEED,
                                 source_actor_id=ctx.actor.entity_id)
            sword['location'] = 'floating'
        else:
            require(free_hands(ctx.engine, ctx.actor), 'Wielding a floating real sword requires a legal free hand.')
            set_weapon_readiness(ctx.engine, ctx.actor, bound_action(ctx.engine, ctx.actor, sword), True, source=SEED,
                                 source_actor_id=ctx.actor.entity_id, hand=free_hands(ctx.engine, ctx.actor)[0])
            sword.update(x=ctx.actor.position.x, y=ctx.actor.position.y, z=ctx.actor.position.z, location='wielded')
        ctx.actor.turn_flags['sword_switch:' + slot_text] = True
    elif do in ('assault', 'guard'):
        sword['mode'] = do
        ctx.actor.turn_flags['sword_mode:' + slot_text] = True
    item_placement(ctx.engine, ctx.actor, sword, 'hand' if sword['location'] == 'wielded' else 'floating')
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
        from ..target_knowledge import knowledge
        legal = [t for t in ctx.engine.state.actors.values() if t.active
                 and (known := knowledge(ctx.engine, ctx.actor, t)) is not None
                 and inside(ctx.engine, zone, known.position)]
        chosen = choose(ctx, 'storm-targets', [t.entity_id for t in legal],
                        {t.entity_id: t.display_name for t in legal},
                        'Returning Swordstorm: choose any number of creatures in the field. Each makes a Dexterity save against 10d8 Slashing or Force damage and loses Reactions.',
                        maximum=len(legal), decline=True) if legal else []
        for tid in chosen:
            target = ctx.engine.state.actors[tid]
            if not inside(ctx.engine, zone, target.position):
                continue  # a remembered position is not live hidden information
            run_effects(replace(ctx, target=target, targets=[target], damage_cache={}), [field_save(int(n['cl']), storm=True)])


def qualifies(ctx):
    if ctx.typed.get('sword_array_delivery'):
        return True
    from .weapon_hits import weapon_identity, weapon_has_family
    identity = weapon_identity(ctx)
    if any(bound_action(ctx.engine, ctx.actor, s) == identity for s in state(ctx.actor)['swords'] if s['form'] == 'real'):
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
    picks = choose(ctx, 'intent:' + target.entity_id, list(INTENTS), INTENT_LABELS,
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
        # Target-turn lifetimes: Severing always; Dread success (including Frightened immunity) too.
        # A failed Dread save keeps the owner-turn Frightened duration.
        target_duration = {'kind': 'target_next_turn'} if name == 'Severing' or not failed else duration
        effects.append({'type': 'condition', 'applies_to': 'target', 'condition': 'frightened' if name == 'Dread' and failed else 'reaction_denied',
                        'duration': target_duration})
        if name == 'Severing' and failed:
            effects.append({'type': 'disadvantage', 'applies_to': 'target', 'on': 'its next Concentration saving throw', 'duration': target_duration})
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


@hook('turn_end')
def second_sword_guard(engine, actor):
    # Guard Mode for each floating non-primary sword: at the end of your turn, protect one creature within 5 feet
    # of it against ranged attacks (+2 AC) until the start of your next turn. Mirrors qi_path.armament_guard.
    if not owned(engine, actor, TWIN) or not actor.active:
        return
    from .needle import ask, checkpoint_id
    from ..relations import relation
    for index, sword in enumerate(state(actor)['swords']):
        if index == 0 or sword['location'] != 'floating' or sword['mode'] != 'guard' or sword.get('suppressed') or sword.get('destroyed'):
            continue
        at = point(sword)
        nearby = sorted(o.entity_id for o in engine.state.actors.values() if o.active and engine.grid.distance_ft(at, o.position) <= 5)
        if not nearby:
            continue
        names = {eid: engine.state.actors[eid].display_name for eid in nearby}
        friendly = [eid for eid in nearby if relation(engine, actor, engine.state.actors[eid]) == 'ALLY']
        picked = ask(engine, None, checkpoint_id(engine, 'sword_guard', actor.entity_id, str(index)), actor,
                     'choice:needle.sword_array.guard:' + str(index), nearby, labels=names,
                     name='Sword Armament: Guard Mode', feature_id=TWIN, allow_decline=True,
                     preferred=sorted(friendly, key=lambda eid: (eid != actor.entity_id, eid)),
                     target_id=actor.entity_id, prompt=(
                         f"Sword Armament (Guard Mode, second sword): {actor.display_name} chooses one creature within 5 feet of "
                         f"this sword to protect until the start of your next turn. It gains +{GUARD_AC_BONUS} AC against ranged attacks. Which creature?"))
        if not picked or picked[0] not in names:
            continue
        engine._add_modifier(engine.state.actors[picked[0]], TWIN, 'armor_class_vs_ranged', 'ADD', GUARD_AC_BONUS, 'SELF',
                             expires_on=TURN, source_actor_id=actor.entity_id)


def _pursuit_route(engine, actor, s, previous):
    # Nothing is spent here. None: no floating sword can reach the mover, so no attack is possible.
    # (None, []): no sword floats, so the projected Seed Sword strikes instead.
    floating = [w for w in s['swords'] if w['location'] == 'floating']
    if not floating:
        return None, []
    for sword in floating:
        if sword.get('suppressed') or sword.get('destroyed') or sword['mode'] != 'assault':
            continue
        legal = [p for p in [point(sword), *destinations(engine, actor, sword, move=True)]
                 if engine.grid.distance_ft(p, previous) <= 5 and engine.grid.line_of_sight(p, previous)]
        if legal:
            return sword, legal
    return None


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
        route = _pursuit_route(engine, actor, s, previous)
        if route is None:
            continue
        sword, legal = route
        ctx = Context(engine=engine, actor=actor, action=action, intent=intent,
                      typed=action.parameters['typed'], targets=[mover], target=mover)
        selected = choose(ctx, 'pursuit:' + mover.entity_id, ['attack'], {'attack': 'Make the Array Pursuit sword attack'},
                          f"Array Pursuit: {mover.display_name} is leaving your field. Attack before it leaves; once per round, "
                          + ('without spending your Reaction.' if ultimate else 'spending your Reaction.'), decline=True)
        if not selected:
            continue
        if sword is not None:
            picked = choose(ctx, 'pursuit-point:' + mover.entity_id, [str(i) for i in range(len(legal))],
                            {str(i): f'({p.x}, {p.y})' for i, p in enumerate(legal)},
                            f'Array Pursuit: choose the sword position within 5 feet of {mover.display_name} before it leaves.')
            p = legal[int(picked[0])]
            sword.update(x=p.x, y=p.y, z=p.z)
            save(engine, actor, s, ARRAY)
        # The attack is committed: only now are the once-per-round use and the Reaction charged.
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
        if sword is None:
            sword = {'form': 'projected', 'damage_type': 'force', 'item_uid': '', 'x': previous.x, 'y': previous.y, 'z': previous.z}
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
    from .effect_durations import parse_round
    held = state(actor)
    clocks = {}
    for index, sword in enumerate(held['swords']):
        marker = sword.get('manifest_condition')
        live = condition(actor, marker) if marker else None
        parsed = parse_round(live.expires_on) if live and live.expires_on else None
        if parsed is not None and sword['location'] == 'floating':
            remaining = max(1, parsed[0] - int(engine.state.round_number))
            clocks[str(index)] = str(Fraction(remaining * ROUND_SECONDS))
    sources = session.state['actors'][aid].setdefault('source_states', {})
    previous = {k: v for k, v in sources.get(FAMILY, {}).items() if k not in ('manifest_rounds', 'manifest_seconds')}
    sources[FAMILY] = {**previous, **held, 'manifest_seconds': clocks}


@hook('journey_snapshot_actor')
def snapshot_without_manifests(actor, session, aid, engine):
    # Only this family's own one-hour manifestations leave the fight snapshot; their
    # remaining clocks are exported by journey_encounter_settled and ticked by travel.
    if not owned(engine, actor) or not any(c.condition_id.startswith(MANIFEST_PREFIX)
                                           for c in actor.conditions.values()):
        return None
    copy = actor.model_copy(deep=True)
    copy.conditions = {k: c for k, c in copy.conditions.items() if not c.condition_id.startswith(MANIFEST_PREFIX)}
    return copy


@hook('journey_elapsed')
def travel_manifest_clock(session, aid, previous, seconds, moving):
    data = session.state['actors'].get(aid, {}).get('source_states', {}).get(FAMILY)
    if not data or not data.get('manifest_seconds') and not data.get('manifest_rounds'):
        return
    clocks = manifest_seconds(data)
    spent = Fraction(seconds)
    data['manifest_seconds'] = {}
    data.pop('manifest_rounds', None)
    for index, left in clocks.items():
        left -= spent
        if left > 0:
            data['manifest_seconds'][index] = str(left)
        elif 0 <= int(index) < len(data.get('swords', [])):
            # The one-hour manifestation ended during travel: the sword is no longer floating.
            data['swords'][int(index)]['location'] = 'carried'


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
    """Update the one existing Artifact ledger record for this real sword, never allocate another item.

    A lent sword is recorded in its owner's ledger, the bundle that lists the physical object; the borrower never
    gets a second item, and the record names the creature actually holding it. A native treasure without an
    opted-in runtime profile has no ledger record anywhere, so placement stays inert rather than inventing one.
    """
    if sword['form'] != 'real':
        return
    from .. import acquisition_inventory as inventory
    ledger = next((holder for holder in (actor, engine.state.actors.get(str(sword.get('owner_id') or '')))
                   if holder is not None and sword['item_uid'] in inventory.read(holder)), None)
    if ledger is None:
        return
    items = inventory.read(ledger)
    item = items[sword['item_uid']]
    item.update(location=location, holder=actor.entity_id if location != 'space' else '',
                placement_declared=1, placement_revision=int(item.get('placement_revision', 0)) + 1)
    if location in ('space', 'floating'):
        item['position'] = point(sword).model_dump(mode='json')
        item['point'] = [sword['x'], sword['y'], sword.get('z', 0)]
    else:
        item.pop('position', None)
        item.pop('point', None)
        if location == 'hand':
            from .hand_occupancy import occupancy
            action = bound_action(engine, actor, sword)
            item['hand'] = next((part for part, held in occupancy(engine, actor).items()
                                 if 'weapon:' + action in held), item.get('hand', ''))
    inventory.write(engine, ledger, items, SEED)


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
            marker = sword.get('manifest_condition')
            if marker and condition(actor, marker) is None and sword['location'] == 'floating':
                sword['location'] = 'fallen' if sword['form'] == 'real' else 'carried'
                item_placement(engine, actor, sword, 'space')
                changed = True
        if changed:
            save(engine, actor, data)


@hook('effect_player_text')
def player_text(row):
    if row.get('type') != 'sword_array_command':
        return None
    key = str(row.get('command', ''))
    do = key.partition(':')[0]
    texts = {
        'release': 'Bonus Action: release your cultivated sword at an unoccupied point within 30 feet. It floats without occupying space; a real sword must travel through an open route.',
        'call': 'Bonus Action: call your floating real bound sword into a legal free hand through an open route. Barriers, sealed space and restraints can prevent the call.',
        'attack_call': 'Free, during your Attack action: call your floating real bound sword into a legal free hand through an open route, once for that Attack action.',
        'switch': 'Without using an action, once during each turn, move this sword between floating and a legal free hand. Taking a real sword in hand readies its normal weapon attacks; letting go leaves it floating.',
        'move': 'Without using an action, move this floating sword once on your turn, normally 20 feet within 30 feet of you. Domain control and your active sword field can extend its movement and range.',
        'assault': 'Without using an action, change this floating sword to Assault Mode so it can make sword attacks; one mode change on your turn.',
        'guard': f'Without using an action, change this floating sword to Guard Mode. At the end of your turn, protect one creature within 5 feet: it gains +{GUARD_AC_BONUS} AC against ranged attacks until the start of your next turn; one mode change on your turn.',
        'attack': 'Bonus Action: move your floating sword, then make one Cultivation Attack against a creature within 5 feet of it. A projected Seed Sword deals 1d6 plus your Qi key modifier; a real sword uses its eligible item damage and properties. Domain Armament scaling applies from CL9.',
        'array': 'Action, 5 Qi, Concentration for 1 minute: create a 20-foot-radius, 20-foot-high sword field centered within 60 feet. A hostile creature entering for the first time in a turn or starting there makes a Dexterity save: 3d8 Slashing or Force damage, half on success; a failed save stops Reactions until its next turn. Damage is 4d8 from CL17.',
        'twins': 'Bonus Action, 2 Qi, for 1 hour: manifest or release both Sword Armaments, choosing each sword’s damage type and mode. Each floating sword can be commanded separately.',
        'twin_command': 'Bonus Action: declare one attack with each floating sword and resolve them separately. The first uses normal Domain damage; the second deals 2d8 at CL14 or 3d8 from CL17, adding its enhancement but normally no key modifier. Once-per-turn benefits apply to one attack.',
        'origin': 'Action, 8 Qi, once per scene, Concentration for 1 minute: create a 30-foot-radius, 30-foot-high sword field centered within 90 feet. Choose creatures inside for a Dexterity save against 10d8 Slashing or Force damage, half on success. Failed saves stop Reactions through the end of their next turn; success stops them until its start. Your sword array is perfected for the duration.',
        'return': 'Without using an action, once during a turn while the perfected field lasts, call one real bound sword in the field into a legal free hand. A restraint, sealed Formation, spatial lock or stronger control can prevent it.',
    }
    return texts.get(do)


@hook('technique_start')
def attack_start_call(engine, actor, action):
    """Printed Call the Seed Sword: "at the beginning or end of your Attack action". The beginning route is a free
    checkpoint before this Attack's effects. It is asked only in a fight (prefight has no intent) to the current actor.
    """
    from types import SimpleNamespace
    if getattr(engine, '_active_intent', None) is None or engine.state.current_actor_id != actor.entity_id:
        return None
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if not typed.get('attack_action') or getattr(action, 'economy', None) is not EconomyKind.ACTION or not owned(engine, actor, SEED):
        return None
    from .hand_occupancy import free_hands
    s = state(actor)
    if incapacitated(actor) or not free_hands(engine, actor):
        return None
    slots = [str(i) for i, w in enumerate(s['swords'])
             if w['form'] == 'real' and w['location'] == 'floating' and not (w.get('suppressed') or w.get('destroyed'))]
    if not slots:
        return None
    ctx = SimpleNamespace(engine=engine, actor=actor, intent=getattr(engine, '_active_intent', None), action=action, typed=typed, targets=[])
    picks = choose(ctx, 'attack-start-call', slots,
                   {slot: 'Call the Seed Sword' + ('' if slot == '0' else ' (second sword)') for slot in slots},
                   'Call the Seed Sword at the beginning of this Attack action, before its attacks.', decline=True)
    if picks:
        actor.turn_flags[ATTACK_WINDOW] = f'{engine.state.round_number}:{engine.state.current_actor_id}'
        try:
            command(ctx, {'command': 'attack_call:' + picks[0]})
        finally:
            actor.turn_flags.pop(ATTACK_WINDOW, None)
    return None


@hook('weapon_delivery_without_grip')
def remote_sword_delivery(engine, actor, weapon):
    """Sword-Qi Origin: a Qi technique delivered with a floating Seed Sword needs no grip on that sword.

    Printed: a Qi-powered sword technique may originate from the Seed Sword or Sword Domain Armament, and "a
    technique requiring a real weapon attack must use an actual sword". The technique's own compiled delivery names
    one actual sword action, so only that sword is admitted, only while it is floating and usable, and only while the
    owner has the Array. Input: the delivering weapon's action id. Default inert (None) for every other weapon.
    """
    if not owned(engine, actor, ARRAY):
        return None
    data = state(actor)
    return True if any(w['location'] == 'floating' and not (w.get('suppressed') or w.get('destroyed'))
                       and bound_action(engine, actor, w) == weapon for w in data['swords']) else None


@hook('technique_final')
def technique_delivery_call(ctx):
    """Printed Call the Seed Sword: "as part of activating a sword-delivered technique through it".

    The technique's own compiled delivery names the actual sword (``delivered_by``/``weapon_source_id``), so this
    offer exists only when that sword is the floating real Seed Sword. The technique is delivered through the floating
    sword and then called: the Call costs no action, travels through open space into a legal free hand, and runs at
    the end of a normally resolved technique so the scoped activation origin it was declared from stays valid.
    """
    from types import SimpleNamespace
    engine, actor, action = ctx.engine, ctx.actor, ctx.action
    if ctx.intent is None or not owned(engine, actor, SEED) or incapacitated(actor):
        return
    parameters = getattr(action, 'parameters', None) or {}
    typed = parameters.get('typed') or {}
    if not weapon_hit_technique(action):
        return
    from ..weapon_delivery import weapon_identity
    identity = weapon_identity(engine, action.source_definition_id, typed, parameters, owner_id=action.owner_id)
    if not identity:
        return
    from .hand_occupancy import free_hands
    if not free_hands(engine, actor):
        return
    slots = [str(index) for index, w in enumerate(state(actor)['swords'])
             if w['form'] == 'real' and w['location'] == 'floating'
             and not (w.get('suppressed') or w.get('destroyed')) and bound_action(engine, actor, w) == identity]
    if not slots:
        return
    ctx = SimpleNamespace(engine=engine, actor=actor, intent=ctx.intent, action=action, typed=typed, targets=[])
    picks = choose(ctx, 'technique-call', slots,
                   {slot: 'Call the Seed Sword' + ('' if slot == '0' else ' (second sword)') for slot in slots},
                   f'Call the Seed Sword as part of activating {action.display_name} through it: it travels through '
                   'open space into a legal free hand without using another action.', decline=True)
    if picks:
        command(ctx, {'command': 'call:' + picks[0]})


@hook('turn_start_choice')
def off_turn_sword_controls(engine, actor):
    """The printed once-during-each-turn sword controls, on every creature's turn including another creature's.

    Sword Control Inside the Field moves a sword to any visible legal point inside it once during each turn, and
    Return to the Hand calls one real bound sword in the perfected field once during each turn. Twin Sword Refinement
    additionally lets the owner move each floating sword up to its normal movement, switch either between floating
    and wielded states with a legal free hand, and switch either between permitted modes once during each turn --
    with or without a field. Each sword has its own allowances, so every one is a separate option (a second sword is
    never left without its own move), and automatic owners are offered the same controls rather than none.
    """
    from types import SimpleNamespace
    from .hand_occupancy import free_hands
    for owner in list(engine.state.actors.values()):
        if owner is actor or not owner.active or not owned(engine, owner) or incapacitated(owner):
            continue
        s = state(owner)
        tag = f'{engine.state.round_number}:{actor.entity_id}'
        twin = owned(engine, owner, TWIN) and int(numbers(engine, owner).get('cl', 0)) >= 14
        free = bool(free_hands(engine, owner))
        options, labels = [], {}
        for slot, w in enumerate(s['swords']):
            slot_text = str(slot)
            suffix = '' if slot == 0 else ' (second sword)'
            if w.get('suppressed') or w.get('destroyed'):
                continue
            floating = w['location'] == 'floating'
            in_field = floating and any(inside(engine, z, point(w)) for z in fields(engine, owner))
            if floating and not owner.turn_flags.get(f'sword_offturn:move:{slot_text}:{tag}'):
                if in_field and destinations(engine, owner, w, move=True):
                    options.append(f'move:{slot_text}')
                    labels[f'move:{slot_text}'] = 'Move the Seed Sword to any visible point inside the field' + suffix
                elif twin and destinations(engine, owner, w, move=True):
                    options.append(f'move:{slot_text}')
                    labels[f'move:{slot_text}'] = 'Move the Sword Armament up to its normal movement' + suffix
            if twin and not owner.turn_flags.get(f'sword_offturn:switch:{slot_text}:{tag}'):
                if w['location'] == 'wielded' or (floating and w['form'] == 'real' and free):
                    options.append(f'switch:{slot_text}')
                    labels[f'switch:{slot_text}'] = ('Put the Sword Armament away and let it float' if w['location'] == 'wielded'
                                                     else 'Take the floating real Sword Armament in a free hand') + suffix
            if twin and floating and not owner.turn_flags.get(f'sword_offturn:mode:{slot_text}:{tag}'):
                other = 'guard' if w.get('mode') != 'guard' else 'assault'
                options.append(f'{other}:{slot_text}')
                labels[f'{other}:{slot_text}'] = ('Guard Mode: protect one creature within 5 feet with +'
                                                  f'{GUARD_AC_BONUS} AC against ranged attacks' if other == 'guard'
                                                  else 'Assault Mode: command this sword to attack') + suffix
            if (w['form'] == 'real' and floating and free and owned(engine, owner, RETURN)
                    and int(numbers(engine, owner).get('cl', 0)) >= 18 and perfected(engine, owner)
                    and any(inside(engine, z, point(w)) for z in fields(engine, owner))
                    and owner.position in destinations(engine, owner, w, call=True)
                    and not owner.turn_flags.get(f'sword_offturn:return:{tag}')):
                options.append(f'return:{slot_text}')
                labels[f'return:{slot_text}'] = 'Return this real bound sword to your hand (one sword a turn)' + suffix
        if not options:
            continue
        picks = ask(engine, getattr(engine, '_active_intent', None),
                    checkpoint_id(engine, 'sword_array', SEED, 'offturn', owner.entity_id), owner,
                    'choice:needle.sword_array.offturn', options, labels=labels,
                    prompt='Off-turn sword control: once during this turn you may move each floating sword, switch '
                           'either between floating and wielded, switch either between its modes, or call one real '
                           'sword in your field to hand. Each listed choice costs no action.',
                    minimum=0, maximum=len(options), allow_decline=True, default='decline', name='Sword Array',
                    feature_id=SEED)
        if not picks:
            continue
        for pick in picks:
            do, _, slot_text = pick.partition(':')
            sword = state(owner)['swords'][int(slot_text)]
            if do == 'move' and (sword['location'] != 'floating'
                                 or not (twin or any(inside(engine, z, point(sword)) for z in fields(engine, owner)))):
                continue
            if do == 'return' and owner.turn_flags.get(f'sword_offturn:return:{tag}'):
                continue
            ctx = SimpleNamespace(engine=engine, actor=owner, intent=getattr(engine, '_active_intent', None),
                                  action=SimpleNamespace(source_definition_id=SEED), typed={'source': SEED}, targets=[])
            # The same command a normal turn uses; it must not consume the owner's own-turn allowance.
            kept = {k: owner.turn_flags.get(k) for k in (f'sword_move:{slot_text}', f'sword_switch:{slot_text}',
                                                         f'sword_mode:{slot_text}', 'sword_return')}
            command(ctx, {'command': do + ':' + slot_text})
            for k, v in kept.items():
                if v is None:
                    owner.turn_flags.pop(k, None)
                else:
                    owner.turn_flags[k] = v
            key = f'sword_offturn:return:{tag}' if do == 'return' else f'sword_offturn:{do}:{slot_text}:{tag}'
            owner.turn_flags[key] = True
