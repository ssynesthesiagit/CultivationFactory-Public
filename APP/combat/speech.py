"""Silenced (owner 2026-09-29: silencing made real). A Silenced creature cannot speak clearly or provide Verbal components,
so it cannot use an ability that needs its own voice -- a roar, kiai, shout, chant, song, spoken command or Verbal
component. The abilities that do are listed in combat/rules/speech.json ("needs_voice": record id -> why, and the
options that need it when only some do); the Pressure Points talents that silence (Breath Seal, Locked Breath Method,
The Point Between Heartbeats, Pressure-Point Strike's whisper) give the condition, and Speech-Knot Point makes the next
voiced ability a saving throw (combat/ext/speech.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SILENCED = "condition:typed.silenced"
SPEECH_KNOT = "condition:typed.speech_knot"
_RULES = Path(__file__).resolve().parent / "rules" / "speech.json"
_cache: dict[str, Any] = {}


def rules() -> dict[str, Any]:
    stamp = _RULES.stat().st_mtime if _RULES.is_file() else 0
    if _cache.get("stamp") != stamp:
        _cache.update(stamp=stamp, rules=json.loads(_RULES.read_text(encoding="utf-8")) if _RULES.is_file() else {})
    return _cache["rules"]


def silenced(actor: Any) -> bool:
    """Silenced, or inside an area whose rule silences (rider lane 9: Quiet Mandate Edict's zone "inside" rule {"silenced": true})."""
    from .typed_executor import condition_rules

    return any(condition.condition_id == SILENCED for condition in actor.conditions.values()) or any(
        rule.get("silenced") for rule in condition_rules(actor))


def _record(action: Any) -> tuple[str, str]:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    return str(typed.get("option_of") or typed.get("source") or ""), str(typed.get("option_label") or "")


def needs_voice(action: Any) -> bool:
    """Whether using this action needs its user's voice."""
    record, option = _record(action)
    return record_needs_voice(record, option)


def record_needs_voice(record: str, option: str = "") -> bool:
    """Whether the ability named by (record, option) needs its user's own voice.

    The same test ``needs_voice`` gives an action, for a caller that holds only the compiled
    typed row: a reaction whose printed trigger is "a creature ... speaks a command word, uses a
    Voice talent, casts a spell with a verbal component, or begins a supernatural chant" asks
    whether the ability that just started was spoken (combat/typed_reactions.on_technique_start).
    """
    entry = (rules().get("needs_voice") or {}).get(str(record or ""))
    if not entry:
        return False
    options = entry.get("options")
    return not options or str(option or "") in options


def row_needs_voice(row: dict[str, Any]) -> bool:
    """A Reaction or passive row (combat/typed_reactions.py) whose ability needs its user's voice."""
    return bool((rules().get("needs_voice") or {}).get(str(row.get("feature_id") or "")))


def can_hear_from(engine: Any, speaker: Any, listener: Any, source: str = '') -> bool:
    """Native hearing plus pure sound-path restrictions, shared by recipient routes.

    The listener's Deafened rule remains authoritative. Missing sound-path
    providers preserve previous hearing eligibility. No query consumes a use.
    """
    from .typed_executor import cant_hear, condition_rules
    from . import ext
    if cant_hear(listener) or any(rule.get('sound_blocked') for rule in condition_rules(listener)):
        return False
    if any(rule.get('sound_blocked') for rule in condition_rules(speaker)):
        return False
    replies = ext.run_strict('sound_path_allowed', engine, speaker, listener, source)
    if any(type(reply) is not bool for reply in replies):
        raise ValueError('sound_path_allowed must return None or a boolean')
    return not any(reply is False for reply in replies)
