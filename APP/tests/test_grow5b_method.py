"""Public synthetic Grow Method lifecycle: real table preview/save/cold reload."""
from copy import deepcopy

import pytest

from app.core import FoundryError
from combat import table_advance as ta, table_levelup as lu, table_method as tm
from non_sphere_authority.method_mechanics import compile_method_mechanics
from stage2.formulas import evaluate_formula
from tests.grow5_support import (
    BODY, QI, PID, ROOT, TALENTS, SPHERE, baseline, install, service, choices, _reach, _add_payload,
)


def method_sheet(path=BODY, mid="METHOD-002"):
    sheet = baseline(path)
    authority = lu.source()
    record = authority.methods[mid]
    mechanics = compile_method_mechanics(record, authority.method_registry_commitment_sha256)
    sheet["method"] = {"state": "active", "status": "active", "record_id": mid, "display_name": record["name"],
                       "mechanical_projection": True, "mechanics": mechanics}
    sheet["identity"]["primary_method_id"] = mid
    primary = sheet["ability_scores_and_statistics"]["primary_resource"]
    pool = primary["definitions"][0]
    context = ta._formula_context(sheet, ta.current_scores(sheet))
    base = pool["max"]
    pool["authority_components"] = [{"role": "path_base", "record_id": path, "value": base,
                                    "base_formula": deepcopy(pool["base_formula"])}]
    for modifier in mechanics["resource_modifiers"]:
        if modifier["resource_id"] != pool["resource_id"]:
            continue
        value = evaluate_formula(modifier["formula"]["root"], context).value
        pool["authority_components"].append({"role": "method_delta", "record_id": mid, "value": value,
                                            "formula_id": modifier["formula"]["formula_id"]})
        pool["max"] += value
    pool["current"] = pool["max"] - 1
    primary.update(maximum=pool["max"], build_state_current=pool["current"])
    return sheet


def payload(mid="METHOD-004", **extra):
    return {"method_id": mid, "source": "teacher", "note": "Master Willow's completed instruction",
            "opportunity": "downtime training", "completed": True, **extra}


def start(root, path=BODY, mid="METHOD-002", **extra):
    sheet = method_sheet(path, mid)
    sheet.update(extra)
    install(root, sheet)
    return service(root, path)


def pool(sheet):
    return sheet["ability_scores_and_statistics"]["primary_resource"]["definitions"][0]


def test_preview_commit_cold_reload_keeps_attainment_choices_and_consequences(tmp_path):
    s = start(tmp_path, foundation={"record_id": "synthetic.foundation", "stage": "Awakened", "choices": {"expression": "kept"}},
              scars=["old scar"], hidden_injuries=["old injury"], deviations=["old deviation"],
              failure_gated_lessons=["old lesson"], known_methods=[
                  {"record_id": "METHOD-003", "display_name": "River-Vein Returning Method", "state": "inactive"}])
    _reach(s, 4)  # Existing Subpath, mandatory choices, talents and above-zero Path attainment.
    before = s.combat._factory_owner_sheet(PID)
    stored = deepcopy(s.buttons.get(PID))
    pv = s.change_method(PID, payload())
    assert s.buttons.get(PID) == stored  # Preview commits nothing.
    assert pv["method"]["record_id"] == "METHOD-004"
    assert pv["statistics"]["primary_resource"]["maximum"] == pool(before)["max"] - 6
    assert pv["statistics"]["primary_resource"]["build_state_current"] == pool(before)["max"] - 6
    result = s.change_method(PID, payload(save=True))
    assert result["method_change"]["primary"]["id"] == "METHOD-004"
    assert result["level_up"]["primary_method"]["id"] == "METHOD-004"
    cold = service(tmp_path, BODY)
    after = cold.combat._factory_owner_sheet(PID)
    assert after["ability_scores_and_statistics"] == pv["statistics"]
    assert after["identity"]["path_ids"] == before["identity"]["path_ids"]
    assert after["identity"]["paths"] == before["identity"]["paths"]
    assert after["path_and_subpath"] == before["path_and_subpath"]
    assert after["spheres_and_talents"] == before["spheres_and_talents"]
    for key in ("foundation", "scars", "hidden_injuries", "deviations", "failure_gated_lessons"):
        assert after[key] == before[key]
    assert {r["record_id"]: r["state"] for r in after["known_methods"]} == {
        "METHOD-002": "inactive", "METHOD-003": "inactive", "METHOD-004": "active"}
    method_terms = [c for c in pool(after)["authority_components"] if c.get("role") == "method_delta"]
    assert {c["record_id"] for c in method_terms} == {"METHOD-004"}
    assert after["method"]["breakthrough_shape"] == lu.source().methods["METHOD-004"]["source_text"]["breakthrough_shape"]
    assert after["method"]["foundation_shape"] == lu.source().methods["METHOD-004"]["source_text"]["foundation_shape"]
    fields = {r["label"]: r["text"] for r in after["method"]["printed_entry"]["fields"]}
    assert "Breakthroughs" in fields and "Foundation relationship" in fields
    assert fields["Resource"].startswith(lu.source().methods["METHOD-004"]["owner_readable"]["resource_summary"])


