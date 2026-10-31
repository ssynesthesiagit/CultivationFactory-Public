"""Red Lotus Cautery, source branch: the reduction also grows when the damage source is below half its Hit Point maximum.

The owner-side branch is covered by test_cautery_wounded_bonus.py. This file isolates the foe-side condition of
combat.ext.foundations3.cautery_wounded_bonus with pure stand-ins, so only the source's Hit Points decide the result.
"""
from types import SimpleNamespace as NS

from combat.ext import foundations3
from combat.ext.foundations3 import CAUTERY, cautery_wounded_bonus

OWNER_ID, FOE_ID = 'owner', 'foe'


def _call(source_hp, source_max=10, owner_hp=20):
    owner = NS(entity_id=OWNER_ID, maximum_hp=20, proficiency_bonus=2)
    foe = NS(entity_id=FOE_ID, current_hp=source_hp, maximum_hp=source_max)
    engine = NS(state=NS(actors={OWNER_ID: owner, FOE_ID: foe}), typed_passive_rows={})
    packet = NS(target_id=OWNER_ID, hostile=True, source_flags=frozenset(), source_actor_id=FOE_ID,
                hp_before=owner_hp)
    return cautery_wounded_bonus(engine, owner, {'feature_id': CAUTERY}, packet, None)


def test_source_below_half_health_adds_one_proficiency_bonus_with_owner_healthy():
    # Owner at full health (not below half); the foe has 4 of 10, which is below half.
    assert _call(source_hp=4) == {'reduction_bonus': 2}


def test_source_exactly_half_health_does_not_add_the_bonus():
    assert _call(source_hp=5) is None


def test_source_check_is_on_the_source_not_the_owner():
    # Owner below half would trigger on its own; here the owner is healthy and the source is not hurt.
    assert _call(source_hp=10, owner_hp=20) is None


def test_source_check_is_not_taken_for_a_missing_source_actor():
    owner = NS(entity_id=OWNER_ID, maximum_hp=20, proficiency_bonus=2)
    engine = NS(state=NS(actors={OWNER_ID: owner}), typed_passive_rows={})
    packet = NS(target_id=OWNER_ID, hostile=True, source_flags=frozenset(), source_actor_id='gone', hp_before=20)
    assert cautery_wounded_bonus(engine, owner, {'feature_id': CAUTERY}, packet, None) is None
