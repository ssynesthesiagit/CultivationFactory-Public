"""Native committed-action regressions for the eight-row movement lane."""
import pytest

from tests.worker2_support import fixture, turn, settle, candidate, reload, OWNER, ALLY, FOE

STEP = 'tianxia.subpath.qi.divination_cultivator.feature.predictive_step'


@pytest.mark.parametrize('cl,recipient', [(6, OWNER), (11, ALLY)])
def test_predictive_step_is_paid_after_the_visible_roll(tmp_path, cl, recipient):
    combat, table, mid = fixture(tmp_path, [STEP], cl=cl, named=True,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=recipient).candidate_id)
    engine = reload(tmp_path, mid)
    used = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == STEP]
    assert len(used) == 1
    assert used[0].target_ids == (recipient,)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == before - 2
    assert used[0].payload['ac_bonus'] == 3
    assert any('roll' in p.get('prompt', '').lower() or 'roll' in str(p).lower() for p in prompts)


@pytest.mark.parametrize('features,cl', [([], 11), ([STEP], 5)])
def test_predictive_step_is_inert_without_access(tmp_path, features, cl):
    combat, table, mid = fixture(tmp_path, features, cl=cl,
        foe_position={'x': 3, 'y': 5})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert not [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == STEP]
