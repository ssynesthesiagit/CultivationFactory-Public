"""Condition qualification and critical/DC rules in table commits and fresh loads."""
import pytest

from combat.gate5_service import CombatService
from combat.gate2_runtime_models import DiceSpec
from tests.h1_support import ROOT, script
from tests.test_sol78_conditions import loaded_table
from tests.test_tabletop_hunt6 import LEFT, RIGHT, ALLY, HOLD


@pytest.mark.parametrize("prefix", ["core", "typed"])
@pytest.mark.parametrize("blocking", [None, "grappled", "incapacitated", "paralyzed"])
def test_dodge_benefits_qualified_after_table_reload(tmp_path, monkeypatch, prefix, blocking):
    def stage(engine):
        target = engine.state.actors[RIGHT]
        engine._apply_condition(target, f"condition:{prefix}.dodge", HOLD, RIGHT, expires_on="UNTIL_REMOVED")
        if blocking:
            engine._apply_condition(target, "condition:typed." + blocking, HOLD, LEFT, expires_on="UNTIL_REMOVED")
        engine._roll_save(target, "DEX", 10, "test:dodge-save")
        script(engine, [5, 5])
        engine._resolve_attack_spec(engine.state.actors[LEFT], target,
                                   {"attack_bonus": 100, "reach_ft": 100}, engine._active_intent,
                                   source_definition_id="test:dodge-attack")

    _, _, _, engine = loaded_table(tmp_path, monkeypatch, stage)
    target = engine.state.actors[RIGHT]
    mode = engine._attack_mode(engine.state.actors[LEFT], target)
    assert mode == ("ADVANTAGE" if blocking == "paralyzed" else "NORMAL" if blocking else "DISADVANTAGE")
    attacks = [r for r in engine.rolls if "test:dodge-attack" in r.reason]
    assert attacks[-1].mode == mode
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == "test:dodge-save"]
    assert saves[-1].payload["mode"] == ("NORMAL" if blocking else "ADVANTAGE")


@pytest.mark.parametrize("visible", [False, True])
def test_frightened_attack_gated_by_source_sight_after_reload(tmp_path, monkeypatch, visible):
    def stage(engine):
        actor, source = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        engine._apply_condition(actor, "condition:typed.frightened", HOLD, RIGHT, expires_on="UNTIL_REMOVED")
        if not visible:
            engine._apply_condition(source, "condition:typed.invisible", HOLD, RIGHT, expires_on="UNTIL_REMOVED")
        # Attack someone other than the source, so Invisible itself adds no mode.
        spec = {"attack_bonus": 100, "reach_ft": 100}
        script(engine, [5, 5])
        engine._resolve_attack_spec(actor, engine.state.actors[ALLY], spec, engine._active_intent,
                                   source_definition_id="test:frightened-attack")

    _, _, _, engine = loaded_table(tmp_path, monkeypatch, stage)
    rolls = [r for r in engine.rolls if "test:frightened-attack" in r.reason]
    assert rolls[-1].mode == ("DISADVANTAGE" if visible else "NORMAL")
    assert engine._attack_mode(engine.state.actors[LEFT], engine.state.actors[ALLY]) == rolls[-1].mode


