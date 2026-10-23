"""Lord of Decay: standing poison defences, Supreme Venom and Decaying Presence riders.

Typed data lives in authority/typed_mechanics/reviewed_final.d/mgr_t14_poison_touch.json
(the lord_of_decay record). The record's ``passive`` effect rows become the
character's standing passive rows through ``compile_passives``; the active
Decaying Presence numbers (bonus dice, dependent-feature cost overrides) are read
from the activated ``feature_state`` overrides with the same public reader Poison
Touch uses (combat/ext/feature_state.py). Hooks return early unless the actor owns
the reviewed row, so nothing changes for other characters.

Consumers:
  * ``compile_passives`` installs immunity to Poison damage and Poisoned, the
    Supreme Venom Resistance bypass, and the ownership row other hooks read.
  * ``save`` grants Advantage on saving throws against disease abilities.
  * ``immunity_as_resistance`` turns an ordinary Poison Immunity into Resistance
    for this character's Poison damage (artifact/Secret/conceptual/absolute
    Immunity is left alone by typed_reactions.immunity_is_ordinary).
  * ``damage_dealt`` delivers the once-per-turn 2d8 Poison-or-Necrotic rider
    while Decaying Presence is active.
  * ``after_save_resolved`` applies the Toxic Cloud healing denial to a creature
    that fails a save inside the owner's cloud while Decaying Presence is active.
  * ``event`` pays the standing Feast of Decay: once per round, when any creature
    affected by the owner's Poison Touch or Toxic Cloud is reduced to 0 Hit Points,
    the owner regains the record's printed Qi if the printed qualification holds.
  * ``concentration_waived``/``zone_creation_profile`` let the owner's Toxic
    Cloud activation skip Concentration while Decaying Presence is active.
"""
from copy import deepcopy

from . import hook

FEATURE = 'tianxia.subpath.qi.poison_cultivator.feature.lord_of_decay'
TOXIC_CLOUD = 'tianxia.subpath.qi.poison_cultivator.feature.toxic_cloud'
BLOCK = 'lord_of_decay'
NAME = 'Lord of Decay'
QI = 'resource:core.qi'
POISONED = 'condition:typed.poisoned'
POISON_TOUCH_CONDITION = 'condition:typed.poison_touch'
BONUS_USED = 'lord_of_decay_bonus_turn'
FEAST_USED = 'lord_of_decay_feast_round'
FEAST_FACT = 'lord_of_decay_feast_fact:'


def _record(info):
    return (info.get('mechanics') or {}).get(FEATURE) or {}


def _standing(record):
    """The printed standing clauses, typed as ``passive`` effect rows in the record."""
    return [row for row in record.get('effects') or () if isinstance(row, dict) and row.get('passive')]


def _rows(engine, actor):
    if actor is None:
        return []
    return [row for row in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, ())
            if row.get('block') == BLOCK and row.get('feature_id') == FEATURE]


def _owned(engine, actor):
    return bool(_rows(engine, actor))


def _trait_types(engine, actor, kind):
    """Damage types one reviewed standing clause names, read from the owned row."""
    for row in _rows(engine, actor):
        for trait in row.get('traits') or ():
            if trait.get('type') == kind:
                return {str(value).upper() for value in trait.get('damage_types') or ()}
    return set()


@hook('compile_passives')
def standing_traits(rows, info):
    """Copy the reviewed standing clauses into passive rows; inert without the row."""
    if FEATURE not in (info.get('owned_ids') or ()):
        return rows
    record = _record(info)
    standing = _standing(record)
    result = [*rows, {'block': BLOCK, 'feature_id': FEATURE, 'numbers': dict(info.get('numbers') or {}),
                      'traits': deepcopy(standing)}]
    for effect in standing:
        kind = str(effect.get('type') or '')
        types = [str(value).upper() for value in effect.get('damage_types') or ()]
        if kind == 'immunity':
            result.append({'block': 'defense', 'feature_id': FEATURE, 'kind': 'immunity',
                           'damage_types': types})
            conditions = [str(value).lower() for value in effect.get('conditions') or ()]
            if conditions:
                result.append({'block': 'condition_immunity', 'feature_id': FEATURE,
                               'conditions': conditions})
    return result


@hook('compile_action')
def activation_only(action, info):
    """Keep the standing rows out of the paid activation and name its active state plainly."""
    typed = action.parameters.get('typed') or {}
    if typed.get('source') != FEATURE:
        return None
    effects = list(typed.get('effects') or ())
    kept = [effect for effect in effects if not effect.get('passive')]
    changes = {}
    if len(kept) != len(effects):
        changes['parameters'] = {**action.parameters, 'typed': {**typed, 'effects': kept}}
    if action.display_name == 'Lord of Decay':
        changes['display_name'] = 'Decaying Presence'
    return action.model_copy(update=changes) if changes else None


