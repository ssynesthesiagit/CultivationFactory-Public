"""Alchemy's immediate poison rechecks and Corrosive Dregs' delayed residue.

Uses the original condition's save, beneficiary-owned choices, and evented
condition state. Nothing is inferred from an unknown condition's name alone.
The residue is installed after the initial damage, and consumed before its
own damage is delivered, so it cannot trigger recursively or twice on reload.
"""
from typing import Any

from . import effect, hook

RESIDUE = 'condition:typed.alchemy_corrosive_residue'


def poison_label(engine: Any, subject: Any, condition: Any) -> str:
    """A poison option a player can tell apart, in plain words.

    Two poisons with the same ability and DC are the same button unless the label says which
    effect is on offer and how long it lasts, so name the source/effect (its stored label when the
    source wrote one, else its printed condition name) and its remaining lifetime. Never an
    instance id: that is engine bookkeeping a player cannot act on.
    """
    from .repeat_saves import save_of
    data = condition.data or {}
    save = save_of(condition) or {}
    action = engine.action_catalog.get(condition.source_definition_id)
    source = engine.state.actors.get(condition.source_actor_id)
    name = str(data.get('label') or '').strip() or getattr(action, 'display_name', None) or 'poison'
    from ..status_text import duration_text
    typed = ((getattr(action, 'parameters', None) or {}).get('typed') or {})
    actor_names = {who: creature.display_name for who, creature in engine.state.actors.items()}
    life = duration_text(str(getattr(condition, 'expires_on', '') or 'UNTIL_REMOVED'), data, typed,
                         getattr(source, 'display_name', 'the source creature'), subject.display_name,
                         actor_names, engine)
    ability, dc = str(save.get('ability') or '?').upper(), save.get('dc')
    against = f'DC {dc}' if dc is not None else 'an unknown DC'
    return f'Poisoned ({name}): {ability} save, {against} ({life})'


