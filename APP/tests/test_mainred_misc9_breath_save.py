"""Hunger-Refining Breath's Failed Save clause: "Disadvantage on the next saving throw made before the end of your next turn"
(MAINREDMISC9). The printed words name no ability, so the prose reader could not tell which saves it covers and the clause was
not automated. The reviewed record now types the abilities and the "next" in its own fields, and the typed executor reads them.

Synthetic engine only (the shared fight helpers); the record itself is read from the shipped authority file.
"""

import json
from pathlib import Path

from combat import typed_executor
from combat.ext.save_against import CONDITION, save_against
from combat.gate2_runtime_content import AN
from tests.test_auto_wenxue import ME, _bundle, _engine
from tests.test_save_against import _ctx, _held

MARTIAL = Path(__file__).resolve().parents[1] / "authority" / "typed_mechanics" / "reviewed_final.d" / "martial.json"
BREATH = "TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH"
ALL_SIX = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]


def _breath_disadvantage():
    record = json.loads(MARTIAL.read_text())[BREATH]
    rider = next(e for e in record["effects"] if e["type"] == "rider_defeats")
    save = next(e for e in rider["effects"] if e["type"] == "save")
    return next(e for e in save["on_fail"] if e["type"] == "disadvantage")


def test_the_record_types_every_ability_and_the_next_save():
    effect = _breath_disadvantage()
    assert effect["save_abilities"] == ALL_SIX
    assert effect["next"] is True


def test_breath_next_save_disadvantage_is_a_typed_grant_on_the_target_for_every_ability():
    engine = _engine(_bundle())
    foe = engine.state.actors[AN]
    typed_executor.block_advantage(_ctx(engine, ME, AN), _breath_disadvantage())
    held = _held(foe)
    assert len(held) == 1, held
    rule = held[0].data["rule"]["save_against"]
    assert rule["mode"] == "DISADVANTAGE" and rule["abilities"] == ALL_SIX and rule["next"] is True
    assert held[0].expires_on.startswith("END_OF_SOURCE_TURN_AT"), held[0].expires_on
    for code in ALL_SIX:
        assert save_against(_ctx(engine, AN, ME), foe, code, set()) == {"bonus": 0, "modes": ["DISADVANTAGE"]}, code


def test_the_breath_disadvantage_is_used_up_by_the_first_save_it_changes():
    engine = _engine(_bundle())
    foe = engine.state.actors[AN]
    typed_executor.block_advantage(_ctx(engine, ME, AN), _breath_disadvantage())
    assert save_against(_ctx(engine, AN, ME), foe, "DEX", set()) == {"bonus": 0, "modes": ["DISADVANTAGE"]}
    assert not _held(foe)
    assert CONDITION not in {c.condition_id for c in foe.conditions.values()}
