"""Brute Maneuvers through source acquisition, table commits and cold replay."""
import pytest

from combat.ext.brute_maneuvers import SOURCE, EFFECT
from combat.ext.scoundrel_riders import held_possessions
from tests.worker2_support import OWNER, FOE, fixture, candidate, reload, settle
from tests.cw2_service_support import seal
from tests.r1i_service_support import force_ai_candidate

KIT = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1},
    {"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}}


def prepare(success):
    def transform(bundles):
        # Ordinary sheet check totals force the contest outcome; no effects,
        # receipts, ownership markers or held-item state are injected.
        bundles[2]["skills"] = {"Athletics": -100 if success else 100,
                                 "Acrobatics": -100 if success else 100}
        for b in bundles:
            seal(b)
    return transform


def disarms(engine, actor=OWNER):
    result = []
    for c in engine.legal_candidates():
        if c.actor_id != actor:
            continue
        action = engine.action_catalog.get(c.source_definition_id)
        if action is None:
            continue
        effects = ((action.parameters.get("typed") or {}).get("effects") or [])
        if any(e.get("type") == EFFECT for e in effects):
            result.append(c)
    return result


@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize("automatic", [False, True])
def test_disarm_native_contest_choice_no_damage_and_exact_drop_reload(tmp_path, success, automatic):
    combat, table, mid = fixture(tmp_path, [SOURCE], owner_kit=KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, named=True, bundle_transform=prepare(success))
    before = reload(tmp_path, mid)
    items = held_possessions(before, before.state.actors[FOE])
    assert len(items) == 2
    chosen = items[-1]
    hp = before.state.actors[FOE].current_hp
    cid = next(c.candidate_id for c in disarms(before) if c.target_ids == (FOE,))
    if automatic:
        force_ai_candidate(combat, mid, OWNER, cid)
    prompts = settle(table, mid, cid, {"choice:needle.brute_disarm_item": chosen["object"],
        "choice:needle.brute_disarm_skill": "Acrobatics"}, auto=automatic)
    cold = reload(tmp_path, mid)
    event = next(e for e in reversed(cold.events) if e.event_type == "CHECK_ROLLED" and e.payload.get("contest") == "disarm")
    assert event.payload["success"] is success
    assert event.payload["actor"]["reason"].startswith("ATTACK:")
    assert event.payload["target"]["reason"].startswith("CHECK:")
    assert event.payload["target_skill"] == "Acrobatics"
    assert cold.state.actors[FOE].current_hp == hp
    assert not cold.state.actors[OWNER].action_available
    remaining = held_possessions(cold, cold.state.actors[FOE])
    # On an AI turn the owner's choice is automatic; the human defender is
    # still asked to select its skill on that other actor's turn.
    if automatic:
        assert not any(p["context"]["reaction_source_id"] == "choice:needle.brute_disarm_item" for p in prompts)
        assert len(remaining) == 2 - int(success)
    else:
        assert {p["context"]["reaction_source_id"] for p in prompts} >= {"choice:needle.brute_disarm_item", "choice:needle.brute_disarm_skill"}
        assert (chosen["object"] in {i["object"] for i in remaining}) is (not success)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.brute_disarm_skill" for p in prompts)
    assert not any(e.event_type == "DAMAGE_COMMITTED" for e in cold.events[len(before.events):])


def test_disarm_requires_real_source_and_a_physically_held_target(tmp_path):
    _, _, mid = fixture(tmp_path / "plain", [], owner_kit=KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5})
    assert not disarms(reload(tmp_path / "plain", mid))
    _, _, mid = fixture(tmp_path / "empty", [SOURCE], owner_kit=KIT,
        foe_position={"x": 4, "y": 5})
    assert not disarms(reload(tmp_path / "empty", mid))


def test_disarm_keeps_remaining_attack_and_can_replace_it_again(tmp_path):
    combat, table, mid = fixture(tmp_path, [SOURCE], owner_kit=KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, bundle_transform=prepare(False),
        owner_features=("tianxia.path.body_refining.feature.extra_attack",))
    e = reload(tmp_path, mid)
    count = __import__("combat.ext.special_attacks", fromlist=["attacks_of"]).attacks_of(e, e.state.actors[OWNER])
    assert count > 1
    settle(table, mid, disarms(e)[0].candidate_id)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].turn_flags["special_attack_rest"] == count - 1
    second = disarms(e)
    assert second
    settle(table, mid, second[0].candidate_id)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].turn_flags["special_attack_rest"] == count - 2


BOW = "tianxia.mortal.weapon.gong_jian"
ARROWS = "tianxia.mortal.gear.arrows_20"
RANGED_KIT = {"starting_kit": {"items": [
    {"item_id": BOW, "quantity": 1},
    {"item_id": ARROWS, "name": "Arrows (20)", "quantity": 1}]}}


def test_ranged_disarm_strike_is_a_real_attack_that_spends_ammunition(tmp_path, monkeypatch):
    # Regression: the Disarm contest roll of a bow must go through the typed attack scope and emit
    # ATTACK_ROLLED, so ammunition is spent per strike and the spend survives commit and cold reload.
    import combat.ext.ammunition as ammunition
    monkeypatch.setitem(ammunition._PIECES_PER_UNIT, ARROWS, 2)
    combat, table, mid = fixture(tmp_path, [SOURCE], owner_kit=RANGED_KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, named=True, bundle_transform=prepare(False))
    before = reload(tmp_path, mid)
    offered = [(c.source_definition_id, c.target_ids) for c in disarms(before)]
    cid = next((c.candidate_id for c in disarms(before)
                if c.target_ids == (FOE,) and BOW in before.action_catalog[c.source_definition_id].parameters["typed"]["weapon_source_id"]),
               None)
    assert cid, offered
    settle(table, mid, cid, {"choice:needle.brute_disarm_item": "first",
        "choice:needle.brute_disarm_skill": "Acrobatics"})
    cold = reload(tmp_path, mid)
    rolls = [e for e in cold.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER
             and e.payload.get("contest") == "disarm"]
    assert len(rolls) == 1
    assert rolls[0].payload["roll_id"]
    spent = [v for k, v in cold.state.actors[OWNER].turn_flags.items() if k.startswith("_round_ammunition_spent:")]
    assert spent == [1]
