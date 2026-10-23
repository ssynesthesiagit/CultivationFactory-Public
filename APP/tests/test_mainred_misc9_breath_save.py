"""Hunger-Refining Breath's Failed Save clause: "Disadvantage on the next saving throw made before the end of your next turn"
(MAINREDMISC9). The printed words name no ability, so the prose reader could not tell which saves it covers and the clause was
not automated. The reviewed record now types the abilities, the unrestricted scope and the "next" in its own fields, and the
typed executor reads them. An unrestricted next save also covers a death saving throw (MAINREDMISC9F14).

Synthetic engine only (the shared fight helpers); the record is read from the compiled authority the engine loads.
"""

import json
from pathlib import Path

from combat import typed_executor
from combat.ext.save_against import CONDITION, save_against
from combat.gate2_runtime_content import AN
from tests.cw2_service_support import seal
from tests.h1_support import sheet
from tests.test_auto_wenxue import ME, _bundle, _engine
from tests.test_save_against import _ctx, _held
from tests.worker2_support import FOE, OWNER, candidate, fixture, reload, sealed_native_attack, settle

# The compiled authority is what the engine loads (combat/typed_numbers.py), so the test reads the built row, not the source record.
AUTHORITY = Path(__file__).resolve().parents[1] / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
BREATH = "TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH"
ALL_SIX = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]


def _breath_disadvantage():
    record = json.loads(AUTHORITY.read_text())["mechanics"][BREATH]
    rider = next(e for e in record["effects"] if e["type"] == "rider_defeats")
    save = next(e for e in rider["effects"] if e["type"] == "save")
    return next(e for e in save["on_fail"] if e["type"] == "disadvantage")


def test_the_record_types_every_ability_and_the_next_save():
    effect = _breath_disadvantage()
    assert effect["save_abilities"] == ALL_SIX
    assert effect["save_scope"] == "any"
    assert effect["next"] is True


def test_breath_next_save_disadvantage_is_a_typed_grant_on_the_target_for_every_ability():
    engine = _engine(_bundle())
    foe = engine.state.actors[AN]
    typed_executor.block_advantage(_ctx(engine, ME, AN), _breath_disadvantage())
    held = _held(foe)
    assert len(held) == 1, held
    rule = held[0].data["rule"]["save_against"]
    assert rule["mode"] == "DISADVANTAGE" and rule["abilities"] == ALL_SIX and rule["next"] is True
    assert rule["scope"] == "any"
    assert held[0].expires_on.startswith("END_OF_SOURCE_TURN_AT"), held[0].expires_on
    # Each ability is checked in its own fight: a "next" grant is used up by the first save it changes.
    for code in ALL_SIX:
        engine = _engine(_bundle())
        foe = engine.state.actors[AN]
        typed_executor.block_advantage(_ctx(engine, ME, AN), _breath_disadvantage())
        assert save_against(_ctx(engine, AN, ME), foe, code, set()) == {"bonus": 0, "modes": ["DISADVANTAGE"]}, code


def test_the_breath_disadvantage_is_used_up_by_the_first_save_it_changes():
    engine = _engine(_bundle())
    foe = engine.state.actors[AN]
    typed_executor.block_advantage(_ctx(engine, ME, AN), _breath_disadvantage())
    assert save_against(_ctx(engine, AN, ME), foe, "DEX", set()) == {"bonus": 0, "modes": ["DISADVANTAGE"]}
    assert not _held(foe)
    assert CONDITION not in {c.condition_id for c in foe.conditions.values()}


BREATH_ACTION = "Hunger-Refining Breath"


def _foe_that_fails_the_cone_save():
    """A foe whose Constitution save cannot meet the Breath's DC, so the printed failure is the one that lands."""
    document = sheet([], cl=15)
    document["ability_scores_and_statistics"]["saving_throws"] = {"CON": -100}
    return document


