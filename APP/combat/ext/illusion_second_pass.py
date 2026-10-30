"""Printed prison endings and permanent creation through existing extension hooks.

Phantom Prison keeps an exact-instance link to its initial Speed 0 and False
Premise. Speed 0 ends at the end of the target's next turn; the prison itself
keeps offering its Intelligence repeat save and Investigation Study until it
ends. Recognition/removal of one prison never clears another caster's hold.
Permanent Illusion modifies creation, rather than an illusion already created.
"""
from __future__ import annotations

from typing import Any
from ..action_variants import choice, cost_delta, with_variant
from . import effect, hook, note

PRISON = 'tianxia.talent.illusion.phantom_prison'
PERMANENT = 'tianxia.talent.illusion.permanent_illusion'
HOLD = 'condition:typed.phantom_prison'


@effect('illusion_phantom_prison')
def imprison(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import mark_condition_id, run_effects
    from .effect_durations import token
    from .condition_ownership import refresh_owned
    target = ctx.target
    if target is None:
        return
    refresh_owned(ctx.engine, target, HOLD, ctx.actor.entity_id, ctx.source)
    ctx.engine._apply_condition(target, HOLD, ctx.source, ctx.actor.entity_id,
        expires_on=ctx.expires_on(), data={'label': 'Phantom Prison: repeat an Intelligence save at each turn end, or use Study to escape',
          'repeat_save': {'ability': 'INT', 'dc': int(ctx.numbers.get('save_dc') or 10), 'when': 'end'}})
    iid = next(i for i, c in target.conditions.items() if c.condition_id == HOLD and c.source_definition_id == ctx.source
               and c.source_actor_id == ctx.actor.entity_id)
    ctx.engine._apply_condition(target, 'condition:typed.phantom_prison_speed', ctx.source, ctx.actor.entity_id,
        expires_on=token('end', target.entity_id, int(target.turns_started or 0) + 1),
        data={'rule': {'speed_zero': True}, 'prison_instance': iid, 'label': 'Phantom Prison: Speed 0 until the end of your next turn'})
    premise = mark_condition_id('False Premise', ctx.actor.entity_id)
    ctx.engine._remove_condition(target, premise, ctx.source)
    ctx.engine._apply_condition(target, premise, ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'prison_instance': iid, 'label': f'False Premise from {ctx.actor.display_name} (Phantom Prison)'})
    run_effects(ctx, [{'type': 'escape_option', 'guards': ['phantom_prison'], 'kind': 'check',
        'abilities': ['INT'], 'skill': 'Investigation', 'skill_proficiency': True, 'name': 'Study Phantom Prison'}])


@hook('event')
def prison_ended(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from .condition_ownership import remove_instance
    payload = kwargs.get('payload') or {}
    if event_type != 'CONDITION_REMOVED' or not payload.get('instance_id'):
        return
    iid = payload.get('instance_id')
    for aid in kwargs.get('target_ids') or ():
        target = engine.state.actors.get(aid)
        if target is None:
            continue
        for key, condition in list(target.conditions.items()):
            if condition.data.get('prison_instance') == iid:
                remove_instance(engine, target, key, condition.source_definition_id)


@hook('compile_actions')
def permanent_glamers(info: dict[str, Any]) -> list[Any] | None:
    """Every represented glamer keeps its original ending conditions and costs."""
    import copy
    import re
    from ..factory_compiler import RESOURCE_IDS
    if PERMANENT not in info['owned_ids']:
        return None
    from ..rule_help import printed_rule_text
    pool = RESOURCE_IDS.get(str(info.get('primary') or 'qi'), 'resource:core.qi')
    out = []
    for action in info['actions']:
        typed = (action.parameters or {}).get('typed') or {}
        source = str(typed.get('source') or '')
        if not re.search(r'^Tags:.*\bGlamer\b', printed_rule_text(source), re.M) or action.economy.value != 'ACTION':
            continue
        clone = copy.deepcopy(typed)
        clone['duration'] = {'kind': 'until_removed', 'concentration': False}
        clone['riders'] = list(typed.get('riders') or [])
        def extend(rows):
            for eff in rows:
                if eff.get('type') in {'condition', 'advantage', 'disadvantage', 'ongoing', 'mark'}:
                    eff['duration'] = {'kind': 'until_removed'}
                    eff['expires_on'] = 'UNTIL_REMOVED'
                for branch in ('on_fail', 'on_success', 'effects'):
                    extend(eff.get(branch) or [])
        extend(clone.get('effects') or [])
        costs = (*action.costs, (pool, 8))
        out.append(with_variant(action.model_copy(update={'source_definition_id': action.source_definition_id + '.permanent',
            'display_name': action.display_name + ' + Permanent Illusion (8 CP)',
            'costs': costs,
            'parameters': {**action.parameters, 'typed': clone, 'illusion_permanent': True,
                'description': 'Create this glamer for its usual cost plus 8 cultivation points. It lasts without Concentration until dispelled, dismissed, or ended by its own rules.'}}),
            action.source_definition_id, action.display_name, [choice('duration', 'permanent', 'Permanent Illusion', cost_delta(costs, action.costs))]))
    if out:
        from ..gate2_runtime_models import ActionDefinition, EconomyKind
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.dismiss_permanent_glamer",
          display_name='Dismiss Permanent Glamer', owner_id=info['actor_id'], economy=EconomyKind.NONE,
          resolution_kind='TYPED', target_kind='SELF', parameters={'illusion_permanent_dismiss': True,
          'typed': {'source': PERMANENT, 'effects': [{'type': 'illusion_dismiss_permanent'}], 'numbers': info['numbers'],
                    'duration': {'kind': 'instant'}, 'riders': []},
          'description': 'No action or cost: choose one permanent glamer you created to dismiss.'}))
    return out


