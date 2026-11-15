"""Actual Table zone crossings plus native stepped path regressions."""
import pytest
from combat import zones, typed_executor
from combat.gate2_runtime_models import Position, ZoneState
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from tests import lock8_support as S
from tests.test_lock8_movement_steps import portable, use
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.h1_support import ROOT


def candidate(e, x, y=6):
    # These tests deliberately cross a particular area. A destination-only
    # default now avoids that area when an equally cheap detour exists.
    from combat.movement_routes import explicit_candidate
    actor = e.state.actors[e.state.current_actor_id]
    path = [actor.position]
    while (path[-1].x, path[-1].y) != (x, y):
        previous = path[-1]
        dx, dy = x - previous.x, y - previous.y
        path.append(Position(x=previous.x + (1 if dx > 0 else -1 if dx < 0 else 0),
                             y=previous.y + (1 if dy > 0 else -1 if dy < 0 else 0)))
    return explicit_candidate(e, actor.entity_id, tuple(path))


def zone(e, *, cells=((5,6),), effects=None, moment="enter", shape="radius"):
    actor=e.state.actors[S.ME]
    source=next(a for a in actor.action_ids if e.action_catalog[a].resolution_kind=="TYPED")
    z=ZoneState(zone_id="zone:test.path",source_definition_id=source,owner_id=S.ME,
        center=Position(x=5,y=6),radius_cells=0,affected_cells=tuple(Position(x=x,y=y) for x,y in cells),
        concentration_link=False,created_round=e.state.round_number,
        trigger_profile={"kind":"TYPED","shape":shape,"numbers":{"save_dc":99},
            "triggers":[{"id":"test:entry","name":"Test area","on":[moment],"who":"hostile",
                         "effects":effects or [{"type":"damage","flat":3,"damage_types":["force"],"applies_to":"target"}]}]})
    e.state.zones[z.zone_id]=z
    return z


def fight():
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(4,6))
    e.state.actors[S.ME].position=Position(x=1,y=1)
    e.state.actors[S.FOE].position=Position(x=3,y=6)
    e.grid.blocked.clear();e.grid.opaque.clear();e._wall_base=(frozenset(),frozenset(),frozenset(),{})
    S.turn(e,S.FOE)
    return e


@pytest.mark.parametrize("temporary",[0,20])
def test_damage_stops_inside_middle_of_path_even_when_absorbed(temporary):
    e=fight();zone(e)
    actor=e.state.actors[S.FOE];actor.temporary_hp=temporary
    use(e,candidate(e,8))
    assert actor.position==Position(x=5,y=6)
    ev=next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED')
    assert ev.payload['cost_ft']==10 and ev.payload['interrupted']
    assert sum(ev.event_type=='DAMAGE_COMMITTED' for ev in e.events)==1


def test_immobilizing_entry_stops_without_duplicate_endpoint_trigger():
    e=fight();z=zone(e,effects=[{"type":"condition","condition":"restrained","applies_to":"target"}])
    use(e,candidate(e,8))
    assert e.state.actors[S.FOE].position==Position(x=5,y=6)
    assert sum(ev.event_type=='PASSIVE_TRIGGERED' and ev.payload.get('moment')=='enter' for ev in e.events)==1


def test_leave_trigger_runs_at_the_first_square_outside():
    e=fight();zone(e,moment='leave')
    use(e,candidate(e,8))
    assert e.state.actors[S.FOE].position==Position(x=6,y=6)
    assert sum(ev.event_type=='PASSIVE_TRIGGERED' and ev.payload.get('moment')=='leave' for ev in e.events)==1


def test_line_crossing_remembers_side_across_landing_on_line():
    e=fight();zone(e,cells=((5,4),(5,5),(5,6),(5,7),(5,8)),moment='cross',shape='line')
    use(e,candidate(e,8))
    assert e.state.actors[S.FOE].position==Position(x=6,y=6)
    assert sum(ev.event_type=='PASSIVE_TRIGGERED' and ev.payload.get('moment')=='cross' for ev in e.events)==1


def test_forced_push_cannot_skip_intermediate_zone():
    e=fight();zone(e)
    e.state.actors[S.ME].position=Position(x=2,y=6)
    action=e.action_catalog[e.state.actors[S.ME].action_ids[0]]
    actor,target=e.state.actors[S.ME],e.state.actors[S.FOE]
    ctx=typed_executor.Context(e,actor,action,None,{"numbers":{}},[target],target,{})
    typed_executor._push(ctx,target,25,pull=False)
    # A push resolves entry damage but keeps its printed distance if the target
    # survives. Dragging/willing interruption is covered separately above.
    assert target.position==Position(x=8,y=6)
    assert sum(ev.event_type=='DAMAGE_COMMITTED' for ev in e.events)==1
    ev=next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED')
    assert ev.payload['forced'] and ev.payload['path'][-1]=={'x':8,'y':6}


