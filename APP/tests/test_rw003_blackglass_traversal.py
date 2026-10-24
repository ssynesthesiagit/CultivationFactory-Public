"""RW003 packet P3: Blackglass Rampart panels hurt a hostile that climbs or moves across them.

Printed text (rules_text.json TAL_MAGMA_BLACKGLASS_RAMPART): "A hostile creature that climbs or
moves across a panel takes Slashing damage equal to your Proficiency Bonus once per turn", and
"not when panels are raised". The row's typed effect is a *deferred* damage row
(combat/rules/terrain.json "blackglass rampart" carries the wall's own "enter" trigger): the
compiler builds that trigger (combat/factory_compiler.py _zone_spec) and removes the deferral
there, because the enter moment is the later trigger the row was waiting for. combat/zones.py
_run_trigger already limits a zone trigger to once per turn per zone and trigger, and on_moved
only fires "enter" on movement -- creating the wall is not a move.

The rest of the record (height 10 ft, panel object AC/HP, Cover) is packet P2's test,
tests/test_rw003_wall_height_and_object.py.
"""

from pathlib import Path

from combat import zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.rw003_blackglass"


def _sheet(talents: list[str], sphere: str) -> dict:
    return {**SHEET, "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}}


def _fight(sheet: dict, *, foe_at=(7, 6), ally: bool = False) -> Gate4ControllerEngine:
    teams = {ME: "team:a", AN: "team:b"}
    actors = [ME, AN]
    positions = {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}
    if ally:
        teams[LEE], actors, positions[LEE] = "team:a", [ME, AN, LEE], {"x": 3, "y": 5}
    engine = Gate4ControllerEngine(
        ROOT, match_seed="RW003-BLACKGLASS",
        typed_bundles=(compile_character(sheet, actor_id=ME),),
        roster_setup={"primary_actor_ids": actors, "team_by_actor": teams, "starting_positions": positions})
    _turn(engine, ME)
    return engine


def _turn(engine: Gate4ControllerEngine, actor_id: str) -> None:
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _cast_wall(engine: Gate4ControllerEngine, name: str, at: tuple[int, int]) -> object:
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.split(" at ")[0] == name
                     and c.destination is not None and (c.destination.x, c.destination.y) == at)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=candidate.actor_id,
                                       target_ids=candidate.target_ids, destination=candidate.destination))
    return next(zone for zone in zones.typed_zones(engine) if zone.trigger_profile.get("wall"))


def _move(engine: Gate4ControllerEngine, actor: object, to: tuple[int, int]) -> None:
    """One committed move into a square (the combat/zones.py entry seam test_auto_docket.py uses)."""
    start, actor.position = actor.position, Position(x=to[0], y=to[1])
    zones.on_moved(engine, actor, start, actor.position)


def _blackglass(**kw) -> Gate4ControllerEngine:
    return _fight(_sheet(["TAL_MAGMA_BLACKGLASS_RAMPART"], "tianxia.sphere.magma"), **kw)


def test_a_hostile_entering_a_panel_takes_pb_slashing_once():
    engine = _blackglass()
    zone = _cast_wall(engine, "Blackglass Rampart", (6, 6))
    foe, pb = engine.state.actors[AN], int(zone.trigger_profile["numbers"]["pb"])
    panel = {(cell.x, cell.y) for cell in zone.affected_cells}
    assert panel == {(6, 4), (6, 5), (6, 6), (6, 7)} and (foe.position.x, foe.position.y) not in panel
    # Cover only: the printed panels are climbable, so their squares stay walkable (no blocks_movement).
    assert panel <= set(engine.grid.cover) and not panel & set(engine.grid.blocked)

    _turn(engine, AN)
    before, events = foe.current_hp, len(engine.events)
    _move(engine, foe, (6, 6))

    assert foe.current_hp == before - pb  # "Slashing damage equal to your Proficiency Bonus"
    dealt = [event for event in engine.events[events:] if event.event_type == "DAMAGE_COMMITTED"]
    assert len(dealt) == 1 and dealt[0].payload["hp_damage"] == pb and dealt[0].payload["damage_type"] == "SLASHING"
    entered = [event for event in engine.events[events:] if event.event_type == "PASSIVE_TRIGGERED"]
    assert [event.payload.get("moment") for event in entered] == ["enter"]


def test_a_second_crossing_in_the_same_turn_takes_nothing_more():
    engine = _blackglass()
    _cast_wall(engine, "Blackglass Rampart", (6, 6))
    foe = engine.state.actors[AN]
    _turn(engine, AN)
    before = foe.current_hp
    _move(engine, foe, (6, 6))
    pb = before - foe.current_hp
    assert pb > 0

    _move(engine, foe, (7, 6))  # leaves the panel
    _move(engine, foe, (6, 6))  # "moves across a panel" again, same turn: "once per turn"

    assert foe.current_hp == before - pb


def test_the_next_turn_takes_the_slashing_again():
    engine = _blackglass()
    _cast_wall(engine, "Blackglass Rampart", (6, 6))
    foe = engine.state.actors[AN]
    _turn(engine, AN)
    before = foe.current_hp
    _move(engine, foe, (6, 6))
    pb = before - foe.current_hp
    assert pb > 0

    engine.state.round_number += 1
    _turn(engine, AN)
    _move(engine, foe, (7, 6))
    _move(engine, foe, (6, 6))

    assert foe.current_hp == before - 2 * pb


def test_raising_the_wall_over_a_hostile_creates_no_damage():
    engine = _blackglass(foe_at=(6, 6))  # the foe already stands in a panel square before the wall exists
    foe = engine.state.actors[AN]
    before, events = foe.current_hp, len(engine.events)

    zone = _cast_wall(engine, "Blackglass Rampart", (6, 6))

    assert (6, 6) in {(cell.x, cell.y) for cell in zone.affected_cells}  # it really is under a panel
    assert foe.current_hp == before  # "not when panels are raised"
    assert not [event for event in engine.events[events:]
                if event.event_type in ("DAMAGE_COMMITTED", "PASSIVE_TRIGGERED")]


def test_allies_and_the_caster_take_no_panel_damage():
    engine = _blackglass(ally=True)
    _cast_wall(engine, "Blackglass Rampart", (6, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[LEE]
    mine, theirs = me.current_hp, ally.current_hp

    _move(engine, me, (6, 5))  # the caster crosses its own panel
    _turn(engine, LEE)
    _move(engine, ally, (6, 4))  # an ally walks onto it

    assert me.current_hp == mine and ally.current_hp == theirs


def test_humble_wall_entry_is_unchanged():
    engine = _fight(_sheet(["TAL_EARTH_HUMBLE_WALL"], "tianxia.sphere.earth"))
    zone = _cast_wall(engine, "Humble Wall", (4, 6))
    assert not zone.trigger_profile.get("triggers")  # no deferred damage to run on entry
    foe = engine.state.actors[AN]
    cell = zone.affected_cells[0]
    before, events = foe.current_hp, len(engine.events)

    _turn(engine, AN)
    _move(engine, foe, (cell.x, cell.y))

    assert foe.current_hp == before
    assert not [event for event in engine.events[events:] if event.event_type in ("DAMAGE_COMMITTED", "PASSIVE_TRIGGERED")]