def permanent_instances(engine: Any, owner: Any) -> dict[str, list[tuple[Any, str, str]]]:
    found = {}
    for target in engine.state.actors.values():
        for kind, rows in (('condition', target.conditions), ('modifier', target.modifiers)):
            for iid, held in rows.items():
                action = engine.action_catalog.get(held.source_definition_id)
                if held.source_actor_id == owner.entity_id and action and action.parameters.get('illusion_permanent'):
                    found.setdefault(held.source_definition_id + '|' + target.entity_id, []).append((target, kind, iid))
    return found


@hook('candidate_allowed')
def dismiss_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action and action.parameters.get('illusion_permanent_dismiss'):
        return bool(permanent_instances(engine, actor))
    return None


@effect('illusion_dismiss_permanent')
def dismiss_permanent(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import CHOICE, ask, checkpoint_id
    from .condition_ownership import remove_instance
    found = permanent_instances(ctx.engine, ctx.actor)
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'PERMANENT_GLAMER', ctx.actor.entity_id),
        ctx.actor, CHOICE + 'illusion.dismiss_permanent', list(found),
        labels={key: ctx.engine.action_catalog[key.split('|')[0]].display_name + ' on ' + found[key][0][0].display_name for key in found},
        prompt='Choose a permanent glamer you created to dismiss.', allow_decline=True)
    for key in picked:
        source = key.split('|')[0]
        for target, kind, iid in found[key]:
            if kind == 'condition':
                remove_instance(ctx.engine, target, iid, source)
            else:
                target.modifiers.pop(iid, None)
                ctx.engine._append_event('MODIFIER_REMOVED', source, actor_id=ctx.actor.entity_id,
                    target_ids=(target.entity_id,), payload={'modifier_id': iid, 'reason': 'DISMISSED'})
        note(ctx.engine, source, ctx.actor, 'The permanent glamer is dismissed.')

# Successful represented observation checks use the shared d20 rewrite registry.
# Its default-inert choose operation allows the printed repeat even on resistance.
from .d20_rewrite import Rule, register
WITNESS = 'tianxia.talent.illusion.unreliable_witness'


def witness_guard(engine: Any, holder: Any, rc: Any) -> bool:
    from . import ai_controlled
    from ..target_knowledge import can_see
    scope = engine.d20_context(rc.roll) or {}
    skill = str(scope.get('skill') or '').lower()
    if skill not in {'perception', 'insight', 'investigation'}:
        return False
    if ai_controlled(engine, holder.actor):
        return rc.roller.team_id != holder.actor.team_id and can_see(engine, holder.actor, rc.roller)
    return True


def witness_repeat(engine: Any, holder: Any, rc: Any) -> int:
    from .effect_durations import token
    from ..typed_executor import mark_condition_id
    repeated = engine.roller.raw_d20(modifier=rc.roll.modifier, actor_id=rc.roller.entity_id,
                                    reason=rc.roll.reason, mode=rc.roll.mode)
    engine._record_roll(repeated)
    dc = 8 + int(holder.numbers.get('pb') or 2) + int(holder.numbers.get('key_mod') or 0)
    save = engine._roll_save(rc.roller, 'WIS', dc, WITNESS,
                            roll_context={'source_actor_id': holder.actor.entity_id, 'named': ['false_premise'],
                                          'include_stored_save_bonuses': True})
    if save is not None and save.total < dc:
        condition = mark_condition_id('False Premise', holder.actor.entity_id)
        engine._remove_condition(rc.roller, condition, WITNESS)
        engine._apply_condition(rc.roller, condition, WITNESS, holder.actor.entity_id,
            expires_on=token('start', holder.actor.entity_id, int(holder.actor.turns_started or 0) + 1),
            data={'label': f'False Premise from {holder.actor.display_name} (Unreliable Witness)'})
        return min(int(rc.natural), int(repeated.natural_result))
    return int(rc.natural)


register(Rule('illusion_witness', 'Unreliable Witness', feature=WITNESS, rolls=('check',),
    who='any', range_ft=60, when='succeeded', reaction=True, costs=((('cp', 2),),),
    checkpoint='D20_REWRITE_ROLL', op='choose', choose=witness_repeat, guard=witness_guard,
    ai=lambda engine, holder, rc: rc.roller.team_id != holder.actor.team_id))
