"""Native Jigoku acquisition, accepted table intents, cold mechanical replay."""
import json
import zipfile
import itertools
import pytest
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import settle
SOURCE='tianxia.subpath.body.jigoku'
PREFIX=SOURCE+'.feature.'
KEY='jigoku:acquisition'

PIDS=['0badc0de-0000-4000-8000-000000000081','0badc0de-0000-4000-8000-000000000082']
A,B=[FACTORY_ACTOR_PREFIX+p for p in PIDS]
IRON='tianxia.path.body_refining.feature.iron_fist'


def game(tmp_path,monkeypatch,cl=18,access=True,fire=False,owner_dc=16):
    serial=itertools.count(100)
    monkeypatch.setattr("secrets.token_hex",lambda size: format(next(serial), "x").zfill(size*2))
    for i,pid in enumerate(PIDS):
        doc=sheet([],cl=cl,name='Ember' if i==0 else 'Challenger',primary='Stamina',dc=owner_dc if i==0 else 16)
        doc['identity']['path']='Body Refining'
        doc['path_and_subpath']={'path_record_ids':['tianxia.path.body_refining'],'path_feature_record_ids':[IRON]}
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'test':{
        'stable_id':'journey:jigoku','width_squares':10,'height_squares':10,'square_size_ft':5,
        'starting_positions':{},'terrain_regions':[]}})
    cold=lambda:CombatService(ROOT,tmp_path)
    if fire:
        TabletopService(cold(),tmp_path).add_advancement(PIDS[1],'sphere','tianxia.sphere.fire')
    s=cold().create_journey(project_ids=PIDS,arena_id='test',positions={A:{'x':2,'y':2},B:{'x':3,'y':2}},base_paces={A:1800,B:1800})
    jid=s['journey_id']
    if access:
        s=cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':A,'kind':'legal_access','scope':'acquisition',
            'value':'The table owner admits the Forbidden Method scripture held by Ember.','expires_at':31536000,'readers':[]})
    def acquire(aid=A):
        s=cold().journey_state(jid)
        return cold().journey_acquire_source(jid,s['revision'],aid,SOURCE,{'scar_locations':'arms','scar_appearance':'permanent red lines','covered':1})
    return cold,jid,acquire


def combat(cold,jid):
    s=cold().journey_state(jid)
    result=cold().journey_start_combat(jid,s['revision'],{A:'team:a',B:'team:b'},maximum_rounds=15)
    mid=result['match_id'];service=cold();table=TabletopService(service,service.userdata_root)
    return service,table,mid


def reload(cold,mid):
    s=cold()._load_session(mid)
    assert s.mechanical.replay()['status']=='PASS'
    return s.engine


def turn(table,mid,aid):
    for _ in range(30):
        if table.state(mid)['menu']['actor_id']==aid:return
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    raise AssertionError('No turn')


def candidate(service,mid,name,target=None,at=None):
    engine=service._load_session(mid).engine
    rows=[c for c in engine.legal_candidates() if name in engine.action_catalog[c.source_definition_id].display_name
          and (target is None or c.target_ids==(target,))
          and (at is None or c.destination and (c.destination.x,c.destination.y)==at)]
    assert rows,name
    return rows[0]


def test_native_access_required_atomic(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,access=False)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='legal Forbidden Method'):acquire()
    assert cold().journey_state(jid)==before


@pytest.mark.parametrize('cl', [3,6,10,14,18])
def test_native_progression_cold_acquisition(tmp_path,monkeypatch,cl):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl)
    s=acquire()
    assert KEY in cold().journey_state(jid)['actors'][A]['source_states']
    encoded=json.dumps(s['actors'][A]['bundle'])
    for level,name in ((3,'hell_tempered'),(6,'pain_eater'),(10,'flame_fist'),(14,'hellwalker'),(18,'asura_s_rage')):
        assert (PREFIX+name in encoded)==(cl>=level)
    assert cold().journey_verify(jid)['status']=='PASS'
    service,table,mid=combat(cold,jid)
    engine=reload(cold,mid)
    assert not [r for r in engine.typed_passive_rows.get(B,[]) if r.get('kind')=='jigoku']


def test_asura_cost_cold_replay(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,A)
    before=reload(cold,mid).state.actors[A].resources['resource:core.stamina']
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    engine=reload(cold,mid);actor=engine.state.actors[A]
    assert actor.resources['resource:core.stamina']==before-7
    assert any(c.condition_id=='condition:typed.state.asura_s_rage' for c in actor.conditions.values())
    assert not actor.bonus_action_available


