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


@pytest.mark.parametrize('cl,recipient,landing', [(6, OWNER, 'cell:2:6:0'), (11, ALLY, 'cell:4:8:0')])
def test_predictive_step_moves_before_reach_check_without_a_second_roll(tmp_path, cl, recipient, landing):
    combat, table, mid = fixture(tmp_path, [STEP], cl=cl, named=True,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    turn(table, mid, FOE)
    start = reload(tmp_path, mid)
    sequence = start.state.event_sequence
    before_hp = start.state.actors[recipient].current_hp
    before_budget = start.state.actors[recipient].movement_remaining_ft
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=recipient).candidate_id,
        picks={'choice:needle.predictive_step': 'protect', 'choice:needle.recipient_consent': 'accept',
               'choice:needle.predictive_step_landing': landing})
    engine = reload(tmp_path, mid)
    events = [e for e in engine.events if e.sequence > sequence]
    assert engine.state.actors[recipient].current_hp == before_hp
    assert engine.state.actors[recipient].movement_remaining_ft == before_budget
    assert len([e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE]) == 1
    assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == recipient for e in events)
    assert not [e for e in events if e.event_type == 'REACTION_RESOLVED' and 'opportunity' in e.source_definition_id]
    assert not [e for e in events if e.event_type == 'DAMAGE_APPLIED']


def test_warn_another_declined_consent_spends_nothing(tmp_path):
    combat, table, mid = fixture(tmp_path, [STEP], cl=11,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    turn(table, mid, FOE)
    start = reload(tmp_path, mid).state.actors[OWNER]
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=ALLY).candidate_id,
        picks={'choice:needle.predictive_step': 'protect', 'choice:needle.recipient_consent': None})
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources == start.resources
    assert owner.reaction_available


@pytest.mark.parametrize('cl', [6, 10])
def test_warn_another_requires_cl11(tmp_path, cl):
    combat, table, mid = fixture(tmp_path, [STEP], cl=cl,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=ALLY).candidate_id)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.predictive_step' for p in prompts)
    assert not [e for e in reload(tmp_path, mid).events if e.source_definition_id == STEP and e.event_type == 'REACTION_RESOLVED']
