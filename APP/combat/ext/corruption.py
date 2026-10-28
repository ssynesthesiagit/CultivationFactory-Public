"""Effective Corruption: shared helper module for the one number a reader reports.

Used by combat/display_values.py (the table's resource rows) and by any rules reader that
reports a creature's Corruption; combat/ext/mgr_reserve_bell_tower_cultivator_watch_bell.py
publishes the suppressions it reads.

Corruption has two carriers on this table. The persistent pool
``resource:named.corruption`` (authority ``resources.corruption``: pool, maximum 10,
persistent, starting at 0) holds the Corruption a creature keeps, and that pool is what a
cost spends or a gain fills. A temporary Corruption is an ongoing effect classified
``temporary_corruption`` (combat/ext/information_sources.TAGS); each live effect holds one
point of ITS OWN source's Corruption, so a temporary point belongs to its effect rather
than to the persistent pool. Printed suppressions act on "one point of temporary
Corruption", never on an unrelated effect and never on the persistent pool.

A suppression is ordinary committed state, not code: an active condition on the holder
whose data carries ``temporary_corruption`` =
``{'source_instance': <effect instance id>, 'points': <positive int>}``. The Bell-Tower
plug-in publishes Purifying Peal's and Returning Clarity's suppression on that contract
(its ``corruption_suppressed`` condition); any producer may use the same one. Only the
named instance's points are suppressed -- a second source keeps its own -- and the
engine's own condition lifetime ends the suppression, so the point returns when the
printed duration runs out.

A marker written before this contract carried the same two facts at the top level of the
condition's data (``source_instance``, ``points``). It is read the same way, so a fight
saved before the contract keeps the suppression it recorded; a marker that names neither
is ignored rather than guessed at.

``total`` is the effective Corruption a reader reports; ``combat/display_values`` serves it
to the table, and any rules reader may import it. A suppression leaves the stored pool
alone, so spending and gain still read ``actor.resources``.
"""
from __future__ import annotations

from typing import Any

CORRUPTION = 'resource:named.corruption'
TAG = 'temporary_corruption'
# A marker written before this contract is recognised by its own condition id naming the
# suppression, so an unrelated condition that happens to carry a ``points`` counter is
# never read as one.
LEGACY_ID = 'corruption_suppressed'


def suppressions(actor: Any) -> dict[str, int]:
    """This holder's live suppressions: temporary-Corruption effect instance id -> points."""
    totals: dict[str, int] = {}
    for condition in getattr(actor, 'conditions', {}).values() or ():
        data = getattr(condition, 'data', None) or {}
        if isinstance(data.get(TAG), dict):
            row = data[TAG]
        elif LEGACY_ID in str(getattr(condition, 'condition_id', '')):
            row = data
        else:
            continue
        instance, points = row.get('source_instance'), row.get('points')
        if not isinstance(instance, str) or not instance or type(points) is not int or points < 1:
            continue
        totals[instance] = totals.get(instance, 0) + points
    return totals


def declared(actor: Any) -> bool:
    """Cheap check: does this holder carry any effect that carries a temporary Corruption?"""
    for condition in getattr(actor, 'conditions', {}).values() or ():
        profile = (getattr(condition, 'data', None) or {}).get('information_profile') or {}
        if TAG in (profile.get('tags') or ()):
            return True
    return False


def points(engine: Any, actor: Any) -> int:
    """Effective temporary Corruption points: each live effect's own point, less its suppression."""
    if not declared(actor):
        return 0
    from .. import observer_information
    live = [source for source in observer_information.sources(engine, actor.entity_id)
            if TAG in source['tags']]
    if not live:
        return 0
    suppressed = suppressions(actor)
    return sum(max(0, 1 - suppressed.get(source['id'], 0)) for source in live)


def total(engine: Any, actor: Any) -> int:
    """Effective Corruption: the persistent pool plus this creature's temporary points."""
    return int((getattr(actor, 'resources', None) or {}).get(CORRUPTION) or 0) + points(engine, actor)
