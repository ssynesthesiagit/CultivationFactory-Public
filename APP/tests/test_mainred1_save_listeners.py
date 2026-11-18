"""Forced opposed saves notify real listeners before table commit and cold replay."""
from copy import deepcopy

import pytest

from combat import ext, typed_executor as te, typed_reactions
from combat.canonical import canonical_sha256
from combat.ext.d20_rewrite import Holder, Rule, RULES
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, FOE, duel, script, sheet
from tests.test_a11_contests import HUNGER, CROWN, _act, _reload
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT

DUE = "resource:foundation.karmic_due"
GENERATE = "foundation.karma_knot_root_v0_2B.generate_karmic_due"


def _table(tmp_path, *, crown):
    bundles = []
    for aid in (LEFT, RIGHT):
        owned = [HUNGER, GENERATE] if aid == LEFT else ([CROWN] if crown else [])
        doc = sheet(owned, cl=18, primary="Resonance" if aid == RIGHT else "Qi",
                    foundation={"foundation_id": "karma_knot_root_v0_2B", "stage": "Awakened",
                                "resource": {"name": "Karmic Due",
                                             "resource_id": "foundation.resource.karma_knot_root_v0_2B",
                                             "maximum": 1, "current": 0}})
        doc["identity"]["display_name"] = "Left" if aid == LEFT else "Right"
        bundle = compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
        bundle["actor_template"]["initiative_bonus"] = 100 if aid == RIGHT else -100
        if aid == LEFT:
            attack = next(a for a in bundle["action_catalog"] if "oppose Charisma" in a["display_name"])
            bundle["action_catalog"] = [attack]
            bundle["actor_template"]["action_ids"] = [attack["source_definition_id"]]
        else:
            bundle["actor_template"]["saving_throws"]["CHA"] = -100 if crown else 100
        bundles.append(bundle)
    # Deterministic, declared setup technique: establish actual hostile damage
    # through the same table transaction/replay path, without an attack/save.
    damage = deepcopy(attack)
    damage["source_definition_id"] = "test:mainred1.establish_damage"
    damage["display_name"] = "Training: establish damage"
    damage["owner_id"] = RIGHT
    damage["economy"] = "ACTION"
    damage["parameters"]["typed"]["riders"] = []
    damage["parameters"]["typed"]["effects"] = [
        {"type": "damage", "flat": 1, "damage_types": ["force"], "applies_to": "target"}]
    bundles[1]["action_catalog"].append(damage)
    bundles[1]["actor_template"]["action_ids"].append(damage["source_definition_id"])
    for bundle in bundles:
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="MAINRED1-LISTENERS", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [LEFT, RIGHT],
                      "team_by_actor": {LEFT: "team:a", RIGHT: "team:b"},
                      "starting_positions": {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}}})
    return service, TabletopService(service, tmp_path), session.match_id


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_crown_success_does_not_generate_failure_reward_after_table_reload(tmp_path, selection):
    service, table, mid = _table(tmp_path, crown=True)
    assert _act(table, mid, "Crown Opening")["status"] == "COMMITTED"
    assert _act(table, mid, "Training: establish damage")["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    before = _reload(tmp_path, mid).state.model_dump(mode="json")
    required = _act(table, mid, "oppose Charisma")
    assert required["status"] == "REACTION_REQUIRED"
    assert required["reaction"]["context"]["reactor_id"] == RIGHT
    assert "Crown Opening" in str(required["reaction"])
    assert service._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**required["reaction"]["context"], "selection": selection}
    assert _act(table, mid, "oppose Charisma", [answer])["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    expected_due = int(selection == "DECLINE")
    assert engine.state.actors[LEFT].resources[DUE] == expected_due
    gains = [e for e in engine.events if e.source_definition_id == "passive:" + GENERATE]
    assert bool(gains) is bool(expected_due)
    contest = next(e.payload for e in engine.events if e.payload.get("roll_kind") == "opposed_check")
    assert contest["actor"]["total"] > contest["target"]["total"]
    assert contest["success"] is bool(expected_due)
    assert contest["target"]["modifier"] == -100
    assert not engine._typed_roll_outcome


def test_forced_failure_generates_failure_reward_after_table_reload(tmp_path, monkeypatch):
    _, table, mid = _table(tmp_path, crown=False)
    assert _act(table, mid, "Training: establish damage")["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    ext.effects()
    rule = Rule("test_mainred1_failure", "Training rewrite", rolls=("save",), when="any", op="choose",
                choose=lambda e, h, rc: rc.natural, outcome="failure",
                finder=lambda e: [Holder(e.state.actors[RIGHT], "test:mainred1", {}, "test:mainred1")],
                ai=lambda e, h, rc: True)
    monkeypatch.setitem(RULES, rule.kind, rule)
    required = _act(table, mid, "oppose Charisma")
    assert required["status"] == "REACTION_REQUIRED"
    assert required["reaction"]["context"]["reactor_id"] == RIGHT
    answer = {**required["reaction"]["context"], "selection": "USE"}
    assert _act(table, mid, "oppose Charisma", [answer])["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    assert engine.state.actors[LEFT].resources[DUE] == 1
    contest = next(e.payload for e in engine.events if e.payload.get("roll_kind") == "opposed_check")
    assert contest["actor"]["total"] < contest["target"]["total"]
    assert contest["success"] and contest["outcome_override"]
    assert contest["target"]["modifier"] == 100
    assert not engine._typed_roll_outcome


@pytest.mark.parametrize("outcome", ["success", "failure"])
@pytest.mark.parametrize("late_override", [False, True])
def test_both_sides_hear_staged_outcome_and_later_save_reactions_still_settle(monkeypatch, outcome, late_override):
    engine = duel(HUNGER)
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    ext.effects()
    rule = Rule("test_mainred1_listeners", "Training rewrite", rolls=("save",), when="any", op="choose",
                choose=lambda e, h, rc: rc.natural, outcome=outcome,
                finder=lambda e: [Holder(target, "test:mainred1", {}, "test:mainred1")],
                ai=lambda e, h, rc: True)
    monkeypatch.setitem(RULES, rule.kind, rule)
    seen = []
    def after_d20(e, subject, kind, **kwargs):
        seen.append((subject.entity_id, kind, kwargs["success"]))
    monkeypatch.setattr(typed_reactions, "after_d20", after_d20)
    creature_events = []
    monkeypatch.setattr(typed_reactions, "on_creature_event",
                        lambda e, subject, kind: creature_events.append((subject.entity_id, kind)))
    save_seen = []
    def after_save(ctx, subject, choice, named, failed):
        save_seen.append(failed)
        if late_override:
            ctx.engine._typed_roll_outcome[subject.entity_id] = "failure" if outcome == "success" else "success"
    monkeypatch.setitem(ext._HOOKS, "after_save", [after_save])
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    ctx = te.Context(engine, actor, action, None, action.parameters["typed"], [target], target)
    script(engine, [20, 1] if outcome == "success" else [1, 20])
    result = te.resolve_opposed_check(ctx, target, {"kind": "cultivation"}, {"kind": "save", "ability": "CHA"})
    failed = outcome == "failure"
    assert seen == [(ME, "check", failed), (FOE, "save", not failed)]
    assert save_seen == [failed]
    assert creature_events == [(FOE, "creature_save_failed" if failed else "creature_save_succeeded")]
    assert result.success is (not failed if late_override else failed)
    assert not engine._typed_roll_outcome
