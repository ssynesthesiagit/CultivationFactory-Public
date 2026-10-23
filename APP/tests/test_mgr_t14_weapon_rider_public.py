"""Weapon Refinement rider (lead ruling 2026): one spent Essence type adds 1d8
(2d8 on a critical hit) on the first confirmed weapon hit of an activation.

Public-CI test: no private authority, no NS1R fixtures, no live model servers.
The engine is replaced by a small stub; the hook and dice are the code under test.
"""
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from combat import typed_executor
from combat.ext import black_cauldron as C


@dataclass
class Ctx:
    engine: object
    actor: object
    action: object
    target: object = None
    targets: list = field(default_factory=list)
    critical_hit: bool = False
    damage_cache: dict = field(default_factory=dict)
    effect_source: str = ''
    typed: dict = field(default_factory=dict)
    source: str = ''

    def with_source(self, source):
        return Ctx(self.engine, self.actor, self.action, self.target, self.targets,
                   self.critical_hit, self.damage_cache, source)


def actor(entity_id='actor:owner'):
    return SimpleNamespace(entity_id=entity_id, turn_flags={}, display_name='Owner')


def make(monkeypatch, *, activation='A1', rolls=(), delivered=None):
    calls = []
    dice = iter(rolls)
    monkeypatch.setattr(C, 'roll', lambda engine, owner, count, sides, feature, modifier=0:
                        calls.append((count, sides, feature)) or next(dice))
    monkeypatch.setattr(C, 'activation_id', lambda engine: activation)

    def run(ctx, rows):
        delivered.append((ctx.effect_source, rows))
    monkeypatch.setattr(typed_executor, 'run_effects', run)
    engine = SimpleNamespace(_black_cauldron_ignore_resistance=None)
    return engine, calls


def armed(a, *, kind='Thunder', source='tianxia.refine', activation='A1', pierce=''):
    a.turn_flags[C.RIDER_FLAG] = {'source': source, 'activation': activation,
                                  'type': kind, 'pierce': pierce, 'done': False}


def hit_ctx(engine, a, *, source='tianxia.refine', critical=False):
    action = SimpleNamespace(source_definition_id=source, display_name='Refine technique')
    target = SimpleNamespace(entity_id='actor:foe', display_name='Foe')
    return Ctx(engine, a, action, target, [target], critical_hit=critical)


def test_first_confirmed_weapon_hit_adds_one_d8_of_chosen_type(monkeypatch):
    delivered = []
    engine, calls = make(monkeypatch, rolls=[5], delivered=delivered)
    a = actor()
    armed(a)
    ctx = hit_ctx(engine, a)
    C.weapon_rider_hit(ctx, ctx.target, 'weapon')
    assert calls == [(1, 8, C.REFINE)]
    assert len(delivered) == 1
    source, rows = delivered[0]
    assert source == C.REFINE
    assert rows == [{'type': 'extra_damage', 'applies_to': 'target', 'flat': 5, 'damage_types': ['thunder']}]


def test_critical_hit_rolls_two_d8(monkeypatch):
    delivered = []
    engine, calls = make(monkeypatch, rolls=[11], delivered=delivered)
    a = actor()
    armed(a)
    C.weapon_rider_hit(hit_ctx(engine, a, critical=True), SimpleNamespace(entity_id='actor:foe'), 'weapon')
    assert calls == [(2, 8, C.REFINE)]
    assert delivered[0][1][0]['flat'] == 11


def test_rider_is_once_per_activation(monkeypatch):
    delivered = []
    engine, calls = make(monkeypatch, rolls=[4, 4], delivered=delivered)
    a = actor()
    armed(a)
    ctx = hit_ctx(engine, a)
    C.weapon_rider_hit(ctx, ctx.target, 'weapon')
    C.weapon_rider_hit(ctx, ctx.target, 'weapon')
    assert len(delivered) == 1 and len(calls) == 1


def test_non_weapon_delivery_does_not_consume_rider(monkeypatch):
    delivered = []
    engine, calls = make(monkeypatch, rolls=[4], delivered=delivered)
    a = actor()
    armed(a)
    ctx = hit_ctx(engine, a)
    C.weapon_rider_hit(ctx, ctx.target, 'other')
    assert delivered == [] and calls == []
    assert a.turn_flags[C.RIDER_FLAG]['done'] is False
    C.weapon_rider_hit(ctx, ctx.target, 'weapon')
    assert len(delivered) == 1


def test_rider_from_other_activation_or_source_is_inert(monkeypatch):
    delivered = []
    engine, calls = make(monkeypatch, activation='A2', rolls=[4], delivered=delivered)
    a = actor()
    armed(a, activation='A1')
    C.weapon_rider_hit(hit_ctx(engine, a), SimpleNamespace(entity_id='actor:foe'), 'weapon')
    assert delivered == []
    a2 = actor('actor:other')
    armed(a2, source='tianxia.other', activation='A2')
    C.weapon_rider_hit(hit_ctx(engine, a2), SimpleNamespace(entity_id='actor:foe'), 'weapon')
    assert delivered == []


