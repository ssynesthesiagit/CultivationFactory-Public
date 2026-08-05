from __future__ import annotations

from playwright.sync_api import Locator

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


def _choose_method(options):
    choices = harness.find_category(options, "method_choice").get("choices") or []
    compatible = [
        row
        for row in choices
        if harness.QI_PATH in set(row.get("related_choice_ids") or [])
        and not (row.get("method_planning") or {}).get("direct_initial_acquisition_available")
        and (row.get("method_planning") or {}).get("owner_route_options")
    ]
    if not compatible:
        raise AssertionError(
            "No source-backed Qi Method requiring an owner acquisition route is available."
        )
    method = compatible[0]
    routes = (method.get("method_planning") or {}).get("owner_route_options") or []
    route = next(
        (row for row in routes if row.get("typed_route") != "CUSTOM_DOCUMENTED_ROUTE"),
        routes[0],
    )
    return method, route


_original_fill = Locator.fill


def _fill_hidden_production_control(
    locator: Locator,
    value: str,
    *,
    force: bool | None = None,
    no_wait_after: bool | None = None,
    timeout: float | None = None,
) -> None:
    selector = getattr(getattr(locator, "_impl_obj", None), "_selector", "")
    if selector == "#sheetMethodLearningNote":
        force = True
    _original_fill(
        locator,
        value,
        force=force,
        no_wait_after=no_wait_after,
        timeout=timeout,
    )


harness.select_option_when_ready = _select_option_when_ready
harness.choose_method = _choose_method
Locator.fill = _fill_hidden_production_control

if __name__ == "__main__":
    raise SystemExit(harness.main())
