"""Effective size for size comparisons: "count as one size larger" (rider lane C12, 2026-09-30 -- shared helper and seam).

Many printed lines change only the size a creature counts as, never its footprint: "You count as one size larger when resisting
Shove, Grapple, forced movement, and effects that would knock you Prone" (Body Heavying), "count as two sizes larger for
resisting forced movement" (Mountain Body CL 5, Moon-Weight Incarnation), "count as one size larger for Shove, Grapple, and
Overrun" (Brute, Wrestling, Body Refining subpaths). The table compared footprint widths inline (typed_executor's save and push
size limits), so none of them could run. typed_executor now asks ``cells`` here instead, at exactly those comparisons:

  cells(engine, actor, role, purposes)   footprint width in squares + the size steps that apply
      role      "resist"   the creature a shove, grapple, push/pull or knock-Prone is aimed at
                "act"      the creature doing it (its size limit: "a creature no more than one size larger than you")
      purposes  what the effect does, from its own rows (``purposes_of``): "forced" (a push or pull), "prone", "grapple",
                and "shove" (a push or a knock-Prone counts as a Shove's outcome)

The ``size_steps(engine, actor, role, purposes)`` hook supplies the steps. An answer is an int (whole sizes) -- these
stack across distinct features; each owner combines its own replacements ("two sizes larger rather than one") -- or
{"steps": n, "additional": m}, where ``additional`` is a printed additional step. Owners answer only for their own abilities and
conditions (combat/ext/gravity.py: Body Heavying, Mountain Body, Moon-Weight Incarnation). A creature with no step has exactly
its footprint width, so every other comparison is unchanged.

Native dynamic_size owns footprint growth; this helper adds functional steps only.
Typed save and movement size limits, including Brutal Shove and Overrun, use it.
Width is counted in squares, as the existing comparisons did (Tiny/Small/Medium all one square).
"""

from __future__ import annotations

from typing import Any, Iterable

from . import run


def purposes_of(effects: Any) -> set[str]:
    """What a save's failure (or an effect list) would do that size can resist."""
    from ..typed_executor import _walk_rows

    rows = (effects.get("on_fail") or []) if isinstance(effects, dict) and effects.get("type") == "save" else (
        [effects] if isinstance(effects, dict) else list(effects or []))
    found: set[str] = set()
    for row in _walk_rows(rows):
        kind = row.get("type")
        if kind == "forced_movement":
            found |= {"forced", "shove"}
        elif kind == "brutal_shove":
            found |= {"shove", "brutal_shove"}
        elif kind == "brute_overrun":
            found.add("overrun")
        elif kind in ("condition", "ongoing"):
            name = str(row.get("base_condition") or row.get("condition") or "").lower()
            if name == "prone":
                found |= {"prone", "shove"}
            elif name == "grappled":
                found.add("grapple")
    return found


def steps(engine: Any, actor: Any, role: str, purposes: set[str]) -> int:
    if actor is None:
        return 0
    plain, extra = 0, 0
    for answer in run("size_steps", engine, actor, role, frozenset(purposes)):
        if isinstance(answer, dict):
            plain += max(0, int(answer.get("steps") or 0))
            extra += max(0, int(answer.get("additional") or 0))
        elif type(answer) is int:
            plain += max(0, answer)
    return max(0, plain) + extra


def cells(engine: Any, actor: Any, role: str, purposes: set[str]) -> int:
    width = int(engine._footprint(actor).width_cells)
    return width + steps(engine, actor, role, purposes) if purposes else width


def rank(engine: Any, actor: Any, role: str, purposes: set[str]) -> int:
    """Current printed size ordinal plus qualified functional steps.

    Relative category limits distinguish Tiny/Small/Medium despite their shared
    one-square footprint. Width-based absolute limits keep using cells.
    Legacy query fixtures without recorded categories retain width differences.
    """
    from ..dynamic_size import CATEGORIES, current_category
    if hasattr(engine, 'actor_footprints') and hasattr(actor, 'size_category'):
        actual = CATEGORIES.index(current_category(engine, actor))
    else:
        actual = min(5, int(engine._footprint(actor).width_cells) + 1)
    return actual + steps(engine, actor, role, purposes)
