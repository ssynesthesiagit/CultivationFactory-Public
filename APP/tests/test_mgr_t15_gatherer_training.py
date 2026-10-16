"""Native Training and Tools acquisition, installed-sheet reload and item replay.

All characters and durable data are generated under pytest's queued basetemp.
No model or network transport is used. The service and installed zip are real.
"""
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from app.models import TabletopAdvanceRequest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat import carry, table_advance
from combat.ext.gatherer_training import SOURCE, SPHERE, KIT_ID, CONTENTS, TEXT_SHA256
from combat.factory_compiler import compile_character, equipment_list
from combat.gate5_service import CombatService
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
PID = "0badc0de-0000-4000-8000-000000000015"
FOE = "0badc0de-0000-4000-8000-000000000016"
OWNER = "actor:factory." + PID
PATH = "tianxia.path.qi_cultivation"
BACKGROUND = "tianxia.background.abandoned_orphan"
BONUS = "tianxia.talent.harvesting_gathering.field_ledger"


def sheet(*, trained=None, cl=1):
    return {
        "identity": {"display_name": "Gatherer", "cultivation_level": cl, "proficiency_bonus": 2,
                     "path_ids": [PATH], "key_ability": "CON"},
        "path_and_subpath": {"path_record_id": PATH, "path_record_ids": [PATH]},
        "background_origin": {"background": {"background_id": BACKGROUND}},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": key, "score": 14, "modifier": 2}
                          for key in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "armor_class": {"base_value": 12}, "hit_points": {"maximum": 30},
            "primary_resource": {"name": "Qi", "maximum": 10}, "speed": {"walking_ft": 30},
            "technique_save_dc": 12, "technique_attack_bonus": 4,
            "skills": [{"skill": trained, "bonus": 4, "proficient": True, "proficiency_multiplier": 1}]
                      if trained in {"Nature", "Survival", "Medicine"} else [],
        },
        "proficiencies": {"skills": [trained] if trained in {"Nature", "Survival", "Medicine"} else [],
                          "tools": [trained] if trained and trained not in {"Nature", "Survival", "Medicine"} else []},
        "spheres_and_talents": {"sphere_record_ids": [], "automatic_sphere_component_record_ids": [],
                               "learned_talent_record_ids": []}, "equipment": [],
    }


def install(root, document, pid=PID):
    folder = root / "portable_characters" / pid
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))


@pytest.fixture(scope="module")
def catalog():
    return CanonicalCatalogAuthorityService(ROOT)


def services(root, catalog):
    combat = CombatService(ROOT, root)
    table = TabletopService(combat, root)
    table.canonical_catalog = catalog
    return combat, table


def acquire(table, proficiency="Nature", *, gm=False, **choices):
    # The same validated model and native caller as the public advancement API.
    request = TabletopAdvanceRequest.model_validate({"kind": "sphere", "record_id": SPHERE,
        "gm": gm, "learning": {"proficiency": proficiency, **choices}})
    return table.add_advancement(PID, request.kind, request.record_id, gm=request.gm, learning=request.learning)


def assignment(by):
    return {"by": by, "background_id": BACKGROUND, "path_id": PATH}


def test_exact_source_hash_and_inert_unselected_control(tmp_path, catalog):
    text = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[SOURCE]
    assert hashlib.sha256(text.encode()).hexdigest() == TEXT_SHA256
    base = sheet()
    install(tmp_path, base)
    combat, table = services(tmp_path, catalog)
    assert combat._factory_owner_sheet(PID) == base
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError, match="proficiency choice"):
        table.add_advancement(PID, "sphere", SPHERE)
    assert table.buttons.get(PID) == before
    assert combat._factory_owner_sheet(PID) == base
    assert not equipment_list(base)["items"]


@pytest.mark.parametrize("proficiency", ["Nature", "Survival", "Medicine", "Herbalism Kit", "Land Vehicles",
                                        "Woodcarver’s Tools", "Mason’s Tools", "Cartographer’s Tools", "Weaver’s Tools"])
