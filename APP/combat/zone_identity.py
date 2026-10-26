"""Stable talent identity reads for Darkness zones.

Used by combat.senses, combat.stealth, combat.ext.dark_riders and
combat.ext.tabik_dark. Sealed source/talent IDs take precedence, including an
explicit empty talent list. Only older profiles without IDs admit immutable,
unambiguous printed headings; editable display labels are never an identity source.
"""
from typing import Any


def source_id(zone: Any) -> str | None:
    """The sealed source record, or its unambiguous legacy printed heading."""
    profile = zone.trigger_profile or {}
    source = (profile.get("source_profile") or {}).get("mechanic_id")
    if source is not None:
        return source
    from factory_authoring.printed_references import printed_reference_id

    return printed_reference_id(profile.get("name"))


def has_talent(zone: Any, mechanic_id: str) -> bool:
    profile = zone.trigger_profile or {}
    ids = profile.get("talent_ids")
    if ids is not None:
        return mechanic_id in ids
    from factory_authoring.printed_references import printed_reference_id

    return mechanic_id in [printed_reference_id(name) for name in profile.get("talents") or []]
