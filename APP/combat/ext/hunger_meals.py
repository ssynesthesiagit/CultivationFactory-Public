"""Refine the Meal's elapsed-time procedure and source-linked Satiety.

Consumers: journey's revision-checked owner commands and hunger_riders. The
public selected_source/activation_source/consume_source helpers connect a real refined portion to
the existing Mantle provider. No creature/material facts are inferred. Recording
a portion is a GM inventory declaration, never an automatic character action.
The journey registry retains the ledger in travel_uses; combat retains it in an
evented permanent condition. Sensory memories stay in the owner journey record,
and never enter the public combat condition, menu or combat log.
"""
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
import json

from . import hook, effect
from .needle import ask, checkpoint_id, CHOICE
from .retained_updates import record_instance_update

REFINE = 'HUNGER_BASE_REFINE_THE_MEAL'
MANTLE = 'HUNGER_BASE_DIGESTIVE_MANTLE'
KEY = 'hunger_meals'
LEDGER = 'condition:typed.hunger_meals'
SAT = 'resource:named.satiety'
IMP = 'resource:named.impurity'
BENEFITS = ('Beast Strength', 'Predator Step', 'Iron Stomach', 'Thick Hide',
            'Venom Belly', 'Furnace Belly', 'Elemental Gut', 'Deep Nourishment')
ELEMENTS = ('acid', 'cold', 'fire', 'lightning', 'necrotic', 'poison', 'thunder')
REWARDS = ('cleanse', 'temporary_hp', 'free_mantle', 'memory')
_SPEND_BENEFIT = ContextVar('hunger_source_spend_benefit', default=None)


def _condition_label(engine, condition):
    from ..condition_text import condition_reading
    from .ability_source import source_label
    reading = condition_reading(condition.condition_id)
    return str(condition.data.get('label') or (reading[0] if reading else
               'Condition from ' + source_label(engine, condition.source_definition_id)))


@hook('compile_bundle')
def compile_meals(bundle, info):
    sheet = info['owner_sheet'].get('spheres_and_talents') or {}
    bases = sheet.get('automatic_sphere_component_record_ids') or []
    if REFINE not in bases:
        return None
    out = deepcopy(bundle)
    numbers = info['numbers']
    cp = next((pool for action in out['action_catalog']
               if ((action.get('parameters', {}).get('typed') or {}).get('option_of')
                   or (action.get('parameters', {}).get('typed') or {}).get('source')) in (REFINE, MANTLE)
               for pool, _ in action.get('costs', [])
               if pool.startswith('resource:core.') and pool != 'resource:core.martial_focus'), None)
    if cp is None:
        cp = next((r['resource_id'] for r in out['actor_template']['resources']
                   if r['resource_id'] == 'resource:core.' + str(info['primary']).lower()), None)
    if cp is None:
        cp = next((r['resource_id'] for r in out['actor_template']['resources']
                   if r['resource_id'] in ('resource:core.qi', 'resource:core.stamina', 'resource:core.devil_qi')), None)
    out[KEY] = {'pb': int(numbers['pb']), 'key_mod': int(numbers['key_mod']),
                'cl': int(numbers['cl']), 'cp': cp or '',
                'satiety_max': next((int(r['maximum']) for r in out['actor_template']['resources'] if r['resource_id'] == SAT), int(numbers['pb']))}
    # The printed routing explicitly forbids turning the ritual into an instant
    # combat action. The journey menu below supplies both procedure modes.
    removed = {a['source_definition_id'] for a in out['action_catalog']
               if (a.get('parameters', {}).get('typed') or {}).get('source') == REFINE}
    out['action_catalog'] = [a for a in out['action_catalog'] if a['source_definition_id'] not in removed]
    out['actor_template']['action_ids'] = [a for a in out['actor_template']['action_ids'] if a not in removed]
    aid = 'action:typed.hunger_meal_selection.' + bundle['actor_id']
    out['action_catalog'].append({'source_definition_id': aid, 'display_name': 'Digestive Mantle: select stored meal',
        'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
        'parameters': {'setting_only': True, 'setting_description': 'Choose which source-linked Satiety your next Digestive Mantle consumes. No action or resource cost.',
            'typed': {'source': MANTLE + ':select_meal', 'numbers': dict(numbers), 'duration': {'kind': 'instant'},
                'effects': [{'type': 'hunger_select_meal'}]}}})
    out['actor_template']['action_ids'].append(aid)
    return out


