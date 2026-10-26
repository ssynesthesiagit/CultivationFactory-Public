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


def test_kit_hint_orders_both_kit_options_without_removing_any(catalog_environment):
    from character_creation.creative_controller.linear_menus import kit_option_order
    from factory_authoring.starting_kits import PATH_OPTIONS, preferred_kit_plan

    committed = {"by_slot": {"background_choice": [BG], "path_choice": [PATH]}, "bounded": {}}
    plan = preferred_kit_plan(BG, PATH, [METEOR_HAMMER])
    assert plan is not None
    order = kit_option_order({"kit_hint_gear_ids": [METEOR_HAMMER]}, {}, committed)

    assert order[0] == plan["path_option"]
    assert sorted(order) == sorted(PATH_OPTIONS)
    assert kit_option_order({}, {}, committed) == list(PATH_OPTIONS)


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
