"""A second weapon attack against a different creature beside the one you hit (rider lane 3, 2026-09-29).

  second_attack  {"of_first_ft": 5, "advantage_if_consumed": "Bite"}

Cleaving Arc ("When you hit with Hewing Strike ... threaten a second creature within your reach and within 5 feet of the original target.
Make a second melee weapon attack against that creature. On hit, it takes the weapon's normal damage but cannot receive a Hewing rider from
this talent. If the first target had Bite from you and you consumed it with another Axes talent this turn, the second attack has Advantage").
It had been "extra_attacks: 1", a second swing at the SAME creature.

The second creature is chosen through the caster's bounded menu within weapon
reach and ``of_first_ft`` (default 5) of the first; AI prefers the weakest. The attack does the weapon's
normal damage with its own ability modifier (Cleave drops it).  Nothing happens when nobody qualifies.

``advantage_if_consumed`` names a mark: a ``mark_spent`` hook notes each mark you consume from a creature this turn, and the second attack has
Advantage when the FIRST target's named mark was one of them (the attack that placed the mark was not yet rolled when it was spent).
"""
from typing import Any

from . import effect, hook
from .rider_helpers import effect_rows

SPENT = "_spent_marks"


@hook("mark_spent")
def note_spent(ctx: Any, name: str, subject: Any) -> None:
    # Only an owner of a compiled second-attack rider needs this history. An
    # unrelated actor spending another kind of mark must keep its saved flags.
    if not any(row.get('type') == 'second_attack' and
               str(row.get('advantage_if_consumed') or '').lower() == str(name).lower()
               for action_id in ctx.actor.action_ids
               for row in effect_rows((ctx.engine.action_catalog[action_id].parameters.get('typed') or {}).get('effects'))):
        return
    ctx.actor.turn_flags[f"{SPENT}:{str(name).lower()}:{subject.entity_id}"] = True


@effect("second_attack")
def second_attack(ctx: Any, row: dict[str, Any]) -> None:
    from dataclasses import replace
    from ..typed_executor import block_attack

    first, engine, actor = ctx.target, ctx.engine, ctx.actor
    if first is None or not actor.active:
        return
    reach, near = int(ctx.action.range_ft or 5), int(row.get("of_first_ft") or 5)
    others = [other for other in engine.state.actors.values()
              if other.active and other.team_id != actor.team_id and other.entity_id != first.entity_id
              and engine._distance_actor_to_actor(first, other) <= near and engine._distance_actor_to_actor(actor, other) <= reach
              and engine._line_of_sight_actor_to_actor(actor, other)]
    if not others:
        return
    from . import needle

    others.sort(key=lambda other: (other.current_hp, other.entity_id))
    chosen = needle.ask(engine, ctx.intent,
        needle.checkpoint_id(engine, 'SECOND_ATTACK', ctx.source, first.entity_id), actor,
        'choice:needle.second_attack', [other.entity_id for other in others],
        labels={other.entity_id: other.display_name for other in others},
        prompt=f'Cleaving Arc: after {ctx.action.display_name} hits {first.display_name}, choose the second creature',
        name='Cleaving Arc', target_id=first.entity_id,
        preferred=[others[0].entity_id], maximum=1, allow_decline=True)
    if not chosen:
        return
    second = engine.state.actors[chosen[0]]
    mark = str(row.get("advantage_if_consumed") or "")
    if mark and actor.turn_flags.get(f"{SPENT}:{mark.lower()}:{first.entity_id}"):
        engine._add_modifier(actor, ctx.source, "attack_mode", "SET", "ADVANTAGE", "NEXT_ATTACK", expires_on="CONSUMED")
    # Reuse the ordinary attack interpreter, including declaration reactions,
    # defender steps and downstream attack hooks. A bare weapon row carries no
    # Hewing riders or another second_attack effect, so it cannot recurse.
    attack = {'type':'attack','attack_kind':'weapon','count':1,'on_hit':[]}
    typed = {key:value for key,value in ctx.typed.items() if key in (
        'weapon','numbers','source','duration','mundane','proficient','magic_bonus','sphere')}
    typed['effects'] = [attack]
    block_attack(replace(ctx,targets=[second],target=second,typed=typed,damage_cache={}),attack)
