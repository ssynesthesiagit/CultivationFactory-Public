"""Offline slow-model controls: no sockets, inference, browser or GUI."""
from copy import deepcopy
import json

import pytest

from agent_seats.providers import ProviderRegistry, complete, request_options
from agent_seats.protocol import build_prompt, stable_prefix
from agent_seats.compact import TINY_PROMPT_BUDGET
from tests.test_seat_compact import large_fight, frame


def registry(tmp_path, **settings):
    row = dict(id="test", kind="local", model="fake", base_url="http://localhost:1")
    row.update(settings)
    path = tmp_path / "providers.json"
    path.write_text(json.dumps({"providers": [row]}))
    return ProviderRegistry(path).load()["test"]


@pytest.mark.parametrize("options", [
    None, [], {"api_key": "secret"}, {"messages": []}, {"model": "other"},
    {"tools": []}, {"stream": True}, {"temperature": True}, {"temperature": -1},
    {"temperature": 3}, {"temperature": float("nan")}, {"temperature": float("inf")},
    {"max_tokens": 0}, {"max_tokens": 32769}, {"max_tokens": "20"},
    {"reasoning_budget": -1}, {"reasoning_budget": True}, {"reasoning_budget": 1.5},
    {"cache_prompt": 1}, {"chat_template_kwargs": {"secret": "x"}},
    {"chat_template_kwargs": {"enable_thinking": "false"}}, {"chat_template_kwargs": []},
])
def test_request_options_reject_unknown_and_invalid(tmp_path, options):
    with pytest.raises(ValueError):
        registry(tmp_path, request_options=options)
    with pytest.raises(ValueError):
        request_options(options)


@pytest.mark.parametrize("kind", ["local", "openai_compatible"])
@pytest.mark.parametrize("override_cache", [None, False])
def test_http_body_merges_options_without_overwriting_contract(tmp_path, monkeypatch, kind, override_cache):
    import agent_seats.providers as module
    options = dict(reasoning_budget=0, chat_template_kwargs={"enable_thinking": False},
                   temperature=0, max_tokens=256)
    if override_cache is not None:
        options["cache_prompt"] = override_cache
    provider = registry(tmp_path, kind=kind, request_options=options)
    captured = {}
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, limit):
            return b'{"choices":[{"message":{"content":"{}"}}]}'
    def send(req, timeout):
        captured.update(json.loads(req.data))
        return Response()
    monkeypatch.setattr(module.urllib.request, "urlopen", send)
    assert complete(provider, "safe prompt")[0] == "{}"
    assert captured["model"] == "fake"
    assert captured["messages"] == [{"role": "user", "content": "safe prompt"}]
    assert all(captured[k] == v for k, v in options.items())
    if kind == "local" or override_cache is not None:
        assert captured["cache_prompt"] is (True if override_cache is None else False)
    else:
        assert "cache_prompt" not in captured


def test_cli_rejects_http_options(tmp_path):
    with pytest.raises(ValueError):
        registry(tmp_path, kind="cli", command=["fake"], request_options={})


