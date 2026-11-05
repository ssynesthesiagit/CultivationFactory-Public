"""Dreams second pass: accepted table/session transactions and cold disk replay."""
import copy
import json
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
DROWSY='condition:typed.drowsy'
SLEEP='condition:typed.dream_sleep'
WAKE='system:combat.awaken_dream_sleeper'
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn

SOV = 'tianxia.talent.dreams.dream_sovereign_incarnation'
SHELTER = 'tianxia.talent.dreams.symbolic_shelter'
GLIMPSE = 'TAL_DREAM_NIGHTMARE_GLIMPSE'
SLEEP_ID = 'TAL_DREAM_SLEEP'
AUTH = json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']


def seal(bundle, name, effects, *, source='test:setup', target='ANY_CREATURE', save_dc=100):
    """Seal deterministic setup/delivery before genesis, never substitute live engine methods."""
    aid='action:test.dreams.'+bundle['actor_id'].rsplit('.',1)[-1]+'.'+name.replace(' ','_')
    row={'source_definition_id':aid,'display_name':name,'owner_id':bundle['actor_id'],
         'economy':'NONE','resolution_kind':'TYPED','target_kind':target,'range_ft':60,'costs':[],
         'parameters':{'typed':{'source':source,'effects':copy.deepcopy(effects),
             'numbers':{'cl':15,'pb':4,'save_dc':save_dc,'attack_bonus':100},'riders':[],
             'duration':{'kind':'instant'}},'expected_damage':0}}
    bundle['action_catalog'].append(row);bundle['actor_template']['action_ids'].append(aid)
    bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)


def cast(combat, table, mid, name, *, target=None, direct=False, at=None):
    c=candidate(combat,mid,name,target=target,at=at)
    if direct:
        session=combat._load_session(mid)
        session.mechanical.execute_intent(ActionIntent(intent_id='a2-dreams-direct',decision_id=c.decision_id,
            candidate_id=c.candidate_id,state_version=c.state_version,actor_id=session.engine.state.current_actor_id,
            target_ids=c.target_ids,destination=c.destination))
    else:
        settle(table,mid,c.candidate_id)
    return c


@pytest.mark.parametrize('direct',[False,True])
def test_incarnation_native_flight_hover_passage_and_expiry(tmp_path,direct):
    combat,table,mid=fixture(tmp_path,[SOV],ask=False,seed='A2DREAMS-MOVEMENT')
    cast(combat,table,mid,'Dream-Sovereign Incarnation',direct=direct)
    e=reload(tmp_path,mid);a=e.state.actors[OWNER]
    from combat import flight
    from combat import ext
    assert e._effective_speed(a)==30
    assert flight.profile(e,a).speed_ft==40 and flight.profile(e,a).hover
    assert 'difficult' in ext.run('pass_through',e,a,e.state.actors[FOE])
    assert a.resources['resource:core.qi']==85
    move=next(r for r in table.state(mid)['menu']['moves'] if r['destination']=={'x':3,'y':6,'z':1})
    settle(table,mid,move['candidate_id'])
    e=reload(tmp_path,mid);assert e.state.actors[OWNER].position.z==1
    # Ten owner turns expire both native body and stance; the flight engine lands/falls normally.
    for _ in range(10):
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    e=reload(tmp_path,mid);a=e.state.actors[OWNER]
    assert flight.profile(e,a).speed_ft==0 and a.position.z==0
    assert 'difficult' not in ext.run('pass_through',e,a,e.state.actors[FOE])


def test_sovereign_ai_seed_enemy_with_ally_in_range(tmp_path):
    combat,table,mid=fixture(tmp_path,[SOV],ask=False,seed='A2DREAMS-SEED')
    cast(combat,table,mid,'Dream-Sovereign Incarnation')
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    session=combat._load_session(mid)
    c=next(c for c in session.engine.legal_candidates() if c.kind.value=='END_TURN')
    session.mechanical.execute_intent(ActionIntent(intent_id='seed-end',decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version,actor_id=OWNER))
    turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    from combat.typed_executor import bears_mark
    assert bears_mark(e.state.actors[FOE],OWNER,'Dream Seed')
    assert not bears_mark(e.state.actors[ALLY],OWNER,'Dream Seed')


