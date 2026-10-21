"""Transport-independent protocol and persisted table repair/fallback checks."""
import json
import time

import pytest

from agent_seats.protocol import VERSION, build_prompt, compact_map, parse_reply, reply_schema, validate_answer
from agent_seats.providers import ProviderRegistry
from tests.test_agent_seats import FakeProvider, runner_for, raw_state
from tests.test_hunt5_player_choices import fixture, FOE, PLAYER
from combat.tabletop_service import TabletopService
from combat.gate5_service import CombatService
from tests.h1_support import ROOT

LEGAL = {"hit": {"action": "Attack", "source": "weapon", "targets": ["enemy"], "description": "Attack one creature."},
         "end": {"action": "End turn", "source": "End turn", "targets": []}}
VIEW = {"actors": [], "fighter": "me", "dao": {}, "map": {"width": 8, "height": 8}}


@pytest.mark.parametrize("text", [
    '{"plan":["hit","end"]}',
    '```json\n{"plan":["hit","end",],}\n```',
    'I choose this:\n{"plan":["hit","end"]}\nDone.',
    '{"plan":["hit","end"],"why":"Keep literal commas ,} and ,] intact."}',
])
def test_tolerant_reply_roundtrip(text):
    answer = parse_reply(text)
    assert validate_answer(answer, LEGAL, "TURN") == {"plan": ["hit", "end"]}
    if "why" in answer:
        assert ",}" in answer["why"] and ",]" in answer["why"]


@pytest.mark.parametrize("text", ["not JSON", '{"plan":["end"]}{"plan":["hit"]}',
    '{"broken": {"plan":["end"]}', '[{"plan":["end"]}]',
    '{"plan":["hit"],"plan":["end"]}', "x" * 65537])
def test_bad_or_ambiguous_reply_rejected(text):
    with pytest.raises(ValueError):
        parse_reply(text)


@pytest.mark.parametrize("answer", [{"plan": [False]}, {"plan": [{}]}, {"plan": ["hit"]},
    {"plan": ["invented", "end"]}, {"plan": ["end"], "tool": "run"}])
def test_validation_never_repairs_illegal_decisions(answer):
    with pytest.raises(ValueError):
        validate_answer(answer, LEGAL, "TURN")


def test_schema_prompt_example_and_group_roundtrip():
    menu = dict(LEGAL, other={**LEGAL["hit"], "targets": ["other"]})
    prompt = build_prompt(VIEW, menu, "hit", "Attack the nearest foe.", "TURN", 4)
    frame = json.loads(prompt.split("\n", 1)[1])
    assert frame["protocol"] == VERSION
    assert frame["reply_schema"] == reply_schema("TURN", 4)
    assert set(frame["legal_menu"]) == set(menu)
    group = frame["legal_menu"]["hit"]["group"]
    assert frame["action_groups"][group]["description"] == "Attack one creature."
    assert group == frame["legal_menu"]["other"]["group"]
    assert "description" not in frame["legal_menu"]["hit"]
    assert validate_answer(frame["worked_example"], menu, "TURN", 4)["plan"] == ["hit", "end"]
    from jsonschema import Draft202012Validator
    Draft202012Validator(frame["reply_schema"]).validate(frame["worked_example"])
    single = json.loads(build_prompt(VIEW, menu, "hit", "Hit", "TURN", 1).split("\n", 1)[1])
    Draft202012Validator(single["reply_schema"]).validate(single["worked_example"])


def test_grouping_does_not_collapse_different_costs():
    menu = dict(LEGAL, costly={**LEGAL["hit"], "cost_label": "2 Stamina"})
    frame = json.loads(build_prompt(VIEW, menu, "hit", "Hit", "TURN").split("\n", 1)[1])
    assert frame["legal_menu"]["hit"]["group"] != frame["legal_menu"]["costly"]["group"]


