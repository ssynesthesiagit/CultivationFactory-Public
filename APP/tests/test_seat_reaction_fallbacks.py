"""Public reaction shapes reconstructed from SOL170r5's seven saved decisions.

No private save files, provider calls, or recorded model replies are required.
Identity keys are replaced; rules, offered labels, HP and source actions match
the captured menus. Each case overflowed before provider dispatch on 053a659d.
"""
from copy import deepcopy

import pytest

from agent_seats.choices import build_prompt, reaction_options, parse_letter
from tests.test_agent_seats import runner_for
from tests.test_hunt5_player_choices import fixture, FOE
from tests.test_seat_choices import configure


STEP_SUMMARY = (
    "Take either the Dash action or Disengage action.\n"
    "Stomping Step represents explosive footwork, controlled bodily release, "
    "tendon refinement, practiced breathing, and the ability to place the body "
    "exactly where its force is required.\nIt does not require Stamina."
)
BREATH_SUMMARY = (
    "You may use your breath to stabilize your body.\n"
    "When you make a Strength or Dexterity saving throw against being pushed, "
    "pulled, knocked Prone, or moved by wind, pressure, or forced movement, "
    "you may add your Proficiency Bonus to the roll if you are not already adding it.\n"
    "Once you use this benefit, you cannot use it again until the start of your next turn."
)
# iteration, Agent_Decisions line, name, source ability, preferred option, HP.
RECORDED = [
    (2, 10, "Su Daohui", "Stomping Step", 2, 49),
    (2, 19, "Su Daohui", "Stomping Step + Swaying Step: Fall Prone and Move", 2, 33),
    (2, 28, "Su Daohui", "Stomping Step + Swaying Step: Stand from Prone", 2, 22),
    (3, 11, "Liu Ling", "Breath-Braced Body", 1, 115),
    (3, 25, "Liu Ling", "Stomping Step", 1, 115),
    (5, 4, "Yun Xiao", "Stomping Step", 1, 251),
    (5, 22, "Yun Xiao", "Stomping Step", 1, 251),
]


def recorded_frame(case):
    iteration, line, name, ability, preferred, hp = case
    view = {"fighter": FOE, "actors": [
        {"entity_id": FOE, "display_name": name, "team_id": "self",
         "position": {"x": 8 if iteration == 2 else 2, "y": 2 if iteration == 2 else 5},
         "hit_points": {"current": hp, "maximum": 61 if iteration == 2 else hp,
                        "temporary": 4 if (iteration, line) == (3, 25) else 0}}],
        "dao": {"temperament": {"natural": (
            "subtle entry, gradual influence, persuasion, growth, penetration" if iteration == 3 else
            "receptivity, support, service, bearing, nourishment, humility")}}}
    if ability == "Breath-Braced Body":
        trigger = f"{ability}: STR save against being moved or knocked Prone by Bite affecting {name}. Choose an option."
        summary = BREATH_SUMMARY
        labels = ["Add your Proficiency Bonus (+4) to this STR save (then not again until your next turn)"]
    else:
        trigger = (f"{ability} (Bonus Action): take the Dash action (move up to your Speed again this turn) "
                   "or the Disengage action (moving away doesn't provoke Opportunity Attacks for the rest of this turn)? "
                   f"— {name} uses {ability}.")
        summary = STEP_SUMMARY
        labels = ["Dash: gain extra movement equal to your Speed this turn",
                  "Disengage: your movement doesn't provoke Opportunity Attacks for the rest of this turn"]
    legal = {"ability": ability, "affected": name, "trigger": trigger, "summary": summary,
             "choice": {"minimum": 1, "maximum": 1, "allow_decline": ability == "Breath-Braced Body",
                        "options": [{"id": f"option:{i}", "label": label, "description": ""}
                                    for i, label in enumerate(labels, 1)]}, "spend_options": [0]}
    builtin = {"selection": "USE", "spend": 0, "option_ids": [f"option:{preferred}"]}
    return view, legal, builtin


@pytest.mark.parametrize("case", RECORDED, ids=[f"iteration{c[0]}-line{c[1]}" for c in RECORDED])
@pytest.mark.parametrize("repair", [None, "invalid reply"])
def test_recorded_reaction_frames_keep_complete_content(case, repair):
    view, legal, builtin = recorded_frame(case)
    prompt, offered = build_prompt(view, reaction_options(legal, builtin), "REACTION", legal, repair)
    assert len(prompt.encode()) <= 800
    assert offered["A"] == builtin
    assert len(offered) == 2
    assert legal["ability"] in prompt and legal["affected"] in prompt
    assert " ".join(legal["summary"].split()) in prompt
    for row in legal["choice"]["options"]:
        assert row["label"] in prompt
    if legal["ability"] == "Breath-Braced Body":
        assert "STR save against being moved or knocked Prone by Bite" in prompt
        assert any(a["selection"] == "DECLINE" for a in offered.values())
    else:
        assert "(Bonus Action)" in prompt
        assert "move up to your Speed again this turn" in prompt
        assert "moving away doesn't provoke Opportunity Attacks for the rest of this turn" in prompt
        assert all(a["selection"] == "USE" for a in offered.values())
    for letter, answer in offered.items():
        assert parse_letter(letter, offered) == answer
    with pytest.raises(ValueError):
        parse_letter("A) or B", offered)


