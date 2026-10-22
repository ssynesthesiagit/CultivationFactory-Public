"""Explicit sound facts shared by speech, sonic delivery and placed objects.

MapStore accepts ``sound``: ambient is air/vacuum/unknown; boundaries contain
explicit cells, kind (soundproof/sealed/silence/ward), name and optional Source
CL, owner_id and absolute protection. Absence is unknown, never inferred from
floor artwork, creature deafness or a wall's visual appearance. The map is
sealed in the match genesis, so cold reload and replay use the same facts.
"""
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar

_SUSPENDED = ContextVar('suspended_sound_boundaries', default=())


@contextmanager
def suspend_boundaries(engine, rows):
    """Temporarily suspend exact map-authored sound sources, never mutate facts.

    Used by Primordial Syllable after its source/area/authority qualification.
    Nested scopes remain engine-specific and unwind on choices or failures.
    No rows leaves all hearing and physical delivery unchanged.
    """
    token = _SUSPENDED.set((*_SUSPENDED.get(), (engine, frozenset(id(r) for r in rows))))
    try:
        yield
    finally:
        _SUSPENDED.reset(token)

FACTS = 'condition:typed.confirmed_sound_medium'
FACT_CHOICE = 'choice:needle.sound_medium'


def normalize(value, width, height):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('ambient') not in {'air', 'vacuum', 'unknown'}:
        raise ValueError('Sound needs an ambient medium: air, vacuum, or unknown.')
    result = {'ambient': value['ambient'], 'boundaries': []}
    for row in value.get('boundaries') or []:
        if not isinstance(row, dict) or row.get('kind') not in {'soundproof', 'sealed', 'silence', 'ward'}:
            raise ValueError('Sound boundaries must name soundproofing, a sealed boundary, silence, or a ward.')
        cells = row.get('cells')
        if not isinstance(cells, list) or not cells or any(
                not isinstance(cell, list) or len(cell) != 2 or
                any(type(n) is not int for n in cell) or
                not (0 <= cell[0] < width and 0 <= cell[1] < height) for cell in cells):
            raise ValueError('Sound boundaries need explicit squares inside the map.')
        item = {'kind': row['kind'], 'cells': deepcopy(cells), 'name': str(row.get('name') or row['kind'])[:100]}
        if row['kind'] in {'silence', 'ward'}:
            if type(row.get('source_cl')) is not int or not 1 <= row['source_cl'] <= 40:
                raise ValueError('Cultivated sound barriers need their creator’s Cultivation Level (1–40).')
            item['source_cl'] = row['source_cl']
            if 'authority_modifier' in row:
                if type(row['authority_modifier']) is not int:
                    raise ValueError('A printed sound-authority modifier must be a whole number.')
                item['authority_modifier'] = row['authority_modifier']
        if row.get('owner_id'):
            item['owner_id'] = str(row['owner_id'])
        if 'surface_object_id' in row:
            if row['kind'] not in {'sealed', 'soundproof'} or type(row['surface_object_id']) is not int or row['surface_object_id'] < 1:
                raise ValueError('A sealed or soundproof boundary’s exposed surface must link to an object placed on the map.')
            item['surface_object_id'] = row['surface_object_id']
        if row.get('absolute'):
            if not isinstance(row['absolute'], str):
                raise ValueError('Name an explicit absolute protection; a numerical advantage cannot bypass it.')
            item['absolute'] = row['absolute'][:200]
        result['boundaries'].append(item)
    return result


