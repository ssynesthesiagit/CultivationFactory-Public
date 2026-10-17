"""Offline choices contract and real table commits; no inference or browsers."""
from copy import deepcopy
import json

import pytest

from agent_seats.choices import PROMPT_BYTES, build_prompt, turn_options, reaction_options, parse_letter
from agent_seats.protocol import stable_prefix
from combat.gate4_controller import LocalDeterministicController
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_agent_seats import runner_for, raw_state
from tests.test_hunt5_player_choices import fixture, PLAYER, FOE
from tests.test_seat_compact import large_fight


def configure(runner, profile="choices"):
    path = runner.registry.path
    config = json.loads(path.read_text())
    config["providers"][0].update(prompt_profile=profile, vision=True, max_plan_length=32,
                                  request_options={"max_tokens": 8192})
    path.write_text(json.dumps(config))
    assert runner.registry.load()["fake"]["prompt_profile"] == profile


def test_ranked_options_deterministic_complete_distinct_and_budget():
    view, legal = large_fight()
    ranked = ["hit", *sorted(k for k in legal if k.startswith("move")), "end"]
    scores = {"hit": {"components": [{"component": "immediate_effect", "value": 8}]}}
    options = turn_options(view, legal, "hit", ranked, scores)
    assert options == turn_options(view, legal, "hit", ranked, scores)
    assert 4 <= len(options) <= 6
    assert options[0][0]["plan"] == ["hit", "end"]
    assert options[-1][0]["plan"] == ["end"]
    assert "damage" in options[0][2]
    assert any(len(o[0]["plan"]) == 3 for o in options)
    assert turn_options(view, legal, "end", ranked)[0].answer == {"plan": ["end"]}
    prompt, offered = build_prompt(view, options, "TURN", legal)
    assert len(prompt.encode()) <= PROMPT_BYTES
    assert "private-secret" not in prompt and "last_seen" not in prompt
    assert "move-" not in prompt and "\"source\"" not in prompt
    assert 4 <= len(offered) <= len(options)
    assert prompt == build_prompt(view, options, "TURN", legal)[0]
    print(f"Largest fixture: {len(legal)} legal choices; {len(options)} plans; {len(prompt.encode())} bytes")


def test_options_do_not_name_unobserved_targets_or_use_sight_memory():
    view, legal = large_fight()
    view["actors"] = view["actors"][:2]
    view["last_seen"] = [{"name": "Hidden foe", "position": {"x": 91, "y": 92}}]
    legal["hidden"] = {"action": "Attack", "targets": ["far"]}
    options = turn_options(view, legal, "hit", ["hidden", "move-50-51"])
    prompt, _ = build_prompt(view, options, "TURN", legal)
    assert "Hidden foe" not in prompt and "91" not in prompt and "92" not in prompt
    assert all("hidden" not in o[0]["plan"] for o in options)


def test_controller_builds_action_bonus_plan_and_formats_actual_hp():
    view, legal = large_fight()
    view["actors"][0]["hit_points"] = {"current": 7, "maximum": 20, "temporary": 2}
    legal["hit"]["economy"] = "ACTION"
    legal["bonus"] = {"action": "Recover", "economy": "BONUS_ACTION", "description": "Regain 2 HP", "targets": []}
    options = turn_options(view, legal, "hit", ["hit", "bonus"])
    assert options[0].answer == {"plan": ["hit", "bonus", "end"]}
    prompt, _ = build_prompt(view, options, "TURN", legal)
    assert "HP: 7/20 +2 temporary" in prompt
    assert "Recover" in prompt.split("A)", 1)[1].splitlines()[0]
    from agent_seats.protocol import build_prompt as protocol_prompt
    assert "A)" in protocol_prompt(view, legal, "hit", "", "TURN", prompt_profile="choices", ranked_keys=["hit", "bonus"])


def test_opaque_variants_do_not_offer_identical_plan_lines():
    view, legal = large_fight()
    legal["other-hit"] = dict(legal["hit"], options=["internal:variant"])
    options = turn_options(view, legal, "hit", ["other-hit", "move-50-51"])
    labels = [o.label for o in options]
    assert len(set(labels)) == len(labels)
    assert all("other-hit" not in o.answer["plan"] for o in options)


