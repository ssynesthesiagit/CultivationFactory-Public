"""Spatial save seams are explicit, scoped, read-only and event-attributable."""
import json
import zipfile
import pytest
from combat import typed_executor as te
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests import lock8_support as S
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act

SOURCE = 'test:spatial_save'
OWNER, TARGET = 'actor:factory.aaaaaaaa', 'actor:factory.bbbbbbbb'


def test_actual_native_attack_uses_shared_effect_cover_table_reload(monkeypatch,tmp_path):
    from tests.test_lock2_persistence import table_match
    def actions(info):
        return [ActionDefinition(source_definition_id='test:cover-shot:'+info['actor_id'],
            display_name='Practice shot',owner_id=info['actor_id'],economy=EconomyKind.ACTION,
            resolution_kind='ATTACK',target_kind='HOSTILE_ENTITY',range_ft=60,attack_bonus=100,
            parameters={'attack_kind':'weapon'})]
    install(monkeypatch,'compile_actions',actions)
    install(monkeypatch,'effect_cover',lambda e,a,t,ray: 2 if ray['purpose']=='attack' and ray['ranged'] else None)
    combat,table,mid=table_match(tmp_path)
    e=combat._load_session(mid).engine;a=e.state.actors[e.state.current_actor_id]
    shot=next(c for c in e.legal_candidates() if c.source_definition_id=='test:cover-shot:'+a.entity_id)
    t=e.state.actors[shot.target_ids[0]]
    before=e.state.model_dump(mode='json')
    explicit=e.cover_from(e._actor_volume(a),a.entity_id,t,purpose='attack')
    assert explicit['bonus']==2 and e.state.model_dump(mode='json')==before
    result=table.act(mid,shot.candidate_id,shot.decision_id,shot.state_version,0,[])
    assert result['status']=='COMMITTED',result
    fresh=CombatService(ROOT,tmp_path)._load_session(mid)
    roll=next(ev for ev in fresh.engine.events if ev.event_type=='ATTACK_ROLLED' and ev.source_definition_id==shot.source_definition_id)
    assert roll.payload['cover_bonus']==explicit['bonus']
    assert roll.payload['target_ac']==t.armor_class+explicit['bonus']
    assert fresh.verify()['status']==fresh.mechanical.replay()['status']=='PASS'


def test_actual_large_target_exposes_nonanchor_volume():
    from combat.footprints import ActorFootprintDefinition
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(7,6))
    target=e.state.actors[S.FOE]
    e.actor_footprints[S.FOE]=ActorFootprintDefinition.rectangle(2,2,footprint_id='test:large-target',source_definition_id='test:large-target')
    e.grid.blocked.clear();e.grid.opaque.clear();e.grid.blocked.add((7,6))
    before=e.state.model_dump(mode='json'),len(e.events),e.roller.counter
    assert e.cover_from([(5,6)],S.ME,target,target_cells=[(7,6)])['blocked']
    assert not e.cover_from([(5,6)],S.ME,target)['blocked']
    assert (e.state.model_dump(mode='json'),len(e.events),e.roller.counter)==before


@pytest.mark.parametrize('shape,expected', [('line',(3,6)), ('cone',(3,6)), ('sphere',(8,6)), ('cube',(8,6)), ('cylinder',(8,6))])
def test_typed_origin_is_vertex_or_area_center(monkeypatch, shape, expected):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'));a=e.state.actors[S.ME];t=e.state.actors[S.FOE]
    action=e.action_catalog[S.action_id(e,S.ME,'Scouring Hand')]
    ctx=te.Context(e,a,action,None,{'area':{'shape':shape,'size_ft':20},'numbers':{'save_dc':10}},[t],t,
                   {'_checkpoint_aim':Position(x=8,y=6)})
    seen=[]
    install(monkeypatch,'save_bonus',lambda engine,*args: seen.append(engine.d20_context()))
    te.block_save(ctx,{'type':'save','ability':'dex','on_fail':[],'on_success':[]})
    assert seen and (seen[0]['effect_origin']['x'],seen[0]['effect_origin']['y'])==expected
    assert seen[0]['effect_origin_kind']=='point' and seen[0]['area']['shape']==shape
    assert e.d20_context() is None