def boundaries(engine, speaker, recipient, *, origin=None, at=None):
    """Intersect the actual origin-to-recipient ray, including both endpoints."""
    facts = (getattr(engine, 'battlefield_document', None) or {}).get('sound')
    if facts is None or facts.get('ambient') == 'unknown':
        confirmed = next((condition.data.get('ambient') for condition in speaker.conditions.values()
                          if condition.condition_id == FACTS and condition.data.get('ambient') in {'air', 'vacuum'}), None)
        if confirmed:
            # Owner confirmation fills only the missing ambient fact. Every
            # previously recorded barrier/ward/absolute remains authoritative.
            facts = {**(facts or {}), 'ambient': confirmed}
    if facts is None or facts.get('ambient') == 'unknown':
        return None
    if facts['ambient'] == 'vacuum':
        return [{'kind': 'soundproof', 'name': 'Vacuum', 'cells': []}]
    ray = set(engine.grid.ray_cells(origin if origin is not None else speaker.position,
                                    at if at is not None else recipient.position))
    stored = [row for row in facts.get('boundaries') or [] if boundary_active(engine, row)
            and ray.intersection(map(tuple, row['cells']))
            # A wall's exposed surface can be struck even though it blocks
            # sound beyond it. Only an explicit surface-object relationship
            # grants this; sharing a square never proves that relationship.
            and not (not row.get('absolute') and row.get('surface_object_id') is not None
                     and getattr(recipient, 'object_id', None) == f"object:map.{row['surface_object_id']}")]
    from . import ext
    for rows in ext.run_strict('sound_boundaries',engine,speaker,recipient,
                               origin if origin is not None else speaker.position,
                               at if at is not None else recipient.position):
        if not isinstance(rows,list) or any(not isinstance(r,dict) or r.get('kind') not in
                {'soundproof','sealed','silence','ward'} for r in rows):
            raise ValueError('sound_boundaries must return typed physical sound-boundary rows')
        stored.extend(rows)
    return stored


def boundary_active(engine, row):
    """Only an explicitly linked, actually destroyed ordinary surface ends its boundary.

    Missing objects remain unknown and do not erase protection. Named absolute
    protections and cultivated wards require their own printed ending rules.
    """
    if any(owner is engine and id(row) in ids for owner,ids in _SUSPENDED.get()):
        return False
    if row.get('surface_object_id') is not None and not row.get('absolute'):
        obj = engine.state.objects.get(f"object:map.{row['surface_object_id']}")
        if obj is not None and obj.destroyed:
            return False
    return True


def confirm_medium(ctx):
    """Native owner input for an unknown ambient medium, before delivery.

    Ask/Manual owners answer through the normal table choice journal, including
    off-turn uses. Automatic creatures have no eligible answers: they cannot
    create an unknown world fact. The confirmed fact survives commit/reload as
    a string condition field; it grants no resonance or remote origin and does
    not remove any existing map boundary. Decline/unknown creates no fact.
    """
    from .ext.needle import ask, checkpoint_id
    if boundaries(ctx.engine, ctx.actor, ctx.actor) is not None:
        return True
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'sound_medium', ctx.actor.entity_id),
        ctx.actor, FACT_CHOICE, ['air', 'vacuum', 'unknown'],
        labels={'air': 'Confirmed normal air; sound travels except through recorded barriers.',
                'vacuum': 'Confirmed vacuum; ordinary sound cannot travel.',
                'unknown': 'Not established; leave the sound medium unknown.'},
        name='Confirm the sound medium', feature_id=str(ctx.typed.get('source') or ''),
        prompt=f'{ctx.action.display_name}: before {ctx.actor.display_name} uses this audible technique, '
               'the table must establish whether sound can physically travel. Confirm an actual battlefield fact; '
               'this does not remove any recorded sound barrier. Choose unknown if the fact is not established.',
        default='decline', allow_decline=True, automatic=False, automatic_options=[])
    if selected and selected[0] in {'air', 'vacuum'}:
        ctx.engine._apply_condition(ctx.actor, FACTS, ctx.source, ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED', data={'ambient': selected[0],
                'label': 'Confirmed battlefield sound medium: ' + selected[0] + '. Recorded sound barriers still apply.'})
        return True
    return False


def hearing_path(engine, speaker, listener):
    """Pure ordinary-hearing admission. Unknown map facts retain legacy hearing.

    This never rolls a contest or spends a resource. Physical sonic abilities
    resolve their own cultivated authority through the activation-local path.
    """
    rows = boundaries(engine, speaker, listener)
    return rows is None or not rows


