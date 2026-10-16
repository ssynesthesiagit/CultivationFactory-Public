"""Water's Cleansing Basin (rider lane C13, 2026-09-30; owner: "i want everything we can automated, keep going until its only the
non-combat ones left"). Printed (Sphere Compendium, Water, Shape Current): "Cleansing Basin. The first time each round you or an ally
enters the area or starts its turn there, it may end the Soaked state on itself, extinguish ordinary flames on itself, or gain Advantage
on the next saving throw before the start of its next turn against Poisoned, a disease, smoke, heat, or mundane contamination."

``water_cleansing`` is the Basin's enter/start trigger (once per creature per round: the zone trigger's ``per_round``); the creature
itself chooses (its player is asked; the built-in AI ends Burning first, then Soaked, else takes the Advantage): end every Soaked mark on
it, end its Burning (the table's ordinary flames), or Advantage on its next save against Poisoned or a disease until the start of its
next turn. Shape Current's other forms are typed zone rows (authority/typed_mechanics/reviewed_final.d/elements.json); moving a Basin
is combat/ext/zone_mover.py. The compile_action hook also replaces Flowing
Current's ordinary initial push in newly compiled Wave Burst variants; their
reviewed effect uses the shared chosen-area recipient selector. Saved catalogs
are unchanged. Cleansing is inert outside a Cleansing Basin.

Owned Cleansing Water annotates this same trigger, grants the actual beneficiary
PB Temporary HP and records one improved cleansing per Basin per round. The
separate wash choice handles recorded mundane surface residue; it never cures
Poisoned, disease or curses. Source ownership is checked during compilation and
all runtime washing requires an active owned upgraded Basin.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note, ai_controlled

SOAKED_PREFIX = "condition:typed.mark.soaked."
BURNING = "condition:typed.burning"
CLEANSING = 'TAL_WATER_CLEANSING_WATER'
WASH = 'action:water.cleansing_residue'
RESIDUE = {'mundane_poison_residue', 'acid_residue', 'dust', 'ash', 'filth', 'mundane_contamination', 'covered_in_smoke'}
WASH_RESIDUE = {'mundane_poison_residue', 'acid_residue', 'dust', 'ash', 'filth'}


def residue_conditions(creature: Any, *, wash_only: bool = False) -> dict[str, Any]:
    """Recorded mundane surface states only; never Poisoned, disease or curses."""
    return {iid: c for iid, c in creature.conditions.items()
            if c.condition_id.removeprefix('condition:typed.') in (WASH_RESIDUE if wash_only else RESIDUE)
            and c.data.get('magical') is not True}


@hook('compile_action')
def cleansing_beneficiary(action: Any, info: dict[str, Any]) -> Any:
    """Move mandatory owned benefits from casting to the actual Basin trigger."""
    import copy
    typed = (action.parameters or {}).get('typed') or {}
    if CLEANSING not in info['owned_ids'] or typed.get('source') != 'WATER_BASE_SHAPE_CURRENT':
        return None
    found = False

    def shape(value):
        nonlocal found
        if isinstance(value, list):
            return [shape(row) for row in value
                    if not isinstance(row, dict) or row.get('source_modifier') != CLEANSING]
        if isinstance(value, dict):
            row = {k: shape(v) for k, v in value.items()}
            if row.get('type') == 'water_cleansing':
                row['cleansing_water'] = 1
                found = True
            return row
        return value

    updated = shape(copy.deepcopy(typed))
    if not found:
        return None
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': updated}})


@hook('zone_trigger_context')
def cleansing_zone(ctx: Any, zone: Any, creature: Any, moment: str) -> None:
    """Bind the retained Basin identity for its shared one-creature-round budget."""
    if any(e.get('type') == 'water_cleansing' and e.get('cleansing_water') for e in ctx.typed.get('effects') or []):
        ctx.typed['_cleansing_zone_id'] = zone.zone_id


def cleansing_areas(engine: Any, owner: Any) -> list[Any]:
    return [z for z in engine.state.zones.values() if z.active and z.owner_id == owner.entity_id
            and any(e.get('type') == 'water_cleansing' and e.get('cleansing_water')
                    for trigger in z.trigger_profile.get('triggers') or [] for e in trigger.get('effects') or [])]


def wash_targets(engine: Any, owner: Any) -> dict[str, Any]:
    from ..senses import perceives, perceives_object
    automatic = ai_controlled(engine, owner)
    cells = tuple(p for z in cleansing_areas(engine, owner) for p in z.affected_cells)
    targets = {a.entity_id: a for a in engine.state.actors.values() if a.active
               and residue_conditions(a, wash_only=True) and (not automatic or a is owner or perceives(engine, owner, a))
               and engine._footprint_intersects(a, cells)}
    targets.update({oid: obj for oid, obj in engine.state.objects.items() if not obj.destroyed
                    and (obj.component or {}).get('mundane_residue') in WASH_RESIDUE
                    and (not automatic or perceives_object(engine, owner, obj)) and obj.position in cells})
    return targets


@hook('compile_actions')
def cleansing_wash_action(info: dict[str, Any]) -> list[Any] | None:
    if CLEANSING not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    return [ActionDefinition(source_definition_id=f'{WASH}.{info["actor_id"]}', display_name='Cleansing Water: Wash Residue',
                             owner_id=info['actor_id'], economy='NONE', resolution_kind='TYPED', target_kind='SELF',
                             parameters={'typed': {'source': CLEANSING, 'numbers': dict(info['numbers']),
                                                   'effects': [{'type': 'water_wash_residue'}], 'riders': []},
                                         'description': 'Wash mundane poison or acid residue, dust, ash or filth from one '
                                                        'creature or object in your Cleansing Basin; allies gain your Proficiency Bonus in Temporary HP. No action or Cultivation Point cost; '
                                                        'this does not cure Poisoned, disease or curses. '
                                                        'Smoke removal uses the Basin benefit, limited to one creature per round.'})]


@hook('candidate_allowed')
def wash_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and action.source_definition_id.startswith(WASH + '.'):
        return bool(wash_targets(engine, actor))
    return None


@effect('water_wash_residue')
def wash_residue(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id
    from .condition_ownership import remove_instance
    targets = wash_targets(ctx.engine, ctx.actor)
    names = {key: (target.display_name if hasattr(target, 'entity_id') else
                   f'{(target.component or {}).get("name") or target.object_kind} at square ({target.position.x}, {target.position.y})')
             for key, target in targets.items()}
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'WATER_WASH', ctx.actor.entity_id), ctx.actor,
                   'choice:needle.water_wash_residue', list(targets), allow_decline=True,
                   labels={key: f'Wash mundane residue from {name}' for key, name in names.items()},
                   name='Cleansing Water', feature_id=CLEANSING,
                   prompt='Cleansing Water: choose one creature or object in your Cleansing Basin to wash. '
                          'Remove mundane surface poison, acid residue, dust, ash or filth; no action or Cultivation Point cost. '
                          'This does not cure Poisoned, magical disease or curses.')
    if not selected:
        return
    target = targets[selected[0]]
    if hasattr(target, 'entity_id'):
        for iid in residue_conditions(target, wash_only=True):
            remove_instance(ctx.engine, target, iid, ctx.source)
        if target.team_id == ctx.actor.team_id:
            from dataclasses import replace
            from ..typed_executor import run_effects
            run_effects(replace(ctx, targets=[target], target=target),
                        [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'pb'}])
    else:
        target.component.pop('mundane_residue', None)
        ctx.engine._update_object(target, ctx.source, actor_id=ctx.actor.entity_id)
    note(ctx.engine, ctx.source, ctx.actor, f'Cleansing Water washes mundane residue from {names[selected[0]]}.')


@hook("compile_action")
def wave_burst_replaces_current_save(action: Any, info: dict[str, Any]) -> Any:
    """The burst replaces the current's initial one-creature push, not two pushes."""
    typed = (action.parameters or {}).get("typed") or {}
    if (typed.get("modifier") or {}).get("id") != "TAL_WATER_WAVE_BURST":
        return None
    effects = [e for e in typed.get("effects") or []
               if not (e.get("type") == "save" and e.get("cast_only") and not e.get("source_modifier"))]
    return action.model_copy(update={"parameters": {**action.parameters, "typed": {**typed, "effects": effects}}})


