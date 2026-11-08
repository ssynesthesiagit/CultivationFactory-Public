"""AUDIT5 condition rules through accepted table commits and fresh disk loads.

Synthetic rules are applied by a test-only event registration during Hold. No
engine methods are replaced and no browser or live store is used.
Locked auto-critical, Dodge, concentration and stand-up rules are Astra items.
"""
import json
import ast

import pytest

from combat import ext, typed_executor
from combat.condition_text import all_conditions
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT, HOLD, ROOT, table_fight, answer_action


def loaded_table(tmp_path, monkeypatch, callback, *, talents=()):
    combat, table, mid = table_fight(tmp_path, list(talents))
    with monkeypatch.context() as fixture:
        def stage(engine, event_type, kwargs):
            if event_type == "HOLD_POSITION_COMMITTED":
                callback(engine)

        fixture.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", ()), stage])
        assert answer_action(table, mid, HOLD, pick="roll")["status"] == "COMMITTED"
    combat = CombatService(ROOT, tmp_path)
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return combat, TabletopService(combat, tmp_path), mid, session.engine


@pytest.mark.parametrize("damage_type", ["FORCE", "POISON", "FIRE", "BLUDGEONING"])
def test_petrified_halves_each_damage_type_and_blocks_poisoned_after_table_reload(tmp_path, monkeypatch, damage_type):
    def petrify_and_damage(engine):
        target = engine.state.actors[RIGHT]
        engine._apply_condition(target, "condition:typed.petrified", HOLD, LEFT, expires_on="UNTIL_REMOVED")
        engine._commit_damage(target, 11, damage_type, HOLD, LEFT, None, reaction_depth=0)

    _, table, mid, engine = loaded_table(tmp_path, monkeypatch, petrify_and_damage)
    target = engine.state.actors[RIGHT]
    assert target.current_hp == target.maximum_hp - 5
    assert typed_executor.condition_immune(engine, target, "poisoned")
    assert not typed_executor.condition_immune(engine, target, "frightened")
    assert not typed_executor.condition_immune(engine, engine.state.actors[LEFT], "poisoned")
    text = next(c["rule_text"] for a in table.state(mid)["presentation"]["actors"] if a["entity_id"] == RIGHT
                for c in a["conditions"] if c["condition_id"] == "condition:typed.petrified")
    assert "half damage" in text and "can't become Poisoned" in text
    # Attempt the actual typed application in a second committed transaction,
    # after Petrified has been loaded from disk; query coverage alone is weaker.
    def poison(engine):
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT)
        ctx = typed_executor.Context(engine, actor, action, engine._active_intent,
                                     {"numbers": {}}, [target], target)
        typed_executor.block_condition(ctx, {"condition": "poisoned", "applies_to": "target",
                                              "duration": {"kind": "until_removed"}})
        # Positive control: this same application must reach a non-immune actor.
        control = typed_executor.Context(engine, actor, action, engine._active_intent,
                                         {"numbers": {}}, [actor], actor)
        typed_executor.block_condition(control, {"condition": "poisoned", "applies_to": "target",
                                                 "duration": {"kind": "until_removed"}})

    with monkeypatch.context() as fixture:
        def stage(engine, event_type, kwargs):
            if event_type == "HOLD_POSITION_COMMITTED":
                poison(engine)
        fixture.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", ()), stage])
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not any(c.condition_id == "condition:typed.poisoned"
                   for c in session.engine.state.actors[RIGHT].conditions.values())
    assert any(c.condition_id == "condition:typed.poisoned"
               for c in session.engine.state.actors[LEFT].conditions.values())
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("name", ["unconscious", "life_unconscious"])
@pytest.mark.parametrize("bearer", ["rider", "mount"])
def test_unconscious_companion_prone_reaches_mounted_fall_after_table_reload(tmp_path, monkeypatch, name, bearer):
    from combat.ext import mounts
    from tests.hunt19_support import fight

    combat, table, mid = fight(tmp_path, ["BEASTMASTERY_BASE_RIDER_PACKAGE"], ask=False)
    staged = {}
    with monkeypatch.context() as fixture:
        def stage(engine, event_type, kwargs):
            if event_type != "HOLD_POSITION_COMMITTED":
                return
            rider = engine.state.actors[LEFT]
            mount = mounts.mount_of(engine, rider)
            assert mount is not None
            staged["mount"] = mount.entity_id
            staged["start"] = rider.position
            # An Unconscious rider auto-fails DEX. For the mount case, use a
            # conscious rider with a scripted failed save, without mutating
            # non-evented character statistics in a persisted transaction.
            if bearer == "mount":
                from tests.h1_support import script
                script(engine, [1])
            target = rider if bearer == "rider" else mount
            engine._apply_condition(target, "condition:typed." + name, HOLD, RIGHT, expires_on="UNTIL_REMOVED")

        fixture.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", ()), stage])
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = session.engine
    rider, mount = engine.state.actors[LEFT], engine.state.actors[staged["mount"]]
    assert mounts.mount_of(engine, rider) is mounts.rider_of(engine, mount) is None
    assert rider.position != staged["start"]
    assert not set(engine._actor_cells(rider)) & set(engine._actor_cells(mount))
    assert engine.grid.distance_ft(rider.position, mount.position) <= 5
    for actor in (rider, mount) if bearer == "mount" else (rider,):
        assert any(c.condition_id == mounts.PRONE for c in actor.conditions.values())
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == mounts.SRC]
    assert len(saves) == 1 and not saves[0].payload["success"]
    if bearer == "rider":
        assert any(e.event_type == "SAVE_AUTO_FAILED" and e.actor_id == LEFT for e in engine.events)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
    engine._assert_invariants()


