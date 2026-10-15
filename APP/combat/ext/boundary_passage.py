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


@hook('compile_bundle')
def threshold_route_profile(bundle,info):
    """Threshold Step produces its actual route authority, not a GM power flag."""
    if not any(((action.get('parameters', {}).get('typed') or {}).get('option_of')
                or (action.get('parameters', {}).get('typed') or {}).get('source')) == STEP
               for action in bundle['action_catalog']):
        return None
    from copy import deepcopy
    out = deepcopy(bundle)
    for action in out['action_catalog']:
        typed = action.get('parameters',{}).get('typed') or {}
        if (typed.get('option_of') or typed.get('source')) == STEP:
            typed['passage_authority'] = {**typed.get('passage_authority',{}), 'category':'route',
                'destination_class':'a visible space on the same battlefield', 'anchor_exists':0}
    return out


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


def crossing(engine, mover, start, end, intent, *, teleport=False, forced=False, route=None, threshold_id=None):
    from . import needle
    from ..typed_executor import run_effects
    from ..target_knowledge import located
    crossed = [obj for obj in geometry.thresholds(engine) if
               (obj.object_id == threshold_id if threshold_id is not None else geometry.crosses(obj, start, end))]
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
            # Automatic denial uses a perceived enemy or the actual hostile
            # controller displacing the defender; roster membership is not consent.
            from ..relations import relation, ENEMY
            controller = engine.state.actors.get((route or {}).get('controller_id'))
            defensive_self = (mover is owner and controller is not None and controller is not owner
                              and relation(engine, owner, controller) == ENEMY)
            preferred = ['deny'] if relation(engine, owner, mover) == ENEMY or defensive_self else []
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
                if route and (route['source_cl'] > int(st.numbers(engine, owner).get('cl') or 1)
                              or route.get('category') in ('secret', 'divine', 'tribulation', 'world_route')):
                    # Only the reacting owner receives protected route knowledge.
                    # This Reaction creates no persistent route-closure record.
                    dx, dy = end.x - start.x, end.y - start.y
                    direction = ('north' if dy < 0 else 'south' if dy > 0 else '') + ('east' if dx > 0 else 'west' if dx < 0 else '')
                    from .spiritual_state import read,write
                    import json
                    learned = {'source_direction':route.get('source_direction') or direction or 'at the threshold'}
                    learned.update({key:route[key] for key in ('destination_class','anchor_exists') if key in route})
                    record = read(owner)
                    # The owner learns broad route facts, not a protected
                    # technique/catalog identity embedded in a receipt key.
                    record.setdefault('facts',{}).setdefault(DENY,{})['route_knowledge:' + str(engine.state.event_sequence)] = {
                        'value':json.dumps(learned,sort_keys=True), 'source_cl':int(route['source_cl']),
                        'ruling':'Deny Passage learned these broad properties from the actual crossing before arrival benefits.'}
                    write(engine,owner,record,DENY)
                    needle.ask(engine, intent, needle.checkpoint_id(engine, 'DENY_AUTHORITY', mover.entity_id), owner,
                        'choice:needle.boundary.route_knowledge', ['understood'],
                        labels={'understood': f"Source direction: {route.get('source_direction') or direction or 'at the threshold'}; "
                                f"destination: {route.get('destination_class', 'not yet known')}; "
                                f"Anchor: {'present' if route.get('anchor_exists') == 1 else 'absent' if route.get('anchor_exists') == 0 else 'not recorded'}"},
                        prompt=f'Deny Passage: the stronger route used by {mover.display_name} cannot be permanently closed by this Reaction.',
                        name='Deny Passage', feature_id=DENY)
                if failed:
                    from .spiritual_state import visible_fact
                    from . import forced_destination
                    host_id = visible_fact(engine, owner, mover, mover.entity_id, 'host_id')
                    presence = visible_fact(engine, owner, mover, mover.entity_id, 'presence_kind')
                    if presence not in ('possessing_spirit', 'occupying_spirit'):
                        host_id = None
                    host = engine.state.actors.get(host_id)
                    vessel = engine.state.objects.get(host_id)
                    adjacent = forced_destination.adjacent_spaces(engine, host, occupant=mover) if host is not None else []
                    if vessel is not None and not vessel.destroyed:
                        from ..gate2_runtime_models import Position
                        adjacent = [Position(x=vessel.position.x + x, y=vessel.position.y + y, z=vessel.position.z)
                                    for x in (-1, 0, 1) for y in (-1, 0, 1) if x or y]
                        adjacent = [p for p in adjacent if engine.grid.volume_legal(p, footprint=engine._footprint(mover),
                                    occupied_cells=engine._occupied_volumes_except(mover.entity_id))]
                    choices = ['stop', 'return'] + (['expel'] if adjacent else [])
                    outcome = needle.ask(engine, intent,
                        needle.checkpoint_id(engine, 'DENY_PASSAGE_FAILED_SAVE', mover.entity_id), owner,
                        'choice:needle.boundary.deny_outcome', choices,
                        labels={'stop': 'Stop before crossing (lose the spent movement)',
                                'return': 'Return to the space just before crossing',
                                'expel': 'Force the occupying spirit into the nearest open space beside its host or vessel'},
                        preferred=['stop'], prompt=f'Deny Passage: choose the failed-save result for {mover.display_name}.', name='Deny Passage', feature_id=DENY)
                    run_effects(ctx, [{'type': 'spiritual_pressure', 'applies_to': 'target'}])
                    if route and int(route.get('source_cl', 0)) == int(st.numbers(engine, owner).get('cl') or 1) and route.get('category') in ('route', 'gate', 'artifact', 'formation', 'domain'):
                        if not wins_passage_contest(engine, owner, mover, route, intent):
                            continue
                    if outcome and outcome[0] == 'expel':
                        from ..gate2_runtime_models import Position
                        from .. import zones
                        positions = [Position.model_validate(p) if isinstance(p, dict) else p for p in adjacent]
                        nearest = min(engine.grid.distance_ft(mover.position, p) for p in positions)
                        positions = [p for p in positions if engine.grid.distance_ft(mover.position, p) == nearest]
                        picked = needle.ask(engine, intent, needle.checkpoint_id(engine, 'DENY_EXPEL', mover.entity_id), owner,
                            'choice:needle.boundary.expel_space', [needle.cell_id(p) for p in positions],
                            prompt=f'Deny Passage: choose a nearest open space for {mover.display_name} beside the host or vessel.',
                            name='Deny Passage', feature_id=DENY)
                        destination = next(p for p in positions if needle.cell_id(p) == picked[0])
                        previous = mover.position
                        mover.position = destination
                        engine._append_event('MOVEMENT_COMMITTED', DENY, actor_id=mover.entity_id,
                            payload={'destination': destination.model_dump(mode='json'), 'forced': True, 'cost_ft': 0,
                                     'path': [previous.model_dump(mode='json'), destination.model_dump(mode='json')]})
                        zones.on_moved(engine, mover, previous, destination, forced=True)
                        from .spiritual_state import read, write
                        record = read(mover)
                        record['facts'][mover.entity_id].pop('host_id', None)
                        write(engine, mover, record, DENY)
                    if not teleport and not forced:
                        from ..movement_steps import record_denial
                        record_denial(engine, mover, DENY, owner)
                        mover.movement_remaining_ft = max(0, mover.movement_remaining_ft - engine.grid.square_size_ft)
                    # Stop/return resolve before the next space is entered;
                    # expulsion above has committed its distinct destination.
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


