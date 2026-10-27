"""Explicit elemental eligibility shared by elemental declarations and consumers.

Only sealed Sphere identity, printed tags and explicit reviewed alignments count.
Damage type, display name, target knowledge and another actor's abilities never do.
"""
ELEMENTS = ("wood", "fire", "earth", "metal", "water")


def eligible(typed):
    found = set(typed.get("elemental_alignments") or ())
    found.update(str(tag).lower() for tag in typed.get("tags") or ())
    sphere = typed.get("sphere")
    found.update(element for element in ELEMENTS if sphere == "tianxia.sphere." + element)
    return tuple(element for element in ELEMENTS if element in found)


def powering_resource(action, owner_sheet=None):
    """Actual Path payment, or a free Sphere technique's selected Path chassis.

    A zero-cost technique still uses its character's Path; spending no Qi is not
    the same thing as canceling and refunding a paid activation.
    """
    paths = {r for r, _ in action.costs if r in {
        "resource:core.qi", "resource:core.stamina", "resource:core.resonance"}}
    if len(paths) == 1:
        return next(iter(paths))
    if not paths and owner_sheet is not None:
        name = ((owner_sheet.get("ability_scores_and_statistics") or {}).get("primary_resource") or {}).get("name", "")
        return {"Qi": "resource:core.qi", "Stamina": "resource:core.stamina",
                "Resonance": "resource:core.resonance"}.get(name)
    return None
