"""Small-model profile: bounded prompts, scored menus and persisted transport."""
import json

import pytest

from agent_seats.compact import PROMPT_BUDGET, select_menu
from agent_seats.protocol import build_prompt, parse_reply, validate_answer
from agent_seats.providers import ProviderRegistry
from combat.gate4_controller import LocalDeterministicController
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_agent_seats import runner_for, raw_state
from tests.test_hunt5_player_choices import fixture, FOE, PLAYER


def frame(prompt):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, f"Duplicate prompt key: {key}"
            result[key] = value
        return result
    return json.loads(prompt.split("\n", 1)[1], object_pairs_hook=unique_object)


def large_fight():
    """Largest profile stress fixture: 100x100 observed map, 10,002 legal choices."""
    own = {"entity_id": "me", "display_name": "Fighter", "position": {"x": 50, "y": 50},
           "resources": {"Stamina": 7}, "action_available": True}
    nearby = {"entity_id": "near", "display_name": "Nearby foe", "position": {"x": 51, "y": 50},
              "hit_points": 20, "resources": {"private-secret": 99}}
    far = {"entity_id": "far", "display_name": "Distant foe", "position": {"x": 99, "y": 99}}
    view = {"fighter": "me", "round": 1, "actors": [own, nearby, far], "dao": {"role": ["Defender"]},
            "last_seen": [{"position": {"x": 90, "y": 90}, "round": 0}],
            "map": {"width": 100, "height": 100,
                    "terrain": [{"name": "Rough ground", "cells": [[x, y] for x in range(100) for y in range(100)]}],
                    "trees": [{"name": "Tree trunk: blocks movement and sight", "cells": [[49, 50], [90, 90]]}],
                    "walls": [{"points": [[49000, 50000], [50000, 50000]], "filled": False},
                              {"points": [[90000, 90000], [91000, 90000]], "filled": False}]}}
    legal = {f"move-{x}-{y}": {"action": "Move", "source": "Move", "targets": [],
                               "destination": {"x": x, "y": y}, "options": []}
             for x in range(100) for y in range(100)}
    legal.update(hit={"action": "Attack", "source": "weapon", "targets": ["near"],
                      "description": "Attack a creature in reach.", "cost_label": "No Stamina cost", "economy": "Action"},
                 end={"action": "End turn", "source": "End turn", "targets": []})
    return view, legal


def test_largest_profile_fixture_budget_determinism_own_view_and_scripted_parse():
    view, legal = large_fight()
    ranked = ["hit", *sorted(k for k in legal if k.startswith("move")), "end"]
    prompt = build_prompt(view, legal, "hit", "Hit", "TURN", 32, None, "compact", ranked)
    assert prompt == build_prompt(view, legal, "hit", "Hit", "TURN", 32, None, "compact", ranked)
    assert len(prompt) <= PROMPT_BUDGET
    assert len(build_prompt(view, legal, "hit", "Hit", "TURN")) > 1000000
    data = frame(prompt)
    assert {"hit", "end"} <= set(data["legal_menu"])
    assert data["reply_schema"]["properties"]["plan"]["maxItems"] == 3
    assert {a["entity_id"] for a in data["state"]["actors"]} == {"me", "near"}
    assert "private-secret" not in prompt and "Distant foe" not in prompt and "last_seen" not in prompt
    assert data["state"]["actors"][0]["resources"] == {"Stamina": 7}
    assert data["visible_map"]["window"] == [44, 44, 56, 56]
    assert data["visible_map"]["trees"][0]["cell_runs"] == [[50, 49, 49]]
    assert len(data["visible_map"]["walls"]) == 1
    reply = 'My choice:\n' + json.dumps(data["worked_example"])[:-1] + ',}\nReady.'
    assert validate_answer(parse_reply(reply), data["legal_menu"], "TURN", 3) == {"plan": ["hit", "end"]}


def test_ranked_menu_retains_top_groups_and_multiple_destinations():
    _, legal = large_fight()
    legal.update({f"spell-{i}": {"action": f"Spell {i}", "source": f"spell-{i}", "targets": []} for i in range(20)})
    ranked = ["spell-9", "move-50-51", "move-51-50", "move-52-50", *[f"spell-{i}" for i in range(20)]]
    menu = select_menu(legal, "hit", ranked)
    assert list(menu)[:5] == ["hit", "end", "spell-9", "move-50-51", "move-51-50"]
    assert "move-52-50" not in menu
    assert len({v["source"] for v in menu.values()}) == 6
    assert "spell-19" not in menu


@pytest.mark.parametrize("profile", [None, "full", "compact"])
def test_registry_profile_default_and_selection(tmp_path, profile):
    path = tmp_path / "providers.json"
    row = {"id": "fake", "kind": "local", "base_url": "http://localhost:1", "model": "fake"}
    if profile is not None:
        row["prompt_profile"] = profile
    path.write_text(json.dumps({"providers": [row]}))
    assert ProviderRegistry(path).load()["fake"]["prompt_profile"] == (profile or "full")
    for invalid in ["small", False, [], None]:
        path.write_text(json.dumps({"providers": [dict(row, prompt_profile=invalid)]}))
        with pytest.raises(ValueError):
            ProviderRegistry(path).load()


def set_compact(runner):
    path = runner.registry.path
    config = json.loads(path.read_text())
    config["providers"][0].update(prompt_profile="compact", max_plan_length=32, vision=True)
    path.write_text(json.dumps(config))


