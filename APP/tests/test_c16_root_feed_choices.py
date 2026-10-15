"""Feed the Root's claim and response-payment decisions at a committed table."""
from copy import deepcopy

import pytest

from combat.canonical import canonical_sha256
from combat.ext import verdant_chassis as verdant
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture, force_ai_candidate
from tests.test_r1i_round3 import reload, resolve
from tests.test_riders_c16 import SOWN, SEED, VG, growth

FEED = VG + "FEED_THE_ROOT"
INCARNATION = "tianxia.talent.verdant_growth.verdant_incarnation_body_becomes_the_ancient_tree"


def probes(bundles):
    """Test-only deterministic mark and melee actions use the normal typed resolver."""
    for bundle in bundles:
        if bundle["actor_id"] not in (OWNER, FOE):
            continue
        strike = next(a for a in bundle["action_catalog"] if a["display_name"] == "Seed-Thorn Strike")
        action = deepcopy(strike)
        action.update(source_definition_id="test:c16.mark_probe" if bundle["actor_id"] == OWNER else "test:c16.melee_probe",
                      display_name="Mark probe" if bundle["actor_id"] == OWNER else "Melee probe", economy="NONE")
        typed = action["parameters"]["typed"]
        typed["effects"] = ([{"type": "mark", "mark": "Growth Mark", "applies_to": "target"}]
                            if bundle["actor_id"] == OWNER else
                            [{"type": "attack", "attack_kind": "melee", "no_damage": True, "on_hit": []}])
        if bundle["actor_id"] == FOE:
            action.update(range_ft=None, reach_ft=5)
            typed["range_ft"] = None
        typed["numbers"]["attack_bonus"] = 100
        bundle["action_catalog"].append(action)
        bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
        if bundle["actor_id"] == OWNER:
            spend = deepcopy(action)
            spend.update(source_definition_id="test:c16.spend_probe", display_name="Spend probe")
            spend["parameters"]["typed"]["effects"] = [{"type": "spend_mark", "mark": "Growth Mark", "applies_to": "target"}]
            bundle["action_catalog"].append(spend)
            bundle["actor_template"]["action_ids"].append(spend["source_definition_id"])
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def sow(table, mid, commit, x, y):
    commit(next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Sow Living Claim"
                for o in g["options"] if o.get("destination") == {"x": x, "y": y}))


def next_owner(table, mid, commit):
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])


def claim_at(engine, x, y):
    return next(o for o in verdant.claims(engine, engine.state.actors[OWNER]) if (o.position.x, o.position.y) == (x, y))


