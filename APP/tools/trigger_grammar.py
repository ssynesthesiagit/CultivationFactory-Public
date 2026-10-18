"""Canonical trigger grammar and its validator (owner 2026-09-26; no model logs named here, so tests may import it)."""
from __future__ import annotations

import hashlib
import re

EVENTS = [
    "attacked", "hit", "missed", "damaged", "drop_to_zero", "bloodied",
    "save_made", "save_failed", "save_succeeded", "condition_gained",
    "technique_targets", "technique_used", "critical_hit", "natural_1",
    "moved", "own_action", "other",
]
CONFIDENCES = ("high", "medium", "low")


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def validate(result: dict, mechanic_id: str, name: str, original_trigger: str) -> tuple[dict, list[str]]:
    """The grounded fields for one answer, and rejection reasons (kept in the row for review)."""
    rejected: list[str] = []
    lowered = original_trigger.lower()
    event = str(result.get("event") or "other").strip().lower()
    if event not in EVENTS:
        rejected.append(f"event '{event}' not in the canonical list")
        event = "other"
    range_ft = result.get("range_ft")
    if isinstance(range_ft, bool) or not isinstance(range_ft, int):
        range_ft = None
    if range_ft is not None and str(range_ft) not in original_trigger:
        rejected.append(f"range_ft {range_ft} not printed in the trigger text")
        range_ft = None
    attack_filter = str(result.get("attack_filter") or "none").strip().lower()
    if attack_filter not in ("melee", "ranged", "none") or attack_filter not in lowered:
        if attack_filter != "none":
            rejected.append(f"attack_filter '{attack_filter}' not printed in the trigger text")
        attack_filter = "none"
    mark_name = str(result.get("mark_name") or "").strip()
    if mark_name and mark_name.lower() not in lowered:
        rejected.append(f"mark_name '{mark_name}' not printed in the trigger text")
        mark_name = ""
    condition = str(result.get("condition") or "").strip()
    if condition and re.sub(r"\s+", " ", condition.lower()) not in re.sub(r"\s+", " ", lowered):
        rejected.append("condition not printed in the trigger text")
        condition = ""
    confidence = str(result.get("confidence") or "low").strip().lower()
    if confidence not in CONFIDENCES:
        rejected.append(f"confidence '{confidence}' not high/medium/low")
        confidence = "low"
    intent_changed = bool(result.get("intent_changed", False))
    normalized_trigger = str(result.get("normalized_trigger") or "").strip()
    if not normalized_trigger.lower().startswith("when"):
        rejected.append("normalized_trigger does not start with 'When'")
        confidence = "low"
    if rejected:
        confidence = "low"
    checked = {
        "normalized_trigger": normalized_trigger or original_trigger, "event": event,
        "subject": str(result.get("subject") or "").strip(), "range_ft": range_ft,
        "attack_filter": attack_filter, "condition": condition, "mark_name": mark_name,
        "extra_conditions": str(result.get("extra_conditions") or "").strip(),
        "intent_changed": intent_changed or bool(rejected), "confidence": confidence,
        "note": str(result.get("note") or "").strip(),
    }
    return checked, rejected
