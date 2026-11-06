"""Automatic full-ledger handling must not roll back a successful field examination."""
from types import SimpleNamespace

from combat.ext import gathering as G
from tests.test_gathering_journey import A, game, patch


def test_automatic_read_replaces_a_full_ledger_entry(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, automatic=True, talents=[G.rules()["ledger"]["feature"]])
    admit('harvest_source', patch('new_site', dc=1))
    session = cold().journeys.load(jid)
    actor = session.state['actors'][A]
    sites = actor.setdefault('gathering_learning', {}).setdefault('sites', {})
    cap = G._site_cap(session, A)
    sites.update({f'old{i}': {'recorded_at': 0, 'used': 1} for i in range(cap)})
    cold().journeys.save(session)
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=20, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 20}))
    option = next(o for o in cold().journey_menu(jid, A)['options']
                  if o['kind'] == 'read_the_sign' and o['payload']['source'] == 'new_site'
                  and o['auto_select'])
    assert option['payload']['record'] and option['payload']['replace'] == 'old0'
    act(option['kind'], option['payload'])
    state = cold().journeys.load(jid).state
    assert any(e['kind'] == 'HARVEST_SIGN' and e['source_id'] == 'new_site' and e['success']
               for e in state['events'])
    assert 'new_site' in state['actors'][A]['gathering_learning']['sites']
    assert 'old0' not in state['actors'][A]['gathering_learning']['sites']
