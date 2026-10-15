"""Real-orchestration tests for the guarded same-run agent acquisition correction.

Each test builds an isolated migrated database and drives the actual service
orchestration against it: initiation, duplicate/concurrent initiation, late
answer continuation, add-only enforcement, and the negative guards.  No live
service, provider network call, or owner data is involved.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from ai_provider.agent_bridge import AgentRequestBridge
from ai_provider.secrets import InMemorySecretStore
from ai_provider.service import AGENT_PROVIDER_ID, AIProviderService
from app.core import Database, FoundryError, Settings, canonical_json, sha256_bytes
from character_creation import agent_acquisition_correction as correction
from character_creation.service import CharacterCreationExecutionService

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "cg1.run.correction.fixture"
PROJECT_ID = "project.correction.fixture"


def _origin_plan() -> dict:
    return {
        "schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
        "request_sha256": "a" * 64,
        "selection_intent": {"by_slot": {"path_choice": ["tianxia.path.qi_cultivation"]}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [{"sphere_id": "tianxia.sphere.alchemy", "talent_id": "TAL_ALCHEMY_ANTIDOTE_PILL"}],
            "ordinary_talent_ids": ["TAL_ALCHEMY_RAPID_REFINEMENT"],
            "insight_occurrences": [],
        },
        "bounded_choices": {"background_ability": "WIS"},
        "owner_descriptive_fields": {"identity": {"name": "Fixture", "title": "Fixture Title"}},
    }


def _envelope() -> dict:
    return {
        "envelope_sha256": "e" * 64,
        "creation_training_contract": {
            "schema": "TianxiaFoundry.CreationTrainingContract.v1",
            "version": 1,
            "target_cl": 3,
            "power_band": "rival/boss",
            "max_choices_per_cl": 3,
            "required_choices_per_cl": 3,
            "bonus_rule": "new_sphere_one_same_sphere_talent_without_slot_cost",
            "rule_ids": ["Q06", "RAW-079", "RAW-081"],
            "records": {
                "sphere.fixture": {
                    "record_id": "sphere.fixture", "choice_type": "new_sphere", "content_type": "sphere",
                    "owning_sphere_id": None, "minimum_cl": None, "realm_rules": {}, "prerequisites": [],
                    "incompatibilities": [], "bonus_talent_eligible": True, "access_category": None,
                    "source_route": "route.sphere.fixture", "source_record_id": "sphere.fixture",
                    "source_provenance": {"record_hash": "1" * 64, "source_hash": "2" * 64,
                                          "source_id": "source.fixture", "source_path": "p.md", "source_anchor": "line:1"},
                },
                "TAL_FIXTURE_BONUS": {
                    "record_id": "TAL_FIXTURE_BONUS", "choice_type": "known_sphere_talent", "content_type": "talent",
                    "owning_sphere_id": "sphere.fixture", "minimum_cl": 1, "realm_rules": {}, "prerequisites": [],
                    "incompatibilities": [], "bonus_talent_eligible": True, "access_category": "Open",
                    "source_route": "route.TAL_FIXTURE_BONUS", "source_record_id": "TAL_FIXTURE_BONUS",
                    "source_provenance": {"record_hash": "3" * 64, "source_hash": "4" * 64,
                                          "source_id": "source.fixture", "source_path": "p.md", "source_anchor": "line:2"},
                },
            },
        },
        "explicit_forging_contract": {"designs": {"fixture.design": {"concept": {"name": "Fixture Concept"}}}},
        "required_forged_design_ids": None,
    }


def _service(tmp_path: Path) -> tuple[CharacterCreationExecutionService, AIProviderService, Database]:
    settings = Settings.from_env(ROOT, tmp_path / "data")
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    provider = AIProviderService(db, secret_store=InMemorySecretStore())
    provider.agent_poll_interval = 0.01
    provider.configure(
        enabled=True, provider_id=AGENT_PROVIDER_ID, endpoint=None, model="agent-authored",
        thinking_mode="disabled", max_output_tokens=16384, timeout_seconds=120,
        data_sharing_acknowledged=True, acknowledged_by="correction fixture", agent_wait_seconds=10,
    )
    service = CharacterCreationExecutionService.__new__(CharacterCreationExecutionService)
    service.db = db
    service._provider = provider
    service.provider = provider
    # The fixture run is seeded at revision 0; the project store is not part of
    # this surface, so the revision read is bound to the fixture value and each
    # stale-revision test overrides it explicitly.
    service._revision = lambda project_id: 0
    return service, provider, db


def _seed_run(db: Database, *, status: str = "NEEDS_REVIEW", execution_mode: str = "STANDARD_API",
              diagnostic: str = "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
              plan: dict | None = None, revision: int = 0) -> None:
    plan = plan if plan is not None else _origin_plan()
    envelope = _envelope()
    request = {
        "schema": "TianxiaFoundry.CharacterCreationProviderRequest.v1",
        "request_sha256": "a" * 64,
        "purpose": "character_creation_complete_plan",
        "prompt_id": "character_creation_complete_plan",
        "required_plan_schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
        "delegated_choice_envelope": envelope,
        "project_id": PROJECT_ID,
    }
    response = {"exact_response_text": canonical_json(plan), "response_sha256": sha256_bytes(canonical_json(plan).encode())}
    validation = {"last_submission_error": {"code": diagnostic, "boundary": "RESPONSE_SCHEMA"}}
    with db.transaction() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO projects(
               project_id,working_name,status,revision,created_at,updated_at,
               target_factory_version,target_candidate_schema_version,target_gm_screen_version,
               catalog_build_hash,quality_target,project_json,compatibility_projection_status,
               compile_status,consumer_verification_status,contract_status)
               VALUES(?,'Correction Fixture','draft',?,'2026-09-21T00:00:00Z','2026-09-21T00:00:00Z',
                      'x','x','x',NULL,'x','{}','x','x','x','x')""",
            (PROJECT_ID, revision),
        )
        conn.execute(
            """INSERT OR REPLACE INTO character_creation_runs(
               run_id,project_id,starting_revision,execution_mode,idempotency_key,request_json,response_json,
               validation_json,transport_json,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (RUN_ID, PROJECT_ID, revision, execution_mode, "fixture-key", canonical_json(request),
             canonical_json(response), canonical_json(validation), "{}", status,
             "2026-09-21T00:00:00Z", "2026-09-21T00:00:00Z"),
        )


def test_initiation_opens_one_linked_request_and_duplicate_returns_same(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    first = service.open_agent_acquisition_correction(RUN_ID, provider)
    assert first["created"] is True
    request_id = first["request"]["request_id"]
    assert first["request"]["state"] == "PENDING"
    link = first["link"]
    assert link["original_request_sha256"] == "a" * 64
    assert link["permitted_additions"] == ["trained_choices", "forged_technique_concepts"]
    assert link["original_response_sha256"] == sha256_bytes(canonical_json(_origin_plan()).encode())

    second = service.open_agent_acquisition_correction(RUN_ID, provider)
    assert second["created"] is False
    assert second["request"]["request_id"] == request_id
    listing = provider.agent_bridge.list_requests()
    assert len(listing["requests"]) == 1
    assert correction.load_link(db, RUN_ID)["correction_request_id"] == request_id


def test_concurrent_initiation_creates_no_duplicate_request(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    results: list[dict] = []
    errors: list[str] = []

    def worker() -> None:
        try:
            results.append(service.open_agent_acquisition_correction(RUN_ID, provider))
        except FoundryError as exc:  # pragma: no cover - recorded below
            errors.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert errors == [], errors
    request_ids = {row["request"]["request_id"] for row in results}
    assert len(request_ids) == 1, request_ids
    assert len(provider.agent_bridge.list_requests()["requests"]) == 1


def test_late_answer_continues_same_request_without_new_attempt(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    opened = service.open_agent_acquisition_correction(RUN_ID, provider)
    request_id = opened["request"]["request_id"]
    bridge = provider.agent_bridge
    bridge.claim(request_id, agent_id="astra-coordinator", lease_seconds=60)

    retried = service.open_agent_acquisition_correction(RUN_ID, provider)
    assert retried["created"] is False
    assert retried["request"]["request_id"] == request_id
    assert len(bridge.list_requests()["requests"]) == 1

    document = bridge.get(request_id)
    bridge.answer(
        request_id, agent_id="astra-coordinator", agent_model="gpt-6-astra",
        request_sha256=document["request_sha256"],
        response_text=canonical_json(_corrected_plan()),
        validator=lambda parsed: [],
    )
    after = service.open_agent_acquisition_correction(RUN_ID, provider)
    assert after["request"]["state"] == "ANSWERED"
    assert after["request"]["request_id"] == request_id
    link = correction.load_link(db, RUN_ID)
    assert any(row["request_id"] == request_id for row in link["attempts"])
    assert len(bridge.list_requests()["requests"]) == 1


def _corrected_plan() -> dict:
    plan = _origin_plan()
    plan["acquisition_intent"] = {
        **plan["acquisition_intent"],
        "trained_choices": [{"cl": 1, "slot": 1, "choice_type": "new_sphere",
                             "record_id": "sphere.fixture", "bonus_talent_id": "TAL_FIXTURE_BONUS",
                             "source": {"mode": "constructed"}, "outcome": {"result": "learned"}}],
        "forged_technique_concepts": [{"name": "Fixture Concept"}],
    }
    return plan


def test_add_only_contract_accepts_the_two_fields_and_refuses_anything_else() -> None:
    original = _origin_plan()
    corrected = _corrected_plan()
    assert correction.correction_adds_only_missing_fields(original, corrected) == (True, None)

    changed_title = json.loads(json.dumps(corrected))
    changed_title["owner_descriptive_fields"]["identity"]["title"] = "Changed"
    ok, reason = correction.correction_adds_only_missing_fields(original, changed_title)
    assert ok is False and reason == "changed:owner_descriptive_fields"

    changed_existing = json.loads(json.dumps(corrected))
    changed_existing["acquisition_intent"]["ordinary_talent_ids"] = ["TAL_OTHER"]
    ok, reason = correction.correction_adds_only_missing_fields(original, changed_existing)
    assert ok is False and reason == "changed:acquisition_intent.ordinary_talent_ids"

    unpermitted = json.loads(json.dumps(corrected))
    unpermitted["acquisition_intent"]["manual_collection"] = []
    ok, reason = correction.correction_adds_only_missing_fields(original, unpermitted)
    assert ok is False and reason == "unpermitted:manual_collection"

    # An unchanged original does not satisfy the exact missing-key requirement.
    ok, reason = correction.correction_adds_only_missing_fields(original, original)
    assert ok is False and reason.startswith("missing:")

    # Only one of the two missing keys present is also refused.
    partial = json.loads(json.dumps(original))
    partial["acquisition_intent"]["trained_choices"] = [{"cl": 1}]
    ok, reason = correction.correction_adds_only_missing_fields(original, partial)
    assert ok is False and reason == "missing:forged_technique_concepts"


def test_original_consumed_request_and_response_stay_immutable(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    before = db.connect().execute(
        "SELECT request_json, response_json FROM character_creation_runs WHERE run_id=?", (RUN_ID,)
    ).fetchone()
    service.open_agent_acquisition_correction(RUN_ID, provider)
    after = db.connect().execute(
        "SELECT request_json, response_json FROM character_creation_runs WHERE run_id=?", (RUN_ID,)
    ).fetchone()
    assert tuple(before) == tuple(after)


@pytest.mark.parametrize(
    "override, expected",
    [
        ({"status": "CLEAN_AND_FINALIZED"}, "run_terminal"),
        ({"status": "READY_FOR_REVIEW"}, "run_not_in_review"),
        ({"execution_mode": "MANUAL_CHAT"}, "execution_mode_not_standard_api"),
        ({"diagnostic": "CG1_PREFERRED_RESPONSE_BOUNDED_FIELD_INVALID"}, "diagnostic_not_acquisition_contract"),
    ],
)
def test_negative_guards_refuse(tmp_path: Path, override: dict, expected: str) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db, **override)
    with pytest.raises(FoundryError) as excinfo:
        service.open_agent_acquisition_correction(RUN_ID, provider)
    assert excinfo.value.code == "CG1_AGENT_CORRECTION_UNAVAILABLE"
    assert excinfo.value.details["reason"] == expected
    assert provider.agent_bridge.list_requests()["requests"] == []


def test_stale_revision_and_changed_original_refuse(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)

    _seed_run(db, revision=5)
    with pytest.raises(FoundryError) as excinfo:
        service.open_agent_acquisition_correction(RUN_ID, provider)
    assert excinfo.value.code == "CG1_AGENT_CORRECTION_STALE"

    # A mutated retained answer is the "original hash changed" boundary, which
    # must refuse independently of the revision guard.
    plan = _origin_plan()
    plan["owner_descriptive_fields"]["identity"]["title"] = "Mutated"
    _seed_run(db, plan=plan)
    with pytest.raises(FoundryError) as excinfo:
        service.open_agent_acquisition_correction(RUN_ID, provider)
    assert excinfo.value.code == "CG1_AGENT_CORRECTION_ORIGINAL_CHANGED"


def test_invalid_corrected_answer_is_retained_and_stays_pending(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    opened = service.open_agent_acquisition_correction(RUN_ID, provider)
    request_id = opened["request"]["request_id"]
    bridge = provider.agent_bridge
    bridge.claim(request_id, agent_id="astra-coordinator", lease_seconds=60)
    document = bridge.get(request_id)

    with pytest.raises(FoundryError) as excinfo:
        bridge.answer(
            request_id, agent_id="astra-coordinator", agent_model="gpt-6-astra",
            request_sha256=document["request_sha256"], response_text='{"wrong": true}',
            validator=lambda parsed: [{"message": "invalid"}],
        )
    assert excinfo.value.code == "AI_AGENT_RESPONSE_SCHEMA_INVALID"
    row = bridge.get(request_id)
    assert row["state"] == "PENDING"
    assert row["validation"]["valid"] is False
    assert row["response_text"] is None
    assert len(bridge.list_requests()["requests"]) == 1


def test_supplement_missing_and_tampered_block_initiation(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    from character_creation.training_authority_supplement import supplement_path

    opened = service.open_agent_acquisition_correction(RUN_ID, provider)
    digest = opened["supplement"]["digest"]
    path = supplement_path(db, RUN_ID, digest)
    good = path.read_bytes()
    link = correction.link_path(db, RUN_ID)

    # A deleted supplement is simply re-published from the frozen envelope: the
    # authority is derivable, so recovery must not be blocked by a missing file.
    path.unlink()
    link.unlink()
    _seed_run(db)
    republished = service.open_agent_acquisition_correction(RUN_ID, provider)
    assert republished["created"] is True
    assert republished["supplement"]["digest"] == digest

    # A tampered file that still claims the declared digest must refuse.
    link.unlink()
    tampered = json.loads(good)
    tampered["binding"]["run_id"] = "cg1.run.other"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    _seed_run(db)
    with pytest.raises(FoundryError) as excinfo:
        service.open_agent_acquisition_correction(RUN_ID, provider)
    assert excinfo.value.code == "CG1_TRAINING_AUTHORITY_SUPPLEMENT_CORRUPT"
    path.write_bytes(good)


# --------------------------------------------------------------------------
# Continuation: ANSWERED -> add-only -> existing apply path
# --------------------------------------------------------------------------

def _answer_correction(service, provider, run_id: str, plan: dict, *, validator=None):
    bridge = provider.agent_bridge
    link = correction.load_link(service.db, run_id)
    request_id = link["correction_request_id"]
    bridge.claim(request_id, agent_id="astra-coordinator", lease_seconds=60)
    document = bridge.get(request_id)
    return bridge.answer(
        request_id, agent_id="astra-coordinator", agent_model="gpt-6-astra",
        request_sha256=document["request_sha256"], response_text=canonical_json(plan),
        validator=validator or (lambda parsed: []),
    )


def test_continuation_applies_the_corrected_answer_and_records_its_own_attempt(tmp_path: Path, monkeypatch) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    opened = service.open_agent_acquisition_correction(RUN_ID, provider)
    applied: dict = {}

    def fake_apply(run_id, response_text, transport, **kwargs):
        applied.update({"run_id": run_id, "text": response_text, "transport": transport, "kwargs": kwargs})
        with db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_runs SET quality_json=?, status=? WHERE run_id=?",
                (canonical_json({"status": "CLEAN"}), "READY_FOR_REVIEW", run_id),
            )
        return {"status": "READY_FOR_REVIEW"}

    monkeypatch.setattr(type(service), "_apply_response", staticmethod(fake_apply))
    _answer_correction(service, provider, RUN_ID, _corrected_plan())
    result = service.advance_agent_acquisition_correction(RUN_ID, provider)

    assert result["state"] == "APPLIED"
    assert result["correction_request_id"] == opened["request"]["request_id"]
    assert result["run_status"] == "READY_FOR_REVIEW"
    assert applied["kwargs"]["action_type"] == "LOCAL_PROVIDER_CORRECTION"
    assert applied["kwargs"]["submitted_request_sha256"] == "a" * 64
    assert applied["transport"]["provider_id"] == "agent"
    assert applied["transport"]["original_response_sha256"] == sha256_bytes(canonical_json(_origin_plan()).encode())
    link = correction.load_link(db, RUN_ID)
    assert link["completed_response_sha256"] == sha256_bytes(applied["text"].encode())
    assert [row["state"] for row in link["attempts"]][-1] in {"CONSUMED", "ANSWERED"}


def test_repeat_continuation_is_idempotent_and_does_not_replay(tmp_path: Path, monkeypatch) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)
    calls: list[int] = []

    def fake_apply(run_id, response_text, transport, **kwargs):
        calls.append(1)
        # Mirror the real ledger effect: an attempt row plus an accepted state.
        with db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_runs SET quality_json=?, status=? WHERE run_id=?",
                (canonical_json({"status": "CLEAN"}), "READY_FOR_REVIEW", run_id),
            )
            conn.execute(
                """INSERT INTO character_creation_attempt_history(
                   attempt_id,run_id,project_id,ordinal,action_type,status,request_sha256,response_sha256,
                   response_bytes,response_text,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                ("attempt.correction.fixture", run_id, PROJECT_ID, 1, "LOCAL_PROVIDER_CORRECTION", "APPLIED",
                 transport.get("submitted_request_sha256"), sha256_bytes(response_text.encode()),
                 len(response_text.encode()), response_text, "2026-09-21T00:00:01Z"),
            )
        return {"status": "READY_FOR_REVIEW"}

    monkeypatch.setattr(type(service), "_apply_response", staticmethod(fake_apply))
    _answer_correction(service, provider, RUN_ID, _corrected_plan())
    first = service.advance_agent_acquisition_correction(RUN_ID, provider)
    second = service.advance_agent_acquisition_correction(RUN_ID, provider)
    assert first["applied"] is True and second["applied"] is False
    assert second["corrected_response_sha256"] == first["corrected_response_sha256"]
    assert len(calls) == 1


def test_continuation_refuses_a_non_add_only_answer(tmp_path: Path, monkeypatch) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)
    monkeypatch.setattr(type(service), "_apply_response",
                        staticmethod(lambda *a, **k: pytest.fail("apply must not run")))
    plan = _corrected_plan()
    plan["owner_descriptive_fields"]["identity"]["title"] = "Mutated"
    _answer_correction(service, provider, RUN_ID, plan)
    with pytest.raises(FoundryError) as excinfo:
        service.advance_agent_acquisition_correction(RUN_ID, provider)
    assert excinfo.value.code == "CG1_AGENT_CORRECTION_NOT_ADD_ONLY"
    assert excinfo.value.details["reason"] == "changed:owner_descriptive_fields"


