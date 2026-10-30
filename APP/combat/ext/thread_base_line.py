"""Draw the Line's Guide benefit, using existing native attack/mark seams.

Only a hit by the owned, compiled Guide option creates the grant. The ordinary
marker clock expires it at the end of the source's next turn. Cover queries are
pure; the next actual attack roll against this target consumes it even on a
miss or when there was no half cover. Other attackers and targets are inert.
Listen reuses the canonical maintained creature/object lines for one chosen
private reading or consumed check. Physical handling, movement and line
destruction come from native actions/events; missing facts remain unknown.
Stock preparation remains with Spool and Strand.

Shared native Thread consumers: thread_weaving.object_line_actions adapts the
canonical Guide option through the generic object attack lifecycle; thread_common
owns the source-scoped line identities and geometry read by Listen and Snaring
Crossing. This module owns the Thread provider hooks and does not expose private
state to other plug-ins.
"""
from . import hook, effect
from .condition_ownership import refresh_owned, remove_instance
from .thread_common import mark_condition_id, maintained_lines, line_origin

DRAW = "THREAD_BASE_DRAW_THE_LINE"
GUIDE = "Thread Guide"


def grants(target, owner_id):
    """Source-owned Guide instances; shared by cover and roll consumption."""
    cid = mark_condition_id(owner_id, GUIDE)
    return [(iid, c) for iid, c in target.conditions.items()
            if c.condition_id == cid and c.source_actor_id == owner_id]


@hook("after_hit")
def guide_hit(ctx, target, kind):
    if ctx.typed.get("option_of") != DRAW or ctx.typed.get("option_label") != "Guide":
        return
    if not target.active:
        return
    cid = mark_condition_id(ctx.actor.entity_id, GUIDE)
    refresh_owned(ctx.engine, target, cid, ctx.actor.entity_id, ctx.source)
    ctx.engine._apply_condition(target, cid, ctx.source, ctx.actor.entity_id,
        expires_on="END_OF_MARKER_NEXT_TURN",
        data={"marker_turn": int(ctx.actor.turns_started),
              "label": f"Draw the Line — Guide: {ctx.actor.display_name}'s next attack against "
                       f"{target.display_name} ignores half cover until the end of their next turn (no extra cost)."})


@hook("cover_reduction")
def guide_cover(engine, attacker, target, cover):
    # Three-quarters and total cover are outside the printed benefit.
    return 1 if cover == 2 and grants(target, attacker.entity_id) else None


@hook("event", nested=True)
def consume_guide(engine, event_type, kwargs):
    if event_type != "ATTACK_ROLLED":
        return
    owner_id = kwargs.get("actor_id")
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is not None:
            for iid, _condition in grants(target, owner_id):
                remove_instance(engine, target, iid, kwargs.get("source_definition_id") or DRAW)

# Listen Through Tension shares this provider with Draw's canonical line marks.
LISTEN = 'THREAD_BASE_LISTEN_THROUGH_TENSION'
LISTENING = 'condition:typed.thread_listen'
CHECKS = {'Insight': 'WIS', 'Perception': 'WIS', 'Sleight of Hand': 'DEX'}



def listening_grants(owner):
    """Owned primitive receipts; presentation and check consumers share this query."""
    return [(iid, c) for iid, c in owner.conditions.items()
            if c.condition_id == LISTENING and c.source_actor_id == owner.entity_id]


def line_target_name(target):
    """One creature/object name for Listen, its check chooser and readings."""
    return (getattr(target, 'display_name', None)
            or (getattr(target, 'component', None) or {}).get('name') or 'object')


@hook('compile_action')
def listen_action(action, info):
    from .ability_source import mechanic_of
    if mechanic_of(action) != LISTEN or LISTEN not in info['owned_ids'] or action.parameters.get('thread_line_check'):
        return None
    typed = {**action.parameters['typed'], 'effects': [{'type': 'thread_listen'}], 'riders': []}
    return action.model_copy(update={'target_kind': 'SELF', 'range_ft': None,
        'parameters': {**action.parameters, 'typed': typed}})


