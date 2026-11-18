"""C9 continuation: printed large zones keep their size on actual battle maps."""
import pytest

from combat.factory_compiler import _area_size
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from test_riders_c9 import ROOT, _portable, BOW


@pytest.mark.parametrize("shape", ["sphere", "emanation", "cube", "line"])
def test_preserve_size_is_a_general_opt_in_for_persistent_areas(shape):
    action = ActionDefinition(source_definition_id="test:large-area", display_name="Large area",
                              owner_id="test:actor", economy=EconomyKind.ACTION,
                              resolution_kind="TYPED", target_kind="SELF", parameters={})
    area = {"shape": shape, "size_ft": 120}
    assert _area_size(area, action) == 60  # Existing saved typing retains its policy.
    assert _area_size({**area, "preserve_size": True}, action) == 120
    scaled = {**area, "preserve_size": True, "size_ft_by_cl": [[1, 20, 90]]}
    assert _area_size(scaled, action) == 90


@pytest.mark.parametrize("choice", ["No Straight Line", "No Steady Foot", "No Safe Breath", "No Fixed Direction"])
def test_storm_full_area_survives_table_commit_reload_and_replay(tmp_path, choice):
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService

    _portable(tmp_path, "gale", ["TAL_AIR_STORM_WITHOUT_DIRECTION"], cl=15, dc=60,
              sphere="tianxia.sphere.air")
    _portable(tmp_path, "rival", [], sphere=None, items=(BOW,))
    gale, rival = [FACTORY_ACTOR_PREFIX + side for side in ("gale", "rival")]
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "C9 large storm yard", "width_squares": 40,
        "height_squares": 10, "walls": [], "starts": {"team1": [[3, 5]], "team2": [[23, 5]]}})
    mid = service.create_factory_match(project_ids=["gale"], opponent_actor_ids=[rival],
        control_modes={a: "MANUAL" for a in (gale, rival)},
        arena_id="battlefield:map.c9-large-storm-yard", match_seed="C9-LARGE-STORM")["match_id"]
    table = TabletopService(service, tmp_path)

    def act(option):
        state = table.state(mid)
        return table.act(mid, option, state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"])

    for _ in range(6):
        state = table.state(mid)
        if state["menu"]["actor_id"] == gale:
            break
        act(state["menu"]["end_turn"])
    group = next(g for g in state["menu"]["actions"] if g["label"] == "Storm Without Direction: " + choice)
    assert act(group["options"][0]["candidate_id"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    zone = next(z for z in loaded.engine.state.zones.values() if z.trigger_profile.get("name") == "Storm Without Direction")
    cells = {(p.x, p.y) for p in zone.affected_cells}
    assert zone.trigger_profile["size_ft"] == 120 and zone.radius_cells == 24
    assert (23, 5) in cells and (27, 5) in cells  # 100 feet and the 120-foot edge.
    assert (28, 5) not in cells  # 125 feet is outside.
    assert all(0 <= x < 40 and 0 <= y < 10 for x, y in cells)
    assert loaded.mechanical.replay()["status"] == "PASS"

    if choice not in ("No Straight Line", "No Steady Foot"):
        return
    act(table.state(mid)["menu"]["end_turn"])
    state = table.state(mid)
    assert state["menu"]["actor_id"] == rival
    if choice == "No Steady Foot":
        move = next(m for m in state["menu"]["moves"] if m["destination"] == {"x": 27, "y": 5})
        assert act(move["candidate_id"])["status"] == "COMMITTED"
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert any(c.condition_id == "condition:typed.prone" for c in loaded.engine.state.actors[rival].conditions.values())
        assert loaded.mechanical.replay()["status"] == "PASS"
        return
    group = next(g for g in state["menu"]["actions"] if g["label"].startswith("Gong Jian"))
    assert act(group["options"][0]["candidate_id"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    attack = next(e for e in reversed(loaded.engine.events) if e.event_type == "ATTACK_ROLLED")
    assert attack.payload["mode"] == "DISADVANTAGE"
    assert loaded.mechanical.replay()["status"] == "PASS"
