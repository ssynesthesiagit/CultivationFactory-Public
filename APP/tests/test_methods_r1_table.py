"""Table transactions exercise the shared reaction admission/payment seam.

Test-only actions provide repeatable triggers, including restored and free
Reactions, without replacing engine methods or production abilities.
"""
import copy

import pytest

from combat import ext, typed_reactions as reactions
from combat.canonical import canonical_sha256
from combat.gate4_adapters import ManualControllerAdapter
from tests.r1i_service_support import OWNER, FOE, fixture, candidate
from tests.test_r1i_round3 import reload
from tests.test_riders_c15 import _commit_all

SWAY = "TAL_DRUNKEN_STYLE_SWAYING_GUARD"
FOCUS = "resource:core.martial_focus"


def auto_probe(combat, mid, actor):
    real = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda c: (next(
                a.candidate_id for a in c.legal_candidates if a.display_name.startswith("Guard probe")), ())).choose_primary_action(context)
        def __getattr__(self, key):
            return getattr(real, key)
    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")


def setup(tmp_path, monkeypatch, *, legacy_grant=False):
    def probe(ctx, effect):
        owner = ctx.engine.state.actors[OWNER]
        row = next(r for r in ctx.engine.typed_reaction_rows[OWNER]
                   if r.get("feature_id") == SWAY and r.get("block") == "generic")
        if effect.get("restore"):
            owner.reaction_available = True
        if reactions._can_trigger(ctx.engine, owner, row) and reactions._consent(
                ctx.engine, row, owner, "METHODS_PROBE", trigger={
                    "actor_id": ctx.actor.entity_id, "target_id": OWNER,
                    "action_name": "Guard probe", "source_id": ctx.action.source_definition_id}):
            reactions._open(ctx.engine, row, owner, (OWNER,), "METHODS_PROBE")
            reactions.spend_reaction(ctx.engine, owner, row)

    monkeypatch.setitem(ext._EFFECTS, "test_methods_probe", probe)

    def prepare(bundles):
        for bundle in bundles:
            if legacy_grant and bundle["actor_id"] == OWNER:
                # db601566's compiled Focus grant, as retained by old saves.
                grant = next(r for r in bundle["typed_passives"]
                             if r.get("feature_id") == SWAY and r.get("grant") == "focus_instead")
                grant["pay"] = {"resource_id": FOCUS, "amount": 1, "once_per_round": True}
            template = next(a for a in bundles[0]["action_catalog"] if a["display_name"] == "Iron Fist attack")
            for restore in (False, True):
                action = copy.deepcopy(template)
                action.update(source_definition_id=f"test:methods.{bundle['actor_id']}.{restore}",
                              display_name="Restore probe" if restore else "Guard probe", economy="NONE", costs=[],
                              owner_id=bundle["actor_id"], target_kind="SELF", range_ft=0)
                action["parameters"] = {"typed": {"source": action["source_definition_id"],
                    "numbers": template["parameters"]["typed"]["numbers"], "duration": {"kind": "instant"},
                    "effects": [{"type": "test_methods_probe", "restore": restore}]}}
                bundle["action_catalog"].append(action)
                bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
            if bundle["actor_id"] == OWNER:
                for resource in bundle["actor_template"]["resources"]:
                    if resource["resource_id"] == FOCUS:
                        resource["initial"] = resource["maximum"] = 3
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    return fixture(tmp_path, [SWAY, "tianxia.path.body_refining.feature.iron_fist"],
                   foe_talents=["tianxia.path.body_refining.feature.iron_fist"], bundle_transform=prepare)


