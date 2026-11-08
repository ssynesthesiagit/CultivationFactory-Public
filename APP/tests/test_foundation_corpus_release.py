from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import zipfile

import pytest

from app.core import Database, FoundryError, sha256_json
from character_creation import compiler_selection_authority as authority
from character_creation import foundation_corpus_release as release
from character_creation import method_corpus_release as parent
from character_creation.delegated_choice_authority import build_delegated_choice_envelope
from non_sphere_authority import NonSphereAuthorityService
from test_compiler_selection_authority import VENDOR, _content_lock, _project, _production_prompt, _test_settings, pinned_authority


@pytest.fixture(scope="module")
def complete_authority():
    return authority.build_compiler_selection_authority(
        VENDOR, content_lock=_content_lock(),
        method_records=json.loads(parent.REGISTRY_PATH.read_text())["methods"],
        foundation_records=json.loads(release.REGISTRY_PATH.read_text())["orthodox"],
    )


def test_all_playable_foundations_have_exact_complete_sources(complete_authority):
    assert complete_authority["schema"] == authority.FOUNDATION_COMPILER_SELECTION_AUTHORITY_SCHEMA
    assert authority.verify_compiler_selection_authority(complete_authority) == complete_authority
    source_rows = json.loads(release.REGISTRY_PATH.read_text())
    records = complete_authority["foundation_choice"]["records"]
    assert set(records) == {row["foundation_id"] for row in source_rows["orthodox"]}
    assert len(complete_authority["foundation_choice"]["compiler_backed_ids"]) == 30
    assert not set(records) & {row["foundation_id"] for row in source_rows["theoretical_chakra"]}
    assert len(complete_authority["method_choice"]["compiler_backed_ids"]) == 102
    with zipfile.ZipFile(release.release_path(VENDOR)) as corpus:
        for source in source_rows["orthodox"]:
            row = records[source["foundation_id"]]
            section = corpus.read(row["source_path"])
            assert sha256(section).hexdigest() == source["source"]["section_sha256"]
            assert row["source_file_sha256"] == source["source"]["section_sha256"]
            assert row["source_text"].encode() == section.splitlines(keepends=True)[0]


def test_release_is_additive_and_reproducible(complete_authority):
    base = parent.release_path(VENDOR).read_bytes()
    first = release.derive_corpus_bytes(base)
    assert first == release.derive_corpus_bytes(base)
    assert sha256(first).hexdigest() == release.CORPUS_SHA256
    with zipfile.ZipFile(BytesIO(base)) as old, zipfile.ZipFile(BytesIO(first)) as new:
        added = set(new.namelist()) - set(old.namelist())
        assert len(added) == 30
        assert all(name.startswith(release.MEMBER_PREFIX) for name in added)
        for name in old.namelist():
            if name != release.MANIFEST_MEMBER:
                assert old.read(name) == new.read(name)
        manifest = json.loads(new.read(release.MANIFEST_MEMBER))
        assert manifest["foundation_corpus_release"] == release.provenance()
        assert manifest["method_corpus_release"] == parent.provenance()


@pytest.mark.parametrize("field", ["source_sha256", "typed_registry_sha256", "corpus_sha256", "parent_corpus_sha256"])
def test_rehashed_release_forgery_is_rejected(complete_authority, field):
    value = deepcopy(complete_authority)
    value["foundation_corpus_release"][field] = "0" * 64
    value["authority_sha256"] = sha256_json({k: v for k, v in value.items() if k != "authority_sha256"})
    with pytest.raises(FoundryError):
        authority.verify_compiler_selection_authority(value)


def test_old_snapshot_stays_old_and_new_release_cannot_be_stripped(pinned_authority, complete_authority):
    assert authority.verify_compiler_selection_authority(pinned_authority) == pinned_authority
    assert len(pinned_authority["foundation_choice"]["compiler_backed_ids"]) == 9
    value = deepcopy(complete_authority)
    value["schema"] = authority.RELEASED_COMPILER_SELECTION_AUTHORITY_SCHEMA
    del value["foundation_corpus_release"]
    value["authority_sha256"] = sha256_json({k: v for k, v in value.items() if k != "authority_sha256"})
    with pytest.raises(FoundryError):
        authority.verify_compiler_selection_authority(value)


def test_modified_source_and_parent_fail(tmp_path, monkeypatch):
    with pytest.raises(FoundryError):
        release.derive_corpus_bytes(b"forged")
    changed = tmp_path / "source.md"
    changed.write_bytes(release.SOURCE_PATH.read_bytes() + b"x")
    monkeypatch.setattr(release, "SOURCE_PATH", changed)
    with pytest.raises(FoundryError):
        release.verified_sections()


def test_existing_corrupt_cache_is_preserved(tmp_path):
    target = release.release_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"preserve corrupt evidence")
    with pytest.raises(FoundryError):
        release.ensure_release(tmp_path, VENDOR / "missing-parent.zip")
    assert target.read_bytes() == b"preserve corrupt evidence"


def test_owner_foundation_is_checked_before_the_walk(tmp_path, pinned_authority, complete_authority):
    project = _project()
    foundation_id = "heaven_devouring_shedding_womb_v0_2B"
    project["user_locks"].append({"field": "character_sheet.locked_choices", "value": {"foundation_choice": [foundation_id]}, "source": "test"})
    prompt = _production_prompt(NonSphereAuthorityService(Database(_test_settings(tmp_path))))
    with pytest.raises(FoundryError) as caught:
        build_delegated_choice_envelope(project, prompt, execution_mode="MANUAL_CHAT",
                                        idempotency_key="old-foundation", compiler_selection_authority=pinned_authority)
    assert caught.value.code == "CG1_FOUNDATION_EXACT_PLAN_UNAVAILABLE"
    envelope = build_delegated_choice_envelope(project, prompt, execution_mode="MANUAL_CHAT",
                                               idempotency_key="complete-foundation", compiler_selection_authority=complete_authority)
    assert envelope["owner_locks"]["by_slot"]["foundation_choice"] == [foundation_id]
    assert foundation_id in envelope["allowed_choice_ids_by_slot"]["foundation_choice"]


def test_complete_release_method_menu_honors_exact_planning(tmp_path, complete_authority):
    from character_creation.creative_controller.linear_menus import _method_candidates
    project = _project()
    prompt = _production_prompt(NonSphereAuthorityService(Database(_test_settings(tmp_path))))
    envelope = build_delegated_choice_envelope(project, prompt, execution_mode="MANUAL_CHAT",
                                               idempotency_key="exact-method", compiler_selection_authority=complete_authority)
    original = _method_candidates({}, envelope, None)
    assert len(original) > 1
    exact = original[-1].choice_ids
    envelope["owner_locks"]["planning_by_slot"] = {"method_choice": {"mode": "EXACT", "choice_ids": list(exact)}}
    assert [row.choice_ids for row in _method_candidates({}, envelope, None)] == [exact]
    envelope["owner_locks"]["planning_by_slot"]["method_choice"]["choice_ids"] = ["METHOD-FORGED"]
    assert _method_candidates({}, envelope, None) == []
    envelope["compiler_selection_authority"]["schema"] = authority.RELEASED_COMPILER_SELECTION_AUTHORITY_SCHEMA
    assert _method_candidates({}, envelope, None) == original
