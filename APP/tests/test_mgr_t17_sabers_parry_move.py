"""MGR-T17-sabers-parry-1 review finding 2: the parry's 5-foot move is wired through the engine.

Printed: "you may move 5 feet without provoking the attacker's Opportunity Attacks when it reduces the
damage to 0". The move is combat-automatable, so it is typed data on the parry's authority record and the
damage-reduction path runs it (``only_if_zero``), instead of a GM rider. The free parry charges nothing
for it. The printed miss clause ("or when the hit misses after another defense raised your AC") cannot
reach this row: the parry answers damage, and a miss never produces a damage step. It stays flagged.
"""
from tests import hunt15_support
from tests.hunt15_support import LEFT, RIGHT, fight, reload, turn
from combat import typed_reactions

from tests.test_t17_sabers_guard_cutting_parry import MAUL, PARRY, _weapon

ROOT_RIDER = "move 5 feet without provoking"


def _ready(tmp_path, monkeypatch, name):
    monkeypatch.setattr(hunt15_support, "KIT", MAUL)
    combat, table, mid = fight(tmp_path / name, right=[PARRY], seed="M1")
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    return combat, mid, engine, engine.state.actors[RIGHT], _weapon(engine)


def test_the_move_is_typed_on_the_parry_not_a_gm_rider(tmp_path, monkeypatch):
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet

    bundle = compile_character(sheet([PARRY], cl=15), actor_id="actor:factory.t17m")
    row = next(row for row in bundle["typed_reactions"] if row["feature_id"] == PARRY)
    moves = [e for e in row.get("effects") or [] if e.get("type") == "movement"]
    assert len(moves) == 1, row.get("effects")
    assert moves[0]["distance_ft"] == 5 and moves[0]["no_opportunity_attacks"] is True
    assert moves[0]["only_if_zero"] is True
    assert "Ask the GM" not in " ".join(row.get("riders") or [])


def test_a_parry_that_reduces_damage_to_zero_grants_the_free_five_feet(tmp_path, monkeypatch):
    _, mid, engine, target, weapon = _ready(tmp_path, monkeypatch, "zero")
    before_move = target.movement_remaining_ft
    before_resources = dict(target.resources)
    # Five points is the row's minimum, and 1d8+4 always clears it: the damage reaches 0.
    assert typed_reactions.on_damage(engine, target, 5, 0, weapon, LEFT) == 0
    assert target.movement_remaining_ft == before_move + 5
    assert target.turn_flags.get("oa_free_ft") == 5
    assert dict(target.resources) == before_resources  # the free parry charges nothing for the move
    granted = [e for e in engine.events if e.event_type == "MOVEMENT_GRANTED" and e.actor_id == RIGHT]
    assert granted and granted[-1].payload["distance_ft"] == 5


def test_a_parry_that_leaves_damage_standing_grants_no_move(tmp_path, monkeypatch):
    _, mid, engine, target, weapon = _ready(tmp_path, monkeypatch, "partial")
    before_move = target.movement_remaining_ft
    # 1d8+4 is at most 12, so 20 damage is never reduced to 0.
    assert typed_reactions.on_damage(engine, target, 20, 0, weapon, LEFT) > 0
    assert target.movement_remaining_ft == before_move
    assert not target.turn_flags.get("oa_free_ft")