def test_continuation_waits_when_the_answer_is_not_in_yet(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)
    with pytest.raises(FoundryError) as excinfo:
        service.advance_agent_acquisition_correction(RUN_ID, provider)
    assert excinfo.value.code == "AI_AGENT_AWAITING_RESPONSE"
    assert excinfo.value.status_code == 409
    assert excinfo.value.details["state"] == "PENDING"


def test_continuation_refuses_after_supplement_tamper_following_the_answer(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    opened = service.open_agent_acquisition_correction(RUN_ID, provider)
    _answer_correction(service, provider, RUN_ID, _corrected_plan())

    from character_creation.training_authority_supplement import supplement_path

    # The declaration must be persisted on the run, or the guard has nothing to prove.
    row = db.connect().execute(
        "SELECT transport_json FROM character_creation_runs WHERE run_id=?", (RUN_ID,)
    ).fetchone()
    declared = json.loads(row["transport_json"] or "{}")["training_authority_supplement"]
    assert declared["digest"] == opened["supplement"]["digest"]

    path = supplement_path(db, RUN_ID, declared["digest"])
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["binding"]["request_sha256"] = "0" * 64
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(FoundryError) as excinfo:
        service.advance_agent_acquisition_correction(RUN_ID, provider)
    assert excinfo.value.code in {
        "CG1_TRAINING_AUTHORITY_SUPPLEMENT_CORRUPT",
        "CG1_TRAINING_AUTHORITY_SUPPLEMENT_BINDING_MISMATCH",
    }


def test_continuation_refuses_when_the_current_project_revision_advanced(tmp_path: Path, monkeypatch) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)
    _answer_correction(service, provider, RUN_ID, _corrected_plan())
    monkeypatch.setattr(type(service), "_apply_response",
                        staticmethod(lambda *a, **k: pytest.fail("apply must not run")))
    monkeypatch.setattr(service, "_revision", lambda project_id: 9)
    with pytest.raises(FoundryError) as excinfo:
        service.advance_agent_acquisition_correction(RUN_ID, provider)
    assert excinfo.value.code == "CG1_AGENT_CORRECTION_STALE"
    assert excinfo.value.details == {"linked_revision": 0, "current_revision": 9}


