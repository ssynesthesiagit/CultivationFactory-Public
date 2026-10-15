"""Printed trigger/recipient/clock branches through native committed callers."""
import pytest
from tests.test_mgr_t14_iron_cloth import SILKEN,BINDING,FLOWING,PRISON,THOUSAND,CHOICE,CLOTH,QI,play,use
from tests.worker2_support import OWNER,ALLY,FOE,settle,turn,reload


@pytest.mark.parametrize('success',[False,True])
def test_flowing_silk_uses_distant_bound_physical_whip_and_strength_success_branch(tmp_path,monkeypatch,success):
    from combat.gate5_service import CombatService,FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT,sheet
    from combat.ext.silken_whip import whip_point
    aid=FACTORY_ACTOR_PREFIX+'cloth';bid=FACTORY_ACTOR_PREFIX+'foe';friend=FACTORY_ACTOR_PREFIX+'friend'
    features=[SILKEN,FLOWING,'tianxia.path.qi_cultivation.feature.domain_armament',
        'tianxia.path.qi_cultivation.feature.domain_armament_link']
    def owner_sheet(self,pid):
        doc=sheet(features if pid=='cloth' else [],cl=18,key='CHA',kit=CLOTH,name=pid)
        if pid=='foe':doc['ability_scores_and_statistics']['saving_throws']={'STR':100 if success else -100}
        return doc
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',owner_sheet)
    scene={'stable_id':'journey:remote_cloth','display_name':'Cloth road','width_squares':16,'height_squares':12,
        'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':scene})
    cold=lambda:CombatService(ROOT,tmp_path)
    state=cold().create_journey(project_ids=['cloth','foe','friend'],arena_id='scene',
        positions={aid:{'x':2,'y':2},bid:{'x':9,'y':3},friend:{'x':8,'y':3}},
        base_paces={aid:5,bid:5,friend:5},control_modes={aid:'MANUAL',bid:'MANUAL',friend:'MANUAL'})
    jid=state['journey_id']
    state=cold().journey_act(jid,state['revision'],aid,'iron_cloth_infuse',{'item_key':'tianxia.mortal.gear.robe','fabric_kind':'flexible_fabric'})
    state=cold().journey_act(jid,state['revision'],aid,'iron_cloth_bind',{'item_key':'tianxia.mortal.gear.robe'})
    mid=cold().journey_start_combat(jid,state['revision'],{aid:'team:a',bid:'team:b',friend:'team:a'})['match_id']
    table=TabletopService(cold(),tmp_path)
    turn(table,mid,aid)
    use(cold(),table,mid,'Domain Armament: Manifest',at=(8,2))
    loaded=cold()._load_session(mid);e=loaded.engine
    assert loaded.mechanical.replay()['status']=='PASS'
    assert e.grid.distance_ft(e.state.actors[aid].position,e.state.actors[friend].position)>15
    assert e.grid.distance_ft(whip_point(e,e.state.actors[aid]),e.state.actors[friend].position)<=15
    for _ in range(8):
        turn(table,mid,bid)
        before=cold()._load_session(mid).engine
        hp=before.state.actors[friend].current_hp;qi=before.state.actors[aid].resources[QI]
        start=before.state.event_sequence
        prompts=use(cold(),table,mid,'Unarmed Strike',target=friend,
            choices={CHOICE+'flowing':['protect'],CHOICE+'redirection':['no_reactions','push']})
        fresh=cold()._load_session(mid);e=fresh.engine
        if any(p['context']['reaction_source_id']==CHOICE+'flowing' for p in prompts):break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    else:pytest.fail('No committed melee hit reached the remote Flowing Silk trigger')
    assert fresh.mechanical.replay()['status']=='PASS'
    assert e.state.actors[friend].current_hp==hp and e.state.actors[aid].resources[QI]==qi-3
    saves=[x for x in e.events if x.sequence>start and x.event_type=='SAVE_ROLLED' and x.actor_id==bid]
    assert saves and saves[-1].payload['success'] is success
    assert any(p['context']['reaction_source_id']==CHOICE+'redirection' for p in prompts) is (not success)
    assert any(c.condition_id=='condition:typed.reaction_denied' for c in e.state.actors[bid].conditions.values()) is (not success)


