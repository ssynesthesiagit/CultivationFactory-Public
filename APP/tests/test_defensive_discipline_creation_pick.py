"""DEFDISC1 finding 1: a new Body Refiner or Qi Cultivator records its Defensive Discipline at creation.

The CL1 Path features are offered, an unknown or non-offered pick is rejected before saving, and a recorded pick
reaches the owner sheet's path_and_subpath.feature_build_choices, where the compiler reads it as chosen."""
import pytest

from app.core import FoundryError
from character_builder.service import CharacterBuilderService
from character_creation.feature_choices import creation_features, resolve
from character_sheet.service import CharacterSheetService
from combat.typed_reactions import compile_blocks
from project_store.service import ProjectStore

BODY = "tianxia.path.body_refining"
QI = "tianxia.path.qi_cultivation"
TEMPERED = "tianxia.path.body_refining.feature.tempered_response"
CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"
SAVES = {"STR": 2, "DEX": 3, "CON": 1, "INT": 0, "CHA": 0}


def test_creation_offers_the_cl1_discipline_for_each_new_path():
    assert TEMPERED in [row["canonical_id"] for row in creation_features([BODY])]
    assert CULTIVATED in [row["canonical_id"] for row in creation_features([QI])]


def test_creation_rejects_an_unknown_option_and_a_pick_for_a_feature_not_gained():
    with pytest.raises(FoundryError):
        resolve(creation_features([BODY]), {TEMPERED: "not-an-option"}, required=False)
    with pytest.raises(FoundryError):
        resolve(creation_features([BODY]), {CULTIVATED: "dex"}, required=False)


def test_a_creation_pick_reaches_the_sheet_and_the_compiler_reads_it_as_chosen():
    project = {"user_locks": [{"field": "character_sheet.feature_choices", "value": {TEMPERED: "dex"}}]}
    grants = CharacterSheetService._creation_feature_choices(project, [TEMPERED])
    assert grants == {TEMPERED: {"choice": "dex", "defensive_discipline": "DEX"}}
    rows = compile_blocks([TEMPERED], pb=2, key_mod=0, saves=SAVES, resource_ids={"stamina": "stamina"}, cl=1,
                          mechanics={}, build_choices=grants)
    row = next(r for r in rows["reactions"] if r.get("block") == "save_rescue")
    assert row["abilities"] == ["DEX"] and row["chosen"] is True


def test_a_character_built_without_a_creation_pick_gets_no_grant():
    assert CharacterSheetService._creation_feature_choices({"user_locks": []}, [TEMPERED]) == {}


def _create(db, path, feature_choices):
    return CharacterBuilderService(db).create_project(
        working_name="Defensive Discipline Test",
        concept="A steady fighter who relies on firm footing.",
        target_cl=15,
        power_band="heroic",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={"STR": 15, "CON": 14, "WIS": 12},
        selections={"path_choice": [path]},
        feature_choices=feature_choices,
    )


def test_creation_pick_is_stored_on_the_project_and_survives_reload(catalog_environment):
    created = _create(catalog_environment["db"], BODY, {TEMPERED: "dex"})
    reloaded = ProjectStore(catalog_environment["db"]).get_project(created["project"]["project_id"])
    grants = CharacterSheetService._creation_feature_choices(reloaded, [TEMPERED])
    assert grants == {TEMPERED: {"choice": "dex", "defensive_discipline": "DEX"}}


def test_creation_rejects_a_pick_for_a_feature_the_character_does_not_gain(catalog_environment):
    with pytest.raises(FoundryError):
        _create(catalog_environment["db"], BODY, {CULTIVATED: "dex"})
