"""Printed Hunger combat effects through real service commits and cold reducer reloads."""
import pytest
from combat import flight, typed_executor
from tests.hunt31_support import OWNER, ALLY, FOE, fixture, reload, owner_turn, pick, act
from tests.test_hunt31_mantle_preservation import _ordered_mantle, _mantle_data, _turn_to

H = 'tianxia.talent.hunger.'
BASE = 'HUNGER_BASE_DIGESTIVE_MANTLE'
SAT = 'resource:named.satiety'
CP = 'resource:core.qi'


def play(combat, table, mid, label, choices=(), target=None):
    cid = pick(table, mid, label, target)
    result = act(table, mid, cid)
    answers, pending = [], list(choices)
    for _ in range(20):
        if result['status'] != 'REACTION_REQUIRED':
            break
        prompt = result['reaction']
        offered = [o['id'] for o in prompt['choice']['options']]
        wanted = pending[0] if pending else offered[0]
        if wanted == 'DECLINE':
            answers.append({**prompt['context'], 'selection':'DECLINE'})
            pending.pop(0)
        else:
            chosen = wanted if wanted in offered else offered[0]
            if pending and chosen == wanted:
                pending.pop(0)
            answers.append({**prompt['context'], 'selection':'USE', 'option_ids':[chosen]})
        result = act(table, mid, cid, answers)
    assert result['status'] == 'COMMITTED', result
    return reload(combat, mid)


@pytest.mark.parametrize('primary,secondary', [('Thick Hide', 'Predator Step'), ('Thick Hide', 'Iron Stomach'),
                                             ('Thick Hide', 'Beast Strength'), ('Thick Hide', 'Elemental Gut')])
def test_hundred_flavour_applies_pays_and_expires_only_secondary(monkeypatch, tmp_path, primary, secondary):
    combat, table, mid = fixture(monkeypatch, tmp_path, [BASE, H+'hundred_flavour_mantle'], resources={SAT:6})
    engine = play(combat, table, mid, 'Digestive Mantle: '+primary, [secondary, 'fire'])
    actor = engine.state.actors[OWNER]
    assert _mantle_data(engine)['benefits'] == [primary, secondary]
    assert actor.resources[SAT] == 4
    if secondary == 'Predator Step':
        assert engine._effective_speed(actor) == 40
    if secondary == 'Beast Strength':
        assert 'ADVANTAGE' in typed_executor.check_modes(actor, 'STR')
    if secondary == 'Iron Stomach':
        assert 'ADVANTAGE' in set(m for c in __import__('combat.ext', fromlist=['run']).run('save',
            type('Context', (), {'engine':engine})(), actor, 'CON', ['poisoned']) if c for m in c['modes'])
    if secondary == 'Elemental Gut':
        assert {m.value for m in actor.modifiers.values() if m.target_field == 'damage_resistance'} == {'FIRE'}
    owner_turn(table, mid, next_turn=True)
    assert _mantle_data(reload(combat, mid))['benefits'] == [primary, secondary]
    assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    actor = engine.state.actors[OWNER]
    assert _mantle_data(engine)['benefits'] == [primary]
    if secondary == 'Predator Step':
        assert engine._effective_speed(actor) == 30
    if secondary == 'Beast Strength':
        assert 'ADVANTAGE' not in typed_executor.check_modes(actor, 'STR')
    if secondary == 'Elemental Gut':
        assert not [m for m in actor.modifiers.values() if m.target_field == 'damage_resistance']


def test_three_course_replaces_speed_and_materializes_elemental_gut(monkeypatch, tmp_path):
    combat, table, mid = fixture(monkeypatch, tmp_path, [BASE,H+'three_course_battle_body'], resources={SAT:6})
    engine = play(combat, table, mid, 'Digestive Mantle: Predator Step')
    assert engine._effective_speed(engine.state.actors[OWNER]) == 40
    owner_turn(table, mid, next_turn=True)
    engine = play(combat, table, mid, 'Three-Course Battle Body', ['Elemental Gut','fire'])
    assert engine._effective_speed(engine.state.actors[OWNER]) == 30
    assert _mantle_data(engine)['element'] == 'fire'
    assert {m.value for m in engine.state.actors[OWNER].modifiers.values() if m.target_field=='damage_resistance'} == {'FIRE'}
    assert engine.state.actors[OWNER].resources[SAT] == 4
    owner_turn(table, mid, next_turn=True)
    engine = play(combat, table, mid, 'Three-Course Battle Body', ['Predator Step'])
    assert engine._effective_speed(engine.state.actors[OWNER]) == 40
    assert not [m for m in engine.state.actors[OWNER].modifiers.values() if m.target_field == 'damage_resistance']
    assert 'element' not in _mantle_data(engine)
    assert engine.state.actors[OWNER].resources[SAT] == 3


