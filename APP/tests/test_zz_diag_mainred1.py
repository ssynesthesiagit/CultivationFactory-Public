import tests.test_a2_hunger_second_pass as m
from tests.test_a2_hunger_second_pass import table_fixture, DRAGON, BASE


def test_diag(monkeypatch, tmp_path):
    real = m.play
    def spy(combat, table, mid, label, choices=(), target=None):
        try:
            return real(combat, table, mid, label, choices, target)
        except StopIteration:
            menu = table.state(mid)['menu']
            labels = [g['label'] for g in menu['actions']]
            opts = [o['label'] for g in menu['actions'] for o in g['options']]
            raise AssertionError('WANT %r HAVEG %s' % (label, ' || '.join(labels)) + ' OPTS ' + ' || '.join(opts))
    monkeypatch.setattr(m, 'play', spy)
    table_fixture(monkeypatch, tmp_path, [BASE, DRAGON])
