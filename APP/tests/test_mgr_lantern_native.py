"""Native Open School acquisition -> journey -> table commit -> cold replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT,sheet
from tests.worker2_support import settle,turn,candidate,reload as native_reload
PARENT='tianxia.subpath.qi.lantern_keeper'
P=PARENT+'.feature.'
OWNER='actor:factory.lantern-keeper'
ALLY='actor:factory.traveler'
FOE='actor:factory.raider'
ALL=[P+s for s in ('light_the_way','lantern_road','lantern_passage','hold_the_departing_soul','ten_thousand_lantern_road')]
POS={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':7,'y':6}}

def journey(tmp_path,cl=18,*,foe_ids=(),ally_hp=60,owner_ids=(),foe_dc=16,ally_ac=14,owner_kit=None,qi=100,qi_profile=None,qi_key_score=None,foe_cl=None,foe_hp=None,ally_ids=(),ally_wis=None,ally_skills=None,ally_saves=None,terrain=(),objects=(),extra_allies=0,ambient=None,walls=()):
    docs=[sheet(owner_ids,cl=cl,name='Wren',kit=owner_kit),sheet(ally_ids,cl=cl,name='Tobin'),sheet(foe_ids,cl=foe_cl or cl,name='Mara',dc=foe_dc)]
    docs[0]['path_and_subpath']={**docs[0].get('path_and_subpath',{}),'path_record_ids':['tianxia.path.qi_cultivation'],
        'paths':[{'path_id':'tianxia.path.qi_cultivation','attainment':cl,**(qi_profile or {})}]}
    if qi_key_score is not None:
        key=qi_profile['key_ability']
        next(a for a in docs[0]['ability_scores_and_statistics']['abilities'] if a['ability']==key).update(score=qi_key_score,modifier=(qi_key_score-10)//2)
    if foe_hp is not None:docs[2]['ability_scores_and_statistics']['hit_points']['maximum']=foe_hp
    docs[1]['ability_scores_and_statistics']['hit_points']['maximum']=ally_hp
    docs[1]['ability_scores_and_statistics']['armor_class']['base_value']=ally_ac
    if ally_wis is not None:
        next(a for a in docs[1]['ability_scores_and_statistics']['abilities'] if a['ability']=='WIS').update(score=ally_wis,modifier=(ally_wis-10)//2)
    if ally_skills is not None:docs[1]['ability_scores_and_statistics']['skills']=[dict(row) for row in ally_skills]
    if ally_saves is not None:docs[1]['ability_scores_and_statistics']['saving_throws']=dict(ally_saves)
    positions=dict(POS)
    for index in range(extra_allies):
        aid=f'actor:factory.companion-{index}'
        positions[aid]={'x':2+index,'y':8}
        docs.append(sheet([],cl=cl,name=f'Companion {index}'))
    for aid,doc in zip(positions,docs):
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=qi
        # exist_ok: a test that calls journey() twice on one tmp_path must fail on its own assertion, never on a
        # helper's FileExistsError (review 1F16R2 item 4).
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.');folder.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    combat=CombatService(ROOT,tmp_path)
    yard=combat.tabletop_maps.save({'map_id':'lantern-native-yard','display_name':'Lantern native yard',
        'width_squares':20,'height_squares':14,'walls':list(walls),'terrain':list(terrain),'objects':list(objects),'starts':{'team1':[[3,6],[4,6]],'team2':[[7,6]]},
        **({'ambient':dict(ambient)} if ambient else {})})
    arena=next(key for key,value in combat.factory_arenas().items() if value.get('display_name')=='Lantern native yard')
    s=combat.create_journey(project_ids=[a.removeprefix('actor:factory.') for a in positions],arena_id=arena,
        positions=positions,base_paces={a:1000 for a in positions},control_modes={a:'MANUAL' for a in positions})
    return combat,s

def play(tmp_path,cl=18,*,lantern_positions=(),max_rounds=50,**kw):
    combat,s=journey(tmp_path,cl,**kw)
    s=combat.journey_acquire_source(s['journey_id'],s['revision'],OWNER,PARENT,{})
    for point in lantern_positions:s=combat.journey_act(s['journey_id'],s['revision'],OWNER,'lantern_create',{'position':point})
    mid=combat.journey_start_combat(s['journey_id'],s['revision'],{OWNER:'team:guides',ALLY:'team:guides',FOE:'team:raiders'},positions=POS,maximum_rounds=max_rounds)['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,OWNER)
    return combat,table,mid

def cast(combat,table,mid,name,picks=None):
    try:return settle(table,mid,candidate(combat,mid,name).candidate_id,picks=picks or {})
    except Exception as exc:
        import traceback
        raise AssertionError(name+': '+str(getattr(getattr(exc,'diagnostic',None),'details',{}))+' '+repr(exc)) from exc

def reload(tmp_path,mid):
    try:return native_reload(tmp_path,mid)
    except Exception as exc:
        raise AssertionError('Cold reload: '+str(getattr(getattr(exc,'diagnostic',None),'details',{}))+' '+repr(exc)) from exc


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

def test_acquisition_recompiles_with_owner_granted_equipment(tmp_path):
    from factory_authoring import owner_items as O
    combat,s=journey(tmp_path)
    project='lantern-keeper'
    store=O.OwnerItemStore(tmp_path/'owner_items')
    choices=O.weapon_choices('tianxia.mortal.weapon.bi_shou','Saint',None,[])
    frost=next(r['enchantment_id'] for r in choices['enchantments'] if r['name']=='Frost-Meridian Inscription')
    store.give(project,{'kind':'weapon','chassis_id':'tianxia.mortal.weapon.bi_shou','grade':'Saint',
        'material_id':choices['material_id'],'enchantment_ids':[frost]})
    acquired=combat.journey_acquire_source(s['journey_id'],s['revision'],OWNER,PARENT,{})
    bundle=acquired['actors'][OWNER]['bundle']
    assert any('Frost-Meridian Bi Shou +2 attack'==r.get('display_name') for r in bundle['action_catalog'])
    cold=CombatService(ROOT,tmp_path).journey_state(s['journey_id'])
    assert any('Frost-Meridian Bi Shou +2 attack'==r.get('display_name')
        for r in cold['actors'][OWNER]['bundle']['action_catalog'])

@pytest.mark.parametrize('cl,count',[(2,0),(3,1),(5,1),(6,2),(9,2),(10,3),(13,3),(14,4),(17,4),(18,5)])
def test_progression_thresholds(cl,count):
    b=compile_character(sheet(ALL,cl=cl),actor_id=OWNER)
    assert len([r for r in b['typed_passives'] if r.get('block')=='lantern_keeper'])==count

def test_installed_lantern_keeper_exports_scene_use_without_journey_acquisition(tmp_path):
    """An already-installed Keeper retains a paid scene limit through encounter continuation."""
    combat,s=journey(tmp_path,owner_ids=ALL)
    jid=s['journey_id']
    assert not s['actors'][OWNER].get('source_states',{}).get(PARENT)
    mid=combat.journey_start_combat(jid,s['revision'],
        {OWNER:'team:guides',ALLY:'team:guides',FOE:'team:raiders'},positions=POS,maximum_rounds=1)['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,OWNER)
    cast(combat,table,mid,'Ten Thousand Lantern Road',{
        'choice:needle.lantern_field_center':'cell:3,6',
        'choice:needle.lantern_protected_allies':[OWNER,ALLY]})
    for _ in range(8):
        if combat._load_session(mid).engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path,mid).state.terminal_result is not None
    cold=CombatService(ROOT,tmp_path)
    state=cold.journey_state(jid)
    state=cold.journey_resume(jid,state['revision'])
    # Resume settles the prior encounter and exports plug-in state before the
    # cold view can assert the continuation payload.
    state=CombatService(ROOT,tmp_path).journey_state(jid)
    assert state['actors'][OWNER]['source_states'][PARENT]['field']
    assert json.loads(state['actors'][OWNER]['source_states'][PARENT]['scene_limits'])
    second=cold.journey_start_combat(jid,state['revision'],
        {OWNER:'team:guides',ALLY:'team:guides',FOE:'team:raiders'},positions=POS,maximum_rounds=1)['match_id']
    turn(table,second,OWNER)
    engine=reload(tmp_path,second)
    assert not any(c.display_name=='Ten Thousand Lantern Road' for c in engine.legal_candidates())


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
    assert {**{'z':0},**s['actors'][OWNER]['position']}=={'x':9,'y':7,'z':0}
    assert s['actors'][OWNER]['resources']['resource:core.qi']==92
    s=combat.journey_act(jid,s['revision'],OWNER,'wait',{'seconds':28800})
    cold=CombatService(ROOT,tmp_path).journey_state(jid)
    records=json.loads(cold['actors'][OWNER]['source_states'][PARENT]['objects'])
    assert records and all(o['destroyed'] for o in records)


def test_passage_declares_both_endpoints_and_willing_passenger_then_replays(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER],{'x':9,'y':6}])
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
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER],{'x':9,'y':6}])
    cast(combat,table,mid,'Lantern Passage',{'choice:needle.lantern_carry_traveler':ALLY,'choice:needle.fact_admission.carry_traveler':None})
    e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].position.x==4
    assert e.state.actors[OWNER].resources['resource:core.qi']==95


def test_field_paid_once_concentration_discount_and_start_step(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER],{'x':9,'y':6}])
    cast(combat,table,mid,'Ten Thousand Lantern Road',{
        'choice:needle.lantern_field_center':'cell:3,6','choice:needle.lantern_protected_allies':[OWNER,ALLY]})
    cast(combat,table,mid,'Lantern Passage',{'choice:needle.lantern_carry_traveler':None})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.qi']==89
    assert e.state.actors[OWNER].concentration
    assert len([z for z in e.state.zones.values() if z.active and z.trigger_profile.get('placed',{}).get('tag')=='ten_thousand_lantern_road'])==1
    assert not any(c.display_name=='Ten Thousand Lantern Road' for c in e.legal_candidates())
    assert not e.state.actors[ALLY].temporary_hp, 'Extinction HP must not be granted at field activation'


def test_ordinary_table_movement_commits_at_4_9_and_keeps_foe_reaction(tmp_path):
    combat,table,mid=play(tmp_path)
    engine=combat._load_session(mid).engine
    moves=[c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination
        and (c.destination.x,c.destination.y)==(4,9)]
    assert moves
    foe_reactions=engine.state.actors[FOE].reaction_available
    c=moves[0];state=table.state(mid)
    result=table.act(mid,c.candidate_id,c.decision_id,c.state_version,state['last_sequence'],[])
    assert result['status']=='COMMITTED'
    e=reload(tmp_path,mid)
    assert (e.state.actors[OWNER].position.x,e.state.actors[OWNER].position.y)==(4,9)
    assert any(ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==OWNER for ev in e.events)
    assert e.state.actors[FOE].reaction_available==foe_reactions


def test_guiding_lantern_move_native_once_and_preserves_ordinary_movement(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER]])
    before=reload(tmp_path,mid).state.actors[OWNER].movement_remaining_ft
    cast(combat,table,mid,'Move Guiding Lantern',{'choice:needle.lantern_lantern_move_destination':'cell:3,7'})
    e=reload(tmp_path,mid)
    assert lamps(e)[0].position.y==7
    assert e.state.actors[OWNER].movement_remaining_ft==before
    assert not any(c.display_name=='Move Guiding Lantern' for c in e.legal_candidates())


def test_road_start_native_movement_has_no_action_cost_or_opportunity(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER],{'x':9,'y':6}])
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
    combat,table,mid=play(tmp_path,cl=14,lantern_positions=[POS[OWNER]],ally_hp=12,ally_ac=0)
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
    assert 'Lantern at (' in json.dumps(prompts), 'Anchor choices must use player-facing labels, not object IDs.'
    assert 'Unarmed Strike' in json.dumps(prompts) and 'Tobin' in json.dumps(prompts)
    # End Wren's next actual turn. The stable soul anchor expires exactly there.
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_moving_lantern':None})
    turn(table,mid,OWNER)
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_moving_lantern':None})
    e=reload(tmp_path,mid)
    assert not any(c.condition_id.endswith('lantern_keeper.soul_anchor') for c in e.state.actors[ALLY].conditions.values())
    assert e.state.actors[ALLY].life_state=='DYING'
    assert any(c.condition_id.endswith('lantern_keeper.hold_used') and c.data['target']==ALLY for c in e.state.actors[OWNER].conditions.values())


def test_extinction_actual_damage_once_per_activation_not_on_cast(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER]],ally_hp=12,ally_ac=0)
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
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER]],foe_ids=['tianxia.talent.beauty.tears_like_pearls'],foe_dc=100)
    turn(table,mid,FOE)
    c=candidate(combat,mid,'Tears Like Pearls',target=ALLY)
    # A real failed save creates the roll-bonus checkpoint; the source has PB4.
    prompts=settle(table,mid,c.candidate_id,picks={'reaction:typed.'+ALL[1]:'first','choice:needle.lantern_returning_flame_step':None})
    e=reload(tmp_path,mid)
    bonuses=[ev for ev in e.events if ev.event_type=='D20_REWRITTEN' and ev.source_definition_id==ALL[1]]
    assert bonuses,{'prompts':prompts,'events':[(ev.event_type,ev.payload) for ev in e.events if ev.event_type in ('SAVE_ROLLED','D20_REWRITTEN','D20_BONUS_APPLIED')]}
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


def declare_source(combat,s,subject,scope,tags,cl=6,dc=10,position=None,resolution=None):
    jid=s['journey_id']
    payload={'source':PARENT,'subject':subject,'kind':'external_source','scope':scope,
        'value':{'source_rule':'world:lantern-regression:'+scope,'tags':tags,'source_cl':cl,'save_dc':dc,
                 'position':position or POS[subject],'plane':'material','authority':'ordinary','duration_seconds':3600},
        'expires_at':s['seconds']+7200,'readers':[OWNER] if subject!=OWNER else []}
    if resolution is not None:payload['value']['resolution']=resolution
    s=combat.journey_world_fact(jid,s['revision'],payload)
    return combat.journey_act(jid,s['revision'],subject,'lantern_record_external_source',{'scope':scope})


def native_spirit_trace_rows(tmp_path):
    from combat.observer_information import readings
    combat,s=journey(tmp_path);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=declare_source(combat,s,FOE,'active-possession',['possession'],cl=6,position=POS[ALLY])
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':POS[OWNER]})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    e=reload(tmp_path,mid)
    cold_combat=CombatService(ROOT,tmp_path)
    public_view=TabletopService(cold_combat,tmp_path).state(mid,fog=True,fog_view='own',fog_actor_ids=(OWNER,),include_menu=False)
    assert set(public_view['fog_perception'])=={OWNER}
    visible=public_view['fog_perception'][OWNER].get('information',[])
    relevant=[r for r in visible if r.get('source_id')==ALL[0]]
    assert relevant and any('Second flame' in r['details']['text'] for r in relevant)
    assert all(set(r['details'])<={'text','position'} for r in relevant)
    encoded=json.dumps(relevant)
    assert 'world:lantern-regression' not in encoded and 'source_cl' not in encoded and 'save_dc' not in encoded
    return relevant


def test_spirit_traces_use_actual_world_input_and_disclose_only_presence_location(tmp_path):
    native_spirit_trace_rows(tmp_path)


@pytest.mark.parametrize('dc,located',[(1,True),(100,False)])
def test_revelations_native_check_retry_guard_and_private_failure(tmp_path,dc,located):
    from combat.observer_information import readings
    combat,s=journey(tmp_path);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=declare_source(combat,s,FOE,'concealed-portal',['concealed_portal'],cl=20,dc=dc,position={'x':5,'y':6})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,OWNER)
    cast(combat,table,mid,'Ten Thousand Lantern Road',{'choice:needle.lantern_field_center':'cell:3,6','choice:needle.lantern_protected_allies':[OWNER,ALLY]})
    e=reload(tmp_path,mid)
    checks=[ev for ev in e.events if ev.event_type=='CHECK_ROLLED' and ev.source_definition_id==ALL[-1]]
    assert len(checks)==1 and checks[0].payload['success']==located
    visible=[r for r in readings(e,e.state.actors[OWNER]) if r.get('source_id')==ALL[-1]]
    assert visible
    if located:assert any({**{'z':0},**r['details'].get('position',{})}=={'x':5,'y':6,'z':0} for r in visible)
    else:assert all(set(r['details'])=={'text'} for r in visible)
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_moving_lantern':None})
    e=reload(tmp_path,mid)
    assert len([ev for ev in e.events if ev.event_type=='CHECK_ROLLED' and ev.source_definition_id==ALL[-1]])==1


def test_native_world_input_rejects_actor_fabrication_and_expiry(tmp_path):
    combat,s=journey(tmp_path);jid=s['journey_id']
    payload={'source':PARENT,'subject':OWNER,'kind':'external_source','scope':'false-spirit',
        'value':{},'expires_at':1000,'readers':[]}
    before=combat.journey_state(jid)
    with pytest.raises(ValueError):combat.journey_act(jid,s['revision'],OWNER,'declare_fact',payload)
    assert combat.journey_state(jid)==before


def test_journey_field_native_import_expiry_and_scene_does_not_reset_on_wait(tmp_path):
    combat,s=journey(tmp_path);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=declare_allies(combat,s,[ALLY])
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_field',{'position':POS[OWNER],'chosen':[OWNER,ALLY]})
    assert s['actors'][OWNER]['resources']['resource:core.qi']==92
    s=combat.journey_act(jid,s['revision'],OWNER,'wait',{'seconds':60})
    assert 'field' not in s['actors'][OWNER]['source_states'][PARENT]
    with pytest.raises(ValueError):combat.journey_act(jid,s['revision'],OWNER,'lantern_field',{'position':POS[OWNER],'chosen':[OWNER,ALLY]})
    s=combat.journey_end_scene(jid,s['revision'],'The caravan reaches shelter and its rescue scene ends.')
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_field',{'position':POS[OWNER],'chosen':[OWNER,ALLY]})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.qi']==84 and e.state.actors[OWNER].concentration
    assert any(z.active and z.trigger_profile.get('placed',{}).get('tag')=='ten_thousand_lantern_road' for z in e.state.zones.values())


def test_suppression_is_native_source_scoped_and_keeps_item_damage_duration(tmp_path):
    combat,s=journey(tmp_path);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':POS[OWNER]})
    s=declare_source(combat,s,FOE,'suppressed-origin',['asset_suppression'],cl=6,position=POS[OWNER])
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':{'x':9,'y':6}})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    assert len(lamps(e))==2 and all(o.current_hp==36 for o in lamps(e))
    assert not any(c.display_name=='Lantern Passage' for c in e.legal_candidates())
    from combat.ext.mgr_reserve_lantern_keeper_light_the_way import live
    assert len(live(e,e.state.actors[OWNER]))==1


def test_domain_armament_uses_actual_lantern_profile_modes_origin_and_reload(tmp_path):
    domain='tianxia.path.qi_cultivation.feature.domain_armament'
    link='tianxia.path.qi_cultivation.feature.domain_armament_link'
    combat,table,mid=play(tmp_path,owner_ids=[domain,link,'tianxia.talent.beauty.tears_like_pearls'],lantern_positions=[POS[OWNER]])
    cast(combat,table,mid,'Domain Armament: Manifest')
    cast(combat,table,mid,'Bind Lantern Domain Armament')
    e=reload(tmp_path,mid)
    o=lamps(e)[0]
    from combat.ext.qi_path import armament_condition
    arm=armament_condition(e.state.actors[OWNER])
    assert arm.data['bound_asset_id']==o.object_id
    assert o.component['domain_armament'] and (o.ac,o.maximum_hp)==(17,36)
    cast(combat,table,mid,'Move Guiding Lantern',{'choice:needle.lantern_lantern_move_destination':'cell:9,6'})
    e=reload(tmp_path,mid)
    o=lamps(e)[0];arm=armament_condition(e.state.actors[OWNER])
    assert (arm.data['ax'],arm.data['ay'])==(o.position.x,o.position.y)==(9,6)
    cast(combat,table,mid,'Domain Armament: Guard Mode')
    e=reload(tmp_path,mid)
    assert armament_condition(e.state.actors[OWNER]).data['mode']=='guard'
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_moving_lantern':None})
    turn(table,mid,OWNER)
    cast(combat,table,mid,'Domain Armament: Assault Mode')
    cast(combat,table,mid,'Move Guiding Lantern',{'choice:needle.lantern_lantern_move_destination':'cell:8,6'})
    # worker2_support.candidate's remote filter is the boolean "this candidate acts from a
    # separate effect origin"; the origin's exact identity is asserted on the candidate itself.
    strike=candidate(combat,mid,'Domain Armament Attack',target=FOE,remote=True)
    assert strike.metadata['effect_origin']['id']==o.object_id
    settle(table,mid,strike.candidate_id)
    e=reload(tmp_path,mid)
    assert armament_condition(e.state.actors[OWNER]).data['mode']=='assault'
    remote=candidate(combat,mid,'Tears Like Pearls',target=FOE,remote=True)
    assert remote.metadata['effect_origin']['id']==o.object_id
    settle(table,mid,remote.candidate_id)
    e=reload(tmp_path,mid)
    assert any(ev.event_type=='SAVE_ROLLED' and ev.actor_id==FOE and ev.source_definition_id==remote.source_definition_id for ev in e.events)


# Native turn traversal answers optional movement explicitly; an unanswered
# fixture default must not silently relocate a Lantern used by a range guard.
def turn(table,mid,actor):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id']==actor:return
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks={
            'choice:needle.lantern_moving_lantern':None,'choice:needle.lantern_road_destination_lantern':None,
            'choice:needle.lantern_road_step':None,'choice:needle.lantern_field_start_step':None})
    raise AssertionError('No native turn for '+actor)


@pytest.mark.parametrize('x,mode',[(2,'ADVANTAGE'),(1,'NORMAL')])
def test_guiding_light_actual_frightened_save_ten_foot_boundary(tmp_path,x,mode):
    combat,table,mid=play(tmp_path,cl=3,lantern_positions=[{'x':x,'y':6}],foe_ids=['tianxia.talent.warleader.frightful_roar'],foe_dc=100)
    turn(table,mid,FOE)
    c=candidate(combat,mid,'Frightful Roar')
    settle(table,mid,c.candidate_id)
    e=reload(tmp_path,mid)
    saves=[ev for ev in e.events if ev.event_type=='SAVE_ROLLED' and ev.actor_id==ALLY]
    assert saves
    roll=saves[-1].payload
    assert (roll.get('mode') or roll.get('actor',{}).get('mode'))==mode
    assert e.state.actors[OWNER].resources['resource:core.qi']==99


def test_carried_real_lantern_keeps_exact_inventory_identity_and_replays(tmp_path):
    torch='tianxia.mortal.gear.torch'
    kit={'starting_kit':{'items':[{'item_id':torch,'name':'Torch','quantity':1}]}}
    combat,table,mid=play(tmp_path,owner_kit=kit)
    cast(combat,table,mid,'Create Guiding Lantern',{
        'choice:needle.lantern_lantern_form':'carried',
        'choice:needle.lantern_carried_light_bearing_item':OWNER+'|'+torch,
        'choice:needle.fact_admission.light_bearing_item':'confirm'})
    e=reload(tmp_path,mid)
    o=lamps(e)[0]
    assert o.object_id==OWNER+'|'+torch and o.component['real_item']==1
    from combat.ext.scoundrel_riders import possessions
    assert len([i for i in possessions(e,e.state.actors[OWNER]) if i.get('object')==o.object_id])==1
    cast(combat,table,mid,'Move Guiding Lantern',{'choice:needle.lantern_lantern_move_destination':'cell:3,7'})
    e=reload(tmp_path,mid);o=lamps(e)[0]
    assert o.object_id==OWNER+'|'+torch and o.position.y==7
    from combat.carry import dropped
    iid=dropped(e.state.actors[OWNER],torch)
    assert iid and e.state.actors[OWNER].conditions[iid].data['dropped_at']['y']==7
    assert not [i for i in possessions(e,e.state.actors[OWNER]) if i.get('object')==o.object_id]
    assert any(ev.event_type=='POSSESSION_RELOCATED' for ev in e.events)


def test_manual_lantern_choice_survives_local_ai_end_turn(tmp_path):
    combat,table,mid=play(tmp_path,lantern_positions=[POS[OWNER]])
    order=combat._load_session(mid).engine.state.initiative_order
    ai_actor=next(a for i,a in enumerate(order) if a!=OWNER and order[(i+1)%len(order)]!=OWNER)
    combat.set_controller_mode(mid,actor_id=ai_actor,controller_mode='LOCAL_AUTO')
    turn(table,mid,ai_actor)
    prompts=[]
    for _ in range(12):
        if table.state(mid)['menu']['actor_id']!=ai_actor:break
        prompts+=settle(table,mid,None,auto=True,picks={'choice:needle.lantern_moving_lantern':None,
            'choice:needle.lantern_road_step':None,'choice:needle.lantern_road_destination_lantern':None})
    assert any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.lantern_moving_lantern' for p in prompts)
    reload(tmp_path,mid)


def test_native_last_qi_payment_applies_one_exhaustion_and_replays(tmp_path):
    combat,table,mid=play(tmp_path,cl=3,qi=6,lantern_positions=[POS[OWNER]]*5)
    before=reload(tmp_path,mid)
    assert before.state.actors[OWNER].resources['resource:core.qi']==1
    create(combat,table,mid)
    e=reload(tmp_path,mid)
    from combat.ext.forged_exhaustion import level
    assert e.state.actors[OWNER].resources['resource:core.qi']==0 and level(e.state.actors[OWNER])==1
    assert e._effective_speed(e.state.actors[OWNER])==25


def test_native_qi_recovery_uses_real_time_environment_and_long_rest_allowances(tmp_path):
    combat,s=journey(tmp_path,cl=3,qi=6);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    for _ in range(6):s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':POS[OWNER]})
    assert s['actors'][OWNER]['resources']['resource:core.qi']==0 and s['actors'][OWNER]['exhaustion']==1
    started=s['seconds']
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_qi_short_rest',{})
    assert s['seconds']==started+3600 and s['actors'][OWNER]['resources']['resource:core.qi']==3
    with pytest.raises(ValueError):combat.journey_act(jid,s['revision'],OWNER,'lantern_qi_short_rest',{})
    with pytest.raises(ValueError):combat.journey_act(jid,s['revision'],OWNER,'lantern_qi_cultivation_session',{'environment_scope':'unknown'})
    s=combat.journey_world_fact(jid,s['revision'],{'source':PARENT,'subject':OWNER,'kind':'cultivation_environment','scope':'quiet-camp',
        'value':{'calm':1,'ambient_qi_or_substitute':1},'expires_at':s['seconds']+8000,'readers':[]})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_qi_cultivation_session',{'environment_scope':'quiet-camp'})
    assert s['seconds']==started+10800 and s['actors'][OWNER]['resources']['resource:core.qi']==6
    with pytest.raises(ValueError):combat.journey_act(jid,s['revision'],OWNER,'lantern_qi_cultivation_session',{'environment_scope':'quiet-camp'})
    s=combat.journey_act(jid,s['revision'],OWNER,'long_rest',{})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_qi_short_rest',{})
    assert s['actors'][OWNER]['long_rests']==1
    assert CombatService(ROOT,tmp_path).journey_state(jid)==s


def test_lethal_last_qi_outside_combat_settles_before_benefit_and_cold_entry(tmp_path):
    combat,s=journey(tmp_path,cl=3,qi=1);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=combat.journey_act(jid,s['revision'],OWNER,'travel_exhaustion',{'levels':5,'ordinary':False})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':POS[OWNER]})
    cold=CombatService(ROOT,tmp_path).journey_state(jid)
    actor=cold['actors'][OWNER]
    assert actor['resources']['resource:core.qi']==0 and actor['exhaustion']==6
    assert actor['incapacitated'] and not cold.get('runtime_objects')
    assert actor['encounter_snapshot']['active']==0
    assert any(json.loads(c)['condition_id']=='condition:typed.death_finalized' for c in actor['encounter_snapshot']['conditions'].values())
    with pytest.raises(ValueError):combat.journey_act(jid,s['revision'],OWNER,'incapacitated',{'value':False})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    e=reload(tmp_path,mid)
    from combat.ext.life_state import is_deceased
    assert not e.state.actors[OWNER].active and is_deceased(e.state.actors[OWNER])
    assert e.state.actors[ALLY].current_hp==60


def test_journey_empowers_actual_carried_item_moves_custody_and_preserves_expiry(tmp_path):
    torch='tianxia.mortal.gear.torch';identity=OWNER+'|'+torch
    combat,s=journey(tmp_path,owner_kit={'starting_kit':{'items':[{'item_id':torch,'name':'Torch','quantity':1}]}})
    jid=s['journey_id'];s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=combat.journey_act(jid,s['revision'],OWNER,'declare_fact',{
        'source':PARENT,'subject':OWNER,'kind':'light_bearing_item','scope':identity,
        'value':1,'expires_at':s['seconds']+28800,'readers':[]})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'item_id':identity,'eligibility_scope':identity})
    assert list(s['runtime_objects'])==[identity]
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_move',{'object_id':identity,'position':{'x':3,'y':7}})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    e=reload(tmp_path,mid)
    from combat.carry import dropped
    assert dropped(e.state.actors[OWNER],torch) is not None
    o=lamps(e)[0]
    assert o.object_id==identity and o.position.y==7
    assert not o.component.get('carried_by')


def test_native_lethal_last_qi_uses_death_lifecycle_and_prevents_paid_benefit(tmp_path):
    combat,s=journey(tmp_path,cl=3,qi=1);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=combat.journey_act(jid,s['revision'],OWNER,'travel_exhaustion',{'levels':5,'ordinary':False})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,OWNER)
    create(combat,table,mid)
    e=reload(tmp_path,mid)
    from combat.ext.life_state import is_deceased
    assert e.state.actors[OWNER].resources['resource:core.qi']==0
    assert is_deceased(e.state.actors[OWNER]) and not e.state.actors[OWNER].active
    assert not lamps(e)


@pytest.mark.parametrize('x,mode,skills,wis,expected',[
    (2,'ADVANTAGE',[{'skill':'Survival','bonus':6}],14,6),  # the sheet's recorded Survival total, not its +9 WIS save
    (1,'NORMAL',None,18,4)])                                # no skill row: the actual WIS modifier, never the +9 save
def test_guiding_light_native_world_lost_check_uses_actual_subject_stat_and_replays(tmp_path,x,mode,skills,wis,expected):
    combat,s=journey(tmp_path,cl=3,ally_skills=skills,ally_wis=wis,ally_saves={'WIS':9});jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=declare_source(combat,s,FOE,'lost-crossroads',['lost'],position=POS[ALLY],resolution={
        'name':'Roadside disorientation','kind':'check','ability':'WIS','skill':'Survival','subjects':[ALLY]})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':{'x':x,'y':6}})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,ALLY)
    e=combat._load_session(mid).engine
    names=[c.display_name for c in e.legal_candidates()]
    from combat.ext.mgr_reserve_lantern_keeper_light_the_way import world_hazards,external_source_definitions
    assert any(k.startswith('action:lantern-source:') for k in e.action_catalog), 'A challenge declared after match start must be registered before listing it.'
    assert 'Face Roadside disorientation' in names,repr({'hazard_count':len(list(world_hazards(e,e.state.actors[ALLY]))),'definition_count':len(external_source_definitions(e,e.state.actors[ALLY]) or []),'catalog_count':len([k for k in e.action_catalog if k.startswith('action:lantern-source')]),'names':names})
    cast(combat,table,mid,'Face Roadside disorientation')
    e=reload(tmp_path,mid)
    checks=[ev for ev in e.events if ev.event_type=='CHECK_ROLLED' and ev.actor_id==ALLY]
    assert checks and checks[-1].payload['mode']==mode
    # Its own sheet number: the recorded skill row when there is one, otherwise the
    # actual WIS modifier. Never the subject's +9 WIS saving-throw total.
    assert checks[-1].payload['modifier']==expected,checks[-1].payload
    assert not any(c.display_name=='Face Roadside disorientation' for c in e.legal_candidates())
    assert e.state.actors[OWNER].resources['resource:core.qi']==99


def test_native_owning_qi_level_and_key_do_not_inherit_overall_primary_profile(tmp_path):
    combat,table,mid=play(tmp_path,cl=18,qi_profile={'attainment':6,'effective_cl':6,'key_ability':'INT'},qi_key_score=18)
    create(combat,table,mid)
    e=reload(tmp_path,mid);o=lamps(e)[0]
    assert (o.maximum_hp,o.component['source_cl'],o.component['save_modifier'])==(12,6,8)
    own=[r for r in e.typed_passive_rows[OWNER] if r.get('block')=='lantern_keeper']
    assert {r['feature_id'] for r in own}==set(ALL[:2])
    assert own[0]['numbers']['key_mod']==4
    assert not any(c.display_name in ('Lantern Passage','Ten Thousand Lantern Road') for c in e.legal_candidates())


@pytest.mark.parametrize('source_cl,remaining',[(14,1),(18,0)])
def test_field_native_object_damage_lower_cl_protection_and_equal_cl_boundary(tmp_path,source_cl,remaining):
    dust='tianxia.subpath.qi.dust_cultivator.feature.dust_to_dust'
    combat,table,mid=play(tmp_path,foe_ids=[dust],foe_cl=source_cl,lantern_positions=[{'x':6,'y':6}])
    cast(combat,table,mid,'Ten Thousand Lantern Road',{'choice:needle.lantern_field_center':'cell:3,6',
        'choice:needle.lantern_protected_allies':[OWNER,ALLY]})
    turn(table,mid,FOE)
    e=combat._load_session(mid).engine;oid=lamps(e)[0].object_id
    casts=0
    for _ in range(6):
        turn(table,mid,FOE)
        c=candidate(combat,mid,'Dust to Dust: Reduce Structure',target=oid)
        settle(table,mid,c.candidate_id);casts+=1
        e=reload(tmp_path,mid)
        if e.state.objects[oid].destroyed:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_moving_lantern':None,
            'choice:needle.lantern_road_step':None,'choice:needle.lantern_field_start_step':None})
    o=e.state.objects[oid]
    assert o.current_hp==remaining and o.destroyed==(remaining==0)
    assert e.state.actors[FOE].resources['resource:core.qi']==100-4*casts


def test_soul_anchor_continues_after_real_retaliation_victory_then_expires_in_journey(tmp_path):
    punishment='tianxia.talent.protection.punishment'
    combat,s=journey(tmp_path,cl=14,owner_ids=[punishment],ally_hp=3,ally_ac=0,foe_cl=1,foe_hp=1)
    jid=s['journey_id'];s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':POS[OWNER]})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,OWNER)
    aegis=candidate(combat,mid,'Aegis: Punishment (Persistent)',target=ALLY)
    settle(table,mid,aegis.candidate_id)
    for _ in range(18):
        attack_ally(combat,table,mid,{'choice:needle.lantern_hold_departing_soul':'hold'})
        e=reload(tmp_path,mid)
        if e.state.terminal_result:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_moving_lantern':None})
    assert e.state.terminal_result and e.state.actors[ALLY].current_hp==0,repr({'terminal':str(e.state.terminal_result),'ally':e.state.actors[ALLY].model_dump(mode='json'),'foe':e.state.actors[FOE].model_dump(mode='json')})
    assert any(c.condition_id.endswith('lantern_keeper.soul_anchor') for c in e.state.actors[ALLY].conditions.values()),'Victory has no soul anchor: '+repr({'ally':e.state.actors[ALLY].model_dump(mode='json'),'owner':e.state.actors[OWNER].model_dump(mode='json'),'events':[(x.event_type,x.actor_id,x.target_ids,x.payload) for x in e.events[-45:]]})
    s=combat.journey_state(jid)
    s=combat.journey_resume(jid,s['revision'],effect_resolutions={ALLY:'The Punishment Aegis is dismissed after the fight.'})
    assert s['actors'][ALLY]['encounter_snapshot']['life_state']=='STABLE'
    s=combat.journey_act(jid,s['revision'],OWNER,'wait',{'seconds':5})
    assert s['actors'][ALLY]['encounter_snapshot']['life_state']=='STABLE'
    s=combat.journey_act(jid,s['revision'],OWNER,'wait',{'seconds':1})
    cold=CombatService(ROOT,tmp_path).journey_state(jid)
    assert cold['actors'][ALLY]['encounter_snapshot']['life_state']=='DYING'
    assert 'anchors' not in cold['actors'][ALLY]['source_states'][PARENT]


def declare_allies(combat,s,allies):
    return combat.journey_world_fact(s['journey_id'],s['revision'],{
        'source':PARENT,'subject':OWNER,'kind':'travel_allies','scope':OWNER,
        'value':{'allies':allies},'expires_at':s['seconds']+7200,'readers':[]})



def test_journey_field_alliance_terrain_menu_and_suppression_use_native_inputs(tmp_path):
    combat,s=journey(tmp_path,terrain=[{'type':'DIFFICULT','cells':[[4,7],[7,7]]}]);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    before=combat.journey_state(jid)
    with pytest.raises(ValueError):combat.journey_act(jid,s['revision'],OWNER,'lantern_field',{'position':POS[OWNER],'chosen':[ALLY]})
    assert combat.journey_state(jid)==before
    s=declare_allies(combat,s,[ALLY])
    menu=combat.journey_menu(jid,OWNER)
    field=next(o for o in menu['options'] if o['kind']=='lantern_field_prepare')
    assert field['auto_select']==0
    assert any(o['kind']=='lantern_create' and o['payload']['position']!={**POS[OWNER],'z':0} for o in menu['options'])
    assert any(o['kind']=='lantern_field_prepare' and o['payload']['position']!={**POS[OWNER],'z':0} for o in menu['options'])
    s=combat.journey_act(jid,s['revision'],OWNER,field['kind'],field['payload'])
    toggle=next(o for o in combat.journey_menu(jid,OWNER)['options'] if o['kind']=='lantern_field_prepare' and ALLY in o['payload']['chosen'])
    s=combat.journey_act(jid,s['revision'],OWNER,toggle['kind'],toggle['payload'])
    field=next(o for o in combat.journey_menu(jid,OWNER)['options'] if o['kind']=='lantern_field')
    assert ALLY in field['payload']['chosen']
    s=combat.journey_act(jid,s['revision'],OWNER,field['kind'],field['payload'])
    started=s['seconds'];s=combat.journey_act(jid,s['revision'],ALLY,'move',{'path':[{'x':4,'y':7}]})
    assert s['seconds']-started==18
    started=s['seconds'];s=combat.journey_act(jid,s['revision'],FOE,'move',{'path':[{'x':7,'y':7}]})
    assert s['seconds']-started==36
    assert CombatService(ROOT,tmp_path).journey_state(jid)==s
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':POS[OWNER]})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':{'x':9,'y':6}})
    s=declare_source(combat,s,FOE,'journey-suppression',['asset_suppression'],position=POS[OWNER])
    objects=[o for o in s['runtime_objects'].values() if not o.get('destroyed',False)]
    first=next(o for o in objects if {**{'z':0},**o['position']}=={**{'z':0},**POS[OWNER]});second=next(o for o in objects if o is not first)
    before=combat.journey_state(jid)
    with pytest.raises(ValueError):combat.journey_act(jid,s['revision'],OWNER,'lantern_passage',{'first':first['object_id'],'second':second['object_id'],'position':{'x':9,'y':7}})
    assert CombatService(ROOT,tmp_path).journey_state(jid)==before


def test_journey_road_native_alliance_route_and_wrong_owner_guard(tmp_path):
    combat,s=journey(tmp_path,cl=6);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    for point in (POS[OWNER],{'x':9,'y':6}):s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':point})
    lamps=list(s['runtime_objects']);payload={'keeper':OWNER,'first':lamps[0],'second':lamps[1],'position':{'x':6,'y':6}}
    before=combat.journey_state(jid)
    with pytest.raises(ValueError):combat.journey_act(jid,s['revision'],ALLY,'lantern_road_step',payload)
    assert combat.journey_state(jid)==before
    s=declare_allies(combat,s,[ALLY])
    s=combat.journey_act(jid,s['revision'],ALLY,'lantern_road_step',payload)
    assert {**{'z':0},**s['actors'][ALLY]['position']}=={'x':6,'y':6,'z':0} and s['actors'][ALLY]['resources']['resource:core.qi']==100
    assert s['actors'][OWNER]['resources']['resource:core.qi']==98
    assert CombatService(ROOT,tmp_path).journey_state(jid)==s
    before=combat.journey_state(jid)
    with pytest.raises(ValueError):combat.journey_act(jid,s['revision'],FOE,'lantern_road_step',{**payload,'position':{'x':8,'y':6}})
    assert combat.journey_state(jid)==before



def test_journey_field_terrain_recomputes_at_actual_expiry_mid_step(tmp_path):
    combat,s=journey(tmp_path,terrain=[{'type':'DIFFICULT','cells':[[4,7]]}]);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=declare_allies(combat,s,[ALLY])
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_field',{'position':POS[OWNER],'chosen':[OWNER,ALLY]})
    s=combat.journey_act(jid,s['revision'],OWNER,'wait',{'seconds':50})
    start=s['seconds']
    s=combat.journey_act(jid,s['revision'],ALLY,'move',{'path':[{'x':4,'y':7}]})
    # 10 s of normal-rate travel covers 25/9 ft, then the remaining 20/9 ft
    # costs 16 s in difficult terrain after the actual field expiry.
    assert s['seconds']-start==26
    assert 'field' not in s['actors'][OWNER]['source_states'][PARENT]
    assert CombatService(ROOT,tmp_path).journey_state(jid)==s



def test_journey_real_map_lamp_retains_original_durability_on_expiry(tmp_path):
    combat,s=journey(tmp_path,objects=[{'id':1,'kind':'custom','name':'Iron shrine lamp','material':'iron','size':'tiny','hp':100,'x':5,'y':6,'blocks':False}]);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    from combat.journey_assets import JourneyAssetContext
    session=combat.journeys.load(jid)
    actual=next(o for o in JourneyAssetContext(session).state.objects.values() if o.component.get('name')=='Iron shrine lamp')
    identity=actual.object_id
    s=combat.journey_act(jid,s['revision'],OWNER,'declare_fact',{'source':PARENT,'subject':OWNER,'kind':'light_bearing_item','scope':identity,'value':1,'expires_at':s['seconds']+28800,'readers':[]})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'item_id':identity,'eligibility_scope':identity})
    assert list(s['runtime_objects'])==[identity] and s['runtime_objects'][identity]['maximum_hp']==36
    s=combat.journey_act(jid,s['revision'],OWNER,'wait',{'seconds':28800})
    cold=CombatService(ROOT,tmp_path).journey_state(jid)
    actual=cold['runtime_objects'][identity]
    assert actual['current_hp']==100 and actual['maximum_hp']==100
    assert actual['component']['empowerment_ended'] and actual['component']['material']=='iron'
    assert not actual.get('destroyed',False)
    assert 'asset_anchor_runtime' not in actual['component'] and 'hover' not in actual['component']
    # The intact restored lamp can be empowered again after the 8-hour retirement.
    s=combat.journey_act(jid,cold['revision'],OWNER,'declare_fact',{'source':PARENT,'subject':OWNER,'kind':'light_bearing_item','scope':identity,'value':1,'expires_at':cold['seconds']+28800,'readers':[]})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'item_id':identity,'eligibility_scope':identity})
    replay=CombatService(ROOT,tmp_path).journey_state(jid)
    active=replay['runtime_objects'][identity]
    assert active['component']['expires_at']>replay['seconds'] and not active['component'].get('empowerment_ended')
    assert active['current_hp']==36 and active['maximum_hp']==36



def test_hold_lethal_qi_payment_retains_reaction_cost_without_anchoring(tmp_path):
    combat,s=journey(tmp_path,cl=14,qi=5,ally_hp=3,ally_ac=0,foe_cl=1);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':POS[OWNER]})
    s=combat.journey_act(jid,s['revision'],OWNER,'travel_exhaustion',{'levels':5,'ordinary':False})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    table=TabletopService(combat,tmp_path)
    for _ in range(18):
        attack_ally(combat,table,mid,{'choice:needle.lantern_hold_departing_soul':'hold'})
        e=reload(tmp_path,mid)
        if e.state.actors[OWNER].resources['resource:core.qi']==0:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_moving_lantern':None})
    from combat.ext.life_state import is_deceased
    assert is_deceased(e.state.actors[OWNER]) and not e.state.actors[OWNER].reaction_available
    assert any(ev.event_type=='REACTION_RESOLVED' and ev.source_definition_id==ALL[3] for ev in e.events)
    assert not any(c.condition_id.endswith('lantern_keeper.soul_anchor') for c in e.state.actors[ALLY].conditions.values())



@pytest.mark.parametrize('ward,moves',[('teleport_block',True),('spatial_lock',False)])
def test_road_physical_barriers_and_real_opportunity_boundary(tmp_path,ward,moves):
    combat,s=journey(tmp_path,cl=6);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=declare_source(combat,s,FOE,'road-ward',[ward],position=POS[ALLY])
    for point in (POS[OWNER],{'x':9,'y':6}):s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':point})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions={**POS,FOE:{'x':5,'y':6}})['match_id']
    table=TabletopService(combat,tmp_path)
    for _ in range(6):
        if table.state(mid)['menu']['actor_id']==ALLY:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_road_destination_lantern':'first','choice:needle.lantern_moving_lantern':None})
    e=reload(tmp_path,mid);ally=e.state.actors[ALLY]
    assert e.state.current_actor_id==ALLY and ally.action_available and ally.bonus_action_available
    # The step itself is the engine's offered first option: what this test pins is the ward's verdict on the walk.
    assert ((ally.position.x,ally.position.y)!=(4,6)) is moves
    assert ally.current_hp==60 and e.state.actors[FOE].reaction_available



@pytest.mark.parametrize('point,located',[({'x':14,'y':13},False),({'x':15,'y':6},True),({'x':3,'y':6,'z':11},True),({'x':3,'y':6,'z':12},False)])
def test_field_revelation_native_circle_and_exclusive_height_boundaries(tmp_path,point,located):
    combat,s=journey(tmp_path);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=declare_source(combat,s,FOE,'field-edge-portal',['concealed_portal'],position=point)
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,OWNER)
    cast(combat,table,mid,'Ten Thousand Lantern Road',{'choice:needle.lantern_field_center':'cell:3,6','choice:needle.lantern_protected_allies':[OWNER]})
    reload(tmp_path,mid)
    state=TabletopService(CombatService(ROOT,tmp_path),tmp_path).state(mid,fog=True,fog_view='own',fog_actor_ids=(OWNER,),include_menu=False)
    rows=state['fog_perception'][OWNER].get('information',[])
    assert any(r.get('source_id')==ALL[-1] and {**{'z':0},**r['details'].get('position',{})}=={**{'z':0},**point} for r in rows)==located



@pytest.mark.parametrize('active,cost',[(True,5),(False,10)])
def test_field_terrain_native_entry_from_outside_and_default_guard(tmp_path,active,cost):
    combat,s=journey(tmp_path,terrain=[{'type':'DIFFICULT','cells':[[15,6]]}]);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions={**POS,ALLY:{'x':16,'y':6}})['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,OWNER)
    if active:cast(combat,table,mid,'Ten Thousand Lantern Road',{'choice:needle.lantern_field_center':'cell:3,6','choice:needle.lantern_protected_allies':[OWNER]})
    turn(table,mid,ALLY)
    e=combat._load_session(mid).engine;before=e.state.actors[ALLY].movement_remaining_ft
    move=next(c for c in e.legal_candidates() if c.kind=='MOVE' and c.destination and (c.destination.x,c.destination.y,c.destination.z)==(15,6,0))
    assert move.movement_cost_ft==cost
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].movement_remaining_ft==before-cost


# --- Review 1F15R: the Lantern's own light, its occlusion, and the Road's once-per-turn window -------------------
NIGHT={'time_of_day':'night'}
SIGHT_WALL=[{'shape':'line','points':[[5,5],[5,7]],'blocks':'sight'}]


def lantern_source_rows(engine):
    from combat import lighting
    return [s for s in lighting.sources(engine) if s.entity_id.startswith('lantern:')]


def test_guiding_lantern_lights_a_dark_map_in_its_printed_radii(tmp_path):
    """Bright 10 feet and Dim another 10 feet, as the printed record says: a 20-foot outer dim radius."""
    from combat import lighting
    combat,table,mid=play(tmp_path,ambient=NIGHT)
    assert lighting.ambient(reload(tmp_path,mid))['level']==lighting.DARK
    create(combat,table,mid,'cell:6,6')
    e=reload(tmp_path,mid)
    levels=lambda cells:[lighting.base(e,x,y) for x,y in cells]
    assert levels([(6,6),(8,6),(7,7),(4,6)])==[lighting.BRIGHT]*4    # Bright: within 10 feet of the Lantern
    assert levels([(9,6),(2,6),(10,6)])==[lighting.DIM]*3           # Dim: the next 10 feet, out to 20
    assert levels([(1,6),(12,6)])==[lighting.DARK]*2                # and nothing past it
    source=next(iter(lantern_source_rows(e)))
    assert (source.bright_ft,source.dim_ft,source.magical)==(10,20,True)
    assert source.cells==frozenset({(6,6)}) and not source.following


def test_moving_the_lantern_moves_its_light(tmp_path):
    """The light is the object's own position, re-read from committed state after a cold reload."""
    from combat import lighting
    combat,table,mid=play(tmp_path,ambient=NIGHT)
    create(combat,table,mid,'cell:6,6')
    e=reload(tmp_path,mid)
    lamp=next(o for o in lamps(e) if (o.position.x,o.position.y)==(6,6))
    cast(combat,table,mid,'Move Guiding Lantern',{'choice:needle.lantern_moving_lantern':lamp.object_id,
        'choice:needle.lantern_lantern_move_destination':'cell:9,6'})
    e=reload(tmp_path,mid)
    assert next(iter(lantern_source_rows(e))).cells==frozenset({(9,6)})
    assert [lighting.base(e,9,6),lighting.base(e,11,6)]==[lighting.BRIGHT]*2
    assert [lighting.base(e,6,6),lighting.base(e,5,6)]==[lighting.DIM]*2
    assert lighting.base(e,4,6)==lighting.DARK


