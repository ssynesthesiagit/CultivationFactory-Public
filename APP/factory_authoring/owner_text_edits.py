"""The owner's edits to printed rules text, and carrying an ability's typing across a number edit.

Used by tools/build_typed_mechanics_authority.py (``sources`` applies the edits; ``build`` carries the typing). An optional
``player_text`` field supplies display-only wording to the builder's player_text.json;
``player_evidence`` maps exact reviewed commentary to its printed-rule reminder.
``player_replace`` changes a phrase in the current display projection, with an
explicit occurrence count. It preserves later source additions and never feeds
the rules parser; stale, overlapping or number-changing pairs are rejected.
it never changes the source, reviewed evidence, source hashes or mechanic typing.
The edits live
in authority/typed_mechanics/owner_text_edits.json, one entry per record id:

    {"remove": ["a whole printed line"],                      # struck from the text (owner 2026-09-29, Meld)
     "replace": [{"old": "Gain +3 AC", "new": "Gain +5 AC"}],  # applied after "remove" (owner 2026-09-30, Qi Armor)
     "retype": true,                                            # type the edited words directly instead of carrying old typing
     "why": "the owner's words"}

A "replace" pair's ``old`` must occur exactly once in the text (after "remove"); otherwise the pair is not applied and the
builder reports it. Set ``retype`` for a word change that changes the record's typed classification: the builder types the
edited text directly instead of trying to carry the earlier review onto different words.

Carrying (owner 2026-09-30: "with qi armour can we change it to 5"): every typing of a record (model passes, reviews,
reviewed_final) is keyed to the sha256 of the exact text it read, so an edited text would lose them all. When nothing has
typed the edited text itself, the builder types the text as it read before the "replace" pairs and hands the result to
``carry_typing``, which moves it onto the edited text:

- a pair must change numbers only (the same words around them); anything else cannot be carried;
- every string of the record that quotes the printed text around a changed number (an effect's "evidence", a rider, a
  description line, a trigger) is re-quoted from the edited text, and must be found in it afterwards;
- a string that restates the edited words without quoting them verbatim (the rider "Cost: 2 Qi" for "**Cost:** 2 Qi") has
  them replaced;
- in the part of the record that string belongs to (the effect, not its nested effects, which quote their own words), the
  one numeric field holding the old number takes the new one; two such fields, or the number also kept in a table
  (dice_by_cl), is ambiguous;
- header fields (trigger, cost, limit, range, area, target, duration) the deterministic parser reads differently from the
  edited text take the new reading where the typing still agrees with the parser's reading of the old text.

A changed number that no typed field held (only quoted in an effect whose fields say nothing of it) or that nothing in the
record quotes is not carried: ``carry_typing`` returns a problem for it and the builder reports the record, which keeps its
earlier typing whole rather than silently losing its effects. ``remove`` edits are not carried: the record is typed afresh
from the edited text, as before.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Callable

_NUMBER = re.compile(r"\d+")
_HEADER_LINE = re.compile(r"^\s*\*\*[^*\n]+:\*\*")
HEADER_FIELDS = ("activation", "cost", "use_limit", "range", "area", "target", "duration")
_SKIP_KEYS = {"source", "mechanic_id", "schema", "provenance", "owner_edit", "typing_status", "structure_source", "origin", "coverage"}
_TEXT_TYPES = {"rider", "description", "gm_rider"}


def player_wording(text: str, edit: dict[str, Any] | None) -> str:
    """Apply checked, simultaneous phrase edits to display text only.

    Used by factory_authoring.player_rules.build_player_text after its field
    projection. No edit means no change. Counts bind each edit to the current
    wording; a future source revision must review a stale phrase explicitly.
    Signed numbers and dice expressions cannot change through this seam.
    """
    spans = []
    numeric = re.compile(r"[+-]?\d+(?:d\d+)?(?:\.\d+)?", re.I)
    for pair in (edit or {}).get("player_replace") or []:
        old, new = pair["old"], pair["new"]
        if not old or type(pair.get("count")) is not int or pair["count"] < 1:
            raise ValueError("player_replace needs a nonempty phrase and a positive occurrence count")
        if numeric.findall(old) != numeric.findall(new):
            raise ValueError("player_replace cannot change numbers or dice")
        starts = _occurrences(text, old)
        if len(starts) != pair["count"]:
            raise ValueError(f"player_replace {old!r}: found {len(starts)} times, expected {pair['count']}")
        spans.extend((start, start + len(old), new) for start in starts)
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError("player_replace phrases overlap")
    for start, end, new in reversed(spans):
        text = text[:start] + new + text[end:]
    return text


def apply_edit(text: str, edit: dict[str, Any] | None) -> tuple[str, str, list[str]]:
    """(text after "remove", text after "remove" and "replace", problems). Problems name "replace" pairs not applied."""
    if not edit:
        return text, text, []
    for line in edit.get("remove") or []:
        text = text.replace(line + "\n", "").replace("\n" + line, "").replace(line, "")
    removed, problems = text, []
    for pair in edit.get("replace") or []:
        old, new = str(pair.get("old") or ""), str(pair.get("new") or "")
        count = text.count(old) if old else 0
        if count != 1:
            problems.append(f"replace {old!r}: found {count} times in the printed text (must be exactly once); not applied")
            continue
        text = text.replace(old, new)
    return removed, text, problems


def replacements(edit: dict[str, Any] | None) -> list[tuple[str, str]]:
    return [(str(pair.get("old") or ""), str(pair.get("new") or "")) for pair in (edit or {}).get("replace") or []]


def _changes(before: str, pairs: list[tuple[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Every changed number: its span in ``before``, old and new value, and whether it sits on a header line."""
    changes, problems = [], []
    for old, new in pairs:
        at = before.find(old)
        if at < 0 or before.count(old) != 1:
            continue  # apply_edit already reported it; nothing was changed
        old_parts, new_parts = _NUMBER.split(old), _NUMBER.split(new)
        old_numbers, new_numbers = _NUMBER.findall(old), _NUMBER.findall(new)
        if old_parts != new_parts or len(old_numbers) != len(new_numbers):
            problems.append(f"replace {old!r} -> {new!r} changes words, not only numbers: its typing cannot be carried")
            continue
        for found, value in zip(_NUMBER.finditer(old), new_numbers):
            if found.group() == value:
                continue
            start = at + found.start()
            line_start = before.rfind("\n", 0, start) + 1
            line = before[line_start:before.find("\n", start) if "\n" in before[start:] else len(before)]
            changes.append({"start": start, "end": at + found.end(), "old": found.group(), "new": value, "pair": (old, new),
                            "header": bool(_HEADER_LINE.match(line)), "covered": set()})
    return changes, problems


