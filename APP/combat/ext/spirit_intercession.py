"""Spirit Intercession's single owning-bond eligibility and post-hit price.

Only an explicitly owned bonded spirit, hosted vessel or spirit shrine qualifies,
never an ordinary ally or another cultivator's spirit. Its roll penalty is typed
data. If that attack still hits, the owner chooses 1 CP or 1 Bond Strain (printed
rules_text.json). Strain belongs to the owner's bond, not a disposable combat
body; it deliberately has no turn expiry. spirit_bond_state.add_strain handles
the shared 0-3 Major Spirit Bond counter and Pact recovery. sync_bond_strain keeps
the existing saved per-bond condition in sync without a fresh application.
"""
from typing import Any
from . import effect, hook

SOURCE = 'tianxia.talent.spirit_companions.spirit_intercession'
STRAIN = 'condition:typed.spirit_bond_strain'
REACTION = 'reaction:bai_meizhen.spirit_intercession'


@hook('reaction_resolved')
def remember_intercession_reaction(engine: Any, event: Any) -> None:
    """Attach this accepted reaction's receipt to the active roll only."""
    if getattr(event, "source_definition_id", None) != REACTION:
        return
    if not event.target_ids:
        return
    from ..roll_reasons import remember_reaction

    target = engine.state.actors.get(event.target_ids[0])
    if target is not None:
        remember_reaction(engine, event.actor_id, REACTION, target)


@hook('reaction_roll_reasons')
def intercession_roll_reason(engine: Any, reactor_id: str, reaction_id: str, target: Any) -> list[dict[str, Any]] | None:
    """Receipt for the accepted Intercession's Disadvantage on the attack against the protected ally."""
    if reaction_id != REACTION:
        return None
    from ..roll_reasons import effect_name, source

    row = source(engine, 'DISADVANTAGE', effect=effect_name(engine, REACTION, 'Spirit Intercession'),
                 owner=engine.state.actors.get(reactor_id),
                 why='the defender spends their Reaction on this attack')
    return [row] if row else None


@effect('spirit_intercession_watch')
def legacy_watch(ctx: Any, row: dict[str, Any]) -> None:
    """Accept old compiled C9 rows; native consumed-roll scope owns the price.

    No turn flag or second post-hit subscriber is needed. New authority rows
    omit this former watcher; saved rows remain readable and resolve once.
    """


