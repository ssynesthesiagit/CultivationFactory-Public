"""Notice Profiling regressions through table execute_intent, commit and cold replay.

The recorded-learning stimulus uses the public helper inside an existing event
hook; it never replaces engine methods. Browser rendering remains for the lead
outside the sandbox; these checks assert the actual service presentation.
"""
import json

import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.gate4_adapters import ManualControllerAdapter
from combat.tabletop_service import TabletopService
from combat.ext.mind_hidden_eye import FOCUS, record_characteristic
from combat.ext.riders14_research import NOTICE
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, turn, candidate, settle, reload
from tests.test_r9i_karma_persistence import act

BASE = "TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES"
BIO = "tianxia.talent.the_hidden_eye.biological_insight"
TALENT = "TAL_THE_HIDDEN_EYE_NOTICE_PROFILING"
CHOICE = "choice:needle.eye_profile"
APPROACH = "choice:needle.eye_approach"
LEARN = "choice:needle.eye_learn"
LIMIT = "Notice Profiling does not detect ordinary observation, guessing, or knowledge a creature possessed before entering range."


def named_bundles(bundles):
    """Distinct display names make learner-identity leaks detectable."""
    for bundle, name in zip(bundles, ("Watcher", "Companion", "Researcher")):
        bundle["actor_template"]["display_name"] = name
        if bundle["actor_id"] == OWNER:
            bundle["actor_template"]["creature_types"] = ["Humanoid"]
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def notice(engine):
    return next((c.data for c in engine.state.actors[OWNER].conditions.values()
                 if c.condition_id == NOTICE), None)


def card(tmp_path, mid):
    return next((c for c in cards(tmp_path, mid) if c["condition_id"] == NOTICE), None)


def cards(tmp_path, mid):
    cold = CombatService(ROOT, tmp_path)
    state = TabletopService(cold, tmp_path).state(mid)
    actor = next(a for a in state["presentation"]["actors"] if a["entity_id"] == OWNER)
    return actor["conditions"]


def foe_analyze(tmp_path, *, answer=None, nature=False, ai=False):
    combat, table, mid = fixture(tmp_path, [BASE, TALENT], cl=5, seed="A2-NOTICE",
                                bundle_transform=named_bundles,
                                foe_sheet=sheet([BASE, *([BIO] if nature else [])], cl=5))
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, FOE)
    if ai:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.actors[OWNER].resources[FOCUS]
    chosen = candidate(combat, mid, "Analyze", target=OWNER)
    prompts = settle(table, mid, chosen.candidate_id,
                     picks={APPROACH: "Nature" if nature else "Investigation", LEARN: "Armor Class", CHOICE: answer})
    engine = reload(tmp_path, mid)
    return combat, table, mid, prompts, engine, before


def test_decline_prompt_does_not_disclose_learner_or_characteristic(tmp_path):
    _, _, mid, prompts, engine, before = foe_analyze(tmp_path)
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    text = json.dumps({k: v for k, v in prompt.items() if k != "context"})
    assert "Notice Profiling" in text and "Analyze" in text
    assert "Martial Focus" in text and "120 feet" in text
    assert "Armor Class" not in text
    assert engine.state.actors[FOE].display_name not in text
    assert engine.state.actors[OWNER].resources[FOCUS] == before
    assert not notice(engine)["revealed"]
    displayed = json.dumps(card(tmp_path, mid))
    assert "Armor Class" not in displayed
    assert engine.state.actors[FOE].display_name not in displayed


@pytest.mark.parametrize("ai", [False, True], ids=["human-off-turn", "computer-owner"])
def test_paid_result_is_visible_after_cold_reload_and_ai_chooses_it(tmp_path, ai):
    _, _, mid, prompts, engine, before = foe_analyze(tmp_path, answer="profile", ai=ai)
    assert notice(engine)["revealed"]
    assert engine.state.actors[OWNER].resources[FOCUS] == before - 1
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts) is (not ai)
    displayed = json.dumps(card(tmp_path, mid))
    assert "Armor Class" in displayed and engine.state.actors[FOE].display_name in displayed
    assert "unavailable" not in displayed
    assert "this round" in displayed and "Martial Focus" in displayed
    assert LIMIT in displayed
    # Preserve the complete printed limitation in the reviewed record too.
    reviewed = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/a2_hidden_eye.json").read_text())
    assert LIMIT in reviewed["mechanics"][TALENT]["description"]


def test_nature_analyze_reports_counted_and_free_learning_together(tmp_path):
    _, _, mid, prompts, engine, _ = foe_analyze(tmp_path, answer="profile", nature=True)
    assert len([p for p in prompts if p["context"]["reaction_source_id"] == CHOICE]) == 1
    facts = [name for row in notice(engine)["notices"] for name in row["characteristics"]]
    assert "Armor Class" in facts and "Creature Type" in facts
    displayed = json.dumps(card(tmp_path, mid))
    assert "Armor Class" in displayed and "Creature Type" in displayed


