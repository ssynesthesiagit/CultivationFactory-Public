"""Replayable external inputs for automatic controller decisions.

gate4_controller captures inputs while scoring; ai_plays and ai_mastermind
record embedding order and accepted speculative outcomes (including fallback).
gate4_persistence replays those inputs after an interrupted PREPARE. Requests
are bound to the complete rebuilt knowledge context and their call order;
scores, selection, intent and explanation are always recomputed and compared.

This is not execution authority or a saved score override. Outside a capture
scope, resolve() simply calls its producer. Scopes are call-local, and worker
threads cannot append late results to the prepared decision.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json

from .canonical import canonical_bytes, canonical_sha256
from .gate4_models import DecisionInput

_REPLAY = ContextVar("decision_input_replay", default=None)
_CAPTURE = ContextVar("decision_input_capture", default=None)


def _mismatch():
    raise ValueError("CONTROLLER_DECISION_NONDETERMINISTIC: decision inputs do not match")


@contextmanager
def replay(inputs):
    """Supply durable input rows to the next primary scoring scope only."""
    token = _REPLAY.set(inputs)
    try:
        yield
    finally:
        _REPLAY.reset(token)


@contextmanager
def capture(context):
    """Capture a primary choice, or strictly consume its prepared input trace.

    Nested primary scoring starts a separate trace, never consuming its
    parent's inputs. Empty traces preserve ordinary deterministic controllers.
    """
    trace = InputTrace(context, _REPLAY.get())
    token = _CAPTURE.set(trace)
    replay_token = _REPLAY.set(None)
    try:
        yield trace.inputs
        if trace.prepared is not None and len(trace.inputs) != len(trace.prepared):
            _mismatch()
    finally:
        _REPLAY.reset(replay_token)
        _CAPTURE.reset(token)


class InputTrace:
    def __init__(self, context, prepared):
        self.context = context
        self.context_sha256 = None
        self.prepared = prepared
        self.inputs = []


def resolve(name, request, produce):
    """Return a detached canonical JSON input, computing it only on first use.

    Replay validates context, request, name, order and complete consumption.
    Only accepted results are captured, not in-flight workers or wall clocks.
    """
    trace = _CAPTURE.get()
    if trace is None:
        return produce()
    # Default-inert for tiers without external evaluation: do not serialize
    # or impose any new context requirements until an input is requested.
    if trace.context_sha256 is None:
        trace.context_sha256 = canonical_sha256(trace.context.model_dump(mode="json"))
    request_sha256 = canonical_sha256({
        "context": trace.context_sha256, "name": name, "request": request,
    })
    if trace.prepared is None:
        row = DecisionInput(name=name, request_sha256=request_sha256,
                            value=json.loads(canonical_bytes(produce())))
    else:
        index = len(trace.inputs)
        if index >= len(trace.prepared):
            _mismatch()
        row = trace.prepared[index]
        if row.name != name or row.request_sha256 != request_sha256:
            _mismatch()
    trace.inputs.append(row)
    return json.loads(canonical_bytes(row.value))
