"""Daemonic Augment's once-per-turn, choose-one typed augmentation.

The compiled modifier (authority/typed_mechanics) attaches one of six option rows to a
qualifying technique.  Four are ordinary typed effects.  Three printed facts need a
little state, so they live here instead of in the shared executor:

* "increase the movement by 5 feet" is a bonus to the triggering effect's own
  forced movement, never a second push of a chosen creature.  The shared
  forced_movement_bonus seam is the one the other movement-increasing
  talents already use (push_lengthening, brute_shove, flesh_crucible);
* "ignore ordinary Resistance to one of those damage types for that instance"
  asks the owner which type at the damage packet (and never during a preview),
  and never pierces Immunity;
* "mark one damaged creature ... gain 1 Devoured Essence" places a mark; the
  Essence is gained on the first damage from the owner, not when the mark is
  applied.

Every one of those paths honours the modifier's once-per-turn gate, including
when a different Augment option was the first one used this round.
Movement and Resistance keep deferred marker rows, so the executor never
sets the gate before the packet or push they describe; those two hooks close it
themselves once their effect has actually landed.
"""

from __future__ import annotations

from typing import Any

from .. import pending_damage
from ..effect_eligibility import modifier_key
from . import effect, hook, needle

AUGMENT = "TAL_DAEMONIC_CULTIVATION_DAEMONIC_AUGMENT"
SPHERE = "tianxia.sphere.daemonic_cultivation"
MARK = "daemonic_augment"
ESSENCE = "resource:named.devoured_essence"
CHOICE = "choice:daemonic_augment."
# The printed list; weapon damage is added separately because it is not a type.
TYPES = ("NECROTIC", "PSYCHIC", "FIRE", "POISON", "ACID", "FORCE", "WEAPON")
# A weapon packet names its physical kind (Slashing, ...); the printed option is "weapon damage".
WEAPON_KINDS = ("BLUDGEONING", "PIERCING", "SLASHING")
WALK_KEYS = ("effects", "on_hit", "on_miss", "on_fail", "on_success", "triggers", "inside")


def _rows(node: Any):
    """Every typed row below node, in execution order (the shared walkers' child keys)."""
    if isinstance(node, dict):
        yield node
        for key in WALK_KEYS:
            for child in _rows(node.get(key)):
                yield child
    elif isinstance(node, list):
        for child in node:
            yield from _rows(child)


def _marker(typed: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next((row for row in _rows(typed.get("effects") or []) if row.get("type") == kind), None)


def _spent(engine: Any, actor: Any, marker: dict[str, Any]) -> bool:
    """The Augment is once per turn, not once per option: any option's gate closes the rest."""
    if actor is None:
        return True
    return bool(marker.get("modifier_once") and actor.turn_flags.get(modifier_key(marker)))


def _spend(engine: Any, actor: Any, marker: dict[str, Any]) -> None:
    if actor is not None and marker.get("modifier_once"):
        actor.turn_flags[modifier_key(marker)] = True


def _damage_types(typed: dict[str, Any]) -> tuple[str, ...]:
    found: list[str] = []
    for row in _rows(typed.get("effects") or []):
        if row.get("type") in ("damage", "half_damage", "extra_damage"):
            found.extend(str(kind).upper() for kind in row.get("damage_types") or [] if str(kind).strip())
    weapon = typed.get("weapon") or {}
    for key in ("damage_type", "damage_types"):
        value = weapon.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value.upper())
        elif isinstance(value, list):
            found.extend(str(kind).upper() for kind in value if str(kind).strip())
    # The printed option also names weapon damage, which has no damage-type id.
    if typed.get("weapon") or any(row.get("type") == "attack" for row in _rows(typed.get("effects") or [])):
        found.append("WEAPON")
    return tuple(dict.fromkeys(found))


def _option_kind(kind: str, typed: dict[str, Any]) -> str | None:
    """The printed option a packet of this raw kind answers to, or None.

    Weapon packets ask as WEAPON; Resistance is still checked against the raw physical kind.
    """
    kind = str(kind or "").upper()
    if kind in TYPES and kind in _damage_types(typed):
        return kind
    if kind in WEAPON_KINDS and "WEAPON" in _damage_types(typed):
        return "WEAPON"
    return None