@hook('compile_actions')
def listen_checks(info):
    if LISTEN not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    from ..factory_compiler import _skill_bonus
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.thread_line_check",
        owner_id=info['actor_id'], display_name='Check involving your Thread Line',
        economy='ACTION', resolution_kind='TYPED', target_kind='SELF', parameters={
            'thread_line_check': 1,
            'description': 'Action, no CP: choose Insight, Perception or Sleight of Hand involving one of your maintained Thread Lines. Listen Through Tension can help one such check.',
            'typed': {'source': LISTEN, 'numbers': dict(info['numbers']), 'riders': [],
                'effects': [{'type': 'contextual_check', 'scope': 'maintained_thread_line',
                    'checks': {s: {'ability': a, 'bonus': _skill_bonus(info['owner_sheet'], s, info['mods'].get(a, 0))}
                               for s, a in CHECKS.items()}}]}})]


@hook('candidate_allowed')
def listen_gate(engine, actor, candidate, action):
    from .ability_source import mechanic_of
    if action is None or mechanic_of(action) != LISTEN:
        return None
    return bool(maintained_lines(engine, actor))


@effect('thread_listen', harmful=False)
def listen(ctx, row):
    from .needle import ask, checkpoint_id
    lines = maintained_lines(ctx.engine, ctx.actor)
    if not lines:
        raise ValueError('Listen Through Tension needs an active Thread Line you maintain.')
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'listen_line', ctx.source), ctx.actor,
        'choice:needle.listen_line', [iid for iid, _, _, _ in lines],
        labels={iid: 'Line to ' + line_target_name(t)
                for iid, t, _, _ in lines}, name='Listen Through Tension', feature_id=LISTEN,
        prompt='Listen Through Tension: choose one Thread Line you maintain. Bonus Action, no CP.')
    if not selected:
        return
    iid, target, holder, line = next(r for r in lines if r[0] == selected[0])
    benefit = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'listen_benefit', ctx.source), ctx.actor,
        'choice:needle.listen_benefit', ['motion', 'handling', 'check'],
        labels={'motion': 'Know whether the target moves closer, farther away, or stays still',
                'handling': 'Know whether the target holds, cuts, or ignores the line',
                'check': 'Gain Advantage on one eligible check involving the line'},
        name='Listen Through Tension', feature_id=LISTEN,
        prompt=f'Listen Through Tension: choose one benefit for {line_target_name(target)}. Bonus Action, no CP.')
    if not benefit:
        return
    choice = benefit[0]
    # Invisible-space knowledge is an additional printed benefit.
    space_connection = (hasattr(target, 'entity_id')
        and line.data.get('thread_medium') in ('mundane', 'qi')
        and any(c.condition_id == 'condition:typed.invisible' for c in target.conditions.values()))
    ctx.engine._apply_condition(ctx.actor, LISTENING, ctx.source, ctx.actor.entity_id,
        expires_on='END_OF_MARKER_NEXT_TURN',
        data={'line_id': iid, 'benefit': choice, 'marker_turn': int(ctx.actor.turns_started),
              'label': 'Listen Through Tension: one chosen benefit for ' + line_target_name(target)})
    if space_connection:
        ctx.engine._apply_condition(ctx.actor, LISTENING, ctx.source, ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED',
            data={'line_id': iid, 'benefit': 'space', 'marker_turn': int(ctx.actor.turns_started),
                  'label': 'Listen Through Tension: invisible connected creature space'})


@hook('contextual_check_subjects')
def line_check_subjects(ctx, spec):
    if spec.get('scope') != 'maintained_thread_line':
        return None
    # A creature line's check is against that creature; an object line names none.
    return {iid: {'label': 'Line to ' + line_target_name(t), 'against': getattr(t, 'entity_id', None)}
            for iid, t, _, _ in maintained_lines(ctx.engine, ctx.actor)}


@hook('contextual_check_modes')
def line_check_mode(engine, actor, frame):
    if frame['scope'] != 'maintained_thread_line' or CHECKS.get(frame['skill']) != frame['ability']:
        return None
    ids = {iid for iid, _, _, _ in maintained_lines(engine, actor)}
    return 'ADVANTAGE' if frame['subject'] in ids and any(
        c.data.get('benefit') == 'check' and c.data.get('line_id') == frame['subject']
        for _, c in listening_grants(actor)) else None