@hook('condition_attempt')
def crossing_incorporeal_lock(ctx, subject, row):
    """The successful-save clause uses the existing native state-attempt seam."""
    if subject is None or str(row.get('condition') or '').lower() != 'incorporeal':
        return None
    if any(c.condition_id == 'condition:typed.boundary_crossing_lock' and c.source_definition_id == DENY
           and (c.data.get('rule') or {}).get('no_incorporeal') for c in subject.conditions.values()):
        return False
    return None


def passage_profile(ctx, authority=None):
    """Public source profile shared by native teleport and spiritual passages.

    Derive defaults from the real activating source. Explicit typed-source
    metadata may describe a printed route; external facts supply only broad
    destination observations, never Source CL or source power.
    """
    from .spiritual_state import fact
    numbers = ctx.numbers
    route = dict(ctx.typed.get('passage_authority') or {})
    route.update(authority or {})
    route.setdefault('controller_id',ctx.actor.entity_id)
    route.setdefault('source_id',ctx.source)
    source = st.feature_of(ctx.action) or ctx.source
    def source_fact(name):
        value = fact(ctx.actor, source, name)
        return value if value is not None else fact(ctx.actor, ctx.source, name)
    profile = ctx.typed.get('activation_profile') or {}
    route.setdefault('source_cl', int(profile.get('source_cl') or numbers.get('cl') or 1))
    route.setdefault('key_mod', int(numbers.get('key_mod') or 0))
    route.setdefault('save_dc', int(numbers.get('save_dc') or 10))
    route.setdefault('category', str(profile.get('source_kind') or 'movement').lower())
    for key in ('destination_class', 'source_direction', 'anchor_exists'):
        value = source_fact(key)
        if value is not None:
            route.setdefault(key, value)
    if route.get('source_cl', 0) and (route['category'] in ('secret', 'divine', 'tribulation', 'world_route')
            or any(route['source_cl'] > int(st.numbers(ctx.engine, a).get('cl') or 1)
                   for a in ctx.engine.state.actors.values() if owns(ctx.engine, a, DENY))):
        route['protected'] = 1
    return route