@pytest.mark.parametrize("ai_turn", [False, True])
@pytest.mark.parametrize("payment", ["reaction", "focus"])
def test_payment_choice_and_cost_survive_table_commit_reload(tmp_path, monkeypatch, ai_turn, payment):
    combat, table, mid, send, commit = setup(tmp_path, monkeypatch)
    if ai_turn:
        commit(table.state(mid)["menu"]["end_turn"])
        while table.state(mid)["menu"]["actor_id"] != FOE:
            commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Guard probe")
    if ai_turn:
        auto_probe(combat, mid, FOE)
    first = send(cid, auto=ai_turn)
    assert first["status"] == "REACTION_REQUIRED"
    prompt = first["reaction"]
    assert {o["id"] for o in prompt["choice"]["options"]} == {"reaction", "focus"}
    assert "Martial Focus" in str(prompt) and "Guard probe" in str(prompt)
    assert "If you pay 1 Martial Focus, you cannot use this ability again until the start of your next turn." in prompt["cost"]
    assert "If you pay 1 Martial Focus" in prompt["trigger"]
    assert "Choose your Reaction or 1 Martial Focus" in prompt["cost"]
    assert send(cid, auto=ai_turn)["reaction"] == prompt
    _commit_all(send, cid, ai_turn, {"reaction:typed." + SWAY: payment})
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources[FOCUS] == (2 if payment == "focus" else 3)
    assert owner.reaction_available is (payment == "focus")


def test_exhausted_saved_focus_grant_offers_only_ordinary_reaction(tmp_path, monkeypatch):
    combat, table, mid, send, commit = setup(tmp_path, monkeypatch, legacy_grant=True)
    _commit_all(send, candidate(table, mid, "Guard probe"), False, {"reaction:typed." + SWAY: "focus"})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[FOCUS] == 2 and owner.reaction_available
    assert owner.turn_flags["_round_reaction_economy:" + SWAY] == engine.state.round_number
    row = next(r for r in engine.typed_reaction_rows[OWNER] if r.get("feature_id") == SWAY and r.get("block") == "generic")
    owner.reaction_available = False
    assert not reactions.reaction_waived(engine, owner, row)
    from combat.ext.reaction_economy import payment_text
    assert payment_text(engine, {"reaction_source_id": "reaction:typed." + SWAY, "reactor_id": OWNER}, {}) is None
    # Spend the retained Reaction, then restore it through the next table action.
    _commit_all(send, candidate(table, mid, "Guard probe"), False, {"reaction:typed." + SWAY: "reaction"})
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources[FOCUS] == 2 and not owner.reaction_available
    # Discard the service cache: the next prompt must use the saved bundle and counter.
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    fresh = CombatService(ROOT, tmp_path)
    table.combat = fresh
    cid = candidate(table, mid, "Restore probe")
    prompt = send(cid)["reaction"]
    assert not prompt.get("choice") or "focus" not in {o["id"] for o in prompt["choice"]["options"]}
    assert "Martial Focus" not in prompt["cost"]
    _commit_all(send, cid, False, {"reaction:typed." + SWAY: "reaction"})
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources[FOCUS] == 2 and not owner.reaction_available


def test_ordinary_payment_allows_another_restored_reaction(tmp_path, monkeypatch):
    combat, table, mid, send, commit = setup(tmp_path, monkeypatch)
    _commit_all(send, candidate(table, mid, "Guard probe"), False, {"reaction:typed." + SWAY: "reaction"})
    cid = candidate(table, mid, "Restore probe")
    prompt = send(cid)["reaction"]
    assert "If you pay 1 Martial Focus" in prompt["cost"]
    assert "If you pay 1 Martial Focus" in prompt["trigger"]
    _commit_all(send, cid, False, {"reaction:typed." + SWAY: "reaction"})
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources[FOCUS] == 3 and not owner.reaction_available
    assert not any(k.startswith("reaction_economy_until_turn:") for k in owner.turn_flags)


def test_active_defense_sheet_describes_selectable_focus_without_round_claim():
    from combat.typed_numbers import authority_mechanics
    record = authority_mechanics()["SHIELD_BASE_ACTIVE_DEFENSE"]
    text = " ".join(record["riders"] + record.get("description", []))
    assert "1 Martial Focus" in text and "even when your Reaction is available" in text
    assert "this round" not in text


