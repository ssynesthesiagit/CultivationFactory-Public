"""Shared critical helpers for bone_monarch and shield_riders.

Find Gap uses native critical range; Helmet Discipline cancels before damage.

Helmet Discipline asks the player to confirm qualifying head protection. Unknown
equipment is never invented by AI. A source-qualified resource is consumed until
an actual long-rest receipt, including across fights and cold reload. Existing
pre-damage conversion and player consent remain; AI uses known qualified armor.
critical_extra stays public for downstream readers; no workaround calls it here.
"""
from __future__ import annotations

from typing import Any

from . import hook

BLOCK = "lane4_crit"
HELMET = "tianxia.talent.equipment.helmet_discipline"
HELMET_POOL = "resource:equipment.helmet_discipline"


@hook("compile_resources")
def helmet_use(info):
    if HELMET not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ResourceDefinition
    return [ResourceDefinition(resource_id=HELMET_POOL, initial=1, maximum=1)]


@hook("preparation_prior_fights")
def helmet_prior_receipts(service, bundle, state):
    if HELMET not in (bundle.get("armor_subject") or {}).get("owned", []):
        return None
    from ..preparation import prior_actor_states
    for previous, actor, active in prior_actor_states(service, bundle["actor_id"]):
        if active:
            raise ValueError("Finish this character's active fight before creating another fight with its shared rest allowance")
        generation = previous["armor_subject"]["rest_generation"]
        if actor.resources.get(HELMET_POOL) == 0:
            state["helmet_spent_generation"] = max(generation, state.get("helmet_spent_generation", -1))


@hook("preparation_bundle")
def helmet_prepared_use(bundle, state):
    if HELMET not in (bundle.get("armor_subject") or {}).get("owned", []):
        return None
    generation = state["rest_generation"]
    bundle["armor_subject"]["rest_generation"] = generation
    for resource in bundle["actor_template"]["resources"]:
        if resource["resource_id"] == HELMET_POOL:
            resource["initial"] = int(state.get("helmet_spent_generation", -1) < generation)
    return bundle


@hook("preparation_committed")
def helmet_committed_use(service, engine):
    from ..preparation import PreparationStore
    store = PreparationStore(service.userdata_root)
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        subject = bundle.get("armor_subject") or {}
        if HELMET not in subject.get("owned", []) or "rest_generation" not in subject:
            continue
        actor = engine.state.actors[bundle["actor_id"]]
        with store.lock(actor.entity_id):
            state = store.read(actor.entity_id)
            before = dict(state)
            previous = state.get("helmet_spent_generation", -1)
            if actor.resources.get(HELMET_POOL) == 0 and subject["rest_generation"] > previous:
                state["helmet_spent_generation"] = subject["rest_generation"]
            if state != before:
                state["revision"] += 1
                store.write(actor.entity_id, state)


@hook("compile_block")
def lane4_crit_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind")}]


def critical_extra(engine: Any, target_id: str, attacker_id: str | None) -> int:
    """The extra dice a critical hit on ``target_id`` by ``attacker_id`` just rolled (0 when the latest roll was no crit)."""
    for event in reversed(engine.events[-25:]):
        if event.event_type == "DAMAGE_ROLLED" and event.actor_id == attacker_id and target_id in (event.target_ids or ()):
            payload = event.payload or {}
            dice = list(payload.get("dice") or ())
            if not payload.get("critical") or len(dice) < 2:
                return 0
            return sum(int(value) for value in dice[len(dice) // 2:])  # the roller doubles the count: the second half is the crit
    return 0


@hook("critical_cancel")
def helmet_discipline(engine, attacker, target, spec, roll, intent):
    rows = [row for row in getattr(engine, "typed_passive_rows", {}).get(target.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == "helmet_discipline"]
    if not rows:
        return None
    from .armor_subject import proficient_worn, bundle_of, worn_item
    bundle = bundle_of(engine, target)
    subject = bundle.get("armor_subject") or {}
    worn = worn_item(bundle)
    if not proficient_worn(engine, target) or not worn or subject.get("head_protection_key") != worn["key"] \
            or target.resources.get(HELMET_POOL, 0) < 1:
        return None
    feature_id = rows[0]["feature_id"]
    if any(event.event_type == "PASSIVE_TRIGGERED" and event.actor_id == target.entity_id
           and event.payload.get("feature_id") == feature_id and event.payload.get("critical_turned_normal")
           for event in engine.events):
        return None
    from .needle import ask
    chosen = ask(engine, intent, f"CRITICAL:{roll.roll_id}", target,
                 "choice:needle.helmet_discipline", ["protected"],
                 labels={"protected": "I am wearing qualifying head protection; turn this into a normal hit"},
                 prompt=f"{attacker.display_name}'s {spec.get('attack_name') or 'attack'} is a critical hit against {target.display_name}. Helmet Discipline requires a helmet, mask, armored hood or equivalent with armor you are proficient with. Turn this into a normal hit before damage is rolled? This uses the feature until your next long rest; it costs no Action or Reaction.",
                 name="Helmet Discipline", feature_id=feature_id, allow_decline=True,
                 automatic=True, preferred=["protected"], default="decline", target_id=attacker.entity_id)
    if not chosen:
        return None
    engine._spend_resource(target, HELMET_POOL, 1, feature_id)
    engine._append_event("PASSIVE_TRIGGERED", feature_id, actor_id=target.entity_id,
                         target_ids=(target.entity_id,), payload={"feature_id": feature_id,
                         "critical_turned_normal": True, "roll_id": roll.roll_id,
                         "log": f"{target.display_name} uses Helmet Discipline: this critical hit becomes a normal hit."})
    return True


@hook("attack_critical_range")
def find_gap(engine, actor, target, spec):
    from .mind_hidden_eye import analyzed_by
    if analyzed_by(target, actor.entity_id) and any(
            row.get("block") == BLOCK and row.get("kind") == "find_gap"
            for row in getattr(engine, "typed_passive_rows", {}).get(actor.entity_id, [])):
        return 19
    return None
