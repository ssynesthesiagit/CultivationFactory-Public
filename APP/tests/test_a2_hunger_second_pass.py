"""Printed Hunger rewards through CombatService/session transactions and cold reload."""
import pytest
from tests import hunt28_support as harness
from tests.hunt31_support import OWNER, ALLY, FOE, fixture, reload, owner_turn, pick, act
from tests.test_a2_hunger import BASE, H, SAT, CP, play
from tests.test_hunt31_mantle_preservation import _mantle_data, _turn_to

DRAGON = H+'dragon_marrow_banquet_scripture'
KING = H+'demon_king_roast_method'
SCHOLAR = 'insight.monster-taste-scholar'
PRESSURE = 'condition:typed.demon_king_pressure'
IMP = 'resource:named.impurity'


def table_fixture(monkeypatch, tmp_path, talents, *, packet=None, owner_cl=17, foe_cl=5, blocked=False,
                  foe_fire_resistance=False, foe_fire_immunity=False):
    original = harness.compile_character
    def compile(doc, **kw):
        actor = kw['actor_id']
        doc['identity']['cultivation_level'] = owner_cl if actor == OWNER else foe_cl
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 300
        bundle = original(doc, **kw)
        if actor == FOE and foe_fire_resistance:
            bundle['typed_passives'].append({'feature_id':'test.fire_resistance','block':'defense',
                'kind':'resistance','damage_types':['FIRE']})
        if actor == FOE and foe_fire_immunity:
            bundle['typed_passives'].append({'feature_id':'test.fire_immunity','block':'defense',
                'kind':'immunity','damage_types':['FIRE']})
        for name, effects, source, typed_extra in (
            ('Strike', [{'type':'attack','attack_kind':'cultivation_ranged','count':1,
                         'on_hit':[{'type':'damage','flat':1,'damage_types':['bludgeoning']}]}], 'test.strike', {}),
            ('Elemental packet', [packet or {'type':'damage','flat':3,'damage_types':['fire']}],
             'FIRE_BASE_IGNITE', {'hunger_sphere_damage':True}),
            ('Ordinary packet', [{'type':'damage','flat':3,'damage_types':['fire']}], 'test.ordinary', {}),
        ):
            aid = 'action:test.hunger_second.'+name.replace(' ','_')+'.'+actor
            bundle['actor_template']['action_ids'].append(aid)
            bundle['action_catalog'].append({'source_definition_id':aid,'display_name':name,'owner_id':actor,
                'economy':'NONE','resolution_kind':'TYPED','target_kind':'ANY_CREATURE','range_ft':60,
                'parameters':{'typed':{'effects':effects, 'source':source,
                    'numbers':{'attack_bonus':99, 'save_dc':1 if packet and packet.get('type')=='save' else 99},
                    'duration':{'kind':'instant'}, **typed_extra}}})
        if actor == OWNER and KING in talents:
            aid='action:test.hunger_second.early_mantle_recast.'+actor
            bundle['actor_template']['action_ids'].append(aid)
            bundle['action_catalog'].append({'source_definition_id':aid,'display_name':'Early Mantle Recast: Thick Hide',
                'owner_id':actor,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','range_ft':0,
                'parameters':{'typed':{'source':'HUNGER_BASE_DIGESTIVE_MANTLE','effects':[],
                    'numbers':{'pb':3},'duration':{'kind':'instant'}}}})
            sweep='action:test.hunger_second.multi_creature_strike.'+actor
            bundle['actor_template']['action_ids'].append(sweep)
            bundle['action_catalog'].append({'source_definition_id':sweep,'display_name':'Multi-creature Strike',
                'owner_id':actor,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','range_ft':0,
                'radius_ft':30,'parameters':{'typed':{'area':{'shape':'sphere','size_ft':30,
                    'recipients':'all','exclude_self':True},'effects':[{'type':'attack',
                    'attack_kind':'cultivation_ranged','count':1,'on_hit':[{'type':'damage','flat':1,
                    'damage_types':['bludgeoning']}]}],'source':'test.multi_creature_strike',
                    'numbers':{'attack_bonus':99},'duration':{'kind':'instant'}}}})
        return bundle
    monkeypatch.setattr(harness,'compile_character',compile)
    combat,table,mid=fixture(monkeypatch,tmp_path,talents,resources={SAT:8,IMP:10},
        setup=[{'type':'spend_resource','applies_to':'self','resource_id':IMP,'flat':5}])
    if blocked:
        from copy import deepcopy
        # New genesis owns this synthetic solid pillar and all positions.
        bundles=deepcopy(combat._load_session(mid).engine.typed_bundle_documents)
        arena=deepcopy(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
        arena['terrain_regions'].append({'region_id':'test.solid','terrain_type':'BLOCKED',
            'movement_cost':0,'cells':[{'x':4,'y':6}],'description':'A solid test pillar.'})
        mid=combat._finish_factory_match(bundles,[OWNER,ALLY,FOE],
            {OWNER:'team:factory',ALLY:'team:factory',FOE:'team:opponents'},
            {OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':5,'y':6}},arena,[OWNER,ALLY],[FOE],
            control_modes={a:'MANUAL' for a in (OWNER,ALLY,FOE)},match_seed='hunger-blocked',
            display_name='Hunger blocked aura regression',maximum_rounds=10)['match_id']
        owner_turn(table,mid)
    play(combat,table,mid,'Prepare',target=OWNER)
    return combat,table,mid


def packets(engine, source):
    return [e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and (e.source_definition_id==source or e.payload.get('display_source_id')==source)]


def test_dragon_sky_chooses_two_pays_once_expires_ends_impurity(monkeypatch,tmp_path):
    from combat.flight import profile
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,DRAGON])
    before=reload(combat,mid).state.actors[OWNER].resources[CP]
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide',['dragon_marrow','Predator Step','sky','impure'])
    actor=engine.state.actors[OWNER]
    assert set(_mantle_data(engine)['benefits'])=={'Thick Hide','Predator Step'}
    assert actor.resources[SAT]==7 and actor.resources[CP]==before-1
    assert profile(engine,actor).speed_ft==40
    owner_turn(table,mid,next_turn=True)
    engine=reload(combat,mid)
    assert profile(engine,engine.state.actors[OWNER]).speed_ft==40
    assert act(table,mid,table.state(mid)['menu']['end_turn'])['status']=='COMMITTED'
    engine=reload(combat,mid)
    assert profile(engine,engine.state.actors[OWNER]).speed_ft==0
    assert _mantle_data(engine)['dragon_sign']=='sky'
    _turn_to(table,mid,OWNER)
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide',['normal'])
    gains=[e for e in engine.events if e.event_type=='RESOURCE_GAINED' and e.source_definition_id==DRAGON]
    assert len(gains)==1
    assert engine.state.actors[OWNER].resources[IMP]==6


