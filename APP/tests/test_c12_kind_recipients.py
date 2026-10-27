"""Shared kind exclusions in real table transactions, including mixed recipients.

Multi-target shapes below are test-only compiled rows, not new printed Mend rules.
"""
import copy
from types import SimpleNamespace

import pytest

from combat.canonical import canonical_sha256
from combat.ext import creature_kinds
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_r1i_round3 import reload

MEND = "LIFE_BASE_MEND_THE_PULSE"
ESOTERIC = "tianxia.talent.life.esoteric_vitality"


def prepare_rows(kind, *, allies=False, gated=True):
    def prepare(bundles):
        owner, foe, second = bundles
        foe["actor_template"]["creature_types"] = [kind] if kind else []
        action = next(a for a in owner["action_catalog"] if a["display_name"] == "Mend the Pulse")
        heal = copy.deepcopy(action["parameters"]["typed"]["effects"][0])
        gate = heal["unless_kind"]
        action["target_kind"] = "SELF"
        typed = action["parameters"]["typed"]
        typed["range"] = {"kind": "self"}
        typed["riders"] = []
        if allies:
            # Real ally resolution must filter the returned list, not ctx.targets
            # (which contains no allies for this self-targeted action).
            heal.update(type="temp_hp", applies_to="ally", flat=20,
                        dice={"count": 0, "sides": 0}, dice_by_cl=[], formula="none",
                        evidence="All allies within 30 feet gain 20 temporary Hit Points.")
            typed["effects"] = [heal]
        else:
            # Make wounds through the transaction itself, then heal the area.
            typed["area"] = {"shape": "sphere", "size_ft": 30, "centered_on_self": True}
            heal.update(flat=20, dice={"count": 0, "sides": 0}, dice_by_cl=[], formula="none")
            typed["effects"] = [
                {"type": "damage", "applies_to": "target", "flat": 50,
                 "dice": {"count": 0, "sides": 0}, "damage_types": ["force"]}, heal]
        if not gated:
            heal.pop("unless_kind")
        for bundle in bundles:
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    return prepare


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("kind,exception,gated", [
    ("Undead", False, True), ("Construct", False, True),
    ("Undead", True, True), (None, False, True), ("Undead", False, False),
])
def test_mixed_healing_table_commit_reload(tmp_path, auto, kind, exception, gated):
    combat, table, mid, send, commit = fixture(
        tmp_path, [MEND, ESOTERIC] if exception else [MEND],
        bundle_transform=prepare_rows(kind, gated=gated))
    before = reload(tmp_path, mid)
    cid = candidate(table, mid, "Mend the Pulse")
    if auto:
        force_ai_candidate(combat, mid, OWNER, cid)
    assert send(cid, auto=auto)["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    allowed = not kind or exception or not gated
    assert after.state.actors[FOE].current_hp == before.state.actors[FOE].current_hp - 50 + (20 if allowed else 0)
    assert after.state.actors[SECOND].current_hp == before.state.actors[SECOND].current_hp - 30
    healing = [e for e in after.events[len(before.events):] if e.event_type == "HEALING_APPLIED"]
    # Owner 2026-10-01: friendly fire applies unless the rule says enemies.
    # This synthetic area affects creatures without an enemy-only restriction.
    assert after.state.actors[OWNER].current_hp == before.state.actors[OWNER].current_hp - 30
    assert {t for e in healing for t in e.target_ids} == ({OWNER, FOE, SECOND} if allowed else {OWNER, SECOND})
    assert not after.state.actors[OWNER].action_available


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("exception", [False, True])
def test_mixed_allies_resolved_outside_context_targets(tmp_path, auto, exception):
    combat, table, mid, send, commit = fixture(
        tmp_path, [MEND, ESOTERIC] if exception else [MEND], allies=[FOE, SECOND],
        bundle_transform=prepare_rows("Undead", allies=True))
    cid = candidate(table, mid, "Mend the Pulse")
    if auto:
        force_ai_candidate(combat, mid, OWNER, cid)
    assert send(cid, auto=auto)["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].temporary_hp == (20 if exception else 0)
    assert after.state.actors[SECOND].temporary_hp == 20
    assert after.state.actors[OWNER].temporary_hp == 0


def test_candidate_filter_retains_mixed_and_rejects_all_excluded(tmp_path):
    combat, table, mid, send, commit = fixture(
        tmp_path, [MEND], bundle_transform=prepare_rows("Undead"))
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Mend the Pulse")
    # Test the pure-healing candidate contract; the wound prelude is test setup.
    params = copy.deepcopy(action.parameters)
    params["typed"]["effects"] = params["typed"]["effects"][1:]
    action = SimpleNamespace(parameters=params)
    assert creature_kinds.kind_candidate_allowed(engine, actor, SimpleNamespace(target_ids=[FOE]), action) is False
    assert creature_kinds.kind_candidate_allowed(engine, actor, SimpleNamespace(target_ids=[FOE, SECOND]), action) is None


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("recipient", ["self", "ally"])
def test_excluded_context_target_does_not_veto_other_recipients(tmp_path, auto, recipient):
    def prepare(bundles):
        prepare_rows("Undead", allies=True)(bundles)
        owner = bundles[0]
        action = next(a for a in owner["action_catalog"] if a["display_name"] == "Mend the Pulse")
        typed = action["parameters"]["typed"]
        typed["area"] = {"shape": "sphere", "size_ft": 30, "centered_on_self": True}
        typed["effects"][0]["applies_to"] = recipient
        owner.pop("bundle_sha256")
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, send, commit = fixture(
        tmp_path, [MEND], allies=[SECOND], bundle_transform=prepare)
    # Only the undead foe is in the hostile area target list; the recipient
    # declaration instead grants the benefit to the living caster or ally.
    cid = candidate(table, mid, "Mend the Pulse")
    if auto:
        force_ai_candidate(combat, mid, OWNER, cid)
    assert send(cid, auto=auto)["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].temporary_hp == 0
    assert after.state.actors[OWNER].temporary_hp == (20 if recipient == "self" else 0)
    assert after.state.actors[SECOND].temporary_hp == (20 if recipient == "ally" else 0)
