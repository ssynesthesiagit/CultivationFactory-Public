"""Sniper follow-ups that hang on a Snipe Shot (riders lane 4, 2026-09-29).

Source (owner text: authority/typed_mechanics/rules_text.json TAL_SNIPER_*; the Sphere Compendium's Sniper chapter):
  Breath-Held Shot: "If you take no movement on your turn before making a Snipe Shot, you may spend 1 CP or expend Martial Focus to
  add your Proficiency Bonus to the attack's damage. If the attack misses, you may keep the CP or Martial Focus spent, but your
  Speed becomes 0 until the start of your next turn."  The variant of Snipe Shot that Breath-Held Shot makes (the modifier's
  own payment, combat/factory_compiler.py) is offered only before the shooter has moved, and a miss optionally gives the payment back and
  holds the shooter still (condition ``still_aim``, combat/rules/typed_conditions.json), through the transactional attack_result hook.
  Hindering Projectile: "On a failed save, the target has Disadvantage on attack rolls until it uses an Action to remove the
  projectile or correct the lodged injury."  Condition ``hindered``; a "Remove the projectile" Action (any creature's, offered
  only while hindered) ends it. "Sufficient healing" has no printed numeric threshold:
  the GM decides whether healing seals the lodged wound. Ordinary HP restoration
  alone does not establish that qualification and never automatically removes it.
  Push Shot: "If this movement forces the target into a solid object, it instead falls Prone and the movement ends."  The
  push (hook ``collision``) stopped short against something that is not a creature; the target falls Prone.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

BREATH = "TAL_SNIPER_BREATH_HELD_SHOT"
STILL = "condition:typed.still_aim"
HINDERED = "condition:typed.hindered"


def _typed(action: Any) -> dict[str, Any]:
    return (getattr(action, "parameters", None) or {}).get("typed") or {}


def _paid_by(typed: dict[str, Any]) -> str:
    return str((typed.get("modifier") or {}).get("id") or "")


@hook("candidate_allowed")
def breath_held_before_moving(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if _paid_by(_typed(action)) != BREATH:
        return None
    from .hold_still import moved_ft

    return moved_ft(engine, actor) == 0


@hook("attack_result")
def breath_held_miss(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    from .needle import CHOICE, ask, checkpoint_id

    if hit or _paid_by(ctx.typed) != BREATH or ctx.intent is None:
        return
    engine, actor = ctx.engine, ctx.actor
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "breath_refund", actor.entity_id, target.entity_id),
                 actor, CHOICE + "breath_held_refund", ["Keep payment"], allow_decline=True,
                 target_id=target.entity_id, name="Breath-Held Shot",
                 prompt=f"Breath-Held Shot: {ctx.action.display_name} missed {target.display_name}. "
                        "Keep the CP or Martial Focus spent and set your Speed to 0 until your next turn?")
    if not picked:
        return
    for resource_id, amount in ctx.action.costs:
        if resource_id in actor.resources and amount > 0:
            engine._gain_resource(actor, resource_id, int(amount), ctx.source)  # "you may keep the CP or Martial Focus spent"
    engine._apply_condition(actor, STILL, ctx.source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": "Held still by a missed Breath-Held Shot (Speed 0)"})


@hook("compile_actions")
def remove_projectile(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.remove_projectile", display_name="Remove the projectile", owner_id=info["actor_id"],
        economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "remove_lodged"}], "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 1, "requires_condition": HINDERED})]


@hook("button_description")
def removal_description(row: dict[str, Any]) -> str | None:
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    if any(eff.get("type") == "remove_lodged" for eff in effects):
        return ("Action: remove one Hindering Projectile from yourself or correct its lodged injury. No check or cultivation points are required. "
                "That projectile no longer gives you disadvantage on attack rolls; other lodged projectiles still affect you.")
    return None


@effect("remove_lodged")
def remove_lodged(ctx: Any, eff: dict[str, Any]) -> None:
    from .needle import CHOICE, ask, checkpoint_id
    from .riders_shared import remove_benefit_condition

    held = [c for c in ctx.actor.conditions.values() if c.condition_id == HINDERED]
    if not held:
        return
    condition = held[0]
    if len(held) > 1:
        labels = {c.instance_id: "Hindering Projectile from " + ctx.engine.state.actors[c.source_actor_id].display_name
                  for c in held}
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "remove_projectile", ctx.actor.entity_id),
                     ctx.actor, CHOICE + "remove_projectile", list(labels), labels=labels, name="Hindering Projectile",
                     prompt=f"Remove the projectile: {ctx.actor.display_name} chooses one Hindering Projectile to remove.")
        if not picked:
            return
        condition = next(c for c in held if c.instance_id == picked[0])
    remove_benefit_condition(ctx.engine, ctx.actor, condition, "PROJECTILE_REMOVED")


PUSH_SHOT = "TAL_SNIPER_PUSH_SHOT"

WAIT = "TAL_SNIPER_HUNDRED_BREATH_WAIT"
WAIT_BLOCK = "sniper_wait"
OBSERVING = "condition:typed.sniper_observing"
WAIT_MARK = "condition:typed.sniper_wait"
FOCUS = "resource:core.martial_focus"


@hook("compile_block")
def compile_wait(block, spec, row, numbers):
    return [{**row, "block": WAIT_BLOCK}] if block == WAIT_BLOCK else None


@hook("compile_actions")
def wait_actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    if not any(r.get("block") == WAIT_BLOCK for r in info.get("passives", [])):
        return None
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.sniper_wait.{kind}",
        display_name=label, owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind="TYPED", target_kind="SELF", costs=(), parameters={
            "description": description, "expected_damage": 1,
            "typed": {"source": WAIT, "effects": [{"type": "sniper_wait", "kind": kind}],
                      "numbers": info['numbers'], "duration": {"kind": "instant"}, "riders": []}})
        for kind,label,description in (
            ('observe', 'Observe for Hundred-Breath Wait',
             'Choose one creature you can see to observe without attacking it for a full round. No Action, Reaction, Focus or cultivation points.'),
            ('mark', 'Mark with Hundred-Breath Wait',
             'After observing for a full round, mark that creature for one minute. Your next Snipe Shot at it adds your Proficiency Bonus to damage; a miss regains Martial Focus. Attacking another target ends the mark. No action or resource cost.'))]


def _wait_condition(actor, kind):
    return next((c for c in actor.conditions.values() if c.condition_id == kind
                 and c.data.get('native_wait') == 1), None)


def _clear_wait(engine, actor, kind):
    from .condition_ownership import remove_instance
    for iid,c in list(actor.conditions.items()):
        if c.condition_id == kind and c.data.get('native_wait') == 1:
            remove_instance(engine, actor, iid, WAIT)


@hook('candidate_allowed')
def wait_available(engine, actor, candidate, action):
    rows = _typed(action).get('effects', [])
    row = next((r for r in rows if r.get('type') == 'sniper_wait'), None)
    if row is None:
        return None
    from ..stealth import sees
    if row['kind'] == 'observe':
        return any(a.active and a.entity_id != actor.entity_id and sees(engine, actor, a)
                   for a in engine.state.actors.values())
    watching = _wait_condition(actor, OBSERVING)
    target = engine.state.actors.get(watching.data['target']) if watching else None
    return bool(target and target.active and actor.turns_started > watching.data['turn'] and sees(engine, actor, target))


@effect('sniper_wait')
def begin_wait(ctx, row):
    from .rider_choices import pick
    from ..stealth import sees
    from .ability_source import has_row
    if not has_row(ctx.engine, ctx.actor.entity_id, WAIT_BLOCK):
        return
    if row['kind'] == 'observe':
        targets = [a for a in ctx.engine.state.actors.values() if a.active
                   and a.entity_id != ctx.actor.entity_id and sees(ctx.engine, ctx.actor, a)]
        chosen = pick(ctx.engine, ctx.actor, 'sniper_wait_observe', 'Hundred-Breath Wait',
            [a.entity_id for a in targets], labels={a.entity_id:a.display_name for a in targets},
            subject=ctx.actor, optional=False, trigger='Choose a creature to observe for one full round without attacking it',
            prompt_context={'cost':'No Action, Reaction, Martial Focus or cultivation points'})
        if not chosen:return
        _clear_wait(ctx.engine, ctx.actor, OBSERVING)
        ctx.engine._apply_condition(ctx.actor, OBSERVING, ctx.source, ctx.actor.entity_id, expires_on=None,
            data={'native_wait':1,'target':chosen[0],'turn':ctx.actor.turns_started,
                  'label':'Hundred-Breath Wait: observing one creature without attacking it'})
    else:
        _claim_wait(ctx.engine,ctx.actor,ctx.source,ctx.numbers)


def _claim_wait(engine, actor, source, numbers):
    from ..stealth import sees
    from ..typed_executor import clock_expiry
    watching = _wait_condition(actor, OBSERVING)
    if watching is None or actor.turns_started <= watching.data['turn']:return
    target = engine.state.actors.get(watching.data['target'])
    if target is None or not target.active or not sees(engine,actor,target):return
    _clear_wait(engine,actor,WAIT_MARK)
    _clear_wait(engine,actor,OBSERVING)
    engine._apply_condition(actor,WAIT_MARK,source,actor.entity_id,
        expires_on=clock_expiry(engine,'minutes',1),data={'native_wait':1,'target':target.entity_id,
            'pb':int(numbers.get('pb') or actor.proficiency_bonus),
            'label':f'Hundred-Breath Wait: next Snipe Shot against {target.display_name} adds Proficiency Bonus damage; a miss regains Martial Focus'})


@hook('turn_start_choice')
def full_round_observed(engine,actor):
    from ..stealth import sees
    from .rider_choices import pick
    watching = _wait_condition(actor,OBSERVING)
    target = engine.state.actors.get(watching.data['target']) if watching else None
    if not target or not target.active or actor.turns_started <= watching.data['turn'] or not sees(engine,actor,target):
        return
    chosen = pick(engine,actor,'sniper_wait_mark','Hundred-Breath Wait',['mark'],subject=target,
        trigger='You observed this creature without attacking it for a full round',
        labels={'mark':'Mark it for one minute: next Snipe Shot adds Proficiency Bonus damage; a miss regains Martial Focus'},
        prompt_context={'cost':'No Action, Reaction, Martial Focus or cultivation points'})
    if chosen:_claim_wait(engine,actor,watching.source_definition_id,{})


@hook('state_event')
def wait_interrupted(engine, event):
    for actor in engine.state.actors.values():
        watching = _wait_condition(actor, OBSERVING)
        marked = _wait_condition(actor, WAIT_MARK)
        if watching and event.event_type == 'ATTACK_ROLLED' and event.actor_id == actor.entity_id and watching.data['target'] in event.target_ids:
            _clear_wait(engine,actor,OBSERVING)
        elif watching and event.event_type in ('MOVEMENT_COMMITTED','CONDITION_APPLIED','CONDITION_REMOVED','ACTOR_DEFEATED'):
            from ..stealth import sees
            target = engine.state.actors.get(watching.data['target'])
            if target is None or not target.active or not sees(engine,actor,target):
                _clear_wait(engine,actor,OBSERVING)
        if marked and event.event_type == 'ATTACK_ROLLED' and event.actor_id == actor.entity_id and event.target_ids and marked.data['target'] not in event.target_ids:
            _clear_wait(engine,actor,WAIT_MARK)


@hook('attack_damage_bonus')
def wait_damage(ctx, target, effect):
    marked = _wait_condition(ctx.actor, WAIT_MARK)
    if marked and ctx.typed.get('maneuver') == 'snipe' and target.entity_id == marked.data['target']:
        return int(marked.data['pb'])
    return None


@hook('attack_result')
def wait_shot_complete(ctx, target, hit, critical):
    marked = _wait_condition(ctx.actor, WAIT_MARK)
    if not marked or ctx.typed.get('maneuver') != 'snipe' or target.entity_id != marked.data['target']:
        return
    if not hit and ctx.actor.resources.get(FOCUS,0) == 0:
        ctx.engine._gain_resource(ctx.actor,FOCUS,1,WAIT)
    _clear_wait(ctx.engine,ctx.actor,WAIT_MARK)


@hook("collision")
def push_shot_into_an_object(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    if _paid_by(ctx.typed) != PUSH_SHOT or not target.active:
        return
    if any(other.active and other.entity_id != target.entity_id and other.position == blocked_at for other in ctx.engine.state.actors.values()):
        return  # a creature in the way is not a solid object
    ctx.engine._apply_condition(target, "condition:typed.prone", ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED")