def test_dragon_scale_first_trigger_only_across_reload(monkeypatch,tmp_path):
    damage={'type':'damage','flat':30,'damage_types':['slashing']}
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,DRAGON],packet=damage)
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['dragon_marrow','Iron Stomach','scale','ordinary'])
    engine=play(combat,table,mid,'Elemental packet',target=OWNER)
    source='action:test.hunger_second.Elemental_packet.'+OWNER
    assert packets(engine,source)[-1].payload['reduced_to']==18  # 3*PB; no key modifier
    assert _mantle_data(engine)['dragon_scale_used'] is True
    owner_turn(table,mid,next_turn=True)
    engine=play(combat,table,mid,'Elemental packet',target=OWNER)
    assert packets(engine,source)[-1].payload['reduced_to']==24  # ordinary PB + key


def test_dragon_breath_only_actual_sphere_elemental_damage_once(monkeypatch,tmp_path):
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,DRAGON])
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['dragon_marrow','Iron Stomach','breath','ordinary'])
    engine=play(combat,table,mid,'Ordinary packet',target=FOE)
    assert not packets(engine,DRAGON)
    engine=play(combat,table,mid,'Elemental packet',target=FOE)
    assert len(packets(engine,DRAGON))==0  # Breath is part of the originating packet.
    assert _mantle_data(engine)['dragon_breath_used'] is True
    source='action:test.hunger_second.Elemental_packet.'+OWNER
    assert packets(engine,source)[-1].payload['damage_type']=='FIRE'
    assert packets(engine,source)[-1].payload['reduced_to']>3
    engine=play(combat,table,mid,'Elemental packet',target=FOE)
    assert len(packets(engine,source))==2
    assert packets(engine,source)[-1].payload['reduced_to']==3
    # Real compilation freezes the same provenance; ordinary weapons are excluded.
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    bundle=compile_character(sheet([BASE,DRAGON,'FIRE_BASE_IGNITE']),actor_id='actor:test.real_provenance')
    assert any(a.get('parameters',{}).get('typed',{}).get('hunger_sphere_damage') for a in bundle['action_catalog']
               if a.get('parameters',{}).get('typed',{}).get('source')=='FIRE_BASE_IGNITE')


