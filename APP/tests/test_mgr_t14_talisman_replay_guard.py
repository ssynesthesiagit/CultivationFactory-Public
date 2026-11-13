"""The unowned guard tolerates shared main changes and rejects lane-only changes."""
import json
from types import SimpleNamespace

import pytest

from tests import talisman_unowned_capture as capture


def test_auto10_guard_uses_resolved_mainline_instead_of_historical_digest(tmp_path, monkeypatch):
    from tests import replay_base, test_auto10_talismans

    compared = []
    monkeypatch.setattr(replay_base, "replay_base_or_skip", lambda: "merged-mainline")
    monkeypatch.setattr(capture, "compare", lambda scratch, base: compared.append((scratch, base)))
    test_auto10_talismans.test_an_unowned_ai_fight_matches_the_pre_lane_capture(tmp_path)
    assert compared == [(tmp_path, "merged-mainline")]


@pytest.mark.parametrize("lane_changed", [False, True])
def test_unowned_guard_compares_selected_base_and_every_persisted_event(tmp_path, monkeypatch, lane_changed):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["env"]["CF_EMBED_MENU"] == "0"
        # A new mainline event payload need not match a historical hardcoded hash.
        events = [{"event_type": "MAINLINE_EVENT", "payload": {"roll": 17}} for _ in range(22)]
        if lane_changed and len(commands) == 2:
            events[-1]["payload"] = {"roll": 18}
        return SimpleNamespace(returncode=0, stdout=json.dumps({"steps": 8, "events": events}), stderr="")

    monkeypatch.setattr(capture.subprocess, "run", run)
    if lane_changed:
        with pytest.raises(AssertionError):
            capture.compare(tmp_path, "selected-mainline")
    else:
        capture.compare(tmp_path, "selected-mainline")
    assert commands[0][-1] == "selected-mainline"
    assert commands[1][-1] == str(tmp_path / "head")


def test_unowned_guard_rejects_failed_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(capture.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=1, stdout="", stderr="capture failed"))
    with pytest.raises(AssertionError, match="capture failed"):
        capture.compare(tmp_path, "selected-mainline")
