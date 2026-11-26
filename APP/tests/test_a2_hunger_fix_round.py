"""Review cases through service/session execution and cold reducer reload."""
import json
import pytest
from tests.hunt31_support import OWNER, FOE, fixture, reload, owner_turn, pick, act
from tests.test_a2_hunger import BASE, H, SAT, CP, play
from tests.test_hunt31_mantle_preservation import _mantle_data, _turn_to


def ai_step(combat, table, mid, label, *, target=None, meal=None, answers=(), raw=False):
    """Select only perceived candidates. Meal is this creature's own known meal.

    Unknown provenance delegates to the production reaction policy. This adapter
    cannot inspect the engine roster or request unfiltered legal candidates.
    """
    from combat.gate4_adapters import ManualControllerAdapter
    original = combat.controller
    class Observed:
        def choose_primary_action(self, context):
            candidates = [c for c in context.legal_candidates if label in c.display_name
                          and (target is None or c.target_ids == (target,))]
            assert candidates, label
            return ManualControllerAdapter(lambda _: (candidates[0].candidate_id, ())).choose_primary_action(context)
        def choose_reaction(self, context):
            choice = original.choose_reaction(context)
            if meal in ('acid','poison','necrotic') and context.reaction_source_id.endswith('fang_meal'):
                assert meal in context.legal_option_ids
                decision = choice.decision.model_copy(update={'selection':'USE', 'option_ids':(meal,)})
                scores=tuple(s.model_copy(update={'total':int(s.candidate_id.endswith(':USE')),
                    'option_ids':(meal,) if s.candidate_id.endswith(':USE') else (),
                    'components':()}) for s in choice.record.scored_alternatives)
                record=choice.record.model_copy(update={'controller_id':'test:known_own_meal',
                    'selected_candidate_id':f'reaction:{context.reaction_source_id}:USE',
                    'selected_option_ids':(meal,), 'selected_reaction':decision,
                    'scored_alternatives':scores, 'explanation':'Declare the creature\'s own known qualifying meal.'})
                return choice.model_copy(update={'decision':decision,'record':record})
            return choice
        def __getattr__(self, name):
            return getattr(original, name)
    combat.controller = Observed()
    try:
        return (combat.local_step(mid, list(answers)) if raw else
                table.auto_step(mid, table.state(mid)['last_sequence'], list(answers)))
    finally:
        combat.controller = original


@pytest.mark.parametrize('meal', [None, 'ordinary', 'poison'])
def test_ai_fang_requires_known_qualifying_meal(monkeypatch, tmp_path, meal):
    combat, table, mid = fixture(monkeypatch, tmp_path, [BASE,H+'devour_the_venom_keep_the_fang'], resources={SAT:6})
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    assert ai_step(combat,table,mid,'Digestive Mantle: Iron Stomach',meal=meal)['status']=='COMMITTED'
    engine=reload(combat,mid)
    data=_mantle_data(engine)
    qualifying=meal=='poison'
    assert data.get('fang_type')==('poison' if qualifying else None)
    assert {m.value for m in engine.state.actors[OWNER].modifiers.values() if m.target_field=='damage_resistance'} == ({'POISON'} if qualifying else set())
    assert bool(data.get('fang_meal_eligible')) is qualifying


@pytest.mark.parametrize('purity',['ordinary_only','includes_impure'])
def test_maw_records_hundred_flavour_purchase_after_declining_maw(monkeypatch,tmp_path,purity):
    impurity='resource:named.impurity'
    combat,table,mid=fixture(monkeypatch,tmp_path,[BASE,H+'maw_of_ten_thousand_courses',H+'hundred_flavour_mantle'],resources={SAT:6,impurity:6})
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide',['normal','DECLINE','Iron Stomach',purity])
    assert engine.state.actors[OWNER].resources[SAT]==4
    data=_mantle_data(engine)
    owner_turn(table,mid,next_turn=True)
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide',['normal','DECLINE','DECLINE'])
    assert engine.state.actors[OWNER].resources[impurity]==(6 if purity=='includes_impure' else 5)
    assert data['additional_impure'] is (purity=='includes_impure')


def answer(prompt,option):
    return {**prompt['context'],'selection':'USE','option_ids':[option]}


