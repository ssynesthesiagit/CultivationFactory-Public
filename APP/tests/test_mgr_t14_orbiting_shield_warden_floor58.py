"""Native portable-sheet compilation, table commits and cold replay.

The authenticated creation fixture admits its mandatory native Sphere/free-Talent
grant. Its assertions certify Warden acquisition and table/replay, not the combat
behavior of unrelated Fire talents.
"""
import pytest
from combat.gate5_service import CombatService
from tests import r1i_service_support as s
from tests.h1_support import ROOT, sheet
from combat.factory_compiler import compile_character
P='tianxia.subpath.qi.orbiting_shield_warden.feature.'
RAISE=P+'raise_the_orbiting_ward'
CONST=P+'shield_constellation'
NINE=P+'nine_shields_seal_heaven'


def cold(tmp_path,mid):
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']=='PASS'
    assert session.mechanical.replay()['status']=='PASS'
    return session.engine


def test_manifest_pays_qi_and_creates_one_destructible_non_actor_after_reload(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[RAISE],owner_cl=3,wide=True)
    commit(s.candidate(table,mid,'Manifest Ward'))
    engine=cold(tmp_path,mid)
    owner=engine.state.actors[s.OWNER]
    assert owner.resources['resource:core.qi']==29
    wards=[o for o in engine.state.objects.values() if o.object_kind=='QI_CONSTRUCT']
    assert len(wards)==1
    ward=wards[0]
    assert ward.ac==18 and ward.maximum_hp==9
    assert ward.damage_immunities==('POISON','PSYCHIC')
    assert ward.component['resist']==['BLUDGEONING','PIERCING','SLASHING']
    assert ward.component['blocks'] is False
    assert ward.object_id not in engine.state.actors
    assert ward.object_id not in engine.state.initiative_order
    assert engine.grid.distance_ft(owner.position,ward.position)<=30
    assert any(c.data.get('object_id')==ward.object_id for c in owner.conditions.values())


@pytest.mark.parametrize('cl',[1,2])
def test_raise_requires_printed_cl_even_if_leaf_is_present(cl):
    b=compile_character(sheet([RAISE],cl=cl),actor_id=s.OWNER)
    assert not any(a['parameters'].get('warden') for a in b['action_catalog'])


def test_default_inert_wrong_owner():
    b=compile_character(sheet([],cl=20),actor_id=s.FOE)
    assert not any(a['parameters'].get('warden') for a in b['action_catalog'])


def test_constellation_pays_once_and_dismissal_survives_replay(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[RAISE,CONST],owner_cl=10,wide=True)
    commit(s.candidate(table,mid,'Manifest Constellation'))
    engine=cold(tmp_path,mid)
    wards=[o for o in engine.state.objects.values() if o.object_kind=='QI_CONSTRUCT' and not o.destroyed]
    assert len(wards)==3
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==27
    commit(s.candidate(table,mid,'Dismiss Orbiting Shields'))
    engine=cold(tmp_path,mid)
    assert not any(o.object_kind=='QI_CONSTRUCT' and not o.destroyed for o in engine.state.objects.values())


def test_source_granted_subpath_leaves_reach_the_existing_compiler():
    doc=sheet([RAISE],cl=3)
    doc['path_and_subpath']={'source_granted_subpath_feature_record_ids':[RAISE]}
    b=compile_character(doc,actor_id=s.OWNER)
    assert any(a['parameters'].get('warden')=='manifest' for a in b['action_catalog'])
    other=compile_character(doc,actor_id=s.SECOND)
    assert all(a['owner_id']==s.SECOND for a in other['action_catalog'])


@pytest.mark.parametrize('cl,count',[(3,1),(10,3)])
def test_projection_never_grants_physical_shield_proficiency_or_inventory(cl,count):
    doc=sheet([RAISE,CONST] if cl>=10 else [RAISE],cl=cl)
    b=compile_character(doc,actor_id=s.OWNER)
    assert not any(i.get('shield') for i in b.get('carrying',{}).get('items',[]))
    assert 'proficiencies' not in doc


def test_journey_manifest_uses_paid_clock_and_cold_command_replay(tmp_path):
    from combat.journey import JourneyStore
    bundle=compile_character(sheet([RAISE],cl=3),actor_id=s.OWNER)
    combat=CombatService(ROOT,tmp_path/'combat')
    arena=combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    store=JourneyStore(tmp_path/'journeys')
    state=store.create([bundle],arena,{s.OWNER:{'x':3,'y':6}},{s.OWNER:3000})
    jid=state['journey_id']
    state=store.act(jid,0,s.OWNER,'warden_manifest',{'points':[{'x':3,'y':5}]})
    assert state['actors'][s.OWNER]['resources']['resource:core.qi']==29
    current=state['actors'][s.OWNER]['source_states']['source:orbiting_shield_warden']
    assert current['expires_at']==28800
    assert store.replay(jid)['status']=='PASS'
    state=store.act(jid,1,s.OWNER,'wait',{'seconds':28799})
    assert 'source:orbiting_shield_warden' in state['actors'][s.OWNER]['source_states']
    state=store.act(jid,2,s.OWNER,'wait',{'seconds':1})
    assert 'source:orbiting_shield_warden' not in state['actors'][s.OWNER]['source_states']
    assert store.replay(jid)['status']=='PASS'