def test_mandatory_reaction_and_integer_spend():
    legal = {"choice": {"minimum": 1, "maximum": 1, "allow_decline": False,
                         "options": [{"id": "a", "label": "Stay here"}]}, "spend_options": [0, 2]}
    answer = {"selection": "USE", "option_ids": ["a"], "spend": 2}
    assert validate_answer(parse_reply(json.dumps(answer)), legal, "REACTION") == answer
    frame = json.loads(build_prompt(VIEW, legal, answer, "Choose Stay here.", "REACTION").split("\n", 1)[1])
    assert validate_answer(frame["worked_example"], legal, "REACTION") == answer
    for bad in [dict(answer, spend=True), dict(answer, spend=-1), dict(answer, option_ids=["a", "a"]),
                dict(answer, selection=[]), dict(answer, selection={}),
                {"selection": "DECLINE", "option_ids": [], "spend": 0}]:
        with pytest.raises(ValueError):
            validate_answer(bad, legal, "REACTION")


def test_compact_map_preserves_visible_cells_and_geometry():
    board = {"width": 8, "height": 8,
             "terrain": [{"name": "Difficult ground", "cells": [[2, 1], [1, 1], [2, 1], [5, 1]]}],
             "zones": [{"name": "Fire", "cells": [{"x": 3, "y": 4}, {"x": 4, "y": 4}]}],
             "walls": [{"points": [[0, 0], [1000, 0]], "filled": False}]}
    frame = compact_map(board)
    assert frame["terrain"][0]["cell_runs"] == [[1, 1, 2], [1, 5, 5]]
    assert frame["zones"][0]["cell_runs"] == [[4, 3, 4]]
    assert frame["walls"] == board["walls"]
    view = dict(VIEW, map=board, visible_cells=[[7, 7]])
    prompt = json.loads(build_prompt(view, LEGAL, "hit", "Hit", "TURN").split("\n", 1)[1])
    assert prompt["visible_map"] == frame
    assert "visible_cells" not in prompt["state"]


def test_repair_once_executes_real_turn_and_reloads(tmp_path):
    combat, table, mid, _, _ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    fake = FakeProvider(attack=True)
    calls = []
    def provider(config, prompt, png):
        calls.append(prompt)
        if len(calls) == 1:
            return '{"plan":["made-up-key"]}', {"total_tokens": 3}
        answer, usage = fake(config, prompt, png)
        return "Here is my plan:\n```json\n" + answer[:-1] + ",}\n```", usage
    runner, _ = runner_for(tmp_path, table, provider)
    runner.set_seat(mid, FOE, "MODEL", "fake")
    assert runner.drive(mid, max_steps=2) == 2
    assert raw_state(runner, mid)["menu"]["actor_id"] == PLAYER
    row = runner.decisions(mid)[0]
    assert row["attempts"] == 2 and row["invalid_replies"] == 1 and not row["fallback"]
    assert row["tokens"] == {"total_tokens": 15}
    assert "repair" in json.loads(calls[1].split("\n", 1)[1])
    assert "made-up-key" not in calls[1]
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reopened.state(mid)["menu"]["actor_id"] == PLAYER
    session = reopened.combat._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


def test_two_bad_answers_fallback_without_retrying_same_turn(tmp_path):
    combat, table, mid, _, _ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    from combat.gate4_controller import LocalDeterministicController
    combat.controller = LocalDeterministicController()
    calls = []
    def bad(config, prompt, png):
        calls.append(prompt)
        return "bad JSON", None
    runner, _ = runner_for(tmp_path, table, bad)
    runner.set_seat(mid, FOE, "MODEL", "fake")
    runner.drive(mid, max_steps=2)
    row = runner.decisions(mid)[0]
    assert row["attempts"] == row["invalid_replies"] == len(calls) == 2
    assert row["fallback"] and row["chosen"] == [row["built_in_pick"]]
    session = combat._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


