"""Stock-wrapper dispatch contracts; real captures run in the stock test file."""
import os

import pytest


@pytest.mark.parametrize('module_name,wrapper_name', [
    ('tests.test_bloodsense_delivery', 'test_stock_replays_against_merged_main'),
    ('tests.test_mgr_t14_bloodsense', 'test_six_stock_replays_with_lane_owned_output'),
])
def test_stock_wrappers_preserve_shared_baseline_and_isolate_captures(
        tmp_path, monkeypatch, module_name, wrapper_name):
    import importlib
    module = importlib.import_module(module_name)
    from tests import test_a2_glass_stock as stock

    # The wrapper must preserve the resolver's environment, including a release
    # pin supplied by CI. Never install a historical lane-specific revision.
    environment_before = dict(os.environ)
    calls = []

    def capture(path, seed):
        allowed = {'CF_STOCK_EVIDENCE'}
        assert {key: value for key, value in os.environ.items() if key not in allowed} == {
            key: value for key, value in environment_before.items() if key not in allowed}
        assert os.environ['CF_STOCK_EVIDENCE'] == str(tmp_path / 'stock-evidence')
        calls.append((path, seed))

    monkeypatch.setattr(stock, 'test_six_stock_captures_equal_main', capture)
    getattr(module, wrapper_name)(tmp_path, monkeypatch, stock.STOCK_SEEDS[0])
    assert calls == [(tmp_path, stock.STOCK_SEEDS[0])]
