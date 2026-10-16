"""Boundary Walker's mapped threshold actions. Uses mounted aperture geometry.

Only newly compiled boundary_passage rows/actions opt in. Untagged geometry is
never inferred from names. Strict walking/forced/teleport checkpoints handle
crossing before arrival, and native teleport handles destinations and defenses.
"""
from . import effect, hook
from . import spirit_traditions as st, threshold_geometry as geometry

PREFIX = 'tianxia.tradition.spirit.boundary_walker.feature.'
STEP, MARK, DENY = (PREFIX + name for name in ('threshold_step', 'mark_the_door', 'deny_passage'))
RESONANCE = 'resource:core.resonance'
MARK_KIND = 'BOUNDARY_MARK'


def owns(engine, actor, feature):
    return any(row.get('block') == 'boundary_passage' and row.get('feature_id') == feature
               for row in engine.typed_passive_rows.get(actor.entity_id, []))


@hook('compile_block')
def ownership(block, spec, row, numbers):
    return [{**row, 'block': block, 'keeps_compiling': True}] if block == 'boundary_passage' else None


def marks(engine, threshold):
    return [obj for obj in engine.state.objects.values() if not obj.destroyed
            and obj.object_kind == MARK_KIND and obj.component.get('threshold_id') == threshold.object_id]


def _eligible_steps(engine, actor, action):
    from .teleport_steps import destinations
    from .states import active
    from ..typed_executor import condition_rules
    if any(row.get('no_teleport') for row in condition_rules(actor)):
        return []
    reach = 30 if active(engine, actor, 'walk_the_border') is not None else 15
    if actor.turn_flags.get('boundary_step') or actor.resources.get(RESONANCE, 0) < 1:
        return []
    out = []
    from ..targeting import line_of_effect
    adjacent = actor.turn_flags.get('boundary_adjacent_at_start')
    if adjacent is None:
        # The first turn precedes map-object installation. Recover its starting
        # position from the first committed movement, or its unchanged position.
        from ..gate2_runtime_models import Position
        started = max((e.sequence for e in engine.events if e.event_type == 'TURN_STARTED'
                       and e.actor_id == actor.entity_id), default=0)
        path = next(((e.payload or {}).get('path', []) for e in engine.events
                     if e.sequence > started and e.event_type == 'MOVEMENT_COMMITTED'
                     and e.actor_id == actor.entity_id), [])
        origin = Position.model_validate(path[0]) if path else actor.position
        adjacent = [o.object_id for o in geometry.thresholds(engine)
                    if engine.grid.distance_ft(origin, o.position) <= 5]
    for obj in geometry.thresholds(engine):
        if not geometry.open_threshold(obj):
            continue
        if (obj.object_id not in adjacent
                and obj.object_id not in actor.turn_flags.get('boundary_crossed', [])):
            continue
        cells = [cell for cell in destinations(engine, actor, engine.grid.distance_ft(actor.position, obj.position) + reach)
                 if engine.grid.distance_ft(obj.position, cell) <= reach
                 and geometry.crosses(obj, actor.position, cell)
                 and line_of_effect(engine, actor, destination=cell)]
        if cells:
            out.append((obj, cells))
    return out


@effect('boundary_step')
def step(ctx, row):
    from . import needle
    from ..typed_executor import _teleport
    choices = _eligible_steps(ctx.engine, ctx.actor, ctx.action)
    if not choices:
        return
    by_id = {obj.object_id: (obj, cells) for obj, cells in choices}
    pick = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'THRESHOLD_STEP', ctx.actor.entity_id),
                      ctx.actor, 'choice:needle.boundary.threshold', list(by_id),
                      labels={key: obj.component.get('name', 'Threshold') for key, (obj, cells) in by_id.items()},
                      preferred=list(by_id)[:1], name='Threshold Step', feature_id=STEP,
                      prompt='Which open threshold will you cross?', allow_decline=True)
    if not pick:
        return
    obj, cells = by_id[pick[0]]
    ids = [needle.cell_id(cell) for cell in cells]
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'THRESHOLD_LANDING', obj.object_id),
                        ctx.actor, 'choice:needle.boundary.landing', ids,
                        labels={needle.cell_id(cell): f'Arrive at {cell.x},{cell.y}' for cell in cells},
                        preferred=ids[:1], name='Threshold Step', feature_id=STEP,
                        prompt='Choose a visible, open space on the other side.', allow_decline=True)
    if not chosen:
        return
    ctx.actor.turn_flags['boundary_step'] = 1
    ctx.engine._spend_resource(ctx.actor, RESONANCE, 1, STEP)
    _teleport(ctx, needle.position_of(chosen[0]))


