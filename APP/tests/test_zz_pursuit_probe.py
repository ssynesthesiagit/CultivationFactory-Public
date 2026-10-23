from tests.test_mgr_t15_pursuit_horizon import fight, move, turn, OWNER, FOE, PURSUIT


def _run(tmp_path):
    combat, table, mid = fight(tmp_path)
    turn(table, mid, FOE)
    engine, prompts = move(tmp_path, mid, 7)
    engine, prompts = move(tmp_path, mid, 8, pending=True)
    return engine


def test_p1_gm_riders(tmp_path):
    engine = _run(tmp_path)
    rows = [str(e.payload)[:150] for e in engine.events if e.event_type == 'GM_RIDER']
    assert not rows, 'GM ' + ' || '.join(rows)[:190]


def test_p2_pursuit_events(tmp_path):
    engine = _run(tmp_path)
    rows = [f"{e.sequence}:{e.event_type}:{str(e.source_definition_id)[-18:]}:{e.actor_id}" for e in engine.events
            if e.event_type not in ('INTENT_ACCEPTED', 'TURN_STARTED') and e.sequence >= 1][-40:]
    assert not rows, 'EV ' + ' '.join(rows)[:190]