@pytest.mark.parametrize('blocked',[False,True])
def test_lantern_light_stops_at_a_wall(tmp_path,blocked):
    """Light is marked through sight-clear rays, so a wall that stops sight stops the Lantern too."""
    from combat import lighting
    combat,table,mid=play(tmp_path,ambient=NIGHT,walls=SIGHT_WALL if blocked else [])
    create(combat,table,mid,'cell:4,6')
    e=reload(tmp_path,mid)
    assert lighting.base(e,4,6)==lighting.BRIGHT
    assert (lighting.base(e,6,6)==lighting.DARK) is blocked


def test_suppressed_lantern_lights_nothing(tmp_path):
    """A suppressed asset is not a light: the same scan that hides its actions hides its illumination."""
    from combat import lighting
    combat,s=journey(tmp_path,ambient=NIGHT);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':{'x':6,'y':6}})
    s=declare_source(combat,s,FOE,'suppressed-lantern',['asset_suppression'],cl=6,position={'x':6,'y':6})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    e=reload(tmp_path,mid)
    assert lamps(e) and not lantern_source_rows(e)
    assert lighting.base(e,6,6)==lighting.DARK


def test_expired_lantern_no_longer_lights_the_dark_map(tmp_path):
    """Eight hours end the empowerment in the journey, and the fight starts with no light from it."""
    from combat import lighting
    combat,s=journey(tmp_path,ambient=NIGHT);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':{'x':6,'y':6}})
    s=combat.journey_act(jid,s['revision'],OWNER,'wait',{'seconds':28800})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions=POS)['match_id']
    e=reload(tmp_path,mid)
    assert not lantern_source_rows(e) and lighting.base(e,6,6)==lighting.DARK


