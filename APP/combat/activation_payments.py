"""Post-payment reaction eligibility, independent of ability rules and economy."""


def reaction_completed(engine, actor, source, *, consumes_reaction=True):
    """Payment riders may incapacitate the payer before its reaction resolves.

    Resource costs already paid remain spent. On interruption, consume any owed
    Reaction and record a plain explanation. Never consult reaction_available:
    callers may have consumed it already. Inert extension subscribers preserve ordinary behavior.
    """
    if consumes_reaction:
        from . import typed_reactions
        # Preserve the dispatcher's continuation result; active/life-state alone
        # misses incapacitation, which denies the pending benefit.
        return typed_reactions.reaction_paid(engine, actor, {"feature_id": source, "name": source})
    from .typed_executor import condition_rules
    # A committed Reaction still resolves when a rider only denies future
    # Reactions; incapacitation (no_actions) interrupts its pending benefit.
    denied = any(r.get('no_actions') or (consumes_reaction and r.get('no_reactions'))
                 for r in condition_rules(actor))
    if actor.active and actor.life_state is None and not denied:
        return True
    if consumes_reaction:
        actor.reaction_available = False
    benefit = 'reaction' if consumes_reaction else 'benefit'
    engine._append_event('PASSIVE_TRIGGERED', source, actor_id=actor.entity_id,
        payload={'log': f'{actor.display_name} cannot finish this {benefit} after paying its cost.'})
    return False
