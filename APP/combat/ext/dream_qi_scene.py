"""Dream Qi's native acquisition, private dream inputs and elapsed-time rituals.

Uses the source acquisition and fact/consent owner's public contracts. Public
helpers ``owned``, ``profile``, ``state``, ``sync`` are shared with dream_qi.
Subjective inner experience is declared by its controller; anatomy/consciousness
and protecting authority are world-owner facts. Neither grants an earned row.
"""
from copy import deepcopy
import json

from . import hook
from ..journey import require
from ..fact_consent_admission import read

PARENT = 'tianxia.subpath.qi.dream_qi_cultivator'
PREFIX = PARENT + '.feature.'
FEATURES = tuple(PREFIX + f for f in ('dreamer_s_rest', 'lucid_strike', 'dream_refinement', 'shared_dream_concordance', 'dream_ascension'))
LEVELS = (3, 6, 10, 14, 18)
QI = 'resource:core.qi'
STATE = 'dream_qi_native'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def owned(bundle, feature):
    return any(r.get('feature_id') == feature and r.get('block') == STATE for r in bundle.get('typed_passives', []))


def earned(level):
    """The printed progression rows this family grants at one acquired level."""
    return [feature for feature, threshold in zip(FEATURES, LEVELS) if level >= threshold]


def state(actor):
    return actor.setdefault('source_states', {}).setdefault(PARENT, {})


def profile(actor):
    bundle = actor['bundle']
    row = next((r for r in bundle.get('typed_passives', []) if r.get('block') == STATE), {})
    return row.get('numbers') or {}


def qi_source(owner_id, target_id, nature):
    """Source eligibility shared by waking refinement and surface harvesting.

    A named Source Rule may supply an equivalent independent inner state to a
    mind otherwise incapable of genuine dreams. It does not make a self, own
    created consciousness or recursive copy an independent donor.
    """
    return (owner_id != target_id and nature.get('genuine_consciousness') == 1 and
            nature.get('created_by') != owner_id and not nature.get('recursive') and
            (bool(nature.get('equivalent_source')) or nature.get('mindless') == 0 and nature.get('genuine_dreams') == 1))


def sync(session):
    from ..canonical import canonical_sha256
    for actor in session.state['actors'].values():
        saved = actor.get('source_states', {}).get(PARENT)
        if saved is None:
            continue
        actor['bundle'][STATE] = deepcopy(saved)
        actor['bundle'].pop('bundle_sha256', None)
        actor['bundle']['bundle_sha256'] = canonical_sha256(actor['bundle'])


@hook('fact_admission_schema')
def dream_inputs(session, source, subject, kind):
    if source != PARENT or subject not in session.state['actors']:
        return None
    if kind in ('source_access', 'inner_state', 'rest_threat', 'dream_restoration', 'memory_authority', 'surface_check'):
        return {'value_type': 'document', 'authority': 'table_owner', 'maximum_seconds': 2592000,
                'description': 'Source-backed scripture access or genuine inner-state classification; never an earned feature or consent.'}
    if not any(owned(a['bundle'], FEATURES[0]) for a in session.state['actors'].values()):
        return None
    if kind in ('dream_content', 'harvest_consent'):
        return {'value_type': 'document', 'maximum_seconds': 28800,
                'description': 'Your private surface dream or your consent to this named ten-minute harvest, including whether you choose to fail its save.'}
    if kind == 'cultivation_environment':
        return {'value_type': 'flag', 'maximum_seconds': 28800,
                'description': 'Confirm calm surroundings and actual ambient Qi for a two-hour Full Cultivation Session.'}
    return None


