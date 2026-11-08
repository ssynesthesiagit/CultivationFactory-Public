"""Armor Knows Its Owner: an unused one-save Advantage ends at the start of the smith's next turn.

Printed: "Advantage on the next Strength or Dexterity saving throw ... before the start of your next turn."
The save option is sealed without a condition; its expiry must come from the rules table's own name
(START_OF_SOURCE_NEXT_TURN) so the turn sweep removes it when the smith's next turn starts, unused or not.
"""
from combat.ext.blacksmith_forge import held_condition
from tests.test_a2_blacksmith import SAVE_ADVANTAGE, SAVE_ID, armor_knows_game, press
from tests.worker2_support import FOE, OWNER, reload, turn


def test_unused_save_advantage_survives_the_foe_turn_and_ends_at_the_smiths_next_turn(tmp_path):
    combat, table, mid = armor_knows_game(tmp_path)
    press(combat, table, mid, "Extra mark")
    press(combat, table, mid, SAVE_ADVANTAGE)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert held_condition(actor, SAVE_ID).expires_on == "START_OF_SOURCE_NEXT_TURN"

    turn(table, mid, FOE)  # the save is not used; it still waits for the smith's next turn
    assert held_condition(reload(tmp_path, mid).state.actors[OWNER], SAVE_ID) is not None

    turn(table, mid, OWNER)  # the smith's next turn starts: the unused Advantage is gone
    assert held_condition(reload(tmp_path, mid).state.actors[OWNER], SAVE_ID) is None

    turn(table, mid, FOE)
    press(combat, table, mid, "Strength save", OWNER)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == OWNER]
    assert saves and saves[-1].payload["mode"] == "NORMAL"
