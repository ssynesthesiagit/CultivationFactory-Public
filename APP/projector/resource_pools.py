"""Owner-sheet resource rows shared by creation and table Path acquisition."""
from copy import deepcopy
from typing import Any


def resource_display_name(resource_id: str) -> str:
    return resource_id.rsplit(".", 1)[-1].replace("_", " ").title()


def resource_pool_row(resource_id: str, *, maximum: int, current: int, formula_id: str,
                      authority_components: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "resource_id": resource_id,
        "name": resource_display_name(resource_id),
        "current": current,
        "max": maximum,
        "formula_id": formula_id,
        "authority_components": deepcopy(authority_components) if authority_components is not None else [],
    }
