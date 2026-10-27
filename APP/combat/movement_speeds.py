"""Live per-mode Speed composition for flight, climbing and mapped travel.

Independent grants receive all-Speeds bonuses once. Walking-derived grants
declare the walking contribution already included, so Focus and restrictions
are not frozen in an activation snapshot or applied a second time. A snapshot's
other components retain their source's existing snapshot semantics.
Consumers: flight.profile, roof_movement.profile and JourneySession.

Composition asks the ``speed`` hooks for walking's live contribution. A
``speed`` provider must answer its own ability only; querying flight or climb
profiles from inside it would re-enter composition. ``_once`` makes the nested
query contribute no walking bonus instead of recursing without bound; it is
inert for providers that answer directly.
"""
from contextlib import contextmanager

from . import ext, carry

MODES = ('walk', 'fly', 'climb', 'swim', 'burrow')
_COMPOSING = set()


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
        return max(0, effective_speed(engine, actor)
                   - effective_speed(engine, actor, include_all_movement_bonus=False))


def resolve(engine, actor, mode, native, rows):
    """Resolve independent/derived grants before comparing their live Speeds."""
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
    speed = max(grants, default=0)
    return carry.speed_limit(engine, actor, speed)


def land_speed_grant(engine, actor, mode='fly'):
    """Public provenance for a grant equal to live walking Speed.

    Persisted leaves are integers. Replace only the all-Speeds contribution
    when Focus changes, including its actual amount after walking restrictions;
    preserve every other component of the source's recorded grant. Live source
    providers continue to recompute their whole grant as before.
"""
    if mode not in MODES[1:]:
        raise ValueError('Choose a native movement mode')
    amount = max(0, engine._effective_speed(actor))
    return {mode + '_speed_ft': amount,
            mode + '_speed_bonus_included_ft': min(amount, walking_bonus(engine, actor)),
            mode + '_speed_uses_walk_bonus': 1}


def speed(engine, actor, mode):
    """Read the same live native capability used by combat movement budgets."""
    if mode not in MODES:
        raise ValueError('Unknown movement Speed')
    if mode == 'walk':
        return engine._effective_speed(actor)
    if mode == 'fly':
        from .flight import profile
        return profile(engine, actor).speed_ft
    if mode == 'climb':
        from .roof_movement import profile
        capability = profile(engine, actor)
        return 0 if capability.disabled or engine._effective_speed(actor) <= 0 else capability.speed_ft
    if engine._effective_speed(actor) <= 0:
        return 0
    rows = [c.data for c in actor.conditions.values()]
    rows += ext.run_strict('movement_speeds', engine, actor)
    return resolve(engine, actor, mode, getattr(actor, mode + '_speed_ft', 0), rows)


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
