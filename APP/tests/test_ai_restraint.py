"""The built-in AI leaves alone what would change nothing (fight audit 2026-09-29: it recast what was still up with every
spare Bonus Action) and walks a summon toward an enemy it cannot reach rather than end its turn where it stands -- but not
into a zone that would hurt it with nothing to strike at, and not into a Dash that opens no way; a player's menu keeps every
choice (combat/ext/ai_restraint.py, combat/gate4_context.py for_ai; combat/zones.py hazard_test)."""

from pathlib import Path

import pytest

from combat import summons, zones
from combat.ext import ai_restraint
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import CandidateKind, Position, ZoneState
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from tests.test_auto_docket import DARK, ME, _fight, _sheet
from tests.test_summons import OWNER, _engine as summon_engine, _turn_of, _use

ROOT = Path(__file__).resolve().parents[1]
STAY = {CandidateKind.END_TURN, CandidateKind.HOLD_POSITION}
CORPSE_SERVANT = ("TAL_DEATH_CORPSE_SERVANT", "corpse_servant")
PAINTED_FORMATION = ("tianxia.talent.ink.ten_thousand_illustrated_soldiers", "painted_formation")


class Candidate:
    def __init__(self, source):
        self.source_definition_id = source
        self.metadata = {}


def _darkness(engine):
    return next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Darkness")


def test_the_ai_does_not_cast_a_concentration_technique_it_still_holds():
    engine = _fight(_sheet([*DARK]))
    me, darkness = engine.state.actors[ME], _darkness(engine)
    assert ai_restraint.restraint(engine, me, Candidate(darkness.source_definition_id), darkness) is None
    engine._start_concentration(me, darkness.source_definition_id)
    assert ai_restraint.restraint(engine, me, Candidate(darkness.source_definition_id), darkness) is False


def test_the_ai_keeps_its_own_weapon_rather_than_grab_an_improvised_one():
    engine = _fight(_sheet([*DARK]))
    me = engine.state.actors[ME]
    grab = next((a for a in engine.action_catalog.values() if a.owner_id == ME and a.source_definition_id.endswith(".improvised.grab")), None)
    if grab is None:
        return
    has_weapon = ai_restraint._has_own_attack(engine, me)
    assert ai_restraint.restraint(engine, me, Candidate(grab.source_definition_id), grab) is (not has_weapon)


def test_a_disarmed_fighter_with_only_the_basic_unarmed_strike_still_grabs_an_improvised_weapon():
    """Hunt 53: every fighter now has the 1 + Strength Unarmed Strike (named like a natural weapon's attack). It does not
    arm a disarmed fighter -- an improvised weapon (1d4 + Strength, a free grab) hits harder -- while a natural weapon does."""
    from tests.test_auto_docket import SHEET as DOCKET_SHEET

    def disarmed_grab(features):
        sheet = {**DOCKET_SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []},
                 "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"], "path_feature_record_ids": features}}
        engine = _fight(sheet, foe_at=(4, 6))
        me = engine.state.actors[ME]
        engine._apply_condition(me, "condition:typed.disarmed", "src.disarm", AN, expires_on="UNTIL_REMOVED", data={})
        grab = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.source_definition_id.endswith(".improvised.grab"))
        return engine, me, grab

    engine, me, grab = disarmed_grab([])
    assert any(a.owner_id == ME and a.source_definition_id.endswith(".natural.unarmed_strike") for a in engine.action_catalog.values())
    assert ai_restraint.restraint(engine, me, Candidate(grab.source_definition_id), grab) is True
    engine, me, grab = disarmed_grab(["tianxia.path.body_refining.feature.iron_fist"])  # a natural weapon keeps it armed
    assert ai_restraint.restraint(engine, me, Candidate(grab.source_definition_id), grab) is False


