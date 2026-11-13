"""Live per-mode Speed composition for flight, climbing and mapped travel.

Independent grants receive all-Speeds bonuses once. Walking-derived grants
declare the walking contribution already included, so Focus and restrictions
are not frozen in an activation snapshot or applied a second time. A snapshot's
other components retain their source's existing snapshot semantics.
Consumers: speed_contributions.effective_speed, flight.profile,
roof_movement.profile, mounts and JourneySession.

Composition asks the ``speed`` hooks for walking's live contribution. A
``speed`` provider must answer its own ability only; querying flight or climb
profiles from inside it would re-enter composition. ``_once`` makes the nested
query contribute no walking bonus instead of recursing without bound; it is
inert for providers that answer directly.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from . import ext, carry

MODES = ('walk', 'fly', 'climb', 'swim', 'burrow')
_COMPOSING = set()
_GRANT_BASIS = ContextVar('movement_grant_basis', default=frozenset())


@contextmanager
def grant_basis(engine, actor):
    """Flight/climb/mapped providers derive grants without another mode's keyed penalty."""
    token = _GRANT_BASIS.set(_GRANT_BASIS.get() | {(id(engine), actor.entity_id)})
    try:
        yield
    finally:
        _GRANT_BASIS.reset(token)


@contextmanager
def _once(engine, actor, scope):
    """Mark one actor's composition scope; yield False when already inside it."""
    key = (id(engine), getattr(actor, 'entity_id', None), scope)
    entered = key not in _COMPOSING
    if entered:
        _COMPOSING.add(key)
    try:
        yield entered
    finally:
        if entered:
            _COMPOSING.discard(key)


def terrain_supports(battlefield, position, mode):
    """Explicit mapped water/substrate facts, never scenery-name inference.

    Native map travel_regions validate coordinates and whole altitude bounds.
    Burrowable describes a traversable substrate; solid BLOCKED cells remain
    walls. This contract does not grant tunnelling through arbitrary objects.
    """
    kind = {'swim': 'water', 'burrow': 'burrowable'}.get(mode)
    return any(row.get('kind') == kind and [position.x, position.y] in row.get('cells', ())
               and row.get('min_z', 0) <= position.z <= row.get('max_z', 0)
               for row in (battlefield or {}).get('travel_regions', ()))


def all_bonus(engine, actor):
    values = ext.run_strict('all_movement_speeds_bonus', engine, actor)
    if any(type(n) is not int or n < 0 for n in values):
        raise ValueError('All movement Speed bonuses require nonnegative integer feet')
    return sum(values)


def walking_bonus(engine, actor):
    """Actual all-Speeds contribution after walking's final restrictions.

    Both projections are pure. This keeps a halved ten-foot bonus at five,
    and never rewrites unrelated components of a recorded capability.
    """
    if not all_bonus(engine, actor):
        return 0
    from .speed_contributions import effective_speed
    with _once(engine, actor, 'walking_bonus') as entered:
        if not entered:
            return 0
        with grant_basis(engine, actor):
            return max(0, effective_speed(engine, actor)
                       - effective_speed(engine, actor, include_all_movement_bonus=False))


def land_speed_grant(engine, actor, mode='fly'):
    """Public provenance for a grant equal to live walking Speed.

    Persisted leaves are integers. Replace only the all-Speeds contribution
    when Focus changes, including its actual amount after walking restrictions;
    preserve every other component of the source's recorded grant. Live source
    providers continue to recompute their whole grant as before.
"""
    if mode not in MODES[1:]:
        raise ValueError('Choose a native movement mode')
    with grant_basis(engine, actor):
        amount = max(0, engine._effective_speed(actor))
    return {mode + '_speed_ft': amount,
            mode + '_speed_bonus_included_ft': min(amount, walking_bonus(engine, actor)),
            mode + '_speed_uses_walk_bonus': 1}


