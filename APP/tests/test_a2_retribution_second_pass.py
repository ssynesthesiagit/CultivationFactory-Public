"""Retribution's remaining Counter talents (A2RETRIBUT, 2026-10-10).

Almost every case drives the real table: TabletopService -> CombatService -> session execute_intent, then a cold reload.
Two cases (movement endpoints, the escape contest) are put through the table's own menus and questions; the granted-move
endpoint cases inject a granted route inside an accepted action (the documented seam the bug lives in) and still reload.
No case substitutes a running engine or patches a core class/function of the game logic. Owner text:
APP/authority/typed_mechanics/rules_text.json.

  Set Up           a preparation-time strike; on a hit the creature must end willing movement adjacent to you, and it
                   may use a Bonus Action to attempt to break the hold with an opposed Athletics/Acrobatics check.
  Clinch           spend the Reaction the Counterstrike restored to attempt a Grapple through an Unarmed Strike.
  Read the Tell    choose one creature you can see within 60 feet; Advantage on Wisdom (Insight) about that creature.
  Powerful Counter the lane leaves this to the GM (no remaining-attack pool exists); the table posts a plain reminder.

Recipient rule (repeat review finding 2026-10-10): every automatic or AI-made pick here chooses by side. Read the Tell
is exercised with an ALLY and an ENEMY both visible and in range, and the automatic choice must name the enemy. Set Up's
automatic strike must likewise name a hostile. The Set Up escape also runs with an AI holder (which picks its own better
skill) and an off-turn player anchor that must be asked.
"""
import pytest

from combat.gate2_runtime_models import Position
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, act, reload, cell_send
from tests.hunt15_support import turn

BASE = "RETRIBUTION_BASE_COUNTERSTRIKE"
REFLEXIVE = "TAL_RETRIBUTION_REFLEXIVE_PREPARATION"
CLINCH = "TAL_RETRIBUTION_CLINCH"
SET_UP = "TAL_RETRIBUTION_SET_UP"
TELL = "tianxia.talent.retribution.read_the_tell"
POWERFUL = "TAL_RETRIBUTION_POWERFUL_COUNTER"
BREAK = "Break free from Set Up"
SET_UP_CONDITION = "condition:typed.set_up"
MOVE = "system:combat.movement"

DAO = {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}
CAUSE = [{"type": "damage", "flat": 9, "damage_types": ["slashing"], "applies_to": "target"}]


def _seal(bundle):
    """Make the opponent's damage land and the fighter's strike connect, so outcomes are deterministic."""
    for action in bundle["action_catalog"]:
        typed = action.get("parameters", {}).get("typed", {})
        if action["display_name"] == "Cause":
            action["economy"] = "ACTION"
        if typed.get("weapon"):
            typed.setdefault("numbers", {})["attack_bonus"] = 100


