"""Reclaim a scene vessel without consuming an unused prepared doll.

Printed order (Raise the Vessel: "One suitable puppet vessel"; no printed rule ranks props against the puppeteer's own
prepared item, so the default is the puppeteer's item first): a prepared doll that is already placed keeps its square,
and raising a prop on another square deactivates the doll only as the second vessel. Raising onto an inactive scene
vessel reclaims that prop and leaves the doll intact.
"""
from combat.ext import placed
from combat.tabletop import normalize_map
from tests.auto28_puppetry_support import turn
from tests.puppet_scene_support import (
    A, B, PID, OTHER, SOURCE, SPHERE, TOOLS, _raise_at, choose, cold, native,
)


def test_reclaiming_a_scene_prop_leaves_the_placed_doll_intact_after_reload(tmp_path):
    combat, table = native(tmp_path)
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=choose(table, TOOLS[0]))
    scene = combat.tabletop_maps.save(normalize_map({
        "map_id": "reclaim-scene", "display_name": "Reclaim scene",
        "width_squares": 12, "height_squares": 8,
        "starts": {"team1": [[3, 6]], "team2": [[10, 6]]},
        "objects": [
            {"id": 1, "kind": "crate", "name": "first puppet", "x": 5, "y": 6, "hp": 20},
            {"id": 2, "kind": "crate", "name": "second puppet", "x": 6, "y": 6, "hp": 20},
        ],
    }))
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id="battlefield:map." + scene["map_id"],
        positions={A: {"x": 3, "y": 6}, B: {"x": 4, "y": 6}}, base_paces={A: 12000, B: 12000})
    jid = state["journey_id"]
    option = next(o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    item = state["actors"][A]["rest_preparations"][SOURCE]
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]
    # The doll is raised on its own empty square first, so no prop square is taken by it.
    _raise_at(table, combat, mid, A, (3, 5))
    turn(table, mid, B)
    _raise_at(table, combat, mid, A, (5, 6))
    combat, table = cold(tmp_path)
    engine = combat._load_session(mid).engine
    doll = next(z for z in placed.of(engine, "vessel", owner_id=A)
                if placed.data(z).get("item_instance_id") == item["item_instance_id"])
    first = next(z for z in placed.of(engine, "vessel", owner_id=A)
                 if placed.data(z).get("scene_object_id") == "object:map.1")
    assert placed.data(first)["state"] == "active"
    assert not engine.state.objects["object:map.1"].unattended
    assert placed.data(doll)["state"] == "inactive"
    turn(table, mid, B)
    _raise_at(table, combat, mid, A, (6, 6))
    combat, table = cold(tmp_path)
    engine = combat._load_session(mid).engine
    # Re-read the zone after this reload: a zone object from before it is stale.
    first = next(z for z in placed.of(engine, "vessel", owner_id=A)
                 if placed.data(z).get("scene_object_id") == "object:map.1")
    assert placed.data(first)["state"] == "inactive"
    assert not engine.state.objects["object:map.1"].unattended
    turn(table, mid, B)
    _raise_at(table, combat, mid, A, (5, 6))
    combat, table = cold(tmp_path)
    engine = combat._load_session(mid).engine
    zones = placed.of(engine, "vessel", owner_id=A)
    first = next(z for z in zones if placed.data(z).get("scene_object_id") == "object:map.1")
    assert placed.data(first)["state"] == "active"
    assert not placed.data(first).get("item_instance_id")
    second = next(z for z in zones if placed.data(z).get("scene_object_id") == "object:map.2")
    assert placed.data(second)["state"] == "inactive"
    assert sum(1 for z in zones if placed.data(z).get("item_instance_id")) == 1
    saved = combat.journeys.actor_preparations(A)[SOURCE]
    assert saved["item_instance_id"] == item["item_instance_id"] and saved["broken"] == 0
