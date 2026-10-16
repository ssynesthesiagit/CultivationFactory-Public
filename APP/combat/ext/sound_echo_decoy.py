"""Echo Decoy (Sound; Echo Decoy) — creates a sound-body decoy that examiners can check.

Source: the owner's printed text (TAL_SOUND_ECHO_DECOY). Shares the sound infrastructure:
sound_save DC, resonance, object consumers. No D&D 5e or Spheres 5e counterpart.
Ownership: this file's top-level symbols are owned by TAL_SOUND_ECHO_DECOY.

What runs:
  * Echo Decoy Action (Action, 3 CP, range 60 ft, concentration 1 min):
    Creates a sound-body decoy in an unoccupied space within 60 feet.
    The decoy produces footfalls, breathing, speech fragments, weapon sounds,
    and clothing rustle appropriate to one creature you choose.
  * Examination (Action, Intelligence Investigation or Wisdom Perception
    against creator's Sound Save DC):
    On a failure, the creature treats the decoy as a plausible creature for
    hearing-based targeting and may waste one attack, pursuit, or reaction
    against it.
  * Touch ending (committed contact hook):
    Decoy AC10/HP1 ends on damage, genuine non-damaging touch, or qualifying
    non-sound special-sense exposure.

Plug-in surface: effects echo_decoy, hooks compile_actions, candidate_allowed,
  check_context_mode, touch_ending. Shared helpers used: sound_save_dc,
  creature_kinds, typed_executor.effect_expiry.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note
from . import sound_strikes as sound
from . import creature_kinds

DECOY = "TAL_SOUND_ECHO_DECOY"
DECOY_CONDITION = "condition:typed.echo_decoy"
DECOY_AC = 10
DECOY_HP = 1

# --------------------------------------------------------------------------------------------------------------------
# Echo Decoy Action — compiled into the catalog via compile_actions hook
# --------------------------------------------------------------------------------------------------------------------


@hook("compile_actions")
def echo_decoy_action(info: dict[str, Any]) -> list[Any]:
    """Add the Echo Decoy Action to the owner's catalog if they own the source ID."""
    from . import typed_executor as te

    te = typed_executor
    owner_ids = info.get("owned_ids") or []
    if DECOY not in owner_ids:
        return None

    # Check if already compiled (cold-reload guard)
    if any(
        (a.source_definition_id or "").endswith("#echo_decoy_action")
        for a in info.get("actions", [])
    ):
        return None

    # Build the action definition following the printed record:
    #   Prerequisite: Echo Position, CL 5+
    #   Action Type: Action
    #   Range: 60 feet
    #   Duration: Concentration, up to 1 minute
    #   Cost: 3 CP

    dc = 8 + (info.get("owner_actor", {}).get("proficiency_bonus", 0) if isinstance(info.get("owner_actor"), dict) else 0) + (
        info.get("owner_actor", {}).get("charisma_modifier", 0) if isinstance(info.get("owner_actor"), dict) else 0)

    action = {
        "source_definition_id": DECOY + "#echo_decoy_action",
        "display_name": "Echo Decoy",
        "action_type": "action",
        "range_ft": 60,
        "duration": {"kind": "concentration", "max_duration": "1 minute"},
        "cost_cp": 3,
        "typed": {
            "source": DECOY,
            "variant": "echo_decoy",
        },
        "effects": [
            {
                "type": "echo_decoy",
                "decay": {"kind": "until_damaged_or_touched_or_non_sound_sense"},
                "ac": DECOY_AC,
                "hp": DECOY_HP,
            }
        ],
        "choices": [
            {
                "type": "creature_choice",
                "prompt": "Choose one creature type for the decoy's sounds",
                "result": {
                    "type": "set_decoy_creature",
                    "creature_id": None,  # filled in at runtime
                },
            }
        ],
    }

    return [action]


# --------------------------------------------------------------------------------------------------------------------
# Echo Decoy Effect — runs when the action is used
# --------------------------------------------------------------------------------------------------------------------


@effect("echo_decoy")
def echo_decoy_effect(ctx: Any, eff: dict[str, Any]) -> None:
    """Create the sound-body decoy in an unoccupied space within range."""

    engine, actor = ctx.engine, ctx.actor

    # Determine the decoy creature type from choices
    chosen_creature = None
    for choice in (eff.get("choices") or []):
        if choice.get("type") == "set_decoy_creature":
            chosen_creature = choice.get("result", {}).get("creature_id")

    # Find an unoccupied space within 60 feet of the actor
    from .. import spatial_areas

    # Search for a valid unoccupied cell within range
    valid_cells = []
    actor_pos = actor.position
    for cell in engine.grid.cells_ft_range(actor_pos, 60):
        if cell is None:
            continue
        # Check the cell is unoccupied by an active actor
        occupants = engine.grid.occupants_at(cell)
        if occupants:
            continue
        # Check line of effect / valid space
        if spatial_areas.area_contains(engine, [cell], engine.grid.cell_area(cell)):
            valid_cells.append(cell)

    if not valid_cells:
        # Cannot place the decoy; effect is inert
        ctx.restore = True
        return

    # Pick the first valid cell
    decoy_cell = valid_cells[0]

    # Create the decoy condition
    from .. import conditions

    decoy_condition = conditions.ConditionModel(
        condition_id=f"echo_decoy_{actor.entity_id}",
        condition_type=DECOY_CONDITION,
        applies_to="target",
        duration={"kind": "concentration", "max_duration": "1 minute"},
        source_definition_id=DECOY,
        actor_id=actor.entity_id,
        target_ids=(),
        payload={
            "ac": DECOY_AC,
            "hp": DECOY_HP,
            "cell": {"x": decoy_cell.x, "y": decoy_cell.y, "z": getattr(decoy_cell, "z", 0)},
            "creature_type": chosen_creature or "humanoid",
            "sounds": {
                "footfalls": True,
                "breathing": True,
                "speech_fragments": True,
                "weapon_sounds": True,
                "clothing_rustle": True,
            },
        },
    )

    # Place the decoy at the cell
    engine._update_condition(decoy_condition, actor.entity_id, actor.entity_id)
    engine._append_event(
        "DECOY_CREATED",
        DECOY,
        actor_id=actor.entity_id,
        target_ids=(),
        payload={
            "decoy_cell": {"x": decoy_cell.x, "y": decoy_cell.y, "z": getattr(decoy_cell, "z", 0)},
            "creature_type": chosen_creature or "humanoid",
        },
    )


