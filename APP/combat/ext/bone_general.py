"""Bone General (Tianxia Insight): one more Death slot for Corpse Servants, and a
commanded servant may step before it acts.

Two printed effects, both owned by this plug-in:

* "Increase your Death Control Limit by 1, but the extra capacity can be
  used only for Corpse Servants or Lesser Corpse Servants."  The extra
  slot is answered through the general ``control_limit_extra`` seam
  (combat/summons.py ``_within_control_limits``): it is reserved for the
  two printed groups, so a Grave Formation never spends a slot it may
  not use and the printed Proficiency-Bonus limit is unchanged for every
  other group.

* "When you use a Bonus Action to command Death servants, one commanded
  summon may move up to 10 feet before taking its action."  The general
  ``command_resolved`` seam (combat/typed_executor.py
  ``block_command_summons``) hands the command's recipients to this
  plug-in; the owner picks which servant steps and where (an AI-controlled
  summoner walks the nearest servant it perceives toward the nearest foe it
  perceives, and may decline both), and the step is a granted movement that
  provokes Opportunity Attacks normally and does not spend the servant's own
  walking allowance for its turn.

A character without the Insight owns none of its rows, so both hooks return
early and every other summoner's limit and command behave exactly as
before.
"""
from __future__ import annotations

from typing import Any

from . import hook, note
from .passive_rows import row_of
from .granted_moves import destinations, commit

INSIGHT = "insight.bone-general"
BLOCK = "bone_general"
DEATH = "death"
# "one commanded summon may move up to 10 feet"
STEP_FT = 10
# the printed groups the extra Death Control slot fits
CORPSE_GROUPS = ("corpse_servant", "lesser_corpse_servant")


def owned(engine: Any, actor: Any) -> bool:
    return row_of(engine, actor.entity_id, BLOCK, "bone_general") is not None


@hook("compile_block")
def compile_bone(block: str, spec: dict[str, Any], row: dict[str, Any],
                 numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "numbers": dict(numbers)}]


# ------------------------------------------------------------------ restricted control capacity
@hook("control_limit_extra")
def control_extra(pool: str, owned_ids: tuple[str, ...]) -> tuple[int, tuple[str, ...]] | None:
    """Bone General's +1 Death Control slot, reserved for Corpse Servants and
    Lesser Corpse Servants (the printed restriction)."""
    if INSIGHT not in owned_ids or pool != DEATH:
        return None
    return 1, CORPSE_GROUPS


# ------------------------------------------------------------------ the commanded servant's step
@hook("command_resolved")
def commanded_move(engine: Any, actor: Any, group: str, commanded: list[str],
                   intent: Any, economy: Any) -> None:
    """One commanded servant may move up to 10 feet before taking its action."""
    if group != DEATH or economy != "BONUS_ACTION" or not owned(engine, actor) or not commanded:
        return
    creatures = [engine.state.actors[creature_id] for creature_id in commanded
                 if engine.state.actors[creature_id].active]
    if not creatures:
        return
    from . import needle
    from ..senses import perceives

    if needle.ai_controlled(engine, actor):
        # the nearest servant the summoner perceives is the one that steps
        walkers = [creature for creature in creatures if perceives(engine, actor, creature)]
        if not walkers:
            return
        mover = min(walkers, key=lambda creature: engine._distance_actor_to_actor(actor, creature))
    else:
        ids = [creature.entity_id for creature in creatures]
        picked = needle.ask(engine, intent,
                            f"choice:needle.bone_general_move:{actor.entity_id}", actor,
                            "choice:needle.bone_general_move", ids,
                            labels={creature_id: engine.state.actors[creature_id].display_name
                                    for creature_id in ids},
                            preferred=[ids[0]], allow_decline=True,
                            name="Commanded Servant Move", feature_id=INSIGHT,
                            prompt=("Bone General: one commanded servant may move up to "
                                    f"{STEP_FT} feet before taking its action. "
                                    "Choose which servant steps, or decline."))
        if not picked:
            return
        mover = engine.state.actors[picked[0]]
    _step(engine, actor, mover, intent)


def _step(engine: Any, owner: Any, mover: Any, intent: Any) -> None:
    """Walk the servant up to STEP_FT feet to a legal destination; staying put
    is always allowed, so the menu offers routes plus a decline."""
    routes = [route for route in destinations(engine, mover, STEP_FT, lambda cell: True)
              if route[0] != mover.position]
    if not routes:
        return
    from . import needle

    if needle.ai_controlled(engine, owner):
        # walk toward the nearest foe the servant perceives, if any
        foes = [other for other in engine.state.actors.values()
                if other.active and other.team_id != owner.team_id]
        seen = [foe for foe in foes if _perceives(engine, mover, foe)]
        if not seen:
            return
        target = min(seen, key=lambda foe: engine._distance_actor_to_actor(mover, foe))
        route = min(routes, key=lambda candidate: (
            engine._distance_actor_to_actor(mover, target, actor_position=candidate[0]) if target else candidate[2],
            candidate[2]))
    else:
        ids = [f"step:{route[0].x},{route[0].y},{route[0].z}" for route in routes]
        picked = needle.ask(engine, intent,
                            f"choice:needle.bone_general_step:{mover.entity_id}", owner,
                            "choice:needle.bone_general_step", ids,
                            labels={option_id: f"Move to {route[0].x},{route[0].y} ({route[2]} feet)"
                                    for option_id, route in zip(ids, routes)},
                            allow_decline=True, name="Commanded Servant Move", feature_id=INSIGHT,
                            prompt=(f"Move {mover.display_name} up to {STEP_FT} feet before it takes "
                                    "its action, or leave it where it stands."))
        if not picked:
            return
        route = routes[ids.index(picked[0])]
    commit(engine, mover, route[1], f"passive:{INSIGHT}", budget_ft=STEP_FT,
           provokes=True, intent=intent)
    note(engine, INSIGHT, owner,
         f"{owner.display_name} moves {mover.display_name} up to {STEP_FT} feet on the command, "
         "before it takes its action.", (owner, mover))


def _perceives(engine: Any, viewer: Any, seen: Any) -> bool:
    from ..senses import perceives

    return perceives(engine, viewer, seen)
