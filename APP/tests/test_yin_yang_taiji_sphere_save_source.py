"""Regression for resolving a Sphere talent's save source to its typed authority row."""

from types import SimpleNamespace

from combat.ext import yin_yang_cultivator as yy


def test_yang_field_qualifies_canonical_sphere_talent_source(monkeypatch):
    owner = SimpleNamespace(entity_id="field-owner")
    target = SimpleNamespace(entity_id="save-target", turn_flags={})
    action = SimpleNamespace(
        owner_id="caster",
        source_definition_id="activation:fireball",
        parameters={"typed": {"source": "action:generated-fireball",
                              "option_of": "FIRE_TAL_FIREBALL_ART"}},
    )
    engine = SimpleNamespace(
        state=SimpleNamespace(actors={"target": target, "caster": SimpleNamespace(entity_id="caster")}),
        action_catalog={"activation:fireball": action},
        d20_context=lambda roll: {"kind": "save", "source_actor_id": "caster",
                                  "source_id": "FIRE_TAL_FIREBALL_ART"},
    )
    roll = SimpleNamespace(actor_id="target")
    monkeypatch.setattr(yy, "_stamp", lambda engine: 7)
    monkeypatch.setattr(yy, "field_owners", lambda *args, **kwargs: [owner])
    monkeypatch.setattr(yy, "relation", lambda *args, **kwargs: yy.ALLY)
    monkeypatch.setattr(yy, "owns", lambda *args, **kwargs: {"numbers": {"pb": 3}})
    monkeypatch.setattr(yy, "feature_context", lambda *args, **kwargs: object())
    monkeypatch.setattr("combat.typed_executor._roll", lambda *args, **kwargs: 2)
    monkeypatch.setattr("combat.typed_numbers.authority_mechanics",
                        lambda: {"FIRE_TAL_FIREBALL_ART": {"sphere_id": "tianxia.sphere.fire"}})

    result = yy.field_save_penalty(engine, roll, None)

    assert result == {"source_id": yy.PREFIX + "taiji_field",
                      "user_id": owner.entity_id, "bonus": -2}
    assert target.turn_flags["_round_taiji_save"] == 7
