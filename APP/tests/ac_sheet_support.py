"""Scratch sheet setup shared by the AC service and browser checks."""
import json
from pathlib import Path
from zipfile import ZipFile

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]


def scratch_sheet_payload(tmp_path):
    """Compile the existing scratch sheet through the production sheet API."""
    sheet = json.loads((ROOT / "tests/fixtures/gm_sheet/scratch_owner_sheet_snapshot.fixture.json").read_text())
    folder = tmp_path / "portable_characters" / "abcdef19"
    folder.mkdir(parents=True)
    with ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    return TabletopService(CombatService(ROOT, tmp_path), tmp_path).sheet("abcdef19")
