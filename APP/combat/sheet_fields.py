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


def published_total(value: Any, *, default: int | None = None) -> int:
    """Read a published total; legacy placeholders can default, but integer zero is a total."""
    if default is not None and not value and type(value) is not int:
        return default
    return int(value)


def skill_ability(name: str | None, explicit: str | None = None) -> str:
    """An explicit skill ability wins over the standard ability for its name."""
    if explicit:
        return explicit
    from .tabletop import SKILLS

    return next((ability for skill, ability in SKILLS if skill == name), "")


def initiative_ability(row: dict[str, Any]) -> str:
    """Initiative follows Dexterity unless the sheet explicitly says otherwise."""
    return row.get("ability") or "DEX"


def key_ability(identity: dict[str, Any]) -> str:
    """Read the ability that supplies the compiler's key modifier."""
    return str(identity.get("key_ability") or "INT").upper()[:3]


def armor_class_basis(value: Any) -> tuple[int, int]:
    """Read (base calculation, folded standing bonuses) from published AC.

    The base can be replaced by armour; standing bonuses apply afterwards.
    A single published AC number is the base, with no separate bonus.
    """
    armor = decode(value)
    if not isinstance(armor, dict):
        return published_total(armor or 10), 0
    base = published_total(armor.get("base_value") or armor.get("value") or 10)
    return base, published_total(armor.get("value") or base) - base


def maximum_hp(stats: dict[str, Any]) -> int | None:
    """Return the published positive integer maximum, or None if invalid."""
    hit_points = decode(stats.get("hit_points"))
    raw = hit_points.get("maximum") if isinstance(hit_points, dict) else None
    try:
        maximum = published_total(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return maximum if maximum > 0 and not isinstance(raw, (bool, float)) else None


def overall_cl(identity: dict[str, Any]) -> int:
    """Return acquired Cultivation Level, not the effective (suppressed) level."""
    return int(identity.get("cultivation_level") or identity.get("cl") or 1)
