"""Regressions for the CLOUDNEXT8F5 review findings."""
from types import SimpleNamespace

from combat.ext import gathering as G
from tests.test_gathering_journey import A, T, game, patch


def test_manual_margin_menu_composes_quick_payment_with_benefit(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'quick_field_harvest'])
    admit('harvest_source', patch('fast', dc=1, rarity='uncommon', lots=4))
    rows = [o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'clean_harvest']
    assert any(o['payload'].get('pay_cp') and o['payload'].get('benefits') == ['pure'] for o in rows)


def test_two_benefits_are_selected_for_ten_margin(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch)
    admit('harvest_source', patch('patch', dc=1, lots=5, perfect=True))
    rows = [o for o in cold().journey_menu(jid, A)['options']
            if o['kind'] == 'clean_harvest' and len(o['payload'].get('benefits', [])) == 2]
    assert rows and all(o['payload']['benefits'] for o in rows)


def test_sovereign_dressing_applies_to_non_core_beast_remains(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, cl=15,
        talents=[T + 'simple_beast_dressing', T + 'beast_core_dressing', T + 'sovereign_beast_dressing'])
    admit('harvest_source', patch('scales', dc=20, rarity='very_rare', category='beast_remains', lots=3))
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=25, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 25}))
    act('clean_harvest', {'source': 'scales', 'benefits': ['extra_lot']})
    lots = [row['lot']['quality'] for row in cold().journeys.load(jid).state['actors'][A]['material_holdings'].values() if row.get('lot')]
    assert lots == ['pure', 'normal']


def test_field_ledger_does_not_rearm_by_reexamination(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'field_ledger'])
    admit('harvest_source', patch('site', dc=1))
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=20, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 20}))
    act('read_the_sign', {'source': 'site', 'record': True})
    act('read_the_sign', {'source': 'site', 'record': True})
    site = cold().journeys.load(jid).state['actors'][A]['gathering_learning']['sites']['site']
    assert site['used'] == 1


def test_seal_menu_uses_display_name_not_storage_key_and_batches(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'spirit_sealing_wax'])
    admit('harvest_source', patch('site', dc=1, lots=5))
    act('clean_harvest', {'source': 'site', 'benefits': []})
    rows = [o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'seal_essence']
    assert rows and all('patch:' not in o['label'] for o in rows)
    assert any(len(o['payload']['lots']) > 1 for o in rows)
    assert all('ten minutes' in o['label'] for o in rows if len(o['payload']['lots']) > 1)