@hook('save')
def disease_advantage(ctx, subject, ability, named):
    """"Advantage against disease": a save caused by a Disease ability."""
    if subject is None or not _owned(ctx.engine, subject):
        return None
    typed = ctx.typed or {}
    text = ' '.join(str(value or '').lower() for value in
                    (typed.get('source'), typed.get('sphere'), ctx.source))
    if 'disease' not in text:
        return None
    return {'bonus': 0, 'modes': ['ADVANTAGE']}


@hook('immunity_as_resistance')
def supreme_venom_immunity(engine, kind, typed, source_actor_id, target):
    """"treats ordinary Poison damage Immunity as Resistance" for this character's Poison."""
    upper = str(kind).upper()
    actor = engine.state.actors.get(str(source_actor_id or ''))
    if target is None or upper not in _trait_types(engine, actor, 'immunity_as_resistance'):
        return None
    from ..typed_reactions import immunity_is_ordinary

    return True if immunity_is_ordinary(engine, target, upper) is True else None


@hook('resistance_ignored')
def supreme_venom_resistance(engine, kind, typed, source_actor_id, target=None):
    """"Your Poison damage ignores ordinary Resistance" (a superior Resistance stays)."""
    upper = str(kind).upper()
    actor = engine.state.actors.get(str(source_actor_id or ''))
    if target is None or upper not in _trait_types(engine, actor, 'ignore_resistance'):
        return None
    from ..typed_reactions import immunity_is_ordinary, resistance_is_ordinary

    ordinary = resistance_is_ordinary(engine, target, upper)
    if ordinary is None and immunity_is_ordinary(engine, target, upper) is True:
        # The Immunity this same clause converted to Resistance is itself ordinary.
        ordinary = True
    return True if ordinary is True else None


def _presence(engine, actor):
    from .feature_state import overrides_for

    return overrides_for(actor, source_feature=FEATURE)


def _turn_stamp(engine):
    current = engine.state.actors.get(engine.state.current_actor_id)
    return f'{engine.state.round_number}:{engine.state.current_actor_id}:{current.turns_started if current else 0}'


def _poisoned(actor):
    return any(condition.condition_id == POISONED for condition in actor.conditions.values())


def _toxic_cloud_action(engine, source):
    action = engine.action_catalog.get(str(source or ''))
    if action is None:
        return None
    return action if (action.parameters.get('typed') or {}).get('source') == TOXIC_CLOUD else None


def _inside_own_cloud(engine, actor, owner):
    from .. import zones

    for zone in zones.typed_zones(engine):
        if zone.owner_id != owner.entity_id:
            continue
        if _toxic_cloud_action(engine, zone.source_definition_id) is None:
            continue
        if zones.actor_inside_zone(engine, actor, zone):
            return True
    return False


@hook('damage_dealt')
def presence_riders(ctx, target, amount):
    """The once-per-turn 2d8 poison/necrotic rider (Feast is a standing ``event``)."""
    if target is None or ctx.actor is None or not _owned(ctx.engine, ctx.actor):
        return
    if int(amount or 0) <= 0:
        return
    override = _presence(ctx.engine, ctx.actor).get(FEATURE) or {}
    count, sides = int(override.get('bonus_dice') or 0), int(override.get('bonus_sides') or 0)
    if count <= 0 or sides <= 0 or target.entity_id == ctx.actor.entity_id or not _poisoned(target):
        return
    stamp = _turn_stamp(ctx.engine)
    if ctx.actor.turn_flags.get(BONUS_USED) != stamp:
        _deal_presence_bonus(ctx, target, count, sides, stamp)


