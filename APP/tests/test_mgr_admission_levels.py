"""Public synthetic installs exercise native Grow/admission projection boundaries.

Palm is the existing contracted source used to test the generic prerequisite;
these tests grant no Living Mercury Body or other uncontracted feature.
"""
import hashlib
import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat import table_advance as ta
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.source_acquisition import SourceAcquisitionStore
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "0adc0de0-0000-4000-8000-000000000014"
OTHER = "0adc0de0-0000-4000-8000-000000000015"
A, B = (FACTORY_ACTOR_PREFIX + pid for pid in (PROJECT, OTHER))
SPIRIT = "tianxia.path.spirit_awakening"
PALM = "tianxia.tradition.spirit.last_inch_palm.feature.palm_across_emptiness"
ACCESS = {"kind": "restricted_spirit_tradition", "basis": "contact_boundary_teacher",
          "record_id": "synthetic:contact-teacher"}


def tabletop(combat):
    table = TabletopService(combat, combat.userdata_root)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return table


def installed(root, monkeypatch, cl):
    sheet = {
        "identity": {"name": "Student", "cultivation_level": cl, "proficiency_bonus": 4,
                     "key_ability": "WIS", "path_ids": [SPIRIT]},
        "path_and_subpath": {"path_record_ids": [SPIRIT]},
        "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.water"]},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2}
                          for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Resonance", "maximum": 30},
            "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": 14, "technique_attack_bonus": 6,
        },
    }
    for pid in (PROJECT, OTHER):
        package = root / "portable_characters" / pid / "current.zip"
        package.parent.mkdir(parents=True)
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    arena = {"stable_id": "battlefield:admission-levels", "display_name": "Practice court",
             "width_squares": 10, "height_squares": 6, "square_size_ft": 5,
             "starting_positions": {}, "terrain_regions": []}
    monkeypatch.setattr(CombatService, "factory_arenas", lambda self, **kw: {"court": arena})
    return tabletop(CombatService(ROOT, root))


def grow(table, view=None):
    """Choose legal published options from the real Grow screen, then commit."""
    options = (view or table.advancement(PROJECT))["level_up"]
    groups = {g["path_id"]: next(r for r in g["options"]
                                if r["legal"] and not r["requires_confirmation"])
              for g in options["subpaths"]}
    choice = {"cl": options["cl"],
              "talent_ids": [r["id"] for r in options["talents"] if r["legal"]][:options["talent_count"]],
              "subpaths": {pid: r["id"] for pid, r in groups.items()},
              "feature_choices": {b["feature_id"]: b["options"][0]["id"]
                                  for b in options["feature_choices"]}}
    for row in groups.values():
        choice["feature_choices"].update({b["feature_id"]: b["options"][0]["id"]
                                          for b in row.get("build_choices") or []})
    if options["advancement_choice"]:
        choice.update(advancement="ability", changes={"WIS": 2})
    return table.level_up(PROJECT, choice)


def admit(combat):
    return combat.acquire_source_feature(PROJECT, feature_id=PALM,
                                         occurrence_id="synthetic:training", access_record=ACCESS)


def journey(combat):
    return combat.create_journey(project_ids=[PROJECT, OTHER], arena_id="court",
                                 positions={A: {"x": 1, "y": 1}, B: {"x": 5, "y": 1}},
                                 base_paces={A: 3000, B: 3000},
                                 control_modes={A: "MANUAL", B: "MANUAL"})


def end_turn(combat, mid):
    table = tabletop(combat)
    menu = table.state(mid)["menu"]
    result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, [])
    assert result["status"] == "COMMITTED", result


