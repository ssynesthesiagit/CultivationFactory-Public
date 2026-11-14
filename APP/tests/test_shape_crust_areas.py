"""On 2026-11-14 Shape the Crust could not cool or crack terrain made by Lava Burst:
"your terrain" searched only Magma Glob placements. Exercise aimed squares of
larger areas through synthetic, persisted tables and built-in catalog rows.
"""
from copy import deepcopy

import pytest

from combat import zones
from combat.ext import area_suppression, magma_crust, placed
from combat.ext.effect_durations import round_token
from combat.gate5_service import CombatService
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, reload, settle, turn
from tests.hunt15_support import act

BURST = "TAL_MAGMA_LAVA_BURST"
SHAPE = "TAL_MAGMA_SHAPE_THE_CRUST"
MAGMA = "tianxia.sphere.magma"
AIM = (5, 6)
CENTER = (8, 6)


def cells(zone):
    return {(p.x, p.y) for p in zone.affected_cells}


def clear_arena(arena):
    arena["terrain_regions"] = []
    arena["map_terrain"] = []
    arena["map_objects"] = []
    arena["tabletop"] = {"walls": [], "trees": [], "floors": [], "ambient": {"level": "bright"}}


def table(tmp_path, **kwargs):
    return fight(tmp_path, [BURST, SHAPE], spheres=[MAGMA], ally=[], maximum_rounds=15,
                 positions={LEFT: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6},
                            RIGHT: {"x": 17, "y": 10}}, arena_edit=clear_arena, **kwargs)


def typed(engine, candidate):
    action = engine.action_catalog.get(candidate.source_definition_id)
    return (action.parameters or {}).get("typed", {}) if action else {}


def candidates(engine, source=SHAPE, op=None):
    return [c for c in engine.legal_candidates()
            if typed(engine, c).get("source") == source
            and (op is None or any(e.get("type") == "magma_shape" and e.get("op") == op
                                  for e in typed(engine, c).get("effects", [])))]


def send_at(combat, tabletop, mid, source, at, op=None):
    def send(answers):
        state = tabletop.state(mid)
        menu = state["menu"]
        engine = combat._load_session(mid).engine
        candidate = next(c for c in candidates(engine, source, op)
                         if c.destination and (c.destination.x, c.destination.y) == at)
        return tabletop.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"],
                            state["last_sequence"], answers)
    return send


def shape(combat, tabletop, mid, op, at=AIM):
    def choose(prompt):
        if prompt["context"]["reaction_source_id"] == "choice:needle.magma_safe_step":
            return [ALLY]
        return [prompt["choice"]["options"][0]["id"]]
    return settle(send_at(combat, tabletop, mid, SHAPE, at, op), choose)


def move(combat, tabletop, mid, at):
    def send(answers):
        state = tabletop.state(mid)
        engine = combat._load_session(mid).engine
        candidate = next(c for c in engine.legal_candidates()
                         if c.kind.value == "MOVE" and c.destination
                         and (c.destination.x, c.destination.y) == at)
        return tabletop.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
                            state["menu"]["state_version"], state["last_sequence"], answers)
    return settle(send)


def burst(combat, tabletop, mid):
    settle(send_at(combat, tabletop, mid, BURST, CENTER))
    engine = reload(combat, mid)
    zone, = [z for z in engine.state.zones.values() if z.active and z.owner_id == LEFT
             and "molten terrain" in z.trigger_profile.get("terrain", [])]
    assert len(cells(zone)) > 1 and AIM in cells(zone) and AIM != CENTER
    assert not any((a.position.x, a.position.y) in cells(zone) for a in engine.state.actors.values())
    return zone


def ground_at(engine, at, name):
    return [z for z in zones.typed_zones(engine) if at in cells(z)
            and name + " terrain" in z.trigger_profile.get("terrain", [])]


def longer_ground(*, moving=False):
    return {"shape": "emanation" if moving else "sphere", "size_ft": 15,
            "centered_on_self": moving, "follows_owner": moving,
            "terrain": ["molten terrain"], "difficult": "all",
            "name": "Synthetic Molten Terrain", "duration": {"kind": "minutes", "amount": 1}}


def prepare_ground(combat, tabletop, mid):
    settle(lambda answers: act(tabletop, mid, "Prepare", answers))
    engine = reload(combat, mid)
    zone, = [z for z in engine.state.zones.values() if z.active and z.owner_id == LEFT]
    return zone


