"""Shared optional movement for rider effects and steal_momentum, including off-turn steps.

Use native granted movement: paths, altitude, footprints, difficult terrain,
hazards and opportunity attacks stay real. The triggering creature is exempt;
no_oa rows exempt every creature. Ordinary movement and Reaction flags are not
borrowed or rewritten. Scaling, Bite and after-attack riders share this adapter.

Two optional row keys name what set the step off, for a printed line that grants it from a Reaction or
another trigger: ``trigger`` is the plain-words phrase that replaced the step's own name in the
question ("after the melee attack that missed you"), and ``no_oa_from_target`` says out loud that only
the triggering creature's opportunity attack is suppressed (which is what a row without ``no_oa``
already does).  Both change only the question a player is asked; neither changes what moves, and a
row using neither behaves exactly as before.

``toward_id`` (a creature id) is the general "toward it" of a printed step: only
squares that end no farther from that creature than the actor's own square are
offered, so "move 5 feet toward the creature that entered your reach" (Unyielding
Advance) cannot be spent walking away from it. Without it every square within the
distance is offered, exactly as before.
"""
from typing import Any

from . import effect, hook
from .rider_helpers import cell_choice_id, effect_rows


@hook("mark_spent")
def consumed(ctx: Any, name: str, subject: Any) -> None:
    if name.lower() == "bite":
        ctx.damage_cache['_rider_bite_consumed'] = subject.entity_id


def _closer(engine: Any, actor: Any, candidate: Any, toward_id: str) -> bool:
    """Whether a destination keeps this creature no farther from ``toward_id`` than its own square is: "toward it" may not
    be spent walking away.  A creature that is already adjacent can be followed (there is no closer square than its own),
    which is the ordinary reading of "move 5 feet toward the creature that entered your reach"."""
    toward = engine.state.actors.get(str(toward_id))
    if toward is None:
        return True  # the creature it stepped toward is gone: ordinary movement
    return engine.grid.distance_ft(candidate.destination, toward.position) <= engine.grid.distance_ft(actor.position, toward.position)


@effect("rider_step")
def step(ctx: Any, row: dict[str, Any]) -> None:
    from . import any_false, needle

    engine, actor = ctx.engine, ctx.actor
    if row.get('after_attack'):
        ctx.damage_cache.setdefault('_rider_pending_steps', []).append((ctx.target.entity_id if ctx.target else None, row))
        return
    if not actor.active or ctx.intent is None:
        return
    cl = int(ctx.numbers.get('cl') or 1)
    feet = next((int(value) for low, high, value in row.get('distance_by_cl') or [] if low <= cl <= high),
                int(row.get('distance_ft') or 0))
    if row.get('after_bite_ft') and ctx.target is not None and ctx.damage_cache.get('_rider_bite_consumed') == ctx.target.entity_id:
        feet = int(row['after_bite_ft'])
    from .. import granted_movement
    candidates = granted_movement.candidates(engine, actor, feet, ctx.intent, ctx.source)
    options = {key.replace('step:', 'cell:', 1): c for key, c in candidates.items()
               if c.destination != actor.position and not any_false('candidate_allowed', engine, actor, c, None)}
    toward_id = str(row.get('toward_id') or '')
    if toward_id and options:
        options = {key: candidate for key, candidate in options.items() if _closer(engine, actor, candidate, toward_id)}
    if not options:
        return
    stay = cell_choice_id(actor.position)
    labels = {stay: f'Stay where you are at {actor.position.z * 5} feet altitude; no movement'}
    for key, candidate in options.items():
        position = candidate.destination
        mode = 'Fly' if candidate.metadata.get('movement_mode') == 'fly' else 'Walk'
        labels[key] = (f'{mode} to {position.x},{position.y} at {position.z * 5} feet altitude '
                       f'({candidate.movement_cost_ft} feet of movement)')
    # What set the step off, in rules words: a Reaction names the action that triggered it instead of
    # repeating its own name, so the prompt names the ability, the triggering action and the creature.
    # combat/ext/trigger_source supplies the action actually in flight (and who used it) -- the accepted
    # candidate, else an attack inside the resolution being answered right now, never an earlier turn's;
    # the row's own phrase is kept and the action is added beside it, so a row that names the printed
    # reaction still says so. On the user's own turn no other creature's action is in flight, so the step
    # keeps its own name exactly as before.
    from . import trigger_source

    trigger = trigger_source.described(ctx, str(row.get('trigger') or ''),
                                       label=str(row.get('label') or ctx.action.display_name)) or ctx.action.display_name
    # A step is exempt from the triggering creature's Opportunity Attack unless the row says otherwise,
    # so ``no_oa_from_target`` only says so out loud; ``no_oa`` exempts everyone and is unchanged.
    exempt = (' No opportunity attacks are provoked.' if row.get('no_oa')
              else (f" {ctx.target.display_name} cannot make an Opportunity Attack against you because of this step."
                    if row.get('no_oa_from_target') and ctx.target else ''))
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, 'RIDER_STEP', ctx.source), actor,
        'choice:needle.rider_step', list(labels), labels=labels, preferred=[stay], allow_decline=True,
        prompt=f"{row.get('label') or ctx.action.display_name}: after {trigger}"
               f" against {ctx.target.display_name if ctx.target else actor.display_name},"
               f" {actor.display_name} may move up to {feet} feet ({feet // 5} square{'' if feet // 5 == 1 else 's'})"
               + (f" toward {engine.state.actors[toward_id].display_name}"
                  if toward_id and toward_id in engine.state.actors else "")
               + ". No extra action, resource or ordinary movement is spent."
               + exempt,
        name=row.get('label') or ctx.action.display_name,
        target_id=ctx.target.entity_id if ctx.target else actor.entity_id)
    if chosen and chosen[0] in options:
        ignored = tuple(engine.state.actors) if row.get('no_oa') else ((ctx.target.entity_id,) if ctx.target else ())
        engine._resolve_movement(actor, options[chosen[0]], ctx.intent, granted_ft=feet, ignore_oa_from=ignored)

@hook('technique_used')
def after_riders(ctx: Any) -> None:
    from dataclasses import replace

    for target_id, row in ctx.damage_cache.pop('_rider_pending_steps', []):
        target = ctx.engine.state.actors.get(target_id)
        step(replace(ctx, targets=[target] if target else [], target=target), {**row, 'after_attack': False})
    ctx.damage_cache.pop('_rider_bite_consumed', None)


@hook('after_hit')
def step_after_a_finishing_hit(ctx: Any, target: Any, kind: str) -> None:
    # The core omits the target's on-hit effects once it is defeated. Splitting
    # Step is the attacker's benefit and still applies to that successful hit.
    if target.active:
        return
    for row in effect_rows(ctx.typed.get('effects') or []):
        if row.get('type') == 'rider_step' and row.get('after_attack'):
            ctx.damage_cache.setdefault('_rider_pending_steps', []).append((target.entity_id, row))