@pytest.mark.parametrize('cl,dice',[(10,1),(17,2)])
def test_brand_native_unarmed_play(tmp_path,monkeypatch,cl,dice):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=cl,owner_dc=1)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,A)
    picks={'choice:needle.path_hit.'+PREFIX+'flame_fist':['Use Burning Brand']}
    prompts=settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,picks)
    engine=reload(cold,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.path_hit.'+PREFIX+'flame_fist' for p in prompts)
    assert any(e.event_type=='SAVE_ROLLED' and (B in e.target_ids or e.actor_id==B) for e in engine.events)
    assert any(r.expression.startswith(str(dice)+'d8') and 'DAMAGE' in r.reason for r in engine.rolls)


def test_native_pain_mark_damage_and_benefit(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=6)
    acquire();service,table,mid=combat(cold,jid)
    picks={'choice:needle.fact_admission.hostile_intent':['genuine'], 'choice:needle.pain_eater':['mark'],
           'choice:needle.pain_eater_benefit':['no_reactions']}
    marked=False
    for _ in range(8):
        turn(table,mid,B)
        settle(table,mid,candidate(service,mid,'Iron Fist',A).candidate_id,picks)
        engine=reload(cold,mid)
        marked=any(c.condition_id=='condition:typed.pain_eater_mark' for c in engine.state.actors[B].conditions.values())
        if marked:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert marked
    turn(table,mid,A)
    prompts=settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,picks)
    engine=reload(cold,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.pain_eater_benefit' for p in prompts)
    assert not any(c.condition_id=='condition:typed.pain_eater_mark' for c in engine.state.actors[B].conditions.values())
    assert any(c.condition_id.endswith('reaction_denied') for c in engine.state.actors[B].conditions.values())


@pytest.mark.parametrize('intent',['genuine','weakened','cooperative','staged'])
def test_native_eat_flame_anti_farming(tmp_path,monkeypatch,intent):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,fire=True)
    acquire();service,table,mid=combat(cold,jid)
    picks={'choice:needle.fact_admission.hostile_intent':[intent],'choice:needle.eat_the_flame':['eat']}
    for _ in range(8):
        turn(table,mid,B)
        before=reload(cold,mid)
        hp=before.state.actors[A].current_hp
        stamina=before.state.actors[A].resources['resource:core.stamina']
        settle(table,mid,candidate(service,mid,'Ignite',A).candidate_id,picks)
        final=reload(cold,mid);actor=final.state.actors[A]
        if actor.current_hp<hp:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert actor.current_hp<hp
    assert actor.resources['resource:core.stamina']==stamina-(intent=='genuine')
    assert actor.temporary_hp==(min(hp-actor.current_hp,2*actor.proficiency_bonus) if intent=='genuine' else 0)


def end_encounter(table,mid):
    for _ in range(40):
        state=table.state(mid)
        if table.combat._load_session(mid).engine.state.terminal_result:return
        settle(table,mid,state['menu']['end_turn'],choices={})
    raise AssertionError('Encounter did not finish')


def test_rage_expiry_native_aftermath_and_rites(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    end_encounter(table,mid)
    final=reload(cold,mid);owner=final.state.actors[A]
    assert not any(c.condition_id=='condition:typed.state.asura_s_rage' for c in owner.conditions.values())
    for cid in ('condition:typed.exhaustion','condition:typed.directional_signal','condition:typed.eat_the_flame_spent'):
        assert any(c.condition_id==cid for c in owner.conditions.values()),cid
    s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
    s=cold().journey_end_scene(jid,s['revision'],'The immediate fight has ended; the party is safe to cool down.')
    def act(kind,payload):
        s=cold().journey_state(jid)
        result=cold().journey_act(jid,s['revision'],A,kind,payload)
        assert cold().journey_verify(jid)['status']=='PASS'
        return result
    start={'source':SOURCE+'.cooling_rite','parameters':{}}
    act('activity_start',start);act('activity_work',{'seconds':599});s=act('wait',{'seconds':1})
    assert 'journey:activity' not in s['actors'][A]['source_states']
    assert any(json.loads(c)['condition_id']=='condition:typed.eat_the_flame_spent' for c in s['actors'][A]['encounter_snapshot']['conditions'].values())
    act('activity_start',start);s=act('activity_work',{'seconds':600})
    ids=[json.loads(c)['condition_id'] for c in s['actors'][A]['encounter_snapshot']['conditions'].values()]
    assert 'condition:typed.eat_the_flame_spent' not in ids
    assert 'condition:typed.directional_signal' in ids
    act('activity_start',{'source':SOURCE+'.cultivation_session','parameters':{}});s=act('activity_work',{'seconds':7200})
    ids=[json.loads(c)['condition_id'] for c in s['actors'][A]['encounter_snapshot']['conditions'].values()]
    assert 'condition:typed.directional_signal' not in ids
    assert 'condition:typed.exhaustion' in ids


def test_unknown_source_wrong_owner_and_low_cl_guards(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=2)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='CL3'):acquire()
    with pytest.raises(ValueError,match='unique native acquisition'):
        cold().journey_acquire_source(jid,before['revision'],A,'unowned:source',{})
    with pytest.raises(ValueError):
        cold().journey_act(jid,before['revision'],B,'activity_start',{'source':SOURCE+'.cooling_rite','parameters':{}})
    assert cold().journey_state(jid)==before


