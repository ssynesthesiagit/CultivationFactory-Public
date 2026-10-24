"""Hunt 14 manual-11: typed Grappled Painted Formation must not loop moves."""
import copy
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_summons import OWNER, ROOT, _sheet


def act(table, mid, needle, target=None):
    state = table.state(mid)
    menu = state["menu"]
    if needle == "end":
        cid = menu["end_turn"]
    else:
        group = next(g for g in menu["actions"] if needle in g["source_definition_id"])
        cid = next(o["candidate_id"] for o in group["options"] if not target or target in o["target_ids"])
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"])


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("grapple_after_start", [False, True])
def test_grappled_painted_formation_table_reload_advances(tmp_path, monkeypatch, auto, grapple_after_start):
    foe = "actor:factory.tabik"
    summon = OWNER + ".summon.painted_formation.1"
    if grapple_after_start:
        from combat import ext
        ext.effects()
        def grab_on_commanded_turn(engine, actor):
            if actor.entity_id == summon and actor.summon.get("commanded") and not actor.conditions:
                # Recreate the exact retained checkpoint: the summon has its
                # 30-foot allowance when Tabik's typed Grappled arrives. Use
                # a documented fixture hook, never patch engine methods.
                engine._apply_condition(actor, "condition:typed.grappled", "test:tabik.grapple", foe,
                                        expires_on="UNTIL_REMOVED")
        monkeypatch.setitem(ext._HOOKS, "turn_start", [*ext._HOOKS.get("turn_start", []), grab_on_commanded_turn])
    owner = compile_character(_sheet(["tianxia.talent.ink.ten_thousand_illustrated_soldiers"]),
                              actor_id=OWNER, summon_plan={"painted_formation": 1})
    enemy = compile_character(_sheet([]), actor_id=foe)
    setup = copy.deepcopy(enemy["action_catalog"][0])
    setup.update(source_definition_id="action:test.grapple", display_name="Test Grapple", economy="ACTION",
                 target_kind="HOSTILE_ENTITY", resolution_kind="TYPED", range_ft=60, costs=[])
    setup["parameters"] = {"typed": {"effects": [{"type": "condition", "condition": "grappled",
        "applies_to": "target", "expires_on": "UNTIL_REMOVED"}], "numbers": {"pb": 4, "cl": 10}}}
    enemy["action_catalog"].append(setup)
    enemy["actor_template"]["action_ids"].append(setup["source_definition_id"])
    enemy.pop("bundle_sha256", None)
    enemy["bundle_sha256"] = canonical_sha256(enemy)
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="HUNT14-SUMMON", typed_bundles=(owner, enemy),
        roster_setup={"primary_actor_ids": [OWNER, foe], "team_by_actor": {OWNER: "team:a", foe: "team:b"},
                      "starting_positions": {OWNER: {"x": 6, "y": 13}, foe: {"x": 6, "y": 12}}})
    mid = session.match_id
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != foe:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    if not grapple_after_start:
        assert act(table, mid, "action:test.grapple", summon)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert act(table, mid, ".command.painted_formation")["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[summon]
    assert (actor.position.x, actor.position.y) == (5, 12)
    assert loaded.engine.state.current_actor_id == summon
    assert actor.movement_remaining_ft == (30 if grapple_after_start else 0)
    assert loaded.engine._effective_speed(actor) == 0
    assert not any(c.kind.value == "MOVE" for c in loaded.engine.legal_candidates())
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO" if auto else "MANUAL")
    for _ in range(8):
        state = table.state(mid)
        if state["menu"]["actor_id"] != summon:
            break
        if auto:
            result = table.auto_step(mid, state["last_sequence"])
        else:
            assert not state["menu"]["moves"]
            result = act(table, mid, "end")
        assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.current_actor_id != summon
    assert not any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == summon and
                   e.payload.get("cost_ft") == 0 for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_manual11_leftover_allowance_is_suppressed_by_existing_safety_net():
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    from combat.gate2_runtime_content import AN
    bundle = compile_character(_sheet(["tianxia.talent.ink.ten_thousand_illustrated_soldiers"]),
        actor_id=OWNER, summon_plan={"painted_formation": 1})
    engine = Gate4ControllerEngine(ROOT, match_seed="HUNT14-SUMMON", typed_bundles=(bundle,),
        roster_setup={"primary_actor_ids": [OWNER, AN], "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                      "starting_positions": {OWNER: {"x": 6, "y": 13}, AN: {"x": 6, "y": 12}}})
    actor = engine.state.actors[OWNER + ".summon.painted_formation.1"]
    foe = engine.state.actors[AN]
    engine.state.current_actor_id = actor.entity_id
    engine.state.current_slot_index = engine.state.initiative_order.index(actor.entity_id)
    actor.summon["commanded"] = True
    engine._apply_condition(actor, "condition:typed.grappled", "test:tabik.grapple", foe.entity_id,
                            expires_on="UNTIL_REMOVED")
    actor.movement_remaining_ft = 30
    assert engine._effective_speed(actor) == 0
    assert not any(c.kind.value == "MOVE" for c in engine.legal_candidates())
    context = build_decision_context(engine, PolicyLibrary(ROOT).for_actor(actor.entity_id)[0], for_ai=True)
    assert not any(c.kind.value == "MOVE" for c in context.legal_candidates)
