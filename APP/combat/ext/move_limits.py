"""A creature that "cannot willingly move closer to" someone, or has Disadvantage on attacks against someone (rider lane 3, 2026-09-29).

  movement_bar  {"applies_to": "target", "avoid": "source" | "ally", "duration": "until_start_of_next_turn"}
  attack_bar    {"applies_to": "target", "avoid": "ally", "duration": "until_start_of_next_turn"}

Headsman's Red Line ("Failed Save: Until the start of your next turn, the target cannot willingly move closer to one ally of your
choice that it can see or hear. Successful Save: The target can move normally, but it has Disadvantage on the next attack roll it makes
against that ally"), Poleaxe Gate ("prevent it from moving closer to you until the start of your next turn").

``avoid`` names the creature to keep away from: ``"source"`` is the creature that used the ability ("you"); ``"ally"`` is "one ally of
your choice" -- selected through the owner's bounded choice. Sight qualifies
the candidate; hearing-only eligibility remains a GM qualification because the
engine has no observer-specific hearing contract. No ally means no rider.

movement_bar   puts ``condition:typed.no_approach`` on the creature; the ``candidate_allowed`` hook (combat/gate4_engine.py legal_candidates,
               which also lists every Move square) rejects a path if any successive step moves nearer to that creature.
               The canonical path is the one the engine will traverse, including obstacle detours. A typed movement (a teleport, a Dash's
               extra Speed) and a forced push or pull are not "willingly move" and are untouched.
attack_bar     the next attack roll the creature makes against that one has Disadvantage -- the Vex shape reversed (``attack_mode_vs``,
               spent by that roll, hit or miss; typed_executor._use_vex).

Tethers (rider lane C15, 2026-09-30 -- shared helper; BLOCKED_CENSUS.md row 31): a condition that ties the creature to an anchor
with a maximum length. Its Move squares farther than that from the anchor are not offered (player and AI alike); teleports,
pushes and pulls are not willing moves and are untouched (what happens to the tether then is its owner's rule).
  data {"tether_ft": n}                 the generic shape (typed rows give it through ``condition_data``): anchored at the
                                        creature that applied the condition, while that creature is active -- the Chains
                                        sphere's Bound ("cannot willingly increase the distance from the Tether beyond the
                                        Tether's maximum length"), combat/ext/chains_sphere.py
  register_tether(condition_id, reader) a plug-in whose saved conditions keep another shape says how to read them:
                                        reader(engine, condition, holder) -> (anchor Position, feet) or None (chain_tethers.py:
                                        Meridian Tether, 20 feet from its owner; Prison Tether, the prison's radius)
  tether(engine, condition, holder)             the (anchor, feet) a condition holds its creature to, or None
  tether_to(engine, anchor_actor, held)  the length in feet of a tether ``anchor_actor`` controls that holds ``held``, or
                                        None when there is none. One reader for every tether shape above, so a printed
                                        ability that says "a tether attached to a creature" (Brute's Get Over Here) asks
                                        one question and never repeats a sphere's private tether shape.

Reach: "natural reach" (a printed requirement, e.g. Get Over Here's "talents requiring natural reach function only if the
target ends within natural reach") is combat/ext/reach_bonus.natural_reach_ft. This module owns movement bars and tethers
only: natural reach is a printed body increase, and that module already reads the rows that carry it.
"""
from typing import Any

from . import effect, hook

CONDITION = "condition:typed.no_approach"
_TETHER_READERS: dict[str, Any] = {}


def register_tether(condition_id: str, reader: Any) -> None:
    """A plug-in's reader for its own tether-shaped conditions (see the module docstring)."""
    _TETHER_READERS[condition_id] = reader


def tether(engine: Any, condition: Any, holder: Any = None) -> tuple[Any, int] | None:
    """The anchor square and the length a condition ties its creature with, or None."""
    reader = _TETHER_READERS.get(condition.condition_id)
    return reader(engine, condition, holder) if reader is not None else plain_tether(engine, condition)


def plain_tether(engine: Any, condition: Any) -> tuple[Any, int] | None:
    """The generic shape every unregistered tether shares: an integer ``tether_ft`` from the active creature
    that applied the condition. Shared by ``tether`` and by a registered reader that only has to add its own
    qualification (spirit_seals.py's Binding Seal, which a suppression ends)."""
    length = (condition.data or {}).get("tether_ft")
    if type(length) is not int or length <= 0:
        return None
    anchor = engine.state.actors.get(condition.source_actor_id or "")
    return (anchor.position, length) if anchor is not None and anchor.active else None


