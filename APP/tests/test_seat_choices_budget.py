"""Offline regressions for SOL170r2's pre-dispatch choices failures.

Small public menu shapes reproduce the recorded long-plan/mandatory-choice
failures without retaining private saves or requiring a model or browser.
"""
import pytest

from agent_seats.choices import build_prompt, parse_letter, reaction_options, turn_options
from tests.test_agent_seats import runner_for
from tests.test_hunt5_player_choices import fixture, FOE
from tests.test_seat_choices import configure


def long_menu():
    view = {"fighter": "self", "actors": [
        {"entity_id": "self", "display_name": "Death fighter", "team_id": "a",
         "position": {"x": 2, "y": 5}, "hit_points": "55/55"},
        {"entity_id": "foe", "display_name": "Enemy fighter", "team_id": "b",
         "position": {"x": 17, "y": 5}},
        {"entity_id": "ally", "display_name": "Corpse Servant 1", "team_id": "a",
         "position": {"x": 2, "y": 5}}],
        "dao": {"temperament": {"natural": "peril, abyss, hidden danger, fear, depth, uncertainty"}}}
    legal = {
        "edict": {"action": "No Return Edict", "economy": "ACTION", "targets": ["foe"],
                  "cost_label": "Action, 10 Resonance, 1 use"},
        "command": {"action": "Command Death servants", "economy": "BONUS_ACTION",
                    "targets": ["self"], "cost_label": "Bonus"},
        "gaze": {"action": "Soul Gaze", "economy": "ACTION", "targets": ["foe"],
                 "cost_label": "Action, 1 Resonance"},
        "seal": {"action": "Mortality Seal", "economy": "ACTION", "targets": ["foe"],
                 "cost_label": "Action, 6 Resonance"},
        "spirit": {"action": "Command Bonded Spirit", "economy": "BONUS_ACTION",
                   "targets": ["self"], "cost_label": "Bonus"},
        "end": {"action": "End turn", "targets": []}}
    return view, legal


def assert_turn_costs(prompt, offered, legal):
    """Check source-menu charges, not the renderer's possibly shortened label."""
    for letter, answer in offered.items():
        line = next(line for line in prompt.splitlines() if line.startswith(letter + ")"))
        for key in answer["plan"]:
            cost = legal[key].get("cost_label")
            if cost:
                assert "(" + cost + ")" in line


@pytest.mark.parametrize("builtin", ["edict", "command"])
@pytest.mark.parametrize("repair", [None, "invalid reply"])
def test_long_complete_plans_reduce_menu_instead_of_failing(builtin, repair):
    view, legal = long_menu()
    options = turn_options(view, legal, builtin, list(legal), limit=3)
    prompt, offered = build_prompt(view, options, "TURN", legal, repair)
    assert len(prompt.encode()) <= 800
    assert 2 <= len(offered) < len(options)
    assert offered["A"] == options[0].answer
    assert list(offered.values())[-1] == {"plan": ["end"]}
    assert_turn_costs(prompt, offered, legal)
    for letter, answer in offered.items():
        option = next(o for o in options if o.answer == answer)
        assert f"{letter}) {option.label}" in prompt


@pytest.mark.parametrize("variant", ["Trip", "Pin"])
def test_long_shared_weapon_prefix_keeps_variant(variant):
    view, legal = long_menu()
    label = "Feathered Celestial Green Gold Cha / Hu Cha +2 attack"
    legal["weapon"] = dict(legal["gaze"], action=label, source="weapon")
    legal["variant"] = dict(legal["weapon"], action=label + ": " + variant, source=variant)
    options = turn_options(view, legal, "variant", ["weapon"], limit=2)
    assert variant in options[0].label
    assert any(o.answer["plan"][0] == "weapon" for o in options)
    assert len({o.label for o in options}) == len(options)


