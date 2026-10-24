"""Lord of Decay: the Poison Cultivator's CL18 record as native combat effects.

The always-on clauses need no active state: a compiled CL18 owner is immune to
Poison damage and to Poisoned, and their Poison damage ignores ordinary
Resistance and treats ordinary Poison Immunity as Resistance (Supreme Venom,
which never beats artifact, Secret, conceptual or explicitly absolute
protection). The Decaying Presence clauses belong to the paid, finite active
state the typed row publishes (``feature_state``), never to bare ownership:
extra Poison/Necrotic damage once a turn, no healing after a failed save in the
owner's Toxic Cloud, no Concentration on Toxic Cloud, a Domain Armament origin
for it, and Feast of Decay's Qi. Every consumer returns early for a creature
that does not own the record.
"""
from dataclasses import replace

from . import hook
from .feature_state import active
from .needle import timed_condition

FEATURE = 'tianxia.subpath.qi.poison_cultivator.feature.poison_touch'
PRESENCE = 'tianxia.subpath.qi.poison_cultivator.feature.lord_of_decay'
TOXIC_CLOUD = 'tianxia.subpath.qi.poison_cultivator.feature.toxic_cloud'
QI = 'resource:core.qi'
TOUCH = 'condition:typed.poison_touch'
POISONED = 'condition:typed.poisoned'
NO_HEAL = 'condition:typed.lord_of_decay_no_heal'
SUPERIOR = {'artifact', 'secret', 'immortal', 'conceptual', 'absolute', 'heavenly', 'world_law'}


def owns(engine, actor):
    """The acquired CL18 record, proven by its owned compiled action.

    The action exists only for a character whose real acquisition granted the
    record at its tier, so ownership never comes from a name or a tag.
    """
    for action_id in getattr(actor, 'action_ids', ()):
        action = engine.action_catalog.get(action_id)
        if action is not None and (action.parameters.get('typed') or {}).get('source') == PRESENCE:
            return True
    return False


def presence(actor):
    """The overrides of an actually activated Decaying Presence, or {}."""
    return active(actor, PRESENCE)


def superior_protection(target, kind):
    """Whether this defence is artifact, Secret, conceptual or explicitly absolute."""
    for held in target.conditions.values():
        authority = (held.data or {}).get('protection_authority') or {}
        if str(authority.get('authority') or '') not in SUPERIOR:
            continue
        if any(row.get('kind') in ('resistance', 'immunity')
               and (not row.get('damage_types')
                    or kind in {str(value).upper() for value in row['damage_types']})
               for row in (held.data or {}).get('defenses') or []):
            return True
    return False


def cloud_zones(engine, owner):
    """The owner's own active Toxic Cloud areas (by the compiled action they came from)."""
    for zone in engine.state.zones.values():
        if not zone.active or zone.owner_id != owner.entity_id:
            continue
        action = engine.action_catalog.get(zone.source_definition_id)
        if action is not None and (action.parameters.get('typed') or {}).get('source') == TOXIC_CLOUD:
            yield zone


def stamp(engine):
    current = engine.state.actors.get(engine.state.current_actor_id)
    return (f'{engine.state.round_number}:{engine.state.current_actor_id}:'
            f'{current.turns_started if current else 0}')


def is_poisoned(creature):
    """Whether this creature bears Poisoned, directly or through a carrier that stands in for it.

    An ``ongoing`` row with ``base_condition: poisoned`` merges the printed condition's
    rules into its carriage (combat/ext/ongoing_effects.py), so the creature IS Poisoned
    even though it has no separate ``condition:typed.poisoned`` instance.
    """
    return any(c.condition_id == POISONED or (c.data or {}).get('base_condition') == 'poisoned'
               for c in creature.conditions.values())


def hostiles(engine, owner, creature):
    """A genuinely hostile creature: another team, not the owner's own creation."""
    if creature is None or not creature.active or creature.entity_id == owner.entity_id:
        return False
    if creature.team_id == owner.team_id:
        return False
    summon = getattr(creature, 'summon', None)
    return not (getattr(creature, 'owner_id', None) == owner.entity_id
                or (summon is not None and summon.get('owner') == owner.entity_id))


# ------------------------------------------------------------------ always on
@hook('condition_immune')
def poisonous_body(engine, actor, name):
    """Immunity to Poisoned (the record's first clause)."""
    if str(name).lower() != 'poisoned' or not owns(engine, actor):
        return None
    return True


@hook('damage_defenses')
def poison_immunity(engine, target, damage_type, typed, source_actor_id):
    """Immunity to Poison damage (the record's first clause)."""
    if str(damage_type).upper() != 'POISON' or not owns(engine, target):
        return None
    return [{'kind': 'immunity', 'damage_types': ['POISON'], 'feature_id': PRESENCE}]


def venom_source(engine, source_actor_id, kind):
    if str(kind).upper() != 'POISON':
        return None
    source = engine.state.actors.get(str(source_actor_id or ''))
    return source if source is not None and owns(engine, source) else None


@hook('resistance_ignored')
def supreme_venom(engine, kind, typed, source_actor_id, target=None):
    """"Your Poison damage ignores ordinary Resistance"."""
    if venom_source(engine, source_actor_id, kind) is None or target is None:
        return None
    if superior_protection(target, 'POISON'):
        return None
    return True


@hook('immunity_as_resistance')
def supreme_venom_immunity(engine, kind, typed, source_actor_id, target):
    """"treats ordinary Poison damage Immunity as Resistance", never superior protection."""
    if venom_source(engine, source_actor_id, kind) is None or target is None:
        return None
    if superior_protection(target, 'POISON'):
        return None
    return True


