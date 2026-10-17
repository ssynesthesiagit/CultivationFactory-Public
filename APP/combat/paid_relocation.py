"""Default-inert paid self-relocation restrictions and causal activation scopes.

The engine knows actual assignments and payments, not ability names or which
resources a rule calls CP. A pure extension supplies an immutable Restriction
at assignment time. Its resource set is matched against positive payments by
that exact activation, including payments made after an earlier assignment.
Nothing in this module is serialized. See combat.ext's public contract.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from . import ext
from .position_observers import observe


class RelocationVeto(ext.CheckpointError):
    """A paid relocation is illegal; even observational hooks must roll back."""


@dataclass(frozen=True)
class Restriction:
    reason: str
    resource_ids: frozenset[str]

    def __post_init__(self):
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ext.CheckpointError("A relocation restriction needs a readable reason.")
        if (not isinstance(self.resource_ids, frozenset) or not self.resource_ids
                or any(not isinstance(value, str) or not value for value in self.resource_ids)):
            raise ext.CheckpointError("A relocation restriction needs a nonempty frozenset of resource IDs.")


@dataclass(frozen=True)
class ActivationView:
    actor_id: str | None
    source_id: str
    payments: tuple[tuple[str, int], ...]
    refunds: tuple[tuple[str, int], ...] = ()

    @property
    def net_payments(self):
        refunded = dict(self.refunds)
        return tuple((key, max(0, value - refunded.get(key, 0))) for key, value in self.payments)


@dataclass(eq=False)
class _Activation:
    actor: Any
    source_id: str
    payments: dict[str, int] = field(default_factory=dict)
    restrictions: list[Restriction] = field(default_factory=list)
    refunds: dict[str, int] = field(default_factory=dict)
    payment_sources: dict[tuple[str, str], int] = field(default_factory=dict)
    refunded_sources: dict[tuple[str, str], int] = field(default_factory=dict)

    def view(self):
        return ActivationView(getattr(self.actor, "entity_id", None), self.source_id,
                              tuple(sorted(self.payments.items())), tuple(sorted(self.refunds.items())))

    def check(self, restriction):
        if any(self.payments.get(resource_id, 0) > 0 for resource_id in restriction.resource_ids):
            raise RelocationVeto(restriction.reason)


@dataclass(frozen=True)
class _CapturedOwner:
    tracker: Any
    owner: _Activation | None


class _Tracker:
    def __init__(self, engine, actor, source_id):
        self.engine = engine
        self.state = engine.state
        self.owner = _Activation(actor, source_id)
        # Retain actor references as well as IDs: replacing an actor or projecting
        # a copy cannot accidentally reuse a position or fall receipt.
        self.eligibility = {}
        self.fall_owners = {}
        self.retained = {}
        self.pending_before = {}
        self.sampling = False
        self.querying = False

    def bound(self, actor):
        return self.state.actors.get(getattr(actor, "entity_id", None)) is actor

    def sample(self, *, baseline=False):
        if self.sampling:
            return
        from .falling import required
        self.sampling = True
        try:
            live = set()
            for actor in tuple(self.state.actors.values()):
                key = id(actor)
                live.add(key)
                due = required(self.engine, actor)
                previous = self.eligibility.get(key)
                if due and (previous is None or not previous[1]):
                    # A fall already due when the transaction started is not
                    # caused by the newly accepted action.
                    self.fall_owners[key] = None if baseline else self.owner
                elif not due:
                    self.fall_owners.pop(key, None)
                self.eligibility[key] = (actor, due)
            for key in set(self.eligibility) - live:
                self.eligibility.pop(key, None)
                self.fall_owners.pop(key, None)
        finally:
            self.sampling = False

    def before_assignment(self, actor, previous, destination):
        if not self.bound(actor) or previous == destination:
            return
        if self.querying:
            raise ext.CheckpointError("paid_relocation_guard must not mutate positions.")
        owner = self.owner
        if owner is None or owner.actor is not actor:
            return
        self.querying = True
        try:
            replies = ext.run_checkpoint("paid_relocation_guard", self.engine, actor, previous, destination)
        finally:
            self.querying = False
        for restriction in replies:
            if not isinstance(restriction, Restriction):
                raise ext.CheckpointError("paid_relocation_guard must return Restriction or None.")
            owner.check(restriction)
            # Keep the rule as it applied BEFORE this assignment; a later cost
            # may occur after the effect has removed the restricting condition.
            if restriction not in owner.restrictions:
                owner.restrictions.append(restriction)


_TRACKER = ContextVar("combat_paid_relocation", default=None)
_MISSING = object()


def _copy_pending(value, memo):
    """Copy pending container structure without cloning live actors or contexts."""
    key = id(value)
    if key in memo:
        return memo[key]
    if type(value) is dict:
        result = {}
        memo[key] = result
        result.update((name, _copy_pending(child, memo)) for name, child in value.items())
        return result
    if type(value) is list:
        result = []
        memo[key] = result
        result.extend(_copy_pending(child, memo) for child in value)
        return result
    if type(value) is tuple:
        children = [_copy_pending(child, memo) for child in value]
        if key in memo:
            return memo[key]
        result = tuple(children)
        memo[key] = result
        return result
    if type(value) in {set, frozenset}:
        result = type(value)(value)
        memo[key] = result
        return result
    return value


def _tracker(engine):
    tracker = _TRACKER.get()
    # Native character adapters share the real state through __dict__.update;
    # read-only projected engines and other concurrent fights do not.
    return tracker if tracker is not None and tracker.state is getattr(engine, "state", None) else None


def current_activation(engine):
    tracker = _tracker(engine)
    return tracker.owner.view() if tracker is not None and tracker.owner is not None else None


def capture(engine):
    """Opaque transient owner receipt for effects deliberately deferred by core."""
    tracker = _tracker(engine)
    return _CapturedOwner(tracker, tracker.owner) if tracker is not None else None


def retain(engine, key, receipt):
    """Retain ownership beside an existing deferred effect, never inside state."""
    tracker = _tracker(engine)
    if tracker is not None:
        if receipt is not None and (not isinstance(receipt, _CapturedOwner) or receipt.tracker is not tracker):
            raise ext.CheckpointError("A deferred effect belongs to a different transaction.")
        tracker.retained[key] = receipt


def take(engine, key):
    tracker = _tracker(engine)
    return tracker.retained.pop(key, None) if tracker is not None else None


def retained_owner(engine, key):
    """Read a retained owner shared by several aftermath callbacks."""
    tracker = _tracker(engine)
    return tracker.retained.get(key) if tracker is not None else None


def preserve_pending(engine, attribute):
    """Before changing a deferred engine binding, enroll it in guard rollback.

    Core restores MatchState already. This covers explicit engine-side callback
    markers/queues, including nested dict/list edits, without a per-plugin key
    list or copying unrelated engine state. Non-container leaves keep identity.
    Producers and consumers call before their first write/removal. It is inert
    without a guard; successful activations keep the native binding unchanged.
    """
    tracker = _tracker(engine)
    if tracker is None:
        return
    # Native adapters alias the live state and may share mutable pending
    # containers, then copy new bindings back to the canonical engine. Enroll
    # both before either object can mutate or publish that deferred marker.
    bindings = (tracker.engine, engine) if engine is not tracker.engine else (engine,)
    for pending_engine in bindings:
        key = (id(pending_engine), attribute)
        if key not in tracker.pending_before:
            value = pending_engine.__dict__.get(attribute, _MISSING)
            tracker.pending_before[key] = (pending_engine, attribute, _copy_pending(value, {}))


def retain_effect(engine, effect, receipt):
    tracker = _tracker(engine)
    if tracker is not None:
        if not isinstance(receipt, _CapturedOwner) or receipt.tracker is not tracker:
            raise ext.CheckpointError("A deferred effect belongs to a different transaction.")
        tracker.retained[("effect_owner", id(effect))] = (effect, receipt)


def take_effect(engine, effect):
    tracker = _tracker(engine)
    if tracker is None:
        return None
    saved = tracker.retained.pop(("effect_owner", id(effect)), None)
    return saved[1] if saved is not None and saved[0] is effect else None


def effect_owner(engine, effect):
    """Read an exact retained effect's owner without consuming its receipt."""
    tracker = _tracker(engine)
    if tracker is None:
        return None
    saved = tracker.retained.get(("effect_owner", id(effect)))
    return saved[1] if saved is not None and saved[0] is effect else None


