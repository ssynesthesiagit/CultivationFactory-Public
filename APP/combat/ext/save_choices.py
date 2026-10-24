"""Target-owned typed saving-throw choices (Technique-Closing Point and future choice saves).

Only save rows with target_choice=True opt in. The ordinary checkpoint transport
asks manual/Ask-me defenders, even on an AI source's turn; AI defenders use the
highest base saving-throw modifier as a deterministic preference. This is an AI
heuristic, not a forecast of conditional bonuses, modes or later reactions.
No roll, reaction resource or one-use modifier is consumed while choosing.
choice_text may name "{actor}" (the creature using the action) and "{subject}" (the creature asked).
Shared helper module: shi_pressure_points uses has_target_choice to enroll
defenders of authority-backed seals for the service's AI-step choice probe.
"""
from typing import Any

from . import hook


def has_target_choice(effects: list[dict[str, Any]]) -> bool:
    """Pure opt-in query shared with shi_pressure_points for its authority-backed seal rows."""
    def contains(value: Any) -> bool:
        if isinstance(value, dict):
            return bool(value.get("type") == "save" and value.get("target_choice")) or any(
                contains(child) for child in value.values())
        return isinstance(value, (list, tuple)) and any(contains(child) for child in value)

    return contains(effects)


@hook("choice_reactors")
def potential_targets(engine: Any) -> tuple[str, ...]:
    """Enroll potential defenders for AI-step probes; actual checkpoints decide who is asked."""
    if not any(has_target_choice((action.parameters.get("typed") or {}).get("effects") or [])
               for action in engine.action_catalog.values()):
        return ()
    return tuple(engine.state.actors)


@hook("save_choice")
def target_choice(ctx: Any, subject: Any, effect: dict[str, Any], options: list[str]) -> str | None:
    if not effect.get("target_choice") or len(options) < 2:
        return None
    from .needle import CHOICE, ask, checkpoint_id

    names = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
             "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}
    name = str(effect.get("name") or ctx.action.display_name)
    preferred = max(options, key=lambda option: subject.saving_throws.get(option, 0))
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "save_choice", ctx.source, subject.entity_id),
                   subject, CHOICE + "save_choice", options, preferred=[preferred],
                   labels={option: f"{names.get(option, option)} saving throw ({subject.saving_throws.get(option, 0):+d})"
                           for option in options}, name=name, target_id=subject.entity_id,
                   prompt=f"{name} after {ctx.actor.display_name}'s {ctx.action.display_name} affects "
                          f"{subject.display_name}. Choose your saving throw; this choice costs no action or resource. "
                          + str(effect.get("choice_text") or "").replace("{actor}", ctx.actor.display_name)
                          .replace("{subject}", subject.display_name))
    return selected[0] if selected else preferred
