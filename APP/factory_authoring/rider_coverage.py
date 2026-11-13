"""Rider locations and structural coverage shared by the builder, converter and census.

Pointers retain the enclosing option, trigger and outcome; the traversal never
moves a rider to a different execution context.
"""
from __future__ import annotations

from typing import Any, Iterator


def rider_locations(node: Any, pointer: str = "") -> Iterator[tuple[str, str, str]]:
    """Yield every array rider and nested type=rider effect, with JSON pointers."""
    if isinstance(node, list):
        for index, value in enumerate(node):
            yield from rider_locations(value, f"{pointer}/{index}")
    elif isinstance(node, dict):
        if node.get("type") == "rider":
            value = node.get("evidence") or node.get("text") or node.get("rider") or ""
            if isinstance(value, str):
                yield pointer, value, "effect_rider"
        for key, value in node.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            child = f"{pointer}/{escaped}"
            if key == "riders" and isinstance(value, list):
                for index, rider in enumerate(value):
                    if isinstance(rider, str):
                        yield f"{child}/{index}", rider, "top_level" if not pointer else "nested_array"
                    else:
                        yield from rider_locations(rider, f"{child}/{index}")
            elif isinstance(value, (dict, list)):
                yield from rider_locations(value, child)


def coverage(mechanic: dict, *, typed: bool | None = None) -> str:
    """Structural label: FULL needs typed content and no riders anywhere.

    Callers with legacy or explicitly reviewed typed content may supply
    `typed`; otherwise effects, options and modifier content decide it.
    This is not a semantic proof of runtime execution.
    """
    if typed is None:
        modifier = mechanic.get("modifier") or {}
        typed = bool(mechanic.get("effects") or mechanic.get("options")
                     or modifier.get("effects") or modifier.get("options"))
    if not typed:
        return "RIDERS_ONLY"
    return "CORE_WITH_RIDERS" if next(rider_locations(mechanic), None) else "FULL"
