"""Equipment consumers execute native rolls, rest receipts and cold replay."""
import pytest

from combat.ext.armor_subject import fitted_ready
from tests.test_mgr_t14_fitted_armor import command, fight, fit, sheet, support, ACTOR, LAMELLAR

HEAVY = "tianxia.mortal.armor.imperial_plate_battle_dress"
CHECK = "action:test.mgr-t14.stealth-check"


def stealth_action(bundle):
    if bundle["actor_id"] != ACTOR:
        return
    support._bundle_action(bundle, CHECK, "Test Dexterity (Stealth)", {"typed": {
        "numbers": {}, "duration": {"kind": "instant"}, "riders": [], "effects": [{"type": "contest_against",
        "actor_check": {"kind": "check", "ability": "DEX", "skill": "Stealth"},
        "target_check": {"kind": "dc", "dc": 15}, "applies_to": "target", "on_success": [], "on_fail": []}]}}, target_kind="HOSTILE_ENTITY", range_ft=60)
    support._seal(bundle)


@pytest.mark.parametrize("case", ["chosen", "wrong_category", "no_choice", "unowned", "untrained", "repeat"])
def test_armor_ease_only_exempts_chosen_proficient_category_real_check(tmp_path, case):
    doc = sheet([] if case == "unowned" else ["armor_ease"] * (2 if case == "repeat" else 1),
                proficiency=() if case == "untrained" else ("light", "medium"))
    if case in {"chosen", "repeat", "wrong_category"}:
        command(tmp_path, doc, "armor.ease.choose", category="light" if case == "wrong_category" else "medium")
        if case == "repeat":
            command(tmp_path, doc, "armor.ease.choose", category="light")
        with pytest.raises(ValueError, match="different category"):
            command(tmp_path, doc, "armor.ease.choose", category="light" if case == "wrong_category" else "medium")
    if case in {"untrained", "unowned"}:
        with pytest.raises(ValueError):
            command(tmp_path, doc, "armor.ease.choose", category="medium")
    combat, table, mid = fight(tmp_path, doc, prepare=stealth_action)
    support._commit(combat, table, mid, CHECK, actor=ACTOR)
    engine = support._reload(tmp_path, mid)
    roll = next(r for r in engine.rolls if r.reason == f"CHECK:{CHECK}")
    assert roll.mode == ("NORMAL" if case in {"chosen", "repeat"} else "DISADVANTAGE")
    assert len(roll.dice) == (1 if case in {"chosen", "repeat"} else 2)


def heavy_sheet(talents, *, proficient=True):
    doc = sheet(talents, proficiency=("heavy",) if proficient else ())
    doc["equipment"][0]["starting_kit"]["items"] = [{"item_id": HEAVY, "name": "Plate", "quantity": 1}]
    for row in doc["ability_scores_and_statistics"]["abilities"]:
        if row["ability"] == "STR":
            row.update(score=8, modifier=-1)
    return doc


@pytest.mark.parametrize("case", ["qualified", "untrained", "unowned"])
def test_sure_harness_waives_only_qualified_strength_speed_penalty(tmp_path, case):
    doc = heavy_sheet([] if case == "unowned" else ["sure_harness"], proficient=case != "untrained")
    combat, table, mid = fight(tmp_path, doc)
    engine = support._reload(tmp_path, mid)
    actor = engine.state.actors[ACTOR]
    assert actor.speed_ft == (30 if case == "qualified" else 20)
    # Native legal movement allowance and its cold state use the same Speed.
    assert table.state(mid)["match_id"] == mid
    assert any(c.destination is not None for c in engine.legal_candidates())


