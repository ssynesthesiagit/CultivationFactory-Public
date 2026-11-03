"""Interactions between separately approved engine seams."""
from combat import action_geometry, shot_geometry
from combat.gate2_runtime_models import Position
from tests import lock8_support as S
from tests.test_lock_choices import install
from tests.test_lock8_passage import corridor, move, use


def test_remote_origin_and_altitude_use_effect_volume_without_moving_caster():
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    actor,target=e.state.actors[S.ME],e.state.actors[S.FOE]
    target.position=Position(x=1,y=1,z=4)
    before=actor.position
    record={'id':'test:origin','label':'Practice anchor','position':{'x':1,'y':1}}
    with action_geometry.activate(e,actor,'test:source',record):
        assert e._effect_distance(actor,target)==20
        assert shot_geometry.source_cells(e,actor,target)=={(1,1,0)}
    assert actor.position==before and action_geometry.record_for(e,actor) is None


def test_projectile_route_begins_at_the_bound_remote_origin(monkeypatch):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    actor,target=e.state.actors[S.ME],e.state.actors[S.FOE]
    target.position=Position(x=6,y=1)
    action=e.action_catalog[actor.action_ids[0]]
    record={'id':'test:origin','label':'Practice anchor','position':{'x':1,'y':1}}
    route={'source_id':'test:route','label':'Around the practice pillar',
        'path':[{'x':1,'y':1},{'x':5,'y':1},{'x':6,'y':1}]}
    install(monkeypatch,'sight_path',lambda *args:route)
    with action_geometry.activate(e,actor,action.source_definition_id,record), shot_geometry.scope(e,actor,action):
        assert shot_geometry.route(e,actor,target)==route
        assert shot_geometry.source_cells(e,actor,target)==((5,1),)
    assert getattr(e,'_shot_geometry',None) is None


def test_flight_capability_does_not_remove_ground_passage_permission(monkeypatch):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(4,6));corridor(e)
    actor=e.state.actors[S.ME];actor.fly_speed_ft=30
    install(monkeypatch,'pass_through',lambda *args:'free')
    c=move(e,5)
    assert c is not None and c.movement_cost_ft==10
    assert c.canonical_path[1]==Position(x=4,y=6)
    use(e,c)
    assert actor.position==Position(x=5,y=6) and actor.movement_remaining_ft==20


def test_deferral_precedes_final_lethal_rescue_decisions(monkeypatch):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    target=e.state.actors[S.ME];target.current_hp=5
    called=[]
    install(monkeypatch,'damage_deferral',lambda engine,actor,packet,intent:packet.amount)
    install(monkeypatch,'lethal_damage',lambda *args:called.append(True))
    e._commit_damage(target,10,'UNTYPED','test:incoming',S.FOE,None,reaction_depth=3)
    assert target.current_hp==5 and not called


def test_zone_entry_precedes_reactions_when_reaction_module_imported_first(monkeypatch,tmp_path):
    from combat import ext
    from combat.ext import area_steps, steal_momentum
    from tests.test_lock11_zone_review import test_zone_defeat_cancels_owned_steal_momentum_before_prompt_or_payment
    ext._load()
    # Reproduce a reaction module being imported before the plug-in loader.
    monkeypatch.setitem(ext._HOOKS,'movement_step',[steal_momentum.interrupt])
    monkeypatch.setattr(ext,'_HOOK_PRIORITIES',dict(ext._HOOK_PRIORITIES))
    ext.hook('movement_step',priority=-100)(area_steps.landed)
    test_zone_defeat_cancels_owned_steal_momentum_before_prompt_or_payment(monkeypatch,tmp_path)


def test_controller_change_rebuilds_cached_movement_menu(tmp_path):
    from tests import test_tabletop_hunt6 as H
    combat,table,mid=H.table_fight(tmp_path,[])
    session=combat._load_session(mid)
    actor=session.engine.state.current_actor_id
    manual=combat._legal_candidates(session)
    assert any(c.metadata.get('movement_mode')=='jump' for c in manual)
    combat.set_controller_mode(mid,actor_id=actor,controller_mode='LOCAL_AUTO')
    fresh=combat._load_session(mid)
    cached=combat._legal_candidates(fresh)
    assert cached==fresh.engine.legal_candidates()
    assert not any(c.metadata.get('movement_mode')=='jump' for c in cached)
    combat.set_controller_mode(mid,actor_id=actor,controller_mode='MANUAL')
    assert any(c.metadata.get('movement_mode')=='jump'
               for c in combat._legal_candidates(combat._load_session(mid)))
