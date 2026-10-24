"""Extension settings and Analyze explanations at the table/reload boundary."""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.status_text import printed_rules, describe
from combat.ext.generated_status_text import SOURCES
from tests.test_tabletop_hunt6 import table_fight, answer_action, on_hold, LEFT, RIGHT, HOLD
from tests.test_lock2_persistence import act


def assert_analyze_rules(text):
    for phrase in ("Intelligence (Investigation)", "Wisdom (Perception)", "10 +", "Challenge Rating",
                   "half", "rounded down", "Success", "Failure", "24 hours", "Long Rest",
                   "Martial Focus", "60 feet"):
        assert phrase in text
    assert "Skill Affinity" not in text and "proficiency in Dexterity (Stealth)" not in text


def test_descriptor_source_records_exist():
    assert set(SOURCES.values()) <= printed_rules().keys()


def test_shared_choice_metadata_matches_only_complete_unambiguous_printed_names():
    from combat.ext.choice_rule_text import named_record
    assert named_record("Guiding Star: choose an ally", printed_rules())
    assert named_record("Sovereign Hidden Eye Incarnation at the start of Left's turn", printed_rules()) == "TAL_THE_HIDDEN_EYE_SOVEREIGN_HIDDEN_EYE_INCARNATION"
    assert named_record("unknown option after Guiding Star", printed_rules()) is None
    assert named_record("Guiding Starlight", printed_rules()) is None
    assert named_record("Shared Name: choose", {"a": "### Shared Name", "b": "## Shared Name"}) is None


@pytest.mark.parametrize("feature,action,needle", [
    ("TAL_IRON_FIST_DRAGON_STEP_CLINCH", ".dragon_step_clinch.maintain", "Speed"),
    ("tianxia.path.body_refining.feature.core_tempering_expression", ".core_tempering_expression.blood_furnace", "permanent"),
    ("TAL_BERSERKER_BERSERK", ".adrenaline.berserk", "Resistance"),
])
def test_generated_pills_have_rules_after_commit_reload_and_replay(tmp_path, feature, action, needle):
    combat, table, mid = table_fight(tmp_path, [feature], ally_talents=[])
    engine = combat._load_session(mid).engine
    source = next(a.source_definition_id for a in engine.action_catalog.values() if action in a.source_definition_id and a.owner_id == LEFT)
    assert answer_action(table, mid, source)["status"] == "COMMITTED"
    def rows(table):
        return [c for a in table.state(mid)["presentation"]["actors"] if a["entity_id"] == LEFT for c in a["conditions"]]
    before = rows(table)
    assert before and all(c["rule_text"] and "unavailable" not in c["detail"] for c in before)
    assert needle in " ".join(c["rule_text"] for c in before)
    resumed = CombatService(combat.source_root, tmp_path)
    assert rows(TabletopService(resumed, tmp_path)) == before
    assert resumed._load_session(mid).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ai_turn", [False, True])
