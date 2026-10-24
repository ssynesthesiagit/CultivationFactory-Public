"""Puppetry's printed movement answers, asked while the creature is walking.

Printed rules (APP/authority/typed_mechanics/rules_text.json):

* ``tianxia.talent.puppetry.knot_the_knee`` -- "When a creature with your Tension Mark
  willingly moves at least 10 feet, spend the mark as a Reaction. The creature makes a
  Dexterity saving throw. Failed Save: It falls Prone after moving 5 feet. Successful
  Save: Its Speed is reduced by 10 feet until the end of the current turn."
* ``tianxia.talent.puppetry.threaded_step_formation`` -- "When you move your active puppet
  vessel, choose one willing ally within 5 feet of it. That ally may move 5 feet without
  provoking Opportunity Attacks from one creature that has your Tension Mark. Use Threaded
  Step Formation once per turn."

Knot the Knee is answered in the documented strict ``movement_attempt`` checkpoint, which runs
before each step is paid. Its outcome comes from the owner's own compiled generic reaction row
(the same ``"moved"`` row and the same effects the engine already runs), so the printed save,
the Prone and the Speed reduction keep exactly one implementation. Answering there is what
makes the printed timing real: the settled failure retains its Prone metadata for save defenses,
then records its original condition packet as an evented pending fall. The first completed five-foot
step delivers that packet through normal condition defenses and ends the move if it lands,
before entry hazards. The end-of-move
reaction fires after the path is committed, which answers this a move too late.

Threaded Step Formation receives the specific completed vessel movement (Raise, Move and group
routes), checks that vessel's connection and adjacency, and hands the ally's step to the shared
``ext.rider_choices.step`` helper: the ally walks by the ordinary step checkpoints, leave-reach
checks and entry hazards while the one marked creature cannot take an Opportunity Attack at it.

Ownership: the owner's own compiled Puppetry kit (combat/ext/vessel.py ``kit``), its active
vessel and its Tension Mark. Unowned characters remain inert. Legacy sealed Knee owners retain
their completed-move timing; existing Threaded Step owners retain their movement grant through
the same vessel receipt, including when their kit predates the native flag.

Shared with: nothing yet. This is the canonical Puppetry movement module; a later lane that
needs the same shape should extend it rather than add another ``movement_attempt`` subscriber.
"""
from __future__ import annotations

import json
from typing import Any

from . import effect, hook, needle, placed, vessel

KNEE = "tianxia.talent.puppetry.knot_the_knee"
STEP = "tianxia.talent.puppetry.threaded_step_formation"
MARK = vessel.MARK
USED = "vessel_threaded_step_round"
PENDING = "condition:puppetry.pending_knee"
# Knot the Knee: "willingly moves at least 10 feet".
KNEE_TRIGGER_FT, KNEE_FALL_FT, KNEE_SPEED_LOSS = 10, 5, 10
# Threaded Step Formation: "within 5 feet of it" and "may move 5 feet".
STEP_FT = 5


def _row(engine: Any, owner: Any, feature_id: str) -> dict[str, Any] | None:
    """The owner's own compiled generic reaction row for one printed reaction."""
    for row in engine.typed_reaction_rows.get(owner.entity_id) or []:
        if row.get("feature_id") == feature_id and row.get("block") == "generic":
            return row
    return None


def _owners(engine: Any, mover: Any, talent: str) -> list[Any]:
    """Native opposing puppeteers owning ``talent`` whose mark is on ``mover``.

    The mark is checked first because it is a plain condition scan: most creatures in a fight
    carry none, and nothing else here runs for them.
    """
    from ..typed_executor import bears_mark

    owners = []
    for owner in engine.state.actors.values():
        if not owner.active or owner.team_id == mover.team_id or owner.entity_id == mover.entity_id:
            continue
        if not bears_mark(mover, owner.entity_id, MARK):
            continue
        owned = vessel.kit(engine, owner)
        if owned is not None and owned.get("native") and talent in owned["owned"]:
            owners.append(owner)
    return owners


def _offered(engine: Any, owner: Any, mover: Any, intent: Any) -> None:
    """Remember that this creature's current move already carried the printed reaction."""
    engine.__dict__.setdefault("_puppetry_knee_offered", {})[(owner.entity_id, mover.entity_id)] = intent


