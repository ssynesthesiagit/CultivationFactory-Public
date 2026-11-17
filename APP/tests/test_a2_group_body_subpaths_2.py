"""Body subpaths: accepted service/table actions, cold reload and replay."""
import pytest
from combat import flight
from combat.gate2_runtime_models import ActionIntent
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn

Y='tianxia.subpath.body.yamabushi.feature.'
G='tianxia.subpath.body.goruden.feature.'
E='tianxia.subpath.body.white_elephant_sovereign_body.feature.'
D='tianxia.subpath.body.heaven_thunder_drum_body.feature.'


def prepare(bundles):
    for b,i in zip(bundles,(100,0,-100)):
        b['actor_template']['initiative_bonus']=i
        b['actor_template']['maximum_hp']=1000
        seal(b)


def press(combat, table, mid, label, target=None):
    c=candidate(combat,mid,label,target=target)
    settle(table,mid,c.candidate_id)


@pytest.mark.parametrize('feature,height,protected',[
    (G+'gilded_bones',12,True),(G+'gilded_bones',14,False),
    (Y+'waterfall_stance',12,True),
])
def test_falling_defenses_are_scoped_to_the_actual_fall(tmp_path,feature,height,protected):
    def setup(bs):
        prepare(bs)
        bs[0]['actor_template']['fly_speed_ft']=30
        seal(bs[0])
        add_action(bs[0],'End test flight',[{'type':'condition','condition':'test_flight_end','applies_to':'self',
            'condition_data':{'flight_disabled':1},'duration':{'kind':'minutes','amount':1}}],target='SELF')
        add_action(bs[2],'Ordinary bludgeoning',[{'type':'damage','flat':20,
            'damage_types':['bludgeoning'],'applies_to':'target'}])
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[feature],bundle_transform=setup,positions={
            OWNER:{'x':3,'y':6,'z':height},ALLY:{'x':8,'y':6},FOE:{'x':4,'y':6}})
    if feature.endswith('waterfall_stance'):
        press(combat,table,mid,'Waterfall Stance')
    before=reload(tmp_path,mid).state.actors[OWNER].current_hp
    press(combat,table,mid,'End test flight')
    e=reload(tmp_path,mid);actor=e.state.actors[OWNER]
    assert actor.position.z==0
    assert (actor.current_hp==before) is protected
    # Neither feature grants general Bludgeoning resistance/reduction.
    turn(table,mid,FOE)
    press(combat,table,mid,'Ordinary bludgeoning',OWNER)
    assert reload(tmp_path,mid).state.actors[OWNER].current_hp==actor.current_hp-20


@pytest.mark.parametrize('feature,label,size',[
    (E+'mountain_walking_sovereign','Mountain-Walking Sovereign','Large'),
    (E+'world_bearing_elephant_king','World-Bearing Elephant King','Huge'),
])
def test_elephant_size_changes_real_occupied_cells_and_reloads(tmp_path,feature,label,size):
    fallback_tmp=tmp_path/'fallback'
    fallback_tmp.mkdir()
    combat,table,mid=fixture(fallback_tmp,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[feature],bundle_transform=prepare,positions={
            OWNER:{'x':3,'y':6},ALLY:{'x':8,'y':6},FOE:{'x':12,'y':6}})
    press(combat,table,mid,label)
    e=reload(fallback_tmp,mid);actor=e.state.actors[OWNER]
    assert actor.transformed_size_category==size
    assert len(e._actor_cells(actor))==({'Large':4,'Huge':9}[size])
    if size=='Large':
        turn(table,mid,FOE);turn(table,mid,OWNER)
        press(combat,table,mid,label)
        e=reload(fallback_tmp,mid)
        assert e.state.actors[OWNER].transformed_size_category is None
        assert len(e._actor_cells(e.state.actors[OWNER]))==1


