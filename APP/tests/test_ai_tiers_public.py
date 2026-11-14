"""Public/offline tier and synthetic-fixture regressions; no combat runtime."""
import ast
from pathlib import Path

import pytest

from tests import ai_tiers_fixtures

from combat.ai_tiers import tier_for_power_band, tier_for_sheet
from tests.ai_tiers_fixtures import sheet


@pytest.mark.parametrize("band,tier", [(None, "TRICKY"), ("", "TRICKY"), ("supporting", "TRICKY"),
                                       ("heroic", "TRICKY"), ("rival/boss", "MASTERMIND"), ("unknown", "TRICKY")])
def test_tier_mapping(band, tier):
    assert tier_for_power_band(band) == tier
    assert tier_for_sheet({"advancement_history": {"all_owner_locks": [{"field": "power_band", "value": band}]}}) == tier



def test_creation_defaults_match_and_select_tricky(tmp_path, monkeypatch):
    from bs4 import BeautifulSoup
    from app.models import CharacterSheetCreateRequest, CreateProjectRequest, QuickBuildRequest
    from app.power_band import DEFAULT_POWER_BAND
    from character_builder.service import BUILDER_FORM_DEFAULT_POWER_BAND
    from character_creation.quick_build import QuickBuildQueue
    from inspect import signature
    from project_store.service import ProjectStore

    assert DEFAULT_POWER_BAND == "supporting"
    soup = BeautifulSoup((Path(__file__).resolve().parents[1] / "static/index.html").read_text(), "html.parser")
    for select_id in ("guidedPower", "quickBuildPower"):
        selected = soup.select(f"#{select_id} option[selected]")
        assert len(selected) == 1 and selected[0]["value"] == DEFAULT_POWER_BAND
    assert CharacterSheetCreateRequest().power_band == DEFAULT_POWER_BAND
    assert QuickBuildRequest(items=[{"seed": "one"}]).power_band == DEFAULT_POWER_BAND
    assert CreateProjectRequest(working_name="Test", pack_locks=[]).quality_target == DEFAULT_POWER_BAND
    assert signature(ProjectStore.create_project).parameters["quality_target"].default == DEFAULT_POWER_BAND
    assert BUILDER_FORM_DEFAULT_POWER_BAND == DEFAULT_POWER_BAND

    queue = QuickBuildQueue(tmp_path, create_project=lambda **kw: None, lock_choices=lambda x: None,
                            start_run=lambda *a, **kw: None, finalize_run=lambda x: None)
    monkeypatch.setattr(queue, "_ensure_workers", lambda: None)
    batch = queue.submit(items=[{"seed": "one"}], target_cl=5)
    assert batch["power_band"] == DEFAULT_POWER_BAND
    assert tier_for_sheet({"power_band": batch["power_band"]}) == "TRICKY"
    assert tier_for_sheet({"power_band": "rival/boss"}) == "MASTERMIND"
    javascript = (Path(__file__).resolve().parents[1] / "static/app.js").read_text()
    assert 'document.getElementById("guidedCreate").reset()' in javascript
    assert 'document.getElementById("guidedPower").value = "rival/boss"' not in javascript


def test_synthetic_sheet_helper_does_not_import_native_runtime():
    # Guard the fixture boundary, not merely the helper's current return value.
    # The old h1 harness imports the compiler, executor and Gate4 engine.
    tree = ast.parse(Path(ai_tiers_fixtures.__file__).read_text())
    native_imports = []
    for node in ast.walk(tree):
        names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        native_imports.extend(name for name in names if name.startswith(
            ("combat", "factory_authoring", "tests")))
    assert not native_imports, f"synthetic sheets import native runtime: {native_imports}"


def test_equal_build_sheets_are_independent_synthetic_records():
    records = {
        "test:base": {"sphere_id": "test:sphere", "kind": "base_ability"},
        "test:talent": {"sphere_id": "test:sphere", "kind": "talent"},
        "test:other": {"sphere_id": "test:other_sphere", "kind": "base_ability"},
    }
    left = sheet(["test:talent"], mechanics=records, name="Planner")
    right = sheet(["test:talent"], mechanics=records, name="Opponent")
    assert left["spheres_and_talents"] == right["spheres_and_talents"] == {
        "sphere_record_ids": ["test:sphere"],
        "learned_talent_record_ids": ["test:talent"],
        "automatic_sphere_component_record_ids": ["test:base"],
    }
    assert left["ability_scores_and_statistics"] == right["ability_scores_and_statistics"]
    right["ability_scores_and_statistics"]["hit_points"]["maximum"] = 25
    right["spheres_and_talents"]["learned_talent_record_ids"].clear()
    assert left["ability_scores_and_statistics"]["hit_points"]["maximum"] == 60
    assert left["spheres_and_talents"]["learned_talent_record_ids"] == ["test:talent"]
    assert left["identity"]["name"] == "Planner"
    assert right["identity"]["name"] == "Opponent"


def test_empty_opponent_sheet_needs_no_corpus_or_owner_data():
    doc = sheet([], mechanics={}, name="Opponent")
    assert "spheres_and_talents" not in doc
    assert "equipment" not in doc
    assert doc["ability_scores_and_statistics"]["primary_resource"] == {"name": "Qi", "maximum": 30}
    assert doc["ability_scores_and_statistics"]["technique_attack_bonus"] == 8