def test_maw_secondary_beast_strength_gives_checks_and_saves(monkeypatch,tmp_path):
    from combat import ext
    combat,table,mid=fixture(monkeypatch,tmp_path,[BASE,H+'maw_of_ten_thousand_courses'],resources={SAT:6})
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide',['normal','Beast Strength','Iron Stomach'])
    actor=engine.state.actors[OWNER]
    assert actor.resources[SAT]==3
    assert 'ADVANTAGE' in typed_executor.check_modes(actor,'STR')
    assert 'ADVANTAGE' in ext.run('save_mode',engine,actor,'STR',15,'action:test',{})
    assert 'ADVANTAGE' in ext.run('save_mode',engine,actor,'CON',15,'action:test',{'named':['disease']})
    assert 'ADVANTAGE' not in ext.run('save_mode',engine,engine.state.actors[ALLY],'STR',15,'action:test',{})


def test_winged_expires_next_turn_while_mantle_remains(monkeypatch,tmp_path):
    combat,table,mid=fixture(monkeypatch,tmp_path,[BASE,H+'nine_beast_sovereign_course'],resources={SAT:6})
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide + Nine-Beast Sovereign Course: Winged Hunger')
    assert flight.profile(engine,engine.state.actors[OWNER]).speed_ft==30
    owner_turn(table,mid,next_turn=True)
    assert flight.profile(reload(combat,mid),reload(combat,mid).state.actors[OWNER]).speed_ft==30
    assert act(table,mid,table.state(mid)['menu']['end_turn'])['status']=='COMMITTED'
    engine=reload(combat,mid)
    assert flight.profile(engine,engine.state.actors[OWNER]).speed_ft==0
    assert _mantle_data(engine)['benefits']==['Thick Hide']


@pytest.mark.parametrize('choose,accept,cp', [('fire',False,10), ('poison',False,10), ('poison',True,10), ('poison',False,0)])
def test_fang_chooses_one_type_and_paid_reaction_after_expiry(monkeypatch,tmp_path,choose,accept,cp):
    # A generic evented preparation packet tests actual damage application, not a bare hook.
    damage={'type':'damage','applies_to':'target','damage_types':['poison'],'flat':20}
    combat,table,mid=fixture(monkeypatch,tmp_path,[BASE,H+'devour_the_venom_keep_the_fang'],resources={SAT:6, CP:cp + 1},setup=[damage])
    choices=['DECLINE'] if choose=='fire' else [choose]
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide',choices)
    resists={m.value for m in engine.state.actors[OWNER].modifiers.values() if m.target_field=='damage_resistance'}
    assert resists== (set() if choose=='fire' else {'POISON'})
    owner_turn(table,mid,next_turn=True)
    assert not [m for m in reload(combat,mid).state.actors[OWNER].modifiers.values() if m.target_field=='damage_resistance']
    before=reload(combat,mid).state.actors[OWNER].resources[CP]
    engine=play(combat,table,mid,'Prepare',['use' if accept else 'DECLINE'],target=OWNER)
    actor=engine.state.actors[OWNER]
    assert actor.resources[CP]==before-int(accept)
    assert actor.reaction_available is (not accept)
    grants = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == H+'devour_the_venom_keep_the_fang']
    assert bool(grants) is accept
    if accept:
        assert grants[-1].payload['offered'] == 4  # the sealed level-12 fixture has PB 4
    packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id.startswith('action:test.h31.prepare')]
    assert packets[-1].payload['reduced_to']==(10 if accept else 20)