def test_elephant_growth_stays_in_current_space_and_uses_local_fallback(tmp_path):
    # The neighbor blocks eastward growth, but a replacement containing the
    # original square can expand west. Exercise the persisted session boundary.
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[E+'mountain_walking_sovereign'],bundle_transform=prepare,positions={
            OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':12,'y':6}})
    c=candidate(combat,mid,'Mountain-Walking Sovereign')
    session=combat._load_session(mid)
    session.submit_intent(ActionIntent(intent_id='growth-west:'+str(c.state_version),
        decision_id=c.decision_id,candidate_id=c.candidate_id,state_version=c.state_version,
        actor_id=c.actor_id,target_ids=c.target_ids,destination=c.destination,option_ids=c.option_ids),
        primary_decision_record=None,reaction_provider=None)
    e=reload(tmp_path,mid);actor=e.state.actors[OWNER]
    assert actor.position.x==2 and actor.position.y==6
    assert actor.transformed_size_category=='Large'

    # A local Huge footprint remains legal west of an ally to the east.
    fallback_tmp=tmp_path/'fallback'
    fallback_tmp.mkdir()
    combat,table,mid=fixture(fallback_tmp,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[E+'world_bearing_elephant_king'],bundle_transform=prepare,positions={
            OWNER:{'x':3,'y':6},ALLY:{'x':5,'y':6},FOE:{'x':12,'y':6}})
    press(combat,table,mid,'World-Bearing Elephant King')
    e=reload(fallback_tmp,mid);actor=e.state.actors[OWNER]
    assert actor.position.x==2 and actor.position.y==6
    assert actor.transformed_size_category=='Huge'


def test_elephant_growth_expands_west_at_map_edge_and_fails_only_when_all_placements_blocked(tmp_path):
    # At the eastern map edge, an ally prevents eastward placement. A legal
    # local replacement must expand west and survive a cold reload.
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[E+'mountain_walking_sovereign'],bundle_transform=prepare,positions={
        OWNER:{'x':19,'y':6},ALLY:{'x':8,'y':6},FOE:{'x':12,'y':6}})
    press(combat,table,mid,'Mountain-Walking Sovereign')
    e=reload(tmp_path,mid);actor=e.state.actors[OWNER]
    assert actor.position.x==18 and actor.transformed_size_category=='Large'

    # Each 2x2 replacement containing (3,6) is blocked. An otherwise open
    # distant region must not be considered, and no growth state is persisted.
    blocked_tmp=tmp_path/'blocked'
    blocked_tmp.mkdir()
    blockers={f'actor:factory.worker2-ally{i}':{'x':x,'y':y}
              for i,(x,y) in enumerate(((2,5),(3,5),(2,6)),start=1)}
    combat,table,mid=fixture(blocked_tmp,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[E+'mountain_walking_sovereign'],bundle_transform=prepare,
        extra_allies=3,positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},
                                  FOE:{'x':12,'y':6},**blockers})
    press(combat,table,mid,'Mountain-Walking Sovereign')
    e=reload(blocked_tmp,mid);actor=e.state.actors[OWNER]
    assert actor.position.x==3 and actor.position.y==6
    assert actor.transformed_size_category is None


@pytest.mark.parametrize('source_cl,stopped',[(1,True),(30,False)])
def test_avatar_teleport_uses_original_source_and_moved_subject(tmp_path,source_cl,stopped):
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Hostile teleport',[{'type':'teleport','applies_to':'target','distance_ft':10,
            'choose_subject_destination':True}],typed={'numbers':{'cl':source_cl,'pb':100 if not stopped else 2,
                'key_mod':100 if not stopped else 0,'save_dc':10}})
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[Y+'avatar_of_the_mountain'],bundle_transform=setup)
    press(combat,table,mid,'Avatar of the Mountain')
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.actors[OWNER].position
    press(combat,table,mid,'Hostile teleport',OWNER)
    e=reload(tmp_path,mid)
    assert (e.state.actors[OWNER].position==before) is stopped
    contests=[x for x in e.events if x.event_type=='CHECK_ROLLED' and x.payload.get('roll_kind')=='opposed_check']
    assert len(contests)==(0 if source_cl==1 else 1)


