"""Sol seam 4F20R2 review fixes (Ten Thousand Sword Array Cultivator).

Finding 1: Twin Guard's +1 AC against melee attack rolls has a regression test (one bonus, the printed field, expiry).
Finding 2: a projected Seed Sword's Slashing or Force is chosen per hit by the Seed-Sword Attack, not fixed at cultivation.
Finding 3: Twin Guard needs both Armaments maintained; a destroyed, suppressed or fallen twin grants nothing.
Finding 4: the owner-wide control range does not follow the first sword's position into a Sword Array Field.

Plug-in level checks with stubbed engine state; no live model or embedding server is called.
"""
from types import SimpleNamespace

import pytest

from combat.ext import ten_thousand_swords as swords
from combat.ext.ten_thousand_swords import TWIN


A = 'actor:sword-owner'


def _sword(index, mode='guard', location='floating', **extra):
    return {'slot': index, 'form': 'projected', 'location': location, 'mode': mode, 'damage_type': 'force',
            'item_uid': '', 'x': 2 + index, 'y': 3, 'z': 0, **extra}


def _actor(turn_flags=None):
    return SimpleNamespace(entity_id=A, display_name=A, active=True, position=SimpleNamespace(x=2, y=2, z=0),
                           turn_flags=dict(turn_flags or {}), conditions={}, resources={})


class _Engine:
    def __init__(self):
        self.modifiers = []
        self.conditions = []

    def _add_modifier(self, actor, source, field, op, value, target, **kw):
        self.modifiers.append({'field': field, 'op': op, 'value': value, 'target': target, **kw})

    def _apply_condition(self, actor, name, source, source_actor_id, **kw):
        self.conditions.append({'name': name, **kw})


def _twin_guard(monkeypatch, swords_list, turn_flags=None):
    monkeypatch.setattr(swords, 'owned', lambda engine, row, source=swords.SEED: source == TWIN)
    monkeypatch.setattr(swords, 'state', lambda row: {'swords': swords_list, 'origin_used': False})
    engine = _Engine()
    swords.twin_guard(engine, _actor(turn_flags))
    return engine


# Finding 1: the printed +1 AC against melee attacks, applied once and ending at the start of the next turn.

def test_twin_guard_guard_mode_twin_gives_one_melee_ac_until_next_turn(monkeypatch):
    engine = _twin_guard(monkeypatch, [_sword(0, 'assault'), _sword(1, 'guard')])
    assert engine.modifiers == [{'field': 'armor_class_vs_melee', 'op': 'ADD', 'value': 1, 'target': 'SELF',
                                 'expires_on': 'START_OF_SOURCE_NEXT_TURN', 'source_actor_id': A}]
    assert [c['name'] for c in engine.conditions] == ['condition:typed.twin_sword_guard']
    assert engine.conditions[0]['expires_on'] == 'START_OF_SOURCE_NEXT_TURN'


def test_twin_guard_uncommanded_assault_twin_gives_the_bonus(monkeypatch):
    engine = _twin_guard(monkeypatch, [_sword(0, 'assault'), _sword(1, 'assault')])
    assert [m['value'] for m in engine.modifiers] == [1]


def test_twin_guard_commanded_swords_give_nothing(monkeypatch):
    engine = _twin_guard(monkeypatch, [_sword(0, 'assault'), _sword(1, 'assault')],
                         turn_flags={'twin_commanded': True})
    assert engine.modifiers == []
    engine = _twin_guard(monkeypatch, [_sword(0, 'assault'), _sword(1, 'assault')],
                         turn_flags={'sword_commanded:0': True, 'sword_commanded:1': True})
    assert engine.modifiers == []


def test_twin_guard_two_qualifying_swords_still_give_a_single_plus_one(monkeypatch):
    engine = _twin_guard(monkeypatch, [_sword(0, 'guard'), _sword(1, 'guard')])
    assert len(engine.modifiers) == 1 and engine.modifiers[0]['value'] == 1


# Finding 3: Twin Guard needs two maintained Armaments.

