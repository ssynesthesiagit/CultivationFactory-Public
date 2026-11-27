"""Read owner-sheet fields for the fight compiler and table score projection."""

from typing import Any


def decode(value):
    """Accept native lists/dicts or their JSON encodings."""
    import json

    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def published_total(value: Any) -> int:
    """Read a published save or skill total with fight admission's integer coercion."""
    return int(value)


def maximum_hp(stats: dict[str, Any]) -> int | None:
    """Return the published positive integer maximum, or None if invalid."""
    hit_points = decode(stats.get("hit_points"))
    raw = hit_points.get("maximum") if isinstance(hit_points, dict) else None
    try:
        maximum = int(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return maximum if maximum > 0 and not isinstance(raw, (bool, float)) else None


def overall_cl(identity: dict[str, Any]) -> int:
    """Return acquired Cultivation Level, not the effective (suppressed) level."""
    return int(identity.get("cultivation_level") or identity.get("cl") or 1)
