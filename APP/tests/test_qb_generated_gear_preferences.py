from __future__ import annotations

from character_creation.service import CharacterCreationExecutionService

BG = "tianxia.background.abandoned_orphan"
PATH = "tianxia.path.body_refining"
METEOR_HAMMER = "tianxia.mortal.weapon.liu_xing_chui"
DAO = "tianxia.mortal.weapon.dao"
# A Background with no printed starting kit in the kit authority.
NO_KIT_BACKGROUND = "tianxia.background.no_printed_kit_for_test"


def _request(catalog_environment, *, seed: str, owner_concept: str | None = None, gear_preferences=None):
    from character_builder import CharacterBuilderService
    from project_store.service import ProjectStore
    from stage1.service import Stage1ClipboardService

    db = catalog_environment["db"]
    project = CharacterBuilderService(db).create_project(
        working_name="Seeded gear preference regression",
        concept=owner_concept or "",
        target_cl=1,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={},
    )
    store = ProjectStore(db)
    locks = [{"field": "character_creation.autogen_seed", "value": seed}]
    if gear_preferences is not None:
        locks.append({"field": "character_sheet.gear_preferences", "value": gear_preferences})
    store.append_user_locks(project["project_id"], locks)
    service = CharacterCreationExecutionService(
        db, stage1=Stage1ClipboardService(db), provider=None, project_store=store,
    )
    return service._complete_request(
        project["project_id"],
        execution_mode="MANUAL_CHAT",
        idempotency_key=f"seeded-gear:{seed}",
    )


def test_seeded_generated_saber_concept_is_kit_hint_not_owner_gear(catalog_environment):
    request = _request(catalog_environment, seed="QB-000018")

    # Seeded concept gear is an optional kit hint. Owner gear preferences
    # become required kit gear and owner-gear warnings, so they must stay empty.
    assert request["kit_hint_gear_ids"] == [DAO]
    assert "owner_gear_preferences" not in request
    assert "owner_gear_requirements" not in request
    assert "owner_gear_warnings" not in request


def test_seeded_concept_gear_never_becomes_required_gear_across_seeds(catalog_environment):
    seeds = ["QB-000018", "QB-000001", "QB-000002", "QB-000003", "QB-000004", "QB-000005"]
    hinted = []
    for seed in seeds:
        request = _request(catalog_environment, seed=seed)
        assert "owner_gear_requirements" not in request, seed
        assert "owner_gear_preferences" not in request, seed
        if request.get("kit_hint_gear_ids"):
            hinted.append(seed)
    assert "QB-000018" in hinted


def test_seeded_hint_adds_no_requirement_or_warning_for_a_background_without_a_kit(catalog_environment):
    request = _request(catalog_environment, seed="QB-000018")
    # The seeded hint must not reach the kit walk as owner gear for a no-kit Background.
    assert not request.get("owner_gear_preferences")
    assert not request.get("owner_gear_requirements")
    run = {"request": request}
    intent = {
        "acquisition_intent": {},
        "selected_by_slot": {"background_choice": [NO_KIT_BACKGROUND], "path_choice": [PATH]},
        "bounded_choices": {},
    }

    result = CharacterCreationExecutionService._starting_kit_construction(
        intent, "seeded-hint-no-kit", 1,
        owner_gear_preferences=request.get("owner_gear_preferences") or [],
        owner_gear_requirements=request.get("owner_gear_requirements") or [],
        run=run,
    )

    assert result is None
    assert "_derived_owner_gear_warnings" not in run


def test_seeded_saber_hint_reaches_resolved_forest_hermit_kit(catalog_environment):
    from character_creation.creative_controller.linear_menus import CommittedState, build_step_menu
    from character_creation.creative_controller.linear_walk import commit_option
    from character_creation.creative_controller.seeded_picker import choose_option
    from factory_authoring.starting_kits import choice_menus

    background = "tianxia.background.forest_hermit"
    request = _request(catalog_environment, seed="QB-000018")
    state = CommittedState(by_slot={"background_choice": [background], "path_choice": [PATH]})
    menu = build_step_menu(request, {}, state, step_id="starting_kit_option")
    assert {option.choice_ids for option in menu.options} == {("option_a",), ("option_b",)}
    option_a = next(option for option in menu.options if option.choice_ids == ("option_a",))
    state = commit_option(menu, option_a.option_id, state)
    for row in choice_menus(background, PATH, "option_a"):
        menu = build_step_menu(request, {}, state, step_id="starting_kit_choice:" + row["choice_id"])
        state = commit_option(menu, choose_option("QB-000018", menu, prefer_insights=True), state)

    intent = {
        "acquisition_intent": {"starting_kit": state.bounded["starting_kit"]},
        "selected_by_slot": {"background_choice": [background], "path_choice": [PATH]},
        "bounded_choices": {},
    }
    kit, _ = CharacterCreationExecutionService._starting_kit_construction(
        intent, "seeded-saber-kit", 1, run={"request": request},
    )
    assert DAO in {item["item_id"] for item in kit["items"]}


def test_explicit_gear_preference_lock_wins_over_seeded_identity(catalog_environment):
    request = _request(
        catalog_environment,
        seed="QB-000018",
        gear_preferences=["tianxia.mortal.weapon.jian"],
    )

    assert request["owner_gear_preferences"] == ["tianxia.mortal.weapon.jian"]
    assert "owner_gear_requirements" not in request
    assert "kit_hint_gear_ids" not in request


def test_owner_locked_weapon_concept_wins_over_seeded_identity(catalog_environment):
    request = _request(
        catalog_environment,
        seed="QB-000018",
        owner_concept="A fighter who carries a meteor hammer.",
    )

    assert request["owner_gear_preferences"] == [METEOR_HAMMER]
    assert request["owner_gear_requirements"] == [{
        "item_id": METEOR_HAMMER,
        "name": "Liu Xing Chui (Meteor Hammer)",
    }]
    assert "kit_hint_gear_ids" not in request
