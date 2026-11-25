"""Custom-effect strikes retain attack planning without treating priced utility as damage.

Use synthetic characters and public authority only: no private rider/history harness.
"""
from combat.ai_tactics import owned_profile
from combat.ext import ancestral_channeler, compass_breaking_hand
from tests.h1_support import ME, duel


def test_procession_is_a_ranged_strike_not_a_priced_utility():
    engine = duel([compass_breaking_hand.FOOTWORK, compass_breaking_hand.HEAVEN],
                  primary="Resonance", cl=18)
    actions = owned_profile(engine, engine.state.actors[ME])["actions"]
    procession = next(row for aid, row in actions.items() if aid.endswith(".compass_procession"))
    assert procession["damage"] > 0
    assert procession["attack"] is True
    assert procession["range"] == 60
    pole = next(row for aid, row in actions.items() if aid.endswith(".compass_pole"))
    assert pole["attack"] is False


def test_legion_ancestral_strike_is_a_declared_strike_and_advise_is_not():
    engine = duel([ancestral_channeler.LEGION], primary="Resonance", cl=18)
    actions = owned_profile(engine, engine.state.actors[ME])["actions"]
    # Both payment options keep the same classification.
    for payment in ("bonus_action", "favor"):
        strike = next(row for aid, row in actions.items()
                      if aid.endswith(".legion.ancestral_strike." + payment))
        advise = next(row for aid, row in actions.items()
                      if aid.endswith(".legion.advise." + payment))
        assert strike["attack"] is True
        assert strike["damage"] > 0
        assert strike["range"] == 30
        assert advise["attack"] is False