@effect("water_cleansing")
def cleansing(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects
    from .condition_ownership import remove_instance
    from .rider_choices import pick

    engine, owner, creature = ctx.engine, ctx.actor, ctx.target
    if creature is None or not creature.active or creature.team_id != owner.team_id:
        return
    soaked = [iid for iid, row in creature.conditions.items() if row.condition_id.startswith(SOAKED_PREFIX)]
    burning = [iid for iid, row in creature.conditions.items() if row.condition_id == BURNING]
    upgraded = bool(eff.get('cleansing_water'))
    zone = engine.state.zones.get(ctx.typed.get('_cleansing_zone_id')) if upgraded else None
    cleanable = {**residue_conditions(creature), **{iid: creature.conditions[iid] for iid in burning}}
    can_clean = bool(zone and zone.per_turn_triggered.get('cleansing_water_round') != engine.state.round_number and cleanable)
    labels = {"save": "Advantage on its next saving throw against Poisoned or a disease before the start of its next turn"}
    if soaked:
        labels = {"soaked": "End the Soaked state on itself", **labels}
    if burning:
        labels = {"flames": "Put out the flames on itself (end Burning)", **labels}
    if can_clean:
        labels = {'cleanse': 'Cleansing Water: end Burning, covered-in-smoke or mundane contamination on yourself '
                             '(one creature per Basin per round)', **labels}
    options = list(labels)
    name = 'Cleansing Water (Cleansing Basin)' if upgraded else 'Cleansing Basin'
    chosen = pick(engine, creature, "water_cleansing", name, options, subject=creature, labels=labels, preferred=[options[0]],
                  trigger=f"{creature.display_name} is in your Cleansing Basin",
                  choose=(f'Choose a free benefit; Cleansing Water also grants {int(ctx.numbers.get("pb") or 0)} Temporary HP.'
                          if upgraded else 'Choose an option.'))
    if not chosen:
        return
    if chosen[0] == 'cleanse':
        from .retained_updates import record_zone_update
        for iid in cleanable:
            remove_instance(engine, creature, iid, ctx.source)
        zone.per_turn_triggered['cleansing_water_round'] = engine.state.round_number
        record_zone_update(engine, zone)
    elif chosen[0] == "flames":
        for iid in burning:
            remove_instance(engine, creature, iid, ctx.source)
    elif chosen[0] == "soaked":
        for iid in soaked:
            remove_instance(engine, creature, iid, ctx.source)
    else:
        run_effects(ctx, [{"type": "advantage", "applies_to": "target", "on": "the next saving throw against Poisoned or a disease",
                           "duration": "until_start_of_next_turn",
                           "evidence": "gain Advantage on the next saving throw before the start of its next turn against Poisoned, a disease, smoke, heat, or mundane contamination"}])
    if upgraded:
        run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'pb',
                           'evidence': 'an ally that benefits from the Basin gains Temporary HP equal to your Proficiency Bonus'}])
    extra = f' Cleansing Water grants {int(ctx.numbers.get("pb") or 0)} Temporary HP (use the higher Temporary HP total).' if upgraded else ''
    note(engine, ctx.source, owner, f"Cleansing Basin: {creature.display_name} -- {labels[chosen[0]].lower()}.{extra}", (creature,))