@pytest.mark.parametrize("case", RECORDED, ids=[f"iteration{c[0]}-line{c[1]}" for c in RECORDED])
@pytest.mark.parametrize("repair", [False, True])
def test_recorded_reactions_dispatch_and_log_through_runner(tmp_path, case, repair):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    calls = []
    def provider(config, prompt, png):
        calls.append(prompt)
        assert len(prompt.encode()) <= 800
        return ("A) or B" if repair and len(calls) == 1 else "B"), None
    runner, _ = runner_for(tmp_path, table, provider)
    configure(runner)
    view, legal, builtin = recorded_frame(case)
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal, builtin, "", "REACTION")
    assert len(calls) == 1 + repair
    assert answer != builtin
    assert answer in build_prompt(view, reaction_options(legal, builtin), "REACTION", legal)[1].values()
    row = runner.decisions(mid)[-1]
    assert row["fallback"] is None and row["fallback_error"] is None
    assert row["attempts"] == 1 + repair and row["invalid_replies"] == int(repair)


@pytest.mark.parametrize("failure", ["builder", "options", "provider", "parser", "timeout", "registry"])
def test_every_fallback_logs_concrete_cause(tmp_path, failure):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    def provider(config, prompt, png):
        if failure == "provider":
            raise ConnectionError("offline endpoint refused connection")
        if failure == "timeout":
            raise TimeoutError("offline deadline exceeded")
        return "A) or B", None
    runner, _ = runner_for(tmp_path, table, provider)
    configure(runner)
    view, legal, builtin = recorded_frame(RECORDED[0])
    if failure == "builder":
        legal = deepcopy(legal)
        legal["summary"] = "1 Stamina, " * 1000
    if failure == "options":
        builtin = dict(builtin, option_ids=["unoffered"])
    seat = {"provider_id": "missing" if failure == "registry" else "fake"}
    assert runner._decide(mid, FOE, seat, view, legal, builtin, "", "REACTION") == builtin
    row = runner.decisions(mid)[-1]
    expected = {
        "builder": ("prompt", "ValueError", "Choices mandatory frame exceeds prompt budget"),
        "options": ("options", "ValueError", "option_ids must contain unique offered option ids"),
        "provider": ("provider", "ConnectionError", "offline endpoint refused connection"),
        "parser": ("validation", "ValueError", "Reply with one offered letter"),
        "timeout": ("provider", "TimeoutError", "offline deadline exceeded"),
        "registry": ("registry", "KeyError", "'missing'"),
    }
    stage, exception, message = expected[failure]
    assert row["fallback_error"] == {"stage": stage, "exception": exception, "message": message}
    assert row["attempts"] == (0 if failure in {"builder", "options", "registry"} else 2 if failure == "parser" else 1)
    assert row["invalid_replies"] == (2 if failure == "parser" else 0)


def test_failure_detail_is_bounded_and_redacts_provider_key(monkeypatch):
    from agent_seats.runner import failure_detail
    monkeypatch.setenv("TEST_SEAT_TOKEN", "private-token-value")
    detail = failure_detail(ConnectionError("private-token-value\n" + "x" * 1000),
                            "provider", {"key_env": "TEST_SEAT_TOKEN"})
    assert detail["exception"] == "ConnectionError"
    assert detail["stage"] == "provider"
    assert "private-token-value" not in detail["message"]
    assert "[redacted]" in detail["message"]
    assert "\n" not in detail["message"] and len(detail["message"]) <= 240


def test_minimum_frame_factoring_is_generic_and_keeps_unmatched_trigger_text():
    view, legal, builtin = recorded_frame(RECORDED[0])
    legal["trigger"] = legal["trigger"].replace("Stomping Step", "Quick Step")
    legal["ability"] = "Quick Step"
    # An unrelated clause must never be dropped as an activation duplicate.
    legal["trigger"] += " Keep the affected creature in sight."
    prompt, _ = build_prompt(view, reaction_options(legal, builtin), "REACTION", legal)
    assert len(prompt.encode()) <= 800
    assert "Quick Step" in prompt
    assert "— Su Daohui uses Quick Step. Keep the affected creature in sight." in prompt
    assert " ".join(legal["summary"].split()) in prompt
