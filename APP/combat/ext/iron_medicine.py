"""Medicine of the Closed Gate in combat (Iron Fist, Meridian; rider lane C10, 2026-09-30).

Owner text (TAL_IRON_FIST_MEDICINE_OF_THE_CLOSED_GATE): "... make a Wisdom (Medicine) check against DC 15. ... During combat, you may
use an Action and expend Martial Focus to apply this treatment to yourself or a willing creature within reach. On a successful
check, the target may immediately repeat one saving throw against a Meridian talent, Grappled condition, Prone-related martial
hindrance, or similar bodily disruption."

How it runs: the owner has "Medicine of the Closed Gate" (an Action, Martial Focus), aimed at itself or an ally within 5 feet that
bears a bodily condition with a saving throw behind it (the save it came from or repeats with, repeat_saves.save_of): Grappled,
Restrained, Prone, Stunned, Paralyzed, Incapacitated, Poisoned, Blinded or Deafened. It rolls Wisdom (Medicine) (the sheet's skill,
else Wisdom + Proficiency Bonus -- the talent requires the proficiency) against DC 15. On a success the treated creature's player
picks which of those saves to repeat, or declines (the choice transport; an AI takes the easiest); a repeated save that succeeds
ends that condition. The one-minute treatment outside combat is not a fight action.
Reading: "similar bodily disruption" is that list; mental conditions (Charmed, Frightened) are not bodily.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

MEDICINE = "TAL_IRON_FIST_MEDICINE_OF_THE_CLOSED_GATE"
BODILY = ("grappled", "restrained", "prone", "stunned", "paralyzed", "incapacitated", "poisoned", "blinded", "deafened")
KEY = "iron_closed_gate"
DC = 15


@hook("compile_actions")
def closed_gate_action(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if MEDICINE not in (info.get("owned_ids") or []):
        return None
    typed = {"effects": [{"type": KEY, "evidence": "During combat, you may use an Action and expend Martial Focus to apply this treatment"}],
             "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": [], "source": MEDICINE, "coverage": "FULL"}
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.{KEY}", display_name="Medicine of the Closed Gate", owner_id=info["actor_id"],
        economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF", range_ft=5,
        costs=((RESOURCE_IDS["martial_focus"], 1),),
        parameters={"typed": typed, "expected_damage": 0, "player_only": True, KEY: True,
                    "description": ("Use your Action and Martial Focus to treat yourself or a willing ally within reach: a Wisdom (Medicine) "
                                    "check against DC 15. On a success they may repeat one saving throw against Grappled, Restrained, "
                                    "Prone, Stunned, Paralyzed, Incapacitated, Poisoned, Blinded or Deafened; a success ends it.")})]


def treatable(subject: Any) -> list[tuple[str, Any]]:
    from .repeat_saves import repeatable

    return repeatable(subject, BODILY)


@hook("candidate_allowed")
def offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get(KEY):
        return None
    targets = [engine.state.actors.get(target_id) for target_id in getattr(candidate, "target_ids", ()) or ()]
    return None if targets and all(t is not None and treatable(t) for t in targets) else False


@effect("iron_closed_gate")
def treat(ctx: Any, row: dict[str, Any]) -> None:
    from . import floored, run
    from ..ability_checks import ability_modifier
    from ..typed_executor import check_mode
    from .eye_common import skill
    from .needle import CHOICE, ask, checkpoint_id
    from .repeat_saves import save_of

    engine, actor = ctx.engine, ctx.actor
    subject = ctx.target or actor
    options = treatable(subject)
    if not options:
        return
    bonus = skill(engine, actor, "Medicine", ability_modifier(actor, "WIS") + int(ctx.numbers.get("pb") or actor.proficiency_bonus or 2))
    bonus += sum(int(value) for value in run("check_bonus", ctx, actor) if isinstance(value, int))
    roll = engine.roller.d20(modifier=bonus, actor_id=actor.entity_id, reason=f"CHECK:{ctx.source}:Medicine", mode=check_mode(actor, "WIS", "Medicine", engine=engine))
    engine._record_roll(roll)
    roll = floored(engine, actor, roll, DC)
    success = roll.total >= DC
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(subject.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": DC, "success": success, "skill": "Medicine"})
    if not success:
        ctx.rider(f"Medicine of the Closed Gate: {actor.display_name}'s treatment of {subject.display_name} fails (Medicine {roll.total} against DC {DC}).")
        return
    labels = {iid: f"Repeat the {save_of(c)['ability'].upper()} save (DC {save_of(c)['dc']}) against {c.condition_id.rsplit('.', 1)[-1].title()}"
              for iid, c in options}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "CLOSED_GATE", actor.entity_id, subject.entity_id), subject, CHOICE + KEY,
                 list(labels), labels=labels, allow_decline=True, name="Medicine of the Closed Gate", feature_id=MEDICINE,
                 target_id=subject.entity_id,
                 prompt=f"Medicine of the Closed Gate: {actor.display_name} treats {subject.display_name}, who may repeat one saving throw.")
    chosen = next(((iid, c) for iid, c in options if iid in picked), None)
    if chosen is None:
        return
    iid, condition = chosen
    save = save_of(condition)
    dc = int(save["dc"])
    saved = engine._roll_save(subject, str(save["ability"]).upper(), dc, ctx.source)
    if saved.total >= dc and iid in subject.conditions:
        subject.conditions.pop(iid)
        engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": iid, "repeat_save": True})
        ctx.rider(f"Medicine of the Closed Gate: {subject.display_name} repeats the save and is no longer "
                  f"{condition.condition_id.rsplit('.', 1)[-1].title()}.")
