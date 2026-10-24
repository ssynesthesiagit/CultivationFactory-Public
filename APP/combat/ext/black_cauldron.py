"""Heaven-Devouring Black Cauldron's source-owned producer and consumers.

Ownership comes from acquired, compiled progression rows. Essence is deliberately
separate from the Maw Body/Daemonic Sphere pool: it cannot be transferred or
recursively spent on its producing activation. Native conditions, object and zone
events carry all durable state; transient contexts are never saved.
"""
from copy import deepcopy
from contextlib import contextmanager
from itertools import combinations

from . import hook, effect
from .needle import ask, checkpoint_id, condition, timed_condition, say
from .effect_durations import holder_next_turn
from ..activation_settlement import profile, path_numbers

PARENT = 'tianxia.subpath.qi.heaven_devouring_black_cauldron'
PREFIX = PARENT + '.feature.'
RESIDUE, DIGEST, ART, REFINE, FIELD = (
    PREFIX + name for name in ('swallow_the_residue', 'digest_the_broken_art',
    'swallow_the_art', 'refine_the_stolen_principle', 'heaven_devouring_cauldron'))
TIERS = {RESIDUE: 3, DIGEST: 6, ART: 10, REFINE: 14, FIELD: 18}
QI = 'resource:core.qi'
CORRUPTION = 'resource:named.corruption'
STORE = 'condition:typed.black_cauldron_essence'
SCENE = 'condition:typed.black_cauldron_scene'
RUPTURE = 'condition:typed.black_cauldron_rupture'
LOCK = 'condition:typed.black_cauldron_no_essence'
VALID = ('ACID', 'COLD', 'FIRE', 'FORCE', 'LIGHTNING', 'NECROTIC',
         'POISON', 'PSYCHIC', 'RADIANT', 'THUNDER')


def owned(engine, actor, feature=RESIDUE):
    from ..cultivation_access import effective_cl
    return next((r for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())
                 if r.get('block') == 'black_cauldron' and r.get('feature_id') == feature
                 and effective_cl(engine, actor, int(r['numbers']['cl'])) >= TIERS[feature]), None)


def numbers(engine, actor):
    row = owned(engine, actor)
    if row is None:
        return {}
    from ..cultivation_access import effective_cl
    ns = dict(row['numbers'])
    level = effective_cl(engine, actor, int(ns['cl']))
    if level < int(ns['cl']):
        ns['cl'] = level
        ns['pb'] = min(int(ns['pb']), 2 + max(0, level - 1) // 4)
        ns['save_dc'] = 8 + int(ns['pb']) + int(ns['key_mod'])
    return ns


@hook('compile_passives')
def acquire(rows, info):
    if not any(fid in info['owned_ids'] for fid in TIERS):
        return rows
    ns = path_numbers(info, 'tianxia.path.qi_cultivation')
    additions = [{'block': 'black_cauldron', 'feature_id': fid, 'numbers': ns,
                  'choice_owner': True} for fid, tier in TIERS.items()
                 if fid in info['owned_ids'] and int(ns['cl']) >= tier]
    return [*rows, *additions]


@hook('compile_resources')
def cauldron_resources(info):
    if RESIDUE not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ResourceDefinition
    return [ResourceDefinition(resource_id=CORRUPTION, maximum=10, initial=0)]


@hook('compile_action')
def native_actions(action, info):
    typed = action.parameters.get('typed') or {}
    source = typed.get('option_of') or typed.get('source')
    if source not in TIERS:
        return None
    params = deepcopy(action.parameters)
    params['typed']['manual_inline_choice'] = True
    params['typed']['numbers'] = path_numbers(info, 'tianxia.path.qi_cultivation')
    utility = params.get('black_cauldron_utility') or params.get('black_cauldron_move')
    params['cauldron_trigger_only'] = source != FIELD and not utility
    changes = {}
    if source == FIELD and not utility:
        params['typed']['effects'] = [{'type': 'black_cauldron_field'}]
        params['typed']['riders'] = []
        # The persisted source scene ledger owns this limit across encounters.
        # A second match-long use pool would remain empty in the next scene.
        counter = 'resource:uses.' + action.source_definition_id
        changes['costs'] = tuple((pool, amount) for pool, amount in action.costs if pool != counter)
    return action.model_copy(update={'parameters': params, **changes})


@hook('compile_actions')
def utility_actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    if RESIDUE not in info['owned_ids']:
        return None
    ns = path_numbers(info, 'tianxia.path.qi_cultivation')
    made = [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.black_cauldron.manifestation",
        display_name='Black Cauldron Manifestation', owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF', parameters={'black_cauldron_utility': True, 'setting_only': True,
            'typed': {'source': RESIDUE, 'numbers': ns, 'manual_inline_choice': True,
                      'effects': [{'type': 'black_cauldron_manifestation'}], 'riders': [], 'duration': {'kind': 'instant'}}})]
    if FIELD not in info['owned_ids'] or ns['cl'] < 18:
        return made
    made.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.black_cauldron.move",
        display_name='Move Cauldron Anchor', owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF', parameters={'black_cauldron_move': True,
            'typed': {'source': FIELD, 'numbers': ns, 'manual_inline_choice': True,
                      'effects': [{'type': 'black_cauldron_move'}], 'riders': [], 'duration': {'kind': 'instant'}}}))
    return made


@hook('candidate_allowed')
def admission(engine, actor, candidate, action):
    if action is None:
        return None
    if action.parameters.get('cauldron_trigger_only'):
        return False
    typed = action.parameters.get('typed') or {}
    if action.parameters.get('black_cauldron_utility'):
        return bool(owned(engine, actor))
    if action.parameters.get('black_cauldron_move'):
        return bool(fields(engine, actor)) and actor.turn_flags.get('_round_black_cauldron_move') != turn_id(engine)
    if typed.get('source') == FIELD:
        return bool(owned(engine, actor, FIELD)) and not scene(actor).get('field_used')
    return None


@hook('choice_reactors')
def choice_owners(engine):
    return tuple(a.entity_id for a in engine.state.actors.values() if owned(engine, a))


def scene(actor):
    row = condition(actor, SCENE)
    return deepcopy(row.data) if row else {}


def store(actor):
    row = condition(actor, STORE)
    return deepcopy(row.data.get('essences', [])) if row else []


def save_scene(engine, actor, data):
    write_condition(engine, actor, SCENE, RESIDUE,
                    {**data, 'label': 'Black Cauldron: uses and Corruption triggers for this scene'})


def save_store(engine, actor, entries):
    write_condition(engine, actor, STORE, RESIDUE,
                    {'essences': entries, 'label': 'Devoured Essence: ' +
                     (', '.join(e['type'].title() for e in entries) or 'none') +
                     '. Unspent Essence deals 1d6 Force each when the scene ends.'})


def write_condition(engine, actor, name, source, data):
    held = condition(actor, name)
    if held:
        engine._update_condition_data(actor, held, data, source)
    else:
        engine._apply_condition(actor, name, source, actor.entity_id,
                                expires_on='UNTIL_REMOVED', data=data)


def activation_id(engine):
    from ..paid_relocation import current_activation
    view = current_activation(engine)
    if view is not None and view.activation_id:
        return view.activation_id
    intent = getattr(engine, '_active_intent', None)
    return str(getattr(intent, 'intent_id', '') or getattr(engine, '_transaction_id', '') or engine.state.event_sequence)


@hook('activation_accounting')
def track_activations(engine):
    if any(owned(engine, actor) for actor in engine.state.actors.values()):
        return True


@hook('activation_prepare')
def prepare_incoming_profile(action, engine, user, candidate, intent):
    if not any(owned(engine, actor) for actor in engine.state.actors.values()):
        return None
    typed = action.parameters.get('typed')
    if not typed:
        return None
    sealed = deepcopy(typed)
    sealed['track_damage_provenance'] = True
    source = str(sealed.get('option_of') or sealed.get('source') or '')
    if action.owner_id == user.entity_id and action.source_definition_id in user.action_ids and source:
        sealed['known_damage_features'] = list(dict.fromkeys([*sealed.get('known_damage_features', []), source]))
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': sealed}})


def turn_id(engine):
    current = engine.state.actors.get(engine.state.current_actor_id)
    return f'{engine.state.round_number}:{engine.state.current_actor_id}:{current.turns_started if current else 0}'


def choose(engine, owner, key, options, prompt, *, target=None, labels=None, maximum=1, optional=True):
    return ask(engine, getattr(engine, '_active_intent', None),
               checkpoint_id(engine, 'black_cauldron_' + key, owner.entity_id, target.entity_id if target else ''),
               owner, 'choice:needle.black_cauldron_' + key, options,
               labels=labels, prompt=prompt, maximum=maximum, allow_decline=optional,
               target_id=target.entity_id if target else owner.entity_id,
               name=prompt.split(':', 1)[0], feature_id=RESIDUE)


def roll(engine, owner, count, sides, feature, modifier=0):
    from ..gate2_runtime_models import DiceSpec
    result = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=modifier),
        actor_id=owner.entity_id, reason='BLACK_CAULDRON:' + feature, critical=False)
    engine._record_roll(result)
    return max(0, int(result.total))


