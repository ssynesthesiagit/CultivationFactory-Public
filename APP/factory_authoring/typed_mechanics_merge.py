"""Merge one mechanic's parser, reviewed and model typing (no model logs named here; tests import it directly)."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def _coverage(effects: list, riders: list) -> str:
    return "FULL" if effects and not riders else "CORE_WITH_RIDERS" if effects else "RIDERS_ONLY"


def _validate(effect: dict, source_text: str) -> str | None:
    """The model tool's validator, re-applied at merge time (rules may have tightened since)."""
    sys.path.insert(0, str(APP / "tools"))
    from type_mechanics_with_model import validate

    return validate(effect, source_text)


def merge(mechanic: dict, proposal: dict | None, review: dict | None, stale: bool, source_text: str | None = None) -> dict:
    """Parser output, then the reviewed or the unchecked model typing for the same printed text."""
    parser_effects = [{**effect, "origin": "parser"} for effect in mechanic["effects"]]
    if review and review.get("replaces_parser"):
        # A checked correction that stands on its own (owner 2026-09-26: Flowing Response's parser read
        # "knocked Prone" out of its own trigger wording and knocked the attacker Prone).
        parser_effects = []
    mechanic = {**mechanic, "effects": parser_effects}
    inferred = mechanic["activation"]["economy"] in {"passive", "reaction"} and not mechanic.get("header_economy")
    if review:
        added = [{**effect, "origin": "reviewed"} for effect in review.get("effects", [])]
        mechanic["riders"] = list(review.get("riders", []))
        if review.get("activation"):
            mechanic["activation"] = {**mechanic["activation"], **review["activation"]}
        for key in ("range", "area", "cost"):  # a review may also correct what the parser read from the header
            if review.get(key) is not None:
                mechanic[key] = review[key]
        status = "checked"
    elif proposal:
        seen = {(effect.get("type"), effect.get("evidence")) for effect in parser_effects}
        added = [{**effect, "origin": "model"} for effect in proposal.get("accepted", [])
                 if (effect.get("type"), effect.get("evidence")) not in seen
                 and (source_text is None or _validate(effect, source_text) is None)]
        mechanic["riders"] = list(proposal.get("still_untyped") or [])
        if inferred and proposal.get("economy"):
            mechanic["activation"] = {**mechanic["activation"], "economy": proposal["economy"],
                                      "trigger": proposal.get("trigger") or mechanic["activation"].get("trigger"),
                                      "modifies": proposal.get("modifies"), "source": "model"}
        status = "model_unchecked"
    else:
        added = []
        status = "stale_model" if stale else "parser_only"
    mechanic["effects"] = parser_effects + added
    if source_text:
        from factory_authoring.typed_mechanics import apply_cl_scaling

        apply_cl_scaling(mechanic, source_text)
    mechanic["coverage"] = _coverage(mechanic["effects"], mechanic["riders"])
    mechanic["typing_status"] = status
    return mechanic
