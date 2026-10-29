"""Qualify Beast Tamer's harm ending for native child-event damage.

The test-only event producer supplies a damage packet inside a table action;
the real Beast Tamer action, native damage path and recorded removals run normally.
"""
import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.ext.beastmastery_riders import PREFIX
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture, force_ai_candidate

TAMER = "TAL_BEASTMASTERY_BEAST_TAMER"


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("case", ["hp", "caster", "temporary_hp", "zero", "enemy", "successful_save"])
def test_nested_harm_ends_only_owned_control_commit_reload_replay(monkeypatch, tmp_path, ai, case):
    ext.effects()

    def damage_inside_event(engine, kind, kwargs):
        if kind == "HOLD_POSITION_COMMITTED" and kwargs.get("actor_id") == OWNER:
            engine._commit_damage(engine.state.actors[FOE], 0 if case == "zero" else 3,
                                  "NECROTIC", "test:nested-harm", OWNER if case == "caster" else SECOND,
                                  getattr(engine, "_active_intent", None), reaction_depth=0)

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS["event"], damage_inside_event])

    def unrelated_state(bundles):
        owner = next(b for b in bundles if b["actor_id"] == OWNER)
        action = next(a for a in owner["action_catalog"] if a["display_name"] == "Beast Tamer")
        # Native effects persist unrelated state before the real save branch.
        action["parameters"]["typed"]["effects"][:0] = [
            {"type": "condition", "condition": "poisoned", "applies_to": "target", "expires_on": "UNTIL_REMOVED"},
            *([{"type": "temp_hp", "flat": 20, "applies_to": "target"}] if case == "temporary_hp" else [])]
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, send, commit = fixture(
        tmp_path, [TAMER], owner_dc=-40 if case == "successful_save" else 50,
        allies=() if case == "enemy" else (SECOND,), bundle_transform=unrelated_state)
    commit(candidate(table, mid, "Beast Tamer", FOE))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    before = CombatService(ROOT, tmp_path)._load_session(mid)
    subject = before.engine.state.actors[FOE]
    ledger = [c for c in subject.conditions.values() if c.condition_id.startswith(PREFIX)]
    assert len(ledger) == int(case != "successful_save")
    owned = set(ledger[0].data["conditions"]) | {ledger[0].instance_id} if ledger else set()
    unrelated = {c.instance_id for c in subject.conditions.values() if c.condition_id == "condition:typed.poisoned"}
    assert unrelated
    hp, temp, sequence = subject.current_hp, subject.temporary_hp, before.engine.state.event_sequence
    if case == "temporary_hp":
        assert temp == 20
    cid = next(c.candidate_id for c in before.engine.legal_candidates()
               if c.source_definition_id == "system:combat.hold_position")
    if ai:
        force_ai_candidate(combat, mid, OWNER, cid)
        assert send(cid, auto=True)["status"] == "COMMITTED"
    else:
        commit(cid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    subject = loaded.engine.state.actors[FOE]
    ends = case in {"hp", "caster", "temporary_hp"}
    if ends:
        assert not (owned & set(subject.conditions))
    else:
        assert owned <= set(subject.conditions)
    assert unrelated <= set(subject.conditions)
    assert subject.current_hp == hp - (3 if case not in {"zero", "temporary_hp"} else 0)
    assert subject.temporary_hp == temp - (3 if case == "temporary_hp" else 0)
    events = [e for e in loaded.engine.events if e.sequence > sequence]
    damage, = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    assert damage.actor_id == (OWNER if case == "caster" else SECOND) and damage.target_ids == (FOE,)
    removals = [e for e in events if e.event_type == "CONDITION_REMOVED" and e.payload.get("reason") == "ALLIED_DAMAGE"]
    assert {e.payload["instance_id"] for e in removals} == (owned if ends else set())
    assert len(removals) == (len(owned) if ends else 0)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
