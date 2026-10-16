"""Creature passage changes paths, not endpoint occupancy or knowledge."""
import pytest
from combat import ext
from combat.creature_passage import geometry
from combat.gate2_runtime_models import Position, ActionIntent
from tests import lock8_support as S
from tests.test_lock_choices import install

CLOUD = 'tianxia.subpath.qi.cloud_walker.feature.cloud_immortal'
LIQUID = 'tianxia.subpath.qi.abyssal_depths_cultivator.feature.deep_s_embrace'


def corridor(e):
    e.grid.blocked = {(x,y) for x in range(e.grid.width) for y in range(e.grid.height) if y != 6}
    e.grid.base_movement_cost.clear()
    e.grid.qi_hazard.clear()
    e._wall_base = (frozenset(e.grid.blocked), frozenset(), frozenset(), {})


def move(e, x):
    return next((c for c in e.legal_candidates() if c.kind.value == 'MOVE' and c.destination == Position(x=x,y=6)), None)


def use(e, c):
    e.execute_intent(ActionIntent(intent_id='passage-'+str(e.state.event_sequence), decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version,actor_id=c.actor_id,
        target_ids=c.target_ids,destination=c.destination))


@pytest.mark.parametrize('mode,cost', [('free',10),('difficult',15)])
def test_pathfinding_permissions_cost_and_forbidden_endpoint(monkeypatch, mode, cost):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(4,6));corridor(e)
    assert move(e,5) is None
    install(monkeypatch,'pass_through',lambda *args:mode)
    c=move(e,5)
    assert c and c.movement_cost_ft == cost and c.canonical_path[1] == Position(x=4,y=6)
    assert move(e,4) is None
    blocked,ends,difficult,record=geometry(e,e.state.actors[S.ME])
    assert e.grid.shortest_path(Position(x=3,y=6),Position(x=4,y=6),occupied_cells=blocked,end_blocked_cells=ends) is None
    assert e.grid.shortest_path(Position(x=3,y=6),Position(x=5,y=6),occupied_cells=blocked,end_blocked_cells=ends,difficult_cells=difficult)[1] == cost
    use(e,c)
    assert e.state.actors[S.ME].position == Position(x=5,y=6)
    assert e.state.actors[S.ME].movement_remaining_ft == 30-cost


@pytest.mark.parametrize('feature,cost',[(CLOUD,8),(LIQUID,3)])
def test_real_owner_activation_passes_and_expires(feature,cost):
    e=S.fight(S.bundle(feature,cl=18 if feature==CLOUD else 15),foe_at=(4,6));corridor(e)
    actor=e.state.actors[S.ME];hp=actor.current_hp;qi=actor.resources['resource:core.qi']
    assert move(e,5) is None
    c=next(c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id) and
           e.action_catalog[c.source_definition_id].parameters.get('typed',{}).get('source')==feature)
    use(e,c)
    assert actor.current_hp == hp and actor.resources['resource:core.qi']==qi-cost
    c=move(e,6);assert c and c.movement_cost_ft==(15 if feature==CLOUD else 20)
    use(e,c)
    assert actor.position==Position(x=6,y=6)
    assert not any(ev.event_type=='REACTION_RESOLVED' and ev.actor_id==S.FOE for ev in e.events)
    marker='condition:typed.cloud_walker_form' if feature==CLOUD else 'condition:typed.creature_passage'
    condition=next(c for c in actor.conditions.values() if c.condition_id==marker)
    assert condition.expires_on!='UNTIL_REMOVED'
    if feature==LIQUID:
        assert condition.data['crossed']==[S.FOE]
        e.end_turn();S.turn(e,S.ME)
        assert not any(c.condition_id=='condition:typed.creature_passage' for c in actor.conditions.values())


