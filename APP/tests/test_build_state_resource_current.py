"""A Path resource in the deterministic build state stays as full as it was.

Before this rule the first calculated maximum pinned ``current`` forever, so a
CL 20 sheet showed Qi 0/40 and Stamina 2/26 with no spending event anywhere.
"""
from __future__ import annotations

from stage2.service import _resource_current_after


def test_first_calculation_starts_full():
    assert _resource_current_after(None, 0) == 0
    assert _resource_current_after(None, 7) == 7


def test_growth_of_the_maximum_raises_current_with_it():
    prior = {"resource_id": "tianxia.resource.qi", "current": 0, "maximum": 0}
    assert _resource_current_after(prior, 2) == 2
    prior = {"resource_id": "tianxia.resource.stamina", "current": 2, "maximum": 2}
    assert _resource_current_after(prior, 26) == 26


def test_an_existing_deficit_is_preserved_never_refilled():
    spent = {"resource_id": "tianxia.resource.stamina", "current": 3, "maximum": 10}
    assert _resource_current_after(spent, 10) == 3
    assert _resource_current_after(spent, 16) == 9
    assert _resource_current_after(spent, 5) == 0
    assert _resource_current_after(spent, 6) == 0
    assert _resource_current_after({"current": 4}, 4) == 4
