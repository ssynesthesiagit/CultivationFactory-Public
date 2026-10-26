"""Grave Tax's printed reward choice (TAL_DEATH_GRAVE_TAX).

Printed rider (authority/typed_mechanics/rules_text.json, TAL_DEATH_GRAVE_TAX):
"If this reduces the healing or Temporary HP to 0, choose one: you regain CP equal
to your Proficiency Bonus, not exceeding your maximum CP; one Death servant you
control regains HP equal to the prevented amount; the target gains a Grave Mark
until the end of your next turn; the target cannot regain HP until the start of
its next turn."

The engine already reduces the pending gain (3d8 + key modifier) before it is
committed (combat/typed_reactions.py on_healing_pending). This plug-in owns only
the reward: the compiled row carries one typed ``grave_tax_reward`` effect, which
runs inside that same reaction, reads the prevented amount from the reaction's own
PASSIVE_TRIGGERED receipt, and asks the player with ``needle.ask`` -- the
documented choice transport -- only when the gain reached 0. A fighter the table
plays decides for itself, so AI fights and saved replays never gain a question.

Inert for characters that do not own Grave Tax: the effect exists only on that
compiled row, and the question uses the shared ``choice:needle.*`` transport
(combat/ext/needle.py already publishes every ``needle.ask`` menu as labelled
buttons), so no second provider is registered for the same choice.
"""
from __future__ import annotations

from typing import Any

from . import effect
from .ability_source import source_label

GRAVE = "TAL_DEATH_GRAVE_TAX"
CHOICE = "choice:needle.grave_tax_reward"
SERVANT_CHOICE = "choice:needle.grave_tax_servant"
CP, SERVANT, MARK, NO_REGAIN = "cp", "servant", "grave_mark", "no_hp_regain"
REWARDS = (CP, SERVANT, MARK, NO_REGAIN)


def _zeroed_gain(engine: Any, subject: Any) -> tuple[int, str, str] | None:
    """``(prevented, kind, source)`` when this reaction reduced a pending gain to 0.

    The reduction runs in combat/typed_reactions.dispatch_creature_reactions, which
    files a PASSIVE_TRIGGERED receipt with the before/after amounts before this
    effect runs. A bare healed/temp-HP notification (no pending frame) has no
    amount to reduce, so it never reaches the reward.
    """
    frame = getattr(engine, "_pending_healing", None)
    if not frame or frame.get("subject") != getattr(subject, "entity_id", None) or int(frame.get("amount") or 0) != 0:
        return None
    for event in reversed(getattr(engine, "events", ())):
        payload = event.payload or {}
        if (event.event_type == "PASSIVE_TRIGGERED" and event.source_definition_id == GRAVE
                and subject.entity_id in (event.target_ids or ()) and "before" in payload):
            before, after = int(payload.get("before") or 0), int(payload.get("after") or 0)
            if before > 0 and after == 0:
                return before, str(frame.get("kind") or "hp"), str(frame.get("source") or "")
            return None
    return None


def _cp_pool(ctx: Any) -> str | None:
    """The Path pool the reaction was paid from ("CP" is the character's Path resource)."""
    from ..typed_executor import CP_POOLS

    for resource_id, _amount in getattr(ctx.action, "costs", ()) or ():
        if resource_id in CP_POOLS:
            return resource_id
    return next((resource_id for resource_id in CP_POOLS if resource_id in ctx.actor.resources), None)


def _death_servants(engine: Any, actor: Any) -> list[Any]:
    from .. import summons

    from ..typed_executor import healing_denied

    # A servant that cannot regain HP from an ordinary source is not offered the reward at all
    # (the same roster rule ordinary healing applies in block_healing).
    return [creature for creature in summons.owned_by(engine, actor.entity_id, "death")
            if creature.active and not healing_denied(creature)]


def _ask(engine: Any, ctx: Any, subject: Any, checkpoint: str, choice_id: str, options: list[str],
         labels: dict[str, str], prompt: str) -> list[str]:
    """Ask the player who owns this fighter; an AI seat chooses the first printed reward itself."""
    from . import needle

    if needle.ai_controlled(engine, ctx.actor):
        return [options[0]]
    return needle.ask(engine, ctx.intent,
                      needle.checkpoint_id(engine, checkpoint, ctx.actor.entity_id, subject.entity_id),
                      ctx.actor, choice_id, options, labels=labels, prompt=prompt, preferred=[options[0]],
                      minimum=1, maximum=1, allow_decline=False, name="Grave Tax reward",
                      feature_id=GRAVE, target_id=subject.entity_id)


