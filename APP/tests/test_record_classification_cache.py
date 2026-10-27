"""Generic event classification must not select later mechanical authority."""

from copy import deepcopy
from types import MappingProxyType

import pytest

from contracts.canonical import canonical_record_hash
import non_sphere_authority.service as non_sphere_authority_module
from project_store.service import ProjectStore
from stage2.service import RulesCausalStage2Service
from tests.test_creation_training_r4 import _real_creation_intent


def _record(record_id, content_type, version):
    record = {
        "record_id": record_id,
        "content_type": content_type,
        "content_binding": {"pack_version": version},
        "publication": {"status": "published"},
        "compatibility": {"factory": {"stage2_authority": {"authority_complete": True}}},
    }
    record["record_hash"] = canonical_record_hash(record)
    return record


@pytest.mark.parametrize("record_id,content_type", [
    ("METHOD-083", "cultivation_method"),
    ("ancient_fixture_foundation", "foundation"),
    ("tianxia.path.body_refining", "cultivation_path"),
    ("fixture.origin_insight", "origin_insight"),
])
@pytest.mark.parametrize("lock_already_proved", [False, True])
def test_classification_cannot_seed_a_different_authority_resolver(
    monkeypatch, record_id, content_type, lock_already_proved,
):
    # The historical event classifier and initial-creation compiler intentionally
    # resolve the same ID under different authority contexts.
    monkeypatch.setattr("non_sphere_authority.NonSphereAuthorityService", lambda db: object())
    legacy = _record(record_id, content_type, "legacy")
    selected = _record(record_id, content_type, "selected")
    store = object.__new__(ProjectStore)
    store.db = object()
    calls = []

    def historical_record(*args, **kwargs):
        calls.append(record_id)
        return legacy

    store._resolve_locked_record = historical_record
    store._resolve_locked_record_after_proof = historical_record
    authority_cache = {}
    event = {"subject": {"record_id": record_id, "content_type": content_type}}
    assert store._record_types(
        None, "fixture.project", [event, deepcopy(event)],
        lock_already_proved=lock_already_proved, record_cache=authority_cache,
    ) == {record_id: content_type}
    assert calls == [record_id]

    compiler = object.__new__(RulesCausalStage2Service)
    compiler._resolve_record_after_proof = lambda *args: selected
    record, blockers = compiler._record(
        None, "fixture.project", record_id, "/choices/0/record_id",
        record_cache=authority_cache,
    )
    assert not blockers
    assert record == selected
    assert legacy == _record(record_id, content_type, "legacy")


def test_classification_consults_caller_records_without_mutating_them():
    existing = _record("fixture.existing", "origin_insight", "selected")
    missing = _record("fixture.missing", "foundation", "legacy")
    authority_cache = {existing["record_id"]: existing}
    before = deepcopy(authority_cache)
    store = object.__new__(ProjectStore)
    calls = []

    def resolve(_conn, _project_id, record_id):
        calls.append(record_id)
        assert record_id == missing["record_id"]
        return missing

    store._resolve_locked_record = resolve
    events = [{"subject": {"record_id": record["record_id"]}} for record in (existing, missing)]
    assert store._record_types(
        None, "fixture.project", events, record_cache=MappingProxyType(authority_cache),
    ) == {"fixture.existing": "origin_insight", "fixture.missing": "foundation"}
    assert calls == [missing["record_id"]]
    assert authority_cache == before


def test_record_types_reuses_store_cached_authority(catalog_environment, monkeypatch):
    creator, project, _, _, _ = _real_creation_intent(catalog_environment)
    store = ProjectStore(creator.db)
    with creator.db.connection() as conn:
        row = conn.execute(
            "SELECT record_id FROM project_locked_records "
            "WHERE project_id=? AND (record_id LIKE 'tianxia.path.%' OR record_id LIKE 'METHOD-%') "
            "ORDER BY record_id LIMIT 1",
            (project["project_id"],),
        ).fetchone()
        assert row is not None
        record_id = row["record_id"]
        event = {
            "event_id": "record-types-cache-event",
            "event_type": "advancement",
            "subject": {"record_id": record_id},
            "created_records": [record_id],
            "updated_records": [],
            "retired_records": [],
        }

        original_init = non_sphere_authority_module.NonSphereAuthorityService.__init__
        constructions = 0

        def counting_init(instance, *args, **kwargs):
            nonlocal constructions
            constructions += 1
            return original_init(instance, *args, **kwargs)

        monkeypatch.setattr(
            non_sphere_authority_module.NonSphereAuthorityService,
            "__init__",
            counting_init,
        )
        replays = [
            store._reduce_events(
                [event], project["project_id"], conn, lock_already_proved=True,
            )
            for _ in range(3)
        ]

    assert constructions <= 1
    assert replays[0] == replays[1] == replays[2]