@pytest.mark.parametrize('remains_inside', [False, True])
def test_displacing_entry_revalidates_other_landed_area_triggers(remains_inside):
    e = fight()
    e.state.actors[S.ME].position = Position(x=2, y=6)
    first = zone(e, effects=[{'type': 'forced_movement', 'distance_ft': 10,
                             'direction': 'away', 'applies_to': 'target'}])
    del e.state.zones[first.zone_id]
    first = first.model_copy(update={'zone_id': 'zone:test.first'})
    e.state.zones[first.zone_id] = first
    zone(e, cells=((5,6), (6,6), (7,6)) if remains_inside else ((5,6),))
    actor = e.state.actors[S.FOE]
    before = actor.current_hp
    use(e, candidate(e, 8))
    assert actor.position == Position(x=7, y=6)
    assert before - actor.current_hp == (3 if remains_inside else 0)
    assert sum(ev.event_type == 'DAMAGE_COMMITTED' for ev in e.events) == int(remains_inside)


@pytest.mark.parametrize('derived', [False, True])
@pytest.mark.parametrize('removal', ['none', 'deactivate', 'remove'])
def test_arrival_revalidates_live_stored_and_projected_zones(monkeypatch, derived, removal):
    from tests.test_lock_choices import install

    e = fight()
    first = zone(e)
    del e.state.zones[first.zone_id]
    first = first.model_copy(update={'zone_id': 'zone:test.first'})
    e.state.zones[first.zone_id] = first
    later = zone(e)
    visible = [True]
    if derived:
        del e.state.zones[later.zone_id]
        # A hook can reconstruct the same logical area on every query.
        install(monkeypatch, 'zones', lambda engine:
                [later.model_copy(deep=True)] if visible[0] else [])

    def earlier_effect(engine, event_type, kwargs):
        if event_type != 'PASSIVE_TRIGGERED' or kwargs.get('payload', {}).get('zone_id') != first.zone_id:
            return
        if removal == 'deactivate':
            later.active = False
        elif removal == 'remove':
            visible[0] = False
            engine.state.zones.pop(later.zone_id, None)

    install(monkeypatch, 'event', earlier_effect)
    actor = e.state.actors[S.FOE]
    before = actor.current_hp
    start, actor.position = actor.position, Position(x=5, y=6)
    zones.on_moved(e, actor, start, actor.position)
    assert before - actor.current_hp == (6 if removal == 'none' else 3)
    fired = [event.payload['zone_id'] for event in e.events
             if event.event_type == 'PASSIVE_TRIGGERED' and event.payload.get('moment') == 'enter']
    assert fired == ([first.zone_id, later.zone_id] if removal == 'none' else [first.zone_id])


def test_granted_path_stops_and_charges_only_its_own_budget():
    e=fight();zone(e)
    a=e.state.actors[S.FOE]
    c=candidate(e,8)
    before=a.movement_remaining_ft
    intent=ActionIntent(intent_id='test:grant',decision_id=c.decision_id,candidate_id=c.candidate_id,
        state_version=c.state_version,actor_id=a.entity_id,destination=c.destination)
    spent=e.grant_movement(a,c.canonical_path,'test:grant',feet=25,intent=intent,provokes=False)
    assert a.position==Position(x=5,y=6) and spent==10
    assert a.movement_remaining_ft==before


def test_new_incapacitation_does_not_shorten_forced_distance():
    e=fight();zone(e,effects=[{'type':'condition','condition':'incapacitated','applies_to':'target'}])
    actor,target=e.state.actors[S.ME],e.state.actors[S.FOE]
    actor.position=Position(x=2,y=6)
    e._apply_condition(target,'condition:typed.grappled','test:grip',actor.entity_id,expires_on='UNTIL_REMOVED')
    action=e.action_catalog[actor.action_ids[0]]
    ctx=typed_executor.Context(e,actor,action,None,{'numbers':{}},[target],target,{})
    typed_executor._push(ctx,target,25,pull=False)
    assert target.position==Position(x=8,y=6)
    assert any(c.condition_id == 'condition:typed.incapacitated' for c in target.conditions.values())