def test_unowned_journey_command_rejects_without_payment_or_state(tmp_path):
    from combat.journey import JourneyStore
    bundle=compile_character(sheet([],cl=20),actor_id=s.OWNER)
    combat=CombatService(ROOT,tmp_path/'combat')
    arena=combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    store=JourneyStore(tmp_path/'journeys')
    state=store.create([bundle],arena,{s.OWNER:{'x':3,'y':6}},{s.OWNER:3000})
    before=store.load(state['journey_id']).state
    with pytest.raises(ValueError):
        store.act(state['journey_id'],0,s.OWNER,'warden_manifest',{'points':[{'x':3,'y':5}]})
    assert store.load(state['journey_id']).state==before


def test_imprisoning_earth_native_target_save_anchor_and_reload(tmp_path):
    from combat.ext import orbiting_shield_warden as w
    combat,table,mid,send,commit=s.fixture(tmp_path,list(w.LEVELS),owner_cl=18,owner_dc=50,wide=True)
    commit(s.candidate(table,mid,'Nine Shields: Imprisoning Earth',s.FOE))
    engine=cold(tmp_path,mid)
    owner,foe=engine.state.actors[s.OWNER],engine.state.actors[s.FOE]
    assert owner.resources['resource:core.qi']==22
    prison=next(c for c in foe.conditions.values() if c.condition_id==w.PRISON)
    assert prison.data['ability'] in ('STR','CHA')
    assert engine._effective_speed(foe)==0
    anchor=next(o for o in engine.state.objects.values() if (o.component or {}).get('name')=='Shield Prison Anchor')
    assert anchor.ac==50 and anchor.current_hp==162 and anchor.damage_threshold==8
    assert anchor.damage_immunities==('POISON','PSYCHIC')
    assert prison.instance_id in anchor.component['bound']['conditions']
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==s.FOE]
    assert saves
    assert owner.concentration is not None


def test_sheltered_heaven_cost_field_and_scene_use_survive_next_owner_turn(tmp_path):
    from combat.ext import orbiting_shield_warden as w
    combat,table,mid,send,commit=s.fixture(tmp_path,list(w.LEVELS),owner_cl=18,wide=True)
    commit(s.candidate(table,mid,'Nine Shields: Sheltered Heaven'))
    engine=cold(tmp_path,mid)
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==22
    zone=w.active_formation(engine,engine.state.actors[s.OWNER])
    assert zone is not None and zone.concentration_link
    from combat.ext.effect_durations import parse_round
    assert parse_round(zone.trigger_profile['placed']['until']) == (zone.created_round+10,engine.state.current_slot_index)
    assert zone.trigger_profile['placed']['mode']=='shelter'
    commit(table.state(mid)['menu']['end_turn'])
    for _ in range(8):
        if table.state(mid)['menu']['actor_id']==s.OWNER:
            break
        commit(table.state(mid)['menu']['end_turn'])
    engine=cold(tmp_path,mid)
    assert engine.state.actors[s.OWNER].turn_flags['_round_warden_nine_scene']==1
    assert not any('Nine Shields:' in g['label'] for g in table.state(mid)['menu']['actions'])


def test_general_activity_refuses_unregistered_source_without_persisting_work(tmp_path):
    from combat.journey import JourneyStore
    bundle=compile_character(sheet([RAISE],cl=3),actor_id=s.OWNER)
    arena=CombatService(ROOT,tmp_path/'combat').factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    store=JourneyStore(tmp_path/'journeys')
    state=store.create([bundle],arena,{s.OWNER:{'x':3,'y':6}},{s.OWNER:3000})
    with pytest.raises(ValueError,match='not available'):
        store.act(state['journey_id'],0,s.OWNER,'activity_start',{'source':'unknown:activity','parameters':{}})
    assert store.load(state['journey_id']).state==state


def test_actor_declaration_cannot_impersonate_native_table_owner(tmp_path):
    from combat.journey import JourneyStore
    bundle=compile_character(sheet([RAISE],cl=3),actor_id=s.OWNER)
    arena=CombatService(ROOT,tmp_path/'combat').factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    store=JourneyStore(tmp_path/'journeys')
    state=store.create([bundle],arena,{s.OWNER:{'x':3,'y':6}},{s.OWNER:3000})
    fact={'source':'system:journey.scene','subject':s.OWNER,'kind':'scene_end','scope':'scene',
          'value':'The table owner closes the scene.','expires_at':1,'readers':[s.OWNER]}
    with pytest.raises(ValueError,match='does not admit'):
        store.act(state['journey_id'],0,s.OWNER,'declare_fact',fact)
    assert store.load(state['journey_id']).state==state


