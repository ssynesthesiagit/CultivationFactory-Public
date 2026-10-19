"""Bounded, reproducible Insight windows; ranking never changes legality.

Stage 1 and fresh character-creation requests use these windows. A window
holds at most thirty rows and stays inside the byte budget of
the old fifty-row prefix; required owner choices
repeat on each window and the rest follow in turn.

One oversized catalog row is isolated rather than fatal: its option text is
shortened to fit, and only a row that cannot be shortened enough is left out
of the windows while every other row stays reachable. Ranking is advisory --
it never changes which rows are eligible, so every eligible Insight that fits
appears on some window.
"""
from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

from app.core import FoundryError, canonical_json, sha256_json

_STOP = set("a an and as at by for from in is of on or the to with character cultivation insight".split())

#: Player-facing text appended to a shortened option.  It says what happened
#: and where the full text lives, in plain words, with no internal jargon.
SHORTENED_NOTE = "... (shortened to fit on one page; the full description is in this Insight's own entry.)"

#: Smallest share an option may be shortened to, so a shortened option still
#: says something. Never exceeds the window budget.
MIN_OPTION_BYTES = 512
PRESENTATION_FIELDS = frozenset({"name", "description", "display_name", "summary"})


def _words(value: Any) -> set[str]:
    return {word for word in re.findall(r"[^\W_]+", str(value).casefold()) if len(word) > 2 and word not in _STOP}


def _size(choice: dict) -> int:
    return len(canonical_json(choice).encode("utf-8"))


def _shorten_choice(choice: dict, budget: int) -> tuple[dict | None, bool]:
    """Return one option that fits ``budget`` bytes, or ``None``.

    Longest text first, so the option keeps every field and loses only the
    words needed to fit. Identifiers, authority and mechanics are never
    touched: a shortened option stays the same choice.
    """
    if _size(choice) <= budget:
        return choice, False
    compact = deepcopy(choice)
    text_fields = sorted(
        (key for key, value in compact.items() if key in PRESENTATION_FIELDS and isinstance(value, str) and value),
        key=lambda key: (-len(compact[key]), str(key)),
    )
    if not text_fields:
        return None, False
    for key in text_fields:
        text = compact[key]
        if _size(compact) <= budget:
            break
        low, high, best = 0, len(text), None
        while low <= high:
            middle = (low + high) // 2
            candidate = text[:middle].rstrip() + SHORTENED_NOTE
            compact[key] = candidate
            if _size(compact) <= budget:
                best = candidate
                low = middle + 1
            else:
                high = middle - 1
        if best is None:
            # Another presentation field may still occupy most of the row.
            # Keep this field short and try the next one before giving up.
            compact[key] = SHORTENED_NOTE if len(text) > len(SHORTENED_NOTE) else text
            continue
        compact[key] = best
    return (compact, True) if _size(compact) <= budget else (None, False)


@dataclass(frozen=True)
class InsightWindows:
    """A bounded chain of option windows plus what had to be adjusted."""

    windows: list[list[dict]] = field(default_factory=list)
    #: ``record_id`` -> shortened option, applied by the caller when it renders
    #: the window. Kept beside the records so the caller keeps building every
    #: option itself and only these rows differ.
    choice_overrides: dict[str, dict] = field(default_factory=dict)
    #: Rows that fit nowhere in the chain, in ranking order.
    omitted_record_ids: list[str] = field(default_factory=list)
    shortened_record_ids: list[str] = field(default_factory=list)

    def page(self, page: int) -> list[dict]:
        if type(page) is not int or page < 0:
            raise FoundryError("STAGE1_INSIGHT_PAGE_INVALID", "Choose an Insight options page starting at zero.")
        if page >= len(self.windows):
            raise FoundryError("STAGE1_INSIGHT_PAGE_EMPTY", "There are no more Insight options pages.",
                               details={"page_count": len(self.windows)})
        return self.windows[page]