@hook('compile_actions')
def actions(info):
    from ..gate2_runtime_models import ActionDefinition
    out = []
    if STEP in info['owned_ids']:
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.boundary_step",
            display_name='Threshold Step', owner_id=info['actor_id'], economy='NONE', resolution_kind='TYPED', target_kind='SELF',
            parameters={'boundary_passage': 'step', 'typed': {'source': STEP, 'numbers': info['numbers'],
                'effects': [{'type': 'boundary_step'}], 'riders': []},
                'description': 'Once per turn, spend 1 Resonance to cross an open threshold you began beside or crossed this turn. Choose a visible unoccupied space within 15 feet of it (30 feet during Walk the Border).'}))
    if MARK in info['owned_ids']:
        for mode in ('witnessing', 'invited', 'refusing'):
            out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.boundary_mark.{mode}",
                display_name=f'Mark the Door: {mode.title()}', owner_id=info['actor_id'], economy='ACTION', resolution_kind='TYPED',
                target_kind='OBJECT', range_ft=5, costs=((RESONANCE, 2),),
                parameters={'boundary_passage': mode, 'typed': {'source': MARK, 'numbers': info['numbers'], 'effects': [], 'riders': []},
                    'description': {
                        'witnessing': 'Action, touch, 2 Resonance: Mark one mapped threshold. For 1 mile, learn when a spiritually perceptible creature crosses it; for a marked, possessed, undead, spirit, or known creature, also learn its direction and willingness.',
                        'invited': 'Action, touch, 2 Resonance: Mark one mapped threshold and name up to your Wisdom modifier in creatures or categories. They may cross without triggering your hostile Boundary Walker effects; this does not compel them.',
                        'refusing': 'Action, touch, 2 Resonance: Mark one mapped threshold and choose a creature or category. The first qualifying creature each round makes a Charisma save: on a failure it stops before crossing; on a success it crosses and bears your Resonance Mark until the end of your next turn.'}[mode]
                    + ' The Mark is damageable (AC 12 + your Proficiency Bonus; 5 × PB Hit Points; Psychic and Force Resistance; Poison and Disease Immunity). Destroying the physical threshold makes the Mark unusable.'}))
    return out or None


@hook('candidate_allowed')
def gates(engine, actor, candidate, action):
    mode = action.parameters.get('boundary_passage') if action else None
    if mode == 'step':
        return bool(_eligible_steps(engine, actor, action))
    if mode == 'refusing':
        from . import ai_controlled
        from ..target_knowledge import located
        if ai_controlled(engine, actor):
            return any(c.active and c.team_id != actor.team_id and located(engine, actor, c)
                       for c in engine.state.actors.values())
    if action and st.feature_of(action) in (MARK, DENY) and not mode:
        return False  # crossing reactions and object actions replace the old empty activation
    return None


@hook('object_targets')
def mark_targets(engine, actor, action):
    if action.parameters.get('boundary_passage') not in {'witnessing', 'invited', 'refusing'}:
        return []
    return [obj.object_id for obj in geometry.thresholds(engine)]


