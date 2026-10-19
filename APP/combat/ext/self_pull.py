"""Pull yourself toward the target (rider lane 3, 2026-09-29).

  pull_self  {"distance_ft": 10}

"If the target is larger or fixed in place, you may pull yourself 10 feet toward it instead" (Lodged Axe Pull). The engine's
``forced_movement`` moves the target, never the caster; this row moves the caster the same way a pull moves a target -- square
by square toward the target's space, stopping at a blocked or occupied square and on arrival -- through the same evented
MOVEMENT_COMMITTED (forced) path, so a saved fight replays it and a Zone at the far end sees the arrival.
"""
from dataclasses import replace
from typing import Any

from . import effect


@effect("pull_self")
def pull_self(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _push

    subject = ctx.target or (ctx.targets[0] if ctx.targets else None)
    distance = int(row.get("distance_ft") or 0)
    if subject is None or not subject.active or distance <= 0 or not ctx.actor.active:
        return
    from . import needle

    chosen = needle.ask(ctx.engine, ctx.intent,
        needle.checkpoint_id(ctx.engine, 'LODGE_PULL', ctx.source, subject.entity_id), ctx.actor,
        'choice:needle.lodge_pull', ['pull'], labels={'pull': f'Pull yourself {distance} feet'},
        prompt=f'Lodged Axe Pull: {ctx.action.display_name} — pull {ctx.actor.display_name} toward {subject.display_name}?',
        name='Lodged Axe Pull', target_id=subject.entity_id, maximum=1, allow_decline=True)
    if not chosen:
        return
    # _push(ctx, mover, ...) pulls ``mover`` toward ``ctx.actor``: swap the two so the caster is the one that moves.
    _push(replace(ctx, actor=subject), ctx.actor, distance, pull=True)
