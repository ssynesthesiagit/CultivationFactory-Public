"""Route-edge queries avoid full actor copies unless reach is being left."""
from contextvars import ContextVar

from combat import ext
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ActorState, Position
from combat.gate3_reducer import canonical_state_sha256
from tests.h1_support import ME, FOE, duel
from tests.test_lock2_persistence import table_match


def test_distant_edges_do_not_copy_runtime_actor(monkeypatch):
    engine = duel([])
    mover, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.position = Position(x=10, y=1)
    before = canonical_state_sha256(engine.state)
    copies = []
    original = ActorState.model_copy
    def observed(actor, **kwargs):
        if actor is mover and kwargs.get('deep'):
            copies.append(kwargs)
        return original(actor, **kwargs)
    monkeypatch.setattr(ActorState, 'model_copy', observed)
    for previous, nxt in ((Position(x=1,y=1),Position(x=2,y=1)),
                          (Position(x=2,y=1),Position(x=3,y=1)),
                          (Position(x=10,y=1),Position(x=10,y=2))):
        assert engine.opportunity_eligible(mover,previous,nxt,reactors=(foe,)) == ()
    assert copies == []
    assert canonical_state_sha256(engine.state) == before


def test_crossing_queries_keep_projected_position_and_isolation(monkeypatch):
    engine = duel([])
    mover, foe = engine.state.actors[ME], engine.state.actors[FOE]
    mover.position = Position(x=1,y=1)
    foe.position = Position(x=5,y=5)
    previous, nxt = Position(x=4,y=5), Position(x=3,y=5)
    before = canonical_state_sha256(engine.state)
    seen = []
    ext.effects()
    def veto(engine, reactor, projected):
        assert projected is not mover
        assert projected.position == previous
        assert projected.turn_flags is not mover.turn_flags
        seen.append(reactor.entity_id)
        return False
    monkeypatch.setitem(ext._HOOKS,'opportunity_allowed',[veto])
    assert engine.opportunity_eligible(mover,previous,nxt,reactors=(foe,)) == ()
    assert seen == [FOE]
    assert canonical_state_sha256(engine.state) == before


def test_table_routes_only_project_crossing_edges_and_reload(tmp_path, monkeypatch):
    # Observe only copies made inside the public opportunity query. Other
    # legitimate preview/commit copies retain their existing isolation.
    combat, table, mid = table_match(tmp_path)
    entered = ContextVar('speedlive_opportunity_test',default=False)
    counts = {'edges':0,'copies':0}
    original_query = Gate2Engine.opportunity_eligible
    original_copy = ActorState.model_copy
    def query(engine,*args,**kwargs):
        counts['edges'] += 1
        token = entered.set(True)
        try:
            return original_query(engine,*args,**kwargs)
        finally:
            entered.reset(token)
    def copied(actor,**kwargs):
        if entered.get() and kwargs.get('deep') and 'position' in (kwargs.get('update') or {}):
            counts['copies'] += 1
        return original_copy(actor,**kwargs)
    monkeypatch.setattr(Gate2Engine,'opportunity_eligible',query)
    monkeypatch.setattr(ActorState,'model_copy',copied)
    combat._derived.clear()
    state = table.state(mid)
    assert counts['edges'] > 0
    assert counts['copies'] < counts['edges'] // 2
    session = combat._load_session(mid)
    moves = [c for c in combat._legal_candidates(session) if c.kind == 'MOVE']
    assert moves
    menu = state['menu']
    result = table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],state['last_sequence'])
    assert result['status'] == 'COMMITTED'
    reloaded = type(combat)(combat.source_root,tmp_path)._load_session(mid)
    assert canonical_state_sha256(reloaded.engine.state) == canonical_state_sha256(combat._load_session(mid).engine.state)
    assert reloaded.mechanical.replay()['status'] == 'PASS'
