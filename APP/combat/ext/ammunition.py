"""Track ordinary weapon ammunition through compiled equipment and attack hooks.

New bundles record ammunition stock in their carrying list. Older bundles with
no such list keep their historical unlimited-ammunition behavior. Spent pieces
are integer turn flags so a commit, reload, and replay retain the same count.
"""
from __future__ import annotations

import re
from typing import Any

from . import hook

_AMMO = {
    "arrow": ("tianxia.mortal.gear.arrows_20", "arrow"),
    "bolt": ("tianxia.mortal.gear.bolts_20", "bolt"),
    "bullet": ("tianxia.mortal.gear.bullets_sling_20", "sling bullet"),
    "needle": ("tianxia.mortal.gear.needles_50", "needle"),
}
_PIECES_PER_UNIT = {
    "tianxia.mortal.gear.arrows_20": 20,
    "tianxia.mortal.gear.bolts_20": 20,
    "tianxia.mortal.gear.bullets_sling_20": 20,
    "tianxia.mortal.gear.needles_50": 50,
}
_SPENT_PREFIX = "_round_ammunition_spent:"
_ZERO_STACK_SEPARATOR = "\x1f"
_CEASELESS = "TAL_BARRAGE_CEASELESS_AMMUNITION"


def _profile(action: Any) -> dict[str, Any]:
    parameters = getattr(action, "parameters", None) or {}
    return parameters.get("typed") or {}


def _ammunition_record(typed: dict[str, Any], owned_ids=()) -> dict[str, Any] | None:
    """Return the matching mundane ammunition identity for a compiled weapon."""
    source = str(typed.get("source") or "")
    if not source or not (typed.get("weapon") or {}).get("properties"):
        return None
    from factory_authoring.starting_kits import _authorities

    item = _authorities()[1].get(source) or {}
    properties = str(item.get("properties") or "")
    if not re.search(r"\bAmmunition\b", properties, re.I):
        return None
    explicit = re.search(r"Ammunition\s*\([^)]*;\s*(Arrow|Bolt|Needle)\s*\)", properties, re.I)
    kind = explicit.group(1).lower() if explicit else ""
    if not kind:
        family = str(item.get("weapon_family") or "").lower()
        name = str(item.get("name") or source).lower()
        if "pellet" in family or "sling" in family or "sling" in name:
            kind = "bullet"
        elif "crossbow" in family or "crossbow" in name:
            kind = "bolt"
        elif "bow" in family or "bow" in name:
            kind = "arrow"
    if kind not in _AMMO:
        return None
    item_id, label = _AMMO[kind]
    return {"item_id": item_id, "label": label, "ceaseless": _CEASELESS in set(owned_ids or ())}


def _explicitly_listed(owner_sheet: dict[str, Any], item_id: str) -> bool:
    """Whether the character explicitly records a quantity for this ammunition."""
    for equipment in owner_sheet.get("equipment") or ():
        kit = equipment.get("starting_kit") if isinstance(equipment, dict) else None
        for row in (kit or {}).get("items") or ():
            if (isinstance(row, dict) and str(row.get("item_id") or "") == item_id
                    and type(row.get("quantity")) is int and row["quantity"] >= 0):
                return True
    return False


def _explicit_zero(owner_sheet: dict[str, Any], item_id: str) -> bool:
    """Detect a recorded zero even though carrying normalization omits it."""
    quantities = []
    for equipment in owner_sheet.get("equipment") or ():
        kit = equipment.get("starting_kit") if isinstance(equipment, dict) else None
        for row in (kit or {}).get("items") or ():
            if (isinstance(row, dict) and str(row.get("item_id") or "") == item_id
                    and type(row.get("quantity")) is int and row["quantity"] >= 0):
                quantities.append(row["quantity"])
    return bool(quantities) and not any(quantities)


