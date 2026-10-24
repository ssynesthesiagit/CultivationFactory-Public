"""Recorded footprint growth shared by the native engine and typed size effects.

apply_growth owns legal placement, refresh and the persistent condition. sync
restores the largest remaining growth after native removal/expiry. _footprint
reads the recorded transformed category, so reach/occupancy and C12's public
effective_size.cells all see the same actual size. No active growth is inert.
"""
from functools import lru_cache
from .footprints import ActorFootprintDefinition

CATEGORIES = ('Tiny', 'Small', 'Medium', 'Large', 'Huge', 'Gargantuan')
WIDTHS = (1, 1, 1, 2, 3, 4)
CONDITION = 'condition:typed.size_change'


def category_name(value):
    """Printed character size; absent/unrecognized legacy values stay Medium."""
    name = str(value or 'Medium').strip().title()
    return name if name in CATEGORIES else 'Medium'


def base_category(engine, actor):
    original = engine.actor_footprints[actor.entity_id]
    width = max(original.width_cells, original.height_cells)
    minimum = 2 if width == 1 else min(5, width+1)
    # Explicit Tiny/Small still occupy one square. Wider sealed footprints take
    # precedence over old templates whose newly defaulted label says Medium.
    return actor.size_category if width == 1 else CATEGORIES[max(minimum, CATEGORIES.index(actor.size_category))]


def current_category(engine, actor):
    return actor.transformed_size_category or base_category(engine, actor)


def shape(original, category):
    width = WIDTHS[CATEGORIES.index(category)]
    if width <= max(original.width_cells, original.height_cells):
        return original
    return grown_footprint(width)


@lru_cache(maxsize=3)
def grown_footprint(width):
    """Immutable standard size shapes; never cache actor state or a veto."""
    return ActorFootprintDefinition.rectangle(width, width,
        footprint_id=f'footprint:grown.{width}x{width}', source_definition_id='system:combat.size_change')


def _placement(engine, actor, category):
    original = engine.actor_footprints[actor.entity_id]
    footprint = shape(original, category)
    spatial = hasattr(engine.grid, 'volume_legal')
    occupied = (engine._occupied_volumes_except(actor.entity_id) if spatial else engine._occupied_cells_except(actor.entity_id))
    legal = engine.grid.volume_legal if spatial else engine.grid.placement_legal
    # Growth is not movement: replacement space must contain every square the
    # creature currently occupies. Enumerate only anchors whose footprint
    # contains that space, preferring the current anchor and then the nearest
    # deterministic local shifts. This permits west/north expansion at map
    # edges without searching distant openings or teleporting through walls.
    current = engine._actor_cells(actor)
    xs = [cell[0] for cell in current]
    ys = [cell[1] for cell in current]
    width, height = footprint.width_cells, footprint.height_cells
    candidates = set()
    shrinking = (width <= engine._footprint(actor).width_cells
                 and height <= engine._footprint(actor).height_cells)
    for x in range(min(xs) - width + 1, max(xs) + 1):
        for y in range(min(ys) - height + 1, max(ys) + 1):
            replacement = set(footprint.occupied_cells((x, y)))
            if (set(current).issubset(replacement) if not shrinking
                    else bool(set(current) & replacement)):
                candidates.add((x, y))
    ordered = sorted(candidates, key=lambda p: (
        abs(p[0] - actor.position.x) + abs(p[1] - actor.position.y), p[1], p[0]))
    for x, y in ordered:
        at = actor.position.model_copy(update={'x': x, 'y': y})
        if legal(at, footprint=footprint, occupied_cells=occupied):
            return at
    return None


def _fit(engine, actor, wanted):
    floor = CATEGORIES.index(base_category(engine, actor))
    for rank in range(max(floor, CATEGORIES.index(wanted)), floor-1, -1):
        category = CATEGORIES[rank]
        place = _placement(engine, actor, category)
        if place is not None:
            return category, place
    raise ValueError('No legal space can contain the creature at its normal size.')


def fitting_category(engine, actor, wanted):
    """Pure local preview; return ``None`` when even the current size is blocked."""
    try:
        return _fit(engine, actor, wanted)[0]
    except ValueError:
        return None


