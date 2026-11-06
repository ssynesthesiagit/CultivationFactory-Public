"""Table regressions for no-op retries; private copied match is opt-in."""
import json
import os
import shutil
from pathlib import Path

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat import target_knowledge
from combat.ext import movement_safety
from combat.gate2_runtime_models import Position
from tests.h1_support import ME, FOE, ROOT, duel
from tests.worker2_support import OWNER, FOE as TABLE_FOE, fixture, settle


def test_table_noop_guard_work_is_bounded_as_verified_history_grows(tmp_path, monkeypatch):
    from combat.turn_progress import HISTORY_RECORD_LIMIT
    combat, table, mid = fixture(tmp_path, [], ask=False)
    hold = next(c for c in combat._legal_candidates(combat._load_session(mid))
                if c.kind.value == 'HOLD_POSITION')
    settle(table, mid, hold.candidate_id)
    # Load through the real storage verifier first. Instrument only the menu's
    # input, modeling older unrelated turns and a long unchanged no-op streak.
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    recent = loaded.mechanical._records
    class CountedHistory(list):
        def __iter__(self):
            pytest.fail('menu iterated the entire verified history')
        def __getitem__(self, key):
            assert isinstance(key, slice), 'menu indexed unbounded history'
            result = super().__getitem__(key)
            self.work = len(result)
            assert self.work <= HISTORY_RECORD_LIMIT
            return result
    def no_scan(**kwargs):
        pytest.fail('menu rescanned/revalidated the on-disk journal')
    monkeypatch.setattr(loaded.store, 'scan_journal', no_scan)
    outputs, work = [], []
    for older_count in (128, 1024, 10000):
        history = CountedHistory([{'record_type': 'ABORT'}] * older_count + recent)
        loaded.mechanical._records = history
        cold = CombatService(ROOT, tmp_path)
        ai = cold._legal_candidates(loaded, knowledge_only=True)
        assert not any(c.kind.value == 'HOLD_POSITION' for c in ai)
        assert any(c.kind.value == 'END_TURN' for c in ai)
        outputs.append([c.model_dump(mode='json') for c in ai])
        work.append(history.work)
    assert outputs[0] == outputs[1] == outputs[2]
    assert work == [HISTORY_RECORD_LIMIT] * 3
    # Even a growing streak in the current unchanged turn stays bounded.
    # Copies of its real verified PREPARE/COMMIT receipts model that streak;
    # the query never uses sequence/hash values to assert journal integrity.
    no_op = recent[-2:]
    for repeat in (65, 512, 5000):
        history = CountedHistory(recent + no_op * repeat)
        loaded.mechanical._records = history
        ai = CombatService(ROOT, tmp_path)._legal_candidates(loaded, knowledge_only=True)
        assert [c.model_dump(mode='json') for c in ai] == outputs[0]
        assert history.work == HISTORY_RECORD_LIMIT


def test_table_noop_identity_ignores_versions_but_resets_on_progress(tmp_path):
    combat, table, mid = fixture(tmp_path, [], ask=False)
    session = combat._load_session(mid)
    before = combat._legal_candidates(session)
    hold = next(c for c in before if c.kind.value == 'HOLD_POSITION')
    settle(table, mid, hold.candidate_id)
    cold = CombatService(ROOT, tmp_path)
    loaded = cold._load_session(mid)
    assert loaded.engine.state.state_version > hold.state_version
    assert any(c.kind.value == 'HOLD_POSITION' for c in cold._legal_candidates(loaded))
    ai = cold._legal_candidates(loaded, knowledge_only=True)
    assert not any(c.kind.value == 'HOLD_POSITION' for c in ai)
    assert any(c.kind.value == 'END_TURN' for c in ai)
    # A real economy change permits reconsideration, including cold reload.
    dash = next(c for c in cold._legal_candidates(loaded) if c.source_definition_id == 'system:combat.dash')
    settle(TabletopService(cold, tmp_path), mid, dash.candidate_id)
    cold = CombatService(ROOT, tmp_path)
    loaded = cold._load_session(mid)
    assert any(c.kind.value == 'HOLD_POSITION' for c in cold._legal_candidates(loaded, knowledge_only=True))
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_unperceived_ordinary_creature_records_physical_contact(monkeypatch):
    engine = duel([])
    actor, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.position = Position(x=actor.position.x+1, y=actor.position.y)
    assert not target_knowledge.concealed(foe)
    monkeypatch.setattr(target_knowledge, 'located', lambda *args: False)
    assert target_knowledge.movement_contact(engine, actor, foe.position)
    assert foe.entity_id in actor.turn_flags['unseen_blockers']
    assert any(e.event_type == 'TARGETS_OBSERVED' for e in engine.events)
    occupied = engine._occupied_cells_except(ME, observed=True)
    assert (foe.position.x, foe.position.y) in occupied


