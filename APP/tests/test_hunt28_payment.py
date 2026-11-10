import pytest

from tests.hunt28_support import ALLY, OWNER, fixture, options, owner_turn, reload, send


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('legacy', [False, True])
def test_invisible_every_application_pays_before_commit(tmp_path, auto, legacy):
    cp = 1 if auto else 2  # AI already declines refreshing an active glamer.
    combat, table, mid = fixture(tmp_path, ['TAL_ILLUSION_OBSCURING_GLAMER'], cp=cp, legacy_payment=legacy)
    for remaining in reversed(range(cp)):
        cid = next(o['candidate_id'] for o in options(table, mid, 'Obscuring Glamer: Invisible (1 CP)')
                   if o['target_ids'] == [ALLY])
        result = send(combat, table, mid, cid, auto)
        assert result['status'] == 'COMMITTED'
        engine = reload(combat, mid)
        assert engine.state.actors[OWNER].resources['resource:core.qi'] == remaining
        assert any(c.condition_id.endswith('.invisible') for c in engine.state.actors[ALLY].conditions.values())
        spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER]
        assert len(spends) == cp - remaining
        owner_turn(table, mid, next_turn=True)
    assert not options(table, mid, 'Obscuring Glamer: Invisible (1 CP)')
    assert options(table, mid, 'Obscuring Glamer: Blurred')
