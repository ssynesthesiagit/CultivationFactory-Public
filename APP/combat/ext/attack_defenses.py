"""Shared attack-only defenses for typed_reactions, typed_executor, traps and Bodyguard.

Reaction declarations collect benefits in transient attack specs. AC installation
and removal are evented; Resistance is a pure query of the confirmed packet and
never enters fight state. Nested attacks own their benefits, and pauses/errors
unwind scratch scopes. The helpers serve native and typed attack declarations.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace

from . import hook

_SCOPES = ContextVar("attack_only_defenses", default=())
_PACKET = ContextVar("attack_defense_packet", default=None)
_DECLARATIONS = ContextVar("native_attack_defense_declarations", default=())
_LEGACY = ContextVar("portable_attack_defense_scopes", default=())


@contextmanager
def declaration_resolution(engine):
    """Bound portable declarations across normal resolution, cancellation and pause.

    character_runtime_adapter uses this for dispatch and direct/opportunity
    attacks. Nested resolutions preserve surviving parent frames without ever
    resurrecting a completed declaration. Only extension scratch is affected.
    """
    before = _DECLARATIONS.get()
    token = _LEGACY.set((*_LEGACY.get(), engine))
    try:
        yield
    finally:
        _DECLARATIONS.set(tuple(f for f in _DECLARATIONS.get()
                                if f[0] is not engine or any(f is parent for parent in before)))
        _LEGACY.reset(token)


def finish_portable_declaration(engine, actor, source, index):
    """attack_notifications ends one settled portable declaration before callbacks."""
    frames = _DECLARATIONS.get()
    own = [f for f in frames if f[0] is engine]
    if own:
        frame = own[-1]
        if frame[1:4] == (actor.entity_id, source, index):
            _DECLARATIONS.set(tuple(f for f in frames if f is not frame))


def declaration_spec(engine, actor, source, index):
    """Own declaration scratch until native or portable completion.

    attack_declaration calls this only when its caller supplies no typed spec.
    A native d20 scope or portable declaration_resolution must own the lifetime.
    Every declaration gets a frame, including ones granting nothing, so
    a nested attack shadows its parent's benefit. No private engine scope access.
    """
    native = engine.d20_context()
    scoped_native = bool(native and native.get("kind") == "attack"
                         and (native.get("actor_id"), native.get("source_id"), native.get("attack_index"))
                         == (actor.entity_id, source, index))
    if not scoped_native and engine not in _LEGACY.get():
        return None  # direct/unscoped declarations cannot grant an attack benefit
    spec = {}
    frame = (engine, actor.entity_id, source, index, len(_SCOPES.get()), spec, scoped_native)
    _DECLARATIONS.set((*_DECLARATIONS.get(), frame))
    return spec


@hook("event", nested=True)
def bind_native_roll(engine, event_type, kwargs):
    if event_type != "ATTACK_ROLLED":
        return
    frames = [f for f in _DECLARATIONS.get() if f[0] is engine]
    if not frames:
        return
    _, actor, source, index, depth, _spec, _native = frames[-1]
    payload = kwargs.get("payload") or {}
    if (len(_SCOPES.get()) == depth and kwargs.get("actor_id") == actor
            and payload.get("reason") in {f"ATTACK:{source}:{index}", f"ATTACK:{source}"}):
        bind_declared_roll(engine, actor, source, index, kwargs.get("target_ids") or (), str(payload["roll_id"]))


def bind_declared_roll(engine, actor_id, source, index, targets, roll_id):
    """Bind one actual roll to the pending declaration, without granting a defense.

    Native event delivery and the portable adapter use the same API; the latter
    standalone harness has no Gate4 event dispatcher. Confirmed packet metadata
    remains an independent prerequisite for every Resistance query.
    """
    frames = [f for f in _DECLARATIONS.get() if f[0] is engine]
    if frames:
        frame = frames[-1]
        if frame[1:5] == (actor_id, source, index, len(_SCOPES.get())):
            frame[5]["attack_roll_id"] = str(roll_id)
            frame[5]["attack_target_ids"] = tuple(targets)


@hook("roll_context_end")
def end_native_declaration(engine, context):
    """Drop only the completed native declaration's scratch, even on abort/pause."""
    if context.get("kind") != "attack" or (context.get("spec") or {}).get("declaration_done"):
        return
    frames = _DECLARATIONS.get()
    own = [f for f in frames if f[0] is engine]
    if own:
        frame = own[-1]
        if frame[6] and frame[1:4] == (context.get("actor_id"), context.get("source_id"), context.get("attack_index")):
            # The native end callback exposes its actual transient resolver spec.
            # Preserve an opted-in grant for explicitly attributed deferred hit
            # packets (Multi-Ray), without keeping a global pending benefit.
            if frame[5].get("attack_only_resistance"):
                context["spec"].setdefault("attack_only_resistance", []).extend(frame[5]["attack_only_resistance"])
            _DECLARATIONS.set(tuple(f for f in frames if f is not frame))


