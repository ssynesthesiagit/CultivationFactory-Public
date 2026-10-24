"""Track ordinary weapon ammunition through compiled equipment and attack hooks.

New bundles record ammunition stock in their carrying list. Older bundles with
no such list keep their historical unlimited-ammunition behavior. Spent pieces
are integer turn flags so a commit, reload, and replay retain the same count.
The shared ammunition_choice query serves ordinary candidate gating and Sky-Net
Suppression's granted-attack weapon menu, using the same tracked-stock policy.
The shared spend_unrolled_projectile mutation serves barrage_second_pass's
automatic misses, reusing these counters and Ceaseless policy without a roll.

``spend_projectiles`` (used by this plug-in and, through the public helpers
``projectile_requirement`` / ``projectiles_available``, by any ability whose
printed text says it uses up ammunition or thrown weapons as a cost rather than
one piece per attack) resolves one printed quantity of pieces for the whole
ability: the ability is unavailable while the fighter's record shows too few,
and using it spends them. Ordinary ammunition comes first, then held thrown
weapons, because the printed costs read "five pieces of ammunition or five
thrown weapons". A fighter whose bundle records no ammunition stock and no
thrown weapon keeps the historical unlimited-ammunition reading of this plug-in;
the printed quantity is then quoted on the ability's own button instead
(``button_description``) so the player still sees what the ability consumes.
"""
from __future__ import annotations

import re
from typing import Any

from . import effect, hook

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
_THROWN_SPENT_PREFIX = "_round_thrown_spent:"
_ZERO_STACK_SEPARATOR = "\x1f"
_CEASELESS = "TAL_BARRAGE_CEASELESS_AMMUNITION"
_PROJECTILES = "spend_projectiles"
_THROWN = re.compile(r"\bThrown\b")


def _profile(action: Any) -> dict[str, Any]:
    parameters = getattr(action, "parameters", None) or {}
    return parameters.get("typed") or {}


def _ammunition_record(typed: dict[str, Any], owned_ids=()) -> dict[str, Any] | None:
    """Return the matching mundane ammunition identity for a compiled weapon."""
    source = str(typed.get("source") or "")
    if not source or not (typed.get("weapon") or {}).get("properties"):
        return None
    from factory_authoring.starting_kits import item_definition

    item = item_definition(source)
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
    """Shared pure stock gate for ordinary menus and granted weapon choices.

    ``candidate`` may be None: availability depends only on the actor and weapon.
    False means tracked stock is empty; None preserves the existing stock policy.
    """
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
    if frame is None:
        from ..attack_delivery import native_strike
        frame = native_strike(engine)
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
    # Native material-unit identity, available to interceptors in this strike
    # only. No subscriber means no extra event, inventory or persisted state.
    frame["fired_projectile"] = {
        "projectile_id": f"{ctx.actor.entity_id}:{stack.get('key')}:{ctx.actor.turn_flags[key]}",
        "item_id": str(ammo["item_id"]), "item_name": str(ammo["label"]),
        "stack_key": str(stack.get("key") or ""), "shooter": ctx.actor.entity_id,
        "source": frame["source"], "target": frame["target_id"], "quantity": 1, "unit": "piece",
        "holdable": 1}


def _stack_remaining(actor: Any, ammo: dict[str, Any], row: dict[str, Any]) -> int:
    key = str(row.get("key") or "")
    if key in (ammo.get("zero_stack_keys") or "").split(_ZERO_STACK_SEPARATOR):
        return 0
    spent = actor.turn_flags.get(_SPENT_PREFIX + str(ammo["item_id"]) + ":" + key, 0)
    if type(spent) is not int or spent < 0:
        spent = 0
    return max(0, int(row.get("quantity") or 0) * _PIECES_PER_UNIT.get(str(ammo["item_id"]), 1) - spent)


