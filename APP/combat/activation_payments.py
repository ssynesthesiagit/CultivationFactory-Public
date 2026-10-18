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
    from .paid_relocation import current_activation
    activation = current_activation(ctx.engine)
    return [event for event in ctx.engine.events
            if event.transaction_id == ctx.engine._transaction_id
            and event.actor_id == ctx.actor.entity_id
            and event.event_type == 'ALTERNATIVE_PAYMENT_COMMITTED'
            and event.payload.get('technique_source_id') == ctx.action.source_definition_id
            and (not event.payload.get('activation_id') or (activation is not None
                 and event.payload['activation_id'] == activation.activation_id))]


def settle_activation(ctx):
    """Strict pre-effect settlement after reactions; False cancels, preserving paid costs.

    Public consumers own source interruption/top-up rules. Default is inert.
    """
    from . import ext
    replies=ext.run_strict('activation_settlement',ctx)
    if any(type(reply) is not bool for reply in replies):
        raise ext.CheckpointError('activation_settlement must return bool or None.')
    return False not in replies


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


def reaction_costs(row):
    """Actual compiled costs, including the older single-resource reaction rows."""
    from .typed_reactions import cost_dict
    if 'costs' in row:
        return tuple((cost['resource_id'],cost['amount']) for raw in row['costs'] if (cost:=cost_dict(raw)))
    return ((row['resource_id'],row['cost']),) if row.get('resource_id') else ()


def reaction_context(engine,actor,row,other=None):
    from .typed_reactions import triggered_context
    normalized={**row,'costs':[{'resource_id':r,'amount':n} for r,n in reaction_costs(row)]}
    return triggered_context(engine,actor,other,normalized,getattr(engine,'_active_intent',None))


def reaction_affordable(engine,actor,row):
    """Preserve native freshness guards for ordinary and substituted payments."""
    from .typed_reactions import _holds
    from .resource_availability import permits
    from .alternative_payments import options,resource_payment
    costs=reaction_costs(row)
    if all(_holds(engine,actor,r,n) for r,n in costs) and permits(engine,actor,row['feature_id'],costs):return True
    return any(all(_holds(engine,actor,r,n) for r,n in resource_payment(costs,plan))
               for plan in options(engine,actor,row['feature_id'],costs))


def pay_reaction(engine,actor,row,*,costs=None):
    """Pay a consented native reaction, then settle before any benefit resolves.

    The caller retains Reaction/once economy and its existing causal activation.
    With no alternative payment this emits exactly the ordinary resource events.
    """
    from .alternative_payments import options,pay
    costs=reaction_costs(row) if costs is None else tuple(costs)
    source=row['feature_id']
    if options(engine,actor,source,costs):
        pay(engine,actor,source,costs,getattr(engine,'_active_intent',None))
    else:
        for resource,amount in costs:
            if amount or 'costs' not in row:engine._spend_resource(actor,resource,amount,source)
    ctx=reaction_context(engine,actor,{**row,'costs':[{'resource_id':r,'amount':n} for r,n in costs]})
    return not receipts(ctx) or settle_activation(ctx)


def finish_reaction(ctx,first_event):
    """Only a native resolved receipt can release promised post-effect gains."""
    if receipts(ctx) and any(event.event_type=='REACTION_RESOLVED'
            and event.actor_id==ctx.actor.entity_id and event.source_definition_id==ctx.action.source_definition_id
            for event in ctx.engine.events[first_event:]):
        complete_activation(ctx)


from contextlib import contextmanager

@contextmanager
def reaction_activation(engine,actor,row,*,independent=True):
    """Legacy native reactions keep their existing relocation ownership and clocks."""
    from .paid_relocation import activation
    with activation(engine,actor,row['feature_id'],independent=independent):
        first=len(engine.events)
        yield
        finish_reaction(reaction_context(engine,actor,row),first)


def source_action(engine,actor,source):
    """Read the actual owned action, including a compiled reaction's metadata."""
    from .technique_interception import frame
    declared=frame(engine,actor.entity_id,source).get('action')
    if declared is not None:return declared
    action=engine.action_catalog.get(source)
    if action is not None:return action if action.owner_id in (actor.entity_id,'*') else None
    row=next((r for r in getattr(engine,'typed_reaction_rows',{}).get(actor.entity_id,[]) if r.get('feature_id')==source),None)
    return reaction_context(engine,actor,row).action if row is not None else None
