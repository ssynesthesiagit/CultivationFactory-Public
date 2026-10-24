"""Outcome and area-boundary regressions for the F12 Yang review."""
import pytest
from combat.canonical import canonical_sha256
from combat.ext.yang_sun_marks import DAWN, NOON, DIM_LIGHT, EXCEPTION
from combat.ext.yang_recovery import ROUND
from combat.typed_executor import bears_mark
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_mgr_t15_yang_occurrences import benefit_setup
from tests.test_mgr_t15_yang_marks import _cast_noon, _move_candidate


@pytest.mark.parametrize("accept", [True, False])
def test_dawn_exception_aim_changes_confirmed_attack_not_damage(tmp_path, monkeypatch, accept):
    from combat import attack_notifications
    original = attack_notifications.capture
    observed = []
    def capture(engine, actor, target, context, intent):
        if actor.entity_id == ALLY:
            changes = [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED"
                       and e.payload.get("roll_id") == context.roll_id]
            if changes:
                assert context.total == changes[-1].payload["total"]
                observed.append(context.total)
        return original(engine, actor, target, context, intent)
    monkeypatch.setattr(attack_notifications, "capture", capture)
    combat, table, mid = fixture(tmp_path, [DAWN], named=True,
                                bundle_transform=benefit_setup(DAWN),
                                positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 6}})
    settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, "Review strike", target=FOE).candidate_id,
           picks={"choice:needle.yang_aim_attack": None,
                  "choice:needle.completion_force": "aim" if accept else None})
    engine = reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == "CHECK_ROLLED"
             and e.payload.get("purpose") == "Complete Aim bonus"]
    changes = [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED"
               and e.payload.get("hook") == "confirmed_attack_roll_bonus"]
    assert bool(rolls) is accept
    assert bool(changes) is accept
    assert bool(observed) is accept
    if accept:
        change = changes[0].payload
        assert change["total"] == change["previous_total"] + rolls[0].payload["total"]
        assert change["bonus"] > 0
    assert engine.state.actors[OWNER].turn_flags.get(ROUND) != engine.state.round_number
    assert not any(c.condition_id == EXCEPTION for c in engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize("native", [True, False])
def test_dawn_exception_aim_subtracts_from_effective_failed_save(tmp_path, monkeypatch, native):
    from combat import ext
    original = ext.run_strict
    observed = []
    def observe(name, *args, **kwargs):
        if name == "save_final" and args[0].source == "action:test.f12_save":
            ctx = args[0]
            changes = [e for e in ctx.engine.events if e.event_type == "PASSIVE_TRIGGERED"
                       and e.payload.get("roll_id") == ctx.save_result.roll_id]
            # Legal-option probes can settle this save without accepting a response.
            # Only the committed response's linked adjustment is an Aim outcome.
            if changes:
                assert ctx.save_result.total == changes[-1].payload["total"]
                observed.append(ctx.save_result.total)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(ext, "run_strict", observe)
    from combat.gate2_runtime_models import ActionDefinition, DiceSpec, SaveDefinition

    source = "action:test.f12_save"
    def prepare(bundles):
        benefit_setup(DAWN)(bundles)
        bundle = bundles[1]
        action = ActionDefinition(
            source_definition_id=source, display_name="F12 save", owner_id=ALLY,
            economy="ACTION", resolution_kind="SAVE_DAMAGE" if native else "TYPED",
            target_kind="HOSTILE_ENTITY", range_ft=60, damage=DiceSpec(count=1, sides=2),
            damage_type="FORCE", save=SaveDefinition(ability="WIS", dc=100),
            parameters={} if native else {"typed": {"numbers": {"save_dc": 100},
                "effects": [{"type": "save", "ability": "WIS", "applies_to": "target",
                             "on_fail": [], "on_success": []}]}})
        bundle["action_catalog"].append(action.model_dump(mode="json"))
        bundle["actor_template"]["action_ids"].append(source)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat, table, mid = fixture(tmp_path, [DAWN], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, "F12 save", target=FOE).candidate_id,
           picks={"choice:needle.yang_aim_save": None, "choice:needle.completion_force": "aim"})
    engine = reload(tmp_path, mid)
    aim = next(e for e in engine.events if e.event_type == "CHECK_ROLLED"
               and e.payload.get("purpose") == "Complete Aim bonus")
    change = next(e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED"
                  and e.payload.get("hook") == "settled_save_roll_bonus")
    save = next(e for e in engine.events if e.event_type == "SAVE_ROLLED"
                and e.source_definition_id == source)
    assert change.payload["bonus"] == -aim.payload["total"]
    assert change.payload["total"] == change.payload["previous_total"] - aim.payload["total"]
    assert save.payload["roll_id"] == change.payload["roll_id"]
    if native:
        assert save.payload["total"] == change.payload["total"]
    else:
        assert observed
        assert save.payload["total"] == change.payload["previous_total"]
    assert not save.payload["success"]
    assert not bears_mark(engine.state.actors[ALLY], OWNER, "Kindled Mark")
    assert engine.state.actors[OWNER].turn_flags.get(ROUND) != engine.state.round_number


