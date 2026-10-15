"""Real acquisition -> journey ritual -> table activation -> cold reducer replay.

Only sheet loading and dice are controlled. Source facts enter production owner
commands; no fixture injects Satiety receipts, eligibility metadata or conditions.
"""
import json
import zipfile
from functools import lru_cache
import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.tabletop import normalize_map, to_battlefield
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate3_reducer import canonical_state_document
from combat.ext.hunger_meals import REFINE, MANTLE, KEY, LEDGER, SAT, IMP
from tests.h1_support import ROOT, sheet

OWNER_PROJECT, OTHER_PROJECT = ('feed0000-0000-4000-8000-000000000001', 'feed0000-0000-4000-8000-000000000002')
A, B = [FACTORY_ACTOR_PREFIX + x for x in (OWNER_PROJECT, OTHER_PROJECT)]
CP = 'resource:core.qi'


@lru_cache(maxsize=1)
def native_catalog():
    from canonical_catalog.service import CanonicalCatalogAuthorityService
    return CanonicalCatalogAuthorityService(ROOT)


def game(tmp_path, monkeypatch, *, natural=20, mode='MANUAL', positions=None, primary='Qi', talents=()):
    assert json.loads((ROOT / 'combat/rules/feature_blocks.d/hunger.json').read_text())['features'], 'Native Hunger test pack lacks its runtime feature registration data.'
    for pid in (OWNER_PROJECT, OTHER_PROJECT):
        # The one existing Maw compatibility probe remains a legacy-sheet
        # guard; it does not certify acquisition. Every assigned-row case
        # starts without Hunger and learns its Sphere through the public API.
        doc = sheet([MANTLE,*talents] if talents and pid == OWNER_PROJECT else [],
                    cl=10, name='Meal owner' if pid == OWNER_PROJECT else 'Meal other', primary=primary, key='WIS' if primary == 'Resonance' else 'INT')
        path = 'tianxia.path.spirit_awakening' if primary == 'Resonance' else 'tianxia.path.qi_cultivation'
        doc['identity'].update(path_ids=[path], path='Spirit Awakening' if primary == 'Resonance' else 'Qi Cultivation')
        doc.setdefault('path_and_subpath', {}).update(path_record_id=path, path_record_ids=[path])
        if talents and pid == OWNER_PROJECT:
            doc['spheres_and_talents']['learned_talent_record_ids'] = list(talents)
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    if not talents:
        service = CombatService(ROOT, tmp_path)
        table = TabletopService(service, tmp_path)
        table.canonical_catalog = native_catalog()
        acquired = table.add_advancement(OWNER_PROJECT, 'sphere', 'tianxia.sphere.hunger')
        assert any(row['id'] == 'tianxia.sphere.hunger' and not row['gm'] for row in acquired['added']['spheres'])
        loaded = CombatService(ROOT, tmp_path)._factory_owner_sheet(OWNER_PROJECT)['spheres_and_talents']
        assert {REFINE, MANTLE} <= set(loaded['automatic_sphere_component_record_ids'])
        assert not {REFINE, MANTLE} & set(loaded['learned_talent_record_ids'])
    arena = to_battlefield(normalize_map({'display_name': 'Meal yard', 'width_squares': 20,
        'height_squares': 6, 'walls': []}))
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kw: {'scene': arena})
    original = DeterministicRollAuthority.d20
    values = list(natural) if isinstance(natural, list) else None
    def controlled(self, **kw):
        roll = original(self, **kw)
        if kw['reason'] == 'CHECK:' + REFINE:
            value = values.pop(0) if values else natural
            return roll.model_copy(update={'dice': (value,), 'natural_result': value, 'total': value + kw['modifier']})
        if kw['reason'].startswith('ATTACK:'):
            return roll.model_copy(update={'dice': (15,), 'natural_result': 15, 'total': 15 + kw['modifier']})
        return roll
    monkeypatch.setattr(DeterministicRollAuthority, 'd20', controlled)
    cold = lambda: CombatService(ROOT, tmp_path)
    state = cold().create_journey(project_ids=[OWNER_PROJECT, OTHER_PROJECT], arena_id='scene',
        positions=positions or {A: {'x': 1, 'y': 1}, B: {'x': 2, 'y': 1}}, base_paces={A: 30, B: 30}, control_modes={A: mode})
    jid = state['journey_id']
    def command(kind, payload=None, aid=A):
        service = cold()
        revision = service.journey_state(jid)['revision']
        if kind in ('record_essence_portion', 'supply_refine_memory'):
            result = service.journey_world_fact(jid, revision, {
                'source':REFINE,'subject':aid,'kind':'essence_portion' if kind == 'record_essence_portion' else 'refine_sensory_memory',
                'scope':payload['portion_id'] if kind == 'record_essence_portion' else 'pending-memory:' +
                    service.journey_state(jid)['actors'][aid]['travel_uses'][KEY]['pending']['portion_id'],
                'value':payload,'expires_at':int(service.journeys.load(jid).clock())+86400,'readers':[]})
        else:
            result = service.journey_act(jid, revision, aid, kind, payload)
        assert cold().journey_state(jid) == result
        return result
    return cold, jid, command


