"""Foundation resource triggers and body-pressure save bonuses (owner 2026-09-28: "we need to automate every aspect before
another playtest"): Ancient Desolate Sacred Body's Golden Sea Pulse, which Golden Sea Guard and Saint-Body Rebuke spend,
and Saint-Body Frame's once-per-round bonus against what tries to seize the body.

Rows in the bundle's typed_passives (combat/rules/feature_blocks.json, compiled by combat/typed_reactions.py compile_blocks);
a fight saved before they existed has none and replays unchanged.

  generate    gain 1 of ``resource_id`` (up to ``max``, at most ``per_round`` a round) after one of ``on``:
                damaged        it takes damage from a hostile creature and is still conscious
                hit_aggressor  its melee hit within 5 feet on a creature that damaged it, moved it or put a condition on it
                               since the start of its previous turn
                pressure_save  it made a save with its save_bonus (Saint-Body Frame's "eligible resistance roll")
              ``expires``: "end_of_next_turn" -- gone at the end of its next turn (a Pulse gained on its own turn lasts
              through the following one)
  save_bonus  +``bonus`` to a save of ``abilities`` against ``against`` (conditions, or "forced_movement"), once a round

A resource gained by an event is gained after that event has resolved, so it cannot pay for that same event (Golden Sea
Guard reduces damage as it lands; the Pulse that damage generates comes after).
"""

from __future__ import annotations

from typing import Any

CLOCK = "pressure_round_clock"  # a turn flag: kept across turns ("_round_") and restored when a saved fight is reloaded


def _rows(engine: Any, actor: Any, block: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if row.get("block") == block]


def _clock(engine: Any, actor: Any) -> dict[str, Any]:
    """Per-resource bookkeeping kept on the fighter. It lives in a turn flag whose key survives turn resets: a fight
    reloads by replaying its events, which restore turn flags but not a condition's data changed in place."""
    return actor.turn_flags.setdefault(CLOCK, {})


def generate(engine: Any, actor: Any, reason: str, *, event: Any = None, require_opt_in: bool = False) -> bool:
    """Gain (or, for a row with ``refresh``, renew) the resource; True when it did. ``refresh`` (sys-resources-states 2026-09-29):
    "if already held, refresh expiration instead of stacking" (Old Light, Heavenly Integrity, Crane Breath, Glass Reflection).

    ``require_opt_in`` is set by the same-team hostile-damage path: only a row whose
    ``resource_generation_allowed`` provider returns True generates there. Legacy rows
    have no such provider, so a GM pair relation override cannot widen their trigger."""
    done = False
    for row in _rows(engine, actor, "generate"):
        if reason not in (row.get("on") or []):
            continue
        from .feature_availability import available
        from . import ext
        if not available(engine, actor, row['feature_id']):
            continue
        replies = ext.run_strict('resource_generation_allowed', engine, actor, row, reason, event)
        if False in replies or (require_opt_in and True not in replies):
            continue
        resource = str(row.get("resource_id") or "")
        if not resource or resource not in actor.resources or not actor.active or actor.current_hp <= 0:
            continue
        held = actor.resources.get(resource, 0) >= int(row.get("max") or actor.resource_maximums.get(resource, 1))
        if held and not row.get("refresh"):
            continue
        clock = _clock(engine, actor)
        entry = clock.get(resource) or {}
        if int(row.get("per_round") or 0) and entry.get("round") == engine.state.round_number and int(entry.get("count") or 0) >= int(row["per_round"]):
            continue
        if not held:
            engine._gain_resource(actor, resource, 1, f"passive:{row['feature_id']}")
        own_turn = engine.state.current_actor_id == actor.entity_id
        clock[resource] = {"round": engine.state.round_number,
                           "count": (int(entry.get("count") or 0) if entry.get("round") == engine.state.round_number else 0) + 1,
                           **({"ends_left": 2 if own_turn else 1} if row.get("expires") == "end_of_next_turn" else {})}
        done = True
    return done