@hook("reaction_subject_allowed")
def knee_answered_once_per_move(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    """The printed reaction is one opportunity per movement, asked as the creature starts to walk.

    Declining it must not hand the same mark back as a second chance after the creature has
    already arrived somewhere else, so the end-of-move moment stays quiet for that move.
    """
    if row.get("feature_id") != KNEE or other is None:
        return None
    offered = (engine.__dict__.get("_puppetry_knee_offered") or {}).get((reactor.entity_id, other.entity_id))
    if offered is None:
        return None
    return False if offered is getattr(engine, "_active_intent", None) else None


@hook("movement_attempt")
def knot_the_knee(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """Knot the Knee, answered on the first step of the marked creature's own move."""
    from ..movement_steps import context

    if not mover.active:
        return None
    ctx = context(engine, mover)
    if int(ctx.get("travelled_ft") or 0) != 0:
        return None  # the printed reaction is asked once, as the creature starts to move
    # Separate grants can share an intent, and a paused transaction can retry
    # that same intent. A new physical walk starts fresh owner-bound receipts.
    offered = engine.__dict__.get("_puppetry_knee_offered") or {}
    for key in list(offered):
        if key[1] == mover.entity_id:
            offered.pop(key)
    if int(ctx.get("remaining_ft") or 0) < KNEE_TRIGGER_FT:
        return None  # "willingly moves at least 10 feet"
    for owner in _owners(engine, mover, KNEE):
        _offer_knee(engine, owner, mover, intent)
    return None


def _offer_knee(engine: Any, owner: Any, mover: Any, intent: Any) -> None:
    from ..typed_executor import run_effects
    from ..typed_reactions import can_use_reaction, open_reaction, triggered_context

    row = _row(engine, owner, KNEE)
    if row is None or not can_use_reaction(engine, owner, mover, row):
        return None  # no mark of yours on it, out of reach, or no Reaction left
    _offered(engine, owner, mover, intent)
    picked = needle.ask(engine, intent, needle.checkpoint_id(engine, "KNOT_THE_KNEE", owner.entity_id, mover.entity_id),
        owner, "choice:needle.knot_the_knee", ["REACT"],
        labels={"REACT": f"Knot the Knee on {mover.display_name}"},
        prompt=f"Knot the Knee: {mover.display_name} is about to move at least {KNEE_TRIGGER_FT} feet while your "
               f"Tension Mark is attached to it. Spend that mark and your Reaction now? It makes a Dexterity save: "
               f"if it fails it falls Prone after moving {KNEE_FALL_FT} feet; if it succeeds its Speed drops by "
               f"{KNEE_SPEED_LOSS} feet until the end of this turn.",
        name="Knot the Knee", target_id=mover.entity_id, preferred=["REACT"], allow_decline=True,
        prompt_context={"cost": "Spend one of your Tension Marks and your Reaction; no cultivation point cost"})
    if not picked:
        return None
    open_reaction(engine, row, owner, (mover.entity_id,), "MOVEMENT_ATTEMPT")
    effects = list(row.get("effects") or [])
    ctx = triggered_context(engine, owner, mover, row, intent)
    ctx.damage_cache["puppetry_delay_knee"] = True
    speed_before = engine._effective_speed(mover)
    run_effects(ctx, effects)
    lost = max(0, speed_before - engine._effective_speed(mover))
    if lost:
        # The typed Speed modifier changes future Speed, not this already
        # granted turn allowance. Preserve its ordinary evented budget path.
        run_effects(ctx, [{"type": "remaining_movement", "flat": -lost, "applies_to": "target"}])
    engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=owner.entity_id,
                         target_ids=(mover.entity_id,), payload={"checkpoint": "MOVEMENT_ATTEMPT"})
    placed.note(engine, KNEE, owner,
        f"Knot the Knee: {owner.display_name} spends the Tension Mark on {mover.display_name} as a Reaction as it "
        f"moves.", targets=(mover,))
    return None


@hook("effect_allowed")
def defer_knee_fall(ctx: Any, eff: dict[str, Any]) -> bool | None:
    """Hold the settled failure packet; its actual delivery owns ordinary condition defenses."""
    if (ctx.source != KNEE or not ctx.damage_cache.get("puppetry_delay_knee")
            or eff.get("type") != "condition" or eff.get("condition") != "prone"):
        return None
    for subject in ctx.targets:
        ctx.engine._apply_condition(subject, PENDING + "." + ctx.actor.entity_id, KNEE, ctx.actor.entity_id,
            expires_on="END_OF_CURRENT_TURN", data={"effect_json": json.dumps(eff),
                "origin_save_json": json.dumps(ctx.origin_save), "save_failed": int(bool(ctx.failed_save)),
                "label": "Knot the Knee: a fall is due after the first 5 feet of this move."})
    return False


@hook("movement_step_settled")
def knot_the_knee_falls(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """The printed fall, applied once the creature has walked the 5 feet the text names."""
    from ..movement_steps import context
    from ..typed_executor import run_effects
    from ..typed_reactions import triggered_context

    if not mover.active:
        return None
    if int(context(engine, mover).get("travelled_ft") or 0) < KNEE_FALL_FT:
        return None  # the printed five feet are not walked yet
    pending = [c for c in mover.conditions.values() if c.condition_id.startswith(PENDING + ".")]
    if not pending:
        return None
    fell = False
    for condition in pending:
        engine._remove_condition(mover, condition.condition_id, KNEE)
        owner = engine.state.actors[condition.source_actor_id]
        ctx = triggered_context(engine, owner, mover, _row(engine, owner, KNEE), intent)
        ctx.origin_save = json.loads(condition.data["origin_save_json"])
        ctx.failed_save = bool(condition.data["save_failed"])
        start = len(engine.events)
        run_effects(ctx, [json.loads(condition.data["effect_json"])])
        landed = any(e.event_type == "CONDITION_APPLIED" and e.payload.get("condition_id") == "condition:typed.prone"
                     and mover.entity_id in e.target_ids for e in engine.events[start:])
        if landed:
            fell = True
            placed.note(engine, KNEE, owner,
                f"Knot the Knee: {mover.display_name} fails the Dexterity save and falls Prone after {KNEE_FALL_FT} feet "
                f"of movement.", targets=(mover,))
    if not fell:
        return None
    return {"stop": True, "source_id": KNEE,
            "label": f"Knot the Knee makes {mover.display_name} fall Prone after {KNEE_FALL_FT} feet."}


@hook("event")
def clear_unwalked_falls(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A stopped-before-entry move owes no future fall; rollback restores evented state normally."""
    if event_type != "MOVEMENT_COMMITTED" or (kwargs.get("payload") or {}).get("forced"):
        return
    mover = engine.state.actors.get(kwargs.get("actor_id"))
    if mover is not None:
        for condition in list(mover.conditions.values()):
            if condition.condition_id.startswith(PENDING + "."):
                engine._remove_condition(mover, condition.condition_id, KNEE)


def _step_allies(engine: Any, owner: Any, vessel_zone: Any) -> list[Any]:
    """Willing allies the printed text can reach: "one willing ally within 5 feet of it"."""
    return [actor for actor in engine.state.actors.values()
            if actor.active and actor.entity_id != owner.entity_id and actor.team_id == owner.team_id
            and engine.grid.distance_ft(actor.position, vessel_zone.center) <= STEP_FT]


@hook("vessel_moved")
def vessel_moved(ctx: Any, zone: Any, previous: Any) -> None:
    """Threaded Step Formation: the printed trigger is the owner's own vessel movement.

    The receipt comes from the vessel movement routes (combat/ext/vessel.py), so it runs exactly
    when that vessel actually walked and after it has arrived, which is what the printed line asks
    for.  It is inert without the talent, without a live thread and without a willing ally.
    """
    from ..typed_executor import bears_mark
    from .rider_choices import pick, step

    engine, owner = ctx.engine, ctx.actor
    owned = vessel.kit(engine, owner)
    if owned is None or STEP not in owned["owned"]:
        return
    if owner.turn_flags.get(USED) == engine.state.round_number:
        return  # "Use Threaded Step Formation once per turn"
    if zone not in vessel.threaded_vessels(engine, owner, owned) or zone.center == previous:
        return  # a moved vessel that left the thread cannot carry an ally
    allies = _step_allies(engine, owner, zone)
    marked = [actor for actor in engine.state.actors.values()
              if actor.active and actor.team_id != owner.team_id and bears_mark(actor, owner.entity_id, MARK)]
    if not allies:
        return
    options = {actor.entity_id: actor for actor in allies}
    protection = ("without provoking Opportunity Attacks from one creature carrying your Tension Mark."
                  if marked else "This movement can provoke Opportunity Attacks because you have no marked enemy.")
    picked = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "THREADED_STEP", zone.zone_id),
        owner, "choice:needle.threaded_step", list(options),
        labels={aid: f"{actor.display_name} moves {STEP_FT} feet" for aid, actor in options.items()},
        prompt=f"Threaded Step Formation: your puppet vessel moved to ({zone.center.x}, {zone.center.y}). Choose one "
               f"willing ally within {STEP_FT} feet of it; that ally may move {STEP_FT} feet this turn "
               f"{protection} Use it once per turn.",
        name="Threaded Step Formation", target_id=owner.entity_id, allow_decline=True,
        prompt_context={"cost": "Free with the vessel movement you just made; no extra Action, Reaction or cultivation point"})
    if not picked:
        return
    ally = options[picked[0]]
    chosen = pick(engine, owner, "threaded_step_exempt", "Threaded Step Formation", [a.entity_id for a in marked],
        subject=ally, labels={a.entity_id: a.display_name for a in marked}, optional=len(marked) > 1,
        trigger=f"Choose which of your marked creatures cannot take an Opportunity Attack at {ally.display_name}",
        prompt_context={"cost": "Included in the movement above; no additional payment"}) if marked else []
    owner.turn_flags[USED] = engine.state.round_number
    moved = step(engine, ally, "threaded_step_move", "Threaded Step Formation", owner, STEP_FT, STEP, ctx.intent,
        trigger=f"your puppet vessel moved next to {ally.display_name}", ignored_oa=[chosen[0]] if chosen else [])
    placed.note(engine, STEP, owner,
        f"Threaded Step Formation: {ally.display_name} "
        + (f"moves up to {STEP_FT} feet to ({ally.position.x}, {ally.position.y})"
           + (f" without provoking an Opportunity Attack from {engine.state.actors[chosen[0]].display_name}."
              if chosen else "; this movement can provoke Opportunity Attacks.")
           if moved else "declines to move."), targets=(ally,))


@effect("vessel_threaded_step")
def legacy_step_row(ctx: Any, eff: Any) -> None:
    """Old sealed effect rows remain readable; only a completed vessel receipt grants a step."""
