"""Chain Clone's owned hit and Tether effects on the existing summon chassis."""
from dataclasses import replace
from typing import Any
from . import effect, hook

SOURCE = 'tianxia.talent.chains.chain_clone'


def owner_context(ctx):
    record = ctx.actor.summon or {}
    if record.get('source') != SOURCE or record.get('status') != 'present':
        return None
    owner = ctx.engine.state.actors.get(record.get('owner'))
    return replace(ctx, actor=owner) if owner is not None else None


@effect('chains_clone_slow')
def hooking_links(ctx: Any, row: dict) -> None:
    """The printed duration names the summoner's next turn, not the clone's."""
    from ..typed_executor import run_effects
    from .effect_durations import token
    owned = owner_context(ctx)
    if owned is not None and ctx.target is not None:
        run_effects(owned, [{'type': 'speed', 'applies_to': 'target', 'flat': -5,
                           'expires_on': token('start', owned.actor.entity_id, int(owned.actor.turns_started) + 1)}])


@effect('chains_clone_tether')
def set_tether(ctx: Any, row: dict) -> None:
    """Clone is the physical anchor; the owner supplies DC and expiry."""
    from ..typed_executor import run_effects
    if owner_context(ctx) is None or ctx.target is None:
        return
    payment = tether_payment(ctx.engine, ctx.actor)
    if payment is None or payment[0].resources.get(payment[1], 0) < 1:
        return
    ctx.engine._spend_resource(payment[0], payment[1], 1, ctx.source)
    bound = {'type': 'condition', 'condition': 'bound', 'applies_to': 'target',
             'expires_on': 'START_OF_SOURCE_NEXT_TURN', 'condition_data': {'tether_ft': 30}}
    # Default source-next-turn is the clone here: bind the printed owner's
    # exact upcoming turn while retaining the clone as the tether endpoint.
    from .effect_durations import token
    owner = owner_context(ctx).actor
    bound['expires_on'] = token('start', owner.entity_id,
                                int(owner.turns_started) + 1)
    slow = {'type': 'speed', 'applies_to': 'target', 'flat': -5,
            'expires_on': bound['expires_on']}
    # Willingness belongs to the affected creature, not to a team shortcut.
    # choice_reactors enrolls potential manual recipients for AI-step prompt
    # discovery; Needle leaves AI recipients to automatic choice handling.
    from . import needle
    options = ['accept', 'refuse']
    preferred = ['accept'] if ctx.target.team_id == ctx.actor.team_id else ['refuse']
    decision = needle.ask(ctx.engine, ctx.intent,
        needle.checkpoint_id(ctx.engine, 'CLONE_TETHER_WILLINGNESS', ctx.target.entity_id),
        ctx.target, 'choice:needle.chains_clone_tether_willingness', options,
        labels={'accept': f'Accept {ctx.actor.display_name}\'s Tether',
                'refuse': 'Refuse the Tether'},
        prompt=(f'{ctx.target.display_name}: {owner.display_name}\'s clone offers you a Tether. '
                f'Accepting means you are Bound: your Speed is 10 feet lower, you cannot Dash, '
                f'you have Disadvantage on checks to escape a grapple or other hold, and you cannot '
                f'willingly move more than 30 feet from the clone. It lasts until the start of '
                f'{owner.display_name}\'s next turn. If you refuse, make a Strength save against '
                f'{owner.display_name}\'s Cultivation Save DC; on a failure, those Bound effects apply, '
                f'and on a success your Speed is reduced by 5 feet until then. The clone\'s owner spends '
                f'1 cultivation point; you spend nothing, and answering costs you no action.'),
        preferred=preferred, automatic=True, default='first', name='Set the Tether',
        target_id=ctx.target.entity_id)
    willing = bool(decision and decision[0] == 'accept')
    if willing:
        run_effects(ctx, [bound])
    else:
        run_effects(ctx, [{'type': 'save', 'ability': 'str', 'on_fail': [bound], 'on_success': [slow]}])


