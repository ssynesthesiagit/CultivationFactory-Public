"""Red Execution Discipline: source-owned mark triggers and one chosen damage die.

Uses fresh_zero_hp, event and the two documented sequential damage-roll adjustments.
Only actual hit contexts qualify. The Full Cultivation Session receipt persists
through turns/reloads; an explicit completed-session source effect clears it.
"""
from . import hook, effect, note
from .needle import ask, checkpoint_id
from .passive_rows import row_of

FEATURE = 'insight.red-execution-discipline'
BLOCK = 'red_execution'
FOCUS = 'resource:core.martial_focus'
USED = 'condition:typed.red_execution_used'
RECOVER = 'choice:needle.red_execution_focus'
DIE = 'choice:needle.red_execution_die'
RESULT = 'choice:needle.red_execution_result'
SOURCES = {'TAL_AXES_HEADSMAN_S_MANDATE', 'TAL_AXES_RENDING_HEW'}


@hook('compile_block')
def compile_rows(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'kind': BLOCK, 'choice_owner': 1,
                 'player_outcome': 'Recover absent Martial Focus when your Execution Mark target falls, teleports or turns Invisible; once between Full Cultivation Sessions, reroll one damage die of Headsman’s Mandate or Rending Hew and choose either result.'}]
    return None


@hook('choice_reactors')
def reactors(engine):
    return tuple(a.entity_id for a in engine.state.actors.values()
                 if row_of(engine, a.entity_id, BLOCK, BLOCK))


def marked(target, owner):
    from ..typed_executor import mark_condition_id
    cid = mark_condition_id('Execution Mark', owner.entity_id)
    return any(c.condition_id == cid and c.source_actor_id == owner.entity_id
               for c in target.conditions.values())


@hook('event', nested=True)
def recovery(engine, event_type, kwargs):
    payload = kwargs.get('payload') or {}
    trigger = None
    if event_type == 'MOVEMENT_COMMITTED' and payload.get('teleport'):
        trigger = 'teleports'
    elif event_type == 'CONDITION_APPLIED' and payload.get('condition_id') in {
            'condition:typed.invisible', 'condition:core.invisible'}:
        trigger = 'becomes Invisible'
    if trigger is None:
        return
    targets = kwargs.get('target_ids') or ((kwargs.get('actor_id'),) if event_type == 'MOVEMENT_COMMITTED' else ())
    for tid in targets:
        target = engine.state.actors.get(tid)
        if target is None:
            continue
        if trigger == 'becomes Invisible':
            # A refresh while already Invisible is not becoming Invisible.
            boundary = getattr(kwargs.get('originating_event'), 'sequence', engine.state.event_sequence)
            active = set()
            for event in engine.events:
                if event.sequence >= boundary:
                    break
                if tid not in event.target_ids or event.payload.get('condition_id') not in {
                        'condition:typed.invisible', 'condition:core.invisible'}:
                    continue
                iid = event.payload.get('instance_id')
                if event.event_type == 'CONDITION_APPLIED':
                    active.add(iid)
                elif event.event_type == 'CONDITION_REMOVED':
                    active.discard(iid)
            if active:
                continue
        offer_focus(engine, target, trigger, kwargs.get('source_definition_id') or '')


@hook('fresh_zero_hp')
def falling(engine, target, attacker_id, source_id):
    # This checkpoint handles DYING, CONSCIOUS and removed map creatures alike;
    # LIFE_STATE_CHANGED's fresh flag represents only CONSCIOUS-at-zero entry.
    offer_focus(engine, target, 'drops to 0 Hit Points', source_id)


def offer_focus(engine, target, trigger, source):
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if (not row_of(engine, owner.entity_id, BLOCK, BLOCK) or not owner.active
                or owner.current_hp <= 0 or owner.resources.get(FOCUS, 0) != 0
                or FOCUS not in owner.resources or not marked(target, owner)):
            continue
        action = engine.action_catalog.get(source)
        action_name = action.display_name if action else 'the triggering effect'
        picked = ask(engine, getattr(engine, '_active_intent', None),
            checkpoint_id(engine, 'RED_EXECUTION_FOCUS', owner.entity_id, target.entity_id), owner,
            RECOVER, ['recover'], labels={'recover': 'Regain Martial Focus; no action or Reaction'},
            preferred=['recover'], allow_decline=True, target_id=target.entity_id,
            prompt=f'Red Execution Discipline: {action_name} causes {target.display_name}, bearing your Execution Mark, to {trigger}. Regain your absent Martial Focus? No action, Reaction or cultivation point cost.')
        if picked:
            engine._gain_resource(owner, FOCUS, 1, FEATURE)
            note(engine, FEATURE, owner, f'Red Execution Discipline: regain Martial Focus after {target.display_name} {trigger}.', targets=(target,))


