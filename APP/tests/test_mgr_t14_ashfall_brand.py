"""Assigned base rows through compiled sheets, table intents and cold reload.

No live model requests. The repeat-hit case only relaxes action economy in its
fixture; the attack, pressure choices and turn clock are the native providers.
"""
import json
from functools import lru_cache

import pytest

from combat.ext import ash_core, placed
from combat.typed_executor import stored_healing_reductions
from tests.auto_worker1_support import (
    LEFT, RIGHT, act, action_sender, cell_send, fight, reload, settle, turn,
)
from tests.test_auto62_destruction import cell_sender
from tests.h1_support import ROOT
from sphere_component_authority import (
    attach_sphere_automatic_component_receipt, build_sphere_automatic_component_authority,
)

ASHFALL = "ASH_BASE_ASHFALL"
BRAND = "ASH_BASE_CINDER_BRAND"
SPHERE = "tianxia.sphere.ash"
POOL = "resource:core.qi"


@lru_cache(maxsize=1)
def grants():
    """The native acquisition producer consumes the real catalog's Ash packet."""
    catalog = json.loads((ROOT / "catalog_authority/cat3/generated/catalog_authority.v1.json").read_text())
    sphere = next(row for row in catalog["spheres"] if row["canonical_sphere_id"] == SPHERE)
    packet = build_sphere_automatic_component_authority(SPHERE, sphere["resolved_automatic_base_abilities"])
    record = {"record_id": SPHERE, "record_hash": sphere["record_commitment_sha256"],
              "automatic_component_authority": packet}
    event = {"event_id": "event.test.ash.acquisition", "advancement": {"target_cl": 1},
             "legal_channel": "ai-bootstrap-free-cl1-sphere",
             "content_binding": {"record_hash": record["record_hash"]}}
    ledger = {}
    attach_sphere_automatic_component_receipt(ledger, record, event)
    components = ledger["automatic_sphere_components"]
    assert {row["component_id"] for row in components} == {ASHFALL, BRAND}
    assert all(row["automatic_grant"] and not row["counts_as_talent_choice"] for row in components)
    return ledger


def acquired(doc, aid):
    """Project actual automatic grants through the production sheet field."""
    if aid == LEFT:
        ledger = grants()
        doc["spheres_and_talents"].update(
            sphere_record_ids=[SPHERE], learned_talent_record_ids=[],
            automatic_sphere_components=ledger["automatic_sphere_components"],
            automatic_sphere_component_receipts=ledger["automatic_sphere_component_receipts"],
            automatic_sphere_component_record_ids=[row["component_id"] for row in ledger["automatic_sphere_components"]])


def table(tmp_path, **kwargs):
    return fight(tmp_path, [], sheet_edit=acquired, left_attack_bonus=100, **kwargs)


def pressure_pick(label):
    def choose(prompt):
        options = [o["id"] for o in prompt["choice"]["options"]]
        return [label] if label in options else options[:1]
    return choose


def remnants(engine, owner=LEFT):
    return placed.of(engine, "ash_remnant", owner_id=owner)


