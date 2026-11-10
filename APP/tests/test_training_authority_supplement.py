"""Frozen training-authority supplement: exactness, atomic publish, guarded reads.

Synthetic frozen-envelope fixtures only; no live database, catalog or provider
is touched and no owner data is copied into the repository.
"""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings
from character_creation.training_authority_supplement import (
    CONSTRUCTED_OUTCOME_TEMPLATE,
    CONSTRUCTED_SOURCE_TEMPLATE,
    SUPPLEMENT_SCHEMA,
    build_supplement,
    load_supplement,
    publish_supplement,
    supplement_digest,
    supplement_path,
)
from creation_training_authority import constructed_outcome, constructed_source

PROVENANCE = {
    "record_id": "TAL_FIXTURE_BONUS",
    "record_hash": "a" * 64,
    "source_hash": "b" * 64,
    "source_id": "source.fixture",
    "source_path": "09_RULES/Source_Text/fixture.md",
    "source_anchor": "line:1:column:1",
    "extra_field": {"nested": [1, 2, 3]},
}


def _route(record_id: str, **overrides) -> dict:
    row = {
        "record_id": record_id,
        "choice_type": "known_sphere_talent",
        "content_type": "talent",
        "owning_sphere_id": "sphere.fixture",
        "minimum_cl": 1,
        "realm_rules": {},
        "prerequisites": [],
        "incompatibilities": [],
        "bonus_talent_eligible": True,
        "access_category": "Open",
        "source_route": f"route.{record_id}",
        "source_record_id": record_id,
        "source_provenance": dict(PROVENANCE),
    }
    row.update(overrides)
    return row


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
                "sphere.fixture": _route(
                    "sphere.fixture", choice_type="new_sphere", content_type="sphere",
                    owning_sphere_id=None, minimum_cl=None, access_category=None,
                ),
                "TAL_FIXTURE_BONUS": _route("TAL_FIXTURE_BONUS"),
                "TAL_FIXTURE_GATED": _route(
                    "TAL_FIXTURE_GATED",
                    minimum_cl=2,
                    realm_rules={"minimum_cl": 2, "allowed_cls": [2, 3]},
                    prerequisites=[
                        {"kind": "talent", "operator": "requires", "target_id": "TAL_FIXTURE_BONUS"},
                        "TAL_FIXTURE_PLAIN_STRING_RELATION",
                    ],
                    incompatibilities=[{"record_id": "TAL_FIXTURE_BONUS"}],
                ),
            },
        },
        "explicit_forging_contract": {"designs": {"fixture.design": {"concept": {"name": "Fixture", "extra": [1]}}}},
        "required_forged_design_ids": ["fixture.design"],
    }


def _db(tmp_path: Path) -> Database:
    settings = Settings.from_env(Path(__file__).resolve().parents[1], tmp_path / "data")
    settings.ensure_dirs()
    return Database(settings)


def _publish(tmp_path: Path, run_id: str = "cg1.run.fixture", request_sha: str = "f" * 64):
    db = _db(tmp_path)
    envelope = _envelope()
    binding = publish_supplement(db, run_id, envelope, request_sha256=request_sha)
    return db, envelope, binding, request_sha


def test_supplement_is_an_exact_copy_of_the_frozen_contract(tmp_path: Path) -> None:
    """No normalization: every field, shape and oddity survives byte-for-byte."""

    _db_handle, envelope, binding, request_sha = _publish(tmp_path)
    document = load_supplement(_db_handle, "cg1.run.fixture", binding["digest"], expected_request_sha256=request_sha)
    assert document["schema"] == SUPPLEMENT_SCHEMA
    assert document["creation_training_contract"] == envelope["creation_training_contract"]
    assert document["explicit_forging_contract"] == envelope["explicit_forging_contract"]
    assert document["required_forged_design_ids"] == ["fixture.design"]
    assert document["binding"]["request_sha256"] == request_sha
    assert document["binding"]["envelope_sha256"] == envelope["envelope_sha256"]
    assert binding["row_count"] == 3 and binding["complete"] is True

    # The awkward shapes the bespoke encoder used to lose are all present.
    gated = document["creation_training_contract"]["records"]["TAL_FIXTURE_GATED"]
    assert gated["prerequisites"][1] == "TAL_FIXTURE_PLAIN_STRING_RELATION"
    assert gated["incompatibilities"] == [{"record_id": "TAL_FIXTURE_BONUS"}]
    assert gated["realm_rules"] == {"minimum_cl": 2, "allowed_cls": [2, 3]}
    bonus = document["creation_training_contract"]["records"]["TAL_FIXTURE_BONUS"]
    assert bonus["source_provenance"]["record_id"] == "TAL_FIXTURE_BONUS"
    assert bonus["source_provenance"]["extra_field"] == {"nested": [1, 2, 3]}


