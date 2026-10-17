"""Every sealed Character Sheet contract passes the service's own sidecar check.

2026-10-17: the readiness profile's .sha256 sidecar declared a repo path instead of its bare file name, so
CharacterSheetService._verify_sealed_json raised CHARACTER_SHEET_READINESS_PROFILE_STALE and every finalize stopped at
NEEDS_REVIEW. The hash itself was right; only the declared name was wrong.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from character_sheet.service import CharacterSheetService

CONTRACTS = Path(__file__).resolve().parents[1] / "character_sheet" / "contracts"
SIDECARS = sorted(CONTRACTS.glob("*.json.sha256"))


def test_contracts_have_sidecars():
    assert SIDECARS, f"no sealed contracts found in {CONTRACTS}"


@pytest.mark.parametrize("sidecar", SIDECARS, ids=lambda p: p.name)
def test_sealed_contract_verifies(sidecar: Path):
    contract = sidecar.with_suffix("")
    schema = json.loads(contract.read_text(encoding="utf-8"))["schema_version"]
    payload, _ = CharacterSheetService._verify_sealed_json(contract, expected_schema=schema, error_prefix="TEST_CONTRACT")
    assert payload["schema_version"] == schema