def portion(pid='portion-1', **extra):
    return {'portion_id': pid, 'name': 'GM-recorded spirit ration', 'grade': 'common',
        'corrupted': 0, 'demon_beast': 0, 'source_realm': 2, 'meaningful': 1, 'benefits': ['Thick Hide'],
        'elements': [], 'ruling': 'One carried, meaningful, persistent spiritual ingredient portion.', **extra}


def refine(command, pid='portion-1', mode='TEN_MINUTE_REFINE', steady_cp=0):
    return command('refine_meal', {'portion_id': pid, 'mode': mode, 'steady_cp': steady_cp})


def start(cold, jid):
    mid = cold().journey_start_combat(jid, cold().journey_state(jid)['revision'], {A: 'team:a', B: 'team:b'})['match_id']
    service = cold()
    table = TabletopService(service, service.userdata_root)
    for _ in range(4):
        state = table.state(mid)
        if state['menu']['actor_id'] == A:
            break
        result = table.act(mid, state['menu']['end_turn'], state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'])
        assert result['status'] == 'COMMITTED', result
    return service, table, mid


def engine(cold, mid):
    session = cold()._load_session(mid)
    assert session.mechanical.replay()['state'] == canonical_state_document(session.engine.state)
    return session.engine


def play(cold, table, mid, label, choices=(), target=None):
    state = table.state(mid)
    groups = state['menu']['actions']
    option = next((o for g in groups if g['label'] == label for o in g['options']
                   if target is None or o['target_ids'] == [target]), None)
    if option is None:
        candidate = next(c for c in cold()._load_session(mid).engine.legal_candidates()
                         if c.display_name == label and (target is None or c.target_ids == (target,)))
        option = {'candidate_id': candidate.candidate_id}
    answers = []
    pending = list(choices)
    for _ in range(10):
        state = table.state(mid)
        result = table.act(mid, option['candidate_id'], state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'], answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return engine(cold, mid)
        prompt = result['reaction']
        ids = [o['id'] for o in prompt['choice']['options']]
        wanted = pending.pop(0) if pending else ids[0]
        assert wanted in ids, (wanted, ids)
        answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': [wanted]})
    raise AssertionError('unresolved choices')


@pytest.mark.parametrize('grade,corrupted,realm,dc', [('common',0,2,12),('notable',0,2,15),
    ('mighty',0,2,18),('common',1,2,14),('common',0,3,14),('mighty',1,3,22)])
def test_native_dc_cost_consumption_and_source_link(tmp_path, monkeypatch, grade, corrupted, realm, dc):
    cold, jid, command = game(tmp_path, monkeypatch, natural=10)
    command('record_essence_portion', portion(grade=grade, corrupted=corrupted, source_realm=realm))
    state = refine(command)
    event = next(e for e in reversed(state['events']) if e['kind'] == 'MEAL_REFINED')
    assert event['dc'] == dc and event['roll']['modifier'] == 6 and event['roll']['total'] == 16
    assert state['seconds'] == 600 and state['actors'][A]['resources'][CP] == 29
    ledger = state['actors'][A]['travel_uses'][KEY]
    assert not ledger['portions']
    assert len(ledger['charges']) == int(16 >= dc)
    assert state['actors'][A]['resources'].get(IMP, 0) == int(16 <= dc - 5)
    if ledger['charges']:
        assert ledger['charges'][0]['portion_id'] == 'portion-1'
    with pytest.raises(ValueError):
        refine(command)
    assert cold().journey_state(jid) == state


@pytest.mark.parametrize('natural,success,impurity,pending', [(5,False,0,False),(1,False,1,False),
    (6,True,0,False),(11,True,0,True)])
def test_exact_margin_boundaries(tmp_path, monkeypatch, natural, success, impurity, pending):
    cold, jid, command = game(tmp_path, monkeypatch, natural=natural)
    command('record_essence_portion', portion())
    state = refine(command)
    actor = state['actors'][A]
    assert actor['resources'].get(SAT,0) == int(success)
    assert actor['resources'].get(IMP,0) == impurity
    assert bool(actor['travel_uses'][KEY].get('pending')) is pending
    if pending:
        menu = cold().journey_menu(jid, A)
        assert len([o for o in menu['options'] if o['kind'] == 'refine_reward']) == 4
        with pytest.raises(ValueError, match='pending'):
            start(cold, jid)


@pytest.mark.parametrize('reward', ['cleanse','temporary_hp','free_mantle','memory'])
def test_all_four_rewards_and_cold_table_transfer(tmp_path, monkeypatch, reward):
    cold, jid, command = game(tmp_path, monkeypatch, natural=[1,20] if reward == 'cleanse' else 20)
    # A real failed ritual first produces the Impurity which cleanse can remove.
    if reward == 'cleanse':
        command('record_essence_portion', portion('failed', grade='mighty', corrupted=1, source_realm=3))
        state = refine(command, 'failed')
        assert state['actors'][A]['resources'][IMP] == 1
    command('record_essence_portion', portion(memories=['winter snow tasted of cedar']))
    state = refine(command, steady_cp=2, mode='SHORT_REST_REFINE')
    assert state['seconds'] == 3600 + 600 * int(reward == 'cleanse')
    expected_cp = 27 - int(reward == 'cleanse')
    assert state['actors'][A]['resources'][CP] == expected_cp
    command('refine_reward', {'reward': reward})
    if reward == 'cleanse':
        assert cold().journey_state(jid)['actors'][A]['resources'][IMP] == 0
    if reward == 'memory':
        assert cold().journey_state(jid)['actors'][A]['travel_uses'][KEY]['memories'] == ['winter snow tasted of cedar']
    service, table, mid = start(cold, jid)
    before = engine(cold, mid).state.actors[A]
    assert before.temporary_hp == (4 if reward == 'temporary_hp' else 0)
    assert 'winter snow tasted of cedar' not in json.dumps(canonical_state_document(engine(cold, mid).state))
    after = play(cold, table, mid, 'Digestive Mantle: Thick Hide').state.actors[A]
    assert after.resources[CP] == expected_cp - int(reward != 'free_mantle')
    assert after.resources[SAT] == 0 and after.temporary_hp == 10
    assert not json.loads(next(c.data['receipt'] for c in after.conditions.values() if c.condition_id == LEDGER))['charges']
    held = next(c for c in after.conditions.values() if c.condition_id == 'condition:typed.digestive_mantle')
    assert held.data['meal_source']['portion_id'] == 'portion-1'
    assert held.expires_on != 'UNTIL_REMOVED'


def test_unknown_memory_stays_unknown_until_owner_supplies_it(tmp_path, monkeypatch):
    cold, jid, command = game(tmp_path, monkeypatch)
    command('record_essence_portion', portion())
    before = refine(command)
    with pytest.raises(ValueError, match='not supplied'):
        command('refine_reward', {'reward':'memory'})
    assert cold().journey_state(jid) == before
    command('supply_refine_memory', {'memory':'smell of autumn leaves', 'ruling':'GM harmless sensory echo from the ingredient'})
    after = command('refine_reward', {'reward':'memory'})
    assert after['actors'][A]['travel_uses'][KEY]['memories'] == ['smell of autumn leaves']


def test_wrong_owner_and_fact_boundaries_are_atomic(tmp_path, monkeypatch):
    cold, jid, command = game(tmp_path, monkeypatch)
    before = cold().journey_state(jid)
    for payload, aid in [(portion(), B), (portion(meaningful=0), A),
        (portion(elements=['psychic']), A), (portion(benefits=['Elemental Gut']), A),
        (portion(source_realm=4), A)]:
        with pytest.raises(ValueError):
            command('record_essence_portion', payload, aid)
        assert cold().journey_state(jid) == before
    command('record_essence_portion', portion())
    before = cold().journey_state(jid)
    for steady in (-1, 5, True):
        with pytest.raises(ValueError):
            refine(command, steady_cp=steady)
        assert cold().journey_state(jid) == before
    with pytest.raises(ValueError, match='already'):
        command('record_essence_portion', portion())


def test_unmodeled_realm_relationship_requires_actual_owner_ruling(tmp_path, monkeypatch):
    cold,jid,command=game(tmp_path,monkeypatch,natural=10)
    command('record_essence_portion',portion(source_realm=4,above_realm=1))
    state=refine(command)
    event=next(e for e in state['events'] if e['kind']=='MEAL_REFINED')
    assert event['dc']==14


@pytest.mark.parametrize('primary', ['Qi','Stamina','Resonance'])
def test_refinement_and_free_mantle_use_actual_path_cp_pool(tmp_path,monkeypatch,primary):
    cold,jid,command=game(tmp_path,monkeypatch,primary=primary)
    pool='resource:core.'+primary.lower()
    command('record_essence_portion',portion())
    state=refine(command)
    assert state['actors'][A]['resources'][pool]==29
    command('refine_reward',{'reward':'free_mantle'})
    _,table,mid=start(cold,jid)
    result=play(cold,table,mid,'Digestive Mantle: Thick Hide')
    assert result.state.actors[A].resources[pool]==29
    assert result.state.actors[A].resources[SAT]==0


def test_ai_cannot_invent_ingredients(tmp_path, monkeypatch):
    cold, jid, command = game(tmp_path, monkeypatch, mode='LOCAL_AUTO')
    before = cold().journey_state(jid)
    assert not any(o['kind'] in ('record_essence_portion','refine_meal') for o in cold().journey_menu(jid,A)['options'])
    with pytest.raises(ValueError, match='currently offered'):
        cold().journey_auto_step(jid, before['revision'], A, option_id='record_essence_portion:invented')
    assert cold().journey_state(jid) == before
    # The owner supplies a real source through the production GM command;
    # the automatic creature then chooses without inventing any other source.
    state = command('record_essence_portion', portion())
    option = next(o for o in cold().journey_menu(jid,A)['options'] if o['kind']=='refine_meal')
    state = cold().journey_auto_step(jid, state['revision'], A, option_id=option['id'])
    assert not state['actors'][A]['travel_uses'][KEY].get('pending')
    assert state['actors'][A]['travel_uses'][KEY]['charges'][0]['free_mantle'] == 1
    assert not state['actors'][A]['travel_uses'][KEY]['memories']


def test_long_rest_expires_sources_and_free_cp(tmp_path, monkeypatch):
    cold, jid, command = game(tmp_path, monkeypatch)
    command('record_essence_portion', portion())
    refine(command)
    command('refine_reward', {'reward': 'free_mantle'})
    state = command('long_rest')
    assert state['actors'][A]['resources'][SAT] == 0
    assert state['actors'][A]['travel_uses'][KEY]['charges'] == []
    _, table, mid = start(cold, jid)
    assert not any('Digestive Mantle:' in g['label'] and g['options'] for g in table.state(mid)['menu']['actions'])


def test_source_suitability_does_not_grant_other_benefits(tmp_path, monkeypatch):
    cold, jid, command = game(tmp_path, monkeypatch)
    command('record_essence_portion', portion())
    refine(command)
    command('refine_reward', {'reward': 'free_mantle'})
    _, table, mid = start(cold, jid)
    labels = [g['label'] for g in table.state(mid)['menu']['actions'] if g['options']]
    assert 'Digestive Mantle: Thick Hide' in labels
    assert 'Digestive Mantle: Furnace Belly' not in labels
    assert 'Digestive Mantle: Demon-Beast Course' not in labels
    assert not any('Refine the Meal' in a.display_name for a in engine(cold,mid).action_catalog.values())


def native_packets(monkeypatch):
    from combat import factory_compiler
    original = factory_compiler.compile_character
    def compile(doc, **kw):
        bundle = original(doc, **kw)
        packets = {
            'Incoming fire': [{'type':'damage','flat':20,'damage_types':['fire'],'applies_to':'self'}],
            'Incoming steel': [{'type':'damage','flat':20,'damage_types':['slashing'],'applies_to':'self'}],
            'Travel fatigue save': [{'type':'save','ability':'CON','dc':15,'save_categories':['travel_exhaustion'], 'on_fail':[], 'on_success':[]}],
            'Ordinary exhaustion save': [{'type':'save','ability':'CON','dc':15,'save_categories':['exhaustion'], 'on_fail':[], 'on_success':[]}],
            'Disease save': [{'type':'save','ability':'CON','dc':15,'on_fail':[{'type':'condition','condition':'disease','applies_to':'self'}], 'on_success':[]}],
            'Hunger penalty': [{'type':'condition','condition':'hungry','applies_to':'self','duration':'until_removed'}],
            'Spend stored Satiety': [{'type':'spend_resource','resource_id':SAT,'flat':1,'applies_to':'self'}],
            'Melee hit': [{'type':'attack','attack_kind':'cultivation_melee','count':1,
                'on_hit':[{'type':'damage','flat':3,'damage_types':['piercing']}]}],
            'Ranged hit': [{'type':'attack','attack_kind':'cultivation_ranged','count':1,
                'on_hit':[{'type':'damage','flat':3,'damage_types':['piercing']}]}],
        }
        for label, effects in packets.items():
            aid = 'action:test.meal.' + label.replace(' ','_') + '.' + kw['actor_id']
            bundle['actor_template']['action_ids'].append(aid)
            bundle['action_catalog'].append({'source_definition_id':aid, 'display_name':label,
                'owner_id':kw['actor_id'], 'economy':'NONE', 'resolution_kind':'TYPED',
                'target_kind':'ANY_CREATURE' if label in ('Melee hit','Ranged hit') else 'SELF',
                'range_ft':60 if label == 'Ranged hit' else 5,
                'parameters':{'typed':{'source':aid,'numbers':{'save_dc':15,'attack_bonus':99},'effects':effects,'duration':{'kind':'instant'}}}})
        return bundle
    monkeypatch.setattr(factory_compiler, 'compile_character', compile)


@pytest.mark.parametrize('limited', [True,False])
def test_weak_element_first_packet_each_round_and_wrong_recipient(tmp_path, monkeypatch, limited):
    native_packets(monkeypatch)
    cold, jid, command = game(tmp_path, monkeypatch)
    command('record_essence_portion', portion(benefits=['Elemental Gut'], elements=['fire'], weak_elements=['fire'], limited_elements=['fire'] if limited else []))
    refine(command)
    command('refine_reward', {'reward':'free_mantle'})
    service, table, mid = start(cold, jid)
    play(cold, table, mid, 'Digestive Mantle: Elemental Gut', ['fire'])
    first = play(cold, table, mid, 'Incoming fire')
    events = lambda e: [x for x in e.events if x.event_type == 'DAMAGE_COMMITTED' and 'Incoming_fire' in x.source_definition_id]
    assert events(first)[-1].payload['reduced_to'] == 10
    second = play(cold, table, mid, 'Incoming fire')
    assert events(second)[-1].payload['reduced_to'] == (20 if limited else 10)
    # Advance both native turns, observing that another creature gets no benefit.
    for _ in range(4):
        state = table.state(mid)
        result = table.act(mid, state['menu']['end_turn'], state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'])
        assert result['status'] == 'COMMITTED'
        state = table.state(mid)
        if state['menu']['actor_id'] == B:
            other = play(cold, table, mid, 'Incoming fire')
            assert events(other)[-1].payload['reduced_to'] == 20
        if state['menu']['actor_id'] == A:
            break
    third = play(cold, table, mid, 'Incoming fire')
    assert events(third)[-1].payload['reduced_to'] == 10


def test_base_demon_course_allows_two_fitting_damage_benefits_and_ends_once(tmp_path, monkeypatch):
    cold, jid, command = game(tmp_path, monkeypatch)
    command('record_essence_portion', portion(corrupted=1,demon_beast=1,
        benefits=['Beast Strength','Furnace Belly']))
    refine(command)
    command('refine_reward', {'reward':'free_mantle'})
    _, table, mid = start(cold, jid)
    result = play(cold, table, mid, 'Digestive Mantle: Demon-Beast Course', ['Beast Strength','Furnace Belly'])
    held = next(c for c in result.state.actors[A].conditions.values() if c.condition_id == 'condition:typed.digestive_mantle')
    assert held.data['benefits'] == ['Beast Strength','Furnace Belly']
    # The real turn clock removes the minute-long Mantle and pays its one debt.
    for _ in range(22):
        state = table.state(mid)
        result = table.act(mid, state['menu']['end_turn'], state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'])
        assert result['status'] == 'COMMITTED'
    result = engine(cold, mid)
    assert not any(c.condition_id == 'condition:typed.digestive_mantle' for c in result.state.actors[A].conditions.values())
    assert result.state.actors[A].resources[IMP] == 1


def test_satiety_capacity_and_all_legal_stored_sources_remain_reachable(tmp_path, monkeypatch):
    cold, jid, command = game(tmp_path, monkeypatch, natural=6)
    for index in range(4):
        pid = 'portion-' + str(index)
        command('record_essence_portion', portion(pid))
        refine(command, pid)
    command('record_essence_portion', portion('excess'))
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='full'):
        refine(command, 'excess')
    assert cold().journey_state(jid) == before
    _, table, mid = start(cold, jid)
    state = table.state(mid)
    # Source selection is a free table setting; all four sources reach its choice.
    setting = next(c for c in cold()._load_session(mid).engine.legal_candidates()
                   if c.display_name == 'Digestive Mantle: select stored meal')
    response = table.act(mid, setting.candidate_id, state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'])
    assert response['status'] == 'REACTION_REQUIRED'
    assert {o['id'] for o in response['reaction']['choice']['options']} == {'portion-0','portion-1','portion-2','portion-3'}


def test_venom_belly_uses_recorded_acid_once_per_turn(tmp_path, monkeypatch):
    native_packets(monkeypatch)
    cold, jid, command = game(tmp_path, monkeypatch)
    command('record_essence_portion', portion(benefits=['Venom Belly'], venom_type='acid'))
    refine(command)
    command('refine_reward', {'reward':'free_mantle'})
    _, table, mid = start(cold, jid)
    play(cold, table, mid, 'Digestive Mantle: Venom Belly')
    first = play(cold, table, mid, 'Melee hit', target=B)
    packets = lambda e: [x for x in e.events if x.event_type == 'DAMAGE_COMMITTED' and x.source_definition_id == MANTLE]
    assert len(packets(first)) == 1
    assert packets(first)[0].payload['damage_type'] == 'ACID'
    assert packets(first)[0].payload['reduced_to'] == 6
    second = play(cold, table, mid, 'Melee hit', target=B)
    assert len(packets(second)) == 1


@pytest.mark.parametrize('reduction', [5, 40])
def test_deep_nourishment_ends_only_owner_recorded_real_penalty(tmp_path, monkeypatch, reduction):
    from combat.ext.source_penalties import SOURCE, KIND, EXISTING, penalties
    native_packets(monkeypatch)
    cold, jid, command = game(tmp_path, monkeypatch)
    command('record_essence_portion', portion(benefits=['Deep Nourishment']))
    refine(command)
    command('refine_reward', {'reward':'free_mantle'})
    _, table, mid = start(cold, jid)
    result = cold()._load_session(mid).engine
    world = {'source':SOURCE,'subject':A,'kind':KIND,'scope':'march-fatigue-one',
        'value':{'penalty_id':'march-fatigue-one','cause':'forced_march','label':'Forced march fatigue',
                 'source_rule':f'External campaign fixture rule: nonmagical forced-march fatigue reduces Speed by {reduction} feet until treated.',
                 'ruling':'This actual campaign penalty has not become Exhaustion.','speed_reduction_ft':reduction},
        'expires_at':86400,'readers':[A]}
    with pytest.raises(ValueError,match='table-owner input'):
        cold().declare_combat_actor_fact(mid,A,state_version=result.state.state_version,payload=world)
    cold().declare_combat_world_fact(mid,state_version=result.state.state_version,payload=world)
    committed = cold()._load_session(mid)
    assert committed.verify()['status'] == 'PASS'
    assert committed.mechanical.replay()['status'] == 'PASS'
    result = committed.engine
    hungry = penalties(result.state.actors[A])[0]
    from combat.ext.condition_authority import source_cl
    assert source_cl(result, hungry) is None, 'An external world rule cannot borrow its victim’s cultivation authority.'
    assert result._effective_speed(result.state.actors[A]) == max(0, 30 - reduction)
    registered = {**world,'kind':EXISTING,'scope':hungry.instance_id,'value':{
        'condition_instance_id':hungry.instance_id,'cause':'forced_march',
        'source_rule':world['value']['source_rule'],'ruling':world['value']['ruling']}}
    cold().declare_combat_world_fact(mid,state_version=result.state.state_version,payload=registered)
    result = cold()._load_session(mid).engine
    assert len(penalties(result.state.actors[A])) == 1
    assert not any(action.display_name == 'Digestive Mantle: record nonmagical travel penalty'
                   for action in result.action_catalog.values())
    result = play(cold, table, mid, 'Digestive Mantle: Deep Nourishment', [hungry.instance_id])
    assert hungry.instance_id not in result.state.actors[A].conditions
    assert result._effective_speed(result.state.actors[A]) == 30
    with pytest.raises(ValueError,match='existing non-Exhaustion travel penalty'):
        cold().declare_combat_world_fact(mid,state_version=result.state.state_version,payload=registered)
    result = play(cold, table, mid, 'Travel fatigue save')
    saves = [e for e in result.events if e.event_type == 'SAVE_ROLLED' and 'Travel_fatigue_save' in e.source_definition_id]
    assert saves and saves[-1].payload['mode'] == 'ADVANTAGE'
    for label in ('Ordinary exhaustion save','Disease save'):
        result = play(cold, table, mid, label)
        saves = [e for e in result.events if e.event_type == 'SAVE_ROLLED' and label.replace(' ','_') in e.source_definition_id]
        assert saves and saves[-1].payload['mode'] == 'NORMAL'


def test_finished_journey_restores_receipts_before_new_encounter(tmp_path, monkeypatch):
    cold, jid, command = game(tmp_path, monkeypatch)
    command('record_essence_portion', portion())
    refine(command)
    command('refine_reward', {'reward':'free_mantle'})
    command('finish')
    new = cold().create_journey(project_ids=[OWNER_PROJECT, OTHER_PROJECT], arena_id='scene',
        positions={A:{'x':1,'y':1},B:{'x':2,'y':1}},base_paces={A:30,B:30})
    _, table, mid = start(cold, new['journey_id'])
    result = play(cold, table, mid, 'Digestive Mantle: Thick Hide')
    assert result.state.actors[A].resources[CP] == 29
    assert result.state.actors[A].resources[SAT] == 0


def test_general_preparation_failure_rolls_back_before_any_match(tmp_path, monkeypatch):
    from combat import ext
    cold, jid, command = game(tmp_path, monkeypatch)
    command('record_essence_portion', portion())
    before = cold().journey_state(jid)
    def reject(session, aid):
        session.state['actors'][aid]['resources'][CP] = 0
        raise ValueError('preparation rejected')
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'journey_encounter_prepare', [*ext._HOOKS.get('journey_encounter_prepare', ()), reject])
    with pytest.raises(ValueError, match='preparation rejected'):
        start(cold, jid)
    assert cold().journey_state(jid) == before
    assert not list(cold().matches_root.iterdir())


def test_player_selects_exact_free_source_without_discounting_another_meal(tmp_path, monkeypatch):
    cold, jid, command = game(tmp_path, monkeypatch, natural=[6,20])
    command('record_essence_portion', portion('ordinary'))
    refine(command, 'ordinary')
    command('record_essence_portion', portion('free', benefits=['Predator Step']))
    refine(command, 'free')
    command('refine_reward', {'reward':'free_mantle'})
    _, table, mid = start(cold, jid)
    play(cold, table, mid, 'Digestive Mantle: select stored meal', ['free'])
    result = play(cold, table, mid, 'Digestive Mantle: Predator Step')
    assert result.state.actors[A].resources[CP] == 28
    assert result.state.actors[A].resources[SAT] == 1
    for _ in range(4):
        state = table.state(mid)
        result = table.act(mid, state['menu']['end_turn'], state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'])
        assert result['status'] == 'COMMITTED'
        if table.state(mid)['menu']['actor_id'] == A:
            break
    result = play(cold, table, mid, 'Digestive Mantle: Thick Hide')
    assert result.state.actors[A].resources[CP] == 27
    assert result.state.actors[A].resources[SAT] == 0


def test_other_native_satiety_spend_consumes_its_selected_source_and_discount(tmp_path, monkeypatch):
    native_packets(monkeypatch)
    cold, jid, command = game(tmp_path, monkeypatch, natural=[6,20])
    command('record_essence_portion', portion('ordinary'))
    refine(command, 'ordinary')
    command('record_essence_portion', portion('free'))
    refine(command, 'free')
    command('refine_reward', {'reward':'free_mantle'})
    _, table, mid = start(cold, jid)
    result = play(cold, table, mid, 'Spend stored Satiety', ['free'])
    data = json.loads(next(c.data['receipt'] for c in result.state.actors[A].conditions.values() if c.condition_id == LEDGER))
    assert [c['portion_id'] for c in data['charges']] == ['ordinary']
    result = play(cold, table, mid, 'Digestive Mantle: Thick Hide')
    assert result.state.actors[A].resources[CP] == 27
    assert result.state.actors[A].resources[SAT] == 0


def move(cold, table, mid, aid, path):
    from combat.movement_routes import explicit_candidate, parse_waypoints
    route = explicit_candidate(engine(cold,mid), aid, parse_waypoints(path))
    answers = []
    for _ in range(8):
        state = table.state(mid)
        result = table.act(mid, route.candidate_id, state['menu']['decision_id'],state['menu']['state_version'],
            state['last_sequence'], answers, movement_path=path, actor_id=aid)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return engine(cold,mid)
        prompt = result['reaction']
        ids = [o['id'] for o in prompt.get('choice',{}).get('options',[])]
        answers.append({**prompt['context'],'selection':'USE','option_ids':ids[:1]})
    raise AssertionError('unresolved movement reaction')


@pytest.mark.parametrize('cells,label,bonus', [
    ([(1,1),(2,1),(3,1),(4,1)],'Melee hit',True),
    ([(1,1),(2,2),(3,1),(4,1)],'Melee hit',False),
    ([(1,1),(2,1)],'Ranged hit',False),
])
def test_predator_step_requires_ten_feet_on_actual_straight_route(tmp_path, monkeypatch,cells,label,bonus):
    native_packets(monkeypatch)
    cold,jid,command = game(tmp_path,monkeypatch,positions={A:{'x':1,'y':1},B:{'x':5,'y':1}})
    command('record_essence_portion',portion(benefits=['Predator Step']))
    refine(command)
    command('refine_reward',{'reward':'free_mantle'})
    _,table,mid = start(cold,jid)
    play(cold,table,mid,'Digestive Mantle: Predator Step')
    move(cold,table,mid,A,[{'x':x,'y':y} for x,y in cells])
    result = play(cold,table,mid,label,target=B)
    packets = [e for e in result.events if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id.startswith('action:test.meal.')]
    assert len(packets) == 1
    assert packets[0].payload['reduced_to'] == 3 + 4 * int(bonus)
    assert not [e for e in result.events if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id==MANTLE]


def test_beast_strength_also_applies_to_a_real_melee_cultivation_attack(tmp_path,monkeypatch):
    native_packets(monkeypatch)
    cold,jid,command=game(tmp_path,monkeypatch)
    command('record_essence_portion',portion(benefits=['Beast Strength']))
    refine(command)
    command('refine_reward',{'reward':'free_mantle'})
    _,table,mid=start(cold,jid)
    play(cold,table,mid,'Digestive Mantle: Beast Strength')
    ranged=play(cold,table,mid,'Ranged hit',target=B)
    assert not [e for e in ranged.events if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id==MANTLE]
    result=play(cold,table,mid,'Melee hit',target=B)
    packets=[e for e in result.events if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id.startswith('action:test.meal.Melee_hit.')]
    assert len(packets)==1 and packets[0].payload['reduced_to']==7
    result=play(cold,table,mid,'Melee hit',target=B)
    packets=[e for e in result.events if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id.startswith('action:test.meal.Melee_hit.')]
    assert [e.payload['reduced_to'] for e in packets] == [7,3]
    assert not [e for e in result.events if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id==MANTLE]


def test_predator_step_does_not_reuse_previous_turn_movement_on_opportunity_hit(tmp_path,monkeypatch):
    native_packets(monkeypatch)
    cold,jid,command=game(tmp_path,monkeypatch,positions={A:{'x':1,'y':1},B:{'x':5,'y':1}})
    command('record_essence_portion',portion(benefits=['Predator Step']))
    refine(command)
    command('refine_reward',{'reward':'free_mantle'})
    _,table,mid=start(cold,jid)
    play(cold,table,mid,'Digestive Mantle: Predator Step')
    move(cold,table,mid,A,[{'x':x,'y':1} for x in range(1,5)])
    state=table.state(mid)
    assert table.act(mid,state['menu']['end_turn'],state['menu']['decision_id'],state['menu']['state_version'],state['last_sequence'])['status']=='COMMITTED'
    assert table.state(mid)['menu']['actor_id']==B
    result=move(cold,table,mid,B,[{'x':5,'y':1},{'x':6,'y':1}])
    assert [e for e in result.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==A], 'A real opportunity attack must occur for this boundary proof.'
    assert not [e for e in result.events if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id==MANTLE]


def test_paid_extra_benefit_can_use_any_fitting_remaining_source(tmp_path,monkeypatch):
    # Existing talent is unchanged; this verifies that the base source adapter
    # does not cut its legal options or consume an inappropriate meal.
    cold,jid,command=game(tmp_path,monkeypatch,natural=6,talents=['tianxia.talent.hunger.maw_of_ten_thousand_courses'])
    command('record_essence_portion',portion('hide',benefits=['Thick Hide']))
    refine(command,'hide')
    command('record_essence_portion',portion('furnace',benefits=['Furnace Belly']))
    refine(command,'furnace')
    _,table,mid=start(cold,jid)
    result=play(cold,table,mid,'Digestive Mantle: Thick Hide',['Furnace Belly','furnace','all_ordinary'])
    held=next(c for c in result.state.actors[A].conditions.values() if c.condition_id=='condition:typed.digestive_mantle')
    assert held.data['benefits']==['Thick Hide','Furnace Belly']
    assert result.state.actors[A].resources[SAT]==0
    data=json.loads(next(c.data['receipt'] for c in result.state.actors[A].conditions.values() if c.condition_id==LEDGER))
    assert data['charges']==[]
