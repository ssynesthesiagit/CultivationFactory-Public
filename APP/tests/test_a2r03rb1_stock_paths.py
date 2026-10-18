"""Keep both stock-output directory overrides usable after the mainline merge."""
import json
from types import SimpleNamespace

import pytest

from tests import test_a2_glass_stock as stock


@pytest.mark.parametrize('explicit,legacy', [(True, False), (False, True), (True, True), (False, False)])
def test_stock_evidence_destination_keeps_both_overrides(tmp_path, monkeypatch, explicit, legacy):
    monkeypatch.delenv('CF_STOCK_EVIDENCE', raising=False)
    monkeypatch.delenv('CF_STOCK_EVIDENCE_DIR', raising=False)
    if explicit:
        monkeypatch.setenv('CF_STOCK_EVIDENCE', str(tmp_path / 'explicit'))
    if legacy:
        monkeypatch.setenv('CF_STOCK_EVIDENCE_DIR', str(tmp_path / 'legacy'))
    expected = tmp_path / ('explicit' if explicit else 'legacy' if legacy else 'stock')
    monkeypatch.setattr(stock, 'replay_base_or_skip', lambda: 'pinned-base')
    capture = {'state': {'terminal_result': 'finished'}}
    monkeypatch.setattr(stock.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=json.dumps(capture), stderr=''))

    stock.test_six_stock_captures_equal_main(tmp_path / 'case', 'merge-regression')

    assert {path.name for path in expected.iterdir()} == {
        'merge-regression-base.json', 'merge-regression-head.json',
        'merge-regression-comparison.json',
    }
    comparison = json.loads((expected / 'merge-regression-comparison.json').read_text())
    assert comparison['base'] == 'pinned-base'
    assert comparison['identical'] is True
    assert comparison['first_difference'] is None
    assert not (tmp_path / ('legacy' if explicit else 'explicit')).exists()
