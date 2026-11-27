"""Earth's owned mark Insight and contact-based location sense.

Only sealed rows/conditions opt in. Pinpointing never grants sight; native
observations, attack modes and sight-required actions keep their own policies.
"""
from . import effect, hook

ADEPT = 'insight.burden-mark-adept'
PALM = 'TAL_EARTH_TREMOR_LISTENING_PALM'
BLOCK = 'earth_second_pass'
SENSE = 'condition:typed.earth_listening'


def owns(engine, actor, kind):
    return any(r.get('block') == BLOCK and r.get('kind') == kind
               for r in engine.typed_passive_rows.get(actor.entity_id, []))


@hook('compile_block')
def compile_block(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'block': BLOCK, 'kind': spec['kind'], 'player_outcome': 'Keep one extra Burden Mark; once per round after spending a mark, move up to 5 feet on the same surface without opportunity attacks from its bearer'}]


@hook('mark_cap')
def adept_capacity(ctx, name):
    if str(name).lower() == 'burden mark' and owns(ctx.engine, ctx.actor, 'mark_adept'):
        return {'add': 1}


@hook('mark_spent')
def adept_step(ctx, name, subject):
    from .rider_choices import step
    from ..surface_contact import connected
    owner = ctx.actor
    if (str(name).lower() != 'burden mark' or not owns(ctx.engine, owner, 'mark_adept')
            or owner.turn_flags.get('once_per_round:earth_adept') == ctx.engine.state.round_number
            or not connected(ctx.engine, owner, subject)):
        return
    # Accepting movement, rather than inspecting/declining it, uses the allowance.
    # Set before moving to prevent nested Earth responses from using it twice.
    previous = owner.turn_flags.get('once_per_round:earth_adept')
    owner.turn_flags['once_per_round:earth_adept'] = ctx.engine.state.round_number
    if not step(ctx.engine, owner, 'earth_mark_adept', 'Burden Mark Adept', subject, 5,
                ADEPT, ignored_oa=[subject.entity_id],
                trigger=f'You spent the Burden Mark on {subject.display_name}; move up to 5 feet without provoking from that creature'):
        if previous is None:
            owner.turn_flags.pop('once_per_round:earth_adept', None)
        else:
            owner.turn_flags['once_per_round:earth_adept'] = previous


@effect('earth_listen')
def listen(ctx, row):
    from ..falling import supported
    from .condition_ownership import refresh_owned
    if not supported(ctx.engine, ctx.actor):
        return
    feet = 60 if int(ctx.numbers.get('cl') or 1) >= 10 else 30
    refresh_owned(ctx.engine, ctx.actor, SENSE, ctx.actor.entity_id, ctx.source)
    ctx.engine._apply_condition(ctx.actor, SENSE, ctx.source, ctx.actor.entity_id,
                  expires_on='START_OF_SOURCE_NEXT_TURN',
                  data={'range_ft': feet, 'label': f'Tremor-Listening Palm: locate surface contact within {feet} feet until the start of your next turn; this does not grant sight'})


@hook('candidate_allowed')
def listen_allowed(engine, actor, candidate, action):
    from ..falling import supported
    if action and any(r.get('type') == 'earth_listen'
                      for r in (action.parameters.get('typed') or {}).get('effects', [])):
        return supported(engine, actor)


@hook('pinpoint_target')
def listen_location(engine, viewer, target):
    from ..surface_contact import connected
    from ..senses import is_creature
    if not is_creature(viewer) or not is_creature(target) or not target.active:
        return
    held = [c for c in viewer.conditions.values() if c.condition_id == SENSE]
    if (not held or not connected(engine, viewer, target)
            or not engine.grid.line_of_physical_transmission(viewer.position, target.position)):
        return
    # Solid map obstructions block transmission; darkness, fog, Hidden,
    # Invisible and the listener's Blinded/Deafened conditions do not.
    if engine._distance_actor_to_actor(viewer, target) <= max(int(c.data['range_ft']) for c in held):
        return True
