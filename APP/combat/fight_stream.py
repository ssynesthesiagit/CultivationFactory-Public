"""Bounded, process-local fight notifications; the journal remains authoritative.

* A durable commit queues an events wake-up with match_id and last_sequence.
  Dispatch after the outer writer reservation releases. Clients read the public
  journal feed from their own cursor.
* After seats/runner running, paused, error or ownership changes publish
  'seat-status' with the SAME seats.status(match_id) response.
* After deferred menu warming completes publish 'menu-ready', {}. After other
  non-journal changes (settings/controllers/maps) publish 'fight-changed', {}.
  These invalidate the view; never broadcast a viewer-specific state/menu.
* GET /api/tabletop/matches/{match_id}/stream?after=N: use Last-Event-ID in
  preference to after. Subscribe BEFORE reading the durable journal catch-up
  with tabletop.events(match_id, cursor); send its boundary first, then queued
  messages, filtering event wake-ups at/below the served cursor.
  Always send initial seat status too. subscribe(after=cursor) only observes
  future publications and skips event wake-ups at/below that initial cursor.
  There is no in-process replay: the journal is the only resume authority.
  Return text/event-stream, Cache-Control: no-cache, X-Accel-Buffering: no;
  yield message.sse(), send heartbeat comments during idle periods, and close
  the subscription in finally on disconnect/cancellation. A dropped subscriber
  ends iteration: the route must end the response so EventSource reconnects.
  Only events have an SSE id (last_sequence); status/menu changes may share a
  journal position and MUST NOT advance Last-Event-ID. One uvicorn process only.
"""
from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

HEARTBEAT_SECONDS = 15
KINDS = frozenset({'events', 'seat-status', 'menu-ready', 'fight-changed'})


@dataclass(frozen=True)
class Message:
    kind: str
    data: str
    event_id: int | None = None

    @classmethod
    def from_payload(cls, kind, payload):
        position = payload.get('last_sequence') if kind == 'events' else None
        if kind == 'events' and (type(position) is not int or position < 0):
            raise ValueError('events require a journal last_sequence')
        return cls(kind, json.dumps(payload, separators=(',', ':'), allow_nan=False), position)

    @property
    def payload(self):
        return json.loads(self.data)

    def sse(self) -> str:
        identity = '' if self.event_id is None else f'id: {self.event_id}\n'
        return f'{identity}event: {self.kind}\ndata: {self.data}\n\n'


class Subscription:
    def __init__(self, broker, match_id, after, loop):
        self.broker, self.match_id, self.after = broker, match_id, after
        self.loop = loop
        self.ready = asyncio.Event()
        self.queue = deque()
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            with self.broker.lock:
                if self.closed:
                    raise StopAsyncIteration
                if self.queue:
                    return self.queue.popleft()
                self.ready.clear()
            await self.ready.wait()

    def close(self):
        with self.broker.lock:
            self.broker._drop(self)


class FightStream:
    def __init__(self, queue_size=64):
        if queue_size < 1:
            raise ValueError('stream bounds must be positive')
        self.queue_size = queue_size
        self.lock = threading.RLock()
        self.subscribers = {}

    def _wake(self, sub):
        try:
            sub.loop.call_soon_threadsafe(sub.ready.set)
        except RuntimeError:  # dead event loop
            self._drop(sub, wake=False)

    def _drop(self, sub, wake=True):
        sub.closed = True
        sub.queue.clear()
        group = self.subscribers.get(sub.match_id)
        if group is not None:
            group.discard(sub)
            if not group:
                del self.subscribers[sub.match_id]
        if wake:
            self._wake(sub)

    def _enqueue(self, sub, message):
        if message.event_id is not None and message.event_id <= sub.after:
            return
        if len(sub.queue) >= self.queue_size:
            self._drop(sub)
            return
        was_empty = not sub.queue
        sub.queue.append(message)
        if was_empty:  # at most one wake callback per nonempty queue
            self._wake(sub)

    def publish(self, match_id, kind, payload):
        if kind not in KINDS:
            raise ValueError(f'unknown stream kind: {kind}')
        message = Message.from_payload(kind, payload)
        with self.lock:
            for sub in tuple(self.subscribers.get(match_id, ())):
                self._enqueue(sub, message)

    def has_subscribers(self, match_id):
        with self.lock:
            return match_id in self.subscribers

    def subscribed_matches(self):
        with self.lock:
            return tuple(self.subscribers)

    def subscribe(self, match_id, *, after=0):
        """Call on the serving asyncio loop; publish may run on any thread."""
        if type(after) is not int or after < 0:
            raise ValueError('after must be a journal position')
        sub = Subscription(self, match_id, after, asyncio.get_running_loop())
        with self.lock:
            self.subscribers.setdefault(match_id, set()).add(sub)
        return sub


_stream = FightStream()
publish = _stream.publish
subscribe = _stream.subscribe
has_subscribers = _stream.has_subscribers
subscribed_matches = _stream.subscribed_matches


_pending_notifications = ContextVar('fight_stream_notifications', default=None)


@contextmanager
def defer_notifications():
    """Flush this operation's notifications after its outermost writer releases."""
    if _pending_notifications.get() is not None:
        yield
        return
    pending = []
    token = _pending_notifications.set(pending)
    try:
        yield
    finally:
        _pending_notifications.reset(token)
        for notification in pending:
            publish(*notification)


def _notify(match_id, kind, payload):
    pending = _pending_notifications.get()
    if pending is None:
        publish(match_id, kind, payload)
    else:
        pending.append((match_id, kind, payload))


def event_position(match_id, last_sequence):
    return {'match_id': match_id, 'last_sequence': last_sequence}


def publish_events(match_id, last_sequence):
    _notify(match_id, 'events', event_position(match_id, last_sequence))


def publish_changed(match_id):
    _notify(match_id, 'fight-changed', {})
