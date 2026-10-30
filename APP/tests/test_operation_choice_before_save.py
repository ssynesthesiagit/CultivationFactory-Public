"""Synthetic operation contract at the real table; no private ability dependency.

Empty Palm's unmerged plug-in is not available on this base. These test-only
providers exercise its required choice/save/outcome shape without claiming to
test Hollow the Weapon's item model.
"""
import copy

import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionDefinition
from combat.gate5_service import CombatService
from combat.ext.needle import ask, checkpoint_id, say
from tests.h1_support import ROOT
from tests.r1i_service_support import OWNER, FOE, candidate, fixture, force_ai_candidate

SOURCE = "test:operation_before_save"
OPERATION = "test_pre_save_operation"
CHOICE = "choice:needle.test_pre_save_operation"


@pytest.mark.parametrize("chooser_role,save_fails,automatic", [
    ("actor", True, False),
    ("actor", False, True),
    ("target", True, False),
    ("target", False, False),
])
def test_operation_choice_precedes_save_and_binds_outcome_after_cold_reload(
        tmp_path, monkeypatch, chooser_role, save_fails, automatic):
    ext.effects()
    marker = {"key": "item", "chooser": chooser_role}
    operation = {"type": OPERATION, "applies_to": "target", "pre_save_choice": marker}
    save = {"type": "save", "applies_to": "target", "ability": "cha",
            "on_fail": [{**operation, "outcome": "failure"}],
            "on_success": [{**operation, "outcome": "success"}]}
    original = copy.deepcopy(save)
    chooser_id = OWNER if chooser_role == "actor" else FOE

    def choose_operation(ctx, row, chooser):
        if row.get("type") != OPERATION:
            return None
        assert chooser.entity_id == chooser_id
        assert ctx.target.entity_id == FOE and ctx.failed_save is None
        # A save reaction must not get to roll/rewrite the outcome first.
        assert not any(e.event_type == "SAVE_ROLLED" and e.source_definition_id == SOURCE
                       for e in ctx.engine.events)
        picked = ask(ctx.engine, ctx.intent,
                     checkpoint_id(ctx.engine, OPERATION, FOE), chooser, CHOICE,
                     ["first", "second"], labels={"first": "First item", "second": "Second item"},
                     preferred=["second"], target_id=FOE, name="Test operation",
                     prompt="Test operation: choose one item carried by Foe before its Charisma save; no extra cost.")
        say(ctx.engine, SOURCE, chooser, "Item selected before saving.", (FOE,))
        return picked

    def apply_operation(ctx, row):
        assert row["selected_options"] == ["second"]
        ctx.engine._apply_condition(
            ctx.target, "condition:typed.test_operation_selection", SOURCE, ctx.actor.entity_id,
            expires_on="START_OF_SOURCE_NEXT_TURN",
            data={"item": row["selected_options"][0], "outcome": row["outcome"]})

    monkeypatch.setitem(ext._HOOKS, "operation_choice", [choose_operation])
    monkeypatch.setitem(ext.effects(), OPERATION, apply_operation)
    monkeypatch.setitem(ext._EFFECT_HARM, OPERATION, True)

    def add_action(bundles):
        owner = next(b for b in bundles if b["actor_id"] == OWNER)
        action = ActionDefinition(
            source_definition_id=SOURCE, display_name="Test operation", owner_id=OWNER,
            economy="ACTION", resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=30,
            parameters={"typed": {"effects": [save], "manual_inline_choice": True,
                                  "numbers": {"save_dc": 100 if save_fails else -100}}})
        owner["action_catalog"].append(action.model_dump(mode="json"))
        owner["actor_template"]["action_ids"].append(SOURCE)
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, send, _ = fixture(tmp_path, [], bundle_transform=add_action)
    if automatic:
        combat.set_controller_mode(mid, actor_id=chooser_id, controller_mode="LOCAL_AUTO")
    cid = candidate(table, mid, "Test operation", FOE)
    if automatic:
        force_ai_candidate(combat, mid, chooser_id, cid)
    result = send(cid, auto=automatic)
    if not automatic:
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        assert prompt["context"]["reactor_id"] == chooser_id
        assert prompt["context"]["reaction_source_id"] == CHOICE
        assert {o["id"] for o in prompt["choice"]["options"]} == {"first", "second"}
        result = send(cid, [{**prompt["context"], "selection": "USE", "option_ids": ["second"]}])
    assert result["status"] == "COMMITTED", result

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    selected, = [c for c in loaded.engine.state.actors[FOE].conditions.values()
                 if c.condition_id == "condition:typed.test_operation_selection"]
    assert selected.data == {"item": "second", "outcome": "failure" if save_fails else "success"}
    saves = [e for e in loaded.engine.events if e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == SOURCE]
    notes = [e for e in loaded.engine.events if e.event_type == "PASSIVE_TRIGGERED"
             and e.source_definition_id == SOURCE]
    assert len(saves) == len(notes) == 1
    assert notes[0].sequence < saves[0].sequence
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    assert save == original
    stored = loaded.engine.action_catalog[SOURCE].parameters["typed"]["effects"][0]
    assert stored == original  # transient answers never rewrite sealed authority/action rows