# ------------------------------------------------------------------------------------------------ printed "spend N pieces"
# "Spend five pieces of ammunition or five thrown weapons" (Needle-Rain Burst), "Spend one ammunition unit or thrown
# weapon per 10 feet of line, minimum 10 projectiles" (Hundred-Arrow Passage), "Spend at least 20 ordinary projectiles"
# (Ten-Thousand Projectile Rain), "Spend 10 pieces of ammunition" (Stair Shot). One whole-ability quantity, not the
# one piece per attack strike above: these abilities fire a volley and print what the volley consumes.
#
# The printed words are "ammunition or thrown weapons", so the pools are everything the fighter carries: the ammunition
# kind this ability is delivered by (when it is delivered by one), then any other ammunition kind carried, then thrown
# weapons. A fighter whose bundle records no ammunition and carries no thrown weapon keeps this plug-in's historical
# unlimited reading, so no existing fighter loses an ability they used to have.
def _carrying(engine: Any, actor: Any) -> list[dict[str, Any]]:
    """The fighter's carried rows that they still hold, in the order the sheet lists them."""
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or ()
                   if row.get("actor_id") == actor.entity_id), None)
    items = ((bundle or {}).get("carrying") or {}).get("items")
    if not isinstance(items, list):
        return []
    from .. import carry

    return [row for row in items if isinstance(row, dict)
            and carry.holds(engine, actor, str(row.get("key") or ""))]


def _thrown_rows(engine: Any, actor: Any, *, recorded: bool = False) -> list[dict[str, Any]]:
    """Carried rows that are thrown weapons ("Thrown (Range 30/120)"); one thrown weapon is one printed piece."""
    from factory_authoring.starting_kits import item_definition
    from .. import carry
    items = (carry.carrying_of(engine, actor.entity_id) or {}).get("items") or []
    return [row for row in (items if recorded else _carrying(engine, actor))
            if isinstance(row, dict)
            and _THROWN.search(str(item_definition(str(row.get("item_id") or "")).get("properties") or ""))]


def _thrown_remaining(actor: Any, row: dict[str, Any]) -> int:
    key = _THROWN_SPENT_PREFIX + str(row.get("key") or "")
    spent = actor.turn_flags.get(key, 0)
    if type(spent) is not int or spent < 0:
        spent = 0
    return max(0, int(row.get("quantity") or 0) - spent)


@hook("carried_item_remaining")
def thrown_remaining(engine: Any, actor: Any, item: dict[str, Any]) -> int | None:
    """Spent thrown weapons leave possession and all weapon modes through carry's shared quantity seam."""
    if not (getattr(actor, "turn_flags", None) or {}).get(_THROWN_SPENT_PREFIX + str(item.get("key") or "")):
        return None
    return _thrown_remaining(actor, item)


def thrown_pieces(engine: Any, actor: Any) -> tuple[int, str]:
    """(carried thrown weapons, a name for them), spent ones already excluded."""
    rows = _thrown_rows(engine, actor)
    remaining = sum(_thrown_remaining(actor, row) for row in rows)
    label = str((rows[0] or {}).get("name") or "thrown weapon") if rows else "thrown weapon"
    return remaining, label


def _ordinal(count: int, label: str) -> str:
    plural = label + ("es" if label.endswith(("s", "x", "ch", "sh")) else "s")
    return f"{count} {label if count == 1 else plural}"


def projectile_requirement(typed: dict[str, Any]) -> dict[str, Any] | None:
    """The printed whole-ability projectile cost on ``typed``, or None when the ability prints none.

    ``pieces`` is a flat count, ``per_ft`` a count per that many feet of the printed shape with ``minimum`` as its floor
    ("one per 10 feet of line, minimum 10"), and ``targets`` reads as one piece per creature the ability reaches
    ("one projectile or thrown weapon per target"). Every number is an integer, so the charge survives a commit and a
    reload like the rest of this plug-in's counts.
    """
    for row in typed.get("effects") or []:
        if isinstance(row, dict) and row.get("type") == _PROJECTILES:
            return row
    return None


