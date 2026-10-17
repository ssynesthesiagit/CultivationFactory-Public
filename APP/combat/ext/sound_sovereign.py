"""Sound-Sovereign Incarnation (Sound, CL 15+; riders lane 5, 2026-09-29).

Bonus Action, 15 CP, once per long rest, 1 minute: "Become a sovereign vessel of world-ringing vibration. For the duration: gain
Resistance to Thunder and Psychic damage; gain Blindsight 30 feet based on vibration and soul-sound; Resonant Note may target two
creatures within range instead of one; once per turn when a creature fails a saving throw against your Sound talent, it cannot take
Reactions until the start of your next turn; you may speak or transmit through your own Sound talents even inside ordinary Silence;
Soundwalk Step range increases by 30 feet; your Sound talents ignore ordinary Thunder Resistance."  (Rules text: authority/
typed_mechanics/rules_text.json.)

The authority row puts the Resistance on you; using it also leaves a mark on you for the minute (authority override), which this
plug-in reads:

* ``after_save``: once per turn, a creature that fails a saving throw against one of your Sound talents cannot take Reactions until
  the start of your next turn.  "Once per turn" is counted per turn of the fight (round and whose turn it is), not per creature.
* ``resistance_ignored``: your Sound talents' Thunder damage ignores the target's Resistance to Thunder.  The table cannot tell an
  ordinary Resistance from a special one (Immunity is untouched, as printed), so every Resistance to Thunder is ignored.
* ``compile_actions`` / ``candidate_allowed``: "Soundwalk Step range increases by 30 feet" -- the authority's modifier for it sits on a
  Bonus Action talent, which the compiler never reads as a modifier, so the longer step is its own action ("Soundwalk Step
  (Sound-Sovereign Incarnation)"), offered only while the Incarnation lasts.

``sound_two_notes`` asks for an optional second creature using the existing choice transport and rolls each attack separately.
Speaking or transmitting through Silence remains a GM line (the table does not model acoustic paths).
"""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

from . import effect, hook, note
from ..typed_executor import Context, bears_mark, run_effects

FEATURE = "TAL_SOUND_SOUND_SOVEREIGN_INCARNATION"
SOUNDWALK = "TAL_SOUND_SOUNDWALK_STEP"
NOTE = "TAL_SOUND_RESONANT_NOTE"
MARK = "Sound-Sovereign Incarnation"
SOUND = "tianxia.sphere.sound"
_TURN = "sound_sovereign_denied_turn"


def active(actor: Any) -> bool:
    return actor is not None and bears_mark(actor, actor.entity_id, MARK)


@hook("resistance_ignored")
def ignore_thunder_resistance(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str | None, target: Any = None) -> bool | None:
    actor = engine.state.actors.get(source_actor_id) if source_actor_id else None
    if kind != "THUNDER" or (typed or {}).get("sphere") != SOUND or not active(actor):
        return None
    return True


@hook("after_save")
def deny_reactions(ctx: Context, subject: Any, ability: str, named: Any, failed: bool) -> None:
    actor, engine = ctx.actor, ctx.engine
    if not failed or subject is None or not subject.active or (ctx.typed or {}).get("sphere") != SOUND \
            or not active(actor):
        return
    key = (int(engine.state.round_number), engine.state.current_actor_id)
    if actor.turn_flags.get(_TURN + "_round_") == list(key):
        return  # once per turn
    actor.turn_flags[_TURN + "_round_"] = list(key)
    run_effects(Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [subject], subject, ctx.damage_cache),
                [{"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn",
                  "evidence": "it cannot take Reactions until the start of your next turn"}])
    note(engine, ctx.source, actor, f"Sound-Sovereign Incarnation: {subject.display_name} cannot take Reactions until the start of "
                                    f"{actor.display_name}'s next turn.", (subject,))


@hook("compile_actions")
def soundwalk_range(info: dict[str, Any]) -> list[Any] | None:
    """"Soundwalk Step range increases by 30 feet": the authority's modifier for it is written on a Bonus Action talent, which the
    compiler never reads as a modifier, so the longer step is its own action, offered only while the Incarnation lasts."""
    if FEATURE not in (info.get("owned_ids") or ()):
        return None
    out = []
    for row in info.get("actions") or []:
        typed = (row.parameters or {}).get("typed") or {}
        if not row.range_ft:
            continue
        if typed.get("source") == NOTE and not typed.get("modifier"):
            parameters = {**row.parameters, "typed": {**typed, "effects": [
                {"type": "sound_two_notes", "effects": copy.deepcopy(typed.get("effects") or [])}]},
                          "sovereign_range": True, "sovereign_note": True}
            out.append(row.model_copy(update={"source_definition_id": row.source_definition_id + "#sovereign",
                                              "display_name": f"{row.display_name} (Sound-Sovereign Incarnation)",
                                              "parameters": parameters}))
            continue
        if typed.get("source") != SOUNDWALK or typed.get("option_of"):
            continue
        longer = int(row.range_ft) + 30
        parameters = {**row.parameters, "typed": {**typed, "range_ft": longer, "variant_of": row.source_definition_id}, "sovereign_range": True}
        out.append(row.model_copy(update={"source_definition_id": row.source_definition_id + "#sovereign",
                                          "display_name": f"{row.display_name} (Sound-Sovereign Incarnation)", "range_ft": longer,
                                          "parameters": parameters}))
    return out or None


@effect("sound_two_notes")
def two_notes(ctx: Context, eff: dict[str, Any]) -> None:
    """Optional second creature chosen through the existing extension choice transport; each gets its own attack roll.

    The first creature comes from the action's ordinary target. No answer means one Note, as the printed 'may' permits.
    Object targets use the ordinary object action and never acquire a second target.
    """
    from .needle import ask, checkpoint_id

    if ctx.target is None or not active(ctx.actor):
        return
    reach = int(ctx.action.range_ft or 60)
    options = [a.entity_id for a in ctx.engine.state.actors.values()
               if a.active and a.entity_id != ctx.target.entity_id
               and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= reach
               and ctx.engine._line_of_sight_actor_to_actor(ctx.actor, a)]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "sound_second_note", ctx.source), ctx.actor,
                 "choice:needle.sound_second_note", options, minimum=0, maximum=1, allow_decline=True,
                 automatic=False, default="decline", target_id=ctx.target.entity_id,
                 labels={a.entity_id: a.display_name for a in ctx.engine.state.actors.values()},
                 name="Sound-Sovereign Incarnation", feature_id=FEATURE,
                 prompt=f"Sound-Sovereign Incarnation: {ctx.actor.display_name} uses Resonant Note on {ctx.target.display_name}; choose an optional second creature.")
    targets = [ctx.target, *[ctx.engine.state.actors[aid] for aid in chosen if aid in options]]
    for target in targets:
        run_effects(replace(ctx, target=target, targets=[target], damage_cache={}), copy.deepcopy(eff.get("effects") or []))


@hook("candidate_allowed")
def range_only_while_it_lasts(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if (getattr(action, "parameters", None) or {}).get("sovereign_note") and any(
            aid in engine.state.objects for aid in candidate.target_ids):
        return False  # the two-creature variant; the ordinary Note remains available for an object
    if (getattr(action, "parameters", None) or {}).get("sovereign_range") and not active(actor):
        return False
    return None
