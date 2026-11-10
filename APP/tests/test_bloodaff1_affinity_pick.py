"""BLOODAFF1: the Bloodline lineage and affinity are one build pick recorded on the sheet.

The pick is offered when Ancestral Bloodline Awakening is gained (CL3), a level with no pick is refused,
a recorded pick sets the single affinity condition with no combat action, a character that gained the
feature before the pick is pending until answered, and an affinity the lineage does not allow is refused.
"""
import pytest

from app.core import FoundryError
from character_creation.feature_choices import contracts, resolve
from combat.ext import ancestral_bloodline as bloodline
from combat.table_levelup import pending_feature_choices
from copy import deepcopy
import json
from pathlib import Path
import zipfile

from combat import table_advance as ta
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from stage2.ability_changes import published_path_records
from stage2.formulas import evaluate_formula

# Synthetic level-up fixture kept local so this test has no private-test imports.
ROOT = Path(__file__).resolve().parents[1]


PID = "0badc0de-0000-4000-8000-000000000003"


BODY = "tianxia.path.body_refining"


QI = "tianxia.path.qi_cultivation"


SCORES = {"STR": 12, "DEX": 14, "CON": 16, "INT": 16, "WIS": 12, "CHA": 8}


SPHERE = "tianxia.sphere.water"


TALENTS = [{"canonical_talent_id": f"synthetic.talent.{i}", "display_name": f"Practice {i}",
            "owning_canonical_sphere_id": SPHERE, "minimum_cl": 1,
            "typed_constraints": [{"kind": "minimum_cl", "value": 1}]} for i in range(6)]


def baseline(path):
    auth = published_path_records()[path]["compatibility"]["factory"]["stage2_authority"]
    context = {"cl": 1, "pb": 2, "ability_scores": SCORES,
               "ability_modifiers": {a: ta.ability_modifier(v) for a, v in SCORES.items()}}
    resource = auth["resources"][0]
    maximum = evaluate_formula(resource["base_formula"]["root"], context).value
    name = "Stamina" if path == BODY else "Qi"
    hp = evaluate_formula(auth["hp_level1_formula"]["root"], context).value
    return {"identity": {"name": "Synthetic cultivator", "cultivation_level": 1, "proficiency_bonus": 2,
                        "key_ability": auth["key_ability"], "path_ids": [path],
                        "paths": [{"path_id": path, "effective_cl": 1}]},
            "path_and_subpath": {"path_record_ids": [path],
                "path_feature_record_ids": auth["progression_by_cl"]["1"]["feature_record_ids"]},
            "spheres_and_talents": {"sphere_record_ids": [SPHERE], "learned_talent_record_ids": []},
            "ability_scores_and_statistics": {
                "abilities": [{"ability": a, "score": v, "modifier": ta.ability_modifier(v)} for a, v in SCORES.items()],
                "hit_points": {"maximum": hp, "build_state_current": hp - 2,
                    "progression": {"levels": [{"cl": 1, "gain": hp, "maximum": hp}]}},
                "primary_resource": {"name": name, "maximum": maximum, "build_state_current": maximum - 1,
                    "definitions": [{"name": name, "resource_id": resource["resource_id"],
                        "max": maximum, "current": maximum - 1, "base_formula": resource["base_formula"]}]},
                "saving_throw_proficiencies": ["CON", "INT"],
                "saving_throws": {a: ta.ability_modifier(v) + (2 if a in ["CON", "INT"] else 0) for a, v in SCORES.items()},
                "armor_class": {"base_value": 15 if path == BODY else 12, "value": 15 if path == BODY else 12},
                "technique_attack_bonus": 5, "technique_save_dc": 13, "initiative": {"ability": "DEX", "bonus": 2},
                "skills": [{"skill": "Lore", "ability": "INT", "bonus": 5, "proficient": True}],
                "speed": {"walking_ft": 30}}}


def service(root, path=QI):
    archive = root / "portable_characters" / PID / "current.zip"
    if not archive.exists():
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(baseline(path)))
    result = TabletopService(CombatService(ROOT, root), root)
    result._talents_cache = deepcopy(TALENTS)
    result._spheres_cache = {SPHERE: "Water"}
    return result


def choices(view, index=0):
    options = view["level_up"]
    selected = {g["path_id"]: next(r for r in g["options"] if not r["requires_confirmation"])
                for g in options["subpaths"]}
    return {"cl": options["cl"], "talent_ids": [TALENTS[index]["canonical_talent_id"]],
            "subpaths": {pid: r["id"] for pid, r in selected.items()},
            "feature_choices": {b["feature_id"]: b["options"][0]["id"]
                                for r in selected.values() for b in r.get("build_choices") or []}}