@pytest.mark.parametrize('target,nightmare,inside,direct',[
    (ALLY,True,True,False),(FOE,True,True,False),(OWNER,True,True,False),(ALLY,False,True,True),(ALLY,True,False,False)])
def test_symbolic_shelter_only_allies_inside_and_nightmare_packets(tmp_path,target,nightmare,inside,direct):
    def setup(bundles):
        # Real action packets with exact sealed printed source classify the damage.
        for b in bundles:
            seal(b,'Nightmare packet',[{'type':'damage','damage_types':['psychic'],'flat':11,'applies_to':'target'}],source=GLIMPSE)
            seal(b,'Other psychic packet',[{'type':'damage','damage_types':['psychic'],'flat':11,'applies_to':'target'}],source='TAL_DREAM_DREAM_NEEDLE')
    combat,table,mid=fixture(tmp_path,[SHELTER],ask=False,seed='A2DREAMS-SHELTER',bundle_transform=setup,
        ally_position={'x':4 if inside else 8,'y':6})
    e=combat._load_session(mid).engine
    shape=next(a.display_name for a in e.action_catalog.values() if a.owner_id==OWNER
               and a.parameters.get('shape_talents')==[SHELTER])
    cast(combat,table,mid,shape)
    cast(combat,table,mid,'Dreamscape',at=(4,6),direct=direct)
    e=reload(tmp_path,mid)
    assert any(z.active and 'Symbolic Shelter' in z.trigger_profile.get('talents',[]) for z in e.state.zones.values())
    # Inspect admission before the packet: damage to the creator may end Concentration.
    from combat import zones
    assert any((r.get('rule') or {}).get('dream_nightmare_resistance') for z,r in zones.current_inside_grants(e,e.state.actors[ALLY]).values())==inside
    for excluded in (FOE,OWNER):
        assert not any((r.get('rule') or {}).get('dream_nightmare_resistance') for z,r in zones.current_inside_grants(e,e.state.actors[excluded]).values())
    before=e.state.actors[target].current_hp
    cast(combat,table,mid,'Nightmare packet' if nightmare else 'Other psychic packet',target=target,direct=direct)
    e=reload(tmp_path,mid)
    assert before-e.state.actors[target].current_hp==(5 if target==ALLY and nightmare and inside else 11)


@pytest.mark.parametrize('direct',[False,True])
def test_sleep_awaken_action_all_combatants_keeps_prone_and_spends_action(tmp_path,direct):
    def setup(bundles):
        seal(bundles[0],'Prepare drowsiness',[{'type':'drowsy','expires_on':'UNTIL_REMOVED'}])
    combat,table,mid=fixture(tmp_path,[SLEEP_ID],ask=False,owner_dc=100,
        seed='A2DREAMS-AWAKEN',bundle_transform=setup,foe_position={'x':5,'y':6})
    cast(combat,table,mid,'Prepare drowsiness',target=FOE)
    cast(combat,table,mid,'Sleep',target=FOE,direct=direct)
    e=reload(tmp_path,mid);assert any(c.condition_id==SLEEP for c in e.state.actors[FOE].conditions.values())
    turn(table,mid,ALLY)
    cast(combat,table,mid,'Awaken Dream Sleep',target=FOE,direct=direct)
    e=reload(tmp_path,mid);foe=e.state.actors[FOE]
    assert not any(c.condition_id==SLEEP for c in foe.conditions.values())
    assert any(c.condition_id=='condition:typed.prone' for c in foe.conditions.values())
    assert not e.state.actors[ALLY].action_available
    assert not any(c.source_definition_id==WAKE for c in e.legal_candidates())


