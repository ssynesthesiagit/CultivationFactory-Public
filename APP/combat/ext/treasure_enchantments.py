"""Reviewed treasure on-hit rules; native damage and expiry do the delivery."""
from contextlib import ExitStack
from dataclasses import replace
import copy
from hashlib import sha256
from typing import Any

from . import effect, effect_permitted, hook, run_strict

# Hashes bind these policies to the printed authority, including every clause.
# Changed text falls back to the compiler's visible unresolved-rule route.
PRINTED = {
    "dream_piercing_inscription": "15840edef29df3a2e1962fbbf70def40b4e4c10e8a36485c875b52a6d2689d95",
    "flame_vein_inscription": "d3a9cac656c72923e67f39c9bd3d9d85eb429566371081a0bf47da44e3025090",
    "frost_meridian_inscription": "45a52552bda35cffa8c235eabd0b10c3a066d8020794c4df465c8f6e951608e5",
    "spirit_striking_inscription": "26cf99246c580da25a1d3048675387af84194745f6521f32b446a057952fd1fe",
}


@hook("compile_weapon_enchantment")
def compile_enchantment(row: dict[str, Any]) -> list[dict[str, Any]] | None:
    key = str(row.get("enchantment_id") or "").rsplit(".", 1)[-1]
    text = str(row.get("text") or "")
    if key not in PRINTED or sha256(text.encode()).hexdigest() != PRINTED[key]:
        return None
    if key == "flame_vein_inscription":
        return [{"type": "treasure_flame_damage", "expected_damage": 2, "dice": {"count": 1, "sides": 4},
                 "damage_types": ["fire"], "applies_to": "target", "damage_label": row["name"]}]
    if key == "frost_meridian_inscription":
        return [{"type": "treasure_frost_damage", "expected_damage": 2, "dice": {"count": 1, "sides": 4}, "damage_types": ["cold"], "applies_to": "target", "damage_label": row["name"]},
                {"type": "treasure_frost", "applies_to": "target"}]
    if key == "dream_piercing_inscription":
        return [{"type": "treasure_dream_damage", "dice": {"count": 1, "sides": 6},
                 "damage_types": ["psychic"], "applies_to": "target", "damage_label": row["name"]}]
    if key == "spirit_striking_inscription":
        return [{"type": "treasure_spirit_damage", "expected_damage": 4, "dice": {"count": 1, "sides": 8},
                 "damage_types": ["psychic"], "applies_to": "target", "damage_label": row["name"]}]
    return None


