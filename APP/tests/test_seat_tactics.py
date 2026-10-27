"""Tactical choices are offline and use only the seat's redacted observation."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re

import pytest

from agent_seats.choices import build_prompt, parse_letter, turn_options
from agent_seats.providers import ProviderRegistry, choices_settings
from combat.gate4_controller import LocalDeterministicController
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_agent_seats import raw_state, runner_for
from tests.test_hunt5_player_choices import fixture, PLAYER, FOE
from tests.test_seat_choices import configure


def situation(enemy=True):
    own = {"entity_id": "me", "display_name": "Sun Taitian", "team_id": "ours",
           "position": {"x": 1, "y": 6}, "hit_points": {"current": 109, "maximum": 109}}
    foe = {"entity_id": "foe", "display_name": "Bone Guard", "team_id": "theirs",
           "position": {"x": 4, "y": 6}}
    view = {"fighter": "me", "actors": [own, *([foe] if enemy else [])],
            "dao": {"role": ["Defender"]}, "last_seen": [],
            "visible_cells": [[x, y] for x in range(10) for y in range(10)],
            "map": {"width": 20, "height": 12, "walls": [], "terrain": [],
                    "trees": [{"name": "Tree trunk", "cells": [[3, 5]]}]}}
    legal = {"end": {"action": "End turn", "targets": []},
             "hit": {"action": "Lightning Lash", "targets": ["foe"] if enemy else [],
                     "economy": "ACTION", "description": "Deal 2 Lightning damage.", "cost_label": "Action"},
             "bonus": {"action": "Gather Current", "targets": ["me"],
                       "economy": "BONUS_ACTION", "description": "Gain 1 current until your next turn.", "cost_label": "Bonus Action"}}
    for x in range(8):
        for y in range(3, 9):
            if (x, y) != (1, 6):
                legal[f"move{x}-{y}"] = {"action": "Move", "targets": [], "destination": {"x": x, "y": y}}
    return view, legal


@pytest.mark.parametrize("builtin", ["hit", "end", "move1-3"])
@pytest.mark.parametrize("budget,maximum", [(800, 6), (2400, 10), (2400, 12)])
def test_move_survives_rank_and_budget_even_when_end_is_builtin(builtin, budget, maximum):
    view, legal = situation()
    options = turn_options(view, legal, builtin, ["hit", "bonus", "end"], limit=3,
                           choices_bytes=budget, max_options=maximum)
    for repair in (None, "invalid"):
        prompt, offered = build_prompt(view, options, "TURN", legal, repair,
                                       choices_bytes=budget, max_options=maximum)
        assert len(prompt.encode()) <= budget
        assert any(any(legal[k]["action"] == "Move" for k in a["plan"]) for a in offered.values())
        from agent_seats.tactics import tactical_moves
        tactical_keys = set(dict(tactical_moves(view, legal)))
        assert any(any(k in tactical_keys for k in a["plan"]) for a in offered.values())
        assert {"plan": ["end"]} in offered.values()
        assert "save resources" not in prompt
        assert "End turn here" in prompt
        assert all(len(a["plan"]) <= 4 and a["plan"][-1] == "end" for a in offered.values())


def test_movement_action_bonus_and_after_action_movement_are_distinct_plans():
    view, legal = situation()
    options = turn_options(view, legal, "hit", ["hit", "bonus"], limit=3,
                           choices_bytes=2400, max_options=12)
    _, offered = build_prompt(view, options, "TURN", legal, choices_bytes=2400, max_options=12)
    assert any([legal[k]["action"] for k in a["plan"]][:2] == ["Move", "Lightning Lash"] for a in offered.values())
    assert any([legal[k]["action"] for k in a["plan"]][:3] == ["Lightning Lash", "Gather Current", "Move"] for a in offered.values())
    assert len({tuple(a["plan"]) for a in offered.values()}) == len(offered)


def test_no_visible_enemy_search_and_memory_are_not_hidden_occupancy():
    view, legal = situation(False)
    first = build_prompt(view, turn_options(view, legal, "end"), "TURN", legal)[0]
    assert "look for enemies" in first
    assert "Bone Guard" not in first
    view["last_seen"] = [{"position": {"x": 8, "y": 6}, "hostile": True}]
    second = build_prompt(view, turn_options(view, legal, "end"), "TURN", legal)[0]
    assert "last seen enemy position" in second
    assert "Bone Guard" not in second
    # Unknown target rows must not appear even with ample menu space.
    legal["hidden-hit"] = {"action": "Strike unseen creature", "targets": ["unknown"]}
    options = turn_options(view, legal, "end", ["hidden-hit"], choices_bytes=2400, max_options=12)
    assert all("hidden-hit" not in o.answer["plan"] for o in options)


def test_observed_defeated_enemy_does_not_suppress_search_for_unseen_survivor():
    from agent_seats.tactics import tactical_moves
    view, legal = situation()
    view["actors"][1]["active"] = False
    # A surviving enemy is unseen: no current row or position is available.
    purposes = dict(tactical_moves(view, legal))
    assert purposes and all("look for enemies" in p for p in purposes.values())
    options = turn_options(view, legal, "hit", choices_bytes=2400, max_options=12)
    assert any("hit" in o.answer["plan"] for o in options)  # Downed targets remain usable.
    for budget, maximum in ((800, 6), (2400, 10), (2400, 12)):
        options = turn_options(view, legal, "hit", choices_bytes=budget, max_options=maximum)
        for repair in (None, "invalid"):
            prompt, offered = build_prompt(view, options, "TURN", legal, repair,
                                           choices_bytes=budget, max_options=maximum)
            assert len(prompt.encode()) <= budget
            assert any(any(k in purposes for k in a["plan"]) for a in offered.values())
            assert "look for enemies" in prompt
            assert "Defeated: Bone Guard" in prompt and "Threat: Bone Guard" not in prompt


@pytest.mark.parametrize("hostile", [None, 0])
def test_search_does_not_chase_remembered_allies_or_unclassified_legacy_markers(hostile):
    view, legal = situation(False)
    expected = build_prompt(view, turn_options(view, legal, "end"), "TURN", legal)
    marker = {"position": {"x": 19, "y": 1}, "name": "Remembered ally"}
    if hostile is not None:
        marker["hostile"] = hostile
    view["last_seen"] = [marker]
    assert build_prompt(view, turn_options(view, legal, "end"), "TURN", legal) == expected


def test_larger_menu_spends_space_on_more_targets_and_actions():
    view, legal = situation()
    for i in range(8):
        view["actors"].append({"entity_id": f"foe{i}", "display_name": f"Guard {i+1}",
                               "team_id": "theirs", "position": {"x": 4+i, "y": 6}})
        legal[f"hit{i}"] = dict(legal["hit"], targets=[f"foe{i}"])
    small = build_prompt(view, turn_options(view, legal, "hit"), "TURN", legal)[1]
    large_options = turn_options(view, legal, "hit", choices_bytes=2400, max_options=12)
    prompt, large = build_prompt(view, large_options, "TURN", legal, choices_bytes=2400, max_options=12)
    assert len(large) > len(small)
    assert len(large) >= 10
    assert len({o.label for o in large_options}) == len(large_options)
    for letter in large:
        assert parse_letter(letter.lower(), large) == large[letter]
    with pytest.raises(ValueError):
        parse_letter("L) actually A", large)
    assert "A-L" in prompt


def test_large_menu_diversifies_before_free_preparation_variants():
    view, legal = situation()
    prep = []
    for i in range(30):
        key = f"prep{i}"
        prep.append(key)
        legal[key] = {"action": "Plan a wall", "source": key, "economy": "FREE",
                      "targets": [], "destination": {"x": i % 10, "y": i // 10},
                      "description": "Choose a point for a later wall; this does not raise it."}
    legal["bow"] = dict(legal["hit"], action="Bow attack")
    legal["dodge"] = {"action": "Dodge", "economy": "ACTION", "targets": [],
                      "description": "Attacks against you have Disadvantage until your next turn."}
    ranked = ["hit", *prep, "bow", "dodge", "bonus"]
    options = turn_options(view, legal, "hit", ranked, choices_bytes=2400, max_options=12)
    _, offered = build_prompt(view, options, "TURN", legal, choices_bytes=2400, max_options=12)
    actions = {legal[k]["action"] for answer in offered.values() for k in answer["plan"]}
    assert {"Bow attack", "Dodge", "Move", "Lightning Lash"} <= actions
    assert len({k for answer in offered.values() for k in answer["plan"] if k in prep}) <= 1


@pytest.mark.parametrize("settings", [{"choices_bytes": True}, {"choices_bytes": 799},
    {"choices_bytes": 4801}, {"choices_bytes": 2400.0}, {"max_options": 2},
    {"max_options": 13}, {"max_options": False}])
def test_provider_menu_settings_reject_unbounded_or_noninteger_values(tmp_path, settings):
    path = tmp_path / "providers.json"
    path.write_text(json.dumps({"providers": [{"id": "fake", "kind": "local", "model": "offline",
        "base_url": "http://127.0.0.1:1", **settings}]}))
    with pytest.raises(ValueError):
        ProviderRegistry(path).load()
    with pytest.raises(ValueError):
        choices_settings(settings)


def test_provider_defaults_custom_budget_and_dispatch_enforced(tmp_path):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, fake = runner_for(tmp_path, table)
    assert choices_settings(runner.registry.load()["fake"]) == (800, 6)
    with pytest.raises(ValueError, match="prompt budget"):
        runner._ask({"prompt_profile": "choices", "choices_bytes": 2400, "max_options": 12}, "x" * 2401, {})
    assert not fake.prompts


def test_lateral_only_movement_still_gets_a_tactical_slot():
    view, legal = situation()
    view["actors"][0]["position"] = {"x": 3, "y": 6}
    legal = {k: r for k, r in legal.items() if r["action"] != "Move"}
    legal["lateral"] = {"action": "Move", "targets": [], "destination": {"x": 3, "y": 7}}
    _, offered = build_prompt(view, turn_options(view, legal, "end"), "TURN", legal)
    assert any("lateral" in a["plan"] for a in offered.values())


@pytest.mark.parametrize("spent", [False, True])
def test_real_reeling_step_followup_move_commits_and_reloads(tmp_path, spent):
    combat, table, mid, *_ = fixture(tmp_path, "TAL_DRUNKEN_STYLE_REELING_STEP")
    combat.controller = LocalDeterministicController()
    before = table.state(mid)
    table.act(mid, before["menu"]["end_turn"], before["menu"]["decision_id"],
              before["menu"]["state_version"], before["last_sequence"], [])
    if spent:
        # Spend the ordinary movement through legal table commits, staying in
        # the opponent's reach so this setup doesn't provoke an attack.
        for _ in range(30):
            state = table.state(mid)
            if combat._load_session(mid).engine.state.actors[PLAYER].movement_remaining_ft == 0:
                break
            candidates = [m for m in state["menu"]["moves"]
                          if not m["destination"].get("z")
                          and max(abs(m["destination"]["x"] - 4), abs(m["destination"]["y"] - 6)) <= 1]
            assert candidates
            move = min(candidates, key=lambda m: (m["destination"]["x"], m["destination"]["y"]))
            assert table.act(mid, move["candidate_id"], state["menu"]["decision_id"],
                             state["menu"]["state_version"], state["last_sequence"], [])["status"] == "COMMITTED"
        assert combat._load_session(mid).engine.state.actors[PLAYER].movement_remaining_ft == 0
        assert not table.state(mid)["menu"]["moves"]
    prompts = []
    granted_destinations = []
    def model(config, prompt, png):
        lines = [line for line in prompt.splitlines() if line[1:3] == ") "]
        if "your Bonus Action grants up to 10 feet of movement" in prompt:
            line = next(line for line in lines if "Move to" in line)
            destination = re.search(r"Move to (\d+),(\d+)", line)
            assert destination
            granted_destinations.append({"x": int(destination[1]), "y": int(destination[2])})
            return line[0], None
        reaction = next((line for line in lines if line[3:].startswith("Pass; spend nothing")), None)
        if reaction:
            return reaction[0], None
        if lines and lines[0][3:].startswith("Use"):
            return lines[0][0], None
        prompts.append(prompt)
        if len(prompts) > 1:
            return next(line[0] for line in lines if line[3:].startswith("Move") and ", then" not in line), None
        return next(line[0] for line in lines if "Reeling Step" in line
                    and (spent or ", then Move" in line)), None
    runner, _ = runner_for(tmp_path, table, model, timeout=30)
    configure(runner)
    settings = json.loads(runner.registry.path.read_text())
    settings["providers"][0].update(choices_bytes=2400, max_options=12)
    runner.registry.path.write_text(json.dumps(settings))
    initial_sequence = table.state(mid)["last_sequence"]
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    assert runner.drive(mid, max_steps=12) >= 3
    decisions = [r for r in runner.decisions(mid) if r["kind"] == "TURN"]
    assert all(not d["fallback"] for d in decisions), prompts
    actions = [r["action"] for d in decisions for r in d["chosen_menu"] if r["action"] != "End turn"]
    assert actions.index("Move") > next(i for i, a in enumerate(actions) if a.startswith("Reeling Step"))
    assert len(prompts) == (2 if spent else 1)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    steps = [r for r in runner.decisions(mid) if r["kind"] == "STEP"]
    # Reeling Step can pause for its legal player-owned rider choices before
    # resuming the commit. A paused attempt is not a failed movement.
    assert any(r["status"] == "COMMITTED" for r in steps)
    assert all(r["status"] in {"COMMITTED", "REACTION_REQUIRED"} for r in steps)
    moves = [r for d in decisions for r in d["chosen_menu"] if r["action"] == "Move"]
    assert len(moves) == 1
    events = [e for e in loaded.engine.events if e.sequence > initial_sequence and e.actor_id == PLAYER]
    reeling = next(e for e in events if e.event_type == "INTENT_ACCEPTED"
                   and e.source_definition_id.endswith(".TAL_DRUNKEN_STYLE_REELING_STEP"))
    assert len(granted_destinations) == 1
    granted = next(e for e in events if e.event_type == "MOVEMENT_COMMITTED"
                   and e.transaction_id == reeling.transaction_id)
    assert granted.payload["destination"] == granted_destinations[0]
    assert 0 < granted.payload["planned_cost_ft"] <= 10
    assert not granted.payload["interrupted"]
    moved = next(e for e in events if e.event_type == "MOVEMENT_COMMITTED"
                 and e.payload.get("destination") == moves[0]["destination"])
    assert reeling.sequence < granted.sequence < moved.sequence
    assert moved.payload["cost_ft"] > 0 and not moved.payload["interrupted"]
    assert moved.payload["planned_cost_ft"] > 0
    assert not any(e.event_type in {"TURN_ENDED", "TURN_STARTED"}
                   and reeling.sequence < e.sequence < moved.sequence for e in loaded.engine.events)
    position = loaded.engine.state.actors[PLAYER].position
    assert {"x": position.x, "y": position.y} == {k: moves[0]["destination"][k] for k in ("x", "y")}


@pytest.mark.parametrize("order", ["action-move", "move-action"])
def test_real_action_and_move_execute_ordered_and_reload(tmp_path, order):
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    # The real typed fighter, not its untrained opponent, has Wind Lash.
    before = table.state(mid)
    table.act(mid, before["menu"]["end_turn"], before["menu"]["decision_id"],
              before["menu"]["state_version"], before["last_sequence"], [])
    prompts = []
    def model(config, prompt, png):
        prompts.append(prompt)
        lines = [line for line in prompt.splitlines() if len(line) > 2 and line[1:3] == ") "]
        if order == "action-move":
            line = next(line for line in lines if "Wind Lash" in line and ", then Move" in line)
        else:
            line = next(line for line in lines if line[3:].startswith("Move") and ", then Wind Lash" in line)
        return line[0], None
    runner, _ = runner_for(tmp_path, table, model, timeout=30)
    configure(runner)
    settings = json.loads(runner.registry.path.read_text())
    settings["providers"][0].update(choices_bytes=2400, max_options=12)
    runner.registry.path.write_text(json.dumps(settings))
    initial = raw_state(runner, mid)
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    assert runner.drive(mid, max_steps=4) >= 3
    decision = next(r for r in runner.decisions(mid) if r["kind"] == "TURN")
    assert not decision["fallback"], "\n\n".join(prompts)
    actions = [r["action"] for r in decision["chosen_menu"]]
    assert (actions[0] == "Move") == (order == "move-action")
    assert "Move" in actions and any(a.startswith("Wind Lash") for a in actions)
    steps = [r for r in runner.decisions(mid) if r["kind"] == "STEP"]
    assert len(steps) == len(decision["chosen"])
    assert len(prompts) == 1  # Both planned steps really stayed legal.
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    loaded = reopened.combat._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    assert reopened.state(mid)["last_sequence"] > initial["last_sequence"]
    move = next(r for r in decision["chosen_menu"] if r["action"] == "Move")
    # A legal jump lands at End turn. Its committed destination survives in
    # the journal; the reloaded final position follows the engine's falling.
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == PLAYER
               and e.payload.get("destination") == move["destination"] for e in loaded.engine.events)
    position = loaded.engine.state.actors[PLAYER].position
    assert {"x": position.x, "y": position.y} == {k: move["destination"][k] for k in ("x", "y")}


def test_closing_reoffers_newly_legal_melee_before_implicit_end(tmp_path):
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    state = table.state(mid)
    melee = next(g["label"] for g in state["menu"]["actions"]
                 if "Unarmed" in g["label"] and any(PLAYER in o.get("target_ids", []) for o in g["options"]))
    engine = combat._load_session(mid).engine
    target = engine.state.actors[PLAYER].position
    far = [m for m in state["menu"]["moves"] if not m["destination"].get("z")
           and 15 <= engine.grid.distance_ft(Position.model_validate(m["destination"]), target) <= 20
           and engine.grid.line_of_sight(Position.model_validate(m["destination"]), target)]
    assert far
    move = min(far, key=lambda m: engine.grid.distance_ft(engine.state.actors[FOE].position, Position.model_validate(m["destination"])))
    # Leaving melee can provoke an opportunity attack during setup. Let the
    # real built-in chooser answer it, then restore manual turn advancement.
    combat.set_controller_mode(mid, actor_id=PLAYER, controller_mode="LOCAL_AUTO")
    state = table.state(mid)
    table.act(mid, move["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"], [])
    combat.set_controller_mode(mid, actor_id=PLAYER, controller_mode="MANUAL")
    for _ in range(2):
        state = table.state(mid)
        table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"], [])
    assert table.state(mid)["menu"]["actor_id"] == FOE
    assert not any(g["label"] == melee for g in table.state(mid)["menu"]["actions"])
    turns = []
    def model(config, prompt, png):
        lines = [line for line in prompt.splitlines() if line[1:3] == ") "]
        reaction = next((line for line in lines if line[3:].startswith("Pass; spend nothing")), None)
        if reaction:
            return reaction[0], None
        turns.append(prompt)
        if len(turns) == 1:
            for line in lines:
                p = re.search(r"\) Move to \((\d+),(\d+)\)", line)
                if p and ", then" not in line and max(abs(int(p[1])-target.x), abs(int(p[2])-target.y)) <= 1:
                    return line[0], None
            pytest.fail("No closing movement in the real menu")
        return next(line[0] for line in lines if line[3:].startswith(melee) and ", then Move" not in line), None
    runner, _ = runner_for(tmp_path, table, model, timeout=30)
    configure(runner)
    settings = json.loads(runner.registry.path.read_text())
    settings["providers"][0].update(choices_bytes=2400, max_options=12)
    runner.registry.path.write_text(json.dumps(settings))
    runner.set_seat(mid, PLAYER, "AI")
    runner.set_seat(mid, FOE, "MODEL", "fake")
    assert runner.drive(mid, max_steps=3) == 3
    decisions = [r for r in runner.decisions(mid) if r["kind"] == "TURN"]
    assert len(turns) == len(decisions) == 2
    assert all(not r["fallback"] for r in decisions), turns
    assert decisions[0]["chosen_menu"][0]["action"] == "Move"
    assert decisions[1]["chosen_menu"][0]["action"] == melee
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.skipif(not os.environ.get("FACTORY_SEAT_TACTICS_LIVE_COPY"), reason="Read-only historical copy is opt-in")
def test_real_sun_liu_captured_menus_and_no_visible_enemy_variants():
    from tools.score_seat_tactics import capture_menus
    names = set()
    for view, legal, row in capture_menus(Path(os.environ["FACTORY_SEAT_TACTICS_LIVE_COPY"])):
        own = next(a for a in view["actors"] if a["entity_id"] == view["fighter"])
        names.add(own["display_name"])
        for no_enemy in (False, True):
            current = deepcopy(view)
            if no_enemy:
                current["actors"] = [a for a in current["actors"] if a["team_id"] == own["team_id"]]
                current["last_seen"] = []
            known = {a["entity_id"] for a in current["actors"]}
            menu = {k: r for k, r in legal.items() if set(r.get("targets", [])) <= known}
            for budget, maximum in ((800, 6), (2400, 12)):
                options = turn_options(current, menu, row["built_in_pick"], limit=3, choices_bytes=budget, max_options=maximum)
                prompt, offered = build_prompt(current, options, "TURN", menu, choices_bytes=budget, max_options=maximum)
                assert any(any(menu[k]["action"] == "Move" for k in a["plan"]) for a in offered.values())
                assert "Bone Guard" not in prompt
                if no_enemy:
                    assert "Corpse Servant" not in prompt
    assert {"Sun Taitian", "Liu Yao Zisheng"} <= names
