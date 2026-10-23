"""A nested sanctuary recovery during No Guest Dies Alone must preserve healing."""
from types import SimpleNamespace

from combat.ext import qi_welcoming_flame as flame
from combat.typed_executor import Context


def test_zero_hp_step_keeps_a_late_entry_recovery(monkeypatch):
    owner = SimpleNamespace(entity_id="owner", display_name="Owner")
    guest = SimpleNamespace(entity_id="guest", display_name="Guest", current_hp=0)
    zone = SimpleNamespace(per_turn_triggered={})
    engine = SimpleNamespace(
        events=[SimpleNamespace(event_type="DAMAGE_COMMITTED", target_ids=("guest",),
                                payload={"hp_before": 4, "hp_damage": 4})],
        state=SimpleNamespace(actors={"owner": owner}),
    )
    engine._apply_condition = lambda *args, **kwargs: None
    engine._set_life_state = lambda target, state, source: setattr(target, "life_state", state)
    ctx = Context(engine=engine, actor=owner, action=None, intent=None, typed={}, targets=[guest], target=guest)

    monkeypatch.setattr(flame, "fields", lambda _engine: [zone])
    monkeypatch.setattr(flame, "protects", lambda _engine, _zone, _target: True)
    monkeypatch.setattr(flame, "context", lambda *_args, **_kwargs: ctx)
    monkeypatch.setattr("combat.pending_damage.current", lambda _engine: SimpleNamespace(
        target_id="guest", source_id="damage-source"))
    monkeypatch.setattr("combat.life_state.massive", lambda *_args: 100)
    monkeypatch.setattr("combat.ext.retained_updates.record_zone_update", lambda *_args: None)
    monkeypatch.setattr("combat.typed_executor.run_effects", lambda *_args: None)

    def recover_during_step(step_ctx, _row):
        # The second sanctuary's late-entry Homefire Recovery resolves inside this
        # granted movement and restores the guest to ordinary living status.
        step_ctx.actor.current_hp = 1
        step_ctx.actor.life_state = None

    monkeypatch.setattr("combat.rider_step.step", recover_during_step)
    result = flame.no_guest_dies_alone(engine, guest, "damage-source", None)

    assert guest.current_hp == 1
    assert guest.life_state == "CONSCIOUS"
    assert result == "CONSCIOUS"