def speed(engine, actor, mode, *, native=None, rows=None, route_speed=0,
          include_all_movement_bonus=True, prior_overloaded=None):
    """The one mode-Speed reader used by walking, flight, climbing and mounts.

    A modifier with no mode key has WALK scope: walking, and every grant
    derived from walking, exactly as today. A modifier with a key applies only
    to that mode. Grant providers read an unkeyed walking basis so a keyed
    walk penalty cannot leak into their Fly/Climb/etc. grants.
    Each mode keeps its existing native/provider bases, bonus provenance,
    restrictions and carrying order. rows/native are capability inputs from
    flight.profile and roof_movement.profile, not alternative composers.
    """
    if mode not in MODES:
        raise ValueError('Unknown movement Speed')
    if mode != 'walk' and rows is None:
        if mode == 'fly':
            from .flight import profile
            return profile(engine, actor).speed_ft
        if mode == 'climb':
            from .roof_movement import profile
            capability = profile(engine, actor)
            with grant_basis(engine, actor):
                mobile = engine._effective_speed(actor) > 0
            return 0 if capability.disabled or not mobile else capability.speed_ft
        with grant_basis(engine, actor):
            if engine._effective_speed(actor) <= 0:
                return 0
            rows = [c.data for c in actor.conditions.values()]
            rows += ext.run_strict('movement_speeds', engine, actor)
        native = getattr(actor, mode + '_speed_ft', 0)

    from .speed_contributions import _composing
    from .read_queries import shared_query
    from .space import point
    apply_keyed = (id(engine), actor.entity_id) not in _GRANT_BASIS.get() or mode != 'walk'
    if mode != 'walk':
        return _compose(engine, actor, mode, native=native, rows=rows, route_speed=route_speed,
                        apply_keyed=apply_keyed)
    reentry = (id(engine), actor.entity_id) in _composing()
    key = ('mode_speed', id(actor), point(actor.position), mode, include_all_movement_bonus,
           reentry, prior_overloaded, apply_keyed)
    return shared_query(engine, key, lambda: _compose(
        engine, actor, mode, include_all_movement_bonus=include_all_movement_bonus,
        prior_overloaded=prior_overloaded, apply_keyed=apply_keyed), refs=(actor,))