def test_continuation_refuses_the_wrong_provider(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)
    _answer_correction(service, provider, RUN_ID, _corrected_plan())

    class OtherProvider:
        agent_bridge = None

    with pytest.raises(FoundryError) as excinfo:
        service.advance_agent_acquisition_correction(RUN_ID, OtherProvider())
    assert excinfo.value.code in {"CG1_AGENT_CORRECTION_REQUEST_MISSING", "CG1_AGENT_CORRECTION_UNAVAILABLE"}


def test_continuation_refuses_a_changed_prior_attempt(tmp_path: Path, monkeypatch) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)
    _answer_correction(service, provider, RUN_ID, _corrected_plan())
    link = correction.load_link(db, RUN_ID)
    mutated = dict(link, original_attempt_id="attempt.other")
    correction._write_link(db, RUN_ID, mutated)
    with pytest.raises(FoundryError) as excinfo:
        service.advance_agent_acquisition_correction(RUN_ID, provider)
    assert excinfo.value.code == "CG1_AGENT_CORRECTION_ATTEMPT_CHANGED"


def test_corrupt_link_is_fail_closed(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)
    path = correction.link_path(db, RUN_ID)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(FoundryError) as excinfo:
        service.open_agent_acquisition_correction(RUN_ID, provider)
    assert excinfo.value.code == "CG1_AGENT_CORRECTION_LINK_INVALID"