def observe_falls(engine):
    """Observe eligibility, without moving a creature or changing settle timing."""
    tracker = _tracker(engine)
    if tracker is not None:
        tracker.sample()


@contextmanager
def transaction(engine, actor, source_id):
    """Own the entire accepted transaction, including its final settlement."""
    accounting = ext.run_strict("activation_accounting", engine)
    if any(type(value) is not bool for value in accounting):
        raise ext.CheckpointError("activation_accounting must return bool or None")
    if not ext.has("paid_relocation_guard") and True not in accounting:
        yield
        return
    tracker = _Tracker(engine, actor, source_id)
    token = _TRACKER.set(tracker)
    try:
        # The native deferred queue may legitimately be absent or None.
        preserve_pending(engine, "_typed_after_commit")
        tracker.sample(baseline=True)
        with observe(tracker.before_assignment):
            yield
    except BaseException:
        for pending_engine, attribute, previous in tracker.pending_before.values():
            if previous is _MISSING:
                pending_engine.__dict__.pop(attribute, None)
            else:
                pending_engine.__dict__[attribute] = previous
        raise
    finally:
        _TRACKER.reset(token)


@contextmanager
def _owned(tracker, owner):
    # Attribute any unrecorded parent change before opening a child. Attribute
    # the child's final change BEFORE restoring its parent, even when actual
    # falling is postponed until transaction settlement.
    tracker.sample()
    previous = tracker.owner
    tracker.owner = owner
    try:
        yield owner.view() if owner is not None else None
    except BaseException as original:
        # Observational extension dispatch may catch ordinary plugin errors and
        # keep the mutation that preceded them. Attribute that child's final
        # eligibility before restoring its parent, even on exceptional exit.
        try:
            tracker.sample()
        except BaseException as sampling_error:
            if (isinstance(original, (ext.CheckpointError, ext.ControllerPause))
                    or not isinstance(original, Exception)):
                raise original from sampling_error
            raise ext.CheckpointError("Could not retain falling ownership after an activation failed.") from sampling_error
        raise
    else:
        tracker.sample()
    finally:
        tracker.owner = previous


