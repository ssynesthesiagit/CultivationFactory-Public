"""Start Over confirm text (review 012915 finding 3).

The confirm shown before Start Over cancels an unfinished build must not show
an internal run id or a raw status. It says what the owner gets: the character
is kept as a Saved Draft.
"""
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"


def test_start_over_confirm_names_no_run_id_or_raw_status():
    lines = [line for line in APP_JS.read_text(encoding="utf-8").splitlines() if "unfinished build" in line]
    assert len(lines) == 1, lines
    line = lines[0]
    assert "run_id" not in line
    assert "run.status" not in line
    assert "WAITING_FOR_RESPONSE" not in line
    assert "Saved Draft" in line
    assert "Choose Cancel to return to the build." in line
