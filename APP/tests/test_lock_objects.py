import json
import pytest

from combat import ext
from combat.gate2_runtime_models import RuntimeObjectState, Position, ActionIntent
from combat.gate3_reducer import Gate3EventReducer
from tests.test_auto_tabik import _engine, ME


def obj(**extra):
    return RuntimeObjectState(object_id="object:eye", object_kind="TEST", position=Position(x=4, y=6),
                              unattended=True, flammable=False, **extra)


def test_legacy_object_serialization_omits_all_new_fields():
    old = dict(object_id="object:eye", object_kind="TEST", position={"x": 4, "y": 6},
               unattended=True, flammable=False, ignited=False, ignition_source_definition_id=None,
               ignition_actor_id=None, ignition_sequence=None)
    assert obj().model_dump(mode="json") == old
    assert json.loads(obj().model_dump_json()) == old
    with pytest.raises(ValueError, match="exceeds"):
        obj(current_hp=4, maximum_hp=3)


def setup(monkeypatch):
    e, _ = _engine([])
    o = obj(ac=13, current_hp=10, maximum_hp=10, damage_immunities=("POISON", "PSYCHIC"))
    e.state.objects[o.object_id] = o
    action = next(e.action_catalog[aid] for aid in e.state.actors[ME].action_ids
                  if e.action_catalog[aid].target_kind == "HOSTILE_ENTITY"
                  and e.action_catalog[aid].economy == "ACTION"
                  and not e.action_catalog[aid].parameters.get("requires_condition"))
    action = action.model_copy(update={"range_ft": 10})
    e.action_catalog[action.source_definition_id] = action
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "object_targets", [
        lambda engine, actor, a: [o.object_id] if a.source_definition_id == action.source_definition_id else []])
    return e, o, action


def test_object_candidates_explicit_only_range_and_destroyed(monkeypatch):
    e, o, action = setup(monkeypatch)
    assert any(c.target_ids == (o.object_id,) for c in e.legal_candidates())
    o.position = Position(x=20, y=20)
    assert not any(c.target_ids == (o.object_id,) for c in e.legal_candidates())
    o.position = Position(x=4, y=6)
    o.destroyed = True
    assert not any(c.target_ids == (o.object_id,) for c in e.legal_candidates())
    o.destroyed = False
    monkeypatch.setitem(ext._HOOKS, "object_targets", [])
    assert not any(c.target_ids == (o.object_id,) for c in e.legal_candidates())


def test_object_dispatch_economy_and_replay(monkeypatch):
    e, o, action = setup(monkeypatch)
    before = e.state.model_copy(deep=True)
    n = len(e.events)
    def resolve(engine, actor, a, target, candidate, intent):
        assert target.object_id == o.object_id
        assert not actor.action_available
        engine._update_object(target.model_copy(update={"current_hp": 0, "destroyed": True}), a.source_definition_id, actor.entity_id)
        return True
    monkeypatch.setitem(ext._HOOKS, "object_action", [resolve])
    c = next(c for c in e.legal_candidates() if c.target_ids == (o.object_id,))
    e.execute_intent(ActionIntent(intent_id="test:object", candidate_id=c.candidate_id, decision_id=c.decision_id,
                                 state_version=c.state_version, actor_id=ME, target_ids=c.target_ids))
    assert e.state.objects[o.object_id].destroyed
    reducer = Gate3EventReducer()
    for event in e.events[n:]:
        reducer.apply_event(before, event)
    assert before.objects[o.object_id].model_dump() == e.state.objects[o.object_id].model_dump()


def test_unhandled_object_rolls_back_costs(monkeypatch):
    e, o, action = setup(monkeypatch)
    monkeypatch.setitem(ext._HOOKS, "object_action", [])
    c = next(c for c in e.legal_candidates() if c.target_ids == (o.object_id,))
    before = e.state.model_dump(mode="json")
    with pytest.raises(Exception, match="No object resolver"):
        e.execute_intent(ActionIntent(intent_id="test:object", candidate_id=c.candidate_id, decision_id=c.decision_id,
                                     state_version=c.state_version, actor_id=ME, target_ids=c.target_ids))
    assert e.state.model_dump(mode="json") == before


def test_objects_use_weapon_reach_when_range_is_unset(monkeypatch):
    e, o, action = setup(monkeypatch)
    o.position = Position(x=5, y=6)
    action = action.model_copy(update={"range_ft": None, "reach_ft": 10})
    e.action_catalog[action.source_definition_id] = action
    assert any(c.target_ids == (o.object_id,) for c in e.legal_candidates())
