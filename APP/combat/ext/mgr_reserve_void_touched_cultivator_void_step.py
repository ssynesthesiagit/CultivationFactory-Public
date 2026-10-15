"""Void-Touched Cultivator's acquired family state and Empty Palm delivery.

Ownership is an exact earned feature, never a Void Sphere or a similar name.
The permanent Scar comes from recorded native acquisition or a sealed builder
choice. Marks are separate source-owned scene records, not ordinary curses;
their integer count and fixed visible sign survive ordinary combat replay.
No hook grants ownership or acts on characters without the acquired family.
"""
from dataclasses import replace

from . import effect, hook

PARENT = 'tianxia.subpath.qi.void_touched_cultivator'
PREFIX = PARENT + '.feature.'
TIERS = {'void_step': 3, 'empty_palm': 6, 'hollow_field': 10,
         'erase': 14, 'law_of_nonexistence': 18}
MARK = 'condition:typed.void_touched_mark'
MERIDIAN = 'condition:typed.void_touched_meridian'
CP_POOLS = ('resource:core.qi', 'resource:core.stamina', 'resource:core.resonance', 'resource:core.cp')


def acquisition_scar(sheet):
    """Read an actual acquisition choice; loose test/profile tags grant nothing."""
    paths = (sheet.get('path_and_subpath') or {}).get('paths') or []
    for path in paths:
        provenance = path.get('subpath_or_tradition_acquisition_provenance') or {}
        if (path.get('path_id') == 'tianxia.path.qi_cultivation'
                and path.get('subpath_or_tradition_id') == PARENT
                and provenance.get('recorded') is True
                and provenance.get('canonical_content_id') == PARENT):
            from character_creation.acquisition_choices import validate
            choices = validate([PARENT], path.get('acquisition_choices'))
            return choices['void_scar']
    from character_creation.acquisition_choices import from_sheet
    return from_sheet(sheet).get('void_scar', '')


def family_source(action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    source = typed.get('source') or ''
    return source if source.startswith(PREFIX) else ''


def turn_token(engine):
    current = engine.state.actors.get(engine.state.current_actor_id)
    return f'{engine.state.round_number}:{engine.state.current_slot_index}:{getattr(current, "turns_started", 0)}'


def owned(ctx, feature):
    return (family_source(ctx.action) == PREFIX + feature
            and bool(ctx.typed.get('void_scar'))
            and int(ctx.numbers.get('source_cl', ctx.numbers.get('cl') or 0)) >= TIERS[feature])


def marks(target, owner_id):
    """Source-scoped count; another cultivator's marks cannot pay this one's cost."""
    return sum(int(c.data.get('count') or 0) for c in target.conditions.values()
               if c.condition_id == MARK and c.source_actor_id == owner_id)


def add_mark(ctx, target):
    """Cap at three. Refresh the common scene deadline through native events."""
    owner = ctx.actor.entity_id
    count = min(3, marks(target, owner) + 1)
    for condition in list(target.conditions.values()):
        if condition.condition_id == MARK and condition.source_actor_id == owner:
            ctx.engine._remove_condition_instance(target, condition.instance_id, ctx.source,
                                                  expected=condition)
    ctx.engine._apply_condition(target, MARK, ctx.source, owner, expires_on='UNTIL_REMOVED',
        data={'count': count, 'source_cl': int(ctx.numbers.get('source_cl', ctx.numbers.get('cl') or 0)),
              'sign': 'A silent outline, visible through Qi Sensing',
              'label': f'{count} Void Marks from {ctx.actor.display_name}; end when the scene ends'})


def spend_marks(ctx, target, count):
    """Spend only real, committed marks from this source; never go negative."""
    owner = ctx.actor.entity_id
    current = marks(target, owner)
    if current < count:
        return False
    held = [c for c in target.conditions.values() if c.condition_id == MARK and c.source_actor_id == owner]
    for condition in held:
        ctx.engine._remove_condition_instance(target, condition.instance_id, ctx.source, expected=condition)
    if current > count:
        ctx.engine._apply_condition(target, MARK, ctx.source, owner, expires_on='UNTIL_REMOVED',
            data={**held[0].data, 'count': current - count,
                  'label': f'{current-count} Void Marks from {ctx.actor.display_name}; end when the scene ends'})
    return True


@hook('compile_action')
def compile_family(action, info):
    source = family_source(action)
    if not source:
        return action
    feature = source.removeprefix(PREFIX)
    if feature not in TIERS:
        return action
    typed = dict(action.parameters['typed'])
    typed.update(min_cl=TIERS[feature], void_scar=acquisition_scar(info['owner_sheet']))
    updates = {}
    if feature == 'void_step':
        # The generic target mark is not Trace: its subject must be selected
        # after the actual departure and arrival have both been committed.
        typed['effects'] = [row for row in typed.get('effects') or [] if row.get('type') != 'mark']
        updates.update(target_kind='SELF', range_ft=30)
    if feature == 'empty_palm':
        label = typed.get('option_label') or ''
        if label == 'Empty the Meridian':
            # Everything after "On a hit" belongs inside the hit branch,
            # including its mark, save, drain and no-points alternative.
            typed['effects'] = [{'type': 'attack', 'attack_kind': 'cultivation_melee', 'count': 1,
                'on_hit': [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 4, 'sides': 8},
                            'formula': 'key_ability_modifier', 'damage_types': ['force', 'void']},
                           {'type': 'void_touched_palm_hit', 'operation': 'meridian'}], 'on_miss': []}]
            typed['riders'] = []
        else:
            # Preserve the operation's existing hit tree, moving only the
            # incorrectly unconditional mark inside each real hit branch.
            from copy import deepcopy
            effects = deepcopy(typed.get('effects') or [])
            effects = [row for row in effects if not (row.get('type') == 'mark' and row.get('mark') == 'Void Mark')]
            for attack in effects:
                if attack.get('type') == 'attack':
                    attack.setdefault('on_hit', []).append({'type': 'void_touched_palm_hit', 'operation': 'mark'})
            typed['effects'] = effects
    return action.model_copy(update={**updates, 'parameters': {**action.parameters, 'typed': typed}})


