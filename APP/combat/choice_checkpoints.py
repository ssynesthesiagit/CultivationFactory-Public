"""Default-inert transport for opt-in choices, including choices costing no Reaction."""
from __future__ import annotations

from . import ext
from .gate4_models import ExtensionChoice


class ChoicePause(ext.ControllerPause):
    """A provider needs a player answer; unwind preview/transaction, never treat
    this control flow as malformed reaction data or commit a partial effect.
    Shared by service previews and generic reaction exception handlers.
    """


def validate(decision, spec: ExtensionChoice):
    if decision is None:
        return
    if decision.selection == "DECLINE":
        if not spec.allow_decline or decision.option_ids or decision.spend:
            raise ValueError("invalid extension choice decline")
        return
    options = decision.option_ids
    if (decision.spend or len(options) != len(set(options))
            or not spec.minimum_selections <= len(options) <= spec.maximum_selections
            or not set(options) <= set(spec.option_ids)):
        raise ValueError("invalid extension choice options")


def dynamic_choice(engine, intent, checkpoint, reactor_id, reaction_id, context=None, *, spec_override=None):
    """Return (handled, decision); no registered provider/spec leaves legacy transport intact."""
    if spec_override is None and not ext.has("choice_options"):
        return False, None
    trigger = context or {}
    specs = ([spec_override] if spec_override is not None else
             ext.run_strict("choice_options", engine, intent, checkpoint, reactor_id, reaction_id, trigger))
    if not specs:
        return False, None
    if len(specs) != 1:
        raise ValueError("one plugin must own each extension choice")
    spec = ExtensionChoice.model_validate(specs[0])
    key = (checkpoint, reactor_id, reaction_id)
    answers = [d for d in intent.reaction_decisions if (d.checkpoint, d.reactor_id, d.reaction_source_id) == key]
    if len(answers) > 1:
        raise ValueError("duplicate extension choice answer")
    cache = getattr(engine, "_gate4_reaction_cache", {})
    provider = getattr(engine, "_gate4_reaction_provider", None)
    record = None
    if answers:
        decision = answers[0]
    elif key in cache:
        decision = cache[key]
    elif provider is None:
        decision = None
    else:
        request = {
            "checkpoint": checkpoint, "reactor_id": reactor_id, "reaction_source_id": reaction_id,
            "protected_target_id": trigger.get("target_id", reactor_id),
            "attacking_actor_id": trigger.get("actor_id", intent.actor_id),
            "legal_reaction_ids": [reaction_id], "spend_options": [],
            "legal_option_ids": list(spec.option_ids), "extension_choice": spec.model_dump(mode="json"),
            "choice_trigger": trigger,
        }
        decision, record = provider(request)
    if decision is not None and (decision.checkpoint, decision.reactor_id, decision.reaction_source_id) != key:
        raise ValueError("extension choice returned for another checkpoint")
    validate(decision, spec)
    if hasattr(engine, "_gate4_reaction_cache"):
        engine._gate4_reaction_cache[key] = decision
    if record is not None:
        engine.gate4_reaction_decision_records.append(record)
    return True, decision


def roll_modes(base, results):
    modes = {base} - {"NORMAL", None}
    modes.update(r.get("mode") for r in results if isinstance(r, dict) and r.get("mode") in {"ADVANTAGE", "DISADVANTAGE"})
    return next(iter(modes)) if len(modes) == 1 else "NORMAL"