def _choice(engine: Any, pending: Any, typed: dict[str, Any], target: Any, kind: str) -> str | None:
    """Ask once per activation which printed damage type this instance ignores."""
    offered = [t for t in _damage_types(typed) if t in TYPES]
    if not offered:
        return None
    cache = getattr(engine, "_daemonic_augment_choices", None)
    if cache is None:
        cache = engine.__dict__["_daemonic_augment_choices"] = {}
    intent = getattr(engine, "_active_intent", None)
    key = (id(intent), "resistance") if intent is not None else (pending.transaction_id, "resistance")
    if key in cache:
        return cache[key]
    preferred = [kind.upper()] if kind.upper() in offered else offered
    chooser = engine.state.actors.get(getattr(pending, "source_actor_id", "")) or engine.state.actors.get(
        engine.state.current_actor_id)
    if chooser is None:
        return None
    answer = needle.ask(
        engine, intent, "damage_absorbed", chooser,
        f"{CHOICE}resist.{getattr(target, 'entity_id', 'target')}", offered,
        labels={value: value.title() for value in offered}, preferred=preferred,
        prompt="Daemonic Augment: choose the damage type whose ordinary Resistance this instance ignores.",
        name="Daemonic Augment", feature_id=AUGMENT, target_id=getattr(target, "entity_id", None),
    )
    picked = next((str(value).upper() for value in answer if str(value).upper() in offered), preferred[0])
    cache[key] = picked
    return picked


@hook("resistance_ignored")
def _ignore_resistance(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str,
                       target: Any, ordinary: bool = False) -> bool | None:
    """Daemonic Augment's Ignore Resistance: one printed type, one instance, ordinary Resistance only.

    Runs inside the engine's own defense query. The keyword argument ordinary is the decision typed_reactions._defenses
    passes (the target has ordinary Resistance to this type for this packet); without it nothing is asked or claimed.
    A claim is only a candidate: defend() turns it into a receipt once the packet's defenses really suppressed Resistance.
    """
    if target is None or not ordinary:
        return None
    marker = _marker(typed, "daemonic_augment_resistance")
    if marker is None:
        return None
    pending = pending_damage.current(engine)
    if pending is None:
        return None  # a preview/resistance query, not the packet that pays for the option
    actor = engine.state.actors.get(source_actor_id)
    if _spent(engine, actor, marker):
        return None
    raw = str(kind or "").upper()
    option = _option_kind(raw, typed)
    if option is None or _choice(engine, pending, typed, target, option) != option:
        return None
    claims = engine.__dict__.setdefault("_daemonic_augment_claims", {})
    claims[(pending.transaction_id, target.entity_id)] = (source_actor_id, marker, raw)
    return True


@hook("damage_defended")
def _record_resistance(engine: Any, target: Any, damage_type: Any, source_id: Any,
                       source_actor_id: Any, defenses: dict[str, Any]) -> None:
    """Notification after a real packet's defenses: keep this packet's claim as an ephemeral receipt.

    Nothing is asked, spent, or logged here (the contract forbids it). final_damage settles the receipt.
    A penetration or other suppression never made the claim, so it leaves no receipt.
    """
    if target is None or not defenses.get("resistance_suppressed") or defenses.get("resist"):
        return
    pending = pending_damage.current(engine)
    if pending is None:
        return
    claim = (engine.__dict__.get("_daemonic_augment_claims") or {}).pop((pending.transaction_id, target.entity_id), None)
    if claim is not None:
        receipts = engine.__dict__.setdefault("_daemonic_augment_receipts", {})
        receipts[(pending.transaction_id, target.entity_id)] = claim


@hook("final_damage")
def _settle_resistance(engine: Any, target: Any, defended: int, damage_type: Any, source_definition_id: Any,
                       source_actor_id: Any, intent: Any) -> dict[str, Any] | None:
    """Commit-time settlement: spend the once-per-turn gate and log the bypass, only if the packet commits."""
    pending = pending_damage.current(engine)
    if pending is None or target is None:
        return None
    receipts = engine.__dict__.get("_daemonic_augment_receipts") or {}
    receipt = receipts.pop((pending.transaction_id, target.entity_id), None)
    if receipt is None:
        return None
    actor_id, marker, raw = receipt
    actor = engine.state.actors.get(actor_id)
    if actor is None or _spent(engine, actor, marker):
        return None

    def settle(applied: int) -> None:
        if _spent(engine, actor, marker):
            return
        _spend(engine, actor, marker)
        engine._append_event(
            "PASSIVE_TRIGGERED", AUGMENT, actor_id=actor_id, target_ids=(target.entity_id,),
            payload={"automated": True,
                     "trigger": f"Daemonic Augment ignored ordinary {raw.title()} Resistance."},
        )

    return {"reduction": 0, "settle": settle}


