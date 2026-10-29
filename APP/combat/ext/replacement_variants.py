"""Button help for optional replacement variants ("Deliver the Dose + Bitter Trace").

A ``replace_*`` modifier is printed as the base ability with part of it swapped out, so the
variant keeps the base's own rules text -- which still promises the save, damage or healing that
the replacement has taken away. factory_compiler compares the two effect trees once and records
the trade in ``typed["replacement"]``; this plug-in turns that record into what a player needs
before pressing the button: what the choice replaces, what it keeps, what it gives up, and what
it costs.

A native replacement may instead identify its modifier; its reviewed replace_*
mode supplies the same boundary. Ordinary additive modifiers return None.
This module only reads compiled data and never resolves an effect, so the same answer comes back
in the table, in a connected sheet and in a replay.

The trade is described by what the removed effect actually was. Only an effect a failed save
used to grant is explained as a lost failed-save benefit; a ``replace_healing`` variant removes
ordinary healing, which no save ever gated, so it is described as the effect given up plus what
this choice does instead.
"""

from __future__ import annotations

import json
from typing import Any

from . import hook


def _walk(effects: list[Any]):
    for effect in effects or []:
        if isinstance(effect, dict):
            yield effect
            for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _walk(effect.get(branch) or [])


def _rider_words(effect: dict[str, Any]) -> str:
    """Name what one rider gives a creature, in words a player who knows only basic D&D can read.

    The subject ("the target gains ...") is left to the caller. Returns "" for an effect with no
    printed evidence, so an unfamiliar rider is left out of the help rather than described with
    invented rules.
    """
    kind = str(effect.get("type") or "")
    evidence = str(effect.get("evidence") or "").strip()
    if evidence:
        return evidence
    if kind == "mark":
        name = str(effect.get("mark") or "Mark")
        until = " that lasts until something removes it" if (effect.get("duration") or {}).get("kind") == "until_removed" else ""
        return f"1 {name}{until}"
    if kind in ("disadvantage", "advantage"):
        word = "Disadvantage" if kind == "disadvantage" else "Advantage"
        on = str(effect.get("on") or "").replace("_", " ")
        return f"{word} on its next {on}" if on else word
    if kind == "condition" and effect.get("condition"):
        return str(effect["condition"]).replace("_", " ")
    return ""


def _list_words(words: list[str]) -> str:
    """Join rider phrases into one clause, dropping the full stops printed evidence already carries."""
    words = [" ".join(str(word or "").split()).rstrip(" .") for word in words]
    words = [word for word in words if word]
    if not words:
        return ""
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _sentence(text: str) -> str:
    """One clean sentence from printed evidence, which already carries its own full stop."""
    text = " ".join(str(text or "").split()).rstrip(" .")
    return f"{text}." if text else ""


def _kept_damage(typed: dict[str, Any], cl: int) -> str:
    """The damage this button still deals, preferring the owner's own printed sentence for it."""
    from ..tabletop import damage_text

    evidence = next((str(effect["evidence"]) for effect in _walk(typed.get("effects") or [])
                     if effect.get("type") == "damage" and effect.get("evidence")), "")
    return evidence or damage_text(typed, cl)


def _identity(effect: dict[str, Any]) -> str:
    """A stable content key for one compiled effect.

    ``typed["replacement"]`` names the same effect twice: once among everything the replacement
    removed, and again among the subset a *failed save* used to grant. They are matched by
    content rather than by object identity, because a button reads them back from serialized
    data. The split is what keeps a ``replace_healing`` trade -- which removes ordinary healing
    that no failed save ever provided -- from being described as a lost failed-save benefit
    (review LUNA74r2 finding 3).
    """
    return json.dumps(effect, sort_keys=True, default=str)


def _cost_words(row: dict[str, Any]) -> str:
    """What pressing this button costs, in words rather than resource ids.

    The amounts are read with ``decision_text.costs_text``, the public formatter every other
    decision prompt and button in the app already uses. It reads both shapes a compiled cost row
    arrives in -- the ``(resource id, amount)`` pair this button receives from
    ``ActionDefinition.model_dump(mode="json")``, and the typed dictionary -- so a paid ability's
    real price is printed instead of a zero from reading a pair as if it were an object.
    """
    from ..decision_text import costs_text

    timing = {"ACTION": "one Action", "BONUS_ACTION": "one Bonus Action"}.get(str(row.get("economy") or ""), "")
    parts = [part for part in (timing, costs_text(row.get("costs"))) if part]
    return " and ".join(parts) if parts else "nothing"