def corrupt(engine, owner, count=1):
    if CORRUPTION not in owner.resources:
        raise ValueError('Black Cauldron requires its acquired Corruption resource.')
    engine._gain_resource(owner, CORRUPTION, count, RESIDUE)


def spend(engine, owner, entries, source):
    existing = store(owner)
    for entry in entries:
        if entry not in existing or entry['activation'] == activation_id(engine):
            raise ValueError('Essence cannot be transferred or spent in the activation that produced it.')
        existing.remove(entry)
    save_store(engine, owner, existing)
    say(engine, source, owner, f"{owner.display_name} spends {len(entries)} Devoured Essence.")


def raw_damage(engine, owner, count, sides, kind, source, *, unpreventable=False, ignore_resistance=False):
    amount = roll(engine, owner, count, sides, source)
    previous_pierce = getattr(engine, '_black_cauldron_ignore_resistance', None)
    if ignore_resistance:
        engine._black_cauldron_ignore_resistance = (owner.entity_id, owner.entity_id, kind)
    try:
        engine._commit_damage(owner, amount, kind, source, owner.entity_id,
                              getattr(engine, '_active_intent', None), reaction_depth=0,
                              source_flags=('unpreventable',) if unpreventable else ())
    finally:
        engine._black_cauldron_ignore_resistance = previous_pierce


def rupture_consent(engine, owner):
    return bool(not scene(owner).get('ruptured') and choose(engine, owner, 'rupture', ['accept'],
        f'Cauldron Rupture: {owner.display_name} would gain Corruption from predatory refinement. '
        'Accept losing all Essence, 3d10 Force plus 3d10 Necrotic damage ignoring Resistance, '
        'and maximum Qi reduced by your proficiency bonus until a Long Rest and 1 hour of purification?',
        labels={'accept': 'Accept Cauldron Rupture and resolve the feature'}))


def gain(engine, owner, kind, count, source, *, art=False, accepted_rupture=False):
    if not owned(engine, owner) or kind not in VALID or condition(owner, LOCK):
        return 0
    entries, data = store(owner), scene(owner)
    capacity = int(numbers(engine, owner)['pb'])
    added = min(count, max(0, capacity - len(entries)))
    if not added:
        return 0
    triggers = []
    if len(entries) + added >= 3 and not data.get('held_three'):
        triggers.append('held_three')
    if art and added >= 2 and not data.get('swallowed_two'):
        triggers.append('swallowed_two')
    rupture = False
    if triggers and owner.resources.get(CORRUPTION, 0) >= 10:
        if data.get('ruptured') or not (accepted_rupture or rupture_consent(engine, owner)):
            return 0
        rupture = True
    for _ in range(added):
        entries.append({'type': kind, 'activation': activation_id(engine)})
    save_store(engine, owner, entries)
    for key in triggers:
        data[key] = 1
    if triggers and not rupture:
        corrupt(engine, owner, len(triggers))
    if rupture:
        data['ruptured'] = 1
        save_store(engine, owner, [])
        raw_damage(engine, owner, 3, 10, 'FORCE', RESIDUE, ignore_resistance=True)
        raw_damage(engine, owner, 3, 10, 'NECROTIC', RESIDUE, ignore_resistance=True)
        maximum = owner.resource_maximums[QI]
        penalty = int(numbers(engine, owner)['pb'])
        owner.resource_maximums[QI] = max(0, maximum - penalty)
        owner.resources[QI] = min(owner.resources[QI], owner.resource_maximums[QI])
        engine._append_event('RESOURCE_MAXIMUM_CHANGED', RESIDUE, actor_id=owner.entity_id,
            payload={'resource_id': QI, 'maximum': owner.resource_maximums[QI], 'current': owner.resources[QI]})
        timed_condition(engine, owner, RUPTURE, RESIDUE, owner.entity_id, 'UNTIL_REMOVED',
                        {'penalty': penalty, 'long_rest': 0, 'purification_seconds': 0,
                         'label': 'Cauldron Rupture: maximum Qi reduced until a Long Rest and 1 hour of purification'})
        timed_condition(engine, owner, LOCK, RESIDUE, owner.entity_id, holder_next_turn(owner),
                        {'label': 'Cauldron Rupture: cannot gain Essence until your next turn starts'})
    save_scene(engine, owner, data)
    return added


def legal_hostile(engine, owner, user):
    if user is None or user.entity_id == owner.entity_id or user.team_id == owner.team_id:
        return False
    summon = getattr(user, 'summon', None)
    return not (getattr(user, 'owner_id', None) == owner.entity_id or
                summon is not None and summon.get('owner') == owner.entity_id)


@effect('black_cauldron_manifestation')
def manifestation(ctx, row):
    from ..fact_consent_admission import admit_choice
    from .qi_path import armament_condition
    from .scoundrel_riders import possessions
    if not owned(ctx.engine, ctx.actor):
        return
    options = ['projected', 'internal']
    labels = {'projected': 'Projected vessel: no occupied space and no independent target',
              'internal': 'Internal mouth or furnace: no occupied space and no independent target'}
    items = {r['object']: r for r in possessions(ctx.engine, ctx.actor)}
    for key, item in items.items():
        options.append(key)
        labels[key] = 'Bind your actual cauldron implement: ' + str(item.get('name') or item.get('key') or 'carried item')
    if int(numbers(ctx.engine, ctx.actor)['cl']) >= 9 and armament_condition(ctx.actor):
        options.append('armament')
        labels['armament'] = 'Shape your manifested Domain Armament as a cauldron'
    record = admit_choice(ctx, ctx.actor, RESIDUE, 'cauldron_manifestation', 'manifestation', options,
        labels=labels, prompt=f'Black Cauldron Manifestation: {ctx.actor.display_name} chooses its vessel. '
        'A real implement must be the actual bound cauldron you carry; it remains a targetable real item. No cost.',
        expires_on='UNTIL_REMOVED', automatic_options=['projected', 'internal'])
    if record:
        write_condition(ctx.engine, ctx.actor, 'condition:typed.black_cauldron_manifestation', RESIDUE,
            {'mode': record['value'], 'admission': record['receipt_id'],
             'label': 'Black Cauldron: ' + labels[record['value']]})


def conduction(engine, owner, target):
    from .qi_path import armament_condition, armament_point, armament_control_range
    from ..gate2_runtime_models import Position
    form = condition(owner, 'condition:typed.black_cauldron_manifestation')
    if (int(numbers(engine, owner).get('cl', 0)) < 9 or form is None or form.data.get('mode') != 'armament'
            or armament_condition(owner) is None):
        return False
    x, y = armament_point(owner)
    point = Position(x=x, y=y)
    if (engine.grid.distance_ft(owner.position, point) > armament_control_range(engine, owner)
            or engine._distance_actor_to_cell(target, point) > 10):
        return False
    return boundary_open(engine, owner, point, remote_reaction=True)


def boundary_open(engine, owner, point, *, remote_reaction=False):
    from ..zone_sources import of
    ray = set(engine.grid.effect_ray_cells(owner.position, point))
    level = int(numbers(engine, owner)['cl'])
    for zone in engine.state.zones.values():
        if not zone.active or not ray.intersection((p.x, p.y, p.z) for p in zone.affected_cells):
            continue
        source = of(zone) or {}
        tags = set(source.get('source_tags') or [])
        blockers = {'consecrated', 'anti_daemonic'} if remote_reaction else {'sealed_boundary'}
        if tags.intersection(blockers) and level <= int(source.get('source_cl', 0)):
            return False
    return engine.grid.line_of_physical_transmission(owner.position, point)


def source_action(engine, source):
    return engine.action_catalog.get(source)


def perceived(engine, owner, target):
    from ..target_knowledge import can_see
    return target.entity_id == owner.entity_id or can_see(engine, owner, target)


def ready_reaction(engine, owner, target, feature):
    from ..typed_reactions import can_use_reaction
    return bool(owned(engine, owner, feature)) and can_use_reaction(engine, owner, target, {'feature_id': feature})


def pay_reaction(engine, owner, target, feature, qi=0):
    from ..typed_reactions import open_reaction
    open_reaction(engine, {'feature_id': feature}, owner, (target.entity_id,), 'DAMAGE_APPLICATION')
    if qi:
        engine._spend_resource(owner, QI, qi, feature)
    engine._append_event('REACTION_RESOLVED', feature, actor_id=owner.entity_id,
                         target_ids=(target.entity_id,), payload={'checkpoint': 'DAMAGE_APPLICATION'})


CANCEL = '_black_cauldron_rider_cancellations'


def fields(engine, owner):
    return [z for z in engine.state.zones.values() if z.active and z.owner_id == owner.entity_id
            and (z.trigger_profile.get('profile') or {}).get('black_cauldron') == 1]


def in_field(engine, owner, target):
    from ..zones import actor_inside_zone
    return any(actor_inside_zone(engine, target, z) for z in fields(engine, owner))


