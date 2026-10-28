"""Heaven-Devouring Maw: while Devour Heaven and Earth is active, a failed Feast upon Protection save softens the target's Immunity."""
from combat import typed_reactions
from tests.test_riders_c7 import FOE, ME, _essence, _maw, end_turns_until, script, unarmed, use

SOFTENED = "condition:typed.immunity_softened"



def _feast(devour, kind="FIRE"):
    ids = ["feast_upon_protection", "devour_heaven_and_earth"] if devour else ["feast_upon_protection"]
    engine, me, foe = _maw(ids, picks={"maw_types": ["spend"], "feast_protection": None})
    if devour:
        use(engine, "Devour Heaven and Earth")
    engine._add_modifier(foe, "test", "damage_immunity", "SET", "FIRE", "PERMANENT", expires_on="UNTIL_REMOVED")
    _essence(engine, me, kind, kind, kind)  # Feast upon Protection spends 3 Essence and deals its damage type (FIRE: the foe's Immunity)
    return engine, me, foe


def _fire_damage_landed(engine):
    # A committed FIRE packet that took Hit Points from the foe (the Feast damage, which Immunity would otherwise zero).
    return [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and (e.payload or {}).get("damage_type") == "FIRE"
            and int((e.payload or {}).get("hp_damage") or 0) > 0]


def _immune(engine, foe):
    return not typed_reactions.damage_bonus_eligible(engine, foe, "FIRE", "x", ME)


def test_failed_save_under_devour_lets_feast_damage_reach_the_immune_foe():
    # Regression (SYS2 review finding 2): the old assertions only checked the condition. The Feast packet's FIRE damage must
    # actually reach the FIRE-immune foe (as Resistance, so it is halved, not zeroed). With the immunity_as_resistance hook
    # removed, no FIRE damage is committed and this fails.
    engine, me, foe = _feast(True)
    script(engine, [18, *([1] * 80)])
    me.action_available = True
    use(engine, unarmed(engine), target=FOE)
    assert _fire_damage_landed(engine), "Feast upon Protection FIRE damage did not reduce the immune foe's Hit Points"


def test_failed_save_under_devour_treats_immunity_as_resistance_then_it_ends():
    engine, me, foe = _feast(True)
    assert _immune(engine, foe)
    script(engine, [18, *([1] * 80)])
    me.action_available = True
    use(engine, unarmed(engine), target=FOE)
    assert any(c.condition_id == SOFTENED for c in foe.conditions.values())
    assert _immune(engine, foe)  # the softening covered the Feast packet only; it is closed once that packet resolves
    end_turns_until(engine, ME)
    assert not any(c.condition_id == SOFTENED for c in foe.conditions.values())
    assert _immune(engine, foe)


def test_failed_save_under_devour_does_not_soften_the_owners_other_hits():
    # Regression (SYS2 review finding 1): the softened condition used to be read for every owner hit on the target. The
    # Feast packet closes when its damage resolves, so the defense check an owner's next hit runs (Maw Strike, World-Eating
    # Bite, reactions) must see the Immunity again. Without the packet marker this assertion fails.
    engine, me, foe = _feast(True)
    script(engine, [18, *([1] * 80)])
    me.action_available = True
    use(engine, unarmed(engine), target=FOE)  # the Feast upon Protection save fails here
    assert any(c.condition_id == SOFTENED for c in foe.conditions.values())
    assert _immune(engine, foe)  # after the Feast packet closes, the owner's next hit meets the Immunity as before
    engine.events.clear()
    end_turns_until(engine, ME)
    me.action_available = True
    use(engine, unarmed(engine), target=FOE)  # a second owner hit: no Feast packet, so no FIRE damage is committed
    assert not _fire_damage_landed(engine)


def test_without_devour_the_immunity_stays():
    engine, me, foe = _feast(False)
    script(engine, [18, *([1] * 80)])
    use(engine, unarmed(engine), target=FOE)
    assert not any(c.condition_id == SOFTENED for c in foe.conditions.values())
    assert _immune(engine, foe)
