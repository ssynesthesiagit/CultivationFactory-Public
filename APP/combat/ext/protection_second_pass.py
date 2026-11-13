"""Opt-in, exact-instance Sanctuary relief; historical state rows stay inert."""
from __future__ import annotations
import re
from typing import Any
from . import effect, hook, note

POLICY = 'protection_sanctuary_relief_policy'


def relief_instances(engine: Any, creature: Any, *, boundary: bool = False) -> list[tuple[str, Any, str]]:
    """Represented ordinary conditions, damage and forced movement only."""
    from . import source_eligibility as sources
    from ..typed_executor import is_active_typed_condition
    from .effect_durations import due, native_due, skipped_expiry_slots
    from .ability_source import source_label
    result = []
    for key, condition in creature.conditions.items():
        if not is_active_typed_condition(condition):
            continue
        if due(engine, condition.expires_on, skipped=skipped_expiry_slots(creature, condition)) or (
                boundary and native_due(engine, condition.expires_on, 'START_OF_TURN',
                                        source_id=condition.source_actor_id, holder_id=creature.entity_id)):
            continue
        action = sources.catalog_action(engine, condition.source_definition_id)
        power = sources.printed_power(action)
        if power and (sources.protected_power(*power, permanent_transformations=True)
                      or re.search(r'\b(?:curse|permanent injury)\b', '\n'.join(
                          line for line in power[1].splitlines() if line.startswith('#')), re.I)):
            continue
        named = condition.condition_id.removeprefix('condition:typed.')
        if named in ('frightened', 'grappled', 'restrained'):
            # An unattributed named condition may be the whole of a curse or
            # Secret effect. New service rows fail closed instead of guessing.
            if not sources.ordinary_source(action):
                continue
            result.append((key, condition, named.title()))
            continue
        typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
        mechanic = str(typed.get('option_of') or typed.get('source') or '')
        if not (mechanic.startswith('tianxia.talent.') or mechanic.startswith('TAL_')) or not sources.ordinary_source(action):
            continue
        kinds = set()
        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if value.get('type') in ('damage', 'forced_movement'):
                    kinds.add(value['type'])
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit((condition.data or {}).get('ongoing_effects') or [])
        if kinds:
            label = 'ongoing damage' if 'damage' in kinds else 'ongoing forced movement'
            result.append((key, condition, f'{label.title()} — {source_label(engine, condition.source_definition_id)}'))
    return result


@effect('protection_sanctuary')
def activate_sanctuary(ctx: Any, row: dict[str, Any]) -> None:
    from . import protection, states
    from .needle import CHOICE, ask, checkpoint_id
    from .retained_updates import record_instance_update
    from ..typed_executor import duration_expiry
    # Transport-less predecessor engines retain their original state route.
    # Service sessions always carry the choice cache and opt into this policy.
    if not hasattr(ctx.engine, '_gate4_reaction_cache'):
        states.state(ctx, {**row, 'name': 'sanctuary_without_borders'})
        return
    wards = protection.own_wards(ctx.engine, ctx.actor)
    if not wards:
        return
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'sanctuary_ward', ctx.actor.entity_id), ctx.actor,
                 CHOICE + 'sanctuary_ward', [zone.zone_id for zone in wards],
                 labels={zone.zone_id: 'Protect your ' + str((zone.trigger_profile or {}).get('name') or 'Ward') for zone in wards},
                 name='Sanctuary Without Borders', prompt='Choose your Ward. Each willing ally may end one eligible effect once during this activation.')
    zone = next((zone for zone in wards if zone.zone_id in chosen), None)
    if zone is None:
        return
    states.state(ctx, {**row, 'name': 'sanctuary_without_borders'})
    running = states.active(ctx.engine, ctx.actor, 'sanctuary_without_borders')
    running.data = {**running.data, POLICY: 1, 'ward_id': zone.zone_id,
                    'relief_deadline': duration_expiry(ctx.engine, ctx.typed.get('duration') or {})}
    record_instance_update(ctx.engine, ctx.actor, 'condition', running.instance_id, running)


