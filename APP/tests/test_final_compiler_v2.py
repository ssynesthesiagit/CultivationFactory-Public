"""Compiler v2: rulebook alignment and additive release integrity."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import factory_authoring.final_compiler_release as release
from factory_authoring.final_character_materializer import FINAL_CHARACTER_DEFAULT_STATE_ROOT

SOURCE = release.SOURCE_PATH


def _module():
    spec = importlib.util.spec_from_file_location("final_compiler_v2_under_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_matches_its_release_pin() -> None:
    assert release.verified_source() == SOURCE


def test_cl20_is_the_immortal_realm() -> None:
    compiler = _module()
    assert [compiler.realm_for_cl(cl) for cl in (1, 5, 10, 15, 19, 20)] == [
        "Mortal", "Foundation", "Core Formation", "Nascent Soul", "Nascent Soul", "Immortal",
    ]
    assert compiler.REALM_RANK["Immortal"] == 5 and "True Immortality" not in compiler.REALM_RANK


def test_quality_floors_and_sphere_cap_are_not_legality_checks() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    for code in (
        "MEANINGFUL_ACTION_MINIMUM_NOT_MET",
        "COMPOSITE_MINIMUM_NOT_MET",
        "RECORDED_ART_MINIMUM_NOT_MET",
        "SPHERE_DIVERSITY_OVERRIDE_REQUIRED",
        "SPHERE_DIVERSITY_EXCEPTIONAL_MAX_EXCEEDED",
    ):
        assert code not in text


def test_cp_minimum_and_level1_bonus_rules_are_present() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert 'max(rcl*key_mod,2*rcl)' in text  # RAW-015 Qi/Resonance minimum
    assert "LEVEL_1_SPHERE_BONUS_TALENT_COUNT_INVALID" in text  # Q01 free-Sphere talent


def test_published_release_matches_its_tree_pin() -> None:
    root = release.release_root(FINAL_CHARACTER_DEFAULT_STATE_ROOT)
    if not root.is_dir():
        pytest.skip("compiler v2 release is not published on this host")
    assert release.tree_sha256(root) == release.FACTORY_ROOT_SHA256
    assert (root / release.COMPILER_RELATIVE_PATH).read_bytes() == SOURCE.read_bytes()
