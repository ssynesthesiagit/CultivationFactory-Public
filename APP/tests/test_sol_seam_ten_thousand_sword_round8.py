"""Sol seam review round 8 regressions (Ten Thousand Sword Array Cultivator).

Finding 1: restored progression must keep the owner's native items in the recompiled bundle.
Finding 5: successful Dread (and Frightened-immune Dread) expires at the target's next turn start.
"""
import json
from types import SimpleNamespace

import pytest

from combat import typed_executor
from combat.ext import ten_thousand_swords as swords
from tests.test_mgr_t14_ten_thousand_sword_array_cultivator_floor58 import A, native
from tests.worker2_support import reload


def _intent_effects(monkeypatch, name, failed, immune=False):
    captured = []
    monkeypatch.setattr(typed_executor, 'run_effects', lambda ctx, effects: captured.extend(effects))
    monkeypatch.setattr(typed_executor, 'condition_immune', lambda engine, t, cond: immune)
    target = SimpleNamespace(entity_id='actor:foe', display_name='Foe')
    ctx = SimpleNamespace(engine=SimpleNamespace(), actor=SimpleNamespace(entity_id=A), target=target, targets=[target])
    swords.intent_result(ctx, {'intent': name, 'failed': int(failed)})
    return captured


# Finding 5: Dread success / immune success uses the target-next-turn lifetime.
@pytest.mark.parametrize('immune', [False, True])
def test_successful_dread_expires_at_target_next_turn(monkeypatch, immune):
    effects = _intent_effects(monkeypatch, 'Dread', failed=False, immune=immune)
    denied = [e for e in effects if e.get('condition') == 'reaction_denied']
    assert denied and all(e['duration'] == {'kind': 'target_next_turn'} for e in denied)


def test_failed_dread_keeps_owner_turn_frightened_duration(monkeypatch):
    effects = _intent_effects(monkeypatch, 'Dread', failed=True)
    frightened = [e for e in effects if e.get('condition') == 'frightened']
    assert frightened and all(e['duration'] == {'kind': 'until_start_of_your_next_turn'} for e in frightened)


def test_severing_still_expires_at_target_next_turn(monkeypatch):
    effects = _intent_effects(monkeypatch, 'Severing', failed=False)
    denied = [e for e in effects if e.get('condition') == 'reaction_denied']
    assert denied and all(e['duration'] == {'kind': 'target_next_turn'} for e in denied)


# Finding 1: after a finished journey, a new journey recompiles the learned sheet with the real owner item.
def test_restored_progression_recompile_keeps_real_owner_item(tmp_path, monkeypatch):
    cold, jid, _ = native(tmp_path, monkeypatch, cl=6, seeds=0, real_sword=True)
    first = cold().journey_state(jid)
    assert any(r['key'] == 'given.0' for r in first['actors'][A]['bundle']['carrying']['items'])
    # Finish the first journey so a new one may include the same creature.
    path = cold().journeys.path(jid)
    registry = json.loads(path.read_text())
    registry['sessions'][jid]['phase'] = 'finished'
    path.write_text(json.dumps(registry))
    second_id = cold().create_journey(project_ids=['sword-owner'], arena_id='court',
        positions={A: {'x': 2, 'y': 2}}, base_paces={A: 5})['journey_id']
    second = cold().journey_state(second_id)
    assert second['actors'][A]['source_states'][swords.FAMILY]['learned']
    physical = next(r for r in second['actors'][A]['bundle']['carrying']['items'] if r['key'] == 'given.0')
    assert any(a['source_definition_id'] == physical['weapon_action']
               for a in second['actors'][A]['bundle']['action_catalog'])
