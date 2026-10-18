"""The native Archivist acquisition must reach projection with authentic inputs.

The full service regression lives in test_formula_archivist_native. These cheap
checks identify a stale sealed dependency before starting that real build.
"""
import hashlib
import json
from pathlib import Path

import pytest

from app.core import sha256_json
from character_sheet.service import CharacterSheetService


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'projector/contracts/C2AR1_Stage2_v3_Projection_Contract.json'


@pytest.mark.parametrize('key,relative', [
    ('validation_profile', 'projector/contracts/C2AR1_Stage_Aware_Validation_Profile.json'),
    ('baseline_pack', 'authority/Tianxia_Core_Character_Baseline_Authority_Pack_R1.json'),
    ('fixture_selection_contract', 'authority/Tianxia_C2AR1_Fixture_Selections_R1.json'),
    ('stage2_authority_pack', 'catalog/typed_authority/C1A_Canonical_Typed_Authority_Pack_v1.json'),
    ('exact_source_map', 'catalog/typed_authority/C1A_Exact_Source_Map_v1.json'),
])
def test_native_projection_contract_binds_current_authority(key, relative):
    contract = json.loads(CONTRACT.read_text())
    actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    assert contract[key]['sha256'] == actual, (key, relative)


def test_native_projection_contract_seal_and_sidecar_match():
    raw = CONTRACT.read_bytes()
    contract = json.loads(raw)
    seal = contract.pop('seal_sha256')
    assert seal == sha256_json(contract)
    expected, filename = CONTRACT.with_suffix('.json.sha256').read_text().split()
    assert filename == CONTRACT.name
    assert expected == hashlib.sha256(raw).hexdigest()

SHEET_CONTRACTS = ROOT / 'character_sheet/contracts'
READINESS = SHEET_CONTRACTS / "Tianxia_Character_Sheet_Readiness_Profile_R1.json"


def test_readiness_profile_verifies_against_its_detached_checksum():
    payload, digest = CharacterSheetService._verify_sealed_json(
        READINESS,
        expected_schema="TianxiaFoundry.CharacterSheetReadinessProfile.v1",
        error_prefix="CHARACTER_SHEET_READINESS_PROFILE",
    )
    assert payload["profile_id"]
    assert digest == hashlib.sha256(READINESS.read_bytes()).hexdigest()


def test_character_sheet_sidecars_declare_bare_file_names():
    for sidecar in sorted(SHEET_CONTRACTS.glob("*.sha256")):
        digest, declared = sidecar.read_text(encoding="utf-8").strip().split(None, 1)
        assert declared.lstrip("*") == sidecar.with_suffix("").name, sidecar.name
        assert len(digest) == 64, sidecar.name


def test_factory_authoring_schema_sidecars_match_their_files():
    """The Command 5 model schema changed in de87f7f7 without re-pinning its checksum sidecar."""
    authoring = ROOT / 'factory_authoring/contracts'
    stale = []
    for sidecar in sorted(authoring.glob('*.sha256')):
        digest, declared = sidecar.read_text(encoding='utf-8').strip().split(None, 1)
        target = authoring / sidecar.with_suffix('').name
        if declared.lstrip('*') != target.name or digest.lower() != hashlib.sha256(target.read_bytes()).hexdigest():
            stale.append(target.name)
    assert stale == []
