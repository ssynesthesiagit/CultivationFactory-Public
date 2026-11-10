"""A damage-taken bonus is a signed answer to ``incoming_damage``, not a reduction.

``damage_taken_bonus`` (Yang's Overgrown Recovery, riders lane 2: "the first damage
roll against that subject gains a bonus equal to your Proficiency Bonus") answers the
``incoming_damage`` hook with a NEGATIVE number: the points it adds to that roll.
``typed_reactions.defend`` subtracts the summed answer, so a negative answer raises the
packet. Summing the answers and clamping the sum at zero silently ate the bonus and its
consumed grant, so an otherwise undefended 10-point hit dealt 10 instead of 14 with
Proficiency Bonus 4, for an ordinary single-type attack as well as a mixed hit.

These regressions assert the signed sum on the same service seam the engine's damage
commit uses, for one damage type and for a native mixed packet;
tests/test_riders_lane2.py plays the same bonus through a whole table fight.
"""
from combat import typed_reactions
from combat.gate2_runtime_content import AN
from tests.test_auto_body import ME, _bundle, _engine

BONUS = 4  # the fixture's Proficiency Bonus
PENDING = "condition:typed.damage_taken_bonus.pending"


def _engine_with_bonus():
    """A real table actor holding the pending grant the DAMAGE_ROLLED event writes."""
    engine = _engine(_bundle([]), {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}})
    target = engine.state.actors[ME]
    engine._apply_condition(target, PENDING, "test:overgrown_recovery", ME, expires_on="END_OF_CURRENT_TURN",
                            data={"amount": BONUS, "damage_source": None, "damage_actor": None})
    return engine, target


def test_a_negative_incoming_damage_answer_raises_the_packet_instead_of_being_dropped():
    engine, target = _engine_with_bonus()
    assert typed_reactions.defend(engine, target, 10, "PIERCING", None, None) == 10 + BONUS
    assert PENDING not in {c.condition_id for c in target.conditions.values()}, "the grant was spent"


def test_a_native_mixed_packet_keeps_the_signed_bonus_once_in_the_hit():
    engine, target = _engine_with_bonus()
    packet = [(10, "PIERCING"), (20, "BLUDGEONING")]
    assert typed_reactions.defend_components(engine, target, packet, None, None) == 30 + BONUS
