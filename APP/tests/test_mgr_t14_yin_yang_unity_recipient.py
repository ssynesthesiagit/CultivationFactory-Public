"""Public synthetic regressions for Unity recipient eligibility (no Git history)."""
from types import SimpleNamespace


def test_unity_healing_offers_another_eligible_ally_when_one_is_spent(monkeypatch):
    from combat.ext import yin_yang_cultivator as yy

    stamp = (2, "turn")
    owner = SimpleNamespace(entity_id="owner", display_name="Unity owner", turn_flags={}, active=True)
    used = SimpleNamespace(entity_id="used", display_name="Already healed", turn_flags={"_round_unity_received": stamp}, active=True)
    available = SimpleNamespace(entity_id="available", display_name="Other ally", turn_flags={}, active=True)
    engine = SimpleNamespace(
        state=SimpleNamespace(actors={a.entity_id: a for a in (owner, used, available)}),
        _distance_actor_to_actor=lambda _source, _target: 5,
    )
    engine.state.round_number = 2
    ctx = SimpleNamespace(engine=engine, actor=owner, action=SimpleNamespace(display_name="Qi technique"))

    monkeypatch.setattr(yy, "_stamp", lambda _engine: stamp)
    monkeypatch.setattr(yy, "owns", lambda *_args: {"numbers": {"pb": 3}})
    monkeypatch.setattr(yy, "known_recipients", lambda *_args: [owner, used, available])
    monkeypatch.setattr(yy, "relation", lambda _engine, _target, _owner: yy.ALLY)
    offered = {}

    def choose(_engine, _actor, _key, _ability, options, **_kwargs):
        offered["options"] = list(options)
        return ["available"]

    import combat.ext.rider_choices as rider_choices
    monkeypatch.setattr(rider_choices, "pick", choose)
    monkeypatch.setattr(yy, "feature_context", lambda *_args: object())
    healed = []
    # run_effects is imported inside the function, so patch its source module.
    import combat.typed_executor as typed_executor
    monkeypatch.setattr(typed_executor, "run_effects", lambda _ctx, effects: healed.append(effects))

    yy.unity_healing(ctx)

    assert offered["options"] == ["available"]
    assert owner.turn_flags["_round_unity_healing"] == stamp
    assert available.turn_flags["_round_unity_received"] == stamp
    assert used.turn_flags["_round_unity_received"] == stamp
    assert len(healed) == 1