@hook('object_action')
def place_mark(engine, actor, action, obj, candidate, intent):
    mode = action.parameters.get('boundary_passage')
    if mode not in {'witnessing', 'invited', 'refusing'}:
        return None
    from ..gate2_runtime_models import RuntimeObjectState
    from . import needle
    from ..target_knowledge import located
    choices = {c.entity_id: c.display_name for c in engine.state.actors.values()
               if c.active and located(engine, actor, c)}
    selection = []
    if mode == 'refusing':
        # These broad categories are presented independently of the current
        # roster, so hidden creatures cannot reveal which categories are present.
        choices.update({'kind:' + kind: kind.title() for kind in
                        ('aberration', 'beast', 'celestial', 'construct', 'dragon', 'elemental',
                         'fey', 'fiend', 'giant', 'humanoid', 'monstrosity', 'ooze', 'plant', 'undead', 'spirit')})
        choices.update({'marked': 'Creatures bearing your Resonance Mark', 'possessed': 'Possessed creatures'})
        preferred = [c.entity_id for c in engine.state.actors.values() if c.active and c.team_id != actor.team_id and located(engine, actor, c)][:1]
    else:
        preferred = [c.entity_id for c in engine.state.actors.values() if c.active and c.team_id == actor.team_id and located(engine, actor, c)]
    if mode != 'witnessing':
        count = max(0, int(action.parameters['typed']['numbers'].get('key_mod', 0))) if mode == 'invited' else 1
        if count:
            selection = needle.ask(engine, intent, needle.checkpoint_id(engine, 'MARK_THE_DOOR', obj.object_id), actor,
                'choice:needle.boundary.subjects', list(choices), labels=choices, preferred=preferred[:count],
                minimum=1 if mode == 'refusing' else 0, maximum=count, default_count=count, automatic_options=preferred if mode == 'invited' else preferred, name='Mark the Door', feature_id=MARK,
                prompt='Who has permission to cross?' if mode == 'invited' else 'Which creature or category will this mark refuse?')
    pb = int(action.parameters['typed']['numbers']['pb'])
    for old in marks(engine, obj):
        if old.owner_id == actor.entity_id:
            engine._update_object(old.model_copy(update={'destroyed': True}), MARK, actor.entity_id)
    engine._update_object(RuntimeObjectState(object_id=f'object:boundary.{actor.entity_id}.{engine.state.event_sequence}',
        object_kind=MARK_KIND, owner_id=actor.entity_id, position=obj.position, unattended=True, flammable=False, ac=12 + pb,
        current_hp=5 * pb, maximum_hp=5 * pb, damage_immunities=('POISON', 'DISEASE'),
        component={'name': f'{mode.title()} Threshold Mark', 'threshold_id': obj.object_id,
                   'mode': mode, 'subjects': list(selection or []), 'resist': ['PSYCHIC', 'FORCE']}), MARK, actor.entity_id)
    return True


def _matches(engine, owner, mover, subjects):
    from .creature_kinds import matches
    from ..typed_executor import bears_mark
    return any(key == mover.entity_id or (key.startswith('kind:') and matches(mover, key[5:]))
               or (key == 'possessed' and matches(mover, 'possessed'))
               or (key == 'marked' and bears_mark(mover, owner.entity_id, 'Resonance')) for key in subjects)


