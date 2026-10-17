"""Explicit table declarations, shared by abilities needing source-owned facts.

Facts are never derived from names, teams or private intent. A typed action may
offer a finite list with record_subject_fact; manual owners state the fact through
the ordinary choice transaction. Computers retain unknown rather than inventing
one. Conditions keep the declaring actor, source action, category and subject.
"""
from . import effect, hook, note

FACT = 'condition:typed.recorded_subject_fact'
AUTHORITY = 'condition:typed.recorded_source_authority'


def source_authority(engine, intent, chooser, target, context):
    """Read or explicitly declare the authority of this exact native source.

    Used by Nudge's Refuse Certainty. Unknown CL is never manufactured; AI uses
    only an existing declaration. A human's answer is journaled and source-owned.
    """
    from . import ai_controlled, needle
    owner = engine.state.actors.get(context.get('source_actor_id')) or target
    known = next((c.data.get('authority') for c in owner.conditions.values()
                  if c.condition_id == AUTHORITY and c.data.get('source') == context['source_id']), None)
    if known is not None or context.get('authority') is not None:
        return context.get('authority') or known
    if ai_controlled(engine, chooser):
        return None
    action = engine.action_catalog.get(context['source_id'])
    name = action.display_name if action is not None else 'this effect'
    selected = needle.ask(engine, intent, needle.checkpoint_id(engine, 'SOURCE_AUTHORITY', context['source_id']), chooser,
        'choice:needle.source_authority', ['unknown', 'ordinary', 'protected'],
        labels={'unknown': 'Authority is unknown', 'ordinary': 'Record that this source is ordinary',
                'protected': 'Record that this source has protected authority'}, preferred=['unknown'],
        name='Record source authority', target_id=target.entity_id,
        prompt=f"{name} would give {target.display_name} an automatic result on the triggering roll. Record only established source authority; unknown stays unknown. This declaration has no cost.")
    if not selected or selected[0] == 'unknown':
        return None
    engine._apply_condition(owner, AUTHORITY, context['source_id'], chooser.entity_id, expires_on='UNTIL_REMOVED',
        data={'source': context['source_id'], 'authority': selected[0], 'label': f"Recorded source authority: {selected[0]}"})
    return selected[0]


def categories(subject):
    return {str(c.data['category']) for c in subject.conditions.values()
            if c.condition_id == FACT and (c.data or {}).get('category')}


@effect('record_subject_fact', harmful=False)
def record(ctx, row):
    from . import ai_controlled, needle
    if ai_controlled(ctx.engine, ctx.actor):
        return  # unknown is not an invitation for the AI to invent a fact
    subject = ctx.target or ctx.actor
    labels = dict(row['categories'])
    labels['unknown'] = 'Unknown: record no fact'
    answer = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'SUBJECT_FACT', subject.entity_id),
        ctx.actor, 'choice:needle.subject_fact', list(labels), labels=labels, preferred=['unknown'],
        name='Record the stakes', prompt=f"State an established fact about {subject.display_name}. This records context; it grants no ability or authority.",
        target_id=subject.entity_id)
    if not answer or answer[0] == 'unknown':
        return
    category = answer[0]
    if category not in categories(subject):
        ctx.engine._apply_condition(subject, FACT, ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'category': category, 'scope': (row.get('category_scopes') or {}).get(category, 'scene'),
                  'label': f"Recorded fact: {labels[category]}"})
    note(ctx.engine, ctx.source, ctx.actor, f"{subject.display_name}: {labels[category]} (recorded by {ctx.actor.display_name}).", (subject,))


@hook('roll_resolved')
def consume_roll_facts(engine, roll, success, frame, intent):
    from .spirit_traditions import remove
    ids = {roll.actor_id, frame.get('target_id'), frame.get('source_actor_id')}
    for actor in engine.state.actors.values():
        if actor.entity_id in ids:
            for held in list(actor.conditions.values()):
                if held.condition_id == FACT and held.data.get('scope') == 'next_roll':
                    remove(engine, actor, held, 'CONSUMED')


@hook('scene_ended')
def expire_facts(engine, serial):
    from .spirit_traditions import remove
    interested = False
    for actor in engine.state.actors.values():
        for held in list(actor.conditions.values()):
            if held.condition_id in (FACT, AUTHORITY):
                remove(engine, actor, held, 'EXPIRED')
                interested = True
    return True if interested else None