def test_increasing_max_never_refills_and_repeated_switches_do_not_stack(tmp_path):
    s = start(tmp_path, mid="METHOD-004")
    before = s.combat._factory_owner_sheet(PID)
    s.change_method(PID, payload("METHOD-002", save=True))
    grown = service(tmp_path, BODY).combat._factory_owner_sheet(PID)
    assert pool(grown)["max"] == pool(before)["max"] + 6
    assert pool(grown)["current"] == pool(before)["current"]
    s.change_method(PID, payload("METHOD-004", save=True))
    assert pool(service(tmp_path, BODY).combat._factory_owner_sheet(PID))["max"] == pool(before)["max"]
    assert pool(service(tmp_path, BODY).combat._factory_owner_sheet(PID))["current"] == pool(before)["current"]


def test_separate_path_pools_and_dormant_paths_remain_separate(tmp_path):
    sheet = method_sheet()
    qi = baseline(QI)["ability_scores_and_statistics"]["primary_resource"]["definitions"][0]
    sheet["ability_scores_and_statistics"]["primary_resource"]["definitions"].append(qi)
    sheet["identity"]["path_ids"].append(QI)
    sheet["identity"]["paths"] += [{"path_id": QI, "effective_cl": 1},
                                  {"path_id": "tianxia.path.spirit_awakening", "effective_cl": 0}]
    install(tmp_path, sheet)
    s = service(tmp_path, BODY)
    before = deepcopy(sheet["ability_scores_and_statistics"]["primary_resource"]["definitions"])
    s.change_method(PID, payload("METHOD-003", save=True))
    after = service(tmp_path, BODY).combat._factory_owner_sheet(PID)
    pools = after["ability_scores_and_statistics"]["primary_resource"]["definitions"]
    assert len(pools) == 2
    assert pools[0]["max"] == before[0]["max"] - 4
    assert pools[0]["current"] == min(before[0]["current"], pools[0]["max"])
    assert pools[1]["max"] == before[1]["max"] + 2
    assert pools[1]["current"] == before[1]["current"]
    assert after["identity"]["paths"] == sheet["identity"]["paths"]


def test_historical_path_without_future_ap_route_is_not_an_incompatibility(tmp_path):
    from non_sphere_authority.foundation_mechanics import verified_foundation_records
    # Sacred Body supports Body; switching to a Qi-only Method cannot erase
    # Body attainment or turn lack of future Body AP into a new incompatibility.
    fid = "ancient_desolate_sacred_body_v0_2C"
    record = verified_foundation_records()[fid]
    s = start(tmp_path, foundation={"record_id": fid, "display_name": record["display_name"], "stage": "Awakened"})
    pv = s.change_method(PID, payload("METHOD-003"))
    assert not pv["change"]["gm"]
    assert pv["paths"]["path_ids"] == [BODY]
    assert pv["foundation"]["record_id"] == fid


def test_blank_starting_sect_replaced_freely_once(tmp_path):
    s = start(tmp_path, QI, "METHOD-001")
    before = s.combat._factory_owner_sheet(PID)
    request = payload("METHOD-003", source="", note="")
    assert s.advancement(PID)["method_change"]["free_replacement"]
    pv = s.change_method(PID, request)
    assert pv["change"]["free_replacement"] and not pv["change"]["gm"]
    s.change_method(PID, {**request, "save": True})
    cold = service(tmp_path)
    assert not cold.advancement(PID)["method_change"]["free_replacement"]
    assert pool(cold.combat._factory_owner_sheet(PID))["current"] == pool(before)["current"]
    with pytest.raises(FoundryError, match="Name the teacher"):
        cold.change_method(PID, payload("METHOD-010", source="", note=""))
    cold.undo_method(PID)
    assert cold.combat._factory_owner_sheet(PID) == before


