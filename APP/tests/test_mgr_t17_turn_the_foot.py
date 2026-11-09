"""TAL_FLOWING_RIVER_TURN_THE_FOOT (RIDERWIRE1 / B7-P2a): all three choices the talent prints actually happen.

The failed save prints "choose one: its Speed is reduced by 10 feet until the start of its next turn; it has
Disadvantage on the next Opportunity Attack it makes before the start of its next turn; it falls Prone". Speed and
Prone already resolved; the Opportunity-Attack choice resolved nothing, because its row
{"type": "disadvantage", "on": "the next Opportunity Attack it makes"} matched no branch of block_advantage and
fell through to a GM rider.

Every test drives a real fight through CombatService/TabletopService (tests/h1_support.sheet builds the sheet,
tests/hunt12_support.reload reads the committed fight back), scripts only the dice it is about, and answers the
prompts a player would answer. The Opportunity Attack is provoked for real: the striker walks out of the
creature's reach and the creature spends its Reaction on it.
"""

import json

import pytest

from combat.factory_compiler import TYPED_AUTHORITY
from tests import test_auto21_weapons as weapons

from combat.ext import effect_durations
from tests.test_auto21_weapons import (DAGGER, FOE, ME, ask, attack_on, conditions, events, fight, force_rolls, reload,
                                       to_turn)


RESPONSE = "TAL_FLOWING_RIVER_FLOWING_RESPONSE"
TURN_THE_FOOT = "TAL_FLOWING_RIVER_TURN_THE_FOOT"
CHOICE = "condition:typed.turn_the_foot_choice"
OA_CONDITION = "condition:typed.opportunity_attack_mode"

SLOW = ("Turn the Foot: Speed -10 feet", "slow")
OA = ("Turn the Foot: Disadvantage on its next Opportunity Attack", "oa")
PRONE = ("Turn the Foot: Prone", "prone")


@pytest.fixture(autouse=True)
def synthetic_response_authority(monkeypatch):
    """Keep the real compiler/table flow, without private prose or display-name matching.

    Public authority scrambles mechanic names independently of modifier target
    names. Build both collaborating records here instead: their names match,
    and their typed effects are the same save/choice seam the fight exercises.
    Equipment and unrelated records use the ordinary, publicly shipped data.
    """
    authority = json.loads(TYPED_AUTHORITY.read_bytes())
    common = {
        "schema": "TianxiaFoundry.TypedMechanic.v1",
        "sphere_id": "tianxia.sphere.flowing_river",
        "cost": [], "range": None, "area": None, "target": None,
        "duration": {"kind": "instant"}, "riders": [], "description": [],
        "coverage": "FULL", "options": [],
    }
    authority["mechanics"][RESPONSE] = {
        **common, "mechanic_id": RESPONSE, "kind": "base_ability",
        "name": "Test response",
        "activation": {"economy": "reaction",
                       "trigger": "When a creature you can see makes a melee attack roll against you"},
        "use_limit": "once_per_round",
        "effects": [{"type": "flowing_yield_attack", "second_pass": True}],
    }
    authority["mechanics"][TURN_THE_FOOT] = {
        **common, "mechanic_id": TURN_THE_FOOT, "kind": "talent",
        "name": "Test response choice", "activation": {"economy": "passive"},
        "effects": [],
        "modifier": {
            "scope": "named", "targets": ["Test response"], "when": "success",
            "optional": False, "limit": "none", "group": "Response",
            "effects": [{"type": "save", "ability": "dex", "applies_to": "target",
                         "on_fail": [{"type": "bodyb_response_choice", "group": "turn_the_foot"}],
                         "on_success": []}],
        },
    }
    compile_character = weapons.compile_character

    def compile_synthetic(document, **kwargs):
        return compile_character(document, typed_authority=authority, **kwargs)

    monkeypatch.setattr(weapons, "compile_character", compile_synthetic)


def _cheb(a, b):
    return max(abs(a.x - b.x), abs(a.y - b.y))


def _walk(table, mid, combat, squares):
    """The striker walks ``squares`` squares and ends next to the creature (ME), so it can still attack it."""
    engine = combat._load_session(mid).engine
    me, foe = engine.state.actors[ME].position, engine.state.actors[FOE].position
    step = next(c for c in engine.legal_candidates()
                if c.kind.value == "MOVE" and _cheb(c.destination, me) == 1 and _cheb(c.destination, foe) == squares)
    ask(table, mid, step.candidate_id)


def _turn_the_foot(tmp_path, monkeypatch, option, *, squares=0, save_value=3):
    """Flowing Response succeeds, the striker (after walking ``squares`` squares) fails its save, the player picks ``option``; return the fight.

    ``option`` is (the toggle's display name, the option key the choice condition records).
    """
    label, key = option
    combat, table, mid = fight(tmp_path, mids=(RESPONSE, TURN_THE_FOOT), me_kit=(DAGGER,), foe_kit=(DAGGER,),
                               seed="MGRT17")
    to_turn(table, mid, ME)
    engine = combat._load_session(mid).engine
    # Pin fixture compilation too: a missing named attachment must not look like
    # a successful save or an inert branch in the table assertions below.
    from combat.ext import flowing_river
    riding = flowing_river._riding(engine, engine.state.actors[ME])
    assert TURN_THE_FOOT in riding, riding
    assert riding[TURN_THE_FOOT][0]["type"] == "save"
    speed_before = engine._effective_speed(engine.state.actors[FOE])
    toggle = next(c for c in engine.legal_candidates() if c.display_name.startswith(label))
    ask(table, mid, toggle.candidate_id)
    to_turn(table, mid, FOE)
    if squares:
        _walk(table, mid, combat, squares)
    # Yield Against an Attack succeeds only when the striker's attack MISSES, and Turn the Foot runs only after that success.
    # So the striker's attack roll is a natural 1 (a miss), and its Dexterity save for Turn the Foot fails (3).
    # force_rolls scripts the named creature only.
    force_rolls(monkeypatch, attack=(FOE,), attack_value=1, save=(FOE,), save_value=save_value)
    ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    assert conditions(tmp_path, mid, ME)[CHOICE].data["choice"] == key, "the printed choice is the one chosen"
    return combat, table, mid, speed_before