def _leaves(value: Any, path: tuple = ()) -> dict[tuple, Any]:
    if isinstance(value, dict):
        out: dict[tuple, Any] = {}
        for key, item in value.items():
            out.update(_leaves(item, path + (key,)))
        return out or {path: value}
    return {path: value}


def _get(node: Any, path: tuple) -> Any:
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return _MISSING
        node = node[key]
    return node


def _set(node: dict, path: tuple, value: Any) -> None:
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = value


_MISSING = object()


def _carry_headers(record: dict, parsed_before: dict, parsed_after: dict, changes: list[dict], problems: list[str]) -> None:
    changed_any = False
    for field in HEADER_FIELDS:
        before, after = _leaves(parsed_before.get(field)), _leaves(parsed_after.get(field))
        for path in sorted(set(before) | set(after), key=str):
            old_value, new_value = before.get(path, _MISSING), after.get(path, _MISSING)
            if old_value == new_value:
                continue
            full = (field,) + path
            current = _get(record, full) if path else record.get(field, _MISSING)
            if current is _MISSING and old_value is _MISSING or current == old_value:
                if new_value is _MISSING:
                    continue
                if path:
                    _set(record, full, copy.deepcopy(new_value))
                else:
                    record[field] = copy.deepcopy(new_value)
                changed_any = True
            else:
                problems.append(f"{field}{''.join(f'.{key}' for key in path)}: the typing says {current!r} where the printed header read "
                                f"{old_value!r}, so the edited header's {new_value!r} cannot be carried")
    if changed_any:
        for change in changes:
            if change["header"]:
                change["covered"].add("typed")


def _numeric_slots(node: dict) -> list[tuple[dict, str]]:
    """The int fields of an effect and of its plain sub-structures (dice, duration...), not of nested effects."""
    slots = []
    for key, value in node.items():
        if key in _SKIP_KEYS:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            slots.append((node, key))
        elif isinstance(value, dict) and "evidence" not in value:
            slots.extend(_numeric_slots(value))
    return slots


def _tables(node: dict, prefix: str = "") -> list[tuple[str, list[int]]]:
    """Numbers an effect keeps in a table (a list of ints or of int rows, e.g. dice_by_cl), which the carry cannot tell apart."""
    out = []
    for key, value in node.items():
        if key in _SKIP_KEYS:
            continue
        if isinstance(value, list) and value:
            flat = [item for row in value for item in (row if isinstance(row, list) else [row])]
            if all(isinstance(item, int) and not isinstance(item, bool) for item in flat):
                out.append((prefix + key, flat))
        elif isinstance(value, dict) and "evidence" not in value:
            out += _tables(value, prefix + key + ".")
    return out


