"""SOL143: journal-only statistics across the table commit/reload boundary."""
from copy import deepcopy
import gc
from types import SimpleNamespace as NS
import time
from statistics import median
import pytest

from combat import ext, summons, typed_executor
from combat.fight_summary import build_summary, metrics
from combat.gate2_runtime_models import DiceSpec
from combat.gate5_service import CombatService
from tests.persistence_support import inventory
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, script
from tests.test_tabletop_hunt6 import table_fight, answer_action, LEFT, ALLY, RIGHT, HOLD


def test_recorded_metrics_and_corrections_without_engine_calls():
    actors = {key: NS(entity_id=key, display_name=key.upper(), team_id=team, owner_id=owner,
                      summon={} if owner else None, current_hp=hp, maximum_hp=40,
                      life_state=None, active=hp > 0, conditions={})
              for key, team, owner, hp in (("a", "red", None, 30), ("b", "blue", None, 0), ("s", "red", "a", 20))}
    events = []
    def record(kind, actor="a", targets=("b",), source="attack", **payload):
        events.append(NS(event_type=kind, actor_id=actor, target_ids=targets,
                         source_definition_id=source, payload=payload, sequence=len(events)+1))
    record("TURN_STARTED")
    record("ATTACK_ROLLED", roll_id="r1", provisional_hit=True, natural_result=20)
    record("DAMAGE_ROLLED", total=99, reason="HEALING:heal")  # misleading history text
    record("DAMAGE_COMMITTED", rolled_or_pending_damage=30, reduced_to=20,
           hp_damage=15, temporary_hp_absorbed=5, remaining_hp=0, damage_type="FIRE")
    record("DAMAGE_COMMITTED", actor="s", rolled_or_pending_damage=4, reduced_to=4,
           hp_damage=4, remaining_hp=0, damage_type="COLD")  # already down
    record("HEALING_APPLIED", targets=("a",), before=20, after=30, offered=99)
    record("TEMP_HP_GRANTED", targets=("a",), before=5, after=8, offered=8)
    record("TEMP_HP_GRANTED", targets=("a",), before=8, after=8, offered=3)
    record("SAVE_ROLLED", actor="b", targets=(), source="area", success=False)
    record("SAVE_ROLLED", actor="a", targets=(), source="hazard", success=True)
    record("RESOURCE_SPENT", resource_id="Stamina", amount=2)
    record("RESOURCE_SPENT", resource_id="CP", amount=3)
    record("RESOURCE_SPENT", resource_id="Focus", amount=1)
    record("REACTION_RESOLVED")
    record("CONDITION_APPLIED", condition_id="prone")
    record("CONDITION_APPLIED", condition_id="prone", retained_instance_update=1)
    record("CONDITION_APPLIED", targets=("s",), condition_id="blessed")
    record("ATTACK_ROLLED", roll_id="r2", provisional_hit=True, natural_result=19)
    record("REACTION_RESOLVED", actor="b", hit_after_recheck=False)
    record("ATTACK_ROLLED", roll_id="r3", provisional_hit=False, natural_result=19)
    record("PASSIVE_TRIGGERED", roll_id="r3", hit_after_correction=True)
    record("ATTACK_ROLLED", roll_id="r4", provisional_hit=True, natural_result=20)
    record("ATTACK_FORCED_MISS", roll_id="r4")
    record("PASSIVE_TRIGGERED", miss_chance_percent=50, missed=True)
    engine = NS(state=NS(actors=actors, terminal_result="DONE"), events=events,
                action_catalog={"area": NS(owner_id="a")})
    before = deepcopy(events)
    result = build_summary(engine, "test")
    assert events == before
    a, b, s = [row["metrics"] for row in result["actors"]]
    assert a == {**metrics(), "damage_dealt": {"total": 20, "by_type": {"FIRE": 20}},
                 "healing_done": 10, "healing_received": 10, "temporary_hp_granted": 3,
                 "attacks": {"made": 5, "hits": 2, "misses": 3, "critical_hits": 1, "concealment_misses": 1},
                 "saves_forced": {"total": 1, "failed": 1}, "saves_made": {"passed": 1, "failed": 0},
                 "creatures_downed": ["b"], "resources_spent": {"Stamina": 2, "CP": 3, "Focus": 1},
                 "reactions_used": 1, "turns_taken": 1, "conditions_applied_to_enemies": {"prone": 1}}
    assert b["damage_taken"] == {"rolled": 34, "applied": 24, "hp_damage": 19, "temporary_hp_absorbed": 5}
    assert b["times_downed"] == 1 and b["saves_made"]["failed"] == 1
    assert s["damage_dealt"]["total"] == 4
    assert result["summoner_totals"][0]["metrics"]["damage_dealt"]["total"] == 24
    assert result["teams"][1]["metrics"]["damage_dealt"]["total"] == 24
    assert result["highlights"]["most_damage_dealt"] == {"value": 20, "entity_ids": ["a"]}


