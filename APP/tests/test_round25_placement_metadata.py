"""Ordinary typed zones do not activate plug-in placement readers."""
from types import SimpleNamespace

import pytest
from combat.ext import placed


@pytest.mark.parametrize('stamp', [1, True, '1', None])
def test_scalar_placement_stamp_is_inert(stamp):
    ordinary = SimpleNamespace(active=True, trigger_profile={'placed': stamp}, owner_id='mage',
                               created_round=1, zone_id='zone:typed:1')
    banner = SimpleNamespace(active=True, trigger_profile={'placed': {'tag': 'standard'}}, owner_id='warrior',
                             created_round=1, zone_id='zone:placed:2')
    engine = SimpleNamespace(state=SimpleNamespace(zones={'ordinary': ordinary, 'banner': banner}))
    assert placed.data(ordinary) == {}
    assert placed.of(engine, 'standard') == [banner]
    assert placed.of(engine) == [banner]
