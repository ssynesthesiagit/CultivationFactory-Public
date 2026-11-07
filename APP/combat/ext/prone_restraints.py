"""Source-owned restrictions on standing; two canonical clauses use the seam."""
from . import effect, hook

FALLING_GATE = 'tianxia.talent.pressure_points.falling_gate_seal'
COMMAND = 'tianxia.subpath.qi.kiai_master.feature.commanding_voice'
RESTRAINT = 'condition:typed.cannot_stand'
UNDERSTANDS = 'condition:typed.command_understanding'


def understands(target, speaker):
    """Recorded player/GM confirmation, not inferred from team or creature name."""
    return any(c.condition_id == UNDERSTANDS and c.source_actor_id == speaker.entity_id
               for c in target.conditions.values())


def confirm_understanding(engine, speaker, target):
    """Record explicit language eligibility; current hearing is still checked separately."""
    if not understands(target, speaker):
        engine._apply_condition(target, UNDERSTANDS, COMMAND, speaker.entity_id,
            expires_on='UNTIL_REMOVED', data={'label': f'Understands {speaker.display_name}\'s spoken commands (confirmed)'})


@hook('fight_setup_tasks')
def understanding_tasks(engine):
    from ..alternative_payments import owned
    return [{'actor_id': a.entity_id, 'source_id': COMMAND}
            for a in engine.state.actors.values() if owned(engine, a, COMMAND)] or None


@hook('fight_setup')
def setup_understanding(engine, actor, source, intent):
    if source != COMMAND:
        return None
    from .needle import ask, checkpoint_id
    from ..target_knowledge import actors_for
    targets = list(actors_for(engine, actor))
    ids = ask(engine, intent, checkpoint_id(engine, 'command_understanding', actor.entity_id), actor,
        'choice:needle.command_understanding', [a.entity_id for a in targets],
        labels={a.entity_id: a.display_name for a in targets}, minimum=0, maximum=len(targets),
        automatic=False, allow_decline=True, default='decline', name='Understanding spoken commands', feature_id=COMMAND,
        prompt='Imperial Command: choose creatures already confirmed to understand your spoken commands. '
        'This records language knowledge, costs nothing and does not issue a command. '
        'Hearing and range are checked when you act. Choose none if you do not know; AI never guesses.')
    for aid in ids:
        confirm_understanding(engine, actor, engine.state.actors[aid])
    return True


@hook('ai_candidate_allowed')
def ai_command(engine, actor, candidate, action):
    if action is None or not (action.parameters.get('typed') or {}).get('imperial_kneel'):
        return None
    return bool(candidate.target_ids) and all(
        (target := engine.state.actors[aid]).team_id != actor.team_id and understands(target, actor)
        for aid in candidate.target_ids)


@effect('imperial_kneel')
def resolve_command(ctx, eff):
    from .needle import ask, checkpoint_id
    from ..typed_executor import run_effects, cant_hear
    target = ctx.target or ctx.actor
    if cant_hear(target):
        return
    if not understands(target, ctx.actor):
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'command_understanding', target.entity_id),
            ctx.actor, 'choice:needle.command_understanding', [target.entity_id],
            labels={target.entity_id: 'Confirm understanding and issue Kneel'}, automatic=False,
            allow_decline=True, default='decline', name='Confirm understanding', feature_id=COMMAND,
            prompt=f'Can {target.display_name} understand your spoken command? Confirm only if already established. '
            'Kneel spends 4 Qi: a failed Wisdom save makes it fall Prone and prevents standing through its next turn; '
            'on success it cannot take Reactions until its next turn starts. Declining has no effect; the action cost remains spent.')
        if not picked:
            return
        confirm_understanding(ctx.engine, ctx.actor, target)
    run_effects(ctx, eff['effects'])


@hook('stand_allowed')
def may_stand(engine, actor):
    if any(c.data.get('cannot_stand') is True for c in actor.conditions.values()):
        return False
    return None


@effect('cannot_stand')
def cannot_stand(ctx, eff):
    target = ctx.target or ctx.actor
    ctx.engine._apply_condition(target, RESTRAINT, ctx.source, ctx.actor.entity_id,
        expires_on=eff['expires_on'], data={'cannot_stand': True, 'label': eff['label']})


@hook('compile_block')
def command_block(block, spec, row, numbers):
    if block == 'imperial_kneel':
        return [{**row, 'block': block}]


@hook('compile_actions')
def imperial_kneel(info):
    if COMMAND not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.imperial_command.kneel",
        display_name='Imperial Command: Kneel', owner_id=info['actor_id'], economy=EconomyKind.ACTION,
        resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=60, costs=(('resource:core.qi', 4),),
        parameters={'harmful': True, 'description': 'Choose one creature, including an ally, that can hear and understand you. '
            'Spend 4 Qi: Wisdom save or fall Prone and remain down through its next turn. '
            'On success it cannot take Reactions until its next turn starts.',
            'typed': {'source': COMMAND, 'numbers': info['numbers'], 'requires_hearing': True, 'imperial_kneel': True,
                'duration': {'kind': 'instant'}, 'riders': [], 'effects': [{'type': 'imperial_kneel', 'effects': [{
                    'type': 'save', 'ability': 'wis', 'applies_to': 'target',
                    'on_fail': [
                        {'type': 'condition', 'condition': 'prone', 'applies_to': 'target'},
                        {'type': 'cannot_stand', 'expires_on': 'END_OF_HOLDER_NEXT_TURN',
                         'label': 'Imperial Command: cannot stand until the end of your next turn'}],
                    'on_success': [{'type': 'reaction_denied', 'applies_to': 'target',
                                    'expires_on': 'START_OF_TARGET_NEXT_TURN'}]}]}]}})]
