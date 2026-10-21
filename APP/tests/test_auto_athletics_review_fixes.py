"""Table-level regressions for the AUTO8 pre-merge review (lane AUTO8f1, findings F2, F7 and F10).

Each test builds a real Factory match, answers the printed question through the table's own Ask-me
transport -- the same pause, answer and replay a live player meets -- and reloads the stored fight from
disk, so saved-fight compatibility is checked rather than asserted. The companion file
``tests/test_auto_athletics.py`` holds the engine-level cases.
"""

from __future__ import annotations

import pytest

from combat import posture
from combat.ext import athletics
from tests.auto8f1_table_support import (
    AXE_KIT,
    FOE,
    OWNER,
    POLEARM_KIT,
    ascent_move,
    candidate_id,
    fixture,
    reload_identical,
    strip_athletics_passives,
    zero_martial_focus,
)
from tests.test_auto_athletics import (
    COORDINATED,
    COURT,
    HELICOPTER,
    MERIDIAN,
    SPARROWS,
    SPEED_BOOST,
)

FOCUS = "resource:core.martial_focus"
COURT_CLAUSES = "condition:typed.court_of_steps"
HELICOPTER_CONDITION = "condition:typed.helicopter_descent"


def test_a_fight_saved_before_the_courts_passive_row_still_gets_its_speed_and_its_free_stand(tmp_path):
    """F2: Court read the printed clauses out of this lane's new passive row, but the stored bundle of a fight
    saved before this lane has no such row; its stance then lost the +20 feet Speed it had always been given.

    The owner's bundle here is exactly the pre-lane one (no ``athletics`` passive rows), and the fight is
    stored and reloaded through the supported path."""
    game = fixture(tmp_path, [COURT], seed="AUTO8F1-COURT", cl=15, bundle_transform=strip_athletics_passives)
    session = game["combat"]._load_session(game["match_id"])
    bundle_rows = [row for rows in session.engine.typed_passive_rows.values() for row in rows
                   if row.get("block") == "athletics"]
    assert not bundle_rows, "this bundle really is the pre-lane one"
    before = session.engine._effective_speed(session.engine.state.actors[OWNER])

    game["commit"](candidate_id(game["menu"](), "Court of Ten Thousand Steps"))

    owner = game["reload_owner"]()
    assert owner is not None
    assert owner.conditions, "the stored fight still holds Court's stance"
    assert any(condition.condition_id.startswith("condition:typed.stance.") for condition in owner.conditions.values())
    stored = game["combat"]._load_session(game["match_id"]).engine
    assert stored._effective_speed(owner) == before + 20, "the +20 feet Speed survives a reload of a pre-lane bundle"
    # Standing is a cost query, so the fighter has to be down for it to mean anything.
    for actor_id, expected in ((OWNER, 0), (FOE, stored._effective_speed(stored.state.actors[FOE]) // 2)):
        target = stored.state.actors[actor_id]
        stored._apply_condition(target, "condition:typed.prone", COURT, OWNER, expires_on="STAND_UP")
        cost = posture.standing_cost(stored, target)
        stored._remove_condition(target, "condition:typed.prone", COURT)
        assert cost == expected, f"{actor_id}: standing costs {cost}, not {expected}"
    assert any(condition.condition_id == COURT_CLAUSES for condition in owner.conditions.values()), \
        "the printed terrain clause is republished for a stance the stored fight already held"
    reload_identical(game["combat"], game["match_id"], game["userdata"])


def test_the_table_asks_meridian_beside_speed_boosts_own_dash_grant(tmp_path):
    """F7: the printed choice was stamped "this Focus grant is the newest event", and Speed Boost's Dash grant
    records an event between that grant and action_completed, so a character owning both talents lost the choice
    entirely. Driven through the table, with the fight stored and reloaded afterwards."""
    game = fixture(tmp_path, [COORDINATED, MERIDIAN, SPEED_BOOST], seed="AUTO8F1-MERIDIAN",
                   bundle_transform=zero_martial_focus)
    owner = game["reload_owner"]()
    assert owner.resources.get(FOCUS, 0) == 0, "the owner starts without Martial Focus"

    def take_step(prompt, choice):
        return game["first_option"](prompt, choice, "step")

    result = game["commit"](candidate_id(game["menu"](), "Dash"), take_step)
    owner = game["reload_owner"]()
    assert owner.resources[FOCUS] == 1, "Coordinated Movement restored Martial Focus through the Dash"
    assert owner.turn_flags.get("oa_free_ft") == 10, "the printed 10 feet of movement without Opportunity Attacks"
    assert owner.turn_flags.get("athletics_used:meridian_threading"), "the printed choice was answered at the table"
    reload_identical(game["combat"], game["match_id"], game["userdata"])
    assert result["status"] == "COMMITTED"


@pytest.mark.parametrize("kit,decline", [(POLEARM_KIT, False), (AXE_KIT, False), (POLEARM_KIT, True)])
def test_helicopter_descent_at_the_table_needs_the_printed_gear_and_can_be_refused(tmp_path, kit, decline):
    """F10: "while wielding an appropriate polearm, rope, chain, whip, or tether item" was never checked, and the
    question offered no way to refuse. Driven through the table with the owner ending its turn in the air."""
    wielding_pole_weapon = kit is POLEARM_KIT
    game = fixture(tmp_path, [HELICOPTER, SPARROWS],
                   seed=f"AUTO8F1-HELI-{'POLEARM' if wielding_pole_weapon else 'AXE'}"
                        f"{'-NODECLINE' if decline else ''}",
                   kit=kit, cl=15)
    game["commit"](ascent_move(game["menu"]())["candidate_id"])
    prompts = game["end_own_turn"](decline=decline)
    asked = [prompt for prompt in prompts if prompt.get("choice")]
    assert bool(asked) is wielding_pole_weapon, (
        f"a {'short axe' if not wielding_pole_weapon else 'halberd'} in hand: the table asked {asked!r}")
    for prompt in asked:
        assert prompt["choice"]["allow_decline"] is True, "a printed cost must be refusable"

    owner = game["reload_owner"]()
    held = [condition for condition in owner.conditions.values() if condition.condition_id == HELICOPTER_CONDITION]
    recorded = wielding_pole_weapon and not decline
    assert bool(held) is recorded, (
        f"descent {'is' if recorded else 'is not'} recorded ({[c.condition_id for c in owner.conditions.values()]})")
    if recorded:
        assert owner.resources[FOCUS] == 0, "the printed Martial Focus is spent"
        assert held[0].data["fall_speed_ft"] == 60 and held[0].data["fall_lands_upright"] == 1
    else:
        assert owner.resources[FOCUS] == 1, "a refused or illegal descent spends nothing"
    reload_identical(game["combat"], game["match_id"], game["userdata"])


def test_the_foe_is_untouched_by_the_owners_court(tmp_path):
    """F1 at the table: the shared ``condition:typed.ignore_difficult`` id must not be Court's to hand out."""
    game = fixture(tmp_path, [COURT], seed="AUTO8F1-ISOLATION", cl=15)
    game["commit"](candidate_id(game["menu"](), "Court of Ten Thousand Steps"))
    state = game["combat"]._load_session(game["match_id"]).engine.state
    for actor in state.actors.values():
        if actor.entity_id == OWNER:
            continue
        assert not [condition for condition in actor.conditions.values()
                    if condition.condition_id == COURT_CLAUSES], f"{actor.entity_id} was given Court's condition"
    assert not [condition for condition in state.actors[FOE].conditions.values()
                if condition.condition_id.startswith("condition:typed.stance.")], "and no stance either"
    reload_identical(game["combat"], game["match_id"], game["userdata"])


def test_the_foe_keeps_its_own_terrain_condition_when_the_owners_court_ends(tmp_path):
    """F1 at the table, the review's own example: Great Beast Charge, Thousand-Mile Legs, Lotus Step and the Jade
    Sovereign all apply the shared ``condition:typed.ignore_difficult``. With Court on its own condition id, the
    stance's printed early end ("if you become Incapacitated") takes off only Court's own instances and leaves
    another creature's terrain benefit alone."""
    from combat import motion

    game = fixture(tmp_path, [COURT], seed="AUTO8F1-LENT", cl=15)
    game["commit"](candidate_id(game["menu"](), "Court of Ten Thousand Steps"))
    owner = game["reload_owner"]()
    assert any(condition.condition_id == COURT_CLAUSES for condition in owner.conditions.values())

    engine = game["combat"]._load_session(game["match_id"]).engine
    foe = engine.state.actors[FOE]
    engine._apply_condition(foe, "condition:typed.ignore_difficult", "TAL_BEASTMASTERY_GREAT_BEAST_CHARGE",
                            foe.entity_id, expires_on="UNTIL_REMOVED", data={"label": "difficult terrain ignored"})
    assert motion.ignores_difficult(engine, engine.state.actors[OWNER]) is True
    assert motion.ignores_difficult(engine, foe) is True

    athletics.court_ends_incapacitated(engine, engine.state.actors[OWNER], {"actor_id": OWNER})
    assert motion.ignores_difficult(engine, engine.state.actors[OWNER]) is False, "Court's own stance is gone"
    assert [condition.condition_id for condition in foe.conditions.values()] == ["condition:typed.ignore_difficult"]
    assert motion.ignores_difficult(engine, foe) is True, "the foe's own benefit never went with it"
