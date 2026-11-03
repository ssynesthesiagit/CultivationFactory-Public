"""Nullifying melee uses are paid after each hit, including off-turn attacks."""
import hashlib
import pytest

from combat.tabletop import ButtonStore
from tests.hunt36_support import LEFT, RIGHT, act, fight, reload, send, turn, weapon
from tests.test_hunt36_nullifying_weapons import NULL, seed_for

EXTRA = "tianxia.path.body_refining.feature.extra_attack"


def test_foreign_paid_hit_metadata_is_inert_without_the_owners_row():
    from types import SimpleNamespace
    from combat.ext.paid_hit import paid_hit

    actor = SimpleNamespace(entity_id=LEFT, resources={"resource:core.stamina": 30})
    ctx = SimpleNamespace(actor=actor, engine=SimpleNamespace(typed_passive_rows={}),
        typed={"paid_hit_choices": [{"id": NULL}]})
    paid_hit(ctx, SimpleNamespace(active=True), "weapon")
    assert actor.resources["resource:core.stamina"] == 30


def miss_seed():
    for i in range(10000):
        seed = f"H36-miss-{i}"
        natural = int.from_bytes(hashlib.sha256(seed.encode() + b"\0" + (2).to_bytes(16, "big")).digest(), "big") % 20 + 1
        if natural == 1:
            return seed
    raise AssertionError("no miss seed")


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("case", ["two_hits", "miss_hit", "all_miss", "decline", "last_two"])
def test_extra_attacks_pay_only_for_selected_affordable_hits(tmp_path, ai, case):
    combat, table, mid = fight(tmp_path, [NULL, EXTRA], primary="Stamina", cl=5,
        stamina=2 if case == "last_two" else None,
        foe_ac=1000 if case == "all_miss" else 1,
        seed=miss_seed() if case == "miss_hit" else seed_for("melee", False))
    turn(combat, table, mid)
    engine = reload(combat, mid)
    before = engine.state.event_sequence
    stamina = engine.state.actors[LEFT].resources["resource:core.stamina"]
    prompts = send(combat, table, mid, weapon(combat, mid).candidate_id, ai=ai,
        decline=(lambda p, n: n == 1) if case == "decline" and not ai else None)
    engine = reload(combat, mid)
    events = [e for e in engine.events if e.sequence > before]
    hits = [e.payload["provisional_hit"] for e in events if e.event_type == "ATTACK_ROLLED"]
    assert hits == ([False, True] if case == "miss_hit" else [False, False] if case == "all_miss" else [True, True])
    uses = 0 if case == "all_miss" else 1 if case in ("miss_hit", "last_two") or (case == "decline" and not ai) else 2
    bonus = [e for e in events if e.event_type == "DAMAGE_ROLLED" and e.payload.get("damage_label") == "Nullifying Strike"]
    payments = [e for e in events if e.event_type == "RESOURCE_SPENT" and e.payload.get("resource_id") == "resource:core.stamina"]
    assert len(bonus) == len(payments) == uses
    assert all(e.payload["amount"] == 2 for e in payments)
    assert all(e.source_definition_id == NULL for e in payments)
    assert engine.state.actors[LEFT].resources["resource:core.stamina"] == stamina - 2 * uses
    if not ai:
        assert len(prompts) == (0 if case == "all_miss" else 1 if case in ("miss_hit", "last_two") else 2)
    # Every payment follows its own hit; no action-start payment or unpaid extra save.
    for payment in payments:
        preceding = [e for e in events if e.sequence < payment.sequence and e.event_type == "ATTACK_ROLLED"]
        assert preceding[-1].payload["provisional_hit"]
    assert len([e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == f"passive:{NULL}"]) == uses


@pytest.mark.parametrize("ai", [False, True])
def test_offhand_melee_hit_offers_paid_rider(tmp_path, ai):
    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou", "quantity": 2}]}}
    combat, table, mid = fight(tmp_path, [NULL], primary="Stamina", kit=kit, seed=seed_for("melee", False))
    turn(combat, table, mid)
    send(combat, table, mid, weapon(combat, mid).candidate_id, ai=ai)
    engine = reload(combat, mid)
    before = engine.state.event_sequence
    stamina = engine.state.actors[LEFT].resources["resource:core.stamina"]
    offhand = next(c for c in engine.legal_candidates() if "#offhand" in c.source_definition_id and tuple(c.target_ids) == (RIGHT,))
    send(combat, table, mid, offhand.candidate_id, ai=ai)
    engine = reload(combat, mid)
    bonus = [e for e in engine.events if e.sequence > before and e.event_type == "DAMAGE_ROLLED" and e.payload.get("damage_label") == "Nullifying Strike"]
    assert len(bonus) == 1
    assert engine.state.actors[LEFT].resources["resource:core.stamina"] == stamina - 2


@pytest.mark.parametrize("owner_ai", [False, True])
def test_melee_opportunity_attack_paid_hit_on_ai_turn(tmp_path, owner_ai):
    combat, table, mid = fight(tmp_path, [NULL], primary="Stamina", seed=seed_for("melee", False))
    turn(combat, table, mid)
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions("36000001", {"mode": "ask"}, {"opportunity_attack"})
    if owner_ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    act(combat, table, mid, "end", ai=owner_ai)
    engine = reload(combat, mid)
    before = engine.state.event_sequence
    stamina = engine.state.actors[LEFT].resources["resource:core.stamina"]
    menu = table.state(mid)["menu"]
    cid = next(m["candidate_id"] for m in menu["moves"] if m["destination"] == {"x": 5, "y": 6})
    prompts = send(combat, table, mid, cid, ai=True)
    engine = reload(combat, mid)
    events = [e for e in engine.events if e.sequence > before]
    assert len([e for e in events if e.event_type == "DAMAGE_ROLLED" and e.payload.get("damage_label") == "Nullifying Strike"]) == 1
    assert engine.state.actors[LEFT].resources["resource:core.stamina"] == stamina - 2
    paid_prompts = [p for p in prompts if p.get("choice") and p["context"].get("reaction_source_id") == "choice:needle.paid_hit"]
    assert bool(paid_prompts) == (not owner_ai), prompts
    if paid_prompts:
        text = paid_prompts[0]["moment"]
        assert "Nullifying Strike" in text and "Opportunity Attack" in text and "Visiting Fighter" in text
        assert "You pay separately for each hit; conditions last for the duration shown in the option." in text
        assert "The chosen effects apply only to this hit." not in text


def test_paid_hit_preview_rolls_back_until_all_hit_choices_are_answered(tmp_path):
    combat, table, mid = fight(tmp_path, [NULL, EXTRA], primary="Stamina", cl=5, seed=seed_for("melee", False))
    turn(combat, table, mid)
    before = reload(combat, mid).state.model_dump(mode="json")
    candidate = weapon(combat, mid)
    state = table.state(mid)
    menu = state["menu"]
    def submit(answers):
        return table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
    first = submit([])
    assert first["status"] == "REACTION_REQUIRED"
    assert reload(combat, mid).state.model_dump(mode="json") == before
    prompt = first["reaction"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": [prompt["choice"]["options"][0]["id"]]}
    second = submit([answer])
    assert second["status"] == "REACTION_REQUIRED"
    assert reload(combat, mid).state.model_dump(mode="json") == before
    decline = {**second["reaction"]["context"], "selection": "DECLINE"}
    assert submit([answer, decline])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources["resource:core.stamina"] == before["actors"][LEFT]["resources"]["resource:core.stamina"] - 2