@hook('state_event')
def listen_lifecycle(engine, event):
    if not any(listening_grants(owner) for owner in engine.state.actors.values()):
        return
    for owner in engine.state.actors.values():
        lines = {iid for iid, _, _, _ in maintained_lines(engine, owner)}
        check_consumed = False
        for iid, c in listening_grants(owner):
            frame = event.payload.get('check_context') or {}
            consumed = (not check_consumed and event.event_type == 'CHECK_ROLLED' and event.actor_id == owner.entity_id
                and c.data.get('benefit') == 'check' and frame.get('scope') == 'maintained_thread_line'
                and frame.get('subject') == c.data.get('line_id') and CHECKS.get(event.payload.get('skill')) == event.payload.get('ability'))
            if c.data.get('line_id') not in lines:
                remove_instance(engine, owner, iid, c.source_definition_id)
            elif consumed:
                # The check is spent, but retain physical-line eligibility for
                # the separate Invisible clause until this line ends.
                # Pass the expiry through the recorded update: a direct assignment
                # would change state without a CONDITION_UPDATED event, and replay
                # would then fail to reproduce the committed post-state.
                engine._update_condition_data(owner, c, {**c.data, 'benefit': 'space_eligible',
                    'label': 'Listen Through Tension: invisible connected-space eligibility'},
                    c.source_definition_id, expires_on='UNTIL_REMOVED')
            check_consumed = check_consumed or consumed
    # If the connected creature becomes Invisible while the timed Listen
    # reading is active, preserve the separately printed space knowledge until
    # this physical line ends.
    if event.event_type == 'CONDITION_APPLIED' and (event.payload or {}).get('condition_id') == 'condition:typed.invisible':
        invisible_ids = set(event.target_ids)
        for owner in engine.state.actors.values():
            live = {iid: (target, line) for iid, target, _, line in maintained_lines(engine, owner)
                    if getattr(target, 'entity_id', None) in invisible_ids
                    and line.data.get('thread_medium') in ('mundane', 'qi')}
            for _, grant in listening_grants(owner):
                iid = grant.data.get('line_id')
                pair = live.get(iid)
                if (grant.data.get('benefit') in ('motion', 'handling', 'check', 'space_eligible') and pair
                        and not any(c.data.get('benefit') == 'space' and c.data.get('line_id') == iid
                                    for _, c in listening_grants(owner))):
                    ctx_source = grant.source_definition_id
                    engine._apply_condition(owner, LISTENING, ctx_source, owner.entity_id,
                        expires_on='UNTIL_REMOVED',
                        data={'line_id': iid, 'benefit': 'space',
                              'marker_turn': int(owner.turns_started),
                              'label': 'Listen Through Tension: invisible connected creature space'})


@hook('personal_location')
def listen_space(engine, viewer, target):
    # Exact native physical connections only. This intentionally supplies no
    # sight, public/team observation, identity discovery or other viewer benefit.
    if not any(c.condition_id == 'condition:typed.invisible' for c in target.conditions.values()):
        return None
    lines = {iid for iid, t, _, c in maintained_lines(engine, viewer)
             if getattr(t, 'entity_id', None) == target.entity_id and c.data.get('thread_medium') in ('mundane', 'qi')}
    return True if any(c.data.get('benefit') == 'space' and c.data.get('line_id') in lines
                       for _, c in listening_grants(viewer)) else None


