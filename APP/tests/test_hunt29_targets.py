"""Hunt 29 regressions through persisted manual/AI tables; no browsers or live data."""
import pytest

from tests.hunt28_support import ALLY, FOE, OWNER, act, fixture, options, owner_turn, reload, send


def named(table, mid, prefix):
    return [o for g in table.state(mid)['menu']['actions'] if g['label'].startswith(prefix) for o in g['options']]


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('talent,label', [
    ('TAL_SMOKE_SOOT_MARKED_WITNESS', 'Soot-Marked Witness'),
    ('tianxia.talent.beauty.court_of_one', 'Court of One'),
    ('tianxia.talent.radiance.mercy_of_morning', 'Mercy of Morning'),
])
def test_unpaid_or_unmarked_actions_are_not_offered(tmp_path, auto, talent, label):
    combat, table, mid = fixture(tmp_path, [talent], cp=0 if 'GRAVITY' in talent else 30)
    assert not named(table, mid, label)
    assert send(combat, table, mid, options(table, mid, 'Dodge')[0]['candidate_id'], auto)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert not any(e.event_type == 'RESOURCE_SPENT' for e in engine.events)


def mark_smoke(table, mid, target):
    veil = next(o for o in options(table, mid, 'Smoke Veil') if o.get('destination') == {'x': 4, 'y': 6})
    assert act(table, mid, veil['candidate_id'])['status'] == 'COMMITTED'
    trace = next(o for o in options(table, mid, 'Place Smoke Trace') if o['target_ids'] == [target])
    assert act(table, mid, trace['candidate_id'])['status'] == 'COMMITTED'


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('marker', [OWNER, ALLY])
def test_witness_only_spends_its_targets_caster_owned_trace(tmp_path, auto, marker):
    combat, table, mid = fixture(tmp_path, ['TAL_SMOKE_SOOT_MARKED_WITNESS'],
                                 ally_talents=['TAL_SMOKE_SOOT_MARKED_WITNESS'])
    while table.state(mid)['menu']['actor_id'] != marker:
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    mark_smoke(table, mid, FOE)
    reload(combat, mid)
    if marker != OWNER:
        owner_turn(table, mid)
    choices = options(table, mid, 'Soot-Marked Witness')
    if marker != OWNER:
        assert not choices
        assert send(combat, table, mid, options(table, mid, 'Dodge')[0]['candidate_id'], auto)['status'] == 'COMMITTED'
    else:
        assert {tuple(o['target_ids']) for o in choices} == {(FOE,)}
        assert send(combat, table, mid, choices[0]['candidate_id'], auto)['status'] == 'COMMITTED'
    from combat.typed_executor import bears_mark
    assert bears_mark(reload(combat, mid).state.actors[FOE], marker, 'Smoke Trace') == (marker != OWNER)


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('mark', ['Glow', 'Dawnmark'])
@pytest.mark.parametrize('marker', [OWNER, ALLY])
def test_mercy_requires_either_mark_from_its_own_caster(tmp_path, auto, mark, marker):
    combat, table, mid = fixture(tmp_path, ['tianxia.talent.radiance.mercy_of_morning'], setup_mark=(marker, mark))
    while table.state(mid)['menu']['actor_id'] != marker:
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    cid = next(o['candidate_id'] for o in options(table, mid, 'Prepare prerequisite mark') if o['target_ids'] == [ALLY])
    assert act(table, mid, cid)['status'] == 'COMMITTED'
    reload(combat, mid)
    if marker != OWNER:
        owner_turn(table, mid)
    choices = options(table, mid, 'Mercy of Morning: Advantage vs Charm')
    if marker != OWNER:
        assert not choices
        assert send(combat, table, mid, options(table, mid, 'Dodge')[0]['candidate_id'], auto)['status'] == 'COMMITTED'
    else:
        assert {tuple(o['target_ids']) for o in choices} == {(ALLY,)}
        assert send(combat, table, mid, choices[0]['candidate_id'], auto)['status'] == 'COMMITTED'
        engine = reload(combat, mid)
        assert engine.state.actors[OWNER].resources['resource:core.qi'] == 29
        benefit = next(c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id.endswith('.save_against'))
        assert benefit.data['rule']['save_against']['mode'] == 'ADVANTAGE'
        assert benefit.data['rule']['save_against']['next'] is True


@pytest.mark.parametrize('auto', [False, True])
def test_witness_preserves_marked_ally_targeting(tmp_path, auto):
    combat, table, mid = fixture(tmp_path, ['TAL_SMOKE_SOOT_MARKED_WITNESS'], setup_mark=(OWNER, 'Smoke Trace'))
    cid = next(o['candidate_id'] for o in options(table, mid, 'Prepare prerequisite mark') if o['target_ids'] == [ALLY])
    assert act(table, mid, cid)['status'] == 'COMMITTED'
    reload(combat, mid)
    choices = options(table, mid, 'Soot-Marked Witness')
    assert {tuple(o['target_ids']) for o in choices} == {(ALLY,)}
    assert send(combat, table, mid, choices[0]['candidate_id'], auto)['status'] == 'COMMITTED'
    from combat.typed_executor import bears_mark
    assert not bears_mark(reload(combat, mid).state.actors[ALLY], OWNER, 'Smoke Trace')