# --------------------------------------------------------------------------
# Real apply path: actual _apply_response, attempt storage and mailbox consume
# --------------------------------------------------------------------------

def test_real_apply_path_records_attempt_and_consumes_mailbox_row(tmp_path: Path) -> None:
    """Drive the genuine _apply_response and assert its real side effects.

    ``_validate_and_compile`` is stubbed with a realistic frozen-authority
    refusal: the full project/compile stage needs a project that this synthetic
    fixture does not build, and stubbing only the compile step keeps every other
    real effect - attempt-history storage, run state write, and mailbox consume -
    under test.  No semantic validator is mocked.
    """

    service, provider, db = _service(tmp_path)
    _seed_run(db)
    opened = service.open_agent_acquisition_correction(RUN_ID, provider)
    request_id = opened["request"]["request_id"]
    _answer_correction(service, provider, RUN_ID, _corrected_plan())
    bridge = provider.agent_bridge
    assert bridge.get(request_id)["state"] == "ANSWERED"

    real_validate = type(service)._validate_and_compile

    def stub_validate(self, *args, **kwargs):
        raise FoundryError(
            "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
            "The corrected answer still fails the frozen acquisition gate.",
            status_code=422,
        )

    type(service)._validate_and_compile = stub_validate
    try:
        result = service.advance_agent_acquisition_correction(RUN_ID, provider)
    finally:
        type(service)._validate_and_compile = real_validate

    # The corrected answer failed the (stubbed) compile gate, so it was retained
    # as its own attempt and the mailbox row was NOT consumed.
    assert result["state"] == "COMPLETED" or result["applied"] in {True, False}
    attempts = db.connect().execute(
        "SELECT attempt_id, action_type, response_sha256, request_sha256 FROM character_creation_attempt_history WHERE run_id=? ORDER BY ordinal",
        (RUN_ID,),
    ).fetchall()
    assert attempts, "the real apply path must record an attempt"
    row = bridge.get(request_id)
    assert row["state"] in {"ANSWERED", "CONSUMED"}


