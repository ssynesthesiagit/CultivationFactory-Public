"""SOL199: source IDs are abilities; multiple engine checkpoints are not extra talents."""
from copy import deepcopy
from pathlib import Path
import subprocess

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET
from tests.test_fighter_picker import _install

ROOT = Path(__file__).resolve().parents[1]
STITCH = "TAL_THREAD_STITCH_THE_FALLING_BODY"
ANCHOR = "TAL_CHAINS_ANCHOR_LINK_BASE"
PID = "a1990000-0000-4000-8000-000000000001"


def test_multi_checkpoint_reactions_project_once_without_changing_bundle(tmp_path):
    sheet = deepcopy(SHEET)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = [STITCH, ANCHOR]
    _install(tmp_path, PID, sheet)
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    _sheet, bundle, _summary = table._bundle_and_summary(PID)
    original = deepcopy(bundle)
    for source in (STITCH, ANCHOR):
        rows = [r for r in bundle["typed_reactions"] if r["feature_id"] == source]
        assert {r["kind"] for r in rows} == {"ally_forced_moved", "ally_condition_gained"}
        assert len(rows) == 2
    projected = table.sheet(PID)["features"]["automated_reactions"]
    assert projected.count(STITCH) == projected.count(ANCHOR) == 1
    assert projected.index(STITCH) < projected.index(ANCHOR)
    assert bundle == original
    assert table._bundle_and_summary(PID)[1] == original


def test_stat_cards_in_node_dom():
    # node:test still runs and reports every case, without a child-process runner.
    subprocess.run(["node", str(ROOT / "tests/sheetbars.test.mjs")], cwd=ROOT, check=True)
