"""First flight consumers, sourced from rules_text.json (lock round 10).

Wind-Borne Body grants 20/30 Fly Speed through the end of the owner's turn after
Gather Current or starting in its own Air Current. Current provenance comes
from the area's sealed source_profile (C9) or its bound action's Air sphere;
appearance and names never confer it. The native engine owns flight and expiry.

Featherfall asks its owner for up to PB falling creatures within 60 ft, pays one
Qi each plus the Reaction, and records the one-minute 60-ft/round safe descent.
The protected creature may end it at the start of its own turn. This grants no
flight or horizontal movement. Air's Feather-Fall Breath is the same Reaction with
the other reading of the same printed shape: a cushioning current that shortens
the distance the fall's damage is calculated from (kind "fall_cushion", reduced
distance and, from its printed CL, landing on its feet), costing only the
Reaction. Both kinds share one choice and every number comes from the feature's
feature_blocks.d row; a creature that owns both is asked which to use. Each
kind's printed numbers are also the code default (KIND_DEFAULTS), so a fight
saved before those numbers moved onto the row keeps them. Each is answered for
each creature that falls at least FALL_TRIGGER_FT on its own account: one fall
far enough in a batch never makes a shorter drop, or one out of the owner's
reach, cost the owner's Reaction. Public reaction admission/recording helpers are
shared with typed reactions; source-specific effects stay here.

Launching Uppercut's hostile Counter line is a chosen Counterstrike modifier:
after actual damage, spend Martial Focus, launch a legal-sized target ten feet,
stop its current movement, then use the native fall. Its separate Ally Launch
permission/timing remains an explicit rider for a later Counterstrike port.
"""

from ..paid_relocation import activation
from . import effect, hook, note
from .needle import ask, checkpoint_id

BLOCK = 'altitude_abilities'
WIND = 'TAL_AIR_WIND_BORNE_BODY'
GATHER = 'AIR_BASE_GATHER_CURRENT'
FEATHER = 'tianxia.path.qi_cultivation.feature.featherfall'
UPPERCUT = 'TAL_RETRIBUTION_LAUNCHING_UPPERCUT'
CRANE = 'tianxia.talent.chains.drag_down_the_flying_crane'
WIND_CONDITION = 'condition:typed.wind_borne_body'
FEATHER_CONDITION = 'condition:typed.featherfall'
FOCUS, QI = 'resource:core.martial_focus', 'resource:core.qi'


@hook('candidate_allowed')
def crane_flying_target(engine, actor, candidate, action):
    """Drag Down targets one flying creature, never a grounded creature.

    Rejecting a ground target also prevents the generic displacement recipe from
    pushing that illegal target sideways through map hazards.
    """
    if action is None or action.parameters.get('typed', {}).get('source') != CRANE:
        return None
    targets = [engine.state.actors.get(aid) for aid in candidate.target_ids]
    modern = any(e.get('type') == 'chains_crane_descent'
                 for row in action.parameters['typed'].get('effects', [])
                 for branch in ('on_fail', 'on_success') for e in row.get(branch, []))
    if modern:
        from ..flight import profile
        return bool(targets) and all(target is not None and target.position.z > 0
            and profile(engine, target).speed_ft > 0 for target in targets)
    return bool(targets) and all(target is not None and target.position.z > 0 for target in targets)