def test_heavy_rest_disables_fitted_consumer_until_ten_minute_refit(tmp_path):
    doc = heavy_sheet(["sleep_in_armor", "breath_aligned_armor"])
    fit(tmp_path, doc, HEAVY)
    command(tmp_path, doc, "rest.start", kind="long_rest")
    command(tmp_path, doc, "time.advance", seconds=28800, observation="sleep")
    state = command(tmp_path, doc)
    assert state["rest_generation"] == 1
    assert state["armor"]["fitted_key"] == HEAVY and state["armor"]["ready"] == 0
    command(tmp_path, doc, "armor.fit.start", item_key=HEAVY)
    assert command(tmp_path, doc, "time.advance", seconds=599, observation="fitting")["armor"]["ready"] == 0
    from tests.test_a2_equipment import PREPARE
    from tests.test_mgr_t14_fitted_armor import prone_action
    from combat import posture
    combat, table, mid = fight(tmp_path, doc, prepare=prone_action)
    support._commit(combat, table, mid, PREPARE, actor=ACTOR)
    engine = support._reload(tmp_path, mid)
    assert not fitted_ready(engine, engine.state.actors[ACTOR])
    before = engine.state.actors[ACTOR].movement_remaining_ft
    support._commit(combat, table, mid, posture.SOURCE, actor=ACTOR)
    stood = support._reload(tmp_path, mid).state.actors[ACTOR]
    assert not posture.prone_conditions(stood) and stood.movement_remaining_ft == before - 10
    finish(combat, table, mid)
    command(tmp_path, doc, "time.advance", seconds=1, observation="fitting")
    combat, table, ready_mid = fight(tmp_path, doc, prepare=prone_action)
    support._commit(combat, table, ready_mid, PREPARE, actor=ACTOR)
    ready = support._reload(tmp_path, ready_mid)
    assert fitted_ready(ready, ready.state.actors[ACTOR])
    before = ready.state.actors[ACTOR].movement_remaining_ft
    support._commit(combat, table, ready_mid, posture.SOURCE, actor=ACTOR)
    stood = support._reload(tmp_path, ready_mid).state.actors[ACTOR]
    assert not posture.prone_conditions(stood) and stood.movement_remaining_ft == before - 5


def finish(combat, table, mid):
    from tests.test_lock2_persistence import act
    for _ in range(20):
        if combat._load_session(mid).engine.state.terminal_result:
            return
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError("Native maximum-round fight did not finish")


@pytest.mark.parametrize("case", ["unowned", "untrained", "unobserved", "interrupted"])
def test_sleep_in_armor_rejects_ineligible_or_unfinished_rest(tmp_path, case):
    doc = heavy_sheet([] if case == "unowned" else ["sleep_in_armor"], proficient=case != "untrained")
    if case in {"unowned", "untrained"}:
        with pytest.raises(ValueError, match="Sleep in Armor"):
            command(tmp_path, doc, "rest.start", kind="long_rest")
        return
    fit(tmp_path, doc, HEAVY)
    command(tmp_path, doc, "rest.start", kind="long_rest")
    if case == "unobserved":
        command(tmp_path, doc, "time.advance", seconds=28800)
    else:
        command(tmp_path, doc, "time.advance", seconds=3600, observation="sleep")
        command(tmp_path, doc, "rest.interrupt", reason="initiative")
    state = command(tmp_path, doc)
    assert state["rest_generation"] == 0
    assert state["armor"]["ready"] == 1


@pytest.mark.parametrize("modality", ["visual", "touch"])
def test_hidden_plates_real_search_and_touch_advantage_cold_reload(tmp_path, modality):
    doc = sheet(["hidden_plates"])
    command(tmp_path, doc, "armor.conceal", item_key=LAMELLAR, disguise="court dress")
    combat, table, mid = fight(tmp_path, doc, attacker_position=(4, 6))
    engine = combat._load_session(mid).engine
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == support.ATTACKER and a.source_definition_id.endswith("armor_search." + modality))
    # Submit the actual target-specific candidate, not the self-search option.
    from tests.test_lock2_persistence import act
    while table.state(mid)["menu"]["actor_id"] != support.ATTACKER:
        act(table, mid, "end")
    state = table.state(mid)
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                     if c.source_definition_id == source and c.target_ids == (ACTOR,))
    result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version, state["last_sequence"])
    assert result["status"] == "COMMITTED"
    cold = support._reload(tmp_path, mid)
    roll = next(r for r in cold.rolls if r.reason == "CHECK:" + source)
    assert roll.actor_id == support.ATTACKER
    assert roll.mode == ("ADVANTAGE" if modality == "touch" else "NORMAL")
    assert len(roll.dice) == (2 if modality == "touch" else 1)
    receipt = next(e for e in cold.events if e.source_definition_id == support.T + "hidden_plates"
                   and "armor_found" in e.payload)
    assert receipt.payload["dc"] == 8 + cold.state.actors[ACTOR].proficiency_bonus + 2
    assert receipt.payload["armor_found"] == int(roll.total >= receipt.payload["dc"])
    assert receipt.payload["modality"] == modality