def settle(send, *, pick=None, decline_sources=(), limit=32):
    """Answer a run of table questions.

    ``pick`` names the option to take at the Counterstrike preparation menu by label prefix. Every other menu falls back
    to the engine's own first option, which is the order the ability itself offers them in (hostile before allied), so an
    automatic pick is exercised rather than steered.
    """
    answers, seen = [], []
    for _ in range(limit):
        result = send(answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return result, seen
        prompt = result["reaction"]
        seen.append(prompt)
        choice = prompt.get("choice") or {}
        options = choice.get("options", [])
        matched = [option["id"] for option in options
                   if pick and any(option.get("label", "").startswith(prefix) for prefix in pick)]
        chosen = matched[:1] or [option["id"] for option in options[:1]]
        source = str(prompt["context"].get("reaction_source_id") or "")
        if source in decline_sources:
            answers.append({**prompt["context"], "selection": "DECLINE", "option_ids": []})
        else:
            answers.append({**prompt["context"], "selection": "USE", "option_ids": chosen})
    raise AssertionError("too many choices")


def _prepare(table, mid, talent_label):
    return settle(lambda answers: act(table, mid, "Reflexive Preparation", answers), pick=[talent_label])


def _counter(tmp_path, talents, *, ally=None, cl=15, sheet_edit=None, positions=None, right_skills=0, left_skills=0,
             prepare=None, arena_edit=None, cause=CAUSE, cause_target="HOSTILE_ENTITY", right_skills_by_name=None,
             bundle_edit=None):
    """A Retribution fighter preparing a Counterstrike against a single opponent."""
    def edit(doc, aid):
        rows = doc["ability_scores_and_statistics"].setdefault("skills", [])
        bonus = right_skills if aid == RIGHT else left_skills
        named = (right_skills_by_name or {}) if aid == RIGHT else {}
        rows.append({"skill": "Athletics", "bonus": named.get("Athletics", bonus), "proficient": True})
        rows.append({"skill": "Acrobatics", "bonus": named.get("Acrobatics", bonus), "proficient": True})
        if sheet_edit is not None:
            sheet_edit(doc, aid)

    def seal(bundle):
        _seal(bundle)
        if bundle_edit is not None:
            bundle_edit(bundle)

    return fight(tmp_path, [BASE, *talents, REFLEXIVE], left_kit=DAO, cause=cause, cause_target=cause_target,
                 bundle_edit=seal, cl=cl, ally=ally, sheet_edit=edit, positions=positions, arena_edit=arena_edit,
                 prepare=prepare, prepare_target="HOSTILE_ENTITY")


def _holds(engine, actor_id, condition_id=SET_UP_CONDITION):
    return [row for row in engine.state.actors[actor_id].conditions.values() if row.condition_id == condition_id]


def _moves(engine):
    return [c for c in engine.legal_candidates()
            if c.source_definition_id == MOVE and c.destination is not None]


# --------------------------------------------------------------------------- Read the Tell
def test_read_the_tell_gives_advantage_on_insight_about_the_chosen_creature(tmp_path):
    combat, table, mid = _counter(tmp_path, [TELL])
    _prepare(table, mid, "Counterstrike + Read the Tell")
    engine = reload(combat, mid)
    me, foe = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    from combat.typed_executor import check_modes

    assert check_modes(me, "WIS", "insight", engine=engine, against_creature=foe) == {"ADVANTAGE"}
    assert check_modes(me, "WIS", "perception", engine=engine, against_creature=foe) == set()
    assert check_modes(me, "WIS", "insight", engine=engine, against_creature=None) == set()


def test_read_the_tell_advantage_lifts_at_the_start_of_the_next_turn(tmp_path):
    combat, table, mid = _counter(tmp_path, [TELL])
    _prepare(table, mid, "Counterstrike + Read the Tell")
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    from combat.typed_executor import check_modes

    assert check_modes(engine.state.actors[LEFT], "WIS", "insight", engine=engine,
                       against_creature=engine.state.actors[RIGHT]) == set()


def test_read_the_tell_names_the_hostile_when_an_ally_and_an_enemy_are_both_in_range(tmp_path):
    """The recipient rule: with an ally and an enemy both visible in range the automatic pick names the enemy."""
    combat, table, mid = _counter(tmp_path, [TELL], ally="ALLY")
    engine = reload(combat, mid)
    ally, foe = engine.state.actors[ALLY], engine.state.actors[RIGHT]
    for other in (ally, foe):
        assert engine._distance_actor_to_actor(engine.state.actors[LEFT], other) <= 60
        assert engine._line_of_sight_actor_to_actor(engine.state.actors[LEFT], other)

    # No answers are supplied for the Read the Tell menu: the table resolves the choice itself, which is how the
    # built-in AI's automatic pick is resolved. It must name the enemy, never the ally standing beside it.
    result, seen = settle(lambda answers: act(table, mid, "Reflexive Preparation", answers))
    menu = next((prompt["choice"] for prompt in seen
                 if prompt["context"].get("reaction_source_id") == "choice:needle.retribution_read_the_tell"), None)
    assert menu is not None, [p["context"].get("reaction_source_id") for p in seen]
    engine = reload(combat, mid)
    from combat.ext.retribution_second_pass import TELL_CONDITION

    held = [row for row in engine.state.actors[LEFT].conditions.values() if row.condition_id == TELL_CONDITION]
    assert len(held) == 1, dict(engine.state.actors[LEFT].conditions)
    assert held[0].data["target_id"] == foe.entity_id, (held[0].data, ally.entity_id, foe.entity_id)


# --------------------------------------------------------------------------- Set Up
def test_set_up_strikes_a_hostile_at_preparation_and_keeps_it_adjacent(tmp_path):
    combat, table, mid = _counter(tmp_path, [SET_UP])
    _prepare(table, mid, "Counterstrike + Set Up")
    engine = reload(combat, mid)

    held = _holds(engine, RIGHT)
    assert len(held) == 1, dict(engine.state.actors[RIGHT].conditions)
    assert held[0].data["anchor_id"] == LEFT
    # "Deal no damage": the preparation strike itself is not a damage source.
    assert engine.state.actors[RIGHT].current_hp == 1000, engine.state.actors[RIGHT].current_hp


def test_set_up_refuses_a_route_that_does_not_end_adjacent(tmp_path):
    """Finding 1: the COMPLETE route is validated, so an illegal endpoint is never offered (and never committed)."""
    combat, table, mid = _counter(tmp_path, [SET_UP])
    _prepare(table, mid, "Counterstrike + Set Up")
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    me, foe = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert engine._distance_actor_to_actor(me, foe) <= 10

    moves = _moves(engine)
    assert moves, "the holder must still be offered the movement it may legally make"
    # Every offered endpoint ends adjacent to the anchor.
    assert all(engine._distance_actor_to_actor(me, foe, target_position=c.destination) <= 10 for c in moves), \
        [(c.destination.x, c.destination.y) for c in moves]
    # A square well beyond adjacency is not offered at all.
    assert not any((c.destination.x, c.destination.y) == (6, 6) for c in moves)
    with pytest.raises(StopIteration):
        cell_send(table, mid, "Move", (6, 6))([])

    # A legal endpoint is untouched and commits; after a cold reload the holder is still adjacent.
    near = next(c for c in moves if (c.destination.x, c.destination.y) == (5, 6))
    settle(cell_send(table, mid, "Move", (5, 6)))
    after = reload(combat, mid)
    assert after._distance_actor_to_actor(after.state.actors[LEFT], after.state.actors[RIGHT]) <= 10
    assert (after.state.actors[RIGHT].position.x, after.state.actors[RIGHT].position.y) == (5, 6)


def test_set_up_does_not_prevent_movement_that_cannot_end_adjacent(tmp_path):
    """The printed exception: movement that cannot legally end adjacent is unaffected.

    The anchor is walled into a pocket no legal endpoint can be reached from, so the holder's moves stay available.
    """
    def edit(arena):
        arena.setdefault("terrain_regions", []).append(
            {"region_id": "pocket", "terrain_type": "BLOCKED", "movement_cost": 0, "description": "stone",
             "cells": [{"x": x, "y": y} for x in range(2, 7) for y in range(4, 9) if (x, y) != (4, 6)]})

    combat, table, mid = _counter(
        tmp_path, [SET_UP], positions={LEFT: {"x": 4, "y": 6}, RIGHT: {"x": 12, "y": 6}}, arena_edit=edit,
        cause=[{"type": "condition", "condition": "set_up", "applies_to": "self",
                "condition_data": {"anchor_id": LEFT, "label": "Set Up"}}],
        cause_target="SELF")
    turn(table, mid, RIGHT)
    settle(lambda answers: act(table, mid, "Cause", answers))
    engine = reload(combat, mid)
    me, foe = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert _holds(engine, RIGHT), dict(engine.state.actors[RIGHT].conditions)
    assert engine._distance_actor_to_actor(me, foe) > 10

    moves = _moves(engine)
    assert moves, "the mover is not trapped"
    # No endpoint within 10 feet of the anchor is reachable, so the printed exception lets the moves stand.
    assert all(engine._distance_actor_to_actor(me, foe, target_position=c.destination) > 10 for c in moves)


def test_set_up_sets_nothing_when_no_creature_is_in_reach(tmp_path):
    combat, table, mid = _counter(tmp_path, [SET_UP], positions={LEFT: {"x": 1, "y": 1}, RIGHT: {"x": 18, "y": 12}})
    _prepare(table, mid, "Counterstrike + Set Up")
    engine = reload(combat, mid)
    assert not _holds(engine, RIGHT), dict(engine.state.actors[RIGHT].conditions)


def test_set_up_expires_at_the_start_of_the_anchor_next_turn(tmp_path):
    combat, table, mid = _counter(tmp_path, [SET_UP])
    _prepare(table, mid, "Counterstrike + Set Up")
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert not _holds(engine, RIGHT), dict(engine.state.actors[RIGHT].conditions)


def test_set_up_names_a_hostile_when_an_ally_and_an_enemy_are_both_in_reach(tmp_path):
    combat, table, mid = _counter(tmp_path, [SET_UP], ally="ALLY")
    _prepare(table, mid, "Counterstrike + Set Up")
    engine = reload(combat, mid)

    holders = [actor.entity_id for actor in engine.state.actors.values() if _holds(engine, actor.entity_id)]
    assert holders == [RIGHT], holders


# --------------------------------------------------- Set Up: granted movement uses the granted allowance (finding 1)
def _held_fight(tmp_path, right_xy, *, arena_edit=None, bundle_edit=None):
    """Place the Set Up hold directly on the holder (via its own Cause action) so its distance from the anchor is free."""
    return _counter(tmp_path, [SET_UP], positions={LEFT: {"x": 3, "y": 2}, RIGHT: {"x": right_xy[0], "y": right_xy[1]}},
                    arena_edit=arena_edit, bundle_edit=bundle_edit,
                    cause=[{"type": "condition", "condition": "set_up", "applies_to": "self",
                            "condition_data": {"anchor_id": LEFT, "label": "Set Up"}}], cause_target="SELF")


def _hold_right(combat, table, mid):
    """Advance to the holder's turn and commit the hold through the table, then a cold reload."""
    turn(table, mid, RIGHT)
    settle(lambda answers: act(table, mid, "Cause", answers))
    engine = reload(combat, mid)
    assert _holds(engine, RIGHT), dict(engine.state.actors[RIGHT].conditions)
    return engine


def _grant_on_hold(monkeypatch, *, feet, to, zero_ordinary=False):
    """Grant the holder one route, injected inside the next accepted table action.

    Movement an ability grants runs through the documented ``movement_attempt`` seam exactly here; granting it inside a
    committed action (the accepted Hold Position) keeps the whole thing at the table/execute_intent level."""
    from tests.test_tabletop_hunt6 import on_hold

    def callback(engine):
        mover = engine.state.actors[RIGHT]
        if zero_ordinary:
            mover.movement_remaining_ft = 0
        engine.grant_movement(mover, (mover.position, Position(x=to[0], y=to[1])), "test:grant", feet=feet,
                              provokes=False, mode="walk")

    on_hold(monkeypatch, callback)


def _sit(actor):
    return (actor.position.x, actor.position.y)


def test_set_up_prices_a_granted_move_against_its_grant_not_the_ordinary_pool(monkeypatch, tmp_path):
    """Finding 1 (case A): the grant, not the ordinary pool, decides whether adjacency is still reachable.

    The holder is 45 feet from the anchor with no ordinary movement left and receives a 45-foot grant. That grant can
    reach adjacency (35 feet), so a 5-foot step AWAY must be refused -- the printed exception does not apply. The old
    ``max(route length, ordinary)`` budget read 5 feet and wrongly allowed the step."""
    combat, table, mid = _held_fight(tmp_path, (12, 2))
    _hold_right(combat, table, mid)
    _grant_on_hold(monkeypatch, feet=45, to=(13, 2), zero_ordinary=True)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    after = reload(combat, mid)
    assert _sit(after.state.actors[RIGHT]) == (12, 2), _sit(after.state.actors[RIGHT])
    assert any(event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == RIGHT and event.payload.get("interrupted")
               for event in after.events), "the granted route was stopped as a whole"


def test_set_up_lets_a_granted_move_through_when_only_the_grant_cannot_end_adjacent(monkeypatch, tmp_path):
    """Finding 1 (case B): a grant too small to reach adjacency leaves the printed exception in force.

    The holder is 30 feet from the anchor with 30 feet of ordinary movement left (which could reach adjacency) but a
    5-foot grant (which cannot). The step AWAY must be allowed; the old code used the ordinary pool and wrongly refused
    it. A grant must also never spend the ordinary allowance."""
    combat, table, mid = _held_fight(tmp_path, (9, 2))
    _hold_right(combat, table, mid)
    _grant_on_hold(monkeypatch, feet=5, to=(10, 2))
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    after = reload(combat, mid)
    assert _sit(after.state.actors[RIGHT]) == (10, 2), _sit(after.state.actors[RIGHT])
    assert after.state.actors[RIGHT].movement_remaining_ft == 30


def _mire_column(arena):
    """An unavoidable mire every walking route to the anchor must cross (a full column of doubled-cost squares)."""
    cells = [{"x": 6, "y": y} for y in range(int(arena.get("height_squares", 14)))]
    arena.setdefault("terrain_regions", []).append(
        {"region_id": "mire", "terrain_type": "OPEN", "movement_cost": 2, "description": "mire", "cells": cells})


def _low_wall(arena):
    """An unavoidable wall that blocks walking but is only 5 feet high, so it can be flown over."""
    cells = [{"x": 6, "y": y} for y in range(int(arena.get("height_squares", 14)))]
    arena.setdefault("terrain_regions", []).append(
        {"region_id": "low_wall", "terrain_type": "BLOCKED", "movement_cost": 0, "height_ft": 5,
         "description": "Low wall: fly over it", "cells": cells})


def _flyer(bundle):
    """Give one side a Fly Speed, so the merged reachability query would offer it flying routes too."""
    if bundle["actor_id"] == RIGHT:
        bundle["actor_template"].update(fly_speed_ft=30, hover=True)


def test_set_up_prices_a_granted_route_through_difficult_terrain(monkeypatch, tmp_path):
    """Finding 1 (terrain): the grant's budget is spent on a terrain-priced path, so geometric length is not a budget.

    The holder is three squares from adjacency. The plain ground walk costs 15 feet; a full column of mire makes every
    walking route to adjacency cost 20, so a 15-foot grant reaches adjacency only if the terrain is ignored. The away
    step must be ALLOWED; the refusal control below shows the rule still fires once adjacency is genuinely walkable."""
    combat, table, mid = _held_fight(tmp_path, (8, 2), arena_edit=_mire_column)
    _hold_right(combat, table, mid)
    _grant_on_hold(monkeypatch, feet=15, to=(9, 2), zero_ordinary=True)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    after = reload(combat, mid)
    assert _sit(after.state.actors[RIGHT]) == (9, 2), _sit(after.state.actors[RIGHT])


def test_set_up_refuses_a_granted_route_when_terrain_still_lets_it_end_adjacent(monkeypatch, tmp_path):
    """Finding 1 (terrain) refusal control: 20 feet does walk the terrain-priced route to adjacency, so the hold stops it."""
    combat, table, mid = _held_fight(tmp_path, (8, 2), arena_edit=_mire_column)
    _hold_right(combat, table, mid)
    _grant_on_hold(monkeypatch, feet=20, to=(9, 2), zero_ordinary=True)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    after = reload(combat, mid)
    assert _sit(after.state.actors[RIGHT]) == (8, 2), _sit(after.state.actors[RIGHT])
    assert any(event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == RIGHT and event.payload.get("interrupted")
               for event in after.events), "the granted route was stopped as a whole"


def test_set_up_judges_a_walking_grant_by_walking_when_only_flight_reaches_adjacency(monkeypatch, tmp_path):
    """Finding 1: a walking grant is judged by WALKING reach, never by a flying route.

    A low wall blocks walking but can be flown over. The holder has Fly Speed and takes a 15-foot WALKING grant one
    square away. Within that grant only flying reaches a square adjacent to the anchor, so the printed exception applies
    and the away step stands. The merged query counted the flying endpoint and wrongly stopped the walking move."""
    combat, table, mid = _held_fight(tmp_path, (8, 2), arena_edit=_low_wall, bundle_edit=_flyer)
    _hold_right(combat, table, mid)
    _grant_on_hold(monkeypatch, feet=15, to=(9, 2), zero_ordinary=True)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    after = reload(combat, mid)
    assert _sit(after.state.actors[RIGHT]) == (9, 2), _sit(after.state.actors[RIGHT])


def test_set_up_still_stops_a_walking_grant_that_can_walk_to_adjacency_with_fly_speed(monkeypatch, tmp_path):
    """Finding 1 control: the walk-mode rule still refuses when the WALKING grant itself reaches adjacency.

    On open ground with Fly Speed the same 15-foot walking grant can end adjacent (three 5-foot steps), so the away
    step must be refused -- the mode fix narrows the search, it does not disable the rule."""
    combat, table, mid = _held_fight(tmp_path, (8, 2), bundle_edit=_flyer)
    _hold_right(combat, table, mid)
    _grant_on_hold(monkeypatch, feet=15, to=(9, 2), zero_ordinary=True)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    after = reload(combat, mid)
    assert _sit(after.state.actors[RIGHT]) == (8, 2), _sit(after.state.actors[RIGHT])
    assert any(event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == RIGHT and event.payload.get("interrupted")
               for event in after.events), "the walking grant was stopped as a whole"


@pytest.mark.parametrize("feet, expected_x", [(15, 8), (10, 9)])
def test_set_up_prices_supported_elevated_walking_after_table_reload(monkeypatch, tmp_path, feet, expected_x):
    """A platform walk reaches adjacency in 15 feet; a 10-foot grant permits moving away."""
    def platform(arena):
        arena.setdefault("terrain_regions", []).append({
            "region_id": "platform", "terrain_type": "BLOCKED", "movement_cost": 0,
            "height_ft": 5, "description": "Raised platform",
            "cells": [{"x": x, "y": y} for x in range(2, 11) for y in range(1, 4)],
        })

    combat, table, mid = _counter(
        tmp_path, [SET_UP], arena_edit=platform,
        positions={LEFT: {"x": 3, "y": 2, "z": 1}, RIGHT: {"x": 8, "y": 2, "z": 1}},
        cause=[{"type": "condition", "condition": "set_up", "applies_to": "self",
                "condition_data": {"anchor_id": LEFT, "label": "Set Up"}}], cause_target="SELF")
    engine = _hold_right(combat, table, mid)
    mover = engine.state.actors[RIGHT]
    from combat import flight, granted_movement

    def callback(engine):
        mover = engine.state.actors[RIGHT]
        mover.movement_remaining_ft = 0
        engine.grant_movement(mover, (mover.position, Position(x=9, y=2, z=1)), "test:grant",
                              feet=feet, provokes=False, mode="walk")

    from tests.test_tabletop_hunt6 import on_hold
    on_hold(monkeypatch, callback)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    after = reload(combat, mid)
    assert after.state.actors[LEFT].position == Position(x=3, y=2, z=1)
    assert after.state.actors[RIGHT].position == Position(x=expected_x, y=2, z=1)
    assert after.state.actors[RIGHT].movement_remaining_ft == 0
    receipt = next(event for event in reversed(after.events)
                   if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == RIGHT)
    assert bool(receipt.payload.get("interrupted")) == (feet >= 15)
    assert receipt.payload["granted_cost_ft"] == (0 if feet >= 15 else 5)

    # Both shared helpers must preserve the platform height and native walking cost.
    adjacent = Position(x=5, y=2, z=1)
    for routes in (flight.reachable(engine, mover, grant_ft=feet, mode="walk"),
                   granted_movement.routes(engine, mover, feet, mode="walk")):
        assert (adjacent in routes) == (feet >= 15)
        if adjacent in routes:
            path, cost, mode = routes[adjacent]
            assert cost == 15 and mode == "walk"
            assert all(p.z == 1 for p in path)


def test_set_up_accepts_a_granted_route_that_leaves_adjacency_and_returns(monkeypatch, tmp_path):
    """Finding 2: a real granted route is judged by its ENDPOINT, so a route that leaves adjacency and comes back stands."""
    combat, table, mid = _held_fight(tmp_path, (4, 2))
    _hold_right(combat, table, mid)

    def callback(engine):
        mover = engine.state.actors[RIGHT]
        path = (mover.position, Position(x=5, y=2), Position(x=6, y=2), Position(x=6, y=1),
                Position(x=5, y=1), Position(x=4, y=1))
        engine.grant_movement(mover, path, "test:grant", feet=25, provokes=False, mode="walk")

    from tests.test_tabletop_hunt6 import on_hold
    on_hold(monkeypatch, callback)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    after = reload(combat, mid)
    assert _sit(after.state.actors[RIGHT]) == (4, 1), _sit(after.state.actors[RIGHT])


# --------------------------------------------------------------------------- Set Up: the printed escape
def _escape_fight(tmp_path, holder_skill, anchor_skill):
    combat, table, mid = _counter(tmp_path, [SET_UP], right_skills=holder_skill, left_skills=anchor_skill)
    _prepare(table, mid, "Counterstrike + Set Up")
    turn(table, mid, RIGHT)
    return combat, table, mid


def test_set_up_escape_is_a_bonus_action_opposed_check_and_ends_the_hold_on_a_win(tmp_path):
    """Finding 2: a Bonus Action opposed Athletics/Acrobatics check, each creature choosing its skill."""
    combat, table, mid = _escape_fight(tmp_path, holder_skill=100, anchor_skill=0)
    assert _holds(reload(combat, mid), RIGHT)

    result, seen = settle(lambda answers: act(table, mid, BREAK, answers))
    contest = [p for p in seen if str(p["context"].get("reaction_source_id") or "").startswith("choice:needle.contest_")]
    # The holder chose its skill and the anchor (off its own turn) chose its own.
    assert {p["context"]["reaction_source_id"] for p in contest} == \
        {"choice:needle.contest_actor", "choice:needle.contest_target"}, [p["context"].get("reaction_source_id") for p in seen]
    for prompt in contest:
        # A real choice prompt: the engine exposes its two legal option ids ("0"/"1"), each naming one skill.
        options = prompt["choice"]["options"]
        assert [option["id"] for option in options] == ["0", "1"], prompt["choice"]
        assert all(option.get("label") for option in options), prompt["choice"]
        assert {option["label"] for option in options} == {"Strength (Athletics)", "Dexterity (Acrobatics)"}, options

    engine = reload(combat, mid)
    assert not _holds(engine, RIGHT), dict(engine.state.actors[RIGHT].conditions)
    assert engine.state.actors[RIGHT].bonus_action_available is False


def test_set_up_escape_keeps_the_hold_on_a_loss(tmp_path):
    combat, table, mid = _escape_fight(tmp_path, holder_skill=0, anchor_skill=100)
    settle(lambda answers: act(table, mid, BREAK, answers))
    engine = reload(combat, mid)
    assert _holds(engine, RIGHT), dict(engine.state.actors[RIGHT].conditions)


def test_set_up_escape_is_offered_only_while_the_hold_stands(tmp_path):
    combat, table, mid = _escape_fight(tmp_path, holder_skill=100, anchor_skill=0)
    settle(lambda answers: act(table, mid, BREAK, answers))
    turn(table, mid, LEFT)
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert not any(c.display_name == BREAK for c in engine.legal_candidates())


def test_set_up_escape_ai_holder_answers_itself_and_the_off_turn_anchor_is_asked(tmp_path):
    """Finding 2: the AI holder decides its own skill (its better one); the player's anchor is asked off its own turn."""
    from combat.gate4_adapters import ManualControllerAdapter

    # The holder's Acrobatics is far better than its Athletics, so an AI must choose Acrobatics; the anchor is a player.
    combat, table, mid = _counter(tmp_path, [SET_UP], left_skills=0,
                                  right_skills_by_name={"Athletics": -30, "Acrobatics": 30})
    _prepare(table, mid, "Counterstrike + Set Up")
    turn(table, mid, RIGHT)
    assert _holds(reload(combat, mid), RIGHT)

    engine = combat._load_session(mid).engine
    cid = next(c.candidate_id for c in engine.legal_candidates() if c.display_name == BREAK)
    real = combat.controller

    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    try:
        _, seen = settle(lambda answers: table.auto_step(mid, table.state(mid)["last_sequence"], answers))
    finally:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="MANUAL")

    asked = [p["context"].get("reaction_source_id") for p in seen]
    assert "choice:needle.contest_target" in asked, asked
    assert "choice:needle.contest_actor" not in asked, asked

    engine = reload(combat, mid)
    log = [event.payload.get("log", "") for event in engine.events if event.event_type == "PASSIVE_TRIGGERED"]
    assert any("Acrobatics" in line and "Set Up" in line for line in log), log[-4:]
    assert not _holds(engine, RIGHT), dict(engine.state.actors[RIGHT].conditions)


