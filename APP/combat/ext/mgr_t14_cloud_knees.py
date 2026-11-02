"""White Crane Cloud-Step: the Cloud-Step Crane Vessel's Speed contribution.

The Vessel's printed contribution ("your Speed increases by 5 feet while
you are not wearing armor or restraints that prevent light footwork")
compiles as one native motion row. Its own typed record states the +5
(source-scoped chassis data, read through the record the compiler
passes); the compiler's worn-armor fact gates the printed footwork
condition at compile time, and restraints that prevent light footwork
need no gate because the engine already gives a Grappled or restrained
creature Speed 0. The Vessel's maximum-Hit-Points projection is folded
into the sheet at character creation (the foundations4 policy) and is
never added a second time in combat; its Advantage-on-balance-checks
clause stays a GM clause.

Refined: Open-Cloud Knees ("its Speed bonus becomes +10 feet ... This
modifies the passive chassis and does not require an action, Reaction,
or Crane Breath spend") REPLACES that single contribution through the
existing compile_passives seam, driven by the Refined record's own
modifier data: its named target (the Vessel) and its typed speed
effect. One effective contribution -- never a second row, never an
addition, no action and no resource spend.
"""

from typing import Any

from . import hook

VESSEL = "foundation.white_crane_cloud_step_v0_2B.cloud_step_crane_vessel"
REFINED = "foundation.white_crane_cloud_step_v0_2B.refined_open_cloud_knees"
BLOCK = "cloud_knees_vessel"
TARGET_NAME = "cloud-step crane vessel"


def _speed_flat(record: dict[str, Any] | None) -> int | None:
    """The single self Speed contribution a record states, or None."""
    values = {effect.get("flat") for effect in ((record or {}).get("effects") or [])
              if isinstance(effect, dict) and effect.get("type") == "speed"
              and effect.get("applies_to", "self") == "self"}
    value = values.pop() if len(values) == 1 else None
    return value if type(value) is int else None


@hook("compile_block")
def vessel_block(block: str, spec: dict[str, Any], row: dict[str, Any], info: dict[str, Any]):
    """The Vessel's always-active Speed contribution as one motion row.

    Worn armor fails the printed footwork condition, so an armored
    fighter compiles no contribution (the number stays off its combat
    sheet entirely). Restraints that prevent light footwork are
    already native Speed 0, so they need no compile-time gate.
    """
    if block != BLOCK:
        return None
    flat = _speed_flat(info.get("record"))
    if flat is None or info.get("armor"):
        return []  # no typed contribution, or the footwork condition fails
    return [{**row, "block": "motion", "kind": "speed_bonus", "ft": flat}]


@hook("compile_passives")
def refined_cloud_knees(passives: list[dict[str, Any]], info: dict[str, Any]):
    """Refined: Open-Cloud Knees replaces the Vessel's one Speed contribution.

    The replacement is driven by the Refined record's own modifier
    data: its named target (the Vessel) and its typed speed effect.
    With the Refined owner compiled, the Vessel's single motion row
    carries the modifier's +10 instead of the chassis's +5 -- one
    effective contribution, never a second row and never an addition.
    Without the Refined owner, and for old saved bundles that never
    carried the row, everything is exactly as it was; every unrelated
    passive row is preserved.
    """
    if REFINED not in (info.get("owned_ids") or ()):
        return None
    from ..typed_numbers import authority_mechanics

    modifier = ((info.get("mechanics") or {}).get(REFINED) or {}).get("modifier") or {}
    if TARGET_NAME not in {str(target).strip().lower() for target in modifier.get("targets") or ()}:
        return None  # the modifier no longer names the chassis: nothing to replace
    flat = _speed_flat({"effects": modifier.get("effects") or []})
    if flat is None:
        return None
    result = []
    replaced = False
    for row in passives:
        if (isinstance(row, dict) and row.get("feature_id") == VESSEL
                and row.get("block") == "motion" and row.get("kind") == "speed_bonus"):
            row = {**row, "ft": flat}  # replaces the base contribution
            replaced = True
        result.append(row)
    return result if replaced else None


@hook("compile_bundle")
def modifier_report(bundle: dict[str, Any], info: dict[str, Any]):
    """The Refined modifier's report row matches what actually happened.

    apply_modifiers only attaches named modifiers to compiled actions,
    so the Refined modifier's row still reads as an unapplied passive
    target even though this plug-in's compile_passives transform
    applied its speed effect to the Vessel's compiled contribution.
    When the replacement compiled, the row reports the Vessel as its
    applied target, the way the compiler reports modifiers it runs in
    its own code (factory_compiler.HANDLED_IN_CODE). An armored
    fighter compiles no Vessel contribution, so its row stays as the
    compiler wrote it.
    """
    modifiers = bundle.get("modifiers") or []
    index = next((position for position, row in enumerate(modifiers)
                  if isinstance(row, dict) and row.get("id") == REFINED), None)
    if index is None or modifiers[index].get("status") == "applied":
        return None
    if not any(isinstance(row, dict) and row.get("feature_id") == VESSEL
               and row.get("block") == "motion" and row.get("kind") == "speed_bonus"
               for row in bundle.get("typed_passives") or ()):
        return None  # the replacement did not compile for this fighter
    from ..typed_numbers import authority_mechanics

    name = str(((info.get("mechanics") or {}).get(VESSEL) or {}).get("name") or "Cloud-Step Crane Vessel")
    row = {**modifiers[index], "status": "applied", "targets": [name],
           "applied": [name], "not_automated_targets": []}
    return {**bundle, "modifiers": [*modifiers[:index], row, *modifiers[index + 1:]]}
