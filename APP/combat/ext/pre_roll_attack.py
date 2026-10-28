"""Composition-time pre-roll attack modifiers: one to-hit delta and one first-hit damage bonus.

A printed talent may change the attack roll *before* it is made -- "take a -5 penalty to the attack roll. Hit: Deal
+10 damage" (Brutal Strike) or the same penalty with a chained follow-up (Reaper's Momentum).  The compiler already
composes such a talent as a row on the attack: an `attack_modifier` row for the roll and, for the damage half of the
same printed rule, an `extra_damage` row marked for the first hit.  The executor has always honoured
`first_roll_bonus` (combat/typed_executor.py), but nothing told the table that the row's printed +10 belonged in its
damage line, and the +10 stayed a second, unlabelled damage packet.

This module is the one general seam between composition and presentation.  It runs last on `compose_actions`, after
every provider (including Special Attacks' rest-of-the-Attack copies) has contributed its variants, and it does two
things to a single-attack action:

* folds an untyped flat `extra_damage` row that a modifier marked `first_hit_only` into
  `attack["first_hit_damage"]`, removing the row.  The executor adds that number to the first hit's own damage roll,
  so it uses the weapon's damage type and appears in the one damage roll the table reads; the row no longer needs a
  second "extra damage" packet.
* keeps (or, for a non-maneuver provider, creates) `attack["first_roll_bonus"]` from the same modifier's
  `attack_modifier` row, plus `first_roll_source` / `first_hit_damage_source` for display.  It does not rewrite
  `numbers.attack_bonus`: that number is the fighter's ordinary attack bonus, and combat/tabletop.py reads the
  delta when it shows the row.

Only rows a modifier contributed (`source_modifier`) are folded.  A formula amount, a damage-type choice, a deferred
effect, or a non-flat bonus stays an ordinary on-hit row: this seam is deliberately narrower than "all extra damage".
Nothing keys on a talent id.  A talent with the same printed shape is handled because it composes the same rows.

Display consumers: combat/tabletop.py::attack_to_hit / damage_text and combat/ext/action_help.py.  Roll consumers:
combat/typed_executor.py's attack block.  Reaper's follow-up chain (combat/ext/weapon_hit_chain.py) reuses
`first_roll_bonus` for each new attack, so no chain-specific number is written here.
"""

from __future__ import annotations

from typing import Any

from . import hook


def _flat_extra(row: dict[str, Any]) -> bool:
    """Whether a modifier's extra damage is one plain, unconditional first-hit number."""
    if row.get("type") != "extra_damage" or not row.get("source_modifier"):
        return False
    if row.get("applies_to") not in (None, "target") or row.get("first_hit_only") is not True:
        return False
    if row.get("deferred") or row.get("weapon_damage") or row.get("damage_types") or row.get("inherit_damage_type"):
        return False
    if str(row.get("formula") or "none").strip().lower() not in ("", "none"):
        return False
    return isinstance(row.get("flat"), int) and not isinstance(row.get("flat"), bool) and int(row["flat"]) != 0


def _label(row: dict[str, Any], typed: dict[str, Any]) -> str:
    """A player-facing source: the row's own label, else the action's modifier name, else the raw source id."""
    named = row.get("damage_label") or row.get("label")
    if named:
        return str(named)
    source = str(row.get("source_modifier") or "Modifier")
    modifier = typed.get("modifier") or {}
    return str(modifier.get("name") or source) if modifier.get("id") == source else source


def _fold(action: Any) -> None:
    parameters = getattr(action, "parameters", None) or {}
    typed = parameters.get("typed")
    if not isinstance(typed, dict):
        return
    effects = typed.get("effects") or []
    if not isinstance(effects, list):
        return
    attacks = [row for row in effects if isinstance(row, dict) and row.get("type") == "attack"]
    if len(attacks) != 1:
        return  # a sequence's rows belong to different attacks; do not guess which one a modifier means
    attack = attacks[0]

    kept: list[Any] = []
    moved: list[dict[str, Any]] = []
    roll_sources: list[str] = []
    for row in effects:
        if row is attack or not isinstance(row, dict):
            kept.append(row)
            continue
        source = str(row.get("source_modifier") or "")
        if (row.get("type") == "attack_modifier" and source
                and row.get("applies_to") in (None, "self")
                and str(row.get("duration") or "instant") == "instant"
                and str(row.get("condition") or "none") in ("", "none")
                and not int(row.get("distance_ft") or 0)
                and isinstance(row.get("flat"), int) and not isinstance(row.get("flat"), bool)
                and int(row["flat"]) != 0):
            attack["first_roll_bonus"] = int(attack.get("first_roll_bonus") or 0) + int(row["flat"])
            roll_sources.append(_label(row, typed))
            continue
        if _flat_extra(row):
            moved.append({**row, "first_hit_only": True})
            continue
        kept.append(row)
    if moved:
        attack["on_hit"] = [*(attack.get("on_hit") or []), *moved]
    typed["effects"] = kept

    on_hit = attack.get("on_hit") or []
    kept_hits: list[Any] = []
    bonus = 0
    damage_sources = list(attack.get("first_hit_damage_source") or [])
    for row in on_hit:
        if isinstance(row, dict) and _flat_extra(row):
            bonus += int(row["flat"])
            damage_sources.append(_label(row, typed))
        else:
            kept_hits.append(row)
    if bonus:
        attack["first_hit_damage"] = int(attack.get("first_hit_damage") or 0) + bonus
        attack["first_hit_damage_source"] = list(dict.fromkeys(damage_sources))
        attack["on_hit"] = kept_hits
    if roll_sources:
        attack["first_roll_source"] = list(dict.fromkeys([*(attack.get("first_roll_source") or []), *roll_sources]))
    elif attack.get("first_roll_bonus") and not attack.get("first_roll_source"):
        # A maneuver provider may already have composed the roll delta (docket_maneuvers.py) without naming it.
        attack["first_roll_source"] = [_label({"source_modifier": (typed.get("modifier") or {}).get("id")}, typed)]


@hook("compose_actions", priority=1000)
def fold_pre_roll_attack_modifiers(info: dict[str, Any]) -> None:
    """Fold every composed action's pre-roll modifier rows; last, so appended variants are included."""
    for action in info.get("actions") or []:
        _fold(action)
    return None