@hook('damage_pending')
def intercept(engine, target, pending, source, by):
    if pending <= 0 or engine.__dict__.get('_damage_unreduced') == target.entity_id:
        return None
    action = source_action(engine, source)
    user = engine.state.actors.get(by)
    kind = str(getattr(engine, '_typed_pending_damage_type', '')).upper()
    if kind not in VALID:
        return None
    from ..pending_damage import current
    retire_receipt(engine, source, target, current(engine), kind)
    from ..damage_provenance import packet_profile
    typed = packet_profile(engine, source) or (action.parameters.get('typed') or {} if action else {})
    incoming = profile(engine, user, action) if action and user else {}
    for owner in engine.state.actors.values():
        if not owned(engine, owner):
            continue
        keymod = int(numbers(engine, owner)['key_mod'])
        # Defensive Digestion answers any matching damage, including a nearby
        # enemy if the player chooses. It never generates Essence.
        matches = [e for e in store(owner) if e['type'] == kind and e['activation'] != activation_id(engine)]
        close = engine._distance_actor_to_actor(owner, target) <= 10 or conduction(engine, owner, target)
        if matches and close and perceived(engine, owner, target) and ready_reaction(engine, owner, target, DIGEST):
            if choose(engine, owner, 'defend', ['use'],
                f'Defensive Digestion: {target.display_name} takes {pending} {kind.title()} damage from '
                f'{action.display_name if action else "the effect"}. Spend 1 matching Essence and your Reaction '
                'for Resistance to this packet, or reduce it by 2d8 plus your Qi key modifier if already resistant?', target=target):
                from ..typed_reactions import resistance_profile
                resistant = resistance_profile(engine, target, kind, typed,
                    source_id=source, source_actor_id=by)['resist']
                spend(engine, owner, matches[:1], DIGEST)
                pay_reaction(engine, owner, target, DIGEST)
                pending = max(0, pending - roll(engine, owner, 2, 8, DIGEST, keymod)) if resistant else pending // 2
                continue
        if not legal_hostile(engine, owner, user) or not incoming.get('qi_powered'):
            continue
        from ..pending_damage import current
        packet = current(engine)
        flags = packet.source_flags if packet is not None else ()
        if any(typed.get(k) or k in flags for k in ('cannot_reduce', 'voluntary_price', 'permanent_sacrifice', 'lifespan_loss', 'pure_conceptual')):
            continue
        self_target = owner.entity_id == target.entity_id
        protected = (target.team_id == owner.team_id and in_field(engine, owner, target)
                     and perceived(engine, owner, target) and
                     (engine._distance_actor_to_actor(owner, target) <= 60 or any(
                         engine.grid.distance_ft(z.center, target.position) <= 60 for z in fields(engine, owner)))
                     and (in_field(engine, owner, user) or in_field(engine, owner, target)))
        instant = not (typed.get('duration') or {}).get('concentration') and (
            bool(typed.get('area')) or any(e.get('attack_kind') == 'cultivation_ranged'
                                         for e in typed.get('effects') or []))
        for feature, price, count, sides in ((ART, 3, 4, 10), (RESIDUE, 1, 2, 8)):
            if feature == ART and not (instant and (self_target or protected)):
                continue
            if feature == RESIDUE and not (self_target or conduction(engine, owner, target)):
                continue
            flag = '_round_black_cauldron_' + feature.rsplit('.', 1)[-1]
            if (owner.turn_flags.get(flag) == engine.state.round_number or owner.resources.get(QI, 0) < price
                    or not ready_reaction(engine, owner, target, feature)):
                continue
            name = 'Swallow the Art' if feature == ART else 'Swallow the Residue'
            if not choose(engine, owner, 'swallow', [kind],
                f'{name}: {action.display_name} deals {pending} {kind.title()} damage to {target.display_name}. '
                f'Spend {price} Qi and your Reaction to reduce this damage by {count}d{sides} plus your Qi key modifier?',
                target=target, labels={kind: f'Swallow {kind.title()} damage ({price} Qi and Reaction)'}):
                continue
            before = pending
            pending = max(0, pending - roll(engine, owner, count, sides, feature, keymod))
            full = before > 0 and pending == 0
            n = 2 if feature == ART and full else 1 if feature == RESIDUE and pending < before else 0
            contested = False
            if feature == ART and n and incoming['source_cl'] >= int(numbers(engine, owner)['cl']) + 3:
                check = engine.roll_check(modifier=keymod + int(numbers(engine, owner)['pb']),
                    actor_id=owner.entity_id, reason='CULTIVATION_CHECK:' + ART)
                engine._record_roll(check)
                if check.total < int((typed.get('numbers') or {}).get('save_dc') or 10):
                    n = 1
                    contested = True
            if (kind == 'RADIANT' or typed.get('consecrated')) and incoming['source_cl'] > int(numbers(engine, owner)['cl']):
                n = 0
            stored = store(owner)
            added = min(n, max(0, int(numbers(engine, owner)['pb']) - len(stored)))
            status = scene(owner)
            triggers_corruption = (added > 0 and len(stored) + added >= 3 and not status.get('held_three') or
                                   feature == ART and added >= 2 and not status.get('swallowed_two'))
            accepted = False
            if triggers_corruption and owner.resources.get(CORRUPTION, 0) >= 10:
                accepted = rupture_consent(engine, owner)
                if not accepted:
                    pending = before
                    continue
            pay_reaction(engine, owner, target, feature, price)
            owner.turn_flags[flag] = engine.state.round_number
            if feature == ART and full and not contested:
                remember_cancellation(engine, owner, target, source, kind, typed, current(engine))
            if n:
                gain(engine, owner, kind, n, feature, art=feature == ART, accepted_rupture=accepted)
            if feature == ART:
                shell(engine, owner, target, source)
            break
    return pending


def remember_cancellation(engine, owner, target, source, kind, typed, packet):
    """Swallow the Art left no damage of ``kind`` in this packet for this target.

    The printed clause makes damage-dependent riders carried solely by the
    chosen type fail against you. A mixed-type activation resolves one packet
    per type, so the receipt names the swallowed type and survives the other
    types' packets; ``swallowed_riders`` then suppresses only riders whose own
    damage claim is that one type. The receipt dies with the packet's own
    aftermath: a later packet of the SAME type to the same target, or a new
    transaction, retires it, so a later hit of the same activation never
    inherits it. Transient, never saved.
    """
    receipts = engine.__dict__.setdefault(CANCEL, {})
    receipts[(source, target.entity_id)] = {
        'kind': kind, 'owner': owner.entity_id, 'typed': sorted(damage_types(typed.get('effects'))),
        'transaction': getattr(engine, '_transaction_id', None),
        'sequence': None if packet is None else packet.event_sequence}


def retire_receipt(engine, source, target, packet, kind):
    """Drop a cancellation once a different packet of the same type resolves for this target.

    A mixed-type activation's Fire and Cold packets carry different sequences;
    the Cold packet must not retire the Fire receipt before the Fire-dependent
    riders have been resolved.
    """
    receipts = engine.__dict__.get(CANCEL) or {}
    receipt = receipts.get((source, target.entity_id))
    if (receipt is not None and receipt['kind'] == kind
            and (packet is None or receipt['sequence'] is None
                 or packet.event_sequence != receipt['sequence'])):
        receipts.pop((source, target.entity_id), None)


def carried_by(effect, receipt):
    """Whether this rider's own typed wording ties it to the swallowed type.

    Typed data marks damage leaves explicitly but has no flag for "only if the
    damage landed", so the row's own evidence/on text is the statement of that
    tie. A row that names damage types is carried by them; in a mixed-type
    activation "the damage" alone names no type, so only wording that says the
    swallowed type, or an activation with no other type to carry it, ties the
    row to what Swallow the Art consumed.
    """
    kinds = {str(k).upper() for k in effect.get('damage_types') or []}
    if kinds:
        return kinds <= {receipt['kind']}
    text = ' '.join(str(effect.get(key) or '') for key in ('evidence', 'on')).lower()
    if receipt['kind'].lower() in text:
        return True
    return 'damage' in text and receipt['typed'] == [receipt['kind']]


@hook('rider_suppressed')
def swallowed_riders(ctx, effect):
    """A fully swallowed type's damage-dependent riders fail.

    Only the packet's own damage-carried consequences are suppressed: a
    successful-save branch is not carried by the damage, a row carrying a
    different damage type is not carried solely by the swallowed one, and a row
    whose wording never mentions damage is an ordinary hit rider. Absent a live
    receipt, this returns None and every other character is unaffected.
    """
    engine, target = ctx.engine, ctx.target
    if target is None or getattr(ctx, 'failed_save', None) is False:
        return None
    receipts = engine.__dict__.get(CANCEL) or {}
    receipt = receipts.get((ctx.damage_source, target.entity_id))
    if receipt is None:
        return None
    if receipt['transaction'] != getattr(engine, '_transaction_id', None):
        receipts.pop((ctx.damage_source, target.entity_id), None)
        return None
    return True if carried_by(effect, receipt) else None