@hook("button_description")
def replacement_choice_help(row: dict[str, Any]) -> str | None:
    """Explain an optional replacement button: what it replaces, keeps, gives up, and costs."""
    from ..status_text import printed_excerpt
    from ..tabletop import saving_throw_text

    typed = (row.get("parameters") or {}).get("typed") or {}
    summary = typed.get("replacement")
    if not isinstance(summary, dict):
        # Native variants retain the modifier's reviewed printed rule instead
        # of the generic executor's replacement summary. Describe that choice,
        # never the unmodified base action's save as though it still applied.
        modifier = typed.get("modifier") or {}
        if typed.get("variant_of") and modifier.get("id"):
            from ..typed_numbers import authority_mechanics
            reviewed = (authority_mechanics().get(str(modifier["id"])) or {}).get("modifier") or {}
            if not str(reviewed.get("when") or "").startswith("replace_"):
                return None
            printed = printed_excerpt(str(modifier["id"]), str(modifier.get("name") or ""))
            if printed:
                return f"{printed}\n\nCost: {_cost_words(row)}."
        return None
    numbers = typed.get("numbers") or {}
    removed = [effect for effect in summary.get("removed") or [] if isinstance(effect, dict)]
    reliable = [effect for effect in summary.get("reliable") or [] if isinstance(effect, dict)]
    added = [effect for effect in summary.get("added") or [] if isinstance(effect, dict)]
    base_name = str(summary.get("base_name") or "").strip() or "this ability"
    lines: list[str] = []

    saves = [effect for effect in removed if effect.get("type") == "save"]
    if saves:
        replaced = _list_words([f"its {saving_throw_text(effect, numbers) or 'saving throw'} removed" for effect in saves])
        lines.append(f"This is {base_name} with {replaced}. The target is never asked to make that save.")
    else:
        lines.append(f"This is {base_name} with part of what it normally does replaced.")

    kept = _kept_damage(typed, int(numbers.get("cl") or 1))
    if kept:
        lines.append(f"You still make the same attack, and on a hit {_sentence(kept)}")

    guaranteed = _list_words([_rider_words(effect) for effect in reliable])
    if guaranteed:
        lines.append(f"Instead of that, a hit always gives the target {_sentence(guaranteed)} "
                     "It happens on a hit, with no save to fail.")

    # What this choice does that the base never did. A ``replace_healing`` variant lives here:
    # it replaces ordinary healing, and without this line the button would only say what is gone.
    instead = _list_words([_rider_words(effect) for effect in added])
    if instead:
        # Printed evidence is a whole sentence, so it already starts with a capital. A phrase
        # ("the target regains ...") reads best after "Instead, "; a sentence reads best after a
        # colon. Both say the same thing, so the lead-in follows the evidence it introduces.
        lead_in = "Instead, " if instead[:1].islower() else "What this choice does instead: "
        lines.append(f"{lead_in}{_sentence(instead)}")

    # What is given up, split by what a failed save actually granted. Only that subset may be
    # described as a lost failed-save benefit; the rest is ordinary effect the choice replaces.
    # A record saved before this change carries no ``save_gated`` key at all, and the engine
    # loads its catalog straight out of the saved bundle -- so those fights keep the wording
    # they were saved with rather than being silently re-worded.
    gated = summary.get("save_gated")
    legacy = gated is None
    gated_keys = {_identity(effect) for effect in gated or [] if isinstance(effect, dict)}
    gave_up = [effect for effect in removed if effect.get("type") != "save"]
    lost_to_save = _list_words([_rider_words(effect) for effect in gave_up
                                if legacy or _identity(effect) in gated_keys])
    lost_otherwise = _list_words([_rider_words(effect) for effect in gave_up
                                  if not legacy and _identity(effect) not in gated_keys])
    if lost_to_save:
        lines.append(f"The target loses what a failed save would have given it: {lost_to_save}.")
    if lost_otherwise:
        lines.append(f"You give up the effect it normally has: {lost_otherwise}.")

    lines.append(f"Cost: {_cost_words(row)}.")

    modifier = typed.get("modifier") or {}
    printed = printed_excerpt(str(modifier.get("id") or ""), str(modifier.get("name") or "")) if modifier.get("id") else ""
    if printed:
        lines.append(printed)
    return "\n\n".join(lines)