@pytest.mark.parametrize("pay_first", [False, True], ids=["pay-after-decline", "later-decline-keeps-paid-snapshot"])
def test_recorded_learning_accumulates_declined_facts_and_reveals_only_when_paid(tmp_path, monkeypatch, pay_first):
    combat, table, mid = fixture(tmp_path, [BASE, TALENT], seed="A2-RECORDED", bundle_transform=named_bundles)
    ext.effects()

    def confirm(engine, kind, kwargs):
        if kind == "HOLD_POSITION_COMMITTED" and kwargs.get("actor_id") == OWNER:
            owner = engine.state.actors[OWNER]
            record_characteristic(engine, engine.state.actors[FOE], owner, "maximum_hp", "test:confirmed")
            if pay_first:
                engine._gain_resource(owner, FOCUS, 1, "test:regained_focus")
            record_characteristic(engine, engine.state.actors[ALLY], owner, "Walking Speed", "test:confirmed")

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), confirm])
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
               if c.source_definition_id == "system:combat.hold_position")
    answers, prompts = [], []
    for _ in range(4):
        result = act(table, mid, cid, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] == CHOICE
        prompts.append(prompt)
        pay = (len(prompts) == 1) is pay_first
        answer = {**prompt["context"], "selection": "USE" if pay else "DECLINE"}
        if answer["selection"] == "USE":
            answer["option_ids"] = ["profile"]
        answers.append(answer)
    else:
        pytest.fail("recorded learning never committed")
    engine = reload(tmp_path, mid)
    assert len(prompts) == 2
    assert notice(engine)["revealed"] is (not pay_first) and len(notice(engine)["notices"]) == 2
    displayed = json.dumps(card(tmp_path, mid))
    for aid in ((FOE,) if pay_first else (FOE, ALLY)):
        assert engine.state.actors[aid].display_name in displayed
    assert "Maximum Hit Points" in displayed
    assert ("Walking Speed" in displayed) is (not pay_first)
    if pay_first:
        assert engine.state.actors[ALLY].display_name not in displayed
        # All target cards must respect payment, including the permanent ledger.
        all_displayed = json.dumps(cards(tmp_path, mid))
        assert "Walking Speed" not in all_displayed
        assert engine.state.actors[ALLY].display_name not in all_displayed
        assert ALLY not in all_displayed
    from combat.ext.mind_hidden_eye import known_characteristic
    assert known_characteristic(engine.state.actors[OWNER], ALLY, "Walking Speed")


def test_manual_owner_is_asked_on_computer_controlled_analyze_turn(tmp_path):
    combat, table, mid = fixture(tmp_path, [BASE, TALENT], cl=5, seed="A2-NOTICE",
                                bundle_transform=named_bundles, foe_sheet=sheet([BASE], cl=5))
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, FOE)
    chosen = candidate(combat, mid, "Analyze", target=OWNER)
    real = combat.controller

    class AnalyzeController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _context: (chosen.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = AnalyzeController()
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    result = table.auto_step(mid, 0)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == CHOICE
    assert prompt["context"]["reactor_id"] == OWNER
    assert "Researcher" not in json.dumps({k: v for k, v in prompt.items() if k != "context"})
    assert table.auto_step(mid, 0, [{**prompt["context"], "selection": "DECLINE"}])["status"] == "COMMITTED"
    assert not notice(reload(tmp_path, mid))["revealed"]
    assert "Researcher" not in json.dumps(card(tmp_path, mid))


def test_printed_limitation_is_preserved_in_reviewed_text_and_cold_service_status(tmp_path):
    _, _, mid, _, _, _ = foe_analyze(tmp_path, answer="profile")
    reviewed = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/a2_hidden_eye.json").read_text())
    assert LIMIT in reviewed["mechanics"][TALENT]["description"]
    assert LIMIT in json.dumps(card(tmp_path, mid))


@pytest.mark.parametrize("answer", [None, "profile"], ids=["unpaid", "paid"])
def test_round_boundary_removes_notice_without_any_later_learning(tmp_path, answer):
    _, table, mid, _, engine, _ = foe_analyze(tmp_path, answer=answer)
    old_round = engine.state.round_number
    assert notice(engine) is not None
    for _ in range(5):
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        engine = reload(tmp_path, mid)
        if engine.state.round_number > old_round:
            break
    assert engine.state.round_number == old_round + 1
    assert notice(engine) is None
    assert card(tmp_path, mid) is None


def test_legacy_saved_notice_expires_without_another_learning_event(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, [BASE, TALENT], seed="A2-LEGACY", bundle_transform=named_bundles)
    ext.effects()

    def old_notice(engine, kind, kwargs):
        if kind == "HOLD_POSITION_COMMITTED" and kwargs.get("actor_id") == OWNER:
            engine._apply_condition(engine.state.actors[OWNER], NOTICE, "passive:eye.notice_profiling", OWNER,
                                    expires_on="UNTIL_REMOVED", data={"round": engine.state.round_number,
                                    "notices": [], "revealed": True})

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), old_notice])
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
               if c.source_definition_id == "system:combat.hold_position")
    settle(table, mid, cid)
    engine = reload(tmp_path, mid)
    old_round = engine.state.round_number
    assert notice(engine) is not None
    for _ in range(5):
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        engine = reload(tmp_path, mid)
        if engine.state.round_number > old_round:
            break
    assert engine.state.round_number == old_round + 1
    assert notice(engine) is None and card(tmp_path, mid) is None
