"""Convert complete, source-checked header restatements, never combat rules.

Used by rider_pattern_conversions. Bookkeeping is preserved verbatim as header
metadata. Combat headers are retired only for simple shapes actually consumed
by the ordinary action compiler and only when the existing field already
represents the entire printed value. Unknown, compound and nested rules stay.
"""
from __future__ import annotations

import copy
import re

from factory_authoring.typed_mechanics import _area, _cost, _duration, _economy, _range, _use_limit, parse_header


def _norm(value: str) -> str:
    return " ".join(value.replace("**", "").replace("`", "").split()).casefold().removesuffix(".").strip()


# Restrict these to shapes whose full meaning survives the corresponding parser
# and whose typed representation is consumed by the normal action compiler.
_COST = re.compile(r"(?:\d+|PB)\s+(?:CP|Qi|Stamina|Resonance|Martial Focus)(?:\s+(?:or|and)\s+(?:\d+|PB)\s+(?:CP|Qi|Stamina|Resonance|Martial Focus))*|expend martial focus", re.I)
_RANGE = re.compile(r"(?:\d+\s+(?:feet|ft)|self|touch|weapon reach|reach)", re.I)
_AREA = re.compile(r"\d+-foot(?:-radius)?\s+(?:sphere|cone|line|cube|emanation|aura|cylinder|radius|square)(?:\s+(?:centered on you|from you))?", re.I)
_DURATION = re.compile(r"(?:(?:concentration\s*,?\s*)?up to\s+)?\d+\s+(?:rounds?|minutes?|hours?|days?)|instant(?:aneous)?", re.I)
_LIMIT = re.compile(r"once per (?:short or long rest|short rest|long rest|scene|combat|fight|encounter|day|week)", re.I)
_TIME = re.compile(r"\d+\s+(?:minutes?|hours?|days?)", re.I)
_RARITY = re.compile(r"common|uncommon|rare|very rare|legendary", re.I)
_RUNTIME_PREREQUISITE = re.compile(r"\b(?:target|creature|subject|self|GM|DC|permission|approval|when|while|during|within|unless|must|cooperating|wielding|wearing|carrying|held|active)\b", re.I)


def _parts(rider: object) -> tuple[str, str] | None:
    if not isinstance(rider, str) or "\n" in rider or "\r" in rider:
        return None
    line = rider.strip().replace("**", "").replace("`", "")
    match = re.fullmatch(r"([A-Za-z ]+):\s*(\S(?:.*\S)?)", line)
    if not match:
        return None
    return match[1].strip().lower(), match[2].strip()


def _plain_cost(value: list) -> list:
    # Omitted amount_formula=None is the same typed cost; no other cost keys
    # may disappear in the comparison.
    return [[{k: v for k, v in part.items() if not (k == "amount_formula" and v is None)}
             for part in option] for option in value]


