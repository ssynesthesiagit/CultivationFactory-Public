"""Configured Shield-Hacking payments retain the triggering one-attack defence."""
import pytest

from tests.test_mgr_t17_shield_hacking_rhythm import (
    _fight, _configure_shield_hacking, _hit_with, _add_defence, _ac_penalty,
    EDGE, CONDITION, ME,
)


@pytest.mark.parametrize("provider", [
    "condition:typed.vessel_guarded",
    "condition:typed.verdant_shelter_cover",
])
def test_configured_hit_keeps_consumed_trigger(provider):
    engine, me, foe = _fight(shield=False)
    engine._apply_condition(foe, provider, "system:test.provider", ME,
                            expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "Temporary defence"})
    _configure_shield_hacking(engine)
    _hit_with(engine, "Forward Cut")
    assert me.resources[EDGE] == 0
    assert any(c.condition_id == CONDITION for c in foe.conditions.values())
    assert not any(c.condition_id == provider for c in foe.conditions.values())
    _add_defence(engine, foe, 2)
    assert _ac_penalty(engine, foe) == -2
    _hit_with(engine, "Forward Cut")
    assert not any(c.condition_id == CONDITION for c in foe.conditions.values())
    assert _ac_penalty(engine, foe) == 0
