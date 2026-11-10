from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v3_bridge_authority_pins_match_file_bytes():
    contract_path = ROOT / "projector/contracts/C2AR1_Stage2_v3_Projection_Contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    authority_files = {
        "baseline_pack": "authority/Tianxia_Core_Character_Baseline_Authority_Pack_R1.json",
        "fixture_selection_contract": "authority/Tianxia_C2AR1_Fixture_Selections_R1.json",
        "validation_profile": "projector/contracts/C2AR1_Stage_Aware_Validation_Profile.json",
        "stage2_authority_pack": "catalog/typed_authority/C1A_Canonical_Typed_Authority_Pack_v1.json",
        "exact_source_map": "catalog/typed_authority/C1A_Exact_Source_Map_v1.json",
    }
    for label, relative_path in authority_files.items():
        path = ROOT / relative_path
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert contract[label]["sha256"] == actual, f"{label} pin does not match {relative_path}"
