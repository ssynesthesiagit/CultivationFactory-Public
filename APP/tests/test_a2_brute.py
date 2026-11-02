"""Brute second pass through table intents, CombatService and cold replay."""
import pytest
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn
from tests.cw2_service_support import seal
from tests.r1i_service_support import force_ai_candidate
from combat.ext.creature_passage import NAMED


@pytest.mark.parametrize('success', [True, False])
@pytest.mark.parametrize('legacy', [True, False])
def test_overrun_named_once_passage_cost_expiry_and_legacy(tmp_path, success, legacy):
    def prepare(bundles):
        bundles[0]['skills']={'Athletics':100 if success else -100}
        bundles[2]['skills']={'Athletics':-100 if success else 100}
        if legacy:
            for action in bundles[0]['action_catalog']:
                for row in ((action.get('parameters') or {}).get('typed') or {}).get('effects') or []:
                    row.pop('named_passage', None)
        for b in bundles: seal(b)
    combat, table, mid=fixture(tmp_path, ['TAL_BRUTE_GREATER_BRUTE'], foe_position={'x':4,'y':5},
        ally_position={'x':1,'y':6}, bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Overrun',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    held=[c for c in e.state.actors[OWNER].conditions.values() if c.condition_id==NAMED]
    assert bool(held)==(success and not legacy)
    if not held:return
    # Short ordinary movement leaves the entitlement available after a cold load.
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination.x==3 and c.destination.y==5)
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid)
    before=e.state.actors[OWNER].movement_remaining_ft
    # An explicit player route can choose the costly crossing rather than the
    # cheapest ordinary menu route around the opponent.
    from combat.movement_routes import explicit_candidate, parse_waypoints
    path=[{'x':x,'y':5} for x in (3,4,5)]
    move=explicit_candidate(e,OWNER,parse_waypoints(path))
    menu=table.state(mid)['menu']
    result=table.commit_move_path(mid,move.candidate_id,menu['decision_id'],menu['state_version'],OWNER,path)
    assert result['status']=='COMMITTED',result
    e=reload(tmp_path,mid)
    mark=next(c for c in e.state.actors[OWNER].conditions.values() if c.condition_id==NAMED)
    assert mark.data['entered']==1
    assert before-e.state.actors[OWNER].movement_remaining_ft>=15
    from combat.ext.creature_passage import named_through
    assert named_through(e,e.state.actors[OWNER],e.state.actors[FOE]) is None
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    e=reload(tmp_path,mid)
    assert not any(c.condition_id==NAMED for c in e.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('auto',[False,True])
@pytest.mark.parametrize('success',[False,True])
def test_stomp_printed_every_other_creature_and_user_exclusion(tmp_path,auto,success):
    def prepare(bs):
        for b in bs:
            b['actor_template']['saving_throws']['DEX']=100 if success else -100
            seal(b)
    combat,table,mid=fixture(tmp_path,['TAL_BRUTE_EARTHQUAKE_STOMP'],cl=5,ask=not auto,
        foe_position={'x':4,'y':5},ally_position={'x':4,'y':6},bundle_transform=prepare)
    cid=candidate(combat,mid,'Earthquake Stomp').candidate_id
    if auto: force_ai_candidate(combat,mid,OWNER,cid)
    settle(table,mid,cid,auto=auto)
    e=reload(tmp_path,mid)
    for aid in [ALLY,FOE]:
        assert any(c.condition_id=='condition:typed.prone' for c in e.state.actors[aid].conditions.values())== (not success)
    assert not any(c.condition_id=='condition:typed.prone' for c in e.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('auto',[False,True])
@pytest.mark.parametrize('success',[False,True])
@pytest.mark.parametrize('cl,count',[(5,2),(11,3),(17,4)])
def test_clap_strength_scaling_half_damage_duration_and_ai_sides(tmp_path,auto,success,cl,count):
    def prepare(bs):
        bs[0]['actor_template']['saving_throws']['STR']=9
        for action in bs[0]['action_catalog']:
            typed=(action.get('parameters') or {}).get('typed') or {}
            if typed.get('source')=='TAL_BRUTE_THUNDEROUS_CLAP':typed['numbers']['key_mod']=7
        for b in bs:
            b['actor_template']['saving_throws']['CON']=100 if success else -100
            seal(b)
    combat,table,mid=fixture(tmp_path,['TAL_BRUTE_THUNDEROUS_CLAP'],cl=cl,ask=not auto,
        foe_position={'x':4,'y':5},ally_position={'x':4,'y':6},bundle_transform=prepare)
    before=reload(tmp_path,mid); hp={aid:a.current_hp for aid,a in before.state.actors.items()}
    cid=candidate(combat,mid,'Thunderous Clap').candidate_id
    if auto:force_ai_candidate(combat,mid,OWNER,cid)
    settle(table,mid,cid,auto=auto)
    e=reload(tmp_path,mid)
    damage=next(x for x in reversed(e.events) if x.event_type=='DAMAGE_COMMITTED' and FOE in x.target_ids)
    rolls=[r for r in e.rolls if 'DAMAGE' in r.reason and 'd8' in r.expression]
    assert rolls and len(rolls[-1].dice)==count and rolls[-1].modifier==2
    assert damage.payload['hp_damage']==(rolls[-1].total//2 if success else rolls[-1].total)
    for aid in [OWNER,ALLY]: assert e.state.actors[aid].current_hp==hp[aid]
    assert e.state.actors[OWNER].resources['resource:core.martial_focus']==0
    held=[c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.deafened']
    duration=[r for r in e.rolls if r.reason=='CONDITION_DURATION']
    assert bool(held)==(not success) and len(duration)==int(not success)
    if held:
        assert 2<=duration[0].total<=5
        round_end=int(held[0].expires_on.split(':')[1])
        assert round_end==before.state.round_number+duration[0].total
        if cl != 5: return
        if auto: combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='MANUAL')
        slot=int(held[0].expires_on.split(':')[2])
        for _ in range(80):
            current=reload(tmp_path,mid)
            if (current.state.round_number,current.state.current_slot_index)>=(round_end,slot):break
            settle(table,mid,table.state(mid)['menu']['end_turn'])
        assert not any(c.condition_id=='condition:typed.deafened' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())

@pytest.mark.parametrize('auto',[False,True])
@pytest.mark.parametrize('ally_in_line',[False,True])
@pytest.mark.parametrize('last_success',[False,True])
def test_bowling_chain_is_prone_only_stops_on_failure_and_spares_allies(tmp_path,auto,ally_in_line,last_success):
    from tests.r1i_service_support import fixture as fight, candidate as pick, OWNER as BOWNER, FOE as BFOE, SECOND, THIRD
    from tests.test_r1i_round3 import resolve, reload as cold
    from tests.test_c4_protection_review import inherited_prompt_loader
    def prepare(bs):
        for b in bs:
            b['skills']={'Athletics':100 if b['actor_id']==BOWNER else -100,'Acrobatics':-100}
            if b['actor_id']==THIRD and not last_success:b['skills']={'Athletics':1000,'Acrobatics':1000}
            seal(b)
    combat,table,mid,send,commit=fight(tmp_path,['BRUTE_BASE_BRUTAL_SHOVE','TAL_BRUTE_DOMINOES','TAL_BRUTE_BATTLEFIELD_BOWLING'],
        extra_foe=True,allies=(THIRD,) if ally_in_line else (),seed='A2-BOWLING',bundle_transform=prepare,
        positions={BOWNER:{'x':3,'y':0},BFOE:{'x':4,'y':0},SECOND:{'x':5,'y':0},THIRD:{'x':6,'y':0}})
    cid=pick(table,mid,'Brutal Shove',BFOE)
    if auto:force_ai_candidate(combat,mid,BOWNER,cid)
    before,prompts=resolve(combat,mid,send,cid,{'choice:needle.brutal_shove_result':'push',
        'choice:needle.brute_contest_skill':'Athletics'},auto=auto)
    e=cold(tmp_path,mid)
    for aid in [SECOND,THIRD]:
        assert e.state.actors[aid].current_hp==before['actors'][aid]['current_hp']
        assert e.state.actors[aid].position.model_dump(mode='json')==before['actors'][aid]['position']
        prone=any(c.condition_id=='condition:typed.prone' for c in e.state.actors[aid].conditions.values())
        assert prone==(aid==SECOND or (last_success and not ally_in_line))
        checks=[x for x in e.events if x.event_type=='CHECK_ROLLED' and aid in x.target_ids]
        assert len(checks)==int(aid==SECOND or not ally_in_line)
        assert not e.state.actors[aid].modifiers

@pytest.mark.parametrize('hidden_second',[False,True])
def test_bowling_ai_does_not_target_concealed_chain_creatures(tmp_path,hidden_second):
    from tests.r1i_service_support import fixture as fight, candidate as pick, OWNER as BOWNER, FOE as BFOE, SECOND, THIRD
    from tests.test_r1i_round3 import resolve, reload as cold
    from tests.test_c4_protection_review import inherited_prompt_loader
    from tests.cw2_service_support import add_action
    hidden=SECOND if hidden_second else THIRD
    def prepare(bs):
        for b in bs:
            b['skills']={'Athletics':100 if b['actor_id']==BOWNER else -100,'Acrobatics':-100}
            if b['actor_id']==BOWNER:
                add_action(b,'Conceal chain creature',[{'type':'condition','condition':'invisible',
                    'applies_to':'target','expires_on':'UNTIL_REMOVED'}])
            seal(b)
    combat,table,mid,send,commit=fight(tmp_path,['BRUTE_BASE_BRUTAL_SHOVE','TAL_BRUTE_DOMINOES','TAL_BRUTE_BATTLEFIELD_BOWLING'],
        extra_foe=True,seed='A2-BOWLING-HIDDEN',bundle_transform=prepare,
        positions={BOWNER:{'x':3,'y':0},BFOE:{'x':4,'y':0},SECOND:{'x':5,'y':0},THIRD:{'x':6,'y':0}})
    commit(pick(table,mid,'Conceal chain creature',hidden))
    cid=pick(table,mid,'Brutal Shove',BFOE)
    force_ai_candidate(combat,mid,BOWNER,cid)
    resolve(combat,mid,send,cid,{'choice:needle.brutal_shove_result':'push',
        'choice:needle.brute_contest_skill':'Athletics'},auto=True)
    e=cold(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.prone' for c in e.state.actors[hidden].conditions.values())
    assert not any(x.event_type=='CHECK_ROLLED' and hidden in x.target_ids for x in e.events)

def test_bowling_ai_entire_long_contiguous_enemy_line_has_no_hidden_cap(tmp_path):
    import json,zipfile
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT,sheet
    ids=['actor:factory.a2-long-owner']+[f'actor:factory.a2-long-foe{i}' for i in range(15)]
    bundles=[]
    for i,aid in enumerate(ids):
        doc=sheet(['BRUTE_BASE_BRUTAL_SHOVE','TAL_BRUTE_DOMINOES','TAL_BRUTE_BATTLEFIELD_BOWLING'] if i==0 else [],cl=17)
        doc['ability_scores_and_statistics']['hit_points']['maximum']=500
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
        b=compile_character(doc,actor_id=aid,reaction_plan={'ask':False})
        b['skills']={'Athletics':100 if i==0 else -100,'Acrobatics':-100};seal(b);bundles.append(b)
    combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path)
    saved=combat.tabletop_maps.save({'display_name':'Brute long line','width_squares':40,'height_squares':20,
        'walls':[],'starts':{'team1':[[3,0]],'team2':[[4,0]]}})
    arena=combat.factory_arenas()['battlefield:map.'+saved['map_id']]
    mid=combat._finish_factory_match(bundles,ids,{aid:'team:a' if i==0 else 'team:b' for i,aid in enumerate(ids)},
        {aid:{'x':3+i,'y':0} for i,aid in enumerate(ids)},arena,[ids[0]],ids[1:],
        control_modes={aid:'MANUAL' for aid in ids},match_seed='A2-LONG-LINE',display_name='Brute long line',maximum_rounds=10)['match_id']
    turn(table,mid,ids[0])
    cid=candidate(combat,mid,'Brutal Shove',target=ids[1]).candidate_id
    force_ai_candidate(combat,mid,ids[0],cid)
    settle(table,mid,cid,auto=True)
    e=reload(tmp_path,mid)
    for aid in ids[2:]:
        checks=[x for x in e.events if x.event_type=='CHECK_ROLLED' and aid in x.target_ids]
        assert len(checks)==1 and checks[0].payload['success']
        assert any(c.condition_id=='condition:typed.prone' for c in e.state.actors[aid].conditions.values())
        assert e.state.actors[aid].current_hp==500

@pytest.mark.parametrize('large',[False,True])
@pytest.mark.parametrize('raised',[False,True])
def test_bowling_contiguity_uses_native_body_volumes(tmp_path,large,raised):
    from tests.r1i_service_support import fixture as fight, candidate as pick, OWNER as BOWNER, FOE as BFOE, SECOND, THIRD
    from tests.test_r1i_round3 import resolve, reload as cold
    from tests.cw2_service_support import add_action
    def prepare(bs):
        for b in bs:
            b['skills']={'Athletics':100 if b['actor_id']==BOWNER else -100,'Acrobatics':-100}
            if b['actor_id']==SECOND and large:
                add_action(b,'Grow for chain',[{'type':'size_change','size':'Large','applies_to':'self',
                    'expires_on':'UNTIL_REMOVED'}],target='SELF')
            if b['actor_id']==THIRD and raised:
                b['actor_template'].update(fly_speed_ft=30,hover=True)
            seal(b)
    positions={BOWNER:{'x':3,'y':0},BFOE:{'x':4,'y':0},SECOND:{'x':5,'y':0},
        THIRD:{'x':7 if large else 6,'y':0,'z':2 if raised else 0}}
    combat,table,mid,send,commit=fight(tmp_path,['BRUTE_BASE_BRUTAL_SHOVE','TAL_BRUTE_DOMINOES','TAL_BRUTE_BATTLEFIELD_BOWLING'],
        extra_foe=True,wide=True,seed='A2-BOWLING-VOLUMES',bundle_transform=prepare,positions=positions)
    if large:
        turn(table,mid,SECOND);commit(pick(table,mid,'Grow for chain',SECOND));turn(table,mid,BOWNER)
    e=cold(tmp_path,mid)
    assert e._footprint(e.state.actors[SECOND]).width_cells==(2 if large else 1)
    assert e.state.actors[THIRD].position.z==(2 if raised else 0)
    cid=pick(table,mid,'Brutal Shove',BFOE);force_ai_candidate(combat,mid,BOWNER,cid)
    resolve(combat,mid,send,cid,{'choice:needle.brutal_shove_result':'push',
        'choice:needle.brute_contest_skill':'Athletics'},auto=True)
    e=cold(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.prone' for c in e.state.actors[SECOND].conditions.values())
    assert any(c.condition_id=='condition:typed.prone' for c in e.state.actors[THIRD].conditions.values())==(not raised)
    assert sum(x.event_type=='CHECK_ROLLED' and THIRD in x.target_ids for x in e.events)==int(not raised)
    for aid in (SECOND,THIRD):assert e.state.actors[aid].current_hp==500
