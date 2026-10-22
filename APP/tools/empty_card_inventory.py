#!/usr/bin/env python3
"""Inventory action/ability cards whose body renders empty (owner feedback desk FD-16).

The table and the character sheet both draw a card from an action row: the row's
own text, then the shared built-in/setting/toggle fallback, then the printed
record. This tool builds synthetic characters that own every typed record (no
owner data), compiles their combat bundles, and asks the same presentation
functions the cards use. It writes one CSV row for every card that still has no
body, so a lane can write its text and a later guard can keep new ones out.

Run from APP:
    python tools/empty_card_inventory.py --output /var/tmp/empty_cards.csv

Read-only: it compiles in memory and never writes a fight, character or service
file. It is an authoring tool, not a test (a full compile takes minutes).
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from combat.factory_compiler import TYPED_AUTHORITY, compile_character  # noqa: E402

CHUNK = 700  # fallback size when the all-records character is rejected


def _mechanics() -> dict[str, dict]:
    return json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]


def _sheet(mids: list[str], mechanics: dict[str, dict]) -> dict:
    """A minimal synthetic owner sheet that owns exactly mids (same shape as tests/h1_support.py)."""
    spheres, talents, features, foundations = [], [], [], []
    for mid in mids:
        row = mechanics.get(mid) or {}
        kind = row.get("kind")
        if row.get("sphere_id"):
            if row["sphere_id"] not in spheres:
                spheres.append(row["sphere_id"])
            talents.append(mid)
        elif kind in ("path_feature", "subpath_feature"):
            features.append(mid)
        elif kind == "foundation_feature" and row.get("foundation_id"):
            foundations.append({"foundation_id": row["foundation_id"], "stage": row.get("stage") or "Perfected"})
    stats = {"STR": 14, "DEX": 14, "CON": 14, "INT": 14, "WIS": 14, "CHA": 14}
    out = {
        "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation", "key_ability": "CON",
                     "name": "Card inventory"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": s, "modifier": (s - 10) // 2} for a, s in stats.items()],
            "primary_resource": {"name": "Qi", "maximum": 30}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 60}, "speed": {"walking_ft": 30}, "technique_save_dc": 16,
            "technique_attack_bonus": 8,
        },
    }
    if spheres:
        bases = [k for k, m in mechanics.items() if m.get("sphere_id") in spheres and m.get("kind") == "base_ability"]
        out["spheres_and_talents"] = {"sphere_record_ids": spheres, "learned_talent_record_ids": talents,
                                      "automatic_sphere_component_record_ids": bases}
    if features:
        out["path_and_subpath"] = {"path_feature_record_ids": features}
    if foundations:
        out["foundation"] = foundations[0]
    return out


def _bundles(mechanics: dict[str, dict], *, chunked: bool = False) -> list[dict]:
    """The sheets to compile: one character owning every record, or chunks of CHUNK records each.

    One owner is the honest sheet -- a plug-in can add a button only because another owned record is present,
    and an Unarmed Strike's grapple and shove buttons draw their words from the Wrestling and Iron Fist
    records -- but it compiles superlinearly (minutes). Chunks take seconds and report every empty card the
    full sheet would (an empty button's own record is always on its chunk's sheet), plus a few false ones
    whose text lives on another chunk: a guard can allow-list those by id, which is why this is a choice
    rather than a fallback.
    """
    ids = list(mechanics)
    if not chunked:
        try:
            return [compile_character(_sheet(ids, mechanics), actor_id="actor:factory.card-inventory")]
        except Exception as exc:  # fall back to independent chunks so one bad combination cannot hide the rest
            print(f"all-records compile: {type(exc).__name__}: {exc}", file=sys.stderr)
    bundles, errors = [], []
    for start in range(0, len(ids), CHUNK):
        chunk = ids[start:start + CHUNK]
        try:
            bundles.append(compile_character(_sheet(chunk, mechanics), actor_id="actor:factory.card-inventory"))
        except Exception as exc:  # keep going: the inventory must cover the rest
            errors.append(f"chunk {start}: {type(exc).__name__}: {exc}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
    return bundles


def _source_lines() -> tuple[dict[str, str], list[tuple[str, str, int]]]:
    """Literal display-name/source/effect -> file:line, from the code that builds actions."""
    by_name: dict[str, str] = {}
    literals: list[tuple[str, str, int]] = []
    for path in sorted((APP / "combat").rglob("*.py")):
        if "tests" in path.parts or path.name == "action_card_text.py":
            continue  # the card-text seam names every button on purpose; it builds none of them
        try:
            text = path.read_text()
            tree = ast.parse(text)
        except (SyntaxError, UnicodeError):
            continue
        rel = str(path.relative_to(APP))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "ActionDefinition":
                continue
            where = f"{rel}:{node.lineno}"
            for keyword in node.keywords:
                if keyword.arg not in ("source_definition_id", "display_name"):
                    continue
                parts = ([keyword.value] if isinstance(keyword.value, ast.Constant)
                         else list(getattr(keyword.value, "values", [])))
                for part in parts:
                    if not isinstance(part, ast.Constant) or not isinstance(part.value, str):
                        continue  # a formatted field: the id's tail is the literal piece that identifies it
                    if keyword.arg == "display_name":
                        by_name.setdefault(part.value, where)
                    if len(part.value) >= 5:
                        literals.append((part.value, where, 0))
        # A plug-in often names its button through a helper (a literal argument) rather than an
        # ActionDefinition keyword, so every literal in a file that builds actions is a candidate too.
        if "action:typed" in text or "ActionDefinition" in text:
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) >= 6:
                    literals.append((node.value, f"{rel}:{node.lineno}", 1))
    return by_name, literals


@lru_cache(maxsize=1)
def _effect_lines() -> dict[str, str]:
    """Effect/hook type -> file:line of the function that resolves it (a plug-in's @effect decorator)."""
    out: dict[str, str] = {}
    for path in sorted((APP / "combat").rglob("*.py")):
        if "tests" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeError):
            continue
        rel = str(path.relative_to(APP))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not decorator.args:
                    continue
                name = getattr(decorator.func, "id", None) or getattr(decorator.func, "attr", None)
                first = decorator.args[0]
                # Only @effect: a hook name is implemented by every plug-in that cares about it, so the
                # first file alphabetically would be a lie.
                if name == "effect" and isinstance(first, ast.Constant) and isinstance(first.value, str):
                    out.setdefault(first.value, f"{rel}:{node.lineno}")
    return out