def test_unused_road_survives_declining_the_start_of_turn_offer(tmp_path):
    """'Once during each turn': declining the offer at turn start keeps the movement for the turn."""
    combat,s=journey(tmp_path,cl=6);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    for point in (POS[OWNER],{'x':9,'y':6}):s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':point})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},positions={**POS,FOE:{'x':5,'y':6}})['match_id']
    table=TabletopService(combat,tmp_path)
    for _ in range(6):
        if table.state(mid)['menu']['actor_id']==ALLY:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_road_destination_lantern':None,'choice:needle.lantern_moving_lantern':None})
    e=reload(tmp_path,mid);ally=e.state.actors[ALLY]
    assert e.state.current_actor_id==ALLY and (ally.position.x,ally.position.y)==(4,6)
    # The ally spends its Action on the raider beside it, and the Road is still offered afterwards.
    attacks=[c for c in e.legal_candidates() if c.target_ids==(FOE,) and c.display_name.startswith('Unarmed Strike')]
    assert attacks
    settle(table,mid,attacks[0].candidate_id)
    e=reload(tmp_path,mid);ally=e.state.actors[ALLY]
    assert not ally.action_available and (ally.position.x,ally.position.y)==(4,6)
    road=[c for c in e.legal_candidates() if c.display_name=='Lantern Road']
    assert road,'the unused Road is still offered after the Action is spent'
    settle(table,mid,road[0].candidate_id)
    e=reload(tmp_path,mid);ally=e.state.actors[ALLY]
    assert (ally.position.x,ally.position.y)!=(4,6)      # the free step actually happened
    assert e.state.actors[FOE].reaction_available   # no Opportunity Attack from Road movement
    assert not ally.action_available and any(c.condition_id.endswith('lantern_keeper.road_used') for c in ally.conditions.values())
    # Once during the turn, not twice: the offer is gone now that the movement is taken.
    assert not [c for c in e.legal_candidates() if c.display_name=='Lantern Road']


