"""Journey regressions for gathering review findings."""
from types import SimpleNamespace

import pytest

from combat.ext import gathering as G
from tests.test_gathering_journey import A, T, game, patch


@pytest.mark.parametrize(("total", "quality"), [(20, "normal"), (25, "pure")])
def test_sovereign_core_margin_through_service(tmp_path, monkeypatch, total, quality):
    cold, jid, act, admit = game(
        tmp_path, monkeypatch, cl=15,
        talents=[T + 'simple_beast_dressing', T + 'beast_core_dressing',
                 T + 'sovereign_beast_dressing'],
    )
    admit('harvest_source', patch('core', dc=20, rarity='very_rare',
                                  category='beast_core', perfect=False))
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=total,
        model_dump=lambda **kwargs: {'natural_result': 10, 'total': total}))
    act('clean_harvest', {'source': 'core', 'benefits': []})
    state = cold().journeys.load(jid).state
    lots = [row['lot'] for row in state['actors'][A]['material_holdings'].values() if row.get('lot')]
    assert [lot['quality'] for lot in lots] == [quality]


def test_quick_menu_describes_unpaid_disadvantage(tmp_path, monkeypatch):
    cold, jid, _, admit = game(tmp_path, monkeypatch, talents=[T + 'quick_field_harvest'])
    admit('harvest_source', patch('fast', rarity='uncommon'))
    options = cold().journey_menu(jid, A)['options']
    row = next(o for o in options if o['id'] == 'harvest:fast:quick')
    assert 'no cost' in row['label'] and 'Disadvantage' in row['label']
    assert not row['payload'].get('pay_cp')
