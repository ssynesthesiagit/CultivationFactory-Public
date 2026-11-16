"""Brute: Get Over Here -- a shove made through a tether (AUTO107, 2026-10-05).

Printed text (APP/authority/typed_mechanics/rules_text.json TAL_BRUTE_GET_OVER_HERE):

  #### Get Over Here
  When you control one end of a tether attached to a creature, make shove attempts against it as though it were within
  reach. Examples: net; lasso; rope; chain; whip; grappling hook; tether technique.
  On a success, move the target toward you instead of away.
  When using Shove Aside, movement must still bring the target at least diagonally closer.
  Apply Manhandle talents normally, but talents requiring natural reach function only if the target ends within natural reach.

What runs here, and why each part is where it is:

- The shove itself is combat/ext/brute_shove.py's Brutal Shove (the Strength (Athletics) contest), not a second contest
  implementation. This module compiles extra buttons whose ``brutal_shove`` row carries the two printed differences:
  ``direction: "toward"`` ("move the target toward you instead of away") and ``tether: true`` (the Shove Aside
  restriction). One Brutal Shove, one contest, two printed directions -- the row carries the direction rather than the
  shove module hard-coding one.
- "When you control one end of a tether attached to a creature" is a printed qualification, so it is asked per target
  rather than assumed: ``tether_admitted`` (the ``candidate_allowed`` hook) offers the buttons only against a creature a
  tether the owner controls is actually attached to, and only while that creature is within the tether's own length.
  The reach is therefore the tether's, read through the one shared seam every sphere's tether shape already uses
  (``move_limits.tether_to``; the Chains sphere's Bound rows and Meridian Tether are read by that same function), not a
  number this module invented. No tether, no button: the printed text grants nothing until one exists.
- "Apply Manhandle talents normally" is the ordinary Brute menu, so the talent variants are compiled too: one button per
  Manhandle talent the owner knows, each carrying that talent's own compiled ``on_success`` rows -- the same rows the
  ordinary "Brutal Shove + <talent>" button runs, so one talent has one implementation and its printed reach requirement
  ("if the target remains within reach", Takedown) is checked on the target's square after the pull, exactly as usual.
  A talent that needs the creature within natural reach therefore works only when the pull actually ends it there.
- Shove Aside is a Brute Maneuvers option, not part of this talent ("When using Shove Aside" only says what changes if
  the character has it), so the aside button is compiled only for a creature that owns BRUTE_BASE_BRUTE_MANEUVERS.
- TETHER_REACH_FT is only the widest reach any tether in this game can have (Chains' longest printed Tether is 30 feet),
  so the legal-target listing is not cut short before the real per-tether check runs. The limit the player feels is the
  tether's own length, from tether_admitted.

Inert for everyone else: every hook returns early unless the actor owns TAL_BRUTE_GET_OVER_HERE and is a Brute, and the
buttons are compiled only for such a creature, so other creatures and saved fights are untouched.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from . import hook
from .move_limits import tether_to

BRUTE = "tianxia.sphere.brute"
BRUTAL_SHOVE = "BRUTE_BASE_BRUTAL_SHOVE"
MANEUVERS = "BRUTE_BASE_BRUTE_MANEUVERS"
GET_OVER_HERE = "TAL_BRUTE_GET_OVER_HERE"
TETHER_REACH_FT = 120  # the widest listing reach; the real limit is the tether's own length (tether_admitted)

_PLAIN_BUTTONS = (
    # (suffix, display name, extra row fields, required owning talent)
    ("tether_shove", "Get Over Here: Shove", {"direction": "toward", "tether": True}, None),
    ("tether_shove_aside", "Get Over Here: Shove Aside", {"mode": "aside", "tether": True}, MANEUVERS),
)

_EXPLANATION = (
    "Get Over Here: shove a creature your tether is attached to, from as far away as your tether reaches, and drag it "
    "toward you instead of pushing it away. Shove Aside must still bring it diagonally closer. Manhandle talents that "
    "need the creature within your natural reach only work if the pull ends it there."
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def _shove_row(action: Any) -> dict[str, Any] | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
    if typed.get("source") != BRUTAL_SHOVE:
        return None
    return next((e for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "brutal_shove"), None)


@hook("compile_actions")
def tether_buttons(info: dict[str, Any]) -> list[Any] | None:
    """Get Over Here's buttons for a creature that owns the talent: the two printed differences of an ordinary Brutal
    Shove, plus one per Manhandle talent the creature knows ("Apply Manhandle talents normally"). The contest, the size
    limit, Hammer, Crushing Collision, Dominoes, Break Defenses, Focused Might and each talent's own rows all come from
    the ordinary Brutal Shove rows they are copied from, so there is one implementation of each."""
    if BRUTE not in set(info.get("spheres") or ()) or GET_OVER_HERE not in set(info.get("owned_ids") or ()):
        return None
    owned = set(info.get("owned_ids") or ())
    actions = list(info.get("actions") or ())
    base = next((a for a in actions
                 if _shove_row(a) is not None and " + " not in a.display_name and "#" not in a.source_definition_id), None)
    if base is None:
        return None
    # Each Manhandle talent the creature knows, as the ordinary "Brutal Shove + <talent>" button the compiler produced.
    talents = [(a.display_name.split(" + ", 1)[1], _shove_row(a)) for a in actions
               if " + " in a.display_name and "#" not in a.source_definition_id and _shove_row(a) is not None
               and _shove_row(a).get("on_success")]
    out = []
    buttons = list(_PLAIN_BUTTONS) + [(f"tether_shove_{_slug(name)}", f"Get Over Here: Shove + {name}", None, None)
                                     for name, _ in talents]
    for suffix, label, fields, requires in buttons:
        if requires is not None and requires not in owned:
            continue
        params = copy.deepcopy(base.parameters)
        row = next((e for e in params["typed"].get("effects") or []
                    if isinstance(e, dict) and e.get("type") == "brutal_shove"), None)
        if row is None:
            continue
        # Every button is this talent's shove: the same two printed differences, on the plain shove and on each Manhandle
        # talent's. A Shove Aside additionally keeps the printed size limit and its own disadvantage (or Alternative
        # Maneuvers' exemption, which combat/ext/brute_shove.py reads from the character's own row).
        row.update({"direction": "toward", "tether": True, **(fields or {})})
        for name, talent_row in talents:  # "Apply Manhandle talents normally": this talent's own compiled rows
            if suffix == f"tether_shove_{_slug(name)}":
                row["on_success"] = copy.deepcopy(talent_row.get("on_success"))
        out.append(base.model_copy(update={
            "source_definition_id": base.source_definition_id + f"#{suffix}",
            "display_name": label,
            "range_ft": TETHER_REACH_FT,
            "parameters": {**params, "brute_tether": True, "description": _EXPLANATION}}))
    return out


@hook("candidate_allowed")
def tether_admitted(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """"When you control one end of a tether attached to a creature" -- the printed admission and reach, asked of the
    creature this candidate names: it must carry a tether the actor controls, and be within that tether's own length."""
    if not ((getattr(action, "parameters", None) or {}).get("brute_tether")):
        return None
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if target is None:
        return None
    feet = tether_to(engine, actor, target)
    if feet is None:
        return False  # no tether of the actor's is attached to that creature: nothing to shove it with
    return None if engine._distance_actor_to_actor(actor, target) <= feet else False