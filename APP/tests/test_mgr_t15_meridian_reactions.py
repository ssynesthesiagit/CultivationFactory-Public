"""Reaction suppression bookkeeping through committed tables and cold replay.

Controlled long-lived composite/overlap producers isolate the shared suppression
contract. Native disease and Meridian saves remain covered by the companion
test_mgr_t15_meridian_regulation module; no successful treatment roll is injected.
Reaction expenditure here is a real opportunity attack, not a flipped state bit.
"""
import copy

import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.ext import benefit_suppression
from combat.gate2_engine import SYSTEM_OPPORTUNITY
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.r1i_service_support import ROOT, OWNER, FOE, SECOND, fixture
from tests.test_mgr_t15_meridian_regulation import act

PARENT = "condition:typed.meridian_reaction_test"
OTHER = "condition:typed.reaction_denied"
PREFIX = "action:test.meridian_reactions."


def _control(ctx, effect):
    holder = ctx.target
    if effect["operation"] == "parent":
        ctx.engine._apply_condition(holder, PARENT, ctx.source, ctx.actor.entity_id,
            expires_on="UNTIL_REMOVED", data={"label": "Physical impairment",
                "rule": {"no_reactions": True}, "untouched": 7})
        holder.reaction_available = False  # Native composite affliction producer contract.
    elif effect["operation"] == "suppress":
        parent = next(c for c in holder.conditions.values() if c.condition_id == PARENT)
        if effect["kind"] == "component":
            assert benefit_suppression.suppress_component(ctx.engine, ctx.actor, holder,
                parent.instance_id, "rule.no_reactions", "holder_turn_end", ctx.source)
        else:
            assert benefit_suppression.suppress(ctx.engine, ctx.actor, holder,
                "condition:" + parent.instance_id, "holder_turn_end", ctx.source)


def _setup(bundles, kind):
    for bundle in bundles:
        template = next(a for a in bundle["action_catalog"] if a["resolution_kind"] == "TYPED")
        effects = {
            "parent": [{"type": "meridian_reaction_control", "operation": "parent"}],
            "suppress": [{"type": "meridian_reaction_control", "operation": "suppress", "kind": kind}],
            "other": [{"type": "condition", "condition": "reaction_denied", "expires_on": "UNTIL_REMOVED"}],
            "end-parent": [{"type": "remove_condition", "condition": PARENT}],
            "end-other": [{"type": "remove_condition", "condition": OTHER}],
        }
        for operation, rows in effects.items():
            source = PREFIX + bundle["actor_id"].removeprefix("actor:factory.") + "." + operation
            action = copy.deepcopy(template)
            action.update(source_definition_id=source, display_name="Test " + operation,
                economy="NONE", costs=[], target_kind="HOSTILE_ENTITY_OR_SELF", range_ft=60)
            action["parameters"] = {"free_primary": True, "typed": {"source": source,
                "numbers": {}, "effects": [{**row, "applies_to": "target"} for row in rows]}}
            bundle["action_catalog"].append(action)
            bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def _table(tmp_path, monkeypatch, kind="component"):
    ext.effects()
    monkeypatch.setitem(ext._EFFECTS, "meridian_reaction_control", _control)
    combat, table, mid, _, _ = fixture(tmp_path, [], seed="MERIDIAN-REACTION-BOOKKEEPING",
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 15, "y": 10}},
        bundle_transform=lambda bundles: _setup(bundles, kind))
    return combat, table, mid


def _cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def _do(tmp_path, table, mid, operation):
    engine = _cold(tmp_path, mid)
    candidate = next(c for c in engine.legal_candidates()
        if c.source_definition_id.startswith(PREFIX) and c.source_definition_id.endswith("." + operation)
        and c.target_ids == (FOE,))
    act(table, mid, candidate.candidate_id)
    return _cold(tmp_path, mid).state.actors[FOE]


def _until(tmp_path, table, mid, actor):
    for _ in range(5):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return
        act(table, mid, table.state(mid)["menu"]["end_turn"])
        _cold(tmp_path, mid)
    raise AssertionError("missing turn")


def test_spent_unlocked_reaction_is_not_refunded_when_parent_ends(tmp_path, monkeypatch):
    _, table, mid = _table(tmp_path, monkeypatch)
    assert not _do(tmp_path, table, mid, "parent").reaction_available
    patient = _do(tmp_path, table, mid, "suppress")
    assert patient.reaction_available
    engine = _cold(tmp_path, mid)
    move = next(c for c in engine.legal_candidates()
        if c.kind.value == "MOVE" and c.destination == Position(x=2, y=6))
    # All seats are deterministic/manual; accept only the real native OA.
    menu = table.state(mid)["menu"]
    answers = []
    for _ in range(12):
        reply = table.act(mid, move.candidate_id, menu["decision_id"], menu["state_version"], 0, answers)
        if reply["status"] == "COMMITTED":
            break
        assert reply["status"] == "REACTION_REQUIRED", reply
        prompt = reply["reaction"]
        answers.append({**prompt["context"], "selection":
            "USE" if prompt["context"]["reaction_source_id"] == SYSTEM_OPPORTUNITY else "DECLINE"})
    else:
        raise AssertionError("unresolved opportunity attack")
    engine = _cold(tmp_path, mid)
    assert any(e.event_type == "REACTION_RESOLVED" and e.actor_id == FOE
               and e.source_definition_id == SYSTEM_OPPORTUNITY for e in engine.events)
    assert not engine.state.actors[FOE].reaction_available
    patient = _do(tmp_path, table, mid, "end-parent")
    assert not any(c.condition_id == PARENT for c in patient.conditions.values())
    assert not patient.reaction_available, "ending the suppressed parent refunded a spent Reaction"


@pytest.mark.parametrize("kind", ["component", "condition"])
@pytest.mark.parametrize("first", ["end-parent", "end-other"])
def test_restored_denial_inherits_unspent_reaction_in_both_removal_orders(tmp_path, monkeypatch, kind, first):
    _, table, mid = _table(tmp_path, monkeypatch, kind)
    _do(tmp_path, table, mid, "parent")
    assert _do(tmp_path, table, mid, "suppress").reaction_available
    _until(tmp_path, table, mid, FOE)
    # Apply the overlapping denial after the holder's refresh, before suppression
    # ends. This leaves availability false while the other denial owns the bit.
    assert not _do(tmp_path, table, mid, "other").reaction_available
    act(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = _cold(tmp_path, mid)
    patient = engine.state.actors[FOE]
    assert not any(c.condition_id == benefit_suppression.SUPPRESSED for c in patient.conditions.values())
    parent = next(c for c in patient.conditions.values() if c.condition_id == PARENT)
    assert parent.data["untouched"] == 7 and parent.data["rule"]["no_reactions"]
    assert parent.data["reaction_suppression_restore"], "restoration lost the inherited unspent Reaction"
    assert not patient.reaction_available
    # No second holder turn/Reaction refresh between the two removals.
    _until(tmp_path, table, mid, OWNER)
    assert not _do(tmp_path, table, mid, first).reaction_available
    second = "end-other" if first == "end-parent" else "end-parent"
    assert _do(tmp_path, table, mid, second).reaction_available


def test_parent_ending_during_overlap_does_not_release_other_denial(tmp_path, monkeypatch):
    _, table, mid = _table(tmp_path, monkeypatch)
    _do(tmp_path, table, mid, "parent")
    _do(tmp_path, table, mid, "other")
    assert not _do(tmp_path, table, mid, "suppress").reaction_available
    assert not _do(tmp_path, table, mid, "end-parent").reaction_available
    assert _do(tmp_path, table, mid, "end-other").reaction_available
