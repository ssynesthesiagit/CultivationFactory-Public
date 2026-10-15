"""Synthetic owned actions through actual table preview, commit and fresh reload.

Test effects use the documented effect registry; no engine method is patched.
The clock and concentration cleanup are the production implementations.
"""
import pytest

from combat import ext, loadout
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_lock_choices import install
from tests.test_lock2_persistence import ROOT, table_match, act

TIMER = "action:test.timer"
END = "action:test.end_concentration"
POOL = "resource:core.stamina"
BASE = "action:test.augmented"
COMBO = BASE + "#strong"
DEADLINE = "condition:typed.concentration_deadline"


def timer_actions(info):
    common = dict(owner_id=info["actor_id"], economy="NONE", resolution_kind="TYPED", target_kind="SELF")
    return [ActionDefinition(source_definition_id=TIMER + info["actor_id"], display_name="Practice concentration",
        parameters={"typed": {"source": TIMER, "duration": {"kind": "rounds", "amount": 1, "concentration": True},
            "numbers": info["numbers"], "effects": [
                {"type": "condition", "condition": "blinded", "applies_to": "self", "expires_on": "CONCENTRATION_END"},
                {"type": "limit_concentration_duration"}]}}, **common),
        ActionDefinition(source_definition_id=END + info["actor_id"], display_name="End practice concentration",
            parameters={"typed": {"source": END, "numbers": info["numbers"],
                "effects": [{"type": "test_end_concentration"}]}}, **common)]


def end_effect(ctx, row):
    ctx.engine._end_concentration(ctx.actor, "VOLUNTARY")


@pytest.mark.parametrize("ending", ["early", "expiry", "same_transaction"])
def test_deadline_history_and_visible_effects_survive_table_commit_reload(monkeypatch, tmp_path, ending):
    install(monkeypatch, "compile_actions", timer_actions)
    monkeypatch.setitem(ext.effects(), "test_end_concentration", end_effect)
    if ending == "same_transaction":
        def finish(ctx):
            if ctx.source.startswith(TIMER):
                end_effect(ctx, {})
        monkeypatch.setitem(ext._HOOKS, "technique_used", [*ext._HOOKS.get("technique_used", []), finish])
    combat, table, mid = table_match(tmp_path)
    actor_id = table.state(mid)["menu"]["actor_id"]
    cast = act(table, mid, TIMER)
    assert cast["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(mid)
    actor = session.engine.state.actors[actor_id]
    if ending != "same_transaction":
        deadline = next(c for c in actor.conditions.values() if c.condition_id == DEADLINE)
        assert deadline.data["hidden"] is True
        assert type(deadline.data["started_sequence"]) is int
        assert any(c.condition_id == "condition:typed.blinded" for c in actor.conditions.values())
        projected = TabletopService(fresh, tmp_path).state(mid)["presentation"]["actors"]
        rows = next(a for a in projected if a["entity_id"] == actor_id)["conditions"]
        assert next(c for c in rows if c["condition_id"] == DEADLINE)["hidden"] is True
        assert not next(c for c in rows if c["condition_id"] == "condition:typed.blinded")["hidden"]
        if ending == "early":
            assert act(table, mid, END)["status"] == "COMMITTED"
        else:
            for _ in range(6):
                assert act(table, mid, "end")["status"] == "COMMITTED"
                if not CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[actor_id].concentration:
                    break
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(mid)
    actor = session.engine.state.actors[actor_id]
    assert actor.concentration is None
    assert not any(c.condition_id in {DEADLINE, "condition:typed.blinded"} for c in actor.conditions.values())
    history = TabletopService(fresh, tmp_path).events(mid, 0)["events"]
    assert not any("deadline" in r["summary"].lower() for r in history)
    assert any("Blinded" in r["summary"] for r in history), history
    assert session.mechanical.replay()["status"] == "PASS"


def priced_actions(info):
    family, combo = BASE + info["actor_id"], COMBO + info["actor_id"]
    common = dict(owner_id=info["actor_id"], economy="ACTION", resolution_kind="TYPED", target_kind="SELF")
    typed = {"source": family, "numbers": info["numbers"], "effects": [{"type": "temp_hp", "flat": 1, "applies_to": "self"}]}
    return [ActionDefinition(source_definition_id=family, display_name="Practice technique", costs=((POOL, 1),),
        parameters={"typed": typed, "augment_loadout": {"combos": {"strong": combo},
            "augments": [{"key": "strong", "name": "Stronger practice"}]}}, **common),
        ActionDefinition(source_definition_id=combo, display_name="Stronger practice", costs=((POOL, 2), (POOL, 2)),
            parameters={"typed": typed}, **common)]


def test_selected_aggregate_cost_reason_survives_commit_reload(monkeypatch, tmp_path):
    install(monkeypatch, "compile_actions", priced_actions)
    def choose(engine, event_type, kwargs):
        if event_type != "HOLD_POSITION_COMMITTED":
            return
        actor = engine.state.actors[kwargs["actor_id"]]
        engine._spend_resource(actor, POOL, actor.resources[POOL] - 3, "test:drain")
        loadout.toggle(engine, actor, BASE + actor.entity_id, "strong", "test:select")
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), choose])
    combat, table, mid = table_match(tmp_path)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    state = TabletopService(fresh, tmp_path).state(mid)
    actor_id = state["menu"]["actor_id"]
    reason = state["unavailable_reasons"]["act:" + BASE + actor_id]
    assert reason == "Requires 4 Stamina (you have 3); no affordable alternative payment is available."
    assert not any(g["source_definition_id"] == COMBO + actor_id for g in state["menu"]["actions"])
    assert fresh._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_alternative_payment_does_not_produce_false_resource_reason(monkeypatch, tmp_path):
    from tests.test_lock5_payments import table_fixture, SOURCE
    _combat, _table, mid = table_fixture(monkeypatch, tmp_path, current=0)
    fresh = CombatService(ROOT, tmp_path)
    state = TabletopService(fresh, tmp_path).state(mid)
    actor_id = state["menu"]["actor_id"]
    assert any(g["source_definition_id"] == SOURCE + ":" + actor_id for g in state["menu"]["actions"])
    assert "act:" + SOURCE + ":" + actor_id not in state["unavailable_reasons"]
    assert fresh._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_alternative_payment_restriction_reason_survives_table_commit_reload(monkeypatch, tmp_path):
    from tests.test_lock5_payments import POOL as STAMINA, SOURCE, priced_action, quote

    def restricted(info):
        action, = priced_action(info)
        return [action.model_copy(update={
            "economy": EconomyKind.NONE,
            "parameters": {**action.parameters, "requires_turn_flag": "test_not_enabled"},
        })]

    install(monkeypatch, "compile_actions", restricted)
    install(monkeypatch, "payment_shortfall", quote)
    def drain(engine, kind, kwargs):
        if kind == "HOLD_POSITION_COMMITTED":
            actor = engine.state.actors[kwargs["actor_id"]]
            engine._spend_resource(actor, STAMINA, actor.resources[STAMINA], "test:drain")
    install(monkeypatch, "event", drain)

    _combat, table, mid = table_match(tmp_path)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    state = TabletopService(fresh, tmp_path).state(mid)
    actor_id = state["menu"]["actor_id"]
    source = SOURCE + ":" + actor_id
    assert not any(g["source_definition_id"] == source for g in state["menu"]["actions"])
    assert state["unavailable_reasons"]["act:" + source] == (
        "The required earlier action or trigger has not happened this turn.")
    assert fresh._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_effective_cost_floor_is_used_by_persisted_button_reason(monkeypatch, tmp_path):
    install(monkeypatch, "compile_actions", priced_actions)
    install(monkeypatch, "technique_cost_floor", lambda e, a, source, listed, proposed:
            {POOL: 100} if source.startswith(BASE) else None)
    combat, table, mid = table_match(tmp_path)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    state = TabletopService(fresh, tmp_path).state(mid)
    actor_id = state["menu"]["actor_id"]
    actor = fresh._load_session(mid).engine.state.actors[actor_id]
    assert state["unavailable_reasons"]["act:" + BASE + actor_id] == (
        f"Requires 100 Stamina (you have {actor.resources[POOL]}); no affordable alternative payment is available.")


