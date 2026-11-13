"""Synthetic sheet helpers shared by AC tests."""
import json
from pathlib import Path
from zipfile import ZipFile

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]


def install_sheet(tmp_path, sheet, pid="hero"):
    """Install a synthetic sheet as a portable character package."""
    folder = tmp_path / "portable_characters" / pid
    folder.mkdir(parents=True)
    with ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))


def projected_sheet(feature, *, armor=None, dex=14):
    """Use the real sheet's statistic producer and published provenance shape."""
    from tests.equipment_sheet_support import ROOT, _sheet, _kit, AXE, UNARMORED
    from tests.test_path_feature_statistics import BASELINE, _context
    from projector.path_feature_statistics import load_path_feature_statistic_formulas, resolve_armor_class
    sheet = _sheet(_kit(AXE, *([armor] if armor else [])), dex=dex, mids=[UNARMORED, feature])
    result = resolve_armor_class(load_path_feature_statistic_formulas(ROOT), [UNARMORED, feature],
        baseline_rule=BASELINE, baseline_value=10 + (dex - 10) // 2,
        baseline_trace={}, context=_context(con=3, dex=(dex - 10) // 2, pb=4))
    sheet['ability_scores_and_statistics']['armor_class'] = {
        'base_value': result['ac_base'], 'value': result['ac_active'], 'generation': result['ac_generation']}
    return sheet



def scratch_sheet_payload(tmp_path):
    """Compile the existing scratch sheet through the production sheet API."""
    sheet = json.loads((ROOT / "tests/fixtures/gm_sheet/scratch_owner_sheet_snapshot.fixture.json").read_text())
    install_sheet(tmp_path, sheet, "abcdef19")
    return TabletopService(CombatService(ROOT, tmp_path), tmp_path).sheet("abcdef19")
