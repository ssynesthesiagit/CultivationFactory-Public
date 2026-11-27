"""One score/modifier calculation for sheet projection and combat readers."""

import json

ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")


def effective_score(base, enhancements=()):
    """Only the highest active enhancement applies; advancement caps do not."""
    return int(base) + max(0, max(enhancements, default=0))


def score_modifier(score):
    return (int(score) - 10) // 2


def ability_rows(sheet):
    rows = (sheet.get("ability_scores_and_statistics") or {}).get("abilities") or []
    if isinstance(rows, str):
        rows = json.loads(rows)
    return {row["ability"]: row for row in rows if isinstance(row, dict) and row.get("ability") in ABILITIES}


def base_scores(sheet):
    """Published scores on the supplied sheet, without inferring gear or advancement."""
    return {ability: int(row["score"]) for ability, row in ability_rows(sheet).items()
            if row.get("score") is not None}


def ability_modifiers(sheet):
    """Modifiers on a base or combat-projected sheet; accept legacy modifier-only rows."""
    return {ability: int(row["modifier"]) if row.get("modifier") is not None else score_modifier(row.get("score", 10))
            for ability, row in ability_rows(sheet).items()}