def shell(engine, owner, target, source):
    from .. import granted_movement
    from . import qi_path
    options = ['hp', 'step', 'save']
    if qi_path.armament_condition(owner):
        options.append('armament')
    labels = {'hp': 'Gain Temporary Hit Points equal to twice proficiency bonus',
              'step': 'Move up to 10 feet without Opportunity Attacks',
              'save': 'Advantage on next save against this source before your next turn ends',
              'armament': 'Move your Domain Armament up to 20 feet'}
    choice = choose(engine, owner, 'shell', options,
        f'Cauldron Shell: {owner.display_name} has swallowed damage to {target.display_name}; choose one free benefit.',
        labels=labels, optional=False)
    if not choice:
        return
    if choice[0] == 'hp':
        engine._grant_temp_hp(owner, 2 * int(numbers(engine, owner)['pb']), ART, owner.entity_id)
    elif choice[0] == 'save':
        timed_condition(engine, owner, 'condition:typed.black_cauldron_save', ART, owner.entity_id,
            holder_next_turn(owner, 'end'), {'source': source, 'label': 'Cauldron Shell: Advantage on next save against the swallowed source until your next turn ends'})
    elif choice[0] == 'step':
        destinations = list(granted_movement.candidates(engine, owner, 10,
                            getattr(engine, '_active_intent', None), ART).values())
        # Movement helper owns legal routes, knowledge, OAs and full choices.
        if destinations:
            opts = {str(i): c for i, c in enumerate(destinations)}
            selected = choose(engine, owner, 'shell_step', list(opts),
                f'Cauldron Shell: choose {owner.display_name}’s route up to 10 feet without Opportunity Attacks.',
                labels={key: f'Move to ({c.destination.x}, {c.destination.y}), {c.destination.z * 5} feet high'
                        for key, c in opts.items()})
            if selected:
                selected = opts[selected[0]]
                granted_movement.resolve_path(engine, owner, selected.canonical_path, ART,
                    feet=10, intent=getattr(engine, '_active_intent', None), provokes=False,
                    mode=selected.metadata.get('movement_mode'))
    else:
        from ..gate2_runtime_models import Position
        origin = qi_path.armament_point(owner)
        points = [Position(x=x, y=y) for x in range(engine.grid.width) for y in range(engine.grid.height)
                  if engine.grid.distance_ft(origin, (x, y)) <= 20
                  and engine.grid.distance_ft(owner.position, (x, y)) <= qi_path.armament_control_range(engine, owner)
                  and engine.grid.volume_legal(Position(x=x, y=y))]
        if points:
            labels = {str(i): f'Move the Armament to square {p.x}, {p.y}, {p.z * 5} feet high'
                      for i, p in enumerate(points)}
            picked = choose(engine, owner, 'armament', [str(i) for i in range(len(points))],
                            f'Cauldron Shell: move {owner.display_name}’s Domain Armament up to 20 feet. '
                            'Choose its destination square.', labels=labels, optional=False)
            if picked:
                qi_path.move_armament(engine, owner, points[int(picked[0])], ART, max_distance_ft=20)


@hook('save_mode')
def shell_save(engine, actor, ability, dc, source, context):
    row = condition(actor, 'condition:typed.black_cauldron_save')
    if row and row.data.get('source') == source:
        return 'ADVANTAGE'


@hook('event', nested=True)
def consume_shell_save(engine, event_type, kwargs):
    if event_type != 'SAVE_ROLLED':
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    held = condition(actor, 'condition:typed.black_cauldron_save') if actor else None
    if held and held.data.get('source') == kwargs.get('source_definition_id'):
        from .condition_ownership import remove_instance
        remove_instance(engine, actor, held.instance_id, ART)


def damage_types(effects):
    """Explicit compiled capability, never names, narration or guessed tags."""
    result = set()
    for row in effects or []:
        if not isinstance(row, dict):
            continue
        if row.get('type') in ('damage', 'extra_damage', 'half_damage'):
            result.update(str(k).upper() for k in row.get('damage_types') or [] if str(k).upper() in VALID)
        for key in ('on_hit', 'on_fail', 'on_success', 'effects', 'turn_start_effects'):
            result.update(damage_types(row.get(key)))
    return sorted(result)


WATCH = 'condition:typed.black_cauldron_watched_arts'


def effect_points(engine, instances, zones):
    """Where each watched effect actually is, never where its user stands.

    A condition rides its bearer: the bearer's id keeps the point live while the
    creature exists, and the stored cell is where it last was. A zone's point is
    its centre, read live while the zone still exists. Cells are integers only,
    so a record survives a table commit and a cold reload.
    """
    points = []
    for c in instances:
        actor = engine.state.actors.get(c.target_id)
        point = {'target': c.target_id}
        if actor is not None:
            point.update(x=actor.position.x, y=actor.position.y, z=actor.position.z)
        points.append(point)
    for zone in zones:
        points.append({'zone': zone.zone_id, 'x': zone.center.x, 'y': zone.center.y, 'z': zone.center.z})
    return points


def effect_distance(engine, owner, record):
    """Nearest watched effect point to ``owner`` in feet, or None when unknown."""
    from ..gate2_runtime_models import Position
    distances = []
    for point in record.get('points') or ():
        if point.get('target'):
            actor = engine.state.actors.get(point['target'])
            if actor is not None:
                distances.append(engine._distance_actor_to_actor(owner, actor))
                continue
        if 'x' not in point:
            continue
        # An area that has just ended is retained with its FINAL centre: the
        # zone record is not deleted and it re-centres as it moves. Reading the
        # activation-time cell instead measured a zone where it was created.
        zone = engine.state.zones.get(point.get('zone'))
        centre = (zone.center if zone is not None else
                  Position(x=int(point['x']), y=int(point['y']), z=int(point.get('z', 0))))
        distances.append(engine.grid.distance_ft(owner.position, centre))
    return min(distances) if distances else None


@hook('activation_settlement')
def collect_active_art(ctx, receipt):
    """Persist actual active effects and their actual meaningful deliveries.

    Damage capability comes from compiled damage leaves. Active instance IDs,
    ownership and meaningful outcomes come from the just-committed activation.
    A catalog row alone is never evidence that a technique became active.
    """
    if not receipt['qi_powered']:
        return
    kinds = sorted(set(receipt['damage_types']) & set(VALID)) or damage_types(ctx.typed.get('effects'))
    if not kinds:
        return
    engine, user = ctx.engine, ctx.actor
    instances = [c for a in engine.state.actors.values() for c in a.conditions.values()
                 if c.source_actor_id == user.entity_id and c.source_definition_id == ctx.source
                 and c.applied_sequence >= receipt['first_sequence']]
    zones = [z for z in engine.state.zones.values() if z.active and z.owner_id == user.entity_id
             and z.source_definition_id == ctx.source]
    if not instances and not zones and not (user.concentration and user.concentration.source_definition_id == ctx.source):
        return
    affected = sorted(set(receipt['damaged_ids']) | {c.target_id for c in instances})
    for owner in engine.state.actors.values():
        if not owned(engine, owner, DIGEST) or not legal_hostile(engine, owner, user):
            continue
        held = condition(owner, WATCH)
        records = deepcopy(held.data.get('arts', [])) if held else []
        records = [r for r in records if (r['source'], r['user']) != (ctx.source, user.entity_id)]
        records.append({'source': ctx.source, 'user': user.entity_id, 'types': kinds,
                        'source_cl': receipt['source_cl'], 'affected': affected,
                        'instance_ids': [c.instance_id for c in instances],
                        'zone_ids': [z.zone_id for z in zones],
                        'points': effect_points(engine, instances, zones) or
                                  [{'target': user.entity_id, 'x': user.position.x,
                                    'y': user.position.y, 'z': user.position.z}],
                        'activation': activation_id(engine)})
        write_condition(engine, owner, WATCH, DIGEST, {'arts': records,
                        'label': 'Digest the Broken Art: active hostile Qi effects'})


@hook('event', nested=True)
def digest_ending(engine, event_type, kwargs):
    if event_type not in ('CONDITION_REMOVED', 'ZONE_REMOVED', 'CONCENTRATION_ENDED', 'ENTITY_DEFEATED'):
        return
    payload = kwargs.get('payload') or {}
    ended = kwargs.get('ended_effect') or {}
    source = ended.get('source_definition_id') or kwargs.get('source_definition_id')
    for owner in list(engine.state.actors.values()):
        held = condition(owner, WATCH)
        if not held or not owned(engine, owner, DIGEST):
            continue
        records = deepcopy(held.data.get('arts', []))
        for record in list(records):
            match = (event_type == 'ENTITY_DEFEATED' and kwargs.get('actor_id') == record['user'] or
                     event_type == 'CONCENTRATION_ENDED' and source == record['source'] or
                     payload.get('instance_id') in record['instance_ids'] or payload.get('zone_id') in record['zone_ids'])
            if not match:
                continue
            user = engine.state.actors.get(record['user'])
            if user is None:
                continue
            # One removed rider does not end a still-active field/technique.
            active_ids = {c.instance_id for a in engine.state.actors.values() for c in a.conditions.values()}
            still_active = any(i in active_ids for i in record['instance_ids']) or any(
                (z := engine.state.zones.get(i)) is not None and z.active for i in record['zone_ids'])
            if still_active and event_type not in ('CONCENTRATION_ENDED', 'ENTITY_DEFEATED'):
                continue
            records.remove(record)
            reason = str(payload.get('reason') or kwargs.get('source_definition_id') or '').upper()
            expired = 'EXPIR' in reason or 'DURATION' in reason or 'TURN_' in reason
            qualifying = (expired or event_type == 'ENTITY_DEFEATED' or
                          any(k in reason for k in ('FAILED_DAMAGE_CHECK', 'DISPEL', 'SUPPRESS', 'ANCHOR_DESTROY', 'DYING', 'ENTITY_DEFEATED')))
            if not qualifying:
                continue
            meaningful = any((a := engine.state.actors.get(i)) is not None and a.team_id == owner.team_id
                             for i in record['affected'])
            if expired and not meaningful:
                continue
            flag = '_round_black_cauldron_digest'
            near = effect_distance(engine, owner, record)
            if (not legal_hostile(engine, owner, user) or near is None or near > 60
                    or record['source_cl'] < max(1, int(numbers(engine, owner)['cl']) - 5)
                    or owner.turn_flags.get(flag) == engine.state.round_number):
                continue
            chosen = choose(engine, owner, 'digest', record['types'],
                f'Digest the Broken Art: {user.display_name}’s hostile Qi technique ended within 60 feet of '
                f'{owner.display_name}. Choose 1 matching Essence; once per round, no Reaction.', target=user)
            if chosen:
                gain(engine, owner, chosen[0], 1, DIGEST)
                owner.turn_flags[flag] = engine.state.round_number
        engine._update_condition_data(owner, held, {**held.data, 'arts': records}, DIGEST)


