"""Ash Mercy's paid, settled restraint rider.

The table's declaration is testimony about intent, never an inference from zero
HP, a nonlethal combat label, a damage colour or an ability name. A mechanical
helpless/defeated creature and the actual completed Foundation spend are required
before that declaration can be offered. Unknown facts grant nothing.
"""
from . import hook, run_strict
from .foundation_context import ASH, settled_execution_events, paid_source_facts, public_scene_declarant
from .needle import ask, checkpoint_id

FEATURE = ASH + 'refined_ash_mercy_boundary'
POOL = 'resource:foundation.funeral_ash'
SCENE = 'choice:needle.ash_mercy.scene'
CONTEXT = 'choice:needle.ash_mercy.context'
TARGET = 'choice:needle.ash_mercy.target'


@hook('compile_block')
def compile_mercy(block, spec, row, numbers):
    if block == 'foundation_mercy':
        return [{**row, 'pb': int(numbers['pb'])}]
    return None


def _row(engine, actor):
    return next((r for r in engine.typed_passive_rows.get(actor.entity_id, ())
                 if r.get('block') == 'foundation_mercy' and r.get('feature_id') == FEATURE), None)


def _helpless(actor):
    return (not actor.active or actor.current_hp == 0
            or any(c.condition_id.rsplit('.', 1)[-1] in
                   {'unconscious', 'life_unconscious', 'asleep', 'paralyzed'}
                   for c in actor.conditions.values()))


@hook('transaction_settled')
def settled_mercy(engine, source_id, actor_id, intent, first_sequence):
    if intent is None:
        return
    from ..senses import perceives
    events = settled_execution_events(engine, first_sequence)
    for spend in events:
        owner = engine.state.actors.get(spend.actor_id)
        if (spend.event_type != 'RESOURCE_SPENT' or owner is None
                or spend.payload.get('resource_id') != POOL
                or int(spend.payload.get('amount') or 0) <= 0):
            continue
        row = _row(engine, owner)
        if row is None or False in run_strict('foundation_expression_selected', engine, owner, FEATURE):
            continue
        source = paid_source_facts(engine, spend)
        if source is None or not str(source['mechanic_id']).startswith(ASH):
            continue
        action_name = source['name']
        # The choice really leaves this creature unharmed by THIS execution.
        # Previous defeat alone does not prove mercy, and an engine's automatic
        # nonlethal label cannot attest intent. Do not expose unseen creatures.
        harmed = {tid for e in events if e.event_type == 'DAMAGE_COMMITTED'
                  and int(e.payload.get('hp_damage') or 0) +
                      int(e.payload.get('temporary_hp_absorbed') or 0) > 0
                  for tid in e.target_ids}
        subjects = [a for a in engine.state.actors.values()
                    if a.entity_id != owner.entity_id and _helpless(a)
                    and a.entity_id not in harmed and perceives(engine, owner, a)]
        if not subjects:
            continue
        meta = {'action_name': action_name, 'source_definition_id': spend.source_definition_id,
                'cost': 'No additional action or resource; the Funeral Ash use is already paid'}
        common = {'name': 'Ash Mercy Boundary', 'feature_id': FEATURE, 'prompt_context': meta}
        picked = ask(engine, intent, checkpoint_id(engine, 'ASH_MERCY_SCENE', spend.sequence),
            owner, SCENE, [a.entity_id for a in subjects],
            labels={a.entity_id: f'Choose restraint toward {a.display_name}, who is helpless or defeated'
                    for a in subjects}, allow_decline=True, default='decline',
            prompt=f'Ash Mercy Boundary after {action_name}: which helpless or defeated creature did you choose to spare rather than harm solely for power?', **common)
        if not picked:
            continue
        subject = engine.state.actors[picked[0]]
        labels = {'genuine': 'Genuine restraint: this Foundation use preserves or spares this creature; no cruelty, staged farming, or false surrender',
                  'unsafe': 'Mercy is unsafe or the surrender is false',
                  'farming': 'Staged, cruel, or farming for power', 'unknown': 'The scene or intent is unknown'}
        declarant = public_scene_declarant(engine, owner, subject, owner.entity_id)
        chooser = declarant or owner
        testimony = f'For {owner.display_name}, ' if chooser is not owner else ''
        chosen = ask(engine, intent, checkpoint_id(engine, 'ASH_MERCY_CONTEXT', spend.sequence),
            chooser, CONTEXT, list(labels), labels=labels,
            automatic_options=None if declarant else ['unknown'],
            preferred=['unknown'], allow_decline=True, default='decline', target_id=subject.entity_id,
            prompt=f'{testimony}Ash Mercy Boundary after {action_name}: did {owner.display_name} genuinely choose to preserve or spare {subject.display_name}? Confirm only what you know, and decline if unsure.', **common)
        context = chosen[0] if chosen else 'unknown'
        engine._append_event('PASSIVE_TRIGGERED', FEATURE, actor_id=owner.entity_id,
            target_ids=(subject.entity_id,), payload={'fact_kind': 'ash_mercy_restraint',
                'spend_sequence': spend.sequence, 'intent_id': intent.intent_id,
                'source_definition_id': spend.source_definition_id, 'declarant': chooser.entity_id,
                'context': context, 'log': f'Ash Mercy Boundary after {action_name}: {labels[context]} ({subject.display_name}).'})
        if context != 'genuine':
            continue
        from ..target_knowledge import knowledge
        # No alive/ally/willing filter is printed. Include defeated creatures,
        # but never reveal an unobserved enemy's current position or presence.
        recipients = [a for a in engine.state.actors.values()
                      if (a is owner or engine._distance_actor_to_actor(owner, a) <= 30)
                      and (known := knowledge(engine, owner, a)) is not None and known.mode == 'DIRECT']
        preferred = sorted(recipients, key=lambda a: (a.team_id != owner.team_id, a.temporary_hp, a.entity_id))
        target = ask(engine, intent, checkpoint_id(engine, 'ASH_MERCY_TARGET', spend.sequence),
            owner, TARGET, [a.entity_id for a in recipients],
            labels={a.entity_id: f'{a.display_name}: {row["pb"]} temporary Hit Points (ordinary replacement; no stacking)'
                    for a in recipients}, preferred=[a.entity_id for a in preferred],
            allow_decline=True, default='decline', target_id=subject.entity_id,
            prompt=f'Ash Mercy Boundary after {action_name} spares {subject.display_name}: choose yourself or one creature within 30 feet for {row["pb"]} temporary Hit Points. No additional action or resource.', **common)
        if target:
            engine._grant_temp_hp(engine.state.actors[target[0]], int(row['pb']), FEATURE, owner.entity_id)
