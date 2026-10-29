"""F4 controller regressions: native hazard quotes, offline phone/desktop clients."""
import json
from pathlib import Path
import subprocess

import pytest

from tests.auto8f1_table_support import OWNER
from tests.test_mgr_t16_athletics import game


@pytest.mark.parametrize('scenario', ['chooser', 'refresh'])
def test_compact_route_controller_confirmation_and_refresh(tmp_path, monkeypatch, scenario):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    _, table, mid = game(tmp_path, [], ask=False, arena_update={'terrain_regions': [{
        'region_id': 'visible-hazard', 'terrain_type': 'QI_HAZARD', 'movement_cost': 1,
        'cells': [{'x': 4, 'y': 6}]}]})
    state = table.state(mid, lazy=True, fog=True, fog_view='own', fog_actor_ids=(OWNER,))
    menu = state['menu']
    quote = table.preview_destination(mid, menu['decision_id'], menu['state_version'], OWNER,
                                      {'x': 4, 'y': 6, 'z': 0}, 'walk')
    assert quote['candidate']['metadata']['hazard_exposure'] is True
    result = subprocess.run(['node', 'tests/menuspeed7_refresh.mjs', scenario],
        cwd=Path(__file__).resolve().parents[1], input=json.dumps({'state': state, 'quote': quote}),
        capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
