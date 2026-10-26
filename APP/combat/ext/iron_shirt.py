"""Iron Shirt Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Iron Shirt (the five features and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "iron_shirt"}`` (Iron Shirt, CL3); Iron Wall and Invincible Iron are named states
(combat/ext/states.py) "iron_wall" and "invincible_iron"; Bell Strike's fourth result is the ``bell_strike_die`` effect.

Iron Shirt       Stamina Guard rolls d12s instead of d10s (soak_dice); when Stamina Guard brings a packet to 0, +1 AC until the
                 start of your next turn (refreshed, never above +1).
Bell Strike      its Reaction's unarmed strike asks one result on a hit (typed); "roll the first Stamina Guard die twice and use
                 the higher" is a condition the next Stamina Guard roll before your next turn uses (soak_total).
Iron Wall        state "iron_wall" (1 minute): Resistance to every damage type but Force, Psychic and Void (typed), Advantage
                 against Grappled/Restrained/pushed/pulled/Prone (typed), forced movement 10 feet shorter
                 (forced_movement_reduction), each Stamina Guard die lower than Proficiency Bonus counts as Proficiency Bonus
                 (soak_total), Speed -10 (typed), no Dash (candidate_allowed).
Invincible Iron  its free drop-to-zero row keeps you at 1 HP and runs ``invincible_iron``: Iron Wall starts (no cost, no use,
                 refreshed) and until the start of your next turn: Resistance to Force and Psychic (typed), no forced movement
                 or Prone (forced_movement_reduction, condition_attempt), Stamina Guard dice roll their maximum (soak_total).
Every hook returns early for a creature without these rows or states.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.iron_shirt.feature."
GUARD = "tianxia.path.body_refining.feature.stamina_guard"
BELL_DIE = "condition:typed.bell_strike_die"
SHIRT_AC = "iron_shirt_ac"
IRON_WALL, INVINCIBLE = "iron_wall", "invincible_iron"
WALL_TYPES = ("acid", "bludgeoning", "cold", "fire", "lightning", "necrotic", "piercing", "poison", "radiant", "slashing", "thunder")


def _owns(engine: Any, actor: Any) -> bool:
    return any(row.get("block") == "path_rider" and row.get("kind") == "iron_shirt"
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


def _state(engine: Any, actor: Any, name: str) -> bool:
    from .states import active

    return bool(active(engine, actor, name))


def _guard(row: dict[str, Any]) -> bool:
    return str(row.get("feature_id") or "") == GUARD


@hook("soak_dice")
def iron_shirt_d12(engine: Any, target: Any, row: dict[str, Any], spend: int, dice: Any) -> Any:
    if not _guard(row) or int(dice.sides) != 10 or not _owns(engine, target):
        return None
    return dice.model_copy(update={"sides": 12})


@hook("soak_total")
def iron_shirt_total(engine: Any, target: Any, row: dict[str, Any], roll: Any) -> int | None:
    """Invincible Iron's maximum, Iron Wall's floor and Bell Strike's first-die reroll, each as the printed text says."""
    if not _guard(row):
        return None
    dice = [int(d) for d in (roll.dice or [])]
    if not dice:
        return None
    modifier = int(roll.total) - sum(dice)
    sides = int(str(roll.expression).split("d", 1)[1].split("+", 1)[0].split("-", 1)[0]) if "d" in str(roll.expression) else max(dice)
    if _state(engine, target, INVINCIBLE):
        return len(dice) * sides + modifier
    held = next((c for c in target.conditions.values() if c.condition_id == BELL_DIE), None)
    if held is not None:
        target.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=target.entity_id, target_ids=(target.entity_id,),
                             payload={"condition_id": BELL_DIE, "instance_id": held.instance_id, "reason": "CONSUMED"})
        from ..gate2_runtime_models import DiceSpec

        again = engine.roller.roll(DiceSpec(count=1, sides=sides, modifier=0), actor_id=target.entity_id, reason=f"DAMAGE_SOAK:{PREFIX}bell_strike")
        engine._record_roll(again)
        dice[0] = max(dice[0], int(again.total))
    if _state(engine, target, IRON_WALL):
        floor = int(target.proficiency_bonus or 2)
        dice = [max(d, floor) for d in dice]
    total = sum(dice) + modifier
    return total if total != int(roll.total) else None