# ------------------------------------------------------------------ Decaying Presence
@hook('damage_dealt')
def presence_bonus(ctx, target, amount):
    """Once a turn, a Poisoned creature this owner damaged takes 2d8 Poison or Necrotic."""
    engine, actor = ctx.engine, ctx.actor
    if ctx.source == PRESENCE or amount <= 0 or not presence(actor) or not owns(engine, actor):
        return
    if not target.active or not is_poisoned(target):
        return
    if actor.turn_flags.get('_turn_lord_of_decay_bonus') == stamp(engine):
        return
    from .rider_choices import pick
    chosen = pick(engine, actor, 'lord_of_decay_bonus', 'Lord of Decay', ['POISON', 'NECROTIC'],
        subject=target, intent=ctx.intent, preferred=['POISON'],
        labels={'POISON': 'Deal 2d8 Poison damage',
                'NECROTIC': 'Deal 2d8 Necrotic damage'},
        prompt=f'Lord of Decay: {ctx.action.display_name} damaged Poisoned {target.display_name}. '
               'Once this turn, deal it an additional 2d8 Poison or Necrotic damage at no cost?')
    if not chosen:
        return
    actor.turn_flags['_turn_lord_of_decay_bonus'] = stamp(engine)
    from ..typed_executor import run_effects
    run_effects(replace(ctx, effect_source=PRESENCE, targets=[target], target=target),
                [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 2, 'sides': 8},
                  'damage_types': [chosen[0].lower()]}])


@hook('after_save_resolved')
def cloud_no_heal(ctx, subject, ability, named, failed):
    """A creature failing a save inside this owner's Toxic Cloud cannot regain Hit Points."""
    if not failed:
        return
    engine = ctx.engine
    if not owns(engine, ctx.actor):
        return
    from ..zones import actor_inside_zone
    from .effect_durations import holder_next_turn
    if not any(actor_inside_zone(engine, subject, zone) for zone in cloud_zones(engine, ctx.actor)):
        return
    timed_condition(engine, subject, NO_HEAL, PRESENCE, ctx.actor.entity_id, holder_next_turn(subject),
        {'rule': {'healing_denied': True},
         'label': 'Lord of Decay: failed its save in Toxic Cloud, so it cannot regain Hit Points '
                  'until the start of its next turn'})


@hook('concentration_required')
def cloud_without_concentration(engine, actor, source_id, typed):
    """"Toxic Cloud needs no Concentration" during Decaying Presence."""
    if (typed.get('source') or typed.get('option_of')) != TOXIC_CLOUD:
        return None
    if presence(actor).get(TOXIC_CLOUD, {}).get('concentration') != 0:
        return None
    return False


@hook('effect_origins')
def cloud_origin(engine, actor, action):
    """"may originate from you or Domain Armament" during Decaying Presence."""
    typed = action.parameters.get('typed') or {}
    if (typed.get('source') or typed.get('option_of')) != TOXIC_CLOUD:
        return None
    if presence(actor).get(TOXIC_CLOUD, {}).get('origin') != 1:
        return None
    from .qi_path import armament_condition, armament_control_range, armament_point
    if armament_condition(actor) is None:
        return None
    x, y = armament_point(actor)
    from ..gate2_runtime_models import Position
    if engine.grid.distance_ft(actor.position, Position(x=x, y=y)) > armament_control_range(engine, actor):
        return None
    return [{'id': 'lord_of_decay:armament', 'label': 'Domain Armament',
             'position': {'x': int(x), 'y': int(y)}}]


@hook('event', nested=True)
def feast_of_decay(engine, event_type, kwargs):
    """Once a round, a qualifying hostile creature affected by Touch or Cloud falls: regain 2 Qi."""
    if event_type not in ('LIFE_STATE_CHANGED', 'ENTITY_DEFEATED'):
        return
    payload = kwargs.get('payload') or {}
    if event_type == 'LIFE_STATE_CHANGED' and payload.get('life_state') != 'DYING':
        return  # first zero-HP moment; STABLE/DYING edges later are not a new fall
    target = engine.state.actors.get(kwargs.get('actor_id'))
    if target is None or target.current_hp != 0:
        return
    for owner in list(engine.state.actors.values()):
        if not owns(engine, owner) or not hostiles(engine, owner, target):
            continue
        from ..cultivation_access import effective_cl
        owner_cl = effective_cl(engine, owner, int(getattr(owner, 'cultivation_level', 0) or 1))
        target_cl = effective_cl(engine, target, int(getattr(target, 'cultivation_level', 0) or 1))
        if target_cl < owner_cl - 5:
            continue
        from ..zones import actor_inside_zone
        touched = any(c.condition_id == TOUCH and c.source_actor_id == owner.entity_id
                      for c in target.conditions.values())
        clouded = any(actor_inside_zone(engine, target, zone) for zone in cloud_zones(engine, owner))
        if not (touched or clouded):
            continue
        if owner.turn_flags.get('_round_lord_of_decay_feast') == engine.state.round_number:
            continue
        if QI not in owner.resources or owner.resources[QI] >= owner.resource_maximums.get(QI, 0):
            continue
        owner.turn_flags['_round_lord_of_decay_feast'] = engine.state.round_number
        engine._gain_resource(owner, QI, 2, PRESENCE)
        engine._append_event('PASSIVE_TRIGGERED', PRESENCE, actor_id=owner.entity_id,
            target_ids=(target.entity_id,),
            payload={'feature_id': PRESENCE,
                     'log': f'Feast of Decay: {target.display_name} was reduced to 0 Hit Points while affected '
                            f'by Poison Touch or Toxic Cloud; {owner.display_name} regains 2 Qi.'})