@pytest.mark.parametrize("repair", [None, "invalid reply"])
def test_mandatory_read_script_difficulty_choices_fit(repair):
    view, _ = long_menu()
    legal = {"ability": "Read the Script", "spend_options": [0],
             "trigger": "Read the Script: how hard is this writing to read? The printed rules set no Difficulty Class.",
             "summary": "Make an Intelligence check using Arcana, Investigation, Calligrapher’s Supplies, or another relevant proficiency. On a success, learn one: formula family; approximate rank;",
             "choice": {"minimum": 1, "maximum": 1, "allow_decline": False,
                        "options": [{"id": str(i), "label": "Read the Script: the writing is " + label}
                                    for i, label in enumerate([
                                        "clear and deliberate (DC 10)", "worn or smudged (DC 10)",
                                        "hidden, damaged or foreign (DC 15)", "sealed or warded (DC 20)"])]}}
    builtin = {"selection": "USE", "spend": 0, "option_ids": ["1"]}
    options = reaction_options(legal, builtin)
    prompt, offered = build_prompt(view, options, "REACTION", legal, repair)
    assert len(prompt.encode()) <= 800
    assert 2 <= len(offered) < 4
    assert offered["A"] == builtin
    assert all(o["selection"] == "USE" for o in offered.values())
    assert legal["summary"] in prompt
    for letter, answer in offered.items():
        line = next(line for line in prompt.splitlines() if line.startswith(letter + ")"))
        assert legal["choice"]["options"][int(answer["option_ids"][0])]["label"].split(": ", 1)[1] in line


@pytest.mark.parametrize("builtin", ["edict", "command"])
@pytest.mark.parametrize("repair", [False, True])
def test_long_choices_dispatch_through_runner_without_fallback(tmp_path, builtin, repair):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    calls = []
    def provider(config, prompt, png):
        calls.append(prompt)
        assert len(prompt.encode()) <= 800
        return ("not a letter" if repair and len(calls) == 1 else "A"), None
    runner, _ = runner_for(tmp_path, table, provider)
    configure(runner)
    view, legal = long_menu()
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal,
                            builtin, "", "TURN", list(legal))
    assert not answer["fallback"]
    assert answer["plan"][0] == builtin
    assert len(calls) == 1 + repair
    options = turn_options(view, legal, builtin, list(legal), limit=3)
    assert answer["plan"] == options[0].answer["plan"]
    for i, prompt in enumerate(calls):
        expected, offered = build_prompt(view, options, "TURN", legal,
                                         "invalid reply" if i else None)
        assert prompt == expected
        assert_turn_costs(prompt, offered, legal)
    decision = runner.decisions(mid)[0]
    assert decision["attempts"] == 1 + repair
    assert decision["invalid_replies"] == int(repair)


@pytest.mark.parametrize("repair", [None, "invalid reply"])
def test_each_step_keeps_long_cost_and_essential_situation(repair):
    view, legal = long_menu()
    # Two charged steps, including non-ASCII text to exercise the byte ceiling.
    legal["command"]["cost_label"] = "Bonus Action, 2 Resonance, 1 servant command use"
    legal["edict"]["cost_label"] = ("Action, 10 Resonance, 1 use, " + "1 jade seal • " * 22).rstrip()
    options = turn_options(view, legal, "edict", list(legal), limit=3)
    prompt, offered = build_prompt(view, options, "TURN", legal, repair)
    assert len(prompt.encode()) <= 800
    assert offered["A"] == {"plan": ["edict", "command", "end"]}
    assert list(offered.values())[-1] == {"plan": ["end"]}
    assert_turn_costs(prompt, offered, legal)
    assert "HP: 55/55" in prompt and "(2,5)" in prompt
    assert "Threat: Enemy fighter at (17,5)" in prompt
    assert "Ally: Corpse Servant 1 at (2,5)" in prompt
    assert " — " not in prompt


@pytest.mark.parametrize("repair", [None, "invalid reply"])
def test_compact_turn_frame_keeps_turn_ending_consequence(repair):
    view, legal = long_menu()
    legal["command"]["cost_label"] = "Bonus Action, 2 Resonance, 1 servant command use"
    legal["edict"]["cost_label"] = ("Action, 10 Resonance, 1 use, " + "1 jade seal • " * 22).rstrip()
    options = turn_options(view, legal, "edict", list(legal), limit=3)
    prompt, offered = build_prompt(view, options, "TURN", legal, repair)
    assert prompt.startswith("Reply "), "Fixture must exercise the compact frame"
    assert "Plans end your turn." in prompt
    assert len(prompt.encode()) <= 800
    assert "Dao:" in prompt and "Situation:" in prompt
    assert "HP: 55/55" in prompt and "Threat: Enemy fighter" in prompt
    assert offered["A"] == {"plan": ["edict", "command", "end"]}
    assert_turn_costs(prompt, offered, legal)


