import tests.test_a2_hunger_second_pass as m
from tests.test_a2_hunger_second_pass import table_fixture, DRAGON, BASE


def test_diag(monkeypatch, tmp_path):
    real = m.play
    def spy(combat, table, mid, label, choices=(), target=None):
        try:
            return real(combat, table, mid, label, choices, target)
        except StopIteration:
            menu = table.state(mid)['menu']
            labels = [(g['label'], [(o['label'], o['target_ids']) for o in g['options']]) for g in menu['actions']]
            raise AssertionError('WANT %r target=%r HAVE %r MOVES=%d' % (label, target, labels, len(menu.get('moves') or [])))
    monkeypatch.setattr(m, 'play', spy)
    table_fixture(monkeypatch, tmp_path, [BASE, DRAGON])