def test_a_commanded_summon_walks_in_rather_than_dodge_out_of_reach():
    from tests.test_summons import OWNER, _engine as summon_engine

    engine = summon_engine(["TAL_DEATH_CORPSE_SERVANT"])  # the foe stands 45 feet off
    servant = next(a for a in engine.state.actors.values() if (a.summon or {}).get("group") == "corpse_servant")
    servant.summon["commanded"], servant.movement_remaining_ft = True, 30
    dodge = Candidate("system:combat.dodge")
    assert ai_restraint.restraint(engine, servant, dodge, None) is False
    servant.summon["commanded"] = False  # an uncommanded one Dodges by itself anyway
    assert ai_restraint.restraint(engine, servant, dodge, None) is None
    assert ai_restraint.restraint(engine, servant, Candidate("system:combat.disengage"), None) is None
    servant.summon["commanded"] = True
    assert ai_restraint.restraint(engine, servant, Candidate("system:combat.disengage"), None) is False
    servant.summon["commanded"], servant.movement_remaining_ft = True, 0
    assert ai_restraint.restraint(engine, servant, dodge, None) is None and OWNER


def test_a_self_buff_with_a_retaliation_is_still_a_self_buff():
    class Action:
        target_kind = "SELF"
        parameters = {"typed": {"effects": [{"type": "temp_hp", "applies_to": "self"}, {"type": "damage", "applies_to": "attacker"},
                                            {"type": "extra_damage", "applies_to": "self"}]}}
    assert ai_restraint._self_only(Action())
    Action.parameters = {"typed": {"effects": [{"type": "attack"}]}}
    assert not ai_restraint._self_only(Action())


# ------------------------------------------------------------------------------------------------ summons close in
def _summon_turn(kind=CORPSE_SERVANT, count=1, at=(0, 6), foe_at=(19, 6)):
    """The Bonus Action command given and the summon's turn begun with its whole Speed, at one end of the arena with the one
    enemy at the other: 95 feet along the middle row, farther than a Dash and a move reach the fallback policy's 30-foot band."""
    talent, group = kind
    engine = summon_engine([talent], **{group: count})
    members = summons.owned_by(engine, OWNER, group)
    _turn_of(engine, OWNER)
    # the group's Command (Death servants share one: Commanding Death Servants, rider lane C14)
    _use(engine, OWNER, f".command.{members[0].summon.get('command_group') or group}")
    engine.end_turn()
    assert engine.state.current_actor_id == members[0].entity_id
    members[0].position, engine.state.actors[AN].position = Position(x=at[0], y=at[1]), Position(x=foe_at[0], y=foe_at[1])
    return engine, members, engine.state.actors[AN]


def _menu(engine, actor, for_ai=True):
    return build_decision_context(engine, PolicyLibrary(ROOT).for_actor(actor.entity_id)[0], for_ai=for_ai).legal_candidates


def _nearer(engine, actor, foe, move) -> bool:
    return engine._distance_actor_to_actor(actor, foe, actor_position=move.destination) < engine._distance_actor_to_actor(actor, foe)


def _kinds(menu) -> set:
    return {candidate.kind for candidate in menu}


def _moves(menu) -> list:
    return [candidate for candidate in menu if candidate.kind == CandidateKind.MOVE]


def _dash(menu) -> bool:
    return any(candidate.source_definition_id == "system:combat.dash" for candidate in menu)


# What Hell Opens Beneath the Sect Gate does (a save at the start of the turn, damage on a failure), as the compiler writes it.
HELLFIRE = [{"type": "save", "ability": "WIS", "on_fail": [{"type": "damage", "applies_to": "enemies_in_area", "damage_types": ["fire"],
                                                            "dice": {"count": 8, "sides": 8, "bonus": None}, "flat": 0}], "on_success": []}]
FAR_SIDE = [(x, y) for x in range(6, 20) for y in range(14)]  # from the seventh column to the far wall of the 20 x 14 arena


def _lay(engine, cells, *, owner=AN, on=("start",), who="hostile", effects=HELLFIRE, shape="sphere", **profile):
    """An area a typed ability leaves on the map (tests/test_zones.py), with one trigger by default: Hellfire, on the foes of
    ``owner``. A second call replaces the first."""
    triggers = [] if on is None else [{"id": "hellfire", "name": "Hellfire", "on": list(on), "who": who, "effects": effects}]
    engine.state.zones["zone:test-area"] = ZoneState(
        zone_id="zone:test-area", source_definition_id="action:test.hellfire", owner_id=owner, active=True,
        center=Position(x=cells[0][0], y=cells[0][1]), radius_cells=0, affected_cells=tuple(Position(x=x, y=y) for x, y in cells),
        concentration_link=False, created_round=1,
        trigger_profile={"kind": zones.KIND, "name": "Hellfire", "shape": shape, "triggers": triggers,
                         "numbers": {"save_dc": 15, "pb": 4, "cl": 10}, **profile})
    return engine.state.zones["zone:test-area"]


