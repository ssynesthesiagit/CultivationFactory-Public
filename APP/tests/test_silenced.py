"""Silencing is real (owner 2026-09-29): Silenced blocks abilities that need a voice (combat/speech.py), Breath Seal and
Locked Breath Method silence and press Concentration (combat/concentration.py save_mode), Speech-Knot Point fails the next
voiced ability. combat/ext/speech.py."""

import json

from combat import concentration, speech, typed_executor
from combat.ext import speech as speech_ext
from combat.factory_compiler import TYPED_AUTHORITY
from combat.gate2_runtime_content import AN
from tests.test_auto_docket import DARK, ME, _fight, _names, _sheet

MECH = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]


def _ctx(engine, actor_id, target_id):
    action = next(iter(engine.action_catalog.values()))
    return typed_executor.Context(engine, engine.state.actors[actor_id], action, None, {"numbers": {"pb": 4, "save_dc": 15}},
                                  [engine.state.actors[target_id]], engine.state.actors[target_id], {})


def _voiced(monkeypatch, record):
    monkeypatch.setattr(speech, "rules", lambda: {"needs_voice": {record: {"name": "test", "why": "you roar"}}})


def test_a_silenced_fighter_is_not_offered_an_ability_that_needs_its_voice(monkeypatch):
    engine = _fight(_sheet([*DARK]))
    _voiced(monkeypatch, "DARK_BASE_DARKNESS")
    assert "Darkness" in _names(engine)
    typed_executor.run_effects(_ctx(engine, AN, ME), [{"type": "condition", "condition": "silenced", "applies_to": "target", "expires_on": "UNTIL_REMOVED"}])
    assert speech.silenced(engine.state.actors[ME]) and "Darkness" not in _names(engine)


def test_breath_seal_silences_and_presses_concentration():
    engine = _fight(_sheet([*DARK]))
    foe = engine.state.actors[AN]
    seal = MECH["tianxia.talent.pressure_points.breath_seal"]["effects"][0]
    typed_executor.run_effects(_ctx(engine, ME, AN), seal["on_fail"])
    assert speech.silenced(foe)
    engine._start_concentration(foe, "action:held")
    engine._concentration_check(foe, 4)
    rolled = next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED")
    assert rolled.payload["mode"] == "DISADVANTAGE"


def test_a_next_concentration_disadvantage_is_used_up():
    engine = _fight(_sheet([*DARK]))
    foe = engine.state.actors[AN]
    typed_executor.run_effects(_ctx(engine, ME, AN), [{"type": "disadvantage", "applies_to": "target", "on": "its next Concentration saving throw"}])
    assert concentration.save_mode(engine, foe) == "DISADVANTAGE"
    assert concentration.save_mode(engine, foe) is None


def test_speech_knot_fails_the_next_voiced_ability_before_its_cost_is_spent(monkeypatch):
    engine = _fight(_sheet([*DARK, "TAL_DARK_DARKVISION", "TAL_DARK_CLEARSIGHT"]))  # its Meld actions cost 1 Qi
    from tests.test_auto_docket import _do, _my_turn
    _do(engine, 'Darkness', at=(3, 6))
    _my_turn(engine)
    me = engine.state.actors[ME]
    action = next(engine.action_catalog[c.source_definition_id] for c in engine.legal_candidates()
                  if c.source_definition_id in engine.action_catalog and engine.action_catalog[c.source_definition_id].costs)
    _voiced(monkeypatch, str((action.parameters.get("typed") or {}).get("option_of") or (action.parameters.get("typed") or {}).get("source")))
    typed_executor.run_effects(_ctx(engine, AN, ME), [{"type": "speech_knot", "applies_to": "target"}])
    resource, amount = action.costs[0]
    before = me.resources.get(resource, 0)
    economy = me.action_available, me.bonus_action_available
    sequence = len(engine.events)

    class Low:
        total = 1
    monkeypatch.setattr(engine, "_roll_save", lambda *args, **kwargs: Low())
    from combat.gate2_runtime_models import ActionIntent
    c = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id)
    engine.execute_intent(ActionIntent(intent_id='knotted', decision_id=c.decision_id, candidate_id=c.candidate_id,
        state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination))
    assert me.resources.get(resource, 0) == before and not any(c.condition_id == speech.SPEECH_KNOT for c in me.conditions.values())
    assert (me.action_available, me.bonus_action_available) == economy
    assert not any(e.event_type in {'RESOURCE_SPENT', 'RESOURCE_GAINED'} and e.actor_id == ME for e in engine.events[sequence:])


def test_locked_breath_forces_a_concentration_save_that_can_end_it(monkeypatch):
    engine = _fight(_sheet([*DARK]))
    foe = engine.state.actors[AN]
    engine._start_concentration(foe, "action:held")

    class Low:
        total = 1
    monkeypatch.setattr(engine, "_roll_save", lambda *args, **kwargs: Low())
    locked = MECH["tianxia.talent.pressure_points.locked_breath_method"]["effects"][0]
    typed_executor.run_effects(_ctx(engine, ME, AN), locked["on_fail"])
    assert speech.silenced(foe) and foe.concentration is None
