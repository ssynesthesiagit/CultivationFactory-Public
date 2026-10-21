import pytest

from combat.directional_cover import crossed_edges, cover_bonus
from combat.gate2_runtime_models import Position
from tests.test_auto_tabik import _engine, ME, AN
from tests.test_lock_choices import install, intent


@pytest.mark.parametrize("start,end,edge", [((0, 0), (1, 0), "W"), ((1, 0), (0, 0), "E"),
    ((0, 0), (0, 1), "N"), ((0, 1), (0, 0), "S")])
def test_cardinal_entry_edges(start, end, edge):
    assert crossed_edges(start, end)[-1] == {"cell": list(end), "edge": edge, "direction": "enter"}


def test_vertex_crossing_two_edges_without_grazed_squares():
    rows = crossed_edges((0, 0), (1, 1))
    assert {r["edge"] for r in rows if r["direction"] == "enter"} == {"N", "W"}
    assert {tuple(r["cell"]) for r in rows} == {(0, 0), (1, 1)}
    assert crossed_edges((1, 1), (1, 1)) == []


@pytest.mark.parametrize("ranged", [True, False])
def test_front_edge_cover_changes_ac_for_melee_and_ranged(monkeypatch, ranged):
    e, _ = _engine([], foe_at=(4, 6))
    a, t = e.state.actors[ME], e.state.actors[AN]
    def facing(engine, attacker, target, ray):
        return 2 if {"cell": [4, 6], "edge": "W", "direction": "enter"} in ray["crossed_edges"] else 0
    install(monkeypatch, "directional_cover", facing)
    install(monkeypatch, "d20_result", lambda *a: {"source_id": "test:roll", "operation": "replace", "natural_result": 10})
    spec = {"attack_bonus": t.armor_class - 10, "reach_ft": 5, "range_ft": 5 if ranged else None}
    assert not e._resolve_attack_spec(a, t, spec, intent(e), source_definition_id="test:front")
    assert next(ev for ev in reversed(e.events) if ev.event_type == "ATTACK_ROLLED").payload["cover_bonus"] == 2
    a.position = Position(x=5, y=6)
    assert cover_bonus(e, a, t, ranged=ranged) == 0


def test_best_clear_footprint_ray_and_terrain_are_combined_per_ray(monkeypatch):
    e, _ = _engine([], foe_at=(6, 6))
    a, t = e.state.actors[ME], e.state.actors[AN]
    original = e._actor_cells
    monkeypatch.setattr(e, "_actor_cells", lambda actor: ((3, 6), (3, 7)) if actor is a else original(actor))
    install(monkeypatch, "directional_cover", lambda engine, attacker, target, ray: 2 if ray["start"] == [3, 6] else 0)
    assert cover_bonus(e, a, t, ranged=False) == 0
    # Independently controlled terrain path, to isolate min(max(terrain, edge)) from max(min(...)).
    monkeypatch.setattr(e.grid, "cover_bonus", lambda start, end: 2 if start.y == 7 else 0)
    assert cover_bonus(e, a, t, ranged=True) == 2


def test_no_hook_exact_base_and_invalid_value(monkeypatch):
    e, _ = _engine([], foe_at=(4, 6))
    a, t = e.state.actors[ME], e.state.actors[AN]
    install(monkeypatch, "directional_cover", lambda *a: None)
    assert cover_bonus(e, a, t, ranged=False, base=5) == 5
    monkeypatch.setattr(e.grid, "cover_bonus", lambda *args: 2)
    assert cover_bonus(e, a, t, ranged=True, base=0) == 0
    install(monkeypatch, "directional_cover", lambda *a: -2)
    with pytest.raises(ValueError, match="directional cover"):
        cover_bonus(e, a, t, ranged=False)