def test_terminal_table_commit_reload_and_warm_refresh(tmp_path, monkeypatch):
    guard = "tianxia.path.body_refining.feature.stamina_guard"
    summon = "tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation"
    combat, table, mid = table_fight(tmp_path, [guard, summon], primary="Stamina")
    assert "summary" not in table.state(mid)
    # A test scenario uses the documented event hook during a real accepted table
    # action, so preview, reaction choices, COMMIT and reload all execute normally.
    ext.effects()
    def scenario(engine, kind, event):
        if kind != "HOLD_POSITION_COMMITTED" or event.get("actor_id") != LEFT:
            return
        left, ally, right = [engine.state.actors[key] for key in (LEFT, ALLY, RIGHT)]
        source = next(key for key, action in engine.action_catalog.items() if action.owner_id == LEFT)
        action = engine.action_catalog[source]
        script(engine, [20] + [1] * 100)
        engine._resolve_attack_spec(right, left, {"range_ft": 500, "attack_bonus": 100,
            "damage": DiceSpec(count=1, sides=8, modifier=20), "damage_type": "FIRE"},
            engine._active_intent, source_definition_id="test:attack", attack_index=1)
        engine._grant_temp_hp(left, 5, source, ally.entity_id)
        engine._commit_damage(left, 7, "COLD", source, RIGHT, None, reaction_depth=0)
        ctx = typed_executor.Context(engine, left, action, engine._active_intent, {}, [left], left, {})
        typed_executor.block_healing(ctx, {"type": "healing", "dice": {"count": 1, "sides": 8}, "flat": 10})
        # An area save resolves for two creatures from the same caster.
        ctx = typed_executor.Context(engine, left, action, engine._active_intent,
            {"area": {"shape": "sphere", "size_ft": 10}}, [ally, right], None, {"save_dc": 50})
        typed_executor.block_save(ctx, {"type": "save", "ability": "DEX", "applies_to": "creatures_in_area",
            "on_fail": [{"type": "condition", "condition": "prone", "duration": "END_OF_CURRENT_TURN"}]})
        creature = next(a for a in summons.owned_by(engine, LEFT))
        summons.summon(engine, left, creature.summon["group"], source)
        engine._commit_damage(right, 3, "FORCE", source, creature.entity_id, None, reaction_depth=0)
        engine._commit_damage(right, 1000, "FORCE", source, LEFT, None, reaction_depth=0)
        for _ in range(3):
            if right.active:
                engine._commit_damage(right, 1, "FORCE", source, LEFT, None, reaction_depth=0)
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), scenario])
    assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    events = loaded.engine.events
    assert loaded.engine.state.terminal_result
    assert any(e.event_type == "REACTION_RESOLVED" and "stamina_guard" in e.source_definition_id for e in events)
    assert any(e.event_type == "DAMAGE_ROLLED" and str(e.payload.get("reason", "")).startswith("HEALING:") for e in events)
    assert any(e.event_type == "SUMMON_APPEARED" for e in events)
    directory = loaded.store.match_dir
    before = inventory(directory)
    result = table.summary(mid)
    assert table.state(mid)["summary"] == result
    assert TabletopService(CombatService(ROOT, tmp_path), tmp_path).summary(mid) == result
    assert inventory(directory) == before
    assert loaded.mechanical.replay()["status"] == "PASS"
    rows = {row["entity_id"]: row for row in result["actors"]}
    for key, row in rows.items():
        m = row["metrics"]
        damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and key in e.target_ids]
        dealt = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == key]
        heals = [e for e in events if e.event_type == "HEALING_APPLIED"]
        assert m["damage_taken"] == {"rolled": sum(e.payload["rolled_or_pending_damage"] for e in damage),
            "applied": sum(e.payload["reduced_to"] for e in damage), "hp_damage": sum(e.payload["hp_damage"] for e in damage),
            "temporary_hp_absorbed": sum(e.payload["temporary_hp_absorbed"] for e in damage)}
        assert m["damage_dealt"]["total"] == sum(e.payload["reduced_to"] for e in dealt)
        assert m["healing_done"] == sum(e.payload["after"]-e.payload["before"] for e in heals if e.actor_id == key)
        assert m["healing_received"] == sum(e.payload["after"]-e.payload["before"] for e in heals if key in e.target_ids)
        assert m["temporary_hp_granted"] == sum(max(0, e.payload["after"]-e.payload["before"])
            for e in events if e.event_type == "TEMP_HP_GRANTED" and e.actor_id == key)
        attacks = [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == key]
        assert m["attacks"] == {"made": len(attacks), "hits": sum(e.payload["provisional_hit"] for e in attacks),
            "misses": sum(not e.payload["provisional_hit"] for e in attacks),
            "critical_hits": sum(e.payload["provisional_hit"] and e.payload["natural_result"] >= 20 for e in attacks),
            "concealment_misses": 0}
        saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == key]
        assert m["saves_made"] == {"passed": sum(e.payload["success"] for e in saves),
                                    "failed": sum(not e.payload["success"] for e in saves)}
        spent = {}
        for e in events:
            if e.event_type == "RESOURCE_SPENT" and e.actor_id == key:
                rid = e.payload["resource_id"]
                spent[rid] = spent.get(rid, 0) + e.payload["amount"]
        assert m["resources_spent"] == spent
        assert m["reactions_used"] == sum(e.event_type == "REACTION_RESOLVED" and e.actor_id == key for e in events)
        conditions = {}
        for e in events:
            if (e.event_type == "CONDITION_APPLIED" and e.actor_id == key
                    and any(rows[t]["team"] != row["team"] for t in e.target_ids)
                    and not e.payload.get("retained_instance_update")):
                cid = e.payload["condition_id"]
                conditions[cid] = conditions.get(cid, 0) + 1
        assert m["conditions_applied_to_enemies"] == conditions
        assert m["turns_taken"] == sum(e.event_type == "TURN_STARTED" and e.actor_id == key for e in events)
        assert row["final_hp"] == loaded.engine.state.actors[key].current_hp
        if row["final_hp"] > 0:
            assert row["life_state"] == "CONSCIOUS"  # absent summons are inactive, not defeated
    assert rows[LEFT]["metrics"]["saves_forced"]["total"] >= 2
    assert rows[RIGHT]["metrics"]["times_downed"] == 1
    assert RIGHT in rows[LEFT]["metrics"]["creatures_downed"]
    assert rows[LEFT]["metrics"]["damage_taken"]["rolled"] > rows[LEFT]["metrics"]["damage_taken"]["applied"]
    assert rows[LEFT]["metrics"]["damage_taken"]["temporary_hp_absorbed"] == 5
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    import httpx
    app = create_app(Settings.from_env(ROOT, tmp_path))
    async def get_summary():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
            response = await client.get(f"/api/tabletop/matches/{mid}/summary")
            assert response.status_code == 200, response.text
            assert response.json() == result
    run_asgi(get_summary())
    # Actual warm state requests including saved-session loading. Interleave the
    # control and treatment to avoid giving one arm all the earlier cache warms.
    original = table._fight_summary
    samples = {False: [], True: []}
    cpu_samples = {False: [], True: []}
    gc.collect()
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for index in range(20):
            for enabled in ((True, False) if index % 2 else (False, True)):
                monkeypatch.setattr(table, "_fight_summary", original if enabled else lambda *_: {})
                start, cpu_start = time.perf_counter(), time.process_time()
                table.state(mid)
                samples[enabled].append(time.perf_counter()-start)
                cpu_samples[enabled].append(time.process_time()-cpu_start)
    finally:
        monkeypatch.setattr(table, "_fight_summary", original)
        if gc_was_enabled:
            gc.enable()
    baseline, warm = median(samples[False]), median(samples[True])
    cpu_baseline, cpu_warm = median(cpu_samples[False]), median(cpu_samples[True])
    print(f"SOL143 warm state seconds: baseline={baseline:.6f}, summary={warm:.6f}, delta={warm-baseline:.6f}")
    print(f"SOL143 warm state CPU seconds: baseline={cpu_baseline:.6f}, summary={cpu_warm:.6f}, delta={cpu_warm-cpu_baseline:.6f}")
    # Other lanes share this host: CPU time measures our work without charging
    # another lane's scheduling delays. Keep wall measurements in the report too.
    assert cpu_warm <= cpu_baseline * 1.1 + .001


