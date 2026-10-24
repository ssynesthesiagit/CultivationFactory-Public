"""Still as the Peak contact (RW189 F2R2 review finding 2).

Printed: "if you are touching earth, stone, or worked masonry" -- the refund of 1 Stamina off the next Body Refining cost needs
that contact, not only "has not willingly moved". The footing is authored the way the other surface_contact fixtures author it
(a condition whose rule carries surface_contact), so the check runs through combat/ext/surface_contact.py. Each test spends
Waterfall Stance and compares the Stamina cost with and without the refund.
"""

from combat.ext.yamabushi import still_as_the_peak
from tests.test_riders_c7 import ME, STAMINA, _yama, use

FOOTING = "condition:typed.rw189_footing"


def _footing(engine, material, *, touching=True):
    me = engine.state.actors[ME]
    engine._apply_condition(me, FOOTING, me, me.entity_id, expires_on="UNTIL_REMOVED",
                            data={"rule": {"surface_contact": {"material": material, "stable": True, "touching": touching}},
                                  "label": "RW189 footing"})
    # The turn-start check runs once per round: re-run it now that the footing is authored, from a clean flag.
    me.turn_flags.pop("_round_still_peak", None)
    still_as_the_peak(engine, me)


def _stamina_spent(engine, me):
    before = me.resources[STAMINA]
    use(engine, "Waterfall Stance")
    return before - me.resources[STAMINA]


def test_still_as_the_peak_refunds_one_stamina_while_touching_stone():
    engine, me, _foe = _yama(["ascetic_body", "waterfall_stance"])
    _footing(engine, "stone")
    assert _stamina_spent(engine, me) == 1


def test_still_as_the_peak_refunds_one_stamina_while_touching_masonry():
    engine, me, _foe = _yama(["ascetic_body", "waterfall_stance"])
    _footing(engine, "masonry")
    assert _stamina_spent(engine, me) == 1


def test_still_as_the_peak_does_not_refund_while_touching_wood():
    engine, me, _foe = _yama(["ascetic_body", "waterfall_stance"])
    _footing(engine, "wood")
    assert _stamina_spent(engine, me) == 2


def test_still_as_the_peak_does_not_refund_when_not_touching_the_ground():
    engine, me, _foe = _yama(["ascetic_body", "waterfall_stance"])
    _footing(engine, "stone", touching=False)
    assert _stamina_spent(engine, me) == 2