def crossing(engine, mover, start, end, intent, *, teleport=False, forced=False):
    from . import needle
    from ..typed_executor import run_effects
    from ..target_knowledge import located
    crossed = [obj for obj in geometry.thresholds(engine) if geometry.crosses(obj, start, end)]
    for threshold in crossed:
        invited = set()
        for mark in marks(engine, threshold):
            owner = engine.state.actors.get(mark.owner_id)
            if owner is None or not owner.active:
                continue
            data = mark.component
            if data['mode'] == 'invited' and _matches(engine, owner, mover, data['subjects']):
                invited.add(owner.entity_id)
        for mark in marks(engine, threshold):
            owner = engine.state.actors.get(mark.owner_id)
            if owner is None or not owner.active or owner.entity_id in invited:
                continue
            data = mark.component
            if data['mode'] != 'refusing' or not _matches(engine, owner, mover, data['subjects']):
                continue
            flag = f"boundary_refused_round_{mark.object_id}"
            if owner.turn_flags.get(flag) == engine.state.round_number:
                continue
            owner.turn_flags[flag] = engine.state.round_number
            ctx = st.context(engine, owner, st.feature_action(engine, owner, MARK), [mover], intent=intent)
            if st.save(ctx, mover, 'cha'):
                return MARK
            run_effects(ctx, [{'type': 'mark', 'mark': 'Resonance Marked', 'applies_to': 'target',
                             'duration': {'kind': 'until_end_of_your_next_turn'}}])
        for owner in sorted(engine.state.actors.values(), key=lambda c: c.entity_id):
            if (owner.entity_id in invited or not owns(engine, owner, DENY) or not st.can_react(owner)
                    or owner.resources.get(RESONANCE, 0) < 4 or engine.grid.distance_ft(owner.position, threshold.position) > 30
                    or not located(engine, owner, mover)):
                continue
            # An automatic response may harm only a perceived enemy.
            preferred = ['deny'] if owner.team_id != mover.team_id else []
            answer = needle.ask(engine, intent, needle.checkpoint_id(engine, 'DENY_PASSAGE', mover.entity_id), owner,
                'choice:needle.boundary.deny', ['deny'], labels={'deny': 'Deny Passage (Reaction, 4 Resonance)'},
                preferred=preferred, automatic_options=['deny'] if preferred else [], default='decline' if not preferred else 'first', allow_decline=True,
                prompt=f'{mover.display_name} attempts to cross a threshold.', name='Deny Passage', feature_id=DENY)
            if not answer:
                continue
            from ..paid_relocation import activation
            with activation(engine, owner, DENY, independent=True):
                owner.reaction_available = False
                engine._spend_resource(owner, RESONANCE, 4, DENY)
                engine._append_event('REACTION_RESOLVED', DENY, actor_id=owner.entity_id, target_ids=(mover.entity_id,),
                    payload={'checkpoint': 'THRESHOLD_CROSSING', 'reaction_name': 'Deny Passage'})
                ctx = st.context(engine, owner, st.feature_action(engine, owner, DENY), [mover], intent=intent)
                failed = st.save(ctx, mover, 'cha')
                if failed:
                    outcome = needle.ask(engine, intent,
                        needle.checkpoint_id(engine, 'DENY_PASSAGE_FAILED_SAVE', mover.entity_id), owner,
                        'choice:needle.boundary.deny_outcome', ['stop', 'return'],
                        labels={'stop': 'Stop before crossing (lose the spent movement)',
                                'return': 'Return to the space just before crossing'},
                        preferred=['stop'], prompt=f'Choose the failed-save result for {mover.display_name}. '
                        'Spirit expulsion is not supported by this table.', name='Deny Passage', feature_id=DENY)
                    run_effects(ctx, [{'type': 'spiritual_pressure', 'applies_to': 'target'}])
                    if not teleport and not forced:
                        mover.movement_remaining_ft = max(0, mover.movement_remaining_ft - engine.grid.square_size_ft)
                    # Both supported outcomes resolve at this pre-arrival
                    # checkpoint to the same prior space; expulsion remains a
                    # clearly disclosed unsupported rider.
                    return DENY
                run_effects(ctx, [{'type': 'speed', 'applies_to': 'target', 'flat': -10, 'expires_on': 'END_OF_CURRENT_TURN'}])
                engine._apply_condition(mover, 'condition:typed.boundary_crossing_lock', DENY, owner.entity_id,
                    expires_on='END_OF_CURRENT_TURN', data={'rule': {'no_teleport': True, 'no_incorporeal': True},
                                                          'label': 'Cannot teleport or become incorporeal again this turn'})
    return None


@hook('movement_attempt')
def walking(engine, mover, previous, nxt, intent):
    source = crossing(engine, mover, previous, nxt, intent)
    return {'stop': True, 'source_id': source, 'label': 'The threshold refuses passage.'} if source else None


@hook('forced_movement_attempt')
def pushed(engine, mover, previous, nxt, intent):
    source = crossing(engine, mover, previous, nxt, intent, forced=True)
    return {'stop': True, 'source_id': source, 'label': 'The threshold refuses passage.'} if source else None