def _zero_stack_keys(owner_sheet: dict[str, Any], item_id: str) -> list[str]:
    """Mirror carrying's stable item keys for explicitly empty rows the compiler normalizes to one."""
    keys: list[str] = []
    seen: dict[str, int] = {}
    for equipment in owner_sheet.get("equipment") or ():
        kit = equipment.get("starting_kit") if isinstance(equipment, dict) else None
        for row in (kit or {}).get("items") or ():
            if not isinstance(row, dict):
                continue
            current = str(row.get("item_id") or row.get("name") or "item")
            seen[current] = seen.get(current, 0) + 1
            key = row.get("combat_item_key") or (current if seen[current] == 1 else f"{current}.{seen[current]}")
            if current == item_id and type(row.get("quantity")) is int and row["quantity"] == 0:
                keys.append(str(key))
    return keys


@hook("compile_action")
def compile_ammunition(action: Any, info: dict[str, Any]) -> Any:
    """Attach inventory-backed ammunition metadata to newly compiled weapon actions."""
    typed = _profile(action)
    if "ammunition" in typed or not (typed.get("weapon") or {}).get("properties"):
        return None
    ammo = _ammunition_record(typed, info.get("owned_ids"))
    if ammo is None:
        return None
    ammo["tracked"] = _explicitly_listed(info.get("owner_sheet") or {}, ammo["item_id"])
    ammo["explicit_zero"] = _explicit_zero(info.get("owner_sheet") or {}, ammo["item_id"])
    ammo["zero_stack_keys"] = _ZERO_STACK_SEPARATOR.join(
        _zero_stack_keys(info.get("owner_sheet") or {}, ammo["item_id"]))
    from copy import deepcopy

    parameters = deepcopy(action.parameters)
    parameters["typed"]["ammunition"] = ammo
    return action.model_copy(update={"parameters": parameters})


@hook("button_description")
def ammunition_description(row: dict[str, Any]) -> str | None:
    """Append tracked-stock guidance to the shared weapon help; unlisted stock is unlimited."""
    typed = (row.get("parameters") or {}).get("typed") or {}
    ammo = typed.get("ammunition")
    if not ammo or not (ammo.get("tracked") or ammo.get("explicit_zero")):
        return None
    from .action_help import control_help

    description = control_help(row)
    if not description:
        return None
    label = ammo["label"]
    plural = label + ("s" if not label.endswith("s") else "")
    if ammo.get("explicit_zero"):
        return f"{description} No {plural} are carried, so this attack is unavailable."
    description += f" Each attack uses one {label}; if none are carried, this attack is unavailable."
    if ammo.get("ceaseless"):
        description += f" With Ceaseless Ammunition and at least 10 {plural}, you can fire without reducing the tracked amount during this fight."
    return description


def _stock(engine: Any, actor: Any, ammo: dict[str, Any]) -> int | None:
    """Pieces remaining, or None when the saved bundle has no stock record."""
    if ammo.get("explicit_zero"):
        return 0
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or ()
                   if row.get("actor_id") == actor.entity_id), None)
    carrying = (bundle or {}).get("carrying")
    if not isinstance(carrying, dict) or not isinstance(carrying.get("items"), list):
        return 0 if ammo.get("tracked") else None
    pieces = 0
    found_stock = False
    wanted = str(ammo.get("item_id") or "")
    for row in carrying["items"]:
        if str(row.get("item_id") or "") != wanted:
            continue
        stack_key = str(row.get("key") or "")
        if stack_key in (ammo.get("zero_stack_keys") or "").split(_ZERO_STACK_SEPARATOR):
            continue
        quantity = row.get("quantity")
        if type(quantity) is not int or quantity < 0:
            continue
        from .. import carry

        if not carry.holds(engine, actor, str(row.get("key") or "")):
            continue
        found_stock = True
        spent = actor.turn_flags.get(_SPENT_PREFIX + wanted + ":" + stack_key, 0)
        if type(spent) is not int or spent < 0:
            spent = 0
        pieces += max(0, quantity * _PIECES_PER_UNIT.get(wanted, 1) - spent)
    if not found_stock and not ammo.get("tracked"):
        return None  # Unlisted ammunition remains unlimited in compiled and legacy bundles.
    return pieces


def _action_ammo(action: Any) -> dict[str, Any] | None:
    return _profile(action).get("ammunition")


