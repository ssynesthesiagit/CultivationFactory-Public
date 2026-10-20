"""Portable regressions for review findings: no implicit shared AI turns."""
from types import SimpleNamespace
import pytest
from tests import worker2_support as shared, bell_support
from combat.typed_executor import condition_rules


def test_shared_prompt_turn_does_not_implicitly_play_an_ai_turn(monkeypatch):
    table = SimpleNamespace(state=lambda mid: {'menu': {'actor_id': 'foe'}})
    calls = []
    monkeypatch.setattr(shared, 'settle', lambda *a, **k: calls.append((a, k)))
    with pytest.raises(KeyError, match='end_turn'):
        shared.prompt_turn(table, 'fight', 'owner')
    assert not calls


def test_bell_turn_driver_explicitly_uses_native_auto_step(monkeypatch):
    menus = iter([{'actor_id': 'foe'}, {'actor_id': 'owner'}])
    table = SimpleNamespace(state=lambda mid: {'menu': next(menus)})
    calls = []
    monkeypatch.setattr(shared, 'settle', lambda *a, **k: calls.append((a, k)))
    bell_support.turn(table, 'fight', 'owner')
    assert calls == [((table, 'fight', None), {'auto': True})]


def test_ninefold_scene_limit_has_no_exhausted_generic_fight_counter():
    from combat.factory_compiler import compile_character
    from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
    from tests.h1_support import sheet
    bundle = compile_character(sheet([bell.NINE], cl=18), actor_id='actor:bell')
    action = next(a for a in bundle['action_catalog']
                  if a['display_name'] == 'Ninefold Heavenly Bell')
    assert action['costs'] == [[bell.QI, 8]]
    assert any(r.get('feature_id') == bell.NINE for r in bundle['typed_passives'])


def test_native_journey_incapacitation_has_rules_without_becoming_unconscious():
    condition = SimpleNamespace(condition_id='incapacitated', data={})
    actor = SimpleNamespace(conditions={'native': condition})
    rows = condition_rules(actor)
    assert len(rows) == 1
    assert rows[0]['no_actions'] and rows[0]['no_reactions']
    assert not rows[0].get('speed_zero')
