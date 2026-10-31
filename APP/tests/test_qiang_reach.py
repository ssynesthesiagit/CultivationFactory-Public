"""Public synthetic FD-10 regressions: reach, real hands, and no silent buttons."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, FOE, sheet

QIANG = "tianxia.mortal.weapon.qiang"
TALENTS = ["TAL_BERSERKER_BATTER", "TAL_BERSERKER_ADVANCING_CARNAGE",
           "TAL_SPEAR_PINNING_STRIKE"]


def fight(tmp_path, *, distance=10, spare=False, weapon=QIANG):
    kit = {"starting_kit": {"items": [
        *([{"item_id": "tianxia.mortal.weapon.gun", "name": "Gun (Staff)", "quantity": 1}] if spare else []),
        {"item_id": weapon, "name": "Test weapon", "quantity": 1}]}}
    player = sheet(TALENTS, kit=kit, name="Reach fighter")
    player["ability_scores_and_statistics"]["initiative"] = {"bonus": 100}
    foe = sheet([], name="Target")
    foe["ability_scores_and_statistics"]["initiative"] = {"bonus": -100}
    combat = CombatService(ROOT, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(
        [compile_character(player, actor_id=ME), compile_character(foe, actor_id=FOE)],
        [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6 + distance // 5}},
        arena, [ME], [FOE], control_modes={ME: "MANUAL", FOE: "MANUAL"},
        match_seed="QIANGREACH1", display_name="Reach regression", maximum_rounds=4,
    )["match_id"]
    table = TabletopService(combat, tmp_path)
    assert table.state(mid)["menu"]["actor_id"] == ME
    return combat, table, mid


def send(table, mid, source):
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["source_definition_id"] == source)
    cid = group["options"][0]["candidate_id"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"])


def weapon_id(combat, mid):
    return next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                if a.owner_id == ME and a.source_definition_id.endswith(".weapon.qiang"))


def assert_no_silent_refusals(state):
    disabled = [a for actor in state["presentation"]["actors"]
                for a in actor["action_availability"] if not a["legal_now"]]
    assert disabled
    for action in disabled:
        reason = state["unavailable_reasons"].get("act:" + action["action_definition_id"])
        assert isinstance(reason, str) and reason.strip(), action


@pytest.mark.parametrize("distance", [10, 15])
def test_qiang_pin_trip_and_batter_use_ten_foot_reach_after_commit_and_cold_reload(tmp_path, distance):
    combat, table, mid = fight(tmp_path, distance=distance)
    source = weapon_id(combat, mid)
    from combat.ext.hand_occupancy import weapon_grips
    engine = combat._load_session(mid).engine
    assert weapon_grips(engine, engine.state.actors[ME]) == {source: 1}
    # A harmless free grip change is a real table commit, not an in-memory edit.
    stow = next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                if (a.parameters.get("equipment_grip") or {}) == {"weapon": source, "held": 0, "hands": 1})
    assert send(table, mid, stow)["status"] == "COMMITTED"
    draw = stow.removesuffix(".stow") + ".draw"
    assert send(table, mid, draw)["status"] == "COMMITTED"
    cold = CombatService(ROOT, tmp_path)
    state = TabletopService(cold, tmp_path).state(mid)
    groups = {g["source_definition_id"]: g for g in state["menu"]["actions"]}
    for suffix in ("", "#pin", "#trip", ".batter"):
        key = source + suffix
        if distance == 10:
            assert key in groups, (key, state["unavailable_reasons"].get("act:" + key))
            assert any(FOE in o.get("target_ids", []) for o in groups[key]["options"])
        else:
            assert key not in groups
            assert "15 ft away" in state["unavailable_reasons"]["act:" + key]
    # A legal weapon range never waives Advancing Carnage's critical/kill trigger.
    assert source + ".advancing_carnage" not in groups
    assert_no_silent_refusals(state)
    assert cold._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_two_readied_weapons_explain_the_second_hand_and_stowing_fixes_it(tmp_path):
    combat, table, mid = fight(tmp_path, spare=True)
    source = weapon_id(combat, mid)
    cold = CombatService(ROOT, tmp_path)
    state = TabletopService(cold, tmp_path).state(mid)
    for suffix in ("", "#pin", "#trip", ".batter"):
        reason = state["unavailable_reasons"]["act:" + source + suffix]
        assert "2 hands" in reason and "only 1" in reason and "Gun (Staff)" in reason
        assert "Stow or drop" in reason
    assert_no_silent_refusals(state)
    staff = next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                 if (a.parameters.get("equipment_grip") or {}).get("held") == 0
                 and a.parameters["equipment_grip"]["weapon"].endswith(".weapon.gun"))
    assert send(table, mid, staff)["status"] == "COMMITTED"
    cold = CombatService(ROOT, tmp_path)
    reloaded = TabletopService(cold, tmp_path).state(mid)
    offered = {g["source_definition_id"] for g in reloaded["menu"]["actions"]}
    assert all(source + suffix in offered for suffix in ("", "#pin", "#trip", ".batter"))
    assert_no_silent_refusals(reloaded)


@pytest.mark.parametrize("weapon,distance", [(QIANG, 10), (QIANG, 15), ("tianxia.mortal.weapon.bi_shou", 10)])
def test_real_table_projections_never_silently_refuse_actions(tmp_path, weapon, distance):
    _, table, mid = fight(tmp_path, weapon=weapon, distance=distance)
    assert_no_silent_refusals(table.state(mid))


def test_projection_fallback_does_not_trust_a_disagreeing_query():
    from combat.action_availability import describe, UNKNOWN_REASON
    projection = {"actors": [{"action_availability": [
        {"action_definition_id": "test:disabled", "legal_now": False, "disabled_reason_codes": ["no_engine_issued_candidate"]},
        {"action_definition_id": "test:legal", "legal_now": True}]}]}
    reasons = describe(None, None, presentation=projection)
    assert reasons == {"act:test:disabled": UNKNOWN_REASON}
