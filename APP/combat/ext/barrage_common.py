"""Public Barrage construction shared by docket_maneuvers and barrage_blitz.

Selection and talent effects stay with each plug-in; this module owns the
single-attack, damage-modifier and Bonus Action follow-up rules.
Follow-ups identify the same physical weapon for shared hand/readiness queries.
"""
import copy
from typing import Any


def one_attack(typed: dict[str, Any]) -> dict[str, Any]:
    typed = copy.deepcopy(typed)
    typed["effects"] = [{**e, "count": 1} if e.get("type") == "attack" else e
                        for e in typed.get("effects", [])]
    return typed


def follow_up(base: Any, typed: dict[str, Any], weapon_id: str, flag: str,
              owned: list[str], action_id: str, name: str, description: str,
              **extra: Any) -> Any:
    from ..gate2_runtime_models import EconomyKind

    typed = one_attack(typed)
    weapon = dict(typed.get("weapon") or {})
    damage = dict(weapon.get("damage") or {})
    refinement = int(typed.get("magic_bonus") or 0)
    if damage:
        damage["modifier"] = min(0, int(damage.get("modifier") or 0) - refinement) + refinement
        weapon["damage"] = damage
    if weapon.get("fixed_damage") is not None:
        weapon["fixed_damage"] = max(0, 1 + min(0, int(damage.get("modifier") or 0)))
    if "weapon" in typed:
        typed["weapon"] = weapon
    # Mixed Barrage may replace the primary ranged weapon with a different
    # melee weapon or an Unarmed Strike. Its usage flag still belongs to the
    # primary Barrage; physical readiness belongs to this attack's base.
    typed.update(maneuver="barrage_follow_up", maneuver_of=weapon_id, weapon_source_id=base.source_definition_id,
                 uses=[flag], barrage_owned=[mid for mid in owned if mid.startswith("TAL_BARRAGE_")], **extra)
    typed.pop("opens", None)
    typed.pop("opportunity_of", None)
    per_hit = ((int(damage.get("count") or 1) * (int(damage.get("sides") or 4) + 1)) // 2
               + int(damage.get("modifier") or 0)) if damage else 0
    return base.model_copy(update={
        "source_definition_id": action_id, "display_name": name,
        "economy": EconomyKind.BONUS_ACTION,
        "parameters": {**{k: v for k, v in base.parameters.items() if k not in ("typed", "expected_damage")},
                       "typed": typed, "expected_damage": max(0, per_hit),
                       "requires_turn_flag": flag, "description": description}})