def _required_pieces(row: dict[str, Any], targets: int) -> int:
    per_ft = int(row.get("per_ft") or 0)
    length = int(row.get("length_ft") or 0)
    needed = int(row.get("pieces") or 0)
    if per_ft > 0 and length > 0:
        needed = max(needed, -(-length // per_ft))  # whole pieces, rounded up
    needed = max(needed, int(row.get("minimum") or 0))
    if row.get("targets"):
        needed = max(needed, int(targets))
    return max(0, needed)


def _area_targets(ctx: Any, row: dict[str, Any]) -> int:
    """How many creatures a ``targets`` cost reaches: those standing in the ability's own printed area."""
    engine, actor = ctx.engine, ctx.actor
    aim = ctx.target
    if aim is None or not getattr(aim, "position", None):
        return 0
    from ..typed_executor import area_cells

    cells = area_cells(engine, actor.position, aim.position,
                       {"shape": str(row.get("shape") or "sphere"), "size_ft": int(row.get("area_ft") or 0)})
    return sum(1 for other in engine.state.actors.values()
               if other.active and other.team_id != actor.team_id and other.position in cells)


def _compiled_record(engine: Any, actor: Any, item_id: str) -> dict[str, Any] | None:
    """The ammunition record this plug-in already compiled onto one of the fighter's own weapon attacks.

    It carries the sheet-level facts a carrying list loses (a recorded zero quiver is normalised to one row), so the
    printed cost reads the same record the one-piece-per-strike rule does.
    """
    for action in (getattr(engine, "action_catalog", {}) or {}).values():
        if getattr(action, "owner_id", None) != actor.entity_id:
            continue
        record = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("ammunition") or {}
        if str(record.get("item_id") or "") == item_id:
            return record
    return None


def _pools(engine: Any, actor: Any, preferred: dict[str, Any] | None,
           requirement: dict[str, Any] | None = None) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """[(ammunition record, its held stacks)] to spend from: the delivered kind first, then any other carried kind.

    A kind carried in the sheet is tracked by definition, so a recorded zero counts as a recorded zero and the printed
    cost cannot be paid from it.
    """
    carried = _carrying(engine, actor)
    from .. import carry
    recorded = (carry.carrying_of(engine, actor.entity_id) or {}).get("items") or []
    kinds: dict[str, dict[str, Any]] = {}
    if preferred is not None:
        kinds[str(preferred.get("item_id") or "")] = preferred
    for item_id, label in _AMMO.values():
        rows = [row for row in recorded if isinstance(row, dict) and str(row.get("item_id") or "") == item_id]
        if not rows or item_id in kinds:
            continue
        kinds[item_id] = {**(_compiled_record(engine, actor, item_id) or {
            "item_id": item_id, "label": label, "explicit_zero": False, "zero_stack_keys": ""}), "tracked": True}
    eligible = (requirement or {}).get("ammunition_ids")
    return [(record, [row for row in carried if str(row.get("item_id") or "") == str(record.get("item_id") or "")])
            for record in kinds.values() if eligible is None or record["item_id"] in eligible]


def _ceaseless_kind(engine: Any, actor: Any, record: dict[str, Any], pieces: int) -> bool:
    """Ceaseless Ammunition: "fire as many pieces of that ammunition as required without reducing the tracked amount
    during combat", once the fighter carries at least ten of one nonmagical ammunition type. The owned talent is read
    from the fighter's own compiled weapon actions, where this plug-in records it."""
    if pieces < 10:
        return False
    wanted = str(record.get("item_id") or "")
    for action in (getattr(engine, "action_catalog", {}) or {}).values():
        if getattr(action, "owner_id", None) != actor.entity_id:
            continue
        ammo = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("ammunition") or {}
        if ammo.get("ceaseless") and str(ammo.get("item_id") or "") == wanted:
            return True
    return False


def projectiles_available(engine: Any, actor: Any, action: Any) -> tuple[int, str] | None:
    """(pieces the fighter can spend, what they are called), or None when no stock was recorded.

    A recorded zero counts as a record: (0, "arrows") means the printed cost cannot be paid. None means the bundle
    records no ammunition at all and carries no thrown weapon, which keeps this plug-in's historical unlimited reading
    so no existing fighter loses an ability they used to have.
    """
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    requirement = projectile_requirement(typed)
    if requirement is None:
        return None
    # A present but exhausted/ineligible stock record is never the legacy "unrecorded" case.
    all_pools = _pools(engine, actor, _delivery_ammo(engine, action, typed))
    pieces, label = 0, ""
    recorded = bool(_thrown_rows(engine, actor, recorded=True)) or any(
        record.get("tracked") or record.get("explicit_zero") or rows for record, rows in all_pools)
    for record, rows in _pools(engine, actor, _delivery_ammo(engine, action, typed), requirement):
        stock = _stock(engine, actor, record)
        if stock is None and not record.get("tracked"):
            continue
        if stock is None:
            stock = sum(int(row.get("quantity") or 0) * _PIECES_PER_UNIT.get(str(record["item_id"]), 1) for row in rows)
        recorded = True
        pieces += max(0, stock)
        name = record["label"] + ("s" if stock != 1 else "")
        label = f"{label} or {name}" if label else name
    if requirement.get("allow_thrown", True):
        thrown, thrown_label = thrown_pieces(engine, actor)
        pieces += thrown
        if thrown:
            label = f"{label} or {thrown_label}" if label else thrown_label
    return (pieces, label) if recorded else None


@hook("candidate_allowed")
def projectiles_payable(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """An ability that prints its own projectile cost is unavailable while the fighter cannot pay it."""
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    row = projectile_requirement(typed)
    if row is None:
        return None
    for record, _rows in _pools(engine, actor, _delivery_ammo(engine, action, typed), row):
        stock = _stock(engine, actor, record)
        if stock and _ceaseless_kind(engine, actor, record, stock):
            return None  # Ceaseless Ammunition satisfies an ordinary nonmagical ammunition requirement.
    available = projectiles_available(engine, actor, action)
    if available is None:
        return None  # nothing carried to spend: unchanged, unlimited-ammunition reading.
    # The printed quantity is the printed quantity: a fighter who cannot pay it does not get the ability. "Spend at
    # least 20 ordinary projectiles" (Ten-Thousand Projectile Rain) with two darts is not a reduced volley, it is a
    # different ability, and the fight must not resolve one and charge the other. A fighter with no stock recorded at
    # all keeps the historical unlimited reading above, so no existing character loses an ability they used to have.
    return available[0] >= _required_pieces(row, 1 if row.get("targets") else 0)


@hook("button_description")
def projectile_description(row: dict[str, Any]) -> str | None:
    """State the printed projectile cost on the ability's own button, in the words the player needs."""
    typed = (row.get("parameters") or {}).get("typed") or {}
    spent = projectile_requirement(typed)
    if spent is None:
        return None
    from .action_help import control_help

    description = control_help(row) or ""
    label = spent.get("stock_label") or "ammunition or thrown weapons"
    sentence = (f"It uses up {_ordinal(_required_pieces(spent, 1), 'projectile')} "
                f"({label}), taken from what you carry.")
    return f"{description} {sentence}" if description else sentence


@effect(_PROJECTILES)
def spend_projectiles(ctx: Any, row: dict[str, Any]) -> None:
    """Charge the printed quantity of pieces this ability consumes: its ammunition kinds first, then thrown weapons.

    Recheck the complete payment at resolution, before consuming any stock. If another effect exhausted it since the
    menu was built, effect_allowed suppresses the rest of this activation rather than firing a partially paid volley.
    """
    engine, actor = ctx.engine, ctx.actor
    if not actor.active:
        return
    pools = _pools(engine, actor, _delivery_ammo(engine, ctx.action, ctx.typed), row)
    for record, _rows in pools:
        stock = _stock(engine, actor, record)
        if stock and _ceaseless_kind(engine, actor, record, stock):
            ctx.damage_cache["projectiles_paid"] = True
            return  # Ceaseless Ammunition: the tracked amount does not reduce during combat.
    needed = _required_pieces(row, _area_targets(ctx, row) if row.get("targets") else 1)
    if needed <= 0:
        return
    available = projectiles_available(engine, actor, ctx.action)
    if available is not None and available[0] < needed:
        ctx.damage_cache["projectiles_unpaid"] = True
        ctx.rider(f"{ctx.action.display_name} needs {_ordinal(needed, 'projectile')}; you cannot pay its full cost, "
                  "so it does not happen and no projectiles are spent.")
        return
    ctx.damage_cache["projectiles_paid"] = True
    spent = 0
    for record, rows in pools:
        spent += _take_ammunition(actor, record, rows, needed - spent)
        if spent >= needed:
            break
    if row.get("allow_thrown", True):
        spent += _take_thrown(actor, _thrown_rows(engine, actor), needed - spent)
    if spent <= 0:
        return  # nothing carried to spend: the historical unlimited reading, and the button quotes the cost.
    short = needed - spent
    engine._append_event("PASSIVE_TRIGGERED", _PROJECTILES, actor_id=actor.entity_id,
                         target_ids=tuple(t.entity_id for t in ctx.targets or () if t is not None),
                         payload={"trigger": str(row.get("evidence") or ""), "pieces": spent, "needed": needed})
    ctx.rider(f"{ctx.action.display_name} used {_ordinal(spent, 'projectile')}"
              + (f", {short} short of the {_ordinal(needed, 'projectile')} it needs." if short > 0 else "."))
    if short > 0:
        ctx.rider(f"You did not have {_ordinal(short, 'projectile')} more, so those shots did not happen.")


@hook("effect_allowed")
def paid_projectile_effect(ctx: Any, row: dict[str, Any]) -> bool | None:
    """An explicitly unpaid cost suppresses only its own activation's subsequent effects."""
    if projectile_requirement(ctx.typed) is not None and ctx.damage_cache.get("projectiles_unpaid"):
        return False
    return None


def _take_ammunition(actor: Any, record: dict[str, Any], rows: list[dict[str, Any]], needed: int) -> int:
    """Spend up to ``needed`` pieces from one ammunition kind's held stacks; how many it could."""
    if needed <= 0:
        return 0
    wanted = str(record.get("item_id") or "")
    spent = 0
    for row in rows:
        key = _SPENT_PREFIX + wanted + ":" + str(row.get("key") or "")
        take = min(_stack_remaining(actor, record, row), needed - spent)
        if take <= 0:
            continue
        actor.turn_flags[key] = int(actor.turn_flags.get(key, 0)) + take
        spent += take
        if spent >= needed:
            break
    return spent


def _take_thrown(actor: Any, rows: list[dict[str, Any]], needed: int) -> int:
    if needed <= 0:
        return 0
    spent = 0
    for row in rows:
        key = _THROWN_SPENT_PREFIX + str(row.get("key") or "")
        take = min(_thrown_remaining(actor, row), needed - spent)
        if take <= 0:
            continue
        actor.turn_flags[key] = int(actor.turn_flags.get(key, 0)) + take
        spent += take
        if spent >= needed:
            break
    return spent


def spend_unrolled_projectile(ctx: Any) -> None:
    """Consume this weapon's ordinary ammunition for a shot that needs no roll.

    The caller validates attack_allowed first and owns the automatic outcome.
    Physical thrown weapons use thrown_equipment.release separately. No fallback
    to another carried ammunition kind; Ceaseless uses its normal stock gate.
    """
    ammo = _context_ammo(ctx)
    if not ammo or _stock(ctx.engine, ctx.actor, ammo) is None or _ceaseless(ctx.engine, ctx.actor, ammo):
        return
    stack = _available_stack(ctx.engine, ctx.actor, ammo)
    if stack is not None:
        key = _SPENT_PREFIX + str(ammo['item_id']) + ':' + str(stack.get('key') or '')
        ctx.actor.turn_flags[key] = int(ctx.actor.turn_flags.get(key, 0)) + 1
