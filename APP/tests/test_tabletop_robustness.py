"""Run the page coordination regressions against its real function bodies."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat.tabletop_service import TabletopService


def test_page_coordination():
    subprocess.run(["node", str(Path(__file__).with_name("tabletop_robustness.cjs"))], check=True)


@pytest.mark.parametrize("code,status,expected", [
    ("COMBAT_CONTENT_NOT_READY", 409, 2),
    ("COMBAT_MATCH_NOT_FOUND", 404, 1),
    ("OTHER", 409, 1),
])
def test_state_load_retries_only_transient_conflict(tmp_path, monkeypatch, code, status, expected):
    class LoadError(Exception):
        diagnostic = SimpleNamespace(code=code)
        status_code = status

    calls = []
    session = object()

    def load(match_id):
        calls.append(match_id)
        if len(calls) == 1:
            raise LoadError()
        return session

    monkeypatch.setattr("combat.tabletop_service.time.sleep", lambda _: None)
    table = TabletopService(SimpleNamespace(_load_session=load), tmp_path)
    if expected == 2:
        assert table._load_state_session("fight") is session
    else:
        with pytest.raises(LoadError):
            table._load_state_session("fight")
    assert len(calls) == expected


def test_state_load_retry_stops_after_second_failure(tmp_path, monkeypatch):
    class LoadError(Exception):
        diagnostic = SimpleNamespace(code="COMBAT_CONTENT_NOT_READY")
        status_code = 409

    calls = []

    def load(match_id):
        calls.append(match_id)
        raise LoadError()

    monkeypatch.setattr("combat.tabletop_service.time.sleep", lambda _: None)
    table = TabletopService(SimpleNamespace(_load_session=load), tmp_path)
    with pytest.raises(LoadError):
        table._load_state_session("fight")
    assert len(calls) == 2
