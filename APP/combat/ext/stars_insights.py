"""Printed Stars Insight clauses, sealed into new bundles only.

Cold Star Heart retains its existing defense row. Its additional ownership flag
is added at compile time, never inferred from a live sheet in an old fight.
Comet Adept uses a confirmed attack roll or a typed damage roll, not an attack
preview: a miss cannot spend its once-per-turn allowance. Seven-Star Battle
Rhythm waits for an actual attack roll before consuming its next-attack grant.
Rules: authority/typed_mechanics/rules_text.json, the insight.* entries below.
Star-Walking Immortal's range clause composes with native Starpath grants.
Its passenger and unseen-anchor clauses still need production map delivery;
the range transform does not claim to implement those clauses.
"""
from typing import Any
from contextlib import contextmanager

from . import hook
from .passive_rows import row_of
from . import stars

BLOCK = "stars_insights"
COLD = "insight.cold-star-heart"
COMET = "insight.comet-adept"
RHYTHM = "insight.seven-star-battle-rhythm"
WALKING = "insight.star-walking-immortal"
STARPATH = "tianxia.talent.stars.starpath_step"
WALKING_SOURCE_HASH = "086759d9a973bf90f989ebf2681920e708c617fb31c1284d9f00f62fa4310749"
READY = "condition:typed.stars_battle_rhythm"
STEP = "_stars_battle_rhythm_hit"
COMET_USED = "stars_insights_comet_turn"
COLD_USED = "stars_insights_cold_turn"
COMET_ROLL = "_stars_insights_comet_roll"
COMET_ROWS = "_stars_insights_comet_rows"


@hook("compile_action")
def star_walking_range(action, info):
    """Extend the owned, source-sealed Step once, including its free variant.

    factory_compiler supplies native sheet ownership and typed source records;
    typed_executor.block_movement consumes the resulting movement distance.
    Modify only the base self-movement row: conditional alignment remains an
    additional 10 feet, not another application of the Insight's 20 feet.
    """
    import copy

    if WALKING not in (info.get("owned_ids") or ()):
        return None
    source = ((info.get("mechanics") or {}).get(WALKING) or {}).get("source") or {}
    if source.get("text_sha256") != WALKING_SOURCE_HASH:
        return None
    typed = (action.parameters or {}).get("typed") or {}
    if (typed.get("source") != STARPATH
            or (action.parameters or {}).get("star_walking_range_source")):
        return None
    parameters = copy.deepcopy(action.parameters)
    row = next((row for row in parameters["typed"].get("effects", ())
                if row.get("type") == "movement" and row.get("applies_to") in (None, "self")
                and row.get("mode") != "teleport" and type(row.get("distance_ft")) is int
                and row["distance_ft"] > 0), None)
    if row is None:
        return None
    before = row["distance_ft"]
    row["distance_ft"] = before + 20
    row["evidence"] = str(row.get("evidence") or "") + " Star-Walking Immortal: Starpath Step range increases by 20 feet."
    parameters["star_walking_range_source"] = {"feature_id": WALKING, "text_sha256": WALKING_SOURCE_HASH,
                                               "distance_ft": 20}
    parameters["description"] = (str(parameters.get("description") or "")
                                 + " Star-Walking Immortal adds 20 feet to this Starpath Step movement, at no extra cost.").strip()
    if type(parameters["typed"].get("range_ft")) is int:
        parameters["typed"]["range_ft"] += 20
    # The sovereign producer prints its own distance in the variant's name.
    name = action.display_name.replace(f": {before} feet,", f": {before + 20} feet,")
    return action.model_copy(update={"parameters": parameters, "display_name": name,
                                     "range_ft": action.range_ft + 20 if action.range_ft is not None else None})


def owns(engine: Any, actor: Any, feature: str) -> dict | None:
    if actor is not None and feature == COLD:
        return next((row for row in engine.typed_passive_rows.get(actor.entity_id, ())
                     if row.get("feature_id") == COLD and row.get("stars_cold_bypass") == 1), None)
    return row_of(engine, actor.entity_id, BLOCK, feature) if actor is not None else None


def turn(engine: Any) -> int:
    return int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)


@hook("compile_block")
def compile_rows(block, spec, row, numbers):
    if block != BLOCK:
        return None
    outcomes = {
        WALKING: "Starpath Step gains 20 feet of range at no extra cost",
        COMET: "Once per turn, add your Proficiency Bonus to a Radiant, Force, or Cold Stars damage roll; you may push a marked target 5 feet at no extra cost",
        RHYTHM: "After Starpath Step or Seven-Star Step, your next attack this turn gains +1 to hit; a marked hit lets you move 5 feet without opportunity attacks at no extra cost",
    }
    return [{**row, "kind": row["feature_id"], "pb": int(numbers["pb"]), "choice_owner": 1,
             "player_outcome": outcomes[row["feature_id"]]}]


