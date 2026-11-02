"""Every detached .sha256 seal in APP names its own file and matches it.

2026-10-17: two seals went stale in the 2026-10-13 composite-playbook cleanup and every finalize stopped at NEEDS_REVIEW:
- the readiness profile's sidecar declared a repo path instead of its bare file name
  (CHARACTER_SHEET_READINESS_PROFILE_STALE from CharacterSheetService._verify_sealed_json);
- the GM model profile schema was edited without resealing (GM_MODEL_PROFILE_SCHEMA_STALE).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from character_sheet.service import CharacterSheetService

APP = Path(__file__).resolve().parents[1]
SIDECARS = sorted(p for p in APP.rglob("*.sha256") if not any(part.startswith(".") for part in p.relative_to(APP).parts))
CONTRACTS = APP / "character_sheet" / "contracts"


def test_seals_found():
    assert any(p.parent == CONTRACTS for p in SIDECARS), f"no sealed contracts found in {CONTRACTS}"


@pytest.mark.parametrize("sidecar", SIDECARS, ids=lambda p: str(p.relative_to(APP)))
def test_seal_names_its_file_and_matches(sidecar: Path):
    target = sidecar.with_suffix("")
    if not target.is_file():
        pytest.skip(f"{target.name} is not in this checkout")
    digest, name = sidecar.read_text(encoding="utf-8").strip().split(None, 1)
    assert name.strip().lstrip("*") == target.name, "a seal must declare its bare file name"
    assert digest.lower() == hashlib.sha256(target.read_bytes()).hexdigest(), f"{target.name} changed without a reseal"


@pytest.mark.parametrize("sidecar", sorted(CONTRACTS.glob("*.json.sha256")), ids=lambda p: p.name)
def test_character_sheet_contract_passes_the_service_verifier(sidecar: Path):
    contract = sidecar.with_suffix("")
    schema = json.loads(contract.read_text(encoding="utf-8"))["schema_version"]
    payload, _ = CharacterSheetService._verify_sealed_json(contract, expected_schema=schema, error_prefix="TEST_CONTRACT")
    assert payload["schema_version"] == schema
