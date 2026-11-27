"""The Piercing Needle's Vacuum Cut, No Space Between Thought and Steel and Vacuum Slice (rider lane 10, 2026-09-29). Rules text: the
owner's Sphere Compendium, "The Piercing Needle" (authority/typed_mechanics/rules_text.json).

  Vacuum Cut      "When you take the Attack action and make a melee weapon attack during the same turn that you draw or otherwise equip
                  the weapon used for that attack, you may expend Martial Focus to extend that attack's reach to 30 feet. Vacuum Cut:
                  changes the reach of that single melee weapon attack; does not turn the attack into a ranged attack; does not allow
                  the attack to pass through Total Cover; does not automatically allow the attack to target a creature you cannot
                  perceive; may receive an Exploit if it otherwise satisfies the Exploit rules."
  No Space Between "When you use Vacuum Cut, increase its reach from 30 feet to 60 feet. Once per turn, when you use Vacuum Cut, you may
  Thought and     draw or otherwise equip the required weapon as part of making the attack even if you already equipped or unequipped a
  Steel           weapon during the same Attack action. This talent does not allow Vacuum Cut to pass through Total Cover or strike a
                  target you cannot otherwise perceive."
  Vacuum Slice    "Action Type: Bonus Action. When you use Vacuum Cut, you may use a Bonus Action to replace the single-target attack with
                  a 30-foot-long, 5-foot-wide line originating from you. Make one attack roll and compare the result to the Armor Class
                  of each creature in the line. Each creature hit takes the normal damage of the melee weapon attack. Vacuum Slice: deals
                  damage only once to each creature in the line; deals only the attack's normal damage; does not apply Exploits, Weapon
                  Mastery properties, or other on-hit riders; does not pass through Total Cover."

Each melee weapon attack of a Vacuum Cut owner gets a variant (the ``maneuvers`` hook, like Lunge): "<weapon> attack: Vacuum Cut"
(Martial Focus, reach 30 feet, 60 with No Space; the Attack action's later strikes keep the weapon's reach: the attack row's
``later_reach_ft``), offered only against a creature beyond the weapon's own reach and only on an Attack action, which is the part
of the printed trigger the table can decide ("When you take the Attack action ..."). The other half of the printed trigger, "during
the same turn that you draw or otherwise equip the weapon used for that attack", stays a Game Master line: nothing in the fight
records when a weapon was drawn or equipped, so the engine cannot decide it, and a stowed weapon cannot be attacked with at all
(the Draw is free and costs no Action). No Space's second draw needs nothing at the table, since drawing already costs no Action and
can be repeated. The variant is still an ordinary melee weapon attack (Exploits, Weapon Mastery, cover and sight as usual).

Vacuum Slice stays a GM line: "Make one attack roll and compare the result to the Armor Class of each creature in the line" needs
one roll shared by several targets, and the sealed attack resolver (combat/gate2_engine.py ``_resolve_attack_spec``, a saved-fight
controller lock file) rolls inside a single target's attempt with its own modes, declaration and reaction checkpoints. That is
lock round 3's shared-roll attack seam, not a plug-in change; no Slice variant is offered and
``vacuum_slice`` only keeps old typed rows honest.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from .needle import FOCUS
from .weapon_profiles import melee_weapon_attack

VACUUM_CUT, NO_SPACE, VACUUM_SLICE = "TAL_FENCING_VACUUM_CUT", "TAL_FENCING_NO_SPACE_BETWEEN_THOUGHT_AND_STEEL", "TAL_FENCING_VACUUM_SLICE"


@hook("maneuvers")
def vacuum_variants(info: dict[str, Any]) -> dict[str, Any] | None:
    owned = set(info.get("owned") or ())
    if VACUUM_CUT not in owned:
        return None
    from ..gate2_runtime_models import EconomyKind

    reach = 60 if NO_SPACE in owned else 30
    made = []
    for action in info.get("actions") or ():
        # "When you take the Attack action and make a melee weapon attack during the same turn that you draw or otherwise equip the
        # weapon used for that attack": the Attack action is the half of that trigger the table decides, so no other action type is
        # offered one. The draw itself stays the Game Master's (see the module docstring and the record's own rider).
        if getattr(action, "economy", None) != EconomyKind.ACTION:
            continue
        if not melee_weapon_attack(action):
            continue
        normal = int(action.range_ft or 5)
        parameters = copy.deepcopy(action.parameters)
        typed = parameters["typed"]
        attack = next(e for e in typed["effects"] if isinstance(e, dict) and e.get("type") == "attack")
        attack["later_reach_ft"] = normal
        focus = {"type": "spend_resource", "resource_id": FOCUS, "flat": 1, "applies_to": "self"}
        typed["effects"] = [focus, *typed["effects"]]
        typed.update({"option_of": action.source_definition_id, "option_label": "Vacuum Cut"})
        parameters.update({"requires_resource": {FOCUS: 1}, "needle_vacuum": "cut", "normal_reach_ft": normal})
        made.append(type(action)(source_definition_id=f"{action.source_definition_id}#vacuum_cut", display_name=f"{action.display_name}: Vacuum Cut",
                                 owner_id=action.owner_id, economy=action.economy, resolution_kind=action.resolution_kind,
                                 target_kind=action.target_kind, range_ft=reach, parameters=parameters))
    return {"actions": made} if made else None


@hook("candidate_allowed")
def vacuum_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if VACUUM_SLICE in str(getattr(action, "source_definition_id", "")) or (getattr(action, "parameters", None) or {}).get("needle_vacuum") == "slice":
        return False
    kind = (getattr(action, "parameters", None) or {}).get("needle_vacuum")
    if not kind:
        return None
    if int(actor.resources.get(FOCUS, 0)) < 1:
        return False
    if kind == "slice":
        return None if actor.bonus_action_available else False
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if target is None:
        return None
    return None if engine._distance_actor_to_actor(actor, target) > int(action.parameters.get("normal_reach_ft") or 5) else False


@effect("needle_vacuum_slice")
def vacuum_slice(ctx: Any, eff: dict[str, Any]) -> None:
    """Compatibility handler for old typed rows; no unreviewed attack resolution."""
    ctx.rider("Vacuum Slice: GM resolves the shared attack roll with normal attack modes, effective AC and reaction checkpoints. "
              "Automation deferred to lock round 3's shared-roll attack seam.")