def test_repair_shares_deadline_and_timeout_is_not_retried(tmp_path):
    _, table, mid, _, _ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    calls = []
    def slow(config, prompt, png):
        calls.append(config["timeout_s"])
        if len(calls) == 1:
            time.sleep(.02)
            return "bad JSON", None
        raise TimeoutError("transport timeout")
    runner, _ = runner_for(tmp_path, table, slow, timeout=.5)
    runner.set_seat(mid, FOE, "MODEL", "fake")
    runner.drive(mid, max_steps=1)
    assert len(calls) == 2 and calls[1] < calls[0] < .5
    assert runner.decisions(mid)[0]["fallback"] == "timeout"


def test_registry_environment_and_plan_limit(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    row = {"id": "fake", "kind": "cli", "command": ["fake"], "max_plan_length": 4}
    path.write_text(json.dumps({"providers": [row]}))
    monkeypatch.setenv("FACTORY_SEAT_PROVIDERS", str(path))
    assert ProviderRegistry().load()["fake"]["max_plan_length"] == 4
    for limit in [True, 0, 33, "4"]:
        path.write_text(json.dumps({"providers": [dict(row, max_plan_length=limit)]}))
        with pytest.raises(ValueError):
            ProviderRegistry().load()


def test_text_prompt_preserves_visible_tree_trunks():
    from agent_seats.snapshots import project_map
    from combat.tabletop import normalize_map, table_section
    source = table_section(normalize_map({"map_id": "prompt-trees", "name": "Trees",
        "width_squares": 8, "height_squares": 8,
        "trees": [{"x": 2, "y": 3, "size": 2, "seed": 77}]}))
    board = project_map(source, [[2, 3], [3, 3]], 8, 8, [])
    frame = json.loads(build_prompt(dict(VIEW, map=board), LEGAL, "hit", "Hit", "TURN").split("\n", 1)[1])
    assert frame["visible_map"]["trees"] == [{"name": "Tree trunk: blocks movement and sight",
                                               "cell_runs": [[3, 2, 3]]}]


@pytest.mark.parametrize("expired_attempt", [0, 1])
def test_prompt_construction_cannot_dispatch_after_deadline(tmp_path, monkeypatch, expired_attempt):
    import agent_seats.runner as module
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    calls = []
    runner, _ = runner_for(tmp_path, table, timeout=.5)
    clock = [100.0]
    builds = []
    original = module.build_prompt
    def build(*args):
        prompt = original(*args)
        clock[0] += .6 if len(builds) == expired_attempt else .1
        builds.append(prompt)
        return prompt
    def ask(config, prompt, view):
        calls.append(config["timeout_s"])
        return "bad JSON", None
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module, "build_prompt", build)
    monkeypatch.setattr(runner, "_ask", ask)
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, VIEW, LEGAL, "hit", "Hit", "TURN")
    assert answer == {"plan": ["hit"], "fallback": True}
    assert len(calls) == expired_attempt
    if calls:
        assert calls[0] == pytest.approx(.4)
    row = runner.decisions(mid)[0]
    assert row["fallback"] == "timeout" and row["attempts"] == len(calls)


def test_prompt_time_reduces_actual_provider_wait(tmp_path, monkeypatch):
    import threading
    import agent_seats.runner as module
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    release = threading.Event()
    entered = threading.Event()
    finished = threading.Event()
    def blocked(config, prompt, png):
        entered.set()
        try:
            release.wait(2)
            return "bad JSON", None
        finally:
            finished.set()
    runner, _ = runner_for(tmp_path, table, blocked, timeout=.4)
    original = module.build_prompt
    def slow_build(*args):
        time.sleep(.25)
        return original(*args)
    monkeypatch.setattr(module, "build_prompt", slow_build)
    started = time.monotonic()
    try:
        runner._decide(mid, FOE, {"provider_id": "fake"}, VIEW, LEGAL, "hit", "Hit", "TURN")
        elapsed = time.monotonic() - started
    finally:
        release.set()
    assert entered.is_set() and finished.wait(2)
    assert .38 <= elapsed < .58
    assert runner.decisions(mid)[0]["fallback"] == "timeout"
