"""Jester: Set the Scene, the Foil, Deliver the Punchline (owner 2026-09-29: "i want everything we can automated";
BLOCKED_SYSTEMS.md "Jester Proposition / Foil / Punchline chain").

Rules source (LocalSources/04_spheres_talents/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md, Jester):

- Set the Scene (Bonus Action, 60 ft, one creature that can see or hear you): "Choose one creature as your Foil and one Proposition.
  You may have only one Foil at a time ... Until the start of your next turn."  The four Propositions are printed as "Choose one".
- Deliver the Punchline (Reaction): "Use one Punchline talent you know whose trigger is compatible with the fulfilled Proposition."
  "One fulfilled Proposition allows one Punchline; after you deliver a Punchline, Set the Scene ends."
- Flustered: "Until the start of your next turn, a Flustered creature cannot take Reactions; has Disadvantage on the next attack roll
  or ability check it makes.  After that roll, the Disadvantage portion ends, but the creature still cannot take Reactions until
  the condition ends."

How it runs.
- Set the Scene is a "Choose one" ability: one action per Proposition (the compiler's own option actions).  Each option's effect is
  ``jester_foil`` -- the Foil gets the mark "Foil: <Proposition>" (a mark this Jester placed: combat/typed_executor.py block_mark, so it
  ends at the start of the Jester's next turn) and any Foil the Jester already had loses its mark ("only one Foil at a time").
- A Punchline talent is a Reaction whose trigger reading (authority/typed_mechanics/trigger_readings.jsonl) needs that mark, so it
  answers only its own Proposition, and only from the Foil: the generic reaction machinery (combat/typed_reactions.py) does the rest --
  "Come Closer" is an ``enters_range`` reading (moves 5 feet toward the Jester, or into its reach), "Ignore the Fool" an
  ``ally_attacked`` one, "Show Your Hand" a ``technique_used`` one; "Strike the Fool" has no Punchline typed yet (see the report).
  The Reaction is the Jester's own, spent as for any Reaction.
- ``jester_end_scene`` (last effect of every Punchline): "after you deliver a Punchline, Set the Scene ends" -- every Foil mark this
  Jester placed comes off, so one Proposition allows one Punchline.
- ``flustered``: the condition of that name (combat/rules/typed_conditions.json: cannot take Reactions), lasting until the start of the
  Jester's next turn.  Its "Disadvantage on the next attack roll" is kept in the condition's data and given by the ``attack_mode``
  hook to the next attack roll, which uses it up (the condition is put back without it: state changes only through evented calls).
  Newly compiled Jester packets also supply check-mode data and consume the shared penalty after a real CHECK_ROLLED or native
  ATTACK_ROLLED event. Historical sealed packets without the owned flag keep their original attack-only behavior.
- ``jester_applause`` (Applaud the Master, The Audience Chooses the Hero): the ally the Foil is attacking gets its bonus against that
  roll only and, "if the attack misses ... the Foil becomes Flustered" -- a watch on the ally that the ``after_hit`` / ``after_miss``
  hooks settle when that attack has been rolled (no hook was added).


Shared API used by jester_riders: foil_mark names the owner's proposition mark; drop_foils removes all that owner's existing Foil marks through events. jester uses jester_riders keeps_foils and focused_applause for scene limits and Martial Focus rewards.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

PROPOSITIONS = ("Come Closer", "Strike the Fool", "Ignore the Fool", "Show Your Hand")
FLUSTERED = "flustered"
WATCH = "jester_applause"


def foil_mark(proposition: str) -> str:
    return f"Foil: {proposition}"


def _conditions():
    from ..typed_executor import CONDITION_PREFIX

    return CONDITION_PREFIX + FLUSTERED, CONDITION_PREFIX + WATCH


def drop_foils(ctx: Any) -> int:
    """Take every Foil mark this Jester placed off whoever bears it (each removal is an ordinary evented condition removal)."""
    from ..typed_executor import bears_mark, mark_condition_id

    owner = ctx.actor.entity_id
    count = 0
    for holder in list(ctx.engine.state.actors.values()):
        for proposition in PROPOSITIONS:
            if bears_mark(holder, owner, foil_mark(proposition)):
                ctx.engine._remove_condition(holder, mark_condition_id(foil_mark(proposition), owner), ctx.source)
                count += 1
    return count


@effect("jester_foil")
def run_foil(ctx: Any, eff: dict[str, Any]) -> None:
    """Set the Scene: the chosen creature becomes the Foil for the chosen Proposition."""
    from ..typed_executor import block_mark

    proposition = str(eff.get("proposition") or "")
    if proposition not in PROPOSITIONS:
        return
    foils = [subject for subject in ([ctx.target] if ctx.target is not None else list(ctx.targets)) if subject is not None and subject.active]
    if not foils:
        return
    from .jester_riders import keeps_foils

    if not keeps_foils(ctx):  # (Recluse-at-Court Incarnation: "maintain up to three Foils at once"; combat/ext/jester_riders.py)
        drop_foils(ctx)  # "You may have only one Foil at a time"
    block_mark(ctx, {"type": "mark", "mark": foil_mark(proposition), "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"}})
    ctx.rider(f"{foils[0].display_name} is your Foil: {proposition}. It fulfils the Proposition when {_fulfilled(proposition)}")


def _fulfilled(proposition: str) -> str:
    return {"Come Closer": "it willingly moves at least 5 feet toward you or willingly enters your reach.",
            "Strike the Fool": "it makes an attack roll against you.",
            "Ignore the Fool": "it targets another creature with an attack roll or harmful effect while it can see or hear you.",
            "Show Your Hand": "it takes the Magic action or activates an explicitly supernatural technique."}[proposition]


@effect("jester_end_scene")
def run_end_scene(ctx: Any, eff: dict[str, Any]) -> None:
    """"After you deliver a Punchline, Set the Scene ends."""
    if drop_foils(ctx):
        ctx.rider("Set the Scene ends.")