@pytest.mark.parametrize("installed_cl", [9, 10])
def test_grow_reopens_after_projected_admission_and_continues_natively(tmp_path, monkeypatch, installed_cl):
    table = installed(tmp_path, monkeypatch, installed_cl)
    package = tmp_path / "portable_characters" / PROJECT / "current.zip"
    sealed = package.read_bytes()
    grow(table)  # actual saved level, not a planted advancement receipt
    before_history = deepcopy(table.buttons.get(PROJECT)["advancement"])
    projected_before = table.combat._factory_owner_sheet(PROJECT)
    active = journey(table.combat)
    jid = active["journey_id"]
    table.combat.journey_act(jid, active["revision"], A, "move", {"path": [{"x": 2, "y": 1}]})
    paid_state = table.combat.journey_state(jid)
    receipt = admit(table.combat)
    assert receipt["acquired_cl"] == installed_cl + 1
    assert receipt["feature_id"] == PALM and receipt["actor_id"] == A
    assert receipt["access_record"] == ACCESS
    store = SourceAcquisitionStore(tmp_path)
    path = store.root / (hashlib.sha256(A.encode()).hexdigest() + ".json")
    receipt_bytes = path.read_bytes()
    cold = CombatService(ROOT, tmp_path)
    assert cold._factory_owner_sheet(PROJECT)["combat_acquisitions"] == [receipt]

    # Before the fix this exact real Grow reopen fails in its raw-base read:
    # acquired_cl > installed_cl, including when both levels meet CL10.
    view = tabletop(cold).advancement(PROJECT)
    assert view["cl"] == installed_cl + 1
    assert view["level_up"]["cl"] == installed_cl + 2
    assert table.buttons.get(PROJECT)["advancement"] == before_history
    raw = cold._factory_owner_sheet(PROJECT, apply_table=False)
    assert raw["identity"]["cultivation_level"] == installed_cl
    assert ta.current_scores(raw)["WIS"] == 14
    assert "combat_acquisitions" not in raw
    assert "table_advancement" not in raw
    assert cold._factory_owner_sheet(PROJECT) == {**projected_before, "combat_acquisitions": [receipt]}
    assert cold.journey_state(jid) == paid_state

    # Native continuation reaches CL12's ability increase exactly once.
    next_table = tabletop(cold)
    while view["cl"] < 12:
        view = grow(next_table, view)
    assert view["ability_panel"]["scores"]["WIS"] == 16
    assert view["ability_panel"]["level_increase"]["recorded_cls"] == [12]
    raw_after = CombatService(ROOT, tmp_path)._factory_owner_sheet(PROJECT, apply_table=False)
    assert raw_after["identity"]["cultivation_level"] == installed_cl
    assert ta.current_scores(raw_after)["WIS"] == 14
    saved = deepcopy(next_table.buttons.get(PROJECT)["advancement"])
    assert [r["cl"] for r in saved["levels"]] == list(range(installed_cl + 1, 13))
    assert len(saved["abilities"]) == 1
    with pytest.raises(TabletopError, match="already recorded at CL 12"):
        next_table.add_ability(PROJECT, {"reason": "level_increase", "cl": 12, "changes": {"WIS": 2}})
    assert next_table.buttons.get(PROJECT)["advancement"] == saved
    with pytest.raises(ValueError, match="already acquired"):
        admit(CombatService(ROOT, tmp_path))
    assert path.read_bytes() == receipt_bytes
    assert CombatService(ROOT, tmp_path).journey_state(jid) == paid_state

    # The native registry allows one active journey per creature. End the
    # preserved session explicitly before starting the fresh compilation.
    finished = CombatService(ROOT, tmp_path).journey_act(jid, paid_state["revision"], A, "finish", {})
    assert finished["phase"] == "finished"
    for aid in (A, B):
        assert finished["actors"][aid]["bundle"] == paid_state["actors"][aid]["bundle"]
        assert finished["actors"][aid]["resources"] == paid_state["actors"][aid]["resources"]
    assert CombatService(ROOT, tmp_path).journey_replay(jid)["status"] == "PASS"
    state = journey(CombatService(ROOT, tmp_path))
    bundle = state["actors"][A]["bundle"]
    assert bundle["cl"] == 12 and bundle["source_acquisitions"] == [receipt]
    assert not state["actors"][B]["bundle"].get("source_acquisitions")
    assert state["actors"][B]["bundle"]["cl"] == installed_cl
    assert bundle["action_catalog"]
    assert state["actors"][B]["bundle"]["action_catalog"] == paid_state["actors"][B]["bundle"]["action_catalog"]
    result = CombatService(ROOT, tmp_path).journey_start_combat(
        state["journey_id"], state["revision"], {A: "team:a", B: "team:b"})
    mid = result["match_id"]
    end_turn(CombatService(ROOT, tmp_path), mid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    assert CombatService(ROOT, tmp_path).verify(mid)["status"] == "PASS"
    version = loaded.engine.state.state_version
    end_turn(CombatService(ROOT, tmp_path), mid)
    continued = CombatService(ROOT, tmp_path)._load_session(mid)
    assert continued.engine.state.state_version > version
    assert continued.mechanical.replay()["status"] == "PASS"
    owner = next(b for b in continued.engine.typed_bundle_documents if b["actor_id"] == A)
    assert owner["source_acquisitions"] == [receipt]
    assert package.read_bytes() == sealed
    assert path.read_bytes() == receipt_bytes
    assert next_table.buttons.get(PROJECT)["advancement"] == saved


@pytest.mark.parametrize("field,value,error", [
    ("source_sha256", "0" * 64, "source or admission contract changed"),
    ("admission_sha256", "0" * 64, "source or admission contract changed"),
    ("actor_id", B, "another creature"),
    ("acquired_cl", 9, "Cultivation Level 10"),
    ("acquired_cl", 20, "Cultivation Level 10"),
    ("access_record", {**ACCESS, "basis": "guessed"}, "Access record"),
    ("feature_id", "tianxia.subpath.qi.living_quicksilver_immortal_embryo.feature.living_mercury_body",
     "no source-backed native admission contract"),
])
def test_grow_projection_still_rejects_invalid_admissions(tmp_path, monkeypatch, field, value, error):
    table = installed(tmp_path, monkeypatch, 9)
    grow(table)
    admit(table.combat)
    store = SourceAcquisitionStore(tmp_path)
    path = store.root / (hashlib.sha256(A.encode()).hexdigest() + ".json")
    doc = json.loads(path.read_text())
    doc["records"][0][field] = value
    path.write_text(json.dumps(doc))
    saved = deepcopy(table.buttons.get(PROJECT)["advancement"])
    with pytest.raises(ValueError, match=error):
        tabletop(CombatService(ROOT, tmp_path)).advancement(PROJECT)
    with pytest.raises(ValueError, match=error):
        CombatService(ROOT, tmp_path)._factory_owner_sheet(PROJECT, apply_table=False)
    assert table.buttons.get(PROJECT)["advancement"] == saved


def test_undo_cannot_save_a_level_below_a_live_admission(tmp_path, monkeypatch):
    table = installed(tmp_path, monkeypatch, 10)
    grow(table)
    receipt = admit(table.combat)
    assert receipt["acquired_cl"] == 11
    saved = deepcopy(table.buttons.get(PROJECT)["advancement"])
    with pytest.raises(ValueError, match="Cultivation Level 10"):
        tabletop(CombatService(ROOT, tmp_path)).undo_level(PROJECT)
    assert table.buttons.get(PROJECT)["advancement"] == saved
    assert CombatService(ROOT, tmp_path)._factory_owner_sheet(PROJECT)["combat_acquisitions"] == [receipt]
