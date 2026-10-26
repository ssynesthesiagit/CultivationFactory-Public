"""A printed step that does not provoke an opportunity attack from named creatures, and only from them.

Several printed abilities hand out a few feet of movement "without provoking opportunity attacks" and then say whose:
"move 10 feet without provoking opportunity attacks from the target" (One Line Cannot Be Crossed), "You may move 5
feet after resolving all attacks without provoking opportunity attacks from one creature hit by this talent" (Flowers in
the Storm).  The engine's own ``movement`` effect row reads ``no_opportunity_attacks`` as protection from *every*
enemy for the rest of the turn: ``typed_executor`` spends it as one ``oa_free_ft`` pool, and the leave-reach window
returns before it looks at any reactor, so a bystander that never provoked anything loses a legal opportunity attack, and
an ability that hit nothing still hands the protection out.

The general seam already exists for the scoped case.  ``combat/granted_movement.py`` is the shared public adapter
(Merciful Hand, Reeling Step, guardian Patrol and Compass Breaking Hand use it) and its ``resolve_path`` takes
``ignore_oa_from``, which exempts named creatures while every other enemy stays eligible; ``combat/gate2_engine.py``
reads the same tuple when it asks who may react.  This module is the typed effect that drives that adapter for a printed
"move N feet without provoking ... from ..." rider, so the printed creature is the only one spared.

Spear uses, from the printed text alone (authority/typed_mechanics/rules_text.json):

  One Line Cannot Be Crossed  "move 10 feet without provoking opportunity attacks from the target"
  Flowers in the Storm        "You may move 5 feet after resolving all attacks without provoking opportunity attacks
                              from one creature hit by this talent"

Typed row::

  {"type": "move_without_provoking", "applies_to": "self", "distance_ft": 10,
   "exempt_from": "target" | "creatures_hit", "optional": true,
   "evidence": "<the printed sentence>"}

``exempt_from: "target"`` spares the ability's own target; ``"creatures_hit"`` spares one of the creatures this very
activation hit, which the user chooses (and, when every attack missed, nobody: the step is walked normally and says
so).  ``optional: true`` is for a printed "you may"; the user may decline and the AI takes the printed step.

"A creature hit" is the settled hit, not a creature that lost normal Hit Points: ``hits_this_activation`` reads the
documented ``attack_result`` hook (``combat/ext/__init__.py``: "Covers hits, misses and zero-damage hits"), so a hit
whose whole packet was absorbed by Temporary HP, or reduced away, still counts, and a miss never does.  The record is
one list in the activation's own ``damage_cache``, so nothing is saved and another ability's hits cannot leak in.

Two things that hook must not get wrong.  It hands the *originally declared* target, while native resolution may send
the attack somewhere else -- Guardian Interpose moves a blow onto the creature behind the guardian -- and records the
creature actually struck in the confirmed hit's own provenance (``Context.attack_damage_context.target_id``, the
``AttackDamage`` the engine built from the resolved target at ``combat/gate2_engine.py``), which the executor itself
reads for attack completion.  A redirect that was recorded as the declared target would offer an unhit creature for the
movement exemption and leave the creature actually struck out of it, so the recipient is read from that provenance and
the declared target is only a fallback for a hit that carries none.  And the hook is inert for an ability with no
``move_without_provoking`` row anywhere in its typed effects: it returns before it reads anything, so no other
character's attack writes into this module's bookkeeping.

"Wherever the row sits" includes inside a printed option, because the engine executes an option's own ``effects``
(``rider_menu``, ``choose_effects``).  One Line Cannot Be Crossed prints its step as one of five options its
reaction menu offers, so ``has_step`` reads the option rows too (``_typed_rows``), and the guard that keeps this
module inert stays a question about the row, never about the ability id.

The printed feet are the ability's own allowance: the step walks through
``granted_movement.resolve_path(..., use_movement=False)``, which charges the row's ``distance_ft`` and leaves the
creature's own remaining movement alone (terrain, difficult ground, occupancy, volume, footprint and the printed
restrictions on a voluntary path all still apply, and the exempted creature's reach still opens its reaction window for
everybody else).  Only the opportunity attack itself is skipped.  No saved state is added.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

#: The two printed ways a rider says whose opportunity attack is skipped.
EXEMPT_FROM = ("target", "creatures_hit")

#: One activation's settled hits, in the order they were made (Context.damage_cache; never saved).
HIT_KEY = "_quiet_step_hits"


@hook("attack_result")
def remember_a_hit(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    """Note every creature this activation actually hit, whatever that hit did to its Hit Points.

    The printed words are "one creature hit by this talent", so a Temporary-HP-only hit and a hit reduced to
    zero damage both count and a miss does not.

    Inert for an ability that prints no such step: ``has_step`` reads the activation's own typed rows (including
    the nested option and branch rows) and the hook returns before touching anything else, so a character with no
    ``move_without_provoking`` row never writes into this list.

    The name recorded is the creature the attack actually settled on.  This hook receives the declared target,
    which native resolution may have replaced (Guardian Interpose), so a confirmed hit's own provenance names
    the recipient; the declared target is a fallback for a hit that carries none.
    """
    if not hit or not has_step(ctx):
        return
    provenance = getattr(ctx, "attack_damage_context", None)
    recipient = str(getattr(provenance, "target_id", "") or "")
    if not recipient:
        if target is None:
            return
        recipient = target.entity_id
    ctx.damage_cache.setdefault(HIT_KEY, []).append(recipient)


def _typed_rows(effects: Any) -> Any:
    """Every effect row this activation can run, a printed option's own rows included.

    ``typed_executor._walk_rows`` descends into the branch containers (``on_hit``, ``on_miss``,
    ``on_success``, ``on_fail`` and ``effects``) but not into ``options``, and an option is a container the
    engine really executes: ``rider_menu`` and ``choose_effects`` run ``option["effects"]`` through the
    executor (``combat/ext/rider_outcomes.py``, ``combat/ext/effect_choices.py``).  One Line Cannot Be
    Crossed prints its only step inside one of its options, so a walk that stopped at the option would
    report that talent as printing no step at all, leave its hit unrecorded and hand out no exemption
    after a confirmed attack.  Options may nest, so this recurses; ``_walk_rows`` stays the shared reader
    of the branch containers and is not reimplemented here.
    """
    from ..typed_executor import _walk_rows

    for row in _walk_rows(effects):
        yield row
        for option in row.get("options") or []:
            if isinstance(option, dict):
                yield from _typed_rows(option.get("effects"))


def has_step(ctx: Any) -> bool:
    """Whether this very activation carries a ``move_without_provoking`` row at all.

    Public so the hit recorder can stay inert for every other character: the check is on the activation's own
    typed effects, nested option and branch rows included, never on an ability id.
    """
    return any(row.get("type") == "move_without_provoking"
               for row in _typed_rows((ctx.typed or {}).get("effects") or []))


def hits_this_activation(ctx: Any) -> list[str]:
    """The creatures this very activation hit, in order, each once.

    Public so a shared helper (or a test) can ask the question without reading an engine event: a committed hit
    with no normal-HP loss is still a hit, and a roll that turned out to be a miss is not.
    """
    return list(dict.fromkeys(ctx.damage_cache.get(HIT_KEY) or ()))


def _choose_exempt(ctx: Any, engine: Any, intent: Any) -> list[str]:
    """Whose opportunity attack the printed step skips: the ability's target, or one creature it hit."""
    from . import needle

    candidates = [row for row in hits_this_activation(ctx)
                  if row in engine.state.actors and engine.state.actors[row].active]
    if len(candidates) <= 1:
        return candidates
    picked = needle.ask(engine, intent, needle.checkpoint_id(engine, "quiet_step_creature", ctx.source), ctx.actor,
                        needle.CHOICE + "quiet_step_creature", candidates,
                        labels={key: engine.state.actors[key].display_name for key in candidates},
                        maximum=1, default_count=1, allow_decline=False,
                        prompt=f"{ctx.action.display_name}: this step avoids the opportunity attack of one creature you "
                               f"hit. Choose which one.")
    return list(picked)


