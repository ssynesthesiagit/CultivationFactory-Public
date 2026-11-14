"""Wall Stunt running, recorded GM creature approval and explicit handholds.

Uses native climbing routes, payment, hazards and reactions. No Fly Speed or
global terrain exemption is granted. Running surfaces and retained grips exist
only for an owner of Athletics' wall_stunt row with the corresponding receipt.
"""
from . import hook, effect
from .athletics import owns
from .needle import ask, checkpoint_id
from ..roof_movement import ClimbSurface

SOURCE = 'TAL_ATHLETICS_WALL_STUNT'
RUN = 'condition:typed.wall_running'
GRIP = 'condition:typed.wall_running_grip'
APPROVAL = 'condition:typed.wall_surface_approval'


def has(actor, condition):
    return any(c.condition_id == condition for c in actor.conditions.values())


def approved(engine, actor):
    from ..dynamic_size import current_category, CATEGORIES
    from ..target_knowledge import can_see
    from ..targeting import line_of_effect
    result = []
    for other in engine.state.actors.values():
        if (other.active and can_see(engine, actor, other) and line_of_effect(engine, actor, target=other)
                and CATEGORIES.index(current_category(engine, other)) >= CATEGORIES.index(current_category(engine, actor)) + 2
                and any(c.condition_id == APPROVAL and c.source_actor_id == actor.entity_id for c in other.conditions.values())):
            result.append(other)
    return result


@hook('climb_surfaces')
def wall_surfaces(engine, actor):
    if not owns(engine, actor, 'wall_stunt') or not (has(actor, RUN) or has(actor, GRIP)):
        return None
    from ..roof_movement import physical_wall_surfaces
    result = list(physical_wall_surfaces(engine, actor))
    if not has(actor, RUN):
        result = [surface for surface in result if surface.handholds]
    for other in approved(engine, actor):
        result.append(ClimbSurface('creature:' + other.entity_id,
            (other.position.z + engine._footprint(other).height_cells) * 5, frozenset(engine._actor_cells(other)),
            bottom_ft=other.position.z * 5))
    return result


@hook('climbing')
def running_capability(engine, actor):
    if owns(engine, actor, 'wall_stunt') and has(actor, RUN):
        return {'climb_without_check': True, 'climb_as_difficult_ground': True}


@hook('compile_actions')
def wall_actions(info):
    if SOURCE not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    rows = []
    for operation, label, target in [('run', 'run up or along a wall', 'SELF'),
            ('approve', 'record GM approval for a creature wall', 'ANY_CREATURE')]:
        typed = {'source': SOURCE, 'numbers': info['numbers'], 'riders': [],
                 'effects': [{'type': 'wall_stunt', 'operation': operation}]}
        if operation == 'approve':
            # The printed approval is an external scene ruling, not the owner's
            # own decision: the table's GM adjudication transport answers it and
            # an automatic seat may never supply it (ext/needle.ask).
            typed['gm_adjudication'] = True
        rows.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.wall_{operation}",
            display_name='Wall Stunt: ' + label, owner_id=info['actor_id'], economy=EconomyKind.NONE,
            resolution_kind='TYPED', target_kind=target, range_ft=5 if operation == 'approve' else None,
            parameters={'typed': typed}))
    return rows


@hook('compile_action')
def wall_action_is_not_an_area(row, info):
    """Printed wall difficulty prices a route; it does not create a terrain zone."""
    typed = row.parameters.get('typed') or {}
    if not any(e.get('type') == 'wall_stunt' for e in typed.get('effects', ())):
        return row
    typed = {key: value for key, value in typed.items() if key != 'zone_spec'}
    return row.model_copy(update={'parameters': {**row.parameters, 'typed': typed, 'expected_damage': 0}})


@hook('candidate_allowed')
def wall_offered(engine, actor, candidate, action):
    effects = ((getattr(action, 'parameters', None) or {}).get('typed') or {}).get('effects', ())
    for row in effects:
        if row.get('type') != 'wall_stunt':
            continue
        if row['operation'] == 'run':
            return False if has(actor, RUN) or engine._effective_speed(actor) <= 0 else None
        from ..dynamic_size import current_category, CATEGORIES
        target = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
        from ..targeting import line_of_effect
        # Offered to every seat, including an automatic one: the printed clause
        # is "with GM approval", so the owner may ask for it and the table's GM
        # answers; execution defers the fact through ask(..., gm_adjudication).
        return None if (target and target not in approved(engine, actor)
            and engine._line_of_sight_actor_to_actor(actor, target) and line_of_effect(engine, actor, target=target)
            and CATEGORIES.index(current_category(engine, target)) >= CATEGORIES.index(current_category(engine, actor)) + 2) else False


