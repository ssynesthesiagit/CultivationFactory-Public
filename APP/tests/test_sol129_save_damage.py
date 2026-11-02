"""Save classification includes recipient-turn damage, but not unrelated triggers."""

import pytest

from combat.ext.save_damage import has_damage


@pytest.mark.parametrize('packet', [
    {'dice': {'count': 2, 'sides': 8}, 'damage_types': ['fire', 'necrotic', 'psychic']},
    {'flat': 3, 'damage_types': ['fire']},
])
@pytest.mark.parametrize('outcome', ['on_fail', 'on_success'])
def test_periodic_damage_packets_make_a_save_damaging(packet, outcome):
    assert has_damage([{'type': 'save', outcome: [
        {'type': 'periodic_damage_state', 'damage': [packet]}]}])


def test_inline_periodic_dice_make_a_save_damaging():
    assert has_damage([{'type': 'periodic_damage_state', 'dice': {'count': 1, 'sides': 6}}])


@pytest.mark.parametrize('row', [
    {'type': 'periodic_damage_state', 'damage': []},
    {'type': 'periodic_damage_state', 'damage': [{'flat': 0}]},
    {'type': 'condition', 'damage': [{'dice': {'count': 1, 'sides': 6}}]},
    {'type': 'retaliation', 'on_damaged': [
        {'type': 'periodic_damage_state', 'damage': [{'flat': 3}]}]},
])
def test_empty_or_contingent_damage_does_not_make_a_save_damaging(row):
    assert not has_damage([{'type': 'save', 'on_fail': [row]}])
