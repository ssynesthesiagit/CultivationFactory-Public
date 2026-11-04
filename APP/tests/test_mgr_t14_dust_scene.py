"""Native scene use: committed combat cost -> journey -> cold continuation."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import settle

SOURCE = 'tianxia.subpath.qi.dust_cultivator.feature.primordial_dust'
PARENT = 'tianxia.subpath.qi.dust_cultivator'
OWNER = 'actor:factory.dust'
FOE = 'actor:factory.foe'


def game(tmp_path, monkeypatch, owned=True):
    monkeypatch.setattr(CombatService, '_factory_owner_sheet',
        lambda self, pid: sheet([SOURCE] if pid == 'dust' and owned else [], cl=18, name=pid))
    arena = {'stable_id':'battlefield:scene-dust','display_name':'Dust scene',
        'width_squares':12,'height_squares':12,'square_size_ft':5,
        'terrain_regions':[],'starting_positions':{}}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'scene':arena})
    def cold():return CombatService(ROOT,tmp_path)
    def create():return cold().create_journey(project_ids=['dust','foe'],arena_id='scene',
        positions={OWNER:{'x':2,'y':2},FOE:{'x':8,'y':8}},base_paces={OWNER:30,FOE:30})
    return cold,create


def test_once_per_scene_survives_combat_rest_reopen_and_only_scene_end_renews(tmp_path,monkeypatch):
    cold,create=game(tmp_path,monkeypatch)
    journey=create();jid=journey['journey_id']
    result=cold().journey_start_combat(jid,journey['revision'],{OWNER:1,FOE:2},maximum_rounds=2)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    def commit(cid):
        settle(table,mid,cid)
        loaded=cold()._load_session(mid)
        assert loaded.verify()['status']=='PASS'
        assert loaded.mechanical.replay()['status']=='PASS'
        return loaded.engine
    while table.state(mid)['menu']['actor_id']!=OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    cid=next(o['candidate_id'] for g in table.state(mid)['menu']['actions']
        if g['label']=='Primordial Dust' for o in g['options'])
    engine=commit(cid)
    counters={key for action in engine.action_catalog.values() if action.owner_id==OWNER
        and action.parameters.get('typed',{}).get('source')==SOURCE
        for key,amount in action.costs if key.startswith('resource:uses.')}
    assert counters and all(engine.state.actors[OWNER].resources[k]==0 for k in counters)
    while engine.state.terminal_result is None:
        engine=commit(table.state(mid)['menu']['end_turn'])
    before=cold().journey_state(jid)
    after=cold().journey_resume(jid,before['revision'],effect_resolutions={
        OWNER:'The table owner ends the remaining timed transformation before resuming travel.'})
    assert after['actors'][OWNER]['source_states'][PARENT]['primordial_spent']==1
    after=cold().journey_act(jid,after['revision'],OWNER,'long_rest',{})
    assert all(after['actors'][OWNER]['resources'][k]==0 for k in counters)
    cold().journey_act(jid,after['revision'],OWNER,'finish',{})
    reopened=create();jid=reopened['journey_id']
    assert reopened['actors'][OWNER]['source_states'][PARENT]['primordial_spent']==1
    assert all(reopened['actors'][OWNER]['resources'][k]==0 for k in counters)
    qi=reopened['actors'][OWNER]['resources']['resource:core.qi']
    after=cold().journey_end_scene(jid,reopened['revision'],'The journey reaches the next scene.')
    assert cold().journey_state(jid)==after
    assert after['actors'][OWNER]['source_states'][PARENT]['primordial_spent']==0
    assert all(after['actors'][OWNER]['resources'][k]==1 for k in counters)
    assert after['actors'][OWNER]['resources']['resource:core.qi']==qi
    result=cold().journey_start_combat(jid,after['revision'],{OWNER:1,FOE:2},maximum_rounds=2)
    loaded=cold()._load_session(result['match_id'])
    assert loaded.verify()['status']=='PASS' and loaded.mechanical.replay()['status']=='PASS'
    assert all(loaded.engine.state.actors[OWNER].resources[k]==1 for k in counters)


def test_scene_end_without_dust_is_inert(tmp_path,monkeypatch):
    cold,create=game(tmp_path,monkeypatch,owned=False)
    before=create();jid=before['journey_id']
    after=cold().journey_end_scene(jid,before['revision'],'The table owner ends this scene.')
    assert cold().journey_state(jid)==after
    for aid in before['actors']:
        assert PARENT not in after['actors'][aid].get('source_states',{})
        assert after['actors'][aid]['resources']==before['actors'][aid]['resources']


def test_separate_dust_continuations_can_join_without_refreshing_uses(tmp_path,monkeypatch):
    cold,_create=game(tmp_path,monkeypatch)
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',
        lambda self,pid:sheet([SOURCE],cl=18,name=pid))
    ids=['actor:factory.dust-a','actor:factory.dust-b']
    prior=[]
    for pid,aid in zip(['dust-a','dust-b'],ids):
        state=cold().create_journey(project_ids=[pid],arena_id='scene',
            positions={aid:{'x':2,'y':2}},base_paces={aid:30})
        prior.append(state['actors'][aid]['source_states'][PARENT]['scene_id'])
        cold().journey_act(state['journey_id'],state['revision'],aid,'finish',{})
    assert len(set(prior))==2
    joined=cold().create_journey(project_ids=['dust-a','dust-b'],arena_id='scene',
        positions={ids[0]:{'x':2,'y':2},ids[1]:{'x':8,'y':8}},base_paces={aid:30 for aid in ids})
    assert cold().journey_state(joined['journey_id'])==joined
    assert not any(e['kind']=='SOURCE_SCENE_USE_RENEWED' for e in joined['events'])
    for aid in ids:
        assert joined['actors'][aid]['source_states'][PARENT]['primordial_spent']==0
        assert joined['actors'][aid]['resources']['resource:core.qi']==30
