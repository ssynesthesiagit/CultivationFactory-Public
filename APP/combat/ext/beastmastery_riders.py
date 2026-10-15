"""Damage ends the declared Beast Tamer effect when its caster or an ally harms it.

Owner source: authority/typed_mechanics/rules_text.json, Beast Tamer: "The
effect ends early if: you or your allies harm the creature". The opt-in
``rider_break_on_allied_damage`` wraps its failed-save branch and records the
new condition/modifier instances. Positive HP damage or Temporary HP absorbed
from the caster's current team releases those exact instances. It preserves
unrelated effects. Non-damage harm and the other printed early endings remain
GM riders; this block does not decide Tame eligibility or command authority.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import effect, hook

PREFIX = "condition:typed.rider_break_on_allied_damage."
TEAMWORK = "TAL_BEASTMASTERY_DEFENSIVE_TEAMWORK"


def teamwork_beasts(engine, owner):
    """The owner's active Beast Allies whose melee reach includes the owner."""
    from ..typed_reactions import physical_melee_reach
    return [beast for beast in engine.state.actors.values()
            if beast.active and beast.owner_id == owner.entity_id and beast.team_id == owner.team_id
            and str((beast.summon or {}).get("group", "")).startswith(("beast", "mount"))
            and engine._distance_actor_to_actor(owner, beast) <= int(physical_melee_reach(engine, beast) or 5)]


@hook("row_allowed")
def teamwork_reach(engine, actor, row):
    if row.get("feature_id") == TEAMWORK:
        return bool(teamwork_beasts(engine, actor))


@hook("ally_row_allowed")
def teamwork_subject(engine, reactor, subject, row):
    if row.get("feature_id") == TEAMWORK:
        return any(beast.entity_id == subject.entity_id for beast in teamwork_beasts(engine, reactor))


@hook("reaction_reach")
def teamwork_printed_reach(engine, reactor, other, row):
    if row.get("feature_id") == TEAMWORK:
        return bool(teamwork_beasts(engine, reactor))


ACCOMPLICE = "TAL_BEASTMASTERY_ACCOMPLICE"


def accomplice_partners(engine: Any, owner: Any) -> list[Any]:
    """The owner's represented tame beasts/mounts within their melee reach.

    Accomplice uses only existing Beast Ally ownership, never nearby humanoid
    allies or unrelated summons. Weapon reach includes the ordinary 5-foot
    unarmed reach; spending a Reaction does not change that reach.
    """
    reach = max([5, *(int(a.reach_ft or 5) for a in engine.action_catalog.values()
                     if a.owner_id == owner.entity_id and a.target_kind == 'HOSTILE_ENTITY'
                     and not a.range_ft and (a.parameters or {}).get('typed', {}).get('weapon'))])
    return sorted((beast for beast in engine.state.actors.values()
                   if beast.active and beast.owner_id == owner.entity_id and beast.team_id == owner.team_id
                   and str((beast.summon or {}).get('group', '')).startswith(('beast', 'mount'))
                   and engine._distance_actor_to_actor(owner, beast) <= reach), key=lambda b: b.entity_id)


@hook('candidate_allowed')
def accomplice_available(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and action.owner_id == actor.entity_id and (action.parameters or {}).get('typed', {}).get('source') == ACCOMPLICE:
        return False if not accomplice_partners(engine, actor) else None
    return None


@hook('ally_subjects')
def accomplice_recipient(ctx: Any, spec: dict[str, Any]) -> list[Any] | None:
    if ctx.typed.get('source') != ACCOMPLICE or spec.get('recipient_choice') != 'accomplice':
        return None
    from .needle import CHOICE, ask, checkpoint_id, incapacitated
    from .choice_prompt import action_context

    partners = accomplice_partners(ctx.engine, ctx.actor)
    # Only the helper must be able to take the Help Action. A beast that
    # cannot act may still receive Help from its owner.
    options = {f'help:{beast.entity_id}': (ctx.actor, beast) for beast in partners if not incapacitated(ctx.actor)}
    options.update({f'receive:{beast.entity_id}': (beast, ctx.actor) for beast in partners if not incapacitated(beast)})
    from .help_policy import allowed
    options = {key: pair for key, pair in options.items() if allowed(ctx.engine, *pair)}
    labels = {key: f'{helper.display_name} helps {recipient.display_name}: Advantage on one attack this turn'
              for key, (helper, recipient) in options.items()}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'ACCOMPLICE', ctx.actor.entity_id), ctx.actor,
                 CHOICE + 'accomplice', list(options), labels=labels, name='Accomplice', feature_id=ACCOMPLICE,
                 prompt=f'Accomplice: who helps whom during {ctx.actor.display_name}\'s Help action?',
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, ctx.actor))
    selected = options.get(picked[0]) if picked else None
    if selected is None or incapacitated(selected[0]):
        return []
    return [selected[1]]


