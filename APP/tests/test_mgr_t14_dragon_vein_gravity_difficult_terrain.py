"""Regression for the Dragon-Vein Gravity Circuit's hostile difficult terrain."""
from types import SimpleNamespace

from combat.ext import dragon_vein_geomancer as dv
from combat.gate2_runtime_models import Position


def test_gravity_anchor_adds_one_square_cost_to_hostile_walking(monkeypatch):
    owner = SimpleNamespace(entity_id="geomancer", position=Position(x=0, y=0, z=0))
    hostile = SimpleNamespace(entity_id="hostile", position=Position(x=1, y=0, z=0))
    anchor = object()
    engine = SimpleNamespace(
        state=SimpleNamespace(actors={"owner": owner, "hostile": hostile}),
        grid=SimpleNamespace(square_size_ft=5),
    )
    monkeypatch.setattr(dv, "kit", lambda engine, actor: {"owned": [dv.CIRCUIT]} if actor is owner else None)
    monkeypatch.setattr(dv, "anchors", lambda engine, actor: [anchor] if actor is owner else [])
    monkeypatch.setattr(dv, "modes", lambda engine, actor, obj: ("gravity",))
    monkeypatch.setattr(dv, "covers", lambda engine, actor, obj, cell: True)
    monkeypatch.setattr("combat.relations.relation",
                        lambda engine, source, target: "ENEMY" if source is owner else "SELF")

    assert dv.gravity_movement_surcharge(engine, hostile, "walk") == 5
    assert dv.gravity_movement_surcharge(engine, hostile, "flight") is None
