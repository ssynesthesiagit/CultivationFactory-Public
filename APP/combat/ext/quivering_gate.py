"""Quivering Gate Strike, the release (Iron Fist, CL 15: authority TAL_IRON_FIST_QUIVERING_GATE_STRIKE).

"Make one Unarmed Strike.  Hit: The target takes normal damage and gains a hidden quivering mark for 1 minute.  While the mark
lasts, you may use an Action to release it if the target is within 120 feet and on the same plane.  When released, the target
makes a Constitution saving throw.  Failed Save: Take 10d10 Force damage and become Stunned until the start of your next turn.
Successful Save: Take half damage and cannot take Reactions until the start of your next turn.  The mark ends after release."

The strike and its mark are the authority entry's (reviewed_final.d/sys_menus-forms.json); the once-per-creature limit is
combat/ext/target_limits.py's.  The release is an Action of its own that the strike's entry cannot carry (it costs no Martial
Focus and no use), so it is added here and offered only against a creature that bears the fighter's mark.
"""

from __future__ import annotations

from typing import Any

from . import hook

FEATURE = "TAL_IRON_FIST_QUIVERING_GATE_STRIKE"
MARK = "Quivering Gate"
DICE = {"count": 10, "sides": 10}


@hook("compile_actions")
def release_action(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if FEATURE not in info["owned_ids"]:
        return None
    effects = [
        {"type": "spend_mark", "mark": MARK, "applies_to": "target", "evidence": "The mark ends after release."},
        {"type": "save", "ability": "con", "dc": "technique_save_dc", "evidence": "the target makes a Constitution saving throw",
         "on_fail": [{"type": "damage", "dice": DICE, "damage_types": ["force"], "evidence": "Take 10d10 Force damage"},
                     {"type": "condition", "applies_to": "target", "condition": "stunned", "duration": "until_start_of_next_turn",
                      "evidence": "become Stunned until the start of your next turn"}],
         "on_success": [{"type": "half_damage", "applies_to": "target", "dice": DICE, "damage_types": ["force"], "evidence": "Take half damage"},
                        {"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn",
                         "evidence": "cannot take Reactions until the start of your next turn"}]}]
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.quivering_gate_release", display_name="Release Quivering Gate Mark",
        owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=120,
        parameters={"typed": {"effects": effects, "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 55, "release_of": MARK,
                    "description": "Release the hidden quivering mark on a creature within 120 feet: it makes a Constitution save. Failed: 10d10 Force "
                                   "and Stunned until the start of your next turn. Successful: half damage and no Reactions until then."})]


@hook("candidate_allowed")
def only_a_marked_creature(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    from ..typed_executor import bears_mark

    if (getattr(action, "parameters", None) or {}).get("release_of") != MARK:
        return None
    return any(bears_mark(engine.state.actors[target_id], actor.entity_id, MARK) for target_id in candidate.target_ids or ()
               if target_id in engine.state.actors)
