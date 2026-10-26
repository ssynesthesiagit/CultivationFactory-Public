"""GROW1: ability-score entries in the table growth record (combat/table_advance.py). A finished character's scores can
change (GM respec now, level increases later) and every score-derived number is recomputed; the sealed install is never
touched. Synthetic sheet only, so this runs in public CI."""

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from copy import deepcopy

import pytest

from combat import table_advance as ta
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService
from stage2.formulas import evaluate_formula

ABILITIES = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
OLD = {"STR": 8, "DEX": 15, "CON": 14, "INT": 14, "WIS": 12, "CHA": 14}
NEW = {"STR": 8, "DEX": 14, "CON": 18, "INT": 10, "WIS": 16, "CHA": 12}


def sheet(scores=OLD, cl=4):
    mods = {a: ta.ability_modifier(scores[a]) for a in ABILITIES}
    con = {"op": "add", "terms": [{"op": "constant", "value": 10}, {"op": "ability_modifier", "ability": "CON"}, {"op": "pb", "value": 2}]}
    return {
        "identity": {"cultivation_level": cl, "key_ability": "CON", "proficiency_bonus": 2, "path": "Qi Cultivation"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": scores[a], "modifier": mods[a]} for a in ABILITIES],
            "armor_class": {"base_value": 10 + mods["CON"] + 2, "calculation": "10 + CON modifier + PB",
                            "formula_trace": evaluate_formula(con, {"cl": cl, "pb": 2, "ability_modifiers": mods}).trace},
            "hit_points": {"maximum": 9 + 3 * mods["CON"], "build_state_current": 9 + 3 * mods["CON"],
                           "progression": {"levels": [{"cl": i, "gain": 3 + mods["CON"], "maximum": 3 + mods["CON"] * i} for i in range(1, cl + 1)]}},
            "initiative": {"ability": "DEX", "bonus": mods["DEX"]},
            "speed": {"walking_ft": 30},
            "skills": [{"skill": "Endurance", "ability": "CON", "bonus": mods["CON"] + 2},
                       {"skill": "Lore", "ability": "INT", "bonus": mods["INT"] + 2}],
            "technique_attack_bonus": mods["CON"] + 2,
            "technique_save_dc": 8 + mods["CON"] + 2,
        },
    }


def stats(s):
    b = s["ability_scores_and_statistics"]
    return {
        "abilities": {r["ability"]: (r["score"], r["modifier"]) for r in b["abilities"]},
        "ac": b["armor_class"]["base_value"], "ac_trace": b["armor_class"]["formula_trace"]["root"]["value"],
        "hp": b["hit_points"]["maximum"], "hp_cur": b["hit_points"]["build_state_current"],
        "hp_levels": [(l["gain"], l["maximum"]) for l in b["hit_points"]["progression"]["levels"]],
        "init": b["initiative"]["bonus"], "skills": [r["bonus"] for r in b["skills"]],
        "tab": b["technique_attack_bonus"], "dc": b["technique_save_dc"],
    }


def test_xiahou_case_recomputes_every_number():
    before = sheet()
    after = ta.recompute_from_abilities(before, OLD, NEW)
    b, a = stats(before), stats(after)
    assert a["abilities"]["CON"] == (18, 4)
    assert a["hp"] == b["hp"] + 2 * 4                       # CON mod +2 -> +4, times CL 4
    assert a["hp_cur"] == b["hp_cur"] + 2 * 4               # at maximum, so current moves too
    assert [g for g, _ in a["hp_levels"]] == [g + 2 for g, _ in b["hp_levels"]]
    assert a["ac"] == b["ac"] + 2 and a["ac_trace"] == b["ac_trace"] + 2   # Path AC is 10 + CON + PB
    assert a["tab"] == b["tab"] + 2 and a["dc"] == b["dc"] + 2             # key ability is CON
    assert a["init"] == b["init"]                                           # DEX 15 -> 14 keeps +2
    assert a["skills"] == [b["skills"][0] + 2, b["skills"][1] - 2]          # Endurance (CON) +2, Lore (INT) -2
    assert before == sheet()                                                # input never changed


