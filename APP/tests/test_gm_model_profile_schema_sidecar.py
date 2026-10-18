"""Regression: the Character/GM model profile schema sidecar must match the schema file.

command5_profile._model_schema() refuses to load the schema with GM_MODEL_PROFILE_SCHEMA_STALE when the
.sha256 sidecar disagrees with the file. main's de87f7f7 edited the schema without updating the sidecar, so every
character creation run that reaches the GM model profile (the Raincaller native tests) stopped at NEEDS_REVIEW.
"""
import hashlib
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[1] / "factory_authoring" / "contracts"
SCHEMA = "Tianxia_C2B3_GM_Character_Model_Profile_R1.schema.json"


def test_gm_model_profile_schema_sidecar_matches_schema_file():
    path = CONTRACTS / SCHEMA
    digest, declared = (CONTRACTS / (SCHEMA + ".sha256")).read_text(encoding="utf-8").strip().split(None, 1)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest.lower()
    assert declared.strip().lstrip("*") == SCHEMA