@hook('decision_text')
def accomplice_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    if context.get('reaction_source_id') != 'choice:needle.accomplice':
        return None
    owner = engine.state.actors.get(context.get('reactor_id'))
    if owner is None or not any(a.owner_id == owner.entity_id and (a.parameters or {}).get('typed', {}).get('source') == ACCOMPLICE
                                for a in engine.action_catalog.values()):
        return None
    return {'feature_id': ACCOMPLICE, 'cost': 'Action already spent; no resource cost',
            'summary': 'You or one of your Beast Allies within reach helps the other. Only the assisted participant gains Advantage on one attack roll before the end of your turn.',
            'limits': 'Choose one Beast Ally and who helps whom. The advantage ends after one attack or at the end of your current turn.'}


@effect("rider_break_on_allied_damage")
def bind_harm_ending(ctx: Any, spec: dict[str, Any]) -> None:
    from .. import typed_executor as te

    for subject in ctx.targets or ([ctx.target] if ctx.target else []):
        before_c, before_m = set(subject.conditions), set(subject.modifiers)
        te.run_effects(replace(ctx, targets=[subject], target=subject), spec.get("effects") or [])
        conditions, modifiers = sorted(set(subject.conditions) - before_c), sorted(set(subject.modifiers) - before_m)
        if conditions or modifiers:
            ctx.engine._apply_condition(subject, PREFIX + te._mark_slug(spec["name"]), ctx.source, ctx.actor.entity_id,
                                        expires_on=te.effect_expiry(ctx, spec, subject, condition=True),
                                        data={"conditions": conditions, "modifiers": modifiers, "label": spec["name"]})


@hook("event", nested=True)
def allied_damage_ends_control(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Release exact owned control after root or child-event allied harm.

    Native event riders can deal damage inside another event's delivery. Opt
    into bounded nested dispatch so those packets obey the same printed early
    ending; without a harm-ending ledger this subscriber changes nothing.
    """
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    attacker = engine.state.actors.get(kwargs.get("actor_id"))
    if attacker is None:
        return
    for who in kwargs.get("target_ids") or ():
        subject = engine.state.actors.get(who)
        if subject is None:
            continue
        for ledger in list(subject.conditions.values()):
            if not ledger.condition_id.startswith(PREFIX):
                continue
            caster = engine.state.actors.get(ledger.source_actor_id)
            if caster is None or attacker.team_id != caster.team_id:
                continue
            for iid in [*(ledger.data.get("conditions") or []), ledger.instance_id]:
                condition = subject.conditions.pop(iid, None)
                if condition:
                    engine._append_event("CONDITION_REMOVED", ledger.source_definition_id,
                                         actor_id=ledger.source_actor_id, target_ids=(who,),
                                         payload={"condition_id": condition.condition_id, "instance_id": iid,
                                                  "reason": "ALLIED_DAMAGE"})
            for mid in ledger.data.get("modifiers") or []:
                if subject.modifiers.pop(mid, None):
                    engine._append_event("MODIFIER_REMOVED", ledger.source_definition_id,
                                         actor_id=ledger.source_actor_id, target_ids=(who,),
                                         payload={"modifier_id": mid, "reason": "ALLIED_DAMAGE"})
