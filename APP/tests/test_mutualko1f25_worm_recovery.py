"""MUTUALKO1F25 regression (review F24R item 1): a lone dying Worm Demon Body host with 0 Brood.

Owner ruling (2026-10-21): a side is defeated only when every creature on it is down with no typed
in-combat self-revival. Worm Demon Body's next-turn Brood gain (start of its turn, 1 Brood, then
Internal Brood raises it) is such a revival. The host's side is therefore not defeated while the
host is dying with 0 Brood: the fight continues until its own turn, where the Brood arrives and the
revival is available.
"""
from __future__ import annotations

import pytest

from combat.victory import recovers_alone
from tests.test_riders_c7 import BROOD, FOE, ME, _foe_save, _parasite, end_turns_until, use

WORM_NAME = "Ten-Thousand Worm Demon Body"


def test_lone_dying_worm_host_with_no_brood_keeps_the_fight_going_until_its_turn():
    engine, me, foe = _parasite(["internal_brood", "ten_thousand_worm_demon_body"], picks={"internal_brood": ["heal"]})
    if WORM_NAME not in {a.display_name for a in engine.action_catalog.values() if a.owner_id == ME}:
        # The scrambled public mirror binds no printed feature name, so the transformation cannot be chosen by name there.
        # This test is private-tree only (see the report's 'Stays private' section).
        pytest.skip("scrambled public mirror: printed Worm Demon Body name not bound")
    engine._gain_resource(me, BROOD, 6, "test")
    use(engine, WORM_NAME)
    engine._spend_resource(me, BROOD, me.resources[BROOD], "test")  # the host holds 0 Brood now
    assert me.resources.get(BROOD, 0) == 0

    end_turns_until(engine, FOE)
    me.current_hp = 1
    _foe_save(engine, foe, me, "con", 30)
    assert me.current_hp == 0 and me.life_state == "DYING"
    # The only creature on its side is dying, but the foe can still act: the fight goes on.
    assert engine.state.terminal_result is None
    assert recovers_alone(engine, me) is True

    end_turns_until(engine, ME)  # + 1 Brood at the start of its turn, then Internal Brood raises it
    assert engine.state.terminal_result is None
    assert me.current_hp > 0 and me.resources[BROOD] == 0
    assert not any(c.condition_id.endswith(".ten_thousand_worm_demon_body") for c in me.conditions.values())
    assert recovers_alone(engine, me) is False  # the one revival is spent; nothing else keeps it up
