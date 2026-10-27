"""Real Factory menus and persisted target choices; no GUI or inference."""
import json
import re

import pytest

from agent_seats import choices
from combat.factory_compiler import compile_character
from combat.gate4_controller import LocalDeterministicController
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_agent_seats import runner_for, raw_state
from tests.test_seat_choices import configure

ME, LEFT, RIGHT = "actor:factory.dao", "actor:factory.guard1", "actor:factory.guard2"


def real_fight(tmp_path, *, attack_line=False):
    mids = ["AIR_BASE_GATHER_CURRENT", "tianxia.path.body_refining.feature.extra_attack"]
    if attack_line:
        mids += ["tianxia.subpath.body.still_water_draw_body.feature.drawn_from_stillness",
                 "tianxia.subpath.body.still_water_draw_body.feature.one_breath_three_horizons"]
    docs = [sheet(mids, cl=18, primary="Stamina", kit={"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}]}}),
            sheet([], cl=18), sheet([], cl=18)]
    docs[0]["path_and_subpath"]["path_record_ids"] = ["tianxia.path.body_refining"]
    bundles = [compile_character(d, actor_id=a, reaction_plan={"ask": True})
               for d, a in zip(docs, (ME, LEFT, RIGHT))]
    for bundle, name in zip(bundles, ("Air fighter", "Guard", "Guard")):
        bundle["actor_template"]["display_name"] = name
    combat = CombatService(ROOT, tmp_path)
    combat.controller = LocalDeterministicController()
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, [ME, LEFT, RIGHT],
        {ME: "team:factory", LEFT: "team:opponents", RIGHT: "team:opponents"},
        {ME: {"x": 3, "y": 6}, LEFT: {"x": 4, "y": 6}, RIGHT: {"x": 3, "y": 7}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [LEFT, RIGHT],
        control_modes={a: "MANUAL" for a in (ME, LEFT, RIGHT)}, match_seed="DAO-R1",
        display_name="Seat target regression", maximum_rounds=10)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != ME:
        state = table.state(mid); menu = state["menu"]
        table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"], [])
    return combat, table, mid


def menu_frame(runner, combat, mid):
    state = raw_state(runner, mid)
    view, known = runner.own_view(mid, state, ME, combat._load_session(mid))
    menu = runner._menu(state, known)
    legal = {k: v["description"] for k, v in menu.items()}
    return view, legal


@pytest.mark.parametrize("repair", [None, "invalid"])
def test_real_menu_has_distinct_ordered_plans_and_complete_prose(tmp_path, repair):
    combat, table, mid = real_fight(tmp_path)
    runner, _ = runner_for(tmp_path, table)
    view, legal = menu_frame(runner, combat, mid)
    primary = next(k for k, v in legal.items() if v.get("economy") in {"Action", "ACTION"}
                   and v.get("targets") == [LEFT])
    bonus = next(k for k, v in legal.items() if v.get("economy") in {"Bonus Action", "BONUS_ACTION"})
    ranked = [primary, bonus, *legal]
    options = choices.turn_options(view, legal, primary, ranked)
    signatures = [tuple(o.answer["plan"]) for o in options]
    assert len(set(signatures)) == len(signatures)
    prompt, offered = choices.build_prompt(view, options, "TURN", legal, repair)
    assert len(prompt.encode()) <= 800 and "Dao:" in prompt
    lines = [line for line in prompt.splitlines() if re.match(r"[A-F]\)", line)]
    assert all("…" not in line and "take the named action" not in line for line in lines)
    assert len(offered) >= 2
    assert "HP:" in prompt and "at (3,6)" in prompt
    assert "Threat: Guard at (4,6)" in prompt and "Threat: Guard at (3,7)" in prompt
    for letter, answer in offered.items():
        assert choices.parse_letter(letter, offered) == answer


@pytest.mark.parametrize("repair", [None, "invalid"])
def test_real_menu_prose_keeps_complete_mechanics(tmp_path, repair):
    combat, table, mid = real_fight(tmp_path)
    runner, _ = runner_for(tmp_path, table)
    view, legal = menu_frame(runner, combat, mid)
    primary = next(k for k, v in legal.items() if v["action"] == "Wind Lash: Pull" and v["targets"] == [LEFT])
    options = choices.turn_options(view, legal, primary, list(legal))
    prompt, offered = choices.build_prompt(view, options, "TURN", legal, repair)
    assert len(prompt.encode()) <= 800 and "Dao:" in prompt
    assert "…" not in prompt.split("Situation:\n", 1)[1]
    # This is a source-to-prompt preservation check, not a wording contract.
    # Bind both complete clauses to the printed record, including on the public
    # copy where the same source prose is deterministically transformed.
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    wind_lash = rules["AIR_BASE_WIND_LASH"].splitlines()
    scaling = wind_lash[7]
    pull = wind_lash[10].split(": ", 1)[1]
    assert scaling and scaling in prompt
    assert pull and pull in prompt
    assert "AIR_BASE_WIND_LASH" in legal[primary]["source"]
    assert offered["A"]["plan"][0] == primary


def test_equal_label_reactions_remain_mechanically_distinct():
    legal = {"choice": {"minimum": 1, "maximum": 1, "allow_decline": True,
             "options": [{"id": "one", "label": "Guard"}, {"id": "two", "label": "Guard"}]}}
    options = choices.reaction_options(legal, {"selection": "USE", "option_ids": ["one"], "spend": 0})
    assert {tuple(o.answer["option_ids"]) for o in options} == {("one",), ("two",), ()}


def test_unrecognized_selected_mode_keeps_all_source_text():
    description = "Choose a mode. Guard: Reduce damage by 2. Strike: Deal 3 damage."
    legal = {mode: {"action": "Technique: " + mode, "description": description}
             for mode in ("Guard", "Strike", "Advanced Guard")}
    assert choices.option_description(legal["Advanced Guard"], legal) == description


def test_same_named_targets_seat_commit_reload(tmp_path):
    combat, table, mid = real_fight(tmp_path, attack_line=True)
    state = table.state(mid); menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"].startswith("One Breath, Three Horizons"))
    cid = next(o["candidate_id"] for o in group["options"] if o.get("destination") == {"x": 8, "y": 6})
    answers = []
    def send():
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
    result = send()
    while result["status"] == "REACTION_REQUIRED" and result["reaction"]["context"]["reaction_source_id"] != "choice:needle.attack_line_attack":
        prompt = result["reaction"]; choice = prompt.get("choice") or {}
        decline = choice.get("allow_decline", True)
        answers.append({**prompt["context"], "selection": "DECLINE" if decline else "USE",
                        "option_ids": [] if decline else [choice["options"][0]["id"]], "spend": 0})
        result = send()
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["context"]["reaction_source_id"] == "choice:needle.attack_line_attack"
    prompts = []
    def provider(config, prompt, png):
        prompts.append(prompt)
        if "Attack whom?" in prompt:
            assert "Guard (at 4,6)" in prompt and "Guard (at 3,7)" in prompt
            return next(line[0] for line in prompt.splitlines() if ") Use: Guard (at 3,7)" in line), None
        return next(line[0] for line in prompt.splitlines() if ") Pass;" in line), None
    runner, _ = runner_for(tmp_path, table, provider, timeout=10)
    configure(runner)
    runner.set_seat(mid, ME, "MODEL", "fake")
    steps = 0
    while raw_state(runner, mid).get("pending_action"):
        assert steps < 8
        assert runner.drive(mid, max_steps=1) == 1
        steps += 1
    assert prompts and all(len(p.encode()) <= 800 and "Dao:" in p for p in prompts)
    records = runner.decisions(mid)
    assert all(not r["fallback"] for r in records)
    assert all("dao_policy_top2" in r for r in records)
    assert all(r["dao_policy_top2"][0] == r["built_in_pick"] and
               r["dao_policy_top2"][1]["selection"] == "DECLINE" for r in records)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    attacks = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME]
    assert attacks and all(e.target_ids == (RIGHT,) for e in attacks)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
