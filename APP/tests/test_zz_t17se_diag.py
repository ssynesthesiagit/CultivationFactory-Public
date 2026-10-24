"""TEMP diagnostic: dump owned Gather Charge event stream."""
import os
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture
from tests.test_mgr_t17_spark_step_table import _run_gather, GATHER, SPARK


def test_diag_owned_gather_stream(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [GATHER, SPARK], owner_cl=4, allies=[SECOND],
                                                positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 7, "y": 6}, SECOND: {"x": 4, "y": 7}})
    engine = combat._load_session(mid).engine
    n0 = len(engine.events)
    prompts = _run_gather(table, mid, candidate(table, mid, "Gather Charge", OWNER), selected=SECOND)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    with open("/var/tmp/t17se_diag_branch.txt", "w") as f:
        for e in loaded.engine.events[n0:]:
            f.write(repr((e.event_type, e.source_definition_id, e.actor_id, tuple(e.target_ids or ()), dict(e.payload or {})))[:700] + "\n")
