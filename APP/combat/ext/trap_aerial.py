"""Opt-in, sealed aerial Trap capabilities. No runtime authority reads.

The owner may switch on physically anchored rigging. Heaven-Net always rigs
its printed Net and Terrain forms when the reviewed capability is owned.
Surface admission checks solid support; the device's columns, height and
capabilities are sealed on that placement. Native landed zone entry, flight,
forced paths and expiry own the actual resolution and persistence.
"""
from . import effect, hook, placed

AERIAL = 'TAL_TRAP_AERIAL_RIGGING'
SKY = 'TAL_TRAP_FALLING_SKY_MECHANISM'
HEAVEN = 'TAL_TRAP_HEAVEN_NET_BATTLEFIELD'
ROAD = 'TAL_TRAP_THE_EMPTY_ROAD_WAS_NEVER_EMPTY'
POLICIES = {AERIAL: 'aerial', SKY: 'falling_sky', HEAVEN: 'heaven_net', ROAD: 'dual_trigger'}


def capabilities(info):
    """Compile only explicitly reviewed capability rows, never ownership alone."""
    return {kind: 1 for mid, kind in POLICIES.items() if mid in info['owned_ids']
            and any(e.get('type') == 'trap_capability' and e.get('kind') == kind
                    for e in info['mechanics'].get(mid, {}).get('effects', []))}


@effect('trap_capability')
def capability(ctx, row):
    """Compilation attribution only; no extra activation or effect at runtime."""
    return None


def supported_cell(engine, cell):
    """Physical devices need ground or an explicit solid anchor on a face."""
    if not engine.grid.volume_legal(cell):
        return False
    if cell.z == 0:
        return True
    x, y, z = cell.x, cell.y, cell.z
    anchors = ((x, y, z - 1), (x, y, z + 1), (x - 1, y, z),
               (x + 1, y, z), (x, y - 1, z), (x, y + 1, z))
    return any(p[2] >= 0 and engine.grid.in_bounds(p[:2]) and engine.grid.terrain_at(p, 'BLOCKED')
               for p in anchors)


def raised_cells(engine, owner, *, include_ground=False):
    """Visible supported device squares within reach; ground is opt-in."""
    from ..gate2_runtime_models import Position
    from ..space import ray, position
    cells = []
    for z in range(max(0 if include_ground else 1, owner.position.z - 1), owner.position.z + 2):
        for y in range(owner.position.y - 1, owner.position.y + 2):
            for x in range(owner.position.x - 1, owner.position.x + 2):
                if x < 0 or y < 0 or not engine.grid.in_bounds((x, y)):
                    continue
                cell = Position(x=x, y=y, z=z)
                if (not supported_cell(engine, cell) or placed.occupied(engine, cell)
                        or placed.at(engine, cell, 'trap')
                        or engine._distance_actor_to_cell(owner, cell) > 5
                        or not engine._line_of_sight_actor_to_cell(owner, cell)):
                    continue
                path = tuple(position(p) for p in ray(owner.position, cell))
                if all(engine.grid.volume_step_legal(a, b) for a, b in zip(path, path[1:])):
                    cells.append(cell)
    return cells


