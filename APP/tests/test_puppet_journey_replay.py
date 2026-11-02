"""Combat product updates checkpoint the current journey, not its history."""
from combat.tabletop import normalize_map
from tests.puppet_scene_support import (
    A, B, PID, OTHER, SOURCE, SPHERE, TOOLS, choose, cold, native, _raise_at,
)


def test_raise_checkpoints_active_journey_and_preserves_finished_journey(tmp_path):
    combat, table = native(tmp_path)
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=choose(table, TOOLS[0]))
    scene = combat.tabletop_maps.save(normalize_map({
        "map_id": "puppet-replay", "display_name": "Puppet replay",
        "width_squares": 12, "height_squares": 8,
        "starts": {"team1": [[3, 6]], "team2": [[10, 6]]},
    }))
    args = dict(project_ids=[PID, OTHER], arena_id="battlefield:map." + scene["map_id"],
                positions={A: {"x": 3, "y": 6}, B: {"x": 4, "y": 6}},
                base_paces={A: 12000, B: 12000})
    earlier = combat.create_journey(**args)
    old_id = earlier["journey_id"]
    combat.journey_act(old_id, earlier["revision"], A, "finish", {})
    before = combat.journey_replay(old_id)
    assert before["status"] == "PASS"

    state = combat.create_journey(**args)
    jid = state["journey_id"]
    option = next(o for o in combat.journey_menu(jid, A)["options"]
                  if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, state["revision"], A, option["kind"], option["payload"])
    product = state["actors"][A]["rest_preparations"][SOURCE]
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]
    result, _ = _raise_at(table, combat, mid, A, (3, 5))
    assert result["status"] == "COMMITTED"
    combat, _ = cold(tmp_path)
    updated = combat.journeys.actor_preparations(A)[SOURCE]
    assert updated != product
    assert combat.journey_replay(jid)["status"] == "PASS"
    assert combat.journey_replay(old_id) == before