@pytest.mark.parametrize('benefit',['temp_hp','move','advantage','terrain'])
def test_hellwalker_native_area_and_all_choices(tmp_path,monkeypatch,benefit):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=14,fire=True)
    acquire();service,table,mid=combat(cold,jid)
    turn(table,mid,B)
    settle(table,mid,candidate(service,mid,'Conflagration',at=(2,2)).candidate_id,choices={})
    before=reload(cold,mid);hp=before.state.actors[A].current_hp
    pos=before.state.actors[A].position
    prompts=settle(table,mid,table.state(mid)['menu']['end_turn'],{
        'choice:needle.hellwalker':[benefit], 'choice:needle.hellwalker_move':'first'})
    engine=reload(cold,mid);actor=engine.state.actors[A]
    assert actor.current_hp==hp
    assert any(p['context']['reaction_source_id']=='choice:needle.hellwalker' for p in prompts)
    if benefit=='temp_hp':assert actor.temporary_hp==actor.proficiency_bonus
    elif benefit=='move':assert actor.position!=pos and engine.grid.in_bounds((actor.position.x,actor.position.y))
    elif benefit=='terrain':assert any(c.condition_id=='condition:typed.hellwalker_ignores_difficult' for c in actor.conditions.values())
    else:
        assert any(c.condition_id=='condition:typed.hellwalker_unarmed_advantage' for c in actor.conditions.values())
        settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,choices={})
        after=reload(cold,mid)
        assert not any(c.condition_id=='condition:typed.hellwalker_unarmed_advantage' for c in after.state.actors[A].conditions.values())
        assert next(e for e in reversed(after.events) if e.event_type=='ATTACK_ROLLED' and e.actor_id==A).payload['mode']=='ADVANTAGE'


def test_human_eat_choice_on_ai_turn_uses_native_source_history(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,fire=True)
    acquire();s=cold().journey_state(jid)
    cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':B,'kind':'hostility','scope':'combat',
        'value':{'hostile_to':[A],'cooperative':0,'staged':0,'weakened':0,'captured':0,'revived':0},
        'expires_at':86400,'readers':[]})
    service,table,mid=combat(cold,jid);turn(table,mid,B)
    service.set_controller_mode(mid,actor_id=B,controller_mode='LOCAL_AUTO')
    chosen=candidate(service,mid,'Ignite',A).candidate_id
    from tests.r1i_service_support import force_ai_candidate
    force_ai_candidate(service,mid,B,chosen)
    prompts=settle(table,mid,chosen,{'choice:needle.eat_the_flame':['eat']},auto=True)
    final=reload(cold,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.eat_the_flame' for p in prompts)
    assert final.state.actors[A].temporary_hp>0


def test_native_acquisition_preserves_reaction_plan_and_rejects_other_progression(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    table=TabletopService(cold(),tmp_path)
    table.save_reactions(PIDS[0],{'mode':'ask'})
    result=acquire()
    # The newly acquired native bundle retains the same public compiler inputs
    # as an ordinary journey build, rather than reverting the player's plan.
    from combat.factory_compiler import compile_character
    expected=compile_character(cold()._factory_owner_sheet(PIDS[0]),actor_id=A,reaction_plan={'mode':'ask'})
    assert result['actors'][A]['bundle'].get('reaction_plan')==expected.get('reaction_plan')
    with pytest.raises(ValueError,match='already acquired'):acquire()