def test_authenticated_creation_acquires_ward_then_table_commit_replays(tmp_path,catalog_environment):
    """Real creation/Stage2/production export; no injected ownership or receipt."""
    from copy import deepcopy
    from app.api import create_app
    from app.core import canonical_json
    from ai_provider.secrets import InMemorySecretStore
    from character_creation.current_fixture import (
        STARTING_SCORES, SELECTIONS, FIRE, ADVANCEMENT_TALENTS,
        ABANDONED_ORPHAN, HIDDEN_TOOL_CACHE, SCOUNDREL, STREET_HARDENED,
        stage2_choices, exact_stage1_response,
    )
    from combat.gate2_runtime_content import AN
    from combat.gate5_service import FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    def no_transport(*args,**kwargs):
        raise AssertionError('No live provider transport is allowed in native acquisition tests')
    app=create_app(catalog_environment['settings'],ai_transport=no_transport,ai_secret_store=InMemorySecretStore())
    builder=app.state.character_builder
    parent='tianxia.subpath.qi.orbiting_shield_warden'
    selected=deepcopy(SELECTIONS)
    selected['subpath_choice']=[parent]
    selected['advancement_skeleton']=[ADVANCEMENT_TALENTS[0]]
    created=builder.create_project(
        working_name='Orbiting Ward native acquisition',concept='Qi Cultivation; Orbiting Shield Warden; protect companions.',
        target_cl=3,power_band='standard',source_reference='Orbiting Shield Warden Open School',creation_mode='detailed',
        ability_scores=deepcopy(STARTING_SCORES),selections=selected,canonical_sphere_ids=[FIRE],
        sphere_free_talent_grants={FIRE:ADVANCEMENT_TALENTS[0]},
        ordinary_talent_ids=[],
        background_route_ids={'background_route_record_id':HIDDEN_TOOL_CACHE,'background_talent_choice_id':HIDDEN_TOOL_CACHE,
                              'background_sphere_choice_id':SCOUNDREL,'origin_insight_choice_id':STREET_HARDENED},
        generation_route='ai_bootstrap')
    pid=created['project']['project_id']
    extra_locks=[
        {'field':'character.identity.display_name','value':'Orbiting Ward native acquisition','source':'owner'},
        {'field':'character.choices.qi_cultivation_skills','value':['tianxia.fixture.skill.arcana','tianxia.fixture.skill.history'],'source':'owner'},
        {'field':'character.choices.street_hardened','value':'tianxia.fixture.street_hardened.deception','source':'owner'},
        {'field':'character.choices.language','value':'tianxia.language.classical','source':'owner'},
    ]
    existing_fields={r['field'] for r in builder.projects.get_project(pid)['project'].get('user_locks',[])}
    additions=[r for r in extra_locks if r['field'] not in existing_fields]
    if additions:builder.projects.append_user_locks(pid,additions)
    execution=app.state.character_creation
    run=execution.start(pid,execution_mode='MANUAL_CHAT',idempotency_key='warden.native.acquisition')
    # The current source authority advertises constructed-training choices.
    # Explicitly choose none, through the preferred native request contract.
    plan={'schema':'TianxiaFoundry.DelegatedSelectionIntentResponse.v1',
        'request_sha256':run['request']['request_sha256'],
        'selection_intent':{'by_slot':{**selected,'background_sphere_choice':[SCOUNDREL],
            'method_choice':[],'foundation_choice':[],'insight_priorities':[],'item_priorities':[]}},
        'acquisition_intent':{'sphere_free_talent_pairs':[{'sphere_id':FIRE,'talent_id':ADVANCEMENT_TALENTS[0]}],
            'ordinary_talent_ids':[],
            'insight_occurrences':[],'trained_choices':[], 'forged_technique_concepts':[]},
        'bounded_choices':{'background_ability':'DEX','path_progression_by_cl':{str(cl):'tianxia.path.qi_cultivation' for cl in range(1,4)},
            'path_skill_choices_by_path_id':{'tianxia.path.qi_cultivation':['Arcana','History']},
            'origin_skill_choices_by_origin_id':{STREET_HARDENED:['Deception']},
            'background_language_choices_by_background_id':{ABANDONED_ORPHAN:['Classical']}},
        'owner_descriptive_fields':{'identity':{'name':'Orbiting Ward native acquisition','title':'Shield-Bound Adept'},
            'concept':'Qi Cultivation; Orbiting Shield Warden; protect companions.'}}
    if run['request']['delegated_choice_envelope'].get('explicit_forging_contract') is None:
        plan['acquisition_intent'].pop('forged_technique_concepts')
    preview=execution.submit_manual(run['run_id'],response_text=canonical_json(plan),request_sha256=run['request']['request_sha256'])
    assert preview['status']=='READY_FOR_REVIEW',preview.get('blockers')
    finalized=execution.finalize(run['run_id'])
    assert finalized['status']=='CLEAN_AND_FINALIZED',finalized
    combat=app.state.combat
    owner=FACTORY_ACTOR_PREFIX+pid
    result=combat.create_factory_match(project_ids=[pid],opponent_actor_ids=[AN],
        control_modes={owner:'MANUAL',AN:'MANUAL'},match_seed='WARDEN-AUTHENTICATED-CL3',maximum_rounds=3)
    mid=result['match_id']
    table=TabletopService(combat,catalog_environment['settings'].data_dir)
    def commit(cid):
        answers=[]
        for _ in range(32):
            menu=table.state(mid)['menu']
            result=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers)
            if result['status']=='COMMITTED':return result
            assert result['status']=='REACTION_REQUIRED',result
            p=result['reaction'];answer={**p['context'],'selection':'DECLINE'}
            if p.get('choice'):
                answer.update(selection='USE',option_ids=[p['choice']['options'][0]['id']])
            answers.append(answer)
        raise AssertionError('Too many native choices')
    while table.state(mid)['menu']['actor_id']!=owner:
        commit(table.state(mid)['menu']['end_turn'])
    before=combat._load_session(mid).engine.state.actors[owner].resources['resource:core.qi']
    cid=next(o['candidate_id'] for g in table.state(mid)['menu']['actions'] if 'Manifest Ward' in g['label'] for o in g['options'])
    commit(cid)
    session=CombatService(ROOT,catalog_environment['settings'].data_dir)._load_session(mid)
    assert session.verify()['status']=='PASS'
    assert session.mechanical.replay()['status']=='PASS'
    assert session.engine.state.actors[owner].resources['resource:core.qi']==before-1
    assert any(o.object_kind=='QI_CONSTRUCT' and o.maximum_hp==9 for o in session.engine.state.objects.values())


