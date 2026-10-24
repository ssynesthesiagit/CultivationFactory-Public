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
from . import hook, effect


def effective_cl(actor, printed_cl, *, engine=None):
    """Read the two published cap contracts; missing restrictions are inert.

    Heaven's Roar writes effective_cl; Cycle of Rebirth writes
    cultivation_cl_cap. Both are explicit active condition-rule inputs, not
    alternate inferred limits. Keep one minimum reader for their consumers.
    """
    from ..typed_executor import condition_rules
    caps = [row[key] for row in condition_rules(actor, engine=engine)
            for key in ('effective_cl', 'cultivation_cl_cap') if type(row.get(key)) is int]
    return min([int(printed_cl), *caps])


@effect('cultivation_suppression')
def suppress(ctx, row):
    """A source/GM supplied effective CL, never inferred from injury or Realm names."""
    from ..typed_executor import _default_subject
    cap = row.get('effective_cl')
    if type(cap) is not int or not 1 <= cap <= 40:
        raise ValueError('Cultivation suppression needs a whole effective Cultivation Level (1–40).')
    for target in _default_subject(ctx, row, harmful=True):
        ctx.engine._apply_condition(target, 'condition:typed.cultivation_suppression', ctx.source,
            ctx.actor.entity_id, expires_on=row.get('expires_on') or 'UNTIL_REMOVED',
            data={'label': f'Cultivation suppressed to level {cap}: higher-level cultivation abilities are unavailable.',
                  'rule': {'effective_cl': cap}})


def min_cl_ready(actor, row):
    """"Prerequisite: CL N+" on its own: False below the printed gate, else None (no opinion)."""
    min_cl = row.get('min_cl')
    numbers = row.get('numbers') or {}
    if min_cl is not None and effective_cl(actor, numbers.get('source_cl', numbers.get('cl') or 1)) < int(min_cl):
        return False  # this character is below the printed gate.
    return None


def dependencies_ready(engine, actor, row):
    """Pure readiness shared by primary and reaction admission."""
    below_gate = min_cl_ready(actor, row)
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
    return min_cl_ready(actor, row)
