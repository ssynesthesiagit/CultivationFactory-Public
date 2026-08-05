from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from playwright.sync_api import Locator

import win1_linux_e2e as harness


FREE_FIRE_TALENT_ID = "FIRE_TAL_FLAME_LASH"
PREFERRED_FIRST_FIRE_TALENT_ID = "FIRE_TAL_BURNING_WEAPON"
PREFERRED_FINAL_FIRE_TALENT_ID = "FIRE_TAL_FIREBALL_ART"
LEVEL_TALENT_CLS = (1, 2, 3, 4, 5)
SELECTED_FIRE_TALENT_IDS: list[str] = []
SELECTED_FIRE_TALENT_DETAILS: list[dict[str, Any]] = []


def _select_option_when_ready(page, selector: str, value: str, *, timeout: int = 120_000) -> None:
    page.wait_for_function(
        "([selector, value]) => Array.from(document.querySelector(selector)?.options || []).some(o => o.value === value)",
        arg=[selector, value],
        timeout=timeout,
    )
    page.locator(selector).select_option(value, force=True)


def _minimum_cl(choice: dict[str, Any]) -> int:
    for key in ("minimum_cl", "min_cl", "minimum_cultivation_level"):
        value = choice.get(key)
        if isinstance(value, int):
            return value
    access = choice.get("access") or {}
    for key in ("minimum_cl", "min_cl", "minimum_cultivation_level"):
        value = access.get(key)
        if isinstance(value, int):
            return value
    return 1


def _collect_talent_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        if "_TAL_" in value or value.startswith("TAL_"):
            found.add(value)
    elif isinstance(value, dict):
        for child in value.values():
            found.update(_collect_talent_ids(child))
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        for child in value:
            found.update(_collect_talent_ids(child))
    return found


