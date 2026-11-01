"""Intercepting Shot (Sniper, Counter-Shot) as a Ready action on the lock round's prepared-action hooks (automation lane H2, 2026-09-29).

Owner text (rules_text.json TAL_SNIPER_INTERCEPTING_SHOT):
  "You may Ready a ranged weapon attack to intercept another ranged attack you can perceive. You cannot intercept spell attacks or
  massive ranged weapons such as boulders, ballista bolts, siege stones, or ship-scale projectiles unless your weapon or technique is
  comparable in scale. When the triggering attack is made, make your ranged attack as normal. If your attack roll is higher than the
  triggering attack roll, the triggering attack is negated. You may expend Martial Focus to use Intercepting Shot as a Reaction
  without first taking the Ready action."
Spheres 5e has no Sniper counterpart; D&D 5.5e's Ready action ("a trigger ... you can use your Reaction") is what the lock round's
transport already plays.

How it runs
  * Ready: a "Ready: Intercepting Shot (<ranged weapon>)" button per ranged weapon (prepare_options). It spends the Action and holds
    until the start of the fighter's next turn. When a hostile creature it can see starts a typed ranged weapon attack on a creature
    within that weapon's long range and in its sight, the table asks Use / Decline (the built-in AI: always Use). Use spends the
    Reaction and ends the Ready.
  * Reaction: the compiled reaction row (a ranged weapon attack made within your weapon's range) now costs Martial Focus
    (reviewed_final.d/zz_h2.json) and runs the same ``intercepting_shot`` effect.
  * The contest: the fighter's ranged attack roll (its best ranged weapon's attack bonus, or the readied weapon's) against the
    triggering attack roll, rolled then for the attacker with that attack's bonus (the attack itself is not rolled yet when it is
    intercepted). Strictly higher negates the attacker's next attack on that creature (typed_executor's ``_typed_negated``, which
    only a typed attack reads; the Ready trigger therefore only fires for one).
Judgment calls: "another ranged attack you can perceive" is any typed ranged weapon attack by a hostile creature the fighter can see
whose target is within the readied weapon's long range and in its sight (the shot meets the projectile on its way in); the attack is
"massive" never (no siege weapons are compiled); the built-in AI does not Ready it (it keeps the Martial Focus Reaction), a player may.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

KEY = "TAL_SNIPER_INTERCEPTING_SHOT"
SOURCE = "ready:sniper.intercepting_shot"
BLOCK = "intercepting_shot"


@hook("decision_text")
def decision_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    prepared = (context.get("choice_trigger") or {}).get("prepared") or {}
    actor = engine.state.actors.get(context.get("reactor_id"))
    if prepared.get("source_id") != SOURCE or actor is None or not _owns(engine, actor):
        return None
    return {"feature_id": KEY, "cost": "Reaction now; the Action to prepare was spent earlier",
            "summary": "Make your prepared ranged weapon attack to intercept the incoming ranged weapon attack. A higher attack roll negates the incoming attack.",
            "limits": "Expires at the start of your next turn. Cannot intercept spell attacks or oversized siege projectiles.",
            "table_note": "Pass keeps your preparation until it expires or you use it."}


@hook("compile_block")
def _compile_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "keeps_compiling": bool(spec.get("keeps_compiling"))}]


def _owns(engine: Any, actor: Any) -> bool:
    return any(row.get("block") == BLOCK for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


def _typed(action: Any) -> dict[str, Any]:
    return ((action.parameters or {}).get("typed") or {}) if action is not None else {}


def _ranged_attack(action: Any) -> bool:
    """A typed ranged weapon attack (not a spell attack: those have no weapon record)."""
    typed = _typed(action)
    return (action is not None and action.resolution_kind == "TYPED" and bool(typed.get("weapon")) and bool(typed.get("range_ft"))
            and any(row.get("type") == "attack" for row in typed.get("effects") or []))


def weapons(engine: Any, actor: Any) -> list[Any]:
    """The fighter's ranged weapon attacks, the strongest first."""
    rows = [action for action in engine.action_catalog.values()
            if action.owner_id == actor.entity_id and _ranged_attack(action) and action.target_kind == "HOSTILE_ENTITY"
            and "#" not in action.source_definition_id and not _typed(action).get("opportunity_of")]
    return sorted(rows, key=lambda action: (-int((action.parameters or {}).get("expected_damage") or 0), action.source_definition_id))


def _bonus(action: Any) -> int:
    return int((_typed(action).get("numbers") or {}).get("attack_bonus") or 0)


def _reach_of(weapon: Any) -> int:
    typed = _typed(weapon)
    return int(typed.get("long_range_ft") or typed.get("range_ft") or weapon.range_ft or 0)


# ------------------------------------------------------------------------------------------------ the Ready
@hook("prepare_options")
def _options(engine: Any, actor: Any) -> list[dict[str, Any]] | None:
    if not _owns(engine, actor):
        return None
    return [{"option_id": f"intercepting_shot:{weapon.source_definition_id}", "source_id": SOURCE,
             "label": f"Intercepting Shot ({weapon.display_name.removesuffix(' attack')}), when a ranged attack you can see is made",
             "trigger": "INTENT_ACCEPTED", "automatic_use": True, "data": {"kind": BLOCK, "weapon": weapon.source_definition_id}}
            for weapon in weapons(engine, actor)[:8]]


