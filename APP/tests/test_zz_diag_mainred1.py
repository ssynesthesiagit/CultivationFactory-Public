from tests.test_a2_hunger_second_pass import table_fixture, DRAGON, BASE
from tests.hunt31_support import OWNER
from tests.test_a2_hunger import play
from tests.hunt31_support import owner_turn


def test_diag(monkeypatch, tmp_path):
    combat, table, mid = table_fixture(monkeypatch, tmp_path, [BASE, DRAGON])
    menu = table.state(mid)['menu']
    labels = [(g['label'], [o['label'] for o in g['options']]) for g in menu['actions']]
    raise AssertionError(repr(labels))
