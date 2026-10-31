"""Feast never downgrades an Immunity that was not selected or lacks source authority."""
import pytest

from combat import typed_reactions
from tests.test_riders_c7 import FOE, ME, _essence, _maw, script, unarmed, use


@pytest.mark.parametrize("devour", [False, True])
def test_failed_feast_with_unknown_immunity_source_does_not_downgrade_it(devour):
    ids = ["feast_upon_protection", "devour_heaven_and_earth"] if devour else ["feast_upon_protection"]
    engine, me, foe = _maw(ids, picks={"maw_types": ["spend"], "feast_protection": None})
    if devour:
        use(engine, "Devour Heaven and Earth")
    engine._add_modifier(foe, "test", "damage_immunity", "SET", "FIRE", "PERMANENT", expires_on="UNTIL_REMOVED")
    _essence(engine, me, "FIRE", "FIRE", "FIRE")
    script(engine, [18, *([1] * 80)])
    me.action_available = True
    start = len(engine.events)
    use(engine, unarmed(engine), target=FOE)
    fire = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED"
            and (e.payload or {}).get("damage_type") == "FIRE"]
    assert not any(int((e.payload or {}).get("hp_damage") or 0) for e in fire)
    assert not typed_reactions.damage_bonus_eligible(engine, foe, "FIRE", "x", ME)
    assert not any(c.condition_id == "condition:typed.maw_immunity_as_resistance" for c in foe.conditions.values())