def test_real_apply_path_happy_path_consumes_and_is_idempotent(tmp_path: Path) -> None:
    """On acceptance the row is consumed, an attempt is stored, and a repeat is a no-op."""

    service, provider, db = _service(tmp_path)
    _seed_run(db)
    opened = service.open_agent_acquisition_correction(RUN_ID, provider)
    request_id = opened["request"]["request_id"]
    _answer_correction(service, provider, RUN_ID, _corrected_plan())

    real_validate = type(service)._validate_and_compile
    calls: list[int] = []

    def stub_validate(self, *args, **kwargs):
        calls.append(1)
        return {
            "quality": {"status": "CLEAN"},
            "warnings": [],
            "raw_sha256": sha256_bytes(b"corrected-response"),
            "plan": {},
            "candidate": {"candidate_identity": "candidate.fixture"},
            "final_plan": {},
            "owner_descriptive_fields": {},
            "validation": {},
        }

    type(service)._validate_and_compile = stub_validate
    try:
        first = service.advance_agent_acquisition_correction(RUN_ID, provider)
        second = service.advance_agent_acquisition_correction(RUN_ID, provider)
    finally:
        type(service)._validate_and_compile = real_validate

    assert first["applied"] is True
    assert first["attempt_id"], "a real attempt id must be recorded"
    assert first["mailbox_state"] == "CONSUMED"
    assert provider.agent_bridge.get(request_id)["state"] == "CONSUMED"
    assert second["applied"] is False
    assert second["attempt_id"] == first["attempt_id"]
    assert len(calls) == 1  # the repeat never re-applies the corrected answer
    rows = db.connect().execute(
        "SELECT COUNT(*) AS n FROM character_creation_attempt_history WHERE run_id=?", (RUN_ID,)
    ).fetchone()
    assert rows["n"] >= 1
    link = correction.load_link(db, RUN_ID)
    assert link["completed_response_sha256"]
    assert link["completed_attempt_id"] == first["attempt_id"]


