"""One price, one wording, one payment: the shared cost quote for choice prompts.

A choice that costs something must say so, and the words it says must be the
words the table charges. Two things used to break that. A plug-in that spent a
resource itself after the answer said nothing, so the prompt fell back to
whatever price the *enclosing action* carried -- which is a different payment,
already committed, and charging it twice in the player's head. And the menu that
asks "how do you want to pay for this?" carried no price at all, so it read
"none" while its own options quoted one.

This module is the single place a choice's own price is built. Consumers:

* ``ext.blood_riders`` -- Bloodletting Strike (1 point) and Crimson Feast (2).
  Each builds one ``Payment``, shows it and spends it, so the prompt and the
  spend cannot disagree.
* ``ext.flowing_second_pass`` -- Empty Bank Evasion quotes and spends one
  Martial Focus with the same Payment; successful-save movement costs nothing.
* ``ext.ice_fracture`` -- Winter Stores the Blow quotes and spends the same
  one-point payment; choosing its storage space adds no second payment.
* ``ext.needle.ask`` -- the shared choice transport every ``choice:needle.*``
  menu rides, plus the sibling menus that reuse it. A choice with no payment of
  its own still quotes the action it rides (Spinning Shot's target pick commits
  the Barrage's Martial Focus); a choice that *does* pay quotes both, apart.
* ``combat.alternative_payments`` -- the substitution menu, which quotes the
  amount being covered and leaves each option's own price to its label.

Display only: nothing here spends, decides or validates. The caller still pays,
through :meth:`Payment.pay`, from the same object it quoted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Trigger keys the choice transport already carries to the table.
COST = "cost"
POOL = "paying_pool"


def quote(costs: Any) -> str:
    """A price in the table's own cost wording ("1 Stamina"), or "" when nothing is charged.

    Delegates to the single formatter every other cost on the table uses, so a
    choice prompt cannot invent a phrasing the rest of the sheet does not use.
    """
    from ..decision_text import costs_text

    return costs_text(costs or ())


@dataclass(frozen=True)
class Payment:
    """One price a choice charges its own chooser: which pool, and how much of it."""

    pool: str
    amount: int

    def quote(self) -> str:
        """The price as the table reads it, from the same formatter as every other cost."""
        return quote(((self.pool, self.amount),))

    def context(self) -> dict[str, str]:
        """The display keys ``prompt_context`` already accepts; payment stays the caller's."""
        return {COST: self.quote(), POOL: self.pool}

    def pay(self, engine: Any, actor: Any, source_id: str) -> None:
        """Spend exactly what was quoted -- the caller's promise, kept by this object."""
        engine._spend_resource(actor, self.pool, self.amount, source_id)


def payable(actor: Any, pool: str, amount: int) -> Payment | None:
    """A Payment only when the chooser really holds it, so a quote is never a promise the table breaks.

    ``None`` means "do not offer this", which is how a plug-in keeps a rider off
    the table for a chooser who cannot pay: no option, no quote, no charge.
    """
    return Payment(pool, amount) if int(amount) > 0 and int(actor.resources.get(pool, 0)) >= int(amount) else None


def separating(action_cost: str, own_cost: str) -> str:
    """A choice's own price and the price of the action it rides, kept apart.

    A paid action is charged whether or not the choice is taken, so a player who
    answers "Not now" has still paid it. Naming one number for both makes the
    choice look dearer or cheaper than it is, so when a choice pays something of
    its own the two are stated separately: what answering spends, then what the
    enclosing action already costs.

    Two payments are two payments even when the numbers match: accepting spends
    both and declining still spends one, so an equal pair is described exactly
    like any other. Collapsing them to a single figure would promise a total
    that no outcome actually charges.

    With only one of the two known, that one is the whole answer -- a free action
    stays free, and an unpaid choice shows only its own price.
    """
    if not own_cost:
        return action_cost
    if not action_cost:
        return own_cost
    return f"{own_cost} to answer this choice; the action you are already paying for costs {action_cost} separately"


def covering(costs: Any) -> str:
    """What a payment menu has to cover, phrased so it cannot be read as the price paid.

    The options of that menu each name their own price in their label, and the
    price actually paid is the option chosen -- HP, or a different pool. So the
    header names the amount being covered and points at the options.
    """
    text = quote(costs)
    return f"{text} to cover; each option below states what paying it costs you" if text else ""
