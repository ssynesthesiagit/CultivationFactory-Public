"""Three passives that add to a saving throw (auto-lane4 2026-09-29): they were GM-only lines because no talent could
add a number to a save except Saint-Body Frame and Pinning-style advantage.

``lane4_save`` rows (combat/rules/feature_blocks.d/auto_lane4.json, compiled by the ``compile_block`` hook below) carry a
``kind``:

- ``braced_body`` (Breath-Braced Body): "When you make a Strength or Dexterity saving throw against being pushed, pulled,
  knocked Prone, or moved by wind, pressure, or forced movement, you may add your Proficiency Bonus to the roll if you are
  not already adding it. Once you use this benefit, you cannot use it again until the start of your next turn." A typed
  save is an ability modifier only (no save proficiency is tracked), so "not already adding it" is always true here. The
  ``save`` hook adds the bonus to the first matching save and sets a turn flag (turn flags are cleared at the start of the
  character's own next turn, which is exactly the printed window). "You may": a player is asked before the save (the row is a
  choice_owner, so the question also comes on the pusher's turn); an AI takes it (rider lane C9, 2026-09-30).
- ``perfect_posture`` (Perfect Posture): "When you make a saving throw against being knocked Prone, moved against your
  will ... you may add 1d4 to the roll. You may use this talent after seeing the d20 roll but before the result is
  declared ... a number of times equal to your Proficiency Bonus per long rest." The ``after_save`` hook runs after the
  d20: when the save failed by 4 or less it rolls the d4, and if the total now reaches the DC it turns the save into a
  success (the R6 outcome override). Uses are counted from the character's own PASSIVE_TRIGGERED events, so a saved fight
  replays the same count; a long rest cannot happen inside a fight, so "per long rest" is per fight. The printed social
  cases (humiliated, forced to kneel or bow) have no condition to key off in this table and stay a GM line. "You may": a player
  is asked once the d20 is seen (the row is a choice_owner, so also on the pusher's turn); a declined use is not spent; an AI
  takes it (rider lane C10, 2026-09-30).
- Identify Rhythms' save half (the Hidden Eye row combat/ext/mind_hidden_eye.py already compiles for its AC half): "While
  you hold Martial Focus, add the same bonus [half Proficiency Bonus, rounded down] to saving throws you make against
  effects created by creatures Analyzed by you." The native ``save_bonus`` hook adds it once to the modifier when the
  explicit effect source is Analyzed by the saver and the saver holds Martial Focus. This includes Concentration checks
  caused by that creature's damage; an unknown source never guesses from the current turn. It does not lower the DC.
"""

from __future__ import annotations

from typing import Any

from . import hook
from ..gate2_runtime_models import DiceSpec

BLOCK = "lane4_save"
_PUSHED = {"prone", "forced_movement"}


@hook("compile_block")
def lane4_save_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    # Breath-Braced Body and Perfect Posture's "you may add" is the player's call, also on the pusher's turn (rider lane C9): choice_owner.
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2),
             **({"choice_owner": True} if spec.get("kind") in {"braced_body", "perfect_posture"} else {})}]


def _rows(engine: Any, actor_id: str, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def _hidden_eye(engine: Any, actor_id: str) -> bool:
    return any(row.get("block") == "hidden_eye" and row.get("kind") == "identify_rhythms"
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, []))


def _braced_body_wanted(ctx: Any, subject: Any, code: str) -> bool:
    """"you may add your Proficiency Bonus": asked of a player (once used, not again until its next turn starts); an AI takes it."""
    from .rider_choices import pick

    pb = int(getattr(subject, "proficiency_bonus", 0) or 2)
    source = getattr(getattr(ctx, "action", None), "display_name", None) or "the push"
    return bool(pick(ctx.engine, subject, "breath_braced_body", "Breath-Braced Body", ["use"], subject=subject,
                     labels={"use": f"Add your Proficiency Bonus (+{pb}) to this {code} save (then not again until your next turn)"},
                     trigger=f"{code} save against being moved or knocked Prone by {source}", intent=getattr(ctx, "intent", None)))


