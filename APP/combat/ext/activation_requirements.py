"""Pre-spend dependencies for owned actions and generic reactions.

Compiled typed metadata may supply requires_compiled_actions: exact
action IDs that must exist in this actor's action_ids and the action catalogue.
It may also supply min_cl: a printed "Prerequisite: CL N+" construction gate,
read against the actor's own compiled Cultivation Level (typed numbers.cl,
baked when the character was compiled).
Candidate regeneration and reaction admission check before any payment. A generic
reaction row carries the same gate on row_allowed, the path _can_trigger consults for
every generic row, so a plug-in that admits its own row without _subject_ok reads it too
(Thousand-Grain Grip answering the escape check). This is not a substitute implementation
for a missing action (for example Tumble). Absent metadata leaves older fights and
unrelated characters unchanged.
"""
from . import hook


def min_cl_ready(actor, row, *, engine=None):
    """"Prerequisite: CL N+" on its own: False below the printed gate, else None (no opinion)."""
    min_cl = row.get('min_cl')
    if min_cl is None:
        return None
    cl = int((row.get('numbers') or {}).get('cl') or 1)
    if engine is not None:
        from ..cultivation_access import effective_cl
        cl = effective_cl(engine, actor, cl)
    if cl < int(min_cl):
        return False  # this character is below the printed gate.
    return None


def dependencies_ready(engine, actor, row):
    """Pure readiness shared by primary and reaction admission."""
    below_gate = min_cl_ready(actor, row, engine=engine)
    if below_gate is False:
        return below_gate
    required = row.get('requires_compiled_actions')
    if required is None:
        return None
    owned = set(engine.actor_templates[actor.entity_id].action_ids)
    if not isinstance(required, list) or not required or any(
            not isinstance(source, str) or source not in owned or source not in engine.action_catalog
            for source in required):
        return False
    return None


@hook('candidate_allowed')
def candidate_ready(engine, actor, candidate, action):
    return dependencies_ready(engine, actor, (getattr(action, 'parameters', None) or {}).get('typed') or {})


@hook('reaction_subject_allowed')
@hook('reaction_ally_allowed')
def reaction_ready(engine, actor, subject, row):
    return dependencies_ready(engine, actor, row)


@hook('row_allowed')
def generic_row_below_printed_gate(engine, actor, row):
    """The printed CL gate on a generic reaction row, on the admission path every generic row takes.

    ``_can_trigger`` consults row_allowed for every generic row (combat/typed_reactions.py), so a
    plug-in that admits its own row through _can_trigger instead of _subject_ok still reads the
    gate: Thousand-Grain Grip, which offers the burier's compiled "moved" row on its Action
    escape check (combat/ext/sand_burial.py _offer_grip). Absent min_cl, inert.
    """
    return min_cl_ready(actor, row, engine=engine)