@pytest.mark.parametrize("condition", ["frightened", "poisoned"])
def test_last_inch_control_save_ignores_check_penalties_and_commits_visible_outcome(tmp_path, monkeypatch, condition):
    from combat import unmaking
    from combat.target_knowledge import can_see
    from tests.h1_support import script

    def gain_strain(engine):
        actor, source = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        engine._apply_condition(actor, "condition:typed." + condition, HOLD, RIGHT, expires_on="UNTIL_REMOVED")
        assert can_see(engine, actor, source)
        assert typed_executor.check_mode(actor, "CON", engine=engine) == "DISADVANTAGE"
        action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT)
        ctx = typed_executor.Context(engine, actor, action, engine._active_intent,
                                     {"numbers": {"save_dc": 15, "pb": 5}}, [actor], actor)
        script(engine, [19, 1])  # NORMAL succeeds; the old check's Disadvantage fails.
        unmaking.gain_strain_checked(ctx, 1, HOLD)

    _, table, mid, engine = loaded_table(tmp_path, monkeypatch, gain_strain,
                                       talents=["TAL_UNMAKING_LAST_INCH_CONTROL"])
    actor = engine.state.actors[LEFT]
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == "passive:TAL_UNMAKING_LAST_INCH_CONTROL"]
    assert len(saves) == 1 and saves[0].payload["mode"] == "NORMAL" and saves[0].payload["success"]
    assert actor.resources[unmaking.STRAIN] == 0
    assert actor.current_hp == actor.maximum_hp - 5
    assert actor.turn_flags["last_inch_control_used"]
    shown = next(a for a in table.state(mid)["presentation"]["actors"] if a["entity_id"] == LEFT)
    assert any(c["condition_id"] == "condition:typed." + condition for c in shown["conditions"])
    damage = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
              and str(e.source_definition_id).endswith(".last_inch_control")]
    assert len(damage) == 1 and damage[0].target_ids == (LEFT,)
    visible_saves = [e["summary"] for e in table.events(mid, 0)["events"]
                     if e["event_type"] == "SAVE_ROLLED" and "Last Inch Control" in e["summary"]]
    assert len(visible_saves) == 1 and "Success" in visible_saves[0]
    assert "disadvantage" not in visible_saves[0].lower()


@pytest.mark.parametrize("name", ["unconscious", "life_unconscious"])
@pytest.mark.parametrize("wake", [False, True])
def test_unconscious_includes_prone_and_leaves_it_after_waking_on_saved_table(tmp_path, monkeypatch, name, wake):
    def apply_and_maybe_wake(engine):
        actor = engine.state.actors[RIGHT]
        # The legacy inline rule remains readable while acquiring shared rules.
        data = {"rule": {"attacked_with": "ADVANTAGE"}} if name == "life_unconscious" else None
        engine._apply_condition(actor, "condition:typed." + name, HOLD, LEFT,
                                expires_on="UNTIL_REMOVED", data=data)
        if wake:
            if name == "life_unconscious":
                # Old saves carried an inline Unconscious rule without Prone.
                # Reproduce that shape before ending the legacy condition.
                engine._remove_condition(actor, "condition:typed.prone", HOLD)
            engine._remove_condition(actor, "condition:typed." + name, HOLD)

    _, table, mid, engine = loaded_table(tmp_path, monkeypatch, apply_and_maybe_wake)
    target, attacker = engine.state.actors[RIGHT], engine.state.actors[LEFT]
    assert any(c.condition_id == "condition:typed.prone" for c in target.conditions.values())
    assert engine._attack_mode(attacker, target) == "ADVANTAGE"
    attacker.position = attacker.position.model_copy(update={"x": 1})
    assert engine._attack_mode(attacker, target) == ("DISADVANTAGE" if wake else "NORMAL")
    if not wake:
        assert any(row.get("critical_hit_within_ft") == 5 for row in typed_executor.condition_rules(target))
        condition = next(c for a in table.state(mid)["presentation"]["actors"] if a["entity_id"] == RIGHT
                         for c in a["conditions"] if c["condition_id"] == "condition:typed." + name)
        assert "Incapacitated and Prone" in condition["rule_text"]


