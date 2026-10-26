"""Silenced on the table (owner 2026-09-29, combat/speech.py): a Silenced fighter is not offered an ability that needs its
voice; Speech-Knot Point's knot makes the next one a Constitution save; Locked Breath Method's immediate Concentration
save.

- Speech-Knot Point ("the next time the target speaks clearly ... uses an ability requiring clear speech, or provides a
  Verbal component before the effect ends, it makes the saving throw. Failed Save: ... the activation fails, but the action
  and resources are not spent unless the ability itself says otherwise. Successful Save: the target speaks normally, and
  this Point ends."): the native pre-payment declaration checks the save before
  spending economy or resources. No refund or extra GM-granted Action is needed.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .. import speech
from ..hook_queries import actor_action


@hook("candidate_allowed", query_key=actor_action,
      present=lambda engine: any(speech.silenced(actor) for actor in engine.state.actors.values()))
def voiceless(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:

    if action is not None and speech.silenced(actor) and speech.needs_voice(action):
        return False
    return None


@effect("speech_knot")
def speech_knot(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import speech, typed_executor

    for subject in typed_executor._default_subject(ctx, eff, harmful=True):
        ctx.engine._remove_condition(subject, speech.SPEECH_KNOT, ctx.source)
        ctx.engine._apply_condition(subject, speech.SPEECH_KNOT, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"dc": int(ctx.numbers.get("save_dc") or 10), "label": "Speech-Knot Point: its next voiced ability calls for a save"})


@hook("technique_declared")
def knotted_speech(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> dict | None:
    from .. import speech

    knot = next(((iid, c) for iid, c in actor.conditions.items() if c.condition_id == speech.SPEECH_KNOT), None)
    if knot is None or not speech.needs_voice(action):
        return None
    instance_id, condition = knot
    dc = int((condition.data or {}).get("dc") or 10)
    roll = engine._roll_save(actor, "CON", dc, condition.source_definition_id)
    actor.conditions.pop(instance_id)
    engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"condition_id": speech.SPEECH_KNOT, "instance_id": instance_id, "reason": "CONSUMED"})
    if roll.total >= dc:
        return None  # it speaks normally, and the Point ends
    return {'source_id': condition.source_definition_id, 'label': f'Speech-Knot Point stops {action.display_name}; no action or resources are spent.',
            'cancel': True}


@effect("lose_concentration")
def lose_concentration(ctx: Any, eff: dict[str, Any]) -> None:
    """"It loses Concentration" (The Point Between Heartbeats): every Concentration technique it holds ends."""
    from .. import concentration, typed_executor

    for subject in typed_executor._default_subject(ctx, eff, harmful=True):
        concentration.end_all_held(ctx.engine, subject, "SEALED")
        ctx.engine._end_concentration(subject, "SEALED")


@effect("concentration_save")
def concentration_save(ctx: Any, eff: dict[str, Any]) -> None:
    """"If the target is concentrating, it immediately makes a Concentration saving throw against your Save DC" (Locked
    Breath Method): a failure ends its most recent Concentration technique (combat/concentration.py).

    World-Nerve uses ``choose_held`` for one exact held instance. Its optional
    ``manual_check`` mapping (label, rider) adds a GM-run alternative for checks
    not represented by Concentration. Selecting it emits only that rider, never
    a Concentration save or consumption of next-save modifiers. Other callers
    omit the mapping and retain their Concentration-only behavior.
    """
    from .. import concentration, typed_executor
    from ..gate2_engine import SYSTEM_CONCENTRATION

    dc = int(ctx.numbers.get("save_dc") or 10)
    for subject in typed_executor._default_subject(ctx, eff, harmful=True):
        manual_check = eff.get("manual_check") if eff.get("choose_held") else None
        if not subject.active or (subject.concentration is None and not manual_check):
            continue
        # World-Nerve Judgment says "for each active effect", including older held techniques.
        checks = [*(concentration.held(subject) if eff.get("all_held") or eff.get("choose_held") else []), (None, subject.concentration)]
        if eff.get("choose_held"):
            from . import needle

            # Instance-bound IDs distinguish repeated copies of the same source.
            by_id = {iid or f"current:{state.started_sequence}": (iid, state) for iid, state in checks if state is not None}
            labels = {}
            for key, (_, state) in by_id.items():
                action = ctx.engine.action_catalog.get(state.source_definition_id)
                labels[key] = f"{action.display_name if action else state.source_definition_id} (held #{state.started_sequence})"
            manual_id = "gm:maintenance_check"
            options = list(by_id)
            if manual_check:
                options.append(manual_id)
                labels[manual_id] = manual_check["label"]
            preferred = ([f"current:{subject.concentration.started_sequence}"] if subject.concentration else [manual_id])
            chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "held_effect", subject.entity_id),
                                ctx.actor, needle.CHOICE + "held_effect", options, labels=labels, preferred=preferred,
                                prompt=f"{ctx.action.display_name}: choose the sustained effect {subject.display_name} must check after its successful save",
                                target_id=subject.entity_id, name=ctx.action.display_name, feature_id=ctx.source)
            if manual_id in chosen:
                ctx.engine._append_event("GM_RIDER", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                                         payload={"rider": f"{ctx.action.display_name} — {subject.display_name}: {manual_check['rider']}"})
                continue
            checks = [by_id[key] for key in chosen]
        for instance_id, state in checks:
            if state is None:
                continue
            # Consume next-save modifiers once, and re-read persistent modes
            # after an earlier failed check ends the technique supplying one.
            modes, support_bonus = concentration.save_contributions(ctx.engine, subject)
            asked = str(eff.get("mode") or "").upper()
            if asked in ("ADVANTAGE", "DISADVANTAGE"):
                modes.add(asked)
            roll = ctx.engine._roll_save(subject, "CON", dc, SYSTEM_CONCENTRATION,
                                         roll_context={"save_modes": sorted(modes), "additional_bonus": support_bonus})
            if roll.total < dc:
                if instance_id is None:
                    ctx.engine._end_concentration(subject, "FAILED_SAVE")
                else:
                    concentration.end_held(ctx.engine, subject, instance_id, "FAILED_SAVE")
