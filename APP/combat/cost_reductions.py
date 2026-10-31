"""Temporary cost reductions a creature carries -- one ordinary temporary benefit.

Printed examples: Erode Technique's trigger names "a cost reduction from an ordinary
temporary effect", Nullification Seal lists "one cost reduction" among the temporary
benefits it can suppress, and Hollowed stops a creature "reducing a technique's cost
below its listed cost". The engine represents one such benefit as a modifier on the
creature it helps whose target field is ``cost_reduction:<resource>`` and whose
integer value is the number of points it takes off that resource's listed cost.

Anything that grants one writes that modifier -- the typed ``cost_reduction`` effect
block in combat/typed_executor.py is the general producer. combat/technique_costs.py
reads every live row in the ordinary cost quote (``Engine.effective_costs``, used by
availability, payment and the plug-in quotes), so suppressing, expiring or removing
the benefit puts the cost back to its listed value. A row is an ordinary modifier: it
persists, expires and is suppressed by combat/ext/benefit_suppression.py like any
other temporary benefit.

Shared by combat/technique_costs.py (the cost quote) and
combat/ext/benefit_suppression.py (the plain-language name of the benefit).
"""
from __future__ import annotations

from typing import Any

PREFIX = "cost_reduction:"


def field(resource_id: str) -> str:
    """The modifier target field one temporary reduction of ``resource_id`` is filed under."""
    return PREFIX + str(resource_id)


def resource(field_name: Any) -> str:
    """The resource a ``cost_reduction:<resource>`` field reduces; "" for any other field."""
    name = str(field_name or "")
    return name[len(PREFIX):] if name.startswith(PREFIX) else ""


def reductions(actor: Any, totals: dict[str, int]) -> dict[str, int]:
    """{resource: points off} from the live temporary reductions ``actor`` owns.

    Only listed resources are answered, only nonnegative integers count, and a
    reduction never takes more than the resource's quoted amount.
    """
    cuts: dict[str, int] = {}
    for modifier in actor.modifiers.values():
        resource_id = resource(modifier.target_field)
        if not resource_id or resource_id not in totals:
            continue
        value = modifier.value
        if type(value) is not int or value <= 0:
            continue
        cuts[resource_id] = cuts.get(resource_id, 0) + value
    return {resource_id: min(totals[resource_id], cut) for resource_id, cut in cuts.items() if cut}


def apply(actor: Any, rows) -> tuple[tuple[str, int], ...]:
    """``rows`` with every live temporary reduction taken off, in their original order."""
    totals: dict[str, int] = {}
    for resource_id, amount in rows:
        totals[resource_id] = totals.get(resource_id, 0) + amount
    cuts = reductions(actor, totals)
    if not cuts:
        return tuple(rows)
    result = []
    for resource_id, amount in rows:
        cut = min(amount, cuts.get(resource_id, 0))
        cuts[resource_id] = cuts.get(resource_id, 0) - cut
        result.append((resource_id, amount - cut))
    return tuple(result)