@pytest.mark.parametrize("mechanic", ["AIR_BASE_GATHER_CURRENT", "TAL_FENCING_FOOTWORK"])
def test_real_table_compact_scoring_repair_commit_reload(tmp_path, mechanic):
    combat, table, mid, *_ = fixture(tmp_path, mechanic)
    combat.controller = LocalDeterministicController()
    prompts = []
    def scripted(config, prompt, png):
        assert not config["vision"] and png is None
        prompts.append(prompt)
        if len(prompts) == 1:
            return "invalid", None
        return "My choice:\n" + json.dumps(frame(prompt)["worked_example"])[:-1] + ",}\nReady.", None
    runner, _ = runner_for(tmp_path, table, scripted, timeout=10)
    set_compact(runner)
    # Give the high-menu fighter its own current turn before model assignment.
    state = raw_state(runner, mid)
    table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"], [])
    state = raw_state(runner, mid)
    session = combat._load_session(mid)
    view, known = runner.own_view(mid, state, PLAYER, session)
    options = runner._menu(state, known)
    ranked = []
    builtin, reason = runner._builtin(mid, session, known, options, view["visible_cells"], ranked)
    assert ranked[0] == builtin and len(ranked) > 2
    legal = {k: v["description"] for k, v in options.items()}
    full = build_prompt(view, legal, builtin, reason, "TURN")
    compact = build_prompt(view, legal, builtin, reason, "TURN", 32, None, "compact", ranked)
    assert len(compact) <= PROMPT_BUDGET and len(compact) < len(full)
    print(f"OFFLINE {mechanic}: choices={len(legal)} full={len(full)} compact={len(compact)}")
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    assert runner.drive(mid, max_steps=2) == 2
    assert len(prompts) == 2 and all(len(p) <= PROMPT_BUDGET for p in prompts)
    row = runner.decisions(mid)[0]
    assert row["attempts"] == 2 and row["invalid_replies"] == 1 and not row["fallback"]
    assert "repair" in frame(prompts[1])
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reopened.state(mid)["last_sequence"] > state["last_sequence"]
    saved = reopened.combat._load_session(mid)
    assert saved.verify()["status"] == saved.mechanical.replay()["status"] == "PASS"


def test_oversized_mandatory_frame_falls_back_without_dispatch(tmp_path):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, fake = runner_for(tmp_path, table)
    set_compact(runner)
    view, legal = large_fight()
    legal["hit"]["description"] = "Too large " * 2000
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal, "hit", "Hit", "TURN")
    assert answer == {"plan": ["hit"], "fallback": True}
    assert not fake.prompts


def test_compact_reaction_preserves_offered_choices_and_costs():
    view, _ = large_fight()
    legal = {"ability": "Footwork", "trigger": "Nearby foe attacks you", "affected": "Fighter",
             "choice": {"minimum": 1, "maximum": 1, "allow_decline": False,
                        "options": [{"id": "stay", "label": "Stay put; spend 1 Martial Focus"}]},
             "spend_options": [0]}
    builtin = {"selection": "USE", "option_ids": ["stay"], "spend": 0}
    prompt = build_prompt(view, legal, builtin, "", "REACTION", 32, "Use required options", "compact")
    assert len(prompt) <= PROMPT_BUDGET
    data = frame(prompt)
    assert data["legal_menu"] == legal
    assert validate_answer(data["worked_example"], legal, "REACTION") == builtin


def test_distant_selected_target_retained_and_low_ranked_large_prose_removed():
    view, legal = large_fight()
    legal["shot"] = {"action": "Bow attack", "source": "bow", "targets": ["far"], "cost_label": "Action"}
    legal["huge"] = {"action": "Other action", "source": "other", "targets": [], "description": "long " * 4000}
    prompt = build_prompt(view, legal, "hit", "Hit", "TURN", 32, None, "compact", ["shot", "huge"])
    data = frame(prompt)
    assert len(prompt) <= PROMPT_BUDGET and "huge" not in data["legal_menu"]
    assert {"hit", "end", "shot"} == set(data["legal_menu"])
    assert "far" in {a["entity_id"] for a in data["state"]["actors"]}


def test_runner_rejects_unoffered_key_and_overlength_plan(tmp_path):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    view, legal = large_fight()
    calls = []
    def bad(config, prompt, png):
        calls.append(prompt)
        return json.dumps({"plan": ["move-99-99", "end"]} if len(calls) == 1
                          else {"plan": ["hit", "hit", "hit", "end"]}), None
    runner, _ = runner_for(tmp_path, table, bad, timeout=10)
    set_compact(runner)
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal, "hit", "Hit", "TURN")
    assert answer["fallback"] and len(calls) == 2
    assert runner.decisions(mid)[0]["invalid_replies"] == 2


@pytest.mark.parametrize("automatic", [False, True])
def test_compact_real_opponent_turn_reaction_reload(tmp_path, automatic):
    combat, table, mid, cid, _ = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    runner, fake = runner_for(tmp_path, table, timeout=10)
    set_compact(runner)
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    if automatic:
        runner.set_seat(mid, FOE, "AI")
    menu = table.state(mid)["menu"]
    out = table.auto_step(mid, 0) if automatic else table.act(mid, cid, menu["decision_id"], menu["state_version"], 0)
    assert out["status"] == "MODEL_DECIDING"
    assert runner.drive(mid, max_steps=1) == 1
    assert len(fake.prompts) == 1 and frame(fake.prompts[0])["decision_kind"] == "REACTION"
    assert len(fake.prompts[0]) <= PROMPT_BUDGET
    saved = CombatService(ROOT, tmp_path)._load_session(mid)
    assert saved.mechanical.replay()["status"] == "PASS"
