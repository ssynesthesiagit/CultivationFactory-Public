"""Paged compact prompts must budget the actual model-facing instructions."""
import json

import pytest

from agent_seats import SeatRunner
from agent_seats.compact import PROMPT_BUDGET, TINY_PROMPT_BUDGET
from agent_seats.providers import ProviderRegistry
from agent_seats.menu_pages import RankedPages
from agent_seats.protocol import build_prompt


@pytest.mark.parametrize("profile,budget", [("compact", PROMPT_BUDGET), ("tiny", TINY_PROMPT_BUDGET)])
@pytest.mark.parametrize("more", [True, False], ids=["has-more", "final-page"])
def test_paged_no_primer_near_cap_dispatches(tmp_path, monkeypatch, profile, budget, more):
    from combat import menu_rank

    mid = "synthetic"
    view = {"fighter": "me", "round": 1,
            "actors": [{"entity_id": "me", "display_name": "Fighter", "position": {"x": 1, "y": 1}}],
            "map": {"width": 10 if more else 3, "height": 10 if more else 3}}
    moves = [f"move-{i}" for i in range(6)] if more else []
    legal = {key: {"action": "Move", "source": "Move", "targets": [],
                   "destination": {"x": i, "y": 1}} for i, key in enumerate(moves)}
    legal["hit"] = {"action": "Attack", "source": "weapon", "targets": []}
    legal["end"] = {"action": "End turn", "source": "End turn", "targets": []}
    ranked = ["hit", *moves]
    pages = RankedPages(legal, ranked, "hit", 4)
    view["actors"][0]["padding"] = ""
    base = build_prompt(view, pages.display_menu(), "hit", "", "TURN", 3, None, profile, ranked)
    steps_note = (" You may reply with active steps without End to build a plan; "
                  "choose End explicitly to finish. Steps already chosen: []. Reply DETAILS followed by a current menu key "
                  "to read its next full rules page without acting.")
    headroom = 40 if more else len(steps_note)
    view["actors"][0]["padding"] = "x" * (budget - headroom - len(base))
    unnoted = build_prompt(view, pages.display_menu(), "hit", "", "TURN", 3, None, profile, ranked)
    assert len(unnoted) == budget - headroom

    prompts = []
    def model(config, prompt, png):
        prompts.append(prompt)
        return json.dumps({"plan": ["hit", "end"]}), None

    class Table:
        def _match_dir(self, match_id):
            return tmp_path

    registry = tmp_path / "providers.json"
    registry.write_text(json.dumps({"providers": [{"id": "fake", "kind": "local", "model": "offline",
        "base_url": "http://127.0.0.1:1/v1", "timeout_s": 10, "prompt_profile": profile}]}))
    runner = SeatRunner(Table(), registry=ProviderRegistry(registry), provider=model, background=False)
    monkeypatch.setattr(menu_rank, "enabled", lambda: True)
    answer = runner._decide(mid, "me", {"provider_id": "fake"}, view, legal,
                            "hit", "", "TURN", ranked, slot_ranked=True)
    assert answer == {"plan": ["hit", "end"], "fallback": False}, runner.decisions(mid)
    assert len(prompts) == 1 and len(prompts[0]) <= budget
    instructions = prompts[0].split("\n", 1)[0]
    assert ("Reply MORE" in instructions) == more
    assert instructions.endswith(steps_note)
    if not more:
        assert len(prompts[0]) == budget