def test_analyze_skill_and_learning_prompts_explain_the_printed_rule(monkeypatch, tmp_path, ai_turn):
    combat, table, mid = table_fight(tmp_path, ["TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES"], ask=True, ally_talents=[])
    def analyze(engine):
        from combat.ext.riders14_eye import chosen_analyze_roll
        from combat.ext.riders14_research import learn
        chosen_analyze_roll(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT])
        learn(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT])
        from combat.ext.mind_hidden_eye import mark_analyzed
        from combat.ext.riders14_eye import count_analyze
        mark_analyzed(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT], "passive:eye.analysis")
        count_analyze(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT], {})
    on_hold(monkeypatch, analyze)
    if ai_turn:
        from combat.gate4_adapters import ManualControllerAdapter
        while table.state(mid)["menu"]["actor_id"] != RIGHT:
            act(table, mid, "end")
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
        real = combat.controller
        class Scripted:
            def choose_primary_action(self, context):
                cid = next(c.candidate_id for c in context.legal_candidates if c.source_definition_id == HOLD)
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Scripted()
    state = table.state(mid)
    menu = state["menu"]
    cid = (None if ai_turn else next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD))
    answers = []
    for _ in range(3):
        result = (table.auto_step(mid, 0, answers) if ai_turn else
                  table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers))
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
        assert prompt["rules"] and "No printed" not in prompt["summary"]
        assert_analyze_rules(prompt["rules"])
        assert "Analyze" in prompt["reaction"] and "Right" in prompt["trigger"]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [prompt["choice"]["options"][0]["id"]]})
    assert result["status"] == "COMMITTED" and len(answers) == 2
    def readings(table):
        return [c for a in table.state(mid)["presentation"]["actors"] for c in a["conditions"]
                if c["condition_id"] in {"condition:typed.analyzed_by", "condition:typed.eye_attempts",
                                         "condition:typed.eye_known_characteristic"}]
    before = readings(table)
    assert len(before) == 3
    for pill in before:
        assert_analyze_rules(pill["rule_text"])
        assert pill["source_ability"] == "Analyze"
    resumed = CombatService(combat.source_root, tmp_path)
    assert readings(TabletopService(resumed, tmp_path)) == before
    assert resumed._load_session(mid).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("feature,action,condition,cost", [
    ("tianxia.talent.disease.court_of_the_crawling_fever", ".crawling_fever.damage", "crawling_fever_choice", "7 Qi"),
    ("TAL_DESTRUCTION_DESTRUCTIVE_BLAST", "TAL_DESTRUCTION_DESTRUCTIVE_BLAST", "destruction_blast_type", "0 Qi"),
    ("tianxia.talent.beauty.beauty_in_motion", ".beauty_motion", "beauty_motion", "1 Qi"),
    ("TAL_MONKEY_STYLE_CAPERING_FOOTWORK", "TAL_MONKEY_STYLE_CAPERING_FOOTWORK", "monkey_caper", "1 Stamina"),
])
@pytest.mark.parametrize("source_known", [True, False])
@pytest.mark.parametrize("primary", ["Qi", "Resonance", "Stamina"])
def test_status_costs_use_retained_paying_pool_at_table_reload(monkeypatch, tmp_path, feature, action, condition, cost, source_known, primary):
    """Use fix/h44-devour's explicit pool argument (b042ed56).

    Approved by the lead in fix/QUEUE.md, LUNA23; fixture conflict resolution
    is documented in fix/R23b.report.md, Devour continuation.
    """
    cost = cost.replace("Qi", primary)
    combat, table, mid = table_fight(tmp_path, [feature], ally_talents=[], primary=primary)
    initial_resources = dict(combat._load_session(mid).engine.state.actors[LEFT].resources)
    def show_status(engine):
        owned = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and action in a.source_definition_id)
        engine._apply_condition(engine.state.actors[LEFT], "condition:typed." + condition,
                                owned.source_definition_id if source_known else "passive:unknown",
                                LEFT if source_known else "actor:missing", expires_on="UNTIL_REMOVED", data={})
    on_hold(monkeypatch, show_status)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    def reading(table):
        return next(c for a in table.state(mid)["presentation"]["actors"] if a["entity_id"] == LEFT
                    for c in a["conditions"] if c["condition_id"] == "condition:typed." + condition)
    before = reading(table)
    assert "CP" not in before["rule_text"]
    if source_known:
        assert cost in before["rule_text"]
        assert "paying Path resource pool" in before["rule_text"]
        if condition == "monkey_caper":
            assert f"1 {primary} (points from the paying Path resource pool)" in before["rule_text"]
            assert "no recorded resource cost" in before["rule_text"]
            assert "does not automatically charge its printed resource payment" in before["rule_text"]
    else:
        assert "paying Path resource pool unavailable in this saved fight" in before["rule_text"]
    # Presentation queries and showing a stored setting do not charge its activation cost.
    assert combat._load_session(mid).engine.state.actors[LEFT].resources == initial_resources
    resumed = CombatService(combat.source_root, tmp_path)
    assert reading(TabletopService(resumed, tmp_path)) == before
    assert resumed._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_resource_reading_uses_bound_cost_not_other_pools_and_explains_missing_pool():
    from types import SimpleNamespace
    from combat.ext.resource_readings import paying_pool, expand_cp
    actor = SimpleNamespace(entity_id=LEFT, resources={"resource:core.qi": 0, "resource:core.stamina": 10})
    action = SimpleNamespace(owner_id=LEFT, costs=(("resource:core.qi", 2),), parameters={})
    engine = SimpleNamespace(state=SimpleNamespace(actors={LEFT: actor}), action_catalog={"bound": action})
    assert paying_pool(engine, actor, {"source_definition_id": "bound"}) == "resource:core.qi"
    assert "2 Qi" in expand_cp("Cost: 2 CP", "resource:core.qi")
    assert paying_pool(engine, actor, {"source_actor_id": LEFT}) == ""
    assert paying_pool(engine, actor, {"source_actor_id": "missing applier"}) == ""
    action.costs = (("resource:core.cp", 2),)
    assert "unavailable" in expand_cp("Cost: 2 CP", paying_pool(engine, actor, {"source_definition_id": "bound"}))
    text = expand_cp("Cost: 7 CP", "")
    assert "CP" not in text and "7 cultivation points" in text and "unavailable in this saved fight" in text
    actor.resources = {"resource:core.qi": 10}
    assert paying_pool(engine, actor, {}) == ""  # A target's pool is not evidence about an unknown payer.
