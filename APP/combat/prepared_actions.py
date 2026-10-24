"""Opt-in supplemental catalog actions, Ready declarations and table-owned Reactions.

Supplemental actions use their own economy through the normal candidate gates;
only Ready declarations always require the actor's Action to remain available.
"""
import logging
from pydantic import Field, JsonValue

from . import ext
from .gate2_runtime_models import CandidateKind
from .models import StrictModel

SOURCE = "system:combat.ready"
CONDITION = "condition:typed.prepared_action"


class PreparedOption(StrictModel):
    option_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    trigger: str = Field(min_length=1)
    data: dict[str, JsonValue] = Field(default_factory=dict)
    automatic_use: bool = False


def candidates(engine, actor, *, sources=None):
    """Supplemental discovery, optionally restricted to selected source IDs."""
    offered = []
    seen_actions = set(actor.action_ids)
    for source_ids in ext.run_strict("additional_actions", engine, actor):
        for source_id in source_ids:
            if sources is not None and source_id not in sources:
                continue
            if source_id in seen_actions:
                continue
            seen_actions.add(source_id)
            offered.extend(engine._action_candidates(actor, engine.action_catalog[source_id]))
    if (not actor.action_available or not ext.has("prepare_options")
            or sources is not None and not any(s.startswith(SOURCE + ':') for s in sources)):
        return offered
    seen = set()
    for rows in ext.run_strict("prepare_options", engine, actor):
        for raw in rows:
            option = PreparedOption.model_validate(raw)
            if option.option_id in seen:
                # A broken provider must not crash the table's read-only menu.
                # Keep the first validated identity; never offer an ambiguous second button.
                logging.getLogger(__name__).warning("duplicate prepared option %s for %s; skipped",
                                                     option.option_id, actor.entity_id)
                continue
            seen.add(option.option_id)
            if len(seen) > 64:
                raise ValueError("too many prepared options (maximum 64)")
            offered.append(engine._candidate(CandidateKind.ACTION, actor, SOURCE + ":" + option.option_id,
                           "Ready: " + option.label, metadata={"prepared": option.model_dump(mode="json")}))
    return offered


def prepare(engine, actor, candidate):
    option = PreparedOption.model_validate(candidate.metadata["prepared"])
    if not actor.active or not actor.action_available or actor.entity_id != engine.state.current_actor_id:
        raise ValueError("Ready requires an Action on your turn")
    actor.action_available = False
    engine._remove_condition(actor, CONDITION, SOURCE)
    engine._apply_condition(actor, CONDITION, option.source_id, actor.entity_id,
                            expires_on="START_OF_SELF_NEXT_TURN", data=option.model_dump(mode="json"))


def on_event(engine, event):
    # Gate 2 passes the exact recorded event here before Gate 4 extension delivery.
    ext.remember_recorded_event(engine, event)
    # Genesis/replay/listing cannot offer a reaction. The accepted action supplies the choice identity.
    if (not ext.has("prepared_action") or not engine._transaction_id or engine._active_intent is None
            or getattr(engine, "_active_turn_advancing", False)
            or getattr(engine, "_resolving_prepared", False)):
        return
    from .choice_checkpoints import dynamic_choice
    from .typed_reactions import can_react

    engine._resolving_prepared = True
    try:
        for actor in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
            if (actor.entity_id == engine.state.current_actor_id or not actor.active or actor.life_state in ("DYING", "STABLE")
                    or not can_react(engine, actor)):
                continue
            held = next((c for c in actor.conditions.values() if c.condition_id == CONDITION), None)
            if held is None:
                continue
            option = PreparedOption.model_validate(held.data)
            if event.event_type != option.trigger:
                continue
            allowed = ext.run_strict("prepared_trigger", engine, actor, option.model_dump(mode="json"), event)
            if allowed != [True]:
                continue
            context = {"actor_id": event.actor_id, "target_id": actor.entity_id,
                       "event_sequence": event.sequence, "event_type": event.event_type, "prepared": held.data}
            _, decision = dynamic_choice(engine, engine._active_intent,
                f"READY:{held.instance_id}:{event.sequence}", actor.entity_id, option.source_id, context,
                # The declaration already bound the action. The table needs only its normal Use/Decline buttons.
                spec_override={"option_ids": [], "minimum_selections": 0, "maximum_selections": 0,
                               "automatic_use": option.automatic_use})
            if decision is None or decision.selection != "USE":
                continue
            from .paid_relocation import activation

            with activation(engine, actor, option.source_id, independent=True):
                # Remove before dispatch: nested events cannot fire this preparation again.
                engine._remove_condition(actor, CONDITION, option.source_id)
                actor.reaction_available = False
                handled = ext.run_strict("prepared_action", engine, actor, option.model_dump(mode="json"),
                                         event, engine._active_intent)
                if handled != [True]:
                    raise ValueError("one plugin must resolve the prepared action")
                engine._append_event("REACTION_RESOLVED", option.source_id, actor_id=actor.entity_id,
                                     payload={"checkpoint": decision.checkpoint, "prepared_option": option.option_id})
    finally:
        engine._resolving_prepared = False
        ext.remember_recorded_event(engine, event)
