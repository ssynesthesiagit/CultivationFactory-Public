from copy import deepcopy

import pytest

from app.core import FoundryError
from character_creation.service import CharacterCreationExecutionService


def _case(kind: str) -> tuple[dict, dict]:
    plan = {
        "schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
        "selection_intent": {"by_slot": {"path_choice": ["path.synthetic"]}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": ["talent.synthetic"],
            "insight_occurrences": [],
        },
        "bounded_choices": {
            "ability_scores": {"STR": 10, "DEX": 10},
            "ability_score_changes_by_milestone_id": {
                "CL8": {"deltas": {"WIS": 1}},
            },
        },
        "owner_descriptive_fields": {
            "identity": {"name": "Synthetic Owner"},
            "concept": "A public-safe owner decision fixture.",
        },
        "unrelated": {"must_remain": ["exact-response-overlay-boundary"]},
    }
    run = {
        "validation": {
            "owner_resolutions": [{
                "operation": "set_milestone_choice",
                "field": "CL4",
                "value": {
                    "milestone_id": "CL4",
                    "kind": kind,
                    "insight_id": "insight.synthetic.cl4",
                    "parameters": {"ability": "INT"},
                },
            }],
        },
    }
    return run, plan


def test_canonical_insight_kind_applies_exact_occurrence_without_asi() -> None:
    run, plan = _case("cultivation_insight_acquisition")
    original = deepcopy(plan)

    overlay = CharacterCreationExecutionService._apply_owner_resolutions(run, plan)

    assert overlay["acquisition_intent"]["insight_occurrences"] == [{
        "insight_id": "insight.synthetic.cl4",
        "milestone_id": "CL4",
        "parameters": {"ability": "INT"},
    }]
    assert overlay["bounded_choices"]["ability_score_changes_by_milestone_id"] == {
        "CL8": {"deltas": {"WIS": 1}},
    }
    assert overlay["selection_intent"] == original["selection_intent"]
    assert overlay["unrelated"] == original["unrelated"]
    assert plan == original


def test_legacy_insight_kind_remains_compatible() -> None:
    run, plan = _case("insight")

    overlay = CharacterCreationExecutionService._apply_owner_resolutions(run, plan)

    assert overlay["acquisition_intent"]["insight_occurrences"][0]["milestone_id"] == "CL4"
    assert "CL4" not in overlay["bounded_choices"]["ability_score_changes_by_milestone_id"]


def test_unrecognized_milestone_kind_remains_fail_closed() -> None:
    run, plan = _case("provider_supplied_insight")
    original = deepcopy(plan)

    with pytest.raises(FoundryError) as raised:
        CharacterCreationExecutionService._apply_owner_resolutions(run, plan)

    assert raised.value.code == "CG1_DECISION_MILESTONE_KIND_INVALID"
    assert raised.value.details == {
        "milestone_id": "CL4",
        "kind": "provider_supplied_insight",
    }
    assert plan == original
