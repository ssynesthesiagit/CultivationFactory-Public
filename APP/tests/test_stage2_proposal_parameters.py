"""Keep the proposal schema and the per-choice parameter allowlist in sync."""
import json
from pathlib import Path

from stage2.service import KIND_PARAMETER_KEYS


def test_proposal_schema_declares_exactly_the_supported_choice_parameters():
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "Stage2_Advancement_Proposal_v2.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    parameters = schema["properties"]["choices"]["items"]["properties"]["parameters"]["properties"]
    assert set(parameters) == set().union(*KIND_PARAMETER_KEYS.values())
