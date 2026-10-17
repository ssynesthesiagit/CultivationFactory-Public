"""Starting kits: printed Background kit plus the highest Path's kit, as catalog items.

The kits live in the hash-pinned ``Tianxia_Starting_Kit_Authority_R1.json`` (built
by ``tools/build_starting_kit_authority.py`` from the printed Background sentences
and the Mortal equipment catalog).  Every choice is a closed menu of concrete
options; the local model may pick an index, and option 0 is the deterministic
fallback.  Printed entries with no catalog item stay verbatim as trinkets.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core import FoundryError

APP_ROOT = Path(__file__).resolve().parents[1]
KIT_AUTHORITY_PATH = "authority/Tianxia_Starting_Kit_Authority_R1.json"
KIT_AUTHORITY_SHA256 = "346ffd1961c41cd7b4b19a81a45c09a758b7e36c4bf276ca38057ec80a99316b"
CATALOG_PATH = "authority/Tianxia_Mundane_Equipment_Catalog_R1.json"
CATALOG_SHA256 = "dced77a989b795bfb9860aabd18ef0bd7694f498bc245314ba14dcb0c3f81754"
PATH_OPTIONS = ("option_a", "option_b")
_UNIT_CC = {"CC": 1, "ST": 10, "GT": 100}


def _invalid(message: str, **details: Any) -> FoundryError:
    return FoundryError("STARTING_KIT_INVALID", message, details=details or None)


def _pinned_json(relative: str, expected_sha256: str) -> dict[str, Any]:
    path = APP_ROOT / relative
    if path.is_symlink() or not path.is_file():
        raise _invalid("A starting-kit authority file is missing.", path=relative)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise _invalid("A starting-kit authority file does not match its pin.", path=relative)
    return json.loads(data.decode("utf-8"))


@lru_cache(maxsize=1)
def _authorities() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    kits = _pinned_json(KIT_AUTHORITY_PATH, KIT_AUTHORITY_SHA256)
    catalog = _pinned_json(CATALOG_PATH, CATALOG_SHA256)
    if kits.get("sources", {}).get("catalog", {}).get("sha256") != CATALOG_SHA256:
        raise _invalid("The starting-kit authority is bound to a different catalog.")
    return kits, {item["item_id"]: item for item in catalog["items"]}


def item_definition(item_id: str) -> dict[str, Any]:
    """Return a copy of a pinned catalog item for shared combat weapon queries.

    Used by weapon_hits (weapon families) and Gravity (weapon proficiency).
    Unknown items return an empty dictionary; callers cannot alter the catalog.
    """
    import copy
    return copy.deepcopy(_authorities()[1].get(str(item_id), {}))


def seeded_roll(seed: str, label: str, sides: int) -> int:
    """A server-owned die roll: reproducible from the seed, not chosen by the model."""

    if not isinstance(seed, str) or not seed:
        raise _invalid("A seeded roll needs a non-empty server seed.", label=label)
    digest = hashlib.sha256(f"tianxia.starting_kit.v1|{seed}|{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % sides + 1


def wealth_multiplier(background_id: str, seed: str) -> dict[str, Any]:
    """Background wealth tier x seeded 1d20 fortune roll, applied to the CL treasure budget."""

    kits, _ = _authorities()
    tier = background_kit(background_id)["wealth_tier"]
    roll = seeded_roll(seed, f"fortune:{background_id}", 20)
    fortune = [row for row in kits["wealth"]["fortune_roll"] if row["min_roll"] <= roll][-1]
    tier_multiplier = kits["wealth"]["tiers"][tier]
    return {
        "wealth_tier": tier,
        "tier_multiplier": tier_multiplier,
        "fortune_roll": roll,
        "fortune": fortune["label"],
        "fortune_multiplier": fortune["multiplier"],
        "multiplier": round(tier_multiplier * fortune["multiplier"], 4),
    }


def wealth_tier_multipliers() -> dict[str, float]:
    kits, _ = _authorities()
    return dict(kits["wealth"]["tiers"])


def path_kit_item_ids(path_id: str) -> set[str]:
    """Every item the Path's printed kit (Option A) names, including each closed-choice option."""
    kits, _ = _authorities()
    entries = list(kits["path_kits"].get(path_id, {}).get("option_a", {}).get("entries", []))
    result: set[str] = set()
    while entries:
        entry = entries.pop()
        if entry.get("item_id"):
            result.add(entry["item_id"])
        entries.extend(entry.get("options") or [])
    return result


def has_starting_kit(background_id: str, path_id: str) -> bool:
    kits, _ = _authorities()
    return background_id in kits["background_kits"] and path_id in kits["path_kits"]


def background_kit(background_id: str) -> dict[str, Any]:
    kits, _ = _authorities()
    kit = kits["background_kits"].get(background_id)
    if kit is None:
        raise _invalid("The Background has no printed starting kit.", background_id=background_id)
    return deepcopy(kit)


def printed_background_items(background_id: str) -> list[str]:
    """The printed kit entries, verbatim and in printed order."""

    return [entry["printed"] for entry in background_kit(background_id)["entries"]]


