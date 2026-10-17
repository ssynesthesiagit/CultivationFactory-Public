"""Body Refining Subpath pools: their printed normal gains, one a round, up to the printed maximum (rider lane C7, 2026-09-30).
Shared helper: thunder_charges.py, black_thorn_demon_body.py, drum_body.py and parasite_vessel.py call ``gain`` (parasite_vessel.py
also ``maximum``).

The Subpath records (Body Refining Subpath Compendium) say how each pool is gained; none was automated, so the features
spending them were rarely usable. Each pool below is kept for a creature that holds it (the compiler only gives the pool to a
character whose features name it). One event grants at most one; a normal gain is once per round across all triggers
(``_round_pool_gain:<resource>`` turn flag, an integer round, kept across reloads); a direct gain a feature grants may ignore
the round limit but never the maximum.

  Thunder Charge (Adamant Thunderbolt Body, max PB): after Stamina Guard reduces a hostile packet by at least PB; after a
      successful save against a hostile creature's Strength or Constitution save; after taking hostile Lightning, Thunder or
      Force damage; after hitting with an attack after moving at least 10 feet this turn.
  Demon Spine (Black Thorn Demon Body, max PB): after hostile Piercing or Slashing damage reaches your Hit Points, or hostile
      damage from a creature within your unarmed reach.
  Body Beat (Heaven-Thunder Drum Body, max PB, PB + 2 with Heaven-Drum Circulation): after hitting a hostile creature with an
      unarmed strike after moving at least 10 feet this turn; after taking hostile damage (Hit Points or Temporary HP);
      after Stamina Guard reduces a hostile packet by at least 1.

  Rebirth Ember (Phoenix Rebirth Body, max PB): after hostile damage that takes at least PB Hit Points in one packet; after
      failing a save whose failure Blinds, Deafens, Frightens, Poisons, Restrains or Stuns you; with Furnace Without Fuel,
      after hostile Fire damage of at least PB before your Immunity.
  Momentum (Returning-Heaven Momentum Body, max PB, PB + 3 with Avalanche Meridian Circuit): after moving at least 20 feet
      willingly during your turn; after a hostile push, pull or teleport of at least 10 feet; after hostile damage reaches you;
      after Stamina Guard reduces a packet by at least PB. The normal grant is 2 with Avalanche Meridian Circuit.
  Celestial Mark (Nine-Star Meridian Body, max PB, PB + 3 with Constellation Circuit): 1 when Initiative is rolled (3 with
      Constellation Circuit; the fight's first turn start); once per round after an Action, Bonus Action or Reaction of a Body
      Refining Path or Subpath feature on which the fighter spent Stamina has resolved.
  Brood (Ten-Thousand Parasite Vessel, max PB, PB + 3 while Ten-Thousand Worm Demon Body lasts): after hostile damage applies at
      least 1 damage to your Hit Points.

``gain(engine, actor, resource, source, *, normal=True, count=1) -> int`` stores and returns how many were gained.
A pool whose rule names ``overflow`` records a gain it could not store (at maximum) in the owner's ``_round_pool_overflow:<resource>``
turn flag for the plug-in that owns the overflow benefit (nine_star.py).
Teleportation does not count as movement here; forced movement never does.
"""

from __future__ import annotations

from typing import Any

from . import hook

