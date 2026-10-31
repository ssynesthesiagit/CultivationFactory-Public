"""Saving-throw proficiency provenance shared by grants and Lightning Grounding.

Numeric save totals never establish proficiency. Factory bundles seal the
explicit sheet list; temporary grants live in evented conditions and expire
with their source. Queries do not mutate state or infer missing statistics.
"""


def base(engine, actor, ability):
    bundle = next((b for b in getattr(engine, "typed_bundle_documents", ())
                   if b.get("actor_id") == actor.entity_id), None)
    if bundle is not None and "save_proficiencies" in bundle:
        return ability.upper() in bundle["save_proficiencies"]
    # Migration: a saved fight whose bundle predates the sealed key kept its proficiency only on the
    # Grounding Breath passive row (proficient_saves). Current bundles never carry that row.
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
    return any(ability.upper() in row.get("proficient_saves", [])
               for row in rows if row.get("block") == "grounding_breath")


def is_proficient(engine, actor, ability):
    from .typed_executor import is_active_typed_condition
    code = ability.upper()
    return base(engine, actor, code) or any(
        is_active_typed_condition(c) and code in
        (((c.data or {}).get("rule") or {}).get("save_bonus") or {}).get("proficiency", ())
        for c in actor.conditions.values())
