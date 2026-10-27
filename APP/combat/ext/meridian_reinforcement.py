"""Meridian Reinforcement (Body Refining, CL7; automation lane AUTO1, 2026-10-04).

Printed text (APP/authority/typed_mechanics/rules_text.json,
tianxia.path.body_refining.feature.meridian_reinforcement):

    You gain Advantage on saving throws against the Poisoned condition, disease, ...
    At the end of your turn, if you are Poisoned or affected by a disease with a printed saving throw DC, you may
    spend 1 Stamina to repeat the original saving throw against the original DC.
    - No action is required.  - You may make this additional saving throw once per round.
    - On a success, the Poisoned condition or disease ends ...

This consolidates the prior Poisoned/Exhaustion Advantage with the newly automated repeat and disease benefit.
This module owns them for any feature whose feature_blocks row declares the
``meridian_reinforcement`` block, so a later Path with the same printed shape needs no code:

  * ``compile_block`` turns the block spec into one typed passive (the cost, the resource and the printed condition
    names), the general seam combat/typed_reactions.py:compile_blocks already offers every plug-in's own block.
  * ``save`` grants Advantage on a save whose named effects are one of those conditions (the same reader
    combat/ext/goruden.py's Golden Sheen uses for "corrosion, bodily decay"; nothing changes for anyone else).
  * ``turn_end`` offers the printed end-of-turn repeat: once per round, for 1 Stamina, repeating the ORIGINAL save
    against the ORIGINAL DC recorded on the condition (``combat/ext/repeat_saves.save_of`` -- a save-imposed condition
    remembers its own save, ``combat/typed_executor.py`` block_save). Only the supported ordinary repeat-save
    contract is eligible; provenance alone, source restrictions and multi-success progress remain GM work. This is the same
    shape combat/ext/adaptations.py already runs for Meridians Remember Affliction, at this feature's own price.

Only the printed condition names are ever considered, so the printed exclusions hold structurally: Exhaustion from
reaching 0 Cultivation Points, Hidden Injuries, Foundation damage, Tribulation scars, curses, possession and
permanent corruption are different conditions and are never touched. Unknown source metadata is conservatively
excluded too. The once-per-round stamp is an integer turn
flag, so it survives a table commit and a reload.

Inert for any creature without such a block, for an old saved fight (its bundle carries no passive row), and for a
Poisoned condition with no save behind it -- the printed text asks for a REPEAT of the original throw, so there is
nothing to repeat. No saved-fight lock file is read or written.
"""

from __future__ import annotations

from typing import Any

from . import hook

BLOCK = "meridian_reinforcement"
STAMINA = "resource:core.stamina"
STAMP = "_round_meridian_reinforcement"
SOURCE = "passive:meridian_reinforcement"
DEFAULT_CONDITIONS = ("poisoned",)
DEFAULT_ADVANTAGE = ("poisoned", "disease", "sickened", "exhaustion")


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK]


def _names(rows: list[dict[str, Any]], key: str, default: tuple[str, ...]) -> set[str]:
    names = {str(name).lower() for row in rows for name in (row.get(key) or ())}
    return names or set(default)


@hook("compile_block")
def meridian_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "name": str(spec.get("name") or "Meridian Reinforcement"),
             "choice_owner": True, "cost": max(1, int(spec.get("cost", 1) or 1)),
             "conditions": sorted(_names([spec], "conditions", DEFAULT_CONDITIONS)),
             "against": sorted(_names([spec], "against", DEFAULT_ADVANTAGE))}]


@hook("save")
def meridian_advantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Advantage on named Poisoned/disease saves, preserving the prior Exhaustion benefit."""
    rows = _rows(ctx.engine, subject) if subject is not None else []
    if not rows:
        return None
    return {"bonus": 0, "modes": ["ADVANTAGE"]} if _names(rows, "against", DEFAULT_ADVANTAGE) & {
        str(name).lower() for name in named or ()} else None


@hook("turn_end")
def repeat_the_original_save(engine: Any, actor: Any) -> None:
    rows = _rows(engine, actor)
    if not rows or actor.turn_flags.get(STAMP) == int(engine.state.round_number):
        return
    resource = next((str(row.get("resource_id")) for row in rows if row.get("resource_id")), STAMINA)
    cost = max(1, min(int(row.get("cost") or 1) for row in rows))
    if actor.resources.get(resource, 0) < cost:
        return

    from .repeat_saves import repeatable, ordinary_repeat_ends

    held = [(iid, c) for iid, c in repeatable(actor, tuple(sorted(_names(rows, "conditions", DEFAULT_CONDITIONS))))
            if ordinary_repeat_ends(c)]
    if not held:
        return

    from .needle import ask, checkpoint_id
    from .choice_costs import Payment

    payment = Payment(resource, cost)

    picked = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "meridian_reinforcement", actor.entity_id), actor,
                 f"choice:needle.meridian_reinforcement.{BLOCK}",
                 [iid for iid, _c in held], allow_decline=True, target_id=actor.entity_id,
                 name=rows[0].get("name") or "Meridian Reinforcement",
                 feature_id=str(rows[0].get("feature_id") or ""), payment=payment,
                 labels={iid: f"Spend {cost} Stamina: repeat the save against {c.condition_id.rsplit('.', 1)[-1].title()}"
                         for iid, c in held},
                 prompt=(f"Meridian Reinforcement: {actor.display_name} may spend {cost} Stamina at the end of this turn "
                         f"to repeat the original saving throw against one poison or disease affecting them. "
                         f"A successful repeat ends that effect; declining costs nothing."))
    if not picked:
        return
    iid, condition = next((pair for pair in held if pair[0] == picked[0]), (None, None))
    if condition is None:
        return
    from .repeat_saves import attempt_repeat

    actor.turn_flags[STAMP] = int(engine.state.round_number)
    payment.pay(engine, actor, SOURCE)
    attempt_repeat(engine, actor, iid, condition, SOURCE, extra_mode="ADVANTAGE")


@hook("save_mode")
def meridian_save_mode(engine: Any, target: Any, ability: str, dc: int, source_id: str,
                       roll_context: dict[str, Any]) -> str | None:
    """Use the native save seam too: ordinary repeats bypass typed effect modifiers."""
    rows = _rows(engine, target)
    if rows and _names(rows, "against", DEFAULT_ADVANTAGE) & {
            str(name).lower() for name in roll_context.get("named") or ()}:
        return "ADVANTAGE"
    return None