# Living Current extends this existing Water-area implementation. Its passive
# row is sealed by native compilation; old saves without that row stay inert.
LIVING = 'TAL_WATER_LIVING_CURRENT'


@hook('compile_block')
def living_block(block, spec, row, numbers):
    if block == 'water_living_current':
        return [{**row, 'block': block, 'kind': 'living_current', 'numbers': dict(numbers)}]
    return None


def living(engine, actor):
    from .passive_rows import row_of
    return row_of(engine, actor.entity_id, 'water_living_current', 'living_current') is not None


@hook('effect_origins')
def living_origins(engine, actor, action):
    from .water_effects import areas
    from ..space import point
    if not living(engine, actor) or (action.parameters.get('typed') or {}).get('source') != 'WATER_BASE_WATER_LASH':
        return None
    # Every occupied water cell is a legal point, not just an area's centre.
    # No sight requirement is printed for the owned origin. The attack's own
    # target perception and line of effect still use the native geometry seam.
    body = engine._actor_volume(actor)
    return [{'id': f'water:{z.zone_id}:{p.x},{p.y},{p.z}',
             'label': f'Living Current: Water Lash from water at ({p.x}, {p.y}, {p.z * 5} feet high)',
             'position': p.model_dump(mode='json')}
            for z in areas(engine, actor) for p in z.affected_cells
            if engine.grid.distance_between_cell_sets_ft(body, {point(p)}) <= 60]


