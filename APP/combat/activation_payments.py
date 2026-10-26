"""Post-payment reaction eligibility, independent of ability rules and economy."""


def reaction_completed(engine, actor, source, *, consumes_reaction=True):
    """Payment riders may incapacitate the payer before its reaction resolves.

    Resource costs already paid remain spent. On interruption, consume any owed
    Reaction and record a plain explanation. Never consult reaction_available:
    callers may have consumed it already. Eligible actors change no bytes/events.
    """
    from .typed_executor import condition_rules
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