@hook('private_information')
def listen_information(engine, viewer):
    lines = {iid: (target, c) for iid, target, _, c in maintained_lines(engine, viewer)}
    rows = []
    for _, grant in listening_grants(viewer):
        pair = lines.get(grant.data.get('line_id'))
        if pair is None:
            continue
        target, line = pair
        benefit = grant.data['benefit']
        details = {}
        if benefit in ('motion', 'handling', 'check'):
            if benefit == 'motion':
                details['motion'] = line.data.get('thread_motion', 'unknown')
            elif benefit == 'handling':
                details['handling'] = line.data.get('thread_handling', 'unknown')
            elif benefit == 'check':
                details['check_available'] = 1
        elif benefit == 'space' and hasattr(target, 'entity_id') and listen_space(engine, viewer, target):
            details['position'] = target.position.model_dump(mode='json')
        if details:
            name = line_target_name(target)
            ending = 'this turn' if viewer.turns_started > int(grant.data['marker_turn']) else 'your next turn'
            if 'motion' in details or 'handling' in details:
                words = {'closer': 'moving closer', 'farther': 'moving farther away',
                         'still': 'staying still', 'unknown': 'with no known movement'}
                handling = details.get('handling', 'unknown')
                if 'motion' in details:
                    text = f'{name} is {words[details["motion"]]}.'
                else:
                    text = f'{name} is {handling if handling != "unknown" else "handling of the line is unknown"}.'
            elif 'check_available' in details:
                text = (f'You have Advantage on one Wisdom (Insight), Wisdom (Perception), or '
                        f'Dexterity (Sleight of Hand) check involving this line until the end of {ending}.')
            else:
                text = f'{name}: you know its space without seeing it, until the line ends.'
            if 'position' in details:
                p = target.position
                text += f' It occupies space ({p.x + 1}, {p.y + 1}), {p.z * 5} feet high.'
            rows.append({'source': LISTEN, 'title': 'Listen Through Tension', 'text': text,
                         'line_id': line.instance_id, 'benefit': benefit, **details})
    return rows or None


@hook('presentation_hidden_conditions')
def hide_listen(engine, actor):
    return [iid for iid, _ in listening_grants(actor)]


@hook('mark_applied')
def physical_line_provenance(ctx, name, subject):
    from .ability_source import mechanic_of
    if name != 'Thread Line' or mechanic_of(ctx.action) != DRAW:
        return
    twin = ctx.action.parameters.get('thread_twin') or {}
    from ..action_geometry import record_for
    origin = record_for(ctx.engine, ctx.actor, ctx.source)
    anchor_id = origin['id'] if origin else ctx.actor.entity_id
    for c in subject.conditions.values():
        if c.condition_id == mark_condition_id(ctx.actor.entity_id, 'Thread Line') and c.source_actor_id == ctx.actor.entity_id:
            ctx.engine._update_condition_data(subject, c, {**c.data,
                'thread_medium': 'qi' if twin.get('qi') else 'mundane', 'thread_anchor': anchor_id,
                'thread_motion': 'still', 'thread_handling': 'unknown'}, ctx.source)
            from .thread_common import materialize_mundane_line
            materialize_mundane_line(ctx, subject, c)


@hook('movement_landed')
def line_motion(engine, mover, previous, destination, intent, forced):
    # Only the connected target's actual landed movement establishes this fact.
    # Unknown external motion remains unknown; source movement alone does not
    # assert that the connected target is moving.
    for owner in engine.state.actors.values():
        for _, target, holder, c in maintained_lines(engine, owner):
            if getattr(target, 'entity_id', None) != mover.entity_id:
                continue
            anchor = line_origin(engine, owner, c)
            if anchor is None:
                continue
            before = engine.grid.distance_ft(anchor.position, previous)
            after = engine.grid.distance_ft(anchor.position, destination)
            motion = 'closer' if after < before else 'farther' if after > before else 'unknown'
            engine._update_condition_data(holder, c, {**c.data, 'thread_motion': motion,
                'thread_motion_turn_actor': str(engine.state.current_actor_id or '')}, c.source_definition_id)

HANDLING = 'condition:typed.thread_handling'


def incoming_lines(engine, actor):
    """Actual connections on this creature, irrespective of either side's team."""
    return [(owner, iid, holder, line) for owner in engine.state.actors.values()
            for iid, target, holder, line in maintained_lines(engine, owner)
            if getattr(target, 'entity_id', None) == actor.entity_id]


@hook('match_start')
def line_handling_actions(engine):
    from ..gate2_runtime_models import ActionDefinition
    from .ability_source import mechanic_of
    if not any(mechanic_of(action) == DRAW for action in engine.action_catalog.values()):
        return
    for stance in ('holding', 'ignoring'):
        source = 'action:system.thread_line.handling.' + stance
        engine.action_catalog[source] = ActionDefinition(source_definition_id=source,
            owner_id='*', display_name='Thread Line: ' + stance,
            economy='NONE', resolution_kind='TYPED', target_kind='SELF', parameters={
                'thread_response': stance, 'free_primary': True,
                'description': ('No action or CP: hold a physically connected Thread Line in a free hand.' if stance == 'holding'
                                else 'No action or CP: release your hold and ignore one physically connected Thread Line.'),
                'typed': {'effects': [{'type': 'thread_line_handling', 'stance': stance}], 'numbers': {}, 'riders': []}})