@effect("flustered")
def run_flustered(ctx: Any, eff: dict[str, Any]) -> None:
    """The Foil (or whoever the effect names) becomes Flustered until the start of the Jester's next turn."""
    from ..typed_executor import _default_subject, effect_expiry

    flustered, _ = _conditions()
    from .jester_riders import rows
    checks = bool(eff.get('check_penalty')) or any(row.get('auto65') for row in rows(ctx.engine, ctx.actor, 'flustered_checks'))
    for subject in _default_subject(ctx, {"applies_to": eff.get("applies_to") or "target"}, harmful=True):
        if not subject.active:
            continue
        ctx.engine._remove_condition(subject, flustered, ctx.source)
        expiry = effect_expiry(ctx, eff, subject, condition=True) if eff.get('duration') or eff.get('expires_on') else "START_OF_SOURCE_NEXT_TURN"
        ctx.engine._apply_condition(subject, flustered, ctx.source, ctx.actor.entity_id, expires_on=expiry,
                                    data={"disadvantage": True, "label": "Flustered: no Reactions; Disadvantage on its next attack roll or ability check",
                                          **({'auto65': 1, 'rule': {'check_mode': {'ALL': 'DISADVANTAGE'}, 'attacks_have': 'DISADVANTAGE'}} if checks else {})})
        subject.reaction_available = False  # as typed_executor.block_condition does for a condition that takes Reactions
        duration = eff.get("duration") or ""
        kind = duration.get("kind") if isinstance(duration, dict) else duration
        source_clock = not (eff.get('expires_on') or kind == 'until_start_of_next_turn')
        ending = "end" if kind == "until_end_of_your_next_turn" else "start"
        clock_owner = "your" if source_clock else "its"
        ctx.rider(f"{subject.display_name} is Flustered: it can't take Reactions until the {ending} of {clock_owner} next turn and has Disadvantage on the "
                  f"next attack roll or ability check it makes" + ('.' if checks else ' (the attack roll is automatic; the ability check is the GM\'s).'))


def _watching(actor: Any) -> list[tuple[str, Any]]:
    _, watch = _conditions()
    return [(iid, condition) for iid, condition in actor.conditions.items() if condition.condition_id == watch]


@effect("jester_applause")
def run_applause(ctx: Any, eff: dict[str, Any]) -> None:
    """Applaud the Master / The Audience Chooses the Hero: the creature the Foil is attacking gets ``ac`` against that attack roll only,
    and if that attack misses the Foil becomes Flustered.  Runs as the bystander's reaction, so the protected creature is the ally."""
    ally = ctx.engine.state.actors.get(ctx.typed.get("protects") or "")
    foil = ctx.target
    if ally is None or foil is None:
        ctx.rider("No creature is being attacked: the Punchline has nothing to protect.")
        return
    _, watch = _conditions()
    for iid, _condition in _watching(ally):
        ctx.engine._remove_condition(ally, watch, ctx.source)
    ac = int(eff.get("ac") or 0)
    ctx.engine._apply_condition(ally, watch, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"foil": foil.entity_id, "ac": ac, "label": f"Applauded by {ctx.actor.display_name}: "
                                      + (f"+{ac} AC against the Foil's attack roll; " if ac else "") + f"if it misses, {foil.display_name} is Flustered"})


