"""MGR-T14-ling-base-gatherer-training-1: printed state of the Gatherer sphere's
"Training and Tools" base ability (HARVESTING_GATHERING_BASE_TRAINING_AND_TOOLS).

This lane reverified the printed clauses against the real native producers and did
NOT implement them: each clause needs a build fact or a catalog item that this
repository does not record, and inventing one would fabricate a character. These
tests are the honest native receipt for the lane's PARTIAL result -- they fail if a
future change claims delivery that the engine does not actually perform.

Evidence is limited to typed authority, public compiler skill projection and
compiled character inventory; it does not establish table/session delivery.
"""
from __future__ import annotations

import json
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parents[1]
MID = "HARVESTING_GATHERING_BASE_TRAINING_AND_TOOLS"
SPHERE = "tianxia.sphere.harvesting_gathering"

RULES_TEXT = json.loads(
    (APP / "authority/typed_mechanics/rules_text.json").read_text(encoding="utf-8")
)[MID]


def test_printed_record_is_the_exact_control_record() -> None:
    """The controlling record's hash covers the full decoded rules_text.

    The preserved T14 packet and generated authority supply the same digest.
    """
    import hashlib

    assert hashlib.sha256(RULES_TEXT.encode("utf-8")).hexdigest() == (
        "b15e67d14069042cfe5a276087fb60272bb4f60572e71d5a54c13bbf08d79c23"
    )
    for clause in ("herbalism kit", "Nature", "Survival", "Medicine", "land vehicles",
                   "bonus talent", "basic gatherer", "waxed paper", "field ledger"):
        assert clause in RULES_TEXT, clause


def test_authority_source_digest_matches_the_decoded_text() -> None:
    """The generated authority's own source digest is the hash of this text."""
    import hashlib

    from combat.factory_compiler import TYPED_AUTHORITY

    authority = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))
    row = (authority.get("mechanics") or {})[MID]
    assert row["source"]["text_sha256"] == hashlib.sha256(RULES_TEXT.encode("utf-8")).hexdigest()
    assert row["source"]["line"] == 38430


def test_row_is_a_sphere_base_ability_with_no_typed_effect() -> None:
    """The row is the sphere's base ability and carries no compiled effect."""
    from combat.factory_compiler import TYPED_AUTHORITY

    authority = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))
    row = (authority.get("mechanics") or {}).get(MID)
    assert row is not None, "the base ability must remain a typed sphere base ability"
    assert row["kind"] == "base_ability"
    assert row["sphere_id"] == SPHERE
    assert row["activation"]["trigger"] == "When you learn this sphere"
    # No typed effect = no compiled fight action. This is the gap the lane reports;
    # it must not silently change without a re-review of the build-fact seam.
    assert row.get("effects") == []


def _assert_unselected_projection(original, projected, handled) -> None:
    assert MID not in handled, "unselected training must not claim handled"
    assert projected == original, "unselected training must preserve the sheet"


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("skills", [[], [{"skill": "Nature", "bonus": 6, "proficient": True}]])
def test_unselected_training_projection_and_handled_receipt(owned, skills) -> None:
    """Exercise actual providers through the public compiler seam, with ownership controls."""
    import copy
    from combat.factory_compiler import compiled_skill_sheet, TYPED_AUTHORITY
    from tests.test_zones import SHEET

    mechanics = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"]
    sheet = copy.deepcopy(SHEET)
    sheet["ability_scores_and_statistics"]["skills"] = skills
    original = copy.deepcopy(sheet)
    projected, handled = compiled_skill_sheet(
        sheet, [MID] if owned else [], mechanics,
        {ability: 2 for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}, 4, [],
    )
    _assert_unselected_projection(original, projected, handled)
    assert sheet == original, "projection must not mutate its input"


def test_projection_guard_rejects_false_handled_without_a_skill_grant() -> None:
    """Finding 1: an empty projection cannot hide behind a provider's module name."""
    sheet = {"ability_scores_and_statistics": {"skills": []}}
    with pytest.raises(AssertionError, match="must not claim handled"):
        _assert_unselected_projection(sheet, sheet, [MID])


def test_feature_status_reports_it_as_a_build_grant_not_a_fight_action() -> None:
    """The owner-editable status file is the only place this row is described."""
    from combat.factory_compiler import feature_status

    # Declare the exact data dependency: public test snapshots cannot infer the
    # compiler's dynamic feature_status.d glob from this test's imports alone.
    source = json.loads(
        (APP / "combat/rules/feature_status.d/life.json").read_text(encoding="utf-8")
    )["features"][MID]
    entry = feature_status().get(MID)
    assert entry == source
    assert entry is not None
    assert entry["status"] in {"build", "outside"}
    assert "proficiency" in entry["why"]


@pytest.mark.parametrize("owned", [False, True])
def test_unspecified_equipment_does_not_grant_items_even_with_catalog_entries(monkeypatch, owned) -> None:
    """Finding 2: catalog availability is independent of character ownership.

    Synthetic catalog entries test future catalog growth, not source-backed kit
    delivery. No equipment mode or proficiency choice is supplied by this sheet.
    """
    import copy
    from combat.factory_compiler import compile_character, equipment_list
    from factory_authoring.starting_kits import _authorities
    from tests.test_teleport import ME
    from tests.test_zones import SHEET

    sheet = copy.deepcopy(SHEET)
    sheet["equipment"] = []
    sheet["spheres_and_talents"] = {
        "sphere_record_ids": [SPHERE] if owned else [],
        "automatic_sphere_component_record_ids": [MID] if owned else [],
        "learned_talent_record_ids": [],
    }
    original = copy.deepcopy(sheet)
    baseline = compile_character(sheet, actor_id=ME)
    catalog = _authorities()[1]
    for index, name in enumerate(("Pruning knife", "Digging hook", "Field ledger", "Gatherer's Kit")):
        monkeypatch.setitem(catalog, f"test:gatherer.{index}", {"name": name, "weight": "1 lb."})
    assert equipment_list(sheet)["items"] == []
    assert compile_character(sheet, actor_id=ME) == baseline
    assert sheet == original


def test_owning_the_sphere_grants_no_skill_or_tool_proficiency_at_compile() -> None:
    """At the real compile boundary, learning the sphere adds no listed proficiency.

    This is the regression that fails if a future change silently invents a
    proficiency choice for every character who learns this sphere.
    """
    from combat.factory_compiler import compile_character
    from tests.test_teleport import ME
    from tests.test_zones import SHEET

    bundle = compile_character(
        {**SHEET, "spheres_and_talents": {
            "sphere_record_ids": [SPHERE],
            "automatic_sphere_component_record_ids": [MID],
            "learned_talent_record_ids": [],
        }},
        actor_id=ME,
    )
    # The bundle carries no skill projection at all for this row: no proficiency
    # choice is invented for a character who learns the sphere.
    assert "skill_sheet" not in bundle and "skills" not in bundle
    # The honest surface: the row is listed as a build grant, not silently dropped.
    assert "Training and Tools" in bundle["diagnostics"]["skipped"]["outside"]
    # And it grants no fight action of its own.
    assert not [
        action for action in bundle["action_catalog"]
        if MID in json.dumps(action)
    ]