def insight_windows(records: list[dict], *, project: dict, effective_by_id: dict,
                    preferred: dict[str, int], linked: set[str], required: list[str],
                    limit: int, choice: Callable) -> InsightWindows:
    """Return the bounded window chain for the eligible Insight rows.

    Explicit preferences and linked Origins precede lexical relevance to the
    concept and locked choices. Hash sorting supplies a platform-independent
    seeded permutation. No relevance score can exclude an eligible row.
    """
    locks = {row.get("field"): row.get("value") for row in project.get("user_locks", [])}
    seed = locks.get("character_creation.autogen_seed") or project["project_id"]
    context = [locks.get(key, "") for key in ("concept", "character.identity.concept", "owner_descriptive_fields.concept")]
    for ids in (locks.get("character_sheet.locked_choices") or {}).values():
        for record_id in ids if isinstance(ids, list) else [ids]:
            row = effective_by_id.get(record_id, {}) if isinstance(record_id, str) else {}
            context.extend([row.get("display_name", ""), row.get("tags", [])])
    words = _words(" ".join(map(str, context)))
    legacy = sorted(records, key=lambda row: (0 if row["record_id"] in preferred else 1,
                    preferred.get(row["record_id"], 10**9), row["record_id"]))
    # Bound each display window, not the complete frozen catalog. Capping the
    # chain here would silently remove fitting options from every continuation.
    budget = sum(_size(choice(row)) for row in legacy[:limit])

    def rank(row):
        record_id = row["record_id"]
        relevant = _words(" ".join(str(row.get(key, "")) for key in ("display_name", "summary", "tags", "dependencies")))
        return (0 if record_id in preferred else 1, preferred.get(record_id, 10**9),
                0 if record_id in linked else 1, -len(words & relevant),
                sha256_json({"seed": seed, "context": sorted(words), "record_id": record_id}))

    ordered = sorted(records, key=rank)
    ceiling = min(limit, 30)
    # One option may never claim the whole window: a single long row is
    # shortened to its own share of the budget, so it cannot crowd out every
    # other option or leave a page half empty.
    option_budget = min(budget, max(MIN_OPTION_BYTES, budget // ceiling))
    overrides: dict[str, dict] = {}
    shortened: list[str] = []
    omitted: list[str] = []
    fitted: list[tuple[dict, int]] = []
    for row in ordered:
        record_id = row["record_id"]
        original = choice(row)
        rendered, was_shortened = (original, False) if _size(original) <= budget else _shorten_choice(original, option_budget)
        if rendered is None:
            rendered, was_shortened = _shorten_choice(original, budget)
        if rendered is None:
            omitted.append(record_id)
            continue
        if was_shortened:
            overrides[record_id] = rendered
            shortened.append(record_id)
        fitted.append((row, _size(rendered)))
    pinned = [entry for entry in fitted if entry[0]["record_id"] in required]
    rest = [entry for entry in fitted if entry[0]["record_id"] not in required]
    # Reserve room for the largest ordinary row as well as a row-count slot.
    # Required rows that cannot repeat beside it remain offered once in rest.
    while pinned and (
        len(pinned) >= ceiling
        or sum(size for _, size in pinned) + max((size for _, size in rest), default=0) > budget
    ):
        rest.insert(0, pinned.pop())
    pinned_bytes = sum(size for _, size in pinned)
    windows: list[list[dict]] = []
    current: list[dict] = []
    used = 0
    for row, size in rest:
        # Close the window before the row that would not fit beside it. Every
        # window also repeats the required rows, so they are charged here too.
        if current and (len(current) + len(pinned) >= ceiling or used + size + pinned_bytes > budget):
            windows.append(current)
            current, used = [], 0
        current.append(row)
        used += size
    if current or not windows:
        windows.append(current)
    pages: list[list[dict]] = []
    for window in windows:
        present = {row["record_id"] for row in window}
        repeat = [entry[0] for entry in pinned if entry[0]["record_id"] not in present]
        pages.append([*repeat, *window])
    return InsightWindows(windows=pages, choice_overrides=overrides,
                          omitted_record_ids=omitted, shortened_record_ids=shortened)


def starting_at(windows: list[list[dict]], page: int) -> list[dict]:
    """Flatten the chain, rotated so ``page`` is the window read first.

    Required rows repeat on every window; the flattened result keeps each one
    only once so the frozen option list stays the size of the chain. A page
    past the end of the chain is refused rather than wrapped, so asking for a
    window that was never published is an error the caller can report instead
    of silently offering the first window again.
    """
    if not windows:
        return []
    if type(page) is not int or page < 0:
        raise FoundryError("STAGE1_INSIGHT_PAGE_INVALID", "Choose an Insight options page starting at zero.")
    if page >= len(windows):
        raise FoundryError("STAGE1_INSIGHT_PAGE_EMPTY", "There are no more Insight options pages.",
                           details={"page_count": len(windows)})
    ordered: list[dict] = []
    seen: set[str] = set()
    for window in windows[page:] + windows[:page]:
        for row in window:
            if row["record_id"] not in seen:
                seen.add(row["record_id"])
                ordered.append(row)
    return ordered
