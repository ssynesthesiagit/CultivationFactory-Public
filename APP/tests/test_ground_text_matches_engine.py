"""MMX96f1: the ground hover card must describe the rule the engine actually runs.

The card's words are written once, in ``combat/ground_text.py``, so a line on the card is only
allowed to say what the engine does. These tests drive the real mechanic first and then assert the
catalog says it -- a card that advises a player wrongly is a bug in itself: a fighter who follows
"standing in cover makes you harder to hit" occupies a cover square and gets no bonus at all, while
the cover that *would* protect them (the square between them and the attacker) is never mentioned.

The client wiring and the two-second rest are covered by tests/ground_hover_board.test.mjs; this
file covers the words. No fight behaviour is changed by the lane, so no replay changes.
"""
from __future__ import annotations

from combat import ground_text
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from tests import lock8_support as S


def _grid(*regions: tuple[str, list[tuple[int, int]], int]) -> SquareGrid:
    """A real 12x12 open battlefield with the given terrain regions painted on it."""
    return SquareGrid({
        "width_squares": 12, "height_squares": 12, "square_size_ft": 5,
        "starting_positions": {},
        "terrain_regions": [{"terrain_type": kind, "movement_cost": cost, "cells": [{"x": x, "y": y} for x, y in cells]}
                            for kind, cells, cost in regions],
    })


def _lines(key: str) -> str:
    return " ".join(ground_text.catalog()[key]["lines"])


# --------------------------------------------------------------------- cover

def test_cover_is_worth_two_only_while_it_sits_between_the_two():
    """The engine's own geometry: +2 Armor Class when a cover square lies strictly BETWEEN them --
    the ray's own endpoints are excluded, so standing in the cover square protects nobody."""
    grid = _grid(("SIMPLE_COVER", [(2, 2)], 1))
    assert grid.cover_bonus(Position(x=0, y=2), Position(x=4, y=2)) == 2
    # The target standing in the cover square itself gets nothing: that square is the ray's end.
    assert grid.cover_bonus(Position(x=2, y=2), Position(x=4, y=2)) == 0
    # Nothing between, nothing to hide behind.
    assert grid.cover_bonus(Position(x=0, y=5), Position(x=4, y=5)) == 0


def test_the_cover_card_says_the_bonus_the_geometry_and_the_ranged_only_limit():
    cover = _lines("cell:cover")
    assert "Armor Class is 2 higher" in cover, cover
    # The geometry the engine runs: the cover has to be BETWEEN the creature and the attacker.
    assert "BETWEEN the creature and the attacker" in cover, cover
    assert "The cover square itself is worth nothing" in cover, cover
    # directional_cover.cover_bonus only consults terrain cover for a ranged attack.
    assert "attacks that travel" in cover and "arm's length" in cover, cover
    # It must not still be the advice the review found wrong.
    assert "a creature standing in it is harder to hit" not in cover.lower(), cover


# ------------------------------------------------------------------ sight only

def test_a_sight_only_square_is_walkable_and_is_not_a_wall():
    grid = _grid(("SIGHT_BLOCKED", [(2, 2)], 1))
    assert grid.terrain_at((2, 2), "SIGHT_BLOCKED")
    assert not grid.terrain_at((2, 2), "BLOCKED"), "a sight-only square must still be enterable"
    assert grid.base_movement_cost[(2, 2)] == 1


def test_the_sight_card_says_it_stops_sight_but_not_movement():
    sight = _lines("cell:sight")
    assert "blocks line of sight" in sight, sight
    assert "walk straight through it" in sight, sight
    assert "It is not a wall" in sight, sight
    # A sight-blocker must not be described as a solid wall, or a player will refuse to path through it.
    assert "cannot be standing in it" not in sight, sight


# --------------------------------------------------------------------- hazard

def _hazard_engine():
    engine = S.fight(S.bundle("SAND_BASE_SCOURING_HAND"))
    actor = engine.state.actors[S.ME]
    engine.grid.qi_hazard = {(int(actor.position.x), int(actor.position.y))}
    engine.grid.blocked = set()
    engine.grid.opaque = set()
    engine.grid.cover = set()
    return engine, actor


def _force_save_total(engine, total: int) -> None:
    """Pin the Dexterity save the hazard makes, so the test states the Difficulty Class exactly."""
    original = engine.roller.d20

    def d20(*args, **kwargs):
        roll = original(*args, **kwargs)
        return roll.model_copy(update={"natural_result": total, "total": total})

    engine.roller.d20 = d20


def _hazard_rolls(engine, actor, *, save_total: int, times: int = 1):
    actor.saving_throws["DEX"] = 0
    _force_save_total(engine, save_total)
    # The engine stamps the hazard per turn, so each measurement starts from a clean turn.
    for key in [k for k in actor.turn_flags if k.startswith("qi_hazard_round:")]:
        del actor.turn_flags[key]
    start = len(engine.events)
    for _ in range(times):
        engine._resolve_qi_hazard(actor)
    rolls = [ev.payload for ev in engine.events[start:]
             if ev.event_type in ("SAVE_ROLLED", "DAMAGE_ROLLED")]
    return {"save": [r for r in rolls if r.get("reason") == "QI_HAZARD_DEX_SAVE"],
            "damage": [r for r in rolls if r.get("reason") == "QI_HAZARD_DAMAGE"]}


def test_the_hazard_save_is_12_and_1d4_hurts_only_below_it():
    engine, actor = _hazard_engine()
    assert _hazard_rolls(engine, actor, save_total=11)["damage"], "a roll of 11 must hurt"
    assert not _hazard_rolls(engine, actor, save_total=12)["damage"], "a roll of 12 must be safe"
    failed = _hazard_rolls(engine, actor, save_total=11)
    assert len(failed["save"]) == 1
    assert len(failed["damage"]) == 1
    damage = failed["damage"][0]
    assert damage["expression"] == "1d4+0", damage
    assert damage["modifier"] == 0 and len(damage["dice"]) == 1, damage


def test_the_hazard_hits_a_creature_only_once_in_a_turn():
    engine, actor = _hazard_engine()
    rolls = _hazard_rolls(engine, actor, save_total=11, times=4)
    assert len(rolls["save"]) == 1, "walking on through the hazard must not re-roll"
    assert len(rolls["damage"]) == 1
    assert any(key.startswith("qi_hazard_round:") for key in actor.turn_flags), actor.turn_flags


def test_the_hazard_card_states_the_save_the_damage_and_the_once_per_turn_limit():
    hazard = _lines("cell:hazard")
    assert "Dexterity saving throw of 12" in hazard, hazard
    assert "1d4 damage" in hazard, hazard
    assert "on a success nothing happens" in hazard, hazard
    assert "once per turn" in hazard, hazard
    # The old card only said "put in danger", which told the player none of the above.
    assert "put in danger" not in hazard.lower(), hazard


# ------------------------------------------------------------------ one source

def test_the_browser_does_not_restate_a_mechanic_in_its_own_words():
    """The card is a pure assembler: the wording exists once, on the server."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "static" / "tabletop" / "ground-text.js").read_text(encoding="utf-8")
    body = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("//"))
    for leaked in ("Armor Class", "1d4", "saving throw", "twice as much movement", "blocks movement and sight"):
        assert leaked not in body, f"ground-text.js restates a mechanic in the browser: {leaked!r}"
