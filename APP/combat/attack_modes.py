"""Strict, default-inert removal of attack modes before cancellation.

Tokens remove benefits or named causes, never add the opposite roll mode.
Temporary typed strike provenance is scoped by attacker, target and source;
it is not saved on modifiers and never changes their historical wire shape.
"""
from contextlib import contextmanager
from . import ext

TOKENS = frozenset({'ADVANTAGE', 'DISADVANTAGE:invisible',
                    'DISADVANTAGE:blinded', 'DISADVANTAGE:obscured', 'DISADVANTAGE:prone',
                    'DISADVANTAGE:long_range', 'DISADVANTAGE:weather'})


def typed_contribution(reply):
    """A legacy mode string, or an explicitly attributed typed contribution.

    Attribution is transient and enters native selective removal. It never
    changes a saved modifier's shape or guesses a cause from a source name.
    """
    if reply in ("ADVANTAGE", "DISADVANTAGE"):
        return reply, ""
    if isinstance(reply, dict):
        mode, cause = reply.get("mode"), reply.get("cause")
        if mode in ("ADVANTAGE", "DISADVANTAGE") and (f"{mode}:{cause}" in TOKENS or
                (not cause and all(isinstance(reply.get(k), str) for k in ('effect', 'why')))):
            return mode, cause
        raise ValueError("attack_mode requires a supported mode/cause contribution")
    return None


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


def contributed(engine, actor, target):
    """Pure, strict attack_roll_modes query for every attack resolver.

    Return uncancelled Advantage/Disadvantage contributions. None/empty is
    inert. Each resolver combines these with its existing contributions before
    cancellation; this reader adds no condition rules or choice provenance.
    Providers must not roll, emit, consume or mutate state.
    """
    result = set()
    for modes in ext.run_strict('attack_roll_modes', engine, actor, target):
        if not isinstance(modes, (list, tuple, set, frozenset)) or any(
                mode not in {'ADVANTAGE', 'DISADVANTAGE'} for mode in modes):
            raise ValueError('attack_roll_modes requires Advantage/Disadvantage contributions')
        result.update(modes)
    return frozenset(result)


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
def strike(engine, actor, target, source, provenance, *, obscuration=None):
    old = getattr(engine, '_attack_mode_provenance', None)
    engine._attack_mode_provenance = (actor.entity_id, target.entity_id, source, dict(provenance), obscuration)
    try:
        yield
    finally:
        engine._attack_mode_provenance = old


def provenance_for(engine, actor, target, source):
    frame = getattr(engine, '_attack_mode_provenance', None)
    if not frame or frame[:3] != (actor.entity_id, target.entity_id, source):
        return {}
    # Resolution supplies the actual source, so a nested attack by the same
    # actor against the same target cannot borrow its parent's sight exception.
    return {**frame[3], '_obscuration': frame[4]} if len(frame) > 4 and frame[4] is not None else frame[3]


def geometry_modes(engine, actor, target, ranged, *, provenance=None, reasons=None):
    """Pure geometry contributions, preserving causes until selective removal.

    Typed strikes can supply uncancelled sight modes after an owned sight
    exception. Native and portable attacks use the same zone sight policy.
    Extension geometry penalties receive the actual delivery kind.
    """
    from . import zones
    sight = (provenance or {}).get('_obscuration')
    if sight is None:
        sight = zones.attack_modes(engine, actor, target)
    result = [(mode, 'obscured' if mode == 'DISADVANTAGE' else '') for mode in sight]
    for reply in ext.run_strict('attack_geometry_mode', engine, actor, target, ranged):
        contribution = typed_contribution(reply)
        if contribution:
            result.append(contribution)
            if reasons is not None and isinstance(reply, dict) and reply.get('effect'):
                from .roll_reasons import source
                reasons.append(source(engine, contribution[0], effect=reply['effect'],
                                      owner=reply.get('owner'), why=reply.get('why')))
    return tuple(result)


def condition_rows(actor, tokens, *, incoming, engine=None, masked=(), with_sources=False):
    """Remove only the named mode field; preserve all other condition rules.

    with_sources retains each (condition, row) pair for display attribution;
    the default remains the same plain rule rows.
    """
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
        result.append((condition, row) if with_sources else row)
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


def chosen(engine, source, spec=None):
    """Explicit accepted-attacker choice contributions, before cancellation.

    A sealed action may declare chosen_attack_modes in its parameters when
    selecting that action intentionally accepts those modes. A per-strike
    choice provider instead writes the same field to the resolved attack spec
    ONLY after acceptance. Typed attack effects forward their own field there.
    These are real contributions, not labels on inferred condition origins.
    Empty/missing is inert. Journal the returned strings on ATTACK_ROLLED;
    cancelled choices remain choices. Callers must never mark enemy-imposed
    penalties, automatic conditions, or an unaccepted optional branch as chosen.
    """
    action = engine.action_catalog.get(source)
    values = [((action.parameters or {}).get('chosen_attack_modes') if action else None),
              (spec or {}).get('chosen_attack_modes')]
    result = set()
    for value in values:
        if value is None:
            continue
        if not isinstance(value, (list, tuple, set, frozenset)) or any(
                mode not in {'ADVANTAGE', 'DISADVANTAGE'} for mode in value):
            raise ValueError('chosen_attack_modes requires Advantage/Disadvantage contributions')
        result.update(value)
    return frozenset(result)


def spend_incoming_advantage(engine, actor, target):
    """Spend the one incoming next-attack Advantage grant on this target's attack roll.

    Every writer grants Advantage on "the next attack roll against it", so the next roll spends it
    whatever its settled mode, including a roll cancelled to NORMAL. Disadvantage and sustained
    sources are not spent here. Called once per real attack roll, right after the roll is made.
    """
    for mid, modifier in list(target.modifiers.items()):
        if modifier.target_field == "incoming_attack_mode" and modifier.value == "ADVANTAGE":
            del target.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id,
                                 actor_id=actor.entity_id, target_ids=(target.entity_id,),
                                 payload={"modifier_id": mid, "reason": "CONSUMED"})
            return mid
    return None


def consume_targeted_next_attack(engine, actor, target):
    """Remove next-roll modes against this recipient; return removed IDs as a tuple.

    Native Gate2Engine._resolve_attack_packet calls immediately after a real
    roll, before damage or hit aftermath can grant/use a fresh benefit.
    typed_executor._use_vex calls at its existing post-result consumption phase
    (and when replacing Vex). Both Advantage and Disadvantage are spent even if
    cancellation/removal made the settled mode NORMAL. Other recipients,
    non-NEXT_ATTACK modifiers and absent benefits are untouched. No state is
    added; each removal uses the existing replayable MODIFIER_REMOVED event.
    """
    removed = []
    for mid, modifier in list(actor.modifiers.items()):
        if (modifier.target_field != "attack_mode_vs"
                or modifier.applies_to != "NEXT_ATTACK"
                or modifier.value not in (f"ADVANTAGE:{target.entity_id}", f"DISADVANTAGE:{target.entity_id}")):
            continue
        del actor.modifiers[mid]
        engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=actor.entity_id,
                             target_ids=(actor.entity_id,), payload={"modifier_id": mid, "reason": "CONSUMED"})
        removed.append(mid)
    return tuple(removed)