@effect('wall_stunt')
def begin(ctx, eff):
    if eff['operation'] == 'approve':
        target = ctx.target
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'wall_approval', target.entity_id), ctx.actor,
            'choice:needle.wall_approval', ['approved'], name='Wall Stunt', feature_id=SOURCE,
            target_id=target.entity_id, labels={'approved': 'The GM approved this creature as a wall'},
            prompt=f'Has the GM approved {ctx.actor.display_name} running on {target.display_name} with Wall Stunt?',
            allow_decline=True, automatic=False, default='decline', gm_adjudication=True)
        if chosen:
            ctx.engine._apply_condition(target, APPROVAL, SOURCE, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
                data={'label': f'Wall Stunt: {ctx.actor.display_name} may run on {target.display_name} like a wall while it '
                      'is at least two sizes larger; doing so provokes its Opportunity Attack.'})
    else:
        ctx.engine._apply_condition(ctx.actor, RUN, SOURCE, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'label': 'Wall Stunt: run up or along walls; walls cost two feet of movement per foot; fall at turn end without a handhold.'})


@hook('movement_attempt')
def creature_wall_opportunity(engine, actor, previous, destination, intent):
    if not owns(engine, actor, 'wall_stunt') or not has(actor, RUN) or destination.z == previous.z == 0:
        return
    from ..movement_steps import context
    if context(engine, actor).get('mode') != 'climb':
        return
    from ..roof_movement import faces
    near = ({face.id for face in faces(engine, actor, previous)}
            & {face.id for face in faces(engine, actor, destination)})
    from .. import typed_reactions
    for other in approved(engine, actor):
        if 'creature:' + other.entity_id not in near:
            continue
        row, _, reach = typed_reactions.opportunity_profile(engine, other)
        if (row and engine._distance_actor_to_actor(other, actor) <= reach
                and typed_reactions.can_use_reaction(engine, other, actor, row)
                and typed_reactions.wants_opportunity_attack(engine, other, actor, intent=intent,
                    consent_display={'actor_id': actor.entity_id, 'target_id': other.entity_id, 'source_id': SOURCE,
                                     'action_name': f'Wall Stunt: {actor.display_name} runs on {other.display_name}'})):
            notice = typed_reactions.opportunity_reaction_notice(engine, other, (actor.entity_id,))
            typed_reactions.open_reaction(engine, row, other, (actor.entity_id,),
                checkpoint_id(engine, 'creature_wall_oa', other.entity_id, actor.entity_id), reaction_notice=notice)
            typed_reactions.opportunity_attack(engine, other, actor, intent, reaction_opened=True, trigger='movement')


@hook('movement_step')
def leaving_grip(engine, actor, previous, destination, intent):
    if has(actor, GRIP):
        from ..falling import supported
        if supported(engine, actor):
            engine._remove_condition(actor, GRIP, SOURCE)


@hook('event', nested=True)
def grip_departure(engine, kind, kwargs):
    if kind not in ('MOVEMENT_COMMITTED', 'ENTITY_DEFEATED', 'SUMMON_DISMISSED'):
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None or not has(actor, GRIP):
        return
    from ..roof_movement import faces
    if (not actor.active or not actor.climbing or (kwargs.get('payload') or {}).get('teleport')
            or not any(getattr(face, 'handholds', False) for face in faces(engine, actor, actor.position))):
        engine._remove_condition(actor, GRIP, SOURCE)


@hook('turn_end')
def running_ends(engine, actor):
    if not owns(engine, actor, 'wall_stunt') or not has(actor, RUN):
        return
    from ..roof_movement import faces
    from ..falling import supported, settle
    if not supported(engine, actor):
        handholds = any(getattr(face, 'handholds', False) for face in faces(engine, actor, actor.position))
        if handholds:
            chosen = ask(engine, getattr(engine, '_active_intent', None),
                checkpoint_id(engine, 'wall_handhold', actor.entity_id), actor,
                'choice:needle.wall_handhold', ['hold'], name='Wall Stunt', feature_id=SOURCE,
                target_id=actor.entity_id, labels={'hold': 'Hold onto the recorded wall handhold; avoid falling'},
                prompt=f'{actor.display_name} ends Wall Stunt on a wall. Hold onto its handhold to avoid falling?',
                automatic=True, allow_decline=True, preferred=['hold'])
            if chosen:
                engine._apply_condition(actor, GRIP, SOURCE, actor.entity_id, expires_on='UNTIL_REMOVED',
                    data={'label': 'Holding a wall handhold; climb or return to supported ground to leave it.'})
    engine._remove_condition(actor, RUN, SOURCE)
    actor.climbing = has(actor, GRIP)
    settle(engine, SOURCE, getattr(engine, '_active_intent', None))


@hook('button_description')
def wall_help(row):
    if any(e.get('type') == 'wall_stunt' for e in ((row.get('parameters') or {}).get('typed') or {}).get('effects', ())):
        return ('Use ordinary movement to run up or along walls, treating them as difficult terrain. Choose your destination '
                'on the map. A creature wall needs recorded GM approval and must be two sizes larger; running on it '
                'provokes its Opportunity Attack. At turn end hold a recorded handhold, reach support, or fall.')