@hook("save")
def lane4_save_bonus(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    engine = ctx.engine
    wanted = {str(value).lower() for value in named or ()}
    code = str(ability or "").upper()[:3]
    bonus = 0
    if code in ("STR", "DEX") and wanted & _PUSHED and _rows(engine, subject.entity_id, "braced_body") \
            and not subject.turn_flags.get("lane4_braced_body") and _braced_body_wanted(ctx, subject, code):
        subject.turn_flags["lane4_braced_body"] = True  # "until the start of your next turn"
        bonus += int(getattr(subject, "proficiency_bonus", 0) or _rows(engine, subject.entity_id, "braced_body")[0].get("pb") or 2)
        engine._append_event("PASSIVE_TRIGGERED", _rows(engine, subject.entity_id, "braced_body")[0]["feature_id"],
                             actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                             payload={"feature_id": _rows(engine, subject.entity_id, "braced_body")[0]["feature_id"],
                                      "save_bonus": bonus, "ability": code})
    return {"bonus": bonus, "modes": []} if bonus else None


@hook("save_bonus")
def identify_rhythms_save(engine: Any, subject: Any, ability: str, dc: int,
                         source_id: str, intent: Any) -> int | None:
    if not _hidden_eye(engine, subject.entity_id) or subject.resources.get('resource:core.martial_focus', 0) < 1:
        return None
    context = engine.d20_context() or {}
    source = engine.state.actors.get(context.get('source_actor_id'))
    if source is None or source.entity_id == subject.entity_id:
        return None
    from .mind_hidden_eye import analyzed_by
    if analyzed_by(source, subject.entity_id):
        return subject.proficiency_bonus // 2
    return None


def _uses(engine: Any, actor_id: str, feature_id: str) -> int:
    return sum(1 for event in engine.events if event.event_type == "PASSIVE_TRIGGERED" and event.actor_id == actor_id
               and (event.payload or {}).get("feature_id") == feature_id)


def _posture_wanted(ctx: Any, subject: Any, shortfall: int, left: int) -> bool:
    """"you may add 1d4 to the roll": asked of a player after the d20 (rider lane C10); an AI takes it."""
    from .rider_choices import pick

    source = getattr(getattr(ctx, "action", None), "display_name", None) or "the effect"
    return bool(pick(ctx.engine, subject, "perfect_posture", "Perfect Posture", ["use"], subject=subject,
                     labels={"use": f"Add 1d4 to this failed save (it failed by {shortfall}; {left} use{'s' if left != 1 else ''} left this fight)"},
                     trigger=f"saving throw against being moved or knocked Prone by {source}", intent=getattr(ctx, "intent", None)))


@hook("after_save")
def perfect_posture(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    if not failed or not (({str(value).lower() for value in named or ()}) & _PUSHED):
        return
    rows = _rows(ctx.engine, subject.entity_id, "perfect_posture")
    if not rows:
        return
    engine, row = ctx.engine, rows[0]
    feature_id = row["feature_id"]
    if _uses(engine, subject.entity_id, feature_id) >= int(getattr(subject, "proficiency_bonus", 0) or row.get("pb") or 2):
        return
    rolled = next((event for event in reversed(engine.events[-30:]) if event.event_type == "SAVE_ROLLED" and event.actor_id == subject.entity_id), None)
    if rolled is None:
        return
    shortfall = int(rolled.payload["dc"]) - int(rolled.payload["total"])
    if shortfall > 4:  # the d4 cannot change this roll: the talent is not spent (it may be used after seeing the d20)
        return
    if not _posture_wanted(ctx, subject, shortfall, int(getattr(subject, "proficiency_bonus", 0) or row.get("pb") or 2)
                           - _uses(engine, subject.entity_id, feature_id)):
        return  # declined: not spent
    roll = engine.roller.roll(DiceSpec(count=1, sides=4, modifier=0), actor_id=subject.entity_id, reason=f"PERFECT_POSTURE:{ctx.source}")
    engine._record_roll(roll)
    saved = roll.total >= shortfall
    engine._append_event("PASSIVE_TRIGGERED", feature_id, actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                         payload={"feature_id": feature_id, "d4": roll.total, "shortfall": shortfall, "turned_into_success": saved})
    if saved:
        engine._typed_roll_outcome = {**(getattr(engine, "_typed_roll_outcome", None) or {}), subject.entity_id: "success"}