@hook('teleport_gate')
def teleporting(ctx, previous, destination):
    return False if crossing(ctx.engine, ctx.actor, previous, destination, ctx.intent, teleport=True,
        forced=ctx.intent is not None and ctx.intent.actor_id != ctx.actor.entity_id) else None


@hook('event')
def remember_crossings(engine, event_type, kwargs):
    if event_type != 'MOVEMENT_COMMITTED':
        return
    from ..gate2_runtime_models import Position
    mover = engine.state.actors.get(kwargs.get('actor_id'))
    if mover is None:
        return
    path = [Position.model_validate(cell) for cell in (kwargs.get('payload') or {}).get('path', [])]
    payload = kwargs.get('payload') or {}
    teleport = bool(payload.get('teleport'))
    forced = payload.get('forced')
    for threshold in geometry.thresholds(engine):
        # A detour may start on the opposite side from its actual crossing.
        # Keep the first intersecting edge for this threshold's single notice.
        crossing_edge = next(((a, b) for a, b in zip(path, path[1:])
                              if geometry.crosses(threshold, a, b)), None)
        if crossing_edge is None:
            continue
        for mark in marks(engine, threshold):
            owner = engine.state.actors.get(mark.owner_id)
            if owner is None or not owner.active or mark.component.get('mode') != 'witnessing':
                continue
            from ..target_knowledge import located
            if engine.grid.distance_ft(owner.position, threshold.position) > 5280:
                continue
            known = located(engine, owner, mover) or _matches(engine, owner, mover, ['marked'])
            directions = ('north', 'south') if threshold.component['mount_axis'] == 'h' else ('west', 'east')
            first = 0 if geometry.side(threshold, crossing_edge[0]) < 0 else 1
            direction = f'{directions[first]} to {directions[1 - first]}'
            subject = mover.display_name if known else 'A creature'
            travel = 'teleports across' if teleport else 'crosses'
            consent = 'willingly' if forced is False else 'forced movement' if forced is True else 'consent unknown'
            detail = f' ({direction}; {consent})' if known else ''
            engine._append_event('PASSIVE_TRIGGERED', MARK, actor_id=owner.entity_id,
                target_ids=(mover.entity_id,) if known else (), payload={
                    'log': f"{subject} {travel} {threshold.component.get('name', 'the threshold')}{detail}.",
                    'threshold_crossing': {'threshold_id': threshold.object_id,
                        **({'creature_id': mover.entity_id, 'direction': direction,
                            **({'willing': not forced} if forced is not None else {})} if known else {})}})
    ids = {obj.object_id for obj in geometry.thresholds(engine) for a, b in zip(path, path[1:]) if geometry.crosses(obj, a, b)}
    if ids and owns(engine, mover, STEP):
        mover.turn_flags['boundary_crossed'] = sorted(set(mover.turn_flags.get('boundary_crossed', [])) | ids)


@hook('event')
def physical_threshold_destroyed(engine, event_type, kwargs):
    if event_type != 'OBJECT_UPDATED':
        return
    data = (kwargs.get('payload') or {}).get('object') or {}
    if not data.get('destroyed') or data.get('object_kind') == MARK_KIND:
        return
    for mark in list(engine.state.objects.values()):
        if not mark.destroyed and mark.object_kind == MARK_KIND and mark.component.get('threshold_id') == data.get('object_id'):
            engine._update_object(mark.model_copy(update={'destroyed': True}), MARK, mark.owner_id)


@hook('empty_action_implemented')
def mapped_mark_action(action, info):
    return True if action.parameters.get('boundary_passage') in {'witnessing', 'invited', 'refusing'} else None


@hook('turn_start')
def remember_start_thresholds(engine, actor):
    if owns(engine, actor, STEP) and geometry.thresholds(engine):
        actor.turn_flags['boundary_adjacent_at_start'] = [
            obj.object_id for obj in geometry.thresholds(engine)
            if engine.grid.distance_ft(actor.position, obj.position) <= 5]
