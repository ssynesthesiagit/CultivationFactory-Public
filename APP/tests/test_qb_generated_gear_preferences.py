from __future__ import annotations

from character_creation.service import CharacterCreationExecutionService


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
    if owner_concept is not None:
        locks.append({"field": "concept", "value": owner_concept})
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


def test_seeded_generated_saber_concept_is_kit_preference_only(catalog_environment):
    request = _request(catalog_environment, seed="QB-000018")

    assert request["owner_gear_preferences"] == ["tianxia.mortal.weapon.dao"]
    assert "owner_gear_requirements" not in request


def test_owner_locked_weapon_concept_wins_over_seeded_identity(catalog_environment):
    request = _request(
        catalog_environment,
        seed="QB-000018",
        owner_concept="A fighter who carries a meteor hammer.",
    )

    assert request["owner_gear_preferences"] == ["tianxia.mortal.weapon.liu_xing_chui"]
    assert request["owner_gear_requirements"] == [{
        "item_id": "tianxia.mortal.weapon.liu_xing_chui",
        "name": "Liu Xing Chui (Meteor Hammer)",
    }]
