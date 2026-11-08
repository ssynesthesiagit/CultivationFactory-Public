"""Typing pass 2026-09-28, the Beastmastery sphere's rider-only abilities.

Distant Tamer ("Increase Beast Tamer range to 120 feet") had been typed by the structured pass, unreviewed, as an
addition of 120 ft, so the compiled Beast Tamer reached 30 + 120 = 150 ft. The printed value is the absolute 120 ft: a
reviewed +90 over Beast Tamer's own 30 ft."""

import json
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.tamer"


def _bundle(talents):
    return compile_character({**SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.beastmastery"],
                                                                              "learned_talent_record_ids": talents}}, actor_id=ME)


def _engine(bundle, foe_x):
    engine = Gate4ControllerEngine(ROOT, match_seed="TAMER", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 0, "y": 6}, AN: {"x": foe_x, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _tamer(bundle):
    return next(row for row in bundle["action_catalog"] if row["display_name"] == "Beast Tamer")


def test_distant_tamer_raises_beast_tamer_to_120_feet():
    assert _tamer(_bundle(["TAL_BEASTMASTERY_BEAST_TAMER"]))["range_ft"] == 30
    assert _tamer(_bundle(["TAL_BEASTMASTERY_BEAST_TAMER", "TAL_BEASTMASTERY_DISTANT_TAMER"]))["range_ft"] == 120


def test_beast_tamer_reaches_a_foe_95_feet_away_only_with_distant_tamer():
    # The grid is 95 ft across, so this checks the engine honours the raised range; the exact 120 is pinned above.
    def offered(talents):
        engine = _engine(_bundle(talents), foe_x=19)  # 19 cells = 95 ft on the 20-wide grid
        return any(c.display_name == "Beast Tamer" and tuple(c.target_ids) == (AN,) for c in engine.legal_candidates())

    assert not offered(["TAL_BEASTMASTERY_BEAST_TAMER"])
    assert offered(["TAL_BEASTMASTERY_BEAST_TAMER", "TAL_BEASTMASTERY_DISTANT_TAMER"])


def test_generated_authority_carries_distant_tamer():
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    entry = authority["TAL_BEASTMASTERY_DISTANT_TAMER"]
    assert entry["typing_status"] == "reviewed_final" and entry["coverage"] != "RIDERS_ONLY"