def test_constructed_source_and_outcome_templates_match_the_authority(tmp_path: Path) -> None:
    """The published templates are exactly what the authority builds."""

    document = build_supplement("cg1.run.fixture", _envelope(), request_sha256="f" * 64)
    templates = document["wire_templates"]
    outcome = constructed_outcome()
    for key, value in outcome.items():
        assert templates["constructed_outcome_template"][key] == value
    route = _envelope()["creation_training_contract"]["records"]["TAL_FIXTURE_BONUS"]
    source = constructed_source(route, choice_type="known_sphere_talent")
    template = templates["constructed_source_template"]
    assert template["mode"] == source["mode"] == "constructed"
    assert template["observed_play"] == source["observed_play"] is False
    assert template["rule_ids"][:2] == source["rule_ids"][:2] == ["Q06", "RAW-079"]
    assert template["source_record_id"] == "<row.source_record_id, copied exactly>"
    assert "bonus_talent_id" in templates["trained_choice_row"]
    assert CONSTRUCTED_OUTCOME_TEMPLATE["slot_cost"] == 1
    assert CONSTRUCTED_SOURCE_TEMPLATE["schema"]


def test_malformed_frozen_contract_is_refused_not_partially_published(tmp_path: Path) -> None:
    db = _db(tmp_path)
    broken = _envelope()
    broken["creation_training_contract"]["records"]["BROKEN"] = "not-an-object"
    with pytest.raises(FoundryError) as excinfo:
        publish_supplement(db, "cg1.run.fixture", broken, request_sha256="f" * 64)
    assert excinfo.value.code == "CG1_TRAINING_AUTHORITY_SUPPLEMENT_SOURCE_INVALID"
    empty = {"creation_training_contract": {"records": {}}}
    with pytest.raises(FoundryError) as excinfo:
        publish_supplement(db, "cg1.run.fixture", empty, request_sha256="f" * 64)
    assert excinfo.value.code == "CG1_TRAINING_AUTHORITY_SUPPLEMENT_SOURCE_INVALID"


def test_publish_is_write_once_atomic_and_concurrency_safe(tmp_path: Path) -> None:
    """Repeated and simultaneous publication yields one immutable document."""

    db, envelope, binding, _request_sha = _publish(tmp_path)
    path = supplement_path(db, "cg1.run.fixture", binding["digest"])
    before = path.read_bytes()
    again = publish_supplement(db, "cg1.run.fixture", envelope, request_sha256="f" * 64)
    assert again["digest"] == binding["digest"]
    assert path.read_bytes() == before
    assert list(path.parent.glob("*.tmp")) == []

    # A second publication race must not corrupt or rewrite the file.
    def worker(target: str, digest: str) -> None:
        import json as _json

        from app.core import Database as _Db, Settings as _Settings
        from character_creation.training_authority_supplement import publish_supplement as _publish

        settings = _Settings.from_env(str(Path(__file__).resolve().parents[1]), Path(target))
        settings.ensure_dirs()
        db_handle = _Db(settings)
        _publish(db_handle, "cg1.run.fixture", _json.loads(Path(target, "envelope.json").read_text()), request_sha256="f" * 64)

    envelope_path = Path(tmp_path, "envelope.json")
    envelope_path.write_text(json.dumps(envelope))
    procs = [
        multiprocessing.Process(target=worker, args=(str(tmp_path / "data"), binding["digest"]))
        for _ in range(3)
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=60)
    assert path.read_bytes() == before
    document = load_supplement(db, "cg1.run.fixture", binding["digest"], expected_request_sha256="f" * 64)
    assert supplement_digest(document) == binding["digest"]


def test_reads_reject_missing_tampered_mismatched_and_symlinked_files(tmp_path: Path) -> None:
    db, _envelope, binding, request_sha = _publish(tmp_path)
    assert binding["digest"]
    with pytest.raises(FoundryError) as excinfo:
        load_supplement(db, "cg1.run.fixture", "0" * 64)
    assert excinfo.value.code == "CG1_TRAINING_AUTHORITY_SUPPLEMENT_MISSING"

    with pytest.raises(FoundryError) as excinfo:
        load_supplement(db, "cg1.run.fixture", "not-a-digest")
    assert excinfo.value.code == "CG1_TRAINING_AUTHORITY_SUPPLEMENT_DIGEST_INVALID"

    with pytest.raises(FoundryError) as excinfo:
        load_supplement(db, "cg1.run.other", binding["digest"])
    assert excinfo.value.code == "CG1_TRAINING_AUTHORITY_SUPPLEMENT_MISSING"

    with pytest.raises(FoundryError) as excinfo:
        load_supplement(db, "cg1.run.fixture", binding["digest"], expected_request_sha256="9" * 64)
    assert excinfo.value.code == "CG1_TRAINING_AUTHORITY_SUPPLEMENT_BINDING_MISMATCH"

    path = supplement_path(db, "cg1.run.fixture", binding["digest"])
    good = path.read_bytes()
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(FoundryError) as excinfo:
        load_supplement(db, "cg1.run.fixture", binding["digest"])
    assert excinfo.value.code == "CG1_TRAINING_AUTHORITY_SUPPLEMENT_CORRUPT"

    path.write_bytes(good)
    tampered = json.loads(good)
    tampered["binding"]["run_id"] = "cg1.run.other"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(FoundryError) as excinfo:
        load_supplement(db, "cg1.run.fixture", binding["digest"])
    assert excinfo.value.code == "CG1_TRAINING_AUTHORITY_SUPPLEMENT_CORRUPT"

    path.unlink()
    path.symlink_to(Path(tmp_path, "elsewhere.json"))
    with pytest.raises(FoundryError) as excinfo:
        load_supplement(db, "cg1.run.fixture", binding["digest"])
    assert excinfo.value.code == "CG1_TRAINING_AUTHORITY_SUPPLEMENT_MISSING"
