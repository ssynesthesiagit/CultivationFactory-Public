"""Refraction's supported owner declaration -> native payment -> cold replay.

These table fixtures isolate the state; they do not certify authenticated
Foundation progression. No live models, private campaign inputs or GUI.
"""
import hashlib
import json
from pathlib import Path

import pytest

from combat.ext.glass_heart_refraction import SOURCE
from combat.ext.foundation_combat import held, pool
from combat.tabletop_service import TabletopError
from combat.target_knowledge import recent_events
from tests.test_a2_foundations_two import table_fixture, use
from tests.glass_refraction_support import declare, available
from tests.worker2_support import OWNER, ALLY, FOE, reload, turn


@pytest.mark.parametrize('scene,qualifies', [
    ('Major combat', True), ('Emotionally decisive scene', True), ('Neither', False)])
def test_private_scene_intent_and_native_paid_state(tmp_path, scene, qualifies):
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    before = reload(tmp_path, mid).state.actors[OWNER]
    declare(combat, table, mid, scene)
    engine = reload(tmp_path, mid)
    assert bool(available(engine)) == qualifies
    assert held(engine.state.actors[OWNER], 'glass_refraction') is None
    assert not any(e['source_definition_id'] == 'system:combat.table_fact'
                   for e in recent_events(engine, engine.state.actors[FOE], engine.events))
    assert not any('tribunal' in str(e) for e in table.events(mid, 0)['events'])
    if not qualifies:
        assert engine.state.actors[OWNER].resources == before.resources
        return
    assert available(engine)[0].kind.value == 'BONUS_ACTION'
    use(combat, table, mid, 'Perfected — Glass Heart Refraction')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources['resource:core.qi'] == before.resources['resource:core.qi'] - 2
    assert owner.resources[pool('glass')] == 0
    assert owner.resource_maximums[pool('glass')] == 1
    assert held(owner, 'glass_refraction')
    assert not held(engine.state.actors[ALLY], 'glass_refraction')
    assert not available(engine)
    for _ in range(9):
        turn(table, mid, FOE); turn(table, mid, OWNER)
    assert held(reload(tmp_path, mid).state.actors[OWNER], 'glass_refraction')
    turn(table, mid, FOE); turn(table, mid, OWNER)
    assert not held(reload(tmp_path, mid).state.actors[OWNER], 'glass_refraction')
    declare(combat, table, mid)
    assert not available(reload(tmp_path, mid))  # Fresh scene cannot bypass once/rest.


def test_character_may_decline_by_not_choosing_the_offered_state(tmp_path):
    """The bearer's own decision: a declared qualifying scene only offers the
    state. Nothing is spent unless that character chooses it from their menu."""
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    before = reload(tmp_path, mid).state.actors[OWNER]
    declare(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert available(engine)  # offered to the bearer
    assert held(engine.state.actors[OWNER], 'glass_refraction') is None
    assert engine.state.actors[OWNER].resources == before.resources  # declined = untouched
    assert engine.state.actors[OWNER].bonus_action_available


def test_declaration_correction_staleness_and_other_turn(tmp_path):
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    turn(table, mid, FOE)
    declare(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert not available(engine)  # No Bonus Action on the foe's turn.
    declare(combat, table, mid, scene='Neither')
    turn(table, mid, OWNER)
    assert not available(reload(tmp_path, mid))
    with pytest.raises(TabletopError) as stale:
        table.record_source_input(mid, SOURCE, OWNER,
            {'scene': 'Major combat', 'reason': 'Actual scene'}, -1)
    assert stale.value.code == 'TABLETOP_STALE'
    with pytest.raises(TabletopError):
        declare(combat, table, mid, actor_id=ALLY)


def test_insufficient_cp_cannot_pay_state(tmp_path):
    from combat.canonical import canonical_sha256
    def poor(bundles):
        for r in bundles[0]['actor_template']['resources']:
            if r['resource_id'] == 'resource:core.qi':
                r['initial'] = 1
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0, transform=poor)
    declare(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert not available(engine)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 1
    assert not held(engine.state.actors[OWNER], 'glass_refraction')
