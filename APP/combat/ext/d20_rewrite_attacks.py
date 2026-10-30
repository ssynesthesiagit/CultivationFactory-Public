"""Attack rerolls (automation lane H1, 2026-09-29): Executioner and Star-Drawn Projectile's "Reroll Miss", on combat/ext/d20_rewrite.py.

Owner text (authority/typed_mechanics/rules_text.json):
  * Executioner (Berserker, CL 5): "While Adrenaline is active, expend Martial Focus to reroll one missed weapon attack. Use the new result."
  * Star-Drawn Projectile (Stars, Bonus Action, 2 CP): "The next ranged weapon attack, thrown weapon attack, Starbolt, Comet Spear, or
    similar line attack you make this turn is drawn along a constellation path. Choose one benefit: ignore Half Cover; increase range by
    60 feet; if the target bears your Stellar Mark and the attack hits, push it 10 feet; if the attack misses a marked target, you may
    reroll the attack once, but must use the new result."
    The authority had typed the reroll option as an Advantage on the next attack; it is now the effect "star_drawn_reroll", which puts
    ``condition:typed.star_drawn_reroll`` on the caster until the end of its turn. The first ranged attack roll it makes uses the
    condition up: a miss against a creature bearing its Stellar Mark is rerolled, any other outcome just ends it.

Judgment calls: a "weapon attack" is an attack made with a weapon action (a typed action that carries a weapon); a "ranged" attack is
one with a range in its spec; an AI uses Executioner whenever it has the Focus (it is a plain reroll of a miss).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .d20_rewrite import Holder, Rule, RollCtx, condition_holders, register

ADRENALINE = "condition:typed.body_adrenaline_executioner"   # combat/ext/body_berserker.py: "Adrenaline: Executioner" is the active talent
STAR = "condition:typed.star_drawn_reroll"
EXECUTIONER = "TAL_BERSERKER_EXECUTIONER"


def _is_weapon_attack(engine: Any, rc: RollCtx) -> bool:
    action = (getattr(engine, "action_catalog", None) or {}).get(rc.source_id or "")
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    return typed.get("weapon") is not None


def _executioner_guard(engine: Any, holder: Holder, rc: RollCtx) -> bool:
    return any(c.condition_id == ADRENALINE for c in holder.actor.conditions.values()) and _is_weapon_attack(engine, rc)


register(Rule("executioner", "Executioner", feature=EXECUTIONER, rolls=("attack",), costs=((("focus", 1),),), guard=_executioner_guard))


@effect("star_drawn_reroll")
def star_drawn(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    for iid, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == STAR:
            ctx.engine._remove_condition(ctx.actor, STAR, ctx.source)
    ctx.engine._apply_condition(
        ctx.actor, STAR, ctx.source, ctx.actor.entity_id, expires_on=typed_executor.effect_expiry(ctx, eff, ctx.actor, condition=True) or "END_OF_CURRENT_TURN",
        data={"label": "Star-Drawn Projectile: reroll a miss",
              "reading": "The next ranged attack this turn is drawn along a constellation path: if it misses a creature bearing your Stellar Mark, reroll it once."})


def _marked(engine: Any, holder: Holder, rc: RollCtx) -> bool:
    from ..typed_executor import bears_mark

    return rc.target is not None and bears_mark(rc.target, holder.actor.entity_id, "Stellar Mark") and rc.spec is not None and rc.spec.get("range_ft") is not None


def _spent(engine: Any, holder: Holder, rc: RollCtx, result: Any) -> None:
    engine._remove_condition(holder.actor, STAR, holder.feature_id)


register(Rule("star_drawn_reroll", "Star-Drawn Projectile (Reroll Miss)", rolls=("attack",), finder=condition_holders(STAR), guard=_marked, after=_spent))


@hook("event")
def first_ranged_attack_uses_it_up(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The next ranged attack is the one the constellation path draws: once it has been rolled the condition is gone, hit or miss."""
    if event_type != "ATTACK_ROLLED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    context = engine.d20_context()
    if actor is None or context is None or context["kind"] != "attack" or (context["spec"] or {}).get("range_ft") is None:
        return
    if any(c.condition_id == STAR for c in actor.conditions.values()):
        engine._remove_condition(actor, STAR, str(kwargs.get("payload", {}).get("source") or STAR))
