"""A generator-3 Forge design without an automated profile stays display-only instead of stopping finalize.

2026-10-17: only two Air designs have a source-preserving action profile (forged_action_mechanics._PROFILES). Any other
gen-3 design made load_forged_action_binding raise COMMAND4_FORGED_MECHANICS_UNRESOLVED, so every such character stopped at
NEEDS_REVIEW (huntkit2 HK2H1, seeded CL5 build). Self-contained (no catalog fixture) so it runs on public CI.
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

import factory_authoring.forged_action_mechanics as fam
from app.core import FoundryError

RECORD_ID = "tianxia.constructed.forged_technique.test"


def _stub_store(monkeypatch, technique):
    record = {"compatibility": {"factory": {"constructed_art": {"technique": technique}}}}
    store = SimpleNamespace(_resolve_locked_record=lambda conn, project_id, record_id: record,
                            _assert_constructed_art_snapshot_record=lambda conn, project_id, rec: None)
    monkeypatch.setattr(fam, "ProjectStore", lambda db: store)
    monkeypatch.setattr(fam, "installed_factory_root", lambda vendor_dir: None)
    return SimpleNamespace(connection=lambda: contextlib.nullcontext(None), settings=SimpleNamespace(vendor_dir=None))


def _technique(talent_id="TAL_WATER_FLOWING_STEP"):
    return {"owner_project_id": "project.test", "construction": {"generator_version": 3},
            "primary_sphere_effect": {"talent_id": talent_id}}


def test_unprofiled_gen3_design_gets_no_native_binding(monkeypatch):
    db = _stub_store(monkeypatch, _technique())
    assert fam.load_forged_action_binding(db, "project.test", RECORD_ID) is None


def test_a_supplied_binding_for_it_still_fails_validation(monkeypatch):
    db = _stub_store(monkeypatch, _technique())
    with pytest.raises(FoundryError) as error:
        fam.validate_forged_action_candidate(db, "project.test", {"record_id": RECORD_ID, "constructed_forged_source_binding": {"forged": True}})
    assert error.value.code == "COMMAND4_FORGED_MECHANICS_UNRESOLVED"


def test_other_forge_errors_still_stop(monkeypatch):
    db = _stub_store(monkeypatch, _technique("TAL_AIR_DOWNBURST_SEAL"))

    def broken(technique, factory_root):
        raise FoundryError("COMMAND4_FORGED_SOURCE_CONTEXT_MISSING", "boom")

    monkeypatch.setattr(fam, "forged_action_projection", broken)
    with pytest.raises(FoundryError) as error:
        fam.load_forged_action_binding(db, "project.test", RECORD_ID)
    assert error.value.code == "COMMAND4_FORGED_SOURCE_CONTEXT_MISSING"


def test_a_known_profile_that_fails_its_source_checks_still_stops(monkeypatch):
    technique = _technique("TAL_AIR_DOWNBURST_SEAL")
    technique["base_form"] = {"form_id": "strike"}       # the Downburst profile requires a burst
    technique["cl_created"], technique["action_type"] = 20, "action"
    db = _stub_store(monkeypatch, technique)
    with pytest.raises(FoundryError) as error:
        fam.load_forged_action_binding(db, "project.test", RECORD_ID)
    assert error.value.code == "COMMAND4_FORGED_MECHANICS_UNRESOLVED"