def test_incompatible_foundation_shown_and_gm_grant_survives_reload(tmp_path):
    foundation = {"record_id": "synthetic.foundation", "display_name": "Quiet Heart", "stage": "Awakened"}
    s = start(tmp_path, foundation=foundation,
              method_foundation_compatibility={"METHOD-004": {"compatible_foundation_ids": ["a.different.foundation"]}})
    view = s.advancement(PID)
    blocked = next(r for r in view["method_change"]["options"] if r["id"] == "METHOD-004")
    assert not blocked["legal"] and "Quiet Heart" in "; ".join(blocked["reasons"])
    with pytest.raises(FoundryError, match="GM grant"):
        s.change_method(PID, payload(save=True))
    pv = s.change_method(PID, payload(gm=True))
    assert pv["change"]["gm"]
    s.change_method(PID, payload(gm=True, save=True))
    cold = service(tmp_path, BODY)
    assert cold.combat._factory_owner_sheet(PID)["method"]["gm"]
    assert cold.advancement(PID)["method_change"]["history"][-1]["gm"]
    assert cold.combat._factory_owner_sheet(PID)["foundation"] == foundation


def test_authored_path_incompatibility_not_just_ap_route(tmp_path, monkeypatch):
    s = start(tmp_path)
    record = deepcopy(lu.source().methods["METHOD-004"])
    record["incompatible_path_ids"] = ["BODY_REFINING"]
    monkeypatch.setitem(lu.source().methods, "METHOD-004", record)
    blocked = next(r for r in s.advancement(PID)["method_change"]["options"] if r["id"] == "METHOD-004")
    assert not blocked["legal"] and "Body Refining" in blocked["reasons"][0]
    with pytest.raises(FoundryError, match="Body Refining"):
        s.change_method(PID, payload())


def test_undo_exact_old_primary_and_lifo_across_levels_and_campaign_gains(tmp_path):
    s = start(tmp_path)
    before = s.combat._factory_owner_sheet(PID)
    s.change_method(PID, payload(save=True))
    s.level_up(PID, choices(s.advancement(PID)))
    with pytest.raises(FoundryError, match="Undo later levels"):
        s.undo_method(PID)
    s.undo_level(PID)
    s.add_advancement(PID, "talent", TALENTS[1]["canonical_talent_id"])
    with pytest.raises(FoundryError, match="later campaign gains"):
        s.undo_method(PID)
    s.remove_advancement(PID, "talent", TALENTS[1]["canonical_talent_id"])
    s.undo_method(PID)
    assert service(tmp_path, BODY).combat._factory_owner_sheet(PID) == before
    assert not service(tmp_path, BODY).advancement(PID)["method_change"]["history"]


def test_switch_after_level_requires_method_undo_before_level_undo(tmp_path):
    s = start(tmp_path)
    s.level_up(PID, choices(s.advancement(PID)))
    before = s.combat._factory_owner_sheet(PID)
    s.change_method(PID, payload(save=True))
    with pytest.raises(FoundryError, match="after this level"):
        s.undo_level(PID)
    service(tmp_path, BODY).undo_method(PID)
    assert service(tmp_path, BODY).combat._factory_owner_sheet(PID) == before
    s.undo_level(PID)


def test_before_grow_switch_creation_authority_still_supplies_current_primary(tmp_path):
    s = start(tmp_path)
    view = s.advancement(PID, primary_method_id="METHOD-003")
    assert view["level_up"]["primary_method"]["id"] == "METHOD-003"
    assert view["method_change"]["primary"]["id"] == "METHOD-003"


