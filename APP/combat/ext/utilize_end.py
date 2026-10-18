"""Utilize to end an effect (rider lane 10, 2026-09-29): printed lines that let a creature spend its Action (the 2024 Utilize action) to
end a lasting harm early -- the shape of the Tianxia Burn's "Extinguish flames" (combat/factory_compiler.py), for effects whose own
plug-in tags the harm with a marker condition.

Rules text (owner's Sphere Compendium, authority/typed_mechanics/rules_text.json):
  Face Strike  "The target or a creature within its reach may take the Utilize action to wipe away blood, dust, or another obstruction
               and end the effect early."  -- no check; the marker is condition:typed.needle_face_strike (combat/ext/needle.py
               face_strike_mark), naming the Blinded instance the Exploit put on.
  Bleed Air    "After choking begins, the effect ends if ... a creature within reach of the target takes the Utilize action and succeeds
               on a Wisdom (Medicine) check against your Cultivation Save DC." -- the marker is Bleed Air's own condition
               (condition:typed.needle_bleed_air, which carries the fencer's DC); not the target itself ("a creature within reach of the
               target"), and only once choking has begun ("After choking begins"; before that only full Hit Points ends it).

Every compiled Factory character gets one action per ENDINGS entry (Action economy, 5 feet: "within its reach"), offered only against
a creature bearing that marker (``target_requires_condition``), so it shows up only while such an effect is on the board. Characters
compiled before carry no such action; saved fights replay unchanged.

Any other plug-in that files a marker condition can add its own Utilize ending with ``register_ending`` (below), which is how the
Scoundrel's Impossible Fastening reuses this action ("The target or an adjacent creature can take the Utilize action to end the
hindrance early"). Register at import time, before any character is compiled; the entries above are untouched.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

ENDINGS: dict[str, dict[str, Any]] = {
    "face_strike": {"marker": "condition:typed.needle_face_strike", "label": "Wipe away the obstruction (Face Strike)",
                    "self": True, "check": None,
                    "describe": "Utilize: wipe away the blood or dust of a Face Strike from yourself or a creature within 5 feet; its Blinded ends."},
    "bleed_air": {"marker": "condition:typed.needle_bleed_air", "label": "Treat the choking (Bleed Air)", "self": False,
                  "check": ("WIS", "Medicine"), "after_key": "dies_round",
                  "describe": "Utilize: a Wisdom (Medicine) check against the fencer's Cultivation Save DC ends a choking creature's Bleed Air."},
}


def register_ending(key: str, spec: dict[str, Any]) -> None:
    """Add one Utilize ending, so a plug-in that files a marker condition need not write its own Action.

    ``spec`` is one of the entries above: ``marker`` (the condition id the ending looks for), ``label`` (the button text),
    ``describe`` (its hover text), optional ``check`` (an ``(ability, skill)`` pair the user must roll), optional
    ``after_key`` (a data key the marker must carry first) and optional ``target_kind`` (defaults to "ALLY_OR_SELF";
    pass "ANY_CREATURE" when the printed line lets any creature within reach, not only an ally, do it). The marker's
    ``linked`` list names the condition instances the ending removes, so it never ends an unrelated effect.
    ``choose_marker=True`` asks which actual marker to end when several match;
    absent metadata keeps the original first-marker procedure.
    ``provided_action=True`` reuses an action already published by its native
    producer and skips compile_actions duplication; ``ended_label`` optionally
    supplies a plain ending sentence without changing the removal.

    Used by combat/ext/scoundrel_riders.py (Impossible Fastening). Call it while this module is being imported, before any
    character is compiled; a later call does not add an action to a character that is already compiled.
    """
    ENDINGS[str(key)] = {**spec, "target_kind": str(spec.get("target_kind") or "ALLY_OR_SELF")}


@hook("compile_actions")
def utilize_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import _skill_bonus
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    out = []
    mods, sheet = info.get("mods") or {}, info.get("owner_sheet") or {}
    for key, spec in ENDINGS.items():
        if spec.get('provided_action'):continue
        check = spec.get("check")
        bonus = _skill_bonus(sheet, check[1], mods.get(check[0], 0)) if check else 0
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.utilize.{key}", display_name=spec["label"], owner_id=info["actor_id"],
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind=str(spec.get("target_kind") or "ALLY_OR_SELF"), range_ft=5,
            parameters={"typed": {"effects": [{"type": "utilize_end", "key": key, "bonus": bonus}], "numbers": info.get("numbers") or {},
                                  "duration": {"kind": "instant"}, "riders": []},
                        "expected_damage": 0, "target_requires_condition": spec["marker"], "utilize_end": key,
                        "description": spec["describe"]}))
    return out


def _marker(subject: Any, spec: dict[str, Any]) -> tuple[str, Any] | None:
    return next(((iid, c) for iid, c in subject.conditions.items() if c.condition_id == spec["marker"]), None)


@hook("candidate_allowed")
def utilize_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    key = ((getattr(action, "parameters", None) or {}).get("utilize_end"))
    if not key or key not in ENDINGS:
        return None
    spec = ENDINGS[key]
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if target is None:
        return None
    if not spec["self"] and target.entity_id == actor.entity_id:
        return False
    found = _marker(target, spec)
    if found is None or (spec.get("after_key") and (found[1].data or {}).get(spec["after_key"]) is None):
        return False
    return None


def _end(engine: Any, subject: Any, iid: str, marker: Any, source: str) -> None:
    """Remove the marker and the condition instances it names, each as its own evented removal (the reducer drops by instance id)."""
    for linked in list((marker.data or {}).get("linked") or []):
        condition = subject.conditions.get(linked)
        if condition is not None:
            del subject.conditions[linked]
            engine._append_event("CONDITION_REMOVED", source, actor_id=condition.source_actor_id, target_ids=(subject.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": linked})
    if iid in subject.conditions:
        del subject.conditions[iid]
        engine._append_event("CONDITION_REMOVED", source, actor_id=marker.source_actor_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": marker.condition_id, "instance_id": iid})


@effect("utilize_end")
def utilize_end(ctx: Any, eff: dict[str, Any]) -> None:
    spec = ENDINGS.get(str(eff.get("key") or ""))
    subject = ctx.target if ctx.target is not None else ctx.actor
    if spec is None or subject is None:
        return
    found = _marker(subject, spec)
    if found is None:
        return
    iid, marker = found
    if spec.get('choose_marker'):
        available={key:c for key,c in subject.conditions.items() if c.condition_id==spec['marker']}
        if len(available)>1:
            from .needle import ask,checkpoint_id
            chosen=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'utilize_end',str(eff.get('key')),subject.entity_id),ctx.actor,
                'choice:needle.utilize_end.'+str(eff.get('key')),list(available),
                labels={key:f"{spec.get('ended_label','Effect')} {index+1} on {subject.display_name}" for index,key in enumerate(available)},
                name=spec['label'],target_id=subject.entity_id,prompt=f"{spec['label']}: choose one effect on {subject.display_name}. This uses one Action and requires no check.")
            if not chosen:return
            iid=chosen[0];marker=available[iid]
    check = spec.get("check")
    if check:
        from .. import ext

        dc = int((marker.data or {}).get("dc") or 10)
        modifier = int(eff.get("bonus") or 0) + sum(ext.run("check_bonus", ctx, ctx.actor))
        roll = ctx.engine.roll_check(modifier=modifier, actor_id=ctx.actor.entity_id, reason=f'CHECK:{ctx.source}')
        ctx.engine._record_roll(roll)
        roll = ext.floored(ctx.engine, ctx.actor, roll, dc)
        if int(roll.total) < dc:
            note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name}'s {check[1]} check ({roll.total} against DC {dc}) fails: "
                                                     f"{subject.display_name} is still affected.", (subject.entity_id,))
            return
    _end(ctx.engine, subject, iid, marker, ctx.source)
    if spec.get('ended_label'):
        note(ctx.engine,ctx.source,ctx.actor,f"{spec['label']}: {spec['ended_label']} on {subject.display_name} ends.",(subject.entity_id,))
    else:
        note(ctx.engine, ctx.source, ctx.actor, f"{spec['label'].split(' (')[0]}: {subject.display_name}'s {spec['label'].split('(')[-1].rstrip(')')} ends.",
             (subject.entity_id,))


# Ordinary Fire burns and Burning Brand use the same printed one-Burn Action.
# The compiler already publishes that system action; do not add a second one.
register_ending('burning',{'marker':'condition:typed.burning','label':'Extinguish flames',
    'describe':'Action: extinguish one Burn affecting yourself or any adjacent creature. No check, water, tool or special equipment is required.',
    'self':True,'target_kind':'ANY_CREATURE','provided_action':True,'choose_marker':True,'ended_label':'One Burn'})


BURN_ACTION='system:combat.extinguish_burn'


def has_burn_action(engine,actor):
    """Pure capability query used by generic native and compiled creatures."""
    return any(engine.action_catalog[key].parameters.get('utilize_end')=='burning' for key in actor.action_ids)


@hook('match_start')
def native_burn_action(engine):
    """Native stock/portable actors share the compiled ordinary Burn procedure.

    Publishing is inert without a compiled Burn action in this encounter, and
    the supplemental option exists only while a real Burn is present. Actors
    with their own compiled action never receive a duplicate.
    """
    if not any(a.parameters.get('utilize_end')=='burning' for a in engine.action_catalog.values()):return
    from ..gate2_runtime_models import ActionDefinition
    spec=ENDINGS['burning']
    engine.action_catalog[BURN_ACTION]=ActionDefinition(source_definition_id=BURN_ACTION,display_name=spec['label'],owner_id='*',
        economy='ACTION',resolution_kind='TYPED',target_kind='ANY_CREATURE',range_ft=5,
        parameters={'utilize_end':'burning','target_requires_condition':spec['marker'],'expected_damage':0,'description':spec['describe'],
            'typed':{'effects':[{'type':'utilize_end','key':'burning'}],'numbers':{},'duration':{'kind':'instant'},'riders':[]}})


@hook('additional_actions')
def supplemental_burn_action(engine,actor):
    if BURN_ACTION not in engine.action_catalog or has_burn_action(engine,actor):return None
    return [BURN_ACTION] if any(c.condition_id=='condition:typed.burning' for a in engine.state.actors.values() for c in a.conditions.values()) else None
