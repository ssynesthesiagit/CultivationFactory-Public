"""Printed clause: Glass Heart Refraction's paid state costs 2 CP and Reflection
cannot pay for the event that created it (rules_text.json, Perfected -
Glass Heart Refraction; owner scene form description).

Synthetic table fixture only: no live models, private inputs or GUI.
"""
from combat.ext.foundation_combat import held, pool
from tests.test_a2_foundations_two import table_fixture, use
from tests.glass_refraction_support import available, declare
from tests.worker2_support import OWNER, reload


def test_reflection_cannot_pay_for_refraction_in_the_scene_that_created_it(tmp_path):
    # The bearer already holds Glass Reflection (max 1) when the scene is declared.
    combat, table, mid = table_fixture(tmp_path, 'glass', current=1, stage='Perfected')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[pool('glass')] == 1
    qi_before = owner.resources['resource:core.qi']

    declare(combat, table, mid, 'Major combat')
    assert available(reload(tmp_path, mid))  # offered, and priced in CP only

    use(combat, table, mid, 'Perfected — Glass Heart Refraction')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    # Paid with 2 CP; the Reflection was not spent and is still available.
    assert owner.resources['resource:core.qi'] == qi_before - 2
    assert owner.resources[pool('glass')] == 1
    assert held(owner, 'glass_refraction')
