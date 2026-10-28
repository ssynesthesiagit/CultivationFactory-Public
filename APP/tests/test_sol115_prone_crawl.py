"""Prone uses extra movement, not reduced Speed, on the actual persisted table."""
import pytest
from combat import posture, flight
from combat.gate2_runtime_models import ActionIntent, Position
from tests import lock8_support as S
from tests.test_lock8_prone import prone_table, record_setup, knock
from tests.test_hidden_targeting import turn
from tests.test_lock_choices import install


def execute(e, c):
    e.execute_intent(ActionIntent(intent_id='crawl-test', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
        target_ids=c.target_ids, destination=c.destination))


def test_kneel_crawl_menu_charge_reload_replay(tmp_path, monkeypatch):
    install(monkeypatch, 'd20_result', lambda engine, roll, context:
        {'source_id': 'test:roll', 'operation': 'replace',
         'natural_result': 1 if engine.d20_context().get('kind') == 'save' else 20})
    service, ui, mid, left, right = prone_table(tmp_path)
    record_setup(ui, mid, [right]); turn(ui, mid, left)
    e = service._load_session(mid).engine
    c = next(c for c in e.legal_candidates() if c.display_name == 'Imperial Command: Kneel' and c.target_ids == (right,))
    assert ui.act(mid, c.candidate_id, c.decision_id, c.state_version, ui.state(mid)['last_sequence'])['status'] == 'COMMITTED'
    turn(ui, mid, right)
    state = ui.state(mid); e = service._load_session(mid).engine; a = e.state.actors[right]
    assert posture.prone_conditions(a) and e._effective_speed(a) == a.speed_ft
    moves = [c for c in e.legal_candidates() if c.kind.value == 'MOVE']
    assert moves and max((len(c.canonical_path)-1)*5 for c in moves) <= a.speed_ft // 2
    assert all(c.movement_cost_ft == (len(c.canonical_path)-1)*10 for c in moves)
    assert not any(c.source_definition_id == posture.SOURCE for c in e.legal_candidates())
    assert all(c.metadata.get('movement_mode') != 'jump' for c in moves)
    summary = state['menu']['movement_explanation']['summary']
    assert any(r['code'] == 'CRAWLING' for r in summary['reasons'])
    shown = next(row for row in state['presentation']['actors'] if row['entity_id'] == right)
    assert shown['walking_distance_remaining_ft'] == a.movement_remaining_ft // 2
    c = min(moves, key=lambda c: c.movement_cost_ft)
    menu_move = next(m for m in state['menu']['moves'] if m['candidate_id'] == c.candidate_id)
    assert menu_move['cost_ft'] == c.movement_cost_ft
    assert any(r['code'] == 'CRAWLING' for r in state['menu']['movement_explanation']['destinations'][f'{c.destination.x},{c.destination.y}']['reasons'])
    before = a.movement_remaining_ft
    assert ui.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'])['status'] == 'COMMITTED'
    loaded = service._load_session(mid)
    assert loaded.engine.state.actors[right].movement_remaining_ft == before - c.movement_cost_ft
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('terrain,expected', [(1,10),(2,15)])
def test_crawl_adds_to_terrain_and_speed_standing_are_unchanged(terrain, expected):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND')); a = e.state.actors[S.ME]
    knock(e, a); knock(e, a, 'test:second')
    dst = Position(x=a.position.x-1,y=a.position.y)
    e.grid.base_movement_cost[(dst.x,dst.y)] = terrain
    assert flight.step_cost(e,a,a.position,dst) == expected
    c = next(c for c in e._movement_candidates(a) if c.destination == dst)
    assert c.movement_cost_ft == expected
    assert e._effective_speed(a) == a.speed_ft
    assert posture.standing_cost(e,a) == a.speed_ft // 2
    stand = next(c for c in e.legal_candidates() if c.source_definition_id == posture.SOURCE)
    before = a.movement_remaining_ft; action = a.action_available
    execute(e, stand)
    assert not posture.prone_conditions(a) and a.action_available == action
    assert a.movement_remaining_ft == before-a.speed_ft//2
    assert len(S.payloads(e.events,'STOOD_UP')) == 1


