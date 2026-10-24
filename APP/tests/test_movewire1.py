"""Native movement grants and stale-rider cleanup, through synthetic saved tables."""
import json

import pytest

from combat import falling, flight, roof_movement
from combat.gate2_runtime_models import Position
from combat.tabletop import normalize_map, to_battlefield
from tests.h1_support import ROOT, script
from tests.test_tabletop_hunt6 import on_hold
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle

DISEASE = "tianxia.talent.disease.plague_sovereign_incarnation"
THUNDER = "tianxia.talent.lightning.when_potential_becomes_judgment"
SLEEVES = "TAL_SCOUNDREL_SOVEREIGN_OF_TEN_THOUSAND_EMPTY_SLEEVES"
BEAST = "tianxia.subpath.body.hundred_beast_scripture.feature."
COURT = "TAL_FORCE_COURT_OF_THE_ANSWERING_WORLD"


def table(tmp_path, ids, *, roof=False, primary="Qi", owner_speed=30):
    document = normalize_map({
        "display_name": "Movement wiring yard", "width_squares": 6, "height_squares": 6,
        "walls": ([{"shape": "rect", "points": [[2, 2], [4, 4]], "filled": False,
                   "height_ft": 10}] if roof else []),
        "roofs": {"height_ft": 10, "climb_check": "none"},
    })
    return fixture(tmp_path, ids, cl=18, primary=primary, owner_speed=owner_speed,
                   positions={OWNER: {"x": 1, "y": 3}, ALLY: {"x": 0, "y": 1},
                              FOE: {"x": 5, "y": 0}},
                   battlefield=to_battlefield(document))


def use(combat, service, mid, name):
    engine = combat._load_session(mid).engine
    chosen = next(c for c in engine.legal_candidates()
                  if str(getattr(engine.action_catalog.get(c.source_definition_id),
                                 "display_name", c.display_name)).casefold() == name.casefold())
    settle(service, mid, chosen.candidate_id)


def movement(combat, mid, destination, *, mode=None):
    engine = combat._load_session(mid).engine
    return next(c for c in engine.legal_candidates()
                if c.kind == "MOVE" and c.destination == destination
                and (mode is None or c.metadata.get("movement_mode") == mode))


