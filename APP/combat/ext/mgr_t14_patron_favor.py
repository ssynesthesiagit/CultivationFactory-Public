"""Patron Spirit's Favor on the technique's own compiled activation.

Final compilation publishes priced variants, preserving the ordinary action and
its targeting, costs, origin and source. Only native Elemental Prayer delivery
is enabled; its printed Patron tag uses the public saved-patron contract.
Other tagged techniques remain deferred.
No damage type, sphere name, terrain or allegiance supplies a missing fact.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from . import effect, hook

FAVOR = 'tianxia.subpath.qi.shugenja.feature.patron_spirit_s_favor'
PRAYER = 'tianxia.subpath.qi.shugenja.feature.elemental_prayer'
BLOCK = 'mgr_t14_patron_favor'
QI = 'resource:core.qi'
KEY = 'patron_spirit_favor'
# Widen and healing Empower await native delivery coverage; Prayer has neither.
NAMES = ('Empower', 'Overwhelm', 'Drive', 'Shelter')
_SAVE = ContextVar('patron_favor_save', default=None)


@effect('patron_favor_ownership')
def ownership_effect(ctx, row):
    """A passive declaration; never an independently payable activation."""


@hook('compile_passives')
def ownership(rows, info):
    if FAVOR not in info['owned_ids'] or int(info['numbers']['cl']) < 10:
        return None
    return [*rows, {'block': BLOCK, 'feature_id': FAVOR, 'numbers': dict(info['numbers'])}]


def prayer_source(typed):
    return (typed.get('source') == PRAYER and
            any(row.get('type') == 'shugenja_prayer' for row in typed.get('effects', [])))


def tagged(typed):
    return typed.get('qi_powered') is not False and (prayer_source(typed) or (typed.get('qi_powered') is True and
                                  bool(set(typed.get('source_tags') or []) &
                                       {'air', 'cold', 'earth', 'fire', 'lightning', 'metal', 'water', 'wood'})))


def widen(action):
    """Grow the actual native geometry before candidate targeting, once."""
    typed = action['parameters']['typed']
    area = typed.get('area') or {}
    shape = area.get('shape')
    if shape not in ('sphere', 'cylinder', 'cone', 'line', 'cube') or not area.get('size_ft'):
        return False
    extra = 20 if shape == 'line' else 10
    area['size_ft'] += extra
    # zone_spec is the same declared primary geometry, when the action creates
    # a lasting field as well as using the immediate targeting geometry.
    zone = typed.get('zone_spec')
    if isinstance(zone, dict) and zone.get('shape') == shape and zone.get('size_ft'):
        zone['size_ft'] += extra
    if action.get('radius_ft') is not None:
        action['radius_ft'] += extra
    return True


@hook('compile_bundle')
def variants(bundle, info):
    if not any(r.get('block') == BLOCK for r in bundle.get('typed_passives', [])):
        return None
    result = deepcopy(bundle)
    for base in bundle['action_catalog']:
        typed = base.get('parameters', {}).get('typed') or {}
        # Only Prayer has verified native delivery here. Explicit tags alone
        # do not certify healing, delayed saves or effect-owned area geometry.
        if (not prayer_source(typed) or not tagged(typed) or typed.get(KEY) or
                base['economy'] not in ('ACTION', 'BONUS_ACTION', 'NONE') or
                base.get('parameters', {}).get('setting_only')):
            continue
        for favor in NAMES:
            row = deepcopy(base)
            params = row['parameters']
            params['typed'][KEY] = favor.lower()
            params['typed']['variant_of'] = base['source_definition_id']
            # This is one priced use of the original Source Rule. Generic
            # costs, funding alternatives, economy and per-source limits remain.
            prices = {}
            for resource, amount in [*row['costs'], [QI, 2]]:
                prices[resource] = prices.get(resource, 0) + amount
            row['costs'] = [[resource, amount] for resource, amount in prices.items()]
            params['typed']['min_cl'] = max(10, int(params['typed'].get('min_cl') or 0))
            row['source_definition_id'] += '#patron_favor_' + favor.lower()
            row['display_name'] += ' — Patron Spirit’s Favor: ' + favor + ' (+2 Qi)'
            params['description'] = ('Choose this Favor before resolving the technique. '
                'Once per turn; one Favor per activation. ' + {
                'Empower': 'Add 3d8 to one chosen damage or healing roll.',
                'Overwhelm': 'Subtract 1d4 from the first saving throw against this technique.',
                'Widen': 'Increase its radius or cone by 10 feet, line by 20 feet, or cube side by 10 feet.',
                'Drive': 'Increase one chosen push, pull, lift or forced movement by 10 feet.',
                'Shelter': 'One consenting affected creature or creature within 10 feet of the origin gains twice your Proficiency Bonus temporary HP.'}[favor])
            result['action_catalog'].append(row)
            result['actor_template']['action_ids'].append(row['source_definition_id'])
    return result


def owner(engine, actor):
    return next((r for r in engine.typed_passive_rows.get(actor.entity_id, [])
                 if r.get('block') == BLOCK and r.get('feature_id') == FAVOR), None)


def stamp(engine):
    return f'{engine.state.round_number}:{engine.state.current_actor_id}'


def qualifies(engine, actor, action):
    from .shugenja_prayer import patron
    from .ability_lockout import records
    if any(c.data.get('mode') == 'barred' and c.data.get('ability') == FAVOR for c in records(actor)):
        return False
    typed = action.parameters.get('typed') or {}
    chosen = patron(actor)
    return bool(owner(engine, actor) and chosen and prayer_source(typed) and tagged(typed))


@hook('candidate_allowed')
def admission(engine, actor, candidate, action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    favor = typed.get(KEY)
    if not favor:
        return None
    if not qualifies(engine, actor, action) or actor.turn_flags.get(KEY) == stamp(engine):
        return False
    if prayer_source(typed):
        from .shugenja_prayer import patron, SAVES
        chosen = patron(actor)
        if favor == 'overwhelm' and chosen not in SAVES:
            return False
        if favor == 'drive' and chosen not in ('air', 'water'):
            return False
    return None


@hook('technique_accepted')
def accepted(engine, actor, action):
    if not (action.parameters.get('typed') or {}).get(KEY):
        return
    if not qualifies(engine, actor, action) or actor.turn_flags.get(KEY) == stamp(engine):
        raise ValueError('Patron Spirit’s Favor is unavailable for this activation.')
    actor.turn_flags[KEY] = stamp(engine)
    engine._append_event('PASSIVE_TRIGGERED', FAVOR, actor_id=actor.entity_id,
        payload={'technique': action.source_definition_id, 'favor': action.parameters['typed'][KEY],
                 'log': action.display_name + ': 2 additional Qi; this turn’s Favor is used.'})


def selected(ctx, favor):
    return (ctx.typed.get(KEY) == favor and qualifies(ctx.engine, ctx.actor, ctx.action)
            and not ctx.damage_cache.get(KEY + ':used'))


def pick(ctx, name, options, labels, *, target=None, optional=True, automatic_options=None):
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context
    return ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, 'patron_favor_' + name, len(ctx.engine.events)), ctx.actor,
        'choice:needle.patron_favor_' + name, options, labels=labels,
        preferred=options[:1], allow_decline=optional, automatic_options=automatic_options, name='Patron Spirit’s Favor',
        feature_id=FAVOR, target_id=target.entity_id if target else None,
        prompt=f'Patron Spirit’s Favor — {ctx.action.display_name}: choose {name}. '
               'The 2 additional Qi is included in this activation; no further cost.',
        prompt_context=action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id,
                                      target or ctx.actor, action=ctx.action))


def die(ctx, count, sides, reason, *, critical=False):
    from ..gate2_runtime_models import DiceSpec
    roll = ctx.engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=0),
        actor_id=ctx.actor.entity_id, reason='PATRON_FAVOR_' + reason, critical=critical)
    ctx.engine._record_roll(roll)
    return int(roll.total)


def empower(ctx, effect, *, healing=False):
    if not selected(ctx, 'empower'):
        return None
    # Flat healing is not a healing roll. Damage's hook is already die-only.
    if healing and not (effect.get('dice') or effect.get('dice_by_cl')):
        return None
    target = ctx.target or (ctx.targets[0] if ctx.targets else ctx.actor)
    picked = pick(ctx, 'roll', ['apply', 'keep'],
        {'apply': 'Add 3d8 to this ' + ('healing' if healing else 'damage') + ' roll',
         'keep': 'Keep Empower for a later roll in this activation'}, target=target)
    if not picked or picked[0] != 'apply':
        return None
    ctx.damage_cache[KEY + ':used'] = 1
    return die(ctx, 3, 8, 'EMPOWER', critical=bool(ctx.critical_hit and not healing))


@hook('damage_roll_bonus')
def damage_bonus(ctx, effect, kinds):
    return empower(ctx, effect)


@hook('effect_resolution_scope')
def overwhelm_scope(ctx, effect):
    if selected(ctx, 'overwhelm'):
        return save_scope(ctx)
    return None


@contextmanager
def save_scope(ctx):
    token = _SAVE.set((ctx.engine, ctx))
    try:
        yield
    finally:
        _SAVE.reset(token)


@hook('before_d20_bonus')
def overwhelm(engine, request, intent):
    pending = _SAVE.get()
    context = engine.d20_context() or {}
    if pending is None or pending[0] is not engine or context.get('kind') != 'save':
        return None
    ctx = pending[1]
    if (context.get('source_id') != ctx.source or context.get('source_actor_id') != ctx.actor.entity_id
            or not selected(ctx, 'overwhelm')):
        return None
    ctx.damage_cache[KEY + ':used'] = 1
    return -die(ctx, 1, 4, 'OVERWHELM')


@hook('effect_resolution_scope')
def drive_scope(ctx, effect):
    if not selected(ctx, 'drive') or effect.get('type') != 'forced_movement' or int(effect.get('distance_ft') or 0) <= 0:
        return None
    return drive(ctx, effect)


@contextmanager
def drive(ctx, effect):
    from ..typed_executor import default_subjects
    subjects = [a for a in default_subjects(ctx, effect, harmful=True) if a.active and a is not ctx.actor]
    if subjects and selected(ctx, 'drive'):
        ids = [a.entity_id for a in subjects]
        picked = pick(ctx, 'movement', ids,
            {a.entity_id: f'Increase {a.display_name}’s forced movement by 10 feet' for a in subjects},
            # These subjects already passed the technique's hit/save gate.
            # Drive requires no sight; do not re-filter a remembered-square hit.
            target=subjects[0], automatic_options=ids)
        if picked:
            ctx.damage_cache[KEY + ':drive'] = (id(effect), picked[0])
            ctx.damage_cache[KEY + ':used'] = 1
    try:
        yield
    finally:
        ctx.damage_cache.pop(KEY + ':drive', None)


@hook('forced_movement_bonus')
def drive_bonus(ctx, subject, effect):
    if ctx.damage_cache.get(KEY + ':drive') == (id(effect), subject.entity_id):
        return 10
    return None


@hook('technique_used')
def shelter(ctx):
    if not selected(ctx, 'shelter'):
        return
    from .. import action_geometry, relations, target_knowledge
    from .willing_targets import asks_consent
    # The actual resolved origin is retained by action_geometry's native scope;
    # candidate.destination is an aim/area centre, never a fabricated origin.
    affected = set()
    for event in ctx.engine.events[ctx.technique_event_start:]:
        if event.source_definition_id != ctx.action.source_definition_id:
            continue
        if event.event_type == 'MOVEMENT_COMMITTED' and len(event.payload.get('path') or []) > 1:
            affected.add(event.actor_id)
        if event.actor_id != ctx.actor.entity_id:
            continue
        actual = event.event_type in {'CONDITION_APPLIED', 'MODIFIER_APPLIED'}
        if event.event_type == 'DAMAGE_COMMITTED':
            actual = int(event.payload.get('hp_damage') or 0) + int(event.payload.get('temporary_hp_absorbed') or 0) > 0
        if event.event_type in {'HEALING_APPLIED', 'TEMP_HP_GRANTED'}:
            actual = int(event.payload.get('after') or 0) > int(event.payload.get('before') or 0)
        if actual:
            affected.update(event.target_ids)
    subjects = [a for a in ctx.engine.state.actors.values() if a.active
                and (a.entity_id in affected or action_geometry.distance(ctx.engine, ctx.actor, a) <= 10)]
    if not subjects:
        return
    picked = pick(ctx, 'shelter', [a.entity_id for a in subjects],
        {a.entity_id: f'{a.display_name}: offer {2 * int(owner(ctx.engine, ctx.actor)["numbers"]["pb"])} temporary HP'
         for a in subjects}, target=ctx.target,
        automatic_options=[a.entity_id for a in subjects if a.entity_id in affected or a is ctx.actor or
            ((known := target_knowledge.knowledge(ctx.engine, ctx.actor, a)) is not None and known.mode == 'DIRECT')])
    if not picked:
        return
    subject = next(a for a in subjects if a.entity_id == picked[0])
    accepted = asks_consent(ctx.engine, ctx.intent, subject, FAVOR,
        f'Patron Spirit’s Favor: {ctx.actor.display_name} offers you temporary HP equal to twice their '
        f'Proficiency Bonus after {ctx.action.display_name}. Accept? No action or cost to you.',
        prefer_accept=relations.relation(ctx.engine, subject, ctx.actor) == relations.ALLY, asker=ctx.actor)
    if accepted:
        ctx.damage_cache[KEY + ':used'] = 1
        ctx.engine._grant_temp_hp(subject, 2 * int(owner(ctx.engine, ctx.actor)['numbers']['pb']), FAVOR, ctx.actor.entity_id)