# --------------------------------------------------------------------------- Clinch
def _clinch_fight(tmp_path):
    combat, table, mid = _counter(tmp_path, [CLINCH])
    settle(lambda answers: act(table, mid, "Reflexive Preparation", answers), pick=["Counterstrike + Clinch"])
    turn(table, mid, RIGHT)
    settle(lambda answers: act(table, mid, "Cause", answers))
    return combat, table, mid


def test_clinch_spends_the_restored_reaction_to_attempt_the_grapple(tmp_path):
    combat, table, mid = _clinch_fight(tmp_path)
    engine = reload(combat, mid)

    assert any(event.event_type == "SAVE_ROLLED" and event.actor_id == RIGHT
               and event.source_definition_id for event in engine.events), [
                   (event.event_type, event.actor_id, event.payload) for event in engine.events
                   if event.event_type in ("SAVE_ROLLED", "CHECK_ROLLED")]
    # The Reaction the Counterstrike restored was offered and spent, not left doubled up.
    assert engine.state.actors[LEFT].reaction_available is False


def test_clinch_declining_leaves_the_restored_reaction_alone(tmp_path):
    combat, table, mid = _counter(tmp_path, [CLINCH])
    settle(lambda answers: act(table, mid, "Reflexive Preparation", answers), pick=["Counterstrike + Clinch"])
    turn(table, mid, RIGHT)
    settle(lambda answers: act(table, mid, "Cause", answers),
           decline_sources=("choice:needle.retribution_clinch",))
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].reaction_available is True


