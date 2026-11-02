"""Content-cache equality and invalidation, through the real run/package APIs."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from pathlib import Path
import shutil
import threading
import zipfile

import pytest

from app.core import FoundryError, canonical_json, sha256_json
from app.validation_cache import ValidationResultCache, file_content_key
from character_creation.creative_controller import route_persistence as routes
from character_creation.creative_controller import dcc_semantic_publication as publication
from portable_character import service as portable
from tests.test_c3b_pre_encounter import FIXTURE, _service as library_service
from tests.test_dcc_stage_b_route import _db, _seed_dcc_run, _stub_service
from tests.test_dcc_semantic_publication import V2_RECEIPT_SHA256


def _semantic(value):
    value = deepcopy(value)
    value.pop("timings", None)  # Response preparation time is intentionally live.
    return value


def test_run_poll_cache_equals_uncached_and_keeps_progress_live(tmp_path, monkeypatch):
    db = _db(tmp_path)
    _seed_dcc_run(db, "cached-run")
    service, _ = _stub_service(db)
    calls = []
    request_hash_calls = []
    original_hash = service.request_payload_sha256

    def request_hash(request):
        request_hash_calls.append(1)
        return original_hash(request)

    monkeypatch.setattr(service, "request_payload_sha256", request_hash)
    original = service.controller_routes._validate_projection_rows

    def validate(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(service.controller_routes, "_validate_projection_rows", validate)
    first = service.get("cached-run")
    assert len(calls) == 1  # _public consults the route several times.
    for _ in range(3):
        assert _semantic(service.get("cached-run")) == _semantic(first)
    assert len(calls) == 1
    assert request_hash_calls == [1]
    first["request"]["controller_route_binding"]["route_mode"] = "caller mutation"
    assert service.get("cached-run")["request"]["controller_route_binding"]["route_mode"] != "caller mutation"
    service._finalizing_run_id = "cached-run"
    assert service.get("cached-run")["finalize_in_progress"] is True
    service._finalizing_run_id = None
    cached = service.get("cached-run")
    service.controller_routes._projection_validations.clear()
    assert _semantic(service.get("cached-run")) == _semantic(cached)
    assert len(calls) == 2
    with db.transaction() as conn:
        conn.execute("UPDATE character_creation_runs SET starting_revision=1,status='NEEDS_REVIEW',warnings_json=? WHERE run_id=?",
                     (canonical_json(["Retained warning"]), "cached-run"))
    changed = service.get("cached-run")
    assert changed["starting_revision"] == 1
    assert changed["status"] == "NEEDS_REVIEW"
    assert changed["warnings"] == ["Retained warning"]
    with db.transaction() as conn:
        row = conn.execute("SELECT request_json FROM character_creation_runs WHERE run_id=?", ("cached-run",)).fetchone()
        import json
        request = json.loads(row["request_json"])
        request["project_revision"] = 1
        conn.execute("UPDATE character_creation_runs SET request_json=? WHERE run_id=?", (canonical_json(request), "cached-run"))
    with pytest.raises(FoundryError) as error:
        service.get("cached-run")
    assert error.value.code == "DCC_ROUTE_REQUEST_HASH_INVALID"
    assert request_hash_calls == [1, 1]


@pytest.mark.parametrize("column,value", [("event_json", "{}"), ("subject_sha256", "f" * 64)])
def test_warm_route_cache_detects_event_tamper_with_identical_error(tmp_path, column, value):
    db = _db(tmp_path)
    _seed_dcc_run(db, "tamper-run")
    service, _ = _stub_service(db)
    service.get("tamper-run")
    with db.transaction() as conn:
        # Simulate corrupted storage on this disposable DB, as existing route
        # tamper tests do; ordinary writers retain the append-only protection.
        conn.execute("DROP TRIGGER trg_dcc_controller_events_no_update")
        conn.execute(f"UPDATE dcc_controller_events SET {column}=? WHERE run_id=?", (value, "tamper-run"))
    with pytest.raises(FoundryError) as cached:
        service.get("tamper-run")
    service.controller_routes._projection_validations.clear()
    with pytest.raises(FoundryError) as uncached:
        service.get("tamper-run")
    assert (cached.value.code, cached.value.message, cached.value.details) == (uncached.value.code, uncached.value.message, uncached.value.details)


def test_request_hash_cache_preserves_blob_json_rows(tmp_path):
    db = _db(tmp_path)
    _seed_dcc_run(db, "blob-run")
    service, _ = _stub_service(db)
    before = service.get("blob-run")
    # SQLite TEXT affinity permits BLOB storage, and the original json.loads
    # path accepts it. Memoization must preserve that existing read behaviour.
    with db.transaction() as conn:
        conn.execute("UPDATE character_creation_runs SET request_json=CAST(request_json AS BLOB) WHERE run_id=?", ("blob-run",))
    assert _semantic(service.get("blob-run")) == _semantic(before)


def test_manual_summary_cache_invalidates_on_actual_content(tmp_path, monkeypatch):
    service, _ = _stub_service(_db(tmp_path))
    calls = []
    monkeypatch.setattr("character_creation.service.build_compact_choice_model", lambda request: calls.append(request) or {"selection": request["selection"]})
    run = {"execution_mode": "MANUAL_CHAT", "request": {"request_sha256": "a" * 64, "selection": "first"},
           "response": {"response_sha256": "b" * 64}, "validation": {},
           "blockers": [{"details": {"ai_correction_required": {"classification": "AI_CORRECTION_REQUIRED", "errors": ["Retained error"]}}}]}
    first = service._manual_ai_correction_summary(run)
    assert service._manual_ai_correction_summary(run) == first
    assert len(calls) == 1
    assert service._manual_ai_correction_summary_uncached(run) == first
    run["request"]["selection"] = "second"  # No change to advertised request hash.
    second = service._manual_ai_correction_summary(run)
    assert second["model_sha256"] != first["model_sha256"]
    assert second["errors"] == first["errors"]
    assert len(calls) == 3


def test_event_append_invalidates_cached_status(tmp_path):
    db = _db(tmp_path)
    _seed_dcc_run(db, "append-run")
    service, _ = _stub_service(db)
    before = service.controller_routes.projection("append-run")
    service.get("append-run")
    service.controller_routes.append_event(
        "append-run", event_type="PROGRESS_RECORDED", subject_sha256="f" * 64,
        state_sha256_before=before["state_sha256"], state_sha256_after=before["state_sha256"],
        payload={"step_id": "new-step"}, expected_event_head_sha256=before["event_head_sha256"],
        expected_ordinal=before["event_count"] + 1, expected_binding_sha256=before["binding_sha256"],
    )
    after = service.get("append-run")
    assert after["controller_route_status"]["event_count"] == before["event_count"] + 1
    service.controller_routes._projection_validations.clear()
    assert _semantic(service.get("append-run")) == _semantic(after)


def test_archive_cached_and_uncached_results_equal_and_isolated(tmp_path, monkeypatch):
    package = tmp_path / "character.zip"
    shutil.copyfile(FIXTURE, package)
    original = zipfile.ZipFile.testzip
    calls = []

    def crc(archive):
        calls.append(1)
        return original(archive)

    monkeypatch.setattr(zipfile.ZipFile, "testzip", crc)
    cached = portable.PortableCharacterPackageService.audit(package)
    assert portable.PortableCharacterPackageService.audit(package) == cached
    assert len(calls) == 1
    assert portable.PortableCharacterPackageService._audit_uncached(package) == cached
    assert len(calls) == 2
    cached["manifest"]["project_id"] = "caller mutation"
    assert portable.PortableCharacterPackageService.audit(package)["manifest"]["project_id"] != "caller mutation"
    stamp = package.stat()
    os.utime(package, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000))
    portable.PortableCharacterPackageService.audit(package)
    assert len(calls) == 3


def _damage_member(package):
    # Flip compressed payload, keeping length and the original mtime. ctime
    # still changes, so this cannot reuse the successful verification marker.
    stamp = package.stat()
    with zipfile.ZipFile(package) as archive:
        info = next(row for row in archive.infolist() if row.compress_size > 50)
    raw = bytearray(package.read_bytes())
    offset = info.header_offset
    name_len = int.from_bytes(raw[offset + 26:offset + 28], "little")
    extra_len = int.from_bytes(raw[offset + 28:offset + 30], "little")
    raw[offset + 30 + name_len + extra_len] ^= 255
    package.write_bytes(raw)
    os.utime(package, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))


def test_tampered_archive_still_fails_cached_and_uncached(tmp_path):
    package = tmp_path / "character.zip"
    shutil.copyfile(FIXTURE, package)
    portable.PortableCharacterPackageService.audit(package)
    before = file_content_key(package)
    _damage_member(package)
    assert file_content_key(package) != before
    errors = []
    for audit in (portable.PortableCharacterPackageService.audit, portable.PortableCharacterPackageService._audit_uncached):
        with pytest.raises(Exception) as error:
            audit(package)
        errors.append((type(error.value), getattr(error.value, "code", None), str(error.value)))
    assert errors[0] == errors[1]


def test_library_reads_reuse_archive_verification_and_detect_tamper(tmp_path, monkeypatch):
    service, data = library_service(tmp_path)
    original = zipfile.ZipFile.testzip
    calls = []
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda archive: calls.append(1) or original(archive))
    first = service.inventory()
    second = service.inventory()
    assert first == second
    assert len(calls) == 1
    package = next((data / "portable_characters").glob("*/current.zip"))
    _damage_member(package)
    blocked = service.inventory()
    assert blocked.accepted_count == 0
    assert blocked.blocked_candidates[0].code == "C3B_INSTALLED_PACKAGE_STALE"


def test_publication_cached_equals_uncached_and_object_tamper_invalidates(tmp_path, monkeypatch):
    objects = tmp_path / "authority" / "dcc_semantics" / "objects"
    shutil.copytree(publication._AUTHORITY_ROOT / "dcc_semantics" / "objects", objects)
    root = objects.parents[1]
    receipt, raw = publication._find_receipt_object_by_internal_digest(objects, V2_RECEIPT_SHA256)
    first = publication._validate_detached_publication(root, receipt, receipt_payload=raw)
    assert publication._validate_detached_publication(root, receipt, receipt_payload=raw) == first
    assert publication._validate_detached_publication_uncached(root, receipt, receipt_payload=raw) == first
    binding = routes.build_active_controller_route_binding(seeded=True)
    binding = {**binding, "publication_receipt_sha256": receipt["receipt_sha256"],
               "content_snapshot_sha256": receipt["content_snapshot_sha256"],
               "semantic_authority_bundle_sha256": receipt["semantic_authority_bundle_sha256"],
               "source_rights_authority_sha256": receipt["source_rights_authority_sha256"]}
    binding["binding_sha256"] = sha256_json({key: value for key, value in binding.items() if key != "binding_sha256"})
    # The route marker also has to notice changes to the stored objects; its
    # old binding-only key could hide a corrupted publication after warm-up.
    monkeypatch.setattr(publication, "_AUTHORITY_ROOT", root)
    repository = routes.ControllerRoutePersistence(_db(tmp_path / "route"))
    repository._validate_active_publication_binding(binding)
    row = next(row for row in receipt["objects"] if row["kind"] == "overlay")
    target = objects / f"{row['sha256']}.json"
    stamp = target.stat()
    payload = target.read_bytes()
    target.write_bytes(b" " + payload[1:])
    os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    errors = []
    for validate in (publication._validate_detached_publication, publication._validate_detached_publication_uncached):
        with pytest.raises(FoundryError) as error:
            validate(root, receipt, receipt_payload=raw)
        errors.append((error.value.code, error.value.message, error.value.details))
    assert errors[0] == errors[1]
    with pytest.raises(FoundryError) as route_error:
        repository._validate_active_publication_binding(binding)
    assert route_error.value.code == "DCC_ROUTE_PUBLICATION_TAMPERED"


def test_singleflight_and_unrelated_warm_read_does_not_wait():
    cache = ValidationResultCache(limit=2)
    assert cache.get_or_compute("warm", lambda: {"ok": True}) == {"ok": True}
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return None

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(cache.get_or_compute, "cold", slow)
        assert entered.wait(5)
        second = pool.submit(cache.get_or_compute, "cold", slow)
        warm = pool.submit(cache.get_or_compute, "warm", lambda: pytest.fail("warm result recomputed"))
        try:
            assert warm.result(timeout=2) == {"ok": True}
        finally:
            release.set()
        assert first.result() is None
        assert second.result() is None
    assert calls == [1]


def test_warm_receipt_lookup_does_not_reread_large_unrelated_history(tmp_path, monkeypatch):
    objects = tmp_path / "objects"
    objects.mkdir()
    # More objects than the bounded digest cache can retain. These unrelated
    # files cannot match the requested receipt; only the first lookup may scan.
    for number in range(300):
        (objects / f"{number:064x}.json").write_bytes(b"{}")
    reads = []
    original = Path.open

    def opened(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    assert publication._find_receipt_object_by_internal_digest(objects, "f" * 64) is None
    assert reads
    reads.clear()
    assert publication._find_receipt_object_by_internal_digest(objects, "f" * 64) is None
    assert reads == []