THUNDER = "resource:named.thunder_charge"
SPINE = "resource:named.demon_spine"
BEAT = "resource:named.body_beat"
CELESTIAL = "resource:named.celestial_mark"
EMBER = "resource:named.rebirth_ember"
BROOD = "resource:named.brood"
MOMENTUM = "resource:named.momentum"
AVALANCHE = "tianxia.subpath.body.returning_heaven_momentum_body.feature.avalanche_meridian_circuit"
FURNACE = "tianxia.subpath.body.phoenix_rebirth_body.feature.furnace_without_fuel"
CONSTELLATION = "tianxia.subpath.body.nine_star_meridian_body.feature.constellation_circuit"
POOLS: dict[str, dict[str, Any]] = {
    THUNDER: {"soak_min": "pb", "saves": ("STR", "CON"), "damage_types": ("LIGHTNING", "THUNDER", "FORCE"), "hit_after_move": "any"},
    SPINE: {"damage_types": ("PIERCING", "SLASHING"), "hp_only": True, "within_reach": True, "max_bonus_state": {"calamity_briar_incarnation": 3}},
    BEAT: {"soak_min": 1, "damage_any": True, "hit_after_move": "unarmed",
           "max_bonus": {"tianxia.subpath.body.heaven_thunder_drum_body.feature.heaven_drum_circulation": 2}},
    MOMENTUM: {"soak_min": "pb", "damage_any": True, "moved_ft": 20, "forced_ft": 10, "normal_count_with": {AVALANCHE: 2}},
    EMBER: {"hp_min": "pb", "saves_imposing": ("blinded", "deafened", "frightened", "poisoned", "restrained", "stunned"), "fire_before_immunity": FURNACE},
    CELESTIAL: {"initiative_with": {CONSTELLATION: 3}, "max_bonus": {CONSTELLATION: 3}, "overflow": True},
    BROOD: {"hp_min": 1, "max_bonus_state": {"ten_thousand_worm_demon_body": 3}},
}


def _pb(actor: Any) -> int:
    return int(getattr(actor, "proficiency_bonus", 0) or 2)


def maximum(engine: Any, actor: Any, resource: str) -> int:
    rule = POOLS.get(resource) or {}
    bonus = 0
    for feature, extra in (rule.get("max_bonus") or {}).items():
        if any(((a.parameters or {}).get("typed") or {}).get("source") == feature for a in engine.action_catalog.values() if a.owner_id == actor.entity_id) \
                or any(str(row.get("feature_id") or "") == feature for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])):
            bonus += int(extra)
    if rule.get("max_bonus_state"):  # a bonus that lasts while a named state does (Ten-Thousand Worm Demon Body)
        from .states import active

        bonus += sum(int(extra) for name, extra in rule["max_bonus_state"].items() if active(engine, actor, name))
    maximum = min(int(actor.resource_maximums.get(resource, 0) or 0), _pb(actor) + bonus)
    from . import run_strict
    for cap in run_strict('subpath_pool_maximum', engine, actor, resource, maximum):
        if type(cap) is not int or cap < 0:
            raise ValueError('A pool maximum cap must be a nonnegative integer.')
        maximum = min(maximum, cap)
    return maximum


def gain(engine: Any, actor: Any, resource: str, source: str, *, normal: bool = True, count: int = 1) -> int:
    if resource not in (actor.resources or {}) or not actor.active:
        return 0
    flag = "_round_pool_gain:" + resource
    if normal and actor.turn_flags.get(flag) == int(engine.state.round_number):
        return 0
    if normal:  # a larger normal grant (Avalanche Meridian Circuit: "gain 2 instead")
        count = max([int(count), *(int(n) for f, n in ((POOLS.get(resource) or {}).get("normal_count_with") or {}).items() if _owns(engine, actor, f))])
    room = max(0, maximum(engine, actor, resource) - int(actor.resources.get(resource, 0) or 0))
    if int(count) > room and (POOLS.get(resource) or {}).get("overflow"):
        key = "_round_pool_overflow:" + resource
        actor.turn_flags[key] = int(actor.turn_flags.get(key) or 0) + int(count) - room
        if normal and room <= 0:
            actor.turn_flags[flag] = int(engine.state.round_number)  # the overflow still counts as the round's normal gain
    count = min(int(count), room)
    if count <= 0:
        return 0
    engine._gain_resource(actor, resource, count, source)
    if normal:
        actor.turn_flags[flag] = int(engine.state.round_number)
    return count