def tether_to(engine: Any, holder: Any, held: Any) -> int | None:
    """The length in feet of a tether ``holder`` controls that holds ``held``, or None.

    "Holder" owns the tether's controlled end (the creature that applied the condition and is still active), "held" is the
    creature it is attached to. Reads every shape ``tether`` knows -- the generic ``tether_ft`` condition and any
    ``register_tether`` reader -- so a caller never repeats a sphere's private tether data. Pure: reads state only.

    Users: combat/ext/brute_tether.py (Get Over Here's "you control one end of a tether attached to a creature").
    """
    if holder is None or held is None or not (holder.active and held.active):
        return None
    best: int | None = None
    for condition in held.conditions.values():
        if condition.source_actor_id != holder.entity_id:
            continue
        tied = tether(engine, condition, held)
        if tied is None or tied[0] != holder.position:
            continue
        feet = int(tied[1])
        best = feet if best is None else max(best, feet)
    return best


def chosen(ctx: Any, subject: Any, row: dict[str, Any]) -> Any:
    """Ask the caster which eligible ally this effect protects; decline is inert."""
    if row.get("avoid") != "ally":
        return ctx.actor
    engine = ctx.engine
    from .. import stealth
    from . import needle

    allies = sorted((other for other in engine.state.actors.values()
                     if other.active and other.team_id == ctx.actor.team_id
                     and other.entity_id not in (ctx.actor.entity_id, subject.entity_id)
                     and stealth.sees(engine, subject, other)),
                    key=lambda other: (engine._distance_actor_to_actor(subject, other), other.entity_id))
    ids = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, 'RED_LINE_ALLY', ctx.source, subject.entity_id),
        ctx.actor, 'choice:needle.red_line_ally', [a.entity_id for a in allies],
        labels={a.entity_id: a.display_name for a in allies},
        prompt=f"Headsman's Red Line: {ctx.action.display_name} — choose an ally protected from {subject.display_name}",
        name="Headsman's Red Line", target_id=subject.entity_id, maximum=1, allow_decline=True)
    return engine.state.actors[ids[0]] if ids else None


@effect("movement_bar")
def movement_bar(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    for subject in _default_subject(ctx, row, harmful=True):
        if not subject.active:
            continue
        avoided = chosen(ctx, subject, row)
        if avoided is None:
            continue
        ctx.engine._apply_condition(subject, CONDITION, ctx.source, ctx.actor.entity_id,
                                    expires_on=effect_expiry(ctx, row, subject, condition=True) or "START_OF_SOURCE_NEXT_TURN",
                                    data={"avoid": avoided.entity_id, "label": f"Cannot willingly move closer to {avoided.display_name}"})


@effect("attack_bar")
def attack_bar(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, _use_vex, effect_expiry

    for subject in _default_subject(ctx, row, harmful=True):
        if not subject.active:
            continue
        avoided = chosen(ctx, subject, row)
        if avoided is None:
            continue
        ctx.engine._add_modifier(subject, ctx.source, "attack_mode_vs", "SET", f"DISADVANTAGE:{avoided.entity_id}", "NEXT_ATTACK",
                                 expires_on=effect_expiry(ctx, row, subject) or "START_OF_SOURCE_NEXT_TURN")


@hook("candidate_allowed")
def gate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if getattr(candidate.kind, "value", candidate.kind) != "MOVE" or candidate.destination is None:
        return None
    for held in actor.conditions.values():
        tied = (tether(engine, held, actor) if (held.condition_id in _TETHER_READERS or "tether_ft" in (held.data or {}))
                else None)
        if tied is not None and engine.grid.distance_ft(candidate.destination, tied[0]) > tied[1]:
            return False  # beyond the tether's length
    for held in actor.conditions.values():
        if held.condition_id != CONDITION:
            continue
        avoided = engine.state.actors.get(str((held.data or {}).get("avoid") or ""))
        if avoided is None or not avoided.active:
            continue
        previous = engine.grid.distance_ft(actor.position, avoided.position)
        for step in (*candidate.canonical_path, candidate.destination):
            distance = engine.grid.distance_ft(step, avoided.position)
            if distance < previous:
                return False
            previous = distance
    return None
