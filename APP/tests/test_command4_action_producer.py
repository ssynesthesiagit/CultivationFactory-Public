from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import FoundryError
from canonical_catalog.service import CanonicalCatalogAuthorityService
from factory_authoring.command4_actions import _resource_projection_from_description, produce_action_documents
from factory_authoring.command5_profile import CharacterGMCommand5Profile


def _card(description: str, *, record_id: str = "talent.test", display_name: str = "Test Art") -> dict:
    return {
        "record_id": record_id,
        "record_hash": "a" * 64,
        "display_name": display_name,
        "full_description": description,
        "one_line_description": "A test art.",
        "source_packet_ids": ["packet.test"],
        "source": {"path": "rules.md", "anchor": "test", "sha256": "b" * 64},
        "acquisition_cl": 3,
        "acquisition_route": "level_talent_acquisition",
    }


def _complete_description(*, cost: str = "None") -> str:
    return "\n".join(
        (
            "Action Type: Action",
            "Factory Combat Bucket: action",
            "Factory Routing: combat_action_row",
            "Cost: " + cost,
            "Range: 30 feet",
            "Target: One creature",
            "Roll/Save/Check: Constitution save",
            "Effect: Apply the exact source-backed test effect.",
            "Failure: No effect on a successful save.",
            "Duration: Until the start of your next turn",
            "Limit: Once per turn",
            "Counterplay: Succeed on the save.",
        )
    )


def _locked_provenance(
    description: str,
    *,
    record_id: str = "talent.test",
    display_name: str = "Test Art",
) -> dict:
    return {
        "typed_choice_snapshot": {
            "typed_locks": [
                {
                    "field": "talent_dispositions",
                    "value": {
                        "talent_dispositions": [
                            {
                                "canonical_talent_id": record_id,
                                "owning_canonical_sphere_id": "sphere.test",
                                "display_name": display_name,
                                "full_description": description,
                            }
                        ]
                    },
                }
            ]
        }
    }


def _prepared_description(*, item_name: str = "Explosive Pill", action_sentence: str | None = None) -> str:
    return "\n".join((
        "Ingredient",
        "Cost: 150 gp.",
        "",
        "Refinement",
        "Cost: 3 CP.",
        "Action Type: Action",
        "Factory Combat Bucket: action",
        "Factory Routing: combat_action_row",
        "Range: 60 feet",
        "Target: One creature",
        "Roll/Save/Check: Dexterity save",
        "Effect: Apply the exact prepared-item effect.",
        "Failure: No effect on a successful save.",
        "Duration: Until the start of your next turn",
        "Limit: Once per turn",
        "Counterplay: Succeed on the save.",
        action_sentence or f"Throw or launch one prepared {item_name}.",
    ))


def test_complete_explicit_none_cost_action_promotes_with_archive_shape() -> None:
    documents = produce_action_documents(
        (_card(_complete_description()) for _ in range(1)),
        projection_provenance=_locked_provenance(_complete_description()),
    )
    surface = documents["Complete_Action_Surface.json"]

    assert surface["status"] == "ACTION_SURFACE_READY"
    assert surface["execution_authority"] is True
    assert surface["global_combat_readiness"] is False
    assert surface["provenance"]["selected_record_count"] == 1
    [action] = surface["actions"]
    assert action["bucket"] == action["action_type"] == "action"
    assert action["action_type_label"] == "action"
    assert action["resource_costs"] == []
    assert action["resource_gains"] == []
    assert action["resource_requirements"] == []
    assert action["source_packet_ids"] == ["packet.test"]


def test_simple_numeric_resource_cost_becomes_typed_transaction() -> None:
    description = _complete_description(cost="1 CP")
    documents = produce_action_documents(
        [_card(description)],
        projection_provenance=_locked_provenance(description),
    )
    surface = documents["Complete_Action_Surface.json"]

    assert surface["execution_authority"] is True
    [action] = surface["actions"]
    assert action["resource_costs"] == [{
        "resource_id": "RES_CP",
        "amount": 1,
        "timing": "When the action is declared and confirmed legal.",
        "condition": "Always for a legal use of this action.",
    }]
    assert action["resource_gains"] == []
    assert action["resource_requirements"] == [{
        "resource_id": "RES_CP",
        "minimum": 1,
        "condition": "The resource must be available before the action resolves.",
    }]