def test_ai_awaken_admits_only_perceived_allied_sleepers(tmp_path):
    def setup(bundles):
        # The shipped condition row is the setup; both recipients are in reach.
        row=AUTH[SLEEP_ID]['effects'][1]['on_fail'][0]
        seal(bundles[0],'Prepare sleepers',[row])
    combat,table,mid=fixture(tmp_path,[SLEEP_ID],ask=False,bundle_transform=setup,
        seed='A2DREAMS-AI-AWAKEN',foe_position={'x':3,'y':7})
    cast(combat,table,mid,'Prepare sleepers',target=ALLY)
    cast(combat,table,mid,'Prepare sleepers',target=FOE)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    e=reload(tmp_path,mid)
    wakes=[c for c in e.legal_candidates() if c.source_definition_id==WAKE]
    assert wakes and all(c.target_ids==(ALLY,) for c in wakes)
    # Accept the AI-legal candidate through the session, with both sides present.
    cast(combat,table,mid,'Awaken Dream Sleep',target=ALLY,direct=True)
    e=reload(tmp_path,mid)
    assert not any(c.condition_id==SLEEP for c in e.state.actors[ALLY].conditions.values())
    assert any(c.condition_id==SLEEP for c in e.state.actors[FOE].conditions.values())


def test_sovereign_committed_creature_crossing_costs_double_and_keeps_oa(tmp_path):
    combat,table,mid=fixture(tmp_path,[SOV],ask=False,seed='A2DREAMS-CROSS')
    cast(combat,table,mid,'Dream-Sovereign Incarnation')
    from combat.movement_routes import explicit_candidate
    from combat.gate2_runtime_models import Position
    session=combat._load_session(mid)
    path=tuple(Position(x=x,y=6) for x in (3,4,5))
    c=explicit_candidate(session.engine,OWNER,path,'walk')
    assert c.movement_cost_ft==15
    before=session.engine.state.actors[OWNER].movement_remaining_ft
    session.mechanical.execute_intent(ActionIntent(intent_id='sovereign-cross',decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version,actor_id=OWNER,destination=c.destination,
        movement_path=path,movement_mode='walk'))
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position==path[-1]
    assert e.state.actors[OWNER].movement_remaining_ft==before-15
    from combat import ext
    assert False not in ext.run('opportunity_allowed',e,e.state.actors[FOE],e.state.actors[OWNER])


@pytest.mark.parametrize('recipient,kind,direct',[(ALLY,'frightened',False),(OWNER,'psychic',True),
    (FOE,'frightened',False),(ALLY,'fire',False)])
def test_dream_ward_adjusts_actual_save_only_for_printed_allied_scope(tmp_path,recipient,kind,direct):
    ward='TAL_DREAM_DREAM_WARD'
    def setup(bundles):
        outcome=({'type':'damage','damage_types':[kind],'flat':11,'applies_to':'target'} if kind in ('psychic','fire') else
                 {'type':'condition','condition':'frightened','applies_to':'target','expires_on':'END_OF_TARGET_NEXT_TURN'})
        for b in bundles:
            seal(b,'Save packet',[{'type':'save','ability':'wis','on_fail':[outcome],'on_success':[]}],save_dc=11 if kind=='psychic' else 100)
    combat,table,mid=fixture(tmp_path,[ward],ask=True,bundle_transform=setup,seed='A2DREAMS-WARD')
    turn(table,mid,FOE)
    # Accepted player's choice: original die is retained, even if the owner spends
    # on a save the bonus cannot rescue. The test is about timing, not AI strategy.
    c=candidate(combat,mid,'Save packet',target=recipient)
    picks={'reaction:typed.TAL_DREAM_DREAM_WARD':'first'}
    if direct:
        from combat.gate2_runtime_models import ReactionDecision
        session=combat._load_session(mid)
        # Table preview supplies a concrete controller-owned answer, then the
        # session transaction receives exactly that answer transport.
        from tests.test_r9i_karma_persistence import act
        result=act(table,mid,c.candidate_id)
        if result['status']=='REACTION_REQUIRED':
            p=result['reaction']
            assert 'fails' not in p['trigger'].lower() and 'DC 11' not in p['trigger']
            answer={**p['context'],'selection':'USE'}
            if p.get('choice'): answer['option_ids']=[p['choice']['options'][0]['id']]
            session=combat._load_session(mid)
            session.mechanical.execute_intent(ActionIntent(intent_id='ward-direct',decision_id=c.decision_id,
                candidate_id=c.candidate_id,state_version=c.state_version,actor_id=FOE,target_ids=c.target_ids,
                reaction_decisions=(ReactionDecision.model_validate(answer),)))
        else:
            assert result['status']=='COMMITTED'
    else:
        # d20-rewrite consent is a ordinary reaction rather than a Needle menu.
        settle(table,mid,c.candidate_id,choices=picks)
    e=reload(tmp_path,mid)
    rewritten=[v for v in e.events if v.event_type=='D20_REWRITTEN' and v.source_definition_id==ward]
    qualifies=recipient in (ALLY,OWNER) and kind!='fire'
    assert bool(rewritten)==qualifies
    assert e.state.actors[OWNER].resources['resource:core.qi']==100-int(qualifies)
    assert e.state.actors[OWNER].reaction_available== (not qualifies)
    if qualifies:
        p=rewritten[-1].payload
        assert p['original']['natural_result']==p['result']['natural_result']
        assert p['result']['total']==p['original']['total']+4
        if kind=='psychic':
            assert e.state.actors[recipient].current_hp==e.state.actors[recipient].maximum_hp
            saved=[v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==recipient][-1]
            assert saved.payload['success'] and saved.payload['total']==p['result']['total']


