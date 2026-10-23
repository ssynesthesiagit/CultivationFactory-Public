"""Regression tests for the Sol review findings on the Ten Thousand Sword Array plug-in (F2 round).

Each test targets one seam directly with stub engines, so it fails on the pre-fix code.
"""
from types import SimpleNamespace
from unittest import mock

import pytest

from combat.ext import ten_thousand_swords as swords
from combat.ext import needle
from combat.ext.effect_durations import round_token


def _actor(eid='actor:sword', team='A', position=None, conditions=None, reaction=True):
    return SimpleNamespace(entity_id=eid, display_name=eid, team_id=team, active=True,
                           position=position or SimpleNamespace(x=0, y=0, z=0), conditions=conditions or {},
                           modifiers={}, reaction_available=reaction, turn_flags={}, resources={})


def _engine(actors=(), round_number=7):
    return SimpleNamespace(state=SimpleNamespace(actors={a.entity_id: a for a in actors}, round_number=round_number,
                                                  match_id='m1', current_slot_index=0, zones={}),
                           action_catalog={}, grid=mock.Mock(), _add_modifier=mock.Mock(),
                           _apply_condition=mock.Mock(), _append_event=mock.Mock())


# Finding 1: the sword plug-in vetoed Qi Path's own Armament controls for owners of the family.
def test_sword_owner_keeps_qi_path_armament_controls(monkeypatch):
    actor = _actor()
    monkeypatch.setattr(swords, 'owned', lambda engine, a, source=swords.SEED: True)
    action = SimpleNamespace(parameters={'armament': 'attack'})
    assert swords.candidates(_engine([actor]), actor, None, action) is not False


# Finding 2: Array Pursuit must not spend its use or Reaction when no sword can make the attack.
def test_pursuit_without_a_reachable_sword_spends_nothing(monkeypatch):
    actor = _actor(eid='actor:array')
    mover = _actor(eid='actor:mover', team='B')
    previous = SimpleNamespace(x=1, y=1, z=0)
    nxt = SimpleNamespace(x=9, y=9, z=0)
    engine = _engine([actor, mover])
    engine.grid.distance_ft.return_value = 99
    engine.grid.line_of_sight.return_value = False
    engine.action_catalog = {'a': SimpleNamespace(owner_id=actor.entity_id,
                                                  parameters={'sword_array': 'array', 'typed': {}})}
    state = {'swords': [{'location': 'floating', 'mode': 'assault', 'x': 0, 'y': 0, 'z': 0, 'form': 'real',
                         'item_uid': '', 'suppressed': 0, 'destroyed': 0}]}
    asked, spent = [], []
    monkeypatch.setattr(swords, 'owned', lambda engine, a, source=swords.SEED: True)
    monkeypatch.setattr(swords, 'state', lambda a: state)
    monkeypatch.setattr(swords, 'perfected', lambda engine, a: False)
    monkeypatch.setattr(swords, 'fields', lambda engine, a: [object()])
    monkeypatch.setattr(swords, 'inside', lambda engine, z, p: p is previous)
    monkeypatch.setattr(swords, 'destinations', lambda *a, **k: [])
    monkeypatch.setattr(swords, 'choose', lambda *a, **k: asked.append(a) or ['attack'])
    monkeypatch.setattr(swords, 'save', lambda *a, **k: spent.append(a))
    swords.pursue(engine, mover, previous, nxt, intent=object())
    assert asked == []
    assert spent == []
    assert actor.reaction_available is True


# Finding 3: Severing's disadvantage and reaction restriction belong to the target: the target's next turn.
def test_severing_clause_expires_at_the_target_next_turn(monkeypatch):
    captured = []
    from combat import typed_executor
    monkeypatch.setattr(typed_executor, 'run_effects', lambda ctx, effects: captured.extend(effects))
    target = _actor(eid='actor:foe', team='B')
    ctx = SimpleNamespace(engine=_engine([target]), target=target, targets=[target])
    swords.intent_result(ctx, {'intent': 'Severing', 'failed': 1})
    assert captured and all(e['duration'] == {'kind': 'target_next_turn'} for e in captured)


# Finding 4: the second sword's Guard Mode protects a creature within 5 feet, as the primary Armament does.
def test_second_sword_guard_shields_a_creature(monkeypatch):
    from combat import relations
    owner = _actor(eid='actor:owner')
    ally = _actor(eid='actor:ally')
    engine = _engine([owner, ally])
    engine.state.event_sequence = 0
    engine.grid.distance_ft.return_value = 5
    state = {'swords': [
        {'location': 'floating', 'mode': 'assault', 'x': 0, 'y': 0, 'z': 0, 'form': 'real', 'item_uid': ''},
        {'location': 'floating', 'mode': 'guard', 'x': 1, 'y': 0, 'z': 0, 'form': 'projected', 'item_uid': ''}]}
    monkeypatch.setattr(swords, 'owned', lambda engine, a, source=swords.TWIN: True)
    monkeypatch.setattr(swords, 'state', lambda a: state)
    monkeypatch.setattr(needle, 'ask', lambda *a, **k: [ally.entity_id])
    monkeypatch.setattr(relations, 'relation', lambda e, a, b: 'ALLY')
    swords.second_sword_guard(engine, owner)
    engine._add_modifier.assert_called_once()
    args = engine._add_modifier.call_args
    assert args.args[0] is ally and args.args[2] == 'armor_class_vs_ranged' and args.args[4] == 2


# Finding 5: the one-hour manifestation clock survives journey continuation as remaining rounds.
def test_manifestation_clock_carries_into_the_next_journey_fight(monkeypatch):
    engine = _engine(round_number=7)
    clock = round_token(engine, 3)  # SLOT_AT:10:0
    marker = 'condition:typed.twin_sword_manifest_1'
    actor = _actor(conditions={'x': SimpleNamespace(condition_id=marker, expires_on=clock, source_actor_id='actor:sword')})
    state = {'swords': [{'location': 'carried', 'mode': 'assault', 'x': 0, 'y': 0, 'z': 0, 'form': 'real', 'item_uid': ''},
                        {'location': 'floating', 'mode': 'assault', 'x': 0, 'y': 0, 'z': 0, 'form': 'projected', 'item_uid': '',
                         'manifest_condition': marker}]}
    monkeypatch.setattr(swords, 'owned', lambda engine, a, source=swords.SEED: True)
    monkeypatch.setattr(swords, 'state', lambda a: state)
    session = SimpleNamespace(state={'actors': {'actor:sword': {}}})
    swords.source_continuation(session, 'actor:sword', engine, actor)
    exported = session.state['actors']['actor:sword']['source_states'][swords.FAMILY]
    assert exported['manifest_seconds'] == {'1': '18'}
    assert 'manifest_rounds' not in exported

    restored = _engine(round_number=0)
    restored_actor = _actor()
    applied = []
    fresh = {'swords': [{'location': 'carried', 'mode': 'assault', 'x': 0, 'y': 0, 'z': 0, 'form': 'real', 'item_uid': ''},
                        {'location': 'floating', 'mode': 'assault', 'x': 0, 'y': 0, 'z': 0, 'form': 'projected', 'item_uid': ''}]}
    monkeypatch.setattr(swords, 'state', lambda a: fresh)
    monkeypatch.setattr(swords, 'save', lambda *a, **k: None)
    monkeypatch.setattr(restored, '_apply_condition', lambda actor_, cid, src, owner, expires_on=None, data=None: applied.append((cid, expires_on)))
    swords.restore_manifests(restored, restored_actor, exported)
    assert applied == [(marker, round_token(restored, 3))]