def test_saved_fight_summary_is_read_only_after_cold_reload(tmp_path):
    combat, _, match_id = table_fight(tmp_path, [])
    source = combat._match_dir(match_id)
    before = inventory(source)
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    summary = table.summary(match_id)
    assert summary["actors"] and summary["match_id"] == match_id
    assert inventory(source) == before


def test_summary_cache_is_bounded_isolated_and_invalidated(monkeypatch, tmp_path):
    from combat import fight_summary
    calls = []
    monkeypatch.setattr(fight_summary, "build_summary", lambda engine, mid: calls.append(mid) or {"actors": []})
    table = TabletopService(None, tmp_path)
    engine = NS(state=NS(state_version=1), events=[])
    table._fight_summary("m", engine)["actors"].append("poison")
    assert table._fight_summary("m", engine) == {"actors": []}
    assert calls == ["m"]
    engine.events.append(None)
    table._fight_summary("m", engine)
    engine.state.state_version += 1
    table._fight_summary("m", engine)
    assert calls == ["m"] * 3
    for i in range(12):
        table._fight_summary(str(i), engine)
    assert len(table._summary_cache) == 8


def test_sparse_historical_metrics_do_not_invent_outcomes():
    actor = NS(entity_id="old", display_name="Old", team_id="red", owner_id=None,
               summon=None, current_hp=8, maximum_hp=20, life_state=None, active=True, conditions={})
    engine = NS(state=NS(actors={"old": actor}, terminal_result=None), action_catalog={}, events=[
        NS(event_type="ATTACK_ROLLED", actor_id="old", target_ids=(), source_definition_id="old:attack",
           sequence=1, payload={"roll_id": "unknown"}),
        NS(event_type="DAMAGE_COMMITTED", actor_id=None, target_ids=("old",), source_definition_id="hazard",
           sequence=2, payload={"hp_damage": 2, "remaining_hp": 8}),
        NS(event_type="SAVE_ROLLED", actor_id="old", target_ids=(), source_definition_id="hazard",
           sequence=3, payload={"total": 10}),
        NS(event_type="HEALING_APPLIED", actor_id="old", target_ids=("old",), source_definition_id="heal",
           sequence=4, payload={"after": 8}),
        NS(event_type="TEMP_HP_GRANTED", actor_id="old", target_ids=("old",), source_definition_id="grant",
           sequence=5, payload={"after": 8}),
    ])
    result = build_summary(engine, "old")
    m = result["actors"][0]["metrics"]
    assert m["attacks"] == {**metrics()["attacks"], "made": 1}
    assert m["saves_made"] == {"passed": 0, "failed": 0}
    assert m["damage_taken"] == {"rolled": 2, "applied": 2, "hp_damage": 2, "temporary_hp_absorbed": 0}
    assert m["healing_done"] == m["healing_received"] == m["temporary_hp_granted"] == 0
    assert len(result["limitations"]) == 6


