import json, pathlib
from tests.test_mgr_t17_spark_step_table import _run_gather, GATHER, SPARK
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture


def test_zz_dump_gather_events(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [GATHER, SPARK], owner_cl=4, allies=[SECOND],
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 7, "y": 6}, SECOND: {"x": 4, "y": 7}})
    engine = combat._load_session(mid).engine
    n0 = len(engine.events)
    gather = candidate(table, mid, "Gather Charge", OWNER)
    _run_gather(table, mid, gather, selected=SECOND)
    engine = combat._load_session(mid).engine
    with open("/var/tmp/t17se_diag_branch.txt", "w") as f:
        for ev in engine.events[n0:]:
            f.write(json.dumps({"type": ev.event_type, "src": ev.source_definition_id, "actor": ev.actor_id,
                                "targets": list(ev.target_ids), "payload": ev.payload}, default=str)[:900] + "\n")