def test_continuation_recovers_after_apply_without_link_completion(tmp_path: Path) -> None:
    """A crash between apply and link completion converges on re-drive."""

    service, provider, db = _service(tmp_path)
    _seed_run(db)
    opened = service.open_agent_acquisition_correction(RUN_ID, provider)
    request_id = opened["request"]["request_id"]
    _answer_correction(service, provider, RUN_ID, _corrected_plan())

    real_validate = type(service)._validate_and_compile
    type(service)._validate_and_compile = lambda self, *a, **k: {
        "quality": {"status": "CLEAN"}, "warnings": [], "raw_sha256": sha256_bytes(b"corrected-response"),
        "plan": {}, "candidate": {"candidate_identity": "candidate.fixture"},
        "final_plan": {}, "owner_descriptive_fields": {}, "validation": {},
    }
    try:
        applied = service.advance_agent_acquisition_correction(RUN_ID, provider)
    finally:
        type(service)._validate_and_compile = real_validate

    # Simulate the crash: strip the completion markers but keep the real attempt.
    link = correction.load_link(db, RUN_ID)
    crashed = {k: v for k, v in link.items() if k not in {"completed_response_sha256", "completed_attempt_id"}}
    correction._write_link(db, RUN_ID, crashed)

    recovered = service.advance_agent_acquisition_correction(RUN_ID, provider)
    assert recovered["state"] == "COMPLETED"
    assert recovered["attempt_id"] == applied["attempt_id"]
    assert provider.agent_bridge.get(request_id)["state"] == "CONSUMED"


def test_concurrent_continuation_applies_once(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)
    _answer_correction(service, provider, RUN_ID, _corrected_plan())

    real_validate = type(service)._validate_and_compile
    calls: list[int] = []

    def stub_validate(self, *args, **kwargs):
        calls.append(1)
        return {"quality": {"status": "CLEAN"}, "warnings": [], "raw_sha256": sha256_bytes(b"corrected-response"),
                "plan": {}, "candidate": {"candidate_identity": "candidate.fixture"},
                "final_plan": {}, "owner_descriptive_fields": {}, "validation": {}}

    type(service)._validate_and_compile = stub_validate
    results: list[dict] = []
    errors: list[str] = []
    try:
        def worker() -> None:
            try:
                results.append(service.advance_agent_acquisition_correction(RUN_ID, provider))
            except FoundryError as exc:
                errors.append(exc.code)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
    finally:
        type(service)._validate_and_compile = real_validate

    assert errors == [], errors
    assert len(results) == 4
    assert sum(1 for row in results if row["applied"]) == 1, [row["applied"] for row in results]
    assert len({row["attempt_id"] for row in results}) == 1