def _available_stack(engine: Any, actor: Any, ammo: dict[str, Any]) -> dict[str, Any] | None:
    """Choose the first held stack with unspent pieces, in compiled inventory order."""
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or ()
                   if row.get("actor_id") == actor.entity_id), None)
    wanted = str(ammo.get("item_id") or "")
    from .. import carry

    for row in ((bundle or {}).get("carrying") or {}).get("items", ()):
        if (str(row.get("item_id") or "") == wanted and carry.holds(engine, actor, str(row.get("key") or ""))
                and _stack_remaining(actor, ammo, row) > 0):
            return row
    return None


def _ceaseless(engine: Any, actor: Any, ammo: dict[str, Any]) -> bool:
    """Apply the owned ten-piece exception to ordinary, nonmagical ammunition."""
    if not ammo.get("ceaseless"):
        return False
    stock = _stock(engine, actor, ammo)
    return stock is not None and stock >= 10


def _delivery_ammo(engine: Any, action: Any, typed: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Resolve ammunition from an action itself or the weapon delivering its strike."""
    typed = typed or (_profile(action) if action is not None else {})
    ammo = typed.get("ammunition") or (_action_ammo(action) if action is not None else None)
    if ammo:
        return ammo
    source = typed.get("delivered_by") or typed.get("weapon_source_id")
    catalog = getattr(engine, "action_catalog", {})
    delivered = catalog.get(str(source or ""))
    if delivered is None and source:
        delivered = catalog.get(str(source).split("#", 1)[0])
    return _action_ammo(delivered) if delivered is not None else None


def _context_ammo(ctx: Any) -> dict[str, Any] | None:
    return _delivery_ammo(ctx.engine, ctx.action, ctx.typed)


@hook("candidate_allowed")
def ammunition_choice(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Hide compiled ammunition attacks when a new-format character has no pieces."""
    ammo = _delivery_ammo(engine, action) if action is not None else None
    remaining = _stock(engine, actor, ammo) if ammo else None
    if ammo and remaining == 0 and not _ceaseless(engine, actor, ammo):
        return False
    return None


@hook("attack_allowed")
def ammunition_strike(ctx: Any, target: Any, effect: dict[str, Any]) -> bool | None:
    """Spend availability one strike at a time, including later Extra Attack strikes."""
    ammo = _context_ammo(ctx)
    if not ammo:
        return None
    if _ceaseless(ctx.engine, ctx.actor, ammo):
        return None
    remaining = _stock(ctx.engine, ctx.actor, ammo)
    if remaining is not None and remaining <= 0:
        ctx.rider(f"No {ammo['label']}s are carried, so {ctx.action.display_name} does not fire.")
        return False
    return None


@hook("event", nested=True)
def spend_on_strike(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Count one piece on the first actual attack roll in each typed strike scope."""
    if event_type != "ATTACK_ROLLED":
        return
    from .attack_scope import current

    frame = current(engine)
    if frame is None or frame.get("ammunition_spent"):
        return
    ctx = frame["context"]
    ammo = _context_ammo(ctx)
    if not ammo or _stock(engine, ctx.actor, ammo) is None or _ceaseless(engine, ctx.actor, ammo):
        return
    payload = kwargs.get("payload") or {}
    if (kwargs.get("actor_id") != frame["actor_id"]
            or tuple(kwargs.get("target_ids") or ()) != (frame["target_id"],)
            or str(payload.get("reason") or "").rsplit(":", 1)[0] != "ATTACK:" + frame["source"]):
        return
    stack = _available_stack(engine, ctx.actor, ammo)
    if stack is None:
        return
    key = _SPENT_PREFIX + str(ammo["item_id"]) + ":" + str(stack.get("key") or "")
    ctx.actor.turn_flags[key] = int(ctx.actor.turn_flags.get(key, 0)) + 1
    frame["ammunition_spent"] = True


def _stack_remaining(actor: Any, ammo: dict[str, Any], row: dict[str, Any]) -> int:
    key = str(row.get("key") or "")
    if key in (ammo.get("zero_stack_keys") or "").split(_ZERO_STACK_SEPARATOR):
        return 0
    spent = actor.turn_flags.get(_SPENT_PREFIX + str(ammo["item_id"]) + ":" + key, 0)
    if type(spent) is not int or spent < 0:
        spent = 0
    return max(0, int(row.get("quantity") or 0) * _PIECES_PER_UNIT.get(str(ammo["item_id"]), 1) - spent)
