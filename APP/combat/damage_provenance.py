"""Opt-in committed packet receipts for damage-triggered feature plug-ins.

typed_executor produces these from the sealed action and compiler-owned feature
list. Subscribers (currently Poison Touch) read the receipt on each packet,
never the enclosing attack's damage type or another packet's power source.
Absent ``track_damage_provenance`` preserves existing event/replay bytes.
"""
from __future__ import annotations
from contextlib import contextmanager


def source_flags_of(effect):
    """Reviewed damage rows explicitly declare source restrictions, never names.

    Shared by ordinary and half-save damage delivery. PendingDamage validates
    native callers too. Absence produces no flags or changed event bytes.
    """
    flags = effect.get('source_flags', ())
    if not isinstance(flags, (list, tuple)) or any(type(f) is not str or not f for f in flags):
        raise ValueError('Damage source_flags must be a list of nonempty names')
    return tuple(flags)


def qi_activation(action, typed):
    """Declared power, selected powering pool, or the feature's own Qi Path."""
    explicit = typed.get('qi_powered')
    if type(explicit) is bool:
        return explicit
    from .ext.insights7 import qi_powered
    feature = str(typed.get('option_of') or typed.get('source') or '')
    return (typed.get('power_resource_id') == 'resource:core.qi'
            or qi_powered(typed.get('sphere'), tuple(pool for pool, _ in action.costs))
            or feature.startswith(('tianxia.subpath.qi.', 'tianxia.path.qi_cultivation.')))


@contextmanager
def packet_scope(ctx):
    """Keep defense authority packet-specific through nested damage/reactions.

    A weapon packet is not cultivated merely because its enclosing action also
    delivers a cultivated technique. The technique's separate frame restores
    its own profile, then restores the enclosing frame on every unwind.
    """
    previous_notification = getattr(ctx.engine, '_typed_damage_notification_source', None)
    ctx.engine._typed_damage_notification_source = (ctx.damage_source, ctx.actor.entity_id)
    previous = getattr(ctx.engine, '_typed_provenance_context', None)
    profile = dict(ctx.typed)
    if ctx.damage_packet_kind == 'weapon':
        profile.pop('authority_contest', None)
    if ctx.typed.get('track_damage_provenance'):
        ctx.engine._typed_provenance_context = (ctx.damage_source, profile)
    try:
        yield
    finally:
        ctx.engine._typed_provenance_context = previous
        ctx.engine._typed_damage_notification_source = previous_notification


def grouped_notification_pending(engine, source, actor_id):
    """True only while a typed delivery owns its later damage_dealt receipt.

    Adaptations use the complete per-hit type list instead of acquiring from
    the first component's raw event. Poison Touch also consumes damage_dealt;
    this public identity lets raw-event consumers avoid duplicate delivery.
    Nested reactions restore the enclosing identity, including on choice pause.
    No persistent state, ownership grant or event is produced here.
    """
    return getattr(engine, '_typed_damage_notification_source', None) == (source, actor_id)


def metadata(ctx):
    if not ctx.typed.get('track_damage_provenance'):
        return {}
    # Display attribution (effect_source) is not activation authority.
    feature = str(ctx.typed.get('option_of') or ctx.typed.get('source') or '')
    qi = qi_activation(ctx.action, ctx.typed)
    return {'damage_origin': {
        'feature_id': feature,
        'owned': int(ctx.action.owner_id == ctx.actor.entity_id
                     and feature in ctx.typed.get('known_damage_features', ())),
        'qi_powered': int(qi),
        'component': str(ctx.damage_packet_kind),
        'source_cl': int(ctx.numbers.get('cl') or 0),
        'attack_index': int(ctx.damage_attack_index or 0),
        'weapon_delivery': int(bool(ctx.typed.get('weapon'))),
    }}


def stamp(ctx, target, first_event):
    """Stamp only unstamped own packets; attached technique receipts stay intact."""
    receipt = metadata(ctx)
    if not receipt:
        return
    for event in ctx.engine.events[first_event:]:
        if (event.event_type == 'DAMAGE_COMMITTED'
                and event.source_definition_id == ctx.damage_source
                and event.actor_id == ctx.actor.entity_id and target.entity_id in event.target_ids):
            event.payload.setdefault('damage_origin', dict(receipt['damage_origin']))