@hook('ally_row_allowed')
def owning_bond(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    if row.get('feature_id') != SOURCE:
        return None
    summon = subject.summon or {}
    pending = getattr(engine, '_typed_pending_attack', None) or {}
    attacker = engine.state.actors.get(pending.get('attacker'))
    from ..stealth import sees

    return (subject.owner_id == reactor.entity_id and summon.get('owner') == reactor.entity_id
            and summon.get('group') in ('bonded_spirit', 'hosted_vessel', 'spirit_shrine')
            and engine._distance_actor_to_actor(reactor, subject) <= 30
            and pending.get('target') == subject.entity_id and attacker is not None
            and sees(engine, reactor, attacker))


@hook('event', nested=True)
def bind_consumed_intercession(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Bind a consumed Intercession modifier to its actual scoped attack.

    Observational scratch only. Nested attacks own separate public attack_scope
    frames; aborted/unconsumed modifiers cannot charge a later unrelated roll.
    Modifier provenance identifies the reaction owner (the generic modifier's
    source_actor_id is the turn actor, so it cannot identify that owner).
    """
    from ..paid_relocation import capture, retain, retain_effect, take

    if event_type == 'MODIFIER_APPLIED' and kwargs.get('source_definition_id') == SOURCE:
        mid = (kwargs.get('payload') or {}).get('modifier_id')
        if mid:
            retain(engine, ('spirit_intercession_modifier', mid), capture(engine))
        return
    if event_type != 'MODIFIER_REMOVED':
        return
    if (kwargs.get('payload') or {}).get('reason') != 'CONSUMED':
        return
    mid = kwargs['payload'].get('modifier_id')
    if not str(mid).startswith(f'modifier:{SOURCE}:'):
        return
    from .attack_scope import current

    frame = current(engine)
    if frame is None or kwargs.get('actor_id') != frame['actor_id']:
        return
    applied = next((e for e in reversed(engine.events) if e.event_type == 'MODIFIER_APPLIED'
                    and e.payload.get('modifier_id') == mid and e.source_definition_id == SOURCE), None)
    if applied is None or applied.payload.get('target_field') != 'attack_mode':
        return
    reaction = next((e for e in reversed(engine.events) if e.sequence > applied.sequence
                     and e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == SOURCE
                     and frame['actor_id'] in e.target_ids
                     and e.payload.get('protects') == frame['target_id']), None)
    if reaction is not None:
        frame['spirit_intercession_owner'] = reaction.actor_id
        receipt = take(engine, ('spirit_intercession_modifier', mid))
        if receipt is not None:
            retain_effect(engine, frame, receipt)


@hook('attack_roll_finished')
def retain_roll_owner(ctx: Any, target: Any, effect: dict[str, Any], roll_id: str) -> None:
    from .attack_scope import current
    from ..paid_relocation import retain, take_effect

    frame = current(ctx.engine)
    owner = frame.get('spirit_intercession_owner') if frame else None
    if owner and roll_id:
        ctx.damage_cache.setdefault('spirit_intercession_rolls', {})[roll_id] = owner
        retain(ctx.engine, ('spirit_intercession_roll', roll_id), take_effect(ctx.engine, frame))


def add_bond_strain(engine: Any, owner: Any, spirit: Any) -> None:
    """Evented owner/bond bookkeeping used by Intercession; no combat penalty invented."""
    from .retained_updates import record_instance_update

    held = next(((key, c) for key, c in owner.conditions.items()
                 if c.condition_id == STRAIN and c.data.get('bond_id') == spirit.entity_id), None)
    count = int(held[1].data.get('strain', 0)) + 1 if held else 1
    from .spirit_bond_state import STRAIN as POOL, add_strain, strain

    if POOL in owner.resources:
        add_strain(engine, owner, 1, SOURCE,
                   f'Spirit Intercession: the attack still hits {spirit.display_name}.')
        count = strain(owner)
        if held:
            return  # add_strain already evented the existing condition projection.
    label = (f'Bond Strain {count}: bond with {spirit.display_name} is strained. '
             'Remains until recovered through an Offering or another permitted bond rule; '
             'the GM resolves the spirit\'s response.')
    data = {'bond_id': spirit.entity_id, 'strain': count, 'label': label}
    if held:
        key, condition = held
        condition.data = data
        record_instance_update(engine, owner, 'condition', key, condition)
    else:
        engine._apply_condition(owner, STRAIN, SOURCE, owner.entity_id, expires_on=None, data=data)


@hook('attack_result')
def post_hit_price(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    roll_id = (ctx.attack_result or {}).get('roll_id')
    owner_id = ctx.damage_cache.get('spirit_intercession_rolls', {}).pop(roll_id, None)
    if not hit or owner_id is None:
        return
    owner = ctx.engine.state.actors.get(owner_id)
    if owner is None or target.owner_id != owner_id:
        return
    from ..paid_relocation import activation as relocation_activation, causal_scope, take
    receipt = take(ctx.engine, ('spirit_intercession_roll', roll_id))
    ownership = (causal_scope(ctx.engine, receipt) if receipt is not None else
                 relocation_activation(ctx.engine, owner, SOURCE, independent=True))
    with ownership:
        from ..typed_executor import CP_POOLS
        from ..decision_text import resource_name
        from .needle import CHOICE, ask
        from .choice_prompt import action_context
        from . import note

        pool = next((p for p in CP_POOLS if owner.resources.get(p, 0) >= 1), None)
        options = ['pay_cp', 'take_strain'] if pool else ['take_strain']
        labels = {'pay_cp': f'Spend 1 {resource_name(pool)} to prevent Bond Strain' if pool else '',
                  'take_strain': f'Gain 1 Bond Strain with {target.display_name} (no CP spent)'}
        price = (f'Spend 1 {resource_name(pool)} (1 CP) or gain 1 Bond Strain' if pool else
                 'You have no CP available; gain 1 Bond Strain')
        chosen = ask(ctx.engine, ctx.intent, f'SPIRIT_INTERCESSION_HIT:{roll_id}', owner,
                     CHOICE + 'spirit_intercession_hit', options, labels=labels,
                     name='Spirit Intercession', feature_id=SOURCE, target_id=target.entity_id,
                     prompt=(f'Spirit Intercession: {ctx.actor.display_name}\'s {ctx.action.display_name} '
                             f'still hits {target.display_name}. {price}. '
                             'Bond Strain records stress on this spirit bond until recovered.'),
                     prompt_context={**action_context(ctx.engine, ctx.actor, ctx.source, target),
                                     'cost': f'No additional Reaction. {price}.'})
        if chosen == ['pay_cp'] and pool:
            ctx.engine._spend_resource(owner, pool, 1, SOURCE)
            note(ctx.engine, SOURCE, owner,
                 f'Spirit Intercession: {owner.display_name} spends 1 {resource_name(pool)}; '
                 f'the hit on {target.display_name} adds no Bond Strain.', (target.entity_id,))
        else:
            add_bond_strain(ctx.engine, owner, target)
            note(ctx.engine, SOURCE, owner,
                 f'Spirit Intercession: the hit on {target.display_name} adds 1 Bond Strain '
                 f'to {owner.display_name}\'s bond; no CP spent.', (target.entity_id,))
