"""Character of Binding hooks stay inert for every actor that does not carry its own Binding or lock state.

Regression for the non-owner note: a bystander, an ally or a foe with unrelated conditions gets no
restraint, speed change, teleport block or possession/incorporeal refusal from the Calligraphy hooks.
"""
from types import SimpleNamespace as NS

from combat.ext.qi_subpaths_four import (
    binding_action, binding_condition, calligraphy_condition_gate, calligraphy_speed,
    calligraphy_willing_teleport)

OTHER = 'condition:typed.some_other_feature'


def actor(*conditions):
    return NS(entity_id='bystander', conditions={i: c for i, c in enumerate(conditions)})


def cond(condition_id, data=None):
    return NS(condition_id=condition_id, data=data or {}, source_definition_id='x', source_actor_id='y', instance_id=condition_id)


def test_unrelated_conditions_grant_no_calligraphy_restriction():
    loose = actor(cond(OTHER, {'rule': {'no_incorporeal': 1, 'no_possession': 1, 'no_willing_teleport': 1, 'speed_ft': -10}}))
    assert calligraphy_condition_gate(None, loose, {'condition': 'incorporeal'}) is None
    assert calligraphy_condition_gate(None, loose, {'condition': 'possessing'}) is None
    assert calligraphy_speed(None, loose) is None
    assert calligraphy_willing_teleport(None, loose, None, None, 'WILLING') is None


def test_empty_actor_is_untouched_by_every_calligraphy_hook():
    empty = actor()
    assert calligraphy_condition_gate(None, empty, {'condition': 'incorporeal'}) is None
    assert calligraphy_speed(None, empty) is None
    assert calligraphy_willing_teleport(None, empty, None, None, 'WILLING') is None
    assert binding_condition(NS(numbers={'save_dc': 10}), empty, {}) is None


def test_lock_only_limits_its_holder_and_only_willing_moves():
    locked = actor(cond('condition:typed.qi_calligraphy_lock', {'rule': {'no_willing_teleport': 1, 'speed_ft': -10}}))
    assert calligraphy_willing_teleport(None, locked, None, None, 'FORCED') is None
    assert calligraphy_willing_teleport(None, locked, None, None, 'WILLING') is False
    assert calligraphy_speed(None, locked) == -10
    assert calligraphy_condition_gate(None, locked, {'condition': 'incorporeal'}) is None


def test_binding_action_rewrite_ignores_other_sources():
    other = NS(parameters={'typed': {'source': 'tianxia.subpath.qi.dust_cultivator.feature.choking_dust'}})
    assert binding_action(other, {}) is None
    assert binding_action(NS(parameters={}), {}) is None
