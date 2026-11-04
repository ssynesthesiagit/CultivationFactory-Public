"""Public synthetic regression for Split the Chain's printed source exclusion."""
from types import SimpleNamespace

from combat.ext.axes_split_chain import _cultivated, split


def test_split_the_chain_keeps_secret_cultivation_restraint_on_five_over(monkeypatch):
    source_id = "action:typed.air.CYCLONE_PRISON"
    held = SimpleNamespace(
        condition_id="condition:typed.restrained",
        source_actor_id="actor:foe",
        source_definition_id=source_id,
    )
    source = SimpleNamespace(parameters={"typed": {
        "source": "TAL_AIR_CYCLONE_PRISON",
        "source_category": "Secret Inheritance",
        "sphere": "tianxia.sphere.air",
        "weapon": None,
        "numbers": {"save_dc": 15},
    }})
    engine = SimpleNamespace(action_catalog={source_id: source})
    holder = SimpleNamespace(entity_id="actor:ally", conditions={"restrained-1": held})

    rows = _cultivated(engine, holder)

    assert rows == [("restrained-1", held, 15, False)]

    from combat import typed_executor

    effects = []
    monkeypatch.setattr(typed_executor, "run_effects", lambda _ctx, rows: effects.extend(rows))
    context = SimpleNamespace(engine=engine, target=holder, actor=SimpleNamespace(entity_id="actor:axe"))
    split(context, {})

    assert effects[0]["on_success_by_5"][0]["end"] is False
