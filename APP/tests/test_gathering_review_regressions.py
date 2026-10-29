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


def test_common_herbcraft_can_decline_its_extra_lot_from_the_menu(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'common_herbcraft'])
    admit('harvest_source', patch('herbs', dc=10, rarity='common', category='herb', lots=5))
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=15, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 15}))
    option = next(o for o in cold().journey_menu(jid, A)['options']
                  if o['kind'] == 'clean_harvest' and o['payload'].get('extra_lot') is False
                  and 'extra_lot' not in o['payload'].get('benefits', []))
    act(option['kind'], option['payload'])
    lots = [row for row in cold().journeys.load(jid).state['actors'][A]['material_holdings'].values() if row.get('lot')]
    assert len(lots) == 1


def test_perfect_lot_can_decline_common_herbcraft_extra_lot(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'common_herbcraft'])
    admit('harvest_source', patch('perfect_herbs', dc=10, rarity='common', category='herb', lots=5, perfect=True))
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=20, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 20}))
    option = next(o for o in cold().journey_menu(jid, A)['options']
                  if o['kind'] == 'clean_harvest' and o['payload'].get('extra_lot') is False)
    act(option['kind'], option['payload'])
    lots = [row['lot']['quality'] for row in cold().journeys.load(jid).state['actors'][A]['material_holdings'].values() if row.get('lot')]
    assert lots == ['perfect']


def test_sovereign_dressing_applies_to_non_core_beast_remains(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, cl=15,
        talents=[T + 'simple_beast_dressing', T + 'beast_core_dressing', T + 'sovereign_beast_dressing'])
    admit('harvest_source', patch('scales', dc=20, rarity='very_rare', category='beast_remains', lots=3))
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=25, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 25}))
    act('clean_harvest', {'source': 'scales', 'benefits': ['extra_lot']})
    lots = [row['lot']['quality'] for row in cold().journeys.load(jid).state['actors'][A]['material_holdings'].values() if row.get('lot')]
    assert lots == ['pure', 'normal']


def test_field_ledger_requires_a_return_to_rearm_advantage(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'field_ledger'])
    admit('harvest_source', patch('site', dc=1))
    admit('harvest_source', patch('other', dc=1))
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=20, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 20}))
    act('read_the_sign', {'source': 'site', 'record': True})
    act('read_the_sign', {'source': 'site', 'record': True})
    state = cold().journeys.load(jid).state
    assert G._check_parts(cold().journeys.load(jid), A, 'clean_harvest', state['material_sources']['site']['harvest'], 'site')[1] == 'NORMAL'
    act('read_the_sign', {'source': 'other'})
    modes = []
    def roll(session, aid, kind, bonus, mode):
        modes.append(mode)
        return SimpleNamespace(natural_result=10, total=20, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 20})
    monkeypatch.setattr(G, '_roll', roll)
    act('read_the_sign', {'source': 'site'})
    act('read_the_sign', {'source': 'site'})
    assert modes == ['ADVANTAGE', 'NORMAL']
    assert cold().journeys.load(jid).state['actors'][A]['gathering_learning']['sites']['site']['used'] == 1


def test_seal_menu_uses_display_name_not_storage_key_and_batches(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'spirit_sealing_wax'])
    admit('harvest_source', patch('site', dc=1, lots=5))
    act('clean_harvest', {'source': 'site', 'benefits': []})
    rows = [o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'seal_essence']
    assert rows and all('patch:' not in o['label'] for o in rows)
    add = next(o for o in cold().journey_menu(jid, A)['options'] if o['id'].startswith('seal:add:') and o['payload']['choice'] == 'double')
    act(add['kind'], add['payload'])
    finish = next(o for o in cold().journey_menu(jid, A)['options'] if o['id'] == 'seal:selected')
    assert finish['payload']['lots'] == [add['payload']['lot']]
    act(finish['kind'], finish['payload'])
    lot = cold().journeys.load(jid).state['actors'][A]['material_holdings'][add['payload']['lot']]['lot']
    assert lot['sealed'] == 1 and lot['stable_until'] is not None


def test_manual_batch_seals_selected_lots_with_individual_choices(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'spirit_sealing_wax'])
    admit('harvest_source', patch('site', dc=1, lots=8, perfect=False))
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=11, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 11}))
    for _ in range(3):
        option = next(o for o in cold().journey_menu(jid, A)['options']
                      if o['kind'] == 'clean_harvest' and o['payload'].get('benefits') == ['pure'])
        act(option['kind'], option['payload'])
    holdings = cold().journeys.load(jid).state['actors'][A]['material_holdings']
    keys = sorted(k for k, row in holdings.items() if row.get('lot'))
    for key, choice in [(keys[0], 'double'), (keys[2], 'hide')]:
        option = next(o for o in cold().journey_menu(jid, A)['options']
                      if o['kind'] == 'select_seal_lot' and o['payload'].get('lot') == key
                      and o['payload'].get('choice') == choice and not o['payload'].get('repair'))
        act(option['kind'], option['payload'])
    start = cold().journeys.load(jid).state['seconds']
    finish = next(o for o in cold().journey_menu(jid, A)['options'] if o['id'] == 'seal:selected')
    assert finish['payload']['lots'] == [keys[0], keys[2]]
    act(finish['kind'], finish['payload'])
    state = cold().journeys.load(jid).state
    lots = state['actors'][A]['material_holdings']
    assert state['seconds'] == start + 600
    assert lots[keys[0]]['lot']['stable_until'] == start + 60 * 86400
    assert lots[keys[2]]['lot']['scent_hidden'] == 1
    assert lots[keys[1]]['lot']['sealed'] == 0
