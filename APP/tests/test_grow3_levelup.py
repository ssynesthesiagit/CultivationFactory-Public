"""Public synthetic installs: table level acquisition, projection and LIFO undo."""
import hashlib
import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from app.core import FoundryError
from combat import table_advance as ta
from combat import table_levelup as lu
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import TabletopError
from stage2.ability_changes import published_path_records
from stage2.formulas import evaluate_formula

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


@pytest.mark.parametrize("path", [BODY, QI])
def test_levels_one_two_three_reload_combat_and_exact_undo(tmp_path, path):
    s = service(tmp_path, path)
    package = tmp_path / "portable_characters" / PID / "current.zip"
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    one = s.combat._factory_owner_sheet(PID)
    view = s.advancement(PID)
    auth = published_path_records()[path]["compatibility"]["factory"]["stage2_authority"]
    assert view["level_up"]["cl"] == 2
    assert view["level_up"]["talent_count"] == 1
    assert not view["level_up"]["advancement_choice"]
    assert view["level_up"]["subpaths"] == []
    assert [r["id"] for r in view["level_up"]["features"]] == auth["progression_by_cl"]["2"]["feature_record_ids"]
    s.level_up(PID, choices(view))
    cold = service(tmp_path, path)
    two = cold.combat._factory_owner_sheet(PID)
    assert two["identity"]["cultivation_level"] == 2
    gain = evaluate_formula(auth["hp_later_formula"]["root"], ta._formula_context(one, SCORES)).value
    assert two["ability_scores_and_statistics"]["hit_points"]["maximum"] == one["ability_scores_and_statistics"]["hit_points"]["maximum"] + gain
    assert two["ability_scores_and_statistics"]["saving_throws"] == one["ability_scores_and_statistics"]["saving_throws"]
    assert two["ability_scores_and_statistics"]["armor_class"]["base_value"] == (15 if path == BODY else 12)
    for cl, snapshot in [(2, two)]:
        pool = snapshot["ability_scores_and_statistics"]["primary_resource"]
        expected = evaluate_formula(auth["resources"][0]["base_formula"]["root"], ta._formula_context(snapshot, SCORES)).value
        assert pool["maximum"] == expected
        assert pool["build_state_current"] == expected - 1
    view = cold.advancement(PID)
    assert view["level_up"]["cl"] == 3
    assert len(view["level_up"]["subpaths"]) == 1
    assert view["level_up"]["subpaths"][0]["path_id"] == path
    assert not view["level_up"]["advancement_choice"]
    assert [r["id"] for r in view["level_up"]["features"]] == auth["progression_by_cl"]["3"]["feature_record_ids"]
    cold.level_up(PID, choices(view, 1))
    three_service = service(tmp_path, path)
    three = three_service.combat._factory_owner_sheet(PID)
    assert three["identity"]["cultivation_level"] == 3
    assert three["identity"]["paths"][0]["effective_cl"] == 3
    assert len(three["spheres_and_talents"]["learned_talent_record_ids"]) == 2
    stored = three_service.buttons.get(PID)["advancement"]
    assert [r["cl"] for r in stored["levels"]] == [2, 3]
    assert all(r["source"] == "level" for r in stored["talents"])
    assert stored["levels"][-1]["features"] and stored["levels"][-1]["talents"]
    with pytest.raises(TabletopError, match="Undo last level"):
        three_service.remove_advancement(PID, "talent", stored["talents"][-1]["id"])
    assert len(three["path_and_subpath"]["subpath_record_ids"]) == 1
    from combat.factory_compiler import compile_character
    bundle = compile_character(three, actor_id="actor:factory." + PID)
    assert bundle["cl"] == 3  # combat bundle consumed by human and AI seats
    assert bundle["actor_template"]["maximum_hp"] == three["ability_scores_and_statistics"]["hit_points"]["maximum"]
    table = three_service.sheet(PID)
    assert table["summary"]["cultivation_level"] == 3
    three_service.undo_level(PID)
    assert service(tmp_path, path).combat._factory_owner_sheet(PID) == two
    service(tmp_path, path).undo_level(PID)
    assert service(tmp_path, path).combat._factory_owner_sheet(PID) == one
    assert hashlib.sha256(package.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("mutation", [
    lambda c: c.update(cl=3),
    lambda c: c.update(talent_ids=[]),
    lambda c: c.update(talent_ids=[TALENTS[0]["canonical_talent_id"], TALENTS[1]["canonical_talent_id"]]),
    lambda c: c.update(changes={"CON": 2}),
])
def test_invalid_or_stale_choices_are_atomic(tmp_path, mutation):
    s = service(tmp_path)
    before = s.buttons.get(PID).get("advancement")
    payload = choices(s.advancement(PID))
    mutation(payload)
    with pytest.raises(FoundryError):
        s.level_up(PID, payload)
    assert s.buttons.get(PID).get("advancement") == before


def test_subpath_is_required_and_wrong_path_is_rejected(tmp_path):
    s = service(tmp_path)
    s.level_up(PID, choices(s.advancement(PID)))
    view = s.advancement(PID)
    for picked in ({}, {QI: "tianxia.subpath.body.flesh_crucible"}):
        payload = {**choices(view, 1), "subpaths": picked}
        with pytest.raises(FoundryError):
            s.level_up(PID, payload)
    assert service(tmp_path).advancement(PID)["cl"] == 2


@pytest.mark.parametrize("source", ["manual", "jade tablet"])
def test_learning_source_persists_and_blocks_destructive_undo(tmp_path, source):
    s = service(tmp_path)
    s.level_up(PID, choices(s.advancement(PID)))
    s.add_advancement(PID, "talent", TALENTS[2]["canonical_talent_id"], source=source)
    cold = service(tmp_path)
    entry = cold.buttons.get(PID)["advancement"]["talents"][-1]
    assert entry["source"] == source and entry["cl"] == 2
    with pytest.raises(FoundryError, match="after this level"):
        cold.undo_level(PID)
    cold.remove_advancement(PID, "talent", entry["id"])
    cold.undo_level(PID)
    assert service(tmp_path).advancement(PID)["cl"] == 1


def test_maximum_level_is_explicit_not_another_pick():
    sheet = baseline(QI)
    sheet["identity"]["cultivation_level"] = 20
    result = lu.menu(sheet, TALENTS, ta.empty())
    assert not result["available"]
    assert "20" in result["reason"]


def test_ability_milestone_is_available_and_applies_the_printed_increase(tmp_path):
    s = service(tmp_path)
    s.level_up(PID, choices(s.advancement(PID)))
    s.level_up(PID, choices(s.advancement(PID), 1))
    menu = s.advancement(PID)["level_up"]
    assert menu["cl"] == 4 and menu["advancement_choice"]
    assert menu["available"]
    s.level_up(PID, {"cl": 4, "talent_ids": [TALENTS[2]["canonical_talent_id"]],
                     "advancement": "ability", "changes": {"CON": 2}})
    assert ta.current_scores(service(tmp_path).combat._factory_owner_sheet(PID))["CON"] == SCORES["CON"] + 2


def test_http_level_contract_reload_and_undo(tmp_path, monkeypatch):
    from app.api import create_app
    from app.core import Settings
    from fastapi.testclient import TestClient
    s = service(tmp_path)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    monkeypatch.setattr(TabletopService, "_catalog_talents", lambda self: deepcopy(TALENTS))
    monkeypatch.setattr(TabletopService, "_sphere_names", lambda self: {SPHERE: "Water"})
    monkeypatch.setattr(app.state.character_sheets, "sheet", lambda _: {
        "owner_character_sheet": baseline(QI), "display_owner_character_sheet": baseline(QI),
        "sections": {"abilities_statistics": {"data": baseline(QI)["ability_scores_and_statistics"]}}})
    monkeypatch.setattr(app.state.character_creation, "recovery", lambda _: {})
    prefix = f"/api/tabletop/characters/{PID}/advancement"
    with TestClient(app) as client:
        token = {"X-Foundry-Token": client.get("/api/session").json()["token"]}
        payload = choices(client.get(prefix).json())
        assert client.post(prefix + "/level", json={**payload, "hp_total": 999}, headers=token).status_code == 422
        response = client.post(prefix + "/level", json=payload, headers=token)
        assert response.status_code == 200, response.text
        view = client.get(f"/api/characters/{PID}/sheet").json()
        for key in ("owner_character_sheet", "display_owner_character_sheet"):
            assert view[key]["identity"]["cultivation_level"] == 2
        assert client.post(prefix + "/level/undo", json={}, headers=token).status_code == 200
    assert service(tmp_path).combat._factory_owner_sheet(PID) == s.combat._factory_owner_sheet(PID, apply_table=False)