@hook('compile_action')
def water_basin_capacity(action, info):
    """Fresh native Basin casts enforce the printed category, not a CP pool.

    The separately sealed owner Concentration ruling remains authoritative.
    This applies only to owned Shape Current Basin casts, with +1 for Living.
    """
    typed = action.parameters.get('typed') or {}
    if typed.get('source') != 'WATER_BASE_SHAPE_CURRENT' or 'WATER_BASE_SHAPE_CURRENT' not in info['owned_ids']:
        return None
    if 'Basin' not in str(typed.get('option_label') or action.display_name):
        return None
    effects = [{'type': 'water_basin_capacity', 'limit': 2 if LIVING in info['owned_ids'] else 1},
               *(typed.get('effects') or [])]
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': {**typed, 'effects': effects}}})


@effect('water_basin_capacity')
def replace_basin(ctx, spec):
    from .water_effects import areas
    from .needle import CHOICE, ask, checkpoint_id
    from .. import concentration, zones
    def basins():
        return [z for z in areas(ctx.engine, ctx.actor)
                if 'Basin' in str((ctx.engine.action_catalog[z.source_definition_id].parameters.get('typed') or {}).get('option_label')
                                  or ctx.engine.action_catalog[z.source_definition_id].display_name)]
    # Court's separately owned printed extra area remains available; this
    # does not make its spiritual Domain into physical water or an origin.
    from .water_tide_footwork import courts
    limit = int(spec['limit']) + int(any(courts(ctx.engine, ctx.actor)))
    while len(current := basins()) >= limit:
        options = {z.zone_id: z for z in current}
        selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'WATER_BASIN_REPLACE', ctx.actor.entity_id, len(current)),
                       ctx.actor, CHOICE + 'water_basin_replace', list(options),
                       labels={key: f'End your Basin at ({z.center.x}, {z.center.y})' for key, z in options.items()},
                       name='Water Control Limit', feature_id=LIVING if living(ctx.engine, ctx.actor) else 'WATER_BASE_SHAPE_CURRENT',
                       prompt=f'{ctx.actor.display_name} uses {ctx.action.display_name}. Your Water Control Limit permits '
                              f'{limit} Created Water Basin(s). Choose which existing Basin ends as you create this one.')
        if not selected:
            raise ValueError('Choose a Basin to replace before creating another.')
        z = options[selected[0]]
        held = next((key for key, state in concentration.held(ctx.actor) if state.zone_id == z.zone_id), None)
        if held:
            concentration.end_held(ctx.engine, ctx.actor, held, 'WATER_CONTROL_LIMIT')
        elif ctx.actor.concentration and ctx.actor.concentration.zone_id == z.zone_id:
            ctx.engine._end_concentration(ctx.actor, 'WATER_CONTROL_LIMIT')
        else:
            zones.remove(ctx.engine, z, 'WATER_CONTROL_LIMIT')
        zones.sync_inside(ctx.engine, ctx.source)


@hook('compile_action')
def living_return_action(action, info):
    typed = action.parameters.get('typed') or {}
    if (LIVING not in info['owned_ids'] or typed.get('source') != 'WATER_BASE_RETURN_THE_FLOW'
            or (typed.get('modifier') or {}).get('id') == 'TAL_WATER_TEN_THOUSAND_RETURNING_STREAMS'):
        return None
    # Returning Streams owns its separate multi-effect operation.
    effects = typed.get('effects') or []
    if not any(e.get('type') == 'zone' and e.get('distance_ft') and not e.get('remove') for e in effects):
        return None
    updated = [{'type': 'water_living_move'} if e.get('type') == 'zone' and e.get('distance_ft') and not e.get('remove') else e
               for e in effects]
    description = ('Living Current — Return the Flow: spend a Bonus Action, no Cultivation Points. '
                   'Choose one Basin or Current you created within 60 feet and move it up to 20 feet. '
                   'Its size and remaining duration stay the same; creatures stay where they are.')
    return action.model_copy(update={'target_kind': 'SELF', 'range_ft': None, 'radius_ft': None,
        'parameters': {**action.parameters, 'description': description, 'typed': {**typed, 'effects': updated}}})