def choose_and_commit(table,mid,send,cid,selected):
    """Supply real controller answers without editing an engine or bundle."""
    answers=[]
    for _ in range(48):
        result=send(cid,answers)
        if result['status']=='COMMITTED':return result
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];answer={**p['context'],'selection':'DECLINE'}
        if p.get('choice'):
            options=p['choice']['options']
            exact=selected(p,options)
            if exact is None:
                exact=(p['choice'].get('preferred') or [options[0]['id']])[:1]
            answer.update(selection='USE',option_ids=exact)
        answers.append(answer)
    raise AssertionError('Too many native source choices')


def test_ward_hovers_moves_vertically_once_and_cold_replays(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[RAISE],owner_cl=3,wide=True)
    def point(wanted):
        def select(prompt,options):
            ids=[o['id'] for o in options]
            return [wanted] if wanted in ids else None
        return select
    choose_and_commit(table,mid,send,s.candidate(table,mid,'Manifest Ward'),point('cell:3,5,1'))
    engine=cold(tmp_path,mid)
    ward=next(o for o in engine.state.objects.values() if o.object_kind=='QI_CONSTRUCT' and not o.destroyed)
    assert ward.position.model_dump()=={'x':3,'y':5,'z':1}
    choose_and_commit(table,mid,send,s.candidate(table,mid,'Move Shields'),point('cell:3,5,2'))
    engine=cold(tmp_path,mid)
    ward=engine.state.objects[ward.object_id]
    assert ward.position.model_dump()=={'x':3,'y':5,'z':2}
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==29
    assert not any('Move Shields' in g['label'] for g in table.state(mid)['menu']['actions'])
    assert ward.object_id not in engine.state.actors


def test_successful_prison_save_halves_live_speed_and_retains_source_expiry(tmp_path):
    from combat.ext import orbiting_shield_warden as w
    combat,table,mid,send,commit=s.fixture(tmp_path,list(w.LEVELS),owner_cl=18,owner_dc=1,wide=True)
    commit(s.candidate(table,mid,'Nine Shields: Imprisoning Earth',s.FOE))
    engine=cold(tmp_path,mid)
    foe=engine.state.actors[s.FOE]
    assert any(c.condition_id==w.SLOWED for c in foe.conditions.values())
    assert not any(c.condition_id==w.PRISON for c in foe.conditions.values())
    assert engine._effective_speed(foe)==15
    assert any(m.target_field=='speed_halved' and m.expires_on=='END_OF_SOURCE_NEXT_TURN' for m in foe.modifiers.values())
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==22


def test_triggered_action_identity_rejects_another_owner_without_spending(tmp_path):
    from combat.typed_reactions import generic_reaction_context
    from combat.ext import orbiting_shield_warden as w
    combat,table,mid,send,commit=s.fixture(tmp_path,[RAISE,w.DEFLECT],owner_cl=6,wide=True)
    engine=cold(tmp_path,mid)
    owner,foe=engine.state.actors[s.OWNER],engine.state.actors[s.FOE]
    action=next(a for a in engine.action_catalog.values() if a.owner_id==s.OWNER and a.parameters.get('warden')=='deflect')
    before=engine.state.model_dump(mode='json')
    with pytest.raises(ValueError,match='own acquired registered action'):
        generic_reaction_context(engine,foe,owner,{'feature_id':w.DEFLECT,'source_action_id':action.source_definition_id})
    assert engine.state.model_dump(mode='json')==before


