"""Review regressions using acquired sheets, table commits and cold replay."""
import pytest
from tests.test_mgr_t14_iron_cloth import (
    SILKEN, BINDING, PRISON, THOUSAND, CLOTH, QI, CHOICE, play, use, whip_of,
)
from tests.worker2_support import OWNER, FOE, reload, turn, settle


@pytest.fixture(scope='module',autouse=True)
def review_source_identity(request):
    import hashlib,json
    root=__import__('pathlib').Path(__file__).resolve().parents[1]
    paths=['combat/ext/silken_whip.py','combat/ext/qi_subpaths_mason.py','combat/gate2_engine.py']
    terminal=request.config.pluginmanager.get_plugin('terminalreporter')
    if terminal:
        terminal.write_line('IRON_CLOTH_REVIEW_SOURCE '+json.dumps({p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths},sort_keys=True))


@pytest.mark.parametrize('feature,activate,control',[
    (SILKEN,'Silken Whip','Silken Whip: end infusion'),
    (PRISON,'Silken Prison','Silken Prison: end concentration'),
    (THOUSAND,'Thousand Ribbons','Thousand Ribbons: end concentration'),
    (BINDING,'Silken Whip','Binding Ribbon: release'),
])
def test_release_controls_reach_builtin_ai_context(tmp_path,feature,activate,control):
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    from tests.h1_support import ROOT
    combat,table,mid=play(tmp_path,[SILKEN,feature],owner_dc=100,seed='IRON-BIND')
    use(combat,table,mid,activate,**({'at':(6,6)} if feature==PRISON else {}))
    if feature==BINDING:
        for _ in range(6):
            use(combat,table,mid,'Silken Whip Attack',target=FOE)
            e=reload(tmp_path,mid)
            if any(c.data.get('binding') for c in e.state.actors[FOE].conditions.values()):break
            settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
        else:pytest.fail('No committed qualifying hit')
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    e=reload(tmp_path,mid)
    ctx=build_decision_context(e,PolicyLibrary(ROOT).for_actor(OWNER)[0],for_ai=True)
    ids={c.source_definition_id for c in ctx.legal_candidates}
    assert any(a.display_name==control and aid in ids for aid,a in e.action_catalog.items())
    # The same canonical control still commits on a manual seat and reloads.
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='MANUAL')
    use(combat,table,mid,control)
    reload(tmp_path,mid)


@pytest.mark.parametrize('bind',[False,True])
def test_encounter_infusion_continues_through_resume_reopen_and_next_encounter(tmp_path,monkeypatch,bind):
    from fractions import Fraction
    from combat.gate5_service import CombatService,FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT,sheet
    from combat.ext.effect_durations import parse_round
    aid=FACTORY_ACTOR_PREFIX+'cloth';bid=FACTORY_ACTOR_PREFIX+'foe'
    features=[SILKEN]+(['tianxia.path.qi_cultivation.feature.domain_armament'] if bind else [])
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:
        sheet(features if pid=='cloth' else [],cl=18,key='CHA',kit=CLOTH,name=pid))
    scene={'stable_id':'journey:cloth','display_name':'Cloth road','width_squares':12,'height_squares':12,'square_size_ft':5,
        'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':scene})
    cold=lambda:CombatService(ROOT,tmp_path)
    state=cold().create_journey(project_ids=['cloth','foe'],arena_id='scene',positions={aid:{'x':2,'y':2},bid:{'x':5,'y':2}},
        base_paces={aid:5,bid:5},control_modes={aid:'MANUAL',bid:'MANUAL'})
    jid=state['journey_id']
    state=cold().journey_act(jid,state['revision'],aid,'iron_cloth_infuse',{'item_key':'tianxia.mortal.gear.robe','fabric_kind':'flexible_fabric'})
    if bind:state=cold().journey_act(jid,state['revision'],aid,'iron_cloth_bind',{'item_key':'tianxia.mortal.gear.robe'})
    mid=cold().journey_start_combat(jid,state['revision'],{aid:'team:a',bid:'team:b'},maximum_rounds=1)['match_id']
    table=TabletopService(cold(),tmp_path)
    for _ in range(6):
        loaded=cold()._load_session(mid)
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert loaded.engine.state.terminal_result is not None
    assert loaded.mechanical.replay()['status']=='PASS'
    e=loaded.engine;w=next(c for c in e.state.actors[aid].conditions.values() if c.condition_id=='condition:typed.silken_whip')
    deadline=parse_round(w.expires_on);slots=len(e.state.initiative_order)
    expected=Fraction(((deadline[0]-e.state.round_number)*slots+deadline[1]-e.state.current_slot_index)*6,slots)
    state=cold().journey_state(jid)
    terminal_before=loaded.engine.state.model_dump_json()
    state=cold().journey_resume(jid,state['revision'])
    assert cold()._load_session(mid).engine.state.model_dump_json()==terminal_before
    state=cold().journey_act(jid,state['revision'],aid,'wait',{'seconds':60})
    saved=state['actors'][aid]['source_states']['tianxia.subpath.qi.iron_cloth_cultivator']
    assert Fraction(saved['remaining_num'],saved['remaining_den'])==expected-60
    state=cold().journey_act(jid,state['revision'],aid,'finish',{})
    assert state['phase']=='finished'
    state=cold().create_journey(project_ids=['cloth','foe'],arena_id='scene',positions={aid:{'x':2,'y':2},bid:{'x':5,'y':2}},
        base_paces={aid:5,bid:5},control_modes={aid:'MANUAL',bid:'MANUAL'})
    restored=state['actors'][aid]['bundle']['iron_cloth_setup']
    assert restored['item_key']==w.data['item_key']
    assert bool(restored.get('domain_bound'))==bind
    result=cold().journey_start_combat(state['journey_id'],state['revision'],{aid:'team:a',bid:'team:b'})
    fresh=cold()._load_session(result['match_id'])
    assert fresh.mechanical.replay()['status']=='PASS'
    actor=fresh.engine.state.actors[aid]
    new=next(c for c in actor.conditions.values() if c.condition_id=='condition:typed.silken_whip')
    assert new.data['item_object']==w.data['item_object']
    assert new.data['fabric_receipt']==w.data['fabric_receipt']
    assert bool(new.data.get('domain_bound'))==bind