@pytest.mark.parametrize("case", ["defense", "auto_save", "cancelled_critical", "qualified_critical"])
def test_final_outcomes_through_table_commit_reload(tmp_path, monkeypatch, case):
    """Use real resolvers and their receipts, including typed self-defense shape."""
    armor = "tianxia.path.qi_cultivation.feature.qi_armor"
    combat, table, mid = table_fight(tmp_path, [armor] if case == "defense" else [])
    ext.effects()
    if case == "cancelled_critical":
        monkeypatch.setitem(ext._HOOKS, "critical_cancel", [lambda *args: True])

    def scenario(engine, kind, event):
        if kind != "HOLD_POSITION_COMMITTED" or event.get("actor_id") != LEFT:
            return
        left, right = [engine.state.actors[key] for key in (LEFT, RIGHT)]
        source = next(key for key, action in engine.action_catalog.items() if action.owner_id == LEFT)
        if case == "auto_save":
            engine._apply_condition(right, "condition:typed.paralyzed", source, LEFT,
                                    expires_on="END_OF_CURRENT_TURN")
            engine._roll_save(right, "DEX", 10, source)
            return
        if case == "qualified_critical":
            engine._apply_condition(right, "condition:typed.paralyzed", source, LEFT,
                                    expires_on="END_OF_CURRENT_TURN")
        # First attack points the opposite way from the later self-defense;
        # a bad attribution must not rewrite this earlier attack against Right.
        script(engine, [20 if case == "cancelled_critical" else 10] + [1] * 100)
        engine._resolve_attack_spec(left, right, {"reach_ft": 5, "attack_bonus": 100,
            "damage": DiceSpec(count=1, sides=4), "damage_type": "FORCE"},
            engine._active_intent, source_definition_id=source, attack_index=1)
        if case == "defense":
            script(engine, [10] + [1] * 100)
            engine._resolve_attack_spec(right, left, {"range_ft": 500, "attack_bonus": 5,
                "damage": DiceSpec(count=1, sides=4), "damage_type": "FORCE"},
                engine._active_intent, source_definition_id="test:incoming", attack_index=2)

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), scenario])
    assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(mid)
    events = session.engine.events
    summary = TabletopService(fresh, tmp_path).summary(mid)
    assert summary == table.summary(mid)
    rows = {row["entity_id"]: row["metrics"] for row in summary["actors"]}
    if case == "defense":
        defense = next(e for e in events if e.event_type == "REACTION_RESOLVED"
                       and e.payload.get("hit_after_recheck") is False)
        assert defense.actor_id == LEFT and defense.target_ids == (RIGHT,)
        assert rows[RIGHT]["attacks"] == {**metrics()["attacks"], "made": 1, "misses": 1}
        assert rows[LEFT]["attacks"] == {**metrics()["attacks"], "made": 1, "hits": 1}
    elif case == "auto_save":
        assert sum(e.event_type == "SAVE_AUTO_FAILED" for e in events) == 1
        assert sum(e.event_type == "SAVE_ROLLED" for e in events) == 1
        assert rows[RIGHT]["saves_made"] == {"passed": 0, "failed": 1}
        assert rows[LEFT]["saves_forced"] == {"total": 1, "failed": 1}
    else:
        receipt = next(e for e in events if e.event_type == "ATTACK_CRITICAL_RESOLVED")
        critical = case == "qualified_critical"
        assert receipt.payload["critical"] is critical
        assert receipt.payload["cancelled"] is (not critical)
        assert rows[LEFT]["attacks"] == {**metrics()["attacks"], "made": 1,
                                       "hits": 1, "critical_hits": int(critical)}
    assert session.mechanical.replay()["status"] == "PASS"