@pytest.mark.parametrize("repair", [None, "invalid reply"])
def test_required_turn_cost_overflow_is_not_silently_shortened(repair):
    view, legal = long_menu()
    legal["edict"]["cost_label"] = "Action, " + "1 charged use, " * 80
    options = turn_options(view, legal, "edict", list(legal), limit=3)
    with pytest.raises(ValueError, match="mandatory frame exceeds prompt budget"):
        build_prompt(view, options, "TURN", legal, repair)


def test_required_turn_cost_overflow_falls_back_without_model_dispatch(tmp_path):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    calls = []
    def provider(config, prompt, png):
        calls.append(prompt)
        return "B", None
    runner, _ = runner_for(tmp_path, table, provider)
    configure(runner)
    view, legal = long_menu()
    legal["edict"]["cost_label"] = "Action, " + "1 charged use, " * 80
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal,
                            "edict", "", "TURN", list(legal))
    assert answer == {"plan": ["edict"], "fallback": True}
    assert calls == []
    assert runner.decisions(mid)[0]["attempts"] == 0


@pytest.mark.parametrize("repair", [None, "invalid reply"])
def test_reactive_mount_cover_preserves_builtin_decline(repair):
    view, _ = long_menu()
    legal = {"ability": "Meat Shield", "spend_options": [0], "affected": "Death fighter",
             "trigger": "Meat Shield: put Warhorse between Death fighter and Enemy fighter's Deliver the Dose + Bitter Trace?",
             "summary": "Choose one edge for your mount to cover. It gives you Total Cover: attacks crossing that edge cannot target you. This triggering attack targets your mount instead. Your mount remains targetable normally.",
             "choice": {"minimum": 1, "maximum": 1, "allow_decline": True,
                        "options": [{"id": edge, "label": f"Reactive Cover: the {edge} edge (1 Martial Focus and your Reaction)",
                                     "description": f"Your mount blocks attacks crossing the {edge} edge of your space until Meat Shield ends."}
                                    for edge in ("north", "east", "south", "west")]}}
    builtin = {"selection": "DECLINE", "spend": 0, "option_ids": []}
    options = reaction_options(legal, builtin)
    prompt, offered = build_prompt(view, options, "REACTION", legal, repair)
    assert len(prompt.encode()) <= 800
    assert 2 <= len(offered) < 4
    assert offered["A"] == builtin
    assert any(o["selection"] == "USE" for o in offered.values())
    assert "Meat Shield" in prompt and "Warhorse" in prompt and "Death fighter" in prompt
    assert "Deliver the Dose + Bitter Trace" in prompt
    assert legal["summary"] in prompt
    for letter, answer in offered.items():
        if answer["selection"] == "USE":
            line = next(line for line in prompt.splitlines() if line.startswith(letter + ")"))
            assert "1 Martial Focus and your Reaction" in line
            assert f"the {answer['option_ids'][0]} edge" in line
            assert "Your mount blocks attacks" in line and "until Meat Shield ends" in line


@pytest.mark.parametrize("repair", [None, "invalid reply"])
def test_hidden_writing_builtin_keeps_dc_15(repair):
    view, _ = long_menu()
    legal = {"ability": "Read the Script", "spend_options": [0],
             "choice": {"minimum": 1, "maximum": 1, "allow_decline": False,
                        "options": [{"id": "hidden", "label": "Read the Script: the writing is hidden, damaged or foreign (DC 15)"},
                                    {"id": "clear", "label": "Read the Script: the writing is clear and deliberate (DC 10)"}]}}
    builtin = {"selection": "USE", "spend": 0, "option_ids": ["hidden"]}
    prompt, offered = build_prompt(view, reaction_options(legal, builtin), "REACTION", legal, repair)
    assert len(prompt.encode()) <= 800 and offered["A"] == builtin
    assert "hidden, damaged or foreign (DC 15)" in prompt
    assert "clear and deliberate (DC 10)" in prompt


def test_menu_reduction_does_not_accept_an_unoffered_letter():
    view, legal = long_menu()
    options = turn_options(view, legal, "edict", list(legal), limit=3)
    _, offered = build_prompt(view, options, "TURN", legal)
    with pytest.raises(ValueError):
        parse_letter(chr(65 + len(offered)), offered)