def offer_relief(engine: Any, owner: Any, creature: Any, running: Any, *, boundary: bool = False, arrival_at: Any = None) -> None:
    """Remove one instance; deferred entry uses its recorded endpoint, without relocation."""
    from . import protection, states
    from .needle import CHOICE, ask, checkpoint_id
    from .end_effect import remove_instance
    from ..spatial_areas import zone_contains
    from .effect_durations import due
    if not creature.active or creature.team_id != owner.team_id or due(engine, (running.data or {}).get('relief_deadline')):
        return
    zone = next((z for z in protection.own_wards(engine, owner) if z.zone_id == (running.data or {}).get('ward_id')), None)
    if zone is None or not zone_contains(engine, creature, zone, at=arrival_at):
        return
    if zone.duration_rounds is not None and engine.state.round_number - zone.created_round >= zone.duration_rounds:
        return
    used_key = f'protection_sanctuary_round_used:{running.instance_id}'
    if creature.entity_id in (owner.turn_flags.get(used_key) or []):
        return
    instances = relief_instances(engine, creature, boundary=boundary)
    if not instances:
        return
    trigger = 'start' if boundary else 'entry'
    checkpoint = checkpoint_id(engine, 'protection_sanctuary', owner.entity_id, running.instance_id, creature.entity_id, trigger)
    timing = 'starts its turn' if boundary else 'enters the Ward'
    chosen = ask(engine, getattr(engine, '_active_intent', None), checkpoint, creature,
                 CHOICE + 'protection_sanctuary', [key for key, _, _ in instances],
                 labels={key: f'End {label}' for key, _, label in instances}, preferred=[instances[0][0]],
                 allow_decline=True, name='Sanctuary Without Borders', target_id=creature.entity_id,
                 prompt=f'{creature.display_name} {timing} protected by {owner.display_name}’s Sanctuary Without Borders. '
                        'You may end one eligible ordinary effect now, once during this Sanctuary. No Action or Reaction is needed.')
    selected = next((item for item in instances if item[0] in chosen), None)
    if selected is None:
        return
    key, item, label = selected
    remove_instance(states.context(engine, owner, running.source_definition_id, [creature]), creature, 'condition', key, item)
    owner.turn_flags[used_key] = sorted({*(owner.turn_flags.get(used_key) or []), creature.entity_id})
    note(engine, running.source_definition_id, creature, f'Sanctuary Without Borders: {creature.display_name} ends {label}.')


def sanctuaries(engine: Any, creature: Any):
    from . import states
    for owner in engine.state.actors.values():
        if owner.team_id != creature.team_id:
            continue
        running = states.active(engine, owner, 'sanctuary_without_borders')
        if running is not None and (running.data or {}).get(POLICY) == 1:
            yield owner, running


@hook('turn_boundary_start')
def sanctuary_start(engine: Any, creature: Any) -> None:
    for owner, running in sanctuaries(engine, creature):
        offer_relief(engine, owner, creature, running, boundary=True)


@hook('zone_arrival')
def sanctuary_arrival(engine: Any, creature: Any, start: Any, end: Any, forced: bool) -> None:
    from ..spatial_areas import zone_contains
    for owner, running in sanctuaries(engine, creature):
        zone = engine.state.zones.get((running.data or {}).get('ward_id'))
        if zone is None or not zone.active or zone_contains(engine, creature, zone, at=start) or not zone_contains(engine, creature, zone, at=end):
            continue
        # Entry receipt is distinct from benefit use: declining the first entry
        # cannot turn a second entry on the same table turn into a fresh offer.
        token = f"{engine.state.current_actor_id}:{engine.state.actors[engine.state.current_actor_id].turns_started}"
        flag = f'protection_sanctuary_round_entered:{running.instance_id}:{creature.entity_id}'
        if owner.turn_flags.get(flag) == token:
            continue
        offer_relief(engine, owner, creature, running, arrival_at=end)
        owner.turn_flags[flag] = token


@hook('choice_reactors')
def sanctuary_recipients(engine: Any) -> tuple[str, ...]:
    """Pure potential-recipient enrollment for AI-step player-choice probes.

    Advertise allies even outside the Ward or without a condition: the pending
    AI action can move them inside or establish an effect before a boundary.
    The relief checkpoint still checks Ward membership at the trigger position, expiry and instances;
    the service filters manual modes and lets AI creatures answer for themselves.
    Unstamped historical Sanctuaries remain inert.
    """
    from . import states
    teams = set()
    for owner in engine.state.actors.values():
        running = states.active(engine, owner, 'sanctuary_without_borders')
        if owner.active and running is not None and (running.data or {}).get(POLICY) == 1:
            teams.add(owner.team_id)
    return tuple(creature.entity_id for creature in engine.state.actors.values()
                 if creature.active and creature.team_id in teams)