def grant_resistance(spec, recipient, source):
    """Grant all-damage Resistance to this recipient for this declared attack only.

    Bodyguard uses this public API. Other rescuing/defensive abilities may use it
    without changing the engine: the transient spec, never a turn flag, owns it.
    """
    spec.setdefault("attack_only_resistance", []).append((recipient.entity_id, source))


@contextmanager
def packet_defenses(engine, spec):
    """Carry a typed on-hit packet's own spec; restore the parent on any exit.

    Used by typed_executor._deal and Destructive Blast. None carries no prior packet spec.
    Provenance is independently checked by packet_resistances, including during
    nested attacks, saves and non-attack damage. No fight state is changed.
    """
    token = _PACKET.set((engine, spec))
    try:
        yield
    finally:
        _PACKET.reset(token)


@hook("damage_defenses")
def packet_resistances(engine, target, damage_type, typed, source_actor_id):
    """Pure Resistance rows for exactly the confirmed packet's declared attack."""
    provenance = engine.damage_context()
    if provenance is None or provenance.target_id != target.entity_id or provenance.attacker_id != source_actor_id:
        return None
    # The public native d20 query intentionally exposes only scalar metadata.
    # Typed resolver scopes own the full spec; native declarations bind an
    # actual roll event and require the independently confirmed packet below.
    specs = [f[1] for f in _SCOPES.get() if f[0] is engine]
    carried = _PACKET.get()
    if carried is not None and carried[0] is engine:
        specs.append(carried[1])
    for spec in specs:
        resolved = spec.get("resolved_attack_context") if spec else None
        # Round 23 distinguishes primary and on-hit rider packets. Both belong
        # to this attack when every identity/roll field matches; a component
        # label must not discard its attack-only defense. Separate sources,
        # targets, rolls and nested attacks still cannot inherit the benefit.
        if (resolved is not None and replace(provenance, component=resolved.component) == resolved
                and any(who == target.entity_id for who, _source in spec.get("attack_only_resistance", []))):
            return [{"kind": "resistance", "damage_types": [str(damage_type or "").upper()]}]
    frames = [f for f in _DECLARATIONS.get() if f[0] is engine]
    if frames:
        _, actor, source, index, _depth, spec, _native = frames[-1]
        if (actor == provenance.attacker_id and source == provenance.source_id and index == provenance.attack_index
                and spec.get("attack_roll_id") == provenance.roll_id
                and spec.get("attack_target_ids") == (provenance.target_id,)
                and any(who == target.entity_id for who, _source in spec.get("attack_only_resistance", []))):
            return [{"kind": "resistance", "damage_types": [str(damage_type or "").upper()]}]
    return None


def grant(spec, recipient, source, amount):
    """Record an integer AC benefit for this attack, without changing fight state."""
    spec.setdefault("attack_only_ac", []).append((recipient.entity_id, source, int(amount)))


def _install(frame):
    engine, spec, ids = frame
    for who, source, amount in spec.get("attack_only_ac", []):
        actor = engine.state.actors[who]
        before = set(actor.modifiers)
        engine._add_modifier(actor, source, "armor_class", "ADD", amount, "SELF", expires_on="CONSUMED")
        ids.extend((who, mid) for mid in set(actor.modifiers) - before)


def _remove(frame):
    engine, _, ids = frame
    for who, mid in ids:
        actor = engine.state.actors[who]
        modifier = actor.modifiers.pop(mid, None)
        if modifier is not None:
            engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id,
                                 actor_id=who, target_ids=(who,),
                                 payload={"modifier_id": mid, "reason": "ATTACK_SCOPE_ENDED"})
    ids.clear()


@contextmanager
def resolving_defenses(engine, spec):
    """Apply only this attack's AC until its resolver returns or unwinds."""
    parents = [frame for frame in _SCOPES.get() if frame[0] is engine and frame[2]]
    for parent in parents:
        _remove(parent)
    frame = (engine, spec, [])
    token = _SCOPES.set((*_SCOPES.get(), frame))
    try:
        _install(frame)
        yield
    finally:
        _remove(frame)
        _SCOPES.reset(token)
        for parent in parents:
            _install(parent)