@contextmanager
def activation(engine, actor, source_id, *, independent=True, continuation=False):
    """Scope an accepted independent activation, before costs through aftermath.

    ``independent=False`` joins only an already matching actor/source owner.
    ``continuation=True`` explicitly joins the same actor's owning activation
    even when a named attached rider has a different source ID.
    ``actor=None`` explicitly identifies an independent environmental effect.
    Callers still own legality, consent, economy, costs, events and rollback.
    """
    tracker = _tracker(engine)
    if tracker is None:
        yield None
        return
    if actor is not None and not tracker.bound(actor):
        raise ext.CheckpointError("An activation must bind the exact live actor object.")
    owner = tracker.owner
    if (owner is not None and owner.actor is actor
            and (continuation or (not independent and owner.source_id == source_id))):
        yield owner.view()
        return
    with _owned(tracker, _Activation(actor, source_id)) as view:
        yield view


@contextmanager
def causal_scope(engine, receipt):
    """Resume a retained owner; never turn deferred paid effects into free ones."""
    tracker = _tracker(engine)
    if tracker is None:
        yield
        return
    if receipt is not None and (not isinstance(receipt, _CapturedOwner) or receipt.tracker is not tracker):
        raise ext.CheckpointError("A deferred effect belongs to a different transaction.")
    with _owned(tracker, receipt.owner if receipt is not None else None):
        yield


@contextmanager
def falling_scope(engine, actor):
    tracker = _tracker(engine)
    if tracker is None:
        yield
        return
    tracker.sample()
    with _owned(tracker, tracker.fall_owners.get(id(actor))):
        yield


def payment(engine, actor, resource_id, amount, source_id=None):
    """Account a successful resource debit before its RESOURCE_SPENT callbacks.

    A drain of another creature is not the current activation owner's payment.
    Refunds do not erase having paid. Zero/negative amounts never classify a use.
    """
    tracker = _tracker(engine)
    if tracker is None or amount <= 0 or not tracker.bound(actor):
        return
    owner = tracker.owner
    if owner is None or owner.actor is not actor:
        return
    owner.payments[resource_id] = owner.payments.get(resource_id, 0) + amount
    key = (resource_id, owner.source_id if source_id is None else source_id)
    owner.payment_sources[key] = owner.payment_sources.get(key, 0) + amount
    for restriction in owner.restrictions:
        owner.check(restriction)


def refund(engine, actor, resource_id, amount, cost_source_id):
    """Record only explicit actual cost refunds; ordinary recovery is not a refund."""
    tracker = _tracker(engine)
    if tracker is None or amount <= 0 or not tracker.bound(actor):
        return
    owner = tracker.owner
    if owner is not None and owner.actor is actor:
        key = (resource_id, cost_source_id)
        actual = min(amount, max(0, owner.payment_sources.get(key, 0) - owner.refunded_sources.get(key, 0)))
        if actual:
            owner.refunded_sources[key] = owner.refunded_sources.get(key, 0) + actual
            owner.refunds[resource_id] = owner.refunds.get(resource_id, 0) + actual
