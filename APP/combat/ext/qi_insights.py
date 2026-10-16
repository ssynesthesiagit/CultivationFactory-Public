"""Qi Cultivation Insights that weave weapons and techniques together (OPUS1 batch 4).

Weapon and Technique Weave   once during each of the owner's turns it may gain one Weave benefit (Ask me; automatic for
                             AI fighters), and only one benefit is held at a time (a new one replaces the old):
  * after a weapon attack hits: +1 to its next Cultivation Attack before the end of its next turn;
  * after a creature fails a saving throw against its Qi-powered technique: +1 to its next weapon attack before the
    end of its next turn;
  * after it activates a Qi-powered technique through a weapon: it moves up to 5 feet, and the creatures that
    technique struck or affected do not get Opportunity Attacks for that move (others still do).

"Qi-powered" is insights7.qi_powered: a Qi sphere or an explicit Qi cost. A held bonus is a condition on the owner
(``weave`` = "cultivation" | "weapon") ending at the end of its next turn (END_OF_SOURCE_TURN_AT); the attack that
uses it removes it once its roll is made (attack_roll_finished); previews read it without spending it. Turn flags hold strings.
Every hook returns at once for a creature without the sealed ``qi_insights`` row.
"""
from __future__ import annotations

from typing import Any

from . import hook, note
from .passive_rows import row_of

BLOCK = "qi_insights"
WEAVE = "insight.weapon-and-technique-weave"
HELD = "condition:typed.weapon_technique_weave"
TURN_FLAG = "qi_insights:weave"
OUTCOMES = {
    WEAVE: "Once each of your turns you may gain one Weave benefit: after a weapon hit, +1 to your next Cultivation Attack; "
           "after a creature fails a save against your Qi technique, +1 to your next weapon attack (each before the end of "
           "your next turn); or after a Qi technique delivered through a weapon, move 5 feet without provoking from the "
           "creatures it struck. Only one Weave benefit is held at a time",
}
LABELS = {"cultivation": "Weave: +1 to your next Cultivation Attack", "weapon": "Weave: +1 to your next weapon attack"}


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    feature = row["feature_id"]
    return [{**row, "kind": feature, "player_outcome": OUTCOMES[feature], "pb": int(numbers["pb"]), "cl": int(numbers["cl"])}]


def _owner_on_turn(engine: Any, actor: Any) -> bool:
    return (actor is not None and actor.active and engine.state.current_actor_id == actor.entity_id
            and row_of(engine, actor.entity_id, BLOCK, WEAVE) is not None
            and actor.turn_flags.get(TURN_FLAG) != str(engine.state.round_number))


def qi_technique(action: Any) -> bool:
    from .insights7 import qi_powered

    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    pools = tuple(pool for pool, _amount in getattr(action, "costs", ()) or ())
    return qi_powered(typed.get("sphere"), pools)


def _offer(ctx: Any, option: str, label: str, prompt: str) -> bool:
    from .needle import ask, checkpoint_id

    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, WEAVE, option), ctx.actor, "choice:needle.qi_insights",
                 [option], allow_decline=True, name="Weapon and Technique Weave", feature_id=WEAVE,
                 target_id=ctx.actor.entity_id, labels={option: label},
                 prompt=f"Weapon and Technique Weave: {prompt} Once per turn, no cost; it replaces any Weave benefit you hold.")
    if not picked:
        return False
    ctx.actor.turn_flags[TURN_FLAG] = str(ctx.engine.state.round_number)
    return True


def _hold(ctx: Any, kind: str) -> None:
    engine, owner = ctx.engine, ctx.actor
    for iid, condition in list(owner.conditions.items()):
        if condition.condition_id == HELD:
            _drop(engine, owner, iid, "REPLACED")
    engine._apply_condition(owner, HELD, WEAVE, owner.entity_id,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(owner.turns_started) + 1}",
                            data={"weave": kind, "label": LABELS[kind] + " (until the end of your next turn)"})
    note(engine, f"passive:{WEAVE}", owner, f"Weapon and Technique Weave: {owner.display_name} holds {LABELS[kind].lower()[7:]}.")


def _drop(engine: Any, owner: Any, iid: str, reason: str) -> None:
    condition = owner.conditions.pop(iid, None)
    if condition is not None:
        engine._append_event("CONDITION_REMOVED", WEAVE, actor_id=owner.entity_id, target_ids=(owner.entity_id,),
                             payload={"instance_id": iid, "condition_id": HELD, "reason": reason})


@hook("after_hit")
def weave_after_weapon_hit(ctx: Any, target: Any, kind: str) -> None:
    if kind != "weapon" or not _owner_on_turn(ctx.engine, ctx.actor):
        return
    if _offer(ctx, "cultivation", "Gain +1 to your next Cultivation Attack before the end of your next turn",
              f"your {ctx.action.display_name} hit {target.display_name}. Gain +1 to your next Cultivation Attack?"):
        _hold(ctx, "cultivation")