def admission(mechanic: dict, source_text: str, rider: object) -> tuple[str, dict | None]:
    """Return (reason, receipt data) for one whole top-level candidate.

    The caller binds the complete source SHA and input digest; this check also
    requires the complete rider to be an actual source line and a primary header.
    """
    parts = _parts(rider)
    if not parts:
        return "compound or unsupported", None
    label, value = parts
    if not any(_norm(line) == _norm(str(rider)) for line in source_text.splitlines()):
        return "not an exact source line", None
    raw = value.removesuffix(".").strip()
    header, _ = parse_header(source_text.splitlines())
    bookkeeping = {
        "prerequisite": ("prerequisite", "prerequisite"),
        "prerequisites": ("prerequisite", "prerequisite"),
        "time": ("preparation_time", "preparation_time"),
        "rarity": ("rarity", None),
    }
    if label in bookkeeping:
        field, header_key = bookkeeping[label]
        if label.startswith("prerequisite"):
            # Reject sentences and fight-time eligibility even if labelled as a
            # prerequisite. Character-acquisition text is retained verbatim.
            if re.search(r"[;:.!?]", raw) or _RUNTIME_PREREQUISITE.search(raw):
                return "compound or runtime prerequisite", None
        elif label == "time" and not _TIME.fullmatch(raw):
            return "compound or unsupported", None
        elif label == "rarity":
            if not _RARITY.fullmatch(raw):
                return "compound or unsupported", None
            # Rarity is ignored by the parser. Accept it only in the initial
            # stat block, not a later ingredient or sub-ability's header.
            lines = [line for line in source_text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
            if not any(_norm(line) == _norm(str(rider)) for line in lines[:4]):
                return "not a primary header", None
        if header_key and _norm(header.get(header_key) or "") != _norm(value):
            return "not a primary header", None
        current = mechanic.get(field)
        if current and (not isinstance(current, str) or _norm(current) != _norm(value)):
            return "field differs", None
        return "admitted", {"field": field, "value": value, "pattern": "header_prerequisite" if field == "prerequisite" else "header_downtime",
                            "engine_seam": "printed catalog / authoring metadata"}

    fields = {
        "cost": ("cost", "cost", "header_cost", "combat.factory_compiler._costs_and_ways"),
        "use limit": ("use_limit", "use_limit", "header_limit", "combat.factory_compiler._fight_limited"),
        "limit": ("use_limit", "use_limit", "header_limit", "combat.factory_compiler._fight_limited"),
        "range": ("range", "range", "header_range_target", "combat.factory_compiler._target_kind/_reach_feet"),
        "area": ("area", "area", "header_range_target", "combat.factory_compiler._aimed_area"),
        "duration": ("duration", "duration", "header_duration", "combat.factory_compiler and combat.typed_executor"),
        "action type": ("activation", "action_type", "header_activation", "combat.factory_compiler compile actions"),
    }
    if label not in fields:
        return "unsupported header", None
    field, header_key, pattern, seam = fields[label]
    if _norm(header.get(header_key) or "") != _norm(value):
        return "not a primary header", None
    current = mechanic.get(field)
    if not current:
        return "field empty", None
    activation = mechanic.get("activation") or {}
    if label == "cost":
        if not _COST.fullmatch(raw):
            return "compound or unsupported", None
        expected = _cost(raw)
        if not isinstance(current, list) or _plain_cost(current) != _plain_cost(expected):
            return "field differs", None
    elif label in {"use limit", "limit"}:
        if not _LIMIT.fullmatch(raw):
            return "compound or unsupported", None
        if current != _use_limit(raw):
            return "field differs", None
    elif label == "range":
        if not _RANGE.fullmatch(raw):
            return "compound or unsupported", None
        if current != _range(raw):
            return "field differs", None
    elif label == "area":
        if not _AREA.fullmatch(raw):
            return "compound or unsupported", None
        expected = _area(raw)
        if not isinstance(current, dict) or {k: v for k, v in current.items() if k != "printed_recipient_seal"} != expected:
            return "field differs", None
    elif label == "duration":
        if not _DURATION.fullmatch(raw):
            return "compound or unsupported", None
        # A separate Concentration header participates in the same field.
        if current != _duration(raw, header.get("concentration")):
            return "field differs", None
    elif label == "action type":
        if raw.casefold() not in {"action", "bonus action"}:
            return "compound or unsupported", None
        if activation.get("economy") != _economy(raw):
            return "field differs", None
    # Modifiers, passives, reactions and rituals have separate compilation or
    # eligibility paths; field presence alone does not prove their execution.
    if (activation.get("economy") not in {"action", "bonus_action"} or mechanic.get("modifier")
            or not (mechanic.get("effects") or mechanic.get("options"))):
        return "unsupported execution path", None
    return "admitted", {"field": field, "value": value, "pattern": pattern, "engine_seam": seam}


def convert(mechanic: dict, source_text: str) -> tuple[dict, list[dict]]:
    """Preserve other fields and emit a receipt for every removed rider."""
    result = copy.deepcopy(mechanic)
    kept, receipts = [], []
    for index, rider in enumerate(result.get("riders") or []):
        reason, match = admission(result, source_text, rider)
        if reason != "admitted":
            kept.append(rider)
            continue
        field, value = match["field"], match["value"]
        if field in {"prerequisite", "preparation_time", "rarity"} and not result.get(field):
            result[field] = value
        receipts.append({
            "pattern": match["pattern"], "rider": rider, "path": f"/riders/{index}",
            "effect_paths": [f"/{field}"], "engine_seam": match["engine_seam"],
            "behavior": "verified_restatement",
        })
    result["riders"] = kept
    return result, receipts