def on_turn_ended(engine: Any, actor: Any) -> None:
    """A Pulse that lasts until the end of its holder's next turn runs out."""
    if not _rows(engine, actor, "generate"):
        return
    clock = actor.turn_flags.get(CLOCK) or {}
    for resource, entry in list(clock.items()):
        if not isinstance(entry, dict) or "ends_left" not in entry:
            continue
        entry["ends_left"] = int(entry["ends_left"]) - 1
        if entry["ends_left"] <= 0:
            del entry["ends_left"]
            held = int(actor.resources.get(resource, 0) or 0)
            if held > 0:
                engine._spend_resource(actor, resource, held, "passive:resource_clock.expired")


def after_damage(engine: Any, event: Any) -> None:
    source = engine.state.actors.get(event.actor_id or "")
    if int((event.payload or {}).get("hp_damage") or 0) + int((event.payload or {}).get("temporary_hp_absorbed") or 0) <= 0:
        return
    from .relations import ENEMY, relation

    for target_id in event.target_ids or ():
        target = engine.state.actors.get(target_id)
        if target is None or source is None:
            continue
        if source.team_id != target.team_id:
            # The established trigger for every existing row: different teams are
            # hostile, independent of relation overrides.
            generate(engine, target, "damaged", event=event)
        elif relation(engine, source, target) == ENEMY:
            # A pair relation override to ENEMY makes same-team damage hostile in the
            # printed sense (relations.py: callers ask relation(), never compare team
            # identifiers), but only a row whose provider explicitly opts in generates.
            # Golden Sea Pulse, Old Light, Crane Breath, Glass Reflection and every
            # other legacy row keep the different-team rule.
            generate(engine, target, "damaged", event=event, require_opt_in=True)


def _pressed_by(engine: Any, actor: Any, other: Any) -> bool:
    """Whether ``other`` damaged ``actor``, moved it or put a condition on it since the start of ``actor``'s previous turn."""
    from .ext.retained_updates import is_retained_update

    starts = 0
    for event in reversed(engine.events):
        if is_retained_update(event.event_type, event.payload or {}):
            continue
        if event.event_type == "TURN_STARTED" and event.actor_id == actor.entity_id:
            starts += 1
            if starts >= 2:
                return False
        if event.actor_id == other.entity_id and actor.entity_id in (event.target_ids or ()) and \
                event.event_type in ("DAMAGE_COMMITTED", "CONDITION_APPLIED", "MOVEMENT_COMMITTED"):
            return True
        if event.event_type == "CONDITION_APPLIED" and (event.payload or {}).get("source_actor_id") == other.entity_id and event.actor_id == actor.entity_id:
            return True
    return False


def after_hit(engine: Any, actor: Any, target: Any, *, ranged: bool) -> None:
    if ranged or not _rows(engine, actor, "generate") or engine.grid.distance_ft(actor.position, target.position) > 5:
        return
    if any("hit_aggressor" in (row.get("on") or []) for row in _rows(engine, actor, "generate")) and _pressed_by(engine, actor, target):
        generate(engine, actor, "hit_aggressor")


def save_advantage(engine: Any, actor: Any, ability: str, against: set[str]) -> bool:
    """Always-on Advantage on a save against these conditions (Tempered Flesh, Meridian Reinforcement: "defense" rows of kind
    "save_advantage"; an empty ``abilities`` list is any save)."""
    from . import typed_reactions

    wanted = {value.lower() for value in against}
    return any(row.get("kind") == "save_advantage" and (not row.get("abilities") or str(ability or "").upper()[:3] in row["abilities"])
               and set(row.get("against") or []) & wanted for row in typed_reactions._rows(engine, actor.entity_id, "defense"))


def save_bonus(engine: Any, actor: Any, ability: str, against: set[str]) -> tuple[int, str | None]:
    """(bonus, feature id) for a save against body pressure, once a round."""
    for row in _rows(engine, actor, "save_bonus"):
        if str(ability or "").upper()[:3] not in [str(value).upper()[:3] for value in row.get("abilities") or []]:
            continue
        if not {str(value).lower() for value in row.get("against") or []} & {value.lower() for value in against}:
            continue
        clock = _clock(engine, actor)
        key = f"save_bonus:{row['feature_id']}"
        if clock.get(key) == engine.state.round_number:
            continue
        clock[key] = engine.state.round_number
        return int(row.get("bonus") or 0), str(row["feature_id"])
    return 0, None


def after_pressure_save(engine: Any, actor: Any) -> None:
    generate(engine, actor, "pressure_save")