def test_road_qualifies_where_the_step_starts_not_where_the_turn_started(tmp_path):
    """Ten feet qualifies the movement's own start, so the Road follows the creature during its turn.

    The record says "an ally starting within 10 feet of one connected Lantern" and, unlike Ten Thousand Lantern
    Road, never "at the start of their turns". An ally that walks into reach of a connected Lantern therefore still
    takes this turn's Road, and the same ally standing out of reach before that walk is offered nothing at all.
    """
    combat,s=journey(tmp_path,cl=6);jid=s['journey_id']
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    for point in (POS[OWNER],{'x':9,'y':6}):s=combat.journey_act(jid,s['revision'],OWNER,'lantern_create',{'position':point})
    mid=combat.journey_start_combat(jid,s['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},
        positions={OWNER:POS[OWNER],ALLY:{'x':6,'y':6},FOE:{'x':8,'y':10}})['match_id']
    table=TabletopService(combat,tmp_path)
    for _ in range(6):
        if table.state(mid)['menu']['actor_id']==ALLY:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.lantern_road_destination_lantern':None,'choice:needle.lantern_moving_lantern':None})
    e=reload(tmp_path,mid);ally=e.state.actors[ALLY]
    assert e.state.current_actor_id==ALLY and (ally.position.x,ally.position.y)==(6,6)
    assert not [c for c in e.legal_candidates() if c.display_name=='Lantern Road'], (
        'fifteen feet from the nearest connected Lantern is not a place a Road step can start')
    step=next(c for c in e.legal_candidates() if c.kind=='MOVE' and c.destination.x==7 and c.destination.y==6)
    settle(table,mid,step.candidate_id)
    e=reload(tmp_path,mid);ally=e.state.actors[ALLY]
    assert (ally.position.x,ally.position.y)==(7,6)
    road=[c for c in e.legal_candidates() if c.display_name=='Lantern Road']
    assert road,"a step starting ten feet from a connected Lantern may still take this turn's Road"
    settle(table,mid,road[0].candidate_id,picks={'choice:needle.lantern_road_step':'cell:4,6'})
    e=reload(tmp_path,mid);ally=e.state.actors[ALLY]
    # Fifteen feet toward the far Lantern, arriving strictly closer and provoking nothing.
    assert (ally.position.x,ally.position.y)==(4,6) and e.state.actors[FOE].reaction_available
    assert not [c for c in e.legal_candidates() if c.display_name=='Lantern Road']