@effect("treasure_frost", harmful=True)
def frost(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.target is None:
        return
    from .. import typed_executor
    # All Frost reductions share the printed 15-foot cap. Each physical weapon
    # keeps its own source-turn receipt, including attacks through other variants.
    from .weapon_actions import strike_identity
    item = str(ctx.typed.get("treasure_item_key") or strike_identity(ctx.action))
    source = f"treasure:frost:{ctx.actor.entity_id}:{item}"
    held = [m for m in ctx.target.modifiers.values()
            if m.source_definition_id.startswith("treasure:frost:") and m.target_field == "speed_ft"]
    old = sum(int(m.value) for m in held if m.source_definition_id == source)
    total = sum(int(m.value) for m in held)
    amount = old - min(5, max(0, 15 + total))
    if amount == 0:
        return
    local = replace(ctx, effect_source=source, damage_cache={})
    typed_executor.block_speed(local, {"type": "speed", "flat": amount,
                                      "applies_to": "target", "source_owned": True,
                                      "expires_on": "START_OF_SOURCE_NEXT_TURN"})


def dreams_source(engine: Any, source: str) -> bool:
    action = engine.action_catalog.get(source)
    typed = ((action.parameters or {}).get("typed") or {}) if action else {}
    origin = str(typed.get("source") or typed.get("option_of") or source)
    from ..factory_compiler import TYPED_AUTHORITY
    from ..authority_cache import read_authority
    authority, _ = read_authority(TYPED_AUTHORITY)
    record = authority["mechanics"].get(origin) or {}
    return record.get("sphere_id") == "tianxia.sphere.dreams"


def dream_target(engine: Any, target: Any) -> bool:
    from ..typed_executor import _condition_excluded, rules
    from ..spatial_areas import zone_contains
    states = {"charmed", "frightened", "unconscious"}
    active = [c for c in target.conditions.values()
              if not c.condition_id.startswith("condition:typed.suppressed.")
              and not (c.data or {}).get("suppressed")
              and not _condition_excluded(engine, target, c)]
    aliases = rules().get("condition_id_aliases") or {}
    names = rules().get("condition_aliases") or {}
    named = any(names.get(aliases.get(c.condition_id, c.condition_id.rsplit(".", 1)[-1]),
                          aliases.get(c.condition_id, c.condition_id.rsplit(".", 1)[-1])) in states
                for c in active)
    affected = any(dreams_source(engine, c.source_definition_id) for c in active) or any(
        not m.target_field.startswith("suppressed:") and dreams_source(engine, m.source_definition_id)
        for m in target.modifiers.values())
    affected = affected or any(z.active and dreams_source(engine, z.source_definition_id)
                              and zone_contains(engine, target, z) for z in engine.state.zones.values())
    return named or affected


BONUS_TYPES = {"treasure_dream_damage", "treasure_spirit_damage", "treasure_flame_damage", "treasure_frost_damage"}


def bonus_receipt(ctx: Any, row: dict[str, Any]) -> str | None:
    provenance = ctx.attack_damage_context
    return ("treasure_delivered:" + provenance.roll_id + ":" + row["type"]) if provenance is not None else None


def deliver_bonus(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.target is None:
        return
    from ..typed_executor import block_damage
    kind = row["type"]
    hit_state = ctx.damage_cache.get("_treasure_hit_dream_eligibility", {})
    if kind == "treasure_dream_damage":
        eligible = hit_state.get(row.get("damage_label"))
        if eligible is None:
            eligible = dream_target(ctx.engine, ctx.target)
        if not eligible:
            return
    if kind == "treasure_flame_damage":
        item = str(row.get("item") or ctx.typed.get("treasure_item_key") or ctx.typed.get("source"))
        if flame_is_off(ctx.engine, item):
            return
    damage = {**row, "type": "damage"}
    if kind == "treasure_spirit_damage":
        from ..creature_types import types_for
        kinds = {label.casefold() for label in types_for(ctx.target)}
        count = 2 if kinds & {"aberration", "celestial", "elemental", "fey", "fiend", "undead"} else 1
        damage["dice"] = {"count": count, "sides": 8}
    block_damage(replace(ctx, continue_after_defeat=True), damage)


@hook("damage_packet_selection")
def treasure_before_damage(ctx: Any, target: Any, packet_kinds: tuple[str, ...]) -> None:
    rows = [row for row in (ctx.attack_effect or {}).get("on_hit", []) if row.get("type") in BONUS_TYPES]
    if not rows or ctx.attack_damage_context is None:
        return
    # Confirmed hit, before any weapon damage can end a Dreams effect, ask a
    # damage save or defeat the target. Native resistance and criticals apply.
    dream_eligibility = {row.get("damage_label"): dream_target(ctx.engine, target)
                         for row in rows if row.get("type") == "treasure_dream_damage"}
    # Printed Dream-Piercing damage lands before any save caused by taking damage,
    # so it is delivered before the other attached bonuses (stable order otherwise).
    rows.sort(key=lambda row: row.get("type") != "treasure_dream_damage")
    for row in rows:
        key = bonus_receipt(ctx, row)
        if ctx.damage_cache.get(key):
            continue
        local = replace(ctx, damage_cache={"_treasure_hit_dream_eligibility": dream_eligibility},
                        defer_damage_notifications=True, continue_after_defeat=True)
        # An attached packet is delivered before the primary packet and outside the
        # ordinary on-hit pass, so it asks the general effect contract itself: the
        # subscribers see the original enchantment row and its recipient, never the
        # converted damage row. A denied bonus is spent for this hit rather than
        # deferred to the ordinary pass, which would deliver what was just denied.
        ctx.damage_cache[key] = True
        if not effect_permitted(local, row, [target]):
            continue
        # Scopes published for the original effect enclose this delivery exactly as
        # they enclose an ordinary effect block, including its nested effects.
        with ExitStack() as scopes:
            for scope in run_strict("effect_resolution_scope", local, row):
                scopes.enter_context(scope)
            deliver_bonus(local, row)


@effect("treasure_dream_damage", harmful=True)
@effect("treasure_spirit_damage", harmful=True)
@effect("treasure_flame_damage", harmful=True)
@effect("treasure_frost_damage", harmful=True)
def treasure_bonus(ctx: Any, row: dict[str, Any]) -> None:
    key = bonus_receipt(ctx, row)
    if key is not None and ctx.damage_cache.get(key):
        return
    deliver_bonus(ctx, row)


@hook("compile_weapon_traits")
def treasure_item_key(info: dict[str, Any]) -> dict[str, Any] | None:
    if not info["weapon"].get("enchantments"):
        return None
    effects = copy.deepcopy(info["typed"]["effects"])
    # Borrowed weapon actions bind to the original physical weapon, not a new
    # holder's catalog ID. Alternatives retain the original base before '#'.
    item = str(info["weapon"].get("held_from") or info["action_id"]).split("#", 1)[0]
    for attack in effects:
        for row in attack.get("on_hit", []):
            if row.get("type") == "treasure_flame_damage":
                row["item"] = item
    return {"treasure_item_key": info["weapon"]["inventory_key"], "effects": effects}


def flame_off_id(item: str) -> str:
    return "condition:typed.treasure_flame_off." + sha256(item.encode()).hexdigest()[:20]


def flame_is_off(engine: Any, item: str) -> bool:
    cid = flame_off_id(item)
    return any(c.condition_id == cid for owner in engine.state.actors.values()
               for c in owner.conditions.values())


@hook("compile_actions")
def flame_actions(info: dict[str, Any]) -> list[Any]:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    out = []
    for base in info["actions"]:
        typed = (base.parameters or {}).get("typed") or {}
        if "#" in base.source_definition_id or not typed.get("weapon"):
            continue
        if not any(e.get("type") == "treasure_flame_damage" for attack in typed.get("effects", [])
                   for e in attack.get("on_hit", [])):
            continue
        item = next(e["item"] for attack in typed["effects"] for e in attack.get("on_hit", [])
                    if e.get("type") == "treasure_flame_damage")
        name = base.display_name.removesuffix(" attack")
        for lit in (False, True):
            out.append(ActionDefinition(
                source_definition_id=base.source_definition_id + ".flame." + str(lit).lower(),
                display_name=("Ignite " if lit else "Extinguish ") + name,
                owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION,
                resolution_kind="TYPED", target_kind="SELF",
                parameters={"player_only": not lit, "expected_damage": 0,
                    "treasure_flame_toggle": {"weapon": base.source_definition_id, "item": item, "lit": lit},
                    "typed": {"source": "tianxia.treasure.enchantment.flame_vein_inscription",
                        "effects": [{"type": "treasure_flame_toggle", "item": item,
                                     "weapon_name": name, "lit": lit}],
                        "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}}))
    return out


@hook("candidate_allowed")
def flame_toggle_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    toggle = (getattr(action, "parameters", None) or {}).get("treasure_flame_toggle")
    if toggle is None:
        return None
    from .weapon_hits import available_weapons
    if toggle["weapon"] not in available_weapons(engine, actor):
        return False
    off = flame_is_off(engine, toggle["item"])
    return off == bool(toggle["lit"])


@effect("treasure_flame_toggle", harmful=False)
def flame_toggle(ctx: Any, row: dict[str, Any]) -> None:
    cid = flame_off_id(str(row["item"]))
    if row["lit"]:
        for owner in ctx.engine.state.actors.values():
            ctx.engine._remove_condition(owner, cid, ctx.source)
    else:
        name = str(row.get("weapon_name") or "this weapon")
        reading = (f"{name}'s Flame-Vein is extinguished, so it deals no extra 1d4 fire damage. "
                   "Use a Bonus Action to ignite this weapon; this lasts until you ignite it.")
        ctx.engine._apply_condition(ctx.actor, cid, ctx.source, ctx.actor.entity_id,
                                   expires_on="UNTIL_REMOVED", data={"label": reading, "reading": reading})
    ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=ctx.actor.entity_id,
        payload={"log": (f"You ignite {row.get('weapon_name') or 'this weapon'}; its extra 1d4 fire damage is restored."
                          if row["lit"] else
                          f"You extinguish {row.get('weapon_name') or 'this weapon'}; it deals no extra 1d4 fire damage until you use a Bonus Action to ignite it.")})