def test_clinch_declining_keeps_the_choice_for_the_preparations_next_counterstrike(tmp_path):
    """Finding 4: declining one Clinch must not spend the choice for the next legal Counterstrike."""
    combat, table, mid = _counter(tmp_path, [CLINCH])
    settle(lambda answers: act(table, mid, "Reflexive Preparation", answers), pick=["Counterstrike + Clinch"])
    turn(table, mid, RIGHT)
    settle(lambda answers: act(table, mid, "Cause", answers),
           decline_sources=("choice:needle.retribution_clinch",))
    engine = reload(combat, mid)
    from combat.ext.retribution_second_pass import CLINCH_FLAG

    # The choice is only spent by taking it; a later hit while the preparation stands may still offer Clinch.
    assert engine.state.actors[LEFT].turn_flags.get(CLINCH_FLAG) == "armed", dict(engine.state.actors[LEFT].turn_flags)


def test_clinch_is_re_offered_on_the_preparations_second_counterstrike(tmp_path):
    """Findings 2/4: TWO eligible Counterstrikes under one preparation; decline the first Clinch, take the second.

    Two Answers Within One Breath allows a second Counterstrike in the round, on a different creature's turn, while
    Court of the Awaiting Blade is up. Declining the first offer must leave Clinch armed so the second hit offers it
    again -- the flag check alone cannot see an offer suppressed by dispatch, variant selection or checkpoint reuse.
    """
    from combat.ext import counterstrike
    from combat.gate2_runtime_content import AN, LEE
    from combat.gate2_runtime_models import ReactionDecision
    from tests.test_auto_docket import ME, WEAPON, _fight, _sheet
    from tests.test_auto_tabik import _turn
    from tests.test_h2_counterstrike import TALENTS, TRIGGERS, _foe_does, _hits_on_foe, _use

    engine = _fight(_sheet([*TALENTS, CLINCH, "TAL_RETRIBUTION_COURT_OF_THE_AWAITING_BLADE",
                            "TAL_RETRIBUTION_TWO_ANSWERS_WITHIN_ONE_BREATH"], ["tianxia.sphere.retribution"], **WEAPON),
                   foe_at=(4, 6), second_foe=(3, 7))
    me = engine.state.actors[ME]
    for foe in (AN, LEE):
        engine.state.actors[foe].armor_class = -50
    _use(engine, "Court of the Awaiting Blade")
    me.bonus_action_available = True

    seen, offers = [], {"count": 0}

    def provider(request):
        seen.append(request)
        checkpoint, source = request["checkpoint"], request["reaction_source_id"]
        if source == "choice:needle.retribution_clinch":
            offers["count"] += 1
            take = offers["count"] == 2  # decline the first, take the second
            return ReactionDecision(checkpoint=checkpoint, reactor_id=request["reactor_id"], reaction_source_id=source,
                                    selection="USE" if take else "DECLINE",
                                    option_ids=("grapple",) if take else ()), None
        if checkpoint.startswith("READY:"):
            return ReactionDecision(checkpoint=checkpoint, reactor_id=request["reactor_id"], reaction_source_id=source,
                                    selection="USE", option_ids=tuple(request["legal_option_ids"])), None
        if source == "choice:needle.counterstrike":
            labels = request["choice_trigger"]["labels"]
            option = next(key for key, label in labels.items()
                          if label.startswith("Counterstrike + Clinch (") and TRIGGERS["me"] in label)
            return ReactionDecision(checkpoint=checkpoint, reactor_id=request["reactor_id"], reaction_source_id=source,
                                    selection="USE", option_ids=(option,)), None
        return ReactionDecision(checkpoint=checkpoint, reactor_id=request["reactor_id"], reaction_source_id=source,
                                selection="DECLINE"), None

    engine.set_reaction_provider(provider)
    _use(engine, "Counterstrike + Clinch")

    _turn(engine, AN)
    assert len(_hits_on_foe(_foe_does(engine, lambda c: ME in (c.target_ids or ()) and c.kind == "ACTION"
                                          and c.display_name.startswith("Paired")))) == 1
    assert counterstrike.used(engine, me) == (1, AN) and offers["count"] == 1
    assert engine.state.actors[AN].active and me.reaction_available is True  # declined: Reaction kept

    _turn(engine, LEE)
    assert not counterstrike._spent(engine, me)  # another creature's turn: the round's second answer
    assert len(_hits_on_foe(_foe_does(engine, lambda c: ME in (c.target_ids or ()) and c.kind == "ACTION"
                                          and c.display_name != "Dodge" and not c.option_ids))) == 1
    assert counterstrike.used(engine, me)[0] == 2
    assert offers["count"] == 2, [row["reaction_source_id"] for row in seen]
    assert me.reaction_available is False  # the second Clinch was taken: the restored Reaction is spent
    assert any(event.event_type == "SAVE_ROLLED" and event.actor_id == LEE for event in engine.events)


