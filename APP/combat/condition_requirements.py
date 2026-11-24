"""One answer to "does this creature carry the condition an action names?".

An action may declare the state it requires either as a full instance id
("condition:core.grappled") or as the condition's plain printed name ("prone",
"grappled", "restrained"). A plain name is needed because the *same* stance is
carried under different ids depending on which runtime applied it
(condition:typed.prone, condition:core.prone), so an ability that prints a
requirement cannot pin one runtime's id.

The name is the condition's own name segment, the one the pill and the fight log
show ("condition:typed.state.calamity_briar_incarnation" -> "calamity_briar_incarnation"),
never a scope or namespace word: a plain name therefore cannot match every
"state." condition by accident.

Used by:
* ``gate2_engine.Gate2Engine._has_condition`` -- legality, the table's refusal
  sentence and the sheet's greyed row;
* ``ai_tactics._own_prerequisites`` -- the planner's "is this action ready?" fact,
  so the planner cannot disagree with the engine about a declared requirement;
* plug-ins that ask the engine the same question (``combat/ext/charge_marks.py``,
  ``combat/ext/ancestral_channeler.py``).

Read-only: it inspects the actor's own conditions and changes nothing.
"""

from __future__ import annotations

from .condition_names import condition_key


def condition_name(condition_id: object) -> str:
    """The name segment of a condition id: "condition:typed.state.foo" -> "foo"."""
    key = condition_key(condition_id)
    return key.rsplit(".", 1)[-1] if key else ""


def condition_present(actor: object, requirement: object) -> bool:
    """True when ``actor`` carries the condition named by ``requirement``.

    A "condition:" requirement must match the carried id exactly, as it always
    has. Any other requirement is a plain name and matches the name segment of a
    carried id.
    """
    required = str(requirement or "")
    if not required:
        return False
    if required.startswith("condition:"):
        return any(condition.condition_id == required for condition in actor.conditions.values())
    return any(condition_name(condition.condition_id) == required
               for condition in actor.conditions.values())
