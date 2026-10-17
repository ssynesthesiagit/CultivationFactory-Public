"""Strict movement-step checkpoint with a scoped, read-only distance context.

A hook that asks a player a question raises ext.ControllerPause, a BaseException, so it
unwinds the intent here rather than being reported as a failed checkpoint; the leave-reach
Opportunity Attack asked mid-route uses the same control flow.
"""
from types import MappingProxyType
from contextlib import contextmanager
from . import ext


@contextmanager
def opportunity_policy(engine, actor, ignore_oa_from):
    """Scope every native route, restoring the enclosing route on every exit."""
    old_ignore = getattr(engine, '_movement_ignore_oa', None)
    old_step = getattr(engine, '_movement_step_oa', None)
    engine._movement_ignore_oa = (actor.entity_id, tuple(ignore_oa_from))
    try:
        yield
    finally:
        engine._movement_ignore_oa = old_ignore
        engine._movement_step_oa = old_step


def opportunity_exempt(engine, mover, reactor_id):
    """Pure query of the current willing step's snapshotted OA exemptions."""
    step = getattr(engine, '_movement_step_oa', None) or {}
    if step.get('actor_id') != mover.entity_id:
        return False
    return bool(step.get('disengaged') or step.get('free')
                or reactor_id in (step.get('ignore') or ())
                or mover.turn_flags.get('spark_step_ignore_oa_from') == reactor_id)


def context(engine, actor):
    """The read-only distance context of the step in progress: feet travelled on this route
    so far, and feet of the route still to come. Empty outside a step, or for another creature."""
    value = getattr(engine, '_movement_step_context', None) or {}
    return value if value.get('actor_id') == actor.entity_id else {}


def checkpoint(engine, mover, previous, nxt, intent, *, travelled_ft, remaining_ft, point='movement_step', source_id=None):
    if point == 'movement_attempt':
        granted = getattr(engine, '_movement_ignore_oa', None) or ('', ())
        engine._movement_step_oa = {
            'actor_id': mover.entity_id,
            'disengaged': bool(mover.turn_flags.get('disengaged')),
            'free': int(mover.turn_flags.get('oa_free_ft') or 0) > 0,
            'ignore': tuple(granted[1]) if granted[0] == mover.entity_id else (),
        }
    old = getattr(engine, '_movement_step_context', None)
    engine._movement_step_context = MappingProxyType({'actor_id': mover.entity_id,
        'travelled_ft': travelled_ft, 'remaining_ft': remaining_ft,
        **({'forced': True, 'source_id': source_id} if point.startswith('forced_') else {})})
    try:
        replies = []
        expected = previous if point.endswith('movement_attempt') else nxt
        def valid():
            return mover.active and mover.position == expected and (
                engine.state.terminal_result is None or getattr(engine, '_final_rider_active', False))
        if not valid():
            return replies
        for reply in ext.iter_strict_all(point, engine, mover, previous, nxt, intent):
            if reply is None:
                if not valid():
                    break
                continue
            if not isinstance(reply, dict) or set(reply) - {'stop', 'source_id', 'label'}:
                raise ValueError('unsupported movement_step reply')
            if reply.get('stop') is not True:
                raise ValueError('a movement interruption must stop the move')
            if not all(isinstance(reply.get(k), str) and reply[k] for k in ('source_id', 'label')):
                raise ValueError('a movement interruption needs a source and readable label')
            engine._append_event('GM_RIDER', reply['source_id'], actor_id=mover.entity_id,
                payload={'rider': reply['label']})
            replies.append(reply)
            # Keep completed effects; later interruptions cannot spend resources
            # against a path that a preceding subscriber already stopped.
            break
        if point == 'movement_step':
            # A step has already been paid and entered. Settle effects owed by
            # that completed step even when an earlier subscriber ends the path.
            # These finalizers do not create a new movement-triggered opportunity;
            # ordinary defenses against their owed effects may still ask a player.
            for reply in ext.iter_strict_all('movement_step_settled', engine, mover, previous, nxt, intent):
                if reply is None:
                    continue
                if (not isinstance(reply, dict) or set(reply) - {'stop', 'source_id', 'label'}
                        or reply.get('stop') is not True
                        or not all(isinstance(reply.get(k), str) and reply[k] for k in ('source_id', 'label'))):
                    raise ValueError('unsupported movement_step_settled reply')
                engine._append_event('GM_RIDER', reply['source_id'], actor_id=mover.entity_id,
                    payload={'rider': reply['label']})
                replies.append(reply)
        return replies
    except ext.CheckpointError:
        raise
    except Exception as exc:
        raise ext.CheckpointError(f'{point} failed: {exc}') from exc
    finally:
        engine._movement_step_context = old
