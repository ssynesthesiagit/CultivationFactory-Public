"""Offline navigation convergence at the seat runner's provider boundary."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from agent_seats.choices import decision_payload, option_description, step_label
from agent_seats.menu_pages import RankedPages, choice_frame, tactical_situation, text_page
from agent_seats.providers import ProviderRegistry
from agent_seats.runner import SeatRunner


def seat(tmp_path, monkeypatch, provider, kind="local"):
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    monkeypatch.setenv("FACTORY_SEAT_RECORDS", "0")
    registry = tmp_path / "providers.json"
    registry.write_text(json.dumps({"providers": [{
        "id": "offline", "kind": kind, "model": "offline",
        "base_url": "http://127.0.0.1:1", "timeout_s": 10,
        "prompt_profile": "choices", "choices_bytes": 800,
    }]}))
    table = SimpleNamespace(_match_dir=lambda mid: tmp_path,
                            combat=SimpleNamespace(userdata_root=tmp_path))
    return SeatRunner(table, registry=ProviderRegistry(registry), provider=provider,
                      background=False, render_png=lambda view: None)


def menu():
    view = {"fighter": "hero", "actors": [{
        "entity_id": "hero", "display_name": "Fighter",
        "position": {"x": 1, "y": 2}, "resources": {},
    }], "information": ["Observed fact %02d: The stone floor is wet. é" % i for i in range(15)]}
    legal = {str(i): {"action": "Strike %d" % i, "targets": [],
                     "cost_label": "1 Action", "description": "Deal damage. é " * 100 + "Final rule."}
             for i in range(4)}
    return view, legal


@pytest.mark.parametrize("kind", ["local", "d1"])
@pytest.mark.parametrize("letter", ["I", "K", "L"])
def test_navigation_preference_exhausts_pages_then_selects_action(tmp_path, monkeypatch, kind, letter):
    view, legal = menu()
    original = deepcopy(legal)
    prompts, replies = [], []
    # Independent byte bounds: situation pages hold 160 bytes; rules rendering
    # always reserves at least 40. Menu pages contain one active choice each.
    value = (tactical_situation(view) if letter == "I" else
             step_label(legal["0"], {}) + ": " + option_description(legal["0"], legal))
    bound = (len(value.encode()) // (160 if letter == "I" else 40) + 2
             if letter != "L" else len(legal) + 1)

    def provider(config, prompt, png):
        prompts.append(prompt)
        assert len(prompts) <= bound, "Navigation did not converge"
        offered = decision_payload(prompt)["options"]
        # Prefer the navigation on EVERY reply, but never invent an unavailable
        # letter. Once all pages are read the provider must choose an action.
        reply = letter if letter in offered else "B"
        replies.append(reply)
        return reply, None

    runner = seat(tmp_path, monkeypatch, provider, kind)
    answer = runner._decide("fight", "hero", {"provider_id": "offline"}, view,
                            legal, "0", "", "TURN", ["0"])
    expected = str(len(legal) - 1) if letter == "L" else "0"
    assert answer == {"plan": [expected], "fallback": False}, runner.decisions("fight")
    row = runner.decisions("fight")[-1]
    assert row["fallback"] is None and row["invalid_replies"] == 0
    assert len(prompts) == row["attempts"] <= bound
    assert len(prompts) > 1 and replies == [letter] * (len(prompts) - 1) + ["B"]
    assert letter not in decision_payload(prompts[-1])["options"]
    assert legal == original
    if letter == "I":
        chunks = [p.split("· Resources: ", 1)[1].split("\n", 1)[1]
                  .split("\nChoose a follow-up.", 1)[0] for p in prompts]
        assert "".join(chunks) == tactical_situation(view)
        assert len(prompts) <= len(tactical_situation(view).encode()) // 160 + 2
    elif letter == "K":
        chunks = [p.split("\nB) ", 1)[1].split(": ", 1)[1]
                  .split(" [display shortened;", 1)[0] for p in prompts]
        assert "".join(chunks) == value
    else:
        assert len(prompts) == len(legal)
        assert "J" in decision_payload(prompts[-1])["options"]
        assert [p.split("\nB) ", 1)[1].split(" (", 1)[0] for p in prompts] == [
            "Strike %d" % i for i in range(len(legal))]


@pytest.mark.parametrize("letter", ["I", "K", "L"])
def test_one_navigation_then_action_preserves_the_chosen_step(tmp_path, monkeypatch, letter):
    view, legal = menu()
    # Include End to exercise staged plan assembly, not only follow-up actions.
    legal["end"] = {"action": "End turn", "targets": []}
    replies = iter([letter, "B", "A"])
    prompts = []

    def provider(config, prompt, png):
        prompts.append(prompt)
        reply = next(replies)
        assert reply in decision_payload(prompt)["options"]
        return reply, None

    runner = seat(tmp_path, monkeypatch, provider)
    answer = runner._decide("fight", "hero", {"provider_id": "offline"}, view,
                            legal, "0", "", "TURN", ["0"])
    assert answer == {"plan": ["1" if letter == "L" else "0", "end"], "fallback": False}
    assert len(prompts) == 3
    assert runner.decisions("fight")[-1]["invalid_replies"] == 0


def test_final_frame_has_only_actions_and_back():
    view, legal = menu()
    pages = RankedPages(legal, ["0"], "0", 1)
    while pages.has_more(set(pages.menu())):
        pages.advance(set(pages.menu()))
    for _ in range(200):
        prompt, answers, _ = choice_frame(view, pages, 800)
        if "I" in answers:
            pages.situation_offset = pages.next_situation_offset
        elif "K" in answers:
            pages.detail_offset = pages.next_detail_offset
        else:
            break
    assert set(answers) == {"B", "J"}
    assert "(cycles)" not in prompt


def test_text_pages_do_not_wrap_after_the_end():
    assert text_page("é", 2, 160) == ("", 2, False)
