from tests.test_chimera_meridian_network import fixture, setup, evidence, strike, end, load, OWNER, FOE, FOE2, ALLY, SWAP, TURN


def test_zz_diag(tmp_path):
    combat, table, mid = fixture(tmp_path, ordered=True)
    setup(table, mid)
    evidence(combat, mid, OWNER, FOE, 'GENUINE')
    evidence(combat, mid, OWNER, FOE2, 'GENUINE')
    lines = []
    def snap(tag):
        eng = load(tmp_path, mid).engine
        lines.append(f"{tag} cur={eng.state.current_actor_id} round={eng.state.round_number}")
        lines.extend(f"  cand {c.kind} {c.source_definition_id} {c.target_ids}" for c in eng.legal_candidates() if c.kind.value == 'ACTION' and OWNER in c.target_ids)
    snap('after setup')
    strike(combat, table, mid)
    snap('after strike1')
    end(table, mid, {SWAP: ['Turtle>Crane'], TURN: ['Tiger', 'Turtle', 'Falcon']})
    snap('after end1')
    end(table, mid)
    snap('after end2')
    end(table, mid)
    snap('after end3')
    end(table, mid)
    snap('after end4')
    open('/var/tmp/auto-audit/fix/MGR-T15-close-chimera-meridian-network-evidence/diag3_out.txt', 'w').write("\n".join(lines))
    assert False, 'diag written'