def test_breath_can_decline_then_choose_later_after_cold_reload(monkeypatch,tmp_path):
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,DRAGON])
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['dragon_marrow','Iron Stomach','breath','ordinary'])
    engine=play(combat,table,mid,'Elemental packet',['DECLINE'],target=FOE)
    assert not _mantle_data(engine).get('dragon_breath_used')
    engine=play(combat,table,mid,'Elemental packet',['use'],target=FOE)
    assert _mantle_data(engine)['dragon_breath_used'] is True
    assert len(packets(engine,DRAGON))==0  # the bonus is part of the triggering packet
    source='action:test.hunger_second.Elemental_packet.'+OWNER
    assert packets(engine,source)[-1].payload['reduced_to'] > 3


@pytest.mark.parametrize('save_for_half,resistant',[(False,False),(True,False),(False,True)])
def test_breath_retains_packet_save_and_resistance_rounding(monkeypatch,tmp_path,save_for_half,resistant):
    packet=({'type':'save','ability':'DEX','dc':1,
             'on_fail':[{'type':'damage','flat':6,'damage_types':['fire']}],
             'on_success':[{'type':'half_damage'}]} if save_for_half else
             {'type':'damage','flat':6,'damage_types':['fire']})
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,DRAGON],packet=packet,
                                    foe_fire_resistance=resistant)
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['dragon_marrow','Iron Stomach','breath','ordinary'])
    engine=play(combat,table,mid,'Elemental packet',target=FOE)
    source='action:test.hunger_second.Elemental_packet.'+OWNER
    event=packets(engine,source)[-1]
    breath_roll=next(r for r in engine.rolls if r.reason==f'DAMAGE:{DRAGON}')
    divisor=2 if save_for_half or resistant else 1
    assert event.payload['reduced_to']==(6+breath_roll.total)//divisor
    assert _mantle_data(engine)['dragon_breath_used'] is True


def test_breath_skips_immune_packet_and_remains_available_after_reload(monkeypatch,tmp_path):
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,DRAGON],foe_fire_immunity=True)
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['dragon_marrow','Iron Stomach','breath','ordinary'])
    source='action:test.hunger_second.Elemental_packet.'+OWNER
    engine=play(combat,table,mid,'Elemental packet',target=FOE)
    assert not _mantle_data(engine).get('dragon_breath_used')
    assert not packets(engine,source)[-1].payload.get('bonus_component')
    engine=reload(combat,mid)
    assert not _mantle_data(engine).get('dragon_breath_used')
    engine=play(combat,table,mid,'Elemental packet',target=ALLY)
    assert _mantle_data(engine)['dragon_breath_used'] is True
    assert packets(engine,source)[-1].payload['reduced_to'] > 3


def test_breath_skips_immune_confirmed_hit_and_remains_available_after_reload(monkeypatch,tmp_path):
    attack={'type':'attack','attack_kind':'cultivation_ranged','count':1,
            'on_hit':[{'type':'damage','flat':6,'damage_types':['fire']} ]}
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,DRAGON],packet=attack,foe_fire_immunity=True)
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['dragon_marrow','Iron Stomach','breath','ordinary'])
    engine=play(combat,table,mid,'Elemental packet',target=FOE)
    assert not _mantle_data(engine).get('dragon_breath_used')
    engine=reload(combat,mid)
    assert not _mantle_data(engine).get('dragon_breath_used')
    engine=play(combat,table,mid,'Elemental packet',target=ALLY)
    assert _mantle_data(engine)['dragon_breath_used'] is True


