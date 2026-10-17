import tests.test_a2_hunger_second_pass as m
from tests.test_a2_hunger_second_pass import table_fixture, DRAGON, BASE


def test_diag(monkeypatch, tmp_path):
    real = m.play
    def spy(combat, table, mid, label, choices=(), target=None):
        try:
            return real(combat, table, mid, label, choices, target)
        except StopIteration:
            menu = table.state(mid)['menu']
            with open('/var/tmp/mainred1-labels.txt', 'w') as f:
                f.write('WANT %r\n' % label)
                for g in menu['actions']:
                    f.write('GROUP %s | %s\n' % (g['label'], [(o['label'], o['target_ids']) for o in g['options']]))
                f.write('MOVES %d\n' % len(menu.get('moves') or []))
            raise
    monkeypatch.setattr(m, 'play', spy)
    table_fixture(monkeypatch, tmp_path, [BASE, DRAGON])
