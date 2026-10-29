"""Core Tempering's scaling, critical rider and printed turn boundaries at the table."""
import json
import subprocess
import sys

import pytest

from tests.hunt14_support import ME, FOE, OTHER, ROOT, act, advance, fight, reload


@pytest.mark.parametrize("cl,pb,amount", [(12, 4, 4), (17, 2, 4), (17, 4, 8)])
def test_blood_furnace_scaling_survives_a_fresh_process(tmp_path, cl, pb, amount):
    combat, table, mid = fight(tmp_path, cl=cl, pb=pb)
    act(table, mid, "core_tempering_expression.blood_furnace")
    code = """
import json, sys
from pathlib import Path
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.hunt14_support import ME, ROOT, act
c=CombatService(ROOT, Path(sys.argv[1])); t=TabletopService(c, Path(sys.argv[1]))
act(t, sys.argv[2], 'tianxia.path.body_refining.feature.iron_voice')
s=c._load_session(sys.argv[2]); a=s.engine.state.actors[ME]
print(json.dumps({'temp_hp': a.temporary_hp, 'replay': s.mechanical.replay()['status']}))
"""
    result = json.loads(subprocess.check_output([sys.executable, "-c", code, str(tmp_path), mid], cwd=ROOT, text=True))
    assert result == {"temp_hp": amount, "replay": "PASS"}
    assert reload(tmp_path, mid).state.actors[ME].temporary_hp == amount


def test_perfected_golden_bell_soak_scaling_in_a_fresh_process(tmp_path):
    combat, table, mid = fight(tmp_path, cl=17, offturn=True)
    act(table, mid, "core_tempering_expression.golden_bell")
    act(table, mid, "golden_bell_circulation")
    act(table, mid, "end")
    advance(table, mid, FOE)
    stamina_before = reload(tmp_path, mid).state.actors[ME].resources["resource:core.stamina"]
    # fix/hunt10b (merge bb8f59ad) replaces boolean Guard consent with a payment
    # choice. Select the printed PB cap to retain this full-soak/Perfected probe.
    code = """
import sys
from pathlib import Path
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.hunt14_support import ROOT, ME, act
c=CombatService(ROOT, Path(sys.argv[1])); t=TabletopService(c, Path(sys.argv[1]))
act(t, sys.argv[2], 'natural.iron_fist', ME, option='4')
"""
    subprocess.check_call([sys.executable, "-c", code, str(tmp_path), mid], cwd=ROOT)
    engine = reload(tmp_path, mid)
    guard = next(e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.actor_id == ME
                 and "spend" in e.payload)
    assert guard.payload["spend"] == 4
    assert engine.state.actors[ME].resources["resource:core.stamina"] == stamina_before - 4
    assert guard.payload["pending_after"] == 0
    assert engine.state.actors[ME].temporary_hp == 8
