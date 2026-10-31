from __future__ import annotations

from pathlib import Path

from tests.rec1_p1cr3_ux1_rendered_harness import CHROMIUM, OWNER_STEPS, VIEWPORTS, fixture_run


ROOT = Path(__file__).resolve().parents[1]


def test_rendered_campaign_is_pinned_to_required_production_browser_and_viewports() -> None:
    assert CHROMIUM == str(Path.home() / ".cache/ms-playwright/chromium-1228/chrome-linux64/chrome")
    # 80fee3e0 (owner 2026-09-13): the wizard is four steps; the former
    # steps 5-8 are collapsed sections of step 4, "Your character".
    assert OWNER_STEPS == tuple(range(1, 5))
    assert VIEWPORTS == (
        (1920, 1080),
        (1536, 864),
        (1366, 768),
        (1280, 720),
        (860, 900),
        (768, 900),
        (390, 844),
    )
    assert (ROOT / "static/index.html").is_file()
    assert (ROOT / "static/styles.css").is_file()
    assert (ROOT / "static/app.js").is_file()


def test_declared_visual_fixture_has_terminal_step_four_one_next_action() -> None:
    run = fixture_run("run", "project", status="CANCELLED")
    owner = run["owner_view"]
    assert run["status"] == "CANCELLED"
    assert owner["display_state"]["step"] == 4
    assert owner["next_legal_action"]["target_step"] == 1
    assert "canonical" in owner["next_legal_action"]["description"]
