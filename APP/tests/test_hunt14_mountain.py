"""Core Tempering's scaling, critical rider and printed turn boundaries at the table."""
import json
import subprocess
import sys

import pytest

from tests.hunt14_support import ME, FOE, OTHER, ROOT, act, advance, fight, reload


@pytest.mark.parametrize("seed,dice", [(0, "2d8+0"), (76, "4d8+0")])
@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("cold", [False, True])
def test_mountain_rending_attack_dice_and_target_start_expiry(tmp_path, seed, dice, auto, cold):
    combat, table, mid = fight(tmp_path, seed=seed)
    act(table, mid, "core_tempering_expression.mountain_rending")
    act(table, mid, "mountain_rending_choice.deny_reactions")
    act(table, mid, "tianxia.path.body_refining.feature.iron_voice", FOE)
    if auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    if cold:
        code = """
import sys
from pathlib import Path
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.hunt14_support import ROOT, FOE, act
c=CombatService(ROOT, Path(sys.argv[1])); t=TabletopService(c, Path(sys.argv[1]))
act(t, sys.argv[2], 'natural.iron_fist', FOE, auto=sys.argv[3]=='True', selected=True)
"""
        subprocess.check_call([sys.executable, "-c", code, str(tmp_path), mid, str(auto)], cwd=ROOT)
    else:
        act(table, mid, "natural.iron_fist", FOE, auto=auto, selected=True)
    engine = reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == ME]
    assert rolls[-1].payload["expression"] == dice
    assert any("reaction_denied" in c.condition_id for c in engine.state.actors[FOE].conditions.values())
    if auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="MANUAL")
    act(table, mid, "end")
    advance(table, mid, FOE)
    engine = reload(tmp_path, mid)
    assert not any("reaction_denied" in c.condition_id for c in engine.state.actors[FOE].conditions.values())