def _state(session, aid, *, save=True):
    actor = session.state['actors'][aid]
    state = deepcopy(actor['travel_uses'].get(KEY) or
        {'portions': {}, 'charges': [], 'selected': '', 'counter': 0, 'temporary_hp': 0, 'memories': []})
    for raw in actor.get('encounter_snapshot', {}).get('conditions', {}).values():
        condition = json.loads(raw)
        if condition['condition_id'] == LEDGER:
            receipt = json.loads(condition['data']['receipt'])
            state.update(charges=receipt['charges'], selected=receipt['selected'], temporary_hp=0)
    if save:
        actor['travel_uses'][KEY] = state
        # Health stays in its generic snapshot; the owned source ledger moves
        # back to journey storage, preventing a spent charge from reappearing.
        snapshot = actor.get('encounter_snapshot')
        if snapshot:
            snapshot['conditions'] = {key: raw for key, raw in snapshot['conditions'].items()
                                      if json.loads(raw)['condition_id'] != LEDGER}
    return state


def _owned(session, aid):
    return KEY in session.state['actors'][aid]['bundle']


def _sync(session, aid):
    state = _state(session, aid)
    # No sensory contents or unused ingredient secrets cross into public combat.
    public = {k: deepcopy(state[k]) for k in ('charges', 'selected', 'temporary_hp')}
    session.state['actors'][aid]['bundle']['hunger_meal_receipt'] = public
    snapshot = session.state['actors'][aid].get('encounter_snapshot')
    if snapshot and state['temporary_hp']:
        snapshot['temporary_hp'] = max(snapshot['temporary_hp'], state['temporary_hp'])


@hook('journey_options')
def meal_options(session, aid):
    if not _owned(session, aid) or session.state['phase'] != 'travel':
        return None
    actor = session.state['actors'][aid]
    state = _state(session, aid, save=False)
    pending = state.get('pending')
    if pending:
        return [{'id': 'refine_reward:' + reward, 'kind': 'refine_reward', 'payload': {'reward': reward},
            'label': 'Refine the Meal: ' + {'cleanse': 'reduce Impurity (spiritual residue that can destabilize a Mantle) by 1',
                'temporary_hp': 'gain Temporary HP equal to your Proficiency Bonus',
                'free_mantle': 'this stored nourishment makes its next Digestive Mantle cost 0 cultivation points; still use a Bonus Action and spend the charge',
                'memory': 'learn one harmless sensory memory supplied by the Game Master'}[reward]}
            for reward in REWARDS]
    if actor['incapacitated']:
        return []
    return [{'id': mode + ':' + pid, 'kind': 'refine_meal',
        'payload': {'portion_id': pid, 'mode': mode, 'steady_cp': 0},
        'label': f"Refine the Meal: consume {portion['name']} and spend 1 cultivation point; "
                 + ('a 10-minute ritual' if mode == 'TEN_MINUTE_REFINE' else 'part of a one-hour short rest')
                 + '. Roll a Hunger Check; success gains 1 Satiety (stored nourishment for Digestive Mantle).'}
        for pid, portion in (state.get('portions') or {}).items()
        for mode in ('TEN_MINUTE_REFINE', 'SHORT_REST_REFINE')
        if actor['resources'].get(actor['bundle'][KEY]['cp'], 0) >= 1]


@hook('journey_auto_blocked')
def meal_pending(session, aid):
    if _owned(session, aid):
        state = _state(session, aid, save=False)
        if state.get('pending') and session.state['actors'][aid]['control_mode'] == 'MANUAL':
            return True
    return None


@hook('journey_command')
def meal_command(session, aid, kind, payload):
    if kind in ('record_essence_portion', 'supply_refine_memory'):
        raise ValueError('Ingredient circumstances and sensory memories require the native table-owner fact input.')
    return apply_meal_command(session, aid, kind, payload)


@hook('fact_admission_schema')
def meal_input_schema(session, source, subject, kind):
    if source != REFINE or kind not in ('essence_portion', 'refine_sensory_memory') or not _owned(session, subject):
        return None
    return {'value_type': 'document', 'maximum_seconds': 86400, 'authority': 'table_owner',
            'validate_value': True, 'description': 'Record an actual carried ingredient and its source circumstances.'
            if kind == 'essence_portion' else 'Supply one harmless sensory memory for a pending refinement benefit.'}


