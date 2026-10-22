"""Printed Sphere prerequisites for native Subpath/Tradition acquisition.

Shared by NonSphereAuthorityService.select_subpath (the persisted native
acquisition path) and combat/authority_projection.py (the combat compile
bridge). A Subpath whose printed requirement names a Sphere is admitted only
when the character supplies that exact Sphere; a name, tag or a loose effect
is not acquisition.

Void-Touched Cultivator prints "Required Sphere: Void, or an equivalent Secret
principle of absence". This build certifies only the Void Sphere: no separate
"equivalent Secret principle of absence" record exists, so an absent Void
Sphere is refused rather than silently admitted by name.
"""

PREREQUISITE_SPHERES: dict[str, frozenset[str]] = {
    'tianxia.subpath.qi.void_touched_cultivator': frozenset({'tianxia.sphere.void'}),
}


def required_spheres(subpath_id: str) -> frozenset[str]:
    """The exact Spheres that admit this Subpath (empty: it has no printed Sphere gate)."""
    return PREREQUISITE_SPHERES.get(subpath_id, frozenset())


def met(sphere_ids: object, subpath_id: str) -> bool:
    """True when one of the supplied Sphere record IDs satisfies the printed gate.

    An empty requirement is always met. A non-Sphere name, a tag or an unowned
    row in ``sphere_ids`` does not satisfy the gate: only canonical Sphere
    record IDs are read.
    """
    required = required_spheres(subpath_id)
    if not required:
        return True
    supplied = sphere_ids if isinstance(sphere_ids, (list, tuple, set, frozenset)) else ()
    return any(isinstance(row, str) and row in required for row in supplied)
