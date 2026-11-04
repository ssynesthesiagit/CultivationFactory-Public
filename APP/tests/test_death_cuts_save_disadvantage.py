"""Death of a Thousand Cuts: the Grapple/Joint Lock option gives Disadvantage on the target's next Strength or Dexterity save."""
from tests.test_riders_c7 import MANTIS, _grapple, _mantis, payloads, unarmed, use

CUTS = "path_hit." + MANTIS + "death_of_a_thousand_cuts"
OPTION = "Disadvantage against your Grapple or Joint Lock"


def _after_cut(option, *extra):
    engine, me, foe = _mantis(["death_of_a_thousand_cuts", *extra], picks={CUTS: [option]})
    foe.armor_class = -50
    use(engine, unarmed(engine), target=foe.entity_id)
    me.action_available = True
    return engine, me, foe


def test_next_grapple_save_rolls_with_disadvantage():
    engine, me, foe = _after_cut(OPTION)
    assert _grapple(engine, foe.entity_id)
    assert len(payloads(engine.events, "SAVE_ROLLED")[-1]["dice"]) == 2


def test_other_options_leave_the_grapple_save_plain():
    engine, me, foe = _after_cut("Speed 0")
    assert _grapple(engine, foe.entity_id)
    assert len(payloads(engine.events, "SAVE_ROLLED")[-1]["dice"]) == 1


def test_disadvantage_is_spent_on_the_first_save():
    engine, me, foe = _after_cut(OPTION)
    _grapple(engine, foe.entity_id)
    use(engine, "Release grapple")
    me.action_available = True
    assert _grapple(engine, foe.entity_id)
    assert len(payloads(engine.events, "SAVE_ROLLED")[-1]["dice"]) == 1