@hook('fact_admission_value')
def meal_input_value(session, payload):
    if payload.get('source') != REFINE or payload.get('kind') not in ('essence_portion', 'refine_sensory_memory'):
        return None
    from ..journey import JourneySession, require
    value = payload['value']
    require(isinstance(value, dict), 'Supply the full typed source record.')
    pending = _state(session, payload['subject'], save=False).get('pending') or {}
    expected = value.get('portion_id') if payload['kind'] == 'essence_portion' else 'pending-memory:' + str(pending.get('portion_id', ''))
    require(payload['scope'] == str(expected), 'Bind the declaration to its actual portion or pending memory.')
    probe = JourneySession(deepcopy(session.state))
    apply_meal_command(probe, payload['subject'], 'record_essence_portion'
        if payload['kind'] == 'essence_portion' else 'supply_refine_memory', value)
    return True


@hook('fact_admitted')
def meal_input_admitted(session, record):
    if record['source'] == REFINE and record['kind'] in ('essence_portion', 'refine_sensory_memory'):
        apply_meal_command(session, record['subject'], 'record_essence_portion'
            if record['kind'] == 'essence_portion' else 'supply_refine_memory', record['value'])


def apply_meal_command(session, aid, kind, payload):
    if kind not in ('record_essence_portion', 'refine_meal', 'refine_reward', 'supply_refine_memory') or not _owned(session, aid):
        return None
    from ..journey import require, integer
    actor, state = session.state['actors'][aid], _state(session, aid)
    config = actor['bundle'][KEY]
    if kind == 'supply_refine_memory':
        require(state.get('pending')
                and set(payload) == {'memory', 'ruling'}
                and all(isinstance(v, str) and v.strip() for v in payload.values()),
                'The GM may supply one harmless sensory memory and its source ruling for a pending benefit.')
        state['pending']['memories'] = [payload['memory']]
        session.emit('REFINE_MEMORY_SUPPLIED', aid, text='The GM supplies one harmless ingredient memory to its consumer.')
    elif kind == 'record_essence_portion':
        # This command is an explicit owner/GM entry point, absent from every
        # automatic menu. A GM can supply facts for an automatic creature too;
        # journey_auto_step can select only the offered, already-sourced actions.
        required = {'portion_id', 'name', 'grade', 'corrupted', 'demon_beast', 'source_realm', 'meaningful', 'benefits', 'elements', 'ruling'}
        require(required <= set(payload) <= required | {'weak_elements', 'limited_elements', 'venom_type', 'memories', 'above_realm'},
                'Record the portion identity, grade, source Realm, meaningful spiritual ingredient ruling and suitable benefits/types.')
        require(all(isinstance(payload[k], str) and payload[k].strip() for k in ('portion_id', 'name', 'ruling')),
                'A portion needs an identity, name and GM source ruling.')
        require(payload['portion_id'] not in state.get('seen', []), 'This ingredient portion was already recorded or consumed.')
        require(payload['grade'] in ('common', 'notable', 'mighty') and type(payload['corrupted']) is int
                and payload['corrupted'] in (0, 1) and integer(payload['source_realm'])
                and type(payload['meaningful']) is int and payload['meaningful'] == 1,
                'The GM must classify a meaningful, persistent, spiritually real portion and its source Realm.')
        require('above_realm' not in payload or type(payload['above_realm']) is int and payload['above_realm'] in (0,1),
                'An explicit above-Realm ruling must be 0 or 1.')
        require((payload['source_realm'] <= 3 and config['cl'] <= 20) or 'above_realm' in payload,
                'Beyond the four native combat Realm bands, the GM must explicitly rule whether this source is above your Realm; that relationship is unknown.')
        require(isinstance(payload['benefits'], list) and payload['benefits']
                and all(x in BENEFITS for x in payload['benefits']) and len(set(payload['benefits'])) == len(payload['benefits']),
                'Record the basic Mantle benefits that fit this source.')
        for key in ('elements', 'weak_elements', 'limited_elements'):
            require(isinstance(payload.get(key, []), list) and all(x in ELEMENTS for x in payload.get(key, [])),
                    'Source-associated damage types must be recorded explicitly.')
        require(set(payload.get('weak_elements', [])) <= set(payload['elements']), 'Weak associations must also be source-associated types.')
        require(set(payload.get('limited_elements', [])) <= set(payload.get('weak_elements', [])),
                'The GM may explicitly limit only a weakly associated Elemental Gut type to its first triggering damage instance per round.')
        require('Elemental Gut' not in payload['benefits'] or payload['elements'], 'Elemental Gut requires at least one recorded source-associated damage type.')
        require(payload.get('venom_type', 'poison') in ('acid', 'poison'), 'Venom Belly uses Acid or Poison.')
        require('Venom Belly' not in payload['benefits'] or 'venom_type' in payload,
                'Record the Acid or Poison expression for a source that supports Venom Belly; an unknown expression is not guessed.')
        require(type(payload.get('demon_beast', 0)) is int and payload.get('demon_beast', 0) in (0, 1), 'Record whether the source is a demon beast.')
        require(isinstance(payload.get('memories', []), list) and all(isinstance(x, str) and x.strip() for x in payload.get('memories', [])),
                'Supply only harmless sensory memories the GM permits the ingredient to reveal.')
        state['portions'][payload['portion_id']] = deepcopy(payload)
        state.setdefault('seen', []).append(payload['portion_id'])
        session.emit('ESSENCE_PORTION_RECORDED', aid, portion_id=payload['portion_id'], text='The GM records one carried Essence Portion and its source ruling.')
    elif kind == 'refine_meal':
        require(set(payload) == {'portion_id', 'mode', 'steady_cp'} and not state.get('pending') and not actor['incapacitated'],
                'Finish your pending Refine the Meal benefit before starting another ritual; incapacitated creatures cannot refine.')
        require(payload['mode'] in ('TEN_MINUTE_REFINE', 'SHORT_REST_REFINE'), 'Choose the 10-minute ritual or short-rest activity.')
        portion = state['portions'].get(payload['portion_id'])
        steady = payload['steady_cp']
        require(portion is not None and integer(steady) and steady <= config['pb'], 'Choose a carried portion and 0 to Proficiency Bonus CP before the roll.')
        require(actor['resources'].get(config['cp'], 0) >= 1 + steady, 'Refine the Meal costs 1 CP plus any CP committed to steady the check.')
        require(actor['resources'].get(SAT, 0) < config.get('satiety_max', config['pb']), 'Your Satiety is full (your Proficiency Bonus, plus any printed capacity increases).')
        dc = {'common': 12, 'notable': 15, 'mighty': 18}[portion['grade']] + 2 * portion['corrupted']
        cl = config['cl']
        realm = 0 if cl < 5 else 1 if cl < 10 else 2 if cl < 15 else 3
        dc += 2 * portion.get('above_realm', int(portion['source_realm'] > realm))
        actor['resources'][config['cp']] -= 1 + steady
        del state['portions'][payload['portion_id']]
        session.tick(600 if payload['mode'] == 'TEN_MINUTE_REFINE' else 3600)
        from ..gate2_rolls import DeterministicRollAuthority
        roller = DeterministicRollAuthority(session.state['journey_id'] + ':' + aid, state['counter'])
        roll = roller.d20(modifier=config['pb'] + config['key_mod'] + steady, actor_id=aid, reason='CHECK:' + REFINE)
        state['counter'] = roller.counter
        margin = roll.total - dc
        if margin >= 0:
            charge = {k: deepcopy(portion[k]) for k in ('portion_id', 'name', 'benefits', 'elements')}
            charge.update(kind='demon_beast' if portion.get('demon_beast') else 'corrupted' if portion['corrupted'] else 'normal',
                          free_mantle=0, weak_elements=portion.get('weak_elements', []),
                          limited_elements=portion.get('limited_elements', []), venom_type=portion.get('venom_type', 'poison'))
            state['charges'].append(charge)
            actor['resources'][SAT] = actor['resources'].get(SAT, 0) + 1
            if not state['selected']:
                state['selected'] = charge['portion_id']
            if margin >= 5:
                state['pending'] = {'portion_id': charge['portion_id'], 'memories': portion.get('memories', [])}
        elif margin <= -5:
            actor['resources'][IMP] = actor['resources'].get(IMP, 0) + 1
        session.emit('MEAL_REFINED', aid, source=REFINE, portion_id=portion['portion_id'], cp_cost=1 + steady,
            dc=dc, roll=roll.model_dump(mode='json'), margin=margin, satiety_gained=int(margin >= 0), impurity_gained=int(margin <= -5),
            text=f"Refine the Meal consumes {portion['name']}: Hunger Check {roll.total} against DC {dc}; "
                 + ('gain 1 source-linked Satiety.' if margin >= 0 else 'no Satiety gained.'))
    else:
        require(set(payload) == {'reward'} and payload['reward'] in REWARDS and state.get('pending'), 'Choose one pending Refine the Meal benefit.')
        pending, reward = state['pending'], payload['reward']
        if reward == 'cleanse':
            actor['resources'][IMP] = max(0, actor['resources'].get(IMP, 0) - 1)
        elif reward == 'temporary_hp':
            state['temporary_hp'] = max(state['temporary_hp'], config['pb'])
        elif reward == 'free_mantle':
            next(c for c in state['charges'] if c['portion_id'] == pending['portion_id'])['free_mantle'] = 1
        else:
            require(pending['memories'], 'The GM has not supplied a harmless sensory memory; it remains unknown. Choose another benefit or request a source ruling.')
            state['memories'].append(pending['memories'][0])
        del state['pending']
        session.emit('REFINE_BENEFIT', aid, reward=reward, text='Refine the Meal: your chosen additional benefit is recorded.')
    # _sync reads the same committed working copy, never an unrecorded receipt.
    actor['travel_uses'][KEY] = state
    _sync(session, aid)
    if kind == 'refine_meal' and state.get('pending') and actor['control_mode'] == 'LOCAL_AUTO':
        meal_command(session, aid, 'refine_reward', {'reward': 'free_mantle'})
    return True