def _resolved_notice(ctx: Any, spec: dict[str, Any], reading: str) -> None:
    if spec.get("resolved_notices_as_log"):
        ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=ctx.actor.entity_id,
                                 payload={"log": reading})
    else:
        ctx.rider(reading)


@effect("move_without_provoking")
def move_without_provoking(ctx: Any, spec: dict[str, Any]) -> None:
    """Walk the printed few feet now, skipping the opportunity attack of the printed creature only."""
    from .. import granted_movement
    from . import needle

    engine, actor = ctx.engine, ctx.actor
    feet = int(spec.get("distance_ft") or 0)
    intent = ctx.intent or getattr(engine, "_active_intent", None)
    scope = str(spec.get("exempt_from") or "target")
    if feet <= 0 or intent is None or scope not in EXEMPT_FROM:
        ctx.rider(f"{ctx.action.display_name}: this step does not say whose opportunity attack it skips, so the GM "
                  f"resolves whether any creature reacts to it.")
        return
    moves = granted_movement.candidates(engine, actor, feet, intent, ctx.source)
    if not moves:
        _resolved_notice(ctx, spec, f"{ctx.action.display_name}: {actor.display_name} has no legal {feet}-foot step, so it does not move.")
        return
    if scope == "target":
        exempt = [row.entity_id for row in (ctx.targets or ([ctx.target] if ctx.target else []))]
    else:
        exempt = _choose_exempt(ctx, engine, intent)
    spared = ", ".join(engine.state.actors[key].display_name for key in exempt)
    hit = hits_this_activation(ctx)
    if not exempt:
        _resolved_notice(ctx, spec, f"{ctx.action.display_name}: this step hit no creature, so it skips nobody's opportunity attack.")
    elif scope == "creatures_hit" and len(hit) > 1:
        _resolved_notice(ctx, spec, f"{ctx.action.display_name}: only {spared} will not make an opportunity attack against this step; "
                  f"every other creature still may.")
    ordered = sorted(moves, key=lambda key: (moves[key].movement_cost_ft, moves[key].destination.y, moves[key].destination.x))
    labels = {key: f"Step to {moves[key].destination.x},{moves[key].destination.y} (up to {feet} ft"
                    + (f"; {spared} cannot attack it" if spared else "") + ")" for key in ordered}
    picked = needle.ask(engine, intent, needle.checkpoint_id(engine, "quiet_step", ctx.source), actor,
                        needle.CHOICE + "move_without_provoking", ordered, labels=labels, maximum=1, default_count=1,
                        allow_decline=bool(spec.get("optional")), default="first",
                        prompt=f"{ctx.action.display_name}: {actor.display_name} may step up to {feet} feet"
                               + (f" without provoking an opportunity attack from {spared}" if spared else "") + ".",
                        target_id=exempt[0] if len(exempt) == 1 else None,
                        name=ctx.action.display_name, feature_id=ctx.source)
    if not picked:
        return
    granted_movement.resolve_path(engine, actor, moves[picked[0]].canonical_path, ctx.source, feet=feet,
                                  intent=intent, provokes=True, ignore_oa_from=tuple(exempt))