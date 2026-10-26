"""STALEMATE1F9: accepting one free setting must not clear the history of another.

ai_restraint.reset_setting_history reopens setup after gameplay (any non-setting INTENT_ACCEPTED). A free setting_only
declaration is not gameplay, so declaring one setting must keep the history of the others. Otherwise the built-in AI
could alternate A, B, A, B and never end its turn. The sequence A -> B -> A asserts that A is still flagged as repeated
after B was accepted. The regression goes through the table (commit and reload), not a single hook call.

Synthetic sheets only; network access is denied and no model or embedding server is used.
"""
import socket
from types import SimpleNamespace

import pytest

from combat import menu_rank
from combat.ext import foundation_combat as foundation
from combat.ext.blacksmith_second_pass import WORKPIECE
from combat.factory_compiler import compile_character
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from tests.h1_support import sheet
from tests.worker2_support import fixture, settle, candidate, OWNER, ALLY

TALENTS = ["tianxia.talent.blacksmith.quench_against_the_grain",
           "tianxia.talent.blacksmith.steady_hammer_breathing"]
WORK = "Set current workpiece: a carried item"
OATH = "Declare Protected Subject"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(menu_rank, "_CLIENT", SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **kw: None))

    def denied(*a, **kw):
        raise AssertionError("No live socket or model in setting regressions")
    monkeypatch.setattr(socket.socket, "connect", denied)


def setup(tmp_path):
    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.jian", "quantity": 1}]}}
    document = sheet(TALENTS, cl=15, kit=kit)
    document["foundation"] = {
        "foundation_id": "iron_oath_skin_v0_2B", "stage": "Awakened",
        "resource": {"name": "Guarding Iron", "resource_id": "fixture:guarding_iron",
                     "maximum": 1, "current": 0}}
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={"ask": False})
    return fixture(tmp_path, TALENTS, owner_bundle=bundle, owner_kit=kit, ask=False,
                   seed="STALEMATE1F9-SEQUENCE")


def declare(combat, table, mid, name):
    settle(table, mid, candidate(combat, mid, name).candidate_id,
           choices={foundation.CHOICE + "foundation_subject": [ALLY],
                    "choice:needle.blacksmith_item": "first"})


def _repeated(combat, mid, name):
    session = combat._load_session(mid)
    actor_id = session.engine.state.current_actor_id
    policy, _ = combat.policies.for_actor(actor_id)
    decision = build_decision_context(session.engine, policy, for_ai=True)
    rows = [c for c in decision.legal_candidates if c.display_name == name]
    assert actor_id == OWNER and rows, (
        f"{name!r} not offered to the owner: actor={actor_id} rows={[c.display_name for c in decision.legal_candidates]}")
    return rows[0].metadata.get("ai_repeated_setting")


def test_declaring_another_setting_keeps_the_first_declarations_history(tmp_path):
    combat, table, mid = setup(tmp_path)
    declare(combat, table, mid, WORK)
    declare(combat, table, mid, OATH)
    # A -> B: accepting B did not clear A's history (the workpiece is still offered and flagged as repeated).
    assert _repeated(combat, mid, WORK) == 1, "declaring Declare Protected Subject cleared the workpiece history"
    # A -> B -> A: repeating A is still recognised as a repeat, and both history keys survive.
    declare(combat, table, mid, WORK)
    assert _repeated(combat, mid, WORK) == 1
    cold = CombatService(combat.source_root, combat.userdata_root)._load_session(mid).engine
    flags = {k for k in cold.state.actors[OWNER].turn_flags if k.startswith("ai_restraint_setting:")}
    assert len(flags) == 2, f"both declarations should be remembered after reload: {flags}"
    assert any(c.condition_id == WORKPIECE for c in cold.state.actors[OWNER].conditions.values())
