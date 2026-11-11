"""Automation lane H3, part 1: the Shield sphere's Faces (Flexible Cover, Projected Shield Face, Moving Rampart, the Mountain) run on
the lock round's ``directional_cover`` hook (combat/ext/shield_faces.py).

Every test compiles a real character with the talent and runs it through the engine: Flexible Cover was RIDERS_ONLY (a fight
showed only the GM's text) and the Modifiers changed nothing.
"""

from pathlib import Path

import pytest

from combat import ext
from combat.directional_cover import cover_bonus
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_auto_lane2 import ALLY, ME, ROOT, _bundle, _conditions, _legal, _me, _ready, _sheet, _use

FACE = "typed.shield_face"
SPHERE = "tianxia.sphere.shield"
FLEX = "TAL_SHIELD_FLEXIBLE_COVER"
PROJECTED = "tianxia.talent.shield.projected_shield_face"
RAMPART = "TAL_SHIELD_MOVING_RAMPART"
MOUNTAIN = "TAL_SHIELD_THE_MOUNTAIN_FITS_BEHIND_ONE_SHIELD"
FOCUS = "resource:core.martial_focus"
NAME = "FLEXIBLE COVER"  # as the catalog prints it
TURN = f"Turn {NAME} face (free, once a turn)"


def _engine(talents, *, me=(6, 6), foe=(6, 3), ally=None):
    bundle = compile_character(_sheet(SPHERE, talents), actor_id=ME)
    bundles, teams, places, roster = (bundle,), {ME: "team:a", AN: "team:b"}, {ME: {"x": me[0], "y": me[1]}, AN: {"x": foe[0], "y": foe[1]}}, [ME, AN]
    if ally is not None:
        bundles += (compile_character(_sheet(None, []), actor_id=ALLY),)
        roster.append(ALLY)
        teams[ALLY], places[ALLY] = "team:a", {"x": ally[0], "y": ally[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed="H3COVER", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": roster, "team_by_actor": teams, "starting_positions": places})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    _ready(engine)
    return engine


def _face(actor):
    return next((c for c in actor.conditions.values() if c.condition_id == "condition:" + FACE), None)


def _raise(engine, edge):
    """The face on ``edge`` without going through the menu (the choice is tested on its own)."""
    from combat.ext import shield_faces

    shield_faces.raise_face(engine, _me(engine), edge, "test:raise")


def _cover(engine, ranged=False, target=ME, attacker=AN):
    return cover_bonus(engine, engine.state.actors[attacker], engine.state.actors[target], ranged=ranged)


# ---------------------------------------------------------------------------------------------------- Flexible Cover
def test_flexible_cover_raises_a_face_on_the_edge_toward_the_nearest_hostile():
    """"Action. Choose one edge of your space and establish a physical Shield Face ... until the start of your next turn": it was
    a GM line with no button at all."""
    engine = _engine([FLEX])
    assert NAME in _legal(engine)
    _use(engine, NAME, target=None)
    face = _face(_me(engine))
    assert face is not None and face.data["edge"] == "N"  # the foe stands north of the bearer
    assert face.expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert not _me(engine).action_available


def test_flexible_cover_gives_three_quarters_cover_to_attacks_that_cross_its_edge():
    engine = _engine([FLEX])
    _raise(engine, "N")
    assert _cover(engine) == 5 and _cover(engine, ranged=True) == 5  # melee and ranged both
    engine.state.actors[AN].position = Position(x=6, y=8)  # a foe on the other side
    assert _cover(engine) == 0 and _cover(engine, ranged=True) == 0
    engine.state.actors[AN].position = Position(x=9, y=6)  # from the east: not the face's edge
    assert _cover(engine) == 0


def test_sovereign_incarnation_widens_projected_faces_and_makes_attack_barriers():
    from combat.ext import shield_faces

    ability = "TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION"
    engine = _engine([FLEX, PROJECTED, ability])
    _me(engine).resources[FOCUS] = 1
    _use(engine, "SOVEREIGN SHIELD-SOUL INCARNATION", target=None)
    assert shield_faces.width_ft(engine, _me(engine)) == 35
    assert _me(engine).resources[FOCUS] == 0
    _raise(engine, "N")
    assert _face(_me(engine)).data["barrier"] is True
    from types import SimpleNamespace

    assert shield_faces.face_candidates(engine, engine.state.actors[AN], SimpleNamespace(target_ids=(ME,)),
                                        SimpleNamespace(attack_bonus=10, parameters={})) is False
    engine.state.round_number += 11
    engine._append_event("TURN_STARTED", "test:expiry", actor_id=ME)
    assert not any(c.condition_id == shield_faces.SOVEREIGN for c in _me(engine).conditions.values())
    assert shield_faces.width_ft(engine, _me(engine)) == 15


def test_sovereign_incarnation_asks_whether_a_face_is_a_barrier_and_can_choose_cover():
    from combat.gate2_runtime_models import ReactionDecision

    ability = "TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION"
    engine = _engine([FLEX, PROJECTED, ability])
    _me(engine).resources[FOCUS] = 1
    _use(engine, "SOVEREIGN SHIELD-SOUL INCARNATION", target=None)
    calls = []

    def choose(request):
        calls.append(request)
        option = "cover" if "cover" in request["legal_option_ids"] else "N"
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=(option,)), None

    engine.set_reaction_provider(choose)
    _use(engine, NAME, target=None)
    assert not _face(_me(engine)).data["barrier"] and _face(_me(engine)).data["width_ft"] == 35
    assert any("barrier" in request["legal_option_ids"] for request in calls)


def test_the_face_is_on_the_chosen_edge_only():
    engine = _engine([FLEX], foe=(6, 3))
    for edge, foe, expected in (("N", (6, 3), 5), ("S", (6, 3), 0), ("E", (9, 6), 5), ("W", (9, 6), 0), ("W", (3, 6), 5), ("S", (6, 9), 5)):
        _me(engine).conditions.clear()
        engine.state.actors[AN].position = Position(x=foe[0], y=foe[1])
        _raise(engine, edge)
        assert _cover(engine) == expected, (edge, foe)


def test_a_diagonal_line_through_the_corner_crosses_both_edges():
    engine = _engine([FLEX], foe=(9, 3))  # north-east: the line enters through the corner of the north and east edges
    _raise(engine, "N")
    assert _cover(engine) == 5
    _me(engine).conditions.clear()
    _raise(engine, "E")
    assert _cover(engine) == 5
    _me(engine).conditions.clear()
    _raise(engine, "S")
    assert _cover(engine) == 0


def test_the_face_does_not_protect_an_attacker_behind_it_or_beside_a_creature_out_of_its_row():
    """An ally behind the face shooting out is not covered against, and the face is not a wall around the bearer's neighbours
    unless it is Projected."""
    engine = _engine([FLEX], ally=(7, 6), foe=(7, 3))
    _raise(engine, "N")
    assert _cover(engine, target=ALLY) == 0  # the ally's own square is beside the bearer's, not behind the face
    assert _cover(engine, target=ME, attacker=ALLY) == 0  # an ally beside the bearer does not cross the face at all


def test_projected_shield_face_covers_the_three_squares_behind_its_plane():
    engine = _engine([FLEX, PROJECTED], ally=(7, 6), foe=(7, 3))
    _raise(engine, "N")
    assert _cover(engine, target=ALLY) == 5  # "a 15-foot-wide plane centered on the chosen edge ... protects creatures behind it"
    engine.state.actors[ALLY].position = Position(x=8, y=6)
    assert _cover(engine, target=ALLY) == 0  # two squares from the bearer: beyond the 15 feet
    engine.state.actors[ALLY].position = Position(x=5, y=6)
    engine.state.actors[AN].position = Position(x=5, y=3)
    assert _cover(engine, target=ALLY) == 5


def test_the_mountain_widens_the_face_to_thirty_feet():
    engine = _engine([FLEX, PROJECTED, MOUNTAIN], ally=(8, 6), foe=(8, 3))
    _raise(engine, "N")
    assert _cover(engine, target=ALLY) == 5  # two squares along: inside 30 feet, outside 15
    plain = _engine([FLEX, PROJECTED], ally=(8, 6), foe=(8, 3))
    _raise(plain, "N")
    assert _cover(plain, target=ALLY) == 0


@pytest.mark.parametrize("moving_talent", [RAMPART, PROJECTED])
def test_a_face_ends_when_the_bearer_leaves_its_space_unless_projected_or_moving_rampart(moving_talent):
    engine = _engine([FLEX])
    _raise(engine, "N")
    assert _face(_me(engine))
    engine._append_event("MOVEMENT_COMMITTED", "test:step", actor_id=ME, payload={})
    assert _face(_me(engine))  # still on the same square
    _me(engine).position = Position(x=7, y=6)
    engine._append_event("MOVEMENT_COMMITTED", "test:step", actor_id=ME, payload={})
    assert _face(_me(engine)) is None and _cover(engine) == 0

    moving = _engine([FLEX, moving_talent])
    _raise(moving, "N")
    _me(moving).position = Position(x=7, y=6)
    moving.state.actors[AN].position = Position(x=7, y=3)
    moving._append_event("MOVEMENT_COMMITTED", "test:step", actor_id=ME, payload={})
    assert _face(_me(moving)) and _cover(moving) == 5  # "your movement does not end the Shield Face": it goes with the bearer


def test_the_face_ends_at_the_start_of_the_bearers_next_turn():
    engine = _engine([FLEX])
    _raise(engine, "N")
    engine._expire_for_checkpoint("START_OF_TURN", ME)
    assert _face(_me(engine)) is None and _cover(engine) == 0


def test_raising_a_new_face_replaces_the_old_one():
    engine = _engine([FLEX])
    _raise(engine, "N")
    _raise(engine, "E")
    assert len([c for c in _me(engine).conditions.values() if c.condition_id == "condition:" + FACE]) == 1
    assert _face(_me(engine)).data["edge"] == "E"


# ---------------------------------------------------------------------------------------------------- the other ways to use it
def test_martial_focus_makes_it_a_bonus_action_and_moving_rampart_makes_that_free():
    engine = _engine([FLEX])
    assert f"{NAME} (Martial Focus, Bonus Action)" in _legal(engine)
    focus = _me(engine).resources[FOCUS]
    _use(engine, f"{NAME} (Martial Focus, Bonus Action)", target=None)
    assert _face(_me(engine)) and _me(engine).resources[FOCUS] == focus - 1
    assert not _me(engine).bonus_action_available and _me(engine).action_available

    free = _engine([FLEX, RAMPART])
    assert f"{NAME} (Bonus Action)" in _legal(free) and f"{NAME} (Martial Focus, Bonus Action)" not in _legal(free)
    focus = _me(free).resources[FOCUS]
    _use(free, f"{NAME} (Bonus Action)", target=None)
    assert _face(_me(free)) and _me(free).resources[FOCUS] == focus


def test_moving_rampart_turns_the_face_once_a_turn_for_free():
    engine = _engine([FLEX, RAMPART])
    assert TURN not in _legal(engine)  # nothing to turn
    _raise(engine, "N")
    assert TURN in _legal(engine)
    action_before = _me(engine).action_available
    _use(engine, TURN, target=None)
    assert _face(_me(engine)).data["edge"] != "N" and _me(engine).action_available == action_before
    assert TURN not in _legal(engine)  # once during your turn


def test_the_reaction_turns_the_face_before_an_attack_roll_that_it_would_not_stop():
    """"As a Reaction, change the selected edge of your space": before the attack roll, the Face on the wrong edge is turned toward
    the attacker (the AI's own choice), and the roll meets Three-Quarters Cover."""
    from combat.gate2_runtime_models import ActionIntent

    engine = _engine([FLEX], foe=(6, 3))
    _raise(engine, "S")
    foe, me = engine.state.actors[AN], _me(engine)
    assert _cover(engine) == 0
    ext.run_strict("before_attack", engine, foe, me, ActionIntent(intent_id="i", decision_id="d", candidate_id="c", state_version=0,
                                                                  actor_id=AN, target_ids=(ME,)), {"attack_index": 1})
    assert _face(me).data["edge"] == "N" and not me.reaction_available
    assert _cover(engine) == 5


def test_no_reaction_when_none_is_left_or_the_face_already_stops_the_attack():
    engine = _engine([FLEX], foe=(6, 3))
    foe, me = engine.state.actors[AN], _me(engine)
    intent = ActionIntent(intent_id="i", decision_id="d", candidate_id="c", state_version=0, actor_id=AN, target_ids=(ME,))
    _raise(engine, "N")
    ext.run_strict("before_attack", engine, foe, me, intent, {"attack_index": 1})
    assert me.reaction_available and _face(me).data["edge"] == "N"  # it already stops the attack: nothing spent
    _raise(engine, "S")
    me.reaction_available = False
    ext.run_strict("before_attack", engine, foe, me, intent, {"attack_index": 1})
    assert _face(me).data["edge"] == "S"  # no Reaction: no turning


def test_the_cover_is_a_real_ac_bonus_on_a_real_attack_roll(monkeypatch):
    engine = _engine([FLEX], foe=(6, 3))
    _raise(engine, "N")
    foe, me = engine.state.actors[AN], _me(engine)
    engine.state.current_actor_id = AN
    spec = {"attack_bonus": 0, "reach_ft": 5, "range_ft": None}
    from tests.test_lock_choices import install, intent

    install(monkeypatch, "d20_result", lambda *a: {"source_id": "test:roll", "operation": "replace", "natural_result": 10})
    foe.position = Position(x=6, y=5)
    engine._resolve_attack_spec(foe, me, spec, intent(engine), source_definition_id="test:strike")
    rolled = next(ev for ev in reversed(engine.events) if ev.event_type == "ATTACK_ROLLED").payload
    assert rolled["cover_bonus"] == 5 and rolled["target_ac"] == me.armor_class + 5


def test_a_character_without_the_talent_meets_no_face_and_the_hook_is_inert():
    engine = _engine([])
    assert NAME not in _legal(engine)
    assert _cover(engine) == 0
    assert ext.run_strict("directional_cover", engine, engine.state.actors[AN], _me(engine),
                          {"start": [6, 3], "end": [6, 6], "ranged": False, "crossed_edges": []}) == []


# ---------------------------------------------------------------------------------------------------- Seal the Breach
SEAL = "TAL_SHIELD_SEAL_THE_BREACH"
COURT = "TAL_SHIELD_COURT_OF_TEN_THOUSAND_TURNING_FACES"
SEAL_NAME = "SEAL THE BREACH"


def _seal_engine(*, foe=(6, 3), ally=None, extra=()):
    engine = _engine([FLEX, PROJECTED, SEAL, *extra], foe=foe, ally=ally)
    return engine


def _barrier(actor):
    return next((c for c in actor.conditions.values() if c.condition_id == "condition:" + FACE and c.data["kind"] == "barrier"), None)


def _attack_names(engine, actor_id):
    return {c.display_name for c in engine.legal_candidates() if AN in (c.target_ids or ()) and c.kind.value == "ACTION"}


def test_seal_the_breach_raises_a_barrier_that_lasts_as_long_as_the_concentration():
    """"Bonus Action, Martial Focus, Concentration up to 1 minute ... a temporary Barrier attached to you": its old typing was a
    stray zone; nothing stood between the bearer and the attack."""
    engine = _seal_engine()
    focus = _me(engine).resources[FOCUS]
    _use(engine, SEAL_NAME, target=None)
    barrier = _barrier(_me(engine))
    assert barrier is not None and barrier.data["edge"] == "N" and barrier.expires_on == "CONCENTRATION_END"
    assert _me(engine).resources[FOCUS] == focus - 1 and _me(engine).concentration is not None
    assert _cover(engine) == 5
    engine._end_concentration(_me(engine), "TEST")
    assert _barrier(_me(engine)) is None and _cover(engine) == 0


def test_a_barrier_is_total_cover_a_hostile_cannot_attack_across_it():
    engine = _seal_engine(foe=(6, 3))
    foe = engine.state.actors[AN]
    engine.state.current_actor_id = AN
    foe.action_available = True
    before = [c for c in engine.legal_candidates() if ME in (c.target_ids or ()) and c.kind.value in ("ACTION", "BONUS_ACTION")]
    assert before, "the foe can attack the bearer before the Barrier"
    engine.state.current_actor_id = ME
    _use(engine, SEAL_NAME, target=None)
    engine.state.current_actor_id = AN
    foe.action_available = True
    after = [c for c in engine.legal_candidates() if ME in (c.target_ids or ()) and c.kind.value in ("ACTION", "BONUS_ACTION")]
    assert not after, [c.display_name for c in after]  # nothing that crosses the Barrier is offered
    foe.position = Position(x=6, y=9)  # from the far side of the bearer: no Barrier in the way
    foe.action_available = True
    assert [c for c in engine.legal_candidates() if ME in (c.target_ids or ()) and c.kind.value in ("ACTION", "BONUS_ACTION")]


def test_a_barrier_ends_when_the_bearer_is_incapacitated_or_after_a_minute():
    engine = _seal_engine()
    _use(engine, SEAL_NAME, target=None)
    engine._apply_condition(_me(engine), "condition:typed.incapacitated", "test", AN, expires_on="UNTIL_REMOVED")
    assert _cover(engine) == 0  # "Seal the Breach ends if ... you have the Incapacitated condition"
    engine._remove_condition(_me(engine), "condition:typed.incapacitated", "test")
    engine._expire_for_checkpoint("START_OF_TURN", ME)
    engine.state.round_number += 11  # "up to 1 minute"
    engine._append_event("TURN_STARTED", "test:turn", actor_id=ME, payload={})
    assert _barrier(_me(engine)) is None


def test_the_barrier_goes_with_its_bearer_and_can_be_turned_once_a_turn():
    engine = _seal_engine()
    _use(engine, SEAL_NAME, target=None)
    _me(engine).position = Position(x=7, y=6)
    engine.state.actors[AN].position = Position(x=7, y=3)
    engine._append_event("MOVEMENT_COMMITTED", "test:step", actor_id=ME, payload={})
    assert _barrier(_me(engine)) and _cover(engine) == 5  # "moves with you"
    _ready(engine)
    name = f"Turn {SEAL_NAME} face (free, once a turn)"
    assert name in _legal(engine)
    _use(engine, name, target=None)
    assert _barrier(_me(engine)).data["edge"] != "N" and name not in _legal(engine)


def test_a_barrier_stops_lines_that_cross_it_and_none_that_start_behind_it():
    """"It does not automatically block ... effects originating behind the face": an ally behind the bearer shooting out is not
    covered against; a line into the far side, past the bearer, still has to cross the Barrier."""
    engine = _seal_engine(foe=(6, 3), ally=(6, 8))
    _use(engine, SEAL_NAME, target=None)
    assert _cover(engine, target=AN, attacker=ALLY) == 0  # outbound
    assert _cover(engine, target=ALLY) == 5  # inbound, through the Barrier, to a creature well behind it


# ---------------------------------------------------------------------------------------------------- the Court
def _court(engine, owner_at=None):
    """A standing Court, as the Court's own action leaves it (a zone the bearer owns)."""
    from combat.gate2_runtime_models import ZoneState

    me = _me(engine)
    engine.state.zones["zone:court"] = ZoneState(zone_id="zone:court", source_definition_id=f"action:typed.x.{COURT}", owner_id=ME, center=me.position,
                                                 radius_cells=6, affected_cells=(), concentration_link=False, duration_rounds=10, created_round=1)


def test_the_court_raises_up_to_three_projected_faces_on_edges_inside_it():
    engine = _engine([FLEX, PROJECTED], ally=(7, 6), foe=(8, 3))
    _court(engine)
    _use(engine, NAME, target=None)
    faces = [c for c in _me(engine).conditions.values() if c.condition_id == "condition:" + FACE]
    assert 1 <= len(faces) <= 3 and all(c.data["kind"] == "court" for c in faces)
    assert {c.data["cells"][0][0] for c in faces} <= {6, 7}  # squares of the bearer and its ally
    assert _cover(engine, target=ALLY) == 5  # the ally's own square is faced toward the foe
    assert _cover(engine, target=ME) == 5


def test_court_faces_stand_where_they_were_raised_and_end_at_the_next_turn():
    engine = _engine([FLEX, PROJECTED], ally=(7, 6), foe=(7, 3))
    _court(engine)
    _use(engine, NAME, target=None)
    engine.state.actors[ALLY].position = Position(x=7, y=8)  # the ally leaves: its Face does not follow
    assert _cover(engine, target=ALLY) == 0
    engine._expire_for_checkpoint("START_OF_TURN", ME)
    assert not [c for c in _me(engine).conditions.values() if c.condition_id == "condition:" + FACE]


def test_court_allies_have_half_cover_against_ranged_attacks_from_outside_the_court():
    engine = _engine([FLEX], ally=(7, 6), foe=(6, 3))
    _court(engine)
    foe = engine.state.actors[AN]
    foe.position = Position(x=6, y=13)  # 35 feet from the bearer: outside the Court
    assert engine._cover_bonus_actor_to_actor(foe, engine.state.actors[ALLY]) == 2
    foe.position = Position(x=6, y=9)  # inside
    assert engine._cover_bonus_actor_to_actor(foe, engine.state.actors[ALLY]) == 0
    engine.state.zones["zone:court"].active = False  # no Court, no cover
    foe.position = Position(x=6, y=13)
    assert engine._cover_bonus_actor_to_actor(foe, engine.state.actors[ALLY]) == 0
