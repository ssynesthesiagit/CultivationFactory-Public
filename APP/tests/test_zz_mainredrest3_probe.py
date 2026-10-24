import test_auto52_beauty as T  # noqa


def test_probe_candidates(tmp_path):
    persistence, session, submit, named = T._declaration_table(tmp_path, "probe")
    e = session.engine
    rows = []
    for c in e.legal_candidates():
        if c.actor_id == T.FOE:
            rows.append((c.display_name, tuple(c.target_ids or ()), str(getattr(c.kind, "value", c.kind))))
    raise AssertionError("PROBE ME=%s FOE=%s ALLY=%s CURRENT=%s CANDS=%r" % (T.ME, T.FOE, T.ALLY, e.state.current_actor_id, rows))