def reaches(ctx, recipient):
    """Resolve physical sound for an opted-in action; never tests Deafened.

    Each boundary is contested once per activation, shared by all creatures
    and objects. Ordinary hearing queries never roll. Transactional previews
    simulate the same deterministic contest on their disposable engine clone.
    """
    from .ext import CheckpointError

    if not any(row.get('type') == 'sound_transmission' for row in ctx.typed.get('effects') or []):
        return True
    from .action_geometry import point
    from .spatial_areas import actor_positions
    from .object_geometry import target_cells
    from .typed_executor import in_area
    origin = point(ctx.engine, ctx.actor)
    cells = ((recipient.position,) if recipient is ctx.actor else
             target_cells(ctx.engine, recipient) if hasattr(recipient, 'object_id') else
             actor_positions(ctx.engine, recipient))
    area, aim = ctx.typed.get('area') or {}, ctx.damage_cache.get('_checkpoint_aim') or origin
    paths = []
    for cell in cells:
        if recipient is not ctx.actor and area.get('size_ft') and not in_area(ctx.engine, origin, aim, cell, area):
            continue
        rows = boundaries(ctx.engine, ctx.actor, recipient, origin=origin, at=cell)
        if rows is None:
            raise CheckpointError('Record the battlefield’s sound medium and boundaries before resolving this audible technique.')
        paths.append(rows)
    # A large creature/object can receive the wave through any exposed portion
    # actually inside the area. Unobstructed portions need no unused ward roll.
    return any(path_allowed(ctx, rows) for rows in sorted(paths, key=len))


def path_allowed(ctx, rows):
    """Activation-local authority settlement shared by occupied-space paths."""
    from .ext import CheckpointError
    cache = ctx.damage_cache.setdefault('_sound_boundaries', {})
    for row in rows:
        if row.get('absolute') or row['kind'] in {'sealed', 'soundproof'}:
            return False
        own_cl = int(ctx.numbers.get('cl') or 1)
        difference = own_cl - row['source_cl']
        if difference >= 3:
            continue
        if difference <= -3:
            return False
        key = str(row)
        if key not in cache:
            owner = ctx.engine.state.actors.get(row.get('owner_id'))
            if row.get('owner_id') and owner is None:
                raise CheckpointError('Record the actual sound barrier user before resolving its opposed Cultivation Check.')
            # Equal authorities without a creature user use the shared
            # environmental opposition DC. Creature users each roll a
            # Cultivation Check; a tie does not displace the existing ward.
            own = cultivation_check(ctx, ctx.actor)
            opposing = cultivation_check(ctx, owner) if owner is not None else 10 + row['source_cl'] // 2 + int(row.get('authority_modifier') or 0)
            cache[key] = own > opposing if owner is not None else own >= opposing
            ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=ctx.actor.entity_id,
                payload={'trigger': 'sound_authority', 'text': f"{ctx.action.display_name} contests a sound barrier: "
                         + ('sound passes.' if cache[key] else 'sound is blocked.'),
                         'total': own, 'opposing_total': opposing})
        if not cache[key]:
            return False
    # Hearing-path providers are separate: e.g. Mantra's hearing suppression
    # explicitly leaves Thunder damage intact.
    return True


def cultivation_check(ctx, actor):
    """A distinct Cultivation Check, not an ordinary ability check or save."""
    if actor is ctx.actor:
        numbers = ctx.numbers
    else:
        from .save_dcs import numbers as sealed_numbers
        numbers = sealed_numbers(ctx.engine, actor)
        if 'key_mod' not in numbers:
            from .ext import CheckpointError
            raise CheckpointError('The opposing sound user needs recorded cultivation statistics.')
    with ctx.engine.d20_scope({'kind': 'cultivation', 'actor_id': actor.entity_id,
                              'source_id': ctx.source}):
        rolled = ctx.engine.roller.d20(modifier=int(numbers.get('pb') or 0) + int(numbers.get('key_mod') or 0),
            actor_id=actor.entity_id, reason=f'CULTIVATION:{ctx.source}:sound')
    ctx.engine._record_roll(rolled)
    return int(rolled.total)