def test_secondary_elemental_and_venom_player_text(monkeypatch,tmp_path):
    combat,table,mid=fixture(monkeypatch,tmp_path,[BASE,H+'hundred_flavour_mantle'],resources={SAT:6})
    cid=pick(table,mid,'Digestive Mantle: Thick Hide')
    result=act(table,mid,cid)
    benefit_menu=json.dumps(result['reaction'])
    answers=[answer(result['reaction'],'Elemental Gut')]
    result=act(table,mid,cid,answers)
    element_moment=result['reaction']['moment']
    answers.append(answer(result['reaction'],'fire'))
    assert act(table,mid,cid,answers)['status']=='COMMITTED'
    engine=reload(combat,mid)
    assert 'Poison or Acid' in benefit_menu
    assert 'until the end of your next turn' in element_moment
    assert 'while the Mantle lasts' not in element_moment
    assert 'Elemental Gut: you have Resistance to fire damage until the end of your next turn' in json.dumps([e.model_dump(mode='json') for e in engine.events])
    owner_turn(table,mid,next_turn=True)
    assert act(table,mid,table.state(mid)['menu']['end_turn'])['status']=='COMMITTED'
    assert not [m for m in reload(combat,mid).state.actors[OWNER].modifiers.values() if m.target_field=='damage_resistance']


def hostile_fixture(monkeypatch,tmp_path,talents,effects,*,resources=None):
    from tests import hunt28_support as h
    original_fixture=h.fixture
    def make(*args,**kwargs):
        built=h.compile_character
        def finalized(doc,**kw):
            bundle=built(doc,**kw)
            if kw['actor_id']==FOE:
                for a in bundle['action_catalog']:
                    if a['display_name']=='Prepare': a['target_kind']='HOSTILE_ENTITY'
            return bundle
        monkeypatch.setattr(h,'compile_character',finalized)
        return original_fixture(*args,**kwargs)
    monkeypatch.setattr(h,'fixture',make)
    return fixture(monkeypatch,tmp_path,talents,resources=resources,setup=effects)


@pytest.mark.parametrize('nested',[False,True])
def test_fang_off_turn_ask_me_names_actual_ai_damage_packet(monkeypatch,tmp_path,nested):
    packet_id='action:test.h31.prepare.'+FOE
    packet_name='Prepare'
    damage={'type':'damage','applies_to':'target','damage_types':['poison'],'flat':20}
    effects=[{'type':'save','ability':'CON','dc':99,'on_fail':[{**damage,'source_modifier':'test.nested.poison'}]}] if nested else [damage]
    combat,table,mid=hostile_fixture(monkeypatch,tmp_path,[BASE,H+'devour_the_venom_keep_the_fang'],effects,resources={SAT:6})
    play(combat,table,mid,'Digestive Mantle: Iron Stomach',['poison'])
    owner_turn(table,mid,next_turn=True)
    _turn_to(table,mid,FOE)
    before=reload(combat,mid).state.actors[OWNER].resources[CP]
    combat.set_controller_mode(mid,actor_id=FOE,controller_mode='LOCAL_AUTO')
    raw=ai_step(combat,table,mid,'Prepare',target=OWNER,raw=True)
    assert raw['status']=='AWAITING_REACTION',raw
    trigger=raw['reaction_context']['choice_trigger']
    result=ai_step(combat,table,mid,'Prepare',target=OWNER)
    assert result['status']=='REACTION_REQUIRED',result
    rendered=json.dumps(result['reaction'])
    prompt=result['reaction']
    assert ai_step(combat,table,mid,'Prepare',target=OWNER,answers=[answer(result['reaction'],'use')])['status']=='COMMITTED'
    engine=reload(combat,mid)
    assert engine.state.actors[OWNER].resources[CP]==before-1
    assert not engine.state.actors[OWNER].reaction_available
    assert trigger['source_definition_id']==packet_id
    assert trigger['action_actor_id']==FOE
    assert trigger['affected_id']==OWNER
    assert packet_name in rendered
    assert prompt['action']==packet_name
    assert prompt['trigger_actor']
    assert prompt['cost']=='Reaction and 1 Qi'
    packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id==packet_id]
    assert packets[-1].payload['reduced_to']==10


