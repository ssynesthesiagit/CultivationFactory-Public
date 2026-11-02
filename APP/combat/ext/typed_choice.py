"""Typed reaction choices (SYS2 review finding 1): the transport for "choice:typed.*" menus.

typed_reactions asks the table through needle.ask for a menu the printed rules make the player decide, such as
"choice:typed.zero_hp_replacer" (Blood Pump's "If several are available, choose one"). needle.ask publishes the options
and bounds in the trigger context; this plug-in hands them to the table as an ExtensionChoice, the same way
combat/ext/needle.py and combat/ext/scoundrel_riders.py do for their own prefixes. Without it the table fell back to a
bare Use/Pass card with raw internal ids and no options, so the player could not answer the choice.

Default-inert: any other choice id, or a question nobody put (no needle_options in the context), returns None.
"""

from __future__ import annotations

from typing import Any

from . import hook
from .needle import option_spec

CHOICE = "choice:typed."


@hook("choice_options")
def typed_options(engine: Any, intent: Any, checkpoint: str, reactor_id: str, choice_id: str,
                  context: dict[str, Any]) -> dict[str, Any] | None:
    """Every typed reaction choice (id "choice:typed.*"), through the shared Needle transport's own spec."""
    return option_spec(choice_id, context, CHOICE)
