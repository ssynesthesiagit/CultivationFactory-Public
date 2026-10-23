"""Immortal Arts are refined by a Refinement Check, never granted for free.

Opening rules 4-6: Refinement Check = d20 + PB + Path ability modifier vs the
Refinement DC after 5 days x Mandate Complexity of research and 250 gp x MC^2
of materials; failure loses half and leaves the Art unstabilized.
"""
from __future__ import annotations

import pytest

from app.core import FoundryError
from character_creation.constructed_arts.immortal_art import (
    IMMORTAL_ART_REFINEMENT_SCHEMA,
    immortal_art_refinement_authority,
    validate_immortal_art_refinement,
)
from character_creation.service import CharacterCreationExecutionService

NONCE = "n" * 48
RUN = {
    "project_id": "project.test",
    "request": {"server_owned_authority": {"manual_collection": {"authority_version": "server_owned_pre_provider.v2", "nonce": NONCE}}},
}
# Mandate Complexity 4 -> DC 17 (10 + 4 + 1 sphere + 1 aspect + escalation 1), 20 research days, 4000 gp.
ART = {
    "cl_created": 20, "pb_at_creation": 6, "refinement_dc": 17, "research_days": 20, "material_cost_gp": 4000,
    "path_id": "tianxia.path.body_refining", "key_ability": "CON",
    "construction": {"request": {"key_ability_modifier": 1}},
}
RECORD = {"record_id": "tianxia.constructed.immortal_art.test", "record_hash": "r" * 64}
KW = dict(
    event_id="event-1", record_id=RECORD["record_id"], record_hash=RECORD["record_hash"], cl=20,
    path_id=ART["path_id"], key_ability="CON", ability_modifier=1, pb=6, dc=17, research_days=20, material_cost_gp=4000,
)


def _build(run=RUN, art=ART, index=1):
    return CharacterCreationExecutionService._immortal_art_creation_parameters(run, art, RECORD, index=index, intent_hash="i" * 64)


def test_builder_derives_a_seeded_check_chain_that_ends_in_success():
    proof = _build()
    assert proof["schema"] == IMMORTAL_ART_REFINEMENT_SCHEMA
    assert proof["authority"] == immortal_art_refinement_authority()
    assert proof["research"] == {"required_days": 20, "meaningful_training_hours": 160, "completed": True}
    assert proof["materials"] == {"required_gp": 4000, "paid_gp": 4000, "payment_complete": True}
    assert _build() == proof, "the same nonce and identity reproduce the same history"
    attempts = proof["attempts"]
    assert 1 <= len(attempts) <= 8
    for attempt in attempts[:-1]:
        assert attempt["check_die_result"] + 6 + 1 < 17
        assert attempt["research_time_hours"] == 80 and attempt["materials_paid_gp"] == 2000
    last = attempts[-1]
    assert last["check_die_result"] + 6 + 1 >= 17
    assert last["research_time_hours"] == 160 and last["materials_paid_gp"] == 4000
    assert [a["retry_of_attempt_id"] for a in attempts] == [None] + [a["attempt_id"] for a in attempts[:-1]]

    validated = validate_immortal_art_refinement(proof, require_authority_binding=True, **KW)
    assert [a["result"] for a in validated["attempts"]] == ["failure"] * (len(attempts) - 1) + ["success"]
    assert validated["attempts"][-1]["computed_check_total"] == last["check_die_result"] + 7
    assert validated["completion"]["event_id"] == "event-1"


def test_builder_is_legacy_silent_without_the_server_nonce_marker():
    assert _build(run={"project_id": "project.test"}) is None


def test_builder_refuses_an_art_without_published_requirements():
    with pytest.raises(FoundryError) as caught:
        _build(art={**ART, "refinement_dc": None})
    assert caught.value.code == "CG1_IMMORTAL_ART_REFINEMENT_AUTHORITY_INVALID"


def _proof(attempts):
    return {
        "schema": IMMORTAL_ART_REFINEMENT_SCHEMA, "authority": immortal_art_refinement_authority(),
        "mode": "creator_generated_history", "scope": "initial_creation", "observed_play": False, "live_currency_debit": False,
        "target_cl": 20, "record_id": RECORD["record_id"], "record_hash": RECORD["record_hash"],
        "path_id": ART["path_id"], "key_ability": "CON",
        "research": {"required_days": 20, "meaningful_training_hours": 160, "completed": True},
        "materials": {"required_gp": 4000, "paid_gp": 4000, "payment_complete": True},
        "completion": {"mode": "creator_generated_history", "scope": "initial_creation", "record_id": RECORD["record_id"], "record_hash": RECORD["record_hash"], "research_complete": True, "payment_complete": True},
        "attempts": attempts,
    }


def test_validator_derives_results_and_keeps_the_failed_retry():
    failed = {"attempt_id": "a1", "retry_of_attempt_id": None, "check_die_result": 5, "research_time_hours": 80, "materials_paid_gp": 2000}
    success = {"attempt_id": "a2", "retry_of_attempt_id": "a1", "check_die_result": 12, "research_time_hours": 160, "materials_paid_gp": 4000}
    result = validate_immortal_art_refinement(_proof([failed, success]), **KW)
    assert [a["result"] for a in result["attempts"]] == ["failure", "success"]
    assert result["attempts"][0]["computed_check_total"] == 12 and result["attempts"][1]["margin"] == 2