def test_breath_critical_doubles_its_dice_in_confirmed_attack_packet(monkeypatch,tmp_path):
    attack={'type':'attack','attack_kind':'cultivation_ranged','count':1,
            'on_hit':[{'type':'damage','flat':6,'damage_types':['fire']} ]}
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,DRAGON],packet=attack)
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['dragon_marrow','Iron Stomach','breath','ordinary'])
    original_load=combat._load_session
    def force_critical_on_load(match_id):
        session=original_load(match_id)
        roller=session.engine.roller
        if not getattr(roller,'_hunger_test_critical',False):
            previous=roller.after_d20
            def critical_attack(roll):
                resolved=previous(roll) if previous else roll
                if roll.reason.startswith('ATTACK:'):
                    natural=int(resolved.natural_result or 1)
                    modifier=int(resolved.total)-natural
                    return resolved.model_copy(update={'natural_result':20,'total':20+modifier})
                return resolved
            roller.after_d20=critical_attack
            roller._hunger_test_critical=True
        return session
    combat._load_session=force_critical_on_load
    engine=play(combat,table,mid,'Elemental packet',target=FOE)
    bonus=next(r for r in engine.rolls if r.reason==f'DAMAGE:{DRAGON}')
    assert len(bonus.dice)==4
    assert _mantle_data(engine)['dragon_breath_used'] is True


def test_scholar_choice_names_actual_creature_and_feature(monkeypatch,tmp_path):
    combat,table,mid=table_fixture(monkeypatch,tmp_path,['HUNGER_BASE_TASTE_THE_QI',SCHOLAR])
    cid=pick(table,mid,'Taste the Qi: Unwilling, concealed nature: oppose Charisma',FOE)
    result=act(table,mid,cid)
    assert result['status']=='REACTION_REQUIRED'
    prompt=result['reaction']
    target_name=reload(combat,mid).state.actors[FOE].display_name
    assert prompt['reaction']=='Monster-Taste Scholar'
    assert prompt['affected']==target_name
    assert prompt['by']==target_name
    assert 'a beast' in prompt['moment'] and 'Taste the Qi' in prompt['moment']
    done=act(table,mid,cid,[{**prompt['context'],'selection':'USE','option_ids':['other']}])
    assert done['status']=='COMMITTED'


def test_demon_king_attack_two_benefits_one_die_and_ending_debt(monkeypatch,tmp_path):
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,KING])
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide',['demon_king','Iron Stomach','attack','cold'])
    assert len(_mantle_data(engine)['benefits'])==2
    assert engine.state.actors[OWNER].resources[SAT]==7
    engine=play(combat,table,mid,'Strike',target=FOE)
    assert len(packets(engine,KING))==1, [(e.event_type,e.payload) for e in engine.events if e.event_type=='ATTACK_ROLLED']
    assert packets(engine,KING)[0].payload['damage_type']=='COLD'
    engine=play(combat,table,mid,'Strike',target=FOE)
    assert len(packets(engine,KING))==1
    owner_turn(table,mid,next_turn=True)
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide',['normal'])
    assert len([e for e in engine.events if e.event_type=='RESOURCE_GAINED' and e.source_definition_id==KING])==1
    assert engine.state.actors[OWNER].resources[IMP]==6


def test_demon_king_attack_reward_can_be_declined_then_spent(monkeypatch,tmp_path):
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,KING])
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['demon_king','Iron Stomach','attack','cold'])
    engine=play(combat,table,mid,'Strike',['DECLINE'],target=FOE)
    assert not _mantle_data(engine).get('demon_king_attack_used')
    engine=play(combat,table,mid,'Strike',['use'],target=FOE)
    assert _mantle_data(engine)['demon_king_attack_used'] is True
    assert len(packets(engine,KING))==1


def test_demon_king_attack_reward_only_damages_the_hit_creature_in_area(monkeypatch,tmp_path):
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,KING])
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['demon_king','Iron Stomach','attack','cold'])
    engine=play(combat,table,mid,'Multi-creature Strike',['use'])
    reward=packets(engine,KING)
    assert len(reward)==1
    assert len(reward[0].target_ids)==1
    assert reward[0].target_ids[0] in (OWNER,ALLY,FOE)
    engine=reload(combat,mid)
    assert _mantle_data(engine)['demon_king_attack_used'] is True