@hook("forced_movement_bonus")
def _movement_bonus(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> int | None:
    """Increase the triggering effect's movement by 5 feet, never add a second movement."""
    marker = _marker(ctx.typed, "forced_movement_bonus")
    if marker is None or subject is None:
        return None
    if _spent(ctx.engine, ctx.actor, marker):
        return None
    row_key = ("daemonic_augment_movement", id(effect_row))
    chosen_key = ctx.damage_cache.get(("daemonic_augment_movement", "chosen"))
    if chosen_key is None:
        ctx.damage_cache[("daemonic_augment_movement", "chosen")] = row_key
        chosen_key = row_key
    if chosen_key != row_key:
        return None  # one movement row of the trigger, not every push it prints
    amount = int(marker.get("distance_ft") or marker.get("flat") or 5)
    _spend(ctx.engine, ctx.actor, marker)
    return amount


@hook("damage_dealt")
def _mark_pays_on_damage(ctx: Any, target: Any, amount: int, **kwargs: Any) -> None:
    """The first damage from the marker's owner to the marked creature yields 1 Devoured Essence."""
    from ..typed_executor import bears_mark, mark_condition_id

    engine, actor = ctx.engine, ctx.actor
    if actor is None or target is None or actor.entity_id == target.entity_id:
        return
    if not bears_mark(target, actor.entity_id, MARK):
        return
    key = f"once_per_round:{AUGMENT}:mark:{target.entity_id}:{engine.state.round_number}"
    if actor.turn_flags.get(key):
        return
    actor.turn_flags[key] = True
    engine._remove_condition(target, mark_condition_id(MARK, actor.entity_id), AUGMENT)
    if actor.resources.get(ESSENCE) is None or actor.resource_maximums.get(ESSENCE) is None:
        actor.resources[ESSENCE] = 0
        actor.resource_maximums[ESSENCE] = 99
    engine._gain_resource(actor, ESSENCE, 1, AUGMENT)


def _one_target(ctx: Any) -> Any:
    subjects = [row for row in (ctx.targets or []) if row is not None and row.entity_id != ctx.actor.entity_id]
    if not subjects and ctx.target is not None and ctx.target.entity_id != ctx.actor.entity_id:
        subjects = [ctx.target]
    return subjects[0] if subjects else None


@effect("daemonic_augment_mark", harmful=False)
def _mark(ctx: Any, effect: dict[str, Any]) -> None:
    if _marker(ctx.typed, "daemonic_augment_mark") is None:
        return
    target = _one_target(ctx)
    if target is None:
        return
    from ..typed_executor import mark_condition_id

    condition = mark_condition_id(MARK, ctx.actor.entity_id)
    if any(row.condition_id == condition for row in target.conditions.values()):
        return
    ctx.engine._apply_condition(target, condition, AUGMENT, ctx.actor.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN")
    # A mark-immune target refuses the condition: then nothing is spent and nothing is logged.
    if not any(row.condition_id == condition for row in target.conditions.values()):
        return
    _spend(ctx.engine, ctx.actor, _marker(ctx.typed, "daemonic_augment_mark"))
    ctx.engine._append_event(
        "PASSIVE_TRIGGERED", AUGMENT, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
        payload={"automated": True, "trigger": f"{ctx.actor.display_name} marks {target.display_name}; "
                                               "the first damage gains 1 Devoured Essence."},
    )


@effect("daemonic_augment_resistance", harmful=False)
def _resistance_choice(ctx: Any, effect: dict[str, Any]) -> None:
    """Marker row: the hook above reads it; nothing happens at effect time."""
    return None


@effect("forced_movement_bonus", harmful=False)
def _movement_marker(ctx: Any, effect: dict[str, Any]) -> None:
    """Marker row: the hook above increases the triggering movement; it is not itself a push."""
    return None