@pytest.mark.parametrize("mode", ["manual", "enemy_ai_turn", "ai_owner"])
@pytest.mark.parametrize("decline", [False, True])
def test_feed_claim_selection_table(tmp_path, monkeypatch, mode, decline):
    from tests.test_lock_choices import install

    install(monkeypatch, "d20_result", lambda *a: {"source_id": "test:c16.feed_hit", "operation": "replace", "natural_result": 10})
    combat, table, mid, send, commit = fixture(
        tmp_path, [SOWN, SEED, FEED, INCARNATION], foe_talents=[SEED], owner_ac=0,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6},
                   SECOND: {"x": 7, "y": 6}}, bundle_transform=probes)
    if mode == "enemy_ai_turn":
        commit(candidate(table, mid, "Verdant Incarnation"))
        next_owner(table, mid, commit)
    sow(table, mid, commit, 4, 6)
    next_owner(table, mid, commit)
    sow(table, mid, commit, 6, 6)
    engine = reload(tmp_path, mid)
    touched, remote = claim_at(engine, 4, 6).object_id, claim_at(engine, 6, 6).object_id
    if mode == "enemy_ai_turn":
        commit(table.state(mid)["menu"]["end_turn"])
        while table.state(mid)["menu"]["actor_id"] != FOE:
            commit(table.state(mid)["menu"]["end_turn"])
        cid = candidate(table, mid, "Melee probe", OWNER)
        force_ai_candidate(combat, mid, FOE, cid)
    else:
        cid = candidate(table, mid, "Mark probe", FOE)
        if mode == "ai_owner":
            force_ai_candidate(combat, mid, OWNER, cid)
    _, prompts = resolve(combat, mid, send, cid, {"choice:needle.feed_the_root": None if decline else remote},
                         auto=mode != "manual")
    feed_prompts = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.feed_the_root"]
    assert bool(feed_prompts) == (mode != "ai_owner")
    if feed_prompts:
        prompt = feed_prompts[0]
        assert {touched, remote} <= {o["id"] for o in prompt["choice"]["options"]}
        assert prompt["context"]["reactor_id"] == OWNER
        assert "Feed the Root" in prompt["moment"] and "Foe" in prompt["moment"]
        assert ("Melee probe" if mode == "enemy_ai_turn" else "Mark probe") in prompt["moment"]
        assert all("Root Feed" in o["label"] and "square" in o["label"] for o in prompt["choice"]["options"])
    engine = reload(tmp_path, mid)
    expected = touched if mode == "ai_owner" else None if decline else remote
    assert growth(engine, FOE, OWNER) == 1
    for obj in verdant.claims(engine, engine.state.actors[OWNER]):
        assert obj.component["feed"] == int(obj.object_id == expected)
        if obj.object_id == expected:
            assert obj.component["feed_until"] == engine.state.actors[OWNER].turns_started + 1
    assert (engine.state.actors[OWNER].turn_flags.get("verdant_round_feed") is not None) == (expected is not None)
    if mode == "manual" and not decline:
        # Remote feed cannot pay a response through the claim touched by the target.
        assert not any(g["label"] == "Verdant Response: Bind" for g in table.state(mid)["menu"]["actions"])
    # A second placement in the same turn cannot feed twice; declining leaves the use available.
    if mode == "manual":
        _, again = resolve(combat, mid, send, candidate(table, mid, "Mark probe", FOE), {"choice:needle.feed_the_root": touched})
        assert bool(again) == decline
        engine = reload(tmp_path, mid)
        assert growth(engine, FOE, OWNER) == 2
        assert sum(o.component["feed"] for o in verdant.claims(engine, engine.state.actors[OWNER])) == 1


