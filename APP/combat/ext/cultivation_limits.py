"""Native typed producers for explicit Source-authorized cultivation restrictions.

Effects must be authored in a Source's typed effects, after its printed save or
contest. This module supplies persistence/expiry and never grants a new power.
The canonical cultivation_limit effect also accepts an explicit foundation_id
with foundation_disabled/passives_allowed flags or a foundation_max_stage cap;
activation_requirements reads these source-scoped rules. No Foundation fields
means no change to Foundation eligibility.
"""
from . import effect, hook


def alignment_admitted(engine, actor, typed):
    # No native restriction, no extra source lookup or eligibility work on the
    # hot menu/AI path. Only this explicit producer writes the canonical row.
    if not any(c.condition_id == "condition:typed.cultivation_limit" for c in actor.conditions.values()):
        return None
    from ..cultivation_access import alignment_available
    from ..technique_alignment import eligible
    from ..typed_numbers import authority_mechanics
    source = authority_mechanics().get(typed.get("source") or typed.get("feature_id")) or {}
    profile = {"sphere": source.get("sphere_id"), "tags": source.get("tags") or [],
               "elemental_alignments": source.get("elemental_alignments") or [], **typed}
    options = eligible(profile)
    if options and not any(alignment_available(engine, actor, element) for element in options):
        return False
    return None


@hook("candidate_allowed")
def candidate_alignment(engine, actor, candidate, action):
    return alignment_admitted(engine, actor, (getattr(action, "parameters", None) or {}).get("typed") or {})


@hook("row_allowed")
def reaction_alignment(engine, actor, row):
    return alignment_admitted(engine, actor, row)


@effect("cultivation_limit", harmful=True)
def apply_limit(ctx, row):
    from ..typed_executor import effect_subjects, effect_expiry
    from ..technique_alignment import ELEMENTS
    rule = {}
    if "cl_cap" in row:
        if type(row["cl_cap"]) is not int or not 0 <= row["cl_cap"] <= 20:
            raise ValueError("An effective cultivation level must be an integer from 0 to 20")
        rule["cultivation_cl_cap"] = row["cl_cap"]
    if "element" in row:
        if row["element"] not in ELEMENTS:
            raise ValueError("An elemental suppression needs a printed element")
        rule["suppressed_element"] = row["element"]
    if "foundation_id" in row:
        foundation = row["foundation_id"]
        if not isinstance(foundation, str) or not foundation:
            raise ValueError("A Foundation restriction needs its source-defined Foundation id")
        rule["foundation_id"] = foundation
        for key in ("foundation_disabled", "foundation_passives_allowed"):
            if key in row:
                if type(row[key]) is not int or row[key] not in (0, 1):
                    raise ValueError("Foundation restrictions use explicit zero or one flags")
                rule[key] = row[key]
        if "foundation_max_stage" in row:
            if row["foundation_max_stage"] not in ("Awakened", "Refined", "Perfected"):
                raise ValueError("A Foundation stage cap must name a printed stage")
            rule["foundation_max_stage"] = row["foundation_max_stage"]
        if not ("foundation_disabled" in rule or "foundation_max_stage" in rule):
            raise ValueError("A Foundation restriction needs an explicit disabled flag or stage cap")
    if not rule or not row.get("duration") and not row.get("expires_on"):
        raise ValueError("A cultivation restriction needs an explicit limit and duration")
    label = (f"Cultivation limited to level {row['cl_cap']}" if "cl_cap" in row
             else f"{row['element'].title()} techniques suppressed" if "element" in row
             else "Foundation abilities restricted by the source effect")
    for target in effect_subjects(ctx, row, harmful=True):
        ctx.engine._apply_condition(target, "condition:typed.cultivation_limit", ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, row, target, condition=True),
            data={"rule": rule, "source_cl": int(ctx.numbers.get("cl") or 0), "label": label})
