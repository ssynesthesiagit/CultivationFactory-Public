"""Cover reductions and projectile routes bind to one accepted attack."""
import pytest
from combat import shot_geometry
from combat.gate2_runtime_models import ActionDefinition,ActionIntent,EconomyKind,DiceSpec,Position
from tests import lock8_support as S
from tests.test_lock_choices import install

BOUNCE='TAL_SNIPER_BOUNCING_SHOT'
WORLD='TAL_SNIPER_WORLD_NEEDLE_RICOCHET'
KIT={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.gong_jian','quantity':1}]}}


def yard(e):
    # Opposite sides of a solid divider need a second, reachable reflector.
    # A turn at the divider's own face cannot pass through its interior.
    blocked={(5,y) for y in range(4,9)}|{(5,0)}
    e.grid.blocked=blocked;e.grid.opaque=set();e.grid.cover=set();e.grid.qi_hazard=set()
    e._wall_base=(frozenset(blocked),frozenset(),frozenset(),{})


def use(e,c):
    e.execute_intent(ActionIntent(intent_id='sight-'+str(e.state.event_sequence),decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version,actor_id=c.actor_id,target_ids=c.target_ids,destination=c.destination))


def ranged(e):
    a=ActionDefinition(source_definition_id='test:ranged',display_name='Test shot',owner_id=S.ME,
        economy=EconomyKind.ACTION,resolution_kind='ATTACK',target_kind='HOSTILE_ENTITY',range_ft=60,
        attack_bonus=100,damage=DiceSpec(count=1,sides=6,modifier=0),damage_type='PIERCING')
    e.action_catalog[a.source_definition_id]=a;e.state.actors[S.ME].action_ids+=(a.source_definition_id,)
    return a


@pytest.mark.parametrize('steps,expected',[(0,5),(1,2),(2,0),(9,0)])
def test_reduction_after_all_cover_sources(monkeypatch,steps,expected):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    install(monkeypatch,'cover',lambda *args:5)
    install(monkeypatch,'cover_reduction',lambda *args:steps)
    assert e._cover_bonus_actor_to_actor(e.state.actors[S.ME],e.state.actors[S.FOE])==expected
    install(monkeypatch,'directional_cover',lambda *args:5)
    cover,ac=e._attack_defense(e.state.actors[S.ME],e.state.actors[S.FOE],
        {'range_ft':60,'declaration_cover':5})
    assert cover==expected and ac==e.state.actors[S.FOE].armor_class+expected


@pytest.mark.parametrize('ignore',[False,True])
def test_native_route_or_explicit_sight_exception_and_scope(monkeypatch,ignore):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(7,6));yard(e);a=ranged(e)
    before={k:v.position for k,v in e.state.actors.items()}
    assert not any(c.source_definition_id==a.source_definition_id for c in e.legal_candidates())
    path=[{'x':3,'y':6},*([] if ignore else [{'x':5,'y':3}]),{'x':7,'y':6}]
    install(monkeypatch,'sight_path',lambda *args:{'source_id':'test:path','label':'Test projectile path','path':path,'ignore_sight':ignore})
    install(monkeypatch,'d20_result',lambda *args:{'source_id':'test:roll','operation':'replace','natural_result':10})
    if ignore:
        # SOL132: bypassing sight does not let an attack pass through solid cover.
        assert not any(c.source_definition_id == a.source_definition_id for c in e.legal_candidates())
        assert before == {k: v.position for k, v in e.state.actors.items()}
        assert getattr(e, '_shot_geometry', None) is None
        return
    c=next(c for c in e.legal_candidates() if c.source_definition_id==a.source_definition_id)
    assert c.metadata['shot_geometry']['route']['path']==path
    use(e,c)
    assert any(ev.event_type=='ATTACK_ROLLED' for ev in e.events)
    assert before=={k:v.position for k,v in e.state.actors.items()}
    assert getattr(e,'_shot_geometry',None) is None
    assert not e._line_of_sight_actor_to_actor(e.state.actors[S.ME],e.state.actors[S.FOE])


@pytest.mark.parametrize('world',[False,True])
def test_real_bounce_around_wall_cost_total_range_and_world_cover(monkeypatch,world):
    e=S.fight(S.bundle(BOUNCE,*([WORLD] if world else []),kit=KIT),foe_at=(7,6));yard(e)
    actor=e.state.actors[S.ME];e._gain_resource(actor,'resource:core.martial_focus',1,'test:focus')
    install(monkeypatch,'cover',lambda *args:5)
    install(monkeypatch,'d20_result',lambda *args:{'source_id':'test:roll','operation':'replace','natural_result':10})
    c=next(c for c in e.legal_candidates() if 'Bouncing Shot' in c.display_name)
    receipt=c.metadata['shot_geometry'];assert receipt['cover_after']==(0 if world else 5)
    assert shot_geometry.length(e,receipt['route'])>e.grid.distance_ft(actor.position,e.state.actors[S.FOE].position)
    original=e.action_catalog[c.source_definition_id]
    e.action_catalog[c.source_definition_id]=original.model_copy(update={'range_ft':20})
    assert not any(c.source_definition_id==original.source_definition_id for c in e.legal_candidates())
    e.action_catalog[original.source_definition_id]=original
    c=next(c for c in e.legal_candidates() if c.source_definition_id==original.source_definition_id)
    use(e,c)
    assert actor.resources['resource:core.martial_focus']==0
    assert any(ev.event_type=='ATTACK_ROLLED' for ev in e.events)
    assert getattr(e,'_shot_geometry',None) is None