@pytest.mark.parametrize("visible", [True, False])
def test_frightened_check_disadvantage_requires_visible_source_after_table_reload(tmp_path, monkeypatch, visible):
    def frighten(engine):
        actor = engine.state.actors[LEFT]
        source = engine.state.actors[RIGHT]
        engine._apply_condition(actor, "condition:typed.frightened", HOLD, RIGHT, expires_on="UNTIL_REMOVED")
        engine._apply_condition(actor, "condition:typed.grappled", HOLD, RIGHT, expires_on="UNTIL_REMOVED",
                                data={"escape_dc": 99, "reach_ft": 5})
        if not visible:
            engine._apply_condition(source, "condition:typed.invisible", HOLD, RIGHT, expires_on="UNTIL_REMOVED")

    combat, table, mid, engine = loaded_table(tmp_path, monkeypatch, frighten)
    actor = engine.state.actors[LEFT]
    assert typed_executor.check_mode(actor, "STR", "athletics", engine=engine) == ("DISADVANTAGE" if visible else "NORMAL")
    assert typed_executor.check_mode(actor, "WIS", "perception", engine=engine) == ("DISADVANTAGE" if visible else "NORMAL")
    # The general contextual seam is ready for Astra's locked attack caller.
    rows = typed_executor.condition_rules(actor, engine=engine)
    assert any(row.get("attacks_have") == "DISADVANTAGE" for row in rows) == visible
    # Resolve the actual Escape Grapple action, not only a pure mode query.
    from tests.test_l18_standard_conditions_table import _commit

    for _ in range(8):
        state = table.state(mid)
        groups = [g for g in state["menu"]["actions"] if "escape" in g["source_definition_id"]]
        if state["menu"]["actor_id"] == LEFT and groups:
            _commit(table, mid, groups[0]["source_definition_id"])
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    else:
        pytest.fail("table never offered Escape Grapple")
    session = combat._load_session(mid)
    checks = [e for e in session.engine.events if e.event_type == "CHECK_ROLLED"
              and "escape" in str(e.source_definition_id)]
    assert len(checks) == 1
    assert checks[0].payload["actor"]["mode"] == ("DISADVANTAGE" if visible else "NORMAL")
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


def test_dodge_glossary_uses_shared_data_and_states_visibility_and_loss_rules():
    row = all_conditions()["dodge"]
    assert row["rule"]["disabled_if_incapacitated_or_speed_zero"]
    assert "if it can see the attacker" in " ".join(row["mechanics"])
    assert "Incapacitated or its Speed is 0" in " ".join(row["mechanics"])
    assert "Advantage on Dexterity saving throws" in row["mechanics"]


def test_poisoned_glossary_explains_attacks_and_ability_checks():
    row = all_conditions()["poisoned"]
    assert row["reading"] == "Its attack rolls and all ability checks have Disadvantage."
    assert row["mechanics"] == ["Its attack rolls have Disadvantage", "Disadvantage on ability checks"]


def test_rules_json_rejects_duplicate_keys_in_every_nested_object():
    def unique(pairs):
        found = {}
        for key, value in pairs:
            assert key not in found, f"duplicate rules key: {key}"
            found[key] = value
        return found

    for path in sorted((ROOT / "combat/rules").rglob("*.json")):
        try:
            json.loads(path.read_text(), object_pairs_hook=unique)
        except AssertionError as exc:
            raise AssertionError(f"{path.relative_to(ROOT)}: {exc}") from exc


def test_every_production_check_mode_query_supplies_engine_for_source_visibility():
    missing = []
    for path in (ROOT / "combat").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name in {"check_mode", "check_modes"} and not any(k.arg == "engine" for k in node.keywords):
                missing.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not missing, missing


def test_every_configured_counted_duration_has_a_clock_and_mark_turns_share_vocabulary():
    data = typed_executor.rules()
    for kind, token in data["durations"].items():
        if token is None and kind not in {"instant", "special"}:
            assert typed_executor.duration_round_count(kind, 1) is not None, kind
    for name, kind in data["mark_durations"].items():
        if name.startswith("_"):
            continue
        assert kind in data["durations"]
        assert typed_executor.duration_turn(kind)
        assert typed_executor.marker_expiry(kind)


