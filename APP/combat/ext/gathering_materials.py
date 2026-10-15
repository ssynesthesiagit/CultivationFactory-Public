"""Clean Harvest and source-bound Harvest Lots, using material_ledger.

The source's Harvest DC, available portions, tools, signs and hazards are typed
GM facts. A Gathering check is a deterministic committed roll, followed by a
separate player-owned outcome choice. Retrying choices never rerolls. Physical
packaging and magical preservation are distinct; this module does not grant
Seal the Essence or other unowned talents.
"""
from copy import deepcopy
from itertools import combinations
from . import hook
from . import material_ledger as ledger
from ..journey import require, integer

CLEAN = 'HARVESTING_GATHERING_BASE_CLEAN_HARVEST'
LOTS = 'HARVESTING_GATHERING_BASE_HARVEST_LOTS_AND_LOT_QUALITY'
BENEFITS = ('extra', 'pure', 'preserve', 'fact', 'avoid_hazard')


def validate_source(row, session):
    required = {'dc', 'perfect', 'methods', 'facts', 'hazards', 'harm', 'ripeness', 'failure_outcome'}
    require(isinstance(row, dict) and set(row) == required, 'A harvest source needs DC, capacity for Perfect material, methods, signs, hazards, harm and ripeness.')
    require(integer(row['dc'], 1) and type(row['perfect']) is int and row['perfect'] in (0, 1), 'Record a positive Harvest DC and a 0/1 Perfect-material capability.')
    require(row['ripeness'] in ('ripe', 'immature', 'overripe', 'awakened'), 'Record the material’s actual ripeness.')
    require(isinstance(row['methods'], list) and row['methods'] and all(isinstance(m, str) and m for m in row['methods']),
            'Record appropriate tool materials or specifically justified improvised methods.')
    require(isinstance(row['facts'], list) and all(isinstance(f, dict) and set(f) == {'kind', 'text'}
            and f['kind'] in ('materials','rarity','state','method','survival','compatibility','danger')
            and isinstance(f['text'], str) and f['text'].strip() for f in row['facts']),
            'Record typed actual Read the Sign facts; unknown facts remain absent.')
    require(row['failure_outcome'] in ('unknown','bruised','immediate_seal'),
            'Record the established failure-by-five alternative, or leave it unknown for a GM ruling.')
    require(type(row['harm']) is int and row['harm'] in (0, 1), 'Record whether ordinary harvest harms this source.')
    require(isinstance(row['hazards'], list), 'Record actual source hazards, or an empty list.')
    for h in row['hazards']:
        require(isinstance(h, dict) and set(h) == {'id', 'name', 'minor', 'consequence', 'amount', 'trigger'}, 'Record typed source hazard consequences.')
        ledger.identity(h['id']); ledger.text(h['name'], 'the hazard name')
        require(type(h['minor']) is int and h['minor'] in (0, 1) and h['consequence'] in ('damage', 'exhaustion', 'tool_break', 'attention', 'source_destroy')
                and integer(h['amount'], 1) and h['trigger'] in ('on_harvest', 'on_failure', 'natural_one'), 'Use a supported hazard with a positive, source-established magnitude.')
    require(len({h['id'] for h in row['hazards']}) == len(row['hazards']), 'Hazard identities must be unique.')
    return deepcopy(row)


def learning(session, aid):
    return session.state['actors'][aid].get('gathering_learning')


def bonus(session, aid):
    choice = learning(session, aid)
    require(choice is not None, 'Choose Wisdom or Intelligence as your Gathering key ability first.')
    n = ledger.numbers(session, aid)
    return n['pb'] + n['ability_mods'][choice]


def available_benefits(source):
    out = ['pure', 'preserve']
    if source['remaining'] > 0:
        out.append('extra')
    if source['harvest']['facts']:
        out.append('fact')
    if any(h['minor'] for h in source['harvest']['hazards']):
        out.append('avoid_hazard')
    return out


def outcome_choices(pending, source):
    natural, margin = pending['natural'], pending['margin']
    if natural == 1 or margin < -5:
        return ['lost']
    if margin < 0:
        outcome = pending.get('failure_outcome', source['harvest']['failure_outcome'])
        return [outcome] if outcome != 'unknown' else []
    choices = ['normal']
    benefits = available_benefits(source)
    if margin >= 5:
        choices += benefits
    if margin >= 10:
        if source['harvest']['perfect']:
            choices.append('perfect')
        choices += ['+'.join(sorted(c)) for c in combinations(benefits, 2)]
    return choices