def test_every_printed_proficiency_class_persists_and_compiles(tmp_path, catalog, proficiency):
    base = sheet()
    # Real portable sheets also carry JSON-encoded statistics.
    base["ability_scores_and_statistics"]["abilities"] = json.dumps(base["ability_scores_and_statistics"]["abilities"])
    base["ability_scores_and_statistics"]["skills"] = "[]"
    install(tmp_path, base)
    combat, table = services(tmp_path, catalog)
    artisan = proficiency not in {"Nature", "Survival", "Medicine", "Herbalism Kit", "Land Vehicles"}
    args = {"artisan_ruling": {"tool": proficiency, "reason": "This artisan tool can prepare and preserve gathered field materials."}} if artisan else {}
    acquire(table, proficiency, gm=artisan, **args)
    fresh, reopened = services(tmp_path, catalog)
    actual = fresh._factory_owner_sheet(PID)
    group = "skills" if proficiency in {"Nature", "Survival", "Medicine"} else "tools"
    assert actual["proficiencies"][group] == [proficiency]
    assert SOURCE in actual["spheres_and_talents"]["automatic_sphere_component_record_ids"]
    assert not actual["spheres_and_talents"]["learned_talent_record_ids"]
    assert not equipment_list(actual)["items"]
    assert table_advance.apply(actual, reopened.buttons.get(PID)["advancement"]) == actual
    bundle = compile_character(actual, actor_id=OWNER)
    if group == "skills":
        summary = reopened.sheet(PID)["summary"]
        assert next(row["bonus"] for row in summary["skills"] if row["skill"] == proficiency) == 4
    assert bundle["actor_id"] == OWNER
    with pytest.raises(TabletopError, match="already recorded"):
        acquire(reopened, proficiency, gm=artisan, **args)
    assert fresh._factory_owner_sheet(PID) == actual


@pytest.mark.parametrize("proficiency", ["Nature", "Herbalism Kit", "Land Vehicles", "Woodcarver’s Tools"])
def test_already_proficient_gets_one_mortal_bonus_without_changing_training(tmp_path, catalog, proficiency):
    base = sheet(trained=proficiency)
    install(tmp_path, base)
    combat, table = services(tmp_path, catalog)
    artisan = proficiency == "Woodcarver’s Tools"
    args = {"artisan_ruling": {"tool": proficiency, "reason": "Suitable for cutting and preparing gathered wood."}} if artisan else {}
    acquire(table, proficiency, gm=artisan, bonus_talent_id=BONUS, **args)
    fresh, reopened = services(tmp_path, catalog)
    actual = fresh._factory_owner_sheet(PID)
    assert actual["proficiencies"] == base["proficiencies"]
    assert actual["spheres_and_talents"]["learned_talent_record_ids"] == [BONUS]
    saved = reopened.buttons.get(PID)["advancement"]
    assert saved["talents"] == []  # attached to its source, no ordinary talent slot
    learning = saved["spheres"][0]["learning"]
    assert learning["already_proficient"] == 1
    assert learning["source"] == {"record_id": SOURCE, "text_sha256": TEXT_SHA256}
    assert table_advance.apply(actual, saved) == actual


@pytest.mark.parametrize("choice", [
    {}, {"bonus_talent_id": "not-a-talent"},
    {"bonus_talent_id": "tianxia.talent.harvesting_gathering.spirit_herb_appraisal"},
    {"bonus_talent_id": "TAL_ATHLETICS_WALL_STUNT"},
    {"bonus_talent_id": [BONUS, BONUS]},
])
def test_invalid_or_nonmortal_bonus_never_commits_even_with_gm_override(tmp_path, catalog, choice):
    install(tmp_path, sheet(trained="Nature", cl=10))
    combat, table = services(tmp_path, catalog)
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        acquire(table, "Nature", gm=True, **choice)
    assert table.buttons.get(PID) == before
    assert SPHERE not in combat._factory_owner_sheet(PID)["spheres_and_talents"]["sphere_record_ids"]


def test_duplicate_bonus_is_rejected(tmp_path, catalog):
    base = sheet(trained="Nature")
    base["spheres_and_talents"]["learned_talent_record_ids"] = [BONUS]
    install(tmp_path, base)
    _, table = services(tmp_path, catalog)
    with pytest.raises(TabletopError):
        acquire(table, bonus_talent_id=BONUS)