@effect("grave_tax_reward", harmful=False)
def reward(ctx: Any, eff: dict[str, Any]) -> None:
    """The printed "if this reduces ... to 0, choose one" reward, after the reduction."""
    engine, actor, subject = ctx.engine, ctx.actor, ctx.target
    if subject is None:
        return
    zeroed = _zeroed_gain(engine, subject)
    if zeroed is None:
        return
    prevented, kind, source = zeroed
    pb = int(ctx.numbers.get("pb") or getattr(actor, "proficiency_bonus", 0) or 0)
    servants = _death_servants(engine, actor)
    options = [CP, *([SERVANT] if servants else []), MARK, NO_REGAIN]
    labels = {
        CP: f"Regain {pb} CP (your Proficiency Bonus), up to your maximum",
        SERVANT: f"A Death servant you control regains {prevented} HP",
        MARK: "The target gains your Grave Mark until the end of your next turn",
        NO_REGAIN: "The target cannot regain HP until the start of its next turn",
    }
    lost = "Temporary Hit Points" if kind == "temp_hp" else "Hit Points"
    prompt = (f"Grave Tax reduced the {lost} {subject.display_name} would gain from "
              f"{source_label(engine, source)} to 0 (prevented {prevented}). Choose one reward.")
    picked = _ask(engine, ctx, subject, "GRAVE_TAX_REWARD", CHOICE, options, labels, prompt)
    choice = picked[0] if picked and picked[0] in options else CP
    if choice == SERVANT and servants:
        _grant_servant(engine, ctx, subject, servants, labels, prevented)
    elif choice == MARK:
        _run(ctx, [{"type": "mark", "mark": "Grave Mark", "applies_to": "target",
                    "duration": {"kind": "until_end_of_your_next_turn"},
                    "evidence": "gains a Grave Mark until the end of your next turn"}])
    elif choice == NO_REGAIN:
        _run(ctx, [{"type": "healing_reduction", "applies_to": "target",
                    "evidence": "The target cannot regain HP until the start of its next turn.",
                    "duration": "START_OF_SELF_NEXT_TURN"}])
    else:
        pool = _cp_pool(ctx)
        if pool is not None:
            engine._gain_resource(actor, pool, pb, GRAVE)
    engine._append_event("PASSIVE_TRIGGERED", GRAVE, actor_id=actor.entity_id, target_ids=(subject.entity_id,),
                         payload={"reward": choice, "prevented": prevented,
                                  "log": f"Grave Tax: {labels[choice]}."})


def _grant_servant(engine: Any, ctx: Any, subject: Any, servants: list[Any],
                   labels: dict[str, str], prevented: int) -> None:
    """One Death servant the user controls regains the prevented HP (a second printed choice when there are several)."""
    if len(servants) > 1:
        options = [creature.entity_id for creature in servants]
        names = {creature.entity_id: creature.display_name for creature in servants}
        picked = _ask(engine, ctx, subject, "GRAVE_TAX_SERVANT", SERVANT_CHOICE, options,
                      {key: f"{names[key]} regains {prevented} HP" for key in options},
                      f"Grave Tax: choose the Death servant that regains {prevented} HP.")
        servant = next((creature for creature in servants if creature.entity_id == (picked[0] if picked else "")),
                       servants[0])
    else:
        servant = servants[0]
    # The same healing path every heal uses: the servant's stored reductions ("cannot regain HP",
    # halved, minus a number) apply to the prevented amount before HP is committed.
    from ..typed_executor import stored_healing_reductions
    amount = stored_healing_reductions(engine, servant, prevented, healer=ctx.actor, source=GRAVE)
    engine._heal(servant, amount, GRAVE, ctx.actor.entity_id, notify_healed=True)


def _run(ctx: Any, effects: list[dict[str, Any]]) -> None:
    from ..typed_executor import run_effects

    run_effects(ctx, effects)