def test_binding_repeat_success_frees_target_before_source_expiry(tmp_path):
    from tests.h1_support import sheet
    foe=sheet([],cl=18,key='CHA',name='Mara');foe['ability_scores_and_statistics']['hit_points']['maximum']=500
    combat,table,mid=play(tmp_path,[SILKEN,BINDING],foe_sheet=foe,seed='IRON-REPEAT-BIND')
    use(combat,table,mid,'Silken Whip')
    for _ in range(8):
        turn(table,mid,OWNER)
        use(combat,table,mid,'Silken Whip Attack',target=FOE)
        e=reload(tmp_path,mid)
        bound=next((c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.restrained' and c.data.get('binding')),None)
        if bound:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    else:pytest.fail('No committed hit produced an initial Binding Ribbon restraint')
    history=[]
    # Keep this exact binding instead of replacing it with a new hit each turn.
    # Native owner-start renewal is explicitly accepted by the table driver.
    for _ in range(8):
        turn(table,mid,FOE)
        start=reload(tmp_path,mid).state.event_sequence
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        e=reload(tmp_path,mid)
        saves=[x for x in e.events if x.sequence>start and x.event_type=='SAVE_ROLLED' and x.actor_id==FOE]
        history.append({'saves':[x.payload for x in saves],'round':e.state.round_number})
        if saves and saves[-1].payload['success']:
            assert not any(c.data.get('binding') for c in e.state.actors[FOE].conditions.values())
            assert e._effective_speed(e.state.actors[FOE])==30
            assert any(x.event_type=='CONDITION_REMOVED' and x.payload.get('instance_id')==bound.instance_id for x in e.events if x.sequence>saves[-1].sequence)
            return
    pytest.fail('No successful repeated Binding Ribbon save in the native stream: '+repr(history))


def test_prison_repeat_success_ejects_and_frees_through_native_turn_end(tmp_path):
    from tests.h1_support import sheet
    from combat.gate2_runtime_models import Position
    foe=sheet([],cl=18,key='CHA',name='Mara');foe['ability_scores_and_statistics']['hit_points']['maximum']=500
    combat,table,mid=play(tmp_path,[PRISON],foe_sheet=foe,seed='IRON-REPEAT-PRISON')
    for _ in range(6):
        turn(table,mid,OWNER);e=reload(tmp_path,mid);p=e.state.actors[FOE].position
        use(combat,table,mid,'Silken Prison',at=(p.x,p.y))
        e=reload(tmp_path,mid)
        if any(c.data.get('iron_cloth_prison') for c in e.state.actors[FOE].conditions.values()):break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    else:pytest.fail('No initial native failed save captured the prisoner')
    obj=next(o for o in e.state.objects.values() if o.component.get('iron_cloth_prison') and not o.destroyed)
    cells={Position(**p) for p in obj.component['cells']}
    for _ in range(6):
        turn(table,mid,FOE);e=reload(tmp_path,mid);start=e.state.event_sequence
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        e=reload(tmp_path,mid)
        saves=[x for x in e.events if x.sequence>start and x.event_type=='SAVE_ROLLED' and x.actor_id==FOE]
        if saves and saves[-1].payload['success']:
            assert not any(c.data.get('iron_cloth_prison') for c in e.state.actors[FOE].conditions.values())
            assert e.state.actors[FOE].position not in cells and e._effective_speed(e.state.actors[FOE])==30
            moves=[x for x in e.events if x.sequence>saves[-1].sequence and x.event_type=='MOVEMENT_COMMITTED' and x.actor_id==FOE]
            assert moves and moves[0].payload.get('cost_ft')==0
            return
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    pytest.fail('The fixed native stream did not exercise the prison repeat-save success branch')


def test_ribbons_entry_reentry_once_per_actual_turn_and_next_start(tmp_path):
    from tests.h1_support import sheet
    from combat.gate2_runtime_models import Position
    foe=sheet([],cl=18,key='CHA',name='Mara');foe['ability_scores_and_statistics']['hit_points']['maximum']=500
    combat,table,mid=play(tmp_path,[THOUSAND],owner_dc=1,foe_sheet=foe,foe_position={'x':10,'y':6},seed='IRON-ENTRY',
        battlefield={'stable_id':'battlefield:iron_entry','display_name':'Open ribbon field','width_squares':18,'height_squares':14,
            'square_size_ft':5,'starting_positions':{},'terrain_regions':[]})
    use(combat,table,mid,'Thousand Ribbons')
    turn(table,mid,FOE);e=reload(tmp_path,mid)
    assert not any(x.event_type=='DAMAGE_COMMITTED' and FOE in x.target_ids for x in e.events)
    dash=next(c for c in e.legal_candidates() if c.source_definition_id=='system:combat.dash')
    settle(table,mid,dash.candidate_id)
    def move(x):
        e=reload(tmp_path,mid)
        c=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination==Position(x=x,y=6))
        settle(table,mid,c.candidate_id)
    def hits():
        return [x for x in reload(tmp_path,mid).events if x.event_type=='DAMAGE_COMMITTED' and FOE in x.target_ids]
    move(9);assert len(hits())==1
    move(10);move(9);assert len(hits())==1
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,FOE)
    assert len(hits())==2


def test_prison_exact_range_cost_minute_and_single_replacement_use_real_cloth(tmp_path):
    from combat.gate2_runtime_models import Position
    combat,table,mid=play(tmp_path,[PRISON],cl=14,
        battlefield={'stable_id':'battlefield:iron_prison_range','display_name':'Open cloth court','width_squares':20,'height_squares':14,
            'square_size_ft':5,'starting_positions':{},'terrain_regions':[]})
    e=reload(tmp_path,mid)
    aimed=[c.destination for c in e.legal_candidates() if
        e.action_catalog.get(c.source_definition_id) and e.action_catalog[c.source_definition_id].display_name=='Silken Prison']
    assert Position(x=15,y=6) in aimed and Position(x=16,y=6) not in aimed
    qi=e.state.actors[OWNER].resources[QI]
    use(combat,table,mid,'Silken Prison',at=(15,6))
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources[QI]==qi-5 and not e.state.actors[OWNER].action_available
    old=next(z for z in e.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('iron_cloth_prison'))
    assert old.duration_rounds==10 and e.state.actors[OWNER].concentration is not None
    obj=next(o for o in e.state.objects.values() if o.component.get('iron_cloth_prison'))
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    use(combat,table,mid,'Silken Prison',at=(6,6))
    e=reload(tmp_path,mid)
    assert not e.state.zones[old.zone_id].active
    assert len([z for z in e.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('iron_cloth_prison')])==1
    assert len([o for o in e.state.objects.values() if o.component.get('iron_cloth_prison') and not o.destroyed])==1
    assert next(o for o in e.state.objects.values() if o.component.get('iron_cloth_prison') and not o.destroyed).object_id==obj.object_id
    assert e.state.actors[OWNER].resources[QI]==qi-10