@pytest.mark.parametrize("ai", [False, True])
def test_ashfall_native_grant_geometry_linger_and_reload(tmp_path, ai):
    c, t, m = table(tmp_path, positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 8, "y": 6}})
    before = reload(c, m).state.actors[LEFT].resources[POOL]
    settle(cell_send(t, m, "Ashfall", (8, 6)))
    if ai:
        menu = t.state(m)["menu"]
        engine = c._load_session(m).engine
        offered = next(v for v in engine.legal_candidates()
                       if v.display_name.startswith("Lingering Ashfall"))
        assert any(o["candidate_id"] == offered.candidate_id
                   for group in menu["actions"] for o in group["options"])
        c.set_controller_mode(m, actor_id=menu["actor_id"], controller_mode="LOCAL_AUTO")
        real = c.controller
        from combat.controllers import ManualControllerAdapter
        class CandidateController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (offered.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        c.controller = CandidateController()
    e = reload(c, m)
    zone = next(z for z in e.state.zones.values() if z.active)
    assert zone.center.x == 8 and zone.center.y == 6
    assert zone.duration_rounds == 10 and zone.concentration_link
    assert zone.trigger_profile["terrain"] == ["ash terrain"]
    cells = {(p.x, p.y) for p in zone.affected_cells}
    assert (8, 9) in cells and (8, 10) not in cells
    assert e.state.actors[LEFT].resources[POOL] == before
    _, prompts = settle(action_sender(c, t, m, "Lingering Ashfall (2 CP)", ai=ai))
    assert not prompts
    e = reload(c, m)
    kept = e.state.zones[zone.zone_id]
    assert kept.active and not kept.concentration_link and kept.center == zone.center
    assert e.state.actors[LEFT].concentration is None
    assert e.state.actors[LEFT].resources[POOL] == before - 2
    if ai:
        c.set_controller_mode(m, actor_id=LEFT, controller_mode="MANUAL")
    turn(t, m, RIGHT)
    assert all("Ashfall" not in g["label"] for g in t.state(m)["menu"]["actions"])
    turn(t, m, LEFT)
    e = reload(c, m)
    assert e.state.zones[zone.zone_id].center == zone.center


@pytest.mark.parametrize("ai", [False, True])
def test_pressure_choice_is_after_hit_owned_and_expires(tmp_path, ai):
    c, t, m = table(tmp_path)
    before = reload(c, m).state.actors[LEFT].resources[POOL]
    _, prompts = settle(action_sender(c, t, m, "Cinder Brand: Create Remnant", ai=ai),
                        pressure_pick("Reduce Healing"))
    e = reload(c, m)
    assert any(v.event_type == "ATTACK_ROLLED" for v in e.events)
    assert any("ashen_brand" in row.condition_id for row in e.state.actors[RIGHT].conditions.values())
    assert e.state.actors[LEFT].resources[POOL] == before
    if ai:
        assert not prompts
        assert len(remnants(e)) == 1
        c.set_controller_mode(m, actor_id=LEFT, controller_mode="MANUAL")
    else:
        choice = next(p for p in prompts if p["context"]["reaction_source_id"].endswith(ash_core.PRESSURE))
        assert choice["context"]["reactor_id"] == LEFT
        assert {o["id"] for o in choice["choice"]["options"]} == {
            "Reduce Healing", "Create Remnant", "Move Remnant", "Suppress Temporary HP"}
        assert not remnants(e)
        assert stored_healing_reductions(e, e.state.actors[RIGHT], 20) == 16
        turn(t, m, RIGHT)
        e = reload(c, m)
        assert stored_healing_reductions(e, e.state.actors[RIGHT], 20) == 16
        turn(t, m, LEFT)
        e = reload(c, m)
        assert stored_healing_reductions(e, e.state.actors[RIGHT], 20) == 20
        assert not any("ashen_brand" in row.condition_id for row in e.state.actors[RIGHT].conditions.values())


def test_remnant_move_offers_short_and_bent_destinations_and_cold_reload(tmp_path):
    c, t, m = table(tmp_path, positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 8, "y": 6}})
    settle(action_sender(c, t, m, "Cinder Brand: Create Remnant"), pressure_pick("Create Remnant"))
    e = reload(c, m)
    zone = remnants(e)[0]
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    destination = (zone.center.x + 1, zone.center.y)
    key = f"{zone.zone_id}|cell:{destination[0]},{destination[1]}"

    def choose(prompt):
        ids = [o["id"] for o in prompt["choice"]["options"]]
        if key in ids:
            expected = {(zone.center.x + dx, zone.center.y + dy)
                        for dx in range(-2, 3) for dy in range(-2, 3)
                        if (dx or dy) and e.grid.in_bounds((zone.center.x + dx, zone.center.y + dy))
                        and (zone.center.x + dx, zone.center.y + dy) not in e.grid.blocked}
            assert len(ids) == len(expected)
            assert f"{zone.zone_id}|cell:{zone.center.x + 1},{zone.center.y + 2}" in ids
            return [key]
        return ["Move Remnant"] if "Move Remnant" in ids else ids[:1]

    _, prompts = settle(action_sender(c, t, m, "Cinder Brand: Move Remnant"), choose)
    assert any(key in [o["id"] for o in p["choice"]["options"]] for p in prompts)
    moved = remnants(reload(c, m))[0]
    assert (moved.center.x, moved.center.y) == destination
    assert moved.created_round == zone.created_round
    assert moved.duration_rounds == zone.duration_rounds == 10
    assert not moved.concentration_link


