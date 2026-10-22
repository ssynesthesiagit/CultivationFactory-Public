"""Beastmastery ownership and activated Sovereign Pack Mind.

Owner rules: authority/typed_mechanics/rules_text.json. The paid Bonus Action
creates an ordinary one-minute condition through reviewed typing. Only that
source-owned grant enables an optional post-roll bonus. The integer round
receipt is persisted by the native table transaction.

Procession's undefined Resistance to Frightened remains a GM reminder, never
immunity. Encirclement uses per-reactor Disengage protection, hit receipts and
native granted movement, with recipients restricted to owned Beast Allies.
The shared beast_allies helper also serves beastmastery_tamer contact checks.
"""
from __future__ import annotations
from typing import Any
from . import hook

PROCESSION = 'TAL_BEASTMASTERY_TEN_THOUSAND_BEAST_PROCESSION'
ENCIRCLEMENT = 'TAL_BEASTMASTERY_PACK_ENCIRCLEMENT'
PACK_MIND = 'TAL_BEASTMASTERY_SOVEREIGN_PACK_MIND'
BLOCK = 'beastmastery_pack'
ALLY_SOURCES = ('tamer', 'rider')
PACK_MIND_RANGE_FT = 120
PACK_MIND_ROUND_FLAG = '_round_sovereign_pack_mind'
PACK_MIND_ACTIVE = 'condition:typed.sovereign_pack_mind'
PACK_MIND_CHOICE = 'choice:needle.beastmastery.pack_mind'