@pytest.mark.parametrize("case", ["unowned", "untrained", "heavy", "wrong_item"])
def test_hidden_plates_negative_concealment_eligibility(tmp_path, case):
    doc = heavy_sheet(["hidden_plates"]) if case == "heavy" else sheet(
        [] if case == "unowned" else ["hidden_plates"], proficiency=() if case == "untrained" else ("medium", "light"))
    with pytest.raises(ValueError):
        command(tmp_path, doc, "armor.conceal", item_key=HEAVY if case == "heavy" else
                "invented" if case == "wrong_item" else LAMELLAR, disguise="court dress")


@pytest.mark.parametrize("moved", [False, True])
def test_hidden_plates_blind_touch_search_keeps_advantage_and_visual_requires_sight(tmp_path, moved):
    blindfold = "action:test.mgr-t14.blindfold"
    doc = sheet(["hidden_plates"])
    command(tmp_path, doc, "armor.conceal", item_key=LAMELLAR, disguise="work garments")
    def prepare(bundle):
        if bundle["actor_id"] == support.ATTACKER:
            support._bundle_action(bundle, blindfold, "Put on a blindfold", {"typed": {"numbers": {}, "riders": [],
                "duration": {"kind": "rounds", "amount": 10}, "effects": [
                    {"type": "condition", "condition": "blinded", "applies_to": "self"}]}}, target_kind="SELF", range_ft=None)
            support._seal(bundle)
    combat, table, mid = fight(tmp_path, doc, prepare=prepare, attacker_position=(4, 6))
    support._commit(combat, table, mid, blindfold)
    from tests.test_lock2_persistence import act
    assert act(table, mid, "end")["status"] == "COMMITTED"
    if moved:
        # The blind searcher must reach for the known space, never follow the
        # target's unobserved movement or learn where it went from its menu.
        state = table.state(mid)
        assert state["menu"]["actor_id"] == ACTOR
        move = next(c for c in state["menu"]["moves"] if c["destination"] == {"x": 2, "y": 6})
        assert table.act(mid, move["candidate_id"], state["menu"]["decision_id"],
                         state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != support.ATTACKER:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == support.ATTACKER and a.source_definition_id.endswith("armor_search.touch"))
    candidates = engine.legal_candidates()
    assert not any(c.source_definition_id.endswith("armor_search.visual") and c.target_ids == (ACTOR,) for c in candidates)
    candidate = next(c for c in candidates if c.source_definition_id == source and c.target_ids == (ACTOR,))
    assert candidate.destination.model_dump(mode="json") == {"x": 3, "y": 6}
    assert "reach toward" in candidate.metadata["target_label"]
    # Model/AI menus use the same known target, without discovering hidden armor.
    from combat.candidate_knowledge import query
    with query(engine):
        assert any(c.source_definition_id == source and c.target_ids == (ACTOR,) for c in engine.legal_candidates())
    result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version, state["last_sequence"])
    assert result["status"] == "COMMITTED"
    cold = support._reload(tmp_path, mid)
    assert any(c.condition_id.endswith("blinded") for c in cold.state.actors[support.ATTACKER].conditions.values())
    if moved:
        assert not any(r.reason == "CHECK:" + source for r in cold.rolls)
        assert any(e.source_definition_id == source and e.payload.get("reason") == "EMPTY_REMEMBERED_SQUARE" for e in cold.events)
        return
    roll = next(r for r in cold.rolls if r.reason == "CHECK:" + source)
    assert roll.mode == "ADVANTAGE" and len(roll.dice) == 2
    assert any(e.payload.get("modality") == "touch" and "armor_found" in e.payload for e in cold.events)


@pytest.mark.parametrize("seed", ["stock-1", "stock-2", "stock-3", "stock-4", "stock-5", "stock-6"])
def test_stock_equipment_seams(tmp_path, seed, monkeypatch):
    """Invoke the six stock guard providers, retaining only this lane's evidence."""
    from tests import test_a2_glass_stock as stock
    from tests.test_save_reload_equivalence import STOCK_SEEDS
    index = int(seed.split("-")[-1]) - 1
    stock_evidence = tmp_path / "stock"
    stock_evidence.mkdir()
    monkeypatch.setenv("CF_STOCK_EVIDENCE", str(stock_evidence))
    stock.test_six_stock_captures_equal_main(tmp_path, STOCK_SEEDS[index])
