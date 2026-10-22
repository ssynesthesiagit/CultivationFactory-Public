"""RB2 regressions for the MGR-T14 Sol seam review (180625).

- Read the Thread rider text in riders_c8.json must match the plugin text (no removed prediction-button rider).
- Resource bounds: an owner's martial focus must stay within its registered maximum; the bdiff script-2 crash
  signature (`resource out of bounds: resource:core.martial_focus`) is the guard that rejects out-of-range state.
"""
import json
from pathlib import Path

import pytest

from tests.worker2_support import OWNER, fixture

APP = Path(__file__).resolve().parents[1]
RIDERS = APP / 'authority' / 'typed_mechanics' / 'reviewed_final.d' / 'riders_c8.json'
THREAD = 'tianxia.tradition.spirit.fate_reader.feature.read_the_thread'


def test_read_the_thread_riders_match_plugin_text():
    row = json.loads(RIDERS.read_text(encoding='utf-8'))['mechanics'][THREAD]
    riders = ' '.join(row['riders'])
    assert 'Thread Clarity' in riders and 'Mark the Branch' in riders
    assert 'choose one creature involved in the predicted branch' in riders
    assert 'prediction button' not in riders
    assert row['riders'], 'riders must not be empty while the plugin implements Mark the Branch'
    from combat.ext import fate_reader
    source = Path(fate_reader.__file__).read_text(encoding='utf-8')
    assert 'choose one creature involved in the predicted branch' in source
    assert 'prediction button' not in source


def test_owner_martial_focus_stays_within_registered_maximum(tmp_path):
    from combat.gate2_runtime_models import ActorState
    combat, table, mid = fixture(tmp_path, ['TAL_BRUTE_GREATER_BRUTE'])
    engine = combat._load_session(mid).engine
    dumped = engine.state.actors[OWNER].model_dump()
    rid = 'resource:core.martial_focus'
    assert dumped['resource_maximums'][rid] == 1
    assert 0 <= dumped['resources'][rid] <= 1
    ActorState.model_validate(dumped)
    dumped['resources'][rid] = 3
    with pytest.raises(ValueError, match='resource out of bounds: resource:core.martial_focus'):
        ActorState.model_validate(dumped)
    dumped['resources'][rid] = 1
    dumped['resource_maximums'].pop(rid)
    with pytest.raises(ValueError, match='resource out of bounds: resource:core.martial_focus'):
        ActorState.model_validate(dumped)
