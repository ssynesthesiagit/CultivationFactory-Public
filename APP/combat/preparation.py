"""Durable, source-qualified preparation between fights.

The service owns source sheets and serializes commands. Providers own equipment
or ability transitions. Rest observations use the existing gameplay reducer;
an imported boolean or the creation of a fight can never complete a rest.
"""
from copy import deepcopy
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path

from . import ext
from .canonical import canonical_bytes, canonical_sha256


class PreparationStore:
    def __init__(self, root):
        self.root = Path(root) / "Combat" / "Preparation"

    def path(self, actor_id):
        return self.root / (hashlib.sha256(actor_id.encode()).hexdigest() + ".json")

    @contextmanager
    def lock(self, actor_id):
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path(actor_id).with_suffix(".lock").open("a") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(file, fcntl.LOCK_UN)

    def read(self, actor_id):
        path = self.path(actor_id)
        return json.loads(path.read_bytes()) if path.exists() else {
            "actor_id": actor_id, "revision": 0, "elapsed_seconds": 0, "rest_generation": 0}

    def write(self, actor_id, state):
        path = self.path(actor_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(canonical_bytes(state))
        temporary.replace(path)

    def reconcile(self, bundle):
        """Persist source reconciliation under the caller's actor lock.

        Only effective state changes invalidate command revisions. Providers
        may accept reconciliation without changing anything on repeated reads.
        """
        actor_id = bundle["actor_id"]
        previous = self.read(actor_id)
        state = deepcopy(previous)
        ext.run_strict("preparation_reconcile", state, bundle)
        if state != previous:
            state["revision"] += 1
            self.write(actor_id, state)
        return state

    def transition(self, bundle, operation, parameters, expected_revision):
        actor_id = bundle["actor_id"]
        state = deepcopy(self.read(actor_id))
        if expected_revision != state["revision"]:
            raise ValueError("Preparation changed; refresh before submitting this command")
        # Reconciliation is mandatory even for an inspection: current published
        # source can revoke a prepared benefit without an invented command.
        ext.run_strict("preparation_reconcile", state, bundle)
        events = []
        if operation in {"rest.start", "rest.cancel", "rest.interrupt", "time.advance"}:
            from services.factory_dm_v0.gameplay.models import Actor, Membership, Scene, World
            from services.factory_dm_v0.gameplay.rules import transition
            ext.run_strict("preparation_before_activity", state, bundle, operation, parameters)
            if "rest_world" in state:
                world = World.from_dict(state["rest_world"])
            else:
                template = bundle["actor_template"]
                maximum_hp = int(template["maximum_hp"])
                world = World("preparation", {actor_id: Actor(actor_id, template["display_name"],
                    "rest", int(state.get("combat_hp", maximum_hp)), maximum_hp, bundle["preparation_abilities"], {})},
                    {"rest": Scene("rest", "Between fights")}, {"host": Membership("gm")},
                    elapsed_seconds=state["elapsed_seconds"])
            # Continuation must use the latest authoritative health receipt as
            # well. A cached pre-combat rest actor cannot heal zero committed HP.
            if "combat_hp" in state:
                world.actors[actor_id].base_hp_max = state["combat_hp_max"]
                world.actors[actor_id].hp = state["combat_hp"]
            kind, payload, subject = {
                "rest.start": ("start_activity", {"kind": parameters.get("kind", "long_rest")}, actor_id),
                "rest.cancel": ("cancel_activity", {}, actor_id),
                "rest.interrupt": ("interrupt_activity", parameters, actor_id),
                "time.advance": ("advance_time", {"seconds": parameters.get("seconds"), "modes": {
                    actor_id: parameters.get("observation", "unobserved")} if world.actors[actor_id].activity
                    and world.actors[actor_id].activity.status == "active" else {}}, None),
            }[operation]
            world, events = transition(world, subject, kind, payload,
                                       f"preparation:{state['revision']}", lambda sides: (_ for _ in ()).throw(
                                           ValueError("This preparation operation cannot roll dice")))
            state["rest_world"] = world.to_dict()
            state["elapsed_seconds"] = world.elapsed_seconds
            if any(e["kind"] == "long_rest_completed" for e in events):
                state["rest_generation"] += 1
                state["combat_hp"] = world.actors[actor_id].hp
                state["combat_hp_max"] = world.actors[actor_id].base_hp_max
            ext.run_strict("preparation_activity", state, bundle, operation, parameters, events)
        elif operation != "inspect":
            if not ext.run_strict("preparation_command", state, bundle, operation, parameters):
                raise ValueError("No source-qualified provider accepts this preparation command")
        ext.run_strict("preparation_reconcile", state, bundle)
        state["revision"] += 1
        self.write(actor_id, state)
        return state


def prepared_bundle(service, bundle):
    """Seal provider projections and interrupt any preparation rest at genesis.

    Initiative ends the between-fight activity through the same public reducer
    and provider cleanup as an explicit interruption. No rest means no change.
    """
    store = PreparationStore(service.userdata_root)
    with store.lock(bundle["actor_id"]):
        state = store.read(bundle["actor_id"])
        ext.run_strict("preparation_prior_fights", service, bundle, state)
        answers = ext.run_strict("preparation_reconcile", state, bundle)
        if answers:
            store.write(bundle["actor_id"], state)
        actor = ((state.get("rest_world") or {}).get("actors") or {}).get(bundle["actor_id"], {})
        if (actor.get("activity") or {}).get("status") == "active":
            state = store.transition(bundle, "rest.interrupt", {"reason": "initiative"}, state["revision"])
    for value in ext.run_strict("preparation_bundle", bundle, state):
        bundle = value
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)
    return bundle


def prior_actor_states(service, actor_id):
    """Current-format authoritative receipts; providers opt in only when needed.

    No saved legacy bundle without a preparation generation can be a receipt.
    A corrupt current-format receipt fails closed instead of restoring a use.
    """
    from .gate3_storage import load_typed_bundles
    for saved in service.persistence.list_matches():
        bundles = load_typed_bundles(service._match_dir(saved["match_id"]))
        bundle = next((b for b in bundles if b.get("actor_id") == actor_id
                       and "rest_generation" in (b.get("armor_subject") or {})), None)
        if bundle is not None:
            engine = service._load_session(saved["match_id"]).engine
            yield bundle, engine.state.actors[actor_id], engine.state.terminal_result is None