def test_lava_burst_cool_is_offered_and_changes_only_the_aimed_square(tmp_path):
    combat, tabletop, mid = table(tmp_path)
    parent = burst(combat, tabletop, mid)
    before = cells(parent)
    assert AIM in {(c.destination.x, c.destination.y)
                   for c in candidates(reload(combat, mid), op="cool")}
    shape(combat, tabletop, mid, "cool")
    engine = reload(combat, mid)
    assert cells(engine.state.zones[parent.zone_id]) == before - {AIM}
    assert not ground_at(engine, AIM, "molten")
    patch, = ground_at(engine, AIM, "obsidian")
    assert cells(patch) == {AIM} and patch.duration_rounds == 10
    record, = area_suppression.records(engine.state.zones[parent.zone_id])
    assert record["cells"] == [list(AIM)] and "lent_patch" not in record
    assert record["until"] == round_token(engine, 10)


@pytest.mark.parametrize("origin", ["cool", "larger_obsidian_area"])
def test_cooled_square_can_be_cracked_with_a_dex_save_for_its_occupant(tmp_path, origin):
    if origin == "cool":
        combat, tabletop, mid = table(tmp_path)
        burst(combat, tabletop, mid)
        shape(combat, tabletop, mid, "cool")
        parent_id, before = None, None
    else:
        spec = longer_ground()
        spec.update(terrain=["obsidian terrain"], centered_on_self=True)
        combat, tabletop, mid = table(tmp_path, prepare=[{"type": "zone"}],
                                     prepare_target="SELF", prepare_zone_spec=spec)
        parent = prepare_ground(combat, tabletop, mid)
        parent_id, before = parent.zone_id, cells(parent)
    turn(tabletop, mid, ALLY)
    move(combat, tabletop, mid, AIM)
    turn(tabletop, mid, LEFT)
    engine = reload(combat, mid)
    hp = engine.state.actors[ALLY].current_hp
    start = len(engine.events)
    assert AIM in {(c.destination.x, c.destination.y) for c in candidates(engine, op="crack")}
    shape(combat, tabletop, mid, "crack")
    engine = reload(combat, mid)
    saves = [e for e in engine.events[start:] if e.event_type == "SAVE_ROLLED" and e.actor_id == ALLY]
    assert len(saves) == 1 and saves[0].payload["reason"].endswith(":DEX")
    action = next(a for a in engine.action_catalog.values()
                  if (a.parameters or {}).get("typed", {}).get("source") == SHAPE)
    pb = action.parameters["typed"]["numbers"]["pb"]
    assert engine.state.actors[ALLY].current_hp == hp - (0 if saves[0].payload["success"] else pb)
    assert not ground_at(engine, AIM, "obsidian")
    if parent_id is not None:
        parent = engine.state.zones[parent_id]
        assert parent.active and cells(parent) == before - {AIM}
        record, = area_suppression.records(parent)
        assert record["until"] == area_suppression.AREA_ENDS and "lent_patch" not in record


def test_another_creatures_molten_area_offers_no_shape_option(tmp_path):
    combat, tabletop, mid = table(tmp_path, right_talents=[BURST], right_spheres=[MAGMA])
    turn(tabletop, mid, RIGHT)
    settle(send_at(combat, tabletop, mid, BURST, CENTER))
    turn(tabletop, mid, LEFT)
    engine = reload(combat, mid)
    assert ground_at(engine, AIM, "molten")
    assert all(z.owner_id == RIGHT for z in ground_at(engine, AIM, "molten"))
    assert not candidates(engine)


def test_moving_area_keeps_the_cooled_board_square_out_after_its_owner_moves(tmp_path):
    combat, tabletop, mid = table(tmp_path, prepare=[{"type": "zone"}],
                                 prepare_target="SELF", prepare_zone_spec=longer_ground(moving=True))
    parent = prepare_ground(combat, tabletop, mid)
    at = (4, 7)
    assert at in cells(parent)
    shape(combat, tabletop, mid, "cool", at)
    move(combat, tabletop, mid, (3, 7))
    engine = reload(combat, mid)
    parent = engine.state.zones[parent.zone_id]
    assert parent.center == engine.state.actors[LEFT].position
    assert at in {(p.x, p.y) for p in zones.area_cells(engine, parent)}
    assert at not in cells(parent)
    assert cells(parent) == {(p.x, p.y) for p in zones.area_cells(engine, parent)} - {at}
    assert ground_at(engine, at, "obsidian")