def _deal_presence_bonus(ctx, target, count, sides, stamp):
    from .choice_costs import Payment
    from .rider_choices import pick
    from ..typed_executor import Context, run_effects

    label = {'poison': f'{count}d{sides} additional Poison damage',
             'necrotic': f'{count}d{sides} additional Necrotic damage'}
    selected = pick(ctx.engine, ctx.actor, 'lord_of_decay_bonus', NAME, ['poison', 'necrotic'],
                    subject=target, intent=ctx.intent, labels=label, preferred=['poison'],
                    prompt_context=Payment(QI, 0).context(),
                    prompt=f'{NAME}: {ctx.action.display_name} damaged {target.display_name}, which is Poisoned. '
                           f'While Decaying Presence is active, once per turn it takes an additional '
                           f'{count}d{sides} Poison or Necrotic damage (your choice). Which damage type?',
                    automatic_options=['poison'])
    if not selected:
        return
    damage_type = selected[0]
    ctx.actor.turn_flags[BONUS_USED] = stamp
    effect = {'type': 'damage', 'applies_to': 'target',
              'dice': {'count': count, 'sides': sides, 'modifier': 0},
              'damage_types': [damage_type],
              'evidence': f'During Decaying Presence, once per turn, one Poisoned creature damaged by you '
                          f'takes an additional {count}d{sides} Poison or Necrotic damage.'}
    try:
        run_effects(Context(ctx.engine, ctx.actor, ctx.action, ctx.intent,
                            {'effects': [effect], 'numbers': dict(ctx.typed.get('numbers') or {})},
                            [target], target, {}), [effect])
    except BaseException:
        ctx.actor.turn_flags.pop(BONUS_USED, None)
        raise
    ctx.engine._append_event('PASSIVE_TRIGGERED', FEATURE, actor_id=ctx.actor.entity_id,
                             target_ids=(target.entity_id,),
                             payload={'feature_id': FEATURE, 'presence_bonus': f'{count}d{sides}',
                                      'damage_type': damage_type.upper(),
                                      'log': f'{NAME}: {target.display_name} is Poisoned and takes an additional '
                                             f'{count}d{sides} {damage_type.title()} damage (once per turn).'})


def _feast_terms(engine, owner):
    """The standing Feast of Decay numbers the reviewed record types."""
    for row in _rows(engine, owner):
        for trait in row.get('traits') or ():
            if trait.get('type') == 'feast_of_decay':
                return {'qi': int(trait.get('qi') or 0), 'max_cl_below': int(trait.get('max_cl_below') or 0)}
    return {}


def _level(engine, actor):
    """The creature's own compiled Cultivation Level, or None when its record has none."""
    for action_id in getattr(actor, 'action_ids', ()):
        action = engine.action_catalog.get(action_id)
        numbers = ((action.parameters or {}).get('typed') or {}).get('numbers') or {} if action is not None else {}
        if type(numbers.get('cl')) is int and numbers['cl'] > 0:
            return int(numbers['cl'])
    return None


def _controlled(target):
    """A creature under another's control never counts as a genuine kill."""
    return any(condition.condition_id in ('condition:typed.charmed', 'condition:typed.dominated')
               for condition in target.conditions.values())


def _revived(engine, target):
    """A creature already brought back this fight is not a fresh kill."""
    return any(event.event_type == 'CONDITION_REMOVED' and target.entity_id in event.target_ids
               and (event.payload or {}).get('reason') == 'REVIVED'
               for event in engine.events)


def _affected(engine, owner, target):
    """"affected by Poison Touch or Toxic Cloud" -- either link counts."""
    touched = any(condition.condition_id == POISON_TOUCH_CONDITION for condition in target.conditions.values())
    return touched or _inside_own_cloud(engine, target, owner)


def _qualifies(engine, owner, target, terms):
    """The part of the printed qualification committed state can decide by itself."""
    if target.team_id == owner.team_id:
        return False  # "genuinely hostile"
    if target.summon is not None or _controlled(target) or _revived(engine, target):
        return False  # "not created, captured, controlled, ... or repeatedly revived"
    level, mine = _level(engine, target), _level(engine, owner)
    if level is None or mine is None:
        return None  # the printed CL band rests on a creature fact this table does not hold
    return level >= mine - int(terms.get('max_cl_below') or 0)


def _feast_fact(engine, owner, target, qi):
    """Ask the table for the qualification facts no engine state holds, once per creature per fight."""
    from .needle import ask, checkpoint_id

    key = f'{FEAST_FACT}{target.entity_id}'
    held = owner.turn_flags.get(key)
    if held is not None:
        return bool(held)
    level, mine = _level(engine, target), _level(engine, owner)
    band = ' and is no more than 5 CL below you' if level is None or mine is None else ''
    chosen = ask(engine, engine._active_intent,
                 checkpoint_id(engine, 'feast_of_decay', owner.entity_id, target.entity_id), owner,
                 'choice:needle.lord_of_decay.feast_of_decay', ['qualifies'],
                 labels={'qualifies': f'It qualifies: regain {qi} Qi'},
                 allow_decline=True, default='decline', automatic=False, gm_adjudication=True,
                 name=NAME, feature_id=FEATURE, target_id=target.entity_id,
                 prompt=f'{NAME} (Feast of Decay): {target.display_name} was reduced to 0 Hit Points while '
                        f'affected by your Poison Touch or Toxic Cloud. Regain {qi} Qi once per round only if it '
                        f'is genuinely hostile{band}, and was not captured, preserved or repeatedly revived for '
                        'resource generation. Choose only when it qualifies.')
    owner.turn_flags[key] = 1 if chosen else 0
    return bool(chosen)


