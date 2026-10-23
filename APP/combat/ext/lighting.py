"""Light's rule hooks (FD-19; the contract is docs/specs/LIGHTING_SPEC.md §5.1 and §5.3).

The model itself is combat/lighting.py: one level per square, one resolved level per viewer, no rules here. This
plug-in answers the two places a fight asks a question the model cannot answer on its own -- the sight checks Dim
Light makes harder -- and nothing else.

Hooks: ability_check_hazard_mode, ability_check_mode, search_mode. No state, no saved fields, no lock or choice-authority edits. A fight on
a map that declares no light and whose creatures carry none answers None to both, so every check resolves exactly as
its print says.
"""

from __future__ import annotations

from typing import Any

from . import hook


def _check_uses_sight(engine: Any, actor: Any) -> bool:
    """Explicitly nonvisual check provenance is not changed by dim light; unmarked checks use ordinary sight."""
    from ..check_context import current

    senses = current(engine, actor).get("senses")
    return not isinstance(senses, (list, tuple, set)) or not senses or "sight" in senses


@hook("ability_check_hazard_mode")
def dim_sight_check(engine: Any, actor: Any, ability: str, skill: Any, against: Any, hazards: Any) -> str | None:
    """A Wisdom (Perception) check made from Dim Light is at Disadvantage (spec §2.6, §5.3 row 8).

    The caller has already named this check's hazards, and this answer joins them as one more printed contribution, so
    the ordinary combination and cancellation apply unchanged. Any other skill, Bright Light, and every map with no
    light data answer None.
    """
    if str(skill or "") != "Perception" or not _check_uses_sight(engine, actor):
        return None
    from .. import lighting

    return "DISADVANTAGE" if lighting.perception_mode(engine, actor) == "DISADVANTAGE" else None


@hook("ability_check_mode")
def dim_perception_check(engine: Any, actor: Any, ability: str, skill: Any, against: Any) -> str | None:
    """The same Dim Light rule for an ordinary sight Perception check that names no hazard (spec §2.6, §5.3 row 8).

    ability_check_hazard_mode runs only for a check that names hazards, so Analyze's Wisdom (Perception) roll, which
    supplies the target and no hazards, is answered here. check_modes unions the answers, so a check that gets both
    still resolves to one Disadvantage.
    """
    if str(skill or "") != "Perception" or not _check_uses_sight(engine, actor):
        return None
    from .. import lighting

    return "DISADVANTAGE" if lighting.perception_mode(engine, actor) == "DISADVANTAGE" else None


@hook("search_mode")
def dim_search(engine: Any, actor: Any) -> str | None:
    """The same rule for the Search and Sweep actions (spec §5.3 row 9: stealth.search_modes).

    check_modes runs the hazard hook only for a check that names hazards, and an ordinary Search names none, so this
    is the documented seam that can answer for one without editing check_mode or check_modes.
    """
    from .. import lighting

    return "DISADVANTAGE" if lighting.perception_mode(engine, actor) == "DISADVANTAGE" else None
