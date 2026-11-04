"""Canon's source-expiring command restriction at table and effect checkpoints."""
from types import SimpleNamespace

import pytest

from combat import typed_executor as te
from combat.ext import effect_denial
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_r4_integration import (
    CANON, P, F, fixture, reach, send, candidate, auto_candidate,
)
from tests.test_riders_lane4 import _metal, _cast


@pytest.mark.parametrize("ai_turn", [False, True])
@pytest.mark.parametrize("ai_hit", [False, True])
def test_canon_blocks_formation_pulse_until_casters_next_turn_after_reload(tmp_path, ai_turn, ai_hit):
    combat, table, mid = fixture(tmp_path, [CANON, "TAL_METAL_NEEDLE_FLICK"],
        foe_mids=["FORMATIONS_BASE_SET_ARRAY"], seed="R4-COMMAND", foe_score=40)
    reach(table, mid, F)
    # A live array remains in place; losing command must not destroy its passives.
    assert send(table, mid, candidate(table, mid, "Combat Array: Nourishing Cycle at 6,6"))["status"] == "COMMITTED"
    reach(table, mid, P)
    assert send(table, mid, candidate(table, mid, "White Tiger Seven-Slaughter Canon"))["status"] == "COMMITTED"
    if ai_hit:
        preset = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] for o in g["options"]
                      if o.get("label") == "Choose White Tiger Seven-Slaughter Canon: Sever the Command")
        assert send(table, mid, preset)["status"] == "COMMITTED"
    cid = candidate(table, mid, "Needle Flick", F)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    if ai_hit:
        auto_candidate(combat, mid, P, cid)
        assert table.auto_step(mid, 0)["status"] == "COMMITTED"
        combat.set_controller_mode(mid, actor_id=P, controller_mode="MANUAL")
    else:
        result = send(table, mid, cid)
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        for word in ("Seven-Slaughter Canon", "Needle Flick", "Rider Foe"):
            assert word in prompt["moment"]
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        answer = {**prompt["context"], "selection": "USE", "option_ids": ["Sever the Command"]}
        assert send(table, mid, cid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    states = [s for s in loaded.engine.state.actors[F].conditions.values()
              if s.condition_id == effect_denial.CONDITION]
    assert len(states) == 1 and states[0].source_actor_id == P
    assert states[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert states[0].data["effect_types"] == ["formation_pulse", "banner_order"]
    assert loaded.mechanical.replay()["status"] == "PASS"
    reach(table, mid, F)
    assert not any("Pulse:" in o.get("label", g["label"])
                   for g in table.state(mid)["menu"]["actions"] for o in g["options"])
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(z.active and z.owner_id == F for z in loaded.engine.state.zones.values())
    end = table.state(mid)["menu"]["end_turn"]
    if ai_turn:
        auto_candidate(combat, mid, F, end)
        assert table.auto_step(mid, 0)["status"] == "COMMITTED"
        combat.set_controller_mode(mid, actor_id=F, controller_mode="MANUAL")
    else:
        assert send(table, mid, end)["status"] == "COMMITTED"
    reach(table, mid, P)
    assert not effect_denial.denied_types(CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[F])
    reach(table, mid, F)
    assert candidate(table, mid, "Pulse: Nourishing Cycle", F)
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("saved", [False, True])
def test_command_sign_save_and_nested_effect_gate(saved):
    engine, actor, target = _metal(CANON, "TAL_METAL_NEEDLE_FLICK")
    target.saving_throws["CHA"] = 500 if saved else -500
    _cast(engine, "White Tiger Seven-Slaughter Canon", exact=True)
    _cast(engine, "Choose White Tiger Seven-Slaughter Canon: Sever the Command", exact=True)
    _cast(engine, "Needle Flick", target=target.entity_id, exact=True)
    assert bool(effect_denial.denied_types(target)) == (not saved)
    ctx = SimpleNamespace(actor=target)
    for kind in ("formation_pulse", "banner_order"):
        assert effect_denial.effect_allowed(ctx, {"type": kind}) == (None if saved else False)
        row = {"effects": [{"type": "on_success", "effects": [{"type": kind}]}]}
        assert effect_denial.reaction_allowed(engine, target, actor, row) == (None if saved else False)
    assert effect_denial.effect_allowed(ctx, {"type": "damage"}) is None
    assert effect_denial.effect_allowed(SimpleNamespace(actor=actor), {"type": "banner_order"}) is None


def test_nested_command_execution_cannot_bypass_denial():
    engine, actor, target = _metal(CANON, "TAL_METAL_NEEDLE_FLICK")
    target.saving_throws["CHA"] = -500
    _cast(engine, "White Tiger Seven-Slaughter Canon", exact=True)
    _cast(engine, "Choose White Tiger Seven-Slaughter Canon: Sever the Command", exact=True)
    _cast(engine, "Needle Flick", target=target.entity_id, exact=True)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == target.entity_id)
    ctx = te.Context(engine, target, action, None, {"source": "test", "numbers": {}}, [actor], actor, {})
    before = engine.state.model_dump(mode="json"), len(engine.events)
    te.run_effects(ctx, [{"type": "formation_pulse", "pattern": "nourishing_cycle"}, {"type": "banner_order"}])
    assert (engine.state.model_dump(mode="json"), len(engine.events)) == before


def test_officers_command_is_filtered_before_cost_or_reaction_prompt():
    from combat import typed_reactions
    from tests.test_sys_placed_effects import _officer, _me, _ally

    engine = _officer()
    leader, ally = _me(engine), _ally(engine)
    engine._apply_condition(leader, effect_denial.CONDITION, "test:command-denial", ally.entity_id,
        expires_on="START_OF_SOURCE_NEXT_TURN", data={"effect_types": ["banner_order"]})
    before = dict(leader.resources), leader.reaction_available, len(engine.events)
    typed_reactions.on_turn_start(engine, ally)
    assert (dict(leader.resources), leader.reaction_available, len(engine.events)) == before
    engine._remove_condition(leader, effect_denial.CONDITION, "test:expiry")
    typed_reactions.on_turn_start(engine, ally)
    assert not leader.reaction_available
    assert any(e.event_type == "MODIFIER_APPLIED" and e.payload.get("value") == "ADVANTAGE"
               for e in engine.events[before[2]:])