def _path_entries(path_id: str, path_option: str) -> tuple[list[dict[str, Any]], int]:
    kits, _ = _authorities()
    kit = kits["path_kits"].get(path_id)
    if kit is None:
        raise _invalid("The Path has no starting kit.", path_id=path_id)
    if path_option not in PATH_OPTIONS:
        raise _invalid("The Path kit option must be option_a or option_b.", path_option=path_option)
    return deepcopy(kit[path_option]["entries"]), int(kit[path_option]["coin_cc"])


def _options(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand a choice into concrete options (category menus become one option per item)."""

    kits, _ = _authorities()
    options: list[dict[str, Any]] = []
    for option in entry["options"]:
        if option["kind"] == "category":
            options.extend({"kind": "item", "item_id": item_id, "quantity": 1} for item_id in kits["category_menus"][option["menu"]])
        else:
            options.append(deepcopy(option))
    return options


def _label(option: Mapping[str, Any], catalog: Mapping[str, Mapping[str, Any]]) -> str:
    if option["kind"] == "trinket":
        return option["text"]
    if option["kind"] == "bundle":
        return " + ".join(_label(part, catalog) for part in option["items"])
    quantity = option.get("quantity", 1)
    name = catalog[option["item_id"]]["name"]
    return f"{quantity} × {name}" if quantity != 1 else name


def path_kit_summary(path_id: str, path_option: str) -> str:
    """A short description of one Path kit option for the option menu."""

    _, catalog = _authorities()
    entries, coin_cc = _path_entries(path_id, path_option)
    parts = []
    for entry in entries:
        options = entry["options"] if entry["kind"] == "choice" else [entry]
        parts.append(" or ".join("any listed weapon" if option["kind"] == "category" else _label(option, catalog) for option in options))
    coin = f"{coin_cc // 10} ST" if coin_cc % 10 == 0 else f"{coin_cc} CC"
    return "; ".join([*parts, coin]) if parts else f"{coin} to buy your own gear"


def highest_path(path_ids: list[str], progression_by_cl: Mapping[str, str] | None) -> str:
    """The Path with the most levels; ties go to the first selected Path."""

    counts = {path_id: 0 for path_id in path_ids}
    for path_id in (progression_by_cl or {}).values():
        if path_id in counts:
            counts[path_id] += 1
    return max(path_ids, key=lambda path_id: (counts[path_id], -path_ids.index(path_id)))


def choice_menus(background_id: str, path_id: str, path_option: str = "option_a") -> list[dict[str, Any]]:
    """Closed menus for every choice in the kit, for the local model to pick from."""

    _, catalog = _authorities()
    menus = []
    sources = [("background", background_kit(background_id)["entries"]), ("path", _path_entries(path_id, path_option)[0])]
    for source, entries in sources:
        for index, entry in enumerate(entries):
            if entry["kind"] == "choice":
                menus.append({
                    "choice_id": f"{source}:{index}",
                    "printed": entry.get("printed"),
                    "options": [_label(option, catalog) for option in _options(entry)],
                    "fallback_index": 0,
                })
    return menus


def resolve_starting_kit(
    background_id: str,
    path_id: str,
    *,
    path_option: str = "option_a",
    picks: Mapping[str, int] | None = None,
    seed: str | None = None,
    purchases: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Resolve the kit into items, trinkets and coin.  Unpicked or invalid picks fall back to 0.

    Printed coin without an amount is a seeded roll; ``seed`` is required for such kits.
    ``purchases`` (Option B only) are catalog items bought in order with the
    kit's coin, as a 5.5e character spends starting gold.
    """

    _, catalog = _authorities()
    picks = dict(picks or {})
    path_entries, coin_cc = _path_entries(path_id, path_option)
    items: list[dict[str, Any]] = []
    trinkets: list[dict[str, Any]] = []
    coin_rolls: list[dict[str, Any]] = []
    choices: list[dict[str, Any]] = []

    def add(option: Mapping[str, Any], *, source: str, printed: str | None) -> None:
        if option["kind"] == "bundle":
            for part in option["items"]:
                add(part, source=source, printed=printed)
        elif option["kind"] == "trinket":
            trinkets.append({"source": source, "text": option.get("text") or printed, "value_cc": 0})
        elif option["kind"] == "coin":
            dice = option["roll"]
            rolls = [seeded_roll(seed, f"coin:{background_id}:{printed}:{index}", dice["sides"]) for index in range(dice["count"])]
            coin_rolls.append({"printed": printed, "dice": f"{dice['count']}d{dice['sides']}", "rolls": rolls,
                               "unit": option["unit"], "amount_cc": sum(rolls) * _UNIT_CC[option["unit"]]})
        else:
            row = catalog[option["item_id"]]
            quantity = int(option.get("quantity", 1))
            item = {
                "item_id": row["item_id"],
                "name": row["name"],
                "quantity": quantity,
                "source": source,
                "unit_price_cc": row["price_cc"],
                "value_cc": row["price_cc"] * quantity,
            }
            if printed:
                item["printed"] = printed
            if option.get("quantity_printed") is False:
                item["quantity_printed"] = False
            items.append(item)

    for source, entries in (("background", background_kit(background_id)["entries"]), ("path", path_entries)):
        for index, entry in enumerate(entries):
            printed = entry.get("printed")
            if entry["kind"] != "choice":
                add(entry, source=source, printed=printed)
                continue
            options = _options(entry)
            choice_id = f"{source}:{index}"
            pick = picks.get(choice_id)
            fallback = not (isinstance(pick, int) and not isinstance(pick, bool) and 0 <= pick < len(options))
            selected = 0 if fallback else pick
            choices.append({"choice_id": choice_id, "selected_index": selected, "fallback_used": fallback,
                            "selected": _label(options[selected], catalog)})
            add(options[selected], source=source, printed=printed)

    coin_total = coin_cc + sum(row["amount_cc"] for row in coin_rolls)
    bought = list(purchases or ())
    if bought and path_option != "option_b":
        raise _invalid("Only the Option B kit (coin) can buy gear.", path_option=path_option)
    for item_id in bought:
        row = catalog.get(item_id)
        if row is None:
            raise _invalid("A purchased item is not in the mundane catalog.", item_id=item_id)
        if row["price_cc"] > coin_total:
            raise _invalid("The kit's coin cannot pay for a purchased item.", item_id=item_id, price_cc=row["price_cc"], coin_cc=coin_total)
        coin_total -= row["price_cc"]
        items.append({
            "item_id": row["item_id"], "name": row["name"], "quantity": 1, "source": "purchase",
            "unit_price_cc": row["price_cc"], "value_cc": row["price_cc"],
        })

    return {
        "schema_version": "TianxiaFoundry.ResolvedStartingKit.v1",
        "background_id": background_id,
        "path_id": path_id,
        "path_option": path_option,
        "items": items,
        "trinkets": trinkets,
        "coin_cc": coin_total,
        "path_coin_cc": coin_cc,
        "printed_coin_rolls": coin_rolls,
        "choices": choices,
        "total_item_value_cc": sum(item["value_cc"] for item in items),
        "authority_sha256": KIT_AUTHORITY_SHA256,
        **({"purchases": bought} if bought else {}),
    }


GEAR_CATEGORIES = ("weapon", "armor", "shield")


def gear_catalog() -> list[dict[str, Any]]:
    """Weapons, armour and shields an owner may name as preferred gear."""

    _, catalog = _authorities()
    return [
        {"item_id": row["item_id"], "name": row["name"], "category": row["category"], "price_cc": row["price_cc"]}
        for row in sorted(catalog.values(), key=lambda item: (GEAR_CATEGORIES.index(item["category"]) if item["category"] in GEAR_CATEGORIES else 9, item["name"]))
        if row["category"] in GEAR_CATEGORIES
    ]


def _option_item_ids(option: Mapping[str, Any]) -> set[str]:
    if option["kind"] == "bundle":
        return set().union(*(_option_item_ids(part) for part in option["items"])) if option["items"] else set()
    return {option["item_id"]} if option["kind"] == "item" else set()


def preferred_kit_plan(background_id: str, path_id: str, preferred_ids: Sequence[str]) -> dict[str, Any] | None:
    """Honour the owner's preferred weapons and armour.

    Option A is kept when its fixed items and choice menus already supply
    every preferred item (the menus are pinned to them).  Otherwise Option B's
    coin buys the preferred items the kit does not supply, in the owner's
    order, while the coin lasts.  ``None`` when there is no preference.
    """

    wanted = [item_id for item_id in dict.fromkeys(preferred_ids or ()) if isinstance(item_id, str)]
    if not wanted:
        return None
    _, catalog = _authorities()
    background_entries = background_kit(background_id)["entries"]

    def supplied(path_option: str) -> tuple[set[str], dict[str, int]]:
        found: set[str] = set()
        picks: dict[str, int] = {}
        for source, entries in (("background", background_entries), ("path", _path_entries(path_id, path_option)[0])):
            for index, entry in enumerate(entries):
                if entry["kind"] != "choice":
                    found |= _option_item_ids(entry) if entry["kind"] in {"item", "bundle"} else set()
                    continue
                for option_index, option in enumerate(_options(entry)):
                    hit = (_option_item_ids(option) & set(wanted)) - found
                    if hit and f"{source}:{index}" not in picks:
                        picks[f"{source}:{index}"] = option_index
                        found |= hit
        return found, picks

    found_a, picks_a = supplied("option_a")
    if set(wanted) <= found_a:
        return {"path_option": "option_a", "picks": picks_a}
    found_b, picks_b = supplied("option_b")
    # Seeded Background coin is rolled later; plan with the Path kit's coin only.
    coin = _path_entries(path_id, "option_b")[1]
    purchases: list[str] = []
    for item_id in wanted:
        if item_id in found_b or item_id not in catalog:
            continue
        price = catalog[item_id]["price_cc"]
        if price <= coin:
            purchases.append(item_id)
            coin -= price
    if not purchases and not picks_b:
        return {"path_option": "option_a", "picks": picks_a}
    return {"path_option": "option_b", "picks": picks_b, "purchases": purchases}