@hook('journey_acquisition')
def acquire(session, actor_id, source, payload, sheet):
    if source != PARENT:
        return None
    require(set(payload) == {'access_scope'}, 'Choose the native Dream Qi scripture access record.')
    actor = session.state['actors'][actor_id]
    access = read(session, source, actor_id, 'source_access', payload['access_scope'], actor_id)
    require(access and set(access['value']) == {'scripture', 'source_rule'} and access['value']['scripture'] == PARENT
            and type(access['value']['source_rule']) is str and access['value']['source_rule'].strip(),
            'The world owner must grant actual access to the Restricted Dream Qi Scripture.')
    result = deepcopy(sheet)
    paths = result.setdefault('path_and_subpath', {})
    qi = next((r for r in paths.get('paths', []) if r.get('path_id') == 'tianxia.path.qi_cultivation'), {})
    level = min(int(result['identity']['cultivation_level']), int(qi.get('attainment', 0)), int(qi.get('effective_cl', qi.get('attainment', 0))))
    require(level >= 3 and not actor['incapacitated'], 'Dream Qi requires acquired Qi Path attainment of CL3 and ability to complete acquisition.')
    selections = [r.get('subpath_id') for r in paths.get('subpaths', []) if r.get('owning_path_id') == 'tianxia.path.qi_cultivation']
    if (qi.get('subpath_or_tradition_acquisition_provenance') or {}).get('recorded') is True:
        selections.append(qi.get('subpath_or_tradition_id'))
    selections += [s for s in paths.get('subpath_record_ids', []) if s.startswith('tianxia.subpath.qi.')]
    if paths.get('subpath_record_id'):
        if paths['subpath_record_id'].startswith('tianxia.subpath.qi.'):
            selections.append(paths['subpath_record_id'])
    ids = set(paths.get('path_feature_record_ids', [])) | set(paths.get('source_granted_subpath_feature_record_ids', []))
    require(not selections and not any(s.startswith('tianxia.subpath.qi.') for s in ids),
            'Dream Qi occupies the Qi Subpath choice; it cannot coexist with another or reset an acquired progression.')
    earned_ids = earned(level)
    new_subpath = {'subpath_id': PARENT, 'display_name': 'Dream Qi Cultivator', 'owning_path_id': 'tianxia.path.qi_cultivation',
                   'source_packet_ids': [access['receipt_id']]}
    paths['subpath_record_id'] = PARENT
    paths['subpath_record_ids'] = [PARENT]
    paths['subpath'] = new_subpath
    paths['subpaths'] = [row for row in paths.get('subpaths', []) if row.get('owning_path_id') != 'tianxia.path.qi_cultivation'] + [new_subpath]
    paths['bindings'] = [row for row in paths.get('bindings', []) if row.get('path_id') != 'tianxia.path.qi_cultivation'] + [
        {'path_id': 'tianxia.path.qi_cultivation', 'subpath_id': PARENT, 'source_packet_ids': [access['receipt_id']]}]
    for key in ('path_feature_record_ids', 'source_granted_subpath_feature_record_ids'):
        paths[key] = list(dict.fromkeys([*paths.get(key, []), *earned_ids]))
    saved = state(actor)
    saved['acquired'] = canonical({'subpath_id': PARENT, 'receipt': access['receipt_id']})
    session.emit('DREAM_QI_ACQUIRED', actor_id, source=PARENT, access_receipt=access['receipt_id'],
                 features=earned_ids)
    return {'sheet': result, 'acquisition_id': access['receipt_id']}


@hook('journey_source_sheet')
def acquired_overlay(sheet, session, actor_id):
    if not session.state['actors'][actor_id].get('source_states', {}).get(PARENT, {}).get('acquired'):
        return None
    result = deepcopy(sheet)
    paths = result.setdefault('path_and_subpath', {})
    selected = paths.get('subpath_record_id')
    qi_selected = [r.get('subpath_id') for r in paths.get('subpaths', []) if r.get('owning_path_id') == 'tianxia.path.qi_cultivation']
    for path in paths.get('paths', []):
        if path.get('path_id') == 'tianxia.path.qi_cultivation' and (path.get('subpath_or_tradition_acquisition_provenance') or {}).get('recorded') is True:
            qi_selected.append(path.get('subpath_or_tradition_id'))
    qi_selected += [s for s in paths.get('subpath_record_ids', []) if s.startswith('tianxia.subpath.qi.')]
    if selected and selected.startswith('tianxia.subpath.qi.'):
        qi_selected.append(selected)
    require(set(qi_selected) <= {PARENT}, 'Resolve the changed Qi Subpath before continuing Dream Qi.')
    new_subpath = {'subpath_id': PARENT, 'display_name': 'Dream Qi Cultivator', 'owning_path_id': 'tianxia.path.qi_cultivation'}
    paths['subpath_record_id'] = PARENT
    paths['subpath_record_ids'] = [PARENT]
    paths['subpath'] = new_subpath
    paths['subpaths'] = [r for r in paths.get('subpaths', []) if r.get('owning_path_id') != 'tianxia.path.qi_cultivation'] + [new_subpath]
    qi = next((r for r in paths.get('paths', []) if r.get('path_id') == 'tianxia.path.qi_cultivation'), {})
    level = min(int(result['identity']['cultivation_level']), int(qi.get('attainment', 0)),
                int(qi.get('effective_cl', qi.get('attainment', 0))))
    for key in ('path_feature_record_ids', 'source_granted_subpath_feature_record_ids'):
        paths[key] = list(dict.fromkeys([sid for sid in paths.get(key, []) if sid not in FEATURES] + earned(level)))
    return result


@hook('journey_acquired')
def publish_acquired(session, actor_id, source, acquisition_id):
    if source == PARENT:
        sync(session)


@hook('journey_initialized')
def initialize(session):
    sync(session)


@hook('journey_replay_enabled')
def native_replay(session, actor_id, source):
    if source == PARENT or any(owned(actor['bundle'], FEATURES[0]) or PARENT in actor.get('source_states', {})
                               for actor in session.state['actors'].values()):
        return True


@hook('journey_combat_bundle')
def project_inputs(bundle, session, actor_id):
    actor = session.state['actors'][actor_id]
    family_present = any(owned(a['bundle'], FEATURES[0]) for a in session.state['actors'].values())
    receiver = {}
    if family_present and actor.get('check_mods'):
        mods = actor['check_mods']
        receiver = {'pb': int(bundle['actor_template']['proficiency_bonus']), 'cl': int(bundle['cl']),
                    'ability_mods': deepcopy(mods), **({'key_mod': mods['KEY']} if 'KEY' in mods else {})}
    if not owned(bundle, FEATURES[0]) and PARENT not in actor.get('source_states', {}):
        return {**deepcopy(bundle), 'dream_qi_receiver': receiver} if receiver else None
    result = deepcopy(bundle)
    if receiver:
        result['dream_qi_receiver'] = receiver
    saved = deepcopy(actor.get('source_states', {}).get(PARENT, {}))
    known = {}
    for fact in session.state.get('fact_consent_admission', []):
        if fact['source'] == PARENT and fact['kind'] == 'inner_state':
            verified = read(session, PARENT, fact['subject'], 'inner_state', fact['scope'], actor_id)
            if verified:
                known[fact['subject']] = verified['value']
    saved['known_inner_states'] = known
    result[STATE] = saved
    return result