def test_dragged_creature_zone_damage_stops_the_grapplers_path():
    e=fight();z=zone(e,cells=((4,5),))
    z.trigger_profile['triggers'][0]['who']='any'
    mover,held=e.state.actors[S.FOE],e.state.actors[S.ME]
    held.position=Position(x=2,y=6)
    e._apply_condition(held,'condition:typed.grappled','test:grip',mover.entity_id,
        expires_on='UNTIL_REMOVED',data={'reach_ft':5})
    # Native drag tie-break steps diagonally; only its held target enters here.
    mover.position=Position(x=4,y=6)
    held.position=Position(x=3,y=6)
    use(e,candidate(e,7))
    assert held.position==Position(x=4,y=5)
    assert mover.position==Position(x=5,y=6)


def send(table,mid,c):
    if c.metadata.get('explicit_movement_path'):
        return table.commit_move_path(mid,c.candidate_id,c.decision_id,c.state_version,c.actor_id,
            [p.model_dump(mode='json') for p in c.canonical_path],table.state(mid)['last_sequence'])
    return table.act(mid,c.candidate_id,c.decision_id,c.state_version,table.state(mid)['last_sequence'])


@pytest.mark.parametrize('cross',[False,True])
def test_crown_entry_save_and_damage_stop_actual_table_path(tmp_path,cross):
    combat,table,mid,left,right=portable(tmp_path,'FIRE_TAL_CROWN_OF_INFERNO','SAND_BASE_SCOURING_HAND',
                                      left_at=(2,6),right_at=(4,1),dc=50)
    e=combat._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.display_name.startswith('Crown of the Inferno') and c.destination==Position(x=4,y=6))
    assert send(table,mid,c)['status']=='COMMITTED'
    turn(table,mid,right)
    assert act(table,mid,'system:combat.dash')['status']=='COMMITTED'
    e=combat._load_session(mid).engine
    before=e.state.event_sequence
    c=candidate(e,4,11 if cross else 3)
    cells={p for z in zones.typed_zones(e) for p in z.affected_cells}
    first=next(p for p in c.canonical_path[1:] if p in cells)
    assert send(table,mid,c)['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    events=[ev for ev in loaded.engine.events if ev.sequence>before]
    assert any(ev.event_type=='SAVE_ROLLED' for ev in events)
    assert any(ev.event_type=='DAMAGE_COMMITTED' and right in ev.target_ids for ev in events)
    moved=next(ev for ev in events if ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==right)
    assert moved.payload['path'][-1]==first.model_dump(mode='json')
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


@pytest.mark.parametrize('split',[False,True])
def test_ash_distance_accumulates_actual_steps_across_table_actions(tmp_path,split):
    combat,table,mid,left,right=portable(tmp_path,'ASH_BASE_ASHFALL','SAND_BASE_SCOURING_HAND',
                                      left_at=(2,6),right_at=(4,4),dc=50)
    e=combat._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.display_name.startswith('Ashfall') and c.destination==Position(x=4,y=6))
    assert send(table,mid,c)['status']=='COMMITTED'
    turn(table,mid,right)
    before=combat._load_session(mid).engine.state.event_sequence
    for y in ([5,6,7] if split else [7]):
        e=combat._load_session(mid).engine
        assert send(table,mid,candidate(e,4,y))['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    triggers=[ev for ev in loaded.engine.events if ev.sequence>before and ev.event_type=='PASSIVE_TRIGGERED'
              and ev.payload.get('moment')=='move_through']
    assert len(triggers)==1
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_zone_damage_reaction_pauses_and_restores_entire_table_path(tmp_path):
    from tests.r10_fixup_support import answer
    combat,table,mid,left,right=portable(tmp_path,'FIRE_TAL_CROWN_OF_INFERNO','tianxia.talent.fire.fire_ward',
                                      left_at=(2,6),right_at=(4,1),dc=50)
    e=combat._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.display_name.startswith('Crown of the Inferno') and c.destination==Position(x=4,y=6))
    assert send(table,mid,c)['status']=='COMMITTED'
    turn(table,mid,right)
    assert act(table,mid,'system:combat.dash')['status']=='COMMITTED'
    e=combat._load_session(mid).engine
    c=candidate(e,4,11)
    before=e.state.model_dump(mode='json')
    sequence=table.state(mid)['last_sequence']
    submit=lambda replies=(): table.commit_move_path(mid,c.candidate_id,c.decision_id,c.state_version,c.actor_id,
        [p.model_dump(mode='json') for p in c.canonical_path],sequence,reactions=list(replies))
    result=submit()
    assert result['status']=='REACTION_REQUIRED'
    assert combat._load_session(mid).engine.state.model_dump(mode='json')==before
    replies=[]
    for _ in range(5):
        prompt=result['reaction']
        replies.append(answer(prompt,use=True) if prompt.get('choice') else {**prompt['context'],'selection':'USE'})
        result=submit(replies)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED'
    assert result['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert not loaded.engine.state.actors[right].reaction_available
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