def _requote(text: str, before: str, after: str, after_of: Callable[[int, int], str], changes: list[dict],
             problems: list[str]) -> tuple[str, list[dict]]:
    """``text`` re-quoted from the edited text if it quotes a changed number, and the changes it quotes. A string that is
    not a verbatim quote but contains a whole edited phrase ("Gain +3 AC (the GM's)") has the phrase replaced."""
    if not text or not any(change["old"] in text for change in changes):
        return text, []
    hits = []
    for index in _occurrences(before, text):
        inside = [change for change in changes if index <= change["start"] and change["end"] <= index + len(text)]
        cut = [change for change in changes if change["start"] < index + len(text) and index < change["end"] and change not in inside]
        if cut:
            problems.append(f"{text!r} cuts through the edited number {cut[0]['old']!r}")
            return text, []
        hits.append((index, inside))
    if not hits:  # a restatement, e.g. the rider "Cost: 2 Qi" for the printed "**Cost:** 2 Qi"
        inside = []
        for old, new in {change["pair"] for change in changes}:
            for said, meant in ((old, new), (_plain(old), _plain(new))):
                if said and said in text:
                    text = text.replace(said, meant)
                    inside += [change for change in changes if change["pair"] == (old, new)]
                    break
        return text, inside
    touching = [(index, inside) for index, inside in hits if inside]
    if not touching:
        return text, []
    if len(hits) > 1:
        problems.append(f"{text!r} is printed {len(hits)} times, so which one the edit changed is ambiguous")
        return text, []
    index, inside = touching[0]
    quoted = after_of(index, index + len(text))
    if quoted not in after:
        problems.append(f"{text!r} re-quoted as {quoted!r}, which the edited text does not print")
        return text, []
    return quoted, inside


def _plain(text: str) -> str:
    return text.replace("**", "").replace("`", "").strip()


def _occurrences(haystack: str, needle: str) -> list[int]:
    out, start = [], haystack.find(needle)
    while start >= 0:
        out.append(start)
        start = haystack.find(needle, start + 1)
    return out


def carry_typing(records: list[dict[str, Any]], before: str, after: str, pairs: list[tuple[str, str]],
                 parse: Callable[[str], dict[str, Any]] | None = None) -> list[str]:
    """Move the typing of ``before`` onto ``after`` in place (every record of one printed ability: the record and any
    split children). Returns the problems; an empty list means every changed number was carried."""
    changes, problems = _changes(before, pairs)
    if not changes:
        return problems or ["the edit changes no number"]

    def after_of(start: int, end: int) -> str:
        """The edited text of before[start:end] (the words are the same; only the changed numbers differ)."""
        out, cursor = [], start
        for change in sorted(changes, key=lambda row: row["start"]):
            if start <= change["start"] and change["end"] <= end:
                out += [before[cursor:change["start"]], change["new"]]
                cursor = change["end"]
        return "".join(out) + before[cursor:end]

    if parse is not None:
        parsed_before, parsed_after = parse(before), parse(after)
        for record in records:
            _carry_headers(record, parsed_before, parsed_after, changes, problems)

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for index, item in enumerate(node):
                if isinstance(item, str):
                    new, inside = _requote(item, before, after, after_of, changes, problems)
                    if inside:
                        node[index] = new
                        for change in inside:
                            change["covered"].add("text")
                else:
                    walk(item)
            return
        if not isinstance(node, dict):
            return
        quoted: list[dict] = []
        for key, value in list(node.items()):
            if key in _SKIP_KEYS:
                continue
            if isinstance(value, str):
                new, inside = _requote(value, before, after, after_of, changes, problems)
                if inside:
                    node[key] = new
                    quoted += inside
            else:
                walk(value)
        for change in {id(change): change for change in quoted}.values():
            slots = [(owner, key) for owner, key in _numeric_slots(node) if owner[key] == int(change["old"])]
            tables = [key for key, values in _tables(node) if int(change["old"]) in values]
            if tables:
                change["covered"].add("untyped")
                problems.append(f"{node.get('type') or 'one entry'} also keeps {change['old']} in a table ({', '.join(tables)}), "
                                f"which the carry cannot rewrite")
            elif len(slots) == 1:
                owner, key = slots[0]
                owner[key] = int(change["new"])
                change["covered"].add("typed")
            elif len(slots) > 1:
                problems.append(f"{len(slots)} fields of {node.get('type') or 'one entry'} hold {change['old']}: which one the edit "
                                f"changes is ambiguous ({', '.join(key for _owner, key in slots)})")
            elif node.get("type") in _TEXT_TYPES or not any(owner[key] for owner, key in _numeric_slots(node)):
                change["covered"].add("text")
            else:
                change["covered"].add("untyped")

    for record in records:
        walk(record)
    for change in changes:
        covered = change["covered"]
        if "typed" in covered or covered == {"text"}:
            continue
        where = before[max(0, change["start"] - 30):change["end"] + 30].replace("\n", " ")
        problems.append(f"{change['old']} -> {change['new']} in {where!r}: "
                        + ("quoted by a typed effect with no field holding it" if covered else "nothing in the typing holds or quotes it"))
    for record in records:
        for old, _new in pairs:
            if old and _mentions(record, old):
                problems.append(f"the typing still quotes {old!r} after carrying")
    return problems


def _mentions(node: Any, phrase: str) -> bool:
    if isinstance(node, str):
        return phrase in node
    if isinstance(node, dict):
        return any(_mentions(value, phrase) for key, value in node.items() if key not in _SKIP_KEYS)
    if isinstance(node, list):
        return any(_mentions(value, phrase) for value in node)
    return False