@hook("after_save_resolved")
def weave_after_failed_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    if not failed or subject is ctx.actor or not _owner_on_turn(ctx.engine, ctx.actor) or not qi_technique(ctx.action):
        return
    if _offer(ctx, "weapon", "Gain +1 to your next weapon attack before the end of your next turn",
              f"{subject.display_name} failed its saving throw against your {ctx.action.display_name}. "
              f"Gain +1 to your next weapon attack?"):
        _hold(ctx, "weapon")


@hook("attack_result")
def weave_struck(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    """Remember resolved hits, including hits that deal no damage; never provisional rolls."""
    if hit and row_of(ctx.engine, ctx.actor.entity_id, BLOCK, WEAVE) is not None:
        ctx.damage_cache.setdefault("_weave_hits", set()).add(target.entity_id)


def _struck(ctx: Any) -> tuple[str, ...]:
    start = int(getattr(ctx, "technique_event_start", 0) or 0)
    hit = set(ctx.damage_cache.get("_weave_hits") or ())
    hit.update(tid for event in ctx.engine.events[start:] if event.actor_id == ctx.actor.entity_id
           and event.source_definition_id == ctx.source
           and (event.event_type == "CONDITION_APPLIED" or
                event.event_type == "DAMAGE_COMMITTED" and int(event.payload.get("reduced_to") or 0) > 0)
           for tid in (event.target_ids or ()) if tid != ctx.actor.entity_id
    )
    return tuple(sorted(hit))


@hook("technique_used")
def weave_after_weapon_technique(ctx: Any) -> None:
    if not (ctx.typed.get("weapon") or ctx.typed.get("weapon_delivery")) or not qi_technique(ctx.action) \
            or not _owner_on_turn(ctx.engine, ctx.actor):
        return
    engine, owner = ctx.engine, ctx.actor
    struck = _struck(ctx)
    from .granted_moves import commit, destinations

    routes = [row for row in destinations(engine, owner, 5, lambda cell: cell != owner.position) if row[2] <= 5]
    if not routes:
        return
    from .needle import ask, checkpoint_id

    by_key = {f"cell:{cell.x},{cell.y},{cell.z}": (cell, path) for cell, path, _cost in routes}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, WEAVE, "step"), owner, "choice:needle.qi_insights",
                 sorted(by_key), allow_decline=True, name="Weapon and Technique Weave", feature_id=WEAVE,
                 target_id=owner.entity_id,
                 labels={key: f"Move to {cell.x},{cell.y} at {cell.z * 5} feet altitude"
                         for key, (cell, _path) in by_key.items()},
                 prompt=(f"Weapon and Technique Weave: you delivered {ctx.action.display_name} through your weapon. Move up "
                         f"to 5 feet; the creatures it struck or affected do not get Opportunity Attacks for this move (others may). "
                         f"Once per turn, no cost; it replaces any Weave benefit you hold."))
    if not picked:
        return
    owner.turn_flags[TURN_FLAG] = str(engine.state.round_number)
    for iid, condition in list(owner.conditions.items()):
        if condition.condition_id == HELD:
            _drop(engine, owner, iid, "REPLACED")
    _cell, path = by_key[picked[0]]
    commit(engine, owner, path, f"passive:{WEAVE}", provokes=True, ignore_oa_from=struck, intent=ctx.intent)


def _held(actor: Any, kind: str) -> str | None:
    return next((iid for iid, c in actor.conditions.items() if c.condition_id == HELD and c.data.get("weave") == kind), None)


def _kind_now(ctx: Any) -> str | None:
    from .attack_scope import current

    frame = current(ctx.engine) or {}
    attack = frame.get("effect") or getattr(ctx, "attack_effect", None) or {}
    if str(attack.get("attack_kind") or "").startswith("cultivation"):
        return "cultivation"
    return "weapon" if ctx.typed.get("weapon") else None


@hook("attack_bonus")
def weave_bonus(ctx: Any, actor: Any) -> int | None:
    kind = _kind_now(ctx) if actor is ctx.actor else None
    return 1 if kind and _held(actor, kind) else None


@hook("attack_roll_finished")
def weave_spent(ctx: Any, target: Any, effect: Any, roll_id: str) -> None:
    """The attack that took the +1 (same kind test as weave_bonus) uses the benefit up once its roll is made."""
    if not roll_id:
        return
    kind = "cultivation" if str((effect or {}).get("attack_kind") or "").startswith("cultivation") else \
        "weapon" if ctx.typed.get("weapon") else None
    iid = _held(ctx.actor, kind) if kind else None
    if iid is not None:
        _drop(ctx.engine, ctx.actor, iid, "CONSUMED")