def test_a_summon_out_of_reach_is_offered_only_steps_toward_the_enemy():
    """Fight audit 2026-09-29 (hunt 1): the fallback policy scores every square 50 feet or more from all enemies alike, below an
    ended turn, so Corpse Servants and Painted Formations Dashed and stood where they were until the round limit."""
    engine, (servant, *_), foe = _summon_turn()
    mine, ai = _menu(engine, servant, for_ai=False), _menu(engine, servant)
    assert STAY <= _kinds(mine) and any(c.kind == CandidateKind.MOVE and not _nearer(engine, servant, foe, c) for c in mine)  # the player's own menu
    assert not _kinds(ai) & STAY
    steps = [c for c in ai if c.kind == CandidateKind.MOVE]
    assert steps and all(_nearer(engine, servant, foe, c) for c in steps)
    assert "system:combat.dash" in {c.source_definition_id for c in ai}


def test_dash_and_then_a_move_stay_open_to_a_summon_walking_in():
    engine, (servant, *_), foe = _summon_turn()
    _use(engine, servant.entity_id, "combat.dash")
    assert servant.movement_remaining_ft == 60 and not servant.action_available
    ai = _menu(engine, servant)
    assert _kinds(ai) == {CandidateKind.MOVE} and all(_nearer(engine, servant, foe, c) for c in ai)
    assert min(engine._distance_actor_to_actor(servant, foe, actor_position=c.destination) for c in ai) == 35  # the whole 60 feet


@pytest.mark.parametrize("kind", [CORPSE_SERVANT, PAINTED_FORMATION], ids=["corpse_servant", "painted_formation"])
def test_the_ai_walks_a_summon_in_across_the_map_rather_than_dash_and_end_its_turn(kind):
    engine, (servant, *_), foe = _summon_turn(kind)
    start, controller = engine._distance_actor_to_actor(servant, foe), LocalDeterministicController()
    policy = PolicyLibrary(ROOT).for_actor(servant.entity_id)[0]
    for _ in range(8):
        if engine.state.current_actor_id != servant.entity_id:
            break
        engine.execute_intent(controller.choose_primary_action(build_decision_context(engine, policy, for_ai=True)).intent)
    assert engine.state.current_actor_id != servant.entity_id  # its turn ended
    assert start - engine._distance_actor_to_actor(servant, foe) >= 30  # by walking in, at least its Speed


def test_a_summon_that_cannot_close_in_keeps_its_choices():
    """Walled into the arena's corner by the arena itself there is no step to take, so its ended turn and Hold stay (an
    empty menu would stop the fight); a Dash opens nothing, so it goes (fight audit 2026-09-29, hunt 2: a Corpse Servant
    sealed in a corridor Dashed every turn and only stepped back and forth). The walls are the three cells around the
    corner: bodies standing there no longer wall it in, because creatures pass each other (combat/gate4_context.py)."""
    engine, members, _ = _summon_turn(at=(0, 0))
    engine.grid.blocked |= {(1, 0), (0, 1), (1, 1)}
    servant = members[0]
    mine, ai = _menu(engine, servant, for_ai=False), _menu(engine, servant)
    assert servant.movement_remaining_ft > 0 and CandidateKind.MOVE not in _kinds(mine) and _dash(mine)
    assert STAY <= _kinds(ai) and not _dash(ai)


def test_a_summon_is_left_alone_when_it_is_not_walking_in():
    engine, (servant, *_), foe = _summon_turn()
    listed = engine.legal_candidates()
    end, hold = (next(c for c in listed if c.kind == kind) for kind in (CandidateKind.END_TURN, CandidateKind.HOLD_POSITION))
    back = next(c for c in listed if c.kind == CandidateKind.MOVE and not _nearer(engine, servant, foe, c))
    verdicts = lambda: [ai_restraint.restraint(engine, servant, c, None) for c in (end, hold, back)]  # noqa: E731
    assert verdicts() == [False, False, False]
    servant.summon["commanded"] = False  # an uncommanded one Dodges and its turn passes by itself
    assert verdicts() == [None, None, None]
    servant.summon["commanded"], servant.movement_remaining_ft = True, 0  # nothing left to walk with
    assert verdicts() == [None, None, None]

    engine, (servant, *_), foe = _summon_turn(at=(18, 6))  # the enemy within reach: with an attack to make it strikes (see below)
    servant.action_available = False  # but once it has, it is left alone: it may step, end its turn or Hold
    assert STAY <= _kinds(_menu(engine, servant))
    assert any(c.kind == CandidateKind.MOVE and not _nearer(engine, servant, foe, c) for c in _menu(engine, servant))