def test_unknown_expend_resource_fails_closed() -> None:
    projection, error = _resource_projection_from_description(
        _complete_description(cost="Expend Unlisted Focus"),
        record_id="talent.test",
        display_name="Test Art",
    )

    assert projection is None
    assert error == "explicit_unknown_resource"
    documents = produce_action_documents(
        [_card(_complete_description(cost="Expend Unlisted Focus"))],
        projection_provenance=_locked_provenance(_complete_description(cost="Expend Unlisted Focus")),
    )
    [candidate] = documents["Action_Authoring_Candidates.json"]["candidates"]
    assert candidate["resource_costs"] == []
    assert {"resource_costs", "resource_gains", "resource_requirements"}.issubset(candidate["missing_fields"])


def test_nonrecipe_prepared_prose_preserves_compound_action_cost() -> None:
    description = _complete_description(cost="1 CP and one Reagent Stock") + (
        "\nRelease one prepared alchemical formula when the action resolves."
    )
    projection, error = _resource_projection_from_description(
        description,
        record_id="TAL_ALCHEMY_BASE_FIELD_FORMULA",
        display_name="Alchemy Base Field Formula",
    )

    assert error is None
    assert projection is not None
    assert [row["resource_id"] for row in projection["resource_costs"]] == [
        "RES_CP",
        "RES_REAGENT_STOCK",
    ]
    assert not any(
        row["resource_id"] == "RES_PREPARED_ALCHEMICAL_FORMULA"
        for row in projection["resource_costs"]
    )


def test_prepared_item_source_cost_ignores_recipe_costs_and_consumes_one_item() -> None:
    description = _prepared_description()
    record_id = "TAL_ALCHEMY_EXPLOSIVE_PILL"
    documents = produce_action_documents(
        [_card(description, record_id=record_id, display_name="Explosive Pill")],
        projection_provenance=_locked_provenance(
            description,
            record_id=record_id,
            display_name="Explosive Pill",
        ),
    )

    [action] = documents["Complete_Action_Surface.json"]["actions"]
    assert action["cost"] == "one prepared Explosive Pill"
    assert action["resource_costs"] == [{
        "resource_id": "RES_PREPARED_EXPLOSIVE_PILL",
        "amount": 1,
        "timing": "When the action is declared and confirmed legal.",
        "condition": "Always for a legal use of this action.",
    }]
    assert action["resource_requirements"] == [{
        "resource_id": "RES_PREPARED_EXPLOSIVE_PILL",
        "minimum": 1,
        "condition": "The resource must be available before the action resolves.",
    }]
    assert action["non_action_costs"] == [
        {"context": "ingredient", "value": "150 gp."},
        {"context": "refinement", "value": "3 CP."},
    ]


@pytest.mark.parametrize(
    "action_sentence",
    [
        "Consume one prepared Explosive Pill.",
        "Also throw or launch one prepared Explosive Pill.",
        "Throw or launch one prepared Explosive Pill now.",
        "Throw or launch one prepared Explosive Pill!",
        "throw or launch one prepared Explosive Pill.",
    ],
)
def test_prepared_item_source_requires_exact_canonical_action_sentence(action_sentence: str) -> None:
    description = _prepared_description(action_sentence=action_sentence)

    projection, error = _resource_projection_from_description(
        description,
        record_id="TAL_ALCHEMY_EXPLOSIVE_PILL",
        display_name="Explosive Pill",
    )

    assert projection is None
    assert isinstance(error, str) and error


def test_prepared_item_source_rejects_name_mismatch_and_duplicate_sentence() -> None:
    mismatch = _prepared_description(item_name="Different Pill")
    duplicate = _prepared_description() + "\nThrow or launch one prepared Explosive Pill."

    for description in (mismatch, duplicate):
        projection, error = _resource_projection_from_description(
            description,
            record_id="TAL_ALCHEMY_EXPLOSIVE_PILL",
            display_name="Explosive Pill",
        )
        assert projection is None
        assert isinstance(error, str) and error