@hook("event")
def iron_shirt_ac(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"If Stamina Guard reduces the triggering damage to 0, gain +1 AC until the start of your next turn" (refreshed)."""
    payload = kwargs.get("payload") or {}
    if event_type != "REACTION_RESOLVED" or payload.get("checkpoint") != "DAMAGE_APPLICATION" or int(payload.get("pending_after", 1)) != 0:
        return
    if str(engine.events[-1].source_definition_id) != GUARD:
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None or not _owns(engine, actor):
        return
    for mid, held in list(actor.modifiers.items()):
        if held.source_definition_id == PREFIX + "iron_shirt" and held.target_field == "armor_class":
            engine._remove_modifier_instance(actor, mid, PREFIX + "iron_shirt", expected=held)
    engine._add_modifier(actor, PREFIX + "iron_shirt", "armor_class", "ADD", 1, "SELF", expires_on="START_OF_SELF_NEXT_TURN")


@effect("bell_strike_die")
def bell_strike_die(ctx: Any, row: dict[str, Any]) -> None:
    for iid, held in list(ctx.actor.conditions.items()):
        if held.condition_id == BELL_DIE:
            ctx.engine._remove_condition_instance(ctx.actor, iid, PREFIX + "bell_strike", expected=held)
    ctx.engine._apply_condition(ctx.actor, BELL_DIE, PREFIX + "bell_strike", ctx.actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                                data={"label": "Bell Strike: the first Stamina Guard die is rolled twice (higher counts)"})


@hook("forced_movement_reduction")
def iron_wall_footing(ctx: Any, subject: Any) -> int:
    if subject is None:
        return 0
    if _state(ctx.engine, subject, INVINCIBLE):
        return 1000  # "cannot be pushed, pulled ... or moved against your will"
    return 10 if _state(ctx.engine, subject, IRON_WALL) else 0


@hook("condition_attempt")
def invincible_footing(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    if subject is not None and str((effect_row or {}).get("condition") or "").lower() == "prone" and _state(ctx.engine, subject, INVINCIBLE):
        return False
    return None


@hook("candidate_allowed")
def iron_wall_no_dash(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if getattr(action, "source_definition_id", "") == "system:combat.dash" and _state(engine, actor, IRON_WALL):
        return False
    return None


def iron_wall_effects() -> list[dict[str, Any]]:
    """Iron Wall's typed body (its entry and Invincible Iron's free activation share it)."""
    return [{"type": "state", "name": IRON_WALL, "label": "Iron Wall", "duration": "one_minute"},
            {"type": "resistance", "applies_to": "self", "damage_types": list(WALL_TYPES), "duration": "one_minute",
             "evidence": "Resistance to all damage except Force, Psychic, and Void."},
            {"type": "advantage", "applies_to": "self", "on": "being Grappled, Restrained, pushed, pulled, or knocked Prone", "duration": "one_minute"},
            {"type": "speed", "applies_to": "self", "flat": -10, "duration": "one_minute"}]


def _iron_wall_source(engine: Any, actor: Any) -> str:
    return next((a.source_definition_id for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                 and a.source_definition_id.endswith(PREFIX + "iron_wall")), PREFIX + "iron_wall")


def _end_iron_wall(engine: Any, actor: Any, source: str) -> None:
    """A fresh Iron Wall replaces the running one (exactly the parts its own source put on this creature)."""
    wall = _iron_wall_source(engine, actor)
    for iid, held in list(actor.conditions.items()):
        if held.source_definition_id == wall and held.source_actor_id == actor.entity_id:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "REFRESHED"})
    for mid, held in list(actor.modifiers.items()):
        if held.source_definition_id == wall and held.source_actor_id == actor.entity_id:
            del actor.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"modifier_id": mid, "reason": "REFRESHED"})


@effect("invincible_iron")
def invincible_iron(ctx: Any, row: dict[str, Any]) -> None:
    """Iron Wall without its cost or use (refreshed), then the until-your-next-turn benefits."""
    from .. import typed_executor as te
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine, actor = ctx.engine, ctx.actor
    _end_iron_wall(engine, actor, PREFIX + "invincible_iron")
    action = ActionDefinition(source_definition_id=_iron_wall_source(engine, actor), display_name="Iron Wall", owner_id=actor.entity_id,
                              economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF")
    wall = te.Context(engine, actor, action, ctx.intent, {"effects": [], "numbers": dict(ctx.numbers), "duration": {"kind": "minutes", "amount": 1},
                                                          "riders": []}, [actor], actor, {})
    te.run_effects(wall, iron_wall_effects())
    te.run_effects(ctx, [{"type": "state", "name": INVINCIBLE, "label": "Invincible Iron", "expires_on": "START_OF_SELF_NEXT_TURN"},
                         {"type": "resistance", "applies_to": "self", "damage_types": ["force", "psychic"], "expires_on": "START_OF_SELF_NEXT_TURN"}])
    note(engine, PREFIX + "invincible_iron", actor, f"Invincible Iron: {actor.display_name} stands at 1 Hit Point behind an Iron Wall.")
