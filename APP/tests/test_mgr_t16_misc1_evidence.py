"""Empirical Tracker's source-object range, age, privacy and cold-reload route."""
import json
import pytest

from combat import target_knowledge
from combat.ext.empirical_evidence import FEATURE, FLAG
from combat.ext.mind_hidden_eye import BASE_ID, ANALYZED
from combat.ext.riders14_research import KNOWN
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn
from tests.test_mgr_t16_misc1_ledger import auto_candidate


def fight(tmp_path, *, age=0, clear=0, owned=True, ai=False, source=True, talents=(), private_source=False):
    def arena(doc):
        doc['terrain_regions']=[{'region_id':'evidence-source-wall','terrain_type':'BLOCKED','movement_cost':0,
            'description':'Solid pillar blocks sight and physical transmission','cells':[{'x':10,'y':6}]}]
        doc['map_objects']=[{'id':600,'kind':'crate','name':'Physical tracks','x':4,'y':5,
            'source_profiles':{'empirical_tracker':{'creature_id':FOE,'age_seconds':age,
                'unusually_clear':clear}}}]
        if not source:
            doc['map_objects'][0].pop('source_profiles')
    def sharpen(bundles):
        bundles[0]['skills']={'Survival':100, 'Nature':100}
        for action in bundles[0]['action_catalog']:
            if action['display_name'] == 'Hide':
                action['parameters']['typed']['effects'][0]['bonus'] = 100
    foe = None
    if private_source:
        from tests.h1_support import sheet
        foe = sheet([], cl=15, name='Secret Evidence Maker')
        foe['identity']['creature_type'] = 'Beast'
    return fixture(tmp_path,[BASE_ID,*([FEATURE] if owned else []),*talents],cl=15,
        seed='T16-EVIDENCE'+str(age)+str(clear)+str(ai)+str(owned)+str(source),
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':6},FOE:{'x':17,'y':6}},
        battlefield_transform=arena,bundle_transform=sharpen,foe_sheet=foe,
        modes={OWNER:'LOCAL_AUTO' if ai else 'MANUAL',ALLY:'MANUAL',FOE:'MANUAL'})


def evidence_candidates(combat,mid):
    engine=combat._load_session(mid).engine
    return [c for c in engine.legal_candidates()
            if (getattr(engine.action_catalog.get(c.source_definition_id),'parameters',None) or {}).get(FLAG)]


def test_system_candidates_without_action_definitions_keep_the_eye_guard_inert():
    from combat.ext.riders14_eye import eye_candidates
    assert eye_candidates(None,None,None,None) is None


@pytest.mark.parametrize('ai',[False,True])
def test_analyze_targets_near_evidence_not_far_unseen_source_and_keeps_full_analyze_choices(tmp_path,ai):
    combat,table,mid=fight(tmp_path,ai=ai)
    engine=reload(tmp_path,mid)
    assert engine._distance_actor_to_actor(engine.state.actors[OWNER],engine.state.actors[FOE])>60
    assert not target_knowledge.located(engine,engine.state.actors[OWNER],engine.state.actors[FOE])
    # Native table presentation does not publish the sealed source facts.
    assert 'source_profiles' not in json.dumps(table.state(mid))
    rows=evidence_candidates(combat,mid)
    assert rows and rows[0].target_ids==('object:map.600',)
    before=engine.state.actors[OWNER].resources['resource:core.martial_focus']
    prompts=(auto_candidate(combat,table,mid,rows[0].candidate_id) if ai else
        settle(table,mid,rows[0].candidate_id,
            picks={'choice:needle.eye_approach':['Survival'],'choice:needle.eye_learn':['Armor Class']}))
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.martial_focus']==before-1
    assert any(c.condition_id==ANALYZED for c in engine.state.actors[FOE].conditions.values())
    learned=[c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id==KNOWN]
    assert learned and learned[-1].data['value']==engine.state.actors[FOE].armor_class
    assert learned[-1].data['subject_record_id']=='object:map.600'
    assert not target_knowledge.located(engine,engine.state.actors[OWNER],engine.state.actors[FOE])
    if not ai:
        choice=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.eye_learn')
        assert {'Armor Class','Walking Speed','STR saving throw','DEX saving throw'} <= {o['id'] for o in choice['choice']['options']}


@pytest.mark.parametrize('age,clear,owned,source,offered',[
    (86401,0,True,True,False),(86401,1,True,True,True),
    (0,0,False,True,False),(0,0,True,False,False),
])
def test_source_age_clear_ruling_and_ownership_admission(tmp_path,age,clear,owned,source,offered):
    combat,table,mid=fight(tmp_path,age=age,clear=clear,owned=owned,source=source)
    reload(tmp_path,mid)
    assert bool(evidence_candidates(combat,mid)) is offered


def test_source_age_clock_advances_after_cold_reload(tmp_path):
    combat,table,mid=fight(tmp_path,age=86399)
    assert evidence_candidates(combat,mid)
    first = reload(tmp_path,mid)
    initial_round = first.state.round_number
    lock = combat._load_session(mid).store.match_lock_path
    assert lock.is_file(), 'Fresh fixture must retain its MatchLock before advancing'
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    assert lock.is_file(), 'Turn commits must preserve the fresh MatchLock'
    engine = reload(tmp_path,mid)
    assert engine.state.round_number > initial_round
    assert not evidence_candidates(combat,mid)


