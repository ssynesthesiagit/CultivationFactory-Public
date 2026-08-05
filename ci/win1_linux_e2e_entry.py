from __future__ import annotations

from playwright.sync_api import Locator

import win1_linux_e2e as harness


CATALOG_CHOICE_PAYLOAD = {
    "acquired_sphere_ids": [harness.FIRE],
    "free_talent_grants": {
        harness.FIRE: "FIRE_TAL_FLAME_LASH",
    },
    "ordinary_talent_ids": [
        "FIRE_TAL_BURNING_WEAPON",
        "TAL_SCOUNDREL_CLEANED_OUT",
        "TAL_SCOUNDREL_DOUBLE_DIP",
        "TAL_SCOUNDREL_FANCY_FOOTWORK",
        "FIRE_TAL_FIREBALL_ART",
    ],
}


def _select_option_when_ready(page, selector: str, value: str, *, timeout: int = 120_000) -> None:
    page.wait_for_function(
        "([selector, value]) => Array.from(document.querySelector(selector)?.options || []).some(o => o.value === value)",
        arg=[selector, value],
        timeout=timeout,
    )
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
_original_click = Locator.click


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


def _click_with_catalog_choice_lock(
    locator: Locator,
    *,
    modifiers=None,
    position=None,
    delay=None,
    button=None,
    click_count=None,
    timeout=None,
    force=None,
    no_wait_after=None,
    trial=None,
    steps=None,
) -> None:
    selector = getattr(getattr(locator, "_impl_obj", None), "_selector", "")
    result = _original_click(
        locator,
        modifiers=modifiers,
        position=position,
        delay=delay,
        button=button,
        click_count=click_count,
        timeout=timeout,
        force=force,
        no_wait_after=no_wait_after,
        trial=trial,
        steps=steps,
    )
    if selector == "#guidedBuildButton" and not trial:
        page = locator.page
        page.wait_for_function("Boolean(guidedProjectId)", timeout=120_000)
        locked = page.evaluate(
            """async payload => {
              const response = await fetch(
                `/api/character-builder/projects/${encodeURIComponent(guidedProjectId)}/catalog-choice-lock`,
                {
                  method: 'POST',
                  headers: {
                    'X-Foundry-Token': token,
                    'Content-Type': 'application/json',
                  },
                  body: JSON.stringify(payload),
                },
              );
              const data = await response.json();
              if (!response.ok) throw new Error(JSON.stringify(data));
              return data;
            }""",
            CATALOG_CHOICE_PAYLOAD,
        )
        if locked.get("grant_plan", {}).get("ready") is not True:
            raise AssertionError(f"Canonical catalog choice lock was not ready: {locked}")
    return result


harness.select_option_when_ready = _select_option_when_ready
harness.choose_method = _choose_method
Locator.fill = _fill_hidden_production_control
Locator.click = _click_with_catalog_choice_lock

if __name__ == "__main__":
    raise SystemExit(harness.main())