def reroll(engine, actor, target, dice, roll, intent, source, qualified):
    from ..gate2_runtime_models import DiceSpec
    if (not qualified or not row_of(engine, actor.entity_id, BLOCK, BLOCK)
            or target is None or not marked(target, actor) or not isinstance(dice, DiceSpec)
            or not roll.dice or any(c.condition_id == USED for c in actor.conditions.values())):
        return None
    action = engine.action_catalog.get(source)
    name = action.display_name if action else 'the axe attack'
    options = [str(i) for i in range(len(roll.dice))]
    picked = ask(engine, intent, checkpoint_id(engine, 'RED_EXECUTION_DIE', roll.roll_id), actor,
        DIE, options, labels={str(i): f'Reroll damage die {i + 1} (currently {value} on a d{dice.sides})'
                             for i, value in enumerate(roll.dice)},
        preferred=[str(min(range(len(roll.dice)), key=lambda i: roll.dice[i]))],
        allow_decline=True, target_id=target.entity_id,
        prompt=f'Red Execution Discipline: {name} hit {target.display_name}, bearing your Execution Mark. Reroll one damage die and then choose either result? No extra cost; once between Full Cultivation Sessions.')
    if not picked:
        return None
    index = int(picked[0])
    replacement = engine.roller.roll(DiceSpec(count=1, sides=dice.sides, modifier=0),
        actor_id=actor.entity_id, reason='DAMAGE_REROLL:' + FEATURE)
    engine._record_roll(replacement)
    engine._append_event('DAMAGE_ROLLED', FEATURE, actor_id=actor.entity_id,
        target_ids=(target.entity_id,), payload={**replacement.model_dump(mode='json'),
            'original_roll_id': roll.roll_id, 'die_index': index})
    original, new = int(roll.dice[index]), int(replacement.total)
    selected = ask(engine, intent, checkpoint_id(engine, 'RED_EXECUTION_RESULT', roll.roll_id), actor,
        RESULT, ['original', 'new'], labels={'original': f'Keep the original result ({original})',
                                           'new': f'Use the rerolled result ({new})'},
        preferred=['new' if new > original else 'original'], allow_decline=False,
        target_id=target.entity_id,
        prompt=f'Red Execution Discipline: choose the damage die result for {name} against {target.display_name}. Original {original}; rerolled {new}. This spends your use until your next Full Cultivation Session.')
    delta = (new if selected and selected[0] == 'new' else original) - original
    engine._apply_condition(actor, USED, FEATURE, actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'label': 'Red Execution Discipline: damage reroll used until your next Full Cultivation Session'})
    note(engine, FEATURE, actor, f'Red Execution Discipline: chose a damage die result for {name} against {target.display_name}.',
         targets=(target,), original_roll_id=roll.roll_id, die_index=index, damage_adjustment=delta)
    from ..damage_roll_replacements import DieReplacement
    return DieReplacement({index: new if selected and selected[0] == 'new' else original})


@hook('confirmed_damage_roll_adjustment')
def weapon_die(engine, actor, target, spec, intent, source, roll):
    action = engine.action_catalog.get(source)
    typed = (action.parameters.get('typed') or {}) if action else {}
    if spec.get('fixed_damage') is not None:
        return None
    modifiers = str((typed.get('modifier') or {}).get('id') or '').split('+')
    return reroll(engine, actor, target, spec.get('damage'), roll, intent, source,
                  typed.get('source') in SOURCES or 'TAL_AXES_RENDING_HEW' in modifiers)


@hook('typed_damage_roll_adjustment')
def attached_die(ctx, dice, roll):
    source = str(ctx.effect_source or '').removeprefix('passive:')
    qualified = (source in SOURCES or ctx.typed.get('source') in SOURCES)
    return reroll(ctx.engine, ctx.actor, ctx.target, dice, roll, ctx.intent,
                  ctx.action.source_definition_id, qualified and ctx.attack_damage_context is not None)


@effect('cultivation_session_completed')
def completed_session(ctx, row):
    """Explicit source bridge, not an action granting an in-combat rest."""
    if row.get('completed') == 1:
        subject = ctx.target or ctx.actor
        ctx.engine._remove_condition(subject, USED, ctx.source)
