"""Resolution-local roll descriptions and check receipts shared by typed reactions,
Intercepting Shot, Fate and Jester.

Descriptions inform optional d20 prompts without changing saved roll reasons,
draws or events. ContextVar tokens restore outer descriptions after nested rolls
and exceptions; nothing is stored on the engine or in a saved fight.
"""
from contextvars import ContextVar
from typing import Any


_description: ContextVar[tuple[Any, str, str, str] | None] = ContextVar("combat_roll_description", default=None)


def described_d20(engine: Any, *, description: str, **kwargs: Any) -> Any:
    """Roll normally, exposing description only to this engine/actor/reason's d20 hooks."""
    token = _description.set((engine, kwargs["actor_id"], kwargs["reason"], description))
    try:
        return engine.roller.d20(**kwargs)
    finally:
        _description.reset(token)


def described_check(engine: Any, *, description: str, **kwargs: Any) -> Any:
    """A described check using the shared native pre-draw mode resolver.

    Keyword arguments follow engine.roll_check: mode contributions are unresolved.
    The description remains local to this exact engine/actor/reason and draw.
    """
    token = _description.set((engine, kwargs["actor_id"], kwargs["reason"], description))
    try:
        return engine.roll_check(**kwargs)
    finally:
        _description.reset(token)


def roll_description(engine: Any, roll: Any) -> str | None:
    """Return the current matching description, or None for an ordinary roll."""
    current = _description.get()
    if current is not None and current[0] is engine and current[1:3] == (roll.actor_id, roll.reason):
        return current[3]
    return None


def check_receipts(kwargs: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Actual ability-check d20s on either side, shared by Fate and Jester.

    CHECK_ROLLED also carries bonus dice and opposed saves. Read the roll's
    reason and natural result rather than a producer-specific contest label.
    Native attacks use the same receipt shape with an ATTACK reason.
    """
    payload = kwargs.get('payload') or {}
    receipts = []
    for roll in (payload.get('actor') or payload.get('roll') or payload, payload.get('target')):
        if not isinstance(roll, dict) or not str(roll.get('reason') or '').startswith('CHECK:'):
            continue
        natural = roll.get('natural_result')
        actor_id = roll.get('actor_id')
        if type(natural) is int and 1 <= natural <= 20 and actor_id:
            receipts.append((actor_id, roll))
    return receipts


def check_skill_receipts(kwargs: dict[str, Any]) -> list[tuple[str, dict[str, Any], str | None]]:
    """Actual check receipts with each participant's skill, never a contest label.

    CHECK_ROLLED producers put the acting check's skill in payload.skill and the
    defending check's skill in payload.target_skill (None for unskilled checks).
    Metadata is authoritative even when None; an opposed save or a printed DC
    is excluded by check_receipts. Producers of legacy single checks may omit
    metadata and name their skill in the final reason component. Do not infer
    a defender's skill from payload.against: it may name a save, DC or label.
    A legacy combined-skill check may also carry payload.mode_skills (or
    target_mode_skills for its defender): the exact skill-mode inputs consulted
    for its single draw. Each is a consumption receipt for that same check,
    never another die or a selected-skill claim. Display labels belong in check,
    never skill. Shared views repeat metadata but must not re-query live modes
    after the first receipt: consuming a benefit cannot alter the other views.
    Only consumers of skill-specific benefits use this contract. Bonus dice,
    draws and saved roll reasons are unchanged; unidentified skills never match.
    """
    payload = kwargs.get('payload') or {}
    defender = payload.get('target')
    receipts = []
    for aid, roll in check_receipts(kwargs):
        key = 'target_skill' if roll is defender else 'skill'
        skill = payload.get(key) if key in payload else str(roll.get('reason') or '').rpartition(':')[2].replace('_', ' ')
        receipts.append((aid, roll, skill))
        modes_key = 'target_mode_skills' if roll is defender else 'mode_skills'
        for name in payload.get(modes_key) or ():
            receipts.append((aid, roll, name))
    return receipts