def test_recompute_then_back_restores_every_number():
    original = sheet()
    there = ta.recompute_from_abilities(original, OLD, NEW)
    back = ta.recompute_from_abilities(there, NEW, OLD)
    drop = lambda s: {k: v for k, v in s.items() if k != "table_advancement"}
    assert drop(back) == drop(original)


def test_apply_with_entry_recomputes_and_removing_restores():
    base = sheet(cl=4)
    doc = ta.normalized({"abilities": [{"type": "ability", "reason": "level_increase", "cl": 4,
                                        "changes": {"CON": 2}, "note": "CON training"}]})
    assert ta.normalized(doc)["abilities"][0]["changes"] == {"CON": 2}
    applied = ta.apply(base, doc)
    assert stats(applied)["abilities"]["CON"] == (16, 3)
    assert stats(applied)["hp"] == stats(base)["hp"] + 1 * 4 and stats(applied)["ac"] == stats(base)["ac"] + 1   # mod +2 -> +3
    assert ta.apply(base, ta.normalized({"abilities": []})) is base   # removing the entry: the untouched sheet


def test_gm_respec_must_be_point_buy_legal():
    s = sheet()
    legal = {"type": "ability", "reason": "gm_respec", "changes": {"STR": 8, "DEX": 14, "CON": 15, "INT": 13, "WIS": 12, "CHA": 10}, "cl": 4}
    assert ta.ability_status(legal, s)["legal"] is True                     # 0+7+9+5+4+2 = 27 points
    over = {**legal, "changes": {**legal["changes"], "INT": 15}}
    assert ta.ability_status(over, s)["legal"] is False                     # 0+7+9+9+4+2 = 31 points, not 27
    spread = {"type": "ability", "reason": "gm_respec", "changes": ta.default_spread("CON"), "cl": 4}
    assert ta.default_spread("CON") == {"CON": 15, "DEX": 14, "WIS": 13, "INT": 12, "CHA": 10, "STR": 8}
    assert ta.ability_status(spread, s)["legal"] is True                    # 9+7+5+4+2+0 = 27
    high = {"type": "ability", "reason": "gm_respec", "changes": {**ta.default_spread("CON"), "CON": 16}, "cl": 4}
    assert ta.ability_status(high, s)["legal"] is False


def test_level_increase_follows_the_stage2_rule():
    s = sheet(cl=4)
    ok = {"type": "ability", "reason": "level_increase", "changes": {"CON": 1, "WIS": 1}, "cl": 4}
    assert ta.ability_status(ok, s)["legal"] is True
    body = sheet(cl=4)
    body["identity"]["path_ids"] = ["tianxia.path.body_refining"]
    assert ta.ability_status(ok, body)["legal"] is True  # shared allocation, not a Qi-only gate
    assert ta.ability_status({**ok, "cl": 8}, sheet(cl=8))["legal"] is True  # native Stage 2 milestone
    assert ta.ability_status({**ok, "cl": 3}, s)["legal"] is False         # CL 4 only
    assert ta.ability_status(ok, sheet(OLD, cl=7))["legal"] is False       # cannot record a missed CL 4 opportunity later
    assert ta.ability_status({**ok, "changes": {"CON": 2, "WIS": 1}}, s)["legal"] is False   # budget 2
    assert ta.ability_status({**ok, "changes": {"CON": 3, "WIS": -1}}, s)["legal"] is False  # deltas +1/+2
    assert ta.ability_status({**ok, "changes": {"CON": 2}}, sheet(OLD, cl=2))["legal"] is False  # below CL 4
    capped = sheet({**OLD, "CON": 20})
    assert ta.ability_status({"type": "ability", "reason": "level_increase", "changes": {"CON": 2}, "cl": 4}, capped)["legal"] is False