@hook("ac")
def applause_ac(engine: Any, target: Any) -> int:
    return sum(int((condition.data or {}).get("ac") or 0) for _, condition in _watching(target))


def _settle(ctx: Any, target: Any, missed: bool) -> None:
    for iid, condition in _watching(target):
        data = condition.data or {}
        if data.get("foil") != ctx.actor.entity_id:
            continue  # someone else's attack: the applause waits for the Foil's own roll
        jester = ctx.engine.state.actors.get(condition.source_actor_id)
        ctx.engine._remove_condition(target, condition.condition_id, ctx.source)
        if missed and jester is not None:
            from ..typed_executor import Context

            inner = Context(ctx.engine, jester, ctx.action, ctx.intent, ctx.typed, [ctx.actor], ctx.actor, {})
            run_flustered(inner, {"applies_to": "target"})
            from .jester_riders import focused_applause

            focused_applause(ctx.engine, jester)  # Focused Applause: "When your Punchline causes an attack to miss"
        break


@hook("after_hit")
def applause_hit(ctx: Any, target: Any, kind: str) -> None:
    _settle(ctx, target, False)


@hook("after_miss")
def applause_miss(ctx: Any, target: Any) -> None:
    _settle(ctx, target, True)


def spent_flustered_data(data: dict[str, Any]) -> dict[str, Any]:
    """Retain lifetime metadata while retiring Flustered's one-roll modes."""
    updated = {**data, "disadvantage": False}
    rule = dict(data.get("rule") or {})
    rule.pop("check_mode", None)
    rule.pop("attacks_have", None)
    if rule:
        updated["rule"] = rule
    else:
        updated.pop("rule", None)
    return updated


@hook("attack_mode")
def flustered_disadvantage(ctx: Any, target: Any) -> str | None:
    """"Has Disadvantage on the next attack roll ... After that roll, the Disadvantage portion ends, but the creature still cannot take
    Reactions until the condition ends."""
    flustered, _ = _conditions()
    for iid, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id != flustered or not (condition.data or {}).get("disadvantage"):
            continue
        if (condition.data or {}).get('auto65'):
            # Mode queries precede declared-attack reactions, which can cancel
            # the attack. New packets consume on the actual roll receipt below.
            return "DISADVANTAGE"
        # Spending the next-roll penalty changes this same condition instance;
        # it does not make the creature Flustered again or restart its clock.
        ctx.engine._update_condition_data(ctx.actor, condition,
            {**spent_flustered_data(condition.data), "label": "Flustered: no Reactions (its next-roll Disadvantage is used up)" if (condition.data or {}).get('auto65') else "Flustered: no Reactions (its attack-roll Disadvantage is used up)",
             **({'auto65': 1} if (condition.data or {}).get('auto65') else {})}, ctx.source)
        return "DISADVANTAGE"
    return None


@hook('event')
def flustered_check_used(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Consume new Flustered packets only after a real check/native attack, even when modes cancel."""
    from .roll_context import check_receipts

    if event_type == 'CHECK_ROLLED':
        actor_ids = [actor_id for actor_id, _ in check_receipts(kwargs)]
    else:
        roll = kwargs.get('payload') or {}
        actor_ids = [roll.get('actor_id')] if (str(roll.get('reason') or '').startswith('ATTACK:')
            and type(roll.get('natural_result')) is int and 1 <= roll['natural_result'] <= 20) else []
    for actor_id in actor_ids:
        actor = engine.state.actors.get(actor_id)
        if actor is None:
            continue
        for condition in list(actor.conditions.values()):
            data = condition.data or {}
            if condition.condition_id != 'condition:typed.flustered' or not data.get('auto65') or not data.get('disadvantage'):
                continue
            # Retain the applied condition and its expiry. This is bookkeeping,
            # not a fresh CONDITION_APPLIED event for downstream triggers.
            engine._update_condition_data(actor, condition,
                {**spent_flustered_data(data), 'auto65': 1,
                 'label': 'Flustered: no Reactions (its next-roll Disadvantage is used up)'},
                condition.source_definition_id)


def _proposition_of(action: Any) -> str | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    for row in typed.get("effects") or []:
        if isinstance(row, dict) and row.get("type") == "jester_foil":
            return str(row.get("proposition") or "") or None
    return None


@hook("ai_candidate_allowed")
def only_a_proposition_with_a_punchline(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The built-in AI sets the scene only for a Proposition it has a Punchline for (a player may choose any)."""
    proposition = _proposition_of(action)
    if proposition is None:
        return None
    from .. import typed_reactions

    return any(row.get("requires_mark") == foil_mark(proposition) for row in typed_reactions._rows(engine, actor.entity_id, "generic"))