def test_twin_guard_needs_two_maintained_armaments(monkeypatch):
    # A single Armament is not a Twin configuration.
    assert _twin_guard(monkeypatch, [_sword(0, 'guard')]).modifiers == []
    # A destroyed, suppressed or fallen twin leaves no second Armament, even if the remaining sword is in Guard Mode.
    for broken in ({'destroyed': 1}, {'suppressed': 1}, {'location': 'fallen'}):
        remaining = _sword(0, 'guard')
        twin = _sword(1, 'guard', **broken)
        assert _twin_guard(monkeypatch, [remaining, twin]).modifiers == [], broken
        assert _twin_guard(monkeypatch, [twin, remaining]).modifiers == [], broken


# Finding 4: the owner-wide control range must not key on swords[0] being inside the field.

def test_control_range_does_not_follow_the_first_sword_into_the_field(monkeypatch):
    from combat.ext import qi_path
    monkeypatch.setattr(swords, 'owned', lambda engine, row, source=swords.SEED: True)
    monkeypatch.setattr(swords, 'numbers', lambda engine, row: {'cl': 12})
    monkeypatch.setattr(swords, 'fields', lambda engine, row: ['field'])
    # Only the first sword (x=2) is inside the field; the second (x=9) is outside.
    monkeypatch.setattr(swords, 'inside', lambda engine, zone, p: p.x == 2)
    monkeypatch.setattr(qi_path, 'base_armament_control_range', lambda engine, row: 30)
    monkeypatch.setattr(swords, 'state', lambda row: {'swords': [_sword(0), _sword(1, x=9)]})
    actor = _actor()
    # CL12 has no 60-foot owner-wide reach outside a field, and the first sword's field position must not grant one.
    assert swords.source_control_range(SimpleNamespace(), actor) == 30


# Finding 2: a projected Seed Sword's damage type is chosen per hit.

class _Stop(Exception):
    def __init__(self, typed):
        super().__init__('stop')
        self.typed = typed


class _Action:
    def __init__(self, parameters=None):
        self.parameters = parameters or {}
        self.source_definition_id = 'action:typed.seed'

    def model_copy(self, update=None):
        update = update or {}
        return _Action({**self.parameters, **update.get('parameters', {})})


def _strike_typed(monkeypatch, sword, *, answer, second=False, pursuit=False):
    calls = []

    def fake_choose(ctx, key, options, labels, prompt, **kw):
        calls.append({'key': key, 'options': list(options)})
        return [answer]

    def fake_replace(ctx, **kw):
        raise _Stop(kw['typed'])

    monkeypatch.setattr(swords, 'choose', fake_choose)
    monkeypatch.setattr(swords, 'replace', fake_replace)
    monkeypatch.setattr(swords, 'numbers', lambda engine, row: {'cl': 6, 'key_mod': 2})
    monkeypatch.setattr(swords, 'perfected', lambda engine, row: False)
    ctx = SimpleNamespace(engine=SimpleNamespace(), actor=_actor(), typed={}, action=_Action(), damage_cache={})
    target = SimpleNamespace(active=True, entity_id='actor:foe', position=SimpleNamespace(x=3, y=3, z=0))
    with pytest.raises(_Stop) as stop:
        swords.strike(ctx, sword, target, second=second, pursuit=pursuit)
    damage = stop.value.typed['effects'][0]['on_hit'][0]
    return calls, damage['damage_types']


def test_projected_seed_sword_hit_chooses_slashing_or_force_at_the_attack(monkeypatch):
    # Cultivated as Force, but this attack is declared as Slashing: the printed per-hit choice decides.
    sword = _sword(0, 'assault', damage_type='force')
    calls, types = _strike_typed(monkeypatch, sword, answer='slashing')
    assert types == ['slashing']
    assert calls == [{'key': 'hit-type:0:attack', 'options': ['slashing', 'force']}]


def test_projected_twin_second_hit_asks_its_own_damage_type(monkeypatch):
    sword = _sword(1, 'assault', damage_type='slashing')
    calls, types = _strike_typed(monkeypatch, sword, answer='force', second=True)
    assert types == ['force']
    assert calls == [{'key': 'hit-type:1:second', 'options': ['slashing', 'force']}]