def test_a_summon_with_no_attack_and_a_character_are_left_alone():
    engine = summon_engine(["TAL_DEATH_GHOST_LANTERN"])
    lantern = summons.owned_by(engine, OWNER, "ghost_lantern")[0]
    _turn_of(engine, OWNER)
    _use(engine, OWNER, ".TAL_DEATH_GHOST_LANTERN")  # it arrives by an Action
    _turn_of(engine, OWNER)
    _use(engine, OWNER, ".command.ghost_lantern")
    engine.end_turn()
    assert engine.state.current_actor_id == lantern.entity_id and lantern.summon["commanded"] and lantern.movement_remaining_ft > 0
    lantern.position, engine.state.actors[AN].position = Position(x=0, y=6), Position(x=19, y=6)
    assert STAY <= _kinds(_menu(engine, lantern))  # nothing here to send it toward an enemy

    engine = _fight(_sheet([*DARK]), me_at=(0, 6), foe_at=(19, 6))
    me = engine.state.actors[ME]
    assert me.movement_remaining_ft > 0 and STAY <= _kinds(_menu(engine, me))  # a character's own way with the enemy is its own


# --------------------------------------------------------------------------------------------- summons that can strike
def _beast_turn(beast="wolf", at=None, foe_at=(19, 6), hp=1.0):
    """A tamed beast, which needs no command, at the start of its own turn with its whole Speed; by default beside the one
    enemy (its attack reaches 5 feet), at ``hp`` of its Hit Points."""
    engine = summon_engine(["TAL_BEASTMASTERY_BEAST_TAMER"], beasts=[beast])
    creature = summons.owned_by(engine, OWNER)[0]
    _turn_of(engine, OWNER)
    engine.end_turn()
    assert engine.state.current_actor_id == creature.entity_id and creature.summon["command"] == "free"
    if at is None:
        # Keep the nearest footprint edge beside the foe. A Large tiger fills
        # two columns; placing its anchor at 18 would overlap the foe at 19.
        at = (foe_at[0] - engine._footprint(creature).width_cells, foe_at[1])
    creature.position, engine.state.actors[AN].position = Position(x=at[0], y=at[1]), Position(x=foe_at[0], y=foe_at[1])
    assert not set(engine._actor_cells(creature)) & set(engine._actor_cells(engine.state.actors[AN]))
    creature.current_hp = int(creature.maximum_hp * hp)
    return engine, creature, engine.state.actors[AN]


def _strikes(engine, menu) -> list:
    return [c for c in menu if c.kind == CandidateKind.ACTION and str(engine.action_catalog[c.source_definition_id].target_kind).endswith("HOSTILE_ENTITY")]


def _play(engine, actor, limit=12) -> list:
    """What the built-in AI chose for the actor, in order, until its turn ended."""
    controller, policy, chosen = LocalDeterministicController(), PolicyLibrary(ROOT).for_actor(actor.entity_id)[0], []
    for _ in range(limit):
        if engine.state.current_actor_id != actor.entity_id:
            break
        context = build_decision_context(engine, policy, for_ai=True)
        intent = controller.choose_primary_action(context).intent
        chosen.append(next(c for c in context.legal_candidates if c.candidate_id == intent.candidate_id))
        engine.execute_intent(intent)
    return chosen