def test_iron_belly_off_turn_ask_me_on_ai_turn(monkeypatch,tmp_path):
    save={'type':'save','ability':'CON','dc':99,'on_fail':[{'type':'condition','condition':'poisoned','applies_to':'target'}]}
    combat,table,mid=hostile_fixture(monkeypatch,tmp_path,['insight.iron-belly-foundation'],[save])
    _turn_to(table,mid,FOE)
    before=reload(combat,mid).state.actors[OWNER].resources[CP]
    combat.set_controller_mode(mid,actor_id=FOE,controller_mode='LOCAL_AUTO')
    result=ai_step(combat,table,mid,'Prepare',target=OWNER)
    assert result['status']=='REACTION_REQUIRED',result
    prompt=result['reaction']
    assert 'Iron Belly Foundation' in json.dumps(prompt)
    assert ai_step(combat,table,mid,'Prepare',target=OWNER,answers=[{**prompt['context'],'selection':'USE'}])['status']=='COMMITTED'
    engine=reload(combat,mid)
    assert engine.state.actors[OWNER].resources[CP]==before-1
    assert len([e for e in engine.events if e.event_type=='D20_REWRITTEN'])==1


def test_fang_names_nested_reaction_instead_of_outer_action(monkeypatch,tmp_path):
    from tests import hunt28_support as h
    original_fixture=h.fixture
    source='test:poison_counter'
    def make(*args,**kwargs):
        built=h.compile_character
        def finalized(doc,**kw):
            bundle=built(doc,**kw)
            if kw['actor_id']==OWNER:
                for a in bundle['action_catalog']:
                    if a['display_name']=='Prepare': a['target_kind']='HOSTILE_ENTITY'
            if kw['actor_id']==FOE:
                bundle['typed_reactions'].append({'block':'generic','kind':'damaged','feature_id':source,
                    'name':'Poison Counter','range_ft':60,'costs':[], 'effects':[
                        {'type':'damage','applies_to':'target','damage_types':['poison'],'flat':20}]})
            return bundle
        monkeypatch.setattr(h,'compile_character',finalized)
        return original_fixture(*args,**kwargs)
    monkeypatch.setattr(h,'fixture',make)
    combat,table,mid=fixture(monkeypatch,tmp_path,[BASE,H+'devour_the_venom_keep_the_fang'],resources={SAT:6},
        setup=[{'type':'damage','applies_to':'target','damage_types':['fire'],'flat':1}])
    play(combat,table,mid,'Digestive Mantle: Iron Stomach',['poison'])
    owner_turn(table,mid,next_turn=True)
    combat.set_controller_mode(mid,actor_id=FOE,controller_mode='LOCAL_AUTO')
    before=reload(combat,mid).state.actors[OWNER].resources[CP]
    cid=pick(table,mid,'Prepare',FOE)
    result=act(table,mid,cid)
    assert result['status']=='REACTION_REQUIRED',result
    prompt=result['reaction']
    assert act(table,mid,cid,[answer(result['reaction'],'use')])['status']=='COMMITTED'
    engine=reload(combat,mid)
    assert engine.state.actors[OWNER].resources[CP]==before-1
    assert prompt['action']=='Poison Counter'
    assert 'Poison Counter' in prompt['moment']
    assert 'Prepare' not in prompt['moment']
    packet=next(e for e in reversed(engine.events) if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id==source)
    assert packet.payload['reduced_to']==10


def test_secondary_elemental_duration_matches_rendered_prompt(monkeypatch,tmp_path):
    combat,table,mid=fixture(monkeypatch,tmp_path,[BASE,H+'hundred_flavour_mantle'],resources={SAT:6})
    cid=pick(table,mid,'Digestive Mantle: Thick Hide')
    result=act(table,mid,cid)
    answers=[answer(result['reaction'],'Elemental Gut')]
    result=act(table,mid,cid,answers)
    moment=result['reaction']['moment']
    answers.append(answer(result['reaction'],'fire'))
    assert act(table,mid,cid,answers)['status']=='COMMITTED'
    engine=reload(combat,mid)
    assert any(m.value=='FIRE' for m in engine.state.actors[OWNER].modifiers.values() if m.target_field=='damage_resistance')
    owner_turn(table,mid,next_turn=True)
    assert act(table,mid,table.state(mid)['menu']['end_turn'])['status']=='COMMITTED'
    assert _mantle_data(reload(combat,mid))['benefits']==['Thick Hide']
    assert not [m for m in reload(combat,mid).state.actors[OWNER].modifiers.values() if m.target_field=='damage_resistance']
    assert 'until the end of your next turn' in moment
    assert 'while the Mantle lasts' not in moment
