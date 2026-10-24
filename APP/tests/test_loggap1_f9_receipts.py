"""LOGGAP1F9 regressions for the Sol review of the log-gap receipts.

1. Accounting receipts (passive armor lining, carried budgets) are not Reactions for Hostile Undertow.
2. A parked pre-damage hit guard does not borrow the incoming attack's damage window.
3. A carried ally budget names the creature that spent the Reaction, not the protected creature.
4. A carried Stamina Guard receipt does not re-grant Mountain-Forged Frame after an intervening save used it.

Unit-level: a small fake engine supplies only the surface each seam reads, so these run with no live
model, no table service and no fixtures beyond the module under test.
"""
from types import SimpleNamespace as NS

import pytest

from combat.ext import attack_reduction as ar
from combat.ext import insights6 as i6
from combat.ext import well_of_hours as woh
from combat import typed_executor

WEARER = 'actor:t.wearer'
PROTECTED = 'actor:t.protected'
REACTOR = 'actor:t.reactor'
ATTACKER = 'actor:t.attacker'
LINING = 'tianxia.treasure.armor_enhancement.fire_shedding_lining'
GUARD_SRC = 'tianxia.path.body_refining.feature.stamina_guard'


class FakeEngine:
    def __init__(self, actors=None, roll_id='roll:1'):
        self.state = NS(actors=actors or {}, current_actor_id=None, round_number=1, current_slot_index=0)
        self.events = []
        self._typed_pending_damage_type = ''
        self._seq = 0
        self.ctx = NS(attacker_id=ATTACKER, target_id=PROTECTED, roll_id=roll_id)

    def damage_context(self):
        return self.ctx

    def _append_event(self, event_type, source, *, actor_id=None, target_ids=(), payload=None, **_):
        self._seq += 1
        self.events.append(NS(event_type=event_type, source_definition_id=source, actor_id=actor_id,
                              target_ids=tuple(target_ids), payload=payload or {}, sequence=self._seq))

    def window(self, source, target_ids):
        self._seq += 1
        self.events.append(NS(event_type='REACTION_WINDOW_OPENED', source_definition_id=source, actor_id=None,
                              target_ids=tuple(target_ids), payload={'checkpoint': 'DAMAGE_APPLICATION'}, sequence=self._seq))

    def _apply_condition(self, actor, condition_id, feature, source_actor_id, expires_on=None, data=None):
        self._seq += 1
        actor.conditions[self._seq] = NS(condition_id=condition_id, instance_id=self._seq, source_actor_id=source_actor_id,
                                         feature=feature, data=data or {})

    def _remove_condition(self, actor, condition_id, feature=None):
        for key in [k for k, c in actor.conditions.items() if c.condition_id == condition_id]:
            del actor.conditions[key]


def _actor(entity_id, team='team:a'):
    return NS(entity_id=entity_id, team_id=team, active=True, conditions={}, turn_flags={}, reaction_available=True)


# ------------------------------------------------------------------ finding 1
@pytest.mark.parametrize('payload', [
    {'checkpoint': 'DAMAGE_APPLICATION', 'reduction': 5, 'damage_type': 'FIRE', 'passive': True},
    {'checkpoint': 'DAMAGE_APPLICATION', 'reduction': 3, 'carried_budget': True},
])
def test_accounting_receipt_does_not_start_hostile_undertow(monkeypatch, payload):
    calls = []
    monkeypatch.setattr(woh, '_undertow_activity', lambda engine, actor, activity, action, **kw: calls.append(activity))
    engine = FakeEngine({WEARER: _actor(WEARER)})
    woh.well_events(engine, 'REACTION_RESOLVED', {'actor_id': WEARER, 'source_definition_id': LINING, 'payload': payload})
    assert calls == []


def test_a_real_reaction_still_starts_hostile_undertow(monkeypatch):
    calls = []
    monkeypatch.setattr(woh, '_undertow_activity', lambda engine, actor, activity, action, **kw: calls.append(activity))
    engine = FakeEngine({WEARER: _actor(WEARER)})
    woh.well_events(engine, 'REACTION_RESOLVED', {'actor_id': WEARER, 'source_definition_id': GUARD_SRC,
                                                  'payload': {'checkpoint': 'DAMAGE_APPLICATION', 'spend': 1}})
    assert calls == ['reaction']


