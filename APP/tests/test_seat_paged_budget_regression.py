"""Paged compact prompts must budget the actual model-facing instructions."""
import json

import pytest

from agent_seats import SeatRunner
from agent_seats.compact import PROMPT_BUDGET, TINY_PROMPT_BUDGET
from agent_seats.providers import ProviderRegistry
from agent_seats.menu_pages import RankedPages
from agent_seats.protocol import build_prompt


@pytest.mark.parametrize("profile,budget", [("compact", PROMPT_BUDGET), ("tiny", TINY_PROMPT_BUDGET)])
def test_paged_no_primer_near_cap_dispatches(tmp_path, monkeypatch, profile, budget):
    from combat import menu_rank

    mid = "synthetic"
    view = {"fighter": "me", "round": 1,
            "actors": [{"entity_id": "me", "display_name": "Fighter", "position": {"x": 1, "y": 1}}],
            "map": {"width": 10, "height": 10}}
    moves = [f"move-{i}" for i in range(6)]
    legal = {key: {"action": "Move", "source": "Move", "targets": [],
                   "destination": {"x": i, "y": 1}} for i, key in enumerate(moves)}
    legal["hit"] = {"action": "Attack", "source": "weapon", "targets": []}
    legal["end"] = {"action": "End turn", "source": "End turn", "targets": []}
    ranked = ["hit", *moves]
    pages = RankedPages(legal, ranked, "hit", 4)
    view["actors"][0]["padding"] = ""
    base = build_prompt(view, pages.display_menu(), "hit", "", "TURN", 3, None, profile, ranked)
    view["actors"][0]["padding"] = "x" * (budget - 40 - len(base))
    unnoted = build_prompt(view, pages.display_menu(), "hit", "", "TURN", 3, None, profile, ranked)
    assert budget - 300 <= len(unnoted) <= budget

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
    assert "Reply MORE" in prompts[0] and "Steps already chosen: []" in prompts[0]
