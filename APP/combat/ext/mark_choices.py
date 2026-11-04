"""Owner-selected replacement for marks explicitly opting into cap_replacement.

Smoke Trace uses this native mark_apply adapter. Other mark effects may opt in
with cap_replacement='owner'; unannotated effects keep ordinary replacement.
Expiry, cap numbers and ownership remain the typed executor's own inputs.
"""
from . import CheckpointError, hook, run_strict


@hook('mark_apply')
def choose_replacement(ctx, effect, subject, expires, data):
    if effect.get('cap_replacement') != 'owner':
        return None
    from ..typed_executor import mark_condition_id, mark_capacity, rules
    from .condition_ownership import remove_instance
    from .needle import ask, checkpoint_id

    name = str(effect['mark'])
    cid = mark_condition_id(name, ctx.actor.entity_id)
    family = next((members for key, members in (rules().get('mark_families') or {}).items()
                   if not key.startswith('_') and name.lower() in members), [name.lower()])
    family_ids = {mark_condition_id(member.title(), ctx.actor.entity_id) for member in family}
    cap = mark_capacity(ctx, name)
    existing = [(holder, held) for holder in ctx.engine.state.actors.values()
                for held in holder.conditions.values() if held.condition_id in family_ids]
    same = [(holder, held) for holder, held in existing if holder.entity_id == subject.entity_id]
    # Refreshing an existing subject consumes no new capacity.
    if not same and cap is not None and len(existing) >= cap:
        needed = len(existing) - cap + 1
        options = [held.instance_id for holder, held in existing]
        selected = ask(ctx.engine, ctx.intent,
            checkpoint_id(ctx.engine, 'mark_cap_replacement', name, subject.entity_id),
            ctx.actor, 'choice:needle.mark_cap_replacement', options,
            labels={held.instance_id: f'End {name} on {holder.display_name}' for holder, held in existing},
            minimum=needed, maximum=needed, allow_decline=False, automatic=False, default='first',
            name=name, target_id=subject.entity_id,
            prompt=f'{name}: {ctx.action.display_name} places {name} on {subject.display_name}, '
                   f'but your limit is {cap}. Choose {needed} existing mark(s) to end. No extra action or resource cost.')
        if len(set(selected)) != needed or any(key not in options for key in selected):
            raise CheckpointError('Choose exactly the required number of existing marks to end')
        for holder, held in existing:
            if held.instance_id in selected:
                remove_instance(ctx.engine, holder, held.instance_id, ctx.source)
    for holder, held in same:
        remove_instance(ctx.engine, holder, held.instance_id, ctx.source)
    ctx.engine._apply_condition(subject, cid, ctx.source, ctx.actor.entity_id, expires_on=expires, data=data)
    run_strict('mark_applied', ctx, name, subject)
    return True