@effect('chains_crane_descent')
def crane_descent(ctx, row):
    """Opt-in Crane descent uses native vertical collision and stable landing."""
    from ..falling import displace, supported
    from ..typed_executor import run_effects
    target = ctx.target
    if ctx.typed.get('source') != CRANE or target is None:
        return
    requested = min(int(row.get('distance_ft', 0)), target.position.z * 5)
    moved = displace(ctx.engine, target, -(requested // 5), ctx.source,
                    intent=ctx.intent, settle_after=False)
    blocked = requested - moved
    # An occupied creature volume may stop displacement too, but the printed
    # damage applies only to solid map/object obstacles.
    below = target.position.model_copy(update={'z': max(0, target.position.z - 1)})
    solid = blocked > 0 and not ctx.engine.grid.volume_legal(below, footprint=ctx.engine._footprint(target))
    damage = min(5, blocked // 10) * int(ctx.numbers.get('pb') or ctx.actor.proficiency_bonus) if solid else 0
    if damage:
        run_effects(ctx, [{'type': 'damage', 'flat': damage, 'damage_types': ['bludgeoning']}])
    if row.get('prone_on_landing') and supported(ctx.engine, target):
        run_effects(ctx, [{'type': 'condition', 'condition': 'prone', 'duration': 'until_removed'}])


@hook('compile_block')
def compile_flight(block, spec, row, numbers):
    if block != BLOCK:
        return None
    # Every number the printed text gives this feature rides on the row (combat/rules/feature_blocks.d/), so a
    # second ability of the same kind is a data row, not new code. Fall protection reads them in _fall_protection.
    carried = {key: spec[key] for key in ('range_ft', 'reduce_ft', 'reduce_ft_by_cl', 'fall_speed_ft', 'fall_speed_ft_by_cl',
                                          'targets', 'targets_by_cl', 'upright', 'upright_cl', 'cost')
               if key in spec}
    return [{**row, 'kind': spec['kind'], 'numbers': {**numbers, **carried}, 'name': spec.get('name') or row.get('name')}]


def _row(engine, actor, kind):
    return next((r for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())
                 if r.get('block') == BLOCK and r.get('kind') == kind), None)


def _current(engine, owner):
    from .. import zones
    for zone in zones.typed_zones(engine):
        if not zone.active or zone.owner_id != owner.entity_id:
            continue
        profile = zone.trigger_profile.get('source_profile') or {}
        action = engine.action_catalog.get(zone.source_definition_id)
        typed = action.parameters.get('typed', {}) if action else {}
        sphere = profile.get('sphere_id') or typed.get('sphere')
        source = profile.get('mechanic_id') or typed.get('source')
        if sphere == 'tianxia.sphere.air' and source != 'TAL_AIR_COURT_OF_THE_FOUR_WINDS' and engine._in_zone(owner, zone):
            return True
    return False


def _wind(engine, actor):
    row = _row(engine, actor, 'wind')
    if row is None or not actor.active or int(row['numbers'].get('cl', 1)) < 5:
        return
    speed = 30 if int(row['numbers']['cl']) >= 11 else 20
    engine._apply_condition(actor, WIND_CONDITION, WIND, actor.entity_id,
        expires_on='END_OF_CURRENT_TURN', data={'fly_speed_ft': speed})
    note(engine, WIND, actor, f'{actor.display_name} can fly at a Speed of {speed} ft. until this turn ends.')


@hook('technique_used')
def gather_complete(ctx):
    if ctx.typed.get('source') == GATHER and str(ctx.action.economy) == 'BONUS_ACTION':
        _wind(ctx.engine, ctx.actor)


@hook('turn_start')
def flight_turn(engine, actor):
    if _row(engine, actor, 'wind') and _current(engine, actor):
        _wind(engine, actor)
    if any(c.condition_id == FEATHER_CONDITION for c in actor.conditions.values()):
        choice = ask(engine, getattr(engine, '_active_intent', None), checkpoint_id(engine, 'end_featherfall'), actor,
            'choice:needle.end_featherfall', ['keep', 'end'],
            labels={'keep': 'Keep the safe descent', 'end': 'End Featherfall on yourself'},
            preferred=['keep'], name='Featherfall', feature_id=FEATHER)
        if choice == ['end']:
            engine._remove_condition(actor, FEATHER_CONDITION, FEATHER)
            note(engine, FEATHER, actor, f'{actor.display_name} ends Featherfall on themself.')


# ----------------------------------------------------------------------------------------- falling reactions
# One printed shape, two readings of it. Both are a Reaction answering a fall, so both ask their owner which
# falling creatures to help, pay their own printed cost, and record one protection per chosen creature:
#   kind 'featherfall'   a slow descent (Path Featherfall). combat/falling.py reads the recorded
#                        fall_speed_ft / fall_damage_immune / fall_lands_upright while the creature falls.
#   kind 'fall_cushion'  a cushioning current (Air's Feather-Fall Breath): the fall still happens, but the
#                        distance its damage is calculated from is shorter, so falling_damage_distance shortens
#                        it before the dice are rolled (ordinary defenses then reduce what the shorter fall
#                        deals) and the fall may end with the creature on its feet.
# Every number is read from the feature's own building-block row (combat/rules/feature_blocks.d/), so a second
# printed ability of either kind needs a data row, not new code.
FALL_KINDS = ('featherfall', 'fall_cushion')
CUSHION_CONDITION = 'condition:typed.air_fall_cushion'
#: A creature that has not fallen at least this far cannot be helped by either reading.
FALL_TRIGGER_FT = 10
#: Each kind's printed numbers, used for a number the feature's row does not carry. 'featherfall' is the
#: printed Path Featherfall - one Qi each, 60 feet, up to your Proficiency Bonus, a 60-foot descent - and it
#: is also what a fight saved before those numbers moved onto the row still has, so it is a code default and
#: not only a data one.
KIND_DEFAULTS = {
    'featherfall': {'cost': 1, 'range_ft': 60, 'targets': 'pb', 'fall_speed_ft': 60, 'upright': True,
                    'name': 'Featherfall', 'checkpoint': 'featherfall', 'choice': 'choice:needle.featherfall'},
    'fall_cushion': {'cost': 0, 'range_ft': 30, 'targets': 1, 'reduce_ft': 0,
                     'name': 'Feather-Fall Breath', 'checkpoint': 'fall_cushion',
                     'choice': 'choice:needle.fall_cushion'},
}


def _cl_number(value, cl, default):
    """A block number that the printed text scales by Cultivation Level ('reduce_ft_by_cl': [[1,4,30],[5,20,60]])."""
    if isinstance(value, list):
        for low, high, number in value:
            if int(low) <= cl <= int(high):
                return int(number)
        return default
    return int(value) if value is not None else default


def _fall_protection(row, cl):
    """The protection one creature gets from this row, as printed: how far the fall is shortened or slowed,
    whether it lands upright, how many creatures one use may help, and what the choice is transported as."""
    kind = str(row.get('kind'))
    spec = {**KIND_DEFAULTS.get(kind, {}), **(row.get('numbers') or {})}
    cushion = kind == 'fall_cushion'
    upright = bool(spec.get('upright')) or (cushion and cl >= int(spec.get('upright_cl') or 0))
    targets = spec.get('targets_by_cl') or spec.get('targets')
    if isinstance(targets, list):
        targets = next((number for low, high, number in targets if int(low) <= cl <= int(high)), 1)
    return {'kind': kind, 'cost': int(spec.get('cost') or 0),
            'range_ft': int(spec.get('range_ft') or 0), 'upright': upright,
            'name': str(row.get('name') or KIND_DEFAULTS.get(kind, {}).get('name') or 'the falling reaction'),
            'checkpoint': str(spec.get('checkpoint') or 'fall'), 'choice': str(spec.get('choice') or 'choice:needle.fall'),
            'reduce_ft': _cl_number(spec.get('reduce_ft_by_cl') or spec.get('reduce_ft'), cl, 0) if cushion else 0,
            'fall_speed_ft': 0 if cushion else _cl_number(spec.get('fall_speed_ft_by_cl') or spec.get('fall_speed_ft'), cl, 60),
            'targets': 'pb' if targets in ('pb', 'proficiency_bonus') else int(targets or 1)}


def _drop_ft(engine, actor):
    """The distance this creature is about to fall, in feet, as the pending set published it.

    combat.falling.settle records one planned distance per falling creature before any of them moves; a call
    outside a settle has published nothing, so nothing it passes is eligible to be helped.
    """
    plans = getattr(engine, '_fall_plans', None) or {}
    return int(plans.get(actor.entity_id, 0) or 0)


def _helped(engine, owner, actors, reach):
    """The falling creatures this owner could protect on this fall: in reach, and each falling far enough itself.

    "You or a creature within 30 feet falls 10 feet or more" is printed about one creature at a time, so the
    minimum is each candidate's own planned drop. A batch is not one trigger: a five-foot drop beside a ten-foot
    one cannot be helped, and a ten-foot drop the owner cannot reach does not make a five-foot drop in reach
    eligible either. A creature already carrying one of these protections is not offered a second.
    """
    return [actor.entity_id for actor in actors
            if _drop_ft(engine, actor) >= FALL_TRIGGER_FT
            and engine._distance_actor_to_actor(owner, actor) <= reach
            and not any(c.condition_id in (FEATHER_CONDITION, CUSHION_CONDITION) for c in actor.conditions.values())]


def _offerable(engine, owner, actors, intent):
    """Every owned falling reaction this fall could answer for, as (row, plan) pairs.

    A reading with nothing left to protect is not offered: each one is admitted on its own reach and its own
    creatures' printed minimum drop, so a fall elsewhere in the batch cannot spend this owner's Reaction.
    A character that owns one reading is offered it alone. A character that owns both is asked which one
    to use, with each one's own printed price beside its name, and only that one is paid for and spent.
    """
    from ..typed_reactions import can_use_reaction

    owned = []
    for kind in FALL_KINDS:
        row = _row(engine, owner, kind)
        if row is None or not can_use_reaction(engine, owner, None, row):
            continue
        plan = _fall_protection(row, int((row.get('numbers') or {}).get('cl') or 1))
        if _helped(engine, owner, actors, plan['range_ft'] or 30):
            owned.append((row, plan))
    if len(owned) < 2:
        return owned
    price = {'featherfall': 'spends Qi and your Reaction', 'fall_cushion': 'costs only your Reaction'}
    chosen = ask(engine, intent, checkpoint_id(engine, 'fall_ability', owner.entity_id), owner,
                 'choice:needle.fall_ability', [plan['checkpoint'] for _, plan in owned],
                 labels={plan['checkpoint']: f"{plan['name']} ({price.get(plan['kind'], 'costs your Reaction')})"
                         for _, plan in owned},
                 prompt='Choose which of your falling abilities to use on this fall. Whichever you choose, '
                        'it costs your Reaction.',
                 preferred=[owned[0][1]['checkpoint']], maximum=1, allow_decline=True,
                 default='decline', name='A falling ability', feature_id=str(owned[0][0].get('feature_id') or ''))
    if not chosen:
        return []
    picked = {plan['checkpoint']: (row, plan) for row, plan in owned}
    return [picked[key] for key in chosen if key in picked]


def _protect_falling(engine, owner, row, plan, actors, intent):
    """Ask which falling creatures this reaction helps, pay its printed cost and record the protection."""
    from ..typed_reactions import open_reaction

    name, feature = plan['name'], str(row.get('feature_id') or '')
    reach = plan['range_ft'] or 30
    options = _helped(engine, owner, actors, reach)
    from .needle import ai_controlled
    from .equipment_armor import can_see
    if ai_controlled(engine, owner):
        options = [key for key in options if engine.state.actors[key].team_id == owner.team_id
                   and (key == owner.entity_id or can_see(engine, owner, engine.state.actors[key]))]
    allowance = owner.proficiency_bonus if plan['targets'] == 'pb' else int(plan['targets'])
    maximum = min(allowance, owner.resources.get(QI, 0) // plan['cost'] if plan['cost'] else allowance, len(options))
    if maximum <= 0:
        return
    preferred = [key for key in options if engine.state.actors[key].team_id == owner.team_id][:maximum]
    prompt = (f'Choose which falling creatures {name} helps.'
              + (f' Spend {plan["cost"]} Qi for each one, and your Reaction.'
                 if plan['cost'] else ' This costs only your Reaction.'))
    checkpoint = checkpoint_id(engine, plan['checkpoint'], owner.entity_id)
    chosen = ask(engine, intent, checkpoint, owner, plan['choice'], options,
                 labels={key: engine.state.actors[key].display_name for key in options}, prompt=prompt,
                 preferred=preferred, maximum=maximum, allow_decline=True, automatic=bool(preferred),
                 default='decline' if not preferred else 'first', name=name, feature_id=feature)
    if not chosen:
        return
    with activation(engine, owner, feature or name):
        if plan['cost']:
            engine._spend_resource(owner, QI, len(chosen) * plan['cost'], feature or name)
        open_reaction(engine, row, owner, tuple(chosen), checkpoint)
        data = ({'reduce_ft': plan['reduce_ft'], 'lands_upright': 1} if plan['upright'] else {'reduce_ft': plan['reduce_ft']})
        for key in chosen:
            target = engine.state.actors[key]
            if plan['kind'] == 'fall_cushion':
                # The cushion lasts exactly as long as the fall it cushions, so it is spent with that fall.
                engine._apply_condition(target, CUSHION_CONDITION, feature or name, owner.entity_id, expires_on='CONSUMED', data=data)
            else:
                from ..typed_executor import clock_expiry

                engine._apply_condition(target, FEATHER_CONDITION, feature or name, owner.entity_id,
                                        expires_on=clock_expiry(engine, 'minutes', 1),
                                        data={'fall_speed_ft': plan['fall_speed_ft'], 'fall_damage_immune': 1, 'fall_lands_upright': 1})
        said = ('the wind cushions the fall' if plan['kind'] == 'fall_cushion'
                else f'the chosen creatures descend safely, at most {plan["fall_speed_ft"]} ft. each round')
        engine._append_event('REACTION_RESOLVED', feature or name, actor_id=owner.entity_id, target_ids=tuple(chosen),
                             payload={'log': f'{owner.display_name} uses {name}: {said}.'})


@hook('falling')
def featherfall(engine, actors, intent):
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        for row, plan in _offerable(engine, owner, actors, intent):
            _protect_falling(engine, owner, row, plan, actors, intent)


def _cushion(engine, target):
    """The cushioning currents this creature is carrying right now, or [] (the caller is not its owner)."""
    return [c for c in target.conditions.values()
            if c.condition_id == CUSHION_CONDITION and 'reduce_ft' in (c.data or {})]


@hook('falling_damage_distance')
def fall_cushion_distance(engine, target, distance, context, intent):
    """"Reduce the fall distance used to calculate fall damage": the shorter distance, before the dice.

    Asked of the falling creature only, so nothing else in the fight changes: the returned distance is what
    combat/falling.py rolls from, and the creature's Resistance, Vulnerability, flat reductions and Temporary
    HP then reduce what that shorter fall deals, exactly as they reduce any other damage.
    """
    held = _cushion(engine, target)
    if not held:
        return None
    cushion = max(int((c.data or {}).get('reduce_ft') or 0) for c in held)
    left = max(0, int(getattr(context, 'distance_ft', 0)) - cushion)
    owners = sorted({str(c.source_actor_id or '') for c in held})
    note(engine, CUSHION_CONDITION, engine.state.actors.get(owners[0]) or target,
         f'The cushioning current shortens the {int(getattr(context, "distance_ft", 0))} ft. fall '
         f'to {left} ft. for {target.display_name}, so only that distance is used to calculate the damage.',
         (target.entity_id,))
    return left


@hook('falling_damage')
def fall_cushion(engine, target, amount, context, intent):
    """The end of a cushioned fall: the cushion is spent with it, and the creature may land on its feet.

    ``amount`` was already defended at the distance the cushion left (falling_damage_distance), so this hook
    changes no damage; it spends the recorded cushion and reports the printed landing posture. "At CL 11, the
    target may also land on its feet if it is not Incapacitated", so an Incapacitated creature is left to land
    as it falls.
    """
    from .condition_ownership import remove_instance
    from .needle import incapacitated

    held = _cushion(engine, target)
    if not held:
        return None
    upright = any((c.data or {}).get('lands_upright') for c in held)
    for c in held:
        remove_instance(engine, target, c.instance_id, CUSHION_CONDITION)
    if not upright:
        return None
    if incapacitated(target):
        note(engine, CUSHION_CONDITION, target,
             f'{target.display_name} is Incapacitated, so the cushion cannot stand them on their feet; they land as they fell.')
        return None
    note(engine, CUSHION_CONDITION, target,
         f'{target.display_name} lands on their feet instead of falling prone.')
    return {'land_prone': False}


@hook('falling_unresolved')
def fall_cushion_unspent(engine, actor, intent):
    """A fall that could not land spends no cushion: the protection goes with the attempt it was paid for."""
    from .condition_ownership import remove_instance

    for c in _cushion(engine, actor):
        remove_instance(engine, actor, c.instance_id, CUSHION_CONDITION)


@effect('launching_uppercut')
def uppercut(ctx, effect):
    from ..falling import displace
    target, owner, engine = ctx.target, ctx.actor, ctx.engine
    if target is None or target.team_id == owner.team_id or owner.resources.get(FOCUS, 0) < 1:
        return
    if engine._footprint(target).width_cells > engine._footprint(owner).width_cells + 1:
        return
    damaged = False
    for event in reversed(engine.events):
        if event.event_type == 'ATTACK_ROLLED':
            break
        if event.event_type == 'DAMAGE_COMMITTED' and target.entity_id in event.target_ids and event.source_definition_id == ctx.source:
            damaged |= int(event.payload.get('reduced_to', 0)) > 0
    if not damaged:
        return
    selected = ask(engine, ctx.intent, checkpoint_id(engine, 'launching_uppercut', target.entity_id), owner,
        'choice:needle.launching_uppercut', ['launch'], labels={'launch': f'Launch {target.display_name} 10 ft. upward'},
        prompt='Spend Martial Focus to launch the damaged creature and end its current movement.',
        allow_decline=True, name='Launching Uppercut', feature_id=UPPERCUT)
    if not selected:
        return
    engine._spend_resource(owner, FOCUS, 1, UPPERCUT)
    target.turn_flags['movement_interrupted_sequence'] = engine.state.event_sequence + 1
    engine._append_event('PASSIVE_TRIGGERED', UPPERCUT, actor_id=owner.entity_id, target_ids=(target.entity_id,),
        payload={'log': f'{owner.display_name} launches {target.display_name} upward and ends that movement.'})
    displace(engine, target, 2, UPPERCUT, intent=ctx.intent)