def is_damage(effects):
    return bool(damage_types(effects)) or any(r.get('type') == 'attack' for r in effects or [] if isinstance(r, dict))


def weapon_delivered(typed):
    """Whether this activation is a weapon-delivered technique.

    Weapon Refinement needs an actual weapon (or Domain Armament) at the origin.
    A Strike's printed unarmed fallback carries a weapon-shaped ``typed.weapon``
    for its attack numbers but delivers with the body, so it is not a weapon
    delivery for this rider.
    """
    if typed.get('qi_weapon_delivery'):
        return True
    kinds = {str(row.get('attack_kind') or '') for row in typed.get('effects') or [] if isinstance(row, dict)}
    return bool(typed.get('weapon')) and 'unarmed' not in kinds


def required(engine, owner, key, options, prompt, *, target=None, labels=None, maximum=1):
    """A mandatory refinement choice that always resolves.

    These follow-ups are offered only after the player already committed the
    printed option, so no answer must never crash the activation. The engine's
    own no-answer default is the first offered option; use the same order.
    """
    options = list(options)
    picked = choose(engine, owner, key, options, prompt, target=target, labels=labels,
                    maximum=maximum, optional=False)
    return picked or options[:1]


@hook('effect_resolution_scope')
@contextmanager
def prepare_refinement(ctx, effect_row):
    """Bind once-per-activation choices before the first native damaging effect.

    Nested effects inherit damage_cache; the selection is charged even on a miss.
    Roll payloads and target riders are subsequently consumed by native hooks.
    """
    engine, actor = ctx.engine, ctx.actor
    key = 'black_cauldron_refinement'
    if (key not in ctx.damage_cache and owned(engine, actor, REFINE)
            and ctx.source not in TIERS and is_damage(ctx.typed.get('effects'))
            and profile(engine, actor, ctx.action)['qi_powered']):
        ctx.damage_cache[key] = {}
        # Printed CL14 Limit: "Once per turn" (Qi Subpath Compendium R19). This
        # feature may be used on only one activation per turn. "Once per
        # activation" belongs to the Weapon Refinement rider below (first
        # confirmed weapon hit), not to this use limit; do not key this gate on
        # activation_id.
        flag = '_round_black_cauldron_refine'
        entries = available(engine, actor)
        if entries and actor.turn_flags.get(flag) != turn_id(engine):
            options = {str(i): e for i, e in enumerate(entries)}
            chosen = choose(engine, actor, 'refine', list(options),
                f'Refine the Stolen Principle: {actor.display_name} activates {ctx.action.display_name}. '
                'Spend up to 3 Essence to add 1d8 matching damage each to one damage roll of this activation. '
                'Limit: once per turn.',
                labels={i: e['type'].title() + ' Essence' for i, e in options.items()}, maximum=min(3, len(options)))
            if chosen:
                spent = [options[i] for i in chosen]
                refinements = []
                weapon_rider = None
                if len(spent) >= 2:
                    menu = ['pierce', 'choke', 'heavy', 'shell', 'translate']
                    labels = {'pierce': 'Ignore one ordinary Resistance among the spent types',
                              'choke': 'One damaged creature loses Reactions until its next turn starts',
                              'heavy': 'One damaged creature loses 15 feet of Speed until your next turn starts',
                              'shell': 'Gain Temporary Hit Points equal to twice proficiency bonus',
                              'translate': 'Change one technique-damage packet to one spent type'}
                    if weapon_delivered(ctx.typed):
                        menu.append('weapon')
                        labels['weapon'] = 'Weapon Refinement: add a valid spent principle as a weapon-delivery rider after a hit'
                    refinements = required(engine, actor, 'refinements', menu,
                        f'Refine the Stolen Principle: {actor.display_name} spends {len(spent)} Essence on '
                        f'{ctx.action.display_name}. Choose a refinement; no additional cost.', labels=labels,
                        maximum=2 if len(spent) == 3 and len({e['type'] for e in spent}) == 3 else 1)
                    if 'weapon' in refinements:
                        # Weapon Refinement (lead ruling 2026-10-21): one spent Essence
                        # becomes an extra 1d8 of its type (2d8 on a critical hit) on
                        # the first confirmed weapon hit of this activation.
                        weapon_rider = required(engine, actor, 'weapon_rider', sorted({e['type'] for e in spent}),
                            f'Weapon Refinement: choose one spent Essence type. {actor.display_name} adds 1d8 of that type '
                            f'(2d8 on a critical hit) after the first weapon hit of {ctx.action.display_name}.')[0]
                spend(engine, actor, spent, REFINE)
                actor.turn_flags[flag] = turn_id(engine)
                record = {'spent': spent, 'refinements': refinements, 'rolls': [], 'delivered': [], 'riders': []}
                if weapon_delivered(ctx.typed):
                    component = required(engine, actor, 'refine_delivery', ['weapon', 'technique'],
                        f'Refine the Stolen Principle: add {actor.display_name}’s matching damage to '
                        f'{ctx.action.display_name}’s weapon damage or technique damage?',
                        labels={'weapon': 'Weapon damage', 'technique': 'Technique damage'})
                    record['component'] = component[0]
                if 'pierce' in refinements:
                    picked = required(engine, actor, 'pierce', sorted({e['type'] for e in spent}),
                        f'Piercing Principle: choose the ordinary Resistance {actor.display_name} ignores for '
                        f'{ctx.action.display_name}’s refined damage.')
                    record['pierce'] = picked[0]
                if 'shell' in refinements:
                    engine._grant_temp_hp(actor, 2 * int(numbers(engine, actor)['pb']), REFINE, actor.entity_id)
                if weapon_rider is not None:
                    record['weapon_rider'] = weapon_rider
                    actor.turn_flags[RIDER_FLAG] = {'source': ctx.action.source_definition_id,
                        'activation': activation_id(engine), 'type': weapon_rider,
                        'pierce': record.get('pierce', ''), 'done': False}
                ctx.damage_cache[key] = record
    yield


@hook('damage_type_override')
def translate(ctx, kinds, targets):
    record = ctx.damage_cache.get('black_cauldron_refinement') or {}
    if ('translate' not in record.get('refinements', []) or record.get('translated')
            or ctx.damage_packet_kind == 'weapon'):
        return None
    picked = required(ctx.engine, ctx.actor, 'translation', sorted({e['type'] for e in record['spent']}),
        f'Principle Translation: change one {ctx.action.display_name} technique packet to a spent damage principle.')
    record['translated'] = 1
    return picked[0]


@hook('damage_roll_resolved')
def refine_roll(ctx, effect_row, roll_key):
    if ctx.effect_source in (RESIDUE, REFINE):
        return
    ctx.damage_cache['black_cauldron_active_roll'] = str(roll_key)
    record = ctx.damage_cache.get('black_cauldron_refinement') or {}
    if not record or record.get('roll_key') is not None:
        return
    record['roll_key'] = str(roll_key)
    record['rolls'] = [{'type': e['type'], 'amount': roll(ctx.engine, ctx.actor, 2 if ctx.critical_hit else 1, 8, REFINE)} for e in record['spent']]


SUPERIOR_AUTHORITY = {'absolute', 'artifact', 'secret', 'immortal', 'conceptual'}
FORM_ORDER = ('absolute', 'temporary', 'item', 'cultivation', 'natural')
FORM_WORDS = {'natural': 'natural toughness', 'item': 'an item',
              'cultivation': 'a cultivation art', 'temporary': 'temporary and will lapse',
              'absolute': 'absolute or artifact-grade'}


