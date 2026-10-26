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
    ended = SimpleNamespace(conditions={}, modifiers={})
    engine = SimpleNamespace(state=SimpleNamespace(zones={}))
    assert not hollow._has_live_talent_effect(engine, ended, action)

    live = SimpleNamespace(conditions={"shell": SimpleNamespace(
        source_definition_id="action:void.shell", data={})}, modifiers={})
    assert hollow._has_live_talent_effect(engine, live, action)


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
