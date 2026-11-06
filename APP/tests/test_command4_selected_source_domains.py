"""Source-bound regression checks using an optional retained workspace."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from app.core import FoundryError
from factory_authoring.command4_provider import _provider_authorable_fields, _provider_field_domain


RECORD_IDS = (
    "TAL_KARMA_INVOKE_THE_LEDGER", "TAL_KARMA_LEDGER_EYE", "TAL_KARMA_RECORD_THE_DEED",
    "TAL_KARMA_SETTLE_MINOR_ACCOUNT", "tianxia.talent.karma.witness_seal",
    "tianxia.talent.karma.minor_oath", "TAL_ALCHEMY_NUMBING_POWDER",
    "TAL_ATHLETICS_BODY_BEYOND_DISTANCE",
)


@pytest.mark.parametrize("record_id", RECORD_IDS)
def test_selected_source_domains_cover_slots_preserve_modes_and_reject_changed_source(record_id):
    root = os.environ.get("CULTIVATION_FACTORY_COMMAND4_FIXTURE_DIR")
    if not root:
        pytest.skip("retained Command 4 workspace is unavailable")
    document = json.loads((Path(root) / "Command_4/Action_Authoring_Candidates.json").read_text())
    candidate = next((row for row in document["candidates"] if row["record_id"] == record_id), None)
    if candidate is None:
        pytest.skip("selected source record is absent from this retained workspace")
    fields = _provider_authorable_fields(candidate)
    assert fields
    domains = {field: _provider_field_domain(candidate, field) for field in fields}
    for domain in domains.values():
        assert len(domain["options"]) == 1
        for option in domain["option_records"]:
            if option["authority"] != "not_applicable":
                assert option["evidence"] in candidate["full_description"]
                assert option["evidence"].strip()
    effect = domains["effect"]["options"][0]
    if record_id == "TAL_KARMA_SETTLE_MINOR_ACCOUNT":
        assert all(value in effect for value in ("Debt.", "Grace.", "4d8", "Temporary HP"))
        assert "Grace specifies no activation failure" in domains["failure"]["options"][0]
    if record_id == "TAL_ALCHEMY_NUMBING_POWDER":
        assert all(value in effect for value in ("Failed Save:", "Successful Save:", "4d6"))
        assert "4d6" not in domains["failure"]["options"][0]
    altered = deepcopy(candidate)
    altered["full_description"] += "\nUntrusted alteration."
    with pytest.raises(FoundryError) as caught:
        _provider_field_domain(altered, fields[0])
    assert caught.value.code == "COMMAND4_PROVIDER_FIELD_DOMAIN_BINDING_INVALID"


def test_retained_fixed_field_wire_preserves_sources_and_exact_quote_domain(monkeypatch):
    """Wire-only fixture: live replay/source authentication is tested separately."""
    from jsonschema import Draft202012Validator
    from factory_authoring.command4_provider import (
        Command4ProviderAuthoring, canonical_command4_wire_bytes,
    )
    root_value = os.environ.get("CULTIVATION_FACTORY_COMMAND4_FIXTURE_DIR")
    if not root_value:
        pytest.skip("retained Command 4 workspace is unavailable")
    root = Path(root_value)
    document = json.loads((root / "Command_4/Action_Authoring_Candidates.json").read_text())
    rows = document["candidates"]
    authoring = Command4ProviderAuthoring(workspace_root=root)
    # Isolate encoding from the independently tested post-Stage-2 DB proof
    # resolver. No provider, overlay, capsule or approval is produced here.
    monkeypatch.setattr(authoring, "_resolve_workspace", lambda project_id: (root, {"workspace_sha256": "a" * 64}))
    monkeypatch.setattr(authoring, "_load_candidates", lambda root: rows)
    monkeypatch.setattr(authoring, "_locked_source_proofs", lambda root, rows: {row["record_id"]: {"fixture_only": True} for row in rows})
    prepared = authoring.prepare(document["project_id"])
    prompt = json.loads(prepared["prompt_text"])
    assert prompt["schema"].endswith(".v2")
    assert [row[3] for row in prompt["source_records"]["rows"]] == [row["full_description"] for row in rows]
    assert [row[0] for row in prompt["source_records"]["rows"]] == [row["record_id"] for row in rows]
    tokens = [prepared["provider_field_domains_by_record_id"][row["record_id"]][field]["selection_tokens"][0]
              for row in rows for field in _provider_authorable_fields(row)]
    assert tokens == prompt["quote_constants"]
    schema = prepared["response_schema"]["properties"]["quotes"]
    validator = Draft202012Validator(schema)
    assert validator.is_valid(tokens)
    assert not validator.is_valid(tokens[:-1])
    assert not validator.is_valid(list(reversed(tokens)))
    assert not validator.is_valid(["changed", *tokens[1:]])
    wire = canonical_command4_wire_bytes(
        prepared["prompt_text"], system_message=prepared["system_message"],
        settings={"provider_id": "local", "model": "granite-4.2-8b-q4km", "max_output_tokens": 16384, "thinking_mode": "disabled"},
        temperature=0, response_schema=prepared["response_schema"],
        response_schema_name=prepared["response_schema_name"],
    )
    assert len(wire) <= authoring.max_request_bytes
