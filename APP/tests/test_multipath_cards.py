"""SOL197: display finalized Path/Subpath ownership without altering characters."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from character_sheet.path_display import path_display
from combat.fighter_picker import card_fields
from combat.tabletop import sheet_summary
from tests.test_factory_combat_compiler import SHEET
from tests.test_fighter_picker import _install
from combat.gate5_service import CombatService
from tests.test_character_sheet_complete_character import _service, _sheet_stubs, PROJECT_ID

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = "Spirit Awakening (Soulstring Dancer) + Body Refining (Göruden)"
MULTI = {**SHEET, "identity": {**SHEET["identity"], "cultivation_level": 10, "path": "Spirit Awakening"},
         "path_and_subpath": {
             "paths": [{"path_id": "spirit", "display_name": "Spirit Awakening"},
                       {"path_id": "body", "display_name": "Body Refining"}],
             # Reversed order deliberately: pairing is by owner, not position.
             "subpaths": [{"owning_path_id": "body", "name": "Göruden"},
                          {"owning_path_id": "spirit", "name": "Soulstring Dancer"}],
             "subpath": {"owning_path_id": "spirit", "name": "Soulstring Dancer"}}}


@pytest.mark.parametrize("multi", [True, False], ids=["multi-path", "single-path"])
def test_finalized_card_and_table_sheet_projections(tmp_path, monkeypatch, multi):
    sheet = deepcopy(MULTI)
    if not multi:
        sheet["path_and_subpath"]["paths"] = sheet["path_and_subpath"]["paths"][:1]
        sheet["path_and_subpath"]["subpaths"] = sheet["path_and_subpath"]["subpaths"][1:]
    sealed = deepcopy(sheet)
    expected = SUMMARY if multi else None
    _install(tmp_path, "sol197", sheet)
    [row] = CombatService(ROOT, tmp_path).factory_characters()
    assert row["path_summary"] == expected
    assert row["path"] == "Spirit Awakening"
    assert row["subpath"] == "Soulstring Dancer"
    assert sheet_summary(sheet)["path_summary"] == expected
    # Real sheet() -> compact list_row(): only sealed-artifact I/O is stubbed.
    service = _service(tmp_path / "library")
    _sheet_stubs(service)
    snapshot = json.loads((ROOT / "tests/fixtures/gm_sheet/scratch_owner_sheet_snapshot.fixture.json").read_text())
    snapshot.update(deepcopy(sheet))
    monkeypatch.setattr(service, "_compiled_artifacts", lambda pid: (
        {"Character_Master_Ledger.json": {"readiness": {"advancement": "ADVANCEMENT_READY"}}}, {}))
    monkeypatch.setattr(service, "_cached_snapshot", lambda *args, **kwargs: (snapshot, {}))
    monkeypatch.setattr(service, "_with_authenticated_rules_text", lambda value: deepcopy(value))
    monkeypatch.setattr(service, "_with_foundation_method_text", lambda value: value)
    assert service.sheet(PROJECT_ID, compact=True)["path_summary"] == expected
    assert service.sheet(PROJECT_ID)["path_summary"] == expected
    assert service.list_row(PROJECT_ID)["path_summary"] == expected
    assert sheet == sealed


def test_explicit_bindings_only_and_no_inferred_primary_owner():
    sheet = deepcopy(MULTI)
    sheet["path_and_subpath"]["subpaths"] = [{"subpath_id": "g", "name": "Göruden"}, {"name": "Unowned"}]
    sheet["path_and_subpath"]["bindings"] = [{"path_id": "body", "subpath_id": "g"}]
    assert card_fields(sheet)["path_summary"] == "Spirit Awakening + Body Refining (Göruden)"


def test_card_text_in_node_dom():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable")
    subprocess.run([node, "--test", str(ROOT / "tests/multipath_cards.test.mjs")], check=True, cwd=ROOT)