def _compose(engine, actor, mode, *, native=None, rows=None, route_speed=0,
             include_all_movement_bonus=True, prior_overloaded=None, apply_keyed=True):
    """One final composer. A modifier with no mode key has WALK scope: walking,
    and every grant derived from walking, exactly as today. Keyed rows affect
    only their named mode.
    """
    from . import motion
    from .speed_contributions import _composing, SpeedReading

    key = (id(engine), actor.entity_id)
    entered = mode == 'walk' and key not in _composing()
    if entered:
        _composing().add(key)
    try:
        sources = []
        if mode == 'walk':
            from .gate2_engine import Gate2Engine
            feet = Gate2Engine._base_speed(engine, actor)
            if feet <= 0:
                return SpeedReading(feet)
            if entered:
                bases = ext.run_strict('movement_speed_base', engine, actor)
                if len(bases) > 1:
                    raise ValueError('Only one provider may replace a movement Speed base')
                if bases:
                    replacement, source, name = bases[0]
                    if type(replacement) is not int or replacement < 0:
                        raise ValueError('A replacement movement Speed must be nonnegative integer feet')
                    # Preserve the rider's own fixed slowing around a replaced base.
                    base = max(0, replacement + feet - actor.speed_ft) if replacement > 0 else 0
                    sources.append((source, name, base - feet))
                    feet = base
            feet += motion.speed_bonus(engine, actor)
            if entered:
                for value in ext.run('speed', engine, actor):
                    feet += int(value)
                    sources.extend(getattr(value, 'sources', ()))
            if not include_all_movement_bonus:
                feet -= all_bonus(engine, actor)
            if apply_keyed:
                # Adjust the mode's complete Speed, including a mounted base,
                # rather than flooring against the rider's unmounted Speed.
                adjustment = motion.speed_adjustment(engine, actor, movement_mode=mode)
                if adjustment:
                    feet = max(0, feet + adjustment)
            if any(m.target_field == 'speed_halved' and not m.consumed
                   and (m.movement_mode is None or (apply_keyed and m.movement_mode == 'walk'))
                   for m in actor.modifiers.values()):
                feet //= 2
            return SpeedReading(carry.prior_speed_limit(engine, actor, feet, prior_overloaded), sources)

        bonus = all_bonus(engine, actor)
        grants = [native + bonus] if native > 0 else []
        for row in rows:
            amount = row.get(mode + '_speed_ft', 0)
            included = row.get(mode + '_speed_bonus_included_ft', 0)
            walk_bonus = row.get(mode + '_speed_uses_walk_bonus', 0)
            if (type(amount) is not int or amount < 0 or type(included) is not int
                    or included < 0 or included > amount or type(walk_bonus) is not int
                    or walk_bonus not in (0, 1)):
                raise ValueError('Movement grants require nonnegative integer feet and included bonus provenance')
            if amount > 0:
                grants.append(max(0, amount - included + (walking_bonus(engine, actor) if walk_bonus else bonus)))
        feet = carry.speed_limit(engine, actor, max(grants, default=0))
        if mode == 'fly':
            added, percent, reductions = 0, 100, {}
            zeroed = False
            for index, row in enumerate(rows):
                value = row.get('fly_speed_percent', 100)
                reduction = row.get('fly_speed_reduction_ft', 0)
                extra = row.get('fly_speed_bonus_ft', 0)
                if type(value) is not int or not 1 <= value <= 100:
                    raise ValueError('fly_speed_percent must be an integer percentage of Fly Speed')
                if type(reduction) is not int or reduction < 0 or type(extra) is not int or extra < 0:
                    raise ValueError('Fly Speed bonuses/reductions require nonnegative integer feet')
                percent = min(percent, value)
                added += extra
                group = ('named', row['fly_speed_reduction_key']) if row.get('fly_speed_reduction_key') else ('row', index)
                reductions[group] = max(reductions.get(group, 0), reduction)
                zeroed |= bool(row.get('fly_speed_zero', 0))
            feet = 0 if zeroed or feet <= 0 else max(0, (feet + added) * percent // 100 - sum(reductions.values()))
            with grant_basis(engine, actor):
                if engine._effective_speed(actor) <= 0:
                    feet = 0
        feet = max(feet, carry.speed_limit(engine, actor, route_speed))
        before_keyed = feet
        if apply_keyed:
            feet = max(0, feet + motion.speed_adjustment(engine, actor, movement_mode=mode)) if feet > 0 else 0
            if any(m.target_field == 'speed_halved' and m.movement_mode == mode and not m.consumed
                   for m in actor.modifiers.values()):
                feet //= 2
        return SpeedReading(carry.speed_limit(engine, actor, feet), keyed_zero=before_keyed > 0 and feet == 0)
    finally:
        if entered:
            _composing().discard(key)


def choose_mode(ctx, row, chooser):
    """Typed speed operations use Needle's shared transactional choice transport."""
    from .ext.needle import ask, checkpoint_id
    subject = ctx.target
    options = [mode for mode in MODES if speed(ctx.engine, subject, mode) > 0]
    return ask(ctx.engine, ctx.intent,
               checkpoint_id(ctx.engine, 'movement-mode', ctx.source, subject.entity_id,
                             row['pre_save_choice']['key']),
               chooser, 'choice:needle.movement_mode', options,
               labels={mode: mode.title() for mode in options}, target_id=subject.entity_id,
               required=True, name=ctx.action.display_name,
               prompt=(f'{ctx.action.display_name}: choose one movement mode for {subject.display_name} '
                       f'before its saving throw. {row.get("choice_prompt", "")}'))


def step_restriction(engine, actor, mode, *, ascending=False):
    """Live capability limits combat applies to one movement step.

    Consumers: JourneySession.step_profile (route validation and its menu
    generation share one check). Combat's flight and roof step admission call
    the same capability queries there; mapped noncombat travel consults this
    helper so a fixture cannot do what the creature cannot do outside a
    fight, without importing combat geometry or journey terrain pricing.
    Speed-zero and carrying limits stay in speed(); only the capability
    restrictions Speed cannot see are answered here. Returns a plain reason
    the menu can refuse, or None when the step is unrestricted.
    """
    if mode == 'climb':
        from .roof_movement import profile as climb_profile
        if climb_profile(engine, actor).physical_disabled:
            return 'Climbing needs a free hand; set a held item down or stow it before climbing.'
    if ascending and mode in ('climb', 'fly'):
        from .flight import profile as flight_profile
        if not flight_profile(engine, actor).can_ascend:
            return 'This creature cannot gain altitude right now.'
    return None
