"""Physical identity across actual transfer, combat infusion and journey continuation."""
from tests.test_mgr_t14_iron_cloth import SILKEN,CLOTH,CHOICE,use
from tests.worker2_support import settle,turn


def test_transferred_cloth_keeps_identity_bond_and_damage_across_native_journeys(tmp_path,monkeypatch):
    from combat.gate5_service import CombatService,FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT,sheet
    from combat.ext.silken_whip import cloth_items
    aid=FACTORY_ACTOR_PREFIX+'cloth';bid=FACTORY_ACTOR_PREFIX+'foe'
    key='tianxia.mortal.gear.robe';identity=bid+'|'+key
    features=[SILKEN,'TAL_SCOUNDREL_STEAL','tianxia.path.qi_cultivation.feature.domain_armament']
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:
        sheet(features if pid=='cloth' else [],cl=18,key='CHA',kit=CLOTH,name=pid))
    scene={'stable_id':'journey:borrowed_cloth','display_name':'Cloth road','width_squares':12,'height_squares':12,
        'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':scene})
    cold=lambda:CombatService(ROOT,tmp_path)
    def create():
        return cold().create_journey(project_ids=['cloth','foe'],arena_id='scene',positions={aid:{'x':2,'y':2},bid:{'x':3,'y':2}},
            base_paces={aid:5,bid:5},control_modes={aid:'MANUAL',bid:'MANUAL'})
    state=create();jid=state['journey_id']
    mid=cold().journey_start_combat(jid,state['revision'],{aid:'team:a',bid:'team:b'},maximum_rounds=8)['match_id']
    table=TabletopService(cold(),tmp_path)
    for _ in range(6):
        turn(table,mid,aid)
        e=cold()._load_session(mid).engine
        rows=[c for c in e.legal_candidates() if c.target_ids==(bid,) and
            e.action_catalog.get(c.source_definition_id) and
            (e.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')=='TAL_SCOUNDREL_STEAL']
        assert rows
        settle(table,mid,rows[0].candidate_id)
        loaded=cold()._load_session(mid);e=loaded.engine
        if any(i['object']==identity for i in cloth_items(e,e.state.actors[aid])):break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    else:raise AssertionError('No committed native transfer succeeded')
    assert loaded.mechanical.replay()['status']=='PASS'
    use(cold(),table,mid,'Silken Whip',choices={CHOICE+'fabric':[identity],
        'choice:needle.fact_admission.iron_cloth_fabric':['flexible_fabric']})
    e=cold()._load_session(mid).engine
    old=next(c for c in e.state.actors[aid].conditions.values() if c.condition_id=='condition:typed.silken_whip')
    oid=old.data['object_id'];hp=e.state.objects[oid].current_hp
    assert old.data['item_owner']==bid and old.data['item_object']==identity
    for _ in range(20):
        loaded=cold()._load_session(mid)
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert loaded.engine.state.terminal_result is not None and loaded.mechanical.replay()['status']=='PASS'
    state=cold().journey_state(jid)
    state=cold().journey_resume(jid,state['revision'])
    state=cold().journey_act(jid,state['revision'],aid,'iron_cloth_bind',{'item_key':key})
    assert state['actors'][aid]['bundle']['iron_cloth_bond']['item_object']==identity
    cold().journey_act(jid,state['revision'],aid,'finish',{})
    state=create()
    assert state['actors'][aid]['bundle']['iron_cloth_setup']['item_object']==identity
    result=cold().journey_start_combat(state['journey_id'],state['revision'],{aid:'team:a',bid:'team:b'})
    loaded=cold()._load_session(result['match_id']);assert loaded.mechanical.replay()['status']=='PASS'
    e=loaded.engine
    w=next(c for c in e.state.actors[aid].conditions.values() if c.condition_id=='condition:typed.silken_whip')
    assert w.data['item_object']==identity and w.data['item_owner']==bid and w.data['domain_bound']==1
    assert w.data['object_id']==oid and e.state.objects[oid].current_hp==hp
    assert len([o for o in e.state.objects.values() if o.component.get('inventory_identity')==identity])==1
    assert not any(o.component.get('inventory_identity')==aid+'|'+key for o in e.state.objects.values())