def placement(engine, kit, cell, config):
    """Public Trap placement decorator; absent reviewed policy is inert."""
    policies = kit.get('runtime') or {}
    heaven = bool(policies.get('heaven_net')
                  and config.get('form') in ('net', 'dart_net', 'terrain', 'terrain_now'))
    if not policies.get('aerial') or not (config.get('aerial') or heaven):
        return {}, {}
    cl = int(kit['numbers'].get('cl') or 1)
    height = 30 if cl >= 15 else 20 if cl >= 10 else 10
    actual_steps = 0
    for dz in range(1, height // engine.grid.square_size_ft + 1):
        if not engine.grid.volume_legal(cell.model_copy(update={'z': cell.z + dz})):
            break
        actual_steps = dz
    # The occupied base square has its own five-foot volume; aerial height is
    # measured above its plane, including a creature whose feet are at the cap.
    return {'footprint_height_ft': (actual_steps + 1) * engine.grid.square_size_ft}, {
        'aerial': 1, 'aerial_height_ft': height, 'heaven_net': int(heaven),
        'walk_through': False}


def threat_cells(zone):
    """The explicit rigged spaces, including the base, for pattern geometry."""
    steps = int(zone.trigger_profile.get('footprint_height_ft') or 5) // 5
    return tuple(cell.model_copy(update={'z': cell.z + dz})
                 for cell in zone.affected_cells for dz in range(steps))


def held_lattice(ctx, zone, subject, hold):
    """A sprung Heaven-Net lattice remains physical until its exact hold ends."""
    placed.place(ctx.engine, ctx.actor, source=zone.source_definition_id, tag='heaven_lattice',
        cells=zone.affected_cells, name=f'{ctx.actor.display_name}\'s Heaven-Net lattice',
        numbers=dict(ctx.numbers), difficult='all', color='#9a7b4f', material='generic',
        extra={'footprint_height_ft': zone.trigger_profile['footprint_height_ft']},
        placed={'heaven_net': 1, 'holder': subject.entity_id, 'hold': hold})


@hook('state_event')
def lattice_lifecycle(engine, event):
    if event.event_type not in ('CONDITION_REMOVED', 'ENTITY_DEFEATED'):
        return
    for zone in placed.of(engine, 'heaven_lattice'):
        data = placed.data(zone)
        subject = engine.state.actors.get(data['holder'])
        if subject is None or data['hold'] not in subject.conditions:
            placed.drop(engine, zone, 'LATTICE_RELEASED')


@effect('trap_anchor_pull')
def anchor_pull(ctx, row):
    """A failed aerial Net/Noose save pulls before the restraint is applied."""
    from ..flight import profile
    from ..movement_paths import resolve
    from ..space import ray, position
    target = ctx.target
    zone = ctx.engine.state.zones.get(row.get('zone_id'))
    if target is None or zone is None or not placed.data(zone).get('aerial'):
        return
    heaven = bool(placed.data(zone).get('heaven_net'))
    if not target.position.z or not (heaven or profile(ctx.engine, target).hover):
        return
    occupied = ctx.engine._occupied_volumes_except(target.entity_id)
    anchors = sorted(zone.affected_cells, key=lambda p: (
        ctx.engine.grid.distance_ft(target.position, p), p.x, p.y, p.z))
    for anchor in anchors:
        if not supported_cell(ctx.engine, anchor):
            continue
        path = tuple(position(p) for p in ray(target.position, anchor))
        if not all(ctx.engine.grid.volume_step_legal(a, b,
                footprint=ctx.engine._footprint(target), occupied_cells=occupied)
                for a, b in zip(path, path[1:])):
            continue
        resolve(ctx.engine, target, path, ctx.source, kind='forced', intent=ctx.intent,
                source_actor_id=ctx.actor.entity_id, ctx=ctx)
        placed.note(ctx.engine, ctx.source, ctx.actor,
                    f'{target.display_name} is drawn into the anchored trap before its restraint takes hold.', [target])
        return


def falling_sky(ctx, zone, target):
    """Public on-hit rider, including hits whose damage was fully resisted."""
    from ..typed_executor import run_effects
    from .effect_durations import token
    if not placed.data(zone).get('falling_sky') or not target.active or not target.position.z:
        return
    from ..falling import supported
    if not has_fly_speed(ctx.engine, target) or supported(ctx.engine, target):
        return
    sub = placed.context(ctx.engine, ctx.actor, ctx.source, ctx.numbers, [target], action=ctx.action)
    sub.intent = ctx.intent
    sub.typed['source'] = f'trap:{zone.zone_id}'
    run_effects(sub, [{'type': 'save', 'ability': 'str', 'on_fail': [{
        'type': 'condition', 'condition': 'falling_sky_grounded',
        'expires_on': token('start', target.entity_id, target.turns_started + 1),
        'condition_data': {'fly_speed_zero': 1,
            'label': 'Falling-Sky Mechanism: Fly Speed is 0 until your next turn starts'},
        'evidence': 'Its Fly Speed becomes 0 until the start of its next turn.'}]}])


def has_fly_speed(engine, actor):
    """Possesses a Fly Speed even while a temporary condition sets it to zero."""
    from . import has, run_strict
    rows = [c.data for c in actor.conditions.values()]
    if has('flight'):
        rows += run_strict('flight', engine, actor)
    return actor.fly_speed_ft > 0 or any(int(row.get('fly_speed_ft') or 0) > 0 for row in rows)


@hook('difficult_zone_exempt')
def lattice_exempt(engine, actor, zone):
    """Only creatures with a Fly Speed pay Heaven-Net's added lattice cost."""
    data = placed.data(zone)
    if data.get('heaven_net') and not has_fly_speed(engine, actor):
        if data.get('tag') in ('trap', 'heaven_lattice'):
            return True
        if data.get('tag') == 'terrain_trap' and actor.position.z != zone.center.z:
            return True  # Ordinary Terrain remains difficult at its base plane.

    return None
