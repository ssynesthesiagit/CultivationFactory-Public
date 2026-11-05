"""More creatures than the one aimed at, "up to N creatures of your choice" (rider lane 3, 2026-09-29).

  extra_targets  {"count": "pb" | "twice_pb" | 3, "sight": true, "range_ft": 60, "within_ft_of_first": 10, "effects": [...]}

"Target: Creatures of your choice up to your Proficiency Bonus ... Each target must be able to perceive you and must make a Wisdom saving throw" (Face That
Halts the Army); "Creatures of your choice up to twice your Proficiency Bonus that can perceive you" (Beauty Beyond Form).  The table offers such an ability
against one creature at a time (the one the user aims at); the existing bounded choice transport selects up to ``count`` creatures
within ``range_ft`` (the ability's own range by default) that can perceive the user (``sight``, default on). Allies and the user are eligible
unless ``who`` is "hostile"; ``area_only`` limits the choice to the compiled area; ``prefer``: "all_hostile" makes every eligible hostile
creature (up to ``count``) the default pick instead of the aimed one alone. Each chosen creature receives the nested effects.
The aimed creature is the default, not an instruction to affect additional creatures. A
target that cannot perceive the user is left out (the aimed one too: nothing happens to it).  Nothing else about the effects changes, so each target
makes its own saving throw.  ``within_ft_of_first`` additionally requires each chosen creature to stand within that many feet of the aimed creature
(and never to be it), for a clause that picks the extra creature next to the first one rather than next to the user; the aimed creature keeps its
own effects either way.  Inert without the key.
"""
import copy
from dataclasses import replace
from typing import Any

from . import effect


def _count(value: Any, numbers: dict[str, Any]) -> int:
    pb = int(numbers.get("pb") or 2)
    if value == "twice_pb":
        return 2 * pb
    if value == "pb":
        return pb
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


@effect("extra_targets")
def extra_targets(ctx: Any, row: dict[str, Any]) -> None:
    from .. import stealth
    from ..typed_executor import run_effects

    engine, actor = ctx.engine, ctx.actor
    # The already-aimed creature: the first real actor among the context's targets.  Some callers hand
    # ``ctx.target`` a fixture or non-actor entry, which would silently make every "within N feet of the
    # first target" test fail; falling through to the target list keeps those lanes working.
    first = next((subject for subject in (ctx.target, *(ctx.targets or ()))
                  if getattr(subject, "entity_id", None) in engine.state.actors), None)
    # Explicit zero means the already-resolved area supplies the bounds; absence keeps the action's range.
    reach = int(row.get("range_ft", ctx.action.range_ft) or 0)
    if row.get("action_reach"):
        from ..attack_reach import maximum
        reach = int(maximum(engine, actor, ctx.action) or 0)
    sight = row.get("sight", True)
    # "Choose one additional creature within 10 feet of the target" (Nine-Needle Cascade): the extra
    # creature is picked relative to the already-aimed one, not to the user, so it gets its own,
    # independent distance test.  General: any "another creature near your first target" clause uses it.
    near_first = row.get("within_ft_of_first")
    # A clause that measures the extra creature from the already-aimed one ("within 10 feet of the
    # target") is not bounded by how far the extra creature stands from the user, so such a row turns
    # the user-distance test off with ``range_from_user: false``.  Absent, behaviour is unchanged.
    from_user = row.get("range_from_user", True)

    def eligible(other: Any) -> bool:
        from .resist_ability import resists, ability_id
        if row.get("exclude_self") and other is actor:
            return False
        if row.get("legal_recipient"):
            from ..recipients import allowed
            if not allowed(engine, actor, other, ctx.action):
                return False
        if row.get("requires_perception") and other is not actor:
            from ..senses import perceives

            if not perceives(engine, actor, other) or not engine._line_of_sight_actor_to_actor(actor, other):
                return False
        return other.active and (row.get("who") != "hostile" or other.team_id != actor.team_id) and not resists(actor.entity_id, other, ability_id(ctx), "immune") and (not from_user or not reach or engine._distance_actor_to_actor(actor, other) <= reach) and (
            not near_first or (first is not None and other is not first and engine._distance_actor_to_actor(first, other) <= int(near_first))) and (
            not sight or other is actor or (stealth.sees(engine, other, actor) and engine._line_of_sight_actor_to_actor(actor, other)))

    pool = list(ctx.targets) if row.get("area_only") else list(engine.state.actors.values())
    others = sorted((other for other in pool if eligible(other)),
                    key=lambda other: (engine._distance_actor_to_actor(actor, other), other.entity_id))
    from . import needle

    options = [other.entity_id for other in others]
    count = len(options) if row.get("count") == "any" else _count(row.get("count"), ctx.numbers)
    preferred = [first.entity_id] if first is not None and first.entity_id in options else [other.entity_id for other in others if other.team_id != actor.team_id][:1]
    default_count = None
    automatic = True
    default = "first"
    if row.get("prefer") == "hostile_or_decline":
        # An optional harmful rider may still target allies by player choice,
        # but the automatic controller declines when it has no enemy recipient.
        preferred = [other.entity_id for other in others if other.team_id != actor.team_id][:count]
        automatic = bool(preferred)
        default = "first" if preferred else "decline"
    if row.get("prefer") == "all_hostile":
        # "Make saber attacks against up to your Proficiency Bonus creatures within reach" (Circle-Cleaving Saber, rider lane C5): with
        # no answer the user takes every hostile creature it may, the aimed one first.
        preferred = list(dict.fromkeys([*preferred, *[other.entity_id for other in others if other.team_id != actor.team_id]]))[:count]
        default_count = len(preferred)
    side = row.get("automatic_recipients")
    automatic_ids = None
    if side in {"enemies", "allies", "allies_and_self"}:
        automatic_ids = [other.entity_id for other in others
                         if (other.team_id != actor.team_id if side == "enemies"
                             else other.team_id == actor.team_id and
                             (side == "allies_and_self" or other is not actor))]
    ids = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "BEAUTY_TARGETS", ctx.source), actor,
                     "choice:needle.beauty_targets", options, labels={other.entity_id: other.display_name for other in others},
                     prompt=(str(row["choice_prompt"]).format(action=ctx.action.display_name, actor=actor.display_name,
                              first=first.display_name if first else "the original creature") if row.get("choice_prompt") else
                             f"{ctx.action.display_name}: {actor.display_name} chooses creatures affected by this action"),
                     name=str(row.get("choice_name") or ctx.action.display_name), preferred=preferred, minimum=0, maximum=count, allow_decline=True,
                     default_count=default_count, automatic=automatic, default=default, automatic_options=automatic_ids)
    chosen = [engine.state.actors[entity_id] for entity_id in ids if entity_id in options][:count]
    if chosen:
        run_effects(replace(ctx, targets=chosen, target=chosen[0] if len(chosen) == 1 else None), copy.deepcopy(row.get("effects") or []))
