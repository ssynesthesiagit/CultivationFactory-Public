"""Hunt 45 regression: seeded Quick Build starts and completes without an AI identity."""

import time
from pathlib import Path

from app.api import create_app
from app.core import Settings
from product_bootstrap.service import ProductBootstrapService


APP = Path(__file__).resolve().parents[1]


def test_seeded_quick_build_runs_through_creation_service_without_ai(tmp_path, monkeypatch):
    monkeypatch.setenv("TIANXIA_BROWSER_EXECUTABLE", str(tmp_path / "BROWSER_FORBIDDEN"))
    settings = Settings.from_env(APP, tmp_path / "userdata")
    ProductBootstrapService(settings).run()
    app = create_app(settings)
    batch = app.state.quick_builds.submit(
        items=[{"route": "seeded", "seed": "H45-OWNER-1"}],
        target_cl=3,
        finalize=False,
    )

    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        current = next(row for row in app.state.quick_builds.list() if row["batch_id"] == batch["batch_id"])["items"][0]
        if current["status"] in {"failed", "ready", "needs_review", "finished", "interrupted"}:
            break
        time.sleep(0.1)

    assert current["status"] in {"ready", "needs_review", "finished"}, current
    assert current["run_id"], current
    run = app.state.character_creation.get(current["run_id"])
    assert run["request"]["autogen_seed"] == "H45-OWNER-1"
    binding = run["request"]["controller_route_binding"]
    assert binding["selected_ai_identity_sha256"] is None
    assert binding["selected_ai_identity_state"] == "SEEDED_NO_AI_IDENTITY"
    events = app.state.character_creation.linear_walk.events(current["run_id"])
    mechanical = [event["payload"] for event in events
                  if event["event_type"] == "STEP_COMMITTED"
                  and event["payload"].get("step_id", "").split(":", 1)[0]
                  in {"point_buy_preset", "point_buy_assignment", "background_ability"}]
    assert mechanical
    assert all(event.get("build_choice_reason") for event in mechanical)
