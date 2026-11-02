"""Shared save provenance and repeatable-condition helpers for blossom, flowers_sphere and warleader_shouts: save_of and repeatable.

Bell of Clarity (Sound): "Choose creatures up to your Proficiency Bonus within range. Each target may immediately repeat one
saving throw against Charmed, Frightened, Deafened, ... On a success, the effect ends for that target."

A save-imposed condition remembers the save it came from (``origin_save`` in its data, typed_executor.block_save); one that
repeats on its own turn carries ``repeat_save``. Either is enough to roll the save again here. A condition with no save behind
it (an attack, a plain "is Frightened") has nothing to repeat, so the bell does nothing for it -- the text asks for a *repeat*
of a saving throw, not a new way out.

Typed as ``{"type": "repeat_save", "conditions": [...], "count": "pb"}`` on an ability aimed at one ally (or self); the other
targets are the next allies within range that also bear one of those conditions. Nothing the bell can help: the choice is not
offered. New rows opt in with ``choose_targets: true``: the caster chooses zero to PB creatures (including foes), then each
recipient may decline or select exactly one of its repeatable effects. The existing ``choice_options`` hook transports these
decisions without spending a Reaction, including off-turn player decisions. Old saved rows keep their original selection.

A hold's printed consequence of getting out of it by its own repeat save (rider lane C15, 2026-09-30): a condition row's
``on_repeat_success`` rows run, as the hold's user against the freed creature, when the engine's end-of-turn repeat save ends
that hold ("At the end of each of its turns, the target repeats the Strength saving throw, ending the Restrained portion of
the effect on a success. If the target succeeds, it remains Bound until the start of its next turn": Chain Prison). Read from
the ``hold_escaped`` report (combat/ext/hold_escapes.py, way "repeat_save"), so it covers holds: grips, restraints, pins and
Bound. A row without the key changes nothing.

``ordinary_repeat_ends`` conservatively recognizes the engine's supported end-on-success source contract.
``attempt_repeat`` is the shared "roll that condition's original save and end it on a success" step, for a printed
ability whose own trigger and price are elsewhere (Meridian Reinforcement). The Bell of Clarity effect below keeps its own
inline roll, because it first asks WHICH condition to repeat.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

DEFAULT_CONDITIONS = ("charmed", "frightened", "deafened")
PREFIX = "condition:typed."


def save_of(condition: Any) -> dict[str, Any] | None:
    """Return the stored originating/repeated save when it has an ability and DC."""
    data = condition.data or {}
    save = data.get("origin_save") or data.get("repeat_save")
    return save if isinstance(save, dict) and save.get("ability") and save.get("dc") else None


def repeatable(subject: Any, names: tuple[str, ...]) -> list[tuple[str, Any]]:
    """The conditions of subject's that a repeated save could end, easiest DC first (one save is rolled against one of them)."""
    found = [(iid, c) for iid, c in subject.conditions.items()
             if c.condition_id.startswith(PREFIX) and c.condition_id[len(PREFIX):] in names and save_of(c) is not None]
    return sorted(found, key=lambda pair: (int(save_of(pair[1])["dc"]), pair[0]))


def ordinary_repeat_ends(condition: Any) -> bool:
    """Whether the stored source contract is the engine's ordinary end-on-success repeat.

    Meridian Reinforcement uses this conservative check. Origin provenance alone says
    nothing about removal. Unknown restrictions or progress contracts stay with the GM;
    only the engine's supported ability/DC/when repeat record is accepted.
    """
    data = condition.data or {}
    repeat = data.get("repeat_save")
    origin = data.get("origin_save") or {}
    return (isinstance(repeat, dict) and bool(repeat.get("ability")) and bool(repeat.get("dc"))
            and set(repeat) <= {"ability", "dc", "when"}
            and repeat.get("when", "end") in {"start", "end"}
            and isinstance(origin, dict) and set(origin) <= {"ability", "dc"}
            and set(data) <= {"origin_save", "repeat_save", "label"})


