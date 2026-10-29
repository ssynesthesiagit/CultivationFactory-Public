"""A2R23F21: non-blocking review items on the Athletics round (A2R23RB3R2 review).

Each test pins one review item and fails on the pre-fix code:
- rope swing refusals say why (no silent return);
- the attach and swing notes write the height as "(N feet up)", not glued to the coordinate;
- dash_reach rejects a malformed dash_bonus_ft answer instead of ignoring it.
"""
from types import SimpleNamespace

import pytest

from combat import flight
from combat.ext import athletics
from combat.gate2_runtime_models import Position


class _Grid:
    square_size_ft = 5
    width = 12
    height = 8

    def distance_ft(self, a, b):
        return 5 * max(abs(a.x - b.x), abs(a.y - b.y), abs(a.z - b.z))

    def placement_legal(self, *args, **kwargs):
        return True


class _Engine:
    def __init__(self, speed):
        self.grid = _Grid()
        self._speed = speed
        self.notes = []

    def _effective_speed(self, actor):
        return self._speed

    def _footprint(self, actor):
        return None

    def _occupied_cells_except(self, actor_id):
        return ()


def _actor(anchor=(8, 4, 3)):
    swing = SimpleNamespace(condition_id=athletics.ROPE_SWING_CONDITION,
                            source_definition_id=athletics.ROPE_SWING,
                            data={"anchor": list(anchor)})
    return SimpleNamespace(entity_id="actor:fighter", display_name="Fighter",
                           position=Position(x=8, y=4, z=0), conditions={"swing": swing})


def _ctx(engine, actor):
    riders = []
    return SimpleNamespace(engine=engine, actor=actor, typed={"source": athletics.ROPE_SWING},
                           intent=None, rider=riders.append), riders


def test_zero_climbing_allowance_tells_the_player_why(monkeypatch):
    monkeypatch.setattr(athletics, "note", lambda *args, **kwargs: None)
    engine = _Engine(speed=0)
    ctx, riders = _ctx(engine, _actor())
    athletics.rope_swing_climb(ctx, {})
    assert riders == ["No climbing allowance remains, so the swing cannot carry the fighter to the anchor."]


def test_spent_climbing_allowance_tells_the_player_why(monkeypatch):
    from combat import granted_movement, roof_movement, flight as flight_mod
    monkeypatch.setattr(athletics, "note", lambda *args, **kwargs: None)
    monkeypatch.setattr(granted_movement, "path_cost", lambda engine, actor, route: 999)
    monkeypatch.setattr(flight_mod, "remaining", lambda engine, actor, mode: 0)

    class _Cap:
        def __enter__(self): return None
        def __exit__(self, *exc): return False

    monkeypatch.setattr(roof_movement, "climb_route_capability", lambda *args, **kwargs: _Cap())
    engine = _Engine(speed=30)
    ctx, riders = _ctx(engine, _actor())
    athletics.rope_swing_climb(ctx, {})
    assert riders == ["No climbing allowance remains, so the swing cannot carry the fighter to the anchor."]


def test_attach_note_names_the_height_as_feet_up(monkeypatch):
    written = []
    monkeypatch.setattr(athletics, "note", lambda engine, source, actor, text: written.append(text))
    monkeypatch.setattr(athletics, "rope_swing_gear", lambda engine, actor: ["Rope"])
    monkeypatch.setattr(athletics, "ask_anchor", lambda ctx: Position(x=8, y=4, z=6))
    monkeypatch.setattr(athletics, "_drop_condition", lambda *args, **kwargs: None)
    engine = _Engine(speed=30)
    engine._apply_condition = lambda *args, **kwargs: None
    actor = _actor()
    ctx = SimpleNamespace(engine=engine, actor=actor, typed={"source": athletics.ROPE_SWING},
                          intent=None, rider=lambda text: None)
    athletics.rope_swing_attach(ctx, {})
    assert written == ["Fighter attaches its rope swing to the square at 8,4 (30 feet up)."]


def test_dash_bonus_answer_must_be_a_non_negative_int(monkeypatch):
    engine = _Engine(speed=30)
    actor = _actor()
    monkeypatch.setattr(flight, "profile", lambda engine, actor, **kw: SimpleNamespace(speed_ft=0))
    from combat import roof_movement
    monkeypatch.setattr(roof_movement, "profile", lambda engine, actor, **kw: SimpleNamespace(speed_ft=0))
    from combat import ext
    for bad in (True, 2.5, -10):
        monkeypatch.setattr(ext, "run_strict", lambda point, *a, **k: [bad])
        with pytest.raises(ValueError):
            flight.dash_reach(engine, actor)
    # run_strict already drops None answers, so only real ints reach dash_reach.
    monkeypatch.setattr(ext, "run_strict", lambda point, *a, **k: [10])
    assert flight.dash_reach(engine, actor) == 40
