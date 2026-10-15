"""Faultline Marks' owner-selected replacement, using the public mark_apply seam.

The ordinary executor supplies talent-adjusted expiry and capacity. This handler
only takes over an owned Faultline Mark that would exceed that capacity; all
other placement, including refresh, retains the ordinary executor's behavior.
"""
from typing import Any

from . import hook
from .rider_choices import pick

OWNER = "GLASS_BASE_FAULTLINE_MARKS"
MARK = "Faultline Mark"


@hook('compile_passives')
def base_acquisition(passives, info):
    """The actual base acquisition supplies its cap/ownership marker once."""
    if OWNER not in (info.get('owned_ids') or ()) or any(
            row.get('feature_id') == OWNER and row.get('block') == 'mark_caps' for row in passives):
        return passives
    from .elements_marks import compile_caps
    return [*passives, *compile_caps({'caps': {'faultline mark': 'pb'}},
        {'feature_id': OWNER, 'block': 'mark_caps', 'resource_id': ''}, info['numbers'])]


def owners(engine):
    """Active actual Faultline Mark owners, independent of Refraction access."""
    return [actor for actor in sorted(engine.state.actors.values(), key=lambda actor: actor.entity_id)
        if actor.active and any(row.get('feature_id') == OWNER
            for row in engine.typed_passive_rows.get(actor.entity_id, ()))]


def _choice_subject(engine, owner, creature):
    """Display projection for this module's optional and capacity choosers."""
    from ..senses import perceives
    return creature if perceives(engine, owner, creature) else creature.model_copy(
        update={'display_name': 'an unseen creature'})


@hook("mark_apply")
def replace_at_capacity(ctx: Any, effect: dict[str, Any], subject: Any,
                        expires: str, data: dict[str, Any] | None) -> bool | None:
    from .. import ext, typed_reactions
    from ..typed_executor import mark_capacity, mark_condition_id

    if effect.get("mark") != MARK or not any(
            row.get("feature_id") == OWNER
            for row in typed_reactions._rows(ctx.engine, ctx.actor.entity_id, "mark_caps")):
        return None
    condition_id = mark_condition_id(MARK, ctx.actor.entity_id)
    from ..mark_ledger import owned, remove, visible_name
    held = owned(ctx.engine, MARK, ctx.actor.entity_id)
    cap = mark_capacity(ctx, MARK)
    if not cap or len(held) < cap or any(entry['recipient'] is subject for entry in held):
        return None
    # Every existing mark remains selectable. AI uses only its own mark ledger;
    # no scene, private opponent state, or model service is consulted.
    options = [entry['id'] for entry in held]
    labels = {entry['id']: 'End your Faultline Mark on ' + visible_name(ctx.engine, ctx.actor, entry)
        + (f' (your mark {index + 1})' if visible_name(ctx.engine, ctx.actor, entry).startswith('an unseen ') else '')
        for index, entry in enumerate(held)}
    visible_subject = _choice_subject(ctx.engine, ctx.actor, subject)
    chosen = pick(ctx.engine, ctx.actor, "glass_faultline_replace", MARK, options,
                  subject=visible_subject, labels=labels, preferred=options[:1], optional=False,
                  trigger=f"placing a Faultline Mark on {visible_subject.display_name} beyond your limit of {cap}",
                  choose="Choose one existing mark to end. The new mark uses no action or CP.")
    if not chosen:
        return True
    remove(ctx.engine, next(entry for entry in held if entry['id'] == chosen[0]), MARK, ctx.actor.entity_id, ctx.source)
    ctx.engine._apply_condition(subject, condition_id, ctx.source, ctx.actor.entity_id,
                                expires_on=expires, data=data)
    ext.run_strict("mark_applied", ctx, MARK, subject)
    return True


