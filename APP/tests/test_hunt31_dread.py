"""A successful save protects only against that owner's Dread Appetite."""
import pytest
from tests.hunt31_support import OWNER, ALLY, FOE, fixture, pick, reload, send, owner_turn, act

DREAD = 'TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE'


@pytest.mark.parametrize('auto', [False, True])
def test_dread_success_survives_commit_reload(monkeypatch, tmp_path, auto):
    combat, table, mid = fixture(monkeypatch, tmp_path, [DREAD], dc=1, ally_talents=[DREAD])
    cid = pick(table, mid, 'Dread Appetite: Frighten', FOE)
    assert send(combat, table, mid, cid, auto)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED']
    assert saves and saves[-1].payload['total'] >= 1
    assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    while table.state(mid)['menu']['actor_id'] != ALLY:
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    assert pick(table, mid, 'Dread Appetite: Frighten', FOE)  # another caster remains eligible
    owner_turn(table, mid)
    assert not any(FOE in o['target_ids'] for g in table.state(mid)['menu']['actions']
                   if 'Dread Appetite' in g['label'] for o in g['options'])
    assert reload(combat, mid).state.actors[FOE].active