def test_marker_only_historical_save_is_counted_once():
    actor = NS(entity_id="old", display_name="Old", team_id="red", owner_id=None,
               summon=None, current_hp=8, maximum_hp=20, life_state=None, active=True, conditions={})
    engine = NS(state=NS(actors={"old": actor}, terminal_result=None), action_catalog={}, events=[
        NS(event_type="SAVE_AUTO_FAILED", actor_id="old", target_ids=(), source_definition_id="hazard",
           sequence=1, payload={"ability": "DEX"})])
    assert build_summary(engine, "old")["actors"][0]["metrics"]["saves_made"] == {"passed": 0, "failed": 1}
    # A later ordinary save of the same ability/source is a separate save,
    # even if an earlier historical marker has no matching result.
    engine.events.extend([
        NS(event_type="INTENT_ACCEPTED", actor_id="old", target_ids=(), source_definition_id="hazard",
           sequence=2, payload={"kind": "ACTION"}),
        NS(event_type="SAVE_ROLLED", actor_id="old", target_ids=(), source_definition_id="hazard",
           sequence=3, payload={"reason": "SAVE:hazard:DEX", "success": True}),
    ])
    assert build_summary(engine, "old")["actors"][0]["metrics"]["saves_made"] == {"passed": 1, "failed": 1}


