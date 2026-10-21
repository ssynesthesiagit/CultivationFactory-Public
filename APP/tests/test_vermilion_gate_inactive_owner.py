"""Regression: an inactive (defeated/removed) actor is never a Vermilion Gate owner.

Before the fix, `_owners()` admitted any actor listed as the owner of a Heaven's Closed Gate action even when the
actor was inactive; the role branch was covered by `available()`, but the gate-owner branch had no liveness check.
"""
from combat.ext import vermilion_gate as vg
from tests.test_riders_c7 import _gate


def test_inactive_gate_owner_is_not_an_owner():
    engine, me, foe = _gate(["heavens_closed_gate"])
    assert me in vg._owners(engine)  # precondition: the living owner is recognised
    me.active = False
    assert me not in vg._owners(engine)
    assert all(owner.active for owner in vg._owners(engine))