def test_prepared_item_source_rejects_unrelated_cost_context_without_promoting_it() -> None:
    description = _prepared_description().replace(
        "Refinement\nCost: 3 CP.\n",
        "Refinement\nCost: 3 CP.\nCrafting\nCost: 1 Qi\n",
        1,
    )
    projection, error = _resource_projection_from_description(
        description,
        record_id="TAL_ALCHEMY_EXPLOSIVE_PILL",
        display_name="Explosive Pill",
    )

    assert projection is None
    assert error == "recipe_cost_context_invalid"
    documents = produce_action_documents(
        [_card(description, record_id="TAL_ALCHEMY_EXPLOSIVE_PILL", display_name="Explosive Pill")],
        projection_provenance=_locked_provenance(
            description,
            record_id="TAL_ALCHEMY_EXPLOSIVE_PILL",
            display_name="Explosive Pill",
        ),
    )
    assert documents["Complete_Action_Surface.json"]["actions"] == []
    assert "RES_QI" not in json.dumps(documents["Action_Authoring_Candidates.json"], sort_keys=True)


def test_conditional_resource_cost_stays_visible_but_non_executable() -> None:
    description = _complete_description(cost="0 Qi; expend 1 Drive only if the recorded rider is used")
    documents = produce_action_documents(
        [_card(description)],
        projection_provenance=_locked_provenance(description),
    )
    surface = documents["Complete_Action_Surface.json"]
    [candidate] = documents["Action_Authoring_Candidates.json"]["candidates"]

    assert surface["actions"] == []
    assert surface["execution_authority"] is False
    assert candidate["parsed_resource_costs"]
    assert {"resource_costs", "resource_gains", "resource_requirements"}.issubset(candidate["missing_fields"])


@pytest.mark.parametrize(
    ("cost", "default_costs", "labels"),
    (
        ("2 CP or 2 Stamina", [("RES_CP", 2)], ("2 CP", "2 Stamina")),
        ("1 CP or Stamina.", [("RES_CP", 1)], ("1 CP", "Stamina")),
        ("1 Stamina or 1 CP", [("RES_CP", 1)], ("1 Stamina", "1 CP")),
        ("1 CP or expend Martial Focus.", [("RES_CP", 1)], ("1 CP", "expend Martial Focus")),
        ("Expend Martial Focus or spend 1 CP.", [("RES_CP", 1)], ("Expend Martial Focus", "spend 1 CP")),
        (
            "Expend Martial Focus if you have it, or spend 5 CP if you do not.",
            [("RES_CP", 5)],
            ("Expend Martial Focus if you have it", "spend 5 CP if you do not"),
        ),
        (
            "2 CP, 2 Stamina, or expend Martial Focus and 1 CP/Stamina",
            [("RES_CP", 2)],
            ("2 CP", "2 Stamina", "expend Martial Focus and 1 CP", "expend Martial Focus and 1 Stamina"),
        ),
        (
            "3 CP or 3 Stamina if created through Body as Cauldron",
            [("RES_CP", 3)],
            ("3 CP", "3 Stamina if created through Body as Cauldron"),
        ),
        ("1 CP, 1 Stamina, or 1 Devoured Essence", [("RES_CP", 1)], ("1 CP", "1 Stamina", "1 Devoured Essence")),
    ),
)
def test_alternative_resource_cost_projects_a_choice_with_an_executable_default(cost: str, default_costs: list, labels: tuple) -> None:
    # 158 compendium talents offer a choice of payments.  The action executes
    # with the generic-pool option as its default and carries every option so
    # the table can honour the source; nothing is typed as a bogus resource.
    description = _complete_description(cost=cost)
    documents = produce_action_documents(
        [_card(description)],
        projection_provenance=_locked_provenance(description),
    )
    surface = documents["Complete_Action_Surface.json"]
    [action] = surface["actions"]
    [candidate] = documents["Action_Authoring_Candidates.json"]["candidates"]

    assert surface["execution_authority"] is True
    assert candidate["executable"] is True
    assert cost.rstrip(".") in action["cost"]
    assert [(row["resource_id"], row["amount"]) for row in action["resource_costs"]] == default_costs
    assert [(row["resource_id"], row["minimum"]) for row in action["resource_requirements"]] == default_costs
    assert all("the source allows instead" in row["condition"] for row in action["resource_costs"])
    options = action["resource_cost_options"]
    assert tuple(option["label"] for option in options) == labels
    assert sum(1 for option in options if option["default"] is True) == 1
    default = next(option for option in options if option["default"])
    assert [(row["resource_id"], row["amount"]) for row in default["resource_costs"]] == default_costs
    assert all(option["resource_costs"] and option["resource_requirements"] for option in options)
    assert not any("_OR" in row["resource_id"] for option in options for row in option["resource_costs"])
    projection, error = _resource_projection_from_description(description, expected_action_type="action")
    assert error is None
    assert projection["projection_kind"] == "explicit_resource_cost_choice_complete"
    assert projection["resource_cost_options"] == options