def test_second_hit_same_turn_keeps_damage_and_brand_but_not_pressure(tmp_path):
    def repeat_economy(bundle):
        for action in bundle["action_catalog"]:
            if BRAND in action["source_definition_id"]:
                action["economy"] = "NONE"
                action["parameters"]["free_primary"] = True

    c, t, m = table(tmp_path, bundle_edit=repeat_economy)
    settle(action_sender(c, t, m, "Cinder Brand: Create Remnant"), pressure_pick("Create Remnant"))
    e = reload(c, m)
    assert len(remnants(e)) == 1
    before = e.state.actors[RIGHT].current_hp
    _, prompts = settle(action_sender(c, t, m, "Cinder Brand: Reduce Healing"), pressure_pick("Reduce Healing"))
    e = reload(c, m)
    assert e.state.actors[RIGHT].current_hp < before
    assert not any(p["context"]["reaction_source_id"].endswith(ash_core.PRESSURE) for p in prompts)
    assert stored_healing_reductions(e, e.state.actors[RIGHT], 20) == 20
    assert len(remnants(e)) == 1
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    _, prompts = settle(action_sender(c, t, m, "Cinder Brand: Reduce Healing"), pressure_pick("Reduce Healing"))
    assert any(p["context"]["reaction_source_id"].endswith(ash_core.PRESSURE) for p in prompts)
    e = reload(c, m)
    assert stored_healing_reductions(e, e.state.actors[RIGHT], 20) == 16


@pytest.mark.parametrize("cl,dice", [(1, 1), (5, 2), (11, 3), (17, 4)])
def test_cinder_native_damage_brackets_and_key_modifier(tmp_path, cl, dice):
    c, t, m = table(tmp_path, cl=cl)
    settle(action_sender(c, t, m, "Cinder Brand: Reduce Healing"), pressure_pick("Reduce Healing"))
    e = reload(c, m)
    rolls = [v.payload for v in e.events if v.event_type == "DAMAGE_ROLLED" and v.actor_id == LEFT]
    assert len(rolls) == 1
    # Critical hits double dice only; the real Path key modifier remains +2.
    assert rolls[0]["expression"] in (f"{dice}d8+2", f"{dice * 2}d8+2")


def test_native_range_and_wrong_owner_controls(tmp_path):
    c, t, m = table(tmp_path, positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 16, "y": 6}})
    e = reload(c, m)
    candidates = e.legal_candidates()
    assert not any(v.display_name.startswith("Cinder Brand:") and RIGHT in v.target_ids for v in candidates)
    casts = [v for v in candidates if v.display_name.startswith("Ashfall at ")]
    assert casts and all(e.grid.distance_ft(e.state.actors[LEFT].position, v.destination) <= 60 for v in casts)
    turn(t, m, RIGHT)
    assert not any("Cinder Brand" in g["label"] or "Ashfall" in g["label"] for g in t.state(m)["menu"]["actions"])


def test_lingering_ashfall_expires_at_original_one_minute_boundary(tmp_path):
    c, t, m = table(tmp_path, maximum_rounds=12)
    settle(cell_send(t, m, "Ashfall", (8, 6)))
    settle(lambda answers: act(t, m, "Lingering Ashfall (2 CP)", answers))
    e = reload(c, m)
    zone = next(z for z in e.state.zones.values() if z.active)
    for _ in range(10):
        turn(t, m, RIGHT)
        turn(t, m, LEFT)
    e = reload(c, m)
    assert not e.state.zones[zone.zone_id].active
    assert any(v.event_type == "ZONE_REMOVED" and v.payload.get("reason") == "DURATION_ENDED" for v in e.events)
