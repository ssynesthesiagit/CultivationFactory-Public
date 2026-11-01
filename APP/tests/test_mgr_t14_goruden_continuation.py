"""Actual acquired-source elapsed scenes, restoration, light and relation guards."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT,sheet
from tests.test_mgr_t14_goruden_build import acquire,settle_acquired
from tests.test_mgr_t14_goruden import G,ready,use
from tests.worker2_support import reload,settle,turn,candidate,fixture,OWNER,ALLY,FOE
from tests.cw2_service_support import add_action,seal


def native_journey(catalog_environment,monkeypatch,tmp_path,*,zero=False,solo=False,foe_first=False):
    owner='actor:factory.gold';foe='actor:factory.foe'
    bundle=compile_character(acquire(catalog_environment,monkeypatch),actor_id=owner,reaction_plan={'ask':True})
    bundles=[bundle]
    if not solo:
        control=compile_character(sheet([],cl=18),actor_id=foe,reaction_plan={'ask':True})
        control['actor_template']['initiative_bonus']=100 if foe_first else -100
        hp=bundle['actor_template']['maximum_hp']
        effects=[{'type':'damage','flat':hp+hp//2,'damage_types':['force'],'applies_to':'target'}]
        if zero:effects.append({'type':'damage','flat':2,'damage_types':['force'],'applies_to':'target'})
        add_action(control,'Statue return trial',effects)
        seal(control);bundles.append(control)
    def cold():return CombatService(ROOT,tmp_path)
    cold().tabletop_maps.save({'display_name':'Native gold scene','width_squares':20,'height_squares':20,'terrain':[]})
    arena=next(v for v in cold().factory_arenas().values() if v['display_name']=='Native gold scene')
    ids=[b['actor_id'] for b in bundles]
    state=cold().journeys.create(bundles,arena,{a:{'x':3+i,'y':6} for i,a in enumerate(ids)},
                                 {a:30 for a in ids})
    return cold,state['journey_id'],owner,foe


def end_window(cold,jid,tmp_path,mid):
    table=TabletopService(cold(),tmp_path)
    ready(table,tmp_path,mid)
    for _ in range(15):
        if reload(tmp_path,mid).state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path,mid).state.terminal_result is not None
    state=cold().journey_resume(jid,cold().journey_state(jid)['revision'])
    assert cold().journey_verify(jid)['status']=='PASS'
    return state


@pytest.mark.parametrize('zero',[False,True])
def test_acquired_statue_crosses_native_scene_without_refunding_cost_or_use(catalog_environment,monkeypatch,tmp_path,zero):
    cold,jid,owner,foe=native_journey(catalog_environment,monkeypatch,tmp_path,zero=zero)
    s=cold().journey_state(jid)
    result=cold().journey_start_scene(jid,s['revision'],{owner:'gold',foe:'trial'})
    mid=result['match_id'];table=TabletopService(cold(),tmp_path);ready(table,tmp_path,mid)
    initial=reload(tmp_path,mid).state.actors[owner].resources.copy()
    turn(table,mid,foe)
    settle_acquired(table,mid,candidate(cold(),mid,'Statue return trial',target=owner).candidate_id,
           picks={'choice:needle.goruden.immortal_gold':['survive']})
    e=reload(tmp_path,mid);actor=e.state.actors[owner]
    assert actor.current_hp==(0 if zero else 1) and actor.active
    assert any(c.condition_id=='condition:typed.golden_statue' for c in actor.conditions.values())
    spent=actor.resources.copy()
    assert spent['resource:core.stamina']==initial['resource:core.stamina']-6
    s=end_window(cold,jid,tmp_path,mid)
    if zero:
        import json
        assert any(json.loads(raw)['expires_on']=='STAND_UP' for raw in s['actors'][owner]['encounter_snapshot']['conditions'].values())
    before=s.copy()
    with pytest.raises(ValueError,match='statue|table scene'):
        cold().journey_act(jid,s['revision'],owner,'wait',{'seconds':6})
    assert cold().journey_state(jid)==before
    result=cold().journey_start_scene(jid,s['revision'],{owner:'party',foe:'party'})
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    assert reload(tmp_path,mid).state.setup_tasks
    ready(table,tmp_path,mid)
    e=reload(tmp_path,mid);actor=e.state.actors[owner]
    assert actor.resources==spent
    assert actor.current_hp==(0 if zero else 1)+5*actor.proficiency_bonus
    assert actor.life_state in (None,'CONSCIOUS')
    assert not any(c.condition_id=='condition:typed.golden_statue' or c.data.get('goruden_statue') for c in actor.conditions.values())
    assert actor.action_available and actor.bonus_action_available and actor.reaction_available
    assert actor.movement_remaining_ft>0
    assert len([z for z in e.state.zones.values() if z.active and z.owner_id==owner and z.source_definition_id.endswith('golden_aura')])==1
    assert not any(r.reason=='DEATH_SAVE' for r in e.rolls)
    if zero:
        # Recovery does not stand the creature for free after the start-turn
        # posture checkpoint has already passed at zero HP/Speed.
        assert any(c.expires_on=='STAND_UP' for c in actor.conditions.values())
        stand=next(c for c in e.legal_candidates() if c.source_definition_id=='system:combat.stand_up')
        before_move=actor.movement_remaining_ft;cost=stand.metadata['standing_cost_ft']
        assert cost>0
        settle(table,mid,stand.candidate_id)
        e=reload(tmp_path,mid);actor=e.state.actors[owner]
        assert actor.movement_remaining_ft==before_move-cost
        assert not any(c.expires_on=='STAND_UP' for c in actor.conditions.values())
        assert any(ev.event_type=='STOOD_UP' and ev.actor_id==owner and ev.payload['cost_ft']==cost for ev in e.events)


def test_single_acquired_actor_can_activate_and_continue_aura_outside_combat(catalog_environment,monkeypatch,tmp_path):
    cold,jid,owner,_=native_journey(catalog_environment,monkeypatch,tmp_path,solo=True)
    s=cold().journey_state(jid)
    option=next(o for o in cold().journey_menu(jid,owner)['options'] if o['kind']=='open_scene')
    result=cold().journey_act(jid,s['revision'],owner,'open_scene',option['payload'])
    mid=result['match_id'];table=TabletopService(cold(),tmp_path);ready(table,tmp_path,mid)
    turn(table,mid,owner)
    before=reload(tmp_path,mid).state.actors[owner].resources.copy()
    settle(table,mid,candidate(cold(),mid,'Golden Aura').candidate_id)
    e=reload(tmp_path,mid)
    zid=next(z.zone_id for z in e.state.zones.values() if z.active and z.owner_id==owner)
    assert e.state.actors[owner].resources['resource:core.stamina']==before['resource:core.stamina']-5
    s=end_window(cold,jid,tmp_path,mid)
    revision=s['revision']
    with pytest.raises(ValueError,match='table scene'):
        cold().journey_act(jid,revision,owner,'move',{'path':[{'x':4,'y':6}]})
    assert cold().journey_state(jid)['revision']==revision
    result=cold().journey_start_scene(jid,revision,{owner:'party'})
    mid=result['match_id'];table=TabletopService(cold(),tmp_path);ready(table,tmp_path,mid)
    assert reload(tmp_path,mid).state.zones[zid].active
    assert reload(tmp_path,mid).state.actors[owner].resources['resource:core.stamina']==before['resource:core.stamina']-5
    s=end_window(cold,jid,tmp_path,mid)
    s=cold().journey_act(jid,s['revision'],owner,'wait',{'seconds':60})
    result=cold().journey_start_scene(jid,s['revision'],{owner:'party'})
    e=reload(tmp_path,result['match_id'])
    assert not any(z.active and z.owner_id==owner for z in e.state.zones.values())


@pytest.mark.parametrize('relationship,save',[('NEUTRAL',False),('ENEMY',True)])
def test_acquired_aura_neutral_and_same_team_enemy_guards(catalog_environment,monkeypatch,tmp_path,relationship,save):
    bundle=compile_character(acquire(catalog_environment,monkeypatch),actor_id=OWNER,reaction_plan={'ask':True})
    c,t,m=fixture(tmp_path,[],owner_bundle=bundle,ally_score=1,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':10,'y':6}},
        battlefield_transform=lambda arena:arena.update(terrain_regions=[],map_objects=[],roof_surfaces=[]))
    e=reload(tmp_path,m)
    assert e.state.actors[OWNER].team_id==e.state.actors[ALLY].team_id
    c.change_relations(m,change={'kind':'ACTOR_RELATION','subject':OWNER,'other':ALLY,'relation':relationship},expected_state_version=e.state.state_version)
    source=candidate(c,m,'Golden Aura').source_definition_id
    use(c,t,m,'Golden Aura')
    e=reload(tmp_path,m)
    assert not any(x.data.get('rule',{}).get('save_against') for x in e.state.actors[ALLY].conditions.values())
    turn(t,m,ALLY)
    e=reload(tmp_path,m)
    saves=[x for x in e.events if x.event_type=='SAVE_ROLLED' and x.source_definition_id==source and x.actor_id==ALLY]
    assert bool(saves)==save
    if save:
        penalty=next(x for x in e.state.actors[ALLY].modifiers.values() if x.target_field=='attack_mode' and x.value=='DISADVANTAGE')
        assert penalty.source_actor_id==OWNER


@pytest.mark.parametrize('rider',['Deny Invisible'])
def test_acquired_fist_rider_returns_on_real_target_and_expires_at_source_turn(catalog_environment,monkeypatch,tmp_path,rider):
    cold,jid,owner,foe=native_journey(catalog_environment,monkeypatch,tmp_path,foe_first=True)
    marker=None
    for _ in range(6):
        state=cold().journey_state(jid)
        result=cold().journey_start_scene(jid,state['revision'],{owner:'gold',foe:'trial'})
        mid=result['match_id'];table=TabletopService(cold(),tmp_path);ready(table,tmp_path,mid)
        turn(table,mid,owner)
        e=reload(tmp_path,mid)
        strike=next(a.display_name for a in e.action_catalog.values() if a.owner_id==owner
                    and any(r.get('type')=='attack' and r.get('attack_kind')=='unarmed'
                            for r in (a.parameters.get('typed') or {}).get('effects',[])))
        settle(table,mid,candidate(cold(),mid,strike,target=foe).candidate_id,
               picks={'choice:needle.path_hit.'+G+'radiant_fist':[rider]})
        e=reload(tmp_path,mid)
        if rider=='Dim Light':
            marker=next((z.zone_id for z in e.state.zones.values() if z.active and z.trigger_profile.get('name')=='Radiant Fist: Dim Light'),None)
        else:
            marker=next((c.instance_id for c in e.state.actors[foe].conditions.values() if c.condition_id=='condition:typed.no_invisible_benefit'),None)
        state=end_window(cold,jid,tmp_path,mid)
        if marker:break
    assert marker,'The native hit must commit the selected rider before testing continuation.'
    carried=state['actors'][foe]['source_states']['tianxia.subpath.body.goruden']['native_effects']
    assert any(p['feature']==G+'radiant_fist' and p['source']==G+'radiant_fist'
               and p['owner']==owner for p in carried['sources'])
    result=cold().journey_start_scene(jid,state['revision'],{owner:'gold',foe:'trial'})
    mid=result['match_id'];table=TabletopService(cold(),tmp_path);ready(table,tmp_path,mid)
    e=reload(tmp_path,mid)
    assert e.state.current_actor_id==foe
    if rider=='Dim Light':
        assert e.state.zones[marker].active
        move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.movement_cost_ft==5)
        settle(table,mid,move.candidate_id)
        e=reload(tmp_path,mid)
        assert e.state.zones[marker].trigger_profile['anchor_id']==foe
        assert e.state.zones[marker].active
    else:
        assert any(c.condition_id=='condition:typed.no_invisible_benefit' for c in e.state.actors[foe].conditions.values())
    turn(table,mid,owner)
    e=reload(tmp_path,mid)
    if rider=='Dim Light':assert not e.state.zones[marker].active
    else:assert not any(c.condition_id=='condition:typed.no_invisible_benefit' for c in e.state.actors[foe].conditions.values())


@pytest.mark.parametrize('rider',['Deny Invisible'])
def test_acquired_fist_does_not_renew_when_target_misses_sources_next_turn(catalog_environment,monkeypatch,tmp_path,rider):
    import json,zipfile
    acquired=acquire(catalog_environment,monkeypatch)
    control=sheet([],cl=18)
    control['ability_scores_and_statistics']['initiative']={'bonus':100}
    control['ability_scores_and_statistics']['hit_points']['maximum']=1000
    owner,foe='actor:factory.gold','actor:factory.foe'
    for pid,doc in [('gold',acquired),('foe',control)]:
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    def cold():return CombatService(ROOT,tmp_path)
    cold().tabletop_maps.save({'display_name':'Absent fist target','width_squares':20,'height_squares':20,'terrain':[]})
    arena=next(k for k,v in cold().factory_arenas().items() if v['display_name']=='Absent fist target')
    def create(ids):
        return cold().create_journey(project_ids=ids,arena_id=arena,
            positions={a:{'x':3+i,'y':6} for i,a in enumerate((owner,foe)) if a.removeprefix('actor:factory.') in ids},
            base_paces={a:30 for a in (owner,foe) if a.removeprefix('actor:factory.') in ids})
    state=create(['gold','foe']);jid=state['journey_id'];marker=None
    for _ in range(6):
        result=cold().journey_start_scene(jid,state['revision'],{owner:'gold',foe:'trial'})
        mid=result['match_id'];table=TabletopService(cold(),tmp_path);ready(table,tmp_path,mid);turn(table,mid,owner)
        e=reload(tmp_path,mid)
        strike=next(a.display_name for a in e.action_catalog.values() if a.owner_id==owner and any(r.get('type')=='attack' and r.get('attack_kind')=='unarmed' for r in (a.parameters.get('typed') or {}).get('effects',[])))
        settle_acquired(table,mid,candidate(cold(),mid,strike,target=foe).candidate_id,
                        {'choice:needle.path_hit.'+G+'radiant_fist':[rider]})
        e=reload(tmp_path,mid)
        marker=(next((z.zone_id for z in e.state.zones.values() if z.active and z.trigger_profile.get('name')=='Radiant Fist: Dim Light'),None) if rider=='Dim Light'
                else next((c.instance_id for c in e.state.actors[foe].conditions.values() if c.condition_id=='condition:typed.no_invisible_benefit'),None))
        state=end_window(cold,jid,tmp_path,mid)
        if marker:break
    assert marker
    state=cold().journey_act(jid,state['revision'],owner,'finish',{})
    assert cold().journey_verify(jid)['status']=='PASS'
    state=create(['gold']);jid=state['journey_id']
    result=cold().journey_start_scene(jid,state['revision'],{owner:'gold'})
    mid=result['match_id'];ready(TabletopService(cold(),tmp_path),tmp_path,mid)
    assert reload(tmp_path,mid).state.actors[owner].turns_started>=1
    state=end_window(cold,jid,tmp_path,mid)
    state=cold().journey_act(jid,state['revision'],owner,'finish',{})
    assert cold().journey_verify(jid)['status']=='PASS'
    state=create(['gold','foe']);jid=state['journey_id']
    result=cold().journey_start_scene(jid,state['revision'],{owner:'gold',foe:'trial'})
    mid=result['match_id'];ready(TabletopService(cold(),tmp_path),tmp_path,mid);e=reload(tmp_path,mid)
    assert e.state.current_actor_id==foe  # Inspect before a fresh source turn can hide renewal.
    assert not any(z.active and z.trigger_profile.get('name')=='Radiant Fist: Dim Light' for z in e.state.zones.values())
    assert not any(c.condition_id=='condition:typed.no_invisible_benefit' for c in e.state.actors[foe].conditions.values())
