"""Required exact-base replay and private-view guards for shared contract integration."""
from pathlib import Path
import subprocess
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS
import tests.test_a2_glass_stock as stock

EVIDENCE=Path('/var/tmp/auto-audit/fix/MGR-T14-ling-reserve-hearthfire-cultivator-kindled-hearth-1-evidence')


@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_six_exact_base_stock_replays(tmp_path,monkeypatch,seed):
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setattr(stock,'EVIDENCE',EVIDENCE/'stock')
    stock.test_six_stock_captures_equal_main(tmp_path,seed)


def test_owner_observer_frontend_keeps_recipient_scope():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','--test','--test-isolation=none','static/tabletop/observer-information.test.mjs'],
        cwd=root,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
