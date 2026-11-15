"""Sequence modifiers retain their working manual Table route and persistence."""
import copy

import pytest

from combat.ext.attack_modifiers import capture
from combat.gate4_engine import Gate4ControllerEngine
from tests.equipment_readiness import ready_table_weapon
from tests.h1_support import script
from tests.hunt36_support import LEFT, RIGHT, act, fight, reload, turn
from tests.test_barrage_hits import BOW, FOLLOW, helpers

PINNING = 'TAL_BARRAGE_PINNING_VOLLEY'


@pytest.mark.parametrize('nested', [False, True])
def test_sequence_declaration_retains_variant_without_loadout(nested):
    declaration = {'type': 'barrage_hit_rule', 'rule': 'future_sequence'}
    effects = [{'type': 'save', 'on_fail': [declaration]}] if nested else [declaration]
    variant = {'typed': {}, 'costs': [], '_compose': {
        'when': 'hit', 'added': effects, 'key': 'future.talent',
        'name': 'Future sequence', 'modifier': {}}}
    base = {'action_id': 'future.attack', 'costs': [], 'typed': {'weapon': True}, 'variants': [variant]}
    capture(base)
    assert 'attack_modifier_loadout' not in base['typed']
    assert 'attack_modifier_variant' not in variant['typed']
    ordinary = copy.deepcopy(base)
    ordinary['variants'][0]['_compose']['added'] = [{'type': 'extra_damage', 'dice': '1d6'}]
    capture(ordinary)
    assert ordinary['typed']['attack_modifier_loadout'][0]['id'] == 'future.talent'
    assert ordinary['variants'][0]['typed']['attack_modifier_variant'] == 'future.attack'


@pytest.mark.parametrize('save_roll,expected_speed', [(1, 0), (19, 20)])
def test_pinning_available_table_route_second_hit_reload_and_expiry(tmp_path, monkeypatch, save_roll, expected_speed):
    from tests import hunt36_support
    original_sheet = hunt36_support.sheet
    def document(*args, **kwargs):
        doc = original_sheet(*args, **kwargs)
        doc['ability_scores_and_statistics']['technique_save_dc'] = 15
        return doc
    monkeypatch.setattr(hunt36_support, 'sheet', document)
    original_attack = Gate4ControllerEngine._resolve_attack_spec
    def hit(engine, *args, **kwargs):
        script(engine, [19, *([1] * 100)])
        return original_attack(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_attack_spec', hit)
    original_save = Gate4ControllerEngine._roll_save
    def save(engine, *args, **kwargs):
        script(engine, [save_roll, *([1] * 100)])
        return original_save(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_roll_save', save)
    combat, table, mid = fight(tmp_path, [PINNING], kit=helpers.BOW_KIT, cl=5,
                               foe_hp=400, seed='SOLFSOL117R3',
                               positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}})
    turn(combat, table, mid)
    engine = reload(combat, mid)
    name = BOW + ' + Pinning Volley'
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == LEFT and a.display_name == name)
    ready_table_weapon(table, mid, source)
    state = table.state(mid)
    assert any(g['label'] == name for g in state['menu']['actions'])
    engine = reload(combat, mid)
    assert not [a for a in engine.action_catalog.values()
                if (a.parameters.get('attack_modifier_setting') or {}).get('modifier') == PINNING]
    assert not engine.action_catalog[source].parameters['typed'].get('attack_modifier_variant')
    sequence = engine.state.event_sequence
    act(combat, table, mid, name)
    engine = reload(combat, mid)  # fresh service verifies recorded events and replay
    events = [e for e in engine.events if e.sequence > sequence]
    assert len([e for e in events if e.event_type == 'ATTACK_ROLLED']) == 1
    assert not [e for e in events if e.event_type == 'SAVE_ROLLED']
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30
    assert not engine.state.actors[LEFT].action_available
    assert engine.state.actors[LEFT].bonus_action_available
    sequence = engine.state.event_sequence
    act(combat, table, mid, FOLLOW)
    engine = reload(combat, mid)
    events = [e for e in engine.events if e.sequence > sequence]
    assert len([e for e in events if e.event_type == 'ATTACK_ROLLED']) == 1
    saves = [e for e in events if e.event_type == 'SAVE_ROLLED']
    assert len(saves) == 1 and 'DEX' in saves[0].payload['reason']
    assert saves[0].payload['success'] == (expected_speed == 20)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == expected_speed
    assert not engine.state.actors[LEFT].bonus_action_available
    act(combat, table, mid, 'end')
    turn(combat, table, mid, RIGHT)
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30
    assert not any(c.condition_id == 'condition:typed.pinning_volley'
                   for c in engine.state.actors[RIGHT].conditions.values())
