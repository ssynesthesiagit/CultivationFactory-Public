"""Merit pays a caster-owned Grace Imprint at the persisted table boundary."""
import pytest
from combat.typed_executor import bears_mark
from tests.hunt28_support import OWNER, ALLY, FOE, act, fixture, options, reload, send

MERIT = 'tianxia.talent.karma.merit_becomes_armor'


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('mark_owner', [None, OWNER, ALLY])
def test_merit_requires_and_consumes_own_grace(tmp_path, auto, mark_owner):
    combat, table, mid = fixture(tmp_path, [MERIT],
        setup_mark=(mark_owner, 'Grace Imprint') if mark_owner else None)
    if mark_owner:
        while table.state(mid)['menu']['actor_id'] != mark_owner:
            act(table, mid, table.state(mid)['menu']['end_turn'])
        mark = next(o['candidate_id'] for o in options(table, mid, 'Prepare prerequisite mark') if o['target_ids'] == [ALLY])
        assert act(table, mid, mark)['status'] == 'COMMITTED'
        while table.state(mid)['menu']['actor_id'] != OWNER:
            act(table, mid, table.state(mid)['menu']['end_turn'])
    candidates = [o for o in options(table, mid, 'Merit Becomes Armor') if o['target_ids'] == [ALLY]]
    assert bool(candidates) == (mark_owner == OWNER)
    if candidates:
        before = reload(combat, mid).state.actors[OWNER].resources['resource:core.qi']
        assert send(combat, table, mid, candidates[0]['candidate_id'], auto)['status'] == 'COMMITTED'
        engine = reload(combat, mid)
        assert not bears_mark(engine.state.actors[ALLY], OWNER, 'Grace Imprint')
        assert engine.state.actors[OWNER].resources['resource:core.qi'] == before - 3
        assert any(m.target_field == 'armor_class' and m.value == 1 for m in engine.state.actors[ALLY].modifiers.values())