def test_native_volume_search_requires_a_finite_budget_and_keeps_ground_routes(tmp_path):
    from combat.gate2_runtime_models import Position
    combat,table,mid,send,commit=s.fixture(tmp_path,[],wide=True)
    engine=cold(tmp_path,mid)
    before=engine.state.model_dump(mode='json')
    start,goal=Position(x=8,y=8),Position(x=8,y=8,z=2)
    with pytest.raises(ValueError,match='finite'):
        engine.grid.shortest_path(start,goal,volume=True)
    path,cost=engine.grid.shortest_path(start,goal,volume=True,max_cost_ft=10)
    assert cost==10 and path[0]==start and path[-1]==goal
    ground=engine.grid.shortest_path(start,Position(x=10,y=8),max_cost_ft=10)
    assert ground is not None and all(p.z==0 for p in ground[0])
    assert engine.state.model_dump(mode='json')==before


def test_native_manifest_settlement_binds_the_paid_owner_and_replays(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[RAISE],owner_cl=3,wide=True)
    commit(s.candidate(table,mid,'Manifest Ward'))
    engine=cold(tmp_path,mid)
    rows=[e for e in engine.events if e.actor_id==s.OWNER and e.payload.get('activation_settlement')]
    assert len(rows)==1
    row=rows[0].payload['activation_settlement']
    assert row['actor_id']==s.OWNER and row['activation_id'].startswith('native:')
    assert row['payments']==[['resource:core.qi',1]]
    assert row['net_payments']==[['resource:core.qi',1]] and row['refunds']==[]
    spent=[e for e in engine.events if e.event_type=='RESOURCE_SPENT' and e.actor_id==s.OWNER]
    assert len(spent)==1 and spent[0].source_definition_id==row['source_id']
    assert spent[0].sequence<rows[0].sequence
    assert not any(e.actor_id!=s.OWNER and e.payload.get('activation_settlement') for e in engine.events)


def test_interposition_remains_an_owner_choice_on_another_manual_turn_and_pays_once(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[RAISE],owner_cl=3,owner_ac=2,foe_score=10,
        seed='WARDEN-INTERPOSE-ABSORB',wide=True)
    def source_answers(prompt,options):
        ids=[o['id'] for o in options]
        for desired in ('cell:3,5,0',s.OWNER,'absorb'):
            if desired in ids:return [desired]
        return None
    choose_and_commit(table,mid,send,s.candidate(table,mid,'Manifest Ward'),source_answers)
    choose_and_commit(table,mid,send,table.state(mid)['menu']['end_turn'],source_answers)
    for _ in range(6):
        if table.state(mid)['menu']['actor_id']==s.FOE:break
        choose_and_commit(table,mid,send,table.state(mid)['menu']['end_turn'],source_answers)
    assert table.state(mid)['menu']['actor_id']==s.FOE
    cid=s.candidate(table,mid,'Unarmed Strike',s.OWNER)
    answers=[];seen=False
    for _ in range(48):
        result=send(cid,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];answer={**p['context'],'selection':'DECLINE'}
        if p.get('choice'):
            options=p['choice']['options'];ids=[o['id'] for o in options]
            if 'absorb' in ids:
                assert p['context']['reactor_id']==s.OWNER
                seen=True
            selected=source_answers(p,options)
            answer.update(selection='USE',option_ids=selected if selected is not None else (p['choice'].get('preferred') or [ids[0]])[:1])
        answers.append(answer)
    else:raise AssertionError('Too many native attack decisions')
    assert seen,'The manual Warden must receive its own off-turn Interposition choice.'
    engine=cold(tmp_path,mid)
    owner=engine.state.actors[s.OWNER]
    assert owner.resources['resource:core.qi']==28
    assert owner.current_hp==500 and owner.reaction_available is False
    settlements=[e.payload['activation_settlement'] for e in engine.events if e.actor_id==s.OWNER and e.payload.get('activation_settlement')]
    assert len(settlements)==2 and len({r['activation_id'] for r in settlements})==2
    assert all(r['net_payments']==[['resource:core.qi',1]] for r in settlements)