@hook('journey_rest')
def clear_meals(session, aid):
    if not _owned(session, aid):
        return
    state = _state(session, aid)
    state.update(charges=[], selected='', temporary_hp=0)
    state.pop('pending', None)
    session.state['actors'][aid]['travel_uses'][KEY] = state
    session.state['actors'][aid]['resources'][SAT] = 0
    _sync(session, aid)


@hook('journey_state_changed')
def guard_pending_meal(session, aid):
    if _owned(session, aid) and session.state['phase'] == 'combat':
        from ..journey import require
        require(not _state(session, aid).get('pending'), 'Choose the pending Refine the Meal additional benefit before entering combat.')
    elif _owned(session, aid):
        _sync(session, aid)


@hook('journey_encounter_prepare')
def prepare_encounter_meals(session, aid):
    if not _owned(session, aid):
        return
    from ..journey import require
    require(not _state(session, aid).get('pending'), 'Choose the pending Refine the Meal additional benefit before entering combat.')
    _sync(session, aid)


@hook('match_initialize')
@hook('activity_initialize')
def initialize_meals(engine):
    for bundle in engine.typed_bundle_documents:
        receipt = bundle.get('hunger_meal_receipt')
        actor = engine.state.actors.get(bundle['actor_id'])
        if not receipt or actor is None:
            continue
        engine._apply_condition(actor, LEDGER, REFINE, actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'receipt': json.dumps(receipt, sort_keys=True), 'label': 'Stored spiritual nourishment for Digestive Mantle'})
        if receipt['temporary_hp']:
            engine._grant_temp_hp(actor, receipt['temporary_hp'], REFINE, actor.entity_id)