def test_secondary_origin_and_unknown_native_nested_scope(monkeypatch):
    from combat.save_context import spatial_context
    from combat.ext import ControllerPause
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'));a=e.state.actors[S.ME];t=e.state.actors[S.FOE]
    ctx=S.ctx_of(e,S.ME,S.FOE,S.action_id(e,S.ME,'Scouring Hand'))
    ctx.save_geometry={'origin_ids':[S.FOE],'range_ft':10}
    data=spatial_context(ctx)
    assert data['effect_origin']==t.position.model_dump(mode='json') and data['effect_origin_kind']=='actor'
    assert data['area'] is None
    ctx.save_geometry={'origin_ids':['missing'],'range_ft':10}
    assert spatial_context(ctx)['effect_origin_kind']=='unknown'
    def nested(engine,target,ability,*args):
        if ability=='DEX':
            outer=engine.d20_context()
            outer['effect_origin']['x']=99
            assert engine.d20_context()['effect_origin']['x']!=99
            engine._roll_save(target,'CON',10,'system:combat.concentration')
            assert engine.d20_context()['effect_origin_kind']=='point'
            raise ControllerPause('test save')
        assert engine.d20_context()['effect_origin_kind']=='unknown'
        assert engine.d20_context()['effect_origin'] is None
    install(monkeypatch,'save_bonus',nested)
    with pytest.raises(ControllerPause):
        with e._transaction('test:save','test:save',S.FOE):
            e._roll_save(t,'DEX',10,'test:save',roll_context={
                'effect_origin_kind':'point','effect_origin':{'x':1,'y':1}})
    assert e.d20_context() is None


def test_cover_query_points_bodies_large_footprints_and_physical_blockage(monkeypatch):
    from combat.footprints import ActorFootprintDefinition
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(7,6),ally=S.bundle('SAND_BASE_SCOURING_HAND',actor_id=S.ALLY),ally_at=(5,6))
    a,t=e.state.actors[S.ME],e.state.actors[S.FOE]
    before=e.state.model_dump(mode='json'),list(e.events),e.roller.counter
    assert e.cover_from([(3,6)],S.ME,t)=={'bonus':2,'blocked':False}
    assert e.cover_from([(6,6)],S.ME,t)=={'bonus':0,'blocked':False}
    e.grid.cover.add((6,6));e._cover_three_quarters={(6,6)}
    assert e.cover_from([(5,6)],S.ME,t)['bonus']==5
    e.grid.opaque.add((6,6))
    assert e.cover_from([(5,6)],S.ME,t)=={'bonus':5,'blocked':False}
    e.grid.blocked.add((6,6))
    assert e.cover_from([(5,6)],S.ME,t)['blocked']
    e.grid.blocked.clear();e.grid.opaque.clear()
    assert not e.cover_from([(5,6)],S.ME,t,target_cells=[(7,6),(7,7)])['blocked']
    footprint=ActorFootprintDefinition.rectangle(2,2,footprint_id='test:large',source_definition_id='test:large')
    old=e._footprint
    monkeypatch.setattr(e,'_footprint',lambda who: footprint if getattr(who,'entity_id',who)==S.ME else old(who))
    assert e.cover_from([(5,6)],S.ME,t)['bonus']==5  # explicit point unaffected by source size
    assert (e.state.model_dump(mode='json'),e.events,e.roller.counter)==before