def _prerequisite_talent_ids(choice: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for key, value in choice.items():
        lowered = key.lower()
        if "prereq" in lowered or "required_talent" in lowered or "requires_talent" in lowered:
            found.update(_collect_talent_ids(value))
        elif isinstance(value, dict):
            found.update(_prerequisite_talent_ids(value))
    found.discard(choice.get("choice_id"))
    return found


def _fire_talent_choices(options: dict[str, Any]) -> list[dict[str, Any]]:
    talent_category = harness.find_category(options, "advancement_skeleton")
    choices = {
        row.get("choice_id"): row
        for row in talent_category.get("choices") or []
        if isinstance(row, dict) and isinstance(row.get("choice_id"), str)
    }
    fire_ids = list(
        ((options.get("sphere_talent_index") or {}).get("by_sphere") or {}).get(harness.FIRE)
        or []
    )
    result = [
        choices[talent_id]
        for talent_id in fire_ids
        if isinstance(talent_id, str)
        and talent_id in choices
        and choices[talent_id].get("planning_priority_available") is not False
    ]
    if not result:
        result = [
            row
            for row in choices.values()
            if harness.FIRE in set(row.get("related_choice_ids") or [])
            and row.get("planning_priority_available") is not False
        ]
    return result


def _choose_fire_progression(options: dict[str, Any]) -> list[str]:
    choices = _fire_talent_choices(options)
    by_id = {row["choice_id"]: row for row in choices}
    if FREE_FIRE_TALENT_ID not in by_id:
        raise AssertionError(
            f"The canonical Fire free Talent {FREE_FIRE_TALENT_ID} is unavailable."
        )
    candidates = [row for row in choices if row["choice_id"] != FREE_FIRE_TALENT_ID]
    selected: list[str] = []
    acquired = {FREE_FIRE_TALENT_ID}

    def eligible(row: dict[str, Any], cl: int) -> bool:
        return (
            row["choice_id"] not in acquired
            and _minimum_cl(row) <= cl
            and _prerequisite_talent_ids(row).issubset(acquired)
        )

    for index, cl in enumerate(LEVEL_TALENT_CLS):
        available = [row for row in candidates if eligible(row, cl)]
        if not available:
            raise AssertionError(
                "The canonical Fire catalog cannot supply a legal five-Talent CL1-5 progression. "
                f"Stopped at CL {cl}; acquired={sorted(acquired)}; "
                f"remaining={[row['choice_id'] for row in candidates if row['choice_id'] not in acquired]}."
            )
        preferred_id = (
            PREFERRED_FIRST_FIRE_TALENT_ID
            if index == 0
            else PREFERRED_FINAL_FIRE_TALENT_ID
            if index == len(LEVEL_TALENT_CLS) - 1
            else None
        )
        preferred = next((row for row in available if row["choice_id"] == preferred_id), None)
        if preferred is None:
            available.sort(
                key=lambda row: (
                    len(_prerequisite_talent_ids(row)),
                    _minimum_cl(row),
                    str(row.get("canonical_name") or row.get("name") or row["choice_id"]),
                    row["choice_id"],
                )
            )
            preferred = available[0]
        selected.append(preferred["choice_id"])
        acquired.add(preferred["choice_id"])

    global SELECTED_FIRE_TALENT_DETAILS
    SELECTED_FIRE_TALENT_DETAILS = [
        {
            "choice_id": talent_id,
            "name": by_id[talent_id].get("canonical_name") or by_id[talent_id].get("name"),
            "minimum_cl": _minimum_cl(by_id[talent_id]),
            "prerequisite_talent_ids": sorted(_prerequisite_talent_ids(by_id[talent_id])),
            "effective_cl": cl,
        }
        for talent_id, cl in zip(selected, LEVEL_TALENT_CLS, strict=True)
    ]
    return selected


def _choose_method(options):
    global SELECTED_FIRE_TALENT_IDS
    SELECTED_FIRE_TALENT_IDS = _choose_fire_progression(options)
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


_original_complete_plan = harness.complete_plan


def _complete_plan_with_source_backed_fire_progression(db, project_id):
    if len(SELECTED_FIRE_TALENT_IDS) != len(LEVEL_TALENT_CLS):
        raise AssertionError("The canonical Fire Talent progression was not selected before Stage 2 planning.")
    plan = _original_complete_plan(db, project_id)
    rows = [
        row
        for row in plan["stage2_proposal"]["choices"]
        if row.get("kind") == "level_talent_acquisition"
    ]
    if len(rows) != len(SELECTED_FIRE_TALENT_IDS):
        raise AssertionError(
            f"Expected {len(SELECTED_FIRE_TALENT_IDS)} level Talent slots, found {len(rows)}."
        )
    for row, talent_id, expected_cl in zip(
        rows,
        SELECTED_FIRE_TALENT_IDS,
        LEVEL_TALENT_CLS,
        strict=True,
    ):
        if row.get("effective_cl") != expected_cl:
            raise AssertionError(
                f"Unexpected Talent slot sequence: expected CL {expected_cl}, got {row.get('effective_cl')}."
            )
        row["record_id"] = talent_id
    return plan


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
        if len(SELECTED_FIRE_TALENT_IDS) != len(LEVEL_TALENT_CLS):
            raise AssertionError("The source-backed Fire Talent progression was not available for catalog locking.")
        page = locator.page
        page.wait_for_function("Boolean(guidedProjectId)", timeout=120_000)
        payload = {
            "acquired_sphere_ids": [harness.FIRE],
            "free_talent_grants": {harness.FIRE: FREE_FIRE_TALENT_ID},
            "ordinary_talent_ids": SELECTED_FIRE_TALENT_IDS,
        }
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
            payload,
        )
        if locked.get("grant_plan", {}).get("ready") is not True:
            raise AssertionError(f"Canonical catalog choice lock was not ready: {locked}")
    return result


harness.select_option_when_ready = _select_option_when_ready
harness.choose_method = _choose_method
harness.complete_plan = _complete_plan_with_source_backed_fire_progression
Locator.fill = _fill_hidden_production_control
Locator.click = _click_with_catalog_choice_lock

if __name__ == "__main__":
    raise SystemExit(harness.main())
