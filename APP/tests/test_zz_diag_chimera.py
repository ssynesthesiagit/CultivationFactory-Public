from tests.test_chimera_meridian_network import *  # noqa


def test_zz_diag(tmp_path):
    combat, table, mid = fixture(tmp_path, ordered=True)
    setup(table, mid)
    evidence(combat, mid, OWNER, FOE, 'GENUINE')
    evidence(combat, mid, OWNER, FOE2, 'GENUINE')
    strike(combat, table, mid)
    end(table, mid, {SWAP: ['Turtle>Crane'], TURN: ['Tiger', 'Turtle', 'Falcon']})
    session = load(tmp_path, mid)
    cur = session.engine.state.current_actor_id
    cands = [(c.kind, c.source_definition_id, tuple(c.target_ids)) for c in session.engine.legal_candidates() if cur]
    evs = [(e.event_type, e.actor_id, tuple(e.target_ids)) for e in session.engine.events[-40:]]
    raise AssertionError(repr({'cur': cur, 'cands': cands[:12], 'evs': evs}))