@hook('journey_native_activity')
def meal_activity(session):
    return True if any(_owned(session, aid) for aid in session.state['actors']) else None


def ledger(actor):
    """Public source receipt reader for Mantle; absent receipt means unknown."""
    held = next((c for c in actor.conditions.values() if c.condition_id == LEDGER), None)
    return (held, json.loads(held.data['receipt'])) if held else (None, None)


def selected_source(actor):
    """Public pure query used by Mantle eligibility, costs and source choices."""
    _, data = ledger(actor)
    if data is None:
        return None
    return next((c for c in data['charges'] if c['portion_id'] == data['selected']), None)


def available_benefits(actor):
    """Public pure union for paid Mantle benefits, used by hunger_riders.

    None preserves the complete legacy menu when any pooled source is unknown.
    A fully recorded pool offers every benefit supported by any remaining meal.
    """
    _, data = ledger(actor)
    if data is None or actor.resources.get(SAT, 0) > len(data['charges']):
        return None
    return [b for b in BENEFITS if any(b in c['benefits'] for c in data['charges'])]


@contextmanager
def satiety_benefit_scope(engine, actor, benefit):
    """Public payment scope for hunger_riders' extra-benefit purchase.

    The generic debit observer asks only for meals that support that benefit.
    Yields a list populated with actually spent source-kind strings, or None
    for an unknown pooled source, so callers never guess meal purity. This
    transient selection context never enters saved state and nests safely.
    """
    spent = []
    token = _SPEND_BENEFIT.set((engine, actor.entity_id, benefit, spent))
    try:
        yield spent
    finally:
        _SPEND_BENEFIT.reset(token)


