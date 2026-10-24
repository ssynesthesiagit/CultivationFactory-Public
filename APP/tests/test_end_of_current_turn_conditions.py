"""A condition that lasts "until the end of the current turn" ends when that turn ends, whoever applied it.

Modifiers already did (gate2_engine._expire_for_checkpoint); conditions only ended on the holder's or the applier's
own turn, so a Resistance granted by a reaction on someone else's turn (Glass Flaw, GLASSR8) outlived the turn.
"""
from combat.ext import glass_faults

from tests.test_shield_possession_and_armor import ME, AN, _fight


def test_a_reaction_granted_condition_ends_with_the_current_turn():
    engine = _fight()
    ally = engine.state.actors[AN]
    assert engine.state.current_actor_id == ME
    engine._apply_condition(ally, glass_faults.RESIST_EFFECT, "test:flaw", AN, expires_on="END_OF_CURRENT_TURN",
                            data={"label": "Flaw: Resistance to Fire damage until the end of this turn",
                                  "rule": {"damage_resistances": ["FIRE"]}})
    assert any(c.condition_id == glass_faults.RESIST_EFFECT for c in ally.conditions.values())

    engine._expire_for_checkpoint("END_OF_TURN", ME)

    assert not any(c.condition_id == glass_faults.RESIST_EFFECT for c in ally.conditions.values())
