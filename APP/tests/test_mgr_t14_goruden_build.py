"""Actual Factory acquisition, followed by native table play; no live model or browser."""
import pytest
from app.api import create_app
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT
from tests.test_mgr_t14_goruden import G, FEATURES, prepare, use
from tests.worker2_support import fixture, reload, turn, candidate as play_candidate, OWNER, ALLY, FOE


def settle_acquired(table, mid, cid, picks=None):
    """Choose the tested source explicitly; decline competing 0-HP replacements.

    Real Body acquisition also grants Blood Pump. Accepting every optional
    choice would spend that source before Immortal Gold is reached, correctly
    preventing a second replacement for the same reduction to zero.
    """
    from tests.table_action_support import act
    answers, prompts = [], []
    for _ in range(30):
        result = act(table, mid, cid, answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']; prompts.append(p)
        rid = p['context']['reaction_source_id']
        default = ('first' if rid.startswith('choice:')
                   and not rid.startswith('choice:life.survive:') else None)
        selected = (picks or {}).get(rid, default)
        answer = {**p['context'], 'selection': 'USE' if selected is not None else 'DECLINE'}
        if selected is not None and p.get('choice'):
            answer['option_ids'] = ([p['choice']['options'][0]['id']] if selected == 'first'
                                    else selected if isinstance(selected, list) else [selected])
        answers.append(answer)
    raise AssertionError('Unsettled acquired-source choices')


def acquire(catalog_environment, monkeypatch, cl=18):
    # Reuse only a successfully validated, genuinely acquired source sheet in
    # this one disposable catalog session. Every caller gets its own copy; no
    # ownership, feature record, cost or source receipt is manufactured.
    from copy import deepcopy
    cache = catalog_environment.setdefault('_goruden_native_acquired_sheets', {})
    if cl in cache:
        return deepcopy(cache[cl])
    monkeypatch.setenv('TIANXIA_BROWSER_EXECUTABLE','/var/tmp/auto-audit/NO_BROWSER_ALLOWED')
    app=create_app(catalog_environment['settings'])
    builder=app.state.character_builder
    project=builder.create_project(working_name='Golden Body',concept='Restricted golden body scripture disciple',
        source_reference=None,target_cl=cl,power_band='rival/boss',creation_mode='detailed',
        generation_route='ai_bootstrap',ability_scores={},autogen_seed='GORUDEN-NATIVE',
        selections={'path_choice':['tianxia.path.body_refining'],
                    'subpath_choice':['tianxia.subpath.body.goruden']},method_planning_mode='AUTO')
    builder.commit_normal_first_cycle_catalog_choices(project['project_id'])
    run=app.state.character_creation.start(project['project_id'],execution_mode='STANDARD_API',
        idempotency_key='goruden-native-acquisition',controller_route='DETERMINISTIC_CREATIVE_CONTROLLER')
    assert run['status'] in ('READY_FOR_REVIEW','NEEDS_REVIEW'),run
    if run['status']=='NEEDS_REVIEW':
        assert [b['code'] for b in run['blockers']]==['COMMAND6_CHARACTER_GM_CONSUMER_FAILED'], run['blockers']
    candidate=app.state.character_creation.load_candidate_gm_context(run['run_id'])
    sheet=candidate['owner_character_sheet']
    expected={feature for feature,minimum in zip(FEATURES,(3,6,10,14,18)) if cl>=minimum}
    # Native Subpath progression is earned from sealed causal level events;
    # path_feature_record_ids is the separate legacy direct Path-feature list.
    earned = [r for r in sheet['path_and_subpath']['earned_feature_occurrences']
              if r.get('parent_record_id') == G.removesuffix('.feature.')]
    assert {r['feature_id'] for r in earned} == expected
    assert all(r['owning_path_id'] == 'tianxia.path.body_refining'
               and r['parent_subpath_record_id'] == G.removesuffix('.feature.')
               and r['source_backed'] is True and r['source_packet_ids']
               and r['acquisition_event_hash'] and r['attainment_event_hash']
               for r in earned)
    cache[cl] = deepcopy(sheet)
    return deepcopy(sheet)


def test_native_restricted_scripture_acquisition_to_table(catalog_environment, monkeypatch, tmp_path):
    sheet=acquire(catalog_environment,monkeypatch)
    bundle=compile_character(sheet,actor_id=OWNER,reaction_plan={'ask':True})
    from tests.cw2_service_support import add_action, seal
    from tests.table_action_support import act
    def native_scenario(bs):
        for b, initiative in zip(bs,(100,0,-100)):
            b['actor_template']['initiative_bonus']=initiative
            seal(b)
        bs[2]['actor_template']['maximum_hp']=1000
        seal(bs[2])
        hp=bs[0]['actor_template']['maximum_hp']
        add_action(bs[2],'Acquired Guard trial',[{'type':'damage','flat':hp//3,
                   'damage_types':['force'],'applies_to':'target'}])
        add_action(bs[2],'Acquired ally Necrotic trial',[{'type':'damage','flat':40,
                   'damage_types':['necrotic'],'applies_to':'target'}])
        add_action(bs[2],'Acquired survival trial',[{'type':'damage','flat':hp,
                   'damage_types':['force'],'applies_to':'target'}])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_bundle=bundle,
                  bundle_transform=native_scenario,
                  positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}})
    def commit(name,target=None,picks=None):
        cid=play_candidate(c,m,name,target=target).candidate_id
        answers=[]
        for _ in range(30):
            result=act(t,m,cid,answers)
            if result['status']=='COMMITTED':
                return reload(tmp_path,m)
            assert result['status']=='REACTION_REQUIRED',result
            p=result['reaction'];rid=p['context']['reaction_source_id']
            answer={**p['context'],'selection':'DECLINE'}
            if p.get('choice') and not rid.startswith('choice:life.survive:'):
                ids=[o['id'] for o in p['choice']['options']]
                desired=('gilded' if rid=='choice:needle.gilded_guard' else
                         'survive' if rid=='choice:needle.goruden.immortal_gold' else
                         'Dim Light' if rid=='choice:needle.path_hit.'+G+'radiant_fist' else
                         '1' if rid=='reaction:typed.tianxia.path.body_refining.feature.stamina_guard' else
                         ((p['choice'].get('preferred') or ids)[0]))
                desired=(picks or {}).get(rid,desired)
                assert desired in ids,(rid,ids,desired)
                answer.update(selection='USE',option_ids=[desired])
            answers.append(answer)
        raise AssertionError('Unsettled native acquired-source choices')
    e=commit('Golden Sheen: Suppress visible gold')
    assert any(x.condition_id=='condition:typed.golden_sheen_suppressed' for x in e.state.actors[OWNER].conditions.values())
    e=commit('Golden Sheen: Reveal visible gold')
    unarmed=next(a.display_name for a in e.action_catalog.values() if a.owner_id==OWNER
                 and any(r.get('type')=='attack' and r.get('attack_kind')=='unarmed'
                         for r in ((a.parameters or {}).get('typed') or {}).get('effects') or []))
    e=commit(unarmed,FOE)
    assert any(z.active and z.trigger_profile.get('name')=='Radiant Fist: Dim Light' for z in e.state.zones.values())
    stamina=e.state.actors[OWNER].resources['resource:core.stamina']
    e=commit('Golden Aura',picks={'choice:needle.goruden.aura_ally':'exclude'})
    assert e.state.actors[OWNER].resources['resource:core.stamina']==stamina-5
    from tests.worker2_support import settle
    settle(t,m,t.state(m)['menu']['end_turn'],picks={'choice:needle.goruden.aura_ally':['exclude']})
    settle(t,m,t.state(m)['menu']['end_turn'])
    e=commit('Acquired ally Necrotic trial',ALLY,{'choice:needle.goruden.aura_ally':'include'})
    ally_packet=next(x.payload for x in reversed(e.events) if x.event_type=='DAMAGE_COMMITTED' and ALLY in x.target_ids)
    assert ally_packet['reduced_to']==20 and ally_packet['temporary_hp_absorbed']==0

    e=commit('Acquired Guard trial',OWNER)
    packet=next(x for x in reversed(e.events) if x.event_type=='DAMAGE_COMMITTED' and OWNER in x.target_ids)
    assert packet.payload['hp_damage']>0
    assert any(x.event_type=='TEMP_HP_GRANTED' and x.source_definition_id==G+'gilded_bones'
               and x.sequence>packet.sequence for x in e.events)
    assert not e.state.actors[OWNER].reaction_available
    e=commit('Acquired survival trial',OWNER)
    assert e.state.actors[OWNER].current_hp==1
    assert any(x.condition_id=='condition:typed.golden_statue' for x in e.state.actors[OWNER].conditions.values())
    turn(t,m,OWNER)
    e=reload(tmp_path,m)
    assert not any(x.condition_id=='condition:typed.golden_statue' for x in e.state.actors[OWNER].conditions.values())
    assert e.state.actors[OWNER].action_available and e.state.actors[OWNER].bonus_action_available and e.state.actors[OWNER].reaction_available
    assert any(x.event_type=='HEALING_APPLIED' and x.source_definition_id==G+'immortal_gold'
               and x.payload['offered']==5*e.state.actors[OWNER].proficiency_bonus for x in e.events)
    assert len([z for z in e.state.zones.values() if z.active and z.owner_id==OWNER
                and z.source_definition_id.endswith('golden_aura')])==1


