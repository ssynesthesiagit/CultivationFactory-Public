"""Nested damage uses native life consequences through a committed table turn.

The fixture action installs afflictions' ordinary periodic condition without a
menu, so bounded damage isolates dispatch rather than ability choices.
"""

import copy

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import life_state
from tests.h1_support import ROOT, sheet, duel, ME, FOE

SOURCE, TARGET, ALLY = (f"actor:factory.sol88-{name}" for name in ("source", "target", "ally"))


def _table(tmp_path, initial_damage, periodic_damage):
    bundles = []
    for aid, initiative, hp, mids in ((SOURCE, 100, 500, []),
                                      (TARGET, 50, 4, ["TAL_BERSERKER_DEATHLESS"]),
                                      (ALLY, -100, 500, [])):
        doc = sheet(mids)
        doc["identity"]["display_name"] = aid.rsplit("-", 1)[-1].title()
        doc["ability_scores_and_statistics"]["initiative"] = {"bonus": initiative}
        doc["ability_scores_and_statistics"]["hit_points"] = {"maximum": hp}
        bundles.append(compile_character(doc, actor_id=aid))
    action = copy.deepcopy(bundles[0]["action_catalog"][0])
    action.update(source_definition_id="action:typed.sol88.affliction", display_name="Test periodic damage",
                  target_kind="HOSTILE_ENTITY", range_ft=60)
    action["parameters"] = {"typed": {"numbers": {"pb": 4, "save_dc": 16}, "effects": [
        {"type": "condition", "condition": "affliction", "applies_to": "target", "duration": "one_minute",
         "condition_data": {"periodic": [{"dice": {"count": periodic_damage, "sides": 2},
                                          "types": ["necrotic"], "label": "Test venom"}]}},
        {"type": "damage", "flat": initial_damage, "damage_types": ["necrotic"], "applies_to": "target"},
    ]}}
    bundles[0]["action_catalog"].append(action)
    bundles[0]["actor_template"]["action_ids"].append(action["source_definition_id"])
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [SOURCE, TARGET, ALLY], {SOURCE: "team:b", TARGET: "team:a", ALLY: "team:a"},
        {SOURCE: {"x": 3, "y": 6}, TARGET: {"x": 4, "y": 6}, ALLY: {"x": 4, "y": 7}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [SOURCE, TARGET, ALLY], [],
        control_modes={aid: "MANUAL" for aid in (SOURCE, TARGET, ALLY)},
        match_seed="SOL88-NESTED", display_name="Nested damage regression", maximum_rounds=5,
    )["match_id"]
    return combat, table, mid


def _send(table, mid, candidate):
    state = table.state(mid)
    menu = state["menu"]
    result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"], [])
    assert result["status"] == "COMMITTED", result


@pytest.mark.parametrize("initial,periodic,dead", [(4, 1, False), (4, 12, True), (0, 16, True)],
                         ids=["dying-damage-adds-failure", "dying-massive-damage-kills", "standing-massive-excess-kills"])
def test_periodic_plugin_damage_applies_life_consequences_and_survives_table_reload(tmp_path, initial, periodic, dead):
    combat, table, mid = _table(tmp_path, initial, periodic)
    engine = combat._load_session(mid).engine
    candidate = next(c.candidate_id for c in engine.legal_candidates()
                     if c.source_definition_id == "action:typed.sol88.affliction" and c.target_ids == (TARGET,))
    _send(table, mid, candidate)
    _send(table, mid, table.state(mid)["menu"]["end_turn"])
    session = combat._load_session(mid)
    target = session.engine.state.actors[TARGET]
    if dead:
        assert not target.active, "nested damage must kill at the massive-damage threshold"
    else:
        assert target.current_hp == 0 and target.life_state == "DYING"
        assert target.turn_flags[life_state.RECORD] == {"ok": 1, "bad": 1}
    assert life_state.HP_BEFORE not in target.turn_flags
    assert life_state.DOOMED not in target.turn_flags
    assert not any(e.event_type == "GM_RIDER" and "depth" in str(e.payload) for e in session.engine.events)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == session.engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_periodic_plugin_damage_already_runs_native_concentration_save():
    from combat.ext import afflictions

    engine = duel(["TAL_BERSERKER_DEATHLESS"], seed="SOL88-CONCENTRATION")
    target = engine.state.actors[ME]
    target.maximum_hp = 200
    target.current_hp = 200
    engine._start_concentration(target, "action:test.concentration")
    engine._apply_condition(target, afflictions.condition_id(), "action:test.venom", FOE,
                            expires_on="END_OF_HOLDER_NEXT_TURN",
                            data={"periodic": [{"dice": {"count": 40, "sides": 2}, "types": ["necrotic"]}]})
    start = len(engine.events)
    engine._system_start_turn()
    saves = [e for e in engine.events[start:] if e.event_type == "SAVE_ROLLED"]
    damage = next(e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED")
    assert len(saves) == 1 and saves[0].payload["dc"] == damage.payload["reduced_to"] // 2
