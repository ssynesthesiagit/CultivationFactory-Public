"""Free sight setup stays reachable through the persisted table menu."""
from tests.test_a11_sight_guards import prepared_table, prepare
from tests.hunt28_support import FOE, OWNER, options


def test_free_setup_is_offered_and_commits(tmp_path, monkeypatch):
    combat, table, mid = prepared_table(tmp_path, monkeypatch)
    while table.state(mid)['menu']['actor_id'] != OWNER:
        from tests.hunt28_support import act
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    assert any(option['target_ids'] == [FOE] for option in options(table, mid, 'Prepare unseen marked target'))
    prepare(combat, table, mid)
