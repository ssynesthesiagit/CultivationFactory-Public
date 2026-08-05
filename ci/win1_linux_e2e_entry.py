from __future__ import annotations

import win1_linux_e2e as harness


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


harness.choose_method = _choose_method

if __name__ == "__main__":
    raise SystemExit(harness.main())