FEATURE = bloodline.BLOODLINE
def _options():
    return contracts()[FEATURE]["options"]


def _option(lineage, affinity):
    return next(o["id"] for o in _options()
                if o["grants"] == {"bloodline_lineage": lineage, "bloodline_affinity": affinity})


def _bloodline_sheet(recorded=None):
    """A Qi Cultivator who owns Ancestral Bloodline Awakening, with or without a recorded pick."""
    sheet = baseline(QI)
    sheet["path_and_subpath"]["path_feature_record_ids"] = list(
        sheet["path_and_subpath"]["path_feature_record_ids"]) + [FEATURE]
    if recorded is not None:
        sheet["path_and_subpath"]["feature_build_choices"] = {FEATURE: dict(recorded)}
    return sheet


def _pending_ids(svc):
    return [row["feature_id"] for row in svc.advancement(PID)["level_up"]["pending_feature_choices"]]


def test_granting_level_offers_the_pick_and_an_unanswered_level_is_refused(tmp_path):
    # (a) The CL3 grant shows the lineage-and-affinity pick; a level-up without it is refused.
    svc = service(tmp_path, QI)
    svc.level_up(PID, choices(svc.advancement(PID)))
    view = svc.advancement(PID)
    assert view["level_up"]["cl"] == 3
    subpath = next(r for r in view["level_up"]["subpaths"] if r["path_id"] == QI)
    offered = [b for row in subpath["options"] for b in row["build_choices"] if b["feature_id"] == FEATURE]
    assert offered and [o["id"] for o in offered[0]["options"]] == [o["id"] for o in _options()]
    unanswered = choices(view)
    unanswered["feature_choices"] = {}
    with pytest.raises(FoundryError):
        svc.level_up(PID, unanswered)


def test_a_recorded_pick_leaves_no_combat_rows_and_sets_that_affinity(tmp_path):
    # (b) One pick sets the affinity condition; no "Bloodline affinity: X" combat rows exist.
    sheet = _bloodline_sheet({"bloodline_lineage": "vermilion_phoenix", "bloodline_affinity": "radiant",
                              "choice": _option("vermilion_phoenix", "radiant")})
    compiled = bloodline_bundle(sheet)
    rows = [r for r in compiled["action_catalog"] if ".bloodline_affinity." in r["source_definition_id"]]
    assert rows == []
    passive = next(r for r in compiled["typed_passives"] if r.get("kind") == "bloodline_strike")
    assert passive["lineage"] == "vermilion_phoenix"
    assert passive["affinity"] == "radiant"


def test_a_character_gained_before_the_pick_is_pending_then_records_and_reloads(tmp_path):
    # (c) Owned with no pick yet: the feature is pending; the recorded pick survives a cold reload.
    svc = service_with_sheet(tmp_path, _bloodline_sheet())
    assert FEATURE in _pending_ids(svc)
    option = _option("azure_dragon", "fire")
    svc.set_feature_picks(PID, {FEATURE: option})
    assert FEATURE not in _pending_ids(svc)
    reloaded = service_with_sheet(tmp_path, _bloodline_sheet(), reload=True).combat._factory_owner_sheet(PID)
    recorded = reloaded["path_and_subpath"]["feature_build_choices"][FEATURE]
    assert recorded["choice"] == option
    assert recorded["bloodline_lineage"] == "azure_dragon"
    assert recorded["bloodline_affinity"] == "fire"


def test_a_lineage_cannot_record_an_affinity_it_does_not_allow():
    # (d) Only lineage-permitted pairs are offered, so a disallowed pair is refused when recorded or compiled.
    offered = {o["id"] for o in _options()}
    assert "vermilion_phoenix_cold" not in offered and "vermilion_phoenix_radiant" in offered
    with pytest.raises(FoundryError):
        resolve([{"canonical_id": FEATURE, "display_name": "Ancestral Bloodline Awakening"}],
                {FEATURE: "vermilion_phoenix_cold"}, required=False)
    sheet = _bloodline_sheet({"choice": "vermilion_phoenix_cold", "bloodline_lineage": "vermilion_phoenix",
                              "bloodline_affinity": "cold"})
    with pytest.raises(ValueError, match="not permitted"):
        bloodline_bundle(sheet)


def service_with_sheet(root, sheet, reload=False):
    """A TabletopService whose character archive holds this sheet; reload rebuilds it cold from disk."""
    import json
    import zipfile
    archive = root / "portable_characters" / PID / "current.zip"
    if not reload:
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    return service(root, QI)


def bloodline_bundle(sheet):
    from combat.factory_compiler import compile_character
    return compile_character(sheet, actor_id="actor:factory.synthetic-bloodline")
