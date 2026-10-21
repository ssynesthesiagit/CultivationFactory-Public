"""Hunger-Refining Breath's failed save leaves Disadvantage on the target's next saving throw.

Printed (TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH): "Failed Save: ... suffer Disadvantage on the next saving
throw made before the end of your next turn." The typed row carries that as a ``disadvantage`` effect whose "on" names
no ability, condition or scope, so combat/typed_executor._names_a_save used to send it to a GM line: no mode ever
reached the target's next save. The generic "next saving throw" is the all-ability form of the existing
condition:typed.save_against grant (combat/ext/save_against.py), so it is applied as one and used up by that save.
"""
from __future__ import annotations

from combat import typed_executor as te
from tests.cw2_service_support import add_action
from tests.h48_table_support import FOE, candidate, fixture

BREATH = "TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH"
SAVE_AGAINST = "condition:typed.save_against"


def _next_save_probe(bundles):
    """A free, scenario-only action that makes its target roll one Constitution save."""
    add_action(bundles[0], "Probe Save", [{"type": "save", "ability": "con", "dc": 16, "applies_to": "target",
                                           "on_fail": [], "on_success": []}])


def test_failed_breath_save_gives_disadvantage_on_the_targets_next_save(tmp_path):
    combat, table, match_id, _send, commit = fixture(
        tmp_path, [BREATH], seed="MAINREDMISC9-BREATH", bundle_transform=_next_save_probe)

    # The fixture's save DC is 50, so the sparring foe's Constitution save fails whatever the dice.
    commit(candidate(table, match_id, "Hunger-Refining Breath"))
    foe = combat._load_session(match_id).engine.state.actors[FOE]
    grants = [c for c in foe.conditions.values() if c.condition_id == SAVE_AGAINST]
    assert len(grants) == 1, [(c.condition_id, c.data) for c in foe.conditions.values()]
    rule = grants[0].data["rule"]["save_against"]
    # Every save: the printed text names no ability, condition or scope.
    assert rule["mode"] == "DISADVANTAGE" and rule["next"] is True
    assert sorted(rule["abilities"]) == ["CHA", "CON", "DEX", "INT", "STR", "WIS"]
    assert rule["against"] == []

    commit(candidate(table, match_id, "Probe Save", target=FOE))
    engine = combat._load_session(match_id).engine
    save = [e for e in engine.events if e.event_type == "SAVE_ROLLED"
            and ".probe_save:" in e.payload.get("reason", "")][-1]
    assert save.payload["mode"] == "DISADVANTAGE", save.payload
    assert len(save.payload["dice"]) == 2, save.payload  # two d20s, the worse one kept
    assert not [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == SAVE_AGAINST]


def test_only_an_unscoped_next_saving_throw_is_generic():
    """The generic grant must not swallow scoped wording (each stays with its own reader or the GM)."""
    assert te._generic_next_save("the next saving throw made before the end of your next turn")
    assert te._generic_next_save("its next saving throw before the start of its next turn")
    assert not te._generic_next_save("the next saving throw against Poisoned")
    assert not te._generic_next_save("the next Charisma saving throw")
    assert not te._generic_next_save("its next Concentration saving throw")
    assert not te._generic_next_save("the next check or saving throw it makes to teleport, possess, or spiritually travel")
    assert not te._generic_next_save("this saving throw")