def test_native_projection_profile_binding_keeps_seals_and_fail_closed_policy():
    import json,hashlib
    from app.core import sha256_json
    contracts=ROOT/'projector/contracts'
    profile=json.loads((contracts/'C2AR1_Stage_Aware_Validation_Profile.json').read_bytes())
    contract=json.loads((contracts/'C2AR1_Stage2_v3_Projection_Contract.json').read_bytes())
    for doc in (profile,contract):
        assert doc['seal_sha256']==sha256_json({k:v for k,v in doc.items() if k!='seal_sha256'})
    assert contract['validation_profile']['sha256']==hashlib.sha256((contracts/'C2AR1_Stage_Aware_Validation_Profile.json').read_bytes()).hexdigest()
    assert contract['unsupported_policy']=='FAIL_CLOSED'
    assert contract['schema_routing']['mixed']==contract['schema_routing']['unknown']=='reject'


def test_native_readiness_profile_sidecar_uses_consumer_filename():
    from hashlib import sha256
    p=ROOT/'character_sheet/contracts/Tianxia_Character_Sheet_Readiness_Profile_R1.json'
    digest,name=p.with_suffix('.json.sha256').read_text().strip().split(None,1)
    assert name==p.name and digest==sha256(p.read_bytes()).hexdigest()



