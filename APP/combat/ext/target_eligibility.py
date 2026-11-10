"""Owner-specific named-mark targets for compiled actions and old saved rows.

Shared by any typed action with target_requires_mark, or a printed Target line
of the unambiguous form 'One creature bearing your ... Mark/Trace', including
Radiance's 'Glow or Dawnmark' alternatives. Reviewed target
data stays authoritative. compile_action supplies the existing engine admission
condition; candidate_allowed covers older serialized actions missing that field.
Existing engine admission and attack-declaration checks enforce the condition;
resolution does not recheck a mark an eligible action has just spent. No matching
target requirement means no changes. Creature-kind exclusions remain their own
contract; nothing is inferred from a creature's name or another caster's mark.
"""
import copy
import re

from . import hook
from .ability_source import mechanic_of


def required_mark(action):
    parameters = getattr(action, 'parameters', None) or {}
    typed = parameters.get('typed') or {}
    if typed.get('target_requires_mark'):
        return str(typed['target_requires_mark'])
    if parameters.get('target_requires_condition'):
        return None  # Explicit reviewed eligibility already has the engine's gate.
    source = mechanic_of(action)
    if not source:
        return None
    from ..rule_help import printed_rule_text

    match = re.search(r'^Target:\s*One creature(?: within range)? (?:bearing|with) your ([^\n.]+)\.?\s*$',
                      printed_rule_text(source), re.MULTILINE | re.IGNORECASE)
    if not match:
        match = re.search(r'^Choose one creature carrying your ([^\n.]+)\.',
                          printed_rule_text(source), re.MULTILINE | re.IGNORECASE)
    if not match:
        return None
    names = [name.strip().rstrip('.') for name in match.group(1).split(' or ')]
    # Preserve the original named-Mark grammar, also accepting named Trace and
    # Radiance's two printed mark names; never interpret arbitrary target prose.
    if not all(re.fullmatch(r'(?:[\w -]+ (?:Mark|Trace|Imprint)|Glow|Dawnmark)', name, re.I) for name in names):
        return None
    return names[0] if len(names) == 1 else names


@hook('compile_action')
def mark_target_contract(action, info):
    mark = required_mark(action)
    if not mark or isinstance(mark, list) or (action.parameters or {}).get('target_requires_condition'):
        return None
    from ..typed_executor import mark_condition_id

    parameters = copy.deepcopy(action.parameters)
    parameters['typed']['target_requires_mark'] = mark
    parameters['target_requires_condition'] = mark_condition_id(mark, action.owner_id)
    return action.model_copy(update={'parameters': parameters})


@hook('candidate_allowed')
def mark_target_admission(engine, actor, candidate, action):
    if (getattr(action, 'parameters', None) or {}).get('target_requires_condition'):
        return None  # Preserve the existing reviewed engine contract.
    mark = required_mark(action)
    if not mark:
        return None
    from ..typed_executor import bears_mark

    subjects = [engine.state.actors.get(t) for t in candidate.target_ids]
    names = mark if isinstance(mark, list) else [mark]
    if not subjects or any(t is None or not any(bears_mark(t, actor.entity_id, name) for name in names) for t in subjects):
        return False
    return None