@pytest.mark.parametrize("kind,cap", [("local", 180), ("openai_compatible", 60), ("cli", 60)])
def test_timeout_validation_by_kind(tmp_path, kind, cap):
    assert registry(tmp_path, kind=kind, command=["fake"], timeout_s=cap)["timeout_s"] == cap
    for value in (0, -1, True, "60", cap + .1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            registry(tmp_path, kind=kind, command=["fake"], timeout_s=value)


@pytest.mark.parametrize("profile", ["full", "compact", "tiny"])
def test_stable_prefix_is_byte_identical_across_decisions_and_repair(profile):
    view, legal = large_fight()
    first = build_prompt(view, legal, "hit", "Hit", "TURN", 3, None, profile, ["hit"])
    later = deepcopy(view)
    later["round"] = 2
    later["actors"][0]["position"]["x"] += 1
    later["actors"][0]["resources"]["Stamina"] -= 1
    second = build_prompt(later, legal, "end", "Done", "TURN", 3, "Invalid reply", profile, ["hit"])
    reaction = build_prompt(later, {"spend_options": [0]},
                            {"selection": "DECLINE", "option_ids": [], "spend": 0},
                            "Decline", "REACTION", 3, None, profile)
    prefix = stable_prefix(first).encode()
    assert prefix == stable_prefix(second).encode() == stable_prefix(reaction).encode()
    assert first != second
    assert b'"schemas"' in prefix and b'"format_examples"' in prefix and b'"dao"' in prefix
    assert b'"round"' not in prefix and b'"built_in_pick"' not in prefix
    print(f"{profile}: stable prefix {len(prefix)}/{len(first.encode())} bytes ({len(prefix)/len(first.encode()):.1%})")


@pytest.mark.parametrize("profile", ["full", "compact", "tiny"])
@pytest.mark.parametrize("kind", ["TURN", "REACTION"])
@pytest.mark.parametrize("repair", [None, "Invalid reply"])
def test_prompt_has_unique_fields_and_preserves_fighter_dao(profile, kind, repair):
    view, legal = large_fight()
    view["dao"].update(temperament={"natural": "Protect allies"},
                       preferred_distance_ft=[5, 10], save_resources={"Stamina": 2})
    builtin = "hit"
    if kind == "REACTION":
        legal = {"spend_options": [0]}
        builtin = {"selection": "DECLINE", "option_ids": [], "spend": 0}
    before = deepcopy(view)
    prompt = build_prompt(view, legal, builtin, "Suggested", kind, 3, repair, profile, ["hit"])
    data = frame(prompt)  # Strict at every JSON object, including table-test frames.
    assert data["fighter"] == data["state"]["fighter"] == view["fighter"]
    expected_dao = (view["dao"] if profile == "full" else
                    "Defender; Protect allies; preferred feet [5, 10]; save resources {'Stamina': 2}")
    assert data["dao"] == expected_dao
    assert "dao" not in data["state"]
    assert data["decision_kind"] == kind
    assert ("repair" in data) == bool(repair)
    assert view == before


def test_tiny_budget_trims_optional_content_and_preserves_required_choices(tmp_path):
    assert registry(tmp_path, prompt_profile="tiny")["prompt_profile"] == "tiny"
    view, legal = large_fight()
    for i in range(5):
        legal[f"extra-{i}"] = {"action": f"Extra {i}", "description": "Optional text. " * 130}
    ranked = [f"extra-{i}" for i in range(5)]
    compact = build_prompt(view, legal, "hit", "Hit", "TURN", 3, None, "compact", ranked)
    tiny = build_prompt(view, legal, "hit", "Hit", "TURN", 3, "Invalid", "tiny", ranked)
    assert len(tiny) <= TINY_PROMPT_BUDGET < len(compact)
    assert {"hit", "end"} <= set(frame(tiny)["legal_menu"])
    assert frame(tiny)["state"]["actors"][0]["resources"] == {"Stamina": 7}
    legal["hit"]["description"] = "Mandatory text. " * 1000
    with pytest.raises(ValueError, match="prompt budget"):
        build_prompt(view, legal, "hit", "Hit", "TURN", 3, None, "tiny")


def test_tiny_real_table_repair_commit_and_reload(tmp_path):
    from tests.test_hunt5_player_choices import fixture, FOE
    from tests.test_agent_seats import runner_for
    from combat.gate4_controller import LocalDeterministicController
    from combat.tabletop_service import TabletopService
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    prompts = []
    def scripted(config, prompt, png):
        assert len(prompt) <= TINY_PROMPT_BUDGET and png is None
        prompts.append(prompt)
        return ("invalid" if len(prompts) == 1 else json.dumps(frame(prompt)["worked_example"])), None
    runner, _ = runner_for(tmp_path, table, scripted, timeout=10)
    path = runner.registry.path
    config = json.loads(path.read_text())
    config["providers"][0].update(prompt_profile="tiny", vision=True)
    path.write_text(json.dumps(config))
    runner.set_seat(mid, FOE, "MODEL", "fake")
    runner.drive(mid, max_steps=2)
    assert len(prompts) == 2 and stable_prefix(prompts[0]) == stable_prefix(prompts[1])
    assert not runner.decisions(mid)[0]["fallback"]
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reopened.state(mid)
    session = reopened.combat._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