@pytest.mark.parametrize('provider', [False,True])
@pytest.mark.parametrize('natural', [False,True])
def test_cadence_suppresses_temporary_flight_but_preserves_wings_and_ally(tmp_path,natural,provider):
    def setup(bs):
        prepare(bs)
        for b in bs[1:]:
            add_action(b,'Test flight',[{'type':'condition','condition':'drunken_sovereign_flight','applies_to':'self',
                'condition_data':{'drunken_sovereign_flight':1},'duration':{'kind':'minutes','amount':1}}
                if provider else {'type':'general_flight','applies_to':'self','speed_ft':30,
                'hover':True,'duration':{'kind':'minutes','amount':1}}],target='SELF')
        if natural:
            bs[2]['actor_template']['fly_speed_ft']=40
            seal(bs[2])
        for r in bs[0]['actor_template']['resources']:
            if r['resource_id']=='resource:named.body_beat':r['initial']=3
        seal(bs[0])
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_dc=100,primary='Stamina',owner_path='Body Refining',
        owner_features=[D+'bone_drum_strike',D+'world_shaking_cadence'],bundle_transform=setup)
    import shutil
    project='12345678-abcd-0000-0000-123456789abc'
    shutil.copytree(tmp_path/'portable_characters'/'worker2-owner',tmp_path/'portable_characters'/project)
    pools=table.sheet(project)['summary']['resources']
    assert table.sheet(project)['summary']['resources']==pools  # cached compilation too
    assert any(p.get('resource_id')=='resource:named.body_beat' and p['maximum']>0 for p in pools)
    turn(table,mid,ALLY);press(combat,table,mid,'Test flight')
    turn(table,mid,FOE);press(combat,table,mid,'Test flight')
    turn(table,mid,OWNER)
    stamina=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.stamina']
    press(combat,table,mid,'World-Shaking Cadence')
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:named.body_beat']==0
    assert e.state.actors[OWNER].resources['resource:core.stamina']==stamina-6
    assert flight.profile(e,e.state.actors[FOE]).speed_ft==(40 if natural else 0)
    # Its Normalized Procedure explicitly says every OTHER creature: allies too.
    assert flight.profile(e,e.state.actors[ALLY]).speed_ft==0
    assert not any(c.condition_id.endswith('cadence_flight_suppressed') for c in e.state.actors[OWNER].conditions.values())
    turn(table,mid,FOE)
    e=reload(tmp_path,mid)
    assert flight.profile(e,e.state.actors[FOE]).speed_ft==(40 if natural else 30)

@pytest.mark.parametrize('teleport', [False,True])
@pytest.mark.parametrize('source_cl,stopped',[(1,True),(30,False)])
def test_immortal_gold_contests_higher_cl_displacement_after_reload(tmp_path,source_cl,stopped,teleport):
    def setup(bs):
        prepare(bs)
        add_action(bs[0],'Prepare statue',[{'type':'golden_statue'}],target='SELF',
            typed={'numbers':{'cl':18,'pb':6,'key_mod':2,'save_dc':16}})
        add_action(bs[2],'Move statue',[{'type':'teleport','distance_ft':10,'applies_to':'target','choose_subject_destination':True}
            if teleport else {'type':'forced_movement','distance_ft':5,'direction':'away','applies_to':'target'}],
            typed={'numbers':{'cl':source_cl,'pb':100 if not stopped else 2,'key_mod':100 if not stopped else 0,'save_dc':16}})
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[G+'immortal_gold'],bundle_transform=setup)
    press(combat,table,mid,'Prepare statue')
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.actors[OWNER].position
    # Explicit persisted session execute_intent boundary in addition to table actions.
    if teleport:
        press(combat,table,mid,'Move statue',OWNER)
    else:
        submit_statue(combat,mid)
    e=reload(tmp_path,mid)
    assert (e.state.actors[OWNER].position==before) is stopped, [x.payload for x in e.events if x.event_type=='CHECK_ROLLED']
    contest_events=[x for x in e.events if x.event_type=='CHECK_ROLLED' and x.payload.get('roll_kind')=='opposed_check']
    assert len(contest_events)==(0 if source_cl==1 else 1)
    if source_cl > 1:
        roll_event=contest_events[0]
        payload=roll_event.payload
        assert payload['roll_kind']=='opposed_check'
        assert payload['actor']['total'] is not None and payload['target']['total'] is not None
        assert payload['tied'] in (True,False)
        history=table.events(mid,0)['events']
        row=next(row['summary'] for row in history if row['event_sequence']==roll_event.sequence)
        assert 'Cultivation Check' in row and 'DC ?' not in row
        assert str(payload['actor']['total']) in row and str(payload['target']['total']) in row


def test_immortal_gold_opposed_check_uses_exhaustion_and_history_after_reload(tmp_path):
    def setup(bs):
        prepare(bs)
        add_action(bs[0],'Prepare Exhaustion',[
            {'type':'exhaustion','amount':2,'applies_to':'self'}],target='SELF')
        add_action(bs[0],'Prepare statue',[{'type':'golden_statue'}],target='SELF',
            typed={'numbers':{'cl':18,'pb':6,'key_mod':2,'save_dc':16}})
        add_action(bs[2],'Move statue',[{'type':'forced_movement','distance_ft':5,
            'direction':'away','applies_to':'target'}],
            typed={'numbers':{'cl':30,'pb':2,'key_mod':0,'save_dc':16}})
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[G+'immortal_gold'],bundle_transform=setup)
    press(combat,table,mid,'Prepare Exhaustion')
    press(combat,table,mid,'Prepare statue')
    turn(table,mid,FOE)
    submit_statue(combat,mid)
    e=reload(tmp_path,mid)
    event=next(x for x in e.events if x.event_type=='CHECK_ROLLED' and x.payload.get('roll_kind')=='opposed_check')
    assert event.payload['roll_kind']=='opposed_check'
    assert event.payload['target']['actor_id']==OWNER
    assert event.payload['target']['modifier'] <= 4
    history=table.events(mid,0)['events']
    row=next(x['summary'] for x in history if x['event_sequence']==event.sequence)
    assert 'vs DC ?' not in row and 'DC ?' not in row

