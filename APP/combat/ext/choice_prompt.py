"""Display-only choice context shared by Needle, Footwork, Thread correction, soul-return consent and rider menus."""
from typing import Any


def action_context(engine: Any, actor: Any, source_id: str, target: Any) -> dict[str, str]:
    """Identify the actual triggering action, its actor and affected creature.

    Strings only; no decision, cost or event changes. Callers with a reaction
    action must pass that action rather than the outer turn's intent.
    """
    action = engine.action_catalog.get(source_id)
    return {"source_definition_id": source_id,
            "action_name": str(action.display_name if action else ""),
            "action_actor_id": str(actor.entity_id if actor else ""),
            "affected_id": str(target.entity_id)}
