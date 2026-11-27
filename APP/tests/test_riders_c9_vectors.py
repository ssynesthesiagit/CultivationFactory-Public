"""Replacement Wind Lash vectors retain damage, not the basic vector's rider."""
import copy

import pytest

from combat.factory_compiler import _changed, compile_character
from test_riders_c9 import ROOT, _portable, bundle


TALENTS = ["Drawing Breath", "Gale Push", "Pressure Break", "Breath-Stealing Palm"]


def talent_id(name):
    return "TAL_AIR_" + name.upper().replace("-", "_").replace(" ", "_")


def test_effect_slot_replacement_is_general_and_preserves_other_riders():
    effects = [{"type": "attack", "on_hit": [
        {"type": "damage", "dice": "1d8"},
        {"type": "save", "on_fail": [{"type": "condition", "effect_slot": "stance"}]},
        {"type": "extra_damage", "formula": "pb", "source_modifier": "other"},
    ]}]
    before = copy.deepcopy(effects)
    assert _changed(effects, {}) == before
    changed = _changed(effects, {"replaces_effect_slot": "stance"})
    assert changed[0]["on_hit"][1]["on_fail"] == []
    assert changed[0]["on_hit"][0] == before[0]["on_hit"][0]
    assert changed[0]["on_hit"][2] == before[0]["on_hit"][2]
    assert effects == before


def test_effect_slot_replacement_also_survives_composed_augments():
    from tests.test_typed_structure import AUTHORITY, SHEET
    authority = copy.deepcopy(AUTHORITY)
    mechanics = authority["mechanics"]
    mechanics["LASH"]["effects"][0]["on_hit"].append(
        {"type": "forced_movement", "distance_ft": 5, "effect_slot": "stance"})
    mechanics["WHIP"]["modifier"].update(group="augment", replaces_effect_slot="stance")
    mechanics["EDGE"]["modifier"].update(group="augment", optional=True, extra_cp=1)
    rows = compile_character(SHEET, actor_id="actor:factory.slots", typed_authority=authority)["action_catalog"]
    combo = next(r for r in rows if len(r["parameters"]["typed"].get("augments", [])) == 2)
    hit = combo["parameters"]["typed"]["effects"][0]["on_hit"]
    assert not any(e.get("effect_slot") == "stance" for e in hit)
    assert {e["type"] for e in hit} == {"damage", "save", "extra_damage"}


@pytest.mark.parametrize("name", TALENTS)
def test_each_replacement_removes_only_the_basic_vector(name):
    rows = bundle([talent_id(name)])["action_catalog"]
    for vector in ("Push", "Pull", "Cut", "Lift", "Scatter"):
        plain = next(r for r in rows if r["display_name"] == "Wind Lash: " + vector)
        variant = next(r for r in rows if r["display_name"] == "Wind Lash: " + vector + " + " + name)
        base_hit = plain["parameters"]["typed"]["effects"][0]["on_hit"]
        hit = variant["parameters"]["typed"]["effects"][0]["on_hit"]
        assert hit[0] == base_hit[0] and hit[0]["type"] == "damage"
        assert not any(e.get("effect_slot") == "basic_vector" for e in hit)
        assert any(e.get("type") == "save" for e in hit)
        if vector in ("Push", "Pull", "Cut"):
            assert any(e.get("effect_slot") == "basic_vector" for e in base_hit)


@pytest.mark.parametrize("name", TALENTS)
@pytest.mark.parametrize("vector", ["Push", "Pull", "Cut"])
@pytest.mark.parametrize("success", [False, True], ids=["failed-save", "successful-save"])
def test_replacement_vector_at_table_commit_reload_and_replay(tmp_path, name, vector, success):
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService

    _portable(tmp_path, "wind", [talent_id(name)], dc=1 if success else 60,
              sphere="tianxia.sphere.air")
    _portable(tmp_path, "rival", [], sphere=None, ac=0)
    wind, rival = [FACTORY_ACTOR_PREFIX + side for side in ("wind", "rival")]
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "C9 vector yard", "width_squares": 20,
        "height_squares": 12, "walls": [], "starts": {"team1": [[3, 6]], "team2": [[8, 6]]}})
    mid = service.create_factory_match(project_ids=["wind"], opponent_actor_ids=[rival],
        control_modes={a: "MANUAL" for a in (wind, rival)},
        arena_id="battlefield:map.c9-vector-yard", match_seed="C9-VECTORS")["match_id"]
    table = TabletopService(service, tmp_path)

    def act(option):
        state = table.state(mid)
        return table.act(mid, option, state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"])

    for _ in range(6):
        state = table.state(mid)
        if state["menu"]["actor_id"] == wind:
            break
        act(state["menu"]["end_turn"])
    group = next(g for g in state["menu"]["actions"] if g["label"] == "Wind Lash: " + vector + " + " + name)
    option = next(o for o in group["options"] if rival in o["target_ids"])
    assert act(option["candidate_id"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    foe = loaded.engine.state.actors[rival]
    assert foe.current_hp < foe.maximum_hp  # The hit still deals Wind Lash damage.
    feet = {"Drawing Breath": -5 if success else -10,
            "Gale Push": 5 if success else 10,
            "Pressure Break": 10 if success else 20,
            "Breath-Stealing Palm": 0}[name]
    assert (foe.position.x, foe.position.y) == (8 + feet // 5, 6)
    from combat.unmaking import NO_REACTIONS_AGAINST
    assert not any(c.condition_id == NO_REACTIONS_AGAINST or c.data.get("rule", {}).get("no_reactions") or
                   "reaction_denied" in c.condition_id for c in foe.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"