@pytest.mark.parametrize("condition", ["paralyzed", "unconscious", "life_unconscious"])
@pytest.mark.parametrize("distance", [5, 10])
def test_condition_hit_is_critical_only_within_five_feet(tmp_path, monkeypatch, condition, distance):
    def stage(engine):
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        engine._apply_condition(target, "condition:typed." + condition, HOLD, LEFT, expires_on="UNTIL_REMOVED")
        spec = {"attack_bonus": 100, "reach_ft": 100,
                "damage": DiceSpec(count=1, sides=4, modifier=0), "damage_type": "FORCE"}
        script(engine, [5, 5, 3, 3])
        engine._resolve_attack_spec(actor, target, spec, engine._active_intent,
                                   source_definition_id="test:condition-critical")
        assert spec["resolved_attack_context"].critical is (distance == 5)

    # Use the existing fixture's persisted starting positions rather than mutate state.
    from tests.test_tabletop_hunt6 import table_fight
    from combat import ext
    from tests.test_lock2_persistence import act
    combat, table, mid = table_fight(tmp_path, [], starts={"team1": [[3, 4], [3, 5]],
                                                         "team2": [[3 + distance // 5, 4]]})
    with monkeypatch.context() as fixture:
        def event(engine, event_type, kwargs):
            if event_type == "HOLD_POSITION_COMMITTED":
                stage(engine)
        fixture.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", ()), event])
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    damage = [e for e in session.engine.events if e.event_type == "DAMAGE_ROLLED"
              and e.source_definition_id == "test:condition-critical"][-1]
    assert damage.payload["critical"] is (distance == 5)
    assert len(damage.payload["dice"]) == (2 if distance == 5 else 1)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("source_distance,expected", [(25, "DISADVANTAGE"), (40, "NORMAL")])
def test_frightened_uses_real_sight_before_blindsight_attack_projection(tmp_path, monkeypatch, source_distance, expected):
    from combat import ext, senses
    from combat.target_knowledge import can_see
    from tests.test_lock2_persistence import act
    from tests.test_tabletop_hunt6 import table_fight

    _, table, mid = table_fight(tmp_path, [], starts={"team1": [[3, 4], [4, 4]],
                                                    "team2": [[3 + source_distance // 5, 4]]})
    observations = []

    def stage(engine, event_type, kwargs):
        if event_type != "HOLD_POSITION_COMMITTED":
            return
        actor, target, source = (engine.state.actors[x] for x in (LEFT, ALLY, RIGHT))
        engine._apply_condition(actor, "condition:typed.blinded", HOLD, RIGHT, expires_on="UNTIL_REMOVED")
        engine._apply_condition(actor, senses.SENSE, HOLD, LEFT, expires_on="UNTIL_REMOVED",
                                data={"sense": "blindsight", "range_ft": 30})
        engine._apply_condition(actor, "condition:typed.frightened", HOLD, RIGHT, expires_on="UNTIL_REMOVED")
        observations.append((can_see(engine, actor, target), can_see(engine, actor, source)))
        script(engine, [5, 5])
        engine._resolve_attack_spec(actor, target, {"attack_bonus": 100, "reach_ft": 100},
                                   engine._active_intent, source_definition_id="test:blinded-fear-attack")

    with monkeypatch.context() as fixture:
        fixture.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", ()), stage])
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
    assert observations and all(row == (True, source_distance <= 30) for row in observations)
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = session.engine
    actor, target, source = (engine.state.actors[x] for x in (LEFT, ALLY, RIGHT))
    assert can_see(engine, actor, source) is (source_distance <= 30)
    assert any(c.condition_id == "condition:typed.blinded" for c in actor.conditions.values())
    rolls = [r for r in engine.rolls if "test:blinded-fear-attack" in r.reason]
    assert rolls[-1].mode == expected
    assert engine._attack_mode(actor, target) == expected
    assert any(c.condition_id == "condition:typed.blinded" for c in actor.conditions.values())
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("cancel", [False, True])
def test_automatic_critical_respects_misses_and_cancellation(tmp_path, monkeypatch, cancel):
    from combat import ext
    if cancel:
        monkeypatch.setitem(ext._HOOKS, "critical_cancel",
                            [*ext._HOOKS.get("critical_cancel", ()), lambda *args: True])

    resolved = []

    def stage(engine):
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        engine._apply_condition(target, "condition:typed.paralyzed", HOLD, LEFT, expires_on="UNTIL_REMOVED")
        spec = {"attack_bonus": 100, "reach_ft": 100,
                "damage": DiceSpec(count=1, sides=4, modifier=0), "damage_type": "FORCE"}
        script(engine, [5, 5, 3] if cancel else [1, 1])
        hit = engine._resolve_attack_spec(actor, target, spec, engine._active_intent,
                                         source_definition_id="test:critical-control")
        resolved.append((hit, spec.get("resolved_attack_context")))

    _, _, _, engine = loaded_table(tmp_path, monkeypatch, stage)
    assert resolved
    for hit, packet in resolved:
        assert hit is cancel
        if cancel:
            assert not packet.critical
            assert packet.critical_cancelled
    criticals = [e for e in engine.events if e.event_type == "ATTACK_CRITICAL_RESOLVED"
                and e.source_definition_id == "test:critical-control"]
    damage = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
              and e.source_definition_id == "test:critical-control"]
    assert bool(criticals) is bool(damage) is cancel
    if cancel:
        assert criticals[-1].payload["cancelled"] and not criticals[-1].payload["critical"]
        assert len(damage[-1].payload["dice"]) == 1


@pytest.mark.parametrize("damage,dc", [(21, 10), (30, 15), (60, 30), (80, 30)])
def test_concentration_dc_cap_after_table_commit_reload(tmp_path, monkeypatch, damage, dc):
    def stage(engine):
        target = engine.state.actors[LEFT]
        engine._start_concentration(target, "test:concentration")
        engine._grant_temp_hp(target, 100, "test:buffer", LEFT)
        script(engine, [1])
        engine._commit_damage(target, damage, "UNTYPED", "test:concentration-damage", RIGHT, None, reaction_depth=0)

    _, _, _, engine = loaded_table(tmp_path, monkeypatch, stage)
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == "system:combat.concentration"]
    assert [e.payload["dc"] for e in saves] == [dc]
    assert engine.state.actors[LEFT].concentration is None