def test_paid_lockout_blocks_restored_reactions_across_round_and_expires_at_owner_turn(tmp_path, monkeypatch):
    combat, table, mid, send, commit = setup(tmp_path, monkeypatch)
    cid = candidate(table, mid, "Guard probe")
    _commit_all(send, cid, False, {"reaction:typed." + SWAY: "reaction"})
    cid = candidate(table, mid, "Guard probe")
    _commit_all(send, cid, False, {"reaction:typed." + SWAY: "focus"})
    engine = reload(tmp_path, mid)
    initial = sum(e.event_type == "REACTION_WINDOW_OPENED" and e.payload.get("checkpoint") == "METHODS_PROBE" for e in engine.events)
    start_round = engine.state.round_number
    # Owner pays on their turn; it must also remain unavailable after their turn.
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(candidate(table, mid, "Restore probe"))
        engine = reload(tmp_path, mid)
        assert sum(e.event_type == "REACTION_WINDOW_OPENED" and e.payload.get("checkpoint") == "METHODS_PROBE" for e in engine.events) == initial
        commit(table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert engine.state.round_number >= start_round
    assert not any(k.startswith("reaction_economy_until_turn:") for k in engine.state.actors[OWNER].turn_flags)
    _commit_all(send, candidate(table, mid, "Guard probe"), False, {"reaction:typed." + SWAY: "focus"})
    assert reload(tmp_path, mid).state.actors[OWNER].resources[FOCUS] == 1


def test_spent_reaction_prompt_describes_actual_focus_payment(tmp_path, monkeypatch):
    combat, table, mid, send, commit = setup(tmp_path, monkeypatch)
    _commit_all(send, candidate(table, mid, "Guard probe"), False, {"reaction:typed." + SWAY: "reaction"})
    cid = candidate(table, mid, "Guard probe")
    result = send(cid)
    prompt = result["reaction"]
    assert prompt["cost"].startswith("1 Martial Focus; no Reaction")
    assert "next turn" in prompt["cost"]
    _commit_all(send, cid, False, {"reaction:typed." + SWAY: "focus"})
    assert reload(tmp_path, mid).state.actors[OWNER].resources[FOCUS] == 2


def test_ai_owner_automatically_uses_reaction_then_focus(tmp_path, monkeypatch):
    combat, table, mid, send, commit = setup(tmp_path, monkeypatch)
    for _ in range(2):
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="MANUAL")
        cid = candidate(table, mid, "Guard probe")
        auto_probe(combat, mid, OWNER)
        assert send(cid, auto=True)["status"] == "COMMITTED"
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert not owner.reaction_available and owner.resources[FOCUS] == 2


@pytest.mark.parametrize("owner_first", [False, True])
def test_real_turn_boundaries_with_early_and_late_owner(owner_first):
    from tests.test_auto4_methods import _guard, _row
    from tests import test_riders_c4 as C4
    engine, owner = _guard(SWAY)
    engine.state.initiative_order = [C4.ME, C4.FOE] if owner_first else [C4.FOE, C4.ME]
    engine.state.current_slot_index = 0
    engine.state.current_actor_id = engine.state.initiative_order[0]
    engine._system_start_turn()
    owner.reaction_available = False
    owner.resources[FOCUS] = 2
    reactions._open(engine, _row(), owner, (), "BOUNDARY_PROBE")
    reactions.spend_reaction(engine, owner, _row())
    paid_round = engine.state.round_number
    engine.end_turn()
    if owner_first:
        assert not reactions._can_trigger(engine, owner, _row())
        engine.end_turn()
        assert engine.state.round_number > paid_round
    else:
        assert engine.state.round_number == paid_round  # owner's turn, SAME round as payment
    assert reactions._can_trigger(engine, owner, _row())
    owner.reaction_available = False
    assert reactions.reaction_waived(engine, owner, _row())
    if not owner_first:
        # A late owner pays on its turn. The global round rolls over to the
        # early attacker before that owner's NEXT turn: still blocked.
        reactions._open(engine, _row(), owner, (), "LATE_OWNER_PROBE")
        reactions.spend_reaction(engine, owner, _row())
        engine.end_turn()
        owner.reaction_available = True
        assert engine.state.round_number > paid_round
        assert not reactions._can_trigger(engine, owner, _row())
        engine.end_turn()
        assert reactions._can_trigger(engine, owner, _row())