def resistance_form(source_id, expiry, authority):
    """One of the printed categories for a single defence, never its full source."""
    if str((authority or {}).get('authority') or '') in SUPERIOR_AUTHORITY:
        return 'absolute'
    if expiry and str(expiry) != 'UNTIL_REMOVED':
        return 'temporary'
    origin = str((authority or {}).get('origin') or '')
    identifier = str(source_id or '')
    if origin in ('item', 'item_based', 'equipment') or identifier.startswith(
            ('tianxia.mortal.', 'tianxia.item.', 'item:')):
        return 'item'
    if origin == 'cultivated' or identifier.startswith(
            ('tianxia.path.', 'tianxia.subpath.', 'tianxia.tradition.', 'tianxia.talent.',
             'tianxia.sphere.', 'tianxia.forged_technique.', 'tianxia.immortal_art.')):
        return 'cultivation'
    return 'natural'


def resistance_forms(engine, target, kind):
    """Every printed category the target's effective Resistance to ``kind`` comes from."""
    forms = set()
    for held in target.conditions.values():
        data = held.data or {}
        rows = [row for row in data.get('defenses') or [] if row.get('kind') in ('resistance', 'immunity')
                and (not row.get('damage_types')
                     or kind in {str(value).upper() for value in row['damage_types']})]
        if rows:
            forms.add(resistance_form(held.source_definition_id, held.expires_on,
                                      data.get('protection_authority')))
    for modifier in target.modifiers.values():
        if (modifier.target_field in ('damage_resistance', 'damage_resistance_next', 'damage_immunity')
                and str(modifier.value).upper() == kind):
            forms.add(resistance_form(modifier.source_definition_id, modifier.expires_on, {}))
    for row in (getattr(engine, 'typed_passive_rows', {}) or {}).get(target.entity_id, ()):
        if (row.get('kind') in ('resistance', 'immunity')
                and kind in {str(value).upper() for value in row.get('damage_types') or []}):
            forms.add(resistance_form(row.get('feature_id'), None, row.get('protection_authority')))
    if kind in {str(value).upper() for value in getattr(target, 'damage_resistances', ())}:
        forms.add('natural')
    return forms


def resists_added(engine, owner, target, kind):
    """Whether this target's own Resistance reduces the damage Refine added (piercing honoured)."""
    from ..typed_reactions import resistance_profile
    return resistance_profile(engine, target, kind, {'effects': []},
                              source_id=REFINE, source_actor_id=owner.entity_id)['resist']


def disclose_resistance(engine, owner, target, kind):
    """Devour the Resistance: the category of the Resistance, never the full source."""
    seen = engine.__dict__.setdefault('_black_cauldron_disclosed', set())
    # Refine is once a turn, so one disclosure per creature and principle per
    # round covers its weapon rider and every refined packet without repeating.
    key = (target.entity_id, kind, engine.state.round_number)
    if key in seen:
        return
    seen.add(key)
    forms = resistance_forms(engine, target, kind) or {'natural'}
    form = next(name for name in FORM_ORDER if name in forms)
    engine._append_event('PASSIVE_TRIGGERED', REFINE, actor_id=owner.entity_id,
        target_ids=(target.entity_id,),
        payload={'feature_id': REFINE, 'devoured_resistance': {'damage_type': kind, 'form': form},
                 'log': f'Devour the Resistance: {target.display_name} resisted the extra {kind.title()} damage '
                        f'{owner.display_name} added with Refine the Stolen Principle. Its Resistance is '
                        f'{FORM_WORDS[form]}; the full source is not revealed.'})


@hook('damage_dealt', priority=-10)
def refine_delivery(ctx, target, amount):
    from ..typed_executor import run_effects
    from dataclasses import replace
    record = ctx.damage_cache.get('black_cauldron_refinement') or {}
    if not record or ctx.effect_source == REFINE or target.entity_id in record.get('delivered', []):
        return
    if record.get('component') and record['component'] != ctx.damage_packet_kind:
        return
    slot = roll_slot(ctx)
    if record.get('selected_slot') is None:
        record['selected_slot'] = slot
    elif record['selected_slot'] != slot:
        return
    if not record.get('rolls'):
        # Native attack primary damage folds independently of typed damage rows.
        record['rolls'] = [{'type': e['type'], 'amount': roll(ctx.engine, ctx.actor, 2 if ctx.critical_hit else 1, 8, REFINE)} for e in record['spent']]
    record['delivered'].append(target.entity_id)
    inner = replace(ctx, effect_source=REFINE, targets=[target], target=target,
                    damage_divisor=2 if ctx.failed_save is False else ctx.damage_divisor)
    previous = getattr(ctx.engine, '_black_cauldron_ignore_resistance', None)
    try:
        for packet in record['rolls']:
            ctx.engine._black_cauldron_ignore_resistance = (ctx.actor.entity_id, target.entity_id,
                                                            record.get('pierce', ''))
            if resists_added(ctx.engine, ctx.actor, target, packet['type']):
                disclose_resistance(ctx.engine, ctx.actor, target, packet['type'])
            run_effects(inner, [{'type': 'extra_damage', 'applies_to': 'target', 'flat': packet['amount'],
                                'damage_types': [packet['type'].lower()]}])
    finally:
        ctx.engine._black_cauldron_ignore_resistance = previous
    for name in ('choke', 'heavy'):
        if name not in record.get('riders', []):
            if name not in record['refinements']:
                continue
            choice = choose(ctx.engine, ctx.actor, 'refined_' + name, ['use'],
                f'{"Choked Reaction" if name == "choke" else "Heavy Digestion"}: {ctx.action.display_name} '
                f'damaged {target.display_name}. Apply the refinement to this creature?', target=target)
            if choice:
                ctx.engine._apply_condition(target, 'condition:typed.black_cauldron_' + name, REFINE,
                    ctx.actor.entity_id, expires_on=holder_next_turn(target) if name == 'choke' else holder_next_turn(ctx.actor),
                    data={'rule': {'no_reactions': 1} if name == 'choke' else {},
                          'speed_delta': -15 if name == 'heavy' else 0,
                          'label': 'Choked Reaction: no Reactions until your next turn starts' if name == 'choke'
                          else 'Heavy Digestion: Speed reduced by 15 feet until the cauldron owner’s next turn starts'})
                record['riders'].append(name)


RIDER_FLAG = '_black_cauldron_weapon_rider'


@hook('after_hit')
def weapon_rider_hit(ctx, target, kind):
    """Weapon Refinement: once per activation, on its first confirmed weapon hit,
    deal 1d8 (2d8 on a critical) of the chosen spent type. Lands even if the weapon
    damage is prevented; a miss never reaches this hook with hit=True."""
    from dataclasses import replace
    from ..typed_executor import run_effects
    pending = ctx.actor.turn_flags.get(RIDER_FLAG)
    if (not pending or pending.get('done') or kind != 'weapon'
            or pending.get('source') != ctx.action.source_definition_id
            or pending.get('activation') != activation_id(ctx.engine)):
        return
    pending['done'] = True
    amount = roll(ctx.engine, ctx.actor, 2 if ctx.critical_hit else 1, 8, REFINE)
    inner = replace(ctx.with_source(REFINE), targets=[target], target=target, damage_cache={})
    previous = getattr(ctx.engine, '_black_cauldron_ignore_resistance', None)
    try:
        ctx.engine._black_cauldron_ignore_resistance = (ctx.actor.entity_id, target.entity_id, pending.get('pierce', ''))
        if resists_added(ctx.engine, ctx.actor, target, pending['type']):
            disclose_resistance(ctx.engine, ctx.actor, target, pending['type'])
        run_effects(inner, [{'type': 'extra_damage', 'applies_to': 'target', 'flat': amount,
                             'damage_types': [pending['type'].lower()]}])
    finally:
        ctx.engine._black_cauldron_ignore_resistance = previous


@hook('resistance_ignored')
def pierce_resistance(engine, kind, typed, by, target):
    scope = getattr(engine, '_black_cauldron_ignore_resistance', None)
    if scope != (by, getattr(target, 'entity_id', None), kind):
        return None
    # Explicit superior Resistance is never classified as ordinary.
    for held in target.conditions.values():
        auth = held.data.get('protection_authority') or {}
        if auth.get('authority') in ('absolute', 'artifact', 'secret', 'immortal', 'conceptual'):
            if any(r.get('kind') == 'resistance' and (not r.get('damage_types') or kind in r['damage_types'])
                   for r in held.data.get('defenses', [])):
                return None
    return True


