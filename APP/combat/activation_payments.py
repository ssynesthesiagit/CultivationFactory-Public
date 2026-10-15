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



def receipts(ctx):
    """Alternative payments committed for this accepted activation, never old uses."""
    return [event for event in ctx.engine.events
            if event.transaction_id == ctx.engine._transaction_id
            and event.actor_id == ctx.actor.entity_id
            and event.event_type == 'ALTERNATIVE_PAYMENT_COMMITTED'
            and event.payload.get('technique_source_id') == ctx.action.source_definition_id]


def settle_activation(ctx):
    """Strict pre-effect settlement after reactions; False cancels, preserving paid costs.

    Public consumers own source interruption/top-up rules. Default is inert.
    """
    from . import ext
    return False not in ext.run_strict('activation_settlement', ctx)


def complete_activation(ctx):
    """Apply promised resource gains only after successful effect resolution.

    A receipt is identified by its sequence; nested uses cannot settle it twice.
    Stored conditions/events remain the consumer's persistence contract.
    """
    from . import ext
    settled = {event.payload.get('payment_sequence') for event in ctx.engine.events
               if event.event_type == 'ACTIVATION_PAYMENT_SETTLED'}
    for receipt in receipts(ctx):
        if receipt.sequence in settled:
            continue
        for resource, amount in receipt.payload.get('resolution_gains', {}).items():
            ctx.engine._gain_resource(ctx.actor, resource, amount, receipt.source_definition_id)
        if receipt.payload.get('resolution_gains'):
            ctx.engine._append_event('ACTIVATION_PAYMENT_SETTLED', receipt.source_definition_id,
                actor_id=ctx.actor.entity_id, payload={'payment_sequence': receipt.sequence})
    ext.run_strict('technique_resolved', ctx)
