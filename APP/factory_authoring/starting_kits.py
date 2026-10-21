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
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core import FoundryError
from factory_authoring.owner_text import without_owner_exclusions

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
    if option["kind"] == "coin":
        dice = option["roll"]
        return f"Starting coin: {dice['count']}d{dice['sides']} × {_UNIT_CC[option['unit']]} Copper Coins"
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

# Irregular gear nouns need explicit forms, rather than trimming a trailing s.
_GEAR_SINGULARS = {"knives": "knife", "staves": "staff", "quarterstaves": "quarterstaff"}

_GEAR_NOUN = re.compile(
    r"\b(?:" + "|".join(_GEAR_SINGULARS) + r"|(?:battleaxe|battle axe|dagger|glaive|greataxe|great axe|greatsword|great sword|"
    r"hammer|halberd|longbow|long sword|longsword|maul|mace|meteor hammer|morningstar|"
    r"quarterstaff|rapier|scimitar|scythe|shortbow|short sword|shortsword|spear|staff|sword|"
    r"trident|warhammer|war hammer|whip|shield|armor|armour|crossbow|pike|lance|flail|club|knife)s?)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=None)
def _printed_knife_aliases(name: str) -> frozenset[str]:
    """Use the pinned starting-kit catalog mappings for printed knife names."""
    kits, catalog = _authorities()
    return frozenset(
        re.sub(r"^(?:a|an|the)\s+", "", entry["printed"], flags=re.IGNORECASE)
        for kit in kits["background_kits"].values()
        for entry in kit["entries"]
        if catalog.get(entry.get("item_id"), {}).get("name") == name
        and str(entry.get("printed", "")).casefold().endswith(" knife")
    )


def gear_name_forms(name: str) -> set[str]:
    """Printed gear name, individual parenthetical aliases and plurals.

    Shared by owner_named_gear and the optional concept index so a resolved
    name cannot become unrelated equipment requirements in semantic advice.
    """
    forms = {name.strip()}
    for parenthetical in re.findall(r"\(([^()]*)\)", name):
        forms.update(part.strip() for part in parenthetical.split("/") if part.strip())
    forms.update(_printed_knife_aliases(name))
    if "Dagger" in forms:
        forms.add("Knife")
    for form in tuple(forms):
        words = form.split()
        if words:
            last = words[-1]
            if last.casefold() in _GEAR_SINGULARS:
                forms.add(" ".join([*words[:-1], _GEAR_SINGULARS[last.casefold()]]))
                continue
            irregular_plural = next((plural for plural, singular in _GEAR_SINGULARS.items() if singular == last.casefold()), None)
            if irregular_plural:
                forms.add(" ".join([*words[:-1], irregular_plural]))
                continue
            singular = last[:-1] if last.casefold().endswith("s") and not last.casefold().endswith("ss") else last
            if singular != last:
                forms.add(" ".join([*words[:-1], singular]))
            elif last.casefold().endswith(("s", "x", "ch", "sh")):
                forms.add(" ".join([*words[:-1], last + "es"]))
            else:
                forms.add(" ".join([*words[:-1], last + "s"]))
    return forms


def owner_named_gear(concept: Any, title: Any = None) -> dict[str, Any]:
    """Resolve concrete gear named in owner text against the mundane catalog.

    Canonical catalog names and parenthetical aliases are matched case-insensitively
    at word boundaries. Only one copy of an unambiguous catalog item is mandatory;
    explicit larger quantities produce non-blocking advice for manual additions.
    Explicit or/either/slash choices outside a catalog name are advisory,
    as are ambiguous aliases;
    ordinary conjunctions keep independently named items mandatory.
    Unknown weapon-shaped phrases
    become plain owner warnings, never invented catalog IDs.
    """
    texts = [without_owner_exclusions(value.strip()) for value in (concept, title) if isinstance(value, str) and value.strip()]
    if not texts:
        return {"item_ids": [], "items": [], "warnings": []}
    rows = [row for row in gear_catalog() if row.get("category") in GEAR_CATEGORIES]
    candidates: list[tuple[str, str, str]] = []
    for row in rows:
        for form in gear_name_forms(str(row.get("name") or "")):
            candidates.append((row["item_id"], row["name"], form))
    candidates.sort(key=lambda item: (-len(item[2]), item[0], item[2].casefold()))
    matched: dict[str, str] = {}
    spans_by_text: dict[str, list[tuple[int, int]]] = {text: [] for text in texts}
    accepted_by_text: dict[str, list[tuple[int, int, set[str]]]] = {text: [] for text in texts}
    # Select longest, non-overlapping catalog phrases in source order after
    # the shared phrase filter has removed whole exclusion clauses.
    raw_by_text: dict[str, list[tuple[int, int, str, str]]] = {text: [] for text in texts}
    for item_id, name, form in candidates:
        pattern = re.compile(r"(?<![\w])" + re.escape(form) + r"(?![\w])", re.IGNORECASE)
        for text in texts:
            raw_by_text[text].extend((m.start(), m.end(), item_id, name) for m in pattern.finditer(text))
    matches_by_text: dict[str, list[tuple[int, int, set[str]]]] = {}
    for text, raw in raw_by_text.items():
        selected: list[tuple[int, int, set[str]]] = []
        for start, end, item_id, _name in sorted(raw, key=lambda row: (row[0], -(row[1] - row[0]), row[2])):
            overlap = next((row for row in selected if start < row[1] and row[0] < end), None)
            if overlap:
                if (start, end) == overlap[:2]:
                    overlap[2].add(item_id)
                continue
            selected.append((start, end, {item_id}))
        matches_by_text[text] = sorted(selected, key=lambda row: row[0])
    for text in texts:
        for start, end, item_ids in matches_by_text[text]:
            match_start, match_end = start, end
            if len(text[match_start:match_end].split()) == 1:
                prefix = text[:match_start].rstrip()
                previous = re.search(r"([\w'-]+)$", prefix)
                if previous and previous.group(1).casefold() not in {
                    "a", "an", "the", "his", "her", "their", "my", "our", "this", "that",
                    "with", "using", "use", "uses", "wield", "wields", "wielding", "carry", "carries", "carrying",
                    "named", "called", "weapon", "weapons", "one", "two", "three", "four", "five", "six",
                    "seven", "eight", "nine", "ten", "and", "or", "either",
                } and not previous.group(1).isdigit() and not re.search(r"\b(?:a\s+)?pair\s+of$", prefix, re.IGNORECASE) and not prefix.endswith("-" + previous.group(1).split("-")[-1]):
                    continue
            spans = spans_by_text[text]
            # A shorter catalog alias such as "hammer" must not turn the
            # owner's explicit "meteor hammer" into two requirements.
            if any(span_start <= match_start and match_end <= span_end and span_end - span_start > match_end - match_start for span_start, span_end in spans):
                continue
            for item_id in item_ids:
                name = next(row[1] for row in candidates if row[0] == item_id)
                matched.setdefault(item_id, name)
            spans.append((match_start, match_end))
            accepted_by_text[text].append((match_start, match_end, item_ids))
    required: dict[str, str] = {}
    warnings: list[str] = []
    advisories: list[str] = []
    advisory_by_text: dict[str, list[tuple[int, int]]] = {text: [] for text in texts}
    for text in texts:
        # A conjunction separates independently named gear. Inside a choice
        # clause, even unmatched or unusually worded options stay advisory.
        for phrase in re.finditer(r"[^;.!?\n]+", text):
            clauses = r"(?:^|\band\b|\bbut\b)(.*?)(?=\band\b|\bbut\b|$)"
            if re.search(r"\beither\b", phrase.group(), re.IGNORECASE) and not re.search(r"\bor\b|/", phrase.group(), re.IGNORECASE):
                clauses = r"(.*)"
            for clause in re.finditer(clauses, phrase.group(), re.IGNORECASE):
                start, end = phrase.start() + clause.start(1), phrase.start() + clause.end(1)
                matches = [(a, b, ids) for a, b, ids in accepted_by_text[text] if start <= a < end]
                wording = text[start:end].strip(" ,")
                choice = any(
                    not any(a <= start + marker.start() and start + marker.end() <= b and len(ids) == 1
                            for a, b, ids in matches)
                    for marker in re.finditer(r"\bor\b|\beither\b|/", text[start:end], re.IGNORECASE)
                )
                if choice and (matches or _GEAR_NOUN.search(wording)):
                    advisory_by_text[text].append((start, end))
                    warnings.append(f"Optional gear suggestion: {wording}. Choose any legal starting gear; this suggestion does not require a starting kit or limit its choices.")
                    continue
                for a, b, ids in matches:
                    if len(ids) == 1:
                        item_id = next(iter(ids))
                        required.setdefault(item_id, matched[item_id])
                        quantity = re.search(
                            r"\b(?:two|three|four|five|six|seven|eight|nine|ten|\d+|(?:a\s+)?pair\s+of)\s+$",
                            text[:a], re.IGNORECASE,
                        )
                        if quantity and (not quantity.group().strip().isdigit() or int(quantity.group()) > 1):
                            wording = text[quantity.start():b]
                            advisories.append(f"Your concept asks for {wording}; one is required. The quantity isn't enforced automatically; add more by hand if you want them.")
                    else:
                        advisory_by_text[text].append((a, b))
                        options = " or ".join(matched[item_id] for item_id in sorted(ids))
                        warnings.append(f"Optional gear suggestion: {options}. Name one specific catalog item if you want it required; this suggestion does not limit starting-kit choices.")
    # A name such as "stormglass glaive" should not disappear silently merely
    # because the catalog has no matching weapon row.
    unknown_phrases: set[str] = set()
    for text in texts:
        for match in _GEAR_NOUN.finditer(text):
            if any(start <= match.start() < end for start, end in advisory_by_text[text]):
                continue
            if any(start <= match.start() and match.end() <= end for start, end in spans_by_text[text]):
                continue
            if any(
                0 <= match.start() - end <= 2
                and text[end:match.start()].strip() == ""
                for _start, end in spans_by_text[text]
            ):
                # Catalog armor names commonly omit the category word that
                # owners naturally append (for example, "Lacquered Leather armor").
                continue
            words = text[max(0, match.start() - 48):match.end()].split()
            tail = words[-3:]
            if tail and tail[0].casefold() in {"a", "an", "the", "his", "her", "their", "my", "our"}:
                tail = tail[1:]
            phrase = " ".join(tail).strip(" ,.;:!?()[]{}\"'")
            if phrase and phrase.casefold() not in {name.casefold() for name in matched.values()}:
                unknown_phrases.add(phrase)
    warnings.extend(
        f"We couldn't match '{phrase}' to catalog gear, so it wasn't added to the starting gear. Choose a catalog item or add this gear by hand."
        for phrase in sorted(unknown_phrases, key=str.casefold)
    )
    return {
        "item_ids": list(required),
        "items": [{"item_id": item_id, "name": name} for item_id, name in required.items()],
        "warnings": list(dict.fromkeys(warnings)),
        "advisories": list(dict.fromkeys(advisories)),
    }


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


def kit_choice_item_ids(background_id: str, path_id: str, path_option: str) -> set[str]:
    """Return fixed and selectable mundane gear IDs in one printed kit option."""
    result: set[str] = set()
    for entries in (background_kit(background_id)["entries"], _path_entries(path_id, path_option)[0]):
        for entry in entries:
            if entry["kind"] == "choice":
                for option in _options(entry):
                    result |= _option_item_ids(option)
            elif entry["kind"] in {"item", "bundle"}:
                result |= _option_item_ids(entry)
    return result


def feasible_kit_item_ids(background_id: str, path_id: str, seed: str) -> set[str]:
    """Return gear the owner can select from either printed kit option.

    Character creation uses this when deciding whether named equipment is
    genuinely unavailable.  The set includes closed-choice items from both
    options and any catalog item Option B can buy with its seeded starting coin.
    """
    _, catalog = _authorities()
    option_b = resolve_starting_kit(background_id, path_id, path_option="option_b", seed=seed)
    coin_cc = int(option_b.get("coin_cc") or 0)
    return (
        kit_choice_item_ids(background_id, path_id, "option_a")
        | kit_choice_item_ids(background_id, path_id, "option_b")
        | {item_id for item_id, row in catalog.items() if int(row.get("price_cc") or 0) <= coin_cc}
    )


def owner_gear_requirements_affordable(
    background_id: str,
    path_id: str,
    path_option: str,
    required_item_ids: Sequence[str],
    *,
    remaining_coin_cc: int,
    retained_item_ids: Sequence[str] = (),
) -> bool:
    """Check mandatory catalog items against one legal kit choice and budget.

    Choice menus are mutually exclusive, so each legal menu combination is
    considered as a whole before the remaining requirements are priced.
    ``remaining_coin_cc`` is the shared unspent guaranteed coin, supplied by
    ``deterministic_kit_coin_cc`` minus purchases already paid for.
    ``retained_item_ids`` are purchases and treasure chassis retained when
    replanning menus. Purchases are already paid from the remaining coin;
    treasure chassis use the separate treasure budget.
    Include satisfied items too, since replacement menus may lose their gear.
    Charge each distinct missing purchase once, even if named more than once.
    """
    _, catalog = _authorities()
    background_entries = background_kit(background_id)["entries"]
    path_entries, _ = _path_entries(path_id, path_option)
    fixed: set[str] = set(retained_item_ids)
    choices: list[list[set[str]]] = []
    for entries in (background_entries, path_entries):
        for entry in entries:
            if entry["kind"] == "choice":
                choices.append([_option_item_ids(option) for option in _options(entry)])
            elif entry["kind"] in {"item", "bundle"}:
                fixed |= _option_item_ids(entry)

    def affordable(available: set[str]) -> bool:
        missing = set(required_item_ids) - available
        return missing <= catalog.keys() and sum(
            int(catalog[item_id]["price_cc"]) for item_id in missing
        ) <= remaining_coin_cc

    def visit(index: int, available: set[str]) -> bool:
        if index == len(choices):
            return affordable(available)
        return any(visit(index + 1, available | option_ids) for option_ids in choices[index])

    return visit(0, fixed)


def deterministic_kit_coin_cc(
    background_id: str, path_id: str, path_option: str, *, picks: Mapping[str, int] | None = None,
) -> int:
    """Guaranteed coin for mandatory gear, shared by planning and validation.

    Count Path coin and fixed or already pinned Background entries only. Dice
    contribute their minimum (one per die); unchosen Background options add
    nothing. This policy never rolls dice or changes actual kit resolution.
    """
    picks = picks or {}

    def coin(entry: Mapping[str, Any]) -> int:
        if entry["kind"] == "bundle":
            return sum(coin(part) for part in entry["items"])
        if entry["kind"] == "coin":
            return int(entry["roll"]["count"]) * _UNIT_CC[entry["unit"]]
        return 0

    total = _path_entries(path_id, path_option)[1]
    for index, entry in enumerate(background_kit(background_id)["entries"]):
        if entry["kind"] == "choice":
            options = _options(entry)
            pick = picks.get(f"background:{index}")
            if type(pick) is int and 0 <= pick < len(options):
                total += coin(options[pick])
        else:
            total += coin(entry)
    return total


def preferred_kit_plan(background_id: str, path_id: str, preferred_ids: Sequence[str], *, picks: Mapping[str, int] | None = None) -> dict[str, Any] | None:
    """Honour the owner's preferred weapons and armour.

    Option A is kept when its fixed items and choice menus already supply
    every preferred item (the menus are pinned to them).  Otherwise Option B's
    coin buys the preferred items the kit does not supply, in the owner's
    order, using guaranteed coin only. ``None`` leaves both kits open when
    there is no preference or the preferences cannot all be guaranteed.
    """

    wanted = [item_id for item_id in dict.fromkeys(preferred_ids or ()) if isinstance(item_id, str)]
    if not wanted:
        return None
    _, catalog = _authorities()
    background_entries = background_kit(background_id)["entries"]

    def supplied(path_option: str) -> tuple[set[str], dict[str, int]]:
        found: set[str] = set()
        selected_picks: dict[str, int] = {}
        for source, entries in (("background", background_entries), ("path", _path_entries(path_id, path_option)[0])):
            for index, entry in enumerate(entries):
                if entry["kind"] != "choice":
                    found |= _option_item_ids(entry) if entry["kind"] in {"item", "bundle"} else set()
                    continue
                choice_id = f"{source}:{index}"
                options = _options(entry)
                pinned = (picks or {}).get(choice_id)
                if type(pinned) is int and 0 <= pinned < len(options):
                    selected_picks[choice_id] = pinned
                    found |= _option_item_ids(options[pinned])
                    continue
                for option_index, option in enumerate(options):
                    hit = (_option_item_ids(option) & set(wanted)) - found
                    if hit and choice_id not in selected_picks:
                        selected_picks[choice_id] = option_index
                        found |= hit
        return found, selected_picks

    found_a, picks_a = supplied("option_a")
    if set(wanted) <= found_a:
        return {"path_option": "option_a", "picks": picks_a}
    found_b, picks_b = supplied("option_b")
    coin = deterministic_kit_coin_cc(background_id, path_id, "option_b", picks=picks)
    purchases: list[str] = []
    for item_id in wanted:
        if item_id in found_b or item_id not in catalog:
            continue
        price = catalog[item_id]["price_cc"]
        if price <= coin:
            purchases.append(item_id)
            coin -= price
    if not set(wanted) <= found_b | set(purchases):
        return None
    return {"path_option": "option_b", "picks": picks_b, "purchases": purchases}
