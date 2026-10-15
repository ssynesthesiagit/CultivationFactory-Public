"""Named owner integration guards and six exact-base stock captures."""
from pathlib import Path
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS
import tests.test_a2_glass_stock as stock
from tests import r1i_service_support as s

EVIDENCE=Path('/var/tmp/auto-audit/fix/MGR-T14-ling-reserve-dust-cultivator-dust-cloud-1-evidence')


@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_six_exact_base_stock_replays(tmp_path,monkeypatch,seed):
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setattr(stock,'EVIDENCE',EVIDENCE/'stock')
    stock.test_six_stock_captures_equal_main(tmp_path,seed)


def test_named_contracts_without_opt_in_are_inert(tmp_path):
    from combat import observer_information as information,asset_anchor_runtime as assets,senses
    combat,table,mid,send,commit=s.fixture(tmp_path,[],wide=True)
    e=combat._load_session(mid).engine;actor=e.state.actors[s.OWNER]
    assert assets.members(e)==[]
    assert information.readings(e,actor)==[]
    assert 'information' not in senses.perception(e,actor)


def test_information_rejects_wrong_source_owner(tmp_path):
    from combat import observer_information as information
    source='tianxia.subpath.qi.dust_cultivator.feature.choking_dust'
    combat,table,mid,send,commit=s.fixture(tmp_path,[source],wide=True)
    e=combat._load_session(mid).engine
    action=next(a for a in e.action_catalog.values() if a.owner_id==s.OWNER and
                a.parameters.get('typed',{}).get('source')==source)
    with pytest.raises(ValueError,match='actual source owner'):
        information.publish(e,e.state.actors[s.OWNER],action.source_definition_id,e.state.actors[s.FOE],
            'declaration',{'fact':'source-scoped'},'START_OF_SOURCE_NEXT_TURN')
    assert information.readings(e,e.state.actors[s.OWNER])==[]