def test_future_access_uses_new_primary_even_with_stale_creation_authority(tmp_path):
    s = start(tmp_path)
    s.change_method(PID, payload("METHOD-003", save=True))
    view = s.advancement(PID, primary_method_id="METHOD-002")
    assert view["level_up"]["primary_method"]["id"] == "METHOD-003"
    bad = {"cl": view["level_up"]["cl"], "add_path_id": QI,
           "add_access": "primary_method", "add_source_id": "METHOD-002"}
    with pytest.raises(FoundryError, match="recorded Primary Method"):
        s.level_up(PID, bad, primary_method_id="METHOD-002")
    # At CL2 no Subpath is due yet. Use the actual add template instead of
    # the CL3+ helper, which assumes a mandatory Subpath group exists.
    good = {**choices(view, 0), "add_path_id": QI, "add_access": "primary_method", "add_source_id": "METHOD-003"}
    good["feature_choices"].update({b["feature_id"]: b["options"][0]["id"]
                                    for b in view["level_up"]["add_templates"][QI]["feature_choices"]})
    s.level_up(PID, good, primary_method_id="METHOD-002")
    sheet = service(tmp_path, BODY).combat._factory_owner_sheet(PID)
    assert set(sheet["identity"]["path_ids"]) == {BODY, QI}
    view = s.advancement(PID)
    spirit = "tianxia.path.spirit_awakening"
    denied = {"cl": view["level_up"]["cl"], "add_path_id": spirit,
              "add_access": "primary_method", "add_source_id": "METHOD-003"}
    with pytest.raises(FoundryError, match="does not grant future advancement"):
        s.level_up(PID, denied)
    assert sheet["method"]["record_id"] == "METHOD-003"


@pytest.mark.parametrize("save", [False, True])
def test_refuse_during_character_fight_even_with_gm_override(tmp_path, monkeypatch, save):
    s = start(tmp_path)
    monkeypatch.setattr(s.combat, "list_matches", lambda: [{"match_id": "synthetic fight", "status": "ACTIVE"}])
    monkeypatch.setattr(s.combat, "get_match", lambda _: {"state": {"terminal_result": None,
        "actors": [{"entity_id": "actor:factory." + PID}]}})
    with pytest.raises(FoundryError, match="Finish this character's fight"):
        s.change_method(PID, payload(gm=True, save=save))
    assert not ta.normalized(s.buttons.get(PID).get("advancement"))["method_changes"]


@pytest.mark.parametrize("extra", [{"completed": False}, {"opportunity": "short rest"}, {"opportunity": "daily loadout"}])
def test_requires_completed_meaningful_opportunity(tmp_path, extra):
    with pytest.raises(FoundryError, match="completed cultivation opportunity"):
        start(tmp_path).change_method(PID, payload(**extra))


def test_http_preview_commit_sheet_reload_and_undo(tmp_path, monkeypatch):
    from app.api import create_app
    from app.core import Settings
    from combat.tabletop_service import TabletopService
    from fastapi.testclient import TestClient

    start(tmp_path)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    monkeypatch.setattr(TabletopService, "_catalog_talents", lambda self: deepcopy(TALENTS))
    monkeypatch.setattr(TabletopService, "_sphere_names", lambda self: {SPHERE: "Water"})
    monkeypatch.setattr(app.state.character_sheets, "sheet", lambda _: {
        "owner_character_sheet": method_sheet(), "display_owner_character_sheet": method_sheet(),
        "sections": {"abilities_statistics": {"data": method_sheet()["ability_scores_and_statistics"]}}})
    monkeypatch.setattr(app.state.character_creation, "recovery", lambda _: {})
    prefix = f"/api/tabletop/characters/{PID}/advancement"
    with TestClient(app) as client:
        headers = {"X-Foundry-Token": client.get("/api/session").json()["token"]}
        response = client.post(prefix + "/method", json=payload(), headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["method"]["record_id"] == "METHOD-004"
        assert client.get(prefix).json()["method_change"]["primary"]["id"] == "METHOD-002"
        response = client.post(prefix + "/method", json=payload(save=True), headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["level_up"]["primary_method"]["id"] == "METHOD-004"
        sheet = client.get(f"/api/characters/{PID}/sheet").json()
        for field in ("owner_character_sheet", "display_owner_character_sheet"):
            assert sheet[field]["method"]["record_id"] == "METHOD-004"
            assert sheet[field]["known_methods"][0]["state"] == "inactive"
        response = client.post(prefix + "/method/undo", json={}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["method_change"]["primary"]["id"] == "METHOD-002"
