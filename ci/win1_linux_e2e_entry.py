from __future__ import annotations

import win1_linux_e2e as harness


def _select_option_when_ready(page, selector: str, value: str, *, timeout: int = 120_000) -> None:
    page.wait_for_function(
        "([selector, value]) => Array.from(document.querySelector(selector)?.options || []).some(o => o.value === value)",
        arg=[selector, value],
        timeout=timeout,
    )
    # Several production owner controls are intentionally hidden while their
    # surrounding card renders the owner-facing state. Selecting the real DOM
    # control with force preserves the application's normal change handlers
    # without requiring a second test-only UI.
    page.locator(selector).select_option(value, force=True)


harness.select_option_when_ready = _select_option_when_ready

if __name__ == "__main__":
    raise SystemExit(harness.main())