@pytest.mark.parametrize("payment", ["marks", "feed", "mixed", "only_mixed", "legacy_feed"])
@pytest.mark.parametrize("ai_owner", [False, True])
def test_bind_root_feed_payment_table(tmp_path, payment, ai_owner):
    combat, table, mid, send, commit = fixture(tmp_path, [SOWN, SEED, FEED], foe_talents=[SEED], bundle_transform=probes)
    sow(table, mid, commit, 4, 6)
    obj = claim_at(reload(tmp_path, mid), 4, 6).object_id
    commit(candidate(table, mid, "Mark probe", FOE))
    if payment != "only_mixed":
        next_owner(table, mid, commit)
        commit(candidate(table, mid, "Mark probe", FOE))
    if payment == "legacy_feed":
        commit(candidate(table, mid, "Spend probe", FOE))
    engine = reload(tmp_path, mid)
    old_marks = growth(engine, FOE, OWNER)
    old_feed = engine.state.objects[obj].component["feed"]
    assert old_marks == (1 if payment in ("only_mixed", "legacy_feed") else 2)
    assert old_feed == (1 if payment == "only_mixed" else 2)
    cid = candidate(table, mid, "Verdant Response: Bind", FOE)
    if ai_owner:
        force_ai_candidate(combat, mid, OWNER, cid)
    selected = "marks" if payment == "marks" else f"feed:{obj}" if payment in ("feed", "legacy_feed") else f"mixed:1:{obj}"
    _, prompts = resolve(combat, mid, send, cid, {"choice:needle.verdant_payment": selected}, auto=ai_owner)
    choices = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.verdant_payment"]
    assert bool(choices) == (not ai_owner and payment != "only_mixed")
    if choices:
        options = {f"feed:{obj}", f"mixed:1:{obj}"} | ({"marks"} if payment != "legacy_feed" else set())
        assert options == {o["id"] for o in choices[0]["choice"]["options"]}
        assert "Bind" in choices[0]["moment"] and "Foe" in choices[0]["moment"]
        assert all("Spend" in o["label"] for o in choices[0]["choice"]["options"])
    engine = reload(tmp_path, mid)
    used_marks = (1 if payment == "only_mixed" else 0 if payment == "legacy_feed" else 2 if ai_owner or payment == "marks"
                  else 0 if payment == "feed" else 1)
    assert growth(engine, FOE, OWNER) == old_marks - used_marks
    assert engine.state.objects[obj].component["feed"] == old_feed - (2 - used_marks)
    assert any(c.condition_id == "condition:typed.grappled" for c in engine.state.actors[FOE].conditions.values())
    assert engine.state.actors[OWNER].turn_flags["verdant_response_turn"]
    # Remaining feed expires at the end of the owner's next turn, never later.
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="MANUAL")
    assert not any(g["label"] == "Verdant Response: Bind" for g in table.state(mid)["menu"]["actions"])
    next_owner(table, mid, commit)
    commit(table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert engine.state.objects[obj].component["feed"] == 0


@pytest.mark.parametrize("pb", [1, 4])
def test_feed_grants_keep_separate_deadlines_and_cap_table(tmp_path, pb):
    _, table, mid, _, commit = fixture(tmp_path, [SOWN, SEED, FEED], foe_talents=[SEED], owner_pb=pb, bundle_transform=probes)
    sow(table, mid, commit, 4, 6)
    commit(candidate(table, mid, "Mark probe", FOE))
    engine = reload(tmp_path, mid)
    old = claim_at(engine, 4, 6)
    due = engine.state.actors[OWNER].turns_started + 1
    assert old.component["feed"] == 1 and old.component["feed_until"] == due
    next_owner(table, mid, commit)
    assert claim_at(reload(tmp_path, mid), 4, 6).component["feed"] == 1
    commit(candidate(table, mid, "Mark probe", FOE))
    engine = reload(tmp_path, mid)
    claim = claim_at(engine, 4, 6)
    assert claim.component["feed"] == (1 if pb == 1 else 2)
    assert claim.component["feed_until"] == (due if pb == 1 else due + 1)
    if pb == 1:
        assert claim.component["feed_schedule"] == old.component["feed_schedule"]  # no renewal at cap
    commit(table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert claim_at(engine, 4, 6).component["feed"] == (0 if pb == 1 else 1)
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(table.state(mid)["menu"]["end_turn"])
    assert claim_at(reload(tmp_path, mid), 4, 6).component["feed"] == 0


def test_no_claim_contact_does_not_feed_table(tmp_path):
    _, table, mid, _, commit = fixture(tmp_path, [SOWN, SEED, FEED], foe_talents=[SEED], bundle_transform=probes)
    sow(table, mid, commit, 6, 6)
    commit(candidate(table, mid, "Mark probe", FOE))
    engine = reload(tmp_path, mid)
    assert claim_at(engine, 6, 6).component["feed"] == 0
    assert growth(engine, FOE, OWNER) == 1
    assert "verdant_round_feed" not in engine.state.actors[OWNER].turn_flags


def test_no_feed_row_is_inert_table(tmp_path):
    def without_feed(bundles):
        probes(bundles)
        owner = next(b for b in bundles if b["actor_id"] == OWNER)
        # Feed is an automatic sphere component; model a sealed bundle lacking its owning row.
        owner["typed_passives"] = [r for r in owner["typed_passives"] if r.get("kind") != "feed_the_root"]
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    _, table, mid, _, commit = fixture(tmp_path, [SOWN, SEED], foe_talents=[SEED], bundle_transform=without_feed)
    sow(table, mid, commit, 4, 6)
    commit(candidate(table, mid, "Mark probe", FOE))
    engine = reload(tmp_path, mid)
    assert claim_at(engine, 4, 6).component["feed"] == 0
    assert growth(engine, FOE, OWNER) == 1
    assert not any(g["label"] == "Verdant Response: Bind" for g in table.state(mid)["menu"]["actions"])


@pytest.mark.parametrize("owner_turn, expected", [(1, 2), (2, 2), (3, 0)])
def test_saved_claim_without_schedule_keeps_recorded_deadline(owner_turn, expected):
    from types import SimpleNamespace

    # Old saves have no feed_schedule. Read-only queries preserve their exact aggregate/deadline.
    obj = SimpleNamespace(component={"feed": 2, "feed_until": 2})
    owner = SimpleNamespace(turns_started=owner_turn)
    assert verdant._feed(None, obj, owner) == expected
    assert obj.component == {"feed": 2, "feed_until": 2}