@pytest.mark.parametrize("source,name,speed", [
    (DISEASE, "Plague-Sovereign Incarnation", 40),
    (THUNDER, "When Potential Becomes Judgment: Body Becomes Thunder", 120),
    (SLEEVES, "Sovereign of Ten Thousand Empty Sleeves", 40),
])
def test_timed_flight_is_native_hover_not_extra_walking_and_survives_reload(tmp_path, source, name, speed):
    combat, service, mid = table(tmp_path, [source])
    before = reload(tmp_path, mid).state.actors[OWNER].movement_remaining_ft
    use(combat, service, mid, name)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert flight.profile(engine, actor).speed_ft == speed
    assert not any("Condition not in the rules file" in str(event.payload)
                   for event in engine.events)
    assert flight.profile(engine, actor).hover
    assert engine._effective_speed(actor) == 30 and actor.movement_remaining_ft == before
    grant = next(c for c in actor.conditions.values() if c.data.get("fly_speed_ft") == speed)
    assert grant.expires_on not in (None, "UNTIL_REMOVED", "CONSUMED")
    up = actor.position.model_copy(update={"z": 2})
    settle(service, mid, movement(combat, mid, up).candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.position == up
    assert flight.remaining(engine, actor, "fly") == speed - 10
    assert not falling.required(engine, actor)


def test_sovereign_live_flight_and_climb_speed_use_the_same_current_speed(tmp_path, monkeypatch):
    ids = [BEAST + "beast_scripture_initiate", BEAST + "sovereign_of_ten_thousand_beasts"]
    combat, service, mid = table(tmp_path, ids, roof=True, primary="Stamina")
    use(combat, service, mid, "Sovereign of Ten Thousand Beasts")
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert engine._effective_speed(actor) == 40  # all Aspects include Crane's +10
    assert flight.profile(engine, actor).speed_ft == roof_movement.profile(engine, actor).speed_ft == 40
    routes = roof_movement.routes(engine, actor)
    up = Position(x=1, y=3, z=2)
    assert routes[up][1:] == (10, "climb")  # no ordinary double-cost climbing
    settle(service, mid, movement(combat, mid, up, mode="climb").candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].climbing
    assert engine.state.actors[OWNER].movement_remaining_ft == 20
    assert flight.remaining(engine, engine.state.actors[OWNER], "climb") == 30

    def slow(e):
        e._add_modifier(e.state.actors[OWNER], "test:slow", "speed_ft", "ADD", -10, "ALL",
                        expires_on="UNTIL_REMOVED")
    on_hold(monkeypatch, slow)
    use(combat, service, mid, "Hold Position")
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert engine._effective_speed(actor) == 30
    assert flight.profile(engine, actor).speed_ft == roof_movement.profile(engine, actor).speed_ft == 30
    assert flight.profile(engine, actor).hover
    assert flight.profile(engine, engine.state.actors[ALLY]).speed_ft == 0
    assert roof_movement.profile(engine, engine.state.actors[ALLY]).speed_ft == 0


def test_body_becomes_thunder_flight_expires_at_end_of_owners_next_turn(tmp_path):
    combat, service, mid = table(tmp_path, [THUNDER])
    use(combat, service, mid, "When Potential Becomes Judgment: Body Becomes Thunder")
    # End this turn, then every intervening turn, then the owner's next turn.
    settle(service, mid, service.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert flight.profile(engine, engine.state.actors[OWNER]).speed_ft == 120
    for _ in range(4):
        if service.state(mid)["menu"]["actor_id"] == OWNER:
            break
        settle(service, mid, service.state(mid)["menu"]["end_turn"])
    assert service.state(mid)["menu"]["actor_id"] == OWNER
    engine = reload(tmp_path, mid)
    assert flight.profile(engine, engine.state.actors[OWNER]).speed_ft == 120
    settle(service, mid, service.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert flight.profile(engine, engine.state.actors[OWNER]).speed_ft == 0


def test_court_native_fall_rolls_damage_then_reduces_it_and_reloads(tmp_path, monkeypatch):
    combat, service, mid = table(tmp_path, [COURT])
    use(combat, service, mid, "Court of the Answering World")
    before = reload(tmp_path, mid).state.actors[ALLY].current_hp

    def launch(e):
        script(e, [6] * 6)
        falling.displace(e, e.state.actors[ALLY], 12, "test:launch", intent=e._active_intent)
    on_hold(monkeypatch, launch)
    use(combat, service, mid, "Hold Position")
    engine = reload(tmp_path, mid)
    target = engine.state.actors[ALLY]
    assert target.position.z == 0
    assert target.current_hp == before - (36 - engine.state.actors[OWNER].proficiency_bonus)
    assert any(c.condition_id.endswith(".prone") for c in target.conditions.values())
    assert any(e.payload.get("fall_distance_ft") == 60 and e.payload.get("damage_taken") == 32
               for e in engine.events)


def test_sovereign_of_beasts_has_no_climb_speed_gm_rider():
    # Climb Speed is native (combat/ext/beast_aspects.py + combat/roof_movement.py): the climb
    # costs no extra movement and the engine rolls the difficult wall's Athletics DC 15 check.
    # Owner rule 2026-10-20 forbids a GM rider for a clause the table automates; only carrying,
    # lifting, pushing and dragging stay manual.
    mechanics = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    riders = mechanics[BEAST + "sovereign_of_ten_thousand_beasts"]["riders"]
    assert all("Climb Speed" not in rider for rider in riders)
    # The manual carrying/lifting/pushing/dragging disclosure stays: two riders, the Large note and that one.
    # Public CI ships owner wording masked, so its exact words are asserted here by count, not by text.
    assert len(riders) == 2


def test_movement_grants_no_longer_have_manual_movement_riders():
    mechanics = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    forbidden = {DISEASE: "flight/altitude", THUNDER: "flight/altitude",
                 SLEEVES: "GM: gain Fly Speed", COURT: "Reduce falling and collision damage",
                 BEAST + "sovereign_of_ten_thousand_beasts": "Fly Speed with Hover"}
    for source, obsolete in forbidden.items():
        assert all(obsolete not in rider for rider in mechanics[source]["riders"])