def test_service_rejects_second_level_increase_at_same_cl():
    from combat.tabletop_service import TabletopService, TabletopError

    class Buttons:
        def get(self, _project):
            return {"advancement": {"abilities": [
                {"reason": "level_increase", "cl": 4, "changes": {"CON": 2}, "gm": False}
            ]}}

    class Combat:
        def _factory_owner_sheet(self, _project, *, apply_table=True):
            return sheet(cl=7)

    service = TabletopService.__new__(TabletopService)
    service.combat, service.buttons = Combat(), Buttons()
    with pytest.raises(TabletopError) as error:
        service.add_ability("synthetic-project", {
            "reason": "level_increase", "cl": 4, "changes": {"WIS": 2}
        })
    assert error.value.status_code == 409
    assert "already recorded at CL 4" in str(error.value)


def test_gm_override_marks_an_illegal_entry(tmp_path):
    service = growth_service(tmp_path)
    entry = {"type": "ability", "reason": "gm_respec", "changes": NEW, "cl": 4}
    with pytest.raises(TabletopError) as refused:
        service.add_ability(PID, entry)
    assert refused.value.status_code == 409
    service.add_ability(PID, entry, gm=True)
    reloaded = growth_service(tmp_path)
    row = reloaded.buttons.get(PID)["advancement"]["abilities"][0]
    assert row["gm"] is True
    assert ta.current_scores(reloaded.combat._factory_owner_sheet(PID)) == NEW


def test_normalized_keeps_ability_entry_through_table_commit_reload(tmp_path):
    from combat.tabletop import ButtonStore

    record = {"abilities": [{"type": "ability", "reason": "level_increase", "cl": 4, "changes": {"CON": 2}, "note": "Training"}]}
    ButtonStore(tmp_path).save_advancement(PID, record)
    reloaded = ButtonStore(tmp_path).get(PID)["advancement"]
    assert ta.empty()["abilities"] == [] and set(reloaded) == set(ta.empty())
    assert reloaded["abilities"] == ta.normalized(record)["abilities"]
    applied = ta.apply(sheet(cl=4), reloaded)
    assert stats(applied)["abilities"]["CON"] == (16, 3)


def test_entry_fields_are_clipped_and_typed():
    row = ta.normalized({"abilities": [{"reason": "gm_respec", "changes": {"CON": "x", "STR": 9, "BOGUS": 1}, "cl": "4", "note": "n" * 300}]})["abilities"][0]
    assert row["changes"] == {"STR": 9, "CON": None} and row["cl"] == 4 and len(row["note"]) == 240



ROOT = Path(__file__).resolve().parents[1]
PID = "0badc0de-0000-4000-8000-000000000001"


def installed_sheet():
    base = sheet({**OLD, "INT": 15})
    base["identity"].update(path_ids=["tianxia.path.qi_cultivation"], path_id="tianxia.path.qi_cultivation")
    base["ability_scores_and_statistics"]["saving_throw_proficiencies"] = ["CON", "INT"]
    base["ability_scores_and_statistics"]["primary_resource"] = {
        "name": "Qi", "maximum": 8, "build_state_current": 6,
        "definitions": [
            {"resource_id": "tianxia.resource.qi", "name": "Qi", "max": 8, "current": 6,
             "formula_id": "c1a.qi.maximum", "authority_components": [
                 {"role": "path_base", "formula_id": "c1a.qi.maximum", "value": 8}]},
            {"resource_id": "tianxia.resource.resonance", "name": "Resonance", "max": 5, "current": 5,
             "base_formula": {"root": {"op": "add", "terms": [
                 {"op": "constant", "value": 4}, {"op": "ability_modifier", "ability": "WIS"}]}}},
        ]}
    return base


def install(data_root):
    package = data_root / "portable_characters" / PID / "current.zip"
    package.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(installed_sheet()))
    return package