def test_table_noop_guard_falls_back_to_end_and_resets_next_turn(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    from tests.worker2_support import turn
    combat, table, mid = fixture(tmp_path, [], ask=False)
    hold = next(c for c in combat._legal_candidates(combat._load_session(mid)) if c.kind.value=='HOLD_POSITION')
    settle(table, mid, hold.candidate_id)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    original = combat.controller
    class RepeatingController:
        def choose_primary_action(self, context):
            chosen = next((c for c in context.legal_candidates if c.kind.value=='HOLD_POSITION'),
                          next(c for c in context.legal_candidates if c.kind.value=='END_TURN'))
            return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(original, name)
    combat.controller = RepeatingController()
    assert table.auto_step(mid, 0)['status']=='COMMITTED'
    assert combat._load_session(mid).engine.state.current_actor_id != OWNER
    turn(table, mid, OWNER)
    cold = CombatService(ROOT, tmp_path)
    loaded = cold._load_session(mid)
    assert any(c.kind.value=='HOLD_POSITION' for c in cold._legal_candidates(loaded, knowledge_only=True))
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_failed_first_edge_is_3d_and_other_routes_remain_available():
    engine = duel([])
    actor = engine.state.actors[ME]
    moves = [c for c in engine.legal_candidates() if c.kind.value == 'MOVE' and len(c.canonical_path)>2]
    first = moves[0]
    same = next(c for c in moves if c.destination != first.destination
                and c.canonical_path[:2] == first.canonical_path[:2])
    actor.turn_flags[movement_safety.edge_key(first.canonical_path)] = movement_safety._movement_state(engine)
    assert movement_safety.movement_allowed(engine, actor, first, None) is False
    assert movement_safety.movement_allowed(engine, actor, same, None) is False
    another = next(c for c in moves if c.canonical_path[:2] != first.canonical_path[:2])
    assert movement_safety.movement_allowed(engine, actor, another, None) is None
    actor.movement_remaining_ft -= 5
    assert movement_safety.movement_allowed(engine, actor, same, None) is None
    assert movement_safety.edge_key((Position(x=1,y=1),Position(x=2,y=1))) != movement_safety.edge_key(
        (Position(x=1,y=1,z=1),Position(x=2,y=1,z=1)))


def test_failed_edge_flag_survives_table_commit_and_reload(tmp_path, monkeypatch):
    from combat import ext
    combat, table, mid = fixture(tmp_path, [], ask=False)
    before = combat._load_session(mid)
    move = next(c for c in combat._legal_candidates(before) if c.kind.value=='MOVE' and len(c.canonical_path)>2)
    edge = movement_safety.edge_key(move.canonical_path)
    old = before.engine.state.actors[TABLE_FOE].position
    def relocate(engine, destination):
        blocker = engine.state.actors[TABLE_FOE]
        start = blocker.position
        blocker.position = destination
        engine._append_event('MOVEMENT_COMMITTED', 'test:speedservant.blocker', actor_id=TABLE_FOE,
            payload={'path':[p.model_dump(mode='json') for p in (start,destination)],
                     'destination':destination.model_dump(mode='json'),'cost_ft':0,'forced':True,'teleport':True})
    def move_blocker(engine, event_type, kwargs):
        if event_type=='INTENT_ACCEPTED' and (kwargs.get('payload') or {}).get('candidate_id')==move.candidate_id:
            relocate(engine, move.canonical_path[1])
        elif event_type=='HOLD_POSITION_COMMITTED' and kwargs.get('actor_id')==OWNER:
            relocate(engine, old)
    # Keep the real movement-safety recorder installed alongside the injector.
    # test_lock_choices.install replaces a hook family and would remove it.
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', ()), move_blocker])
    settle(table, mid, move.candidate_id)
    cold = CombatService(ROOT, tmp_path)
    loaded = cold._load_session(mid)
    actor = loaded.engine.state.actors[OWNER]
    assert actor.position == before.engine.state.actors[OWNER].position
    assert isinstance(actor.turn_flags[edge], str)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
    hold = next(c for c in cold._legal_candidates(loaded) if c.kind.value=='HOLD_POSITION')
    settle(TabletopService(cold,tmp_path),mid,hold.candidate_id)
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    assert any(c.kind.value=='MOVE' and c.canonical_path[:2]==move.canonical_path[:2]
               for c in loaded.engine.legal_candidates()), 'an opened route was still vetoed'
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


@pytest.mark.skipif(not os.environ.get('CF_SPEEDSERVANT_MATCH'), reason='private copied-match table regression is opt-in')
def test_copied_table_exits_servant_no_progress_loop(tmp_path):
    from combat.gate3_storage import encode_match_directory_name
    from tools.benchmark_ai_turns import prepare_scenario
    source = Path(os.environ['CF_SPEEDSERVANT_MATCH'])
    mid = json.loads((source/'Manifest.json').read_text())['match_id']
    shutil.copytree(source, tmp_path/'input/Combat/Matches'/encode_match_directory_name(mid))
    combat, session, mid = prepare_scenario('loop', tmp_path/'data', tmp_path/'input')
    table = TabletopService(combat, tmp_path/'data')
    actor_id = session.engine.state.current_actor_id
    actor = session.engine.state.actors[actor_id]
    assert actor.summon and actor.position == Position(x=24,y=11)
    failed_edge = ((24,11,0),(24,12,0))
    def first_edge(candidate):
        return tuple((p.x,p.y,p.z) for p in candidate.canonical_path[:2])
    assert not any(first_edge(c) == failed_edge
                   for c in combat._legal_candidates(session, knowledge_only=True)), 'failed first edge was reoffered'
    start = actor.position
    receipts = []
    blocked_origins = {(24,11,0)}
    for _ in range(12):
        loaded = combat._load_session(mid)
        if loaded.engine.state.current_actor_id != actor_id:
            break
        offset = len(loaded.engine.events)
        result = table.auto_step(mid, 0)
        assert result['status'] == 'COMMITTED', result
        loaded = CombatService(ROOT, tmp_path/'data')._load_session(mid)
        events = loaded.engine.events[offset:]
        for event in events:
            if event.event_type == 'MOVEMENT_COMMITTED' and event.actor_id == actor_id:
                if event.payload['cost_ft'] == 0:
                    origin = event.payload['path'][0]
                    cell = (origin['x'],origin['y'],origin.get('z',0))
                    assert cell not in blocked_origins, 'servant repeated a blocked zero-foot move'
                    blocked_origins.add(cell)
        receipts.append([e.event_type for e in events])
    else:
        pytest.fail('servant failed to finish its turn')
    assert receipts and loaded.engine.state.actors[actor_id].position != start
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
