"""Native Open School acquisition -> journey -> table commit -> cold replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT,sheet
from tests.worker2_support import settle,turn,candidate,reload
PARENT='tianxia.subpath.qi.lantern_keeper'
P=PARENT+'.feature.'
OWNER='actor:factory.lantern-keeper'
ALLY='actor:factory.traveler'
FOE='actor:factory.raider'
ALL=[P+s for s in ('light_the_way','lantern_road','lantern_passage','hold_the_departing_soul','ten_thousand_lantern_road')]
POS={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':7,'y':6}}

def journey(tmp_path,cl=18,*,foe_ids=(),ally_hp=60,owner_ids=()):
    docs=[sheet(owner_ids,cl=cl,name='Wren'),sheet([],cl=cl,name='Tobin'),sheet(foe_ids,cl=cl,name='Mara')]
    docs[0]['path_and_subpath']={**docs[0].get('path_and_subpath',{}),'path_record_ids':['tianxia.path.qi_cultivation'],
        'paths':[{'path_id':'tianxia.path.qi_cultivation','attainment':cl}]}
    docs[1]['ability_scores_and_statistics']['hit_points']['maximum']=ally_hp
    for aid,doc in zip(POS,docs):
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.');folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    combat=CombatService(ROOT,tmp_path)
    s=combat.create_journey(project_ids=[a.removeprefix('actor:factory.') for a in POS],arena_id='battlefield:factory_pillar_arena',
        positions=POS,base_paces={a:1000 for a in POS},control_modes={a:'MANUAL' for a in POS})
    return combat,s

def play(tmp_path,cl=18,*,lantern_positions=(),max_rounds=50,**kw):
    combat,s=journey(tmp_path,cl,**kw)
    s=combat.journey_acquire_source(s['journey_id'],s['revision'],OWNER,PARENT,{})
    for point in lantern_positions:s=combat.journey_act(s['journey_id'],s['revision'],OWNER,'lantern_create',{'position':point})
    mid=combat.journey_start_combat(s['journey_id'],s['revision'],{OWNER:'team:guides',ALLY:'team:guides',FOE:'team:raiders'},positions=POS,maximum_rounds=max_rounds)['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,OWNER)
    return combat,table,mid

def cast(combat,table,mid,name,picks=None):
    return settle(table,mid,candidate(combat,mid,name).candidate_id,picks=picks or {})

def lamps(engine):
    return [o for o in engine.state.objects.values() if not o.destroyed and o.object_kind=='guiding_lantern']

def create(combat,table,mid,point='cell:3,6'):
    return cast(combat,table,mid,'Create Guiding Lantern',{'choice:needle.lantern_lantern_form':'projected','choice:needle.lantern_lantern_location':point})

def test_acquisition_is_native_exclusive_persisted_and_default_inert(tmp_path):
    combat,s=journey(tmp_path);jid=s['journey_id']
    assert not any(r.get('block')=='lantern_keeper' for r in s['actors'][OWNER]['bundle']['typed_passives'])
    before=combat.journey_state(jid)
    with pytest.raises(ValueError):combat.journey_acquire_source(jid,s['revision'],ALLY,PARENT,{})
    assert combat.journey_state(jid)==before
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    assert {r['feature_id'] for r in s['actors'][OWNER]['bundle']['typed_passives'] if r.get('block')=='lantern_keeper'}==set(ALL)
    assert any(e['kind']=='LANTERN_KEEPER_ACQUIRED' for e in s['events'])
    assert CombatService(ROOT,tmp_path).journey_state(jid)==s
    with pytest.raises(ValueError):combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})

@pytest.mark.parametrize('cl,count',[(2,0),(3,1),(5,1),(6,2),(9,2),(10,3),(13,3),(14,4),(17,4),(18,5)])
def test_progression_thresholds(cl,count):
    b=compile_character(sheet(ALL,cl=cl),actor_id=OWNER)
    assert len([r for r in b['typed_passives'] if r.get('block')=='lantern_keeper'])==count

def test_create_paid_native_profile_no_space_and_cold_replay(tmp_path):
    combat,table,mid=play(tmp_path);prompts=create(combat,table,mid)
    e=reload(tmp_path,mid);a=e.state.actors[OWNER]
    assert len(lamps(e))==1
    o=lamps(e)[0]
    assert (o.ac,o.current_hp,o.maximum_hp)==(17,36,36)
    assert set(o.damage_immunities)=={'FIRE','POISON','PSYCHIC'} and o.position==a.position
    assert a.resources['resource:core.qi']==99 and not a.action_available
    assert o.component['hover'] and o.component['speed_ft']==20
    assert not o.component['blocks'] and not o.component['creature'] and not o.component['cover']
    assert prompts


def test_journey_lantern_limit_expiry_custody_and_native_passage(tmp_path):
    combat,s=journey(tmp_path);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    first_id=None
    for x in (3,5,6,8,9):
        s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':{'x':x,'y':6}})
        first_id=first_id or next(iter(s['runtime_objects']))
    live=[o for o in s['runtime_objects'].values() if not o['destroyed']]
    assert len(live)==4 and s['runtime_objects'][first_id]['destroyed']
    before=combat.journey_state(jid)
    with pytest.raises(ValueError):combat.journey_act(jid,s['revision'],ALLY,'lantern_move',{'object_id':live[0]['object_id'],'position':{'x':4,'y':6}})
    assert combat.journey_state(jid)==before
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_move',{'object_id':live[0]['object_id'],'position':{'x':3,'y':6}})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_passage',{'first':live[0]['object_id'],'second':live[-1]['object_id'],'position':{'x':9,'y':7}})
    assert s['actors'][OWNER]['position']=={'x':9,'y':7,'z':0}
    assert s['actors'][OWNER]['resources']['resource:core.qi']==92
    s=combat.journey_act(jid,s['revision'],OWNER,'wait',{'seconds':28800})
    cold=CombatService(ROOT,tmp_path).journey_state(jid)
    records=json.loads(cold['actors'][OWNER]['source_states'][PARENT]['objects'])
    assert records and all(o['destroyed'] for o in records)


def test_passage_declares_both_endpoints_and_willing_passenger_then_replays(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER],{'x':10,'y':6}])
    prompts=cast(combat,table,mid,'Lantern Passage',{
        'choice:needle.lantern_passage_endpoints_and_arrival':'first',
        'choice:needle.lantern_carry_traveler':ALLY,
        'choice:needle.fact_admission.carry_traveler':'willing',
        'choice:needle.lantern_traveler_adjacent_arrival':'first'})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position!=e.state.actors[ALLY].position
    assert e.grid.distance_ft(e.state.actors[OWNER].position,e.state.actors[ALLY].position)<=5
    assert e.state.actors[OWNER].resources['resource:core.qi']==93
    assert not e.state.actors[OWNER].bonus_action_available
    moves=[ev for ev in e.events if ev.event_type=='MOVEMENT_COMMITTED' and ev.payload.get('teleport')]
    assert {OWNER,ALLY}<={ev.actor_id for ev in moves} and all(ev.payload.get('cost_ft')==0 for ev in moves)
    assert any(p['context'].get('reactor_id')==ALLY and p['context']['reaction_source_id']=='choice:needle.fact_admission.carry_traveler' for p in prompts)
    assert not any(c.display_name=='Lantern Passage' for c in e.legal_candidates())


def test_carry_refusal_does_not_imply_willing_or_spend_extra_qi(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER],{'x':10,'y':6}])
    cast(combat,table,mid,'Lantern Passage',{'choice:needle.lantern_carry_traveler':ALLY,'choice:needle.fact_admission.carry_traveler':None})
    e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].position.x==4
    assert e.state.actors[OWNER].resources['resource:core.qi']==95


def test_field_paid_once_concentration_discount_and_start_step(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER],{'x':10,'y':6}])
    cast(combat,table,mid,'Ten Thousand Lantern Road',{
        'choice:needle.lantern_field_center':'cell:3,6','choice:needle.lantern_protected_allies':[OWNER,ALLY]})
    cast(combat,table,mid,'Lantern Passage',{'choice:needle.lantern_carry_traveler':None})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.qi']==89
    assert e.state.actors[OWNER].concentration
    assert len([z for z in e.state.zones.values() if z.active and z.trigger_profile.get('placed',{}).get('tag')=='ten_thousand_lantern_road'])==1
    assert not any(c.display_name=='Ten Thousand Lantern Road' for c in e.legal_candidates())
    assert not e.state.actors[ALLY].temporary_hp, 'Extinction HP must not be granted at field activation'


def test_guiding_lantern_move_native_once_and_preserves_ordinary_movement(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER]])
    before=reload(tmp_path,mid).state.actors[OWNER].movement_remaining_ft
    cast(combat,table,mid,'Move Guiding Lantern',{'choice:needle.lantern_lantern_move_destination':'cell:3,7'})
    e=reload(tmp_path,mid)
    assert lamps(e)[0].position.y==7
    assert e.state.actors[OWNER].movement_remaining_ft==before
    assert not any(c.display_name=='Move Guiding Lantern' for c in e.legal_candidates())


def test_road_start_native_movement_has_no_action_cost_or_opportunity(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER],{'x':10,'y':6}])
    # Choices are transported on the accepted End Turn that starts Tobin's turn.
    for _ in range(4):
        if table.state(mid)['menu']['actor_id']==ALLY:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks={
            'choice:needle.lantern_road_destination_lantern':'first',
            'choice:needle.lantern_road_step':'first',
            'choice:needle.lantern_moving_lantern':None})
    e=reload(tmp_path,mid)
    ally=e.state.actors[ALLY]
    assert e.state.current_actor_id==ALLY
    assert ally.action_available and ally.bonus_action_available
    assert any(ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==ALLY for ev in e.events)
    assert not any(ev.event_type=='REACTION_RESOLVED' and 'opportunity' in str(ev.source_definition_id) for ev in e.events)


def attack_ally(combat,table,mid,picks=None):
    turn(table,mid,FOE)
    e=combat._load_session(mid).engine
    if e._distance_actor_to_actor(e.state.actors[FOE],e.state.actors[ALLY])>5:
        moves=[c for c in e.legal_candidates() if c.kind=='MOVE' and c.destination and e.grid.distance_ft(c.destination,e.state.actors[ALLY].position)<=5]
        assert moves
        settle(table,mid,min(moves,key=lambda c:c.movement_cost_ft).candidate_id,picks={'choice:needle.lantern_moving_lantern':None})
    e=combat._load_session(mid).engine
    attacks=[c for c in e.legal_candidates() if c.target_ids==(ALLY,) and c.display_name.startswith('Unarmed Strike')]
    assert attacks
    return settle(table,mid,attacks[0].candidate_id,picks=picks or {})


def test_hold_soul_actual_damage_reaction_expiry_and_scene_guard(tmp_path):
    combat,table,mid=play(tmp_path,cl=14,lantern_positions=[POS[OWNER]],ally_hp=12)
    anchored=None
    for _ in range(18):
        prompts=attack_ally(combat,table,mid,{'choice:needle.lantern_hold_departing_soul':'hold'})
        e=reload(tmp_path,mid)
        anchors=[c for c in e.state.actors[ALLY].conditions.values() if c.condition_id.endswith('lantern_keeper.soul_anchor')]
        if anchors:
            anchored=anchors[0];break
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_moving_lantern':None})
    assert anchored,'Native attacks must exercise a genuine noninstant drop to 0 HP.'
    assert e.state.actors[ALLY].current_hp==0 and e.state.actors[ALLY].life_state=='STABLE'
    assert e.state.actors[OWNER].resources['resource:core.qi']==95
    assert not e.state.actors[OWNER].reaction_available
    assert any(p['context']['reaction_source_id']=='choice:needle.lantern_hold_departing_soul' for p in prompts)
    # End Wren's next actual turn. The stable soul anchor expires exactly there.
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_moving_lantern':None})
    turn(table,mid,OWNER)
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_moving_lantern':None})
    e=reload(tmp_path,mid)
    assert not any(c.condition_id.endswith('lantern_keeper.soul_anchor') for c in e.state.actors[ALLY].conditions.values())
    assert e.state.actors[ALLY].life_state=='DYING'
    assert any(c.condition_id.endswith('lantern_keeper.hold_used') and c.data['target']==ALLY for c in e.state.actors[OWNER].conditions.values())


def test_extinction_actual_damage_once_per_activation_not_on_cast(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER]],ally_hp=12)
    cast(combat,table,mid,'Ten Thousand Lantern Road',{'choice:needle.lantern_field_center':'cell:3,6','choice:needle.lantern_protected_allies':[OWNER,ALLY]})
    e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].temporary_hp==0
    saved=False
    for _ in range(9):
        attack_ally(combat,table,mid,{'choice:needle.lantern_hold_departing_soul':None,'choice:needle.lantern_flame_refuses_extinction_step':None})
        e=reload(tmp_path,mid)
        zones=[z for z in e.state.zones.values() if z.active and z.trigger_profile.get('placed',{}).get('tag')=='ten_thousand_lantern_road']
        if zones and ALLY in zones[0].trigger_profile['placed'].get('saved',[]):saved=True;break
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_moving_lantern':None,'choice:needle.lantern_field_start_step':None,'choice:needle.lantern_road_step':None})
    assert saved,'Exercise the actual would-drop damage checkpoint during the one-minute field.'
    assert e.state.actors[ALLY].current_hp==1 and e.state.actors[ALLY].temporary_hp==8
    assert e.state.actors[ALLY].life_state is None


def test_returning_flame_actual_failed_charm_save_additive_round_guard(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER]],foe_ids=['tianxia.talent.beauty.tears_like_pearls'])
    turn(table,mid,FOE)
    c=candidate(combat,mid,'Tears Like Pearls',target=ALLY)
    # A real failed save creates the roll-bonus checkpoint; the source has PB4.
    prompts=settle(table,mid,c.candidate_id,picks={ALL[1]:'first','choice:needle.lantern_returning_flame_step':None})
    e=reload(tmp_path,mid)
    bonuses=[ev for ev in e.events if ev.event_type=='D20_REWRITTEN' and ev.source_definition_id==ALL[1]]
    assert bonuses,[(ev.event_type,ev.payload) for ev in e.events if ev.event_type in ('SAVE_ROLLED','D20_REWRITTEN')]
    assert e.state.actors[OWNER].resources['resource:core.qi']==98
    assert not e.state.actors[OWNER].reaction_available
    assert any(p['context']['reactor_id']==OWNER for p in prompts)


def test_guide_requires_traveler_consent_and_spends_only_teleport_cost(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER]])
    cast(combat,table,mid,'Ten Thousand Lantern Road',{'choice:needle.lantern_field_center':'cell:3,6','choice:needle.lantern_protected_allies':[OWNER,ALLY]})
    cast(combat,table,mid,'Guide the Traveler',{'choice:needle.lantern_guided_ally':ALLY,
        'choice:needle.fact_admission.guide_traveler':'willing','choice:needle.lantern_travel_method':'teleport',
        'choice:needle.lantern_guided_teleport_destination':'cell:5,6'})
    e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].position.x==5
    assert e.state.actors[OWNER].resources['resource:core.qi']==90
    assert not any(c.display_name=='Guide the Traveler' for c in e.legal_candidates())