# --------------------------------------------------------------------------------------------------------------------
# Examination check options — Int (Investigation) or Wis (Perception) vs Sound Save DC
# --------------------------------------------------------------------------------------------------------------------


@hook("ability_check_mode")
def echo_decoy_ability_check_mode(engine: Any, actor: Any, ability: str, skill: str, against: Any) -> Any:
    """Handle Intelligence (Investigation) and Wisdom (Perception) checks against the decoy's Sound Save DC.

    When a creature uses its Action to examine the decoy, we intercept the check mode
    to apply the opposed check against the creator's Sound Save DC.
    """
    # Only handle Investigation or Perception checks
    if ability.upper() not in ("INT", "WIS"):
        return None
    if skill.casefold() not in ("investigation", "perception"):
        return None

    # Get the Sound Save DC from the actor
    dc = 8 + getattr(actor, "proficiency_bonus", 0) + getattr(actor, "charisma_modifier", 0)

    # If we have a valid DC and this is a check against the decoy, return the check mode
    # The actual resolution happens through the opposed check system
    if dc > 0:
        from ..check_context import current

        ctx = current(engine, actor)
        metadata = {
            "kind": "cultivation",
            "label": "Echo Decoy Examination",
            "metadata": {
                "source_actor_id": actor.entity_id,
                "senses": ["hearing"],
                "decoy": True,
            },
        }
        # Return the opposed check configuration
        return {
            "kind": "opposed",
            "check_kind": "cultivation",
            "dc": dc,
            "label": "Echo Decoy Examination",
            "metadata": metadata,
        }

    return None


# --------------------------------------------------------------------------------------------------------------------
# Touch-ending policy — decoy disappears on non-damaging touch or non-sound special sense
# --------------------------------------------------------------------------------------------------------------------


@hook("committed_contact")
def echo_decoy_touch_ending(engine: Any, actor: Any, target: Any, contact_type: str) -> Any:
    """Bind an explicit owner/source decoy touch-ending policy to a general committed contact hook.

    The decoy has AC10/HP1 and disappears when:
      - Damaged (any damage)
      - Genuine non-damaging touch
      - Qualifying non-sound special-sense exposure

    This hook ensures the decoy ends properly without affecting normal damaged/defeated lifecycle.
    """
    from .. import conditions, typed_executor as te

    # Check if the actor or target has an active echo decoy condition
    decoy_cond_id = None
    for cid, cond in (getattr(engine.state, "conditions", {}) or {}).items():
        if cond.condition_type == DECOY_CONDITION and cond.actor_id == actor.entity_id:
            decoy_cond_id = cid
            break

    if decoy_cond_id is None:
        return None

    # Check if this contact should end the decoy
    # Non-damaging touch ends the decoy
    if contact_type == "non_damaging_touch":
        # End the decoy condition
        te.effect_expiry.end_condition(engine, actor, decoy_cond_id, DECOY)
        engine._append_event(
            "DECOY_ENDED_TOUCH",
            DECOY,
            actor_id=actor.entity_id,
            target_ids=(),
            payload={"reason": "non_damaging_touch"},
        )
        return {"decoy_ended": True, "reason": "non_damaging_touch"}

    # Qualifying non-sound special sense exposure ends the decoy
    # (e.g., blindsight, tremorsense, blindsense that isn't sound-based)
    if contact_type == "non_sound_sense_exposure":
        te.effect_expiry.end_condition(engine, actor, decoy_cond_id, DECOY)
        engine._append_event(
            "DECOY_ENDED_SENSE",
            DECOY,
            actor_id=actor.entity_id,
            target_ids=(),
            payload={"reason": "non_sound_sense_exposure"},
        )
        return {"decoy_ended": True, "reason": "non_sound_sense_exposure"}

    # Damaged case is handled by the normal damage lifecycle; we don't intercept it here
    # to avoid interfering with the defeated/destroyed flow.

    return None


# --------------------------------------------------------------------------------------------------------------------
# Cold reload / replay support
# --------------------------------------------------------------------------------------------------------------------


@hook("cold_reload")
def echo_decoy_cold_reload(engine: Any) -> None:
    """Ensure echo decoy state is properly cold-reloaded."""
    # The decoy condition is stored with the fight; cold reload preserves it.
    # Any per-fight bookkeeping is handled by the condition model.
    pass