def test_acquired_source_world_input_and_journey_collection_reach_native_hit(catalog_environment,monkeypatch,tmp_path):
    import json,zipfile
    import pytest
    from copy import deepcopy
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.ext.goruden_journey import FACT,FIST,KIND,SCOPE
    from tests.h1_support import sheet as control_sheet
    from tests.worker2_support import settle
    acquired=acquire(catalog_environment,monkeypatch)
    owner='actor:factory.gold';friend='actor:factory.friend';foe='actor:factory.foe'
    for mode in ('fresh','reopen','expired'):
        expired=mode=='expired'
        root=tmp_path/mode
        for pid,doc in [('gold',acquired),('friend',control_sheet([],cl=18)),('foe',control_sheet([],cl=18))]:
            doc=deepcopy(doc)
            if pid=='foe':doc['ability_scores_and_statistics']['armor_class']={'base_value':1,'value':1}
            folder=root/'portable_characters'/pid;folder.mkdir(parents=True)
            with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
        def cold():return CombatService(ROOT,root)
        cold().tabletop_maps.save({'display_name':'Goruden courtyard','width_squares':20,'height_squares':20,'terrain':[]})
        arena=next(k for k,v in cold().factory_arenas().items() if v['display_name']=='Goruden courtyard')
        initial=cold().create_journey(project_ids=['gold','friend','foe'],arena_id=arena,
            positions={owner:{'x':3,'y':6},friend:{'x':4,'y':6},foe:{'x':3,'y':7}},
            base_paces={owner:30,friend:30,foe:30})
        jid=initial['journey_id']
        def intent(aid,kind,payload):
            before=cold().journey_state(jid)
            result=cold().journey_act(jid,before['revision'],aid,kind,payload)
            assert result==cold().journey_state(jid)
            return result
        fact={'source':FIST,'subject':foe,'kind':KIND,'scope':SCOPE,'value':1,'expires_at':60,'readers':[]}
        with pytest.raises(ValueError,match='table-owner'):
            cold().journey_act(jid,0,foe,'declare_fact',fact)
        assert cold().journey_state(jid)==initial
        state=cold().journey_world_fact(jid,0,fact)
        assert state['events'][-1]['kind']=='WORLD_FACT_DECLARED' and 'value' not in state['events'][-1]
        intent(owner,'goruden_sheen',{'hidden':1})
        state=intent(owner,'goruden_collect',{})
        previous_receipt=state['actors'][foe]['bundle']['goruden_continuation']['corruption']['record']['receipt_id']
        # The actual world-owner boundary may run immediately before combat.
        # Its new receipt must be sealed by the owner's pure pre-genesis hook,
        # rather than read from a late enter_combat observer or stale bundle.
        state=cold().journey_world_fact(jid,state['revision'],fact)
        newest_receipt=state['fact_consent_admission'][-1]['receipt_id']
        assert newest_receipt!=previous_receipt
        assert state['actors'][foe]['bundle']['goruden_continuation']['corruption']['record']['receipt_id']==previous_receipt
        if mode=='reopen':
            state=intent(owner,'wait',{'seconds':5})
            scene=state['actors'][owner]['source_states'][G.removesuffix('.feature.')]['scene']
            intent(owner,'finish',{})
            state=cold().create_journey(project_ids=['gold','friend','foe'],arena_id=arena,
                positions={owner:{'x':3,'y':6},friend:{'x':4,'y':6},foe:{'x':3,'y':7}},
                base_paces={owner:30,friend:30,foe:30})
            jid=state['journey_id']
            assert state['seconds']==0
            assert state['actors'][owner]['bundle']['goruden_continuation']['scene']==scene
            carried=state['actors'][foe]['bundle']['goruden_continuation']['corruption']
            assert carried['record']['receipt_id']==newest_receipt
            assert carried['remaining_num']==55 and carried['remaining_den']==1
        if expired:state=intent(owner,'wait',{'seconds':60})
        result=cold().journey_start_combat(jid,state['revision'],{owner:'team:gold',friend:'team:gold',foe:'team:foe'},maximum_rounds=15)
        mid=result['match_id'];table=TabletopService(cold(),root)
        turn(table,mid,owner)
        e=reload(root,mid)
        assert any(x.condition_id=='condition:typed.golden_sheen_suppressed' for x in e.state.actors[owner].conditions.values())
        classifications=[x for x in e.state.actors[foe].conditions.values() if x.condition_id==FACT]
        assert bool(classifications) is (not expired)
        if classifications:
            assert classifications[0].data['receipt_id']==newest_receipt
            assert classifications[0].data['authority_actor_id']=='table_owner'
            assert classifications[0].source_actor_id is None
        strike=next(a.display_name for a in e.action_catalog.values() if a.owner_id==owner
                    and any(r.get('type')=='attack' and r.get('attack_kind')=='unarmed'
                            for r in ((a.parameters or {}).get('typed') or {}).get('effects') or []))
        for attempt in range(5):
            cid=play_candidate(cold(),mid,strike,target=foe).candidate_id
            settle(table,mid,cid,picks={'choice:needle.path_hit.'+FIST:['Extra Radiant Damage']})
            e=reload(root,mid)
            packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.actor_id==owner
                     and x.payload.get('damage_type')=='RADIANT']
            if packets:break
            turn(table,mid,foe);turn(table,mid,owner)
        assert packets
        pb=e.state.actors[owner].proficiency_bonus
        assert packets[-1].payload['rolled_or_pending_damage']==pb*(1 if expired else 2)