@effect('chains_clone_help')
def help_attack(ctx: Any, row: dict) -> None:
    """Ordinary combat Help: distract an adjacent enemy for one perceived ally."""
    from ..target_knowledge import actors_for
    from .rider_choices import pick
    from .effect_durations import token
    from . import note
    if owner_context(ctx) is None or ctx.target is None or ctx.target.team_id == ctx.actor.team_id:
        return
    allies = [a for a in actors_for(ctx.engine, ctx.actor) if a.active
              and a.team_id == ctx.actor.team_id and a.entity_id != ctx.actor.entity_id]
    if not allies:
        return
    allies.sort(key=lambda a: (ctx.engine.grid.distance_ft(a.position, ctx.target.position), a.entity_id))
    ids = [a.entity_id for a in allies]
    chosen = pick(ctx.engine, ctx.actor, 'chains_clone_help', 'Help', ids,
        subject=ctx.target, optional=False, labels={a.entity_id: a.display_name for a in allies},
        preferred=ids[:1], trigger=f'{ctx.actor.display_name} distracts {ctx.target.display_name}',
        choose=f'Choose an ally to gain Advantage on its next attack against that enemy before the start of {ctx.actor.display_name}\'s next turn.',
        prompt_context={'cost': 'The clone uses its Action; no cultivation points.'})
    if not chosen:
        return
    ally = ctx.engine.state.actors[chosen[0]]
    ctx.engine._add_modifier(ally, ctx.source, 'attack_mode_vs', 'SET',
        f'ADVANTAGE:{ctx.target.entity_id}', 'NEXT_ATTACK',
        expires_on=token('start', ctx.actor.entity_id, int(ctx.actor.turns_started) + 1))
    note(ctx.engine, ctx.source, ctx.actor,
         f'Help: {ally.display_name} has Advantage on its next attack against {ctx.target.display_name} before the start of {ctx.actor.display_name}\'s next turn.', targets=[ally])


def tether_payment(engine, clone):
    """The inherited Set the Tether cost uses its summoner's compiled CP pool."""
    from .ability_source import mechanic_of
    record = clone.summon or {}
    if record.get('source') != SOURCE or record.get('status') != 'present':
        return None
    owner = engine.state.actors.get(record.get('owner'))
    if owner is None:
        return None
    ability = next((a for a in engine.action_catalog.values()
                    if a.owner_id == owner.entity_id and mechanic_of(a) == SOURCE and a.costs), None)
    return (owner, ability.costs[0][0]) if ability is not None else None


@hook('candidate_allowed')
def affordable_tether(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not any(e.get('type') == 'chains_clone_tether'
                               for e in (action.parameters.get('typed') or {}).get('effects') or []):
        return None
    payment = tether_payment(engine, actor)
    return False if payment is None or payment[0].resources.get(payment[1], 0) < 1 else None


@hook('button_description')
def tether_description(row: dict) -> str | None:
    if not any(e.get('type') == 'chains_clone_tether'
               for e in ((row.get('parameters') or {}).get('typed') or {}).get('effects') or []):
        return None
    return ('Set the Tether: the clone uses its Action and spends 1 of your cultivation points. '
            'The target chooses whether to accept. Acceptance binds it without a save; refusal calls for a '
            'Strength save against your Cultivation Save DC. On a failed save, it is Bound: Speed is 10 feet '
            'lower, it cannot Dash, has Disadvantage on checks to escape a grapple or other hold, and cannot '
            'willingly move more than 30 feet from the clone. On a successful save, Speed is reduced by 5 feet. '
            'The effect ends at the start of your next turn.')


@hook('choice_reactors')
def tether_consent_reactors(engine: Any) -> tuple[str, ...] | None:
    """Potential manual recipients for a Chain Clone consent prompt.

    If an AI step reaches this effect, the service can pause for player-controlled
    recipients and handles AI recipients automatically. No Clone feature means
    nobody opts in.
    """
    if not any((action.parameters.get('typed') or {}).get('source') == SOURCE
               or any(effect.get('type') == 'chains_clone_tether'
                      for effect in ((action.parameters.get('typed') or {}).get('effects') or []))
               for action in engine.action_catalog.values()):
        return None
    return tuple(actor.entity_id for actor in engine.state.actors.values() if actor.active)