@hook('candidate_allowed')
def automatic_corrosive_target(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Humans retain the printed creature domain; automatic harm picks enemies."""
    if action is None:
        return None
    typed = action.parameters.get('typed') or {}
    if typed.get('source') != 'ALCHEMY_BASE_FIELD_FORMULA' or typed.get('option_label') != 'Corrosive Dregs':
        return None
    from . import ai_controlled
    if ai_controlled(engine, actor):
        return all(engine.state.actors[who].team_id != actor.team_id for who in candidate.target_ids)


@effect('alchemy_repeat_poison')
def repeat_poison(ctx: Any, row: dict[str, Any]) -> None:
    """Offer one original Poisoned save to the actual beneficiary, never bystanders.

    Antidote requires a source with repeat saves and its repetition is mandatory.
    Medicinal Smoke permits declining; either an originating or a repeated save
    supplies its original ability/DC. Conditions without either have no save
    to repeat. Native _roll_save retains defenses, reactions and roll receipts.
    """
    from . import needle
    from .repeat_saves import repeatable, save_of
    from ..typed_executor import _default_subject

    for subject in _default_subject(ctx, row, harmful=False):
        eligible = repeatable(subject, ('poisoned',))
        if row.get('requires_repeat'):
            eligible = [(iid, c) for iid, c in eligible
                        if isinstance(c.data.get('repeat_save'), dict)
                        and c.data['repeat_save'].get('ability')
                        and c.data['repeat_save'].get('dc') is not None]
        if not eligible:
            continue
        optional = bool(row.get('optional'))
        chosen = needle.ask(ctx.engine, ctx.intent,
            needle.checkpoint_id(ctx.engine, 'ALCHEMY_POISON_RECHECK', ctx.source, subject.entity_id),
            subject, 'choice:needle.alchemy_poison_recheck', [iid for iid, _ in eligible],
            labels={iid: poison_label(ctx.engine, subject, c) for iid, c in eligible},
            prompt=f'{ctx.action.display_name}: {subject.display_name} '
                   + ('may repeat' if optional else 'repeats')
                   + ' one saving throw against Poisoned. Choose the effect to try to end.',
            name=ctx.action.display_name, minimum=0 if optional else 1, maximum=1,
            allow_decline=optional, preferred=[eligible[0][0]], target_id=subject.entity_id)
        if not chosen:
            continue
        iid, condition = next(pair for pair in eligible if pair[0] == chosen[0])
        save = save_of(condition)
        roll = ctx.engine._roll_save(subject, str(save['ability']).upper(), int(save['dc']), ctx.source,
            roll_context={'source_actor_id': condition.source_actor_id, 'named': ['poisoned']})
        if roll is not None and roll.total >= int(save['dc']) and iid in subject.conditions:
            del subject.conditions[iid]
            ctx.engine._append_event('CONDITION_REMOVED', ctx.source, actor_id=subject.entity_id,
                target_ids=(subject.entity_id,),
                payload={'condition_id': condition.condition_id, 'instance_id': iid, 'repeat_save': True})


@hook('choice_reactors')
def poison_choice_reactors(engine: Any) -> tuple[str, ...] | None:
    """Enroll only poisoned beneficiaries when this fight has a repeat-poison action."""
    from ..typed_executor import _walk_rows
    from .repeat_saves import repeatable

    offers_recheck = any(
        row.get('type') == 'alchemy_repeat_poison'
        for action in engine.action_catalog.values()
        for row in _walk_rows(((getattr(action, 'parameters', None) or {}).get('typed') or {}).get('effects') or [])
    )
    if not offers_recheck:
        return None
    return tuple(actor.entity_id for actor in engine.state.actors.values()
                 if actor.active and repeatable(actor, ('poisoned',)))


@effect('alchemy_corrosive_residue')
def coat(ctx: Any, row: dict[str, Any]) -> None:
    """Remember PB when the failed-save residue lands, for the printed lifetime."""
    from ..typed_executor import _default_subject, effect_expiry

    for subject in _default_subject(ctx, row, harmful=True):
        # Reapplication by the same caster refreshes its own coating. Another
        # caster's still-active coating retains its original lifetime/strength.
        for iid, held in list(subject.conditions.items()):
            if held.condition_id == RESIDUE and held.source_actor_id == ctx.actor.entity_id:
                del subject.conditions[iid]
                ctx.engine._append_event('CONDITION_REMOVED', ctx.source, actor_id=ctx.actor.entity_id,
                    target_ids=(subject.entity_id,), payload={'condition_id': RESIDUE, 'instance_id': iid})
        ctx.engine._apply_condition(subject, RESIDUE, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, row, subject, condition=True),
            data={'amount': ctx.formula('pb'),
                  'label': f"Corrosive Dregs: the next damage also deals {ctx.formula('pb')} extra Acid damage, "
                           "until the start of the alchemist's next turn"})


@hook('event', nested=True)
def residue_damage(engine: Any, kind: str, record: dict[str, Any]) -> None:
    """The first actual damage, including Temporary HP absorption, spends the coating.

    Identical overlapping coatings do not add together: consume them all and
    deliver the strongest one. Removal precedes delivery and is journaled.
    Reconstruct only from the stored source action/actor, never the new attacker.
    """
    if kind != 'DAMAGE_COMMITTED' or int((record.get('payload') or {}).get('reduced_to') or 0) <= 0:
        return
    from ..typed_executor import Context, block_damage

    for target_id in record.get('target_ids') or ():
        subject = engine.state.actors.get(target_id)
        if subject is None:
            continue
        coatings = [(iid, c) for iid, c in subject.conditions.items() if c.condition_id == RESIDUE]
        if not coatings:
            continue
        _, strongest = max(coatings, key=lambda pair: (int(pair[1].data.get('amount', 0)), pair[0]))
        for iid, c in coatings:
            del subject.conditions[iid]
            engine._append_event('CONDITION_REMOVED', c.source_definition_id,
                actor_id=c.source_actor_id, target_ids=(subject.entity_id,),
                payload={'condition_id': RESIDUE, 'instance_id': iid})
        actor = engine.state.actors.get(strongest.source_actor_id)
        action = engine.action_catalog.get(strongest.source_definition_id)
        if actor is None or action is None:
            return
        ctx = Context(engine, actor, action, getattr(engine, '_active_intent', None),
                      action.parameters.get('typed') or {}, [subject], subject,
                      explicit_self_recipient=subject.entity_id == actor.entity_id)
        block_damage(ctx, {'type': 'damage', 'applies_to': 'target',
                          'flat': int(strongest.data['amount']), 'damage_types': ['acid']})