@hook('subject_teleport_attempt')
def teleporting(ctx, subject, previous, destination):
    """Keep the real source/controller when the passenger is another actor."""
    route = passage_profile(ctx)
    return False if crossing(ctx.engine, subject, previous, destination, ctx.intent, teleport=True,
        forced=None, route=route) else None


@effect('spiritual_crossing')
def spiritual_crossing(ctx, row):
    """A source's semantic/incorporeal passage, before its arrival benefits.

    The source names an existing meaningful threshold, legal destination and
    authority metadata. Deny Passage consumes the same reaction as physical
    movement. No row means no new crossing, relocation or benefit.
    """
    from ..gate2_runtime_models import Position
    from .. import zones
    destination = Position.model_validate(row['destination'])
    subject = ctx.target or ctx.actor
    if not engine_threshold(ctx.engine, row.get('threshold_id')):
        raise ValueError('Spiritual crossing needs an existing meaningful threshold.')
    if not ctx.engine.grid.volume_legal(destination, footprint=ctx.engine._footprint(subject),
            occupied_cells=ctx.engine._occupied_volumes_except(subject.entity_id)):
        return
    source = crossing(ctx.engine, subject, subject.position, destination, ctx.intent,
                      route=passage_profile(ctx, row.get('authority')), threshold_id=row['threshold_id'])
    if source:
        return
    previous = subject.position
    subject.position = destination
    ctx.engine._append_event('MOVEMENT_COMMITTED', ctx.source, actor_id=subject.entity_id,
        payload={'destination': destination.model_dump(mode='json'), 'spiritual_passage': 1, 'cost_ft': 0,
                 'forced': False if subject is ctx.actor else row.get('forced'),
                 'path': [previous.model_dump(mode='json'), destination.model_dump(mode='json')]})
    zones.on_moved(ctx.engine, subject, previous, destination, forced=False)
    from ..typed_executor import run_effects
    run_effects(ctx, row.get('after_crossing') or [])


def engine_threshold(engine, identity):
    return next((obj for obj in geometry.thresholds(engine) if obj.object_id == identity), None)


def wins_passage_contest(engine, denier, mover, route, intent):
    """R7 Boundary Collision: both real controllers roll; a tie stops passage.

    Uncontrolled external authority retains the printed fallback DC. Its absent
    controller is never replaced with the passenger or an invented creature.
    """
    controller = engine.state.actors.get(route.get('controller_id'))
    if controller is not None and controller is not denier:
        from ..typed_executor import resolve_opposed_check
        context = st.context(engine,controller,st.feature_action(engine,denier,DENY),[denier],
                             st.numbers(engine,controller),intent)
        result = resolve_opposed_check(context,denier,
            {'kind':'cultivation','label':'Route authority'},
            {'kind':'cultivation','label':'Deny Passage authority'},
            event_metadata={'boundary_collision':1,'moving_creature_id':mover.entity_id})
        # The route must beat the refusing boundary, so ties leave the mover
        # on its origin side rather than quietly favoring passage.
        return not result.success
    from .ability_source import cultivation_check
    dc = route.get('save_dc')
    if dc is None:
        cl = route['source_cl']
        dc = 10 + (2 + max(0,cl-1)//4) + int(route.get('key_mod',3))
    return cultivation_check(engine,denier,st.numbers(engine,denier),int(dc),DENY)


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