def test_destroy_repair_exact_cloth_reinfuse_and_cold_replay(tmp_path):
    from tests.h1_support import sheet
    from combat.fact_consent_admission import combat_records
    repairs='tianxia.subpath.qi.mason_cultivator.feature.emergency_repairs'
    foe=sheet(['TAL_BERSERKER_GREAT_DESTROYER','TAL_AXES_GATE_SPLITTING_BLOW'],cl=18,key='CHA',name='Mara',
        kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.fu','name':'Fu (Short Axe)','quantity':1}]}})
    kit={'starting_kit':{'items':CLOTH['starting_kit']['items']*2}}
    combat,table,mid=play(tmp_path,[SILKEN],cl=6,ally_talents=[repairs],owner_kit=kit,foe_sheet=foe,
        foe_position={'x':4,'y':7},seed='IRON-REPAIR')
    use(combat,table,mid,'Silken Whip')
    e=reload(tmp_path,mid);oid=whip_of(e).data['object_id']
    for _ in range(10):
        turn(table,mid,FOE);e=reload(tmp_path,mid)
        rows=[c for c in e.legal_candidates() if c.target_ids==(oid,) and
            'Gate-Splitting Blow' in e.action_catalog[c.source_definition_id].display_name and
            e.action_catalog[c.source_definition_id].costs]
        assert rows
        settle(table,mid,rows[0].candidate_id)
        e=reload(tmp_path,mid)
        if e.state.objects[oid].destroyed:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    else:pytest.fail('The acquired object attack never destroyed the real cloth')
    broken=lambda e:[c for c in e.state.actors[OWNER].conditions.values() if c.condition_id=='condition:typed.iron_cloth_broken']
    assert broken(e) and whip_of(e) is None
    turn(table,mid,OWNER)
    assert not any(c.target_ids==(oid,) for c in reload(tmp_path,mid).legal_candidates()), 'No repair or ordinary attack on a destroyed object without its source opt-in'
    use(combat,table,mid,'Silken Whip',choices={CHOICE+'fabric':[OWNER+'|tianxia.mortal.gear.robe.2'],
        'choice:needle.fact_admission.iron_cloth_fabric':['flexible_fabric']})
    assert broken(reload(tmp_path,mid)), 'Creating another physical cloth object cannot repair this identity'
    use(combat,table,mid,'Silken Whip: end infusion')
    turn(table,mid,'actor:factory.worker2-ally')
    before_qi=reload(tmp_path,mid).state.actors['actor:factory.worker2-ally'].resources[QI]
    use(combat,table,mid,'Emergency Repairs: Repair Structure with sufficient material',target=oid)
    e=reload(tmp_path,mid);obj=e.state.objects[oid]
    assert obj.current_hp>0 and not obj.destroyed
    assert e.state.actors['actor:factory.worker2-ally'].resources[QI]==before_qi-2
    assert obj.component['inventory_identity']==OWNER+'|tianxia.mortal.gear.robe'
    assert obj.component['repair_declaration']['subject']=='actor:factory.worker2-ally'
    assert not broken(e)
    turn(table,mid,OWNER)
    use(combat,table,mid,'Silken Whip',choices={CHOICE+'fabric':[OWNER+'|tianxia.mortal.gear.robe'],
        'choice:needle.fact_admission.iron_cloth_fabric':['flexible_fabric']})
    e=reload(tmp_path,mid)
    assert whip_of(e).data['object_id']==oid
    assert e.state.objects[oid].current_hp==obj.current_hp
    assert not broken(e)
