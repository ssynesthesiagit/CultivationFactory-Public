from __future__ import annotations

from typing import Any

import win1_linux_e2e as harness
from character_builder import CharacterBuilderService


LEVEL_TALENT_CLS = (1, 2, 3, 4, 5)
SELECTED_FIRE_TALENT_IDS: list[str] = []
SELECTED_BACKGROUND_ROUTE: dict[str, Any] = {}


def _select_option_when_ready(page, selector: str, value: str, *, timeout: int = 120_000) -> None:
    if selector == "#sheetBackgroundTalent":
        sphere_choice_id = SELECTED_BACKGROUND_ROUTE.get("background_sphere_choice_id")
        if not sphere_choice_id:
            raise AssertionError("The exact Abandoned-Orphan background route was not resolved.")
        page.wait_for_function(
            "value => Array.from(document.querySelector('#sheetBackgroundSphere')?.options || []).some(o => o.value === value)",
            arg=sphere_choice_id,
            timeout=timeout,
        )
        page.locator("#sheetBackgroundSphere").select_option(sphere_choice_id, force=True)
    page.wait_for_function(
        "([selector, value]) => Array.from(document.querySelector(selector)?.options || []).some(o => o.value === value)",
        arg=[selector, value],
        timeout=timeout,
    )
    page.locator(selector).select_option(value, force=True)


def _choose_background_route(options: dict[str, Any]) -> dict[str, Any]:
    background = next(
        (
            row
            for row in harness.find_category(options, "background_choice").get("choices") or []
            if row.get("choice_id") == harness.ABANDONED_ORPHAN
        ),
        None,
    )
    routes = ((background or {}).get("ns1r_exact_route_authority") or {}).get("route_options") or []
    route = next(
        (
            row
            for row in routes
            if row.get("background_talent_choice_id") == harness.HIDDEN_TOOL_CACHE
        ),
        None,
    )
    if not route:
        raise AssertionError(
            "No exact Abandoned-Orphan route binds Hidden Tool Cache to its background Sphere."
        )
    return route


def _choose_method(options):
    global SELECTED_BACKGROUND_ROUTE
    SELECTED_BACKGROUND_ROUTE = _choose_background_route(options)
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


def _server_committed_catalog_plan(db, project_id: str) -> tuple[list[str], dict[str, str], list[str]]:
    project = CharacterBuilderService(db).projects.get_project(project_id)["project"]
    locks = {
        lock.get("field"): lock.get("value")
        for lock in project.get("user_locks", [])
        if isinstance(lock, dict) and isinstance(lock.get("field"), str)
    }
    plan = locks.get("character_creation.committed_catalog_choice_plan")
    accounting = plan.get("grant_accounting") if isinstance(plan, dict) else None
    acquired = plan.get("acquired_canonical_sphere_ids") if isinstance(plan, dict) else None
    free_rows = accounting.get("free_sphere_talent_grants") if isinstance(accounting, dict) else None
    ordinary = accounting.get("ordinary_talent_ids") if isinstance(accounting, dict) else None
    if (
        not isinstance(plan, dict)
        or plan.get("schema") != "TianxiaFactory.CanonicalGrantPlan.v1"
        or plan.get("ready") is not True
        or not isinstance(acquired, list)
        or len(acquired) != 1
        or not isinstance(free_rows, list)
        or len(free_rows) != 1
        or not isinstance(ordinary, list)
        or len(ordinary) != len(LEVEL_TALENT_CLS)
    ):
        raise AssertionError(
            "The normal wizard did not leave one ready server-validated first-cycle catalog plan."
        )
    free = free_rows[0]
    if not isinstance(free, dict) or free.get("sphere_id") != acquired[0] or not isinstance(free.get("talent_id"), str):
        raise AssertionError(f"The committed free Talent does not match the committed Sphere: {free!r}.")
    if not all(isinstance(talent_id, str) for talent_id in ordinary):
        raise AssertionError(f"The committed ordinary Talent IDs are not typed strings: {ordinary!r}.")
    return list(acquired), {acquired[0]: free["talent_id"]}, list(ordinary)


def _stage2_expected_revision(db, project_id: str) -> int:
    project = CharacterBuilderService(db).projects.get_project(project_id)["project"]
    locks = {
        lock.get("field"): lock.get("value")
        for lock in project.get("user_locks", [])
        if isinstance(lock, dict) and isinstance(lock.get("field"), str)
    }
    expected = int(project["revision"]) + 1
    method_mode = locks.get("character_sheet.method_planning_mode")
    method_access_plan = locks.get("character_sheet.method_access_plan")
    if method_mode in {"EXACT", "HARD_LOCK"} and isinstance(method_access_plan, dict) and method_access_plan:
        expected += 1
    return expected


def _complete_plan_with_source_backed_fire_progression(db, project_id):
    global SELECTED_FIRE_TALENT_IDS
    acquired_spheres, free_talent_grants, SELECTED_FIRE_TALENT_IDS = _server_committed_catalog_plan(db, project_id)
    if acquired_spheres != [harness.FIRE] or free_talent_grants != {harness.FIRE: "FIRE_TAL_FLAME_LASH"}:
        raise AssertionError(
            "The bounded Linux E2E expects the normal wizard's server plan to be the canonical Fire first-cycle route. "
            f"Got spheres={acquired_spheres!r}, free={free_talent_grants!r}."
        )
    plan = _original_complete_plan(db, project_id)
    plan["stage2_proposal"]["expected_project_revision"] = _stage2_expected_revision(db, project_id)
    sphere_rows = [
        row
        for row in plan["stage2_proposal"]["choices"]
        if row.get("kind") == "ai_bootstrap_sphere_acquisition"
    ]
    free_rows = [
        row
        for row in plan["stage2_proposal"]["choices"]
        if row.get("kind") == "ai_bootstrap_talent_acquisition"
    ]
    if len(sphere_rows) != len(acquired_spheres) or len(free_rows) != len(free_talent_grants):
        raise AssertionError(
            "The Stage 2 fixture does not expose the committed first-cycle Sphere/free-Talent slots."
        )
    for row, sphere_id in zip(sphere_rows, acquired_spheres, strict=True):
        row["record_id"] = sphere_id
    for row, sphere_id in zip(free_rows, acquired_spheres, strict=True):
        row["record_id"] = free_talent_grants[sphere_id]
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


harness.select_option_when_ready = _select_option_when_ready
harness.choose_method = _choose_method
harness.complete_plan = _complete_plan_with_source_backed_fire_progression

if __name__ == "__main__":
    raise SystemExit(harness.main())