def test_shelter_genuine_nightmare_glimpse_and_concentration_end(tmp_path):
    def setup(bundles):
        seal(bundles[0],'Prepare drowsiness',[{'type':'drowsy','expires_on':'UNTIL_REMOVED'}])
        seal(bundles[0],'Become incapacitated',[{'type':'condition','condition':'incapacitated','applies_to':'self','expires_on':'END_OF_TARGET_NEXT_TURN'}],target='SELF')
    combat,table,mid=fixture(tmp_path,[SHELTER],ask=False,seed='A2DREAMS-GENUINE-NIGHTMARE',
        bundle_transform=setup,foe_sheet=sheet([GLIMPSE],cl=15,dc=100))
    e=combat._load_session(mid).engine
    shape=next(a.display_name for a in e.action_catalog.values() if a.owner_id==OWNER and a.parameters.get('shape_talents')==[SHELTER])
    cast(combat,table,mid,shape)
    cast(combat,table,mid,'Dreamscape',at=(4,6))
    cast(combat,table,mid,'Prepare drowsiness',target=ALLY)
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.actors[ALLY].current_hp
    cast(combat,table,mid,'Nightmare Glimpse',target=ALLY)
    e=reload(tmp_path,mid)
    rolled=[v for v in e.events if v.event_type=='DAMAGE_ROLLED' and v.actor_id==FOE][-1]
    assert before-e.state.actors[ALLY].current_hp==rolled.payload['total']//2
    assert rolled.payload['expression'].startswith('4d6')
    turn(table,mid,OWNER)
    # Native incapacitation ends Concentration, then the entire standing boon.
    cast(combat,table,mid,'Become incapacitated')
    e=reload(tmp_path,mid)
    from combat import zones
    assert not any((r.get('rule') or {}).get('dream_nightmare_resistance') for z,r in zones.current_inside_grants(e,e.state.actors[ALLY]).values())


def test_dream_ward_allied_save_does_not_require_sight(tmp_path):
    ward='TAL_DREAM_DREAM_WARD'
    def setup(bundles):
        seal(bundles[0],'Become blinded',[{'type':'condition','condition':'blinded','applies_to':'self','expires_on':'UNTIL_REMOVED'}],target='SELF')
        seal(bundles[2],'Frightening save',[{'type':'save','ability':'wis','on_fail':[{'type':'condition','condition':'frightened','expires_on':'END_OF_TARGET_NEXT_TURN'}]}])
    combat,table,mid=fixture(tmp_path,[ward],ask=True,bundle_transform=setup,seed='A2DREAMS-WARD-SIGHT')
    cast(combat,table,mid,'Become blinded')
    turn(table,mid,FOE)
    c=candidate(combat,mid,'Frightening save',target=ALLY)
    from tests.test_r9i_karma_persistence import act
    result=act(table,mid,c.candidate_id)
    assert result['status']=='REACTION_REQUIRED'
    from combat.gate2_runtime_models import ReactionDecision
    prompt=result['reaction']
    answer={**prompt['context'],'selection':'USE'}
    session=combat._load_session(mid)
    session.mechanical.execute_intent(ActionIntent(intent_id='ward-blind',decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version,actor_id=FOE,target_ids=c.target_ids,
        reaction_decisions=(ReactionDecision.model_validate(answer),)))
    e=reload(tmp_path,mid)
    assert any(v.event_type=='D20_REWRITTEN' and v.source_definition_id==ward for v in e.events)
    assert e.state.actors[OWNER].resources['resource:core.qi']==99
    assert not e.state.actors[OWNER].reaction_available


