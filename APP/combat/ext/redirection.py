"""Shared retarget eligibility/choice API (legal_target, owns, provider, constraint) for mount_guard and redirect_reactions.

The one owner of the lock round's ``retarget_attack`` hook (automation lane H2, 2026-09-29).

The engine allows exactly one plug-in to answer ``retarget_attack`` (combat/attack_declaration.py: "one plugin must own attack
redirection"), so abilities that change an attack's target before it is rolled cannot each register their own. They register a
*provider* here instead; the first provider (lowest priority number) that answers wins, and its answer is the attack's target
(``{"source_id", "target_id", "cover_bonus"}``, the engine's own shape). A provider must return None unless it really redirects,
and must never return a target the engine would reject (an inactive creature, the attacker, one out of sight or out of range):
``legal_target`` below is the engine's own test.

TWO KINDS OF ANSWER, AND WHY THEY ARE ASKED IN THAT ORDER (AUTO52r2f1, 2026-10-05).  A provider answers *for the defender*
("redirect the attack to yourself", "turn it on another creature"): it takes an attack already aimed somewhere and moves it.
A *constraint* answers *for the attacker*, about whether it may declare the attack at all and against whom -- the printed
"the first time on each of its turns that it targets a creature other than you with an attack, it must make a saving throw ...
on failure it must choose you if legal".  A defender's redirection cannot answer that question, and winner-takes-first let it
pretend to: because only the first answer counted, Defensive Rider (priority 10) or Harmonious Body (40) could re-aim a
Captivated creature's first attack without ever running its save, offering its player the remedy or spending its printed
clock.  So the two kinds are separate registries and the constraints are asked first, in priority order among themselves,
and each attack's constraint stage is asked exactly once -- the constraint that wins decides what the attacker may declare,
and no other constraint is asked about that declaration afterwards, so a save is never run twice on one attack and no
redirection recurses through this hook.

WHAT A CONSTRAINT'S ANSWER DOES *NOT* DO (AUTO52r3f1, 2026-10-05).  Winning the constraint stage settles the attacker's
declaration; it does not delete the new target's own printed defences.  A constraint that answers names the creature the
attack is now aimed at, and that creature's defensive redirections are then answered for the attack it now faces -- the
providers are asked with the *resulting* defender in place of the declared one, so a captive told to aim at a charmer who
owns Meat Shield is still offered Reactive Cover ("Reaction when targeted by an attack roll"), and is still offered Defensive
Rider when the charmer is riding.  This is not a rerun of the declaration: the constraint stage is not consulted a second
time, so the attacker's save is asked once and its once-each-turn clock is spent once.  A constraint that returns None
leaves the declaration exactly as it was, and the providers answer for the declared defender as before, so a rule that only
*loses* an attack never costs a defender its printed redirection either.  Both registries are empty for a fight with no
such rule, so no attack moves that did not move before.

Also here: the feature block ``redirect`` (combat/rules/feature_blocks.d/zz_h2.json) that marks who owns which redirecting
ability, so the compiled fighter carries a passive row for it.
"""

from __future__ import annotations

from typing import Any, Callable

from . import hook

BLOCK = "redirect"
Provider = Callable[[Any, Any, Any, Any, dict[str, Any]], "dict[str, Any] | None"]
_PROVIDERS: list[tuple[int, str, Provider]] = []
_CONSTRAINTS: list[tuple[int, str, Provider]] = []


def provider(priority: int) -> Callable[[Provider], Provider]:
    """Register a redirecting ability: ``function(engine, attacker, defender, intent, context)``."""
    def register(function: Provider) -> Provider:
        _PROVIDERS.append((priority, f"{function.__module__}.{function.__name__}", function))
        _PROVIDERS.sort(key=lambda row: (row[0], row[1]))
        return function
    return register


def constraint(priority: int) -> Callable[[Provider], Provider]:
    """Register a printed constraint on the attacker's own declaration (see the module docstring).

    Same call and answer shape as :func:`provider` -- it may re-aim the attack -- but constraints are consulted before any
    redirection provider, each attack's constraint stage is asked exactly once, and a constraint's answer ends that stage:
    the attacker's own printed rule has decided what it may declare, and no other constraint is asked about it.  The
    creature the answer names is then the attack's defender, so its own printed defensive redirections are still answered.
    Use it only for a printed rule that constrains what the *attacker* may declare (its own saving throw, its own declared
    target); a rule that answers for the defender belongs in :func:`provider`.
    """
    def register(function: Provider) -> Provider:
        _CONSTRAINTS.append((priority, f"{function.__module__}.{function.__name__}", function))
        _CONSTRAINTS.sort(key=lambda row: (row[0], row[1]))
        return function
    return register


def rows(engine: Any, actor: Any, kind: str | None = None) -> list[dict[str, Any]]:
    """The actor's compiled ``redirect`` passive rows (optionally one kind)."""
    found = [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if row.get("block") == BLOCK]
    return [row for row in found if kind is None or row.get("kind") == kind]


def owns(engine: Any, actor: Any, kind: str) -> bool:
    return bool(rows(engine, actor, kind))


def legal_target(engine: Any, attacker: Any, target: Any, range_ft: int | None) -> bool:
    """The engine's own test of a redirected target (combat/attack_declaration.py): an active creature that is not the
    attacker, in sight, and within the attack's range or reach."""
    return (target is not None and target.active and target.entity_id != attacker.entity_id
            and bool(engine._line_of_sight_actor_to_actor(attacker, target))
            and (range_ft is None or engine._distance_actor_to_actor(attacker, target) <= range_ft))


@hook("compile_block")
def compile_redirect_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "keeps_compiling": bool(spec.get("keeps_compiling"))}]


@hook("retarget_attack")
def retarget(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    if not (_PROVIDERS or _CONSTRAINTS) or getattr(engine, "_redirection_busy", False):
        return None
    engine._redirection_busy = True  # an attack made by an answer to a redirection is not itself redirected again
    try:
        forced = None
        for _priority, _name, answer in _CONSTRAINTS:
            forced = answer(engine, attacker, defender, intent, context)
            if forced:
                break
        # A constraint that answered has settled what the attacker may declare, and that is final: no other
        # constraint is asked, so its own saving throw is not run again.  The attack now faces the creature the
        # answer names, and that creature's own printed defensive redirection is still answered for it (see the
        # module docstring); otherwise it faces the creature it was declared against, as before.
        current = defender if forced is None else engine.state.actors.get(forced.get("target_id"))
        if current is None:
            return forced
        for _priority, _name, answer in _PROVIDERS:
            result = answer(engine, attacker, current, intent, context)
            if result:
                return result
        return forced
    finally:
        engine._redirection_busy = False