def test_later_proficiency_cannot_manufacture_a_retroactive_learning_bonus(tmp_path, catalog):
    base = sheet(trained="Nature")
    base["spheres_and_talents"]["sphere_record_ids"] = [SPHERE]
    install(tmp_path, base)
    combat, table = services(tmp_path, catalog)
    with pytest.raises(TabletopError, match="when the Sphere is learned"):
        acquire(table, gm=True, bonus_talent_id=BONUS)
    assert combat._factory_owner_sheet(PID) == base
    assert not (table.buttons.get(PID).get("advancement") or {}).get("spheres")


@pytest.mark.parametrize("gm,ruling", [(False, {"tool": "Weaver’s Tools", "reason": "Preserving field materials"}),
                                       (True, None), (True, {"tool": "Mason’s Tools", "reason": "Wrong tool"}),
                                       (True, {"tool": "Weaver’s Tools", "reason": ""})])
def test_artisan_suitability_needs_the_actual_gm_tool_decision(tmp_path, catalog, gm, ruling):
    install(tmp_path, sheet())
    _, table = services(tmp_path, catalog)
    with pytest.raises(TabletopError):
        acquire(table, "Weaver’s Tools", gm=gm, artisan_ruling=ruling)
    assert not (table.buttons.get(PID).get("advancement") or {}).get("spheres")


@pytest.mark.parametrize("by", ["class", "background"])
def test_actual_starting_assignment_delivers_one_exact_kit_cold_reload_and_item_replay(tmp_path, catalog, by):
    install(tmp_path, sheet())
    install(tmp_path, sheet(), FOE)
    combat, table = services(tmp_path, catalog)
    acquire(table, equipment_assignment=assignment(by))
    fresh, reopened = services(tmp_path, catalog)
    actual = fresh._factory_owner_sheet(PID)
    kit = actual["equipment"][0]["starting_kit"]
    [item] = [row for row in kit["items"] if row["item_id"] == KIT_ID]
    assert item["quantity"] == 1 and item["contents"] == list(CONTENTS)
    assert item["source"] == SOURCE and item["source_reference"]["text_sha256"] == TEXT_SHA256
    assert kit["background_id"] == BACKGROUND and kit["path_id"] == PATH
    assert {row["source"] for row in kit["items"]} >= {"background", "path", SOURCE}
    assert len([row for row in equipment_list(actual)["items"] if row["item_id"] == KIT_ID]) == 1
    assert table_advance.apply(actual, reopened.buttons.get(PID)["advancement"]) == actual
    # Import the acquired character through native compilation/match creation.
    other = "actor:factory." + FOE
    view = fresh.create_factory_match(project_ids=[PID], opponent_actor_ids=[other],
        control_modes={OWNER: "MANUAL", other: "MANUAL"}, match_seed="GATHERER-ITEM-" + by)
    mid = view["match_id"]
    for _ in range(2):
        state = reopened.state(mid)
        if state["menu"]["actor_id"] == OWNER:
            break
        menu = state["menu"]
        assert reopened.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    for verb in ("Drop", "Pick up"):
        state = reopened.state(mid)
        menu = state["menu"]
        group = next(row for row in menu["actions"] if row["label"] == verb + " Basic gatherer’s kit")
        assert reopened.act(mid, group["options"][0]["candidate_id"], menu["decision_id"],
                            menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
        fresh, reopened = services(tmp_path, catalog)
        loaded = fresh._load_session(mid)
        actor = loaded.engine.state.actors[OWNER]
        assert carry.holds(loaded.engine, actor, KIT_ID) == (verb == "Pick up")
        assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("assignment_input", [True, {"by": "purchase"},
    {"by": "background", "background_id": "tianxia.background.exiled_noble", "path_id": PATH},
    {"by": "class", "background_id": BACKGROUND, "path_id": "tianxia.path.body_refining"}])
def test_no_invented_assignment_or_other_character_equipment(tmp_path, catalog, assignment_input):
    install(tmp_path, sheet())
    combat, table = services(tmp_path, catalog)
    with pytest.raises(TabletopError):
        acquire(table, equipment_assignment=assignment_input)
    assert combat._factory_owner_sheet(PID)["equipment"] == []
    assert not (table.buttons.get(PID).get("advancement") or {}).get("spheres")