def test_lava_burst_and_cooled_square_replay_to_identical_zones(tmp_path):
    combat, tabletop, mid = table(tmp_path)
    burst(combat, tabletop, mid)
    shape(combat, tabletop, mid, "cool")
    original = {k: z.model_dump(mode="json") for k, z in combat._load_session(mid).engine.state.zones.items()}
    session = CombatService(combat.source_root, tmp_path)._load_session(mid)
    replay = session.mechanical.replay()
    assert replay["status"] == "PASS"
    assert replay["state"]["zones"] == original
    assert {k: z.model_dump(mode="json") for k, z in session.engine.state.zones.items()} == original


def test_safe_line_waives_only_one_square_of_a_larger_lava_burst_area(tmp_path):
    combat, tabletop, mid = table(tmp_path)
    parent = burst(combat, tabletop, mid)
    shape(combat, tabletop, mid, "safe")
    engine = reload(combat, mid)
    parent = engine.state.zones[parent.zone_id]
    patch, = [z for z in placed.of(engine, magma_crust.TAG) if z.zone_id != parent.zone_id]
    assert cells(patch) == {AIM} and patch.duration_rounds is None
    assert AIM not in cells(parent) and (6, 6) in cells(parent)
    assert AIM not in zones.difficult_cells(engine, engine.state.actors[ALLY])
    assert (6, 6) in zones.difficult_cells(engine, engine.state.actors[ALLY])
    assert AIM in zones.difficult_cells(engine, engine.state.actors[RIGHT])
    turn(tabletop, mid, ALLY)
    before = reload(combat, mid).state.actors[ALLY].movement_remaining_ft
    move(combat, tabletop, mid, AIM)
    after_safe = reload(combat, mid).state.actors[ALLY].movement_remaining_ft
    assert before - after_safe == 5
    move(combat, tabletop, mid, (6, 6))
    assert after_safe - reload(combat, mid).state.actors[ALLY].movement_remaining_ft == 10


@pytest.mark.parametrize("op", ["safe", "move"])
def test_parent_area_ending_also_ends_its_lent_patch(tmp_path, op):
    combat, tabletop, mid = table(tmp_path)
    parent = burst(combat, tabletop, mid)
    profile = deepcopy(parent.trigger_profile)
    before = cells(parent)
    shape(combat, tabletop, mid, op)
    engine = reload(combat, mid)
    record, = area_suppression.records(engine.state.zones[parent.zone_id])
    if op == "move":
        assert record["until"] == area_suppression.AREA_ENDS
    else:
        assert record["until"].startswith("START_OF_TURN_AT:")
    patch = engine.state.zones[record["lent_patch"]]
    assert patch.active and patch.duration_rounds is None
    assert patch.source_definition_id == parent.source_definition_id and patch.owner_id == parent.owner_id
    assert patch.trigger_profile["terrain"] == profile["terrain"]
    assert patch.trigger_profile["triggers"] == profile["triggers"]
    assert patch.trigger_profile["numbers"] == profile["numbers"]
    assert len(cells(patch)) == 1
    if op == "move":
        assert not cells(patch) & before
    turn(tabletop, mid, ALLY)
    turn(tabletop, mid, LEFT)
    engine = reload(combat, mid)
    assert not engine.state.zones[parent.zone_id].active
    assert not engine.state.zones[patch.zone_id].active
    assert not area_suppression.records(engine.state.zones[parent.zone_id])


def test_safe_line_expiry_restores_the_square_and_drops_the_lent_patch(tmp_path):
    spec = longer_ground()
    spec["centered_on_self"] = True
    combat, tabletop, mid = table(tmp_path, prepare=[{"type": "zone"}],
                                 prepare_target="SELF", prepare_zone_spec=spec)
    parent = prepare_ground(combat, tabletop, mid)
    before = cells(parent)
    shape(combat, tabletop, mid, "safe")
    engine = reload(combat, mid)
    record, = area_suppression.records(engine.state.zones[parent.zone_id])
    patch_id = record["lent_patch"]
    assert AIM not in cells(engine.state.zones[parent.zone_id])
    turn(tabletop, mid, ALLY)
    turn(tabletop, mid, LEFT)
    engine = reload(combat, mid)
    parent = engine.state.zones[parent.zone_id]
    assert parent.active and cells(parent) == before
    assert not area_suppression.records(parent) and not engine.state.zones[patch_id].active
    assert AIM in zones.difficult_cells(engine, engine.state.actors[ALLY])