@pytest.mark.parametrize('check', [False,True])
@pytest.mark.parametrize('feature,category,advantage',[
    (G+'gilded_bones','fracture',True),(G+'gilded_bones','fear',False),
    (G+'golden_sheen','corrosion',True),(G+'golden_sheen','fire',False),
])
def test_tagged_bodily_saves_are_scoped_and_persisted(tmp_path,feature,category,advantage,check):
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Bodily pressure',[{'type':'contest_against','applies_to':'target',
            'actor_check':{'ability':'STR'},'target_check':{'ability':'CON','hazards':[category]}} if check else
            {'type':'save','ability':'con','save_categories':[category],
            'on_fail':[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}]}])
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[feature],bundle_transform=setup)
    turn(table,mid,FOE);press(combat,table,mid,'Bodily pressure',OWNER)
    e=reload(tmp_path,mid)
    rolls=[r for r in e.rolls if r.reason.startswith('CHECK:' if check else 'SAVE:') and r.actor_id==OWNER]
    assert rolls and rolls[-1].mode==('ADVANTAGE' if advantage else 'NORMAL')


def submit_statue(combat,mid):
    session=combat._load_session(mid);c=candidate(combat,mid,'Move statue',target=OWNER)
    session.submit_intent(ActionIntent(intent_id='body2:'+str(c.state_version),decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version,actor_id=c.actor_id,target_ids=c.target_ids,
        destination=c.destination,option_ids=c.option_ids),primary_decision_record=None,reaction_provider=None)

@pytest.mark.parametrize('feature,label',[
    (E+'mountain_walking_sovereign','Mountain-Walking Sovereign'),
    (E+'world_bearing_elephant_king','World-Bearing Elephant King'),
])
def test_elephant_unconscious_ends_growth_and_transformation_defenses(tmp_path,feature,label):
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Knock unconscious',[{'type':'condition','condition':'unconscious','applies_to':'target'}])
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[feature],bundle_transform=setup,positions={
            OWNER:{'x':3,'y':6},ALLY:{'x':14,'y':6},FOE:{'x':8,'y':6}})
    press(combat,table,mid,label)
    turn(table,mid,FOE);press(combat,table,mid,'Knock unconscious',OWNER)
    e=reload(tmp_path,mid);actor=e.state.actors[OWNER]
    assert actor.transformed_size_category is None
    assert not any(c.data.get('name') in {'world_bearing_elephant_king','mountain_walking_large'} for c in actor.conditions.values())
    assert not any(m.target_field=='damage_resistance' for m in actor.modifiers.values())
    assert not any(z.active and z.owner_id==OWNER for z in e.state.zones.values())

