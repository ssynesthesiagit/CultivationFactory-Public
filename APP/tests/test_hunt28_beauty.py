import pytest

from tests.hunt28_support import ALLY, FOE, OWNER, act, fixture, options, owner_turn, reload, send


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('talent,label', [('beauty_that_judges', 'Beauty That Judges'),
                                        ('court_of_one', 'Court of One'), ('envious_glance', 'Envious Glance'),
                                        ('fragrant_sleeve_diversion', 'Fragrant Sleeve Diversion'),
                                        ('unbearable_splendor', 'Unbearable Splendor')])
def test_printed_beauty_mark_target_requires_casters_mark(tmp_path, auto, legacy, talent, label):
    combat, table, mid = fixture(tmp_path, ['tianxia.talent.beauty.' + talent], legacy_targets=legacy)
    assert not options(table, mid, label)
    cid = options(table, mid, 'Dodge')[0]['candidate_id']
    assert send(combat, table, mid, cid, auto)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert not any('beauty_mark' in c.condition_id for c in engine.state.actors[FOE].conditions.values())
    assert not any(e.event_type == 'RESOURCE_SPENT' for e in engine.events)


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('marker', [OWNER, ALLY])
def test_judges_only_own_mark_after_table_commit_reload(tmp_path, auto, marker):
    combat, table, mid = fixture(tmp_path, ['tianxia.talent.beauty.beauty_that_judges'],
                                 ally_talents=['BEAUTY_BASE_CATCH_THE_EYE'])
    for _ in range(3):
        if table.state(mid)['menu']['actor_id'] == marker:
            break
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    cid = next(o['candidate_id'] for o in options(table, mid, 'Catch the Eye') if o['target_ids'] == [FOE])
    assert act(table, mid, cid)['status'] == 'COMMITTED'
    reload(combat, mid)
    owner_turn(table, mid, next_turn=True)
    choices = options(table, mid, 'Beauty That Judges')
    if marker == ALLY:
        assert not choices
        return
    cid = next(o['candidate_id'] for o in choices if o['target_ids'] == [FOE])
    assert send(combat, table, mid, cid, auto)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 27
    assert any(c.condition_id.endswith('.charmed') for c in engine.state.actors[FOE].conditions.values())