# ------------------------------------------------------------------ finding 2
def test_parked_hit_guard_budget_does_not_inherit_the_incoming_attack_window():
    engine = FakeEngine()
    target = _actor(PROTECTED)
    engine.window('action:incoming_attack', [PROTECTED])  # the damage window the incoming attack opened
    ar.remember(engine, target, 7, 7, [(10, ())], infer_window=False)
    (portion,) = target.turn_flags[ar.RECORD][ar.key_for(engine.ctx)]
    assert portion['feature'] == '' and portion['source'] == ''


def test_default_window_inference_still_names_the_accepted_window():
    engine = FakeEngine()
    target = _actor(PROTECTED)
    engine.window('action:incoming_attack', [PROTECTED])
    ar.remember(engine, target, 7, 7, [(10, ())])
    (portion,) = target.turn_flags[ar.RECORD][ar.key_for(engine.ctx)]
    assert portion['feature'] == 'action:incoming_attack'


# ------------------------------------------------------------------ finding 13
def test_carried_ally_budget_names_the_reactor_not_the_protected_creature():
    engine = FakeEngine()
    target = _actor(PROTECTED)
    engine.window('action:first_attack', [PROTECTED])
    ar.remember(engine, target, 7, 7, [(10, ())], feature='tianxia.talent.chains.iron_link_guard', reactor_id=REACTOR)
    engine.window('action:second_attack', [PROTECTED])  # a later packet of the same roll
    ar.carry(engine, target, 4)
    receipts = [e for e in engine.events if e.event_type == 'DAMAGE_REDUCTION_APPLIED' and e.payload.get('carried_budget')]
    assert receipts
    assert all(e.actor_id == REACTOR for e in receipts)
    # The carried packet is accounting, not another accepted reaction.
    assert not [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.payload.get('carried_budget')]


# ------------------------------------------------------------------ finding 3
def test_carried_guard_receipt_does_not_regrant_frame_after_an_intervening_save(monkeypatch):
    monkeypatch.setattr(i6, 'owns', lambda engine, actor, feature: feature == i6.FRAME)
    monkeypatch.setattr(typed_executor, 'active_save_pending', lambda *a, **k: False)
    engine = FakeEngine()
    subject = _actor(PROTECTED)
    engine.state.actors[PROTECTED] = subject

    # The accepted Stamina Guard reaction grants Frame's next-save allowance.
    i6.events(engine, 'REACTION_RESOLVED', {'actor_id': PROTECTED, 'source_definition_id': GUARD_SRC,
                                           'payload': {'checkpoint': 'DAMAGE_APPLICATION', 'spend': 1}})
    assert any(c.condition_id == i6.GUARD for c in subject.conditions.values())

    # An eligible intervening save consumes it.
    assert i6.native_saves(engine, subject, 'DEX', 13, 'system:save', {'named': {'forced_movement'}}) == 'ADVANTAGE'
    assert not any(c.condition_id == i6.GUARD for c in subject.conditions.values())

    # A later carried packet of the same Guard must not grant it again.
    i6.events(engine, 'REACTION_RESOLVED', {'actor_id': PROTECTED, 'source_definition_id': GUARD_SRC,
                                           'payload': {'checkpoint': 'DAMAGE_APPLICATION', 'reduction': 3, 'carried_budget': True}})
    assert not any(c.condition_id == i6.GUARD for c in subject.conditions.values())


# ------------------------------------------------------------------ finding 2 (several parked guards)
def test_each_parked_hit_guard_is_named_for_its_own_amount():
    engine = FakeEngine()
    target = _actor(PROTECTED)
    engine.window('action:incoming_attack', [PROTECTED])
    ar.park(target, ATTACKER, 3, 'feature:guard_a')
    ar.park(target, ATTACKER, 5, 'feature:guard_b')
    parked = target.turn_flags.pop(f'typed_hit_reduction:{ATTACKER}')
    parts = target.turn_flags.pop(f'typed_hit_reduction_parts:{ATTACKER}')
    reduced_by = target.turn_flags.pop(f'typed_hit_reduced_by:{ATTACKER}')
    pending = ar.apply_parked(engine, target, 2, parked, parts, reduced_by)
    assert pending == 0
    rows = target.turn_flags[ar.RECORD][ar.key_for(engine.ctx)]
    # Hit of 2 absorbed by guard_a's 3 (surplus 1), then guard_b's full 5 is surplus.
    assert {(p['feature'], p['source'], p['remaining']) for p in rows} == {
        ('feature:guard_a', 'feature:guard_a', 1), ('feature:guard_b', 'feature:guard_b', 5)}
    assert all(p['feature'] != 'action:incoming_attack' for p in rows)
