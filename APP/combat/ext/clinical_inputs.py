"""Default-inert owner-authored clinical sources; no inferred classifications.

Uses existing match_initialize and presentation_hidden_conditions hooks.
Input validation and the trusted private-file entry point live in the public
combat.clinical_sources module. Conditions are private; only authorized readers
receive source labels in a clinical consumer's choice, never in public pills.
"""
from . import hook
from .. import clinical_sources as sources


@hook("match_initialize")
def clinical_setup(engine):
    rows = [row for bundle in engine.typed_bundle_documents
            for row in bundle.get(sources.SETUP, [])]
    required = {row["subject"] for row in rows}
    required.update(reader for row in rows for reader in row["readers"])
    if not required <= set(engine.state.actors):
        return  # saved state replaces the preliminary constructor roster
    for bundle in engine.typed_bundle_documents:
        rows = bundle.get(sources.SETUP)
        if rows is None:
            continue
        # Replay constructors can first build a preliminary stock roster.
        if bundle["actor_id"] not in engine.state.actors:
            continue
        rows = sources.validate_sources(rows, set(engine.state.actors))
        for row in rows:
            sources.apply_source(engine, engine.state.actors[row["subject"]], row)


@hook("presentation_hidden_conditions")
def private_clinical_sources(engine, actor):
    return [iid for iid, held in actor.conditions.items() if sources.DATA in held.data] or None