def test_stopped_transit_returns_to_free_space_and_keeps_spent_cost(monkeypatch):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(4,6));corridor(e)
    install(monkeypatch,'pass_through',lambda *args:'free')
    def stop(engine,mover,occupant,intent):
        engine._apply_condition(mover,'condition:typed.pinned','test:pin',occupant.entity_id,expires_on='UNTIL_REMOVED')
    install(monkeypatch,'pass_through_entered',stop)
    use(e,move(e,5))
    event=next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED')
    assert e.state.actors[S.ME].position==Position(x=3,y=6)
    assert event.payload['interrupted'] and event.payload['cost_ft']==5


def test_unknown_occupant_not_disclosed_and_wall_still_blocks(monkeypatch):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(4,6));corridor(e)
    install(monkeypatch,'pass_through',lambda *args:'free')
    e._apply_condition(e.state.actors[S.FOE],'condition:typed.invisible','test:hide',S.FOE,expires_on='UNTIL_REMOVED')
    e.state.observations.clear()
    assert S.FOE not in geometry(e,e.state.actors[S.ME],observed=True)[3]
    e.grid.blocked.add((4,6))
    e._wall_base = (frozenset(e.grid.blocked), frozenset(), frozenset(), {})
    assert move(e,5) is None


def test_invalid_permission_is_rejected(monkeypatch):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    install(monkeypatch,'pass_through',lambda *args:True)
    with pytest.raises(ValueError):geometry(e,e.state.actors[S.ME])


@pytest.mark.parametrize('feature', [CLOUD, LIQUID])
def test_passage_protection_against_legacy_opportunity_attacks(feature):
    from tests.h1_support import duel, ME, FOE
    e=duel([feature],cl=20)
    corridor(e)
    c=next(c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id) and
           e.action_catalog[c.source_definition_id].parameters.get('typed',{}).get('source')==feature)
    use(e,c)
    before=len(e.events)
    use(e,move(e,6))
    assert e.state.actors[ME].position==Position(x=6,y=6)
    assert not any(ev.event_type=='REACTION_RESOLVED' and ev.actor_id==FOE for ev in e.events[before:])


@pytest.mark.parametrize('feature', [CLOUD, LIQUID])
@pytest.mark.parametrize('finite_wall', [False, True])
def test_portable_activation_crossing_reload_and_replay(tmp_path, feature, finite_wall):
    import json, zipfile
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, sheet
    from tests.test_hidden_targeting import turn
    for pid, owned in [('left',feature),('right','SAND_BASE_SCOURING_HAND')]:
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(sheet([owned],cl=20)))
    combat=CombatService(ROOT,tmp_path)
    combat.tabletop_maps.save({'display_name':'Passage hall','width_squares':12,'height_squares':14,
        'walls':[{'shape':'rect','points':[[0,0],[12,6]]},
                 {'shape':'rect','points':[[0,7],[12,14]]},
                 *([{'shape':'rect','points':[[0,0],[1,1]],'height_ft':5}] if finite_wall else [])],
        'starts':{'team1':[[3,6]],'team2':[[4,6]]}})
    left,right='actor:factory.left','actor:factory.right'
    mid=combat.create_factory_match(project_ids=['left'],opponent_actor_ids=[right],
        control_modes={left:'MANUAL',right:'MANUAL'},arena_id='battlefield:map.passage-hall',match_seed='L8-PASSAGE')['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,left)
    def send(c):
        state=table.state(mid)
        return table.act(mid,c.candidate_id,c.decision_id,c.state_version,state['last_sequence'])
    e=combat._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id) and
           e.action_catalog[c.source_definition_id].parameters.get('typed',{}).get('source')==feature)
    assert send(c)['status']=='COMMITTED'
    combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path);e=combat._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination==Position(x=6,y=6))
    assert c.movement_cost_ft==(15 if feature==CLOUD else 20) and Position(x=4,y=6) in c.canonical_path
    assert send(c)['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[left].position==Position(x=6,y=6)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
    if feature==LIQUID:
        marker=next(c for c in loaded.engine.state.actors[left].conditions.values() if c.condition_id=='condition:typed.creature_passage')
        assert marker.data['crossed']==[right]