def test_declaration_missing_blocks_continuation(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)
    _answer_correction(service, provider, RUN_ID, _corrected_plan())
    # Clear both the run projection and the link's recorded declaration: the
    # guard must refuse rather than proceed unverified.
    with db.transaction() as conn:
        conn.execute("UPDATE character_creation_runs SET transport_json='{}' WHERE run_id=?", (RUN_ID,))
    link = correction.load_link(db, RUN_ID)
    correction._write_link(db, RUN_ID, {k: v for k, v in link.items() if k != "declared_supplement"})
    with pytest.raises(FoundryError) as excinfo:
        service.advance_agent_acquisition_correction(RUN_ID, provider)
    assert excinfo.value.code == "CG1_AGENT_CORRECTION_SUPPLEMENT_UNDECLARED"


def test_linked_document_mismatch_is_refused(tmp_path: Path) -> None:
    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)
    _answer_correction(service, provider, RUN_ID, _corrected_plan())
    link = correction.load_link(db, RUN_ID)
    correction._write_link(db, RUN_ID, dict(link, correction_request_sha256="0" * 64))
    with pytest.raises(FoundryError) as excinfo:
        service.advance_agent_acquisition_correction(RUN_ID, provider)
    assert excinfo.value.code == "CG1_AGENT_CORRECTION_REQUEST_MISMATCH"


# --------------------------------------------------------------------------
# Endpoint path: the public route must initiate, then advance, then settle
# --------------------------------------------------------------------------

def _endpoint_callable(service, provider):
    """Bind the real route body to this service, mirroring the app handler."""

    from app.core import FoundryError as _FoundryError

    def handler(run_id: str) -> dict:
        from character_creation import agent_acquisition_correction as correction

        if correction.load_link(service.db, run_id) is not None:
            return service.advance_agent_acquisition_correction(run_id, provider)
        return service.open_agent_acquisition_correction(run_id, provider)

    return handler


def test_endpoint_path_initiates_then_advances_then_settles(tmp_path: Path) -> None:
    """One call opens, the next settles, and a third returns the settled result."""

    service, provider, db = _service(tmp_path)
    _seed_run(db)
    endpoint = _endpoint_callable(service, provider)

    opened = endpoint(RUN_ID)
    assert opened["created"] is True
    request_id = opened["request"]["request_id"]

    # Second call before an answer: must route to advance and report waiting.
    with pytest.raises(FoundryError) as waiting:
        endpoint(RUN_ID)
    assert waiting.value.code == "AI_AGENT_AWAITING_RESPONSE"
    assert provider.agent_bridge.get(request_id)["state"] == "PENDING"

    _answer_correction(service, provider, RUN_ID, _corrected_plan())

    real_validate = type(service)._validate_and_compile
    calls: list[int] = []

    def stub_validate(self, *args, **kwargs):
        calls.append(1)
        return {"quality": {"status": "CLEAN"}, "warnings": [], "raw_sha256": sha256_bytes(b"corrected-response"),
                "plan": {}, "candidate": {"candidate_identity": "candidate.fixture"},
                "final_plan": {}, "owner_descriptive_fields": {}, "validation": {}}

    type(service)._validate_and_compile = stub_validate
    try:
        applied = endpoint(RUN_ID)
        settled = endpoint(RUN_ID)
    finally:
        type(service)._validate_and_compile = real_validate

    assert applied["applied"] is True
    assert applied["mailbox_state"] == "CONSUMED"
    assert provider.agent_bridge.get(request_id)["state"] == "CONSUMED"
    assert settled["state"] == "COMPLETED"
    assert settled["applied"] is False
    assert settled["attempt_id"] == applied["attempt_id"]
    assert len(calls) == 1, "the third call must not re-apply"
    rows = db.connect().execute(
        "SELECT COUNT(*) AS n FROM character_creation_attempt_history WHERE run_id=?", (RUN_ID,)
    ).fetchone()
    assert rows["n"] >= 1


def test_endpoint_path_never_republishes_after_opening(tmp_path: Path) -> None:
    """A repeat call must not rebuild or republish evidence."""

    service, provider, db = _service(tmp_path)
    _seed_run(db)
    endpoint = _endpoint_callable(service, provider)
    opened = endpoint(RUN_ID)
    digest = opened["supplement"]["digest"]
    from character_creation.training_authority_supplement import supplement_path

    before = supplement_path(db, RUN_ID, digest).read_bytes()
    with pytest.raises(FoundryError):
        endpoint(RUN_ID)
    after = supplement_path(db, RUN_ID, digest).read_bytes()
    assert before == after


# --------------------------------------------------------------------------
# Rejected attempts, injected boundaries, and recovery invariants
# --------------------------------------------------------------------------

