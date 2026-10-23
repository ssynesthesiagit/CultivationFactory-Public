"""Refined/Heavenly Fist's shared integrated-weapon interface.

Used by integrated_weapons and its Blade, Chain, Bow and other group providers.
Identity is the recorded physical weapon, never the attack's chosen ability.
"""
from typing import Any

from . import hook

PREFIX = "tianxia.path.body_refining.feature."
BLOCK = "integrated_authority"


@hook("compile_bundle")
def authority_rows(bundle: dict, info: dict) -> dict | None:
    from .integrated_weapons import integrated_bases

    owned = set(info["owned_ids"])
    heavenly = PREFIX + "heavenly_fist" in owned
    refined = heavenly or PREFIX + "refined_iron_fist" in owned
    if not refined:
        return None
    from ..gate2_runtime_models import ActionDefinition
    weapons = integrated_bases({**info, "actions": [ActionDefinition.model_validate(a) for a in bundle["action_catalog"]]})
    if not weapons:
        return None
    import copy
    from ..weapon_delivery import physical_weapon_id
    result = copy.deepcopy(bundle)
    identities = {a.source_definition_id for a in weapons}
    for action in result["action_catalog"]:
        parameters = action.get("parameters") or {}
        typed = parameters.get("typed") or {}
        identity = typed.get("object_weapon_source") or physical_weapon_id(action["source_definition_id"], parameters)
        if identity in identities:
            typed["mundane"] = False
            weapon = typed.get("weapon") or typed.get("object_weapon")
            if weapon:
                weapon.update(magical=1, cultivation_powered=1)
                if heavenly:
                    weapon["adamantine"] = 1
    result["typed_passives"] = [*bundle["typed_passives"], *[
        {"block": BLOCK, "kind": "weapon", "weapon": a.source_definition_id,
         "heavenly": int(heavenly), "cl": int(info["numbers"]["cl"])} for a in weapons]]
    return result


def weapon_row(engine: Any, actor: Any, action: Any) -> dict | None:
    from ..weapon_delivery import physical_weapon_id
    from .hand_occupancy import weapon_allowed

    if actor is None or action is None or weapon_allowed(engine, actor, action) is False:
        return None
    identity = physical_weapon_id(action.source_definition_id, action.parameters)
    return next((r for r in getattr(engine, "typed_passive_rows", {}).get(actor.entity_id, [])
                 if r.get("block") == BLOCK and r.get("weapon") == identity), None)


@hook("attack_damage_types")
def heavenly_types(ctx: Any, attack: dict, kinds: Any) -> list[str] | None:
    action = ctx.engine.action_catalog.get(ctx.typed.get("object_weapon_source")) if ctx.typed.get("object_weapon_source") else ctx.action
    row = weapon_row(ctx.engine, ctx.actor, action)
    if row and row["heavenly"]:
        return list(dict.fromkeys([*kinds, "FORCE"]))
    return None


@hook("effect_subject_allowed")
def heavenly_equipment(ctx: Any, effect: dict, subject: Any) -> bool | None:
    """Mundane disarm/rust/dulling/break effects cannot disable a wielded integrated weapon."""
    if ctx.typed.get("mundane") is not True or subject is None or subject.entity_id == ctx.actor.entity_id:
        return None
    names = effect.get("conditions") or [effect.get("condition")]
    disabled = effect.get("type") in {"drop_item", "break_weapon", "rust_weapon", "dull_weapon"}
    if not disabled and not any(str(n).removeprefix("condition:typed.") in
                                {"disarmed", "weapon_broken", "weapon_rusted", "weapon_dulled"} for n in names):
        return None
    from ..typed_executor import _best_weapon_action

    identity = effect.get("weapon") or _best_weapon_action(ctx.engine, subject)
    row = weapon_row(ctx.engine, subject, ctx.engine.action_catalog.get(identity))
    return False if row and row["heavenly"] else None


@hook("object_damage_modifiers")
def heavenly_objects(engine: Any, actor: Any, obj: Any, packets: Any, source: str) -> dict | None:
    action = engine.action_catalog.get(source)
    typed = (action.parameters or {}).get("typed") or {} if action else {}
    weapon = engine.action_catalog.get(typed.get("object_weapon_source")) if typed.get("object_weapon_source") else action
    row = weapon_row(engine, actor, weapon)
    component = obj.component or {}
    if (not row or not row["heavenly"] or int(component.get("source_cl") or 0) > row["cl"]
            or component.get("artifact") or component.get("immortal") or component.get("void")
            or component.get("physical_force_immune")):
        return None
    if not (obj.unattended or obj.object_kind in {"vehicle", "structure", "terrain"}
            or component.get("structure") or component.get("temporary_barrier") or component.get("formation_anchor")):
        return None
    return {"ignore_threshold": True, "multiplier": 2,
            "ignore_resistance_types": ["BLUDGEONING", "PIERCING", "SLASHING", "FORCE"]}


def _choose(ctx: Any, kinds: list[str], target: Any, index: int = 0) -> str | None:
    action = ctx.engine.action_catalog.get(ctx.typed.get("object_weapon_source")) if ctx.typed.get("object_weapon_source") else ctx.action
    row = weapon_row(ctx.engine, ctx.actor, action)
    if not row or not row["heavenly"] or len(kinds) < 2:
        return None
    from .needle import ask, checkpoint_id
    target_id = getattr(target, "entity_id", None) or getattr(target, "object_id", None) or ctx.actor.entity_id
    name = getattr(target, "display_name", None) or (getattr(target, "component", None) or {}).get("name") or "the target"
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "heavenly_fist_type", target_id, index), ctx.actor,
                 "choice:needle.heavenly_fist_type", list(kinds), labels={k: k.title() + " damage" for k in kinds},
                 preferred=[kinds[0]], target_id=target_id, name="Heavenly Fist",
                 prompt=f"Heavenly Fist: choose the damage type for {ctx.action.display_name} against {name}. No extra cost; only this strike's damage type changes.")
    return picked[0] if picked else kinds[0]


@hook("attack_damage_type_choice")
def heavenly_strike_choice(ctx: Any, attack: dict, target: Any, kinds: list[str], attack_index: int) -> str | None:
    return _choose(ctx, kinds, target, attack_index)


@hook("damage_type_choice")
def heavenly_object_choice(ctx: Any, kinds: list[str], targets: Any) -> str | None:
    if not ctx.typed.get("object_weapon_source"):
        return None
    return _choose(ctx, kinds, ctx.damage_cache.get("_object"))
