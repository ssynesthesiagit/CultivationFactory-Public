"""Medicine Saint's field administration of the three common medicinal pills.

Preparation remains outside combat. Reuse each owned, compiled consumer action;
the recipe's numbers and effects are retained, with self recipients changed to
the administered creature. This does not turn Medicinal Smoke into a pill.
Other recipes retain their existing administration/qualification boundaries.
"""
import copy
from typing import Any

from . import effect, hook

SAINT = 'insight.medicine-saint'
SAVE = 'condition:typed.medicine_saint_con_save'
RECIPES = {'TAL_ALCHEMY_HEALING_PILL', 'TAL_ALCHEMY_ANTIDOTE_PILL', 'TAL_ALCHEMY_CALMING_HEART_PILL'}


@hook('compile_block')
def compile_saint(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[Any] | None:
    if block == 'alchemy_medicine_saint':
        return [{**row, 'kind': 'administration'}]


@effect('medicine_saint_administration')
def marker(ctx: Any, row: dict[str, Any]) -> None:
    """The passive's component marker; compile_actions supplies its priced uses."""


def target_rows(value: Any) -> Any:
    """Copy a consumer's effect tree, aiming self effects at the recipient."""
    if isinstance(value, list):
        return [target_rows(row) for row in value]
    if not isinstance(value, dict):
        return value
    out = {key: target_rows(val) for key, val in value.items()}
    if out.get('applies_to') == 'self':
        out['applies_to'] = 'target'
    if out.get('type') == 'alchemy_healing_pill':
        out['formula'] = 'key_ability_modifier'
    return out


@hook('compile_actions')
def administrations(info: dict[str, Any]) -> list[Any] | None:
    if SAINT not in (info.get('owned_ids') or ()):
        return None
    from ..gate2_runtime_models import EconomyKind

    out = []
    for action in info.get('actions') or ():
        typed = (action.parameters or {}).get('typed') or {}
        if typed.get('source') not in RECIPES or typed.get('option_of') or typed.get('modifier'):
            continue
        typed = copy.deepcopy(typed)
        typed['effects'] = target_rows(typed.get('effects') or [])
        typed['effects'].append({'type': 'alchemy_saint_con_save', 'applies_to': 'target',
            'duration': 'until_end_of_its_next_turn',
            'evidence': 'The target gains Advantage on one Constitution saving throw it makes before the end of its next turn.'})
        out.append(action.model_copy(update={
            'source_definition_id': action.source_definition_id + '.medicine_saint',
            'display_name': 'Medicine Saint: Administer ' + action.display_name,
            'economy': EconomyKind.BONUS_ACTION, 'target_kind': 'ANY_CREATURE', 'range_ft': 5,
            'parameters': {**action.parameters, 'typed': typed, 'medicine_saint': True,
                'description': 'Administer a prepared medicinal pill to a creature you can reach as a Bonus Action. '
                               'Healing adds your Alchemy key ability modifier. The recipient gains Advantage '
                               'on one Constitution saving throw before the end of its next turn.'}}))
    return out


@hook('candidate_allowed')
def automatic_recipients(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not action.parameters.get('medicine_saint'):
        return None
    from . import ai_controlled

    if ai_controlled(engine, actor):
        return all(engine.state.actors[who].team_id == actor.team_id for who in candidate.target_ids)


@effect('alchemy_saint_con_save')
def grant_save(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry
    for subject in _default_subject(ctx, row, harmful=False):
        ctx.engine._remove_condition(subject, SAVE, ctx.source)
        ctx.engine._apply_condition(subject, SAVE, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, row, subject, condition=True),
            data={'label': 'Medicine Saint: Advantage on one Constitution saving throw before your next turn ends'})


@hook('condition_choice_owner')
def medicine_saint_choice_owner(engine: Any, actor: Any, condition: Any) -> bool | None:
    """Persisted optional saves belong to their beneficiary at every table boundary."""
    if condition.condition_id == SAVE:
        return True


@hook('save_mode')
def choose_save(engine: Any, subject: Any, ability: str, dc: int,
                 source_id: str, context: dict[str, Any]) -> str | None:
    if ability.upper() != 'CON':
        return None
    held = [(iid, c) for iid, c in subject.conditions.items() if c.condition_id == SAVE]
    if not held:
        return None
    from ..typed_executor import condition_rules
    if any(ability.upper() in (row.get('no_save_advantage') or []) for row in condition_rules(subject)):
        return None
    from . import choice_prompt, needle
    # The question is "spend the one-save benefit on THIS save?", so it must name the save being made.
    # The incoming effect arrives as save_mode metadata for whatever is causing this roll (including a
    # nested reaction's), not as this choice's own source: read the actor and action the roll actually
    # came from through the shared display-only context, and never from the outer turn's intent.
    incoming = engine.state.actors.get(str(context.get('source_actor_id') or ''))
    cause = choice_prompt.action_context(engine, incoming, str(context.get('source_id') or source_id), subject)
    against = cause['action_name'] or 'another creature\'s effect'
    chosen = needle.ask(engine, engine._active_intent,
        needle.checkpoint_id(engine, 'MEDICINE_SAINT_SAVE', source_id, subject.entity_id),
        subject, 'choice:needle.medicine_saint_save', [iid for iid, _ in held],
        labels={iid: 'Use Medicine Saint Advantage' for iid, _ in held},
        prompt=f'Medicine Saint: {subject.display_name} must make a Constitution saving throw '
               f'(DC {dc}) against {against}. Use the pill\'s Advantage for this save, or save it '
               'for a later save before your next turn ends?',
        name='Medicine Saint', minimum=0, maximum=1, allow_decline=True,
        preferred=[held[0][0]], target_id=subject.entity_id, prompt_context=cause)
    if chosen:
        iid = chosen[0]
        condition = subject.conditions.pop(iid)
        engine._append_event('CONDITION_REMOVED', condition.source_definition_id,
            actor_id=subject.entity_id, target_ids=(subject.entity_id,),
            payload={'condition_id': SAVE, 'instance_id': iid, 'reason': 'CONSUMED'})
        return 'ADVANTAGE'