@hook('compile_block')
def pack_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Ownership marker only; keep compiling the ordinary Actions/modifier."""
    if block != BLOCK:
        return None
    # The owner may be asked to make a free choice during another actor's AI
    # turn. Enroll that decision independently of generic reaction preferences.
    return [{**row, 'block': BLOCK, 'kind': spec.get('kind'), 'keeps_compiling': True,
             'choice_owner': spec.get('kind') == 'encirclement'}]


def beast_allies(engine: Any, owner: Any) -> list[Any]:
    """Public recipient predicate used by Pack Mind and pack regression fixtures.

    Only active, present, same-side Tamer/Rider summons with this owner count.
    Ownership of unrelated summons never makes them Beast Allies.
    """
    from ..relations import relation, ALLY
    return [beast for beast in engine.state.actors.values()
            if beast.active and relation(engine, owner, beast) == ALLY and beast.summon
            and beast.summon.get('source') in ALLY_SOURCES
            and str(beast.summon.get('owner') or '') == owner.entity_id
            and beast.summon.get('status', 'present') == 'present']


def holds(engine: Any, actor: Any, kind: str) -> bool:
    from .passive_rows import row_of
    return row_of(engine, actor.entity_id, BLOCK, kind) is not None


@hook('choice_reactors')
def beastmastery_choice_reactors(engine: Any) -> tuple[str, ...]:
    """Keep players with off-turn pack or Animal Handling choices in the AI-step probe."""
    from .passive_rows import row_of
    return tuple(sorted(actor.entity_id for actor in engine.state.actors.values()
                        if actor.active and (holds(engine, actor, 'encirclement')
                                             or row_of(engine, actor.entity_id, 'beastmastery_tamer',
                                                       'steady_handler') is not None)))


@hook('d20_bonus')
def sovereign_pack_mind_bonus(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """Offer a grant after the die, before outcome; spend only on acceptance."""
    from . import needle
    context = engine.d20_context(roll) or {}
    kind = str(context.get('kind') or '')
    if kind not in {'attack', 'save', 'check'} or intent is None:
        return None
    roller = engine.state.actors.get(str(roll.actor_id or ''))
    if roller is None or not roller.active:
        return None
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if (not owner.active or needle.incapacitated(owner)
                or not holds(engine, owner, 'sovereign_pack_mind')
                or owner.turn_flags.get(PACK_MIND_ROUND_FLAG) == engine.state.round_number
                or not any(c.condition_id == PACK_MIND_ACTIVE and c.source_actor_id == owner.entity_id
                           for c in owner.conditions.values())
                or roller not in beast_allies(engine, owner)
                or engine._distance_actor_to_actor(owner, roller) > PACK_MIND_RANGE_FT):
            continue
        source = str(context.get('source_id') or '')
        action = engine.action_catalog.get(source)
        action_name = getattr(action, 'display_name', None) or {'attack': 'attack', 'save': 'saving throw', 'check': 'ability check'}[kind]
        bonus = int(owner.proficiency_bonus or 2)
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, 'PACK_MIND', roll.roll_id),
                            owner, PACK_MIND_CHOICE, ['grant'],
                            labels={'grant': f'Add {bonus} to this roll'}, preferred=['grant'],
                            allow_decline=True, automatic=True, default='decline',
                            name='Sovereign Pack Mind', feature_id=PACK_MIND, target_id=roller.entity_id,
                            prompt=f"Sovereign Pack Mind: {roller.display_name}'s {kind} roll for {action_name} is {roll.total}. "
                                   f"Add {bonus} (your Proficiency Bonus) before the outcome is known? "
                                   "No additional cost; uses your one grant this round. You may decline and save it for another roll. "
                                   "Available only during the 1-minute effect, activated by a Bonus Action that expends Martial Focus once per long rest.",
                            prompt_context={'cost': 'No additional cost; one grant per round', 'action_name': action_name})
        if chosen != ['grant']:
            continue
        owner.turn_flags[PACK_MIND_ROUND_FLAG] = int(engine.state.round_number)
        return {'source_id': PACK_MIND, 'bonus': bonus, 'user_id': owner.entity_id}
    return None


def threatening_pack(engine: Any, owner: Any, enemy: Any) -> list[Any]:
    from .needle import incapacitated
    from ..typed_reactions import physical_melee_reach
    from .. import targeting
    from ..relations import relation, ENEMY
    if relation(engine, owner, enemy) != ENEMY:
        return []
    return [beast for beast in beast_allies(engine, owner) if relation(engine, beast, enemy) == ENEMY
            and not incapacitated(beast)
            and engine._distance_actor_to_actor(beast, enemy) <= (physical_melee_reach(engine, beast) or 5)
            and targeting.line_of_effect(engine, beast, target=enemy)]


@hook('disengage_protection')
def encirclement_disengage(engine: Any, reactor: Any, mover: Any) -> bool | None:
    owner = engine.state.actors.get(str((reactor.summon or {}).get('owner') or ''))
    if owner is not None and holds(engine, owner, 'encirclement'):
        pack = threatening_pack(engine, owner, mover)
        if len(pack) >= 2 and any(b.entity_id == reactor.entity_id for b in pack):
            return False
    return None


@hook('after_hit')
def encirclement_hit(ctx: Any, target: Any, kind: str) -> None:
    from dataclasses import replace
    from ..typed_executor import run_effects
    owner = ctx.engine.state.actors.get(str((ctx.actor.summon or {}).get('owner') or ''))
    if owner is None or not holds(ctx.engine, owner, 'encirclement'):
        return
    pack = threatening_pack(ctx.engine, owner, target)
    # The rule's threshold is supplied by two Beast Allies threatening the
    # target. Its first hitter can be another owned Beast Ally at range.
    if len(pack) < 2 or ctx.actor not in beast_allies(ctx.engine, owner):
        return
    receipt = owner.turn_flags.setdefault('_round_pack_encirclement_hits', {})
    if receipt.get(target.entity_id) == ctx.engine.state.round_number:
        return
    receipt[target.entity_id] = int(ctx.engine.state.round_number)
    run_effects(replace(ctx.with_source(ENCIRCLEMENT), actor=owner, targets=[target], target=target),
                [{'type': 'speed', 'applies_to': 'target', 'flat': -10,
                  'expires_on': 'START_OF_TARGET_NEXT_TURN',
                  'evidence': 'The first Beast Ally hitting it each round reduces its Speed by 10 feet until the start of its next turn.'}])


@hook('before_attack')
def encirclement_move(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> None:
    from . import needle
    from .choice_prompt import action_context
    from .. import granted_movement
    from ..target_knowledge import located
    from . import ai_controlled
    owner = engine.state.actors.get(str((defender.summon or {}).get('owner') or ''))
    if owner is None or not holds(engine, owner, 'encirclement') or intent is None:
        return
    if ai_controlled(engine, owner) and not located(engine, owner, attacker):
        return  # automatic choices cannot infer an unseen attacker's position
    pack = threatening_pack(engine, owner, attacker)
    if defender not in beast_allies(engine, owner) or len(pack) < 2:
        return
    # AI may select only companions it perceives. Side/ownership are hard gates,
    # not ordering preferences. Player destination choices use native routes.
    from ..typed_reactions import physical_melee_reach
    from .. import targeting
    from ..relations import relation, ENEMY
    reach = physical_melee_reach(engine, attacker) or 5
    others = [b for b in beast_allies(engine, owner) if b is not defender
              and not needle.incapacitated(b)
              and engine._distance_actor_to_actor(attacker, b) <= reach
              and relation(engine, b, attacker) == ENEMY
              and targeting.line_of_effect(engine, attacker, target=b)
              and (not ai_controlled(engine, owner)
                   or located(engine, owner, b))]
    routes = {b.entity_id: granted_movement.candidates(engine, b, 5, intent, ENCIRCLEMENT) for b in others}
    options = sorted(b.entity_id for b in others if routes[b.entity_id])
    picked = needle.ask(engine, intent, needle.checkpoint_id(engine, 'ENCIRCLE_BEAST', attacker.entity_id,
                       defender.entity_id, context.get('attack_index', 1)), owner,
                       'choice:needle.beastmastery.encircle_beast', options,
                       labels={b.entity_id: f'{b.display_name} may move 5 feet without Opportunity Attacks' for b in others},
                       allow_decline=True, preferred=options[:1], feature_id=ENCIRCLEMENT,
                       name='Pack Encirclement',
                       prompt=(f'Pack Encirclement: {attacker.display_name} attacked {defender.display_name} with '
                               f'{getattr(engine.action_catalog.get(str(context.get("source_id") or "")), "display_name", "an attack")}. '
                               f'Choose another Beast Ally within {reach} feet of {attacker.display_name} to move 5 feet. '
                               'This costs no Action or Reaction.'),
                       prompt_context={**action_context(engine, attacker, str(context.get('source_id') or ''), defender),
                           'cost': 'No Action or Reaction; up to 5 feet without Opportunity Attacks'})
    if not picked:
        return
    beast = engine.state.actors[picked[0]]
    available = routes[beast.entity_id]
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, 'ENCIRCLE_MOVE', beast.entity_id), owner,
                        'choice:needle.beastmastery.encircle_move', list(available),
                        labels={key: f'Move to {c.destination.x},{c.destination.y}' for key, c in available.items()},
                        allow_decline=True, preferred=list(available)[:1], feature_id=ENCIRCLEMENT,
                        name='Pack Encirclement',
                        prompt=(f'Pack Encirclement: {attacker.display_name} attacked {defender.display_name} with '
                                f'{getattr(engine.action_catalog.get(str(context.get("source_id") or "")), "display_name", "an attack")}. '
                                f'Where should {beast.display_name} move? This costs no Action or Reaction.'),
                        prompt_context={**action_context(engine, attacker, str(context.get('source_id') or ''), defender),
                            'cost': 'No Action or Reaction; up to 5 feet without Opportunity Attacks'})
    if chosen:
        candidate = available[chosen[0]]
        engine.grant_movement(beast, granted_movement.Route(candidate.canonical_path,
                              candidate.metadata.get('movement_mode', 'walk')), ENCIRCLEMENT,
                              feet=5, intent=intent, provokes=False)
