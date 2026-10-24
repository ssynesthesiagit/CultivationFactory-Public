import test_auto52_beauty as T  # noqa


def test_probe_candidates(tmp_path):
    persistence, session, submit, named = T._declaration_table(tmp_path, "probe")
    e = session.engine
    print("IDS ME", T.ME, "FOE", T.FOE, "ALLY", T.ALLY)
    print("CURRENT", e.state.current_actor_id)
    for c in e.legal_candidates():
        if c.actor_id == T.FOE:
            print("CAND", c.display_name, c.target_ids, c.kind)
    assert False, "probe"
