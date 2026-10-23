"""The three lead addendum questions, using only public synthetic fixtures."""
import json

import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate3_artifacts import build_gate3_artifacts, _SCHEMA_MODELS
from combat.gate3_models import Gate3AbortRecord
from combat.gate5_service import CombatService
from combat.object_interaction import used
from tests.test_mgr_t14_cultivator_of_seals_floor58 import ROOT, ME, MINOR, act, setup


def test_abort_record_generator_and_action_intent_fields_are_in_sync(tmp_path):
    # Source of truth: gate3_artifacts._SCHEMA_MODELS -> Gate3AbortRecord ->
    # gate2_runtime_models.ActionIntent. No history/private artifact is needed.
    manifest = build_gate3_artifacts(tmp_path)
    filename = next(name for name, model in _SCHEMA_MODELS.items() if model is Gate3AbortRecord)
    generated = json.loads((tmp_path / 'generated' / 'schemas' / filename).read_text())
    assert generated == Gate3AbortRecord.model_json_schema(by_alias=True)
    intent = generated['$defs']['ActionIntent']
    runtime = ActionIntent.model_json_schema(by_alias=True)
    assert intent['properties'] == runtime['properties']
    assert set(intent['required']) == {k for k, field in ActionIntent.model_fields.items() if field.is_required()}
    assert {'placement_destination', 'movement_mode'} <= set(intent['properties'])
    assert intent['additionalProperties'] is False
    assert manifest['runtime_schema_sha256'][filename] == canonical_sha256(generated)


@pytest.mark.parametrize('opening', [True, False])
def test_thread_simple_door_runs_the_same_operation_gate_for_open_and_close(monkeypatch, opening):
    # Printed PUPPETRY_BASE_THREAD_THE_OBJECT explicitly permits "open or close".
    from combat.ext import thread_object as thread, needle
    from tests.test_r3i_thread_object import _sheet
    from tests.test_sysv2_objects import fight, ME as OWNER
    from combat.factory_compiler import compile_character
    engine = fight(compile_character(_sheet(), actor_id=OWNER), objects=[{
        'id': 1, 'kind': 'door', 'x': 4, 'y': 6, 'interaction': 'simple_door',
        'weight_lb': 10, 'door_open': int(not opening), 'door_locked': 0, 'door_jammed': 0}])
    actor = engine.state.actors[OWNER]
    action = next(a for a in engine.action_catalog.values() if a.parameters.get('thread_object_door'))
    obj = engine.state.objects['object:map.1']
    calls = []
    original = ext.run_strict
    def deny(name, *args):
        if name == 'object_operation_gate':
            calls.append(args[3])
            return [False]
        return original(name, *args)
    monkeypatch.setattr(ext, 'run_strict', deny)
    monkeypatch.setattr(needle, 'ask', lambda *a, **k: ['OPEN' if opening else 'CLOSE'])
    assert thread._door(engine, actor, action, obj, None)
    assert calls == ['open' if opening else 'close']
    assert engine.state.objects[obj.object_id].component['door_open'] == int(not opening)


def test_denied_free_door_neither_spends_nor_refunds_action_or_interaction_after_reload(tmp_path):
    _, session = setup(tmp_path)
    seal = next(c for c in session.engine.legal_candidates()
        if (a := session.engine.action_catalog.get(c.source_definition_id))
        and (a.parameters.get('typed') or {}).get('source') == MINOR)
    act(session, seal)
    for _ in range(2):
        act(session, next(c for c in session.engine.legal_candidates() if c.kind.value == 'END_TURN'))
    session = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    before = session.engine.state.actors[ME].model_dump(mode='json')
    first = len(session.engine.events)
    act(session, next(c for c in session.engine.legal_candidates()
                      if c.source_definition_id == 'system:door.open.free'))
    session = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    actor = session.engine.state.actors[ME]
    assert actor.action_available and not used(actor)
    assert actor.resources == before['resources']
    assert actor.action_available == before['action_available']
    assert session.engine.state.objects['object:map.1'].component['door_open'] == 0
    denied = session.engine.events[first:]
    assert not any(e.event_type in {'RESOURCE_SPENT', 'RESOURCE_GAINED', 'ONCE_PER_TURN_CLAIMED'}
                   for e in denied)
    assert any(c.source_definition_id == 'system:door.open.free' for c in session.engine.legal_candidates())
    assert session.mechanical.replay()['status'] == 'PASS'