def test_a_summon_with_an_attack_to_make_is_offered_it_and_nothing_in_its_place():
    """Fight audit 2026-09-29, hunt 3: 26 of 397 summon decisions took a step or a Dodge with an attack legal (a Wolf beside its
    foe stepped round it five times, out of reach, then Dodged): the fallback policy scores a step that ends 5 to 30 feet from
    an enemy above a plain attack, and a Dodge above any attack once the summon is at 40% of its Hit Points."""
    engine, (servant, *_), _ = _summon_turn(at=(18, 6))  # commanded, the enemy within reach
    mine, ai = _menu(engine, servant, for_ai=False), _menu(engine, servant)
    assert STAY <= _kinds(mine) and _moves(mine) and _dash(mine) and len(_strikes(engine, mine)) == 1  # the player's menu keeps every choice
    assert {c.candidate_id for c in mine if c.source_definition_id in {"system:combat.dodge", "system:combat.disengage"}}
    assert [c.candidate_id for c in ai] == [c.candidate_id for c in _strikes(engine, mine)]  # no step, Dodge, Disengage, Dash, end, Hold

    left_out = [c for c in mine if c not in _strikes(engine, mine)]
    assert [ai_restraint.restraint(engine, servant, c, None) for c in left_out] == [False] * len(left_out)
    servant.summon["commanded"] = False  # one that is not acting is left to the engine (its turn passes by itself)
    assert {ai_restraint.restraint(engine, servant, c, None) for c in left_out} == {None}
    servant.summon["commanded"] = True

    servant.action_available = False  # it has struck: it may step, end its turn or Hold (the menu is worked out anew)
    assert STAY <= _kinds(_menu(engine, servant)) and _moves(_menu(engine, servant))
    servant.action_available = True
    assert [c.candidate_id for c in _menu(engine, servant)] == [c.candidate_id for c in _strikes(engine, mine)]


@pytest.mark.parametrize("beast, hp", [("wolf", 1.0), ("wolf", 0.3), ("tiger", 0.3)], ids=["wolf", "wounded wolf", "wounded tiger"])
def test_the_ai_has_a_summon_beside_its_foe_attack_rather_than_step_or_dodge(beast, hp):
    """Its first choice, not its last: a Wolf's step (90) beat its bite (86) and any wounded beast's Dodge beat its attack."""
    engine, creature, foe = _beast_turn(beast, hp=hp)
    # The admitted summon-size metadata gives a tiger its printed 2x2 body.
    # Keep its whole body beside the foe instead of overlapping the foe's cell.
    creature.position = creature.position.model_copy(update={
        'x': foe.position.x - engine._footprint(creature).width_cells})
    assert engine._distance_actor_to_actor(creature, foe) == 5
    engine._assert_invariants()
    chosen = _play(engine, creature)
    assert engine.state.current_actor_id != creature.entity_id  # its turn ended
    assert chosen[0].kind == CandidateKind.ACTION and chosen[0].target_ids == (foe.entity_id,) and _strikes(engine, chosen[:1])
    assert not any(c.source_definition_id in {"system:combat.dodge", "system:combat.disengage", "system:combat.dash"} for c in chosen)
    assert not creature.action_available and len(_strikes(engine, chosen)) == 1  # it struck, once (an Action is one attack)


def test_the_ai_strikes_as_soon_as_a_summon_walking_in_is_within_reach():
    engine, creature, foe = _beast_turn("wolf", at=(13, 6))  # 30 feet off: it walks in and stands beside the foe
    chosen = _play(engine, creature)
    strike = next(i for i, c in enumerate(chosen) if c in _strikes(engine, chosen))
    assert strike and all(c.kind == CandidateKind.MOVE for c in chosen[:strike])  # it only walked in until then
    reached = [engine._distance_actor_to_actor(creature, foe, actor_position=c.destination) <= 5 for c in chosen[:strike]]
    assert reached[-1] and reached.count(True) == 1  # the step that brought it within reach was the last before its bite (not the first of several)