def pending(session, aid):
    return session.state['actors'][aid].get('material_preparation', {}).get('harvest')


def trigger_hazard(session, aid, source, hazard, tool):
    actor = session.state['actors'][aid]
    consequence, amount = hazard['consequence'], hazard['amount']
    if consequence == 'tool_break':
        ledger.consume(session, aid, tool, 1)
    elif consequence == 'source_destroy':
        source['remaining'] = 0
    elif consequence == 'exhaustion':
        from .forged_exhaustion import MAX_LEVEL
        require(actor['exhaustion'] + amount < MAX_LEVEL,
                'Resolve this source’s lethal exhaustion hazard in combat before harvesting.')
        actor['exhaustion'] += amount
    elif consequence == 'damage':
        snapshot = actor.get('encounter_snapshot')
        maximum = actor['bundle']['actor_template']['maximum_hp']
        if snapshot is None:
            snapshot = {'current_hp': maximum, 'maximum_hp': maximum, 'temporary_hp': 0,
                        'active': 1, 'life_state': '', 'conditions': {}}
            actor['encounter_snapshot'] = snapshot
        require(snapshot['current_hp'] + snapshot['temporary_hp'] > amount,
                'Resolve this source’s potentially lethal damage in combat before harvesting.')
        absorbed = min(snapshot['temporary_hp'], amount)
        snapshot['temporary_hp'] -= absorbed
        snapshot['current_hp'] -= amount - absorbed
    else:
        actor.setdefault('material_preparation', {}).setdefault('attention', []).append(
            {'source_id': source['id'], 'hazard_id': hazard['id'], 'name': hazard['name'], 'amount': amount})
    ledger.record(session, aid, 'HARVEST_HAZARD', source_id=source['id'], hazard=hazard['id'],
                  consequence=consequence, amount=amount)


@hook('journey_admission')
def failure_ruling(session, aid, kind, payload, reason):
    if kind != 'harvest_failure': return None
    p = pending(session,aid)
    require(p is not None and -5 <= p['margin'] < 0 and p['natural'] != 1,
            'Only the actual committed near-failure can receive this ruling.')
    require(set(payload) == {'serial','outcome'} and payload['serial'] == p['serial']
            and payload['outcome'] in ('bruised','immediate_seal'), 'Choose one printed alternative for this exact failed harvest.')
    require(p.get('failure_outcome', ledger.sources(session)[p['source']]['harvest']['failure_outcome']) == 'unknown',
            'This harvest already has its recorded failure alternative.')
    p['failure_outcome'] = payload['outcome']
    ledger.record(session,aid,'HARVEST_FAILURE_RULED',serial=p['serial'],outcome=payload['outcome'],reason=reason)
    return True