@pytest.mark.parametrize('ward_priority',[1,100])
def test_dream_ward_bonus_composes_with_another_owners_save_reroll(tmp_path,ward_priority):
    ward='TAL_DREAM_DREAM_WARD'
    candle='tianxia.tradition.spirit.candlemaker.feature.candle_against_the_dark'
    from combat.ext import d20_rewrite
    rule=d20_rewrite.RULES['dream_ward']
    assert rule.additive_save_bonus is not None
    old=rule.priority
    rule.priority=ward_priority
    try:
        def setup(bundles):
            # Candle spends Resonance; Ward's owner keeps the Qi pool used
            # by Dream Ward's printed CP cost.
            ally=bundles[1]
            ally['actor_template']['resources'].append({'resource_id':'resource:core.resonance','initial':30,'maximum':30})
            ally.pop('bundle_sha256',None)
            ally['bundle_sha256']=canonical_sha256(ally)
            seal(bundles[0],'Frightening save',[{'type':'save','ability':'wis','on_fail':[
                {'type':'condition','condition':'frightened','expires_on':'END_OF_TARGET_NEXT_TURN'}]}],save_dc=100)
        combat,table,mid=fixture(tmp_path,[ward],ask=True,ally_talents=[candle],bundle_transform=setup,
                                 seed=f'A2DREAMS-WARD-COMPOSE-{ward_priority}')
        session=combat._load_session(mid)
        assert any(holder.feature_id==candle for _rule,holder in d20_rewrite._holders(session.engine))
        c=candidate(combat,mid,'Frightening save',target=ALLY)
        prompts=settle(table,mid,c.candidate_id,choices={
            f'reaction:typed.{ward}':'first',
            f'reaction:typed.{candle}':'first',
        })
        assert any(p['context']['reaction_source_id']==f'reaction:typed.{ward}' for p in prompts)
        e=reload(tmp_path,mid)
        rewrites=[v for v in e.events if v.event_type=='D20_REWRITTEN']
        assert len(rewrites)==1 and rewrites[0].source_definition_id==candle
        save=[v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==ALLY][-1]
        assert rewrites[0].payload['result']['modifier']==rewrites[0].payload['original']['modifier']+4
        assert save.payload['total']==rewrites[0].payload['result']['total']
        assert e.state.actors[OWNER].resources['resource:core.qi']==99
        assert not e.state.actors[OWNER].reaction_available
        assert not e.state.actors[ALLY].reaction_available
    finally:
        rule.priority=old


def test_dream_ward_rescue_suppresses_later_failed_save_rewrite_after_reload(tmp_path):
    ward='TAL_DREAM_DREAM_WARD'
    candle='tianxia.tradition.spirit.candlemaker.feature.candle_against_the_dark'
    from combat.ext import d20_rewrite
    def setup(bundles):
        ally=bundles[1]
        ally['actor_template']['resources'].append({'resource_id':'resource:core.resonance','initial':30,'maximum':30})
        ally.pop('bundle_sha256',None)
        ally['bundle_sha256']=canonical_sha256(ally)
        seal(bundles[0],'Frightening save',[{'type':'save','ability':'wis','on_fail':[
            {'type':'condition','condition':'frightened','expires_on':'END_OF_TARGET_NEXT_TURN'}]}],save_dc=18)
    combat,table,mid=fixture(tmp_path,[ward],ask=True,ally_talents=[candle],bundle_transform=setup,
                             seed='A2DREAMS-WARD-RESCUED-SAVE')
    c=candidate(combat,mid,'Frightening save',target=ALLY)
    prompts=settle(table,mid,c.candidate_id,choices={f'reaction:typed.{ward}':'first'})
    e=reload(tmp_path,mid)
    save=[v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==ALLY][-1]
    rewrites=[v for v in e.events if v.event_type=='D20_REWRITTEN' and v.source_definition_id==ward]
    assert len(rewrites)==1
    adjustment=rewrites[0].payload
    # This seed rolls 14 + 2: DC 18 fails before Ward and succeeds with +4.
    assert adjustment['original']['total'] < save.payload['dc'] <= adjustment['result']['total']
    assert adjustment['result']['natural_result']==adjustment['original']['natural_result']
    assert adjustment['result']['modifier']==adjustment['original']['modifier']+4
    assert save.payload['success'] and save.payload['total']==adjustment['result']['total']
    assert not any(p['context']['reaction_source_id']==f'reaction:typed.{candle}' for p in prompts)
    assert e.state.actors[ALLY].resources['resource:core.resonance']==30
    assert e.state.actors[OWNER].resources['resource:core.qi']==99
    assert not e.state.actors[OWNER].reaction_available
    assert e.state.actors[ALLY].reaction_available


