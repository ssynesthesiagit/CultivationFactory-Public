"""Venomous Qi's Venom Conversion: an owned, paid damage-type change on a Qi technique.

Printed (Tianxia Qi Cultivation Subpath Compendium R19, Venomous Qi / Venom Conversion):
"Trigger: A Qi-powered feature deals damage. Cost: 1 Qi. Limit: Once per turn. Change one
damage type dealt by the activation to Poison. ... It cannot convert Force, Void, or untyped
damage unless another rule permits it. For a weapon-delivered technique, convert only
technique damage ... It applies only to the first qualifying attack unless expressly extended."

The typed record (authority/typed_mechanics/reviewed_final.d/mgr_t14_poison_features.json)
types Venom Conversion as Venomous Qi's own technique modifier: the compiler offers
"<technique> + Venomous Qi" as a paid, once-per-turn variant. This module is the one
implementation of the actual change:

  * ``damage_type_override`` replaces the first qualifying technique packet's type with
    Poison. Weapon packets keep their own type, and Force/Void/untyped damage is refused.
  * ``technique_used`` records the turn the conversion variant was spent on, so the same
    once-per-turn limit also ends the offer; ``candidate_allowed`` withdraws the spent
    variant for the rest of that turn (the option is illegal, not hidden from a legal use).
  * ``technique_cost_discount`` makes that one conversion free while Decaying Presence is
    active ("Venom Conversion costs 0 Qi once per turn"), reading the Lord of Decay
    feature_state override the same way Poison Touch reads its own.

Every hook returns early unless the compiled technique is exactly this modifier's variant,
so nothing changes for a character who does not own Venomous Qi, for a base technique used
without the variant, or for another ability's damage type.
"""
from __future__ import annotations

from . import hook

VENOMOUS_QI = 'tianxia.subpath.qi.poison_cultivator.feature.venomous_qi'
VENOM_CONVERSION = 'tianxia.subpath.qi.poison_cultivator.feature.venom_conversion'
PRESENCE = 'tianxia.subpath.qi.poison_cultivator.feature.lord_of_decay'
QI = 'resource:core.qi'
TURN_FLAG = 'venom_conversion_turn'
CONVERTED = 'venom_conversion_packet'
# "It cannot convert Force, Void, or untyped damage unless another rule permits it."
REFUSED = frozenset({'FORCE', 'VOID', 'UNTYPED'})


def _variant(ctx_or_typed):
    typed = getattr(ctx_or_typed, 'typed', ctx_or_typed) or {}
    return (typed.get('modifier') or {}).get('id') == VENOMOUS_QI


def _stamp(engine, actor):
    """The owner's own turn clock: a new turn starts a fresh once-per-turn use."""
    return f'{engine.state.round_number}:{actor.entity_id}:{actor.turns_started}'


@hook('damage_type_override')
def converted_type(ctx, kinds, targets):
    """One technique packet becomes Poison, once per activation, unless it is exempt."""
    if not _variant(ctx) or ctx.damage_packet_kind == 'weapon':
        return None
    if ctx.damage_cache.get(CONVERTED):
        return None
    kinds = {str(kind).upper() for kind in kinds}
    if not kinds or kinds <= REFUSED:
        return None
    ctx.damage_cache[CONVERTED] = True
    return 'POISON'


@hook('technique_used')
def spent_this_turn(ctx):
    """Mark the once-per-turn use of the conversion variant."""
    if _variant(ctx):
        ctx.actor.turn_flags[TURN_FLAG] = _stamp(ctx.engine, ctx.actor)


@hook('candidate_allowed')
def spent_variant(engine, actor, candidate, action):
    """Offer the conversion again only on a later turn of its owner, and only where there is damage to change."""
    if action is None:
        return None
    typed = action.parameters.get('typed') or {}
    if not _variant(typed):
        return None
    if not _deals_damage(typed.get('effects') or ()):
        return False  # "A Qi-powered feature deals damage": nothing here to convert
    if engine.state.actors.get(actor.entity_id) is None:
        return None
    return False if actor.turn_flags.get(TURN_FLAG) == _stamp(engine, actor) else None


def _deals_damage(rows):
    """Whether this activation has a damage packet the conversion could change."""
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        if row.get('type') in ('damage', 'extra_damage', 'half_damage', 'attack'):
            return True
        if any(_deals_damage(value) for value in row.values() if isinstance(value, (list, tuple))):
            return True
    return False


@hook('technique_cost_discount')
def presence_free_conversion(engine, actor, source_id, total):
    """"Venom Conversion costs 0 Qi once per turn" while Decaying Presence is active."""
    action = engine.action_catalog.get(str(source_id))
    if action is None or not _variant(action.parameters.get('typed') or {}):
        return None
    from .feature_state import override_for

    if override_for(actor, VENOM_CONVERSION, source_feature=PRESENCE).get('cost') != 0:
        return None
    return {QI: 1} if int(total.get(QI, 0)) >= 1 else None