@hook('event')
def feast_of_decay(engine, event_type, kwargs):
    """The standing clause: any creature reduced to 0 HP, whoever struck the blow, no Presence needed."""
    if event_type != 'DAMAGE_COMMITTED':
        return
    payload = kwargs.get('payload') or {}
    if int(payload.get('hp_damage') or 0) + int(payload.get('temporary_hp_absorbed') or 0) <= 0:
        return
    for target_id in kwargs.get('target_ids') or ():
        target = engine.state.actors.get(str(target_id or ''))
        if target is None or target.current_hp > 0:
            continue
        for owner in engine.state.actors.values():
            if not owner.active or owner.entity_id == target.entity_id:
                continue
            terms = _feast_terms(engine, owner)
            qi = int(terms.get('qi') or 0)
            if qi <= 0 or owner.turn_flags.get(FEAST_USED) == engine.state.round_number:
                continue
            if not _affected(engine, owner, target):
                continue
            if _qualifies(engine, owner, target, terms) is False:
                continue
            if not _feast_fact(engine, owner, target, qi):
                continue
            owner.turn_flags[FEAST_USED] = engine.state.round_number
            engine._gain_resource(owner, QI, qi, FEATURE)
            engine._append_event('PASSIVE_TRIGGERED', FEATURE, actor_id=owner.entity_id,
                                 target_ids=(target.entity_id,),
                                 payload={'feature_id': FEATURE, 'feast_of_decay': qi,
                                          'log': f'{NAME}: {target.display_name} fell while affected by Poison Touch '
                                                 f'or Toxic Cloud; {owner.display_name} regains {qi} Qi '
                                                 f'(once per round).'})


@hook('after_save_resolved')
def cloud_healing_denial(ctx, subject, ability, named, failed):
    """A creature failing a save inside this owner's Toxic Cloud cannot regain Hit Points."""
    if not failed or subject is None or ctx.actor is None or subject is ctx.actor:
        return
    if not _owned(ctx.engine, ctx.actor) or _toxic_cloud_action(ctx.engine, ctx.source) is None:
        return
    if not (_presence(ctx.engine, ctx.actor).get(FEATURE) or {}).get('heal_denied'):
        return
    if not _inside_own_cloud(ctx.engine, subject, ctx.actor):
        return
    from ..typed_executor import Context, run_effects

    effect = {'type': 'healing_reduction', 'applies_to': 'target',
              'evidence': 'cannot regain Hit Points until the start of its next turn'}
    run_effects(Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, {'effects': [effect]},
                        [subject], subject, {}), [effect])


@hook('concentration_waived')
def toxic_cloud_without_concentration(engine, actor, action, ctx):
    """"Toxic Cloud needs no Concentration" while Decaying Presence is active."""
    typed = action.parameters.get('typed') or {}
    if typed.get('source') != TOXIC_CLOUD or not _owned(engine, actor):
        return None
    return True if (_presence(engine, actor).get(TOXIC_CLOUD) or {}).get('concentration_free') else None


@hook('effect_origins')
def armament_origin(engine, actor, action):
    """"Toxic Cloud ... may originate from you or Domain Armament" while Decaying Presence is active."""
    typed = action.parameters.get('typed') or {}
    if typed.get('source') != TOXIC_CLOUD or not _owned(engine, actor):
        return None
    if not (_presence(engine, actor).get(TOXIC_CLOUD) or {}).get('origin_domain_armament'):
        return None
    from .qi_path import armament_condition, armament_point

    if armament_condition(actor) is None:
        return None
    x, y = armament_point(actor)
    return [{'id': 'lord_of_decay:armament',
             'label': f'{action.display_name} from your Domain Armament',
             'position': {'x': int(x), 'y': int(y)}}]


@hook('zone_creation_profile')
def cloud_profile(zone, ctx):
    """Keep the unlinked cloud state when the owner's Toxic Cloud skipped Concentration."""
    typed = ctx.typed or {}
    if typed.get('source') != TOXIC_CLOUD or not _owned(ctx.engine, ctx.actor):
        return None
    if not (_presence(ctx.engine, ctx.actor).get(TOXIC_CLOUD) or {}).get('concentration_free'):
        return None
    return zone.model_copy(update={'concentration_link': False})