def place_object_mark(ctx, obj, effect=None):
    """The explicit hit producer shares creature/object PB capacity and timing."""
    from ..mark_ledger import owned, remove, visible_name
    from ..typed_executor import mark_capacity
    from .object_marks import apply, has, resolved_expiry
    from .needle import ask, checkpoint_id
    from ..object_rules import label
    from ..senses import perceives_object
    obj = ctx.engine.state.objects[obj.object_id]
    if not any(row.get('feature_id') == OWNER for row in ctx.engine.typed_passive_rows.get(ctx.actor.entity_id, ())):
        return
    held = owned(ctx.engine, MARK, ctx.actor.entity_id)
    cap = mark_capacity(ctx, MARK)
    if cap and len(held) >= cap and not has(obj, MARK, ctx.actor.entity_id):
        target_name = label(obj) if perceives_object(ctx.engine, ctx.actor, obj) else 'the object your attack hit'
        selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'GLASS_OBJECT_REPLACE', ctx.actor.entity_id, obj.object_id),
            ctx.actor, 'choice:needle.glass_faultline_replace', [entry['id'] for entry in held],
            labels={entry['id']: 'End your Faultline Mark on ' + visible_name(ctx.engine, ctx.actor, entry)
                + f' (your mark {index + 1})' for index, entry in enumerate(held)},
            preferred=[held[0]['id']], name='Faultline Marks', target_id=obj.object_id,
            prompt=f'{ctx.action.display_name} hits {target_name}, placing a Faultline Mark beyond your limit of {cap}. '
                'Choose one of your existing marks to end. No extra Action or resource cost.')
        if not selected:
            return
        remove(ctx.engine, next(entry for entry in held if entry['id'] == selected[0]), MARK, ctx.actor.entity_id, ctx.source)
    timing = {**(effect or {'duration': {'kind': 'until_removed'}}), 'mark': MARK}
    apply(ctx.engine, obj, MARK, ctx.actor, ctx.source, resolved_expiry(ctx, timing))


def offer_surface_mark(engine, owner, creature, trigger, *, unseen_trigger=None):
    """The receipt supplies the trigger; the owner's base row supplies authority."""
    from .glass_refraction import give_mark, marked
    if not owner.active or not creature.active or marked(creature, owner.entity_id):
        return
    if not any(row.get('feature_id') == OWNER for row in
               engine.typed_passive_rows.get(owner.entity_id, [])):
        return
    subject = _choice_subject(engine, owner, creature)
    if subject is not creature:
        # The surface supplies a trigger, not another creature's identity or
        # knowledge of its unobserved technique. Preserve the legal response.
        trigger = unseen_trigger or 'an unseen creature attacks or damages your Glass Surface'
    if pick(engine, owner, 'glass_surface_mark', MARK, ['mark'], subject=subject,
            labels={'mark': f'Place your Faultline Mark on {subject.display_name} until your next turn ends'},
            preferred=['mark'], optional=True, trigger=trigger,
            choose='Place a Faultline Mark? No Action or resource cost.'):
        give_mark(engine, owner, creature, OWNER, any_side=True)


def surface_owners(engine, obj):
    """Only the actual creator's standing pane supplies created-surface authority."""
    from .glass_pane import is_pane, owner_id
    from .glass_surface_profiles import object_owners
    owners = object_owners(engine, obj)
    owner = engine.state.actors.get(owner_id(obj)) if is_pane(obj) else None
    if owner is not None and owner not in owners:
        owners.append(owner)
    return owners


@hook('object_attack_resolved')
def attacked_surface(ctx, obj, hit, natural):
    for owner in surface_owners(ctx.engine, obj):
        offer_surface_mark(ctx.engine, owner, ctx.actor,
                           f'{ctx.actor.display_name} attacks your Glass Surface with {ctx.action.display_name}')


@hook('event', nested=True)
def damaged_surface(engine, event_type, kwargs):
    if event_type != 'OBJECT_UPDATED':
        return
    payload = kwargs.get('payload') or {}
    if int((payload.get('damage') or {}).get('hp_damage') or 0) <= 0:
        return
    creature = engine.state.actors.get(kwargs.get('actor_id'))
    obj = engine.state.objects.get((payload.get('object') or {}).get('object_id'))
    if creature is None or obj is None:
        return
    from .ability_source import source_label
    source = str(kwargs.get('source_definition_id') or OWNER)
    for owner in surface_owners(engine, obj):
        offer_surface_mark(engine, owner, creature,
                           f'{creature.display_name} uses {source_label(engine, source)} to damage or break your Glass Surface')