def growth_service(data_root):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    if not (data_root / "portable_characters" / PID / "current.zip").is_file():
        install(data_root)
    service = TabletopService(CombatService(ROOT, data_root), data_root)
    # No catalog choices are needed to exercise growth; still use the real
    # service, ButtonStore, install reader and overlay for every mutation.
    service._talents_cache = []
    service._spheres_cache = {}
    return service


@pytest.mark.parametrize("formula_id", ["c1a.qi.maximum", "ns1r.tianxia.path.qi_cultivation.resource.maximum"])
def test_saved_growth_reloads_recalculates_compiled_pools_and_removes(tmp_path, formula_id):
    from combat.factory_compiler import compile_character

    service = growth_service(tmp_path)
    package = tmp_path / "portable_characters" / PID / "current.zip"
    baseline = installed_sheet()
    definition = baseline["ability_scores_and_statistics"]["primary_resource"]["definitions"][0]
    definition["formula_id"] = formula_id
    definition["authority_components"][0]["formula_id"] = formula_id
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(baseline))
    sealed_hash = hashlib.sha256(package.read_bytes()).hexdigest()
    original = service.combat._factory_owner_sheet(PID)
    service.add_ability(PID, {"reason": "level_increase", "cl": 4, "changes": {"INT": 2}})
    cold = growth_service(tmp_path)
    adjusted = cold.combat._factory_owner_sheet(PID)
    resource = adjusted["ability_scores_and_statistics"]["primary_resource"]
    assert resource["maximum"] == 12 and resource["build_state_current"] == 10
    assert resource["definitions"][0]["max"] == 12
    assert resource["definitions"][0]["authority_components"][0]["value"] == 12
    bundle = compile_character(adjusted, actor_id="actor:factory." + PID)
    pools = {row["resource_id"]: row for row in bundle["actor_template"]["resources"]}
    assert pools["resource:core.qi"]["maximum"] == 12
    assert pools["resource:core.resonance"]["maximum"] == 5
    assert adjusted["ability_scores_and_statistics"]["saving_throws"]["INT"] == 5
    cold.remove_advancement(PID, "ability", "0")
    assert growth_service(tmp_path).combat._factory_owner_sheet(PID) == original
    assert hashlib.sha256(package.read_bytes()).hexdigest() == sealed_hash


def test_resource_lowering_floor_secondary_and_missing_proficient_saves(tmp_path):
    service = growth_service(tmp_path)
    service.add_ability(PID, {"reason": "gm_respec", "cl": 4, "changes": {**OLD, "INT": 19, "WIS": 18}}, gm=True)
    service.add_ability(PID, {"reason": "gm_respec", "cl": 4, "changes": {**OLD, "INT": 8, "WIS": 10}}, gm=True)
    block = growth_service(tmp_path).combat._factory_owner_sheet(PID)["ability_scores_and_statistics"]
    assert block["primary_resource"]["maximum"] == 8  # max(CL * -1, 2 * CL)
    assert block["primary_resource"]["build_state_current"] == 6  # deficit preserved
    assert block["primary_resource"]["definitions"][1]["max"] == 4
    assert block["saving_throws"]["CON"] == 4
    assert block["saving_throws"]["INT"] == 1
    assert block["saving_throws"]["WIS"] == 0


