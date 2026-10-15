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
    held = [(actor, condition) for actor in ctx.engine.state.actors.values()
            for condition in actor.conditions.values() if condition.condition_id == condition_id]
    cap = mark_capacity(ctx, MARK)
    if not cap or len(held) < cap or any(actor is subject for actor, _ in held):
        return None
    # Every existing mark remains selectable. AI uses only its own mark ledger;
    # no scene, private opponent state, or model service is consulted.
    held.sort(key=lambda item: item[1].applied_sequence)
    options = [condition.instance_id for _, condition in held]
    labels = {condition.instance_id: f"End your Faultline Mark on {_choice_subject(ctx.engine, ctx.actor, actor).display_name}"
              + (f" (your mark {index + 1})" if _choice_subject(ctx.engine, ctx.actor, actor) is not actor else '')
              for index, (actor, condition) in enumerate(held)}
    visible_subject = _choice_subject(ctx.engine, ctx.actor, subject)
    chosen = pick(ctx.engine, ctx.actor, "glass_faultline_replace", MARK, options,
                  subject=visible_subject, labels=labels, preferred=options[:1], optional=False,
                  trigger=f"placing a Faultline Mark on {visible_subject.display_name} beyond your limit of {cap}",
                  choose="Choose one existing mark to end. The new mark uses no action or CP.")
    if not chosen:
        return True
    bearer, old = next(item for item in held if item[1].instance_id == chosen[0])
    ctx.engine._remove_condition_instance(bearer, old.instance_id, ctx.source)
    ctx.engine._apply_condition(subject, condition_id, ctx.source, ctx.actor.entity_id,
                                expires_on=expires, data=data)
    ext.run_strict("mark_applied", ctx, MARK, subject)
    return True


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
    if not is_pane(obj):
        return []
    owner = engine.state.actors.get(owner_id(obj))
    return [owner] if owner is not None else []


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