@pytest.mark.parametrize('variant', ['court', 'uncanny'])
@pytest.mark.parametrize('ai', [False, True])
def test_evidence_retains_native_bonus_variants_after_action_spent(tmp_path, variant, ai):
    talent = 'TAL_THE_HIDDEN_EYE_' + ('COURT_OF_THE_HIDDEN_EYE' if variant == 'court' else 'UNCANNY_STALKER')
    combat,table,mid=fight(tmp_path,talents=[talent])
    suffix = '.court_analyze' if variant == 'court' else '.uncanny_analyze'
    def variants():
        return [c for c in evidence_candidates(combat,mid) if suffix in c.source_definition_id]
    assert not variants(), 'Native activation/hidden guard also applies to evidence'
    if variant == 'court':
        settle(table,mid,candidate(combat,mid,'Court of the Hidden Eye').candidate_id)
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        turn(table,mid,OWNER)
        settle(table,mid,candidate(combat,mid,'Dodge').candidate_id)
    else:
        settle(table,mid,candidate(combat,mid,'Hide').candidate_id)
    engine=reload(tmp_path,mid)
    assert not engine.state.actors[OWNER].action_available
    before=engine.state.actors[OWNER].resources['resource:core.martial_focus']
    rows=variants()
    assert rows, 'Evidence must retain every legal native Bonus Action route'
    action=engine.action_catalog[rows[0].source_definition_id]
    assert action.economy.value == 'BONUS_ACTION'
    assert action.costs == (() if variant == 'court' else (('resource:core.martial_focus',1),))
    assert not action.parameters.get('player_only')
    if ai:
        combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
        rows=variants()
        auto_candidate(combat,table,mid,rows[0].candidate_id)
    else:
        settle(table,mid,rows[0].candidate_id,picks={'choice:needle.eye_approach':'Survival',
                                                   'choice:needle.eye_learn':'Armor Class'})
    engine=reload(tmp_path,mid)
    assert any(c.condition_id==ANALYZED for c in engine.state.actors[FOE].conditions.values())
    assert not engine.state.actors[OWNER].bonus_action_available
    assert engine.state.actors[OWNER].resources['resource:core.martial_focus'] == before - int(variant == 'uncanny')
    assert not target_knowledge.located(engine,engine.state.actors[OWNER],engine.state.actors[FOE])


@pytest.mark.parametrize('characteristic', ['Armor Class', 'GM information 1'])
def test_evidence_context_survives_attempts_free_learning_rival_and_table_readings(tmp_path,characteristic):
    from combat.ext.riders14_eye import ATTEMPTS, RIVAL
    from combat.ext.riders14_research import CREATURE_TYPE
    combat,table,mid=fight(tmp_path,private_source=True,talents=['tianxia.talent.the_hidden_eye.biological_insight',
                                          'TAL_THE_HIDDEN_EYE_WORTHY_OPPONENT'])
    prompts=settle(table,mid,evidence_candidates(combat,mid)[0].candidate_id,
                  picks={'choice:needle.eye_approach':'Nature', 'choice:needle.eye_learn':characteristic,
                         'choice:needle.eye_rival':'designate'})
    engine=reload(tmp_path,mid)
    name=engine.state.actors[FOE].display_name
    assert name == 'Secret Evidence Maker'
    rival=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.eye_rival')
    assert 'physical evidence' in json.dumps(rival)
    assert name not in json.dumps(prompts)
    assert FOE not in json.dumps(prompts), 'Choice checkpoints must not disclose the sealed source id'
    # The real target stays private for mechanics; every persisted public reading uses the sign.
    records=[c for c in engine.state.actors[OWNER].conditions.values()
             if c.condition_id in {ATTEMPTS,KNOWN,RIVAL}]
    assert {ATTEMPTS,KNOWN,RIVAL} <= {c.condition_id for c in records}
    assert any(c.data.get('name')==CREATURE_TYPE and c.data['value']=='Beast' for c in records)
    for record in records:
        assert record.data['target_id']==FOE
        assert record.data.get('subject_record_id')=='object:map.600'
        assert record.data.get('subject_label')=='the creature that left this physical evidence'
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    cold_table=TabletopService(CombatService(ROOT,tmp_path),tmp_path)
    statuses=[c for a in cold_table.state(mid)['presentation']['actors'] if a['entity_id']==OWNER
              for c in a['conditions'] if c['condition_id'] in {ATTEMPTS,KNOWN,RIVAL}]
    assert statuses
    assert name not in json.dumps(statuses)
    assert FOE not in json.dumps(statuses)
    assert all('physical evidence' in c['rule_text'] for c in statuses)
    if characteristic == 'GM information 1':
        records=[e for e in engine.events if e.event_type=='GM_RIDER' and e.source_definition_id=='passive:eye.knowledge']
        assert records and all(e.target_ids==('object:map.600',) for e in records)
    for prompt in prompts:
        if prompt['context']['reaction_source_id'] in {'choice:needle.eye_approach','choice:needle.eye_learn'}:
            rendered=json.dumps(prompt)
            assert 'physical evidence' in rendered
            assert 'inspect one creature you can see' not in rendered
            assert 'current location' in rendered