def attempt_repeat(engine: Any, subject: Any, iid: str, condition: Any, source: str, *,
                   extra_mode: str | None = None) -> Any:
    """Roll a supported ordinary repeat contract, ending it on success. Returns None for unknown source semantics
    or when the engine declined to roll. Used by Meridian Reinforcement (combat/ext/meridian_reinforcement.py),
    whose repeat uses the ORIGINAL ability and DC; the Bell of Clarity effect below keeps its own
    inline roll because it also has to report a choice of which condition to repeat."""
    save = save_of(condition)
    if save is None or iid not in subject.conditions or not ordinary_repeat_ends(condition):
        return None
    dc = int(save["dc"])
    from .adaptations import ending_save_scope
    with ending_save_scope(engine, subject, condition):
        roll = engine._roll_save(subject, str(save["ability"]).upper(), dc, source, extra_mode,
                                 roll_context={"source_actor_id": condition.source_actor_id,
                                               "named": [condition.condition_id[len(PREFIX):]]})
    if roll is not None and roll.total >= dc and iid in subject.conditions:
        subject.conditions.pop(iid)
        engine._append_event("CONDITION_REMOVED", source, actor_id=subject.entity_id,
                             target_ids=(subject.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": iid, "repeat_save": True})
    return roll


# Internal callers keep their spelling; other plug-ins use the public helpers.
_save_of = save_of
_repeatable = repeatable


def _names(effect_row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(name).lower() for name in (effect_row.get("conditions") or DEFAULT_CONDITIONS))


def _in_reach(engine: Any, actor: Any, subject: Any, reach: int, *, any_creature: bool = False) -> bool:
    return subject.active and (any_creature or subject.team_id == actor.team_id) and (subject is actor or engine._distance_actor_to_actor(actor, subject) <= reach)


def _row(action: Any) -> dict[str, Any] | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    return next((row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "repeat_save"), None)


@hook("candidate_allowed")
def bell_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    row = _row(action)
    if row is None:
        return None
    reach = int(getattr(action, "range_ft", None) or 30)
    if row.get("choose_targets"):
        return any(_in_reach(engine, actor, subject, reach, any_creature=True) and _repeatable(subject, _names(row))
                   for subject in engine.state.actors.values())
    return any(_in_reach(engine, actor, subject, reach) and _repeatable(subject, _names(row))
               for subject in (engine.state.actors.get(target_id) for target_id in candidate.target_ids) if subject is not None)


@hook("choice_options")
def bell_choices(engine: Any, intent: Any, checkpoint: str, reactor_id: str, choice_id: str,
                 context: dict[str, Any]) -> dict[str, Any] | None:
    """Only this plug-in's scoped target/save choices; every other checkpoint is inert."""
    if choice_id not in ("choice:repeat_save.targets", "choice:repeat_save.effect") or not context.get("repeat_save_options"):
        return None
    return {"option_ids": context["repeat_save_options"], "minimum_selections": context["minimum"],
            "maximum_selections": context["maximum"], "allow_decline": True, "automatic_use": True,
            "preferred_option_ids": context["preferred"]}


def _choose(ctx: Any, chooser: Any, kind: str, options: list[str], labels: dict[str, str], *, maximum: int,
            preferred: list[str], prompt: str, minimum: int = 0) -> list[str]:
    """Use the documented choice transport, with deterministic defaults for engines without a provider."""
    if not options:
        return []
    fallback = preferred[:maximum]
    if ctx.intent is None or not hasattr(ctx.engine, "_gate4_reaction_cache"):
        return fallback
    # The AI preview pauses TYPED checkpoints; reserve that prefix for player Ask me owners.
    prefix = "TYPED:" if chooser.entity_id in getattr(ctx.engine, "typed_ask_reactors", ()) else "CHOICE:"
    checkpoint = f"{prefix}Bell of Clarity {kind}@{ctx.engine.state.event_sequence}:{chooser.entity_id}"
    context = {"actor_id": ctx.actor.entity_id, "target_id": chooser.entity_id, "ability": ctx.action.display_name,
               "repeat_save_options": options, "labels": labels, "prompt": prompt, "minimum": minimum,
               "maximum": min(maximum, len(options)), "preferred": preferred}
    decision = ctx.engine._reaction_decision(ctx.intent, checkpoint, chooser.entity_id, f"choice:repeat_save.{kind}", context=context)
    if decision is None:
        return fallback
    return [] if decision.selection == "DECLINE" else list(decision.option_ids)


@effect("repeat_save")
def repeat_save(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    names = _names(eff)
    reach = int(getattr(ctx.action, "range_ft", None) or eff.get("range_ft") or 30)
    count = max(1, ctx.formula(eff.get("count") or "pb"))
    aimed = ctx.target if ctx.target is not None else actor
    others = sorted((other for other in engine.state.actors.values() if other is not aimed and _in_reach(engine, actor, other, reach)),
                    key=lambda other: (engine._distance_actor_to_actor(actor, other), other.entity_id))
    chosen = [subject for subject in [aimed, *others] if _in_reach(engine, actor, subject, reach) and _repeatable(subject, names)][:count]
    if eff.get("choose_targets"):
        available = sorted((subject for subject in engine.state.actors.values()
                            if _in_reach(engine, actor, subject, reach, any_creature=True) and _repeatable(subject, names)),
                           key=lambda subject: (subject is not aimed, subject.team_id != actor.team_id,
                                                engine._distance_actor_to_actor(actor, subject), subject.entity_id))
        selected = _choose(ctx, actor, "targets", [s.entity_id for s in available],
                           {s.entity_id: s.display_name for s in available}, maximum=count,
                           preferred=[s.entity_id for s in available if s.team_id == actor.team_id],
                           prompt=f"{actor.display_name} uses Bell of Clarity: choose up to {count} creatures to offer a repeated save.")
        chosen = [engine.state.actors[entity_id] for entity_id in selected]
    if not chosen:
        ctx.rider("Bell of Clarity: no creatures selected." if eff.get("choose_targets")
                  else "Bell of Clarity: no creature in range bears a saving-throw effect to repeat.")
        return
    for subject in chosen:
        repeatable = _repeatable(subject, names)
        if not repeatable:
            continue  # An earlier recipient's save/reaction may have ended this effect already.
        if eff.get("choose_targets"):
            selected = _choose(ctx, subject, "effect", [iid for iid, c in repeatable],
                               {iid: f"{c.condition_id.removeprefix(PREFIX)} ({_save_of(c)['ability']}, DC {_save_of(c)['dc']})"
                                for iid, c in repeatable}, maximum=1, minimum=1,
                               preferred=[repeatable[0][0]],
                               prompt=f"Bell of Clarity used by {actor.display_name}: {subject.display_name} may repeat one saving throw or decline.")
            if not selected:
                continue
            iid, condition = next(pair for pair in repeatable if pair[0] == selected[0])
        else:
            iid, condition = repeatable[0]
        save = _save_of(condition)
        dc = int(save["dc"])
        from .adaptations import ending_save_scope
        with ending_save_scope(engine, subject, condition):
            roll = engine._roll_save(subject, str(save["ability"]).upper(), dc, ctx.source,
                roll_context={'source_actor_id': condition.source_actor_id,
                              'named': [condition.condition_id[len(PREFIX):]]})
        if roll.total >= dc and iid in subject.conditions:
            subject.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(subject.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid, "repeat_save": True, "bell_of_clarity": True})


@hook("hold_escaped")
def on_repeat_success(engine: Any, record: dict[str, Any]) -> None:
    if record.get("way") != "repeat_save":
        return
    from .. import typed_executor as te

    holder = engine.state.actors.get(record.get("holder") or "")
    for hold in record.get("holds") or []:
        action = engine.action_catalog.get(str(hold.get("source") or "").split("#")[0])
        owner = engine.state.actors.get(hold.get("owner") or "")
        if action is None or owner is None or holder is None or not holder.active:
            continue
        typed = (action.parameters or {}).get("typed") or {}
        name = str(hold.get("condition_id") or "").removeprefix(PREFIX)
        rows = next((row["on_repeat_success"] for row in te._walk_rows(typed.get("effects") or [])
                     if row.get("type") == "condition" and str(row.get("condition") or "").lower() == name
                     and row.get("repeat_save") and row.get("on_repeat_success")), None)
        if rows:
            ctx = te.Context(engine, owner, action, getattr(engine, "_active_intent", None), typed, [holder], holder, {})
            te.run_effects(ctx, list(rows))
