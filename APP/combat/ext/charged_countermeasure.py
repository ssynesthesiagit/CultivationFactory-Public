"""Charged Countermeasure (Lightning talent, Reaction, CL 5+): one branch of its failed save, on the reaction it answers,
and the creatures it answers (AI fight hunt, /var/tmp/auto-audit/hunt1/REPORT.md item 5;
authority/typed_mechanics/rules_text.json TAL_LIGHTNING_CHARGED_COUNTERMEASURE):

    The triggering creature must be Charged, Conductive, or using a visible qi circuit.
    Failed Save: The triggering reaction or counter has Disadvantage if it uses a roll. If it does not use a roll, its
    damage reduction, AC bonus, shield value, or movement prevention is reduced by your Proficiency Bonus.

The record typed both halves of the failed save as two unconditional effects -- a "disadvantage" on "the triggering reaction
or counter" (no block understands that target: a GM rider) and a "damage_modifier" of PB (another GM rider) -- so every
failed save handed the GM both riders, and the Disadvantage never reached a roll. The record now carries one effect,
``countermeasure_penalty``, and this module decides which branch the answered reaction gets:

- The reaction uses a roll (an attack, a contest, a chance d20 -- ``uses_roll``): its own d20 has Disadvantage, and only that
  reaction's own. typed_reactions._open leaves the reaction being answered in ``engine._typed_answered_reaction`` while the
  "a creature uses a reaction" replies run; the effect pins the penalty to that reactor and that reaction
  (the dispatch frame's ``penalty``) and typed_executor's ``attack_mode`` (a reaction attack) and ``reaction_roll_mode``
  (a contest or chance roll) hooks read it through ``typed_reactions.reaction_penalty``. Each accepted reaction has its own
  frame, replaced on its next use; nested dispatch restores the parent being answered. Only the answered
  reaction's own attacks (``reaction_attack``, its own feature id) consult it, so a later unrelated attack never has it.
- It does not: one GM rider says the reaction's damage reduction, AC bonus, shield value or movement prevention is reduced
  by PB. The answered reaction has already worked out those numbers when it is opened (its amounts are computed by
  a dozen separate sites in typed_reactions.py), and the table has no hook that lowers them afterwards, so that branch stays
  by hand -- but it is the only rider, and it names the reaction and the amount.
- With no reaction being answered (the effect run some other way), a single rider gives the printed text for the GM.

The requirement ("Charged, Conductive, or using a visible qi circuit") was not enforced: the reading only says "a creature
within 60 feet uses a reaction", the record's rider promising GM confirmation is silent on a reaction row, and so an AI or
Auto fighter answered every creature that used a Reaction. ``reaction_subject_allowed`` now keeps an AI or Auto reactor to
a creature bearing a Charged or Conductive mark (combat/ext/charge_marks.py places both). "Using a visible qi circuit"
tracks nothing on this table, so it is not automated: a fighter whose player is asked (Ask me) is offered every
reaction and decides that for themself, as the printed line leaves it to the table.

Native opportunity attacks publish the same moment through native_reactions.attack_scope.
Its roll-mode hook consumes this same penalty only during the answered native attack.
Plug-in reactions must publish their own accepted-Reaction moment to be answered.
"""

from __future__ import annotations

from typing import Any, Iterator

from . import effect, hook

EFFECT = "countermeasure_penalty"
# An effect whose typed block rolls a d20 for the reactor: block_attack, block_counter_technique, block_negate_attack.
ROLLING = {"attack", "counter_technique", "contest_against"}
MARKS = ("Charged", "Conductive")


def _nodes(node: Any) -> Iterator[dict[str, Any]]:
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
        elif isinstance(item, list):
            stack.extend(item)


