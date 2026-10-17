from tests.test_chimera_meridian_network import fixture, setup, evidence, strike, end, load, OWNER, FOE, FOE2, ALLY, SWAP, TURN


def test_zz_diag(tmp_path):
    combat, table, mid = fixture(tmp_path, ordered=True)
    setup(table, mid)
    evidence(combat, mid, OWNER, FOE, 'GENUINE')
    evidence(combat, mid, OWNER, FOE2, 'GENUINE')
    strike(combat, table, mid)
    end(table, mid, {SWAP: ['Turtle>Crane'], TURN: ['Tiger', 'Turtle', 'Falcon']})
    end(table, mid); end(table, mid); end(table, mid)
    assert load(tmp_path, mid).engine.state.round_number == 2
    strike(combat, table, mid)
    eng = load(tmp_path, mid).engine
    out = [f"{e.event_type} {e.actor_id} {e.target_ids} {str(e.payload)[:300]}" for e in eng.events[-14:]]
    open('/var/tmp/auto-audit/fix/MGR-T15-close-chimera-meridian-network-evidence/diag4_out.txt', 'w').write("\n".join(out))
    assert False, 'diag written'

