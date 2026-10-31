"""Guiding Candle: a placed hour-long candle, created with Mold Wax or Press Seal.

The candle is a placed zone, not a light on the caster and not the later flare.
Creation is optional and shares the parent action's wax location and cost.
The Bonus Action chooses one existing candle within 60 feet. Its separate,
source-turn-timed flare grants sight-gated nonmagical terrain footing nearby.
All persisted references are strings/integers; ordinary zone/condition clocks
and events handle expiry, commit and replay. No owned talent means no hooks.
"""
from typing import Any

from . import effect, hook, placed

FEATURE = "TAL_WAX_GUIDING_CANDLE"
PARENTS = {"TAL_WAX_MOLD_WAX", "TAL_WAX_PRESS_SEAL"}
TAG = "guiding_candle"
FLARE = "condition:typed.guiding_candle_flare"


@hook("compile_passives")
def ownership(rows: list[dict[str, Any]], info: dict[str, Any]) -> list[dict[str, Any]] | None:
    if FEATURE in info["owned_ids"]:
        return [*rows, {"block": TAG, "feature_id": FEATURE, "choice_owner": True}]
    return None


def _owns(engine: Any, actor: Any) -> bool:
    return any(row.get("block") == TAG for row in
               (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ()))


@hook("technique_used")
def create(ctx: Any) -> None:
    if not _owns(ctx.engine, ctx.actor):
        return
    if ctx.typed.get("source") not in PARENTS and not ctx.source.endswith(".wax.press_seal_ally"):
        return
    from .needle import ask, checkpoint_id
    from .. import light_sources

    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, TAG, ctx.source), ctx.actor,
        "choice:needle.guiding_candle_create", ["create"], allow_decline=True,
        name="Guiding Candle", feature_id=FEATURE,
        labels={"create": "Create a candle at the wax: bright light 10 feet, dim light another 10 feet, for 1 hour; no extra cost"},
        prompt=f"Guiding Candle: {ctx.actor.display_name} used {ctx.action.display_name}. Create a candle at the wax?")
    if not chosen:
        return
    cell = (ctx.destination or ctx.damage_cache.get("_checkpoint_aim")
            or (ctx.target.position if ctx.target is not None else ctx.actor.position))
    placed.place(ctx.engine, ctx.actor, source=ctx.source, tag=TAG, cells=[cell],
        name="Guiding Candle", duration_rounds=600, material="wax",
        extra={"visual": {"material": "wax", "light": light_sources.light(FEATURE)}})


def _in_range(engine: Any, actor: Any) -> list[Any]:
    from . import ai_controlled
    from .. import senses

    # No printed sight requirement. Humans can name any candle; automatic
    # seats know their own placements or candles they can currently perceive.
    return [zone for zone in placed.of(engine, TAG)
            if engine._distance_actor_to_cell(actor, zone.center) <= 60
            and (not ai_controlled(engine, actor) or zone.owner_id == actor.entity_id
                 or senses.perceives_cell(engine, actor, zone.center))]


@hook("candidate_allowed")
def flare_available(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if any(row.get("type") == "guiding_candle_flare"
           for row in (getattr(action, "parameters", {}).get("typed") or {}).get("effects") or []):
        return bool(_in_range(engine, actor))
    return None


@effect("guiding_candle_flare")
def flare(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id
    from .effect_durations import token

    candles = _in_range(ctx.engine, ctx.actor)
    labels = {z.zone_id: f"Flare Guiding Candle at ({z.center.x}, {z.center.y}): allies who see it ignore nonmagical Difficult Terrain within 10 feet until your next turn starts"
              for z in candles}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, TAG, "flare"), ctx.actor,
        "choice:needle.guiding_candle_flare", list(labels), labels=labels,
        name="Guiding Candle", feature_id=FEATURE,
        prompt=f"Guiding Candle: {ctx.actor.display_name} uses a Bonus Action. Choose a candle within 60 feet to flare.")
    if picked:
        ctx.engine._apply_condition(ctx.actor, FLARE, FEATURE, ctx.actor.entity_id,
            expires_on=token("start", ctx.actor.entity_id, int(ctx.actor.turns_started) + 1),
            data={"candle_id": picked[0], "label": "Guiding Candle: nearby allies who see the flaring candle ignore nonmagical Difficult Terrain until your next turn starts"})


@hook("difficult_exempt")
def footing(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    from .. import senses, zones
    from .area_suppression import magical

    if not actor.active:
        return None
    covered: set[tuple[int, int]] = set()
    for owner in engine.state.actors.values():
        if owner.team_id != actor.team_id:
            continue
        for held in owner.conditions.values():
            if held.condition_id != FLARE:
                continue
            candle = engine.state.zones.get(held.data.get("candle_id"))
            if candle is None or not candle.active:
                continue
            if not senses.perceives_cell(engine, actor, candle.center):
                continue
            covered.update((cell.x, cell.y) for cell in placed.area(engine, candle.center, "sphere", 10))
    if not covered:
        return None
    # Bare map-painted movement costs need no typed zone. Keep those covered,
    # but never waive overlapping magical (or unclassified created) terrain.
    blocked = {(cell.x, cell.y) for zone in zones.typed_zones(engine)
               if zone.owner_id != zones.MAP_OWNER and magical(zone) is not False
               and zones.zone_is_difficult(engine, zone, actor) for cell in zone.affected_cells}
    return covered - blocked
