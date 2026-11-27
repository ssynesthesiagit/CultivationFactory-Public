"""Read owner-sheet fields for the fight compiler and table score projection."""

from typing import Any, NamedTuple

from .ability_scores import ABILITIES


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


def canonical_skill_name(name: str | None) -> str:
    """Use the standard name for case and underscore variants; preserve other names."""
    from .tabletop import SKILLS

    name = str(name or "")
    key = name.replace("_", " ").casefold()
    return next((skill for skill, _ in SKILLS if skill.casefold() == key), name)


def skill_ability(name: str | None, explicit: str | None = None) -> str:
    """An explicit skill ability wins over the standard ability for its name."""
    if explicit:
        return explicit
    from .tabletop import SKILLS

    name = canonical_skill_name(name)
    return next((ability for skill, ability in SKILLS if skill == name), "")


class SkillRow(NamedTuple):
    ability: str
    total: int
    rank: int | None
    source: dict[str, Any]


def skill_rows(stats: dict[str, Any], mods: dict[str, int]) -> dict[str, SkillRow]:
    """Read each listed skill once, keeping the first canonical match.

    The total and explicit rank are independent. Keep the source for callers
    writing a projected row or displaying a label, not for interpreting numbers.
    """
    from .ability_checks import proficiency_rank

    rows = {}
    for row in decode(stats.get("skills")) or []:
        if not isinstance(row, dict) or not row.get("skill"):
            continue
        name = canonical_skill_name(row["skill"])
        if name not in rows:
            ability = skill_ability(name, row.get("ability"))
            total = published_total(row.get("bonus"), default=mods.get(ability, 0))
            rows[name] = SkillRow(ability, total, proficiency_rank(row), row)
    return rows


def published_skill_totals(stats: dict[str, Any], mods: dict[str, int]) -> dict[str, int]:
    """The totals view for callers that do not need proficiency provenance."""
    return {name: row.total for name, row in skill_rows(stats, mods).items()}


def saving_throw_totals(stats: dict[str, Any], mods: dict[str, int], pb: int) -> dict[str, int]:
    """A published save already includes proficiency; only the fallback adds it."""
    recorded = decode(stats.get("saving_throws")) or {}
    if isinstance(recorded, list):
        recorded = {row["ability"]: row["bonus"] for row in recorded
                    if isinstance(row, dict) and row.get("ability") in ABILITIES and row.get("bonus") is not None}
    declared = decode(stats.get("saving_throw_proficiencies"))
    proficient = declared if isinstance(declared, list) else []
    return {ability: published_total(recorded.get(ability, mods.get(ability, 0) + (pb if ability in proficient else 0)))
            for ability in ABILITIES}


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
