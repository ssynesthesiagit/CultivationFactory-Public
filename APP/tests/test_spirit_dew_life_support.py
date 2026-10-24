"""Retained HP/temp-HP generation uses real compiled Life sources."""
import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_a2_foundations3 import add_action, pool
from tests.test_spirit_dew_reduction import OWNER_ROW
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn


@pytest.mark.parametrize('name,event_type', [
    ('Mend the Pulse', 'HEALING_APPLIED'),
    ('Borrowed Breath + Greater Invigorate', 'TEMP_HP_GRANTED')])
def test_compiled_positive_life_support_generates_for_actual_provider(tmp_path, name, event_type):
    doc = sheet([OWNER_ROW, 'LIFE_BASE_MEND_THE_PULSE', 'tianxia.talent.life.greater_invigorate'],
                foundation={'foundation_id': 'origin_spirit_body_v0_2B', 'stage': 'Awakened',
                            'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                                         'maximum': 1, 'current': 0}})
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})

    def delivery(bundles):
        add_action(bundles[2], 'Injure patient', [
            {'type': 'damage', 'flat': 10, 'damage_types': ['force'], 'applies_to': 'target'}])

    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, bundle_transform=delivery,
                                seed='DEW-LIFE-SUPPORT')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Injure patient', target=ALLY).candidate_id)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    cid = candidate(combat, mid, name, target=ALLY).candidate_id
    for _ in range(2):
        table.state(mid)
        assert candidate(combat, mid, name, target=ALLY).candidate_id == cid
        assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('spirit')] == 0
    settle(table, mid, cid)
    engine = reload(tmp_path, mid)
    receipt = next(e for e in reversed(engine.events) if e.event_type == event_type
                   and e.actor_id == OWNER and ALLY in e.target_ids)
    assert receipt.payload['after'] > receipt.payload['before']
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 1
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 1