@hook('technique_declared')
def lesser_art(engine, user, action, candidate, intent):
    incoming = profile(engine, user, action)
    typed = action.parameters.get('typed') or {}
    if not incoming['qi_powered'] or any(typed.get(k) for k in ('secret', 'immortal', 'artifact', 'permanent', 'strategic')):
        return None
    if incoming['source_kind'] == 'Immortal':
        return None
    total = sum(n for pool, n in action.costs if pool == QI)
    for owner in engine.state.actors.values():
        if (not owned(engine, owner, FIELD) or not legal_hostile(engine, owner, user)
                or engine.state.current_actor_id != owner.entity_id or not in_field(engine, owner, user)
                or not ready_reaction(engine, owner, user, FIELD)):
            continue
        ns = numbers(engine, owner)
        entries = available(engine, owner)
        flag = '_round_black_cauldron_lesser'
        if (incoming['source_cl'] > int(ns['cl']) - 6 or total > int(ns['pb']) or len(entries) < 2
                or owner.turn_flags.get(flag) == turn_id(engine)):
            continue
        options = {f'{a}:{b}': (entries[a], entries[b]) for a, b in combinations(range(len(entries)), 2)}
        picks = choose(engine, owner, 'lesser', list(options),
            f'Devour the Lesser Art: {user.display_name} activates {action.display_name} inside '
            f'{owner.display_name}’s field. Spend 2 Essence and your Reaction to force a Constitution save; '
            'failure cancels the activation but keeps its cost spent, success reduces its damage in the field by your proficiency bonus.',
            labels={k: f'Spend {a["type"].title()} and {b["type"].title()} Essence' for k, (a, b) in options.items()}, target=user)
        if not picks:
            continue
        spent = list(options[picks[0]])
        spend(engine, owner, spent, FIELD)
        pay_reaction(engine, owner, user, FIELD)
        owner.turn_flags[flag] = turn_id(engine)
        result = engine._roll_save(user, 'CON', int(ns['save_dc']), FIELD,
            roll_context={'source_actor_id': owner.entity_id})
        failed = result is None or result.total < int(ns['save_dc'])
        if failed:
            types = damage_types(typed.get('effects'))
            # An energyless effect supplies no invented damage principle.
            if types:
                chosen = choose(engine, owner, 'lesser_gain', types,
                    f'Devour the Lesser Art: {user.display_name}’s {action.display_name} fails; '
                    f'{owner.display_name} gains 1 Essence of its damage principle.', target=user, optional=False)
                gain(engine, owner, chosen[0], 1, FIELD)
            return {'source_id': FIELD, 'label': 'Devour the Lesser Art', 'cancel': True, 'spend_activation': True}
        timed_condition(engine, owner, 'condition:typed.black_cauldron_lesser', FIELD, owner.entity_id,
            holder_next_turn(owner), {'user': user.entity_id, 'source': action.source_definition_id,
                'activation': activation_id(engine), 'pb': int(ns['pb']),
                'label': 'Devour the Lesser Art: this activation’s damage in the field is reduced by proficiency bonus'})
    return None


@hook('source_damage_reduction')
def lesser_reduction(engine, target, amount, kind, source, by):
    total = 0
    for owner in engine.state.actors.values():
        held = condition(owner, 'condition:typed.black_cauldron_lesser')
        if (held and held.data['user'] == by and held.data['source'] == source
                and held.data['activation'] == activation_id(engine) and in_field(engine, owner, target)):
            total += int(held.data['pb'])
    return total or None


def available(engine, actor):
    return [e for e in store(actor) if e['activation'] != activation_id(engine)]


def roll_slot(ctx):
    if ctx.damage_attack_index is not None:
        return 'attack:' + str(ctx.damage_attack_index) + ':' + ctx.damage_packet_kind
    return 'roll:' + str(ctx.damage_cache.get('black_cauldron_active_roll', ''))


@hook('damage_packet_selection')
def spit_delivery(ctx, target, kinds):
    if (not owned(ctx.engine, ctx.actor) or not available(ctx.engine, ctx.actor)
            or not profile(ctx.engine, ctx.actor, ctx.action)['qi_powered']
            or 'black_cauldron_spit_component' in ctx.damage_cache or len(kinds) < 2):
        return
    selected = choose(ctx.engine, ctx.actor, 'spit_delivery', list(kinds),
        f'Spit the Principle: {ctx.action.display_name} hit {target.display_name}. '
        'If you spend Essence on this activation, add it to the weapon damage or technique damage?',
        labels={'weapon': 'Weapon damage', 'technique': 'Technique damage'}, optional=False, target=target)
    if selected:
        ctx.damage_cache['black_cauldron_spit_component'] = selected[0]


@hook('damage_dealt')
def spit(ctx, target, amount):
    from dataclasses import replace
    from ..typed_executor import run_effects
    engine, actor = ctx.engine, ctx.actor
    if (amount <= 0 or not owned(engine, actor) or ctx.source in TIERS
            or not profile(engine, actor, ctx.action)['qi_powered']):
        return
    flag = '_round_black_cauldron_spit'
    record = ctx.damage_cache.get('black_cauldron_spit')
    if record:
        if record['slot'] == roll_slot(ctx) and target.entity_id not in record['delivered']:
            record['delivered'].append(target.entity_id)
            run_effects(replace(ctx, effect_source=RESIDUE, targets=[target], target=target,
                                damage_divisor=2 if ctx.failed_save is False else ctx.damage_divisor),
                        [{'type': 'extra_damage', 'applies_to': 'target', 'flat': record['amount'],
                          'damage_types': [record['type'].lower()]}])
        return
    from .damage_delivery import area
    zone = engine.state.zones.get(area(engine))
    source_zone = (zone if zone is not None and zone.owner_id == actor.entity_id
                   and zone.source_definition_id == ctx.action.source_definition_id else None)
    if source_zone is not None and actor.entity_id in source_zone.trigger_profile.get('cauldron_spit_used', []):
        return
    component = ctx.damage_cache.get('black_cauldron_spit_component')
    if component and component != ctx.damage_packet_kind:
        return
    if actor.turn_flags.get(flag) == turn_id(engine):
        return
    entries = available(engine, actor)
    types = sorted({e['type'] for e in entries})
    if not types:
        return
    picked = choose(engine, actor, 'spit', types,
        f'Spit the Principle: {ctx.action.display_name} damaged {target.display_name}. '
        'Spend 1 Essence to add matching damage once to this activation?', target=target)
    if not picked:
        return
    entry = next(e for e in entries if e['type'] == picked[0])
    spend(engine, actor, [entry], RESIDUE)
    actor.turn_flags[flag] = turn_id(engine)
    level = int(numbers(engine, actor)['cl'])
    count = 3 if level >= 17 else 2 if level >= 11 else 1
    bonus = roll(engine, actor, count * (2 if ctx.critical_hit else 1), 8, RESIDUE)
    ctx.damage_cache['black_cauldron_spit'] = {'slot': roll_slot(ctx), 'type': entry['type'],
                                             'amount': bonus, 'delivered': [target.entity_id]}
    if source_zone is not None:
        source_zone.trigger_profile.setdefault('cauldron_spit_used', []).append(actor.entity_id)
        engine._append_event('PASSIVE_TRIGGERED', RESIDUE, actor_id=actor.entity_id,
            payload={'zone_after': source_zone.model_dump(mode='json'),
                     'log': 'Spit the Principle refines one damage roll of this field activation; later pulses cannot spend it again.'})
    run_effects(replace(ctx, effect_source=RESIDUE, targets=[target], target=target,
                        damage_divisor=2 if ctx.failed_save is False else ctx.damage_divisor),
                [{'type': 'extra_damage', 'applies_to': 'target', 'flat': bonus,
                  'damage_types': [entry['type'].lower()]}])


@effect('black_cauldron_field', harmful=True)
def create_field(ctx, row):
    from .. import zones, asset_anchor_runtime
    engine, actor = ctx.engine, ctx.actor
    if not owned(engine, actor, FIELD) or scene(actor).get('field_used'):
        raise ValueError('Heaven-Devouring Cauldron is available once per scene at Qi CL18.')
    ns = numbers(engine, actor)
    center = ctx.destination or getattr(ctx.intent, 'destination', None)
    if center is None:
        raise ValueError('Choose the center of the Cauldron field within 90 feet.')
    choice = choose(engine, actor, 'field_type', ['NECROTIC', 'FORCE'],
        f'Heaven-Devouring Cauldron: {actor.display_name} spends 8 Qi and Concentration for up to 1 minute. '
        'Choose its field damage principle.', optional=False)
    kind = choice[0]
    anchor = asset_anchor_runtime.create(engine, actor, ctx.source,
        {'name': 'Cauldron Anchor', 'kind': 'cultivation_asset', 'ac': int(ns['save_dc']),
         'hp': 5 * int(ns['cl']), 'source_cl': int(ns['cl']), 'height_ft': 10, 'group': PARENT,
         'saving_throw_bonus': int(ns['key_mod']) + int(ns['pb'])}, center,
        component={'width_cells': 2, 'length_cells': 2, 'daemonic': 1,
                   'black_cauldron': 1, 'key_mod': int(ns['key_mod']), 'pb': int(ns['pb'])})
    zone = zones.create(ctx, {'name': 'Heaven-Devouring Cauldron', 'shape': 'cylinder', 'size_ft': 30,
        'height_ft': 40, 'placed': 1, 'difficult': 'hostile',
        'duration': {'kind': 'minutes', 'amount': 1, 'concentration': True},
        'profile': {'black_cauldron': 1, 'anchor': anchor.object_id, 'consumed_cp': 0},
        'triggers': [{'id': 'cauldron_entry_start', 'name': 'Heaven-Devouring Cauldron', 'on': ['enter', 'start'],
                      'who': 'hostile', 'effects': [{'type': 'black_cauldron_pulse', 'kind': kind}]}]})
    data = scene(actor); data['field_used'] = 1
    save_scene(engine, actor, data)


