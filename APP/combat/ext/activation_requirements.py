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

Shared Foundation suppression queries: mud_lotus_native and mud_lotus_reserve
use foundation_ready for compiled owners; mud_lotus_native also uses
journey_foundation_ready for the same source-scoped rules outside combat.
These helpers grant no ownership and infer no Foundation stage from CL.
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


def _foundation_rules_ready(rules, foundation_id, stage, passive):
    """Apply only explicit, source-scoped suppression to a compiled owned row."""
    stages = ('Awakened', 'Refined', 'Perfected')
    for rule in rules:
        if rule.get('foundation_id') not in (foundation_id, '*'):
            continue
        if rule.get('foundation_disabled') and not (passive and rule.get('foundation_passives_allowed')):
            return False
        cap = rule.get('foundation_max_stage')
        if cap in stages and stage in stages and stages.index(stage) > stages.index(cap):
            return False
    return True


def foundation_ready(actor, foundation_id, stage, passive=False):
    """Check explicit Foundation suppression; callers establish compiled ownership."""
    from ..typed_executor import condition_rules
    return _foundation_rules_ready(condition_rules(actor), foundation_id, stage, passive)


def journey_foundation_ready(actor, foundation_id, stage, passive=False):
    """Apply the same suppression to actual saved and continued journey conditions."""
    import json
    from types import SimpleNamespace
    from ..gate2_runtime_models import ConditionInstance
    from ..typed_executor import condition_rules
    from .journey_setup import journey_conditions
    saved = (actor.get('encounter_snapshot') or {}).get('conditions', {})
    conditions = [ConditionInstance.model_validate(json.loads(row)) for row in saved.values()]
    conditions.extend(journey_conditions(actor))
    proxy = SimpleNamespace(conditions={str(i): c for i, c in enumerate(conditions)})
    return _foundation_rules_ready(condition_rules(proxy), foundation_id, stage, passive)
