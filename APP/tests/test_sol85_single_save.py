"""One meaningful save per effect, through accepted table actions and reload."""
import json
from pathlib import Path

import pytest

import combat
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_riders_c9 import sheet

ROOT = Path(combat.__file__).resolve().parents[1]
LEFT, RIGHT = "actor:factory.sol85-left", "actor:factory.sol85-right"
BLACK_LUNG = "TAL_DARK_BLACK_LUNG"
PROJECT = "tianxia.talent.formations.heavenly_grand_formation"


def formation_technique():
    # The hunt's Formation project has no creature payload. Its Zone carries
    # a minor hindrance, whose Constitution save is the only outcome to decide.
    return {"technique_id": "sol85.formation-zone", "name": "Formation hindrance zone", "action_type": "bonus action",
            "base_form": {"form_id": "zone"}, "primary_sphere_effect": {"talent_id": PROJECT},
            "augments": [{"augment_id": "minor_hindrance"}], "table_choices": {"minor_hindrance": "slowed"},
            "cp_cost": {"final": 1}}


def table_fight(tmp_path, scenario, seed="SOL85"):
    bundles = []
    for aid in (LEFT, RIGHT):
        ids = ([BLACK_LUNG, "TAL_DARK_DIRECTIONAL_DARKNESS"] if scenario == "dark" else [PROJECT]) if aid == LEFT else []
        document = sheet(ids, cl=15, dc=15)
        document["identity"]["display_name"] = "Zone keeper" if aid == LEFT else "Visiting fighter"
        if aid == LEFT and scenario == "formation":
            document["forged_techniques"] = [formation_technique()]
        bundles.append(compile_character(document, actor_id=aid))
    service = CombatService(ROOT, tmp_path)
    mid = service._finish_factory_match(bundles, [LEFT, RIGHT], {LEFT: "team:factory", RIGHT: "team:opponents"},
        {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}}, service.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [LEFT], [RIGHT], control_modes={LEFT: "MANUAL", RIGHT: "MANUAL"}, match_seed=seed,
        display_name="Single-save regression", maximum_rounds=4)["match_id"]
    return service, TabletopService(service, tmp_path), mid


def act(table, mid, label, destination=None):
    state = table.state(mid)
    menu = state["menu"]
    if label == "end":
        cid = menu["end_turn"]
    else:
        group = next(g for g in menu["actions"] if g["label"] == label)
        cid = next(o["candidate_id"] for o in group["options"] if destination is None or o.get("destination") == destination)
    result = table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED", result


def owner_turn(table, mid):
    for _ in range(3):
        if table.state(mid)["menu"]["actor_id"] == LEFT:
            return
        act(table, mid, "end")
    raise AssertionError("owner turn not reached")


def reload(service, mid):
    before = service._load_session(mid).engine.state.model_dump(mode="json")
    loaded = CombatService(ROOT, service.userdata_root)._load_session(mid)
    assert loaded.engine.state.model_dump(mode="json") == before
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine


@pytest.mark.parametrize("seed", ["SOL85-DARK-0", "SOL85-DARK-1", "SOL85-DARK-2", "SOL85-DARK-3"])
def test_dark_black_lung_rolls_once_and_that_roll_decides_poison_after_table_reload(tmp_path, seed):
    service, table, mid = table_fight(tmp_path, "dark", seed)
    owner_turn(table, mid)
    act(table, mid, "Shape Darkness: Black Lung")
    act(table, mid, "Darkness + Directional Darkness", {"x": 4, "y": 6})
    engine = reload(service, mid)
    active = [z for z in engine.state.zones.values() if z.active]
    assert len(active) == 1  # Directional Darkness republishes this same zone.
    source = active[0].source_definition_id
    was_poisoned = any(c.condition_id == "condition:typed.poisoned" for c in engine.state.actors[RIGHT].conditions.values())
    start = len(engine.events)
    act(table, mid, "end")  # The visitor starts its turn in Black Lung.
    engine = reload(service, mid)
    events = engine.events[start:]
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == source and e.actor_id == RIGHT]
    assert len(saves) == 1
    assert saves[0].payload["reason"].endswith(":CON")
    poisoned = any(c.condition_id == "condition:typed.poisoned" for c in engine.state.actors[RIGHT].conditions.values())
    applied = [e for e in events if e.event_type == "CONDITION_APPLIED" and RIGHT in e.target_ids
               and e.payload.get("condition_id") == "condition:typed.poisoned"]
    assert bool(applied) == (not saves[0].payload["success"])
    # A successful entry/start save does not remove poison from an earlier
    # failure: the printed removal trigger is leaving the Darkness.
    assert poisoned == (was_poisoned or not saves[0].payload["success"])


@pytest.mark.parametrize("seed", ["SOL85-FORM-0", "SOL85-FORM-1", "SOL85-FORM-2", "SOL85-FORM-3"])
def test_formation_project_zone_has_only_hindrance_save_and_its_result_survives_table_reload(tmp_path, seed):
    service, table, mid = table_fight(tmp_path, "formation", seed)
    owner_turn(table, mid)
    start = len(service._load_session(mid).engine.events)
    act(table, mid, "Formation hindrance zone", {"x": 4, "y": 6})
    engine = reload(service, mid)
    saves = [e for e in engine.events[start:] if e.event_type == "SAVE_ROLLED" and e.actor_id == RIGHT]
    assert len(saves) == 1
    assert saves[0].payload["reason"].endswith(":CON")
    slowed = any(m.target_field == "speed_ft" and m.value == -10 for m in engine.state.actors[RIGHT].modifiers.values())
    assert slowed == (not saves[0].payload["success"])


@pytest.mark.parametrize("form", ["burst", "cone", "line", "aura", "zone", "counter"])
def test_payload_free_forged_forms_do_not_add_an_outcome_free_save(form):
    from combat.forged import mechanic_for
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    technique = formation_technique()
    technique["base_form"] = {"form_id": form}
    row = mechanic_for(technique, authority["mechanics"])
    assert [e["ability"] for e in row["effects"] if e["type"] == "save"] == ["con"]


def test_forged_damage_and_separate_hindrance_keep_their_distinct_saves():
    from combat.forged import mechanic_for
    primary = {"name": "Damage", "effects": [{"type": "save", "ability": "dex", "on_fail": [
        {"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["fire"]}], "on_success": [{"type": "half_damage"}]}]}
    technique = formation_technique()
    row = mechanic_for(technique, {PROJECT: primary})
    assert [e["ability"] for e in row["effects"] if e["type"] == "save"] == ["dex", "con"]