def test_marrow_damage_consumption_keeps_mantle_impurity_debt(monkeypatch, tmp_path):
    from tests import hunt28_support as h
    # The synthetic preparation action is sealed before genesis and uses the
    # ordinary executor, resource payment, Hunger completion hook and damage roll.
    original = h.compile_character
    def compile(doc, **kw):
        bundle = original(doc, **kw)
        aid = 'action:test.hunger.cp.' + kw['actor_id']
        bundle['actor_template']['action_ids'].append(aid)
        bundle['action_catalog'].append({'source_definition_id': aid, 'display_name':'Spend CP on Hunger',
            'owner_id':kw['actor_id'], 'economy':'ACTION', 'resolution_kind':'TYPED', 'target_kind':'SELF',
            'costs':[[CP,1]], 'parameters':{'typed':{'source':H+'test_cp_spend', 'effects':[],
                                               'numbers':{}, 'duration':{'kind':'instant'}}}})
        aid = 'action:test.hunger.roll.' + kw['actor_id']
        bundle['actor_template']['action_ids'].append(aid)
        bundle['action_catalog'].append({'source_definition_id':aid,'display_name':'Roll damage',
            'owner_id':kw['actor_id'],'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF',
            'parameters':{'typed':{'effects':[{'type':'spend_resource','applies_to':'self','resource_id':'resource:named.impurity','flat':5}, {'type':'damage','applies_to':'self','damage_types':['fire'],
                'dice':{'count':1,'sides':6}}], 'numbers':{},'duration':{'kind':'instant'}}}})
        return bundle
    monkeypatch.setattr(h,'compile_character',compile)
    combat,table,mid=fixture(monkeypatch,tmp_path,[BASE,H+'marrow_furnace_pulse'],
        resources={SAT:6,'resource:named.impurity':6})
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['demon_beast','Iron Stomach'])
    play(combat,table,mid,'Spend CP on Hunger')
    engine=play(combat,table,mid,'Roll damage')
    assert engine.state.actors[OWNER].turn_flags.get('hunger_marrow_damage')==0
    assert _mantle_data(engine)['marrow_debt'] is True
    owner_turn(table,mid,next_turn=True)
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide',['normal'])
    gains=[e for e in engine.events if e.event_type=='RESOURCE_GAINED' and e.source_definition_id==H+'marrow_furnace_pulse']
    assert gains, 'Consuming the bonus must not cancel the Impurity owed when the old Mantle ends'


def test_sealed_pre_policy_bundle_retains_its_flight_lifecycle(monkeypatch,tmp_path):
    from tests import hunt28_support as h
    original=h.compile_character
    def legacy(doc,**kw):
        bundle=original(doc,**kw)
        bundle['typed_passives']=[r for r in bundle['typed_passives']
                                 if not (r.get('block')=='lane9_hunger' and r.get('kind')=='mantle_policy')]
        return bundle
    monkeypatch.setattr(h,'compile_character',legacy)
    combat,table,mid=fixture(monkeypatch,tmp_path,[BASE,H+'nine_beast_sovereign_course'],resources={SAT:6})
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide + Nine-Beast Sovereign Course: Winged Hunger')
    assert 'runtime' not in _mantle_data(engine)
    owner_turn(table,mid,next_turn=True)
    assert act(table,mid,table.state(mid)['menu']['end_turn'])['status']=='COMMITTED'
    engine=reload(combat,mid)
    assert flight.profile(engine,engine.state.actors[OWNER]).speed_ft==30
    assert not any(c.condition_id=='condition:typed.hunger_winged_expiry' for c in engine.state.actors[OWNER].conditions.values())


def test_maw_mixed_additional_meals_do_not_reduce_impurity(monkeypatch,tmp_path):
    combat,table,mid=fixture(monkeypatch,tmp_path,[BASE,H+'maw_of_ten_thousand_courses'],
        resources={SAT:6,'resource:named.impurity':6})
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide',['normal','Iron Stomach','Beast Strength','includes_impure'])
    assert _mantle_data(engine)['additional_impure'] is True
    owner_turn(table,mid,next_turn=True)
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide',['normal','DECLINE'])
    assert engine.state.actors[OWNER].resources['resource:named.impurity']==6


@pytest.mark.parametrize('accept', [False, True])
def test_iron_belly_rerolls_only_one_failed_poison_save_per_scene(monkeypatch,tmp_path,accept):
    save={'type':'save','applies_to':'target','ability':'con','dc':40,
          'on_fail':[{'type':'condition','applies_to':'target','condition':'poisoned','duration':'until_end_of_next_turn'}],
          'on_success':[]}
    combat,table,mid=fixture(monkeypatch,tmp_path,['insight.iron-belly-foundation'],setup=[save],dc=40)
    before=reload(combat,mid).state.actors[OWNER].resources[CP]
    cid=pick(table,mid,'Prepare',OWNER)
    result=act(table,mid,cid)
    answers=[]
    if accept:
        assert result['status']=='REACTION_REQUIRED'
    for _ in range(10):
        if result['status']!='REACTION_REQUIRED': break
        prompt=result['reaction']
        answers.append({**prompt['context'],'selection':'USE' if accept else 'DECLINE'})
        result=act(table,mid,cid,answers)
    assert result['status']=='COMMITTED',result
    engine=reload(combat,mid)
    rewrites=[e for e in engine.events if e.event_type=='D20_REWRITTEN' and e.source_definition_id=='insight.iron-belly-foundation']
    assert len(rewrites)==int(accept)
    assert engine.state.actors[OWNER].resources[CP]==before-int(accept)
    if accept:
        # Another failed poison save after cold reload cannot spend this scene's
        # already-consumed allowance, despite enough CP and a free Reaction.
        assert act(table,mid,pick(table,mid,'Prepare',OWNER))['status']=='COMMITTED'
        engine=reload(combat,mid)
        assert len([e for e in engine.events if e.event_type=='D20_REWRITTEN' and e.source_definition_id=='insight.iron-belly-foundation'])==1
        assert engine.state.actors[OWNER].resources[CP]==before-1


