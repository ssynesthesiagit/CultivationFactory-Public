"""Insights that act "when Initiative is rolled", through the documented fight-setup queue (OPUS1 batch 6).

Each owner gets one fight_setup task (fight_setup_tasks / fight_setup in combat/ext/__init__.py): it resolves after
Initiative and before turn one, in one transaction, asking a person or deciding for an AI fighter (needle.ask).

Emergency Commander   "When Initiative is rolled, immediately Set the Standard without spending a Bonus Action": the owner
                      chooses one Standard it knows (warleader.known_standards) and Warleader's own ``warleader_standard``
                      effect sets it, lasting as printed until the start of the owner's next turn. The table models no
                      Surprise, so the "if you are Surprised" timing never arises.
Fool's Balance        "When you roll Initiative, you may immediately use Reeling Step before the first turn begins": the
                      owner may run its own Reeling Step (Drunken Style's ``drunken_reeling_step`` effect, which chooses
                      the tested creature and the route itself); if that applies Off-Rhythm to a creature and the owner has
                      no Martial Focus, it regains Martial Focus. Not offered when the owner has no Reeling Step or Speed 0.

Rows are sealed into block ``initiative_insights`` (kind = Insight id); without one an actor gets no task.
"""
from __future__ import annotations

from typing import Any

from . import hook, note
from .passive_rows import row_of

BLOCK = "initiative_insights"
EMERGENCY = "insight.emergency-commander"
FOOLS_BALANCE = "insight.fool-s-balance"
FOCUS = "resource:core.martial_focus"
OUTCOMES = {
    EMERGENCY: "When Initiative is rolled, you Set a Standard you know at once, without spending a Bonus Action",
    FOOLS_BALANCE: "When Initiative is rolled, you may use Reeling Step before the first turn; if it makes a creature "
                   "Off-Rhythm and you have no Martial Focus, you regain Martial Focus",
}


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    feature = row["feature_id"]
    return [{**row, "kind": feature, "player_outcome": OUTCOMES[feature], "pb": int(numbers["pb"]), "cl": int(numbers["cl"])}]


def _action_with(engine: Any, actor: Any, effect_type: str) -> Any:
    """The owner's own action whose typed effects include ``effect_type`` (its first, by catalog id)."""
    for action_id in sorted(actor.action_ids):
        action = engine.action_catalog.get(action_id)
        effects = (((action.parameters or {}).get("typed") or {}).get("effects") or []) if action is not None else []
        if any(isinstance(row, dict) and row.get("type") == effect_type for row in effects):
            return action
    return None


@hook("fight_setup_tasks")
def tasks(engine: Any) -> list[dict[str, str]] | None:
    found = []
    for actor in engine.state.actors.values():
        for feature in (EMERGENCY, FOOLS_BALANCE):
            if actor.active and row_of(engine, actor.entity_id, BLOCK, feature) is not None:
                found.append({"actor_id": actor.entity_id, "source_id": feature})
    return found or None


@hook("fight_setup")
def resolve(engine: Any, actor: Any, source: str, intent: Any) -> bool | None:
    if source == EMERGENCY:
        _emergency(engine, actor, intent)
        return True
    if source == FOOLS_BALANCE:
        _fools_balance(engine, actor, intent)
        return True
    return None


def _context(engine: Any, actor: Any, action: Any, intent: Any) -> Any:
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    return te.Context(engine, actor, action, intent, typed, [actor], actor, {})


def _emergency(engine: Any, actor: Any, intent: Any) -> None:
    from .needle import ask, checkpoint_id
    from .warleader import STANDARDS, known_standards

    action = _action_with(engine, actor, "warleader_standard")
    standards = [slug for slug in known_standards(engine, actor) if slug in STANDARDS]
    if action is None or not standards:
        return
    picked = ask(engine, intent, checkpoint_id(engine, EMERGENCY, actor.entity_id), actor, "choice:needle.initiative_insights",
                 standards, name="Emergency Commander", feature_id=EMERGENCY, target_id=actor.entity_id,
                 labels={slug: f"Set the Standard: {STANDARDS[slug][0]}. {STANDARDS[slug][1]}" for slug in standards},
                 prompt=("Emergency Commander: Initiative has been rolled. Choose the Standard you Set now, without spending "
                         "a Bonus Action; it lasts until the start of your next turn. You benefit while able to act; "
                         "Commanded allies are allies within your Command Range (normally 30 feet) who can see or hear "
                         "you and are able to follow orders."))
    slug = (picked or standards)[0]
    from ..typed_executor import run_effects

    run_effects(_context(engine, actor, action, intent), [{"type": "warleader_standard", "standard": slug}])


def _fools_balance(engine: Any, actor: Any, intent: Any) -> None:
    action = _action_with(engine, actor, "drunken_reeling_step")
    if action is None or engine._effective_speed(actor) <= 0:
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, intent, checkpoint_id(engine, FOOLS_BALANCE, actor.entity_id), actor, "choice:needle.initiative_insights",
                 ["use"], allow_decline=True, name="Fool's Balance", feature_id=FOOLS_BALANCE, target_id=actor.entity_id,
                 labels={"use": "Use Reeling Step now: move up to 10 feet; one creature within 10 feet that sees you makes a "
                                "Wisdom save or becomes Off-Rhythm from you"},
                 prompt=("Fool's Balance: Initiative has been rolled. Use Reeling Step before the first turn begins? No Bonus "
                         "Action or cost. If it makes a creature Off-Rhythm and you have no Martial Focus, you regain it."))
    if not picked:
        return
    from ..typed_executor import mark_condition_id, run_effects
    from .drunken_style import MARK

    before = len(engine.events)
    typed = (action.parameters or {}).get("typed") or {}
    run_effects(_context(engine, actor, action, intent), list(typed.get("effects") or []))
    off_rhythm = mark_condition_id(MARK, actor.entity_id)
    if int(actor.resources.get(FOCUS, 1)) < 1 and FOCUS in actor.resources and any(
            e.event_type == "CONDITION_APPLIED" and (e.payload or {}).get("condition_id") == off_rhythm
            for e in engine.events[before:]):
        engine._gain_resource(actor, FOCUS, 1, FOOLS_BALANCE)
        note(engine, f"passive:{FOOLS_BALANCE}", actor, f"Fool's Balance: {actor.display_name} regains Martial Focus.")