def _protected(engine: Any, actor: Any, weapon: Any, event: Any) -> Any | None:
    """The creature whose incoming ranged attack this Ready would shoot down, or None when the event is not its trigger."""
    from .. import stealth

    if event.event_type != "INTENT_ACCEPTED" or str((event.payload or {}).get("kind")) not in ("ACTION", "BONUS_ACTION"):
        return None
    attacker = engine.state.actors.get(event.actor_id or "")
    if (attacker is None or not attacker.active or attacker.team_id == actor.team_id or weapon is None
            or not _ranged_attack(engine.action_catalog.get(event.source_definition_id))
            or not engine._line_of_sight_actor_to_actor(actor, attacker) or not stealth.sees(engine, actor, attacker)):
        return None
    targets = [row for row in (engine.state.actors.get(target) for target in event.target_ids or ()) if row is not None and row.active]
    targets.sort(key=lambda row: (row.entity_id != actor.entity_id, row.team_id != actor.team_id, row.entity_id))
    return next((row for row in targets if row.entity_id == actor.entity_id
                 or (engine._distance_actor_to_actor(actor, row) <= _reach_of(weapon) and engine._line_of_sight_actor_to_actor(actor, row))), None)


@hook("prepared_trigger")
def _trigger(engine: Any, actor: Any, option: dict[str, Any], event: Any) -> bool | None:
    if option.get("source_id") != SOURCE:
        return None
    return _protected(engine, actor, engine.action_catalog.get((option.get("data") or {}).get("weapon")), event) is not None


@hook("prepared_action")
def _resolve(engine: Any, actor: Any, option: dict[str, Any], event: Any, intent: Any) -> bool | None:
    if option.get("source_id") != SOURCE:
        return None
    from .. import typed_reactions

    weapon = engine.action_catalog[option["data"]["weapon"]]
    protected = _protected(engine, actor, weapon, event)
    attacker = engine.state.actors[event.actor_id]
    action = engine.action_catalog[event.source_definition_id]
    row = {"feature_id": KEY, "name": "Intercepting Shot", "effects": [], "numbers": {"attack_bonus": _bonus(weapon)}}
    previous = getattr(engine, "_typed_pending_attack", None)
    engine._typed_pending_attack = {"attacker": attacker.entity_id, "target": protected.entity_id, "bonus": _bonus(action),
                                    "reach": int(action.range_ft or action.reach_ft or 5)}
    try:
        intercept(typed_reactions._generic_context(engine, actor, attacker, row, intent), {"weapon": weapon.source_definition_id})
    finally:
        engine._typed_pending_attack = previous
    return True


@hook("ai_candidate_allowed")
def _ai(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The built-in AI does not spend its Action on this Ready (its Martial Focus Reaction covers the same shot)."""
    metadata = (candidate.metadata or {}).get("prepared") or {}
    return False if metadata.get("source_id") == SOURCE else None


# ------------------------------------------------------------------------------------------------ the shot
@effect("intercepting_shot")
def intercept(ctx: Any, spec: dict[str, Any]) -> None:
    """Your ranged attack roll against the triggering attack roll; strictly higher negates it."""
    from ..typed_executor import _reaction_roll_mode
    from .roll_context import described_d20

    engine = ctx.engine
    pending = getattr(engine, "_typed_pending_attack", None)
    if not pending:
        ctx.rider("Intercepting Shot: negate the triggering ranged attack if your attack roll is higher (GM).")
        return
    attacker, protected = engine.state.actors.get(pending["attacker"]), engine.state.actors.get(pending["target"])
    weapon = engine.action_catalog.get(spec.get("weapon") or "") or next(iter(weapons(engine, ctx.actor)), None)
    if attacker is None or protected is None:
        return
    if weapon is None:
        ctx.rider("Intercepting Shot needs a ranged weapon in hand.")
        return
    attack_name = pending.get("action_name") or "attack"
    theirs = described_d20(engine, description=f"attack roll for {attack_name} against {protected.display_name}, opposed by {ctx.action.display_name}",
                           modifier=int(pending.get("bonus") or 0), actor_id=attacker.entity_id, reason="REACTION_CONTEST")
    engine._record_roll(theirs)
    mine = described_d20(engine, description=f"attack roll for {ctx.action.display_name} ({weapon.display_name.removesuffix(' attack')}) to intercept {attacker.display_name}'s {attack_name} against {protected.display_name}",
                         modifier=_bonus(weapon), actor_id=ctx.actor.entity_id, reason="REACTION_CONTEST", mode=_reaction_roll_mode(ctx))
    engine._record_roll(mine)
    success = mine.total > theirs.total
    if success:
        engine._typed_negated = {*getattr(engine, "_typed_negated", set()), (attacker.entity_id, protected.entity_id)}
    ctx.rider(f"Intercepting Shot ({weapon.display_name.removesuffix(' attack')}, {mine.total} against {theirs.total}): "
              f"the attack on {protected.display_name} is {'negated' if success else 'not negated'}.")