def test_base_demon_beast_course_picks_two_and_settles_debt_on_recast(monkeypatch, tmp_path):
    impurity = 'resource:named.impurity'
    damage = {'type':'spend_resource', 'applies_to':'self', 'resource_id':impurity, 'flat':5}
    combat, table, mid = fixture(monkeypatch, tmp_path, [BASE],
                                resources={SAT:6, impurity:6}, setup=[damage])
    engine = play(combat, table, mid, 'Prepare', target=OWNER)
    assert engine.state.actors[OWNER].resources[impurity] == 1
    engine = play(combat, table, mid, 'Digestive Mantle: Demon-Beast Course', ['Predator Step', 'Iron Stomach'])
    assert _mantle_data(engine)['satiety'] == 'demon_beast'
    assert _mantle_data(engine)['benefits'] == ['Predator Step', 'Iron Stomach']
    assert engine._effective_speed(engine.state.actors[OWNER]) == 40
    assert engine.state.actors[OWNER].resources[SAT] == 5
    assert engine.state.actors[OWNER].resources[impurity] == 1
    owner_turn(table, mid, next_turn=True)
    engine = play(combat, table, mid, 'Digestive Mantle: Thick Hide')
    assert engine.state.actors[OWNER].resources[impurity] == 2
    assert engine._effective_speed(engine.state.actors[OWNER]) == 30
    assert _mantle_data(engine)['benefits'] == ['Thick Hide']


@pytest.mark.parametrize('defense,expected', [('passive',10), ('next',10), ('penetration',20)])
def test_fang_uses_actual_packet_defenses(monkeypatch, tmp_path, defense, expected):
    from tests import hunt28_support as h
    original = h.compile_character
    def compile(doc, **kw):
        bundle = original(doc, **kw)
        if defense == 'passive' and kw['actor_id'] == OWNER:
            bundle['typed_passives'].append({'feature_id':'test:standing.poison', 'name':'Standing Poison Resistance',
                'block':'defense', 'kind':'resistance', 'damage_types':['POISON']})
        if kw['actor_id'] == OWNER:
            aid = 'action:test.h31.prepare.' + OWNER
            bundle['actor_template']['action_ids'].append(aid)
            bundle['action_catalog'].append({'source_definition_id':aid, 'display_name':'Packet',
                'owner_id':OWNER, 'economy':'NONE', 'resolution_kind':'TYPED', 'target_kind':'ALLY_OR_SELF', 'range_ft':60,
                'parameters':{'typed':{'source':'test:packet', 'effects':setup, 'numbers':{}, 'duration':{'kind':'instant'}}}})
        return bundle
    monkeypatch.setattr(h, 'compile_character', compile)
    setup = []
    if defense == 'next':
        setup.append({'type':'resistance_next', 'applies_to':'self', 'damage_types':['poison']})
    elif defense == 'penetration':
        setup.append({'type':'ignore_resistance', 'damage_types':['poison']})
    setup.append({'type':'damage', 'applies_to':'target', 'damage_types':['poison'], 'flat':20})
    combat, table, mid = fixture(monkeypatch, tmp_path, [BASE,H+'devour_the_venom_keep_the_fang'],
                                resources={SAT:6})
    play(combat, table, mid, 'Digestive Mantle: Iron Stomach', ['poison'])
    owner_turn(table, mid, next_turn=True)
    before = reload(combat, mid).state.actors[OWNER].resources[CP]
    engine = play(combat, table, mid, 'Packet', ['use'], target=OWNER)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and e.source_definition_id.startswith('action:test.h31.prepare')]
    assert packets[-1].payload['reduced_to'] == expected
    assert engine.state.actors[OWNER].resources[CP] == before - 1
    assert not engine.state.actors[OWNER].reaction_available
    assert not [m for m in engine.state.actors[OWNER].modifiers.values() if m.target_field == 'damage_resistance_next']