def consume_source(ctx):
    """Acknowledge this activation's actual native Satiety debit, once."""
    held, data = ledger(ctx.actor)
    source = activation_source(ctx)
    if source is None:
        return None
    data.pop('activation', None)
    held.data['receipt'] = json.dumps(data, sort_keys=True)
    record_instance_update(ctx.engine, ctx.actor, 'condition', held.instance_id, held)
    return source


def activation_source(ctx):
    """Public paid source query for hunger_riders, bound to one native intent.

    Unlike selected_source's pure future-cost quote, this reads the charge that
    has actually been debited. An interrupted activation cannot preserve its
    source or discount for another intent.
    """
    _, data = ledger(ctx.actor)
    paid = (data or {}).get('activation') or {}
    intent_id = getattr(ctx.intent, 'intent_id', '')
    if paid.get('intent_id') == intent_id and paid.get('action_id') == ctx.action.source_definition_id:
        return paid.get('source')
    return None


@hook('candidate_allowed')
def meal_candidate(engine, actor, candidate, action):
    if action is None:
        return None
    typed = action.parameters.get('typed') or {}
    held, data = ledger(actor)
    if typed.get('source') == MANTLE + ':select_meal':
        return data is not None and len(data['charges']) + int(actor.resources.get(SAT, 0) > len(data['charges'])) > 1
    if (typed.get('option_of') or typed.get('source')) != MANTLE or data is None:
        return None
    source = selected_source(actor)
    if source is None:
        return None if actor.resources.get(SAT, 0) > len(data['charges']) else False
    if 'Demon-Beast Course' in action.display_name:
        return source['kind'] == 'demon_beast' and len(source['benefits']) >= 2
    return any(b in action.display_name for b in source['benefits'])


@effect('hunger_select_meal', harmful=False)
def select_meal(ctx, spec):
    held, data = ledger(ctx.actor)
    if data is None:
        return
    choices = [c['portion_id'] for c in data['charges']]
    labels = {c['portion_id']: c['name'] + (' — next Mantle costs 0 cultivation points' if c['free_mantle'] else ' — next Mantle costs 1 cultivation point') for c in data['charges']}
    if ctx.actor.resources.get(SAT, 0) > len(data['charges']):
        choices.append('unrecorded')
        labels['unrecorded'] = 'Previously stored Satiety — source not recorded; no refinement discount'
    if not choices:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'HUNGER_MEAL_SELECTION', ctx.actor.entity_id),
        ctx.actor, CHOICE + 'hunger_meal_selection', choices,
        labels=labels,
        name='Digestive Mantle', feature_id=MANTLE, target_id=ctx.actor.entity_id,
        prompt=f'Digestive Mantle: choose the stored meal {ctx.actor.display_name} will consume on their next activation. No cost for this selection.')
    if picked:
        data['selected'] = '' if picked[0] == 'unrecorded' else picked[0]
        held.data['receipt'] = json.dumps(data, sort_keys=True)
        record_instance_update(ctx.engine, ctx.actor, 'condition', held.instance_id, held)


@hook('technique_cost_discount')
def refined_discount(engine, actor, source_id, totals):
    action = engine.action_catalog.get(source_id)
    typed = action.parameters.get('typed', {}) if action else {}
    source = selected_source(actor)
    if (typed.get('option_of') or typed.get('source')) != MANTLE or not source or not source['free_mantle']:
        return None
    # Native action costs already resolved the paying Path pool (including
    # Spirit Awakening's Resonance); never guess it from the ingredient.
    cp_pools = {pool for pool, _ in action.costs
                if pool.startswith('resource:core.') and pool != 'resource:core.martial_focus'}
    return {key: value for key, value in totals.items() if key in cp_pools}


