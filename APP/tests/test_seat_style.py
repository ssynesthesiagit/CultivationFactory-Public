"""A model seat's play style overrides its provider's prompt profile; offline, real table commits."""
import json

import pytest

from agent_seats.choices import PROMPT_BYTES
from combat.gate4_controller import LocalDeterministicController
from combat.tabletop import TabletopError
from tests.test_agent_seats import runner_for, raw_state
from tests.test_hunt5_player_choices import fixture, PLAYER, FOE
from tests.test_seat_choices import configure


def _end_first_turn(runner, table, mid):
    state = raw_state(runner, mid)
    table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"], [])


def test_short_list_style_overrides_a_whole_turn_provider(tmp_path):
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    seen = []
    def model(config, prompt, png):
        seen.append((config["prompt_profile"], prompt))
        return "A", None
    runner, _ = runner_for(tmp_path, table, model, timeout=10)
    configure(runner, "full")
    _end_first_turn(runner, table, mid)
    assert runner.set_seat(mid, PLAYER, "MODEL", "fake", "choices")["style"] == "choices"
    assert runner.seats(mid)[PLAYER] == {"control": "MODEL", "provider_id": "fake", "style": "choices"}
    assert runner.drive(mid, max_steps=3) >= 1
    assert seen and all(profile == "choices" for profile, _ in seen)
    assert all(len(prompt.encode()) <= PROMPT_BYTES for _, prompt in seen)
    assert not runner.decisions(mid)[0]["fallback"]


def test_whole_turn_style_overrides_a_short_list_provider(tmp_path):
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    seen = []
    def model(config, prompt, png):
        seen.append(config["prompt_profile"])
        return "not json", None
    runner, _ = runner_for(tmp_path, table, model, timeout=10)
    configure(runner, "choices")
    _end_first_turn(runner, table, mid)
    runner.set_seat(mid, PLAYER, "MODEL", "fake", "full")
    runner.drive(mid, max_steps=1)
    assert seen and set(seen) == {"full"}


def test_no_style_keeps_the_provider_profile_and_switching_model_clears_it(tmp_path):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, _ = runner_for(tmp_path, table, lambda *a: ("A", None), timeout=10)
    configure(runner, "choices")
    runner.set_seat(mid, PLAYER, "MODEL", "fake", "full")
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    assert runner.seats(mid)[PLAYER] == {"control": "MODEL", "provider_id": "fake"}
    assert any(row.get("prompt_profile") == "choices" for row in runner.registry.public())


@pytest.mark.parametrize("control, provider, style", [
    ("AI", None, "choices"), ("MANUAL", None, "full"), ("MODEL", "fake", "tiny"), ("MODEL", "fake", "anything"),
])
def test_invalid_styles_are_refused(tmp_path, control, provider, style):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, _ = runner_for(tmp_path, table, lambda *a: ("A", None), timeout=10)
    with pytest.raises(TabletopError):
        runner.set_seat(mid, PLAYER, control, provider, style)
    assert PLAYER not in runner.seats(mid)


@pytest.mark.parametrize("provider_profile", ["compact", "tiny"])
def test_whole_turn_style_lifts_a_compact_or_tiny_provider(tmp_path, provider_profile):
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    seen = []
    def model(config, prompt, png):
        seen.append(config["prompt_profile"])
        return "not json", None
    runner, _ = runner_for(tmp_path, table, model, timeout=10)
    configure(runner, provider_profile)
    _end_first_turn(runner, table, mid)
    runner.set_seat(mid, PLAYER, "MODEL", "fake", "full")
    runner.set_seat(mid, PLAYER, "MODEL", "fake", "full")  # re-applying a saved override keeps it
    assert runner.seats(mid)[PLAYER]["style"] == "full"
    runner.drive(mid, max_steps=1)
    assert seen and set(seen) == {"full"}