def test_real_http_add_factory_sheet_cold_reload_remove_and_override(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.core import Settings
    from combat.tabletop_service import TabletopService

    install(tmp_path)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    # Synthetic display projection, not a fake mutation or growth reader.
    # The HTTP handler still overlays the real persisted ButtonStore record.
    monkeypatch.setattr(app.state.character_sheets, "sheet", lambda _: {
        "owner_character_sheet": installed_sheet(), "display_owner_character_sheet": installed_sheet(),
        "sections": {"abilities_statistics": {"data": installed_sheet()["ability_scores_and_statistics"]}}})
    monkeypatch.setattr(app.state.character_creation, "recovery", lambda _: {})
    # Catalog-independent menu projection for this synthetic character.
    monkeypatch.setattr(TabletopService, "_sphere_names", lambda self: {})
    monkeypatch.setattr(TabletopService, "_catalog_talents", lambda self: [])
    prefix = f"/api/tabletop/characters/{PID}/advancement"
    with TestClient(app) as client:
        headers = {"X-Foundry-Token": client.get("/api/session").json()["token"]}
        rejected = client.post(prefix, headers=headers, json={"kind": "ability", "record_id": "0"})
        assert rejected.status_code == 422  # addition contract was NOT widened
        added = client.post(prefix + "/ability", headers=headers, json={
            "reason": "level_increase", "cl": 4, "changes": {"INT": 2}})
        assert added.status_code == 200, added.text
        assert growth_service(tmp_path).buttons.get(PID)["advancement"]["abilities"][0]["gm"] is False
        view = client.get(f"/api/characters/{PID}/sheet").json()
        for snapshot in (view["owner_character_sheet"], view["display_owner_character_sheet"]):
            assert ta.current_scores(snapshot)["INT"] == 17
            assert "adjusted at the table" in snapshot["ability_scores_and_statistics"]["table_adjustment_note"]
        assert view["sections"]["abilities_statistics"]["data"]["primary_resource"]["maximum"] == 12
        removed = client.post(prefix + "/remove", headers=headers, json={"kind": "ability", "record_id": "0"})
        assert removed.status_code == 200, removed.text
        assert growth_service(tmp_path).combat._factory_owner_sheet(PID) == installed_sheet()
        reset = client.post(prefix + "/ability", headers=headers, json={
            "reason": "gm_respec", "cl": 4, "changes": NEW, "gm": True})
        assert reset.status_code == 200, reset.text
        assert growth_service(tmp_path).buttons.get(PID)["advancement"]["abilities"][0]["gm"] is True
        restored = client.post(prefix + "/remove", headers=headers, json={"kind": "ability", "record_id": "0"})
        assert restored.status_code == 200
        assert ta.current_scores(client.get(f"/api/characters/{PID}/sheet").json()["display_owner_character_sheet"])["INT"] == 15


@pytest.mark.parametrize("profile", ["legacy_phase2h_v1", "fire_qi_c2c1_v1", "canonical_v2"])
def test_gm_adapter_reads_installed_growth_without_changing_package(tmp_path, monkeypatch, profile):
    from gm2_contract import adapter

    package = install(tmp_path)
    sealed_hash = hashlib.sha256(package.read_bytes()).hexdigest()
    service = growth_service(tmp_path)
    service.add_ability(PID, {"reason": "level_increase", "cl": 4, "changes": {"INT": 2}})
    stats_block = installed_sheet()["ability_scores_and_statistics"]
    source = {"identity": installed_sheet()["identity"], "stats": stats_block}
    source["identity"].update(display_name="Synthetic", CL=4)
    if profile == "legacy_phase2h_v1":
        source["stats"] = {**stats_block, "ability_scores": {**OLD, "INT": 15}, "ability_modifiers": {a: ta.ability_modifier(v) for a, v in {**OLD, "INT": 15}.items()},
                           "hp_max": 15, "hp_current": 15, "ac_active": 14, "speed_ft": 30, "save_dc": 12,
                           "primary_resource_name": "Qi", "primary_resource_current": 6, "primary_resource_max": 8,
                           "skills": {"Endurance": 4, "Lore": 4}}
    selected = {"profile": profile, "model": source, "model_sha256": "a" * 64, "manifest": {},
                "path": "synthetic.json", "runtime_package": False}
    if profile == "canonical_v2":
        selected["profile"] = "fire_qi_c2c1_v1"
        selected["model"] = adapter._migrate_fire(selected, sealed_hash)[0]
        selected["profile"] = profile
    monkeypatch.setattr(adapter, "audit_package", lambda _: {"package_sha256": sealed_hash})
    monkeypatch.setattr(adapter, "select_candidate", lambda _: deepcopy(selected))
    result = adapter.migrate_package(package)
    assert result["status"] != "REJECTED", result
    model = result["model"]
    assert model["ability_scores"]["INT"]["score"] == 17
    assert model["combat"]["saving_throws"][3]["bonus"] == 5
    assert model["cultivation"]["resources"][0]["maximum"] == 12
    assert any("adjusted at the table" in row["message"] for row in result["diagnostics"])
    assert "adjusted at the table" in adapter.render_reference_html(result)
    assert result["normalized_view"]["core_stats"]["ability_scores"]["INT"]["score"] == 17
    assert hashlib.sha256(package.read_bytes()).hexdigest() == sealed_hash


def test_respec_preserves_background_and_prior_table_increase():
    base = sheet()
    base["background_and_origin"] = {"background": {"ability_score_change": {"CON": 1}}}
    base["advancement_history"] = {"levels": [{"selection": {
        "choice_kind": "ability_score_change", "deltas": {"WIS": 1}
    }}]}
    doc = ta.normalized({"abilities": [
        {"reason": "level_increase", "cl": 4, "changes": {"CON": 2}},
        {"reason": "gm_respec", "cl": 4, "changes": {
            "STR": 8, "DEX": 14, "CON": 15, "INT": 13, "WIS": 12, "CHA": 10
        }},
    ]})
    result = ta.apply(base, doc)
    # The respec resets to a legal 27-point spread, then retains background +1
    # and the earlier earned +2 CON increase.
    assert ta.current_scores(result)["CON"] == 18
    assert ta.current_scores(result)["INT"] == 13
    assert ta.current_scores(result)["WIS"] == 13
    assert ta.ability_status(doc["abilities"][1], base)["legal"]


def test_service_blocks_installed_asi_and_insight_opportunity():
    from combat.tabletop_service import TabletopService

    for kind in ("ability_score_change", "cultivation_insight_acquisition"):
        installed = sheet(cl=7)
        installed["advancement_history"] = {"canonical_allocations": [
            {"target_cl": 4, "advancement_kind": kind}
        ]}
        class Buttons:
            def get(self, _project):
                return {"advancement": {"abilities": []}}
        class Combat:
            def _factory_owner_sheet(self, _project, *, apply_table=True):
                return installed
        service = TabletopService.__new__(TabletopService)
        service.combat, service.buttons = Combat(), Buttons()
        with pytest.raises(TabletopError, match="already recorded at CL 4"):
            service.add_ability("synthetic-project", {
                "reason": "level_increase", "cl": 4, "changes": {"WIS": 2}
            })


def test_service_rejects_second_level_increase_at_cap():
    """A second level increase must see the first increase's projected score:
    base CON 19 -> +1 at CL 4 -> 20 (cap) -> another +1 at CL 8 must be rejected."""

    class Buttons:
        def __init__(self):
            self.record = ta.empty()

        def get(self, _project):
            return {"advancement": self.record}

        def save_advancement(self, _project, record):
            self.record = record

    class Combat:
        def __init__(self):
            self._cl = 4

        def _factory_owner_sheet(self, _project, *, apply_table=True):
            return sheet({**OLD, "CON": 19}, cl=self._cl)

    service = TabletopService.__new__(TabletopService)
    buttons = Buttons()
    combat = Combat()
    service.combat, service.buttons = combat, buttons
    service._talents_cache = []
    service._spheres_cache = {}

    # First increase at CL 4: CON 19 -> 20, at the cap, legal (budget +1/+1).
    service.add_ability("synthetic-project", {"reason": "level_increase", "cl": 4, "changes": {"CON": 1, "WIS": 1}})

    # Character is now at CL 8; the sealed sheet still shows base CON 19.
    combat._cl = 8

    # Second increase at CL 8: projected CON is 20, 20 + 1 = 21 > cap 20 -> rejected.
    with pytest.raises(TabletopError) as error:
        service.add_ability("synthetic-project", {"reason": "level_increase", "cl": 8, "changes": {"CON": 1, "WIS": 1}})
    assert error.value.status_code == 409
    assert "cap" in str(error.value).lower()


def test_advancement_reports_first_increase_at_cap_as_legal():
    """The Grow tab checks each recorded increase against scores at recording
    time, so a level increase to the cap reads legal, not illegal."""

    base = {**OLD, "CON": 19}
    saved_doc = ta.normalized({"abilities": [
        {"reason": "level_increase", "cl": 4, "changes": {"CON": 1, "WIS": 1},
         "note": "CL4 training", "gm": False, "at": "2026-01-01T00:00:00Z"}
    ]})

    class Buttons:
        def __init__(self):
            self.record = saved_doc

        def get(self, _project):
            return {"advancement": self.record}

        def save_advancement(self, _project, record):
            self.record = record

    class Combat:
        def _factory_owner_sheet(self, _project, *, apply_table=True):
            base_sheet = sheet(base, cl=4)
            return ta.apply(base_sheet, saved_doc) if apply_table else base_sheet

    service = TabletopService.__new__(TabletopService)
    service.combat, service.buttons = Combat(), Buttons()
    service._talents_cache = []
    service._spheres_cache = {}

    options = service.advancement("synthetic-project")
    abilities = options["added"]["abilities"]
    assert len(abilities) == 1
    assert abilities[0]["status"]["legal"] is True
    assert options["ability_panel"]["scores"]["CON"] == 20


def test_ac_reselects_best_calculation_after_scores_change(monkeypatch):
    import combat.table_advance as module

    con_formula = {"op": "add", "terms": [
        {"op": "constant", "value": 12},
        {"op": "ability_modifier", "ability": "CON"},
    ]}
    dex_formula = {"op": "add", "terms": [
        {"op": "constant", "value": 12},
        {"op": "ability_modifier", "ability": "DEX"},
    ]}
    authority = {"rules": [
        {"rule_id": "dex", "kind": "base_ac_calculation", "feature_id": None, "formula": {"formula_id": "dex.formula", "root": dex_formula}},
        {"rule_id": "path", "kind": "base_ac_calculation", "feature_id": "path.ac", "formula": {"formula_id": "path.formula", "root": con_formula}},
        {"rule_id": "path-bonus", "kind": "ac_bonus", "feature_id": "path.ac", "requires_base_calculation_feature_id": "path.ac", "bonus": 1},
    ]}
    # Keep the synthetic baseline formula, but use the production rule's
    # stable identity rather than relying on a display label.
    baseline_id = "tianxia.core.unarmored_ac.owner_r1"
    authority["rules"][0]["rule_id"] = baseline_id
    monkeypatch.setattr(module, "_path_statistic_formulas", lambda: authority)
    old = sheet()
    stats = old["ability_scores_and_statistics"]
    stats["armor_class"].update(base_value=14, value=14, generation={
        "calculation_id": baseline_id, "calculation_feature_id": None,
        "alternatives_considered": [
            {"calculation_id": baseline_id, "display_name": "Dexterity", "value": 14},
            {"calculation_id": "path", "display_name": "Path", "value": 14},
        ], "always_on_bonuses": [],
        "conditional_bonus_sources": [{"rule_id": "path-bonus", "bonus": 1}],
    })
    # DEX and CON modifiers tie; +1 CON makes the Path calculation the winner.
    new_scores = {**OLD, "CON": 16}
    result = ta.recompute_from_abilities(old, OLD, new_scores)
    armor = result["ability_scores_and_statistics"]["armor_class"]
    assert armor["generation"]["calculation_id"] == "path"
    assert armor["base_value"] == 15
    assert armor["value"] == 16
    assert armor["generation"]["always_on_bonuses"][0]["rule_id"] == "path-bonus"

    # Reverse direction: a previously winning Path calculation loses to the
    # unarmored baseline when CON falls.
    reverse_scores = {**OLD, "DEX": 16, "CON": 18}
    reverse = sheet(reverse_scores)
    reverse_stats = reverse["ability_scores_and_statistics"]
    reverse_stats["armor_class"].update(base_value=16, value=17, formula_trace=evaluate_formula(
        con_formula, {"cl": 4, "pb": 2, "ability_scores": reverse_scores,
                      "ability_modifiers": {a: ta.ability_modifier(v) for a, v in reverse_scores.items()}}).trace,
        generation={"calculation_id": "path", "calculation_feature_id": "path.ac",
                    "alternatives_considered": [
                        {"calculation_id": baseline_id, "display_name": "Unarmored baseline", "value": 15},
                        {"calculation_id": "path", "display_name": "Path", "value": 16},
                    ], "always_on_bonuses": [{"rule_id": "path-bonus", "bonus": 1}],
                    "conditional_bonus_sources": []})
    lowered = ta.recompute_from_abilities(reverse, reverse_scores, {**reverse_scores, "CON": 14})
    armor = lowered["ability_scores_and_statistics"]["armor_class"]
    assert armor["generation"]["calculation_id"] == baseline_id
    assert armor["base_value"] == 15
    assert armor["generation"]["always_on_bonuses"] == []
    restored = ta.recompute_from_abilities(lowered, {**reverse_scores, "CON": 14}, reverse_scores)
    assert restored["ability_scores_and_statistics"]["armor_class"]["value"] == 17


def test_grow_number_input_never_uses_text_selection(tmp_path):
    """Execute the production handler with a number-input API that throws."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the DOM-free input regression")
    source = (ROOT / "static/tabletop/grow.js").read_text()
    handler = source[source.index("function onInput(event) {"):source.index("  const t = event.target;", source.index("function onInput(event) {"))]
    script = """
      const assert = require('node:assert/strict');
      let abilityDraft = {values: {}};
      let focused = false;
      const input = {type: 'number', focus() { focused = true; },
        setSelectionRange() { throw new Error('InvalidStateError'); }};
      const deps = {$: () => input};
      const render = () => {};
    """ + handler + """
      }
      onInput({target: {id: 'grow-ability-INT', type: 'number', value: '17',
        selectionStart: null, selectionEnd: null, dataset: {growAbility: 'INT'}}});
      assert.equal(abilityDraft.values.INT, 17);
      assert.equal(focused, true);
    """
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


@pytest.mark.skipif(os.environ.get("GROW1_BROWSER") != "1", reason="Lead runs Chromium outside the sandbox")
def test_grow_number_edit_in_chromium():
    from playwright.sync_api import sync_playwright

    source = (ROOT / "static/tabletop/grow.js").read_text()
    handler = source[source.index("function onInput(event) {"):source.index("  const t = event.target;", source.index("function onInput(event) {"))] + "}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.set_content('<div id="panel"><input id="grow-ability-INT" type="number" data-grow-ability="INT" value="15"></div>')
            page.evaluate("""handler => {
              window.abilityDraft = {values: {}};
              window.deps = {$: id => document.getElementById(id)};
              window.render = () => {document.getElementById('panel').innerHTML =
                '<input id="grow-ability-INT" type="number" data-grow-ability="INT" value="' + abilityDraft.values.INT + '">';};
              (0, eval)(handler);
              document.addEventListener('input', onInput);
            }""", handler)
            page.locator("#grow-ability-INT").fill("17")
            assert page.locator("#grow-ability-INT").input_value() == "17"
            assert page.evaluate("abilityDraft.values.INT") == 17
            assert not errors
        finally:
            browser.close()