@pytest.mark.parametrize(
    ("cost", "expected"),
    (
        ("0 CP", []),
        ("Spend 1 Forge Mark", [("RES_FORGE_MARK", 1)]),
        ("Spend a Monkey Link", [("RES_MONKEY_LINK", 1)]),
        ("3 CP and two Reagent Stock.", [("RES_CP", 3), ("RES_REAGENT_STOCK", 2)]),
    ),
)
def test_zero_spend_and_number_word_costs_are_typed(cost: str, expected: list) -> None:
    description = _complete_description(cost=cost)
    documents = produce_action_documents(
        [_card(description)],
        projection_provenance=_locked_provenance(description),
    )
    [action] = documents["Complete_Action_Surface.json"]["actions"]
    assert [(row["resource_id"], row["amount"]) for row in action["resource_costs"]] == expected
    assert action["resource_cost_options"] == []


def test_conditional_choice_options_keep_their_source_conditions() -> None:
    description = _complete_description(cost="Expend Martial Focus if you have it, or spend 5 CP if you do not.")
    documents = produce_action_documents(
        [_card(description)],
        projection_provenance=_locked_provenance(description),
    )
    [action] = documents["Complete_Action_Surface.json"]["actions"]
    focus, points = action["resource_cost_options"]
    assert focus["condition"] == "if you have it"
    assert focus["resource_costs"][0]["resource_id"] == "RES_MARTIAL_FOCUS"
    assert focus["default"] is False
    assert points["condition"] == "if you do not"
    assert points["default"] is True
    assert action["resource_costs"][0]["condition"].endswith("Expend Martial Focus if you have it.")


@pytest.mark.parametrize(
    ("cost", "reason"),
    (
        ("Spend 1 or more Forge Marks", "explicit_resource_cost_variable"),
        (
            "25,000 gp, a Phoenix Feather or equivalent rebirth material, the heart or core of a CR 20+ creature",
            "explicit_resource_cost_alternative_unparsed",
        ),
        ("2 CP or 2 Reagent Stock", "explicit_resource_cost_alternative_unparsed"),
    ),
)
def test_unparseable_alternative_cost_stays_visible_but_non_executable(cost: str, reason: str) -> None:
    description = _complete_description(cost=cost)
    documents = produce_action_documents(
        [_card(description)],
        projection_provenance=_locked_provenance(description),
    )
    surface = documents["Complete_Action_Surface.json"]
    [candidate] = documents["Action_Authoring_Candidates.json"]["candidates"]

    assert surface["actions"] == []
    assert candidate["cost"] == cost
    assert candidate["resource_costs"] == []
    assert candidate["resource_cost_options"] == []
    assert {"resource_costs", "resource_gains", "resource_requirements"}.issubset(candidate["missing_fields"])
    projection, error = _resource_projection_from_description(description, expected_action_type="action")
    assert projection is None
    assert error == reason


def test_scalar_cost_does_not_absorb_following_rules_paragraph() -> None:
    description = _complete_description(cost="2 Qi").replace(
        "Cost: 2 Qi\nRange:",
        "Cost: 2 Qi\n\nThis prose belongs to the rules body, not the cost.\n\nRange:",
    )
    documents = produce_action_documents(
        [_card(description)],
        projection_provenance=_locked_provenance(description),
    )

    [action] = documents["Complete_Action_Surface.json"]["actions"]
    assert action["cost"] == "2 Qi"
    assert action["resource_costs"][0]["resource_id"] == "RES_QI"


def test_unlabelled_prose_cannot_fill_required_action_fields() -> None:
    card = _card("Action Type: Action\nFactory Combat Bucket: action\nCost: None\nIt probably hits a nearby enemy very hard.")
    documents = produce_action_documents([card])
    [candidate] = documents["Action_Authoring_Candidates.json"]["candidates"]

    assert documents["Complete_Action_Surface.json"]["actions"] == []
    assert {"range", "target", "roll_save_check", "effect", "failure", "duration", "limit", "counterplay"}.issubset(
        candidate["missing_fields"]
    )


