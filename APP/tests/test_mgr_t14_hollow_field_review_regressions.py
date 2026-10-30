from types import SimpleNamespace

from combat.ext import void_touched_cultivator as cultivator
from combat.ext import void_touched_hollow_field as hollow


def test_trace_turn_token_uses_current_slot_not_recipient_turn_count():
    engine = SimpleNamespace(state=SimpleNamespace(round_number=4, current_slot_index=2))
    target = SimpleNamespace(turns_started=0)
    first = cultivator._turn(engine, target)
    engine.state.current_slot_index = 3
    assert cultivator._turn(engine, target) != first


def test_active_talent_requires_a_live_source_owned_contribution():
    action = SimpleNamespace(source_definition_id="action:void.shell",
                             parameters={"typed": {"source": "talent:void.shell"}})
    ended = SimpleNamespace(entity_id="ended", conditions={}, modifiers={})
    engine = SimpleNamespace(state=SimpleNamespace(zones={}, actors={"ended": ended}))
    assert not hollow._has_live_talent_effect(engine, ended, action)

    live = SimpleNamespace(entity_id="live", conditions={"shell": SimpleNamespace(
        source_definition_id="action:void.shell", data={})}, modifiers={})
    engine.state.actors["live"] = live
    assert hollow._has_live_talent_effect(engine, live, action)


def test_deepen_repeat_save_runs_at_another_creatures_turn_end(monkeypatch):
    target = SimpleNamespace(entity_id="target", display_name="Target", conditions={})
    condition = SimpleNamespace(condition_id=hollow.SYSTEM, data={"cl": 10, "zone": "field", "label": "Sphere"})
    target.conditions["suppression"] = condition
    ending = SimpleNamespace(entity_id="ending-creature", conditions={})
    zone = SimpleNamespace(active=True, source_definition_id="field-source")
    rolled = []
    released = []
    engine = SimpleNamespace(
        state=SimpleNamespace(actors={"target": target, "ending": ending}, zones={"field": zone}),
        _roll_save=lambda actor, ability, dc, source: (rolled.append(actor.entity_id)
                                                       or SimpleNamespace(total=dc)),
    )
    monkeypatch.setattr(hollow, "creature_cl", lambda _engine, actor: 13 if actor is target else 1)
    monkeypatch.setattr(hollow, "_field_dc", lambda _zone: 15)
    monkeypatch.setattr(hollow, "_release_system",
                        lambda _engine, actor, held, _reason: released.append((actor.entity_id, held)))
    monkeypatch.setattr(hollow, "_note", lambda *_args: None)

    hollow.deepen_repeat_save(engine, ending)

    assert rolled == ["target"]
    assert released == [("target", condition)]


def test_recovery_detection_reads_typed_gain_effect_not_feature_name(monkeypatch):
    from pathlib import Path
    from combat import factory_compiler
    original = factory_compiler.TYPED_AUTHORITY
    # The helper resolves typed semantics from the current authority, so provide a
    # tiny synthetic authority without depending on the player's local data.
    class Authority:
        def read_text(self, **kwargs):
            return '{"mechanics":{"tianxia.path.qi_cultivation.feature.immortal_of_qi":' \
                   '{"effects":[{"type":"gain_resource","resource":"resource:core.qi"}]}}}'
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", Authority())
    engine = object()
    assert hollow._is_recovery(engine, "tianxia.path.qi_cultivation.feature.immortal_of_qi", "Immortal of Qi")
    assert not hollow._is_recovery(engine, "tianxia.sphere.void.feature.test", "Regain")
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", original)
