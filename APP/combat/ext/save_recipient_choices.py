"""One choice from this activation's failed-save recipients, after all saves.

Rows and receipts live in the owning Context's damage_cache. No save history or
live authority lookup supplies candidates. The selected effects use a child
Context with exactly one recipient. Existing Needle transport owns pause/retry.
"""
from dataclasses import replace
from typing import Any
from . import effect
from .rider_choices import pick


@effect('remember_failed_save_recipient')
def remember_failed_save_recipient(ctx: Any, row: dict) -> None:
    """Place in a save's on_fail branch; collect only this activation's targets."""
    if ctx.target is not None:
        candidates = ctx.damage_cache.setdefault('failed_recipients:' + row['key'], [])
        if ctx.target.entity_id not in candidates:
            candidates.append(ctx.target.entity_id)


@effect('choose_failed_save_recipient')
def choose_failed_save_recipient(ctx: Any, row: dict) -> None:
    """Choose after the owning save row. With no failures there is no question."""
    from ..target_knowledge import located
    from ..typed_executor import run_effects
    from .needle import ai_controlled

    ids = ctx.damage_cache.pop('failed_recipients:' + row['key'], [])
    subjects = {aid: ctx.engine.state.actors[aid] for aid in ids
                if aid in ctx.engine.state.actors and ctx.engine.state.actors[aid].active}
    # An AI does not acquire knowledge of concealed creatures from a save receipt.
    if ai_controlled(ctx.engine, ctx.actor):
        subjects = {aid: subject for aid, subject in subjects.items() if located(ctx.engine, ctx.actor, subject)}
    if not subjects:
        return
    labels = {aid: subject.display_name for aid, subject in subjects.items()}
    selected = pick(ctx.engine, ctx.actor, row['key'], row['name'], list(subjects),
                    subject=ctx.actor, labels=labels, optional=False, intent=ctx.intent,
                    prompt=f"{row['name']}: choose one creature that failed its saving throw. "
                           "Only that creature receives the following effect. "
                           + ' '.join(str(e.get('evidence') or '') for e in row['effects']))
    if selected:
        subject = subjects[selected[0]]
        run_effects(replace(ctx, targets=[subject], target=subject), row['effects'])