def test_locked_typed_choice_mechanics_replace_short_display_projection() -> None:
    card = _card("Action Type: Action", record_id="talent.rich")
    provenance = {
        "typed_choice_snapshot_sha256": "c" * 64,
        "typed_choice_snapshot": {
            "typed_locks": [
                {
                    "value": {
                        "talent_dispositions": [
                            {
                                "canonical_talent_id": "talent.rich",
                                "owning_canonical_sphere_id": "sphere.test",
                                "display_name": "Test Art",
                                "full_description": _complete_description(),
                                "short_description": "The retained canonical mechanics.",
                                "source_reference": {"path": "catalog.md", "anchor": "rich"},
                            }
                        ]
                    }
                }
            ]
        },
    }

    documents = produce_action_documents([card], projection_provenance=provenance)
    [action] = documents["Complete_Action_Surface.json"]["actions"]

    assert action["full_description"] == _complete_description()
    assert action["one_line_description"] == "The retained canonical mechanics."
    assert action["mechanics_source"]["authority"] == "locked_typed_choice_snapshot"
    assert action["mechanics_source"]["typed_choice_snapshot_sha256"] == "c" * 64


def test_fully_labelled_same_id_prose_outside_typed_lock_cannot_execute() -> None:
    provenance = {
        "typed_choice_snapshot": {
            "display_rows": [
                {
                    "canonical_talent_id": "talent.test",
                    "owning_canonical_sphere_id": "sphere.test",
                    "full_description": _complete_description(),
                }
            ],
            "typed_locks": [
                {"value": {"unrelated_display_copy": {"canonical_talent_id": "talent.test", "full_description": _complete_description()}}},
            ]
        }
    }
    documents = produce_action_documents([_card(_complete_description())], projection_provenance=provenance)

    assert documents["Complete_Action_Surface.json"]["actions"] == []
    [candidate] = documents["Action_Authoring_Candidates.json"]["candidates"]
    assert "unambiguous_locked_mechanics_source" in candidate["missing_fields"]
    assert candidate["mechanics_source"] is None


def test_ambiguous_rows_inside_typed_lock_fail_closed() -> None:
    provenance = {
        "typed_choice_snapshot": {
            "typed_locks": [
                {
                    "value": {
                        "talent_dispositions": [
                            {
                                "canonical_talent_id": "talent.test",
                                "owning_canonical_sphere_id": "sphere.test",
                                "full_description": _complete_description(),
                            },
                            {
                                "canonical_talent_id": "talent.test",
                                "owning_canonical_sphere_id": "sphere.other",
                                "full_description": _complete_description() + "\nDifferent.",
                            },
                        ]
                    }
                }
            ]
        }
    }
    documents = produce_action_documents([_card("Action Type: Action")], projection_provenance=provenance)

    assert documents["Complete_Action_Surface.json"]["execution_authority"] is False
    assert any(
        row["status"] == "NON_EXECUTABLE_AMBIGUOUS_SOURCE"
        for row in documents["Complete_Action_Surface.json"]["unresolved"]
    )


def test_command5_prefers_post_workspace_surface_and_preserves_legacy_fallback(tmp_path: Path) -> None:
    display = [{"record_id": "display.only", "display_only_not_execution_authority": True}]
    legacy = CharacterGMCommand5Profile._action_surface(tmp_path, display)
    assert legacy["status"] == "LEGACY_DISPLAY_ONLY_FALLBACK"
    assert legacy["actions"] == display
    assert legacy["execution_authority"] is False

    command4 = tmp_path / "Command_4"
    command4.mkdir()
    typed = {
        "schema_version": "TianxiaFoundry.Command4CompleteActionSurface.v1",
        "status": "ACTION_SURFACE_READY",
        "actions": [{"action_id": "action.1"}],
        "execution_authority": True,
        "global_combat_readiness": False,
        "unresolved": [],
    }
    (command4 / "Complete_Action_Surface.json").write_text(json.dumps(typed), encoding="utf-8")
    assert CharacterGMCommand5Profile._action_surface(tmp_path, display) == typed


def test_command5_rejects_malformed_post_workspace_surface(tmp_path: Path) -> None:
    command4 = tmp_path / "Command_4"
    command4.mkdir()
    (command4 / "Complete_Action_Surface.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FoundryError) as exc_info:
        CharacterGMCommand5Profile._action_surface(tmp_path, [])
    assert exc_info.value.code == "CHARACTER_GM_ACTION_SURFACE_INVALID"
