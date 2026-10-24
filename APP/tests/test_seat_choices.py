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


@pytest.mark.parametrize("enabled", [True, False])
def test_explicit_slot_ranking_bounds_full_model_prompt_and_flag_off_preserves_menu(tmp_path, monkeypatch, enabled):
    import agent_seats.runner as module
    monkeypatch.setenv("CF_EMBED_MENU", "1" if enabled else "0")
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, _ = runner_for(tmp_path, table, lambda *args: (json.dumps({"plan": ["hit", "end"]}), None), timeout=10)
    configure(runner, "full")
    view, legal = large_fight()
    move = next(key for key, row in legal.items() if row["action"] == "Move")
    seen = []
    original = module.build_prompt
    def capture(view, menu, *args, **kwargs):
        seen.append(set(menu))
        return original(view, menu, *args, **kwargs)
    monkeypatch.setattr(module, "build_prompt", capture)
    runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal, "hit", "", "TURN",
                   ["hit", move], slot_ranked=True)
    assert seen and seen[0] == ({"hit", move, "end"} if enabled else set(legal))


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


@pytest.mark.parametrize("d1", [False, True])
def test_ranked_browse_final_page_back_and_select_first_step(tmp_path, d1):
    from agent_seats.choices import decision_payload
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    view, original = large_fight()
    legal = {"hit": original["hit"], "middle": dict(original["hit"], action="Dodge"),
             "last": dict(original["hit"], action="Last option"), "end": original["end"]}
    replies = iter(["L", "L", "J", "J", "B", "A"])
    prompts = []
    def model(config, prompt, png):
        prompts.append(prompt)
        assert len(prompt.encode()) <= PROMPT_BYTES
        reply = next(replies)
        assert reply in decision_payload(prompt)["options"]
        return reply, None
    runner, _ = runner_for(tmp_path, table, model, timeout=30)
    configure(runner)
    if d1:
        providers = runner.registry.load()
        providers["fake"] = dict(providers["fake"], kind="d1")
        runner.registry.load = lambda: providers
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal, "hit", "", "TURN",
                            ["hit", "middle", "last"], slot_ranked=True)
    assert answer == {"plan": ["hit", "end"], "fallback": False}, runner.decisions(mid)[-1]
    assert "B) Last option" in prompts[2] and "L)" not in prompts[2]
    assert "B) Attack" in prompts[4] and "Plan so far:" not in prompts[4]
    assert runner.decisions(mid)[-1]["invalid_replies"] == 0


def test_ranked_sparse_first_page_keeps_all_options_and_can_revisit():
    from agent_seats.menu_pages import RankedPages
    _, original = large_fight()
    legal = {"hit": original["hit"], **{str(i): dict(original["hit"], action=f"Option {i}") for i in range(7)},
             "end": original["end"]}
    pages = RankedPages(legal, ["hit"], "hit", 3)
    visited = [set(pages.menu())]
    while pages.has_more(set(pages.menu())):
        pages.advance(set(pages.menu()))
        visited.append(set(pages.menu()))
    assert set.union(*visited) == set(legal)
    for expected in reversed(visited[:-1]):
        pages.back()
        assert set(pages.menu()) == expected
    pages.back()
    assert set(pages.menu()) == visited[0]


def test_ranked_turn_situation_and_complete_option_facts_are_retrievable(tmp_path):
    from agent_seats.choices import decision_payload, step_label, perceived_names
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    view, original = large_fight()
    own, foe, ally = view["actors"]
    own.update(team_id="blue", position={"x": 7, "y": 8, "z": 3},
               movement_remaining_ft=25, action_available=True, bonus_action_available=False)
    foe.update(team_id="red", position={"x": 10, "y": 11, "z": 2})
    ally.update(team_id="blue", position={"x": 2, "y": 4, "z": 1})
    view["last_seen"] = [{"display_name": "Hidden secret", "position": {"x": 91, "y": 92}}]
    huge = dict(original["hit"], action="Variant " + "many variants é " * 80,
                targets=["near", "far"], cost_label="Costs exactly 13 Stamina",
                description="Complete printed effect.")
    legal = {"hit": huge, "end": original["end"]}
    prompts, situation, details = [], [], []
    phase = ["situation"]
    def model(config, prompt, png):
        prompts.append(prompt)
        assert len(prompt.encode()) <= PROMPT_BYTES
        assert "Hidden secret" not in prompt and "private-secret" not in prompt
        assert "(7,8), 15 ft" in prompts[0]
        if phase[0] == "situation":
            # Join only the observation chunks, excluding repeated controls
            # and headers between UTF-8 pages.
            facts = prompt.split("· Resources: ", 1)[1].split("\n", 1)[1]
            situation.append(facts.split("\nI) ", 1)[0].split("\nA) ", 1)[0])
            if "Ally: Distant foe at (2,4), 5 ft" not in "".join(situation):
                return "I", None
            phase[0] = "details"
        if phase[0] == "details":
            detail = prompt.split("\nB) ", 1)[1].splitlines()[0].split("full rules]: ", 1)[1]
            details.append(detail.split(" [display shortened;")[0])
            if "Complete printed effect." not in "".join(details):
                return "K", None
            phase[0] = "select"
            return "B", None
        return "A", None
    runner, _ = runner_for(tmp_path, table, model, timeout=30)
    configure(runner)
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal, "hit", "", "TURN", ["hit"], slot_ranked=True)
    assert answer == {"plan": ["hit", "end"], "fallback": False}, runner.decisions(mid)[-1]
    facts = "".join(situation)
    assert "Threat: Nearby foe at (10,11), 10 ft" in facts
    assert "Movement remaining: 25 ft; Action available: True; Bonus action available: False" in facts
    full = "".join(details)
    assert step_label(huge, perceived_names(view)) + ": Complete printed effect." == full