def test_demon_king_resistance_recast_removes_old_type_and_expiry(monkeypatch,tmp_path):
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,KING])
    engine=play(combat,table,mid,'Digestive Mantle: Thick Hide',['demon_king','Iron Stomach','resistance','fire'])
    old={i for i,m in engine.state.actors[OWNER].modifiers.items() if m.target_field=='damage_resistance'}
    assert old
    assert {m.value for m in reload(combat,mid).state.actors[OWNER].modifiers.values()
            if m.target_field=='damage_resistance'}=={'FIRE'}
    engine=play(combat,table,mid,'Early Mantle Recast',['demon_king','Iron Stomach','resistance','cold'])
    assert not old.intersection(engine.state.actors[OWNER].modifiers)
    assert {m.value for m in engine.state.actors[OWNER].modifiers.values()
            if m.target_field=='damage_resistance'}=={'COLD'}
    engine=reload(combat,mid)
    assert {m.value for m in engine.state.actors[OWNER].modifiers.values()
            if m.target_field=='damage_resistance'}=={'COLD'}
    assert not old.intersection(engine.state.actors[OWNER].modifiers)
    owner_turn(table,mid,next_turn=True)
    engine=reload(combat,mid)
    assert not [m for m in engine.state.actors[OWNER].modifiers.values() if m.target_field=='damage_resistance']


@pytest.mark.parametrize('packet,mode',[
    ({'type':'save','ability':'WIS','dc':99,'on_fail':[{'type':'condition','condition':'frightened','applies_to':'target'}]},'ADVANTAGE'),
    ({'type':'save','ability':'WIS','dc':99,'on_fail':[]},'NORMAL'),
])
def test_demon_king_fear_only_affects_frightened_save(monkeypatch,tmp_path,packet,mode):
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,KING],packet=packet)
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['demon_king','Iron Stomach','fear'])
    engine=play(combat,table,mid,'Elemental packet',target=OWNER)
    rolls=[r for r in engine.rolls if r.reason.startswith('SAVE:') and r.actor_id==OWNER]
    assert rolls[-1].mode==mode


@pytest.mark.parametrize('foe_cl,applies',[(5,True),(17,False)])
def test_demon_king_pressure_enemy_lower_realm_only_consumes_actual_attack(monkeypatch,tmp_path,foe_cl,applies):
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,KING],foe_cl=foe_cl)
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['demon_king','Iron Stomach','pressure'])
    _turn_to(table,mid,FOE)
    engine=reload(combat,mid)
    assert not [c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id==PRESSURE]
    assert bool([c for c in engine.state.actors[FOE].conditions.values() if c.condition_id==PRESSURE]) is applies
    engine=play(combat,table,mid,'Strike',target=OWNER)
    rolls=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==FOE]
    assert rolls[-1].payload['mode']==('DISADVANTAGE' if applies else 'NORMAL')
    assert not [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id==PRESSURE]