@hook('journey_command')
def command(session, aid, kind, payload):
    if kind not in ('gathering_key', 'harvest_begin', 'harvest_finish'):
        return None
    require(ledger.owned(session, aid, CLEAN), 'This creature has not learned Clean Harvest.')
    actor = session.state['actors'][aid]
    require(not actor['incapacitated'], 'An incapacitated creature cannot harvest.')
    if kind == 'gathering_key':
        require(set(payload) == {'ability'} and payload['ability'] in ('WIS', 'INT') and not learning(session, aid),
                'Choose Wisdom or Intelligence once when learning Gathering.')
        actor['gathering_learning'] = payload['ability']
        ledger.record(session, aid, 'HARVEST_KEY_CHOSEN', ability=payload['ability'])
        return True
    if kind == 'harvest_begin':
        require(set(payload) == {'source', 'tool', 'container'} and not pending(session, aid), 'Choose a source, recorded method and packaging; finish any pending harvest first.')
        source = ledger.sources(session).get(payload['source'])
        require(source is not None and aid in source['known_to'] and 'harvest' in source
                and source['remaining'] > 0 and (not source['exclusive_to'] or source['exclusive_to'] == aid),
                'Choose a known, accessible source that still has material.')
        tool = ledger.holdings(session, aid).get(payload['tool'])
        container = ledger.holdings(session, aid).get(payload['container'])
        require(tool is not None and tool['quantity'] > 0 and tool['kind'] == 'harvest_tool'
                and ledger.sources(session)[tool['source_id']]['material'] in source['harvest']['methods'],
                'Use appropriate tools or a specifically admitted improvised method.')
        require(container is not None and container['quantity'] > 0 and container['kind'] == 'container', 'A usable Lot needs actual packaging.')
        require(source['harvest']['ripeness'] != 'awakened', 'Resolve the awakened source’s negotiation, combat or permission before recording it as harvestable.')
        from ..gate2_rolls import DeterministicRollAuthority
        roller = DeterministicRollAuthority(session.state['journey_id'] + ':harvest')
        roller.counter = actor.get('material_preparation', {}).get('roll_counter', 0)
        roll = roller.d20(modifier=bonus(session, aid), actor_id=aid, reason='CHECK:Gathering')
        preparation = actor.setdefault('material_preparation', {})
        preparation['roll_counter'] = roller.counter
        source['remaining'] -= 1  # reserve/consume the attempt once, including failures
        dc = source['harvest']['dc'] + (2 if source['harvest']['ripeness'] == 'overripe' else 0)
        preparation['harvest'] = {'source': source['id'], 'tool': payload['tool'], 'container': payload['container'],
                                  'natural': roll.natural_result, 'total': roll.total, 'margin': roll.total - dc,
                                  'serial': source['quantity'] - source['remaining']}
        session.tick(600)
        ledger.record(session, aid, 'HARVEST_CHECK', source_id=source['id'], roll=roll.model_dump(mode='json'), dc=dc)
        if roll.natural_result == 1 or roll.total - dc < -5:
            settle_loss(session, aid)
        return True
    p = pending(session, aid)
    require(p is not None and {'choice', 'product'} <= set(payload) <= {'choice', 'product', 'hazard', 'fact'}, 'Finish the committed harvest and choose a Lot or specific ingredient.')
    source = ledger.sources(session)[p['source']]
    require(isinstance(payload['choice'], str) and '+'.join(sorted(payload['choice'].split('+'))) in outcome_choices(p, source) and payload['product'] in ('lot', 'ingredient'), 'Choose a legal result of the committed Gathering check.')
    choice = payload['choice']; benefits = choice.split('+')
    hazard_avoided = ''
    if 'avoid_hazard' in benefits:
        hazard_avoided = payload.get('hazard')
        require(any(h['id'] == hazard_avoided and h['minor'] for h in source['harvest']['hazards']), 'Choose one actual minor harvest hazard to avoid.')
    if 'fact' in benefits:
        fact = payload.get('fact')
        require(type(fact) is int and 0 <= fact < len(source['harvest']['facts']), 'Choose one actual Read the Sign fact.')
        ledger.record(session, aid, 'HARVEST_FACT', source_id=source['id'], fact=source['harvest']['facts'][fact]['text'])
    if choice != 'lost':
        count = 2 if 'extra' in benefits else 1
        if count == 2:
            require(source['remaining'] > 0, 'The source no longer contains an extra portion.')
            source['remaining'] -= 1
        ledger.consume(session, aid, p['container'], 1)
        quality = ('Bruised' if choice in ('bruised', 'immediate_seal') else 'Perfect' if choice == 'perfect' else 'Pure' if 'pure' in benefits else 'Normal')
        if source['harvest']['ripeness'] == 'immature':
            quality = 'Bruised'
        if source['harvest']['ripeness'] == 'overripe' and p['margin'] >= 5:
            quality = 'Pure'
        key = f"{source['id']}:harvest:{p['serial']}"
        ledger.holdings(session, aid)[key] = {'id': key, 'source_id': source['id'], 'name': source['name'],
            'kind': 'harvest_lot' if payload['product'] == 'lot' else 'ingredient', 'unit': 'Lot' if payload['product'] == 'lot' else source['unit'],
            'quantity': count, 'quality': quality, 'packaged': 1, 'sealed_essence': 0,
            'spoils_after_rest': actor['long_rests'] + 1 if quality == 'Bruised' else -1,
            'provenance': source['provenance'], 'acquired_at': session.state['seconds']}
        ledger.record(session, aid, 'HARVEST_LOTS_CREATED', holding=key, quantity=count, quality=quality, source_id=source['id'])
    if source['harvest']['harm'] and 'preserve' not in benefits:
        source['harmed'] = 1
        ledger.record(session, aid, 'HARVEST_SOURCE_HARMED', source_id=source['id'])
    for h in source['harvest']['hazards']:
        if h['id'] != hazard_avoided and (h['trigger'] == 'on_harvest'
                or (p['margin'] < 0 and (h['trigger'] == 'on_failure' or source['harvest']['ripeness'] == 'overripe'))):
            trigger_hazard(session, aid, source, h, p['tool'])
    del actor['material_preparation']['harvest']
    return True


