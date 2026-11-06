"""Ordered execution and essential perceived situation in real seat frames."""
import pytest

from agent_seats import choices
from agent_seats.protocol import dao_line
from combat.gate4_controller import LocalDeterministicController
from tests.test_seat_choices_budget import long_menu
from tests.test_seat_dao_r1 import real_fight, menu_frame
from tests.test_agent_seats import runner_for, raw_state
from tests.test_seat_choices import configure
from tests.test_hunt5_player_choices import fixture, PLAYER


def assert_situation(prompt, view):
    own = next(a for a in view["actors"] if a["entity_id"] == view["fighter"])
    hp = own["hit_points"]
    if isinstance(hp, dict):
        hp = f"{hp['current']}/{hp['maximum']}"
    assert f"HP: {hp}" in prompt
    for actor in view["actors"]:
        p = actor["position"]
        assert f"({p['x']},{p['y']})" in prompt
        if actor is not own:
            label = "Ally" if actor["team_id"] == own["team_id"] else "Threat"
            assert f"{label}: {actor['display_name']}" in prompt
    assert "Dao:" in prompt and "…" not in prompt


@pytest.mark.parametrize("repair", [None, "invalid"])
def test_every_shortened_real_turn_frame_keeps_situation(tmp_path, monkeypatch, repair):
    combat, table, mid = real_fight(tmp_path)
    runner, _ = runner_for(tmp_path, table)
    view, legal = menu_frame(runner, combat, mid)
    primary = next(k for k, r in legal.items() if r["action"] == "Wind Lash: Pull")
    options = choices.turn_options(view, legal, primary, list(legal))
    successful = []
    for budget in range(800, 149, -25):
        monkeypatch.setattr(choices, "PROMPT_BYTES", budget)
        try:
            prompt, offered = choices.build_prompt(view, options, "TURN", legal, repair)
        except ValueError as exc:
            assert "mandatory frame" in str(exc)
            continue
        assert len(prompt.encode()) <= budget and len(offered) >= 2
        assert_situation(prompt, view)
        successful.append(budget)
    assert 800 in successful
    assert len(successful) >= 2


@pytest.mark.parametrize("mechanic", ["AIR_BASE_GATHER_CURRENT", "TAL_FENCING_FOOTWORK",
                                     "RETRIBUTION_BASE_COUNTERSTRIKE", "FIRE_TAL_BURNING_WEAPON"])
def test_real_initial_and_repair_turn_dispatch_keep_situation_or_fail_closed(tmp_path, mechanic):
    combat, table, mid, *_ = fixture(tmp_path, mechanic)
    combat.controller = LocalDeterministicController()
    prompts = []
    runner, _ = runner_for(tmp_path, table, lambda c, p, png: (prompts.append(p) or
                          ("invalid" if len(prompts) == 1 else "A"), None), timeout=10)
    configure(runner)
    state = raw_state(runner, mid)
    menu = state["menu"]
    table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"], [])
    state = raw_state(runner, mid)
    view, _ = runner.own_view(mid, state, PLAYER, combat._load_session(mid))
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    assert runner.drive(mid, max_steps=1) == 1
    if mechanic == "FIRE_TAL_BURNING_WEAPON":
        # This public Fire sheet's ranked Ignite option has 830 bytes of
        # source mechanics alone. The owner's movement requirement now drops
        # that whole alternative, rather than shortening it or hiding Move.
        assert len(prompts) == 2
        record = runner.decisions(mid)[0]
        assert not record["fallback"] and record["chosen_menu"][0]["action"] == "Move"
        assert all("Ignite" not in p for p in prompts)
    assert len(prompts) == 2
    for prompt in prompts:
        assert len(prompt.encode()) <= 800
        assert_situation(prompt, view)
    assert not runner.decisions(mid)[0]["fallback"]


@pytest.mark.parametrize("repair", [None, "invalid"])
def test_reaction_budget_keeps_all_visible_allies_and_threats(monkeypatch, repair):
    view, _ = long_menu()
    view["last_seen"] = [{"name": "Hidden enemy", "position": {"x": 98, "y": 99}}]
    legal = {"ability": "Guard", "trigger": "Enemy fighter attacks Death fighter.",
             "affected": "Death fighter", "summary": "Reduce damage by 2.", "spend_options": [0]}
    options = choices.reaction_options(legal, {"selection": "USE", "spend": 0, "option_ids": []})
    successes = 0
    for budget in range(800, 149, -25):
        monkeypatch.setattr(choices, "PROMPT_BYTES", budget)
        try:
            prompt, _ = choices.build_prompt(view, options, "REACTION", legal, repair)
        except ValueError:
            continue
        successes += 1
        assert_situation(prompt, view)
        assert "Hidden enemy" not in prompt and "98" not in prompt and "99" not in prompt
        assert len(prompt.encode()) <= budget
    assert successes > 1


def test_ordered_plans_survive_only_when_no_more_different_alternative():
    view, legal = long_menu()
    legal = {k: legal[k] for k in ("edict", "command", "end")}
    options = choices.turn_options(view, legal, "edict", ["command", "end"])
    assert [o.answer["plan"] for o in options] == [
        ["edict", "command", "end"], ["command", "edict", "end"], ["end"]]
    # The printed Burning Weapon rule makes bonus-before-hit consequential;
    # menu packing must not assert arbitrary actions commute.
    legal["different"] = dict(legal["edict"], action="Soul Gaze")
    options = choices.turn_options(view, legal, "edict", ["command", "different", "end"])
    assert options[0].answer["plan"] == ["edict", "command", "end"]
    assert options[1].answer["plan"] == ["different", "command", "end"]
    assert not any(o.answer["plan"] == ["command", "edict", "end"] for o in options)
    del legal["different"]
    legal["other_target"] = dict(legal["edict"], targets=["ally"])
    options = choices.turn_options(view, legal, "edict", ["command", "other_target", "end"])
    assert options[1].answer["plan"] == ["other_target", "command", "end"]
    assert not any(o.answer["plan"] == ["command", "edict", "end"] for o in options)


def test_compact_dao_drops_whole_clauses_without_cut_off_text():
    view, _ = long_menu()
    view["dao"] = {"name": "Air", "temperament": {"fighting": "breathes, moves, evades, lifts"}}
    assert dao_line(view, 15) == "Dao: Air: breathes, moves"
    assert dao_line(view, 10) == "Dao: Air: breathes"
    view["dao"]["temperament"]["fighting"] = "lightning follows the shortest truthful path"
    assert dao_line(view, 10).endswith("lightning follows the shortest truthful path")