@pytest.mark.parametrize('cl',[3,6,10,14,17])
def test_native_acquisition_progression_does_not_grant_future_goruden_rows(catalog_environment,monkeypatch,tmp_path,cl):
    acquired=acquire(catalog_environment,monkeypatch,cl)
    bundle=compile_character(acquired,actor_id=OWNER,reaction_plan={'ask':True})
    passives=bundle['typed_passives']
    assert any(r.get('feature_id')==G+'gilded_bones' for r in passives) is (cl>=6)
    assert any(r.get('feature_id')==G+'radiant_fist' for r in passives) is (cl>=10)
    assert any((a.get('parameters',{}).get('typed') or {}).get('source')==G+'golden_aura'
               for a in bundle['action_catalog']) is (cl>=14)
    assert not any(r.get('kind')=='immortal_gold_final' for r in passives)
    if cl==3:
        from combat.gate5_service import CombatService
        runtime=CombatService(ROOT,tmp_path/'future-source-guard')
        arena=runtime.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
        state=runtime.journeys.create([bundle],arena,{OWNER:{'x':3,'y':6}},{OWNER:30})
        with pytest.raises(ValueError,match='does not admit'):
            runtime.journey_world_fact(state['journey_id'],0,{
                'source':G+'radiant_fist','subject':OWNER,'kind':'active_daemonic_corruption',
                'scope':'ongoing_source','value':1,'expires_at':60,'readers':[]})
        assert runtime.journey_state(state['journey_id'])==state