@hook('journey_options')
def options(session, aid):
    if not ledger.owned(session, aid, CLEAN) or session.state['phase'] != 'travel' or session.state['actors'][aid]['incapacitated']:
        return None
    if not learning(session, aid):
        return [{'id': 'gathering-key:' + key, 'kind': 'gathering_key', 'payload': {'ability': key},
                 'label': 'Choose ' + name + ' as your Gathering key ability.'} for key, name in [('WIS', 'Wisdom'), ('INT', 'Intelligence')]]
    p = pending(session, aid)
    if p:
        source = ledger.sources(session)[p['source']]
        rows = []
        for choice in outcome_choices(p, source):
            facts = range(len(source['harvest']['facts'])) if 'fact' in choice.split('+') else [None]
            hazards = [h['id'] for h in source['harvest']['hazards'] if h['minor']] if 'avoid_hazard' in choice.split('+') else [None]
            for product in ('lot', 'ingredient'):
                for fact in facts:
                    for hazard in hazards:
                        payload = {'choice': choice, 'product': product, **({'fact': fact} if fact is not None else {}), **({'hazard': hazard} if hazard else {})}
                        rows.append({'id': f'harvest-result:{choice}:{product}:{fact}:{hazard}', 'kind': 'harvest_finish', 'payload': payload,
                                     'label': f"Clean Harvest: choose {choice.replace('_', ' ')} for {source['name']} as {product}; the committed total is {p['total']}."})
        return rows
    rows = []
    inventory = ledger.holdings(session, aid)
    for sid, source in ledger.sources(session).items():
        if aid not in source['known_to'] or source['remaining'] <= 0 or 'harvest' not in source or (source['exclusive_to'] and source['exclusive_to'] != aid):
            continue
        for tid, tool in inventory.items():
            if tool['kind'] != 'harvest_tool' or tool['quantity'] <= 0 or ledger.sources(session)[tool['source_id']]['material'] not in source['harvest']['methods']:
                continue
            for cid, container in inventory.items():
                if container['kind'] == 'container' and container['quantity'] > 0:
                    rows.append({'id': f'harvest:{sid}:{tid}:{cid}', 'kind': 'harvest_begin',
                                 'payload': {'source': sid, 'tool': tid, 'container': cid},
                                 'label': f"Clean Harvest: work {source['name']} for 10 minutes with {tool['name']} and {container['name']}; roll a Gathering check."})
    return rows


@hook('journey_rest')
def spoil(session, aid):
    if 'material_holdings' not in session.state['actors'][aid]:
        return None
    for row in ledger.holdings(session, aid).values():
        if row.get('spoils_after_rest', -1) == session.state['actors'][aid]['long_rests'] and row['quantity']:
            row['quantity'] = 0
            ledger.record(session, aid, 'MATERIAL_SPOILED', holding=row['id'], source_id=row['source_id'])


def settle_loss(session, aid):
    actor = session.state['actors'][aid]
    p = pending(session, aid)
    source = ledger.sources(session)[p['source']]
    ledger.record(session, aid, 'HARVEST_PORTION_LOST', source_id=source['id'], natural=p['natural'], total=p['total'])
    hazards = source['harvest']['hazards']
    if p['natural'] == 1:
        hazards = hazards[:1]
    else:
        hazards = [h for h in hazards if h['trigger'] in ('on_harvest', 'on_failure') or source['harvest']['ripeness'] == 'overripe']
    for hazard in hazards:
        trigger_hazard(session, aid, source, hazard, p['tool'])
    if source['harvest']['harm']:
        source['harmed'] = 1
        ledger.record(session, aid, 'HARVEST_SOURCE_HARMED', source_id=source['id'])
    del actor['material_preparation']['harvest']


@hook('journey_command_gate')
def finish_choice_first(session, aid, kind, payload):
    waiting = [who for who in session.state['actors'] if pending(session, who)]
    if waiting:
        return kind == 'harvest_finish' and aid in waiting
    return None
