"""Rider lines a player must not be shown (MMX78): internal ids, engine words, code references (no model logs named here)."""
from __future__ import annotations

import re


# --- Rider text the fight log shows a player (MMX78) ------------------------
# A rider is a GM reminder the fight log prints verbatim through
# combat.history_text.rider_text. hunt87 printed one that named the internal id
# "condition:typed.stance.demon_seed" and explained a missing engine hook, so a
# player who knows only basic D&D read the software instead of the rules. Riders
# are read here through that same filter, so this guards what a player actually
# sees and not every bracketed authoring note the log already drops.
RIDER_INTERNAL_ID = re.compile(
    r"\b(?:condition|resource|action|event|effect|flag|state|source|turn_flag|mount):[a-z_]"
    r"|\btyped\.[a-z_]", re.I)
RIDER_ENGINE_WORD = re.compile(r"\b(?:compiler|interpreter|plug-?in|seams?)\b", re.I)
RIDER_CODE_REF = re.compile(
    r"\bcombat/|\.py\b"
    r"|\b(?:factory_compiler|typed_executor|typed_reactions|history_text|status_text"
    r"|end_effect|tabletop_service|combat\.ext|gate\d_[a-z_]+)\b", re.I)
# "hook" is a rules word (Soul Hook, a grappling hook, Staff-Swing Step) and a
# software word ("no generic reaction hook"), so it only counts as software when
# the sentence it sits in is about the implementation.
RIDER_HOOK = re.compile(r"\bhooks?\b", re.I)
RIDER_ENGINE_SENTENCE = re.compile(
    r"\b(?:blocked|automated|automation|compiler|interpreter|plug-?in|seams?|engine|generic"
    r"|code|expose|key off|modelled|modeled|deferred|char_review|lock round|not applied)\b", re.I)
RIDER_SENTENCE = re.compile(r"(?<=[.;])\s+|\n+")


def rider_problems(line):
    """Why this printed rider line cannot be shown to a player, or [] if it can."""

    problems = []
    if RIDER_INTERNAL_ID.search(line):
        problems.append("internal id")
    if RIDER_ENGINE_WORD.search(line):
        problems.append("engine word")
    if RIDER_CODE_REF.search(line):
        problems.append("code reference")
    if any(RIDER_HOOK.search(part) and RIDER_ENGINE_SENTENCE.search(part) for part in RIDER_SENTENCE.split(line)):
        problems.append("hook used as an engine term")
    return problems