def test_ai_stands_when_allowed_and_crawls_when_vetoed():
    from tests.test_combat_gate4_controller import choose, selected_source
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND')); a=e.state.actors[S.ME]
    knock(e,a)
    choice, context = choose(e,S.ME)
    assert selected_source(context,choice) == posture.SOURCE
    e._apply_condition(a,'condition:typed.cannot_stand','test:held',S.FOE,
        expires_on='END_OF_TURN',data={'cannot_stand':True})
    assert not any(c.source_definition_id == posture.SOURCE for c in e.legal_candidates())
    assert e._movement_candidates(a)


def test_crawl_cost_is_not_difficult_terrain():
    from combat import motion
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND')); a=e.state.actors[S.ME]; knock(e,a)
    dst=Position(x=a.position.x-1,y=a.position.y)
    e.grid.base_movement_cost[(dst.x,dst.y)]=2
    e._apply_condition(a,'condition:typed.ignore_difficult','test:terrain',S.ME,expires_on='END_OF_TURN')
    with motion.terrain_for(e,a):
        assert flight.step_cost(e,a,a.position,dst)==10
        c=next(c for c in e._movement_candidates(a) if c.destination==dst)
        assert c.movement_cost_ft==10
    assert e.grid.base_movement_cost[(dst.x,dst.y)]==2


def test_modified_speed_dash_and_partial_movement_keep_one_allowance():
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND')); a=e.state.actors[S.ME]
    a.speed_ft=40
    e._add_modifier(a,'test:slow','speed_ft','ADD',-10,'SELF',expires_on='END_OF_TURN')
    a.movement_remaining_ft=30; knock(e,a)
    assert e._effective_speed(a)==30 and posture.standing_cost(e,a)==15
    dash=next(c for c in e.legal_candidates() if c.source_definition_id=='system:combat.dash')
    execute(e,dash)
    assert a.movement_remaining_ft==60 and e._effective_speed(a)==30
    move=min(e._movement_candidates(a),key=lambda c:c.movement_cost_ft)
    execute(e,move)
    assert a.movement_remaining_ft==50
    assert posture.stand_up(e,a) and a.movement_remaining_ft==35


def test_midturn_stand_table_commit_reload_replay(tmp_path,monkeypatch):
    from combat import ext
    from tests.test_lock2_persistence import act
    service,ui,mid,left,right=prone_table(tmp_path)
    record_setup(ui,mid,[]); turn(ui,mid,left)
    def fall(engine,event_type,kwargs):
        if event_type=='HOLD_POSITION_COMMITTED' and kwargs.get('actor_id')==left:
            knock(engine,engine.state.actors[left])
    ext.effects()
    monkeypatch.setitem(ext._HOOKS,'event',[*ext._HOOKS.get('event',[]),fall])
    assert act(ui,mid,'system:combat.hold_position')['status']=='COMMITTED'
    state=ui.state(mid); e=service._load_session(mid).engine
    a=e.state.actors[left]; before=a.movement_remaining_ft; action=a.action_available
    group=next(g for g in state['menu']['actions'] if g['source_definition_id']==posture.SOURCE)
    assert 'no Action' in group['cost_label']
    assert ui.act(mid,group['options'][0]['candidate_id'],state['menu']['decision_id'],state['menu']['state_version'],state['last_sequence'])['status']=='COMMITTED'
    loaded=service._load_session(mid); a=loaded.engine.state.actors[left]
    assert not posture.prone_conditions(a) and a.action_available==action
    assert a.movement_remaining_ft==before-loaded.engine._effective_speed(a)//2
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_heavenly_drunk_preserves_printed_full_speed_crawl():
    feature='tianxia.subpath.body.drunken_fist.feature.heavenly_drunk'
    e=S.fight(S.bundle(feature)); a=e.state.actors[S.ME]
    e._apply_condition(a,'condition:typed.state.heavenly_drunk',feature,S.ME,
        expires_on='END_OF_TURN',data={'name':'heavenly_drunk','label':'Heavenly Drunk'})
    knock(e,a)
    dst=Position(x=a.position.x-1,y=a.position.y)
    assert posture.walking_extra(e,a)==0 and posture.standing_cost(e,a)==0
    assert flight.step_cost(e,a,a.position,dst)==5
    e.grid.base_movement_cost[(dst.x,dst.y)]=2
    assert flight.step_cost(e,a,a.position,dst)==10
    c=next(c for c in e._movement_candidates(a) if c.destination==dst)
    assert c.movement_cost_ft==10
    assert 'without extra movement cost' in next(r['message'] for r in e.movement_explanation(S.ME)['reasons'] if r['code']=='CRAWLING')
