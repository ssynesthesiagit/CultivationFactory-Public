"""Exact-base six-stock replay comparison. Capture path supplied by lane list."""
import hashlib
import json
from pathlib import Path
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS,_play,_bytes_of,_start_stock

EVIDENCE=Path('/var/tmp/auto-audit/fix/MGR-T14-sol-reserve-sumo-sumo-strike-1-evidence')


@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_stock_exact_base(tmp_path,seed):
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    capture=_bytes_of(_play(tmp_path,lambda root:_start_stock(root,seed)))
    # Base marker is a file in this checkout, never inferred from runtime data.
    base=Path(__file__).with_name('sumo_base_capture.marker').exists()
    digest=hashlib.sha256(capture.encode()).hexdigest()
    record=EVIDENCE/('stock-base-' if base else 'stock-head-')
    path=Path(str(record)+seed+'.json')
    path.write_text(json.dumps({'seed':seed,'sha256':digest,'capture':json.loads(capture)},sort_keys=True))
    if not base:
        expected=json.loads((EVIDENCE/('stock-base-'+seed+'.json')).read_text())
        assert digest==expected['sha256']