@pytest.mark.parametrize("profile", ["full", "compact", "tiny", "choices"])
def test_ranked_model_more_can_select_tail_without_acting_or_losing_legal_keys(tmp_path, profile):
    import re
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    view, original = large_fight()
    moves = [key for key in original if key.startswith("move")][:8]
    legal = {key: original[key] for key in ["hit", *moves, "end"]}
    legal["rare"] = dict(legal["hit"], action="Rare option")
    before = deepcopy(legal)
    calls = []
    def model(config, prompt, png):
        calls.append(prompt)
        if profile == "choices":
            if "Plan so far: Rare option" in prompt:
                return "A", None
            found = re.search(r"^([A-K])\) Rare option", prompt, re.M)
            return (found[1] if found else "L"), None
        frame = json.loads(prompt.split("\n", 1)[1])
        assert len(frame["legal_menu"]) <= 5
        return (json.dumps({"plan": ["rare", "end"]}) if "rare" in frame["legal_menu"] else "MORE"), None
    runner, _ = runner_for(tmp_path, table, model, timeout=10, render_png=lambda view: None)
    configure(runner, profile)
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal, "hit", "", "TURN",
                            ["hit", moves[0]], slot_ranked=True)
    assert answer == {"plan": ["rare", "end"], "fallback": False}, runner.decisions(mid)[-1]
    assert len(calls) > 2 and legal == before
    assert runner.decisions(mid)[0]["invalid_replies"] == 0
    if profile == "choices":
        assert all(len(prompt.encode()) <= PROMPT_BYTES for prompt in calls)


@pytest.mark.parametrize("steps", [("Move", "Dodge"), ("Dodge", "Gather Current")])
def test_ranked_staged_plans_execute_across_pages_and_reload(tmp_path, monkeypatch, steps):
    import re
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    chosen, prompts = [], []
    def model(config, prompt, png):
        prompts.append(prompt)
        assert len(prompt.encode()) <= PROMPT_BYTES
        if len(chosen) == 2:
            return "A", None
        label = re.search(r"^B\) (.+)", prompt, re.M)
        if label and label[1].startswith(steps[len(chosen)]):
            chosen.append(steps[len(chosen)])
            return "B", None
        assert "L) More" in prompt
        return "L", None
    runner, _ = runner_for(tmp_path, table, model, timeout=30)
    configure(runner)
    combat.controller = LocalDeterministicController()
    state = raw_state(runner, mid)
    table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"], [])
    def rank(mid, session, known, options, cells, ranked_keys, scores, **kwargs):
        keys = []
        for action in steps:
            matches = [k for k, row in options.items() if row["description"]["action"].split(":", 1)[0] == action]
            assert matches, action
            keys.append(matches[0])
        ranked_keys[:] = keys
        return keys[0], "offline test ordering"
    monkeypatch.setattr(runner, "_builtin", rank)
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    assert runner.drive(mid, max_steps=2) == 2
    row = next(row for row in runner.decisions(mid) if row["kind"] == "TURN")
    assert not row["fallback"], row
    assert [option["action"].split(":", 1)[0] for option in row["chosen_menu"]] == [*steps, "End turn"]
    assert any("Plan so far:" in prompt and "L) More" in prompt for prompt in prompts)
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    session = reopened.combat._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
    actor = session.engine.state.actors[PLAYER]
    assert not actor.action_available
    if steps[0] == "Move":
        assert (actor.position.x, actor.position.y) != (3, 6)
    else:
        assert not actor.bonus_action_available