def test_actual_ability_use_reset_text_survives_table_reload(tmp_path):
    from tests.test_tabletop_hunt6 import table_fight, LEFT
    from tests.r10_fixup_support import cast_sender, commit
    ability = "TAL_ATHLETICS_COURT_OF_TEN_THOUSAND_STEPS"
    combat, table, mid = table_fight(tmp_path, [ability], primary="Body")
    commit(cast_sender(combat, table, mid, "Court of Ten Thousand Steps"))
    for _ in range(3):
        assert act(table, mid, "end")["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    state = TabletopService(fresh, tmp_path).state(mid)
    assert state["menu"]["actor_id"] == LEFT
    reasons = [v for k, v in state["unavailable_reasons"].items() if ability in k]
    assert reasons and any("No uses of this ability remain in this fight" in r and "new fight" in r for r in reasons)
    assert fresh._load_session(mid).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("restriction,expected", [
    ({"requires_condition": "condition:test.missing"}, "The required effect or stance is not active on you."),
    ({"requires_turn_flag": "test_missing"}, "The required earlier action or trigger has not happened this turn."),
    ({"requires_resource": {POOL: 100}}, "You must have 100 Stamina available before using this action."),
    ({"requires_grappling": True}, "You must be grappling a creature before dragging it."),
])
def test_non_cost_engine_rejections_have_specific_reloaded_reasons(monkeypatch, tmp_path, restriction, expected):
    def restricted(info):
        rows = priced_actions(info)
        return [rows[0].model_copy(update={"parameters": {**rows[0].parameters, **restriction}})]
    install(monkeypatch, "compile_actions", restricted)
    _combat, table, mid = table_match(tmp_path)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    state = TabletopService(fresh, tmp_path).state(mid)
    source = BASE + state["menu"]["actor_id"]
    assert not any(g["source_definition_id"] == source for g in state["menu"]["actions"])
    assert state["unavailable_reasons"]["act:" + source] == expected
    assert fresh._load_session(mid).mechanical.replay()["status"] == "PASS"