@hook("compile_passives")
def cold_ownership(passives, info):
    if COLD not in (info.get("owned_ids") or ()):
        return passives
    return [{**row, "stars_cold_bypass": 1,
             "player_outcome": "Cold damage is halved; once per turn, you may ignore a target's Cold Resistance for damage from a Stars talent at no extra cost; Cold Immunity remains unchanged"}
            if row.get("feature_id") == COLD and row.get("kind") == "resistance" else row
            for row in passives]


def stars_talent(typed):
    source = str((typed or {}).get("source") or "")
    return ((typed or {}).get("sphere") == "tianxia.sphere.stars"
            and (source.startswith("tianxia.talent.stars.") or source.startswith("STARS_")))


def comet_bonus(ctx, targets=None):
    owned = owns(ctx.engine, ctx.actor, COMET)
    if not owned or not stars_talent(ctx.typed) or ctx.actor.turn_flags.get(COMET_USED) == turn(ctx.engine):
        return None
    if str(getattr(ctx.engine, "_typed_pending_damage_type", "")).lower() not in stars.STAR_TYPES:
        return None
    from ..typed_reactions import damage_factor
    recipients = ctx.targets if targets is None else targets
    kind = str(ctx.engine._typed_pending_damage_type)
    # A wholly immune area/strike deals no qualifying damage. Query without a
    # source actor, so this preview cannot open a Cold Star Heart choice.
    if recipients and not any(damage_factor(ctx.engine, target, kind, ctx.source, None) > 0
                              for target in recipients):
        return None
    return int(owned["pb"])


@hook("damage_roll_bonus")
def comet_damage(ctx, effect, kinds=None):
    if effect is None:
        return None  # attack-sequence dice are shaped before the hit exists
    bonus = comet_bonus(ctx, ctx.damage_cache.get("_area_targets") or ctx.targets)
    if bonus:
        key = comet_roll_key(effect)
        ctx.damage_cache[COMET_ROLL] = key
        ctx.damage_cache.setdefault(COMET_ROWS, set()).add(key)
    return bonus


def comet_roll_key(effect):
    """Use the executor's shared-roll identity, including grouped damage rows."""
    group = effect.get("damage_bonus_group")
    return f"damage_bonus_roll:{group}" if group else id(effect)


@hook("damage_roll_resolved")
def comet_cached_roll(ctx, effect, key):
    if not owns(ctx.engine, ctx.actor, COMET):
        return
    # Both ordinary dispatch and direct save-for-half delivery retrieve the
    # actual roll here. A later unboosted row must clear the earlier marker.
    ctx.damage_cache.pop(COMET_ROLL, None)
    if key in ctx.damage_cache.get(COMET_ROWS, ()):
        ctx.damage_cache[COMET_ROLL] = key


@hook("effect_resolution_scope")
def comet_roll_scope(ctx, effect):
    if effect.get("type") not in ("damage", "extra_damage") or not owns(ctx.engine, ctx.actor, COMET):
        return None

    @contextmanager
    def scope():
        previous = ctx.damage_cache.pop(COMET_ROLL, None)
        key = comet_roll_key(effect)
        if key in ctx.damage_cache.get(COMET_ROWS, ()):
            ctx.damage_cache[COMET_ROLL] = key  # later recipients share this same damage roll
        try:
            yield
        finally:
            ctx.damage_cache.pop(COMET_ROLL, None)
            if previous is not None:
                ctx.damage_cache[COMET_ROLL] = previous
    return scope()


@hook("confirmed_hit_roll_bonus")
def comet_hit(engine, attacker, target, spec, intent, source):
    from .attack_scope import current
    from ..gate2_runtime_models import DiceSpec

    frame = current(engine)
    if not frame or frame["actor_id"] != attacker.entity_id or frame["source"] != source:
        return None
    if not isinstance(spec.get("damage"), DiceSpec) or spec["damage"].count <= 0:
        return None
    ctx = frame["context"]
    bonus = comet_bonus(ctx, [target])
    if bonus:
        frame[COMET_ROLL] = 1
    return bonus


@hook("attack_roll_finished")
def finished(engine_ctx, target, effect, roll_id):
    from .attack_scope import current

    ctx = engine_ctx
    frame = current(ctx.engine)
    ctx.damage_cache.pop(STEP, None)
    # This copy marks only the confirmed roll's damage, not a later strike.
    ctx.damage_cache.pop(COMET_ROLL, None)
    if frame and frame.get(COMET_ROLL):
        ctx.damage_cache[COMET_ROLL] = "attack"
    if not roll_id or not owns(ctx.engine, ctx.actor, RHYTHM):
        return
    ready = next((c for c in ctx.actor.conditions.values() if c.condition_id == READY), None)
    if ready is None:
        return
    ctx.engine._remove_condition(ctx.actor, READY, ready.source_definition_id)
    ctx.damage_cache[STEP] = target.entity_id


