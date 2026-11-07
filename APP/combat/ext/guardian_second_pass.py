"""Guardian second pass: opt-in Adamant Guardian clauses.

Adamant's reviewed effect stamps a separate state; predecessor saved bundles retain their old interpreter.
Shelter eligibility is allies other than self, within 20 feet and perceived by
its owner. The native grouped next-resistance modifiers cover all damage types on one hit that
actually hurts the ally; owner-next-start expiry survives cold service reload.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .needle import ask, checkpoint_id

ADAMANT = 'TAL_GUARDIAN_ADAMANT_GUARDIAN_INCARNATION'
STATE = 'adamant_guardian_second_pass'
TYPES = ('acid', 'bludgeoning', 'cold', 'fire', 'force', 'lightning',
         'necrotic', 'piercing', 'poison', 'psychic', 'radiant', 'slashing', 'thunder')


@effect('guardian_adamant')
def adamant(ctx: Any, eff: dict[str, Any]) -> None:
    from .states import state
    state(ctx, {'type': 'state', 'name': STATE, 'applies_to': 'self', 'duration': 'one_minute',
                'label': 'Adamant Guardian: +5 feet melee reach; may refuse pushes and pulls; Shelter allies at the start of each turn'})


def live(engine: Any, actor: Any):
    from .states import active
    from .effect_durations import due
    condition = active(engine, actor, STATE)
    return condition if condition and not due(engine, condition.expires_on) else None


@hook('choice_reactors')
def adamant_choice_owners(engine: Any) -> tuple[str, ...]:
    """Enroll only active Adamant holders; their free consent choices belong to them."""
    return tuple(sorted(actor.entity_id for actor in engine.state.actors.values()
                        if actor.active and live(engine, actor)))


@hook('attack_reach_bonus')
def adamant_reach(engine: Any, actor: Any, action: Any, opportunity: bool):
    condition = live(engine, actor)
    if condition:
        return {'source_id': condition.source_definition_id, 'feet': 5, 'condition_id': condition.instance_id}
    return None


@hook('forced_movement_restriction')
def adamant_refusal(ctx: Any, subject: Any, eff: Any, maximum_ft: int):
    if not live(ctx.engine, subject):
        return None
    from .choice_prompt import action_context
    allowed = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'ADAMANT_MOVE', ctx.source, subject.entity_id, ctx.actor.entity_id),
                  subject, 'choice:needle.guardian_adamant_movement', ['refuse', 'allow'],
                  labels={'refuse': 'Refuse the forced movement', 'allow': 'Willingly allow the forced movement'},
                  prompt=f'Adamant Guardian: {subject.display_name} is immune to this forced movement '
                         'unless you willingly allow it. Choose whether to remain here. No cost.',
                  name='Adamant Guardian: forced movement', feature_id=ADAMANT,
                  target_id=subject.entity_id,
                  prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, subject))
    permitted = allowed == ['allow']
    note(ctx.engine, ADAMANT, subject,
         f'Adamant Guardian: {subject.display_name} ' + ('allows' if permitted else 'refuses') + ' this push or pull.',
         (subject.entity_id,))
    return None if permitted else 0


@hook('turn_boundary_start')
def shelter(engine: Any, guardian: Any) -> None:
    condition = live(engine, guardian)
    if not condition or not guardian.active:
        return
    from .. import stealth
    from ..targeting import line_of_effect
    from .effect_durations import token
    allies = sorted((a for a in engine.state.actors.values() if a.active
                     and a.entity_id != guardian.entity_id and a.team_id == guardian.team_id
                     and engine._distance_actor_to_actor(guardian, a) <= 20
                     and stealth.sees(engine, guardian, a) and line_of_effect(engine, guardian, target=a)), key=lambda a: a.entity_id)
    ids = [a.entity_id for a in allies]
    picks = ask(engine, None, f'ADAMANT_SHELTER:{guardian.entity_id}:{guardian.turns_started}', guardian,
                'choice:needle.guardian_adamant_shelter', ids,
                labels={a.entity_id: f'{a.display_name}: resist the first damage instance before your next turn' for a in allies},
                prompt=f'Shelter the Weak: choose up to {guardian.proficiency_bonus} allies within 20 feet. '
                       'Each resists its first damage instance until the start of your next turn. No cost.',
                name='Adamant Guardian: Shelter the Weak', feature_id=ADAMANT,
                minimum=0, maximum=max(0, int(guardian.proficiency_bonus)), allow_decline=True,
                default_count=max(0, int(guardian.proficiency_bonus)))
    expiry = token('start', guardian.entity_id, guardian.turns_started + 1)
    source = ADAMANT + '#shelter'
    for aid in picks:
        subject = engine.state.actors[aid]
        for kind in TYPES:
            engine._add_modifier(subject, source, 'damage_resistance_next', 'SET', kind.upper(), 'ALWAYS',
                                 expires_on=expiry)
        note(engine, ADAMANT, guardian, f'Shelter the Weak: {subject.display_name} gains Resistance to the '
             f'first instance of damage it takes, until the start of {guardian.display_name}\'s next turn. '
             f'GM: the game spends this protection as soon as the ally is dealt damage of that type, before '
             f'any Resistance, Immunity or damage reduction is worked out, so an attack the ally survives '
             f'unharmed has still spent it. If that attack dealt no damage, put the protection back. If one '
             f'attack harms the ally in several parts, apply Resistance to every one of those parts, then '
             f'remove the protection.', (aid,))