def apply_growth(engine, actor, wanted, source, *, source_actor_id, expires_on, functional_steps=0):
    """Apply/refresh one source's growth, clamped to the nearest fitting size.

    The chosen size is recorded once; unrelated later condition changes do not
    make a previously space-limited form silently grow. Distinct growth effects
    combine by their largest replacement, never by adding their widths.
    """
    if wanted not in CATEGORIES or type(functional_steps) is not int or functional_steps < 0:
        raise ValueError('Growth requires a known size and nonnegative whole functional steps.')
    chosen, _ = _fit(engine, actor, wanted)
    from .history_text import history_name, expiry_text
    names = {key: action.display_name for key, action in engine.action_catalog.items()}
    label = history_name(source, names)
    actors = {key: value.display_name for key, value in engine.state.actors.items()}
    duration = expiry_text(expires_on, actors, actors.get(source_actor_id, 'the source'), actor.display_name)
    benefit = (f' Counts as {functional_steps} additional size '
               f'{"category" if functional_steps == 1 else "categories"} for Grappling, Shoving and pushing; '
               'this does not add occupied space or reach.') if functional_steps else ''
    data = {'growth_category':chosen, 'functional_size_steps':functional_steps,
            'label':f'{label}: {chosen}',
            'reading':f'{label} grants {chosen} size {duration}.{benefit} Other growth uses the largest size, without adding sizes together.'}
    existing = next((c for c in actor.conditions.values() if c.condition_id == CONDITION
                     and c.source_definition_id == source and c.source_actor_id == source_actor_id), None)
    if existing is not None:
        actor.conditions[existing.instance_id] = existing.model_copy(update={
            'applied_sequence': engine.state.event_sequence+1, 'expires_on': expires_on, 'data':data})
        engine._append_event('CONDITION_APPLIED', source, actor_id=source_actor_id, target_ids=(actor.entity_id,),
            payload={'condition_id':CONDITION, 'instance_id':existing.instance_id, 'expires_on':expires_on})
    else:
        engine._apply_condition(actor, CONDITION, source, source_actor_id, expires_on=expires_on, data=data)
    if chosen != wanted:
        engine._append_event('PASSIVE_TRIGGERED', source, actor_id=actor.entity_id,
            payload={'log':f'{actor.display_name} grows only as far as space allows: {chosen}.'})


def sync(engine, source):
    if getattr(engine, '_syncing_size', False):
        return
    engine._syncing_size = True
    try:
        for actor in sorted(engine.state.actors.values(), key=lambda a:a.entity_id):
            growth = [c.data['growth_category'] for c in actor.conditions.values() if c.condition_id == CONDITION and 'growth_category' in c.data]
            if not growth and actor.transformed_size_category is None:
                continue
            if any(value not in CATEGORIES for value in growth):
                raise ValueError('A growth condition names an unknown size.')
            base = base_category(engine, actor)
            desired = max([base, *growth], key=CATEGORIES.index)
            selected, at = _fit(engine, actor, desired)
            override = selected if selected != base else None
            if actor.transformed_size_category == override and actor.position == at:
                continue
            before = current_category(engine, actor)
            from . import zones
            previous_inside = zones.geometry_snapshot(engine, actor)
            actor.transformed_size_category, actor.position = override, at
            active = [c.data.get('label', c.data['growth_category']) for c in actor.conditions.values()
                      if c.condition_id == CONDITION and 'growth_category' in c.data]
            details = ' Active growth: ' + '; '.join(active) + '.' if active else ' Temporary growth has ended.'
            functional = max((int(c.data.get('functional_size_steps', 0)) for c in actor.conditions.values()
                              if c.condition_id == CONDITION), default=0)
            if functional:
                details += f' Counts {functional} additional size {"category" if functional == 1 else "categories"} for Grappling, Shoving and pushing.'
            engine._append_event('FOOTPRINT_CHANGED', source, actor_id=actor.entity_id,
                payload={'before':before, 'size_category':selected, 'transformed_size_category':override,
                         'position':at.model_dump(mode='json'),
                         'log':f'{actor.display_name} is now {selected} and occupies its new space.{details}'})
            zones.geometry_changed(engine, actor, previous_inside)
    finally:
        engine._syncing_size = False