@pytest.mark.parametrize('dc,prone',[(100,True),(-100,False)])
def test_sovereign_trampling_advance_resolves_enemies_and_reload(tmp_path,dc,prone):
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_dc=dc,
        owner_features=[E+'world_bearing_elephant_king'],bundle_transform=prepare,positions={
            OWNER:{'x':3,'y':11},ALLY:{'x':3,'y':6},FOE:{'x':11,'y':12}})
    press(combat,table,mid,'World-Bearing Elephant King')
    dash=next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name=='Dash')
    settle(table,mid,dash.candidate_id)
    before=reload(tmp_path,mid)
    chosen_route(table,mid,[{'x':x,'y':11} for x in range(3,8)])
    chosen_route(table,mid,[{'x':x,'y':11} for x in range(7,14)])
    crossed=reload(tmp_path,mid)
    marker=next(c for c in crossed.state.actors[OWNER].conditions.values()
                if c.condition_id=='condition:typed.sovereign_trampling_advance')
    assert marker.data['affected']==[FOE]
    assert len([r for r in crossed.rolls if r.actor_id==FOE and r.reason.startswith('SAVE:')])==1
    chosen_route(table,mid,[{'x':x,'y':11} for x in range(13,16)])
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position.x==15
    target=e.state.actors[FOE]
    damage=next(r.total for r in e.rolls if r.expression.startswith('4d8'))
    assert before.state.actors[FOE].current_hp-target.current_hp==(damage if prone else damage//2)
    assert (any(c.condition_id.endswith('prone') for c in target.conditions.values())) is prone
    assert not set(e._actor_cells(target)) & {(x,y) for x in range(7,16) for y in range(11,14)}
    assert e.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp
    rolls=[r for r in e.rolls if r.actor_id==FOE and r.reason.startswith('SAVE:')]
    assert len(rolls)==1
    assert any(c.condition_id=='condition:typed.sovereign_trampling_advance' for c in e.state.actors[OWNER].conditions.values())
    turn(table,mid,FOE)
    e=reload(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.sovereign_trampling_advance'
                   for c in e.state.actors[OWNER].conditions.values())
    # The same recipient walks back into a new legal straight route on the
    # next round. The expired roster must allow its next saving throw.
    foe_dash=next(c for c in combat._load_session(mid).engine.legal_candidates()
                  if c.display_name=='Dash')
    settle(table,mid,foe_dash.candidate_id)
    chosen_route(table,mid,[{'x':x,'y':y} for x,y in
        [(9,10),(10,9),(11,8),(12,7),(13,6),(14,5),(15,5)]],actor=FOE)
    turn(table,mid,OWNER)
    dash=next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name=='Dash')
    settle(table,mid,dash.candidate_id)
    chosen_route(table,mid,[{'x':15,'y':y} for y in range(11,6,-1)])
    fresh_run=reload(tmp_path,mid)
    assert fresh_run.state.actors[OWNER].position.y==7
    assert not any(c.condition_id=='condition:typed.sovereign_trampling_advance'
                   for c in fresh_run.state.actors[OWNER].conditions.values())
    chosen_route(table,mid,[{'x':15,'y':y} for y in range(7,1,-1)])
    e=reload(tmp_path,mid)
    rolls=[r for r in e.rolls if r.actor_id==FOE and r.reason.startswith('SAVE:')]
    assert len(rolls)==2


def test_trampling_advance_does_not_grant_a_turning_route(tmp_path):
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[E+'world_bearing_elephant_king'],bundle_transform=prepare,positions={
            OWNER:{'x':3,'y':11},ALLY:{'x':3,'y':6},FOE:{'x':11,'y':10}})
    press(combat,table,mid,'World-Bearing Elephant King')
    dash=next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name=='Dash')
    settle(table,mid,dash.candidate_id)
    chosen_route(table,mid,[{'x':x,'y':11} for x in range(3,8)])
    # Pure menu queries neither hurt the hostile nor authorize a bent path
    # through it; cold reload verifies that browsing also spent no crossing.
    session=combat._load_session(mid)
    offered=session.engine.legal_candidates()
    from combat.tabletop_service import TabletopError
    menu=table.state(mid)['menu']
    with pytest.raises(TabletopError,match='cannot take that movement'):
        table.preview_move_path(mid,menu['decision_id'],menu['state_version'],OWNER,
            [{'x':7,'y':11},{'x':8,'y':11},{'x':8,'y':10},{'x':9,'y':10},{'x':9,'y':11},{'x':10,'y':11}])
    e=reload(tmp_path,mid)
    assert e.state.actors[FOE].current_hp==1000
    assert not any(c.condition_id=='condition:typed.sovereign_trampling_advance' for c in e.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('source_cl,stopped',[(1,True),(18,True),(30,False)])
def test_elephant_king_anchors_against_hostile_teleport(tmp_path,source_cl,stopped):
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Hostile teleport',[{'type':'teleport','applies_to':'target','distance_ft':10,
            'choose_subject_destination':True}],typed={'numbers':{'cl':source_cl,'pb':6,'key_mod':2,'save_dc':16}})
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[E+'world_bearing_elephant_king'],bundle_transform=setup,positions={
            OWNER:{'x':3,'y':6},ALLY:{'x':14,'y':6},FOE:{'x':8,'y':6}})
    press(combat,table,mid,'World-Bearing Elephant King')
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.actors[OWNER].position
    press(combat,table,mid,'Hostile teleport',OWNER)
    assert (reload(tmp_path,mid).state.actors[OWNER].position==before) is stopped


def chosen_route(table,mid,path,*,actor=OWNER):
    menu=table.state(mid)['menu']
    quote=table.preview_move_path(mid,menu['decision_id'],menu['state_version'],actor,path)
    replies=[]
    for _ in range(20):
        result=table.commit_move_path(mid,quote['candidate']['candidate_id'],menu['decision_id'],
            menu['state_version'],actor,path,reactions=replies)
        if result['status']=='COMMITTED':return
        assert result['status']=='REACTION_REQUIRED',result
        replies.append({**result['reaction']['context'],'selection':'DECLINE','option_ids':[]})
    raise AssertionError('Route did not settle')