def _owns(engine: Any, actor: Any, feature: str) -> bool:
    return any(((a.parameters or {}).get("typed") or {}).get("source") == feature for a in engine.action_catalog.values() if a.owner_id == actor.entity_id) \
        or any(str(row.get("feature_id") or "") == feature for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


def _body_refining(source: str) -> bool:
    return "tianxia.path.body_refining" in str(source) or "tianxia.subpath.body." in str(source)


def _stamina_on_body_feature(engine: Any, actor: Any, stop: str) -> bool:
    """Stamina spent by ``actor`` on a Body Refining Path or Subpath feature since the latest ``stop`` event of its own."""
    for event in reversed(engine.events):
        if event.event_type == stop and event.actor_id == actor.entity_id:
            return False
        payload = event.payload or {}
        if event.event_type == "RESOURCE_SPENT" and event.actor_id == actor.entity_id and payload.get("resource_id") == "resource:core.stamina" \
                and _body_refining(event.source_definition_id):
            return True
    return False


@hook("action_completed")
def stamina_activation(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    for resource in _held(actor):
        if POOLS[resource].get("stamina_activation") and _stamina_on_body_feature(engine, actor, "INTENT_ACCEPTED"):
            gain(engine, actor, resource, "system:subpath_pool")


@hook("turn_start")
def initiative_grant(engine: Any, actor: Any) -> None:
    """"Gain 1 when Initiative is rolled" (3 with Constellation Circuit): once, when the fight's first turn starts."""
    if int(engine.state.round_number) != 1:
        return
    for owner in engine.state.actors.values():
        for resource in _held(owner):
            rule = POOLS[resource]
            if not rule.get("initiative") or owner.turn_flags.get("_round_pool_initiative:" + resource):
                continue
            owner.turn_flags["_round_pool_initiative:" + resource] = 1
            amount = max([int(rule["initiative"]), *(int(n) for f, n in (rule.get("initiative_with") or {}).items() if _owns(engine, owner, f))])
            gain(engine, owner, resource, "system:subpath_pool_initiative", normal=False, count=amount)


def _held(actor: Any) -> list[str]:
    return [resource for resource in POOLS if resource in (actor.resources or {})]


def moved_on_foot(engine: Any, actor: Any) -> int:
    """Willing movement this turn, without teleports or forced movement."""
    total = 0
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED" and event.actor_id == actor.entity_id:
            break
        payload = event.payload or {}
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and not payload.get("forced") and not payload.get("teleport"):
            total += max(0, len(payload.get("path") or []) - 1) * engine.grid.square_size_ft
    return total


@hook("event")
def pool_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    last = engine.events[-1] if engine.events else None
    if event_type == "REACTION_RESOLVED" and last is not None and _body_refining(last.source_definition_id):
        reactor = engine.state.actors.get(kwargs.get("actor_id") or "")
        for resource in _held(reactor) if reactor is not None else []:
            if POOLS[resource].get("stamina_activation") and _stamina_on_body_feature(engine, reactor, "REACTION_WINDOW_OPENED"):
                gain(engine, reactor, resource, "system:subpath_pool")
    if event_type == "REACTION_RESOLVED" and last is not None and str(last.source_definition_id).endswith("feature.stamina_guard"):
        actor = engine.state.actors.get(kwargs.get("actor_id") or "")
        reduced = int((kwargs.get("payload") or {}).get("reduction") or 0)
        for resource in _held(actor) if actor is not None else []:
            rule = POOLS[resource]
            least = _pb(actor) if rule.get("soak_min") == "pb" else int(rule.get("soak_min") or 0)
            if rule.get("soak_min") is not None and reduced >= least:
                gain(engine, actor, resource, "tianxia.path.body_refining.feature.stamina_guard")
    elif event_type == "MOVEMENT_COMMITTED":
        _movement_gains(engine, kwargs)
    elif event_type == "DAMAGE_COMMITTED":
        payload = kwargs.get("payload") or {}
        source = engine.state.actors.get(kwargs.get("actor_id") or "")
        kind = str(payload.get("damage_type") or "").upper()
        if payload.get("gate_damage"):
            return
        for target_id in kwargs.get("target_ids") or ():
            actor = engine.state.actors.get(target_id)
            if actor is None or source is None or source.team_id == actor.team_id:
                continue
            for resource in _held(actor):
                rule = POOLS[resource]
                hp = int(payload.get("hp_damage") or 0)
                total = hp + int(payload.get("temporary_hp_absorbed") or 0)
                ok = (rule.get("damage_any") and total >= 1) or (kind in (rule.get("damage_types") or ()) and (hp if rule.get("hp_only") else total) >= 1)
                ok = ok or (rule.get("hp_min") == "pb" and hp >= _pb(actor)) or (isinstance(rule.get("hp_min"), int) and hp >= rule["hp_min"])
                ok = ok or (rule.get("fire_before_immunity") and kind == "FIRE" and _owns(engine, actor, rule["fire_before_immunity"])
                            and int(payload.get("rolled_or_pending_damage") or 0) >= _pb(actor))
                if not ok and rule.get("within_reach") and total >= 1:
                    from ..typed_reactions import attack_reaches

                    ok = attack_reaches(engine, actor, source, {"attack_kind": "unarmed"})
                if ok:
                    gain(engine, actor, resource, "system:subpath_pool")


def _movement_gains(engine: Any, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None:
        return
    for resource in _held(actor):
        rule = POOLS[resource]
        if rule.get("moved_ft") and not payload.get("forced") and not payload.get("teleport") and engine.state.current_actor_id == actor.entity_id \
                and moved_on_foot(engine, actor) >= int(rule["moved_ft"]):
            gain(engine, actor, resource, "system:subpath_pool")
        elif rule.get("forced_ft") and (payload.get("forced") or payload.get("teleport")):
            source = engine.state.actors.get(str(payload.get("dragged_by") or "")) or _forcer(engine)
            if source is not None and source.team_id != actor.team_id and _forced_this_action(engine, actor) >= int(rule["forced_ft"]):
                gain(engine, actor, resource, "system:subpath_pool")


def _forcer(engine: Any) -> Any:
    intent = getattr(engine, "_active_intent", None)
    return engine.state.actors.get(str(getattr(intent, "actor_id", "") or "")) if intent is not None else None


def _forced_this_action(engine: Any, actor: Any) -> int:
    """Feet ``actor`` was moved against its will since the current action began."""
    total = 0
    for event in reversed(engine.events):
        if event.event_type == "INTENT_ACCEPTED":
            break
        payload = event.payload or {}
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and (payload.get("forced") or payload.get("teleport")):
            path = payload.get("path") or []
            total += max(0, len(path) - 1) * engine.grid.square_size_ft if path else 0
    return total


@hook("after_save_resolved")
def pool_saves(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    if subject is None or failed or ctx.actor.team_id == subject.team_id:
        return
    for resource in _held(subject):
        if str(ability).upper()[:3] in (POOLS[resource].get("saves") or ()):
            gain(ctx.engine, subject, resource, "system:subpath_pool")


@hook("after_save_resolved")
def pool_failed_saves(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    if subject is None or not failed or ctx.actor.team_id == subject.team_id:
        return
    for resource in _held(subject):
        wanted = set(POOLS[resource].get("saves_imposing") or ())
        if wanted & set(named or ()) and any(c.condition_id.rsplit(".", 1)[-1] in wanted for c in subject.conditions.values()):
            gain(ctx.engine, subject, resource, "system:subpath_pool")


@hook("after_hit")
def pool_hits(ctx: Any, target: Any, kind: str) -> None:
    actor = ctx.actor
    if target is None or target.team_id == actor.team_id:
        return
    for resource in _held(actor):
        need = POOLS[resource].get("hit_after_move")
        if need and (need == "any" or kind == need) and moved_on_foot(ctx.engine, actor) >= 10:
            gain(ctx.engine, actor, resource, "system:subpath_pool")


@hook('match_start')
def initiative_pools_at_genesis(engine: Any) -> None:
    """The constructed roster exists here; the initial turn precedes state binding."""
    initiative_grant(engine, engine.state.actors[engine.state.current_actor_id])