def living_destinations(engine, zone):
    """Every area translation reachable within 20 feet, including detours.

    The area's complete footprint crosses no blocked square or diagonal corner.
    Creature occupancy and difficult terrain do not restrict moving water; no
    creature is carried and the zone's altitude, shape and lifetime stay fixed.
    """
    from collections import deque
    from ..gate2_runtime_models import Position
    start = (zone.center.x, zone.center.y)
    offsets = [(c.x-zone.center.x, c.y-zone.center.y, c.z) for c in zone.affected_cells]
    def fits(x, y):
        return all(engine.grid.in_bounds((x+dx, y+dy)) and (x+dx, y+dy) not in engine.grid.blocked
                   for dx, dy, _ in offsets)
    reached, pending = {start: 0}, deque([start])
    result = {}
    while pending:
        x, y = pending.popleft()
        for dx, dy in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
            nx, ny = x+dx, y+dy
            feet = reached[(x,y)] + engine.grid.square_size_ft
            if feet > 20 or (nx,ny) in reached or not fits(nx,ny):
                continue
            if dx and dy and (not fits(nx,y) or not fits(x,ny)):
                continue
            reached[(nx,ny)] = feet
            pending.append((nx,ny))
            p = Position(x=nx, y=ny, z=zone.center.z)
            cells = tuple(Position(x=nx+ox, y=ny+oy, z=oz) for ox,oy,oz in offsets)
            result[f'{nx},{ny}'] = (p, cells)
    return dict(sorted(result.items()))


def living_movable(engine, actor):
    from .water_effects import areas, distance
    return {z.zone_id: z for z in areas(engine, actor)
            if not z.trigger_profile.get('anchor_id') and distance(engine, actor, z, actor) <= 60
            and living_destinations(engine, z)}


@hook('candidate_allowed')
def living_move_allowed(engine, actor, candidate, action):
    if action and any(e.get('type') == 'water_living_move' for e in (action.parameters.get('typed') or {}).get('effects') or []):
        return bool(living_movable(engine, actor))
    return None


@effect('water_living_move')
def living_move(ctx, spec):
    from .needle import CHOICE, ask, checkpoint_id
    from .retained_updates import record_zone_update
    from .. import zones
    available = living_movable(ctx.engine, ctx.actor)
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'WATER_LIVING_MOVE', ctx.actor.entity_id), ctx.actor,
                   CHOICE + 'water_living_area', list(available), allow_decline=True,
                   labels={key: f'Basin or Current at ({z.center.x}, {z.center.y})' for key, z in available.items()},
                   name='Living Current', feature_id=LIVING,
                   prompt=f'Living Current: {ctx.actor.display_name} uses Return the Flow. Choose one of your Basins or Currents '
                          'within 60 feet to move up to 20 feet, or leave them in place. No Cultivation Point cost.')
    if not selected:
        return
    z = available[selected[0]]
    options = living_destinations(ctx.engine, z)
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'WATER_LIVING_DESTINATION', z.zone_id), ctx.actor,
                   CHOICE + 'water_living_destination', list(options), allow_decline=True,
                   labels={key: f'Move water to ({p.x}, {p.y}) along a legal route of at most 20 feet' for key, (p, _) in options.items()},
                   name='Living Current', feature_id=LIVING,
                   prompt=f'Living Current: {ctx.actor.display_name} uses Return the Flow on water at ({z.center.x}, {z.center.y}). '
                          'Choose its destination, up to 20 feet away; creatures stay put and the remaining duration stays the same.')
    if not selected:
        return
    z.center, z.affected_cells = options[selected[0]]
    record_zone_update(ctx.engine, z)
    zones.sync_inside(ctx.engine, ctx.source)
    note(ctx.engine, ctx.source, ctx.actor, f'Living Current: Return the Flow moves water to ({z.center.x}, {z.center.y}); its remaining duration is unchanged.')


@hook('candidate_allowed')
def living_origin_perception(engine, actor, candidate, action):
    """The owned water is an origin, never an extra sensor for an AI seat."""
    origin = (candidate.metadata or {}).get('effect_origin') or {}
    if not str(origin.get('id') or '').startswith('water:'):
        return None
    from ..action_geometry import activate
    from ..target_knowledge import located
    from ..senses import perceives
    with activate(engine, actor, action.source_definition_id, None):
        perceive = perceives if ai_controlled(engine, actor) else located
        return all((target := engine.state.actors.get(tid)) is None or perceive(engine, actor, target)
                   for tid in candidate.target_ids)
