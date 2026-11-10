"""Public, synthetic MENUPRUNE1 checks. No model server or owner fixtures."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from agent_seats.choices import build_prompt, reaction_options, turn_options
from agent_seats.providers import ProviderRegistry, choices_settings
from tools import menuprune_replay as replay
from tools.menuprune_report import render, summarize


def example(count=32, kind="TURN"):
    legal = {f"act{i}": {"action": f"Technique {i}", "targets": [],
                        "economy": "ACTION", "description": f"Deal {i+1} damage.",
                        "cost_label": "Action"} for i in range(count)}
    if kind == "TURN":
        legal["end"] = {"action": "End turn", "targets": []}
    state = {"view": {"fighter": "me", "actors": [
        {"entity_id": "me", "display_name": "Hero", "team_id": "ours",
         "position": {"x": 1, "y": 1}, "hit_points": "20/20"}],
        "objects": [], "dao": {"role": ["Defender"]}},
        "legal": legal, "provider": {"kind": "local", "choices_bytes": 4800, "max_options": 5},
        "ranked": list(legal), "limit": 3, "geometry": "open",
        "reference_top_k": {"MASTERMIND": ["act0", f"act{count-1}"], "TRICKY": ["act1"]},
        "useful_keys": ["act0"]}
    row = {"match_id": "synthetic", "decision_id": "decision:1", "attempt": 0,
           "kind": kind, "built_in_pick": "act0", "built_in_id": "A"}
    row["prompt"] = replay.frame(row, state, "A")[0]
    return row, state


class Fake:
    def __init__(self, first=None, end=False):
        self.calls = []
        self.first, self.end = first, end

    def __call__(self, prompt, offered, provider):
        self.calls.append((prompt, deepcopy(offered)))
        token = next((k for k, a in offered.items()
                      if a.get("plan", [None])[0] == self.first), None)
        if self.end:
            token = next(k for k, a in offered.items() if a == {"plan": ["end"]})
        return {"choice": token or next(iter(offered)),
                "probabilities": {k: int(k == (token or next(iter(offered)))) for k in offered}}


@pytest.mark.parametrize("kind", ["TURN", "STEP"])
def test_arm_sizes_full_coverage_and_explicit_opt_in(kind):
    row, state = example(kind=kind)
    original = deepcopy(state)
    a = replay.frame(row, state, "A")
    b = replay.frame(row, state, "B")
    c = replay.frame(row, state, "C")
    assert len(a[1]) == 5
    assert len(b[1]) == 12
    assert len(c[1]) == 32 + (kind == "TURN")
    assert {a["plan"][0] for a in c[1].values()} == set(state["legal"])
    assert "P27)" in c[0]
    assert set(replay.decision_payload(c[0], c[1])["options"]) == set(c[1])
    assert state == original
    with pytest.raises(ValueError, match="explicit"):
        turn_options(state["view"], state["legal"], "act0", max_options="all")
    with pytest.raises(ValueError, match="explicit"):
        build_prompt(state["view"], [], kind, state["legal"], max_options="all")
    with pytest.raises(ValueError, match="no options removed"):
        build_prompt(state["view"], turn_options(state["view"], state["legal"], "act0",
                     max_options="all", experiment="menuprune1"), kind, state["legal"],
                     choices_bytes=800, max_options="all", experiment="menuprune1")


def test_full_families_hidden_targets_and_existing_navigation():
    row, state = example()
    # Same family, different issued legal keys: C must not stop at 2/3 variants.
    for i, value in enumerate(state["legal"].values()):
        if value["action"] != "End turn":
            value.update(action=f"Technique: Mode {i}", source=f"source{i}")
    state["legal"]["hidden"] = {"action": "Strike", "targets": ["unseen"]}
    row["prompt"] = replay.frame(row, state, "A")[0]
    c_prompt, c = replay.frame(row, state, "C")
    assert {a["plan"][0] for a in c.values()} == set(state["legal"]) - {"hidden"}
    assert "unseen" not in c_prompt
    # Existing navigation is retained, rather than treating "More" as End.
    state["pages"] = {}
    state["provider"].update(primer="Prefer cover.", choices_bytes=800)
    from agent_seats.menu_pages import RankedPages, choice_frame
    guidance = replay.guidance_block(state["provider"]["primer"])
    pages = RankedPages(state["legal"], state["ranked"], row["built_in_pick"], 1)
    pages.first = pages.first[:1]
    recorded_prompt, recorded_offered, _ = choice_frame(
        state["view"], pages, 800 - len(guidance.encode()))
    recorded_prompt = replay.with_guidance(recorded_prompt, guidance)
    row["prompt"] = recorded_prompt
    a_prompt, a = replay.frame(row, state, "A")
    c_prompt, c = replay.frame(row, state, "C")
    assert (a_prompt, a) == (recorded_prompt, recorded_offered)
    assert c_prompt == a_prompt
    assert c == a
    assert replay.useful_offered(state, c) is True
    assert replay.is_end({"plan": ["__menu_more__"]}, state["legal"]) is False
    assert "Prefer cover." in a_prompt


def test_live_row_and_a_prompt_bytes_unchanged(tmp_path):
    row, state = example()
    registry_path = tmp_path / "providers.json"
    registry_path.write_text(json.dumps({"providers": [{
        "id": "synthetic", "model": "fake", "base_url": "http://invalid.example/v1",
        **state["provider"]}]}))
    before = registry_path.read_bytes()
    provider = ProviderRegistry(registry_path).load()["synthetic"]
    provider_before = deepcopy(provider)
    budget, maximum = choices_settings(provider)
    options = turn_options(state["view"], state["legal"], row["built_in_pick"],
                           state["ranked"], None, 3, budget, maximum)
    live = build_prompt(state["view"], options, "TURN", state["legal"],
                        choices_bytes=budget, max_options=maximum)
    state["provider"] = provider
    assert replay.frame(row, state, "A") == live
    replay.frame(row, state, "B")
    replay.frame(row, state, "C")
    assert registry_path.read_bytes() == before
    assert provider == provider_before
    # The shipped rows file is not read from private/live configuration.
    shipped = Path(replay.__file__).parents[1] / "agent_seats" / "providers.json"
    shipped_before = shipped.read_bytes()
    assert ProviderRegistry(shipped).load() == {}
    assert shipped.read_bytes() == shipped_before
    for settings in ({"max_options": "all"}, {"choices_bytes": 100000}):
        with pytest.raises(ValueError):
            choices_settings(settings)


def test_fake_replay_coverage_end_usefulness_and_larger_only():
    row, state = example()
    fake = Fake(end=True)
    a = replay.replay_one(row, state, "A", "fake", fake)
    assert not a["error"] and a["a_byte_identical"]
    assert a["built_in_in_menu"]
    assert a["mastermind_top_k_in_menu"] == [True, False]
    assert a["tricky_top_k_in_menu"] == [True]
    assert a["end_while_useful"] is True
    assert a["only_in_larger_menu"] is False
    c = replay.replay_one(row, state, "C", "fake", Fake("act31"))
    assert c["pick"]["plan"][0] == "act31"
    assert c["only_in_larger_menu"]
    assert c["mastermind_top_k_in_menu"] == [True, True]
    assert c["end_while_useful"] is False
    assert c["candidate_generation_ms"] >= 0 and c["inference_ms"] >= 0
    state["useful_keys"] = []
    assert replay.replay_one(row, state, "A", "fake", Fake(end=True))["end_while_useful"] is False
    del state["useful_keys"]
    assert replay.replay_one(row, state, "A", "fake", Fake(end=True))["end_while_useful"] is None
    assert len(fake.calls) == 1
    for arm in "AC":
        recovered = replay.replay_one(row, state, arm, "fake",
            lambda *args: {"choice": "Option B"})
        assert recovered["error"] is None
        assert recovered["pick"]["plan"][0] == "act1"


def test_failures_are_retained_without_dispatch_or_fake_agreement():
    row, state = example()
    fake = Fake()
    for broken in (None, {**state, "view": {**state["view"], "dao": {"role": ["Attacker"]}}}):
        result = replay.replay_one(row, broken, "C", "fake", fake)
        assert result["error"] and result["fallback"]
        assert result["pick"] is None and result["inference_ms"] is None
    assert not fake.calls
    class Broken:
        def __call__(self, *args):
            raise TimeoutError("synthetic deadline")
    result = replay.replay_one(row, state, "A", "fake", Broken())
    assert result["fallback"] and result["inference_ms"] >= 0
    assert "TimeoutError" in result["error"]
    assert result["pick"] is None


def test_full_reaction_menu_keeps_all_responses():
    row, state = example()
    state["legal"] = {"ability": "Guard", "choice": {
        "options": [{"id": f"r{i}", "label": f"Guard {i}", "description": "Reduce damage."}
                    for i in range(8)],
        "minimum": 1, "maximum": 1, "allow_decline": True}, "spend_options": [0]}
    row.update(kind="REACTION", built_in_pick={"selection": "DECLINE", "option_ids": [], "spend": 0})
    row["prompt"] = replay.frame(row, state, "A")[0]
    assert len(reaction_options(state["legal"], row["built_in_pick"])) <= 6
    prompt, offered = replay.frame(row, state, "C")
    assert len(offered) == 9
    result = replay.replay_one(row, state, "C", "fake", Fake())
    assert not result["error"] and result["built_in_in_menu"]


def test_paired_stop_rule_report_and_partial_error_retention():
    row, state = example()
    rows = []
    for i in range(100):
        for arm in "ABC":
            result = replay.replay_one({**row, "decision_id": str(i)}, state, arm, "fake", Fake())
            # This example has unique action families and no ranking confound.
            assert not result["error"]
            rows.append(result)
    report = summarize(rows, 100)
    assert report["paired_measurement"][0]["stop"]
    assert report["paired_measurement"][0]["abc_agreement_percent"] == 100
    reordered = {**state, "legal": dict(reversed(list(state["legal"].items())))}
    assert replay.fingerprint(reordered) != replay.fingerprint(state)
    mismatch = deepcopy(rows)
    mismatch[2]["state_sha256"] = replay.fingerprint(reordered)
    assert not summarize(mismatch, 100)["paired_measurement"][0]["stop"]
    text = render(report)
    assert "| fake | A | 100 / 100 |" in text
    assert "Candidate ms" in text and "Inference ms" in text and "MASTERMIND top-k" in text
    assert summarize(rows[:-1], 100)["paired_measurement"][0]["stop"] is False
    for i in range(5):
        rows[i*3+2]["pick"] = {"plan": ["act31", "end"]}
    assert summarize(rows, 100)["paired_measurement"][0]["stop"] is True
    rows[17]["pick"] = {"plan": ["act31", "end"]}
    assert summarize(rows, 100)["paired_measurement"][0]["stop"] is False
    rows[17]["error"], rows[17]["fallback"] = "synthetic error", True
    assert "synthetic error" in render(summarize(rows, 100))
    with pytest.raises(ValueError, match="Duplicate"):
        summarize([*rows, rows[0]], 100)


def test_archive_adapter_resolves_real_storage_layout_without_writes(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from combat.gate3_storage import encode_match_directory_name

    row, state = example()
    row["match_id"] = "match:synthetic"
    row["provider_id"] = "synthetic"
    directory = tmp_path / encode_match_directory_name(row["match_id"])
    directory.mkdir()
    calls = []
    def capture_menus(path):
        calls.append(path)
        yield state["view"], state["legal"], {
            "decision_id": row["decision_id"], "dao_policy_top2": ["act0", "act1"]}
    monkeypatch.setitem(sys.modules, "tools.score_seat_tactics",
                        SimpleNamespace(capture_menus=capture_menus))
    found = replay.archive_states(tmp_path, [row], {"synthetic": state["provider"]})
    assert calls == [directory]
    assert found[replay.identity(row)]["legal"] == state["legal"]
    assert found[replay.identity(row)]["provider"] == state["provider"]
    assert list(directory.iterdir()) == []  # No repairing store/save writes.
    assert replay.archive_states(tmp_path, [{**row, "match_id": "match:absent"}],
                                 {"synthetic": state["provider"]}) == {}
    assert calls == [directory]


def test_caps_safety_psi_selection_and_append_resume(tmp_path, monkeypatch):
    matches = tmp_path / "matches"
    matches.mkdir()
    psi = tmp_path / "io"
    psi.write_text("some avg10=0 avg60=0 avg300=0 total=0\nfull avg10=0 avg60=6 avg300=0 total=0\n")
    sleeps = []
    def sleep(seconds):
        sleeps.append(seconds)
        psi.write_text("full avg10=0 avg60=5 avg300=0 total=0\n")
    replay.wait_idle(matches, [psi], sleep=sleep)
    assert sleeps == [5]
    fight = matches / "owner"
    fight.mkdir()
    (fight / "FactoryIntegration.json").write_text('{"paused": false}')
    (fight / "GenesisState.json").write_text('{"state": {"terminal_result": null}}')
    (fight / "Journal.ndjson").write_text("")
    with pytest.raises(RuntimeError, match="Active owner"):
        replay.check_owner_idle(matches)
    (fight / "FactoryIntegration.json").write_text('{"paused": true}')
    replay.check_owner_idle(matches)
    row, state = example()
    records = [{**row, "state": state},
               {**row, "kind": "REACTION", "decision_id": "reaction", "state": state}]
    assert len(replay.select_records(records, 1)) == 1
    assert len(replay.select_records([*records, row], 200)) == 2
    decisions, output = tmp_path / "decisions.jsonl", tmp_path / "result.jsonl"
    decisions.write_text(json.dumps({**row, "state": state}) + "\n")
    fake = Fake()
    monkeypatch.setattr(replay, "ModelClient", lambda *a: fake)
    monkeypatch.setattr(replay.os, "setpriority", lambda *a: None)
    args = ["--decisions", str(decisions), "--endpoint", "http://invalid.example",
            "--protocol", "openai", "--model", "fake", "--arm", "C", "--out", str(output),
            "--live-matches", str(matches), "--psi", str(psi), "--max-decisions", "1"]
    assert replay.main(args) == 0
    assert replay.main(args) == 0
    assert len(list(replay.jsonl(output))) == 1 and len(fake.calls) == 1
    with pytest.raises(SystemExit):
        replay.main([*args, "--max-decisions", "201"])


@pytest.mark.parametrize("protocol", ["openai", "d1", "local-app", "systemone"])
def test_protocol_payloads_are_fake_transport_only(monkeypatch, protocol):
    row, state = example(32)
    prompt, offered = replay.frame(row, state, "C")
    calls = []
    def request(self, path, body=None, headers=None):
        calls.append((path, body))
        if path == "/session":
            return {"token": "synthetic"}
        if path == "/chat/completions":
            return {"choices": [{"message": {"content": "A"}}]}
        answer = {"choice": "A", "probabilities": {k: int(k == "A") for k in offered}}
        return {"answers": {"action": answer}} if "questions" in body else answer
    monkeypatch.setattr(replay.ModelClient, "request", request)
    client = replay.ModelClient("http://invalid.example", protocol, "fake")
    if protocol == "local-app":
        # Fits or fails by the ACTUAL serialized app frame; never trims C.
        prompt += "\n" + "x" * 7000
        with pytest.raises(ValueError, match="6000"):
            client(prompt, offered, state["provider"])
        assert calls == []
    else:
        assert client(prompt, offered, state["provider"])["choice"] == "A"
        assert len([p for p, _ in calls if p != "/session"]) == 1
        if protocol == "systemone":
            assert "P27" in calls[-1][1]["questions"]["action"]["criteria"]