def test_dream_ward_bonus_survives_resisted_hostile_replacement_after_reload(tmp_path):
    ward='TAL_DREAM_DREAM_WARD'
    disaster='TAL_FATE_REWRITE_THE_DISASTER'
    def setup(bundles):
        # The affected ally resists reliably so the hostile replacement keeps the
        # original die; Ward's already-paid additive bonus must still reach SAVE_ROLLED.
        ally=bundles[1]
        ally['actor_template']['saving_throws']['CHA']=100
        ally.pop('bundle_sha256',None)
        ally['bundle_sha256']=canonical_sha256(ally)
        seal(bundles[0],'Frightening save',[{'type':'save','ability':'wis','on_fail':[
            {'type':'condition','condition':'frightened','expires_on':'END_OF_TARGET_NEXT_TURN'}]}],save_dc=11)
    combat,table,mid=fixture(tmp_path,[ward],ask=True,foe_sheet=sheet([disaster]),bundle_transform=setup,
                             seed='A2DREAMS-WARD-RESISTED-REPLACEMENT')
    c=candidate(combat,mid,'Frightening save',target=ALLY)
    prompts=settle(table,mid,c.candidate_id,choices={
        f'reaction:typed.{ward}':'first', 'choice:needle.rewrite_the_disaster':'1'})
    e=reload(tmp_path,mid)
    ward_events=[v for v in e.events if v.event_type=='D20_REWRITTEN' and v.source_definition_id==ward]
    assert len(ward_events)==1
    ward_adjustment=ward_events[0].payload
    assert ward_adjustment['original']['natural_result']==ward_adjustment['result']['natural_result']
    assert ward_adjustment['result']['modifier']==ward_adjustment['original']['modifier']+4
    saves=[v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==ALLY]
    # The nested Rewrite resistance save occurs before the outer action save.
    # Select each by its event semantics instead of relying on append order.
    resistance_saves=[v for v in saves
                      if v.payload['reason'].endswith(':CHA')]
    action_saves=[v for v in saves
                  if v.payload['reason'].endswith(':WIS')]
    assert len(resistance_saves)==1
    resistance_save=resistance_saves[0]
    assert resistance_save.payload['success']
    assert resistance_save.payload['modifier']>=100
    assert len(action_saves)==1
    action_save=action_saves[0]
    assert action_save.payload['total']==ward_adjustment['result']['total']
    assert action_save.payload['success']==(
        ward_adjustment['result']['total']>=action_save.payload['dc'])
    assert e.state.actors[OWNER].resources['resource:core.qi']==99
    assert not e.state.actors[OWNER].reaction_available
    assert e.state.actors[FOE].resources['resource:core.qi']==88
    assert not e.state.actors[FOE].reaction_available
    assert any('resists Rewrite the Disaster' in str((v.payload or {}).get('log') or '')
               for v in e.events if v.event_type=='PASSIVE_TRIGGERED')
    # Rewrite the Disaster asks its owner which natural die to use.
    replacement_prompts=[p for p in prompts
                         if p['context']['reaction_source_id']=='choice:needle.rewrite_the_disaster']
    assert replacement_prompts
    assert all(p['context']['reactor_id']==FOE for p in replacement_prompts)
    assert all({o['id'] for o in p['choice']['options']}=={'1','20'} for p in replacement_prompts)
