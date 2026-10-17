"""Strict, default-inert removal of attack modes before cancellation.

Tokens remove benefits or named causes, never add the opposite roll mode.
Temporary typed strike provenance is scoped by attacker, target and source;
it is not saved on modifiers and never changes their historical wire shape.
"""
from contextlib import contextmanager
from . import ext

TOKENS = frozenset({'ADVANTAGE', 'DISADVANTAGE:invisible',
                    'DISADVANTAGE:blinded', 'DISADVANTAGE:obscured', 'DISADVANTAGE:prone',
                    'DISADVANTAGE:long_range'})


def presentation_modes(engine, actor, target):
    """Read-only actor/target contributions for targeting menu presentation.

    Reuse the resolver's condition/modifier query and strict owned removals,
    plus the sight contributions normally materialized during an attack.
    Return uncancelled modes so consumers can explain normal-roll cancellation.
    This does not predict later action-specific penalties or reaction choices.
    No modifiers, events, dice or persistent state are created or consumed.
    """
    from . import zones
    tokens = removed(engine, actor, target)
    modes = set()
    engine._attack_mode(actor, target, removed=tokens, contributions=modes)
    modes.update(mode for mode in zones.attack_modes(engine, actor, target)
                 if not (mode == 'DISADVANTAGE' and 'DISADVANTAGE:obscured' in tokens))
    if 'ADVANTAGE' in tokens:
        modes.discard('ADVANTAGE')
    return frozenset(modes)


def removed(engine, actor, target, ranged=None):
    """Pure query; None/empty replies preserve all existing contributions."""
    tokens = set()
    for reply in ext.run_strict('attack_mode_removed', engine, actor, target, ranged):
        if not isinstance(reply, (list, tuple, set, frozenset)) or any(
                not isinstance(token, str) or token not in TOKENS for token in reply):
            raise ValueError('attack_mode_removed requires supported mode-removal tokens')
        tokens.update(reply)
    return frozenset(tokens)


@contextmanager
def strike(engine, actor, target, source, provenance):
    old = getattr(engine, '_attack_mode_provenance', None)
    engine._attack_mode_provenance = (actor.entity_id, target.entity_id, source, dict(provenance))
    try:
        yield
    finally:
        engine._attack_mode_provenance = old


def provenance_for(engine, actor, target, source):
    frame = getattr(engine, '_attack_mode_provenance', None)
    return frame[3] if frame and frame[:3] == (actor.entity_id, target.entity_id, source) else {}


def condition_rows(actor, tokens, *, incoming, engine=None, masked=()):
    """Remove only the named mode field; preserve all other condition rules."""
    from .typed_executor import condition_rules, is_active_typed_condition, rules
    rows = condition_rules(actor, engine=engine)
    disabled = engine is not None and any(row.get('disabled_if_incapacitated_or_speed_zero') for row in rows) and (
        engine._effective_speed(actor) <= 0 or any(row.get('no_actions') for row in rows))
    conditions = [c for c in actor.conditions.values()
                  if (is_active_typed_condition(c) or c.condition_id in (rules().get('condition_id_aliases') or {}))
                  and not (c.data or {}).get('suppressed')]
    result = []
    for condition, row in zip(conditions, rows, strict=True):
        if disabled and row.get('disabled_if_incapacitated_or_speed_zero'):
            continue
        if condition.instance_id in masked:
            continue
        field = None
        if incoming and condition.condition_id == 'condition:typed.invisible' and 'DISADVANTAGE:invisible' in tokens:
            field = 'attacked_with'
        elif not incoming and condition.condition_id == 'condition:typed.blinded' and 'DISADVANTAGE:blinded' in tokens:
            field = 'attacks_have'
        elif not incoming and condition.condition_id == 'condition:typed.prone' and 'DISADVANTAGE:prone' in tokens:
            field = 'attacks_have'
        if field and row.get(field) == 'DISADVANTAGE':
            row = {key: value for key, value in row.items() if key != field}
        result.append(row)
    return result


def checkpoint_results(results, tokens):
    """A checkpoint cannot reintroduce a prohibited Advantage contribution."""
    if 'ADVANTAGE' not in tokens:
        return results
    return [{key: value for key, value in row.items() if key != 'mode'}
            if isinstance(row, dict) and row.get('mode') == 'ADVANTAGE' else row for row in results]


def disadvantage_alternatives(answers, initial_mode):
    """Declaration responses may replace redundant Disadvantage with a penalty.

    ``disadvantage_penalty`` is a nonpositive integer, meaningful only alongside
    ``mode=DISADVANTAGE``. The pre-checkpoint mode decides every substitution.
    Input responses are never mutated; absent the field this is inert.
    """
    out, penalty = [], 0
    for answer in answers:
        if not isinstance(answer, dict) or 'disadvantage_penalty' not in answer:
            out.append(answer)
            continue
        value = answer['disadvantage_penalty']
        if type(value) is not int or value > 0 or answer.get('mode') != 'DISADVANTAGE':
            raise ValueError('disadvantage_penalty requires DISADVANTAGE and a nonpositive integer')
        reply = {k: v for k, v in answer.items() if k != 'disadvantage_penalty'}
        if initial_mode == 'DISADVANTAGE':
            penalty += value
            reply.pop('mode', None)
        out.append(reply)
    return out, penalty