def test_settled_save_bonus_outcome_follows_its_effective_total(tmp_path, monkeypatch):
    """A settled-save adjustment moves the result with the roll it changed.

    Life Refuses Closure only subtracts from a save that already failed, so its own
    outcome cannot flip. The shared seam must still keep the effective total and the
    reported success/failure one result for any provider, forced outcomes aside.
    """
    from combat import ext
    from combat.gate2_runtime_models import ActionDefinition, DiceSpec, SaveDefinition

    source = "action:test.f12_save"
    seen = {}

    def crossing(engine, subject, ability, dc, roll, source_id, intent, failed, bearer):
        return dc - roll.total + 1 if failed else None

    original = ext.run_strict

    def observe(name, *args, **kwargs):
        if name == "save_final" and args[0].source == source:
            seen["failed"] = args[4]
            seen["total"] = args[0].save_result.total
            seen["dc"] = args[0].save_dc
        return original(name, *args, **kwargs)

    monkeypatch.setitem(ext._HOOKS, "settled_save_roll_bonus", [crossing])
    monkeypatch.setattr(ext, "run_strict", observe)

    def prepare(bundles):
        benefit_setup(DAWN)(bundles)
        bundle = bundles[1]
        bundle["action_catalog"].append(ActionDefinition(
            source_definition_id=source, display_name="F12 save", owner_id=ALLY,
            economy="ACTION", resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
            range_ft=60, damage=DiceSpec(count=1, sides=2), damage_type="FORCE",
            save=SaveDefinition(ability="WIS", dc=100),
            parameters={"typed": {"numbers": {"save_dc": 100}, "effects": [
                {"type": "save", "ability": "WIS", "applies_to": "target",
                 "on_fail": [], "on_success": []}]}}).model_dump(mode="json"))
        bundle["actor_template"]["action_ids"].append(source)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid = fixture(tmp_path, [DAWN], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, "F12 save", target=FOE).candidate_id)
    assert seen["dc"] == 100
    assert seen["total"] >= seen["dc"]
    assert seen["failed"] is False


@pytest.mark.parametrize("start,steps", [
    (7, [5, 4, 3, 2, 3, 4]),  # enter after walking outside; split inside steps
    (4, [5, 6, 5, 4, 3, 2, 3, 4]),  # leave and re-enter
])
def test_noon_counts_only_segments_in_its_own_area_after_reload(tmp_path, start, steps):
    def prepare(bundles):
        bundle = bundles[0]
        # A small synthetic area makes boundary crossings possible on the public arena.
        def shrink(value):
            if isinstance(value, dict):
                if value.get("shape") == "sphere" and "size_ft" in value:
                    value["size_ft"] = 5
                for child in value.values():
                    shrink(child)
            elif isinstance(value, list):
                for child in value:
                    shrink(child)
        shrink(bundle["action_catalog"])
        bundles[1]["actor_template"]["speed_ft"] = 90
        bundles[1]["carrying"]["speed_ft"] = 90
        for b in bundles:
            b.pop("bundle_sha256", None)
            b["bundle_sha256"] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [NOON], bundle_transform=prepare,
        positions={OWNER: {"x": 3, "y": 5}, ALLY: {"x": start, "y": 6}, FOE: {"x": 9, "y": 9}})
    _cast_noon(table, combat, mid, (3, 6))
    turn(table, mid, ALLY)
    for index, x in enumerate(steps):
        settle(table, mid, _move_candidate(combat, mid, (x, 6)).candidate_id)
        engine = reload(tmp_path, mid)
        lit = any(c.condition_id == DIM_LIGHT for c in engine.state.actors[ALLY].conditions.values())
        assert lit is (index == len(steps) - 1)
