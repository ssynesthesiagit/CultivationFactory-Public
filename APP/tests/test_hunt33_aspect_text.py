"""Beast Aspect explanations at the real turn-boundary table pause and reload."""
import pytest

from combat.ext.beast_aspects import PREFIX, ASPECTS, active, aspect_decision_text
from combat.gate5_service import CombatService
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, LEFT


@pytest.mark.parametrize("feature,count", [("beast_scripture_initiate", 1),
                                         ("paired_beast_body", 2),
                                         ("chimera_meridian_network", 3)])
def test_aspect_turn_prompt_explains_options_and_commits_reload(tmp_path, feature, count):
    ids = [PREFIX + "beast_scripture_initiate"]
    if feature != "beast_scripture_initiate":
        ids.append(PREFIX + feature)
    combat, table, mid = table_fight(tmp_path, ids, ask=True, ally_talents=[])
    # End a complete round: the real start-turn hook must ask the manual owner.
    for _ in range(4):
        state = table.state(mid)
        menu = state["menu"]
        args = (mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
        answers = []
        result = table.act(*args, answers)
        while result["status"] == "REACTION_REQUIRED" and result["reaction"]["context"]["reaction_source_id"] != "choice:needle.beast_aspects":
            # Chimera also offers a separate optional replacement after a foe's turn.
            swap = result["reaction"]
            assert "Replace one active Beast Aspect" in swap["summary"]
            assert all(o["description"] for o in swap["choice"]["options"])
            answers.append({**swap["context"], "selection": "DECLINE"})
            result = table.act(*args, answers)
        if result["status"] == "REACTION_REQUIRED":
            break
        assert result["status"] == "COMMITTED"
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert "Beast Aspects" in prompt["summary"] and "Left" in prompt["summary"]
    assert "start of your next turn" in prompt["summary"]
    assert "Activating an Aspect requires no action or Stamina" in prompt["rules"]
    assert prompt["cost"] == "No action or Stamina cost"
    expected = {"Tiger": "Proficiency Bonus", "Crane": "10 feet", "Serpent": "unarmed reach",
                "Ox": "one size larger", "Turtle": "+1 Armor Class", "Wolf": "conscious ally",
                "Ape": "Grapples and Shoves", "Falcon": "thrown weapons"}
    options = prompt["choice"]["options"]
    assert {o["id"] for o in options} == set(ASPECTS if count == 3 else ASPECTS[:count + 2])
    for option in options:
        text = option["description"]
        assert expected[option["id"]] in text
        assert "start of your next turn" in text and "No action or Stamina cost" in text
        assert "actor:" not in text and "beast_aspect_" not in text
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    assert table.act(*args, answers)["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    picks = [o["id"] for o in options][-count:]
    answer = {**prompt["context"], "selection": "USE", "option_ids": picks}
    assert table.act(*args, [*answers, answer])["status"] == "COMMITTED"
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    assert set(active(loaded.engine, loaded.engine.state.actors[LEFT])) == set(picks)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("choice,options,phrase", [
    ("chimera_swap", ["Tiger>Turtle"], "End your Tiger Aspect and activate Turtle"),
    ("sovereign_end", ["Falcon", "Ox", "Ape"], "Activate Falcon"),
])
def test_other_aspect_selectors_explain_replacement_and_free_cost(tmp_path, choice, options, phrase):
    combat, _, mid = table_fight(tmp_path, [PREFIX + "beast_scripture_initiate", PREFIX + "chimera_meridian_network"],
                                 ask=True, ally_talents=[])
    engine = combat._load_session(mid).engine
    context = {"reaction_source_id": "choice:needle." + choice, "reactor_id": LEFT,
               "extension_choice": {"option_ids": options}}
    text = aspect_decision_text(engine, context, {})
    assert phrase in text["option_descriptions"][options[0]]
    assert "No action or Stamina cost" in text["cost"]
    assert ("next legal Aspect selection or replacement" if choice == "chimera_swap" else
            "start of your next turn") in text["summary"]
    assert aspect_decision_text(engine, {**context, "reactor_id": "missing"}, {}) is None
    assert aspect_decision_text(engine, {**context, "reaction_source_id": "choice:unrelated"}, {}) is None
    engine.typed_passive_rows[LEFT] = []
    assert aspect_decision_text(engine, context, {}) is None