@hook('candidate_allowed')
def family_admission(engine, actor, candidate, action):
    if family_source(action) and not (action.parameters['typed'].get('void_scar')):
        return False
    if family_source(action) == PREFIX + 'void_step':
        if actor.turn_flags.get('_round_void_step_turn') == turn_token(engine):
            return False
    return None


@hook('resolution_final')
def record_void_step_use(engine, actor, action, candidate, intent):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if family_source(action) == PREFIX + 'void_step' and typed.get('void_scar'):
        actor.turn_flags['_round_void_step_turn'] = turn_token(engine)


@hook('teleport_settled')
def trace_after_void_step(ctx, subject, previous, destination, unwilling):
    if subject is not ctx.actor or not owned(ctx, 'void_step'):
        return
    from ..senses import perceives
    from .needle import ask
    from ..relations import relation, ENEMY
    token = turn_token(ctx.engine)
    eligible = []
    departure_viewer = subject.model_copy(update={'position': previous})
    for target in ctx.engine.state.actors.values():
        if not target.active or target.turn_flags.get('_round_void_trace:' + subject.entity_id) == token:
            continue
        at_departure = ctx.engine._distance_actor_to_cell(target, previous) <= 5
        at_arrival = ctx.engine._distance_actor_to_cell(target, destination) <= 5
        perceived = (target is subject or (at_departure and perceives(ctx.engine, departure_viewer, target))
                     or (at_arrival and perceives(ctx.engine, subject, target)))
        if (at_departure or at_arrival) and perceived:
            eligible.append(target)
    by_id = {target.entity_id: target for target in eligible}
    selected = ask(ctx.engine, ctx.intent, 'void_step_trace', subject,
        'choice:needle.void_step_trace', list(by_id),
        labels={key: target.display_name for key, target in by_id.items()},
        preferred=[target.entity_id for target in eligible if relation(ctx.engine, subject, target) == ENEMY],
        name='Void Step — Trace of Nonexistence',
        prompt=f'{subject.display_name} used Void Step. Choose one perceived creature within 5 feet of departure or arrival to gain a Void Mark until the scene ends. No additional Qi cost.')
    if selected:
        target = by_id[selected[0]]
        add_mark(ctx, target)
        target.turn_flags['_round_void_trace:' + subject.entity_id] = token


@effect('void_touched_palm_hit', harmful=True)
def palm_hit(ctx, row):
    if not owned(ctx, 'empty_palm'):
        return
    from ..typed_executor import run_effects, effect_subjects
    for target in effect_subjects(ctx, {'applies_to': 'target'}, harmful=True):
        child = replace(ctx, target=target, targets=[target])
        add_mark(child, target)
        if row.get('operation') != 'meridian':
            continue
        points = sum(int(target.resources.get(pool) or 0) for pool in CP_POOLS)
        if points == 0:
            run_effects(child, [{'type': 'damage', 'applies_to': 'target',
                'flat': 2 * int(ctx.numbers.get('pb') or 0), 'damage_types': ['force']}])
            continue
        run_effects(child, [{'type': 'save', 'applies_to': 'target', 'ability': 'con',
            'on_fail': [{'type': 'void_touched_meridian_drain', 'failed': 1}],
            'on_success': [{'type': 'void_touched_meridian_drain', 'failed': 0}]}])


@effect('void_touched_meridian_drain', harmful=True)
def drain_meridian(ctx, row):
    if not owned(ctx, 'empty_palm'):
        return
    from .needle import ask
    from .effect_durations import holder_next_turn
    from ..typed_executor import effect_subjects
    for target in effect_subjects(ctx, {'applies_to': 'target'}, harmful=True):
        pools = [pool for pool in CP_POOLS if target.resources.get(pool, 0) > 0]
        if pools:
            labels = {pool: pool.removeprefix('resource:core.').title() for pool in pools}
            selected = ask(ctx.engine, ctx.intent, 'empty_palm_pool:' + target.entity_id,
                ctx.actor, 'choice:needle.void_palm_pool', pools, labels=labels,
                name='Empty Palm — Empty the Meridian', target_id=target.entity_id,
                prompt=f'Empty Palm hit {target.display_name}. Choose its current cultivation-point pool to drain.')
            if selected:
                amount = int(ctx.numbers.get('pb') or 0) if row['failed'] else 1
                pool = selected[0]
                ctx.engine._spend_resource(target, pool, min(amount, target.resources[pool]), ctx.source)
        if row['failed']:
            ctx.engine._apply_condition(target, MERIDIAN, ctx.source, ctx.actor.entity_id,
                expires_on=holder_next_turn(target),
                data={'label': f'{target.display_name} cannot regain cultivation points until the start of its next turn'})


@hook('resource_gain_allowed')
def meridian_recovery(engine, actor, resource_id, amount, source_id):
    if resource_id in CP_POOLS and amount > 0 and any(c.condition_id == MERIDIAN for c in actor.conditions.values()):
        return False
    return None