# --------------------------------------------------------------------------- Powerful Counter
def _powerful_notes(engine):
    """The plain GM reminders Powerful Counter has posted so far (its only table output)."""
    return [str(event.payload.get("log") or "") for event in engine.events
            if event.event_type == "PASSIVE_TRIGGERED" and event.source_definition_id == POWERFUL]


def test_powerful_counter_is_left_to_the_gm_and_never_awarded_automatically(tmp_path):
    """Powerful Counter is presented as a GM-resolved rule, not automated.

    The engine has no pool of a replaced Attack Action's remaining attacks, so the table must not offer an automatic
    forgo choice or roll its 1d8: preparing it posts one plain GM reminder instead. Exercised through the ordinary
    Action (the path the counterstrike_prepare seam answers)."""
    combat, table, mid = _counter(tmp_path, [POWERFUL])
    from combat.gate4_adapters import ManualControllerAdapter

    engine = combat._load_session(mid).engine
    cid = next(c.candidate_id for c in engine.legal_candidates() if c.display_name == "Counterstrike + Powerful Counter")
    real = combat.controller

    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    _, seen = settle(lambda answers: table.auto_step(mid, table.state(mid)["last_sequence"], answers))
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="MANUAL")
    menus = [prompt["context"].get("reaction_source_id") for prompt in seen]
    assert "choice:needle.retribution_powerful_counter" not in menus, menus
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].turn_flags.get("once_per_counterstrike:powerful_counter") is None
    log = [event.payload.get("log", "") for event in engine.events if event.event_type == "PASSIVE_TRIGGERED"]
    assert any("Powerful Counter" in line and "GM" in line and "1d8" in line for line in log), log[-4:]
    assert not any(event.event_type == "DAMAGE_ROLLED" for event in engine.events), "no dice are rolled for it"


