"""Strict movement-step checkpoint with a scoped, read-only distance context.

A hook that asks a player a question raises ext.ControllerPause, a BaseException, so it
unwinds the intent here rather than being reported as a failed checkpoint; the leave-reach
Opportunity Attack asked mid-route uses the same control flow.
"""
from types import MappingProxyType
from contextlib import contextmanager
from . import ext


@contextmanager
def opportunity_policy(engine, actor, ignore_oa_from, path=()):
    """Scope every native route, restoring the enclosing route on every exit."""
    old_ignore = getattr(engine, '_movement_ignore_oa', None)
    old_step = getattr(engine, '_movement_step_oa', None)
    old_route = getattr(engine, '_movement_route_context', None)
    engine._movement_route_context = MappingProxyType({'actor_id':actor.entity_id,'path':tuple(path),'ignore_oa_from':tuple(ignore_oa_from),'intent_id':getattr(getattr(engine,'_active_intent',None),'intent_id',None)})
    engine._movement_ignore_oa = (actor.entity_id, tuple(ignore_oa_from))
    try:
        yield
    finally:
        engine._movement_ignore_oa = old_ignore
        engine._movement_step_oa = old_step
        engine._movement_route_context = old_route


def opportunity_exempt(engine, mover, reactor_id):
    """Pure query of the current willing step's snapshotted OA exemptions."""
    step = getattr(engine, '_movement_step_oa', None) or {}
    if step.get('actor_id') != mover.entity_id:
        return False
    return bool(step.get('disengaged') or step.get('free')
                or reactor_id in (step.get('ignore') or ())
                or mover.turn_flags.get('spark_step_ignore_oa_from') == reactor_id)


def context(engine, actor):
    """The read-only context of the movement in progress, for the creature making it.

    Keys (all transient; never stored in fight state, restored across nesting):
      * ``travelled_ft`` -- whole feet of THIS route already covered (geometric route length so far).
      * ``remaining_ft`` -- whole feet of THIS route still to come (geometric route length left), NOT the
        feet the creature may still spend. Route length ignores terrain cost, dragging and flight, so it is
        not a movement budget; use ``allowance_ft`` for that.
      * ``destination`` -- the route's own chosen endpoint (``Position`` or ``None``), the square the complete
        canonical path was validated against, so a whole-route rule can answer on the very first step.
      * ``allowance_ft`` -- the movement allowance in whole feet that actually governs THIS movement (``None``
        outside a step): the mover's remaining ordinary movement in the route's mode, or, when ``granted`` is
        true, the grant's own remaining budget. The budget to price a rule against, never ``remaining_ft``.
      * ``mode`` -- the movement mode in play, ``'walk'``, ``'fly'`` or ``'jump'`` (``None`` outside a step).
      * ``granted`` -- true when ``allowance_ft`` is a grant's budget rather than the mover's ordinary
        allowance, so a rule can pick the grant-aware route builder instead of the native candidate list.
      * ``forced`` / ``source_id`` -- present only for forced-displacement attempts.

    Empty outside a step, or for another creature."""
    value = getattr(engine, '_movement_step_context', None) or {}
    return value if value.get('actor_id') == actor.entity_id else {}


def landed(engine, mover, previous, destination, intent, *, forced=False):
    """Reconcile owned spatial assets before any effects of an entered step.

    Notification only: providers return None and record their own asset updates.
    Willing/granted entry and forced/dragged landing share this boundary. It is
    not a movement grant or a reaction window; normal transaction rollback and
    ControllerPause propagation apply. No subscribers is inert.
    """
    try:
        # This position was paid and entered. Quotes/attempts never reach here.
        if ext.has('movement_progress_committed') and mover.position == destination and previous != destination:
            scope = engine.movement_scope(mover.entity_id) or {}
            receipt = MappingProxyType({
                'actor_id': mover.entity_id,
                'intent_id': getattr(intent, 'intent_id', None),
                'source_id': scope.get('source_id'),
                'distance_ft': int(engine.grid.distance_ft(previous, destination)),
                'voluntary': bool(scope) and not forced,
                'granted': bool(scope.get('granted')),
                'turn_actor_id': engine.state.current_actor_id,
                'own_turn': engine.state.current_actor_id == mover.entity_id,
            })
            replies = ext.run_strict('movement_progress_committed', engine, mover, receipt)
            if any(reply is not None for reply in replies):
                raise ValueError('movement_progress_committed providers must return None')
        replies = ext.run_strict('movement_landed', engine, mover, previous, destination, intent, forced)
        if any(reply is not None for reply in replies):
            raise ValueError('movement_landed providers must return None')
    except ext.CheckpointError:
        raise
    except Exception as exc:
        raise ext.CheckpointError(f'movement_landed failed: {exc}') from exc


def checkpoint(engine, mover, previous, nxt, intent, *, travelled_ft, remaining_ft, point='movement_step', source_id=None,
               destination=None, allowance_ft=None, mode=None, granted=False):
    if point == 'movement_attempt':
        oa_scope = getattr(engine, '_movement_ignore_oa', None) or ('', ())
        engine._movement_step_oa = {
            'actor_id': mover.entity_id,
            'disengaged': bool(mover.turn_flags.get('disengaged')),
            'free': int(mover.turn_flags.get('oa_free_ft') or 0) > 0,
            'ignore': tuple(oa_scope[1]) if oa_scope[0] == mover.entity_id else (),
        }
    old = getattr(engine, '_movement_step_context', None)
    engine._movement_step_context = MappingProxyType({'actor_id': mover.entity_id,
        'travelled_ft': travelled_ft, 'remaining_ft': remaining_ft, 'destination': destination,
        'allowance_ft': allowance_ft, 'mode': mode, 'granted': bool(granted),
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


def route(engine, actor):
    """Read-only accepted voluntary route, shared by movement-dependent riders.

    Includes the starting position. Nested routes restore their parent; quotes
    and movement outside native resolution return an empty mapping.
    """
    value = getattr(engine, '_movement_route_context', None) or {}
    return value if value.get('actor_id') == actor.entity_id else {}