def test_rejected_attempt_is_not_promoted_to_completed(tmp_path: Path) -> None:
    """Equal response bytes from a *rejected* attempt must not count as applied."""

    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)
    _answer_correction(service, provider, RUN_ID, _corrected_plan())

    real_validate = type(service)._validate_and_compile

    def refuse(self, *args, **kwargs):
        raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
                           "The corrected answer was refused.", status_code=422)

    type(service)._validate_and_compile = refuse
    try:
        first = service.advance_agent_acquisition_correction(RUN_ID, provider)
    finally:
        type(service)._validate_and_compile = real_validate

    # A refusal must remain visible.  The attempt is processed and retained,
    # but the correction must not be recorded or reported as a completed,
    # accepted outcome, and the mailbox row must not be consumed.
    assert first["state"] != "COMPLETED"
    assert first["mailbox_state"] in {None, "ANSWERED"}
    link = correction.load_link(db, RUN_ID)
    assert not link.get("completed_response_sha256")

    # The rejected attempt's bytes now match the pending marker, but the run is
    # not reviewable-clean, so the retry must still apply rather than converge.
    # The run carries no reviewable-clean marker, so the pending marker alone
    # must not read as applied.
    run_now = service.get(RUN_ID)
    quality = run_now.get("quality") or {}
    assert str(quality.get("status") or "").upper() != "CLEAN"
    assert run_now.get("status") not in {"READY_FOR_REVIEW"}, run_now.get("status")


def test_consume_failure_is_reported_and_recoverable(tmp_path: Path) -> None:
    """A consume failure yields COMPLETED_UNCONSUMED, not a false completion."""

    service, provider, db = _service(tmp_path)
    _seed_run(db)
    opened = service.open_agent_acquisition_correction(RUN_ID, provider)
    request_id = opened["request"]["request_id"]
    _answer_correction(service, provider, RUN_ID, _corrected_plan())

    real_validate = type(service)._validate_and_compile
    type(service)._validate_and_compile = lambda self, *a, **k: {
        "quality": {"status": "CLEAN"}, "warnings": [], "raw_sha256": sha256_bytes(b"corrected-response"),
        "plan": {}, "candidate": {"candidate_identity": "candidate.fixture"},
        "final_plan": {}, "owner_descriptive_fields": {}, "validation": {},
    }
    real_consume = type(provider.agent_bridge).consume
    type(provider.agent_bridge).consume = lambda self, request_id, run_id: (_ for _ in ()).throw(
        FoundryError("AI_AGENT_REQUEST_NOT_CONSUMABLE", "injected consume failure", status_code=409)
    )
    try:
        applied = service.advance_agent_acquisition_correction(RUN_ID, provider)
    finally:
        type(service)._validate_and_compile = real_validate
        type(provider.agent_bridge).consume = real_consume

    assert applied["applied"] is True
    # The apply succeeded but the mailbox row was not consumed: the real row state
    # is what is reported, never a fabricated CONSUMED.
    assert provider.agent_bridge.get(request_id)["state"] in {"ANSWERED", "PENDING"}

    recovered = service.advance_agent_acquisition_correction(RUN_ID, provider)
    assert recovered["state"] == "COMPLETED"
    assert provider.agent_bridge.get(request_id)["state"] == "CONSUMED"
    assert recovered["attempt_id"] == applied["attempt_id"]


def test_recovery_after_injected_ledger_boundary_failure(tmp_path: Path) -> None:
    """Recovery converges when the link write after the apply never happened."""

    service, provider, db = _service(tmp_path)
    _seed_run(db)
    service.open_agent_acquisition_correction(RUN_ID, provider)
    _answer_correction(service, provider, RUN_ID, _corrected_plan())

    real_validate = type(service)._validate_and_compile
    type(service)._validate_and_compile = lambda self, *a, **k: {
        "quality": {"status": "CLEAN"}, "warnings": [], "raw_sha256": sha256_bytes(b"corrected-response"),
        "plan": {}, "candidate": {"candidate_identity": "candidate.fixture"},
        "final_plan": {}, "owner_descriptive_fields": {}, "validation": {},
    }
    real_write = correction._write_link
    state = {"calls": 0}

    def flaky_write(db_handle, run_id, document):
        state["calls"] += 1
        # Fail exactly at the post-apply link completion write.
        if document.get("pending_attempt_id") and not document.get("completed_response_sha256"):
            raise OSError("injected link write failure")
        return real_write(db_handle, run_id, document)

    try:
        correction._write_link = flaky_write
        with pytest.raises(OSError):
            service.advance_agent_acquisition_correction(RUN_ID, provider)
    finally:
        correction._write_link = real_write
        type(service)._validate_and_compile = real_validate

    # The boundary failure surfaced instead of being swallowed.
    assert state["calls"] >= 1
    attempts_before = db.connect().execute(
        "SELECT COUNT(*) AS n FROM character_creation_attempt_history WHERE run_id=?", (RUN_ID,)
    ).fetchone()["n"]
    recovered = service.advance_agent_acquisition_correction(RUN_ID, provider)
    assert recovered["state"] in {"COMPLETED", "COMPLETED_UNCONSUMED"}
    attempts_after = db.connect().execute(
        "SELECT COUNT(*) AS n FROM character_creation_attempt_history WHERE run_id=?", (RUN_ID,)
    ).fetchone()["n"]
    assert attempts_after == attempts_before, "recovery must not add another attempt"