@pytest.mark.parametrize("kind,amount,rounds", [("rounds", 2, 2), ("minutes", 2, 20), ("hours", 2, 1200)])
def test_counted_condition_and_mark_keep_same_removable_deadline_after_table_reload(tmp_path, monkeypatch, kind, amount, rounds):
    from combat.ext import effect_durations
    from combat import zones

    def apply(engine):
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT)
        duration = {"kind": kind, "amount": amount}
        ctx = typed_executor.Context(engine, actor, action, engine._active_intent,
                                     {"duration": duration, "numbers": {}}, [target], target)
        typed_executor.block_condition(ctx, {"type": "condition", "condition": "smothered", "applies_to": "target", "duration": duration})
        typed_executor.block_mark(ctx, {"type": "mark", "mark": "Test clock", "applies_to": "target", "duration": duration})

    _, _, _, engine = loaded_table(tmp_path, monkeypatch, apply)
    target = engine.state.actors[RIGHT]
    conditions = [c for c in target.conditions.values() if c.condition_id == "condition:typed.smothered"
                  or c.condition_id.startswith("condition:typed.mark.test_clock.")]
    assert len(conditions) == 2
    assert conditions[0].expires_on == conditions[1].expires_on
    deadline = effect_durations.parse_round(conditions[0].expires_on)
    assert deadline is not None
    assert deadline[0] == engine.state.round_number + rounds
    assert zones._duration_rounds({"kind": kind, "amount": amount}) == rounds
    # Exact boundary query on the freshly loaded copy; no live time/state jump.
    engine.state.round_number, engine.state.current_slot_index = deadline[0] - 1, deadline[1]
    assert not effect_durations.due(engine, conditions[0].expires_on)
    engine.state.round_number = deadline[0]
    assert effect_durations.due(engine, conditions[0].expires_on)


@pytest.mark.parametrize("kind", ["until_end_of_your_next_turn", "until_start_of_your_next_turn"])
def test_mark_and_effect_your_next_turn_share_source_and_expire_after_table_reload(tmp_path, monkeypatch, kind):
    def apply(engine):
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT)
        ctx = typed_executor.Context(engine, actor, action, engine._active_intent,
                                     {"duration": {"kind": "instant"}, "numbers": {}}, [target], target)
        typed_executor.block_condition(ctx, {"condition": "smothered", "applies_to": "target", "duration": {"kind": kind}})
        typed_executor.block_mark(ctx, {"mark": "Test turn", "applies_to": "target", "duration": {"kind": kind}})

    combat, table, mid, engine = loaded_table(tmp_path, monkeypatch, apply)
    applied_turn = engine.state.actors[LEFT].turns_started
    target = engine.state.actors[RIGHT]
    assert len(target.conditions) == 2
    for _ in range(12):
        assert act(table, mid, "end")["status"] == "COMMITTED"
        engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
        left = engine.state.actors[LEFT]
        ended = (left.turns_started > applied_turn if kind.startswith("until_start")
                 else left.turns_started > applied_turn and engine.state.current_actor_id != LEFT)
        remaining = [c for c in engine.state.actors[RIGHT].conditions.values()
                     if c.condition_id == "condition:typed.smothered" or c.condition_id.startswith("condition:typed.mark.test_turn.")]
        assert len(remaining) == (0 if ended else 2)
        if ended:
            break
    else:
        pytest.fail("source deadline was never reached")
    session = combat._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("speed", [30, 25, 0])
def test_existing_stand_up_spends_half_speed_rounded_down_and_cannot_stand_at_zero_on_table(tmp_path, monkeypatch, speed):
    """Disproves AUDIT5 row 8 on the base; retain the existing standing path."""
    def knock_prone(engine):
        target = engine.state.actors[RIGHT]
        engine._add_modifier(target, HOLD, "speed_ft", "ADD", speed - engine._effective_speed(target),
                             "SELF", expires_on="UNTIL_REMOVED")
        engine._apply_condition(target, "condition:typed.prone", HOLD, LEFT, expires_on="STAND_UP")

    _, table, mid, _ = loaded_table(tmp_path, monkeypatch, knock_prone)
    for _ in range(8):
        assert act(table, mid, "end")["status"] == "COMMITTED"
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        if session.engine.state.current_actor_id == RIGHT:
            break
    else:
        pytest.fail("Prone creature never reached its turn")
    actor = session.engine.state.actors[RIGHT]
    assert session.engine._effective_speed(actor) == speed
    assert actor.movement_remaining_ft == speed - speed // 2
    assert any(c.condition_id == "condition:typed.prone" for c in actor.conditions.values()) == (speed == 0)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
