"""Opt-in cancel/roll modes bound to the exact pending typed activation.

Cancellation uses the executor's existing paid-counter protocol. Roll policies
are evented conditions keyed by the triggering intent and action; unrelated
attacks, reaction saves, and subsequent uses never borrow them. Completion
removes the exact instance; an interrupted activation's fallback current-turn
expiry is native. Historical rows without this effect remain inert.
"""
from typing import Any
from . import effect, hook

CONDITION = 'condition:typed.pending_technique_modes'


@effect('pending_technique_result')
def apply(ctx: Any, row: dict) -> None:
    engine = ctx.engine
    pending = getattr(engine, '_typed_pending_technique', None) or {}
    target = ctx.target
    intent = getattr(engine, '_active_intent', None)
    source = getattr(engine, '_active_action_source_id', None)
    if target is None or pending.get('actor') != target.entity_id or intent is None or not source:
        return
    if row.get('cancel'):
        engine._typed_countered = True
        return
    engine._apply_condition(target, CONDITION, ctx.source, ctx.actor.entity_id,
        expires_on='END_OF_CURRENT_TURN', data={'intent_id': intent.intent_id,
            'source': source, 'attack_mode': row.get('attack_mode'), 'save_mode': row.get('save_mode'),
            'label': f'{ctx.action.display_name}: this technique has Disadvantage on attacks; its targets have Advantage on saves'})


def policies(ctx: Any):
    return [c for c in ctx.actor.conditions.values() if c.condition_id == CONDITION
            and c.data.get('intent_id') == getattr(ctx.intent, 'intent_id', None)
            and c.data.get('source') == ctx.source]


@hook('attack_mode')
def attack_mode(ctx: Any, target: Any) -> str | None:
    return next((c.data['attack_mode'] for c in policies(ctx) if c.data.get('attack_mode')), None)


@hook('save')
def save_mode(ctx: Any, subject: Any, ability: str, named: Any) -> dict | None:
    modes = [c.data['save_mode'] for c in policies(ctx) if c.data.get('save_mode')]
    return {'modes': modes} if modes else None


@hook('technique_used')
def finished(ctx: Any) -> None:
    from .condition_ownership import remove_instance
    for c in policies(ctx):
        remove_instance(ctx.engine, ctx.actor, c.instance_id, ctx.source)


@hook('reaction_subject_allowed')
def voice_trigger(engine: Any, reactor: Any, other: Any, row: dict) -> bool | None:
    """Opt-in voice predicates narrow the classifier's broad technique route."""
    def needs(value):
        if isinstance(value, dict):
            return (value.get('type') == 'pending_technique_result' and value.get('requires_voice')) or any(needs(v) for v in value.values())
        return any(needs(v) for v in value) if isinstance(value, list) else False
    if not needs(row.get('effects') or []):
        return None
    from .. import speech, senses
    from ..typed_executor import cant_hear
    pending = getattr(engine, '_typed_pending_technique', None) or {}
    action = engine.action_catalog.get(getattr(engine, '_active_action_source_id', ''))
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if other is None or pending.get('actor') != other.entity_id or not (speech.needs_voice(action) or typed.get('requires_hearing')):
        return False
    # This response answers a perceived vocal declaration, never an unheard
    # hidden action. Native sight/pinpointing or an unobstructed audible voice
    # supplies that perception; no hidden tactical roster is consulted.
    seen = senses.perceives(engine, reactor, other, locate_concealed=True)
    heard = not cant_hear(reactor) and not speech.silenced(other) and engine._line_of_sight_actor_to_actor(reactor, other)
    return None if seen or heard else False


def owns_result(row: dict) -> bool:
    def visit(value):
        if isinstance(value, dict):
            return value.get('type') == 'pending_technique_result' or any(visit(v) for v in value.values())
        return any(visit(v) for v in value) if isinstance(value, list) else False
    return visit(row.get('effects') or [])


@hook('reaction_consent')
def consent(engine: Any, row: dict, reactor: Any, checkpoint: str) -> bool | None:
    if not owns_result(row):
        return None
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context
    from .choice_costs import quote
    pending = getattr(engine, '_typed_pending_technique', None) or {}
    caster = engine.state.actors.get(pending.get('actor', ''))
    source = getattr(engine, '_active_action_source_id', '')
    action = engine.action_catalog.get(source)
    if caster is None or action is None:
        return False
    chosen = ask(engine, getattr(engine, '_active_intent', None),
        checkpoint_id(engine, 'pending_technique_consent', reactor.entity_id, source), reactor,
        'choice:needle.pending_technique_consent', ['answer'], labels={'answer': 'Spend Reaction and ' + quote(row.get('costs') or [])},
        allow_decline=True, automatic=False, default='decline', name=row.get('name', 'Technique response'),
        feature_id=row['feature_id'], target_id=caster.entity_id,
        prompt_context=action_context(engine, caster, source, caster),
        prompt=f"{row.get('name', 'Technique response')}: {caster.display_name} uses {action.display_name}. Spend your Reaction and {quote(row.get('costs') or [])}? A failed Constitution save stops that technique with its cost spent; a success gives its attacks Disadvantage and its targets Advantage on saves. Decline to let it resolve normally.")
    return 'answer' in chosen


@hook('choice_reactors')
def choosers(engine: Any) -> tuple[str, ...]:
    return tuple(aid for aid, rows in engine.typed_reaction_rows.items() if any(owns_result(row) for row in rows))