def _where(key: str, row: dict, by_name: dict[str, str], literals: list[tuple[str, str, int]]) -> str:
    """The file:line that builds this id: its own literal tail, its display name's builder, or the effect
    that resolves it.

    Only the tail after the character id is searched: every builder shares the "action:typed." prefix, so
    matching the whole id would report whichever file happened to spell that prefix longest.
    """
    tail = key.split(".", 2)[-1]
    matches = [(priority, -len(value), where) for value, where, priority in literals
               if value and value.lstrip(".") == tail]
    if matches:
        return min(matches)[2]
    if row.get("display_name") in by_name:
        return by_name[row["display_name"]]
    handlers = _effect_lines()
    for effect in (((row.get("parameters") or {}).get("typed") or {}).get("effects") or []):
        where = handlers.get(str(effect.get("type") or ""))
        if where:
            return where
    return ""


def _body(row: dict, bundle: dict, owned_ids: frozenset[str]) -> tuple[str, str]:
    """The text a table/sheet card resolves, and where it came from.

    ``own`` is the row's own printed entry (the card is fine). ``fallback`` is
    shared text borrowed from a feature or the built-in table: a real body, but
    one that does not say what this particular button does. ``name`` is a
    built-in action named by label. ``none`` is the FD-16 empty card.
    """
    from combat.tabletop import (engine_button_description, engine_button_description_for_name,
                                 untyped_button_text)
    text = (engine_button_description(row) or "").strip()
    if text:
        return text, "own"
    text = (untyped_button_text(row, bundle, owned_ids=owned_ids) or "").strip()
    if text:
        return text, "fallback"
    text = (engine_button_description_for_name(str(row.get("display_name") or ""),
                                               str(row.get("source_definition_id") or ""),
                                               row.get("parameters") or {}) or "").strip()
    if text:
        return text, "name"
    return "", "none"


def _kind(row: dict) -> str:
    parameters = row.get("parameters") or {}
    if parameters.get("setting_only"):
        return "setting/toggle"
    if parameters.get("basic"):
        return "basic action"
    if parameters.get("escape_option"):
        return "escape action"
    if row.get("economy") == "REACTION":
        return "reaction"
    if "granted" in str(row.get("source_definition_id") or ""):
        return "granted action"
    if row.get("economy") == "NONE":
        return "free choice"
    return "action"


def inventory(*, chunked: bool = False) -> list[dict]:
    mechanics = _mechanics()
    by_name, literals = _source_lines()
    rows: dict[str, dict] = {}
    for bundle in _bundles(mechanics, chunked=chunked):
        owned_ids = frozenset(str(key).split(".", 2)[-1] for key in
                              [row.get("source_definition_id") for row in bundle.get("action_catalog") or []])
        for row in bundle.get("action_catalog") or []:
            key = str(row.get("source_definition_id") or "")
            if not key or key in rows:
                continue
            body, origin = _body(row, bundle, owned_ids)
            if origin == "name":  # built-in label with its own printed line (Dash, Hide, Search)
                continue
            if origin == "own" and body and re.sub(r"\W+", "", body).casefold() != re.sub(r"\W+", "", str(row.get("display_name") or "")).casefold():
                continue
            typed = (row.get("parameters") or {}).get("typed") or {}
            rows[key] = {
                "id": key,
                "source_file:line": _where(key, row, by_name, literals) or _where(str(typed.get("source") or ""), row, by_name, literals),
                "kind": _kind(row),
                "where_shown": "table action bar + character sheet action card",
                "current_body": " ".join(body.split())[:200] if body else "",
                "body": body,
                "body_origin": origin,
                "name": row.get("display_name") or "",
                "typed_source": typed.get("source") or "",
                "effects": ",".join(str(effect.get("type")) for effect in typed.get("effects") or []),
            }
    order = {"escape action": 0, "action": 1, "granted action": 2, "reaction": 3,
             "free choice": 4, "setting/toggle": 5, "basic action": 6}
    return sorted(rows.values(), key=lambda row: (order.get(row["kind"], 9), row["body_origin"] != "none",
                                                  row["name"].casefold(), row["id"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = inventory()
    fields = ["id", "source_file:line", "kind", "where_shown", "current_body", "body_origin", "name", "typed_source", "effects"]
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"empty_cards": len(rows), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