@effect('black_cauldron_pulse', harmful=True)
def field_pulse(ctx, row):
    from ..typed_executor import run_effects
    kind = row['kind'].lower()
    run_effects(ctx, [{'type': 'save', 'ability': 'con',
        'on_fail': [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 5, 'sides': 8}, 'damage_types': [kind]},
                    {'type': 'black_cauldron_drain', 'kind': kind}],
        'on_success': [{'type': 'half_damage', 'applies_to': 'target', 'damage_types': [kind]}]}])


@effect('black_cauldron_drain', harmful=True)
def field_drain(ctx, row):
    from ..typed_executor import CP_POOLS, run_effects
    target = ctx.target
    pools = [p for p in CP_POOLS if target.resources.get(p, 0) > 0]
    if pools:
        picked = choose(ctx.engine, target, 'drain_pool', pools,
            f'Heaven-Devouring Cauldron: {target.display_name} loses 1 Cultivation Point; choose its Path pool.', optional=False)
        ctx.engine._spend_resource(target, picked[0], 1, FIELD)
        for zone in fields(ctx.engine, ctx.actor):
            if in_field(ctx.engine, ctx.actor, target):
                field_consumed(ctx.engine, zone, 1)
    if not any(target.resources.get(p, 0) > 0 for p in CP_POOLS):
        run_effects(ctx, [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 2, 'sides': 8}, 'damage_types': [row['kind']]}])
    ctx.engine._apply_condition(target, 'condition:typed.black_cauldron_recovery', FIELD, ctx.actor.entity_id,
        expires_on=holder_next_turn(target), data={'no_cp_regain': 1,
        'label': 'Heaven-Devouring Cauldron: cannot regain Cultivation Points until your next turn starts'})


@hook('resource_gain_allowed')
def no_recovery(engine, actor, resource, amount, source):
    from ..typed_executor import CP_POOLS
    if resource in CP_POOLS and amount > 0 and condition(actor, 'condition:typed.black_cauldron_recovery'):
        return False


@hook('object_damage_defenses')
def anchor_resists(engine, actor, obj, packets, source):
    if (obj.component or {}).get('black_cauldron') != 1:
        return None
    action = source_action(engine, source)
    if action and profile(engine, actor, action).get('qi_powered'):
        return None
    return [{'kind': 'resistance', 'damage_types': ['BLUDGEONING', 'PIERCING', 'SLASHING']}]


@hook('event', nested=True)
def anchor_destroyed(engine, event_type, kwargs):
    if event_type != 'OBJECT_UPDATED':
        return
    snapshot = (kwargs.get('payload') or {}).get('object') or {}
    if snapshot.get('component', {}).get('black_cauldron') != 1 or not snapshot.get('destroyed'):
        return
    owner = engine.state.actors.get(snapshot.get('owner_id'))
    if owner is None:
        return
    for zone in fields(engine, owner):
        if zone.trigger_profile['profile']['anchor'] == snapshot['object_id']:
            from .. import zones
            zones.remove(engine, zone, 'ANCHOR_DESTROYED')
            save_store(engine, owner, [])
            raw_damage(engine, owner, 4, 10, 'FORCE', FIELD)
            corrupt(engine, owner)


@hook('activation_settlement')
def feed(ctx, receipt):
    from ..typed_executor import CP_POOLS
    from ..zones import actor_inside_zone
    engine, user = ctx.engine, ctx.actor
    from ..paid_relocation import current_activation
    active = current_activation(engine)
    if active is None or active.actor_id != user.entity_id or active.source_id != ctx.source:
        return
    paid = sum(amount for pool, amount in active.net_payments if pool in CP_POOLS)
    if paid <= 0:
        return
    for owner in engine.state.actors.values():
        if (not owned(engine, owner, FIELD) or not legal_hostile(engine, owner, user)
                or receipt['source_cl'] < max(1, int(numbers(engine, owner)['cl']) - 5)):
            continue
        for zone in fields(engine, owner):
            if not actor_inside_zone(engine, user, zone):
                continue
            field_consumed(engine, zone, paid)
            flag = '_round_black_cauldron_feed'
            if owner.turn_flags.get(flag) == engine.state.round_number:
                continue
            types = [t for t in receipt['damage_types'] if t in VALID] or ['FORCE']
            chosen = choose(engine, owner, 'feed', types,
                f'Feed on Expenditure: {user.display_name} spent Cultivation Points on {ctx.action.display_name} '
                f'inside {owner.display_name}’s field. Gain 1 matching Essence?', target=user)
            if chosen:
                gain(engine, owner, chosen[0], 1, FIELD)
                owner.turn_flags[flag] = engine.state.round_number


def field_consumed(engine, zone, amount):
    zone.trigger_profile['profile']['consumed_cp'] += amount
    engine._append_event('PASSIVE_TRIGGERED', zone.source_definition_id, actor_id=zone.owner_id,
        payload={'zone_after': zone.model_dump(mode='json'), 'log': f'Heaven-Devouring Cauldron consumed {amount} Cultivation Point(s).'})


@effect('black_cauldron_move')
def move_anchor(ctx, row):
    from .. import asset_anchor_runtime as assets, zones
    from ..gate2_runtime_models import Position
    engine, owner = ctx.engine, ctx.actor
    if (not owned(engine, owner, FIELD) or owner.turn_flags.get('_round_black_cauldron_move') == turn_id(engine)):
        return
    for zone in fields(engine, owner):
        obj = engine.state.objects.get(zone.trigger_profile['profile']['anchor'])
        if not obj or obj.destroyed:
            continue
        options = {}
        for x in range(max(0, obj.position.x - 4), min(engine.grid.width, obj.position.x + 5)):
            for y in range(max(0, obj.position.y - 4), min(engine.grid.height, obj.position.y + 5)):
                for z in range(max(0, obj.position.z - 4), obj.position.z + 5):
                    point = Position(x=x, y=y, z=z)
                    if engine.grid.distance_ft(obj.position, point) > 20:
                        continue
                    cells = [Position(x=x + dx, y=y + dy, z=z) for dx in range(2) for dy in range(2)]
                    if (assets.legal_placement(engine, cells, 10, ignore=(obj.object_id,), require_support=False)
                            and engine.grid.line_of_physical_transmission(obj.position, point)):
                        options[f'{x},{y},{z}'] = point
        selected = choose(engine, owner, 'move_anchor', list(options),
            f'Heaven-Devouring Cauldron: move {owner.display_name}’s Cauldron Anchor up to 20 feet; '
            'no action, once during your turn.', labels={k: f'Square {p.x},{p.y}, {p.z * 5} feet high' for k, p in options.items()})
        if not selected:
            return
        point = options[selected[0]]
        engine._update_object(obj.model_copy(update={'position': point}), ctx.source, owner.entity_id)
        zone.center = point
        zone.affected_cells = zones.area_cells(engine, zone)
        engine._append_event('ZONE_CREATED', zone.source_definition_id, actor_id=owner.entity_id,
                            payload={'zone': zone.model_dump(mode='json')})
        owner.turn_flags['_round_black_cauldron_move'] = turn_id(engine)
        zones.sync_inside(engine, ctx.source)
        # Shared Qi R4: moving a field over a creature is not that creature
        # entering. Its next actual turn start still uses the native trigger.


@hook('event', nested=True)
def field_ended(engine, event_type, kwargs):
    if event_type != 'ZONE_REMOVED':
        return
    zone = engine.state.zones.get((kwargs.get('payload') or {}).get('zone_id'))
    if zone is None or (zone.trigger_profile.get('profile') or {}).get('black_cauldron') != 1:
        return
    owner = engine.state.actors.get(zone.owner_id)
    if owner is None:
        return
    from ..asset_anchor_runtime import retire
    anchor = engine.state.objects.get(zone.trigger_profile['profile']['anchor'])
    if anchor and not anchor.destroyed:
        retire(engine, anchor, zone.source_definition_id)
    reason = (kwargs.get('payload') or {}).get('reason')
    if reason == 'ANCHOR_DESTROYED':
        return
    entries = available(engine, owner)
    if entries:
        options = {str(i): e for i, e in enumerate(entries)}
        selected = choose(engine, owner, 'end_field', list(options),
            f'Heaven-Devouring Cauldron ends for {owner.display_name}. Spend any remaining Essence '
            'to cancel its own 1d6 Force scene-end backlash; unspent Essence keeps its normal scene-end damage.',
            labels={i: e['type'].title() + ' Essence: cancel its backlash' for i, e in options.items()}, maximum=len(options))
        if selected:
            spend(engine, owner, [options[i] for i in selected], FIELD)
    if zone.trigger_profile['profile']['consumed_cp'] >= 6:
        corrupt(engine, owner)


@hook('effect_origins')
def technique_origin(engine, actor, action):
    if not owned(engine, actor, FIELD) or not profile(engine, actor, action)['qi_powered']:
        return None
    if (action.parameters.get('typed') or {}).get('weapon'):
        return None  # A weapon/Armament must actually be at the origin.
    result = []
    for zone in fields(engine, actor):
        anchor = engine.state.objects.get(zone.trigger_profile['profile']['anchor'])
        if anchor and not anchor.destroyed and boundary_open(engine, actor, anchor.position):
            result.append({'id': 'black_cauldron:' + anchor.object_id, 'label': 'Cauldron Anchor',
                           'position': anchor.position.model_dump(mode='json')})
    return result or None
