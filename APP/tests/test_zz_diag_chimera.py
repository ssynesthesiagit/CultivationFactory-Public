from tests.test_chimera_meridian_network import fixture, setup, evidence, strike, end, load, OWNER, FOE, FOE2, ALLY, SWAP, TURN


def test_zz_diag(tmp_path):
    combat, table, mid = fixture(tmp_path, ordered=True)
    setup(table, mid)
    evidence(combat, mid, OWNER, FOE, 'GENUINE')
    evidence(combat, mid, OWNER, FOE2, 'GENUINE')
    strike(combat, table, mid)
    end(table, mid, {SWAP: ['Turtle>Crane'], TURN: ['Tiger', 'Turtle', 'Falcon']})
    end(table, mid)
    session = load(tmp_path, mid)
    eng = session.engine
    lines = [f"cur={eng.state.current_actor_id}"]
    lines += [f"cand {c.kind} {c.source_definition_id} {c.target_ids} {c.candidate_id}" for c in eng.legal_candidates()]
    lines += [f"ev {e.event_type} {e.actor_id} {e.target_ids} {str(e.payload)[:160]}" for e in eng.events[-60:]]
    open('/var/tmp/auto-audit/fix/MGR-T15-close-chimera-meridian-network-evidence/diag_out.txt', 'w').write("\n".join(lines))
    assert False, 'diag written'