def test_a_summon_with_nothing_to_strike_at_is_left_alone():
    # A living beast can be Charmed; a Corpse Servant is immune to that condition.
    engine, servant, foe = _beast_turn("wolf", at=(18, 6))
    engine._apply_condition(servant, "condition:typed.charmed", "src.charm", foe.entity_id, expires_on="UNTIL_REMOVED")
    assert engine._has_condition(servant, "condition:typed.charmed")
    ai = _menu(engine, servant)
    assert not _strikes(engine, ai) and STAY <= _kinds(ai) and _moves(ai) and _dash(ai)

    engine = summon_engine(["TAL_DEATH_GHOST_LANTERN"])  # a lantern has nothing to fight with
    lantern = summons.owned_by(engine, OWNER, "ghost_lantern")[0]
    _turn_of(engine, OWNER)
    _use(engine, OWNER, ".TAL_DEATH_GHOST_LANTERN")
    _turn_of(engine, OWNER)
    _use(engine, OWNER, ".command.ghost_lantern")
    engine.end_turn()
    assert engine.state.current_actor_id == lantern.entity_id and lantern.summon["commanded"]
    lantern.position, engine.state.actors[AN].position = Position(x=18, y=6), Position(x=19, y=6)
    ai = _menu(engine, lantern)
    assert not _strikes(engine, ai) and STAY <= _kinds(ai) and _moves(ai)

    engine = _fight(_sheet([*DARK]), me_at=(18, 6), foe_at=(19, 6))  # a character beside the enemy keeps its own way with it
    me = engine.state.actors[ME]
    assert STAY <= _kinds(_menu(engine, me)) and _moves(_menu(engine, me))


def test_a_summon_is_never_left_without_a_choice(monkeypatch):
    """The attack that keeps the rest off the menu must be one the AI's menu keeps (combat/gate4_context.py drops what is
    inert): a menu with nothing in it stops the fight (CONTROLLER_NO_LEGAL_CHOICE)."""
    engine, (servant, *_), _ = _summon_turn(at=(18, 6))
    for action in engine.action_catalog.values():
        if action.owner_id == servant.entity_id and str(action.target_kind).endswith("HOSTILE_ENTITY"):
            monkeypatch.setitem(action.parameters, "inert", True)
    ai = _menu(engine, servant)
    assert ai and not _strikes(engine, ai) and STAY <= _kinds(ai)


def test_an_attack_this_plug_in_drops_does_not_take_the_rest_of_the_menu_with_it(monkeypatch):
    """Nor one that ai_restraint itself leaves off (a Concentration technique the summon still holds): it is not an attack
    it would make, so a step or a Dodge stays open rather than leave the AI nothing."""
    engine, (servant, *_), _ = _summon_turn(at=(18, 6))
    strike = next(a for a in engine.action_catalog.values() if a.owner_id == servant.entity_id and a.source_definition_id.endswith(".attack0"))
    assert [c.candidate_id for c in _menu(engine, servant)] == [c.candidate_id for c in _strikes(engine, _menu(engine, servant, for_ai=False))]
    typed = strike.parameters.get("typed") or {}
    monkeypatch.setitem(strike.parameters, "typed", {**typed, "duration": {**(typed.get("duration") or {}), "concentration": True}})
    engine._start_concentration(servant, strike.source_definition_id)
    ai = _menu(engine, servant)  # the attack is dropped ...
    assert ai and not _strikes(engine, ai) and STAY <= _kinds(ai) and _moves(ai)  # ... and the steps and the Dodge come back


# ---------------------------------------------------------------------------------------- summons and zones that hurt
def test_a_summon_is_not_offered_a_step_into_a_zone_that_would_hurt_it():
    """Fight audit 2026-09-29, hunt 2: 14 of 48 summon defeats were a zone's trigger, 7 of them before the summon had made an
    attack -- all four of a caster's Corpse Servants walked into "Hell Opens Beneath the Sect Gate", which damages at the start
    of the turn, by the nearer steps the menu had left them. A step into it is no step toward the enemy."""
    engine, (servant, *_), foe = _summon_turn()
    _lay(engine, FAR_SIDE)
    mine, ai = _menu(engine, servant, for_ai=False), _menu(engine, servant)
    assert max(c.destination.x for c in _moves(mine)) >= 6 and _dash(mine)  # the player's own menu: every step, into it too
    steps = _moves(ai)
    assert steps and all(c.destination.x < 6 and _nearer(engine, servant, foe, c) for c in steps)
    assert not _kinds(ai) & STAY and _dash(ai)  # safe steps toward the enemy remain, so it does not stand; a Dash adds more
    into = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.MOVE and c.destination.x == 6)
    assert ai_restraint.restraint(engine, servant, into, None) is False
    servant.summon["commanded"] = False  # one that is not acting is left to the engine
    assert ai_restraint.restraint(engine, servant, into, None) is None


