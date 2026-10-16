"""Accepted native reaction attacks, shared by Gate2 and character-runtime attacks.

The caller owns acceptance, payment and journal windows. This scope publishes
once by default, then carries the reacting actor, target and source through nested
answers and the attack's own d20. Callers that already published the accepted
reaction may pass ``publish=False``; attack context and roll hooks are still set.
It restores parent frames even on an Ask-me pause and creates no journal window.
"""
from contextlib import contextmanager, ExitStack

from . import ext, typed_reactions


@contextmanager
def attack_scope(engine, actor, target, source_id, name, *, runtime=False, publish=True):
    from .paid_relocation import activation

    # The native caller opens its independent activation before payment. Join
    # it here; direct granted-attack callers still establish an owning scope.
    with activation(engine, actor, source_id, independent=False):
        with _attack_scope(engine, actor, target, source_id, name, runtime=runtime, publish=publish):
            yield


@contextmanager
def _attack_scope(engine, actor, target, source_id, name, *, runtime=False, publish=True):
    previous = getattr(engine, "_native_reaction_attack", None)
    frames = getattr(engine, "_typed_reaction_frames", {})
    key = (actor.entity_id, source_id)
    parent = frames.get(key)
    context = {"kind": "attack", "actor_id": actor.entity_id,
               "source_actor_id": actor.entity_id, "target_id": target.entity_id,
               "source_id": source_id, "reaction_source_id": source_id,
               "economy": "REACTION", "attack_index": 1,
               "reason": f"ATTACK:{source_id}" + ("" if runtime else ":1")}
    engine._native_reaction_attack = context
    try:
        with ExitStack() as scopes:
            for scope in ext.run_strict("native_attack_scope", engine, context):
                if scope is not None:
                    scopes.enter_context(scope)
            scopes.enter_context(engine.d20_scope(context))
            if publish:
                typed_reactions.publish_reaction_used(engine, actor, {
                    "feature_id": source_id, "name": name, "target_ids": [target.entity_id],
                    "effects": [{"type": "attack", "attack_kind": "weapon_melee", "count": 1}],
                })
            yield
    finally:
        engine._native_reaction_attack = previous
        frames = getattr(engine, "_typed_reaction_frames", {})
        if parent is None:
            frames.pop(key, None)
        else:
            frames[key] = parent


def context(engine, actor_id, source_id):
    """Return a copy only for this accepted reaction's own attacker and source."""
    frame = getattr(engine, "_native_reaction_attack", None)
    if frame and frame["actor_id"] == actor_id and frame["source_id"] == source_id:
        return dict(frame)
    return None


def roll_mode(engine, actor_id, source_id, mode, *, contributions=None, checkpoints=()):
    """Combine original and checkpoint sources with native reaction answers once.

Gate2 supplies pre-cancellation sources from its masked attack-mode query; the
character runtime supplies its own original sources. A collapsed NORMAL cannot
tell absence from cancellation. Outside the accepted scope, preserve mode.
"""
    frame = context(engine, actor_id, source_id)
    if frame is None:
        return mode
    modes = set(contributions) if contributions is not None else {mode}
    modes.update(row.get('mode') for row in checkpoints
                 if isinstance(row, dict) and row.get('mode') in {'ADVANTAGE', 'DISADVANTAGE'})
    for answer in ext.run_strict("native_reaction_roll_mode", engine, frame):
        if answer not in {None, "NORMAL", "ADVANTAGE", "DISADVANTAGE"}:
            raise ValueError("native reaction roll mode must be a d20 mode")
        modes.add(answer)
    if {"ADVANTAGE", "DISADVANTAGE"} <= modes:
        return "NORMAL"
    return "DISADVANTAGE" if "DISADVANTAGE" in modes else "ADVANTAGE" if "ADVANTAGE" in modes else mode