def uses_roll(row: dict[str, Any]) -> bool:
    """Whether the reaction makes a d20 roll of its own (an attack roll, or a contest or chance roll to negate an attack or
    counter a technique) -- what "if it uses a roll" asks. A damage die, a bonus added to someone else's roll, an AC
    bonus, a move and the like are no roll."""
    for node in _nodes(row.get("effects")):
        kind = node.get("type")
        if kind in ROLLING or (kind == "negate_attack" and (node.get("chance_d20") or node.get("contest"))):
            return True
    return False


def _is_countermeasure(row: dict[str, Any]) -> bool:
    return any(node.get("type") == EFFECT for node in _nodes(row.get("effects")))


@effect(EFFECT)
def penalty(ctx: Any, eff: dict[str, Any]) -> None:
    """The failed save's one branch, run against the creature that failed it (block_save's per-subject Context): the
    creature whose reaction is being answered."""
    subject, engine = ctx.target, ctx.engine
    if subject is None:
        return
    answered = getattr(engine, "_typed_answered_reaction", None)
    power = int(ctx.numbers.get("pb") or 0)
    if not answered or answered["actor_id"] != subject.entity_id:
        ctx.rider(f"{ctx.action.display_name}: {subject.display_name}'s reaction has Disadvantage if it uses a roll; if it does not, "
                  f"its damage reduction, AC bonus, shield value or movement prevention is reduced by {power} (GM).")
        return
    row = answered["row"]
    name = row.get("name") or row.get("feature_id")
    if uses_roll(row):
        pending = {"actor_id": subject.entity_id, "feature_id": row["feature_id"]}
        if "penalty" in answered:
            answered["penalty"] = pending
        else:
            engine._typed_reaction_penalty = pending
        ctx.rider(f"{ctx.action.display_name}: {subject.display_name}'s {name} uses a roll, so that roll has Disadvantage.")
    else:
        ctx.rider(f"{ctx.action.display_name}: {subject.display_name}'s {name} uses no roll, so its damage reduction, AC bonus, "
                  f"shield value or movement prevention is reduced by {power} (Proficiency Bonus) -- apply it by hand (GM).")


def _pending(ctx: Any) -> bool:
    """The Disadvantage is for the answered reaction's own roll: the same reactor, the same reaction, a reaction's own attack."""
    from ..typed_reactions import reaction_penalty

    pending = reaction_penalty(ctx.engine, ctx.actor.entity_id, ctx.source)
    return bool(pending) and bool(ctx.typed.get("reaction_attack")) and pending["actor_id"] == ctx.actor.entity_id \
        and pending["feature_id"] == ctx.source


@hook("attack_mode")
def attack_mode(ctx: Any, target: Any) -> str | None:
    return "DISADVANTAGE" if _pending(ctx) else None


@hook("reaction_roll_mode")
def roll_mode(ctx: Any) -> str | None:
    return "DISADVANTAGE" if _pending(ctx) else None


@hook("native_reaction_roll_mode")
def native_roll_mode(engine: Any, context: dict[str, Any]) -> str | None:
    from ..typed_reactions import reaction_penalty

    pending = reaction_penalty(engine, context["actor_id"], context["source_id"])
    if not pending:
        return None
    marked = pending.get('actor_id') if isinstance(pending, dict) else None
    return {'mode': 'DISADVANTAGE', 'effect': 'Charged Countermeasure',
            'owner': engine.state.actors.get(marked) if marked else None,
            'why': 'the Failed Save of the answered Charged Countermeasure gives this reaction Disadvantage'}


def _bears(actor: Any, name: str) -> bool:
    from ..typed_executor import mark_condition_id

    prefix = mark_condition_id(name, "")  # every owner's: the printed word is "Charged", not "Charged by you"
    return any(condition.condition_id.startswith(prefix) for condition in actor.conditions.values())


@hook("reaction_subject_allowed")
def eligible(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    if other is None or not _is_countermeasure(row):
        return None
    from .. import typed_reactions

    if typed_reactions._asking(engine, reactor, row):
        return None  # its player is asked and judges "a visible qi circuit" for themself
    return None if any(_bears(other, name) for name in MARKS) else False
