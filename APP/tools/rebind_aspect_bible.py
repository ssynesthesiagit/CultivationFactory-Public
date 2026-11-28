#!/usr/bin/env python3
"""Rebind previously admitted Bible reviews only for certified line pairs.

Run from APP with python -m tools.rebind_aspect_bible OLD_BIBLE CHANGED_LINES.
OLD_BIBLE is a local copy of the pre-rename pin, including its own matcher.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from tools.aspect_term_values import json_values
from tools.aspect_terms import aspect_terms


def line_pairs(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) % 3:
        raise ValueError(f"Incomplete line pair in {path}")
    for header, old, new in zip(lines[::3], lines[1::3], lines[2::3]):
        if not (header.startswith("@@ ") and old.startswith("- ") and new.startswith("+ ")):
            raise ValueError(f"Invalid line pair: {header!r}")
        yield header[3:].rsplit(":", 1)[0], old[2:], new[2:]


def text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def review_paths():
    from tools import typed_mechanics_helpers as typed

    yield typed.REVIEWED_FINAL
    yield from sorted((typed.REVIEWED_FINAL.parent / "reviewed_final.d").glob("*.json"))


def write_reviews(bindings, wording, *, pinned_paths=()):
    """Write review bindings and return the IDs left untouched in pinned files."""
    kept = set()
    for path in review_paths():
        is_pinned = path in pinned_paths
        text = path.read_bytes().decode("utf-8")

        def update(value, key, offset):
            if len(key) < 3 or key[0] != "mechanics" or key[1] not in bindings:
                return value
            old_sha, new_sha = bindings[key[1]]
            if key[2:] == ("text_sha256",):
                if value == old_sha:
                    if is_pinned:
                        kept.add(key[1])
                    else:
                        return new_sha
                return value
            return wording(value) if not is_pinned and any(c.isspace() for c in value) else value

        changed = json_values(text, update)
        if changed != text:
            path.write_bytes(changed.encode("utf-8"))
    return kept


def _index(root):
    spec = importlib.util.spec_from_file_location("_pre_aspect_bible_index", root / "tools/check_damage_floor.py")
    matcher = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = matcher
    spec.loader.exec_module(matcher)
    return matcher.BibleIndex(root)


def rebind(old_root, pairs_path):
    from tools import typed_mechanics_helpers as typed

    pairs = defaultdict(set)
    for rel, old, new in line_pairs(pairs_path):
        pairs[rel].add((old, new))
    old_index = _index(old_root)
    new_index = typed._bible_index(typed.BIBLE_ROOT)
    finals = typed.load_finals()
    old_mapped, new_mapped = set(), set()
    before, after, bindings, kept = set(), set(), {}, {}
    gaps = defaultdict(Counter)
    rows = typed._gather_sources()
    for row in rows:
        key = row["id"]
        old, _ = old_index.resolve_key(key, row["text"])
        new, error = new_index.resolve_key(key, row["text"])
        if old:
            old_mapped.add(key)
            gaps[old[0].split("/")[0]]["old_mapped"] += 1
        if new:
            new_mapped.add(key)
            gaps[new[0].split("/")[0]]["new_mapped"] += 1
        current = finals.get(key, {}).get("text_sha256")
        old_sha = text_sha(old[3]) if old else None
        new_sha = text_sha(new[3]) if new else None
        if old_sha and current == old_sha:
            before.add(key)
            gaps[old[0].split("/")[0]]["old_switched"] += 1
            if not new:
                kept[key] = {"unmapped": error}
            elif old_sha != new_sha:
                left, right = old[3].splitlines(), new[3].splitlines()
                uncertified = [(a, b) for a, b in zip(left, right) if a != b and (a, b) not in pairs[old[0]]]
                if old[0] == new[0] and len(left) == len(right) and not uncertified:
                    bindings[key] = (old_sha, new_sha)
                else:
                    kept[key] = {"old_location": old[:3], "new_location": new[:3], "nonrename_pairs": uncertified[:4]}
        if new_sha and (current == new_sha or key in bindings):
            after.add(key)
            gaps[new[0].split("/")[0]]["new_switched"] += 1

    write_reviews(bindings, aspect_terms)
    return {
        "sources": len(rows),
        "mapped_before": len(old_mapped), "mapped_after": len(new_mapped),
        "mapping_added": sorted(new_mapped - old_mapped), "mapping_lost": sorted(old_mapped - new_mapped),
        "switched_before": len(before), "switched_after": len(after), "rebound": sorted(bindings), "kept": kept,
        "by_book": gaps,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_bible", type=Path)
    parser.add_argument("changed_lines", type=Path)
    args = parser.parse_args()
    print(json.dumps(rebind(args.old_bible, args.changed_lines), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