@hook('additional_actions')
def offer_line_handling(engine, actor):
    if not incoming_lines(engine, actor):
        return []
    return [source for source in engine.action_catalog if source.startswith('action:system.thread_line.handling.')]


@hook('candidate_allowed')
def line_handling_gate(engine, actor, candidate, action):
    if action is None or not action.parameters.get('thread_response'):
        return None
    if not incoming_lines(engine, actor):
        return False
    if action.parameters['thread_response'] == 'holding':
        from .hand_occupancy import free_hands
        return bool(free_hands(engine, actor))
    return None


@effect('thread_line_handling', harmful=False)
def handle_line(ctx, spec):
    from .needle import ask, checkpoint_id
    from .hand_occupancy import free_hands
    incoming = incoming_lines(ctx.engine, ctx.actor)
    ids = [iid for _, iid, _, _ in incoming]
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'handle_line', ctx.source), ctx.actor,
        'choice:needle.handle_line', ids,
        labels={iid: 'Connected line from ' + owner.display_name for owner, iid, _, _ in incoming},
        name='Thread Line', prompt='Choose the physical line you are holding or ignoring. No action or CP.')
    if not picked:
        return
    _, iid, holder, line = next(r for r in incoming if r[1] == picked[0])
    for key, c in list(ctx.actor.conditions.items()):
        if c.condition_id == HANDLING and c.data.get('line_id') == iid:
            remove_instance(ctx.engine, ctx.actor, key, ctx.source)
    data = {'line_id': iid, 'stance': spec['stance'], 'label': 'Handling a connected Thread Line'}
    if spec['stance'] == 'holding':
        hands = free_hands(ctx.engine, ctx.actor)
        if not hands:
            raise ValueError('Holding a Thread Line needs a free hand. Release a hold or stow an item first.')
        data['hand'] = hands[0]
    ctx.engine._apply_condition(ctx.actor, HANDLING, ctx.source, ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED', data=data)
    ctx.engine._update_condition_data(holder, line, {**line.data, 'thread_handling': spec['stance']}, ctx.source)


@hook('hand_occupants')
def line_hand_occupants(engine, actor):
    return {c.data['hand']: c.instance_id for c in actor.conditions.values()
            if c.condition_id == HANDLING and c.data.get('stance') == 'holding' and c.data.get('hand')}


@hook('state_event')
def physical_reading_lifecycle(engine, event):
    # Completing the native turn that contained movement stops its landed
    # movement cue, including moved objects and off-turn forced movement.
    # Merely reading menus never changes or guesses a fact.
    holdings = [(actor, key, c) for actor in engine.state.actors.values()
                for key, c in actor.conditions.items() if c.condition_id == HANDLING]
    if holdings:
        valid = {iid for owner in engine.state.actors.values()
                 for iid, _, _, _ in maintained_lines(engine, owner)}
        for actor, key, c in holdings:
            if c.data.get('line_id') not in valid:
                remove_instance(engine, actor, key, c.source_definition_id)
    if event.event_type == 'TURN_ENDED':
        for owner in engine.state.actors.values():
            for _, target, holder, line in maintained_lines(engine, owner):
                turn_actor = line.data.get('thread_motion_turn_actor', getattr(target, 'entity_id', None))
                if turn_actor == event.actor_id and line.data.get('thread_motion') != 'still':
                    engine._update_condition_data(holder, line, {**line.data, 'thread_motion': 'still'}, line.source_definition_id)


def object_line_actions(info, actions):
    """Native object delivery adapters for Draw's non-damaging Guide line.

    Called by thread_weaving.twins after its canonical medium/payment variants
    exist, so this adapter never duplicates Spool's CP or strand policies.
    The generic objects attack lifecycle owns range, LoE, rolls and completion.
    Other Draw options keep their current implementation and scope.
    """
    from copy import deepcopy
    from .ability_source import mechanic_of
    if DRAW not in info['owned_ids']:
        return []
    out = []
    for action in actions:
        typed = action.parameters.get('typed') or {}
        if mechanic_of(action) != DRAW or typed.get('option_label') != 'Guide' or action.parameters.get('thread_twin', {}).get('two'):
            continue
        params = deepcopy(action.parameters)
        attack = next((e for e in params['typed'].get('effects', []) if e.get('type') == 'attack'), None)
        if attack is None:
            continue
        attack.update(object_target='unattended', object_non_damaging=True,
                      object_on_hit_effects=['thread_object_connection'])
        attack['on_hit'].append({'type': 'thread_object_connection'})
        out.append(action.model_copy(update={'source_definition_id': action.source_definition_id + '.connected_object',
            'display_name': action.display_name + ' (at an object)', 'target_kind': 'OBJECT',
            'parameters': params}))
    return out


@effect('thread_object_connection', harmful=False)
def connect_object(ctx, row):
    from ..typed_executor import mark_capacity
    oid = row.get('recipient_object_id')
    obj = ctx.engine.state.objects.get(oid)
    if obj is None or obj.destroyed:
        return
    cid = mark_condition_id(ctx.actor.entity_id, 'Thread Line')
    live = maintained_lines(ctx.engine, ctx.actor)
    for _, target, holder, c in live:
        if getattr(target, 'object_id', None) == oid:
            remove_instance(ctx.engine, holder, c.instance_id, ctx.source)
    cap = mark_capacity(ctx, 'Thread Line')
    from ..mark_limits import reserve_mark_slot
    reserve_mark_slot(ctx.engine, {cid}, cap, ctx.source)
    medium = 'qi' if ctx.action.parameters.get('thread_twin', {}).get('qi') else 'mundane'
    from ..action_geometry import record_for
    origin = record_for(ctx.engine, ctx.actor, ctx.source)
    anchor_id = origin['id'] if origin else ctx.actor.entity_id
    ctx.engine._apply_condition(ctx.actor, cid, ctx.source, ctx.actor.entity_id,
        expires_on='END_OF_MARKER_NEXT_TURN', data={'connected_object_id': oid,
            'thread_medium': medium, 'thread_anchor': anchor_id, 'thread_motion': 'still', 'thread_handling': 'unknown',
            'thread_object_position': obj.position.model_dump(mode='json'),
            'marker_turn': int(ctx.actor.turns_started), 'label': 'Thread Line to ' + (obj.component or {}).get('name', 'object')})
    from .thread_common import materialize_mundane_line
    line = max((c for c in ctx.actor.conditions.values() if c.condition_id == cid and c.data.get('connected_object_id') == oid), key=lambda c: c.applied_sequence)
    materialize_mundane_line(ctx, ctx.actor, line)


@hook('state_event')
def connected_object_lifecycle(engine, event):
    if event.event_type != 'OBJECT_UPDATED':
        return
    from ..gate2_runtime_models import Position
    for owner in engine.state.actors.values():
        for holder in engine.state.actors.values():
            for c in list(holder.conditions.values()):
                oid = c.data.get('connected_object_id')
                if c.condition_id != mark_condition_id(owner.entity_id, 'Thread Line') or not oid:
                    continue
                obj = engine.state.objects.get(oid)
                if obj is None or obj.destroyed:
                    remove_instance(engine, holder, c.instance_id, c.source_definition_id)
                    continue
                previous = c.data.get('thread_object_position')
                if previous and previous != obj.position.model_dump(mode='json'):
                    anchor = line_origin(engine, owner, c)
                    if anchor is None:
                        continue
                    before = engine.grid.distance_ft(anchor.position, Position.model_validate(previous))
                    after = engine.grid.distance_ft(anchor.position, obj.position)
                    engine._update_condition_data(holder, c, {**c.data,
                        'thread_object_position': obj.position.model_dump(mode='json'),
                        'thread_motion_turn_actor': str(engine.state.current_actor_id or ''),
                        'thread_motion': 'closer' if after < before else 'farther' if after > before else 'unknown'}, c.source_definition_id)


@hook('object_target_cells')
def physical_line_cells(engine, obj):
    from .thread_common import line_for_object, line_origin
    from ..gate2_runtime_models import Position
    if (obj.component or {}).get('thread_line') != 1:
        return None
    bound = line_for_object(engine, obj)
    if bound is None:
        return (obj.position,)
    owner, target, _, line = bound
    anchor = line_origin(engine, owner, line)
    if target is None or anchor is None:
        return (obj.position,)
    return tuple(Position(x=x, y=y, z=z) for x, y, z in
                 engine.grid.effect_ray_cells(anchor.position, target.position))


@hook('candidate_allowed')
def physical_line_attack_gate(engine, actor, candidate, action):
    # General Thread Rules permit attacking a visible mundane line adjacent to
    # the attacker. The native object path still checks the same cell's LoE.
    for tid in candidate.target_ids or ():
        obj = engine.state.objects.get(tid)
        if obj is None or (obj.component or {}).get('thread_line') != 1:
            continue
        from .thread_common import line_for_object
        if line_for_object(engine, obj) is None or obj.destroyed:
            return False
        if min(engine._distance_actor_to_cell(actor, cell) for cell in physical_line_cells(engine, obj)) > 5:
            return False
    return None


@hook('state_event')
def physical_line_lifecycle(engine, event):
    from .thread_common import line_for_object
    for obj in list(engine.state.objects.values()):
        if (obj.component or {}).get('thread_line') != 1:
            continue
        bound = line_for_object(engine, obj)
        if obj.destroyed:
            if bound is not None:
                _, _, holder, line = bound
                remove_instance(engine, holder, line.instance_id, event.source_definition_id)
            continue
        if bound is None:
            engine._update_object(obj.model_copy(update={'destroyed': True, 'current_hp': 0}),
                                  event.source_definition_id, obj.owner_id)
            continue
        owner, target, holder, line = bound
        if (event.event_type == 'ATTACK_ROLLED' and obj.object_id in event.target_ids
                and getattr(target, 'entity_id', None) == event.actor_id):
            # An actual attack aimed at this physical line, including a miss,
            # establishes a cutting attempt. Damage is still native object HP.
            for key, held in list(target.conditions.items()):
                if held.condition_id == HANDLING and held.data.get('line_id') == line.instance_id and held.data.get('stance') == 'ignoring':
                    remove_instance(engine, target, key, event.source_definition_id)
            engine._update_condition_data(holder, line, {**line.data, 'thread_handling': 'cutting'}, event.source_definition_id)
        if event.event_type == 'TURN_ENDED' and getattr(target, 'entity_id', None) == event.actor_id and line.data.get('thread_handling') == 'cutting':
            holding = any(held.condition_id == HANDLING and held.data.get('line_id') == line.instance_id
                          and held.data.get('stance') == 'holding' for held in target.conditions.values())
            engine._update_condition_data(holder, line, {**line.data, 'thread_handling': 'holding' if holding else 'unknown'}, event.source_definition_id)


@hook('movement_landed')
def move_physical_line_source(engine, mover, previous, destination, intent, forced):
    from .thread_common import line_for_object, line_origin
    for obj in list(engine.state.objects.values()):
        if obj.destroyed or (obj.component or {}).get('thread_line') != 1:
            continue
        bound = line_for_object(engine, obj)
        if bound is None:
            continue
        owner, _, _, line = bound
        anchor = line_origin(engine, owner, line)
        if getattr(anchor, 'entity_id', None) == mover.entity_id and obj.position != destination:
            engine._update_object(obj.model_copy(update={'position': destination}), line.source_definition_id, owner.entity_id)


@hook('event_audience')
def private_line_history(engine, event):
    from ..private_information import event_value
    payload = event_value(event, 'payload', {}) or {}
    cid = str(payload.get('condition_id') or '')
    prefix = 'condition:typed.mark.thread_line.'
    if event_value(event, 'event_type') == 'CONDITION_UPDATED' and cid.startswith(prefix):
        # Even the maintainer gets only the chosen benefit, through the
        # private_information provider, never all raw line facts at once.
        return ()
    if cid in (LISTENING, HANDLING):
        return tuple(a for a in event_value(event, 'target_ids', ()) if a in engine.state.actors)
    source = str(event_value(event, 'source_definition_id') or '')
    if source.startswith(('action:system.thread_line.handling.', 'choice:needle.listen_', 'choice:needle.handle_line')):
        actor = event_value(event, 'actor_id')
        return (actor,) if actor in engine.state.actors else ()
    return None