@pytest.mark.parametrize("huge_first", [True, False])
@pytest.mark.parametrize("profile", ["choices", "full", "compact", "tiny"])
def test_ranked_huge_option_rules_and_tail_remain_reachable(tmp_path, huge_first, profile):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    view, original = large_fight()
    huge = dict(original["hit"], action="Huge power", description="Long printed mechanics. " * 300 + "FINAL RULE.")
    legal = {"hit": huge if huge_first else original["hit"], "huge": huge,
             "rare": dict(original["hit"], action="Rare option"), "end": original["end"]}
    prompts, reading = [], [False]
    def model(config, prompt, png):
        prompts.append(prompt)
        if profile != "choices":
            frame = json.loads(prompt.split("\n", 1)[1])
            menu = frame["legal_menu"]
            if 'Steps already chosen: ["rare"]' in prompt:
                return json.dumps({"plan": ["end"]}), None
            huge_key = next((key for key, row in menu.items() if row.get("action") == "Huge power"), None)
            if huge_key and "FINAL RULE." not in prompt:
                return "DETAILS " + huge_key, None
            if "rare" in menu:
                return json.dumps({"plan": ["rare", "end"]}), None
            return "MORE", None
        assert len(prompt.encode()) <= PROMPT_BYTES
        if "Plan so far: Rare option" in prompt:
            return "A", None
        if "B) Huge power" in prompt and not reading[0]:
            reading[0] = True
            return "K", None
        if "B) Huge power" in prompt and reading[0] and "FINAL RULE." not in prompt:
            return "K", None
        if "B) Rare option" in prompt:
            return "B", None
        return "L", None
    runner, _ = runner_for(tmp_path, table, model, timeout=30, render_png=lambda view: None)
    configure(runner, profile)
    config = json.loads(runner.registry.path.read_text())
    config["providers"][0]["max_options"] = 3
    runner.registry.path.write_text(json.dumps(config))
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal, "hit", "", "TURN",
                            ["hit", "huge", "rare"], slot_ranked=True)
    assert answer == {"plan": ["rare", "end"], "fallback": False}, runner.decisions(mid)[-1]
    assert any("display shortened" in prompt and ("L) More" if profile == "choices" else "Reply MORE") in prompt for prompt in prompts)
    assert any("FINAL RULE." in prompt for prompt in prompts)
    assert len(legal["huge"]["description"]) > 6000


@pytest.mark.parametrize("profile", ["full", "compact", "tiny"])
def test_ranked_json_profiles_compose_steps_from_different_pages(tmp_path, profile):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    view, original = large_fight()
    legal = {"hit": original["hit"], "rare": dict(original["hit"], action="Recover", economy="BONUS_ACTION"),
             "end": original["end"]}
    step = [0]
    def model(config, prompt, png):
        menu = json.loads(prompt.split("\n", 1)[1])["legal_menu"]
        wanted = ["hit", "rare", "end"][step[0]]
        if wanted not in menu:
            return "MORE", None
        step[0] += 1
        return json.dumps({"plan": [wanted]}), None
    runner, _ = runner_for(tmp_path, table, model, timeout=30, render_png=lambda view: None)
    configure(runner, profile)
    config = json.loads(runner.registry.path.read_text())
    config["providers"][0]["max_options"] = 3  # one active row per page
    runner.registry.path.write_text(json.dumps(config))
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal, "hit", "", "TURN",
                            ["hit", "rare"], slot_ranked=True)
    assert answer == {"plan": ["hit", "rare", "end"], "fallback": False}, runner.decisions(mid)[-1]


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
        return ("invalid" if len(prompts) == 1 else "Option A" if "Plan so far:" in prompt else "Option B"), None
    runner, _ = runner_for(tmp_path, table, model, timeout=10)
    configure(runner)
    state = raw_state(runner, mid)
    table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"], [])
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    assert runner.drive(mid, max_steps=3) >= 2
    row = runner.decisions(mid)[0]
    # Repair, select an active step, then explicitly finish the staged plan.
    assert not row["fallback"] and row["attempts"] == 3 and row["invalid_replies"] == 1
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
            from agent_seats.providers import choices_settings
            budget, maximum = choices_settings(runner.registry.load()["fake"])
            offered = build_prompt(view, turn_options(view, legal, builtin, ranked, limit=3,
                choices_bytes=budget, max_options=maximum), kind, legal, "bad", budget, maximum)[1]
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
