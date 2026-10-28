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


def _sound_path_answers(replies: list[Any]) -> tuple[int, list[Any]]:
    """Read sound_path_allowed replies as (grants, blocks).

    A block is either the source that owns it (its suppression is ordinary Silence, which a
    printed grant may pierce) or None when the provider names no source and the block stands.
    """
    grants, blocks = 0, []
    for reply in replies:
        if reply is None:
            continue
        if reply is True:
            grants += 1
        elif reply is False:
            blocks.append(None)
        elif (isinstance(reply, dict) and reply.get('allowed') is False
              and isinstance(reply.get('source'), str)):
            blocks.append(reply['source'])
        else:
            raise ValueError("sound_path_allowed must return None, a boolean or {'allowed': False, 'source': id}")
    return grants, blocks


def ordinary_silence(engine: Any, source: str) -> bool:
    """Whether this source's sound suppression is ordinary Silence, not a protected obstruction.

    The source is read through combat/observer_information.source_profile, the same authored
    catalogue a source's own information rows use, so a Curse or a sealed rite stays 'protected'
    and no printed hearing grant pierces it.
    """
    if not isinstance(source, str) or not source:
        return False
    from .observer_information import source_profile

    return source_profile(engine, source, {}).get('authority') != 'protected'


def _silence_deafness(engine: Any, condition: Any, silence_sources: set[str]) -> bool:
    """Whether this cant_hear rule is a Silence field's own deafness rather than a separate Deafened.

    True Silence prints both a Deafened condition and silence inside its field, and both are
    applied from the one ability, so the field that silences also owns the deafness it causes.
    A Deafened from another ability is deafness no Silence field accounts for.
    """
    source = condition.source_definition_id
    return source in silence_sources and ordinary_silence(engine, source)


def can_hear_from(engine: Any, speaker: Any, listener: Any, source: str = '') -> bool:
    """Native hearing plus pure sound-path restrictions, shared by recipient routes.

    The listener's own Deafened rule and a provider's refusal keep ordinary hearing shut, and
    missing sound-path providers preserve previous hearing eligibility. One provider may instead
    answer True: a grant that carries THIS printed sound to THIS listener past ordinary sound
    suppression -- a Silence field's deafness and blocked path, which is what Ninefold Heavenly
    Bell's "allies inside the field can hear your bell through ordinary Silence, noise and
    distance" buys. A deafness no Silence field accounts for, and a refusal that names a
    protected source (a Curse, a Foundation Injury, a Secret Law), still stop the sound. No
    query consumes a use.
    """
    from .typed_executor import condition_rule_instances
    from . import ext
    grants, blocks = _sound_path_answers(
        ext.run_strict('sound_path_allowed', engine, speaker, listener, source))
    rows = condition_rule_instances(listener, engine=engine)
    silence_sources = {c.source_definition_id for c, row in rows if row.get('silenced')}
    barriers = [(c, row) for c, row in rows if row.get('cant_hear')]
    if not barriers and not blocks:
        return True
    if not grants or not all(ordinary_silence(engine, owner) for owner in blocks):
        return False
    return all(_silence_deafness(engine, condition, silence_sources) for condition, _row in barriers)