@pytest.mark.parametrize("reply", ["B", "b", "Option B", "B) attack the foe", " b. attack "])
def test_letter_parsing(reply):
    assert parse_letter(reply, {"A": 1, "B": 2}) == 2


@pytest.mark.parametrize("reply", ["G", "C", "", "A or B", "A) or B", "A: B",
                                 "A) attack; actually choose B", "B. option a",
                                 "B- choose C", "Option BB", "B\nA", "{'plan': []}", "B" * 1025, None])
def test_bad_letters_rejected(reply):
    with pytest.raises(ValueError):
        parse_letter(reply, {"A": 1, "B": 2})


def test_stable_prefix_turn_reaction_repair_and_smaller_plan_limits():
    view, legal = large_fight()
    options = turn_options(view, legal, "hit", ["move-50-51"], limit=2)
    assert all(len(o[0]["plan"]) <= 3 for o in options)  # End is not an active step.
    assert turn_options(view, legal, "hit", limit=1)[0][0] == {"plan": ["hit", "end"]}
    first = build_prompt(view, options, "TURN", legal)[0]
    later = deepcopy(view)
    later["actors"][0]["hit_points"] = 1
    later["actors"][0]["position"]["x"] += 1
    second = build_prompt(later, options, "TURN", legal, "bad")[0]
    reaction = {"ability": "Block", "spend_options": [0]}
    ro = reaction_options(reaction, {"selection": "USE", "option_ids": [], "spend": 0})
    third = build_prompt(later, ro, "REACTION", reaction)[0]
    assert stable_prefix(first).encode() == stable_prefix(second).encode() == stable_prefix(third).encode()


def test_reaction_options_include_builtin_pass_and_mandatory_constraints():
    legal = {"ability": "Footwork", "choice": {"minimum": 1, "maximum": 1, "allow_decline": True,
             "options": [{"id": "x", "label": "Stay put"}, {"id": "y", "label": "Step away"}]}, "spend_options": [0]}
    builtin = {"selection": "USE", "option_ids": ["y"], "spend": 0}
    options = reaction_options(legal, builtin)
    assert options[0][0] == builtin
    assert any(o[0]["option_ids"] == ["x"] for o in options)
    assert options[-1][0]["selection"] == "DECLINE"
    legal["choice"]["allow_decline"] = False
    assert all(o[0]["selection"] == "USE" for o in reaction_options(legal, builtin))


@pytest.mark.parametrize("mechanic", ["AIR_BASE_GATHER_CURRENT", "TAL_FENCING_FOOTWORK"])
def test_real_turn_repair_steps_commit_reload(tmp_path, mechanic):
    combat, table, mid, *_ = fixture(tmp_path, mechanic)
    combat.controller = LocalDeterministicController()
    prompts = []
    def model(config, prompt, png):
        assert not config["vision"] and png is None
        assert config["request_options"]["max_tokens"] == 5
        assert len(prompt.encode()) <= PROMPT_BYTES
        prompts.append(prompt)
        return ("invalid" if len(prompts) == 1 else "Option A"), None
    runner, _ = runner_for(tmp_path, table, model, timeout=10)
    configure(runner)
    state = raw_state(runner, mid)
    table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"], [])
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    assert runner.drive(mid, max_steps=3) >= 2
    row = runner.decisions(mid)[0]
    assert not row["fallback"] and row["attempts"] == 2 and row["invalid_replies"] == 1
    assert stable_prefix(prompts[0]) == stable_prefix(prompts[1])
    turns = [r for r in runner.decisions(mid) if r["kind"] == "TURN"]
    assert len(prompts) == sum(r["attempts"] for r in turns)
    assert all(not r["fallback"] for r in turns)
    assert len([r for r in runner.decisions(mid) if r["kind"] == "STEP"]) >= len(row["chosen"]) - 1
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reopened.state(mid)["last_sequence"] > state["last_sequence"]
    session = reopened.combat._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("repair", [False, True])