def _provoke(tmp_path, combat, table, mid):
    """Walk the striker out of the creature's reach; return the Opportunity Attacks the creature then makes."""
    to_turn(table, mid, ME)
    engine = combat._load_session(mid).engine
    foe_at = engine.state.actors[FOE].position
    away = next(c for c in engine.legal_candidates()
                if c.kind.value == "MOVE"
                and max(abs(c.destination.x - foe_at.x), abs(c.destination.y - foe_at.y)) > 1)
    ask(table, mid, away.candidate_id)
    return [roll for roll in events(tmp_path, mid, "ATTACK_ROLLED", FOE)
            if "opportunity_attack" in str(roll.payload.get("reason"))]


def _modes(tmp_path, mid, actor_id):
    return [roll.payload["mode"] for roll in events(tmp_path, mid, "ATTACK_ROLLED", actor_id)]


def test_oa_choice_gives_disadvantage_on_exactly_the_next_opportunity_attack(tmp_path, monkeypatch):
    """Printed: "it has Disadvantage on the next Opportunity Attack it makes before the start of its next turn"."""
    combat, table, mid, _ = _turn_the_foot(tmp_path, monkeypatch, OA)
    armed = conditions(tmp_path, mid, FOE)[OA_CONDITION]
    foe_turn = reload(tmp_path, mid).state.actors[FOE].turns_started + 1
    assert armed.expires_on == effect_durations.token("start", FOE, foe_turn), \
        "the window ends at the start of the creature's own next turn: " + armed.expires_on
    assert _modes(tmp_path, mid, FOE) == ["NORMAL"], "the attack it made this turn was not an Opportunity Attack"

    opportunity = _provoke(tmp_path, combat, table, mid)
    assert len(opportunity) == 1, "one Opportunity Attack, not two"
    assert opportunity[0].payload["mode"] == "DISADVANTAGE"
    assert _modes(tmp_path, mid, FOE) == ["NORMAL", "DISADVANTAGE"]
    assert OA_CONDITION not in conditions(tmp_path, mid, FOE), "that one Opportunity Attack used the condition up"


@pytest.mark.parametrize("option", [SLOW, OA, PRONE])
def test_successful_save_applies_none_of_the_failed_save_choices(tmp_path, monkeypatch, option):
    _, _, mid, speed_before = _turn_the_foot(tmp_path, monkeypatch, option, squares=2, save_value=20)
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[FOE]) == speed_before
    held = conditions(tmp_path, mid, FOE)
    assert OA_CONDITION not in held
    assert "condition:typed.prone" not in held


def test_oa_choice_does_not_outlive_its_window(tmp_path, monkeypatch):
    """Printed: "before the start of its next turn" -- an unspent condition ends with the window."""
    combat, table, mid, _ = _turn_the_foot(tmp_path, monkeypatch, OA)
    assert OA_CONDITION in conditions(tmp_path, mid, FOE)
    to_turn(table, mid, ME)   # the striker walks nowhere
    to_turn(table, mid, FOE)  # the creature's next turn simply starts
    assert OA_CONDITION not in conditions(tmp_path, mid, FOE)
    assert _modes(tmp_path, mid, FOE) == ["NORMAL"]


def test_speed_choice_still_only_slows_the_creature(tmp_path, monkeypatch):
    combat, table, mid, speed_before = _turn_the_foot(tmp_path, monkeypatch, SLOW)
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[FOE]) == speed_before - 10
    assert OA_CONDITION not in conditions(tmp_path, mid, FOE)
    assert _provoke(tmp_path, combat, table, mid)[0].payload["mode"] == "NORMAL", \
        "slowing the creature must not disarm its Opportunity Attack"


def test_speed_penalty_ends_when_the_creatures_next_turn_starts(tmp_path, monkeypatch):
    """Printed: "until the start of its next turn" -- the -10 is gone once the creature's own next turn begins."""
    _, table, mid, speed_before = _turn_the_foot(tmp_path, monkeypatch, SLOW)
    to_turn(table, mid, ME)
    to_turn(table, mid, FOE)
    assert reload(tmp_path, mid)._effective_speed(reload(tmp_path, mid).state.actors[FOE]) == speed_before


def test_prone_choice_knocks_the_creature_prone_after_it_moved_ten_feet(tmp_path, monkeypatch):
    """Printed: "falls Prone if it moved at least 10 feet immediately before triggering Flowing Response"."""
    _, _, mid, _ = _turn_the_foot(tmp_path, monkeypatch, PRONE, squares=2)
    held = conditions(tmp_path, mid, FOE)
    assert "condition:typed.prone" in held
    assert OA_CONDITION not in held, "the Prone choice is Prone, not the Opportunity-Attack penalty"


def test_prone_choice_does_not_knock_the_creature_prone_after_only_five_feet(tmp_path, monkeypatch):
    """Printed: Prone only "if it moved at least 10 feet". One 5-ft square is under that, so the Prone branch must not apply."""
    _, _, mid, _ = _turn_the_foot(tmp_path, monkeypatch, PRONE, squares=1)
    assert "condition:typed.prone" not in conditions(tmp_path, mid, FOE), "5 feet is not 10 feet of movement"
