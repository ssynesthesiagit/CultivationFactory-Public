"""Independent free declarations compose on one turn; repeats remain reachable.

Synthetic sheets only. All controller choices use personal decision contexts,
with network access denied and no model/embedding server.
"""
import socket
from types import SimpleNamespace

import pytest

from combat import menu_rank
from combat.ext import foundation_combat as foundation
from combat.ext.blacksmith_second_pass import WORKPIECE
from combat.factory_compiler import compile_character
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
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
                   seed="STALEMATE1-INDEPENDENT")


def context(combat, mid):
    session = combat._load_session(mid)
    policy, _ = combat.policies.for_actor(session.engine.state.current_actor_id)
    return session, build_decision_context(session.engine, policy, for_ai=True)


def declare(combat, table, mid, name):
    settle(table, mid, candidate(combat, mid, name).candidate_id,
           choices={foundation.CHOICE + "foundation_subject": [ALLY],
                    "choice:needle.blacksmith_item": "first"})


@pytest.mark.parametrize("first", [WORK, OATH])
def test_independent_declarations_remain_available_and_turn_finishes(tmp_path, first):
    combat, table, mid = setup(tmp_path)
    # Human declaration followed by AI control is part of the original failure.
    declare(combat, table, mid, first)
    session, decision = context(combat, mid)
    second = OATH if first == WORK else WORK
    other = next(c for c in decision.legal_candidates if c.display_name == second)
    assert not other.metadata.get("ai_repeated_setting"), "unrelated setting was penalized"
    # Complete the second declaration from the controller's actual option set.
    declare(combat, table, mid, other.display_name)
    cold = CombatService(combat.source_root, combat.userdata_root)._load_session(mid).engine
    actor = cold.state.actors[OWNER]
    assert cold.state.current_actor_id == OWNER
    assert foundation.held(actor, "protected_subject").data["subject"] == ALLY
    assert any(c.condition_id == WORKPIECE for c in actor.conditions.values())
    assert actor.action_available and actor.bonus_action_available

    controller = LocalDeterministicController()
    for _ in range(40):
        session, decision = context(combat, mid)
        if decision.active_actor_id != OWNER:
            break
        choice = controller.choose_primary_action(decision)
        picked = next(c for c in decision.legal_candidates if c.candidate_id == choice.intent.candidate_id)
        assert not picked.metadata.get("ai_repeated_setting"), "AI repeated setup instead of acting"
        # Table commit + reload, with native prompts answered, not an isolated hook call.
        settle(table, mid, picked.candidate_id, choices={})
    else:
        pytest.fail("AI never completed the turn after composing independent declarations")
    assert combat._load_session(mid).engine.state.current_actor_id != OWNER


@pytest.mark.parametrize("intervening", ["action", "move"])
def test_setup_can_be_reconsidered_after_intervening_gameplay(tmp_path, intervening):
    combat, table, mid = setup(tmp_path)
    declare(combat, table, mid, WORK)
    _, decision = context(combat, mid)
    row = next(c for c in decision.legal_candidates if c.display_name == WORK)
    assert row.metadata.get("ai_repeated_setting") == 1
    if intervening == "action":
        row = candidate(combat, mid, "Dodge")
    else:
        row = next(c for c in decision.legal_candidates if c.kind == "MOVE")
    settle(table, mid, row.candidate_id, choices={})
    _, decision = context(combat, mid)
    assert decision.active_actor_id == OWNER
    row = next(c for c in decision.legal_candidates if c.display_name == WORK)
    assert not row.metadata.get("ai_repeated_setting"), "intervening gameplay did not reopen setup"
    declare(combat, table, mid, WORK)
    _, decision = context(combat, mid)
    row = next(c for c in decision.legal_candidates if c.display_name == WORK)
    assert row.metadata.get("ai_repeated_setting") == 1