def test_ai_pressure_uses_known_meal_and_only_enemies_with_ally_in_range(monkeypatch,tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,KING])
    original=combat.controller
    class KnownMeal:
        def choose_primary_action(self, context):
            candidate=next(c for c in context.legal_candidates if c.display_name=='Digestive Mantle: Thick Hide')
            return ManualControllerAdapter(lambda _: (candidate.candidate_id,())).choose_primary_action(context)
        def choose_reaction(self, context):
            answer=original.choose_reaction(context)
            options=None
            if context.reaction_source_id.endswith('hunger_satiety') and 'demon_king' in context.legal_option_ids: options=('demon_king',)
            if context.reaction_source_id.endswith('demon_king_gift'): options=('pressure',)
            if options:
                decision=answer.decision.model_copy(update={'selection':'USE','option_ids':options})
                scores=tuple(s.model_copy(update={'total':int(s.candidate_id.endswith(':USE')),
                    'option_ids':options if s.candidate_id.endswith(':USE') else (), 'components':()})
                    for s in answer.record.scored_alternatives)
                record=answer.record.model_copy(update={'controller_id':'test:known_own_satiety',
                    'selected_candidate_id':f'reaction:{context.reaction_source_id}:USE','selected_option_ids':options,
                    'selected_reaction':decision,'scored_alternatives':scores,
                    'explanation':'Use the creature’s own prepared Demon-King Satiety and pressure gift.'})
                return answer.model_copy(update={'decision':decision,'record':record})
            return answer
        def __getattr__(self,name): return getattr(original,name)
    combat.controller=KnownMeal()
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    try:
        assert table.auto_step(mid,table.state(mid)['last_sequence'])['status']=='COMMITTED'
    finally:
        combat.controller=original
    engine=reload(combat,mid)
    assert _mantle_data(engine)['demon_king_gift']=='pressure'
    # The player-owned end-turn transport advances an automatic owner, then
    # restores automatic mode before another creature starts in the aura.
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='MANUAL')
    assert act(table,mid,table.state(mid)['menu']['end_turn'])['status']=='COMMITTED'
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    _turn_to(table,mid,FOE)
    engine=reload(combat,mid)
    assert any(c.condition_id==PRESSURE for c in engine.state.actors[FOE].conditions.values())
    assert not any(c.condition_id==PRESSURE for c in engine.state.actors[ALLY].conditions.values())
    assert not any(c.condition_id==PRESSURE for c in engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('qualifies,bonus', [('qualifying',1),('other',0)])
def test_scholar_bonus_only_declared_qualifying_opposed_hunger_roll(monkeypatch,tmp_path,qualifies,bonus):
    combat,table,mid=table_fixture(monkeypatch,tmp_path,['HUNGER_BASE_TASTE_THE_QI',SCHOLAR])
    engine=play(combat,table,mid,'Taste the Qi: Unwilling, concealed nature: oppose Charisma',[qualifies],target=FOE)
    events=[e for e in engine.events if e.event_type=='CHECK_ROLLED' and e.actor_id==OWNER]
    assert events
    assert events[-1].payload['actor']['modifier']==6+bonus


def test_pressure_does_not_cross_solid_pillar(monkeypatch,tmp_path):
    from combat.targeting import line_of_effect
    combat,table,mid=table_fixture(monkeypatch,tmp_path,[BASE,KING],blocked=True)
    play(combat,table,mid,'Digestive Mantle: Thick Hide',['demon_king','Iron Stomach','pressure'])
    _turn_to(table,mid,FOE)
    engine=reload(combat,mid)
    assert engine._distance_actor_to_actor(engine.state.actors[OWNER],engine.state.actors[FOE])==10
    assert not line_of_effect(engine,engine.state.actors[OWNER],target=engine.state.actors[FOE])
    assert not any(c.condition_id==PRESSURE for c in engine.state.actors[FOE].conditions.values())
    assert not [r for r in engine.rolls if r.actor_id==FOE and KING in r.reason]


@pytest.mark.parametrize('known,bonus',[(False,0),(True,1)])
def test_ai_scholar_unknown_source_declines_known_perceived_source_gets_bonus(monkeypatch,tmp_path,known,bonus):
    from tests.test_a2_hunger_fix_round import ai_step
    combat,table,mid=table_fixture(monkeypatch,tmp_path,['HUNGER_BASE_TASTE_THE_QI',SCHOLAR])
    original=combat.controller
    class KnownSource:
        def choose_reaction(self, context):
            answer=original.choose_reaction(context)
            if known and context.reaction_source_id.endswith('scholar_source'):
                assert 'qualifying' in context.legal_option_ids
                opts=('qualifying',)
                decision=answer.decision.model_copy(update={'selection':'USE','option_ids':opts})
                scores=tuple(s.model_copy(update={'total':int(s.candidate_id.endswith(':USE')),
                    'option_ids':opts if s.candidate_id.endswith(':USE') else (), 'components':()})
                    for s in answer.record.scored_alternatives)
                record=answer.record.model_copy(update={'controller_id':'test:known_perceived_source',
                    'selected_candidate_id':f'reaction:{context.reaction_source_id}:USE',
                    'selected_option_ids':opts,'selected_reaction':decision,'scored_alternatives':scores,
                    'explanation':'Read the visible creature already known to this character as a beast.'})
                return answer.model_copy(update={'decision':decision,'record':record})
            return answer
        def __getattr__(self,name):return getattr(original,name)
    combat.controller=KnownSource()
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    try:
        assert ai_step(combat,table,mid,'Taste the Qi: Unwilling, concealed nature: oppose Charisma',target=FOE)['status']=='COMMITTED'
    finally:
        combat.controller=original
    engine=reload(combat,mid)
    checks=[e for e in engine.events if e.event_type=='CHECK_ROLLED' and e.actor_id==OWNER]
    assert checks[-1].payload['actor']['modifier']==6+bonus
