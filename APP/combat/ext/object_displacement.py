"""Source-backed loose-object displacement; Wind Lash Scatter is the first consumer.

The typed ``displace_object`` effect chooses one size-qualified unattended map
object near its recipient, then an endpoint along a clear straight route. Native
volume/corner and effect-ray policies apply. All represented directions and
shorter distances, including staying put, remain selectable. Needle owns the
transactional choices; OBJECT_UPDATED owns commit, cold reload and replay.
"""
from itertools import product
from typing import Any

from . import effect, note, run_strict
from . import needle
from .. import object_rules
from ..gate2_runtime_models import Position
from ..senses import perceives_cell
from ..effect_cover import rays


def destinations(engine: Any, obj: Any, feet: int) -> list[Position]:
    """Straight object routes, independent of creature speed and movement pools."""
    start = obj.position
    occupied = {tuple(c) for actor in engine.state.actors.values() if actor.active
                for c in engine._actor_volume(actor)}
    occupied.update((o.position.x, o.position.y, o.position.z)
                    for o in engine.state.objects.values()
                    if o.object_id != obj.object_id and not o.destroyed and (o.component or {}).get('blocks'))
    reach = feet // engine.grid.square_size_ft
    found = [start]
    for dx, dy, dz in product(range(-reach, reach + 1), repeat=3):
        steps = max(abs(dx), abs(dy), abs(dz))
        if not steps or start.z + dz < 0:
            continue
        end = Position(x=start.x + dx, y=start.y + dy, z=start.z + dz)
        if engine.grid.distance_ft(start, end) > feet or not engine.grid.volume_legal(end, occupied_cells=occupied):
            continue
        if next(rays(engine, (start,), (end,), purpose='effect'), None) is None:
            continue
        route = [Position(x=start.x + round(dx * i / steps), y=start.y + round(dy * i / steps),
                          z=start.z + round(dz * i / steps)) for i in range(steps + 1)]
        if all(engine.grid.volume_step_legal(a, b, occupied_cells=occupied) for a, b in zip(route, route[1:])):
            found.append(end)
    return found


@effect('displace_object')
def displace_object(ctx: Any, row: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    target = ctx.target or engine.state.objects.get(str(row.get('recipient_object_id') or ''))
    if target is None:
        return
    name = str(row['name'])
    target_id = getattr(target, 'entity_id', None) or target.object_id
    target_name = getattr(target, 'display_name', None) or object_rules.label(target)
    feet, radius = int(row['distance_ft']), int(row['within_ft'])
    eligible = {o.object_id: o for o in sorted(engine.state.objects.values(), key=lambda o: o.object_id)
                if not o.destroyed and o.unattended and (o.component or {}).get('size') == row['size']
                and engine.grid.distance_ft(target.position, o.position) <= radius}
    selected = needle.ask(engine, ctx.intent,
        needle.checkpoint_id(engine, 'displace_object_subject', ctx.source, target_id), owner,
        'choice:needle.displace_object_subject', list(eligible),
        labels={key: object_rules.label(obj) for key, obj in eligible.items()}, name=name,
        prompt=f'{name}: the attack hits {target_name}. Choose one {row["size"]} unattended object within {radius} feet to move up to {feet} feet, at no additional cost.',
        target_id=target_id, allow_decline=True,
        automatic_options=[key for key, obj in eligible.items() if perceives_cell(engine, owner, obj.position)])
    if not selected:
        return
    obj = eligible[selected[0]]
    cells = {needle.cell_id(cell): cell for cell in destinations(engine, obj, feet)}
    # A direction does not require destination sight. Prefer actual movement,
    # then perceived endpoints, without removing unseen directions or staying put.
    preferred = sorted((key for key, cell in cells.items() if cell != obj.position),
                       key=lambda key: not perceives_cell(engine, owner, cells[key]))
    chosen = needle.ask(engine, ctx.intent,
        needle.checkpoint_id(engine, 'displace_object_destination', ctx.source, obj.object_id), owner,
        'choice:needle.displace_object_destination', list(cells), name=name,
        labels={key: f'({cell.x}, {cell.y}, {cell.z}) — {engine.grid.distance_ft(obj.position, cell)} feet'
                for key, cell in cells.items()},
        prompt=f'{name}: move {object_rules.label(obj)} up to {feet} feet in which direction? Choose its destination, or keep it in place; no additional cost.',
        target_id=obj.object_id, allow_decline=True, preferred=preferred)
    if not chosen:
        return
    destination = cells[chosen[0]]
    if destination == obj.position:
        return
    if False in run_strict('object_operation_gate', engine, owner, obj, 'move', ctx.source, ctx.intent):
        return
    engine._update_object(obj.model_copy(update={'position': destination}), ctx.source, owner.entity_id)
    note(engine, ctx.source, owner,
         f'{name}: {object_rules.label(obj)} moves to ({destination.x}, {destination.y}, {destination.z}).',
         targets=(obj.object_id,))