def maximum(actor, rid):
    return next((int(r['maximum']) for r in actor['bundle']['actor_template']['resources'] if r['resource_id'] == rid), 0)


def gain(session, actor_id, rid, amount):
    actor = session.state['actors'][actor_id]
    withheld = int(state(actor).get('drained', {}).get(rid, 0))
    before = actor['resources'].get(rid, 0)
    actor['resources'][rid] = min(max(0, maximum(actor, rid) - withheld), before + max(0, amount))
    session.emit('DREAM_RESOURCE_RECOVERED', actor_id, resource=rid, amount=actor['resources'][rid] - before)


def roll(session, actor_id, *, sides=20, count=1, modifier=0, mode='NORMAL', reason):
    from ..gate2_rolls import DeterministicRollAuthority
    from ..gate2_runtime_models import DiceSpec
    roller = DeterministicRollAuthority(session.state['journey_id'] + ':dream', counter=session.state.get('dream_roll_counter', 0))
    if sides == 20 and count == 1:
        result = roller.d20(modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
    else:
        result = roller.roll(DiceSpec(count=count, sides=sides, modifier=modifier), actor_id=actor_id, reason=reason)
    session.state['dream_roll_counter'] = roller.counter
    session.emit('DREAM_ROLLED', actor_id, reason=reason, roll=result.model_dump(mode='json'))
    return result.total


def damage(session, actor_id, amount):
    """Harvest Psychic damage through the shared outside-combat settlement.

    Consumers: finish_harvest's repeated-harvest and resisted-save branches.
    Either branch takes the target's native Psychic Resistance/Immunity, pays
    Temporary HP first and leaves the ordinary DAMAGE_COMMITTED receipt, so a
    defended creature is not treated like an unprotected one. Dream's printed
    awakening stays with this source; a sealed-sleep effect keeps it asleep.
    """
    from .journey_damage import settle, snapshot
    actor = session.state['actors'][actor_id]
    lost = settle(session, actor_id, amount, 'PSYCHIC', FEATURES[2], None)
    snap = snapshot(actor)
    if amount > 0:
        for key, raw in list(snap['conditions'].items()):
            condition = json.loads(raw)
            if condition['condition_id'] == 'condition:typed.dream_sleep' and not (condition.get('data', {}).get('rule') or {}).get('sealed_sleep'):
                snap['conditions'].pop(key)
                state(actor)['rest_mode'] = 'awake'
    session.emit('DREAM_HARVEST_DAMAGE', actor_id, amount=amount, hp_damage=lost,
                 damage_type='PSYCHIC', current_hp=snap['current_hp'])


def exhaustion(session, actor_id, amount):
    from .journey_path_resources import add_exhaustion
    add_exhaustion(session, actor_id, amount, FEATURES[2], event='DREAM_HARVEST_EXHAUSTION')


def inner(session, actor_id, viewer, scope):
    fact = read(session, PARENT, actor_id, 'inner_state', scope, viewer)
    require(fact is not None, 'The world owner must record this creature’s actual independent inner state.')
    value = fact['value']
    require(set(value) == {'genuine_consciousness', 'genuine_dreams', 'created_by', 'recursive', 'mindless', 'equivalent_source'},
            'Record genuine consciousness, dreams, creating actor, recursion, mindlessness and any explicit equivalent Source Rule.')
    require(all(type(value[k]) is int and value[k] in (0, 1) for k in ('genuine_consciousness', 'genuine_dreams', 'recursive', 'mindless'))
            and all(type(value[k]) is str for k in ('created_by', 'equivalent_source')), 'Use typed inner-state facts.')
    return value


@hook('journey_options')
def scene_options(session, actor_id):
    actor = session.state['actors'][actor_id]
    affected = bool(actor.get('source_states', {}).get(PARENT, {}).get('harvests'))
    if not owned(actor['bundle'], FEATURES[0]) and not affected:
        return []
    pending = actor.get('source_states', {}).get(PARENT, {}).get('harvest_save')
    if pending:
        can_rescue = pending['total'] + int(profile(actor)['pb']) >= pending['dc']
        return [{'id': 'dream:ward:' + str(use), 'kind': 'dream_harvest_save', 'auto_select': int(bool(use) == can_rescue),
                 'payload': {'use_ward': use}, 'label': f'{actor["name"]}: ' +
                 (f'Dream Ward: add {profile(actor)["pb"]} to your failed Harvest save ({pending["total"]} against {pending["dc"]}), once this scene' if use else 'Decline Dream Ward and resolve the failed Harvest save')}
                for use in (1, 0)]
    result = [{'id': 'dream:rest', 'kind': 'dream_rest_mode', 'payload': {'mode': 'meditating'},
             'label': 'Dreamer’s Rest: meditate with passive Perception; no actions while asleep until awakened.'},
            {'id': 'dream:cultivation', 'kind': 'dream_cultivation', 'payload': {'environment_scope': 'cultivation'},
             'label': 'Full Cultivation Session: meditate for two hours in calm ambient Qi, restore Qi and release harvested resource locks (once per Long Rest).'}]
    if not owned(actor['bundle'], FEATURES[0]):
        result = result[1:]
    if actor.get('source_states', {}).get(PARENT, {}).get('blurred_association'):
        for fact in session.state.get('fact_consent_admission', []):
            if fact['source'] == PARENT and fact['subject'] == actor_id and fact['kind'] == 'surface_check':
                current = read(session, PARENT, actor_id, 'surface_check', fact['scope'], actor_id)
                if current and current['receipt_id'] == fact['receipt_id']:
                    result.append({'id': 'dream:surface:' + fact['receipt_id'], 'kind': 'dream_surface_check',
                        'payload': {'scope': fact['scope']}, 'auto_select': 0,
                        'label': f'{actor["name"]}: attempt the requested Intelligence or Wisdom memory check with Disadvantage; this uses the one blurred association.'})
    if owned(actor['bundle'], FEATURES[2]):
        for target_id, target in session.state['actors'].items():
            if session.near_visible(actor_id, target_id):
                for mode, label in (('cultivation', 'Cultivation Residue'), ('memory', 'Surface Memory'), ('emotion', 'Emotional Residue')):
                    result.append({'id': f'dream:harvest:{target_id}:{mode}', 'kind': 'activity_start', 'payload': {'source': FEATURES[2], 'parameters': {
                        'target': target_id, 'mode': mode, 'inner_scope': 'inner-state', 'consent_scope': 'harvest:' + actor_id,
                        'content_scope': 'dream', 'association': state(actor).get('declared_association', ''), 'resource': QI}},
                        'label': f'Harvest {target["name"]}’s {label}: touch, 10 minutes, 2 Qi; target saves unless willing to fail. Requires native inner-state and dream inputs.'})
                    if state(actor).get('resonance'):
                        base = deepcopy(result[-1])
                        for trigger, words in (('repeat_damage', 'the repeated-harvest damage roll'),
                                               ('resisted_damage', 'the resisted-harvest damage roll'),
                                               *([('protected_check', 'the check against protecting dream authority')] if mode == 'memory' else [])):
                            row = deepcopy(base)
                            row['id'] = f'dream:harvest:{target_id}:{mode}:{trigger}'
                            row['payload']['parameters']['resonance'] = trigger
                            row['label'] = f'Harvest {target["name"]}’s {label}: 2 Qi, 10 minutes; spend your Dream Resonance to add 1d8 to {words}, if that roll occurs.'
                            result.append(row)
    return result


@hook('journey_command')
def scene_command(session, actor_id, kind, payload):
    if not kind.startswith('dream_'):
        return None
    actor = session.state['actors'][actor_id]
    affected = actor.get('source_states', {}).get(PARENT, {})
    require(owned(actor['bundle'], FEATURES[0]) or kind in ('dream_cultivation', 'dream_receive_restoration') and
            (affected.get('harvests') or affected.get('drained')) or kind == 'dream_surface_check' and affected.get('blurred_association'),
            'This creature has not acquired Dream Qi and has no harvested state to recover.')
    saved = state(actor)
    if kind == 'dream_rest_mode':
        require(set(payload) == {'mode'} and payload['mode'] in ('sleeping', 'meditating', 'awake'), 'Choose sleeping, meditating or awake.')
        saved['rest_mode'] = payload['mode']
        session.emit('DREAM_REST_MODE', actor_id, mode=payload['mode'])
    elif kind == 'dream_notice_threat':
        require(set(payload) == {'scope'}, 'Choose the world-owner threat in your immediate surroundings.')
        fact = read(session, PARENT, actor_id, 'rest_threat', payload['scope'], actor_id)
        require(fact and set(fact['value']) == {'perception_dc', 'source_rule', 'sealed_sleep_cl'}
                and type(fact['value']['perception_dc']) is int and type(fact['value']['sealed_sleep_cl']) is int,
                'The world owner must record an actual perceived threat and any deeper or sealed supernatural sleep authority.')
        value = fact['value']
        passive = 10 + int(actor['bundle']['actor_template'].get('skills', {}).get('Perception', profile(actor).get('ability_mods', {}).get('WIS', 0)))
        perceived = passive >= value['perception_dc']
        sealed = bool(value['source_rule']) and value['sealed_sleep_cl'] >= int(profile(actor)['cl'])
        if perceived and not sealed:
            saved['rest_mode'] = 'awake'
        session.emit('DREAM_THREAT_PERCEIVED', actor_id, perception=passive, perceived=int(perceived), awakened=int(perceived and not sealed), authority_receipt=fact['receipt_id'])
    elif kind == 'dream_prepare_expression':
        require(set(payload) == {'expression'} and type(payload['expression']) is str and 0 < len(payload['expression'].strip()) <= 500,
                'Name one fixed visible dream image, up to 500 characters.')
        saved['expression'] = payload['expression'].strip()
        session.emit('DREAM_EXPRESSION_CHOSEN', actor_id)
    elif kind == 'dream_prepare_message':
        require(set(payload) == {'message'} and type(payload['message']) is str and 0 < len(payload['message'].strip()) <= 2000,
                'Choose a private message of symbols, emotions, images or speech, up to 2000 characters.')
        saved['message'] = payload['message'].strip()
        session.emit('DREAM_MESSAGE_PREPARED', actor_id)
    elif kind == 'dream_receive_restoration':
        require(set(payload) == {'scope'}, 'Choose the native world-owner record of received dream restoration.')
        restoration = read(session, PARENT, actor_id, 'dream_restoration', payload['scope'], actor_id)
        require(restoration and set(restoration['value']) == {'source_rule', 'source_cl'} and
                type(restoration['value']['source_rule']) is str and restoration['value']['source_rule'] and
                type(restoration['value']['source_cl']) is int and restoration['value']['source_cl'] >= int(saved.get('drain_cl', 1)),
                'The world owner must identify actual equal- or higher-Source-CL dream restoration and its native event.')
        event_id = 'dream-restoration:' + restoration['receipt_id']
        matched = [(i, e) for i, e in enumerate(session.state['events']) if e.get('event_id') == event_id]
        require(matched and matched[0][0] >= int(saved.get('drained_at_sequence', 0)) and
                matched[0][1].get('dream_restoration') == 1 and matched[0][1].get('actor_id') == actor_id and
                matched[0][1].get('source_cl', 0) >= int(saved.get('drain_cl', 1)),
                'A declaration alone cannot replace the committed native dream-restoration event.')
        # This is source restoration admission, not a new restoration ability.
        # It grants no Qi; the target can subsequently recover withheld points.
        saved['drained'] = {}
        session.emit('DREAM_DRAIN_RESTORED', actor_id, restoration_receipt=restoration['receipt_id'], native_event=event_id)
    elif kind == 'dream_harvest_save':
        require(set(payload) == {'use_ward'} and type(payload['use_ward']) is int and payload['use_ward'] in (0, 1)
                and saved.get('harvest_save'), 'Choose whether to use your Dream Ward on this pending failed save.')
        pending = saved.pop('harvest_save')
        total = pending['total']
        if payload['use_ward']:
            require(not saved.get('ward_used'), 'Dream Ward was already used this scene.')
            total += int(profile(actor)['pb'])
            saved['ward_used'] = 1
        session.emit('DREAM_WARD_SETTLED', actor_id, source=FEATURES[0], total=total, dc=pending['dc'], used=payload['use_ward'])
        state(session.state['actors'][pending['resolution']['actor']]).pop('waiting_harvest_target', None)
        finish_harvest(session, pending['resolution'], total < pending['dc'])
    elif kind == 'dream_surface_check':
        require(set(payload) == {'scope'}, 'Choose the native world-owner request for this relevant memory check.')
        request = read(session, PARENT, actor_id, 'surface_check', payload['scope'], actor_id)
        require(request and set(request['value']) == {'association', 'ability', 'skill', 'dc'}, 'The world owner must specify the actual relevant check, not its outcome.')
        spec = request['value']
        require(spec['association'] == saved.get('blurred_association') and spec['ability'] in ('INT', 'WIS') and
                type(spec['skill']) is str and type(spec['dc']) is int and spec['dc'] >= 0 and
                spec['ability'] in actor.get('check_mods', {}), 'Use one relevant Intelligence or Wisdom check with actual sealed ability statistics.')
        used = saved.setdefault('surface_checks', [])
        require(request['receipt_id'] not in used, 'This native check was already rolled.')
        modifier = actor['bundle']['actor_template'].get('skills', {}).get(spec['skill'], actor['check_mods'][spec['ability']])
        total = roll(session, actor_id, modifier=int(modifier) - 2 * actor['exhaustion'], mode='DISADVANTAGE', reason='BLURRED_SURFACE_ASSOCIATION')
        used.append(request['receipt_id'])
        saved.pop('blurred_association')
        session.emit('DREAM_SURFACE_CHECK_RESOLVED', actor_id, total=total, success=int(total >= spec['dc']), request=request['receipt_id'])
    elif kind == 'dream_association':
        require(set(payload) == {'association'} and type(payload['association']) is str and 0 < len(payload['association']) <= 500,
                'Declare the person, place, object or event for the surface memory.')
        saved['declared_association'] = payload['association']
    elif kind == 'dream_cultivation':
        require(set(payload) == {'environment_scope'} and not saved.get('cultivation_used'), 'Choose a Full Cultivation Session once per Long Rest.')
        fact = read(session, PARENT, actor_id, 'cultivation_environment', payload['environment_scope'], actor_id)
        require(fact and fact['value'] == 1 and fact['expires_at'] > session.clock() + 7200,
                'Confirm calm surroundings and ambient Qi for the complete two-hour session.')
        require(not actor['incapacitated'], 'An incapacitated creature cannot cultivate.')
        session.tick(7200)
        saved.update(drained={}, harvests=0, successes=0, cultivation_used=1)
        gain(session, actor_id, QI, maximum(actor, QI))
        session.emit('DREAM_FULL_CULTIVATION', actor_id)
    elif kind == 'dream_harvest':
        harvest(session, actor_id, payload)
    else:
        return None
    sync(session)
    return True


@hook('journey_properties')
def rest_properties(session, actor_id):
    actor = session.state['actors'][actor_id]
    if not owned(actor['bundle'], FEATURES[0]):
        return None
    mode = state(actor).get('rest_mode', 'awake')
    saved = state(actor)
    memory = json.loads(saved['memory']) if saved.get('memory') else {}
    return {'dream_rest_mode': mode, 'counts_as_sleeping': int(mode == 'sleeping'),
            'counts_as_resting': int(mode in ('sleeping', 'meditating')), 'passive_perception_while_resting': 1,
            'asleep_alone_causes_surprise': 0, 'dream_surface_memory': memory.get('fragment', ''),
            'dream_memory_association': memory.get('association', ''), 'dream_emotion': saved.get('emotion', ''),
            'dream_resonance': int(bool(saved.get('resonance')))}


@hook('journey_step')
def sleeping_movement(session, actor_id, previous, destination, regions):
    # journey_step is a pure presentation query on current main; the strict
    # command gate below is what actually blocks a sleeping creature's move.
    return None


def harvest(session, actor_id, payload, *, prepare=False, paid=False, elapsed=False):
    require(set(payload) <= {'target', 'mode', 'inner_scope', 'consent_scope', 'content_scope', 'resource', 'association', 'resonance'}
            and {'target', 'mode', 'inner_scope'} <= set(payload), 'Choose a real target, residue, and scoped native inputs.')
    actor = session.state['actors'][actor_id]
    require(state(actor).get('rest_mode') != 'sleeping', 'Awaken before taking actions or working while asleep during Dreamer’s Rest.')
    require(owned(actor['bundle'], FEATURES[2]) and not actor['incapacitated'], 'Dream Refinement requires acquired CL10 and ability to perform the ritual.')
    target_id = payload['target']
    require(target_id in session.state['actors'] and (target_id == actor_id or session.near_visible(actor_id, target_id)), 'Harvest requires touching one real creature.')
    target = session.state['actors'][target_id]
    nature = inner(session, target_id, actor_id, payload['inner_scope'])
    require(nature['genuine_consciousness'], 'Harvest requires genuine consciousness.')
    consent = read(session, PARENT, target_id, 'harvest_consent', payload.get('consent_scope', ''), actor_id)
    willing = bool(consent and consent['value'].get('harvester') == actor_id and consent['value'].get('willing') == 1)
    snap = target.get('encounter_snapshot') or {}
    names = {json.loads(c)['condition_id'].split('.')[-1] for c in snap.get('conditions', {}).values()}
    require('death_finalized' not in names, 'A finalized dead creature is not an available living dream source.')
    require(willing or state(target).get('rest_mode') == 'sleeping' or target['incapacitated'] or names & {'dream_sleep', 'unconscious', 'incapacitated', 'restrained', 'completely_subdued'},
            'The target must be asleep, dreaming, incapacitated, restrained, completely subdued or genuinely willing.')
    mode = payload['mode']
    require(mode in ('cultivation', 'memory', 'emotion'), 'Choose cultivation residue, surface memory or emotional residue.')
    resonance = payload.get('resonance', '')
    require(resonance in ('', 'repeat_damage', 'resisted_damage', 'protected_check') and
            (not resonance or state(actor).get('resonance')) and (resonance != 'protected_check' or mode == 'memory'),
            'Choose one available Dream Resonance bonus, spent only if its actual roll occurs.')
    content = None
    if mode != 'cultivation':
        content = read(session, PARENT, target_id, 'dream_content', payload.get('content_scope', ''), actor_id)
        require(content and set(content['value']) == {'association', 'fragment', 'emotion', 'protection_dc', 'protected_kind'}
                and all(type(content['value'][k]) is str for k in ('association', 'fragment', 'emotion', 'protected_kind'))
                and type(content['value']['protection_dc']) is int and content['value']['protection_dc'] >= 0,
                'The target’s controller must supply a private brief fragment, association, emotion and protecting authority.')
        if mode == 'memory':
            require(content['value']['association'] == payload.get('association') and content['value']['fragment'], 'Declare the person, place, object or event the brief fragment concerns.')
            protection = read(session, PARENT, target_id, 'memory_authority', payload.get('content_scope', ''), actor_id)
            require(protection and set(protection['value']) == {'kind', 'dc', 'source_rule'} and
                    protection['value']['kind'] in ('surface', 'true_name', 'secret_inheritance', 'sealed_memory', 'defining_identity') and
                    type(protection['value']['dc']) is int and protection['value']['dc'] >= (0 if protection['value']['kind'] == 'surface' else 1)
                    and type(protection['value']['source_rule']) is str and protection['value']['source_rule'],
                    'The world owner must record the actual memory protection; a subject’s narration cannot bypass protecting authority.')
    else:
        rid = payload.get('resource')
        require(rid in ('resource:core.qi', 'resource:core.stamina', 'resource:core.resonance') and rid in target['resources'], 'Choose a Cultivation Point resource the target actually possesses.')
        require(qi_source(actor_id, target_id, nature), 'Self, own created minds, recursive copies and minds without genuine dreams or an explicit independent equivalent cannot restore Qi.')
    require(paid or actor['resources'].get(QI, 0) >= 2, 'Harvest costs 2 Qi.')
    # All inputs must remain valid throughout the actual ten-minute procedure.
    remaining = 0 if elapsed else 600
    require((not consent or consent['expires_at'] > session.clock() + remaining) and
            (not content or content['expires_at'] > session.clock() + remaining) and
            (mode != 'memory' or protection['expires_at'] > session.clock() + remaining), 'Dream input expires before the ritual completes.')
    if prepare:
        return
    if not paid:
        session.spend_resource(actor_id, QI, 2, FEATURES[2])
    if not elapsed:
        session.tick(600)
    inner(session, target_id, actor_id, payload['inner_scope'])
    saved = state(target)
    previous = int(saved.get('harvests', 0))
    successes = int(saved.get('successes', 0))
    n = profile(actor)
    dc = int(n['save_dc'])
    modifier = int(target['bundle']['actor_template']['saving_throws'].get('WIS', 0))
    voluntary_fail = willing and consent['value'].get('fail_save') == 1
    ward = owned(target['bundle'], FEATURES[0])
    save_mode = 'ADVANTAGE' if ward and successes < 2 else 'DISADVANTAGE' if successes >= 2 and not ward else 'NORMAL'
    total = dc - 1 if voluntary_fail else roll(session, target_id, modifier=modifier - 2 * target['exhaustion'], mode=save_mode, reason='HARVEST_WISDOM_SAVE')
    resolution = {'actor': actor_id, 'target': target_id, 'mode': mode, 'nature': nature,
                  'resonance': resonance,
                  'content': content['value'] if content else {}, 'protection': protection['value'] if mode == 'memory' else {},
                  'resource': rid if mode == 'cultivation' else '',
                  'numbers': {k: int(n[k]) for k in ('pb', 'cl', 'key_mod', 'save_dc')}}
    if total < dc and ward and not voluntary_fail and not saved.get('ward_used'):
        saved['harvest_save'] = {'total': total, 'dc': dc, 'resolution': resolution}
        state(actor)['waiting_harvest_target'] = target_id
        session.emit('DREAM_HARVEST_SAVE_PENDING', target_id, caster=actor_id, source=FEATURES[0])
        return
    finish_harvest(session, resolution, total < dc)


def finish_harvest(session, resolution, failed):
    """Settle one actually rolled native Harvest; also used after Dream Ward."""
    actor_id, target_id, mode = resolution['actor'], resolution['target'], resolution['mode']
    actor, target = session.state['actors'][actor_id], session.state['actors'][target_id]
    n, nature, rid = resolution['numbers'], resolution['nature'], resolution['resource']
    content, protection = {'value': resolution['content']}, {'value': resolution['protection']}
    saved = state(target)
    previous, successes = int(saved.get('harvests', 0)), int(saved.get('successes', 0))
    saved['harvests'] = previous + 1
    if previous:
        amount = roll(session, target_id, sides=8, count=2, reason='REPEATED_HARVEST_DAMAGE')
        amount += resonance_bonus(session, resolution, 'repeat_damage')
        damage(session, target_id, amount)
    result = ''
    if failed:
        saved['successes'] = successes + 1
        if previous:
            exhaustion(session, target_id, 1)
        if mode == 'cultivation':
            require(qi_source(actor_id, target_id, nature), 'This is not an independent Qi source.')
            amount = min(int(n['pb']), target['resources'][rid])
            if amount:
                session.spend_resource(target_id, rid, amount, FEATURES[2])
            saved.setdefault('drained', {})[rid] = int(saved.get('drained', {}).get(rid, 0)) + amount
            saved['drain_cl'] = int(n['cl'])
            saved['drained_at_sequence'] = len(session.state['events'])
            exhaustion(session, target_id, 1)
            gain(session, actor_id, QI, amount)
            result = f'Drained {amount} current cultivation points; recovery blocked until Full Cultivation or sufficient dream restoration.'
        elif mode == 'emotion':
            state(actor)['resonance'] = 1
            state(actor)['emotion'] = content['value']['emotion']
            result = 'Gained one Dream Resonance until the end of the next Long Rest.'
        else:
            doc = content['value']
            protected = protection['value']
            if protected['kind'] == 'surface':
                allowed = True
            else:
                total = roll(session, actor_id, modifier=int(n['pb']) + int(n['key_mod']), reason='PROTECTED_DREAM_CULTIVATION_CHECK')
                total += resonance_bonus(session, resolution, 'protected_check')
                allowed = total >= protected['dc']
            state(actor)['memory'] = canonical({'fragment': doc['fragment'] if allowed else 'The protecting authority conceals this fragment.', 'association': doc['association']})
            saved['blurred_association'] = doc['association']
            result = 'Observed a brief surface fragment; one relevant Intelligence or Wisdom check is blurred until Long Rest.'
    else:
        amount = roll(session, target_id, sides=8, count=2, reason='RESISTED_HARVEST_DAMAGE')
        amount += resonance_bonus(session, resolution, 'resisted_damage')
        damage(session, target_id, amount)
        conditions = [json.loads(c) for c in (target.get('encounter_snapshot') or {}).get('conditions', {}).values()]
        if not any((c.get('data', {}).get('rule') or {}).get('sealed_sleep') for c in conditions):
            saved['rest_mode'] = 'awake'
        if not any((c.get('data', {}).get('rule') or {}).get('conceals_dream_intrusion') for c in conditions):
            saved['intrusion_known'] = actor_id
        result = 'The target resisted, took Psychic damage and perceived the intrusion.'
    session.emit('DREAM_HARVEST_RESOLVED', actor_id, target=target_id, mode=mode, failed=int(failed), previous=previous, result=result)


def resonance_bonus(session, resolution, trigger):
    actor_id = resolution['actor']
    saved = state(session.state['actors'][actor_id])
    if resolution.get('resonance') != trigger or not saved.get('resonance'):
        return 0
    saved.pop('resonance')
    bonus = roll(session, actor_id, sides=8, reason='DREAM_RESONANCE')
    session.emit('DREAM_RESONANCE_SPENT', actor_id, bonus=bonus, trigger=trigger)
    return bonus


@hook('journey_before_command')
def pending_save_gate(session, actor_id, kind, payload):
    saved = session.state['actors'][actor_id].get('source_states', {}).get(PARENT) or {}
    if kind == 'move' and saved.get('rest_mode') == 'sleeping':
        raise ValueError('Awaken before taking actions or moving while asleep during Dreamer’s Rest.')
    pending = [aid for aid, actor in session.state['actors'].items() if actor.get('source_states', {}).get(PARENT, {}).get('harvest_save')]
    if pending:
        require(kind == 'dream_harvest_save' and actor_id in pending, 'Resolve the target’s pending Dream Ward decision before another action or time advance.')


@hook('journey_world_fact_committed')
def pending_world_gate(session, receipt):
    require(not any(actor.get('source_states', {}).get(PARENT, {}).get('harvest_save') for actor in session.state['actors'].values()),
            'Resolve the pending Dream Ward save before changing its native world inputs.')
    if receipt['source'] == PARENT and receipt['kind'] == 'dream_restoration':
        value = receipt['value']
        require(set(value) == {'source_rule', 'source_cl'} and type(value['source_rule']) is str and
                bool(value['source_rule'].strip()) and len(value['source_rule']) <= 2000 and
                type(value['source_cl']) is int and value['source_cl'] >= 1,
                'Name the actual external dream-restoration Source Rule and its positive Source CL.')
        # This is the native world owner's application of an external treatment,
        # like the shared external-effect producer. It grants no restoration
        # ability, Qi or ownership; the consumer must still compare actual CL.
        session.emit('DREAM_RESTORATION_RECEIVED', receipt['subject'], authority='table_owner',
            source_rule=value['source_rule'], source_cl=value['source_cl'], dream_restoration=1,
            event_id='dream-restoration:' + receipt['receipt_id'], receipt_id=receipt['receipt_id'])


@hook('activity_spec')
def harvest_activity(session, actor_id, source, parameters):
    if source != FEATURES[2]:
        return None
    harvest(session, actor_id, parameters, prepare=True)
    return {'seconds': 600, 'label': 'Harvest a Surface Dream: touch for ten minutes (2 Qi)'}


@hook('activity_started')
def harvest_started(session, actor_id, row):
    if row['source'] == FEATURES[2]:
        session.spend_resource(actor_id, QI, 2, FEATURES[2])
        sync(session)


@hook('activity_validate')
def harvest_validate(session, actor_id, row):
    if row['source'] == FEATURES[2]:
        harvest(session, actor_id, row['parameters'], prepare=True, paid=True, elapsed=True)


@hook('activity_finished')
def harvest_finished(session, actor_id, row):
    if row['source'] == FEATURES[2]:
        harvest(session, actor_id, row['parameters'], paid=True, elapsed=True)
        sync(session)


@hook('activity_command_interrupts')
def harvest_interrupts(session, worker, row, actor_id, kind, payload):
    if row['source'] != FEATURES[2]:
        return None
    if actor_id == worker and kind in ('dream_harvest', 'dream_cultivation', 'dream_rest_mode'):
        return True
    if row['parameters']['target'] == actor_id and kind == 'move':
        from ..gate2_runtime_models import Position
        origin = Position.model_validate(session.state['actors'][worker]['position'])
        if any(session.grid.distance_ft(origin, Position.model_validate(p)) > 5 or
               not session.grid.line_of_physical_transmission(origin, Position.model_validate(p))
               for p in payload.get('path', [])):
            return True


@hook('journey_rest')
def rest(session, actor_id):
    actor = session.state['actors'][actor_id]
    saved = actor.get('source_states', {}).get(PARENT)
    if saved is not None:
        for key in ('resonance', 'emotion', 'blurred_association', 'harvests', 'successes', 'cultivation_used'):
            saved.pop(key, None)
        saved['rest_mode'] = 'awake'
    if owned(actor['bundle'], FEATURES[0]):
        gain(session, actor_id, QI, maximum(actor, QI) // 2)
        session.emit('DREAM_NORMAL_QI_RECOVERY', actor_id)
        gain(session, actor_id, QI, int(profile(actor)['pb']))
        session.emit('DREAM_ONEIRIC_RECOVERY', actor_id)
    sync(session)


@hook('journey_scene_end')
def scene_end(session, previous, current):
    for actor in session.state['actors'].values():
        saved = actor.get('source_states', {}).get(PARENT)
        if saved is not None:
            for key in ('ward_used', 'waking_gains', 'ascension_used'):
                saved.pop(key, None)
    sync(session)