@pytest.mark.parametrize('cover', [2,5])
def test_bonus_proposal_and_opposite_side_center_survive_table_reload(monkeypatch,tmp_path,cover):
    for pid in ('aaaaaaaa','bbbbbbbb'):
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(sheet([],cl=5)))
    def compile_action(info):
        if info['actor_id']!=OWNER:return []
        return [ActionDefinition(source_definition_id=SOURCE,display_name='Practice saving throw',owner_id=OWNER,
            economy=EconomyKind.ACTION,resolution_kind='TYPED',target_kind='CELL',range_ft=60,radius_ft=10,
            parameters={'any_cell':True,'typed':{'numbers':{**info['numbers'],'save_dc':16},
                'area':{'shape':'sphere','size_ft':10},'effects':[{'type':'save','ability':'DEX',
                    'on_fail':[{'type':'damage','flat':1,'damage_types':['force']}],'on_success':[]}]}})]
    install(monkeypatch,'compile_actions',compile_action)
    def provider(e,target,ability,*args):
        context=e.d20_context()
        if ability!='DEX' or context['effect_origin_kind']=='unknown':return None
        result=e.cover_from(context['effect_origin_cells'],context['source_actor_id'],target)
        return {'bonus':result['bonus'],'contributions':{'cover':result['bonus']}}
    install(monkeypatch,'save_bonus_details',provider)
    if cover==5:
        def dune(e,event,kwargs):
            if event=='HOLD_POSITION_COMMITTED':
                from combat import zones
                a=e.state.actors[OWNER];action=e.action_catalog[SOURCE]
                intent=e._active_intent.model_copy(update={'destination':Position(x=5,y=4)})
                ctx=te.Context(e,a,action,intent,{},[])
                zones.create(ctx,{'name':'Practice dune','shape':'sphere','size_ft':0,
                    'wall':{'length_ft':5,'thick_ft':5,'cover':'three_quarters'},'duration':{}})
        install(monkeypatch,'event',dune)
    service=CombatService(ROOT,tmp_path)
    service.tabletop_maps.save({'display_name':'Save origin yard','width_squares':12,'height_squares':8,
        'walls':[],'terrain':[{'type':'SIMPLE_COVER','cells':[[5,4]]}] if cover==2 else [],
        'starts':{'team1':[[3,4]],'team2':[[4,4]]}})
    mid=service.create_factory_match(project_ids=['aaaaaaaa'],opponent_actor_ids=[TARGET],
        control_modes={OWNER:'MANUAL',TARGET:'MANUAL'},arena_id='battlefield:map.save-origin-yard',match_seed='L15-SAVE')['match_id']
    table=TabletopService(service,tmp_path)
    while table.state(mid)['menu']['actor_id']!=OWNER:assert act(table,mid,'end')['status']=='COMMITTED'
    if cover==5:assert act(table,mid,'system:combat.hold_position')['status']=='COMMITTED'
    state=table.state(mid);e=service._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.source_definition_id==SOURCE and c.destination==Position(x=6,y=4))
    assert table.act(mid,c.candidate_id,c.decision_id,c.state_version,state['last_sequence'])['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    event=next(ev for ev in loaded.engine.events if ev.event_type=='SAVE_ROLLED' and ev.actor_id==TARGET)
    assert event.payload['save_bonus_contributions']=={'cover':cover}
    assert event.payload['modifier']==loaded.engine.state.actors[TARGET].saving_throws['DEX']+cover
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


@pytest.mark.parametrize('proposal',[{'bonus':True,'contributions':{'cover':1}}, {'bonus':2,'contributions':{'cover':5}}])
def test_invalid_details_roll_back_before_drawing(monkeypatch,proposal):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'));t=e.state.actors[S.FOE]
    before=e.state.model_dump(mode='json'),list(e.events),e.roller.counter
    install(monkeypatch,'save_bonus_details',lambda *args:proposal)
    with pytest.raises(ValueError,match='save_bonus_details'):
        with e._transaction('test:save','test:save',S.FOE):e._roll_save(t,'DEX',10,'test:save')
    assert (e.state.model_dump(mode='json'),e.events,e.roller.counter)==before