@pytest.mark.parametrize("kind,reactor,targets,payload", [
    ("REACTION_RESOLVED", "b", ("b",), {}),  # native self-defense
    ("PASSIVE_TRIGGERED", "b", ("a",), {}),  # typed passive self-defense
    ("REACTION_RESOLVED", "ally", ("a",), {"protects": "b"}),
])
def test_defensive_event_conventions_only_correct_the_protected_attack(kind, reactor, targets, payload):
    actors = {key: NS(entity_id=key, display_name=key, team_id=key, owner_id=None,
                     summon=None, current_hp=30, maximum_hp=30, life_state=None, active=True, conditions={})
              for key in ("a", "b", "ally")}
    def event(kind, actor, targets, sequence, **payload):
        return NS(event_type=kind, actor_id=actor, target_ids=targets, sequence=sequence,
                  source_definition_id="test:attack", payload=payload)
    events = [event("ATTACK_ROLLED", "b", ("a",), 1, roll_id="earlier", provisional_hit=True, natural_result=10),
              event("ATTACK_ROLLED", "a", ("b",), 2, roll_id="current", provisional_hit=True, natural_result=10),
              event(kind, reactor, targets, 3, hit_after_recheck=False, **payload)]
    result = build_summary(NS(state=NS(actors=actors, terminal_result=None), events=events, action_catalog={}), "test")
    rows = {row["entity_id"]: row["metrics"]["attacks"] for row in result["actors"]}
    assert rows["a"]["misses"] == 1 and rows["a"]["hits"] == 0
    assert rows["b"]["hits"] == 1 and rows["b"]["misses"] == 0


def test_passive_and_carried_receipts_are_not_counted_as_reactions():
    """A real reaction counts once; passive and carried-budget receipts are not reactions taken."""
    actors = {key: NS(entity_id=key, display_name=key.upper(), team_id=team, owner_id=None, summon=None,
                      current_hp=30, maximum_hp=40, life_state=None, active=True, conditions={})
              for key, team in (("a", "red"), ("b", "blue"))}
    events = []
    def record(kind, **payload):
        events.append(NS(event_type=kind, actor_id="a", target_ids=("b",), source_definition_id="feature.x",
                         payload=payload, sequence=len(events)+1))
    record("REACTION_RESOLVED", checkpoint="DAMAGE_APPLICATION", reduction=4, pending_before=9, pending_after=5)
    record("REACTION_RESOLVED", passive=True, checkpoint="DAMAGE_APPLICATION", reduction=3, damage_type="FIRE")
    record("REACTION_RESOLVED", carried_budget=True, checkpoint="DAMAGE_APPLICATION", reduction=2)
    engine = NS(state=NS(actors=actors, terminal_result="DONE"), events=events, action_catalog={})
    result = build_summary(engine, "test")
    a = result["actors"][0]["metrics"]  # actors are reported in the order given (a, b)
    assert a["reactions_used"] == 1