def test_piercing_choice_carries_into_rider(monkeypatch):
    delivered = []
    engine, calls = make(monkeypatch, rolls=[3], delivered=delivered)
    a = actor()
    armed(a, pierce='Fire')
    C.weapon_rider_hit(hit_ctx(engine, a), SimpleNamespace(entity_id='actor:foe'), 'weapon')
    assert engine._black_cauldron_ignore_resistance is None
    assert delivered and delivered[0][1][0]['damage_types'] == ['thunder']


def test_no_pending_rider_is_noop(monkeypatch):
    delivered = []
    engine, calls = make(monkeypatch, rolls=[], delivered=delivered)
    C.weapon_rider_hit(hit_ctx(engine, actor()), SimpleNamespace(entity_id='actor:foe'), 'weapon')
    assert delivered == [] and calls == []


def test_mandatory_refinement_choice_resolves_without_an_answer(monkeypatch):
    """Selecting Weapon Refinement must never crash on a follow-up with no answer.

    The old code indexed the answer as ``[0]``; an empty transport answer raised
    IndexError inside the activation. The engine's own no-answer default is the
    first offered option, and the rider uses the same order.
    """
    monkeypatch.setattr(C, 'choose', lambda *args, **kwargs: [])
    assert C.required(object(), actor(), 'weapon_rider', ['THUNDER', 'FIRE'], 'pick one') == ['THUNDER']


def test_unarmed_strike_fallback_is_not_a_weapon_delivery():
    """Weapon Refinement needs a real weapon, not the Strike's unarmed fallback."""
    weapon = {'ability': 'STR', 'damage': {'count': 1, 'sides': 4}}
    assert not C.weapon_delivered({'weapon': weapon, 'effects': [{'type': 'attack', 'attack_kind': 'unarmed'}]})
    assert C.weapon_delivered({'weapon': weapon, 'effects': [{'type': 'attack', 'attack_kind': 'weapon'}]})
    assert C.weapon_delivered({'qi_weapon_delivery': True, 'effects': []})


def activate_refinement(engine, owner):
    action = SimpleNamespace(display_name='Thunder Palm', source_definition_id='tianxia.refine')
    ctx = Ctx(engine, owner, action,
              typed={'effects': [{'type': 'damage', 'damage_types': ['THUNDER']}]})
    with C.prepare_refinement(ctx, None):
        pass


def test_refinement_use_is_limited_once_per_turn(monkeypatch):
    """Printed CL14 Limit: Once per turn, not once per activation.

    Two qi-powered activations in the same turn: only the first offers the
    refinement and spends Essence. The feature is offered again on the next
    turn. (Weapon Refinement's rider is the part that is once per activation.)
    """
    prompts, spends = [], []
    monkeypatch.setattr(C, 'owned', lambda engine, owner, feature=C.RESIDUE: {'numbers': {'cl': 14}})
    monkeypatch.setattr(C, 'profile', lambda engine, owner, action: {'qi_powered': True})
    monkeypatch.setattr(C, 'is_damage', lambda effects: True)
    monkeypatch.setattr(C, 'available', lambda engine, owner: [{'type': 'THUNDER', 'activation': 'EARLIER'}])
    monkeypatch.setattr(C, 'choose', lambda engine, owner, key, options, prompt, **kwargs:
                        prompts.append(prompt) or ['0'])
    monkeypatch.setattr(C, 'spend', lambda engine, owner, spent, source: spends.append(spent))
    monkeypatch.setattr(C, 'activation_id', lambda engine: 'A1')

    owner = actor()
    engine = SimpleNamespace(state=SimpleNamespace(
        round_number=1, current_actor_id='actor:owner',
        actors={'actor:owner': SimpleNamespace(turns_started=1)}))

    activate_refinement(engine, owner)
    activate_refinement(engine, owner)
    assert len(prompts) == 1 and len(spends) == 1
    assert 'Limit: once per turn' in prompts[0]

    engine.state.round_number = 2
    activate_refinement(engine, owner)
    assert len(prompts) == 2 and len(spends) == 2


def test_piercing_choice_matches_the_native_damage_kind():
    """The spent Essence type and resistance_ignored's kind are the same uppercase string."""
    target = SimpleNamespace(entity_id='actor:foe', conditions={})
    engine = SimpleNamespace(_black_cauldron_ignore_resistance=('actor:owner', 'actor:foe', 'FIRE'))
    assert C.pierce_resistance(engine, 'FIRE', {}, 'actor:owner', target) is True
    assert C.pierce_resistance(engine, 'fire', {}, 'actor:owner', target) is None
    assert C.pierce_resistance(engine, 'FIRE', {}, 'actor:other', target) is None
    assert all(kind == kind.upper() for kind in C.VALID)