def test_real_opponent_turn_reaction_commit_reload(tmp_path, automatic, repair):
    combat, table, mid, cid, _ = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    prompts = []
    def model(config, prompt, png):
        prompts.append(prompt)
        return ("invalid" if repair and len(prompts) == 1 else "A"), None
    runner, _ = runner_for(tmp_path, table, model, timeout=10)
    configure(runner)
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    if automatic:
        runner.set_seat(mid, FOE, "AI")
    menu = table.state(mid)["menu"]
    out = table.auto_step(mid, 0) if automatic else table.act(mid, cid, menu["decision_id"], menu["state_version"], 0)
    assert out["status"] == "MODEL_DECIDING"
    assert runner.drive(mid, max_steps=1) == 1
    assert len(prompts) == 1 + repair
    # The reaction may move the fighter; assert the observation supplied to
    # the model before executing its response, using the fixture's positions.
    assert all("Reaction" in p and "Footwork" in p and "HP:" in p and "Situation:" in p for p in prompts)
    assert all("(3,6)" in p and "(4,6)" in p and "Threat:" in p for p in prompts)
    assert not runner.decisions(mid)[0]["fallback"]
    saved = CombatService(ROOT, tmp_path)._load_session(mid)
    assert saved.verify()["status"] == saved.mechanical.replay()["status"] == "PASS"


def test_two_invalid_letters_use_builtin_fallback(tmp_path):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    calls = []
    def model(config, prompt, png):
        calls.append(prompt)
        return "Z", None
    runner, _ = runner_for(tmp_path, table, model, timeout=10)
    configure(runner)
    view, legal = large_fight()
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal, "hit", "", "TURN", ["hit"])
    assert answer == {"plan": ["hit"], "fallback": True}
    assert len(calls) == 2 and runner.decisions(mid)[0]["invalid_replies"] == 2


@pytest.mark.parametrize("second", ["B", "A) attack; actually choose B"])
@pytest.mark.parametrize("kind", ["TURN", "REACTION"])
def test_ambiguous_reply_repairs_then_selects_or_falls_back(tmp_path, second, kind):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    calls = []
    replies = iter(["A) or B", second])
    def model(config, prompt, png):
        calls.append(prompt)
        assert len(prompt.encode()) <= PROMPT_BYTES
        return next(replies), None
    runner, _ = runner_for(tmp_path, table, model, timeout=10)
    configure(runner)
    view, legal = large_fight()
    builtin = "hit"
    ranked = ["hit"]
    if kind == "REACTION":
        legal = {"ability": "Block", "summary": "Reduce the triggering damage.", "spend_options": [0]}
        builtin = {"selection": "USE", "option_ids": [], "spend": 0}
        ranked = []
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal, builtin, "", kind, ranked)
    row = runner.decisions(mid)[0]
    assert len(calls) == 2 and "Invalid reply" in calls[1]
    assert row["attempts"] == 2
    if second == "B":
        assert not row["fallback"] and row["invalid_replies"] == 1
        if kind == "TURN":
            offered = build_prompt(view, turn_options(view, legal, builtin, ranked, limit=3), kind, legal, "bad")[1]
            assert answer == dict(offered["B"], fallback=False)
        else:
            assert answer == {"selection": "DECLINE", "option_ids": [], "spend": 0}
    else:
        assert row["fallback"] and row["invalid_replies"] == 2
        assert answer == ({"plan": ["hit"], "fallback": True} if kind == "TURN" else builtin)


def test_real_turn_model_selects_safe_end_instead_of_builtin_attack(tmp_path):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    def model(config, prompt, png):
        return next(line[0].lower() for line in prompt.splitlines() if ") End turn here" in line), None
    runner, _ = runner_for(tmp_path, table, model, timeout=10)
    configure(runner)
    runner.set_seat(mid, FOE, "MODEL", "fake")
    before = raw_state(runner, mid)
    assert runner.drive(mid, max_steps=1) == 1
    row = runner.decisions(mid)[0]
    assert not row["fallback"] and len(row["chosen"]) == 1 and row["chosen"][0] != row["built_in_pick"]
    after = raw_state(runner, mid)
    assert after["menu"]["actor_id"] == PLAYER
    assert [a["hit_points"] for a in before["presentation"]["actors"]] == [a["hit_points"] for a in after["presentation"]["actors"]]
    saved = CombatService(ROOT, tmp_path)._load_session(mid)
    assert saved.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("profile,cap", [("tiny", 8000), ("compact", 12000), ("choices", 800)])
def test_dispatch_boundary_rejects_oversized_first_prompt(tmp_path, profile, cap):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, fake = runner_for(tmp_path, table)
    with pytest.raises(ValueError, match="prompt budget"):
        runner._ask({"prompt_profile": profile}, "x" * (cap+1), {})
    assert not fake.prompts