@hook('event')
def other_satiety_spent(engine, event_type, kwargs):
    """Keep owned receipts consistent when another native action burns Satiety.

    This is source-ledger accounting, not another ability implementation. The
    payer still owns legality, amounts and effects. Every known charge remains
    selectable; spending an unknown pooled charge never invents its source.
    Mantle's own debit is bound to its native intent here; consume_source later
    acknowledges the paid receipt, without spending a second charge.
    """
    payload = kwargs.get('payload') or {}
    if event_type != 'RESOURCE_SPENT' or payload.get('resource_id') != SAT:
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None:
        return
    action = engine.action_catalog.get(kwargs.get('source_definition_id'))
    typed = action.parameters.get('typed', {}) if action else {}
    held, data = ledger(actor)
    if data is None:
        return
    count = int(payload.get('amount') or 0)
    if count <= 0:
        return
    if (typed.get('option_of') or typed.get('source') or kwargs.get('source_definition_id')) == MANTLE:
        source = selected_source(actor)
        data.pop('activation', None)
        if source is not None:
            data['charges'] = [c for c in data['charges'] if c['portion_id'] != source['portion_id']]
            data['selected'] = data['charges'][0]['portion_id'] if data['charges'] else ''
            data['activation'] = {'source': source,
                'intent_id': getattr(getattr(engine, '_active_intent', None), 'intent_id', ''),
                'action_id': kwargs.get('source_definition_id') or ''}
        held.data['receipt'] = json.dumps(data, sort_keys=True)
        record_instance_update(engine, actor, 'condition', held.instance_id, held)
        return
    if not data['charges']:
        return
    requirement = _SPEND_BENEFIT.get()
    benefit = requirement[2] if requirement and requirement[:2] == (engine, actor.entity_id) else None
    for index in range(count):
        if not data['charges']:
            break
        options = [c['portion_id'] for c in data['charges'] if benefit is None or benefit in c['benefits']]
        labels = {c['portion_id']: c['name'] for c in data['charges'] if c['portion_id'] in options}
        unknown = actor.resources.get(SAT, 0) + count - index > len(data['charges'])
        if unknown:
            options.append('unrecorded')
            labels['unrecorded'] = 'Previously stored Satiety — source not recorded'
        if not options:
            raise ValueError('No remaining source supports the selected Mantle benefit; no Satiety was committed.')
        picked = ask(engine, None, checkpoint_id(engine, 'HUNGER_OTHER_SATIETY_' + str(index), actor.entity_id),
            actor, CHOICE + 'hunger_other_satiety', options, labels=labels,
            name='Stored Satiety', feature_id=REFINE, target_id=actor.entity_id,
            prompt=f"{actor.display_name}: {action.display_name if action else 'this action'} consumes Satiety. Choose meal {index + 1} of {count}; this spends its source-linked charge and any unused refinement discount.")
        if picked and picked[0] != 'unrecorded':
            if benefit is not None:
                requirement[3].append(next(c['kind'] for c in data['charges'] if c['portion_id'] == picked[0]))
            data['charges'] = [c for c in data['charges'] if c['portion_id'] != picked[0]]
            if data['selected'] == picked[0]:
                data['selected'] = data['charges'][0]['portion_id'] if data['charges'] else ''
        elif picked and benefit is not None:
            requirement[3].append(None)
    held.data['receipt'] = json.dumps(data, sort_keys=True)
    record_instance_update(engine, actor, 'condition', held.instance_id, held)


@effect('hunger_record_penalty', harmful=False)
def record_penalty(ctx, spec):
    raise ValueError('Record an actual nonmagical penalty through the native table-owner source input; actors cannot classify GM conditions.')


def end_nourishment_penalty(ctx):
    """End one actual penalty admitted through the native table-owner path."""
    from .source_penalties import penalties
    options = {condition.instance_id: condition for condition in penalties(ctx.actor)}
    if not options:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'DEEP_NOURISHMENT_PENALTY', ctx.actor.entity_id),
        ctx.actor, CHOICE + 'deep_nourishment_penalty', list(options),
        labels={key: _condition_label(ctx.engine, c) for key, c in options.items()},
        name='Digestive Mantle: Deep Nourishment', feature_id=MANTLE, target_id=ctx.actor.entity_id,
        prompt=f'Digestive Mantle: Deep Nourishment ends one recorded nonmagical hunger, thirst, forced-march or travel-fatigue penalty on {ctx.actor.display_name}. Choose one; Exhaustion cannot be removed.')
    if picked:
        from .end_effect import remove_instance
        held = options[picked[0]]
        remove_instance(ctx, ctx.actor, 'condition', held.instance_id, held)
