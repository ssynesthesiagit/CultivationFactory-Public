"""Incarnation of the Patient Mountain pays Temporary HP only when a Burden Mark is spent (review MGR-T14-sol-base-burden-marks-1F11R).

Printed: "when you spend a Burden Mark, gain Temporary HP equal to your Proficiency Bonus." A free Earth Domain
response (Settle the Impact without a mark) spends no mark, so it grants nothing.
"""
from combat.ext import earth_responses as earth
from tests.test_riders_lane9 import ME, THEM, _burden, _earth_fight

MOUNTAIN = "INCARNATION_OF_THE_PATIENT_MOUNTAIN"


def _grants(engine):
    return [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and ME in e.target_ids
            and e.source_definition_id == earth.T + 'INCARNATION_OF_THE_PATIENT_MOUNTAIN']


def test_free_settle_the_impact_grants_no_incarnation_temp_hp():
    engine = _earth_fight([MOUNTAIN])
    caster, target = engine.state.actors[ME], engine.state.actors[THEM]
    engine._apply_condition(caster, earth.INCARNATION, "test", ME, expires_on="UNTIL_REMOVED")
    assert earth._offer(engine, caster, target, "settle", "Settle the Impact", free=True)
    assert _grants(engine) == []
    assert caster.turn_flags.get("earth_spent_round") is None


def test_paid_settle_the_impact_grants_exactly_one_incarnation_temp_hp():
    engine = _earth_fight([MOUNTAIN])
    caster, target = engine.state.actors[ME], engine.state.actors[THEM]
    engine._apply_condition(caster, earth.INCARNATION, "test", ME, expires_on="UNTIL_REMOVED")
    _burden(engine)
    assert earth._offer(engine, caster, target, "settle", "Settle the Impact")
    grants = _grants(engine)
    assert len(grants) == 1
    assert grants[0].payload['offered'] == int(earth._row(engine, caster).get('pb', 2))


def test_passive_forced_distance_has_a_name_distinct_from_the_interception_helper():
    # Review F11R optional item: two functions were both named forced_distance. The passive hook is now
    # passive_forced_distance_reduction; the interception helper keeps its name and is not a hook.
    from combat.ext import passive_traits
    from combat import technique_interception

    assert not hasattr(passive_traits, 'forced_distance')
    assert callable(passive_traits.passive_forced_distance_reduction)
    assert callable(technique_interception.forced_distance)