@pytest.mark.parametrize("mutation", [
    "final_attempt_failed", "authored_dc", "authored_result_field", "wrong_record_hash",
    "full_payment_on_failure", "broken_retry_chain", "success_not_last", "die_out_of_range",
])
def test_validator_rejects_authored_or_unstabilized_refinement(mutation):
    failed = {"attempt_id": "a1", "retry_of_attempt_id": None, "check_die_result": 5, "research_time_hours": 80, "materials_paid_gp": 2000}
    success = {"attempt_id": "a2", "retry_of_attempt_id": "a1", "check_die_result": 12, "research_time_hours": 160, "materials_paid_gp": 4000}
    proof = _proof([failed, success])
    if mutation == "final_attempt_failed":
        proof["attempts"] = [failed]
    elif mutation == "authored_dc":
        proof["dc"] = 5
    elif mutation == "authored_result_field":
        proof["attempts"][1]["result"] = "success"
    elif mutation == "wrong_record_hash":
        proof["record_hash"] = "s" * 64
    elif mutation == "full_payment_on_failure":
        proof["attempts"][0]["materials_paid_gp"] = 4000
    elif mutation == "broken_retry_chain":
        proof["attempts"][1]["retry_of_attempt_id"] = None
    elif mutation == "success_not_last":
        proof["attempts"] = [success, failed]
    elif mutation == "die_out_of_range":
        proof["attempts"][1]["check_die_result"] = 21
    with pytest.raises(FoundryError) as err:
        validate_immortal_art_refinement(proof, **KW)
    assert err.value.code == "IMMORTAL_ART_REFINEMENT_INVALID"


def test_validator_requires_the_server_authority_binding_for_new_creator_proofs():
    success = {"attempt_id": "a1", "retry_of_attempt_id": None, "check_die_result": 12, "research_time_hours": 160, "materials_paid_gp": 4000}
    proof = _proof([success])
    assert validate_immortal_art_refinement(proof, **KW, require_authority_binding=True)["attempts"][0]["result"] == "success"
    unbound = {k: v for k, v in proof.items() if k != "authority"}
    assert validate_immortal_art_refinement(unbound, **KW)["attempts"][0]["result"] == "success"
    with pytest.raises(FoundryError):
        validate_immortal_art_refinement(unbound, **KW, require_authority_binding=True)
    with pytest.raises(FoundryError):
        validate_immortal_art_refinement({**proof, "authority": {**proof["authority"], "issuer": "someone-else"}}, **KW)


# --- Count ceiling: Core Rules Reference §17.6 / opening rules Step 7 (owner ruling 2026-09-11) ---

def test_count_ceiling_follows_the_sealed_mandate_thresholds():
    import json
    from pathlib import Path

    from character_creation.constructed_arts.immortal_art import (
        IMMORTAL_ART_COUNT_CEILING_BY_TIER,
        IMMORTAL_ART_FILENAME,
        immortal_art_count_ceiling,
        immortal_art_tier_for_cl,
    )

    authority = json.loads((Path(__file__).resolve().parents[1] / "authority" / IMMORTAL_ART_FILENAME).read_text(encoding="utf-8"))
    thresholds = {row["realm"]: row["mandate_threshold"] for row in authority["shared_rules"]["realm_thresholds"]}
    assert IMMORTAL_ART_COUNT_CEILING_BY_TIER == {"Nascent Soul": thresholds["Nascent Soul"], "Immortal": thresholds["Immortal"]}
    assert IMMORTAL_ART_COUNT_CEILING_BY_TIER == {"Nascent Soul": 3, "Immortal": 6}
    assert [immortal_art_tier_for_cl(cl) for cl in (14, 15, 19, 20)] == [None, "Nascent Soul", "Nascent Soul", "Immortal"]
    assert [immortal_art_count_ceiling(cl) for cl in (14, 15, 19, 20)] == [0, 3, 3, 6]
    assert immortal_art_tier_for_cl(True) is None and immortal_art_tier_for_cl("20") is None




# --- The closed Stage 2 proposal schema admits the generated proof (and nothing extra) ---

def test_generated_refinement_proof_validates_at_the_proposal_schema_boundary():
    import json
    from pathlib import Path

    import jsonschema

    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "Stage2_Advancement_Proposal_v2.schema.json").read_text(encoding="utf-8"))
    record = {"record_id": RECORD["record_id"], "record_hash": "a" * 64}
    proof = CharacterCreationExecutionService._immortal_art_creation_parameters(RUN, ART, record, index=1, intent_hash="i" * 64)
    proposal = {
        "schema_version": "TianxiaFoundry.Stage2AdvancementProposal.v2", "project_id": "project.test",
        "expected_project_revision": 0, "expected_content_lock_hash": "a" * 64, "target_cl": 20, "idempotency_key": "k",
        "choices": [{"kind": "immortal_art_creation", "effective_cl": 20, "record_id": RECORD["record_id"],
                     "acquisition_channel": "immortal-art-creation", "parameters": {"immortal_refinement": proof}}],
    }
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(proposal)) == []
    forged = json.loads(json.dumps(proposal))
    forged["choices"][0]["parameters"]["immortal_refinement"]["attempts"][0]["extra"] = 1
    assert any("extra" in error.message for error in validator.iter_errors(forged))
    forged = json.loads(json.dumps(proposal))
    forged["choices"][0]["parameters"]["immortal_refinement"]["observed_play"] = True
    assert list(validator.iter_errors(forged)) != []