def test_a_summon_at_the_edge_of_a_hurting_zone_holds_rather_than_walk_in_or_dash():
    """Every step toward the enemy ends in the zone: nothing pushes it in (its turn may end, or Hold), a Dash would only spend
    its Action, and what is left of the menu is not empty."""
    engine, (servant, *_), _ = _summon_turn(at=(5, 6))
    _lay(engine, FAR_SIDE)
    mine, ai = _menu(engine, servant, for_ai=False), _menu(engine, servant)
    assert any(c.destination.x >= 6 for c in _moves(mine)) and _dash(mine)
    assert STAY <= _kinds(ai) and not _dash(ai)
    assert _moves(ai) and all(c.destination.x < 6 for c in _moves(ai))


def test_a_summon_may_step_into_a_hurting_zone_to_strike_from_there():
    """"...unless it ends within attack reach of an enemy" -- and still has its Action to use on it. After a Dash it has none,
    so the same step is one into the zone for nothing."""
    engine, (servant, *_), foe = _summon_turn(at=(2, 6), foe_at=(8, 6))
    _lay(engine, FAR_SIDE)
    inside = [c for c in _moves(_menu(engine, servant)) if c.destination.x >= 6]
    assert inside and all(engine._distance_actor_to_actor(servant, foe, actor_position=c.destination) <= 5 for c in inside)
    assert any(c.destination.x >= 6 and engine._distance_actor_to_actor(servant, foe, actor_position=c.destination) > 5
               for c in _moves(_menu(engine, servant, for_ai=False)))
    assert not _kinds(_menu(engine, servant)) & STAY

    engine, (servant, *_), foe = _summon_turn(at=(2, 6), foe_at=(8, 6))
    _lay(engine, FAR_SIDE)
    servant.action_available = False
    steps = _moves(_menu(engine, servant))
    assert steps and all(c.destination.x < 6 for c in steps)


def test_a_summon_already_in_a_hurting_zone_walks_on_toward_the_enemy():
    """Ending a step deeper in is no new exposure: what the zone does, it does at the start of the summon's next turn wherever
    in it the summon stands, and the summon strikes sooner from nearer."""
    engine, (servant, *_), foe = _summon_turn(at=(8, 6))
    _lay(engine, FAR_SIDE)
    steps = _moves(_menu(engine, servant))
    assert steps and all(_nearer(engine, servant, foe, c) for c in steps) and max(c.destination.x for c in steps) >= 13
    assert not _kinds(_menu(engine, servant)) & STAY


def test_the_ai_stops_a_summon_short_of_a_zone_that_would_hurt_it():
    """Played out by the built-in AI: its Dash, and the steps after it with its Action spent, end at the edge of the zone."""
    engine, (servant, *_), _ = _summon_turn()
    _lay(engine, FAR_SIDE)
    controller, policy = LocalDeterministicController(), PolicyLibrary(ROOT).for_actor(servant.entity_id)[0]
    for _ in range(8):
        if engine.state.current_actor_id != servant.entity_id:
            break
        engine.execute_intent(controller.choose_primary_action(build_decision_context(engine, policy, for_ai=True)).intent)
    assert engine.state.current_actor_id != servant.entity_id  # its turn ended
    assert 0 < servant.position.x < 6  # it walked in, but not into the zone


def test_only_a_zone_that_would_hurt_this_creature_is_a_hazard():
    engine, (servant, *_), foe = _summon_turn()
    inside, outside = Position(x=8, y=6), Position(x=3, y=6)
    _lay(engine, FAR_SIDE)  # the enemy's, working on the enemy's foes (the default)
    hurts = zones.hazard_test(engine, servant)
    assert hurts(inside) and not hurts(outside)
    foe.position = outside  # (it stood inside its own zone at the far wall)
    assert zones.hazard_test(engine, foe) is None  # not the side that made it
    _lay(engine, FAR_SIDE, who="any")
    assert zones.hazard_test(engine, foe)(inside)  # unless it works on every creature
    _lay(engine, FAR_SIDE, owner=OWNER)  # the summon's own side's
    assert zones.hazard_test(engine, servant) is None
    _lay(engine, FAR_SIDE, owner=OWNER, who="ally")  # unless it works on its creator's allies
    assert zones.hazard_test(engine, servant)(inside)