def real_shield_journey(tmp_path,*,trained=True):
    from combat.ext.qi_path import ARMAMENT
    features=[RAISE,ARMAMENT]+(['SHIELD_BASE_SHIELD_TRAINING'] if trained else [])
    doc=sheet(features,cl=10,kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.armor.shield','quantity':1}]}})
    bundle=compile_character(doc,actor_id=s.OWNER)
    combat=CombatService(ROOT,tmp_path/'combat')
    arena=combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    state=combat.journeys.create([bundle],arena,{s.OWNER:{'x':3,'y':6}},{s.OWNER:3000})
    item=next(r for r in bundle['carrying']['items'] if r.get('shield'))
    return combat,state,item


def record_native_shield_profile(combat,state,item,*,source_cl=0):
    from combat.ext.qi_path import ARMAMENT
    from combat.fact_consent_admission import digest
    from combat.object_rules import stats
    # Material/sentience are explicit GM-collected facts about this real item.
    # Durability comes from the existing native object rules, never Ward HP.
    physical=stats({'material':'iron','size':'small','resilient':True})
    return combat.journey_world_fact(state['journey_id'],state['revision'],{
        'source':ARMAMENT,'subject':s.OWNER,'kind':'shield_item_profile',
        'scope':'item:'+s.OWNER+'|'+item['key'],
        'value':{'item_sha256':digest(item),'source_rule':f'Qi R4 actual-item Source CL adjudication: the scenario GM explicitly declares this item Source CL {source_cl}; native object rules for the GM-declared Small resilient iron shield',
                 'source_cl':source_cl,'ac':physical['ac'],'hp':physical['hp'],'threshold':physical['threshold'] or 0,
                 'resist':list(physical['resist']),'immune':list(physical['immune']),'sentience':'nonsentient','artifact':0},
        'expires_at':86400,'readers':[s.OWNER]})


def test_real_item_binding_is_six_hundred_committed_seconds_then_cold_journey_replay(tmp_path):
    from combat.ext.qi_path import ARMAMENT
    from combat.ext.orbiting_shield_warden import BOND
    combat,state,item=real_shield_journey(tmp_path)
    jid=state['journey_id']
    state=record_native_shield_profile(combat,state,item)
    state=combat.journey_act(jid,state['revision'],s.OWNER,'activity_start',{
        'source':ARMAMENT,'parameters':{'inventory_owner':s.OWNER,'item_key':item['key']}})
    state=combat.journey_act(jid,state['revision'],s.OWNER,'activity_work',{'seconds':599})
    assert BOND not in state['actors'][s.OWNER]['source_states']
    state=combat.journey_act(jid,state['revision'],s.OWNER,'activity_work',{'seconds':1})
    bond=state['actors'][s.OWNER]['source_states'][BOND]
    assert bond['bound_at']==600 and bond['item_key']==item['key']
    assert bond['profile']['hp']!=30  # not the CL10 projected Ward's 3×CL profile
    assert state['actors'][s.OWNER]['resources']['resource:core.qi']==30
    fresh=CombatService(ROOT,tmp_path/'combat')
    assert fresh.journey_state(jid)==state
    assert fresh.journey_replay(jid)['status']=='PASS'
    assert len([e for e in state['events'] if e['kind']=='ACTIVITY_FINISHED'])==1


def test_binding_rejects_missing_proficiency_and_interrupted_work_is_not_preparation(tmp_path):
    from combat.ext.qi_path import ARMAMENT
    from combat.ext.orbiting_shield_warden import BOND
    untrained,state,item=real_shield_journey(tmp_path/'untrained',trained=False)
    before=untrained.journey_state(state['journey_id'])
    with pytest.raises(ValueError,match='proficiency'):
        untrained.journey_act(state['journey_id'],state['revision'],s.OWNER,'activity_start',{
            'source':ARMAMENT,'parameters':{'inventory_owner':s.OWNER,'item_key':item['key']}})
    assert untrained.journey_state(state['journey_id'])==before
    combat,state,item=real_shield_journey(tmp_path/'interrupted')
    jid=state['journey_id'];state=record_native_shield_profile(combat,state,item)
    parameters={'source':ARMAMENT,'parameters':{'inventory_owner':s.OWNER,'item_key':item['key']}}
    state=combat.journey_act(jid,state['revision'],s.OWNER,'activity_start',parameters)
    state=combat.journey_act(jid,state['revision'],s.OWNER,'activity_work',{'seconds':300})
    state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':1})
    assert BOND not in state['actors'][s.OWNER]['source_states']
    assert 'journey:activity' not in state['actors'][s.OWNER]['source_states']
    state=combat.journey_act(jid,state['revision'],s.OWNER,'activity_start',parameters)
    state=combat.journey_act(jid,state['revision'],s.OWNER,'activity_work',{'seconds':600})
    assert state['actors'][s.OWNER]['source_states'][BOND]['bound_at']==901
    assert CombatService(ROOT,tmp_path/'interrupted'/'combat').journey_replay(jid)['status']=='PASS'


def test_foreign_primary_path_with_no_acquired_qi_profile_is_inert():
    doc=sheet([RAISE,CONST,NINE],cl=18)
    doc['identity']['path']='Body Tempering'
    doc['path_and_subpath']['paths']=[{'path_id':'tianxia.path.body_tempering','effective_cl':18,'key_ability':'STR'}]
    result=compile_character(doc,actor_id=s.OWNER)
    assert not any(r.get('block')=='orbiting_warden' for r in result['typed_passives'])
    assert not any(a['parameters'].get('warden') for a in result['action_catalog'])


@pytest.mark.parametrize('qi_cl,sheet_cl',[(6,18),(20,6)])
def test_secondary_qi_uses_its_own_key_level_and_the_sheet_cap(qi_cl,sheet_cl):
    from combat.ext.orbiting_shield_warden import DEFLECT
    doc=sheet([RAISE,DEFLECT,CONST,NINE],cl=sheet_cl,dc=50,key='STR',score=12)
    doc['identity']['path']='Body Tempering'
    doc['ability_scores_and_statistics']['primary_resource']={'name':'Stamina','maximum':30,'definitions':[{'name':'Qi','maximum':24}]}
    next(r for r in doc['ability_scores_and_statistics']['abilities'] if r['ability']=='INT').update(score=18,modifier=4)
    doc['path_and_subpath']['paths']=[
        {'path_id':'tianxia.path.body_tempering','effective_cl':sheet_cl,'key_ability':'STR'},
        {'path_id':'tianxia.path.qi_cultivation','effective_cl':qi_cl,'key_ability':'INT'}]
    result=compile_character(doc,actor_id=s.OWNER)
    rows=[a for a in result['action_catalog'] if a['parameters'].get('warden')]
    assert rows
    assert {a['parameters']['typed']['numbers']['cl'] for a in rows}=={6}
    assert {a['parameters']['typed']['numbers']['key_mod'] for a in rows}=={4}
    assert {a['parameters']['typed']['numbers']['save_dc'] for a in rows}=={16}
    assert not any(a['parameters']['warden'] in ('constellation','prison','shelter') for a in rows)
    assert any(r['resource_id']=='resource:core.qi' and r['maximum']==24 for r in result['actor_template']['resources'])


def test_real_ward_perception_uses_its_own_point_without_actor_or_owner_senses(tmp_path):
    from combat.senses import object_perceives
    combat,table,mid,send,commit=s.fixture(tmp_path,[RAISE],owner_cl=3,wide=True)
    choose_and_commit(table,mid,send,s.candidate(table,mid,'Manifest Ward'),
        lambda prompt,options:['cell:3,5,0'] if any(o['id']=='cell:3,5,0' for o in options) else None)
    engine=cold(tmp_path,mid)
    ward=next(o for o in engine.state.objects.values() if o.object_kind=='QI_CONSTRUCT' and not o.destroyed)
    target=engine.state.actors[s.FOE]
    before=engine.state.model_dump(mode='json')
    footprints=set(engine.actor_footprints)
    assert object_perceives(engine,ward,target)
    assert not object_perceives(engine,ward.model_copy(update={'suppressed':True}),target)
    assert not object_perceives(engine,ward.model_copy(update={'object_id':'foreign'}),target)
    assert engine.state.model_dump(mode='json')==before
    assert set(engine.actor_footprints)==footprints
    assert ward.object_id not in engine.state.actors


def test_constellation_only_profile_does_not_grant_raise_or_interposition(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[CONST],owner_cl=10,wide=True)
    labels=[g['label'] for g in table.state(mid)['menu']['actions']]
    assert not any('Manifest Ward' in label for label in labels)
    commit(s.candidate(table,mid,'Manifest Constellation'))
    engine=cold(tmp_path,mid)
    assert len([o for o in engine.state.objects.values() if not o.destroyed and o.object_kind=='QI_CONSTRUCT'])==3
    assert any('Move Shields' in g['label'] for g in table.state(mid)['menu']['actions'])
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==27
    assert not any(r.get('feature_id')==RAISE and r.get('block')=='orbiting_warden'
        for r in engine.typed_passive_rows[s.OWNER])


def test_triggered_geometry_rejects_unpublished_origin_before_payment(tmp_path):
    from combat.typed_reactions import reaction_activation
    from combat.ext import orbiting_shield_warden as w
    combat,table,mid,send,commit=s.fixture(tmp_path,[RAISE,w.DEFLECT],owner_cl=6,wide=True)
    engine=cold(tmp_path,mid)
    owner,foe=engine.state.actors[s.OWNER],engine.state.actors[s.FOE]
    action=next(a for a in engine.action_catalog.values() if a.owner_id==s.OWNER and a.parameters.get('warden')=='deflect')
    before=engine.state.model_dump(mode='json')
    with pytest.raises(ValueError,match='current published|registered action'):
        with reaction_activation(engine,owner,foe,{'feature_id':w.DEFLECT,'source_action_id':action.source_definition_id,'free':True},
            range_origin={'id':'foreign','label':'Foreign origin','position':{'x':4,'y':6}}):
            raise AssertionError('Unpublished origins must never activate')
    assert engine.state.model_dump(mode='json')==before


def test_last_paid_qi_applies_native_exhaustion_after_resource_event_and_cold_replays(tmp_path):
    def last_point(bundles):
        owner=next(b for b in bundles if b['actor_id']==s.OWNER)
        next(r for r in owner['actor_template']['resources'] if r['resource_id']=='resource:core.qi')['initial']=1
        from combat.canonical import canonical_sha256
        owner.pop('bundle_sha256',None);owner['bundle_sha256']=canonical_sha256(owner)
    combat,table,mid,send,commit=s.fixture(tmp_path,[RAISE],owner_cl=3,wide=True,bundle_transform=last_point)
    commit(s.candidate(table,mid,'Manifest Ward'))
    engine=cold(tmp_path,mid)
    from combat.ext.forged_exhaustion import level
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==0
    assert level(engine.state.actors[s.OWNER])==1
    spent=next(e for e in engine.events if e.event_type=='RESOURCE_SPENT' and e.actor_id==s.OWNER)
    exhausted=next(e for e in engine.events if e.event_type=='CONDITION_APPLIED' and e.actor_id==s.OWNER and e.payload.get('condition_id')=='condition:typed.exhaustion')
    assert spent.sequence<exhausted.sequence


def test_thirty_committed_journey_manifestations_reach_zero_once_and_cold_replay(tmp_path):
    combat=CombatService(ROOT,tmp_path/'combat')
    arena=combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    bundle=compile_character(sheet([RAISE],cl=3),actor_id=s.OWNER)
    state=combat.journeys.create([bundle],arena,{s.OWNER:{'x':3,'y':6}},{s.OWNER:3000})
    jid=state['journey_id']
    for _ in range(30):
        state=combat.journey_act(jid,state['revision'],s.OWNER,'warden_manifest',{'points':[{'x':3,'y':5}]})
    assert state['actors'][s.OWNER]['resources']['resource:core.qi']==0
    assert state['actors'][s.OWNER]['exhaustion']==1
    assert len([e for e in state['events'] if e['kind']=='QI_DEPLETION_EXHAUSTION'])==1
    with pytest.raises(ValueError,match='does not have enough'):
        combat.journey_act(jid,state['revision'],s.OWNER,'warden_manifest',{'points':[{'x':3,'y':5}]})
    assert CombatService(ROOT,tmp_path/'combat').journey_state(jid)==state
    assert combat.journey_replay(jid)['status']=='PASS'


def test_journey_constellation_menu_choices_commit_once_and_cold_replay(tmp_path):
    from combat.gate2_runtime_models import Position
    from combat.ext.orbiting_shield_warden import JOURNEY_KEY,DRAFT
    combat=CombatService(ROOT,tmp_path/'combat')
    arena=combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    bundle=compile_character(sheet([RAISE,CONST],cl=10),actor_id=s.OWNER)
    state=combat.journeys.create([bundle],arena,{s.OWNER:{'x':3,'y':6}},{s.OWNER:3000})
    jid=state['journey_id']
    for _ in range(2):
        state=combat.journey_act(jid,state['revision'],s.OWNER,'warden_begin',{'mode':'constellation'})
        for point in ({'x':3,'y':5,'z':0},{'x':3,'y':5,'z':1},{'x':3,'y':5,'z':2}):
            menu=combat.journeys.load(jid).menu(s.OWNER)
            choice=next(o for o in menu['options'] if o['kind']=='warden_choose_point'
                        and Position.model_validate(o['payload']['point'])==Position.model_validate(point))
            state=combat.journey_act(jid,state['revision'],s.OWNER,choice['kind'],choice['payload'])
        assert state['actors'][s.OWNER]['resources']['resource:core.qi']==30
        if _==0:
            state=combat.journey_act(jid,state['revision'],s.OWNER,'warden_cancel',{})
            assert JOURNEY_KEY not in state['actors'][s.OWNER]['source_states']
    state=combat.journey_act(jid,state['revision'],s.OWNER,'warden_confirm',{})
    assert DRAFT not in state['actors'][s.OWNER]['source_states']
    assert len(state['actors'][s.OWNER]['source_states'][JOURNEY_KEY]['shields'])==3
    assert state['actors'][s.OWNER]['resources']['resource:core.qi']==27
    assert combat.journey_replay(jid)['status']=='PASS'
    assert CombatService(ROOT,tmp_path/'combat').journey_state(jid)==state


def test_ward_remaining_lifetime_rebases_without_recovering_elapsed_time(tmp_path):
    from combat.ext.orbiting_shield_warden import JOURNEY_KEY
    combat=CombatService(ROOT,tmp_path/'combat')
    arena=combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    bundle=compile_character(sheet([RAISE],cl=3),actor_id=s.OWNER)
    store=combat.journeys
    state=store.create([bundle],arena,{s.OWNER:{'x':3,'y':6}},{s.OWNER:3000})
    jid=state['journey_id']
    state=store.act(jid,state['revision'],s.OWNER,'warden_manifest',{'points':[{'x':3,'y':5}]})
    state=store.act(jid,state['revision'],s.OWNER,'wait',{'seconds':28790})
    assert state['actors'][s.OWNER]['source_states'][JOURNEY_KEY]['remaining_num']==10
    state=store.act(jid,state['revision'],s.OWNER,'finish',{})
    assert state['phase']=='finished'
    second=store.create([bundle],arena,{s.OWNER:{'x':3,'y':6}},{s.OWNER:3000})
    assert second['seconds']==0
    assert second['actors'][s.OWNER]['source_states'][JOURNEY_KEY]['expires_at']==10
    second=store.act(second['journey_id'],second['revision'],s.OWNER,'wait',{'seconds':10})
    assert JOURNEY_KEY not in second['actors'][s.OWNER]['source_states']
    assert combat.journey_replay(second['journey_id'])['status']=='PASS'