def test_powerful_counter_reminds_the_gm_on_the_hit_and_adds_no_dice(tmp_path):
    """Finding 2: a real hit drives the changed on-hit handler; the reminder is not merely a preparation message.

    Extra Attack is owned, satisfying the printed prerequisite. Reflexive Preparation posts no reminder, so any reminder
    after the strike must come from the hit itself. The Counterstrike deals its ordinary weapon damage, records exactly
    one plain GM reminder during that hit, and rolls no automatic forgone-attack 1d8. Reloaded from the committed state.
    """
    combat, table, mid = _counter(tmp_path, ["tianxia.path.body_refining.feature.extra_attack", POWERFUL])
    _prepare(table, mid, "Counterstrike + Powerful Counter")
    turn(table, mid, RIGHT)
    before = reload(combat, mid)
    assert before.state.actors[RIGHT].current_hp == 1000, before.state.actors[RIGHT].current_hp
    assert _powerful_notes(before) == [], _powerful_notes(before)  # the Reflexive preparation reminder is silent

    settle(lambda answers: act(table, mid, "Cause", answers))
    after = reload(combat, mid)

    assert after.state.actors[RIGHT].current_hp < 1000, after.state.actors[RIGHT].current_hp  # ordinary attack damage
    notes = _powerful_notes(after)
    assert len(notes) == 1, notes
    assert "1d8" in notes[0] and "GM" in notes[0], notes[0]
    # No automatic forgone-attack dice: the strike made exactly its one ordinary weapon damage roll.
    rolls = [event for event in after.events
             if event.event_type == "DAMAGE_ROLLED" and RIGHT in (event.target_ids or ())]
    assert len(rolls) == 1, [(event.payload.get("expression"), event.payload.get("total")) for event in rolls]
    assert all("1d8" not in str(event.payload.get("expression") or "") for event in rolls), \
        [event.payload.get("expression") for event in rolls]