def test_bouncing_shot_respects_finite_wall_top_height():
    from copy import deepcopy

    def fight_at_altitude(z):
        e=S.fight(S.bundle(BOUNCE,kit=KIT),foe_at=(7,6));yard(e)
        actor=e.state.actors[S.ME];target=e.state.actors[S.FOE]
        actor.position=actor.position.model_copy(update={'z':z})
        target.position=target.position.model_copy(update={'z':z})
        e._gain_resource(actor,'resource:core.martial_focus',1,'test:focus')
        spans={cell:[(0,3)] for cell in e.grid.blocked}
        e._wall_base_spans={'BLOCKED':deepcopy(spans)}
        e.grid.terrain_spans={'BLOCKED':deepcopy(spans)}
        e.grid.terrain_heights={'BLOCKED':{cell:3 for cell in spans}}
        e.grid.finite_heights=True
        return e

    ground=fight_at_altitude(0)
    assert any('Bouncing Shot' in c.display_name for c in ground.legal_candidates())
    above_wall=fight_at_altitude(1)  # 5 feet, above the 3-foot wall
    assert not any('Bouncing Shot' in c.display_name for c in above_wall.legal_candidates())


def test_no_valid_bounce_or_unowned_world_does_not_grant_geometry():
    e=S.fight(S.bundle(BOUNCE,kit=KIT),foe_at=(7,6));yard(e)
    e._gain_resource(e.state.actors[S.ME],'resource:core.martial_focus',1,'test:focus')
    # A solid column across the arena has no route around either end.
    e._wall_base=(frozenset((5,y) for y in range(e.grid.height)),frozenset(),frozenset(),{})
    e.grid.blocked=set(e._wall_base[0])
    assert not any('Bouncing Shot' in c.display_name for c in e.legal_candidates())


def test_invalid_hook_data_rejected_and_scope_restored(monkeypatch):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'));a=ranged(e)
    install(monkeypatch,'sight_path',lambda *args:{'source_id':'test:bad','label':'Bad route','path':[{'x':True,'y':6},{'x':6,'y':6}]})
    with pytest.raises(ValueError):e.legal_candidates()
    assert getattr(e,'_shot_geometry',None) is None


def test_bound_route_becoming_blocked_is_not_replaced_by_another_route():
    e=S.fight(S.bundle(BOUNCE,kit=KIT),foe_at=(7,6));yard(e)
    actor=e.state.actors[S.ME];target=e.state.actors[S.FOE]
    e._gain_resource(actor,'resource:core.martial_focus',1,'test:focus')
    c=next(c for c in e.legal_candidates() if 'Bouncing Shot' in c.display_name)
    action=e.action_catalog[c.source_definition_id];bound=c.metadata['shot_geometry']
    p=bound['route']['path'][1]
    e.grid.opaque.add((p['x'],p['y']))
    # Opaque endpoints of a segment also block the continuation as an intermediate
    # projectile point; the bound route must never silently select the other side.
    with shot_geometry.scope(e,actor,action,bound):
        assert shot_geometry.route(e,actor,target)==bound['route']
        assert not shot_geometry.valid(e,actor,target,shot_geometry.route(e,actor,target))


@pytest.mark.parametrize('world',[False,True])
def test_real_bounce_table_payment_geometry_reload_and_replay(tmp_path,monkeypatch,world):
    import json,zipfile
    from combat import ext
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT,sheet
    from tests.test_hidden_targeting import turn
    from tests.test_lock2_persistence import act
    left,right='actor:factory.left','actor:factory.right'
    for pid,features in [('left',[BOUNCE,*([WORLD] if world else [])]),('right',['SAND_BASE_SCOURING_HAND'])]:
        document=sheet(features,cl=20,kit=KIT if pid=='left' else None)
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(document))
    def focus(engine,kind,kwargs):
        if kind=='HOLD_POSITION_COMMITTED' and kwargs.get('actor_id')==left:
            engine._gain_resource(engine.state.actors[left],'resource:core.martial_focus',1,'test:ready')
    ext.effects();monkeypatch.setitem(ext._HOOKS,'event',[*ext._HOOKS.get('event',[]),focus])
    install(monkeypatch,'cover',lambda engine,actor,target:5 if target.entity_id==right else None)
    install(monkeypatch,'d20_result',lambda *args:{'source_id':'test:roll','operation':'replace','natural_result':10})
    service=CombatService(ROOT,tmp_path)
    service.tabletop_maps.save({'display_name':'Ricochet yard','width_squares':20,'height_squares':14,
        'walls':[{'shape':'rect','points':[[5,4],[6,9]]},
                 {'shape':'rect','points':[[5,0],[6,1]]}],
        'starts':{'team1':[[3,6]],'team2':[[7,6]]}})
    mid=service.create_factory_match(project_ids=['left'],opponent_actor_ids=[right],control_modes={left:'MANUAL',right:'MANUAL'},
        arena_id='battlefield:map.ricochet-yard',match_seed='L8-BOUNCE')['match_id']
    table=TabletopService(service,tmp_path);turn(table,mid,left)
    assert act(table,mid,'system:combat.hold_position')['status']=='COMMITTED'
    e=service._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if 'Bouncing Shot' in c.display_name)
    receipt=c.metadata['shot_geometry']
    assert receipt['cover_before']==5 and receipt['cover_after']==(0 if world else 5)
    result=table.act(mid,c.candidate_id,c.decision_id,c.state_version,table.state(mid)['last_sequence'])
    assert result['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
    assert loaded.engine.state.actors[left].resources['resource:core.martial_focus']==0
    assert any(ev.payload.get('shot_geometry')==receipt for ev in loaded.engine.events)
    assert getattr(loaded.engine,'_shot_geometry',None) is None