DAMAGE = {"type": "damage", "applies_to": "target", "damage_types": ["fire"], "dice": {"count": 2, "sides": 6}}


@pytest.mark.parametrize("effects", [
    [], [{"type": "condition", "condition": "blinded", "applies_to": "target"}], [{**DAMAGE, "applies_to": "self"}],
    [{**DAMAGE, "deferred": True}], [{**DAMAGE, "min_cl": 15}]],
    ids=["nothing", "a condition", "damage to its creator", "deferred", "above the zone's level"])
def test_a_zone_that_would_not_hurt_it_is_no_hazard(effects):
    engine, (servant, *_), _ = _summon_turn()
    _lay(engine, FAR_SIDE, on=("enter", "start"), effects=effects)
    assert zones.hazard_test(engine, servant) is None
    _lay(engine, FAR_SIDE, on=("enter", "start"), effects=[*effects, DAMAGE])
    assert zones.hazard_test(engine, servant)(Position(x=8, y=6))


def test_a_line_that_hurts_those_who_cross_it_is_a_hazard_across_it():
    engine, (servant, *_), _ = _summon_turn()
    _lay(engine, [(8, y) for y in range(14)], on=("cross",), shape="line", effects=[DAMAGE])
    hurts = zones.hazard_test(engine, servant)
    assert hurts(Position(x=9, y=6)) and hurts(Position(x=12, y=2))
    assert not hurts(Position(x=7, y=6)) and not hurts(Position(x=8, y=6))  # short of it, or on it (only "enter" reads that)


def test_map_terrain_is_a_hazard_by_its_own_rule_for_moving_through_it():
    """combat/rules/terrain.json: Shattered Glass cuts at any distance, Obsidian on a move of more than 10 feet, Ash costs a
    Reaction, not blood. The map takes no side."""
    terrains = zones.terrain_rules()["terrains"]
    engine, (servant, *_), _ = _summon_turn()
    cells = [(x, y) for x in range(1, 20) for y in range(14)]  # the servant stands on the bare ground at (0, 6)
    _lay(engine, cells, owner=zones.MAP_OWNER, on=None, move_through=terrains["shattered glass terrain"]["move_through"])
    assert zones.hazard_test(engine, servant)(Position(x=1, y=6))
    _lay(engine, cells, owner=zones.MAP_OWNER, on=None, move_through=terrains["obsidian terrain"]["move_through"])
    hurts = zones.hazard_test(engine, servant)
    assert not hurts(Position(x=2, y=6)) and hurts(Position(x=3, y=6))  # 10 feet, and 15
    _lay(engine, cells, owner=zones.MAP_OWNER, on=None, move_through=terrains["ash terrain"]["move_through"])
    assert zones.hazard_test(engine, servant) is None


def test_dash_stays_when_the_movement_it_adds_opens_a_step_toward_the_enemy():
    """Only a Dash that opens no way is spent for nothing (hunt 2: sealed in a corridor a Corpse Servant Dashed every turn and
    only stepped back and forth): not with 5 feet left in ground that costs double, nor where the way round a wall is more
    than the Movement it has left but not more than a Dash's."""
    engine, (servant, *_), foe = _summon_turn(at=(2, 6))
    _lay(engine, [(x, y) for x in range(6) for y in range(14)], owner=foe.entity_id, on=None, difficult="all")
    servant.movement_remaining_ft = 5
    assert not _moves(_menu(engine, servant, for_ai=False))
    ai = _menu(engine, servant)
    assert not _moves(ai) and STAY <= _kinds(ai) and _dash(ai)

    engine, (servant, *_), _ = _summon_turn(at=(3, 6))
    engine.grid.blocked |= {(4, y) for y in range(14) if y != 13}  # a wall down the fifth column, open at the far end only
    ai = _menu(engine, servant)
    assert not [c for c in _moves(ai) if c.destination.x > 3] and STAY <= _kinds(ai) and _dash(ai)

    engine, (servant, *_), _ = _summon_turn(at=(3, 6))
    engine.grid.blocked |= {(4, y) for y in range(14)}  # the gap shut
    ai = _menu(engine, servant)
    assert STAY <= _kinds(ai) and not _dash(ai) and _dash(_menu(engine, servant, for_ai=False))