def test_the_breath_grant_is_committed_at_the_table_and_survives_a_cold_reload(tmp_path):
    """The failed-save clause through the real table: breath, commit, cold reload.

    The engine files own the cone (combat/ext/foundation_combat.py) and the save grant (combat/ext/save_against.py).
    Only the saved fight is read after the reload, so a grant that is not stored on the foe is lost there. The stored
    rule must carry all six abilities, one next save and the printed expiry, and still change a real save.
    """
    combat, table, match = fixture(tmp_path, [BREATH], foe_sheet=_foe_that_fails_the_cone_save(),
                                   ally_position={"x": 3, "y": 10})   # the ally stands outside the cone
    settled = candidate(combat, match, BREATH_ACTION, at=(6, 6))       # fixture's foe square: the cone's mouth
    settle(table, match, settled.candidate_id)

    engine = reload(tmp_path, match)                                  # cold: a fresh service reads only the committed fight
    foe = engine.state.actors[FOE]
    held = _held(foe)
    assert len(held) == 1, [c.condition_id for c in foe.conditions.values()]
    rule = held[0].data["rule"]["save_against"]
    assert rule == {"mode": "DISADVANTAGE", "against": [], "abilities": ALL_SIX, "next": True, "scope": "any"}, rule
    assert held[0].expires_on.startswith("END_OF_SOURCE_TURN_AT"), held[0].expires_on
    # The reloaded grant still changes a real save, and a "next" one is spent by it.
    assert save_against(_ctx(engine, FOE, OWNER), foe, "CHA", set()) == {"bonus": 0, "modes": ["DISADVANTAGE"]}
    assert not _held(foe)


def _opening_strike(bundles):
    """A real bonus-action weapon hit that leaves the foe at 1 Hit Point, so the Breath's own damage is the lethal one."""
    source = sealed_native_attack(bundles[0], "Test Opening Strike", damage_type="FIRE",
                                  count=1, sides=1, modifier=58, attack_bonus=20)
    action = next(a for a in bundles[0]["action_catalog"] if a["source_definition_id"] == source)
    action["economy"] = "BONUS_ACTION"
    seal(bundles[0])


def _death_saves(engine):
    return [roll for roll in engine.rolls if roll.actor_id == FOE and roll.reason == "SAVE:death"]


def test_the_breath_grant_also_changes_and_is_used_up_by_a_death_saving_throw(tmp_path):
    """An unrestricted "next saving throw" includes the death save, through the table, after a commit and cold reload.

    The printed clause names no ability, so it is not limited to the six ability saves: a creature that fails the Breath
    and is knocked to 0 Hit Points before its next turn must roll its next death saving throw with Disadvantage, and that
    roll uses up the same single grant an ordinary save would.
    """
    combat, table, match = fixture(tmp_path, [BREATH], foe_sheet=_foe_that_fails_the_cone_save(),
                                   ally_position={"x": 3, "y": 10}, bundle_transform=_opening_strike,
                                   seed="WORKER2-BREATH-DEATH")
    settle(table, match, candidate(combat, match, "Test Opening Strike", target=FOE).candidate_id)
    foe = combat._load_session(match).engine.state.actors[FOE]
    assert foe.current_hp == 1 and foe.life_state is None, (foe.current_hp, foe.life_state)  # one more point of damage drops it
    settle(table, match, candidate(combat, match, BREATH_ACTION, at=(6, 6)).candidate_id)

    engine = reload(tmp_path, match)                                  # cold: a fresh service reads only the committed fight
    foe = engine.state.actors[FOE]
    assert foe.current_hp == 0 and foe.life_state == "DYING", (foe.current_hp, foe.life_state)
    held = _held(foe)
    assert len(held) == 1, [c.condition_id for c in foe.conditions.values()]  # one grant, not one per save path
    assert held[0].data["rule"]["save_against"]["scope"] == "any"
    assert not _death_saves(engine)

    # The real table advances to the dying creature's turn, whose start makes the actual death saving throw.
    for _ in range(8):
        engine = combat._load_session(match).engine
        if _death_saves(engine):
            break
        settle(table, match, table.state(match)["menu"]["end_turn"])
    engine = reload(tmp_path, match)
    saves = _death_saves(engine)
    assert len(saves) == 1, [roll.reason for roll in engine.rolls]
    assert saves[0].mode == "DISADVANTAGE", saves[0].model_dump(mode="json")
    foe = engine.state.actors[FOE]
    assert not _held(foe)  # the same single grant is consumed by the death save
    assert any(event.event_type == "CONDITION_REMOVED" and (event.payload or {}).get("reason") == "CONSUMED"
               and (event.payload or {}).get("condition_id") == CONDITION for event in engine.events)
    # The printed duration still bounds it: it did not simply last the rest of the fight.
    assert held[0].expires_on.startswith("END_OF_SOURCE_TURN_AT"), held[0].expires_on