@hook("damage_dealt")
def comet_push(ctx, target, amount):
    if not owns(ctx.engine, ctx.actor, COMET) or not ctx.damage_cache.get(COMET_ROLL):
        return
    # A qualifying roll reserves the bonus; only actual HP/temp-HP damage
    # spends it. Immunity or complete damage reduction leaves it available.
    ctx.actor.turn_flags[COMET_USED] = turn(ctx.engine)
    if not stars.bears_mark(target, ctx.actor.entity_id) or not target.active:
        return
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context
    from ..typed_executor import run_effects

    if not ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "Comet Adept", target.entity_id), ctx.actor,
               "choice:needle.stars_comet", ["push"], allow_decline=True, default="first",
               labels={"push": "Push this marked creature 5 feet; no extra action or resource cost"},
               name="Comet Adept", feature_id=COMET, target_id=target.entity_id,
               prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target),
               prompt=f"Comet Adept: {ctx.actor.display_name}'s {ctx.action.display_name} damages {target.display_name}, "
                      "who bears your Stellar Mark. Push it 5 feet? This costs no extra action or resource."):
        return
    run_effects(ctx.on_hit_context(target), [{"type": "forced_movement", "applies_to": "target",
                                            "distance_ft": 5, "evidence": "Comet Adept: push it 5 feet."}])


@hook("resistance_ignored")
def cold_bypass(engine, kind, typed, source_actor_id, target=None):
    from ..pending_damage import current, packet_scratch
    from ..typed_reactions import damage_factor
    from .needle import ask, checkpoint_id

    actor = engine.state.actors.get(source_actor_id)
    packet, scratch = current(engine), packet_scratch(engine)
    if (kind != "COLD" or not owns(engine, actor, COLD) or not stars_talent(typed)
            or packet is None or scratch is None or target is None or packet.amount <= 0
            or packet.target_id != target.entity_id or packet.source_actor_id != source_actor_id):
        return None
    if COLD in scratch:
        return scratch[COLD] or None
    if actor.turn_flags.get(COLD_USED) == turn(engine):
        return None
    # A source-free query cannot enter this ownership hook and preserves Immunity.
    if damage_factor(engine, target, kind, packet.source_id, None) == 0:
        return None
    action = engine.action_catalog.get(packet.source_id)
    name = getattr(action, "display_name", "Stars talent")
    picked = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "Cold Star Heart", target.entity_id), actor,
                 "choice:needle.stars_cold_heart", ["ignore"], allow_decline=True, default="first",
                 labels={"ignore": "Ignore Cold Resistance for this damage; once per turn, no extra cost"},
                 name="Cold Star Heart", feature_id=COLD, target_id=target.entity_id,
                 prompt_context={"source_definition_id": packet.source_id, "action_name": name,
                                 "affected_id": target.entity_id},
                 prompt=f"Cold Star Heart: {actor.display_name}'s {name} deals Cold damage to {target.display_name}. "
                        "Ignore its Cold Resistance for this damage? Once per turn; no extra action or resource cost. "
                        "Cold Immunity is unchanged.")
    scratch[COLD] = bool(picked)
    if picked:
        actor.turn_flags[COLD_USED] = turn(engine)
        return True
    return None


@hook("technique_used")
def rhythm_ready(ctx):
    if not owns(ctx.engine, ctx.actor, RHYTHM) or ctx.typed.get("source") not in (
            "tianxia.talent.stars.starpath_step", "tianxia.talent.stars.seven_star_step"):
        return
    ctx.engine._remove_condition(ctx.actor, READY, RHYTHM)
    ctx.engine._apply_condition(ctx.actor, READY, RHYTHM, ctx.actor.entity_id,
                               expires_on="END_OF_CURRENT_TURN", data={
                                   "label": "Seven-Star Battle Rhythm: +1 to your next attack this turn; on a marked hit, move 5 feet without opportunity attacks"})


@hook("attack_bonus")
def rhythm_bonus(ctx, actor):
    if actor is ctx.actor and owns(ctx.engine, actor, RHYTHM) and any(
            c.condition_id == READY for c in actor.conditions.values()):
        return 1
    return None


@hook("after_hit_choice")
def rhythm_step(ctx, target, kind):
    if (not owns(ctx.engine, ctx.actor, RHYTHM) or ctx.damage_cache.pop(STEP, None) != target.entity_id
            or not stars.bears_mark(target, ctx.actor.entity_id)):
        return
    from ..typed_executor import run_effects

    run_effects(ctx.on_hit_context(target), [{"type": "rider_step", "distance_ft": 5, "no_oa": True,
                                            "label": "Seven-Star Battle Rhythm"}])
