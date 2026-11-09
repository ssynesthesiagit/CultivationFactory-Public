"""Synthetic Foundation growth fixtures, without imports of private test modules."""
import json
import zipfile
from copy import deepcopy
from pathlib import Path

from combat import table_advance as ta
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from stage2.ability_changes import published_path_records
from stage2.formulas import evaluate_formula

PHB = "PHB Chapter 3"
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


def _add_payload(view, path_id, access="phb", source=PHB, index=3, confirmed=False):
    base = choices(view, index)
    tmpl = view["level_up"]["add_templates"][path_id]
    sub = next(r for g in tmpl["subpaths"] for r in g["options"] if not r["requires_confirmation"])
    feature_choices = {b["feature_id"]: b["options"][0]["id"] for b in sub.get("build_choices") or []}
    feature_choices.update({b["feature_id"]: b["options"][0]["id"] for b in tmpl.get("feature_choices") or []})
    payload = {**base, "subpaths": {**base["subpaths"], path_id: sub["id"]},
               "feature_choices": {**base["feature_choices"], **feature_choices},
               "add_path_id": path_id, "add_access": access, "add_source_id": source, "access_confirmed": confirmed}
    if view["level_up"]["advancement_choice"]:
        payload.update(advancement="ability", changes={"CON": 2})
    return payload


def _reach(s, cl):
    """Commit levels until the next level to plan is cl (talent i per committed level)."""
    for i in range(cl - 2):
        view = s.advancement(PID)
        assert view["level_up"]["cl"] == i + 2
        payload = choices(view, i)
        if view["level_up"]["advancement_choice"]:
            payload.update(advancement="ability", changes={"CON": 2})
        s.level_up(PID, payload)


def install(root, sheet):
    path = root / "portable_characters" / PID / "current.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
