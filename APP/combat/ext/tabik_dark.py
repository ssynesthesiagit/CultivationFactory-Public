"""The Dark sphere's area talents (owner 2026-09-28: "we need to automate every aspect before another playtest"; Tabik
Damu's kit). combat/zones.py makes and shapes the Darkness; this adds what its talents do to it afterwards:

  Clinging Darkness     augment, 0 CP: the Darkness is centered on a creature and moves with it; an unwilling creature
                        makes a Wisdom save to refuse, and repeats it at the end of each of its turns (effect cling_zone)
  Directional Darkness  augment, 1 CP: those outside see in clearly and those inside can't see out (effect
                        zone_directional; combat/zones.py _blocks). Seeing out from inside is how every Darkness already
                        works on this table, so that choice adds nothing and is not offered.
  Rolling Blackout      augment, 0 CP: a Bonus Action moves one of its Darkness areas up to 30 feet, staying within 120
                        feet of it (action "Rolling Blackout: move Darkness", effect move_zone); Eternal Darkness stays put
  Creeping Lethargy     a failed Wisdom save leaves a creature Lethargic (an Action or a Bonus Action on its turn, not
                        both) until it starts a turn outside; failing again as it starts a turn inside puts it to sleep
                        (Unconscious) until it saves at the start of a turn, takes damage, or starts a turn outside
  Fearful Darkness      Frightened until the creature ends its turn outside the Darkness; a save at the start of a later
                        turn inside ends it
  Dark Slaughter        Meld: while it stands in its own Darkness, +1d6/1d8/1d10/1d12 (by CL) when it hits with
                        Advantage or hits a creature that can't see it; doubled on a critical hit (block dark_slaughter)
  Obfuscation           augment, 1 CP: nothing on the fight table resolves scrying, so the printed effect is stated
                        in plain words as a GM rider at the moment the 1 CP is spent, rather than charging for a
                        silent nothing (hook technique_used; combat/rules/feature_status.d/tabik.json)
  Clearsight            Meld: the target is immune to the negative effects created by its own Darkness talents, so a
                        Darkness it made leaves it untouched (hook zone_talent_immune, asked by combat/zones.py for
                        the inside rows, the triggers, movement, the AI hazard test and Darkvision)
  how they are drawn    the zone_visual hook: which of the Dark sphere's three looks an area gets, from the typed
                        rows that shaped it (owner 2026-10-03 03:38: "a more transparent darkness for regular darkness
                        and still slightly transparent but almost pitch black for pure darkness ... for snagging/
                        clinging darkness we could have dark tentacles you can barely see waving in the area")

Everything keys off the character's own compiled rows and the areas it made; nothing else changes.

Shared Tabik area API. The other Tabik-sphere plug-ins that also make and move Darkness read this module through its public
names, never an underscore-prefixed one: zone_made_now is the area a talent's use just created, movable lists the areas this
character may move (unanchored, not a wall, still running), and republish re-publishes a changed area so a saved fight
replays it as the same area. combat/ext/tabik_ninpo.py and combat/ext/disease_court.py are the current consumers; a further
one must use these public names and be recorded here.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

LETHARGIC = "condition:typed.creeping_lethargy"
ASLEEP = "condition:typed.unconscious"
FRIGHTENED = "condition:typed.frightened"
CLINGS = "condition:typed.darkness_clings"
DARKNESS = "DARK_BASE_DARKNESS"
OBFUSCATION = "TAL_DARK_OBFUSCATION"
DARK_SPHERE = "tianxia.sphere.dark"
# The typed rows that decide which look an area is drawn with. Pure Darkness is the deepest shade; the two that
# reach out and grab a creature (Snagging restrains it on a failed save, Clinging anchors the area to it) get the
# tentacles laid over whatever shade they are.
PURE_DARKNESS = "TAL_DARK_PURE_DARKNESS"
GRASPING_ROWS = frozenset({"TAL_DARK_SNAGGING_DARKNESS", "TAL_DARK_CLINGING_DARKNESS"})
DARKNESS_ROWS = frozenset({DARKNESS, PURE_DARKNESS}) | GRASPING_ROWS


# ------------------------------------------------------------------------------------------------ helpers
def zone_made_now(ctx: Any) -> Any:
    """The area this use of the ability just made."""
    made = [zone for zone in ctx.engine.state.zones.values()
            if zone.active and zone.owner_id == ctx.actor.entity_id and zone.source_definition_id == ctx.source]
    return max(made, key=lambda zone: zone.zone_id.rsplit(":", 1)[-1].zfill(12), default=None)


def republish(engine: Any, zone: Any, source: str) -> None:
    """A changed area is published again (a saved fight replays it as the same area)."""
    from .. import zones

    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})
    zones.sync_inside(engine, source)


def _recenter(engine: Any, zone: Any, center: Any) -> None:
    from .. import zones

    zone.center = center
    zone.affected_cells = zones._cells(engine, center, {"size_ft": zone.trigger_profile.get("size_ft"), "shape": zone.trigger_profile.get("shape"),
                                                        "spreads": zone.trigger_profile.get("spreads"),
                                                        # A run of connected cubes keeps the shape it was made with when the
                                                        # area is moved: the direction is the one stored on the area, not
                                                        # one re-decided from wherever its owner now stands.
                                                        **({"blocks": int(zone.trigger_profile["blocks"]),
                                                            "blocks_along": zone.trigger_profile.get("blocks_along")}
                                                           if int(zone.trigger_profile.get("blocks") or 1) > 1 else {})})  # not through walls (docket)


def _drop_instance(engine: Any, creature: Any, instance_id: str, source: str) -> None:
    condition = creature.conditions.pop(instance_id, None)
    if condition is not None:
        engine._append_event("CONDITION_REMOVED", source, actor_id=condition.source_actor_id, target_ids=(creature.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": instance_id})


def _context(engine: Any, owner: Any, zone: Any, creature: Any) -> Any:
    from .. import typed_executor

    action = engine.action_catalog.get(zone.source_definition_id)
    if action is None:
        return None
    typed = {"effects": [], "numbers": dict(zone.trigger_profile.get("numbers") or {}), "weapon": None, "duration": {"kind": "instant"},
             "riders": [], "source": zone.source_definition_id}
    return typed_executor.Context(engine, owner, action, getattr(engine, "_active_intent", None), typed, [creature], creature, {})


def _zones_with(engine: Any, talent_name: str) -> list[Any]:
    from .. import zones

    return [zone for zone in zones.typed_zones(engine) if talent_name in (zone.trigger_profile.get("talents") or [])]


def _inside_any(engine: Any, creature: Any, rows: list[Any]) -> bool:
    from .. import zones

    return any(zones._inside(engine, creature, zone) for zone in rows)


# ------------------------------------------------------------------------------------------------ Clearsight
CLEARSIGHT = "TAL_DARK_CLEARSIGHT"
CLEARSIGHT_PERMISSION = 'condition:typed.clearsight_creator_permission'


def _owns_darkness(engine: Any, actor: Any) -> bool:
    return any((action.parameters.get('typed') or {}).get('sphere') == DARK_SPHERE
               for aid in actor.action_ids if (action := engine.action_catalog.get(aid)))


@hook('choice_reactors')
def clearsight_choice_owners(engine: Any) -> tuple[str, ...]:
    """Enroll allied creators only in fights with an owned Clearsight action.

    The service filters this potential roster to manual controllers. Actual
    casting still decides which creator is asked, without inferring consent.
    """
    from ..relations import relation, ALLY
    casters = [actor for actor in engine.state.actors.values() if actor.active
               and any(action.parameters.get('meld_talent') == CLEARSIGHT
                       for aid in actor.action_ids if (action := engine.action_catalog.get(aid)))]
    return tuple(creator.entity_id for creator in engine.state.actors.values()
                 if creator.active and _owns_darkness(engine, creator)
                 and any(creator is not caster and relation(engine, creator, caster) == ALLY
                         for caster in casters))


@hook('technique_used')
def allied_clearsight_consent(ctx: Any) -> None:
    """Allied creators decide for their own Darkness, including on AI turns.

    Permission binds to this exact live Meld instance; renewal never inherits an
    earlier creator's answer. No consent is inferred from sharing a team.
    """
    if ctx.action.parameters.get('meld_talent') != CLEARSIGHT:
        return
    from .. import senses
    from ..relations import relation, ALLY
    from .rider_choices import pick
    holder = ctx.target or ctx.actor
    grant = next((c for c in holder.conditions.values() if c.condition_id == senses.MELD
                  and c.data.get('talent') == CLEARSIGHT and c.source_definition_id == ctx.source
                  and c.source_actor_id == ctx.actor.entity_id), None)
    if grant is None:
        return
    for creator in ctx.engine.state.actors.values():
        if creator is ctx.actor or not creator.active or relation(ctx.engine, creator, ctx.actor) != ALLY:
            continue
        if not _owns_darkness(ctx.engine, creator):
            continue
        from .needle import ai_controlled
        if ai_controlled(ctx.engine, creator) and not senses.perceives(ctx.engine, creator, holder):
            continue
        chosen = pick(ctx.engine, creator, 'clearsight_creator_consent', 'Clearsight', ['allow'],
            subject=holder, intent=ctx.intent,
            labels={'allow': 'Let this Clearsight protect the recipient from negative effects of my Darkness talents'},
            prompt=f'Clearsight: {ctx.actor.display_name} grants {holder.display_name} immunity to the negative effects of their Darkness talents. {creator.display_name}, allow this same protection against your Darkness talents for this Meld’s duration? No action or points are spent.')
        if chosen:
            ctx.engine._apply_condition(holder, CLEARSIGHT_PERMISSION, ctx.source, creator.entity_id,
                expires_on='UNTIL_REMOVED', data={'meld_instance': grant.instance_id,
                    'label': f'Clearsight: {creator.display_name} permits protection against their Darkness while this Meld lasts'})


@hook('turn_start')
def retire_clearsight_permissions(engine: Any, actor: Any) -> None:
    from .condition_ownership import remove_instance
    for holder in engine.state.actors.values():
        for condition in list(holder.conditions.values()):
            if condition.condition_id == CLEARSIGHT_PERMISSION and condition.data.get('meld_instance') not in holder.conditions:
                remove_instance(engine, holder, condition.instance_id, condition.source_definition_id)


@hook("zone_talent_immune")
def clearsight_immune(engine: Any, zone: Any, creature: Any) -> bool:
    """An active recipient grant protects against the granting caster's Darkness talents.

    Bundle/pre-fight Clearsight retains its self-creator scope. Recipient markers
    name their caster explicitly and must still be within their clock and actual
    Concentration. An allied creator's accepted permission binds to this exact
    grant and extends only that creator's Darkness immunity.
    """
    if not zone.trigger_profile.get("talents") or not (zone.trigger_profile.get("visual") or {}).get("darkness"):
        return False
    from .. import senses, concentration
    from .effect_durations import due

    for condition in creature.conditions.values():
        data = condition.data or {}
        caster_id = data.get("caster_id") or condition.source_actor_id
        permitted = any(c.condition_id == CLEARSIGHT_PERMISSION and c.source_actor_id == zone.owner_id
                        and c.data.get('meld_instance') == condition.instance_id for c in creature.conditions.values())
        if condition.condition_id != senses.MELD or data.get("talent") != CLEARSIGHT or (caster_id != zone.owner_id and not permitted):
            continue
        caster = engine.state.actors.get(caster_id)
        if caster is None or due(engine, data.get("end_clock")):
            continue
        if data.get("concentration") and not concentration.concentrating_on(caster, data.get("source")):
            continue
        return True
    # Possessing a recipient grant must never imply immunity to the recipient's
    # own areas. The self route needs a compiled, active self Meld.
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or ()
                   if row.get("actor_id") == creature.entity_id), {})
    return bool(creature.entity_id == zone.owner_id and bundle.get("clearsight")
                and senses.meld_active(engine, creature, CLEARSIGHT))


@hook("event", nested=True)
def refresh_meld_immunity(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Re-evaluate continuous Darkness effects when a recipient's Meld changes.

    Immunity queries already read active grants. Existing inside-condition rows
    must follow the same state immediately, including grant, replacement and
    Concentration cleanup; refreshing never fires an area's turn-start damage.
    Native Concentration removals do not always name the condition in their
    receipt, so CONCENTRATION_ENDED is also a refresh boundary after cleanup.
    Nested dispatch is needed when cleanup runs inside another event.
    Zone-effect receipts cannot re-enter this Meld/Concentration-only refresh.
    """
    from .. import senses, zones

    if event_type not in ("CONDITION_APPLIED", "CONDITION_REMOVED", "CONCENTRATION_ENDED"):
        return
    if event_type != "CONCENTRATION_ENDED" and (kwargs.get("payload") or {}).get("condition_id") not in (senses.MELD, CLEARSIGHT_PERMISSION):
        return
    for zone in zones.typed_zones(engine):
        if (zone.trigger_profile.get("visual") or {}).get("darkness"):
            zones.sync_inside(engine, zone.source_definition_id)


# ------------------------------------------------------------------------------------------------ Clinging Darkness
@effect("cling_zone")
def cling_zone(ctx: Any, eff: dict[str, Any]) -> None:
    engine = ctx.engine
    zone = zone_made_now(ctx)
    if zone is None:
        return
    if zone.duration_rounds is None and not zone.concentration_link:
        ctx.rider("Eternal Darkness is stationary: it can't be centered on a creature.")
        return
    aim = getattr(ctx.intent, "destination", None) or zone.center
    creature = next((row for row in sorted(engine.state.actors.values(), key=lambda row: row.entity_id)
                     if row.active and engine._footprint_intersects(row, (aim,))), None)
    if creature is None:
        ctx.rider("Clinging Darkness: no creature at its center; anchoring it to an object is the GM's.")
        return
    if creature.team_id != ctx.actor.team_id:
        from .. import typed_executor

        sub = typed_executor.Context(engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [creature], creature, {})
        typed_executor.run_effects(sub, [{"type": "save", "ability": "wis", "applies_to": "target",
                                          "on_fail": [{"type": "anchor_zone", "zone_id": zone.zone_id}], "on_success": []}])
    else:
        _anchor(engine, zone, creature, ctx.source, save_dc=None)


@effect("anchor_zone")
def anchor_zone(ctx: Any, eff: dict[str, Any]) -> None:
    zone = ctx.engine.state.zones.get(str(eff.get("zone_id") or ""))
    subject = ctx.target
    if zone is not None and zone.active and subject is not None and subject.active:
        _anchor(ctx.engine, zone, subject, ctx.source, save_dc=int(ctx.numbers.get("save_dc") or 10))


def _anchor(engine: Any, zone: Any, creature: Any, source: str, *, save_dc: int | None) -> None:
    zone.trigger_profile = {**zone.trigger_profile, "anchor_id": creature.entity_id}
    _recenter(engine, zone, creature.position)
    republish(engine, zone, source)
    if save_dc is not None:  # an unwilling creature repeats the save at the end of each of its turns
        engine._apply_condition(creature, CLINGS, source, zone.owner_id, expires_on="UNTIL_REMOVED",
                                data={"zone_id": zone.zone_id, "label": "Darkness clings to it (Wisdom save at the end of its turn)"})


def _release(engine: Any, zone: Any, source: str) -> None:
    if zone.trigger_profile.get("anchor_id"):
        zone.trigger_profile = {key: value for key, value in zone.trigger_profile.items() if key != "anchor_id"}
        republish(engine, zone, source)


@effect("release_zone")
def release_zone(ctx: Any, eff: dict[str, Any]) -> None:
    zone = ctx.engine.state.zones.get(str(eff.get("zone_id") or ""))
    subject = ctx.target
    if zone is not None and subject is not None:
        _release(ctx.engine, zone, ctx.source)
        for iid, condition in list(subject.conditions.items()):
            if condition.condition_id == CLINGS and (condition.data or {}).get("zone_id") == zone.zone_id:
                _drop_instance(ctx.engine, subject, iid, ctx.source)


# ------------------------------------------------------------------------------------------------ Directional Darkness
@effect("zone_directional")
def zone_directional(ctx: Any, eff: dict[str, Any]) -> None:
    zone = zone_made_now(ctx)
    if zone is None:
        return
    zone.trigger_profile = {**zone.trigger_profile, "visual": {**(zone.trigger_profile.get("visual") or {}), "sees": "inward"}}
    republish(ctx.engine, zone, ctx.source)


# ------------------------------------------------------------------------------------------------ Rolling Blackout
def movable(engine: Any, actor: Any, name: str = "Darkness") -> list[Any]:
    from .. import zones

    return [zone for zone in zones.typed_zones(engine)
            if zone.owner_id == actor.entity_id and (zone.trigger_profile.get("name") or "") == name and not zone.trigger_profile.get("wall")
            and not zone.trigger_profile.get("anchor_id") and (zone.duration_rounds is not None or zone.concentration_link)]


@hook("compile_actions")
def rolling_blackout(info: dict[str, Any]) -> list[Any] | None:
    if "TAL_DARK_ROLLING_BLACKOUT" not in info["owned_ids"] or DARKNESS not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    spec = (info["mechanics"].get("TAL_DARK_ROLLING_BLACKOUT") or {}).get("modifier") or {}
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.rolling_blackout" + (".action" if economy == "ACTION" else ""),
        display_name="Rolling Blackout: move Darkness" + (" (Action)" if economy == "ACTION" else ""),
        owner_id=info["actor_id"], economy=EconomyKind(economy), resolution_kind="TYPED", target_kind="CELL", range_ft=120,
        parameters={"typed": {"effects": [{"type": "move_zone", "max_ft": 30, "range_ft": 120,
                                           **({"choose_zone": True} if spec.get("choose_zone") else {}),
                                           "evidence": "Move one area of Darkness you created up to 30 feet as an Action or Bonus Action, remaining within the effect's maximum range."}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": "TAL_DARK_ROLLING_BLACKOUT"},
                    "expected_damage": 0, "player_only": True, "rolling_blackout": True, "any_cell": True})
        for economy in spec.get("movement_economies") or ["BONUS_ACTION"]]


@effect("move_zone")
def move_zone(ctx: Any, eff: dict[str, Any]) -> None:
    engine = ctx.engine
    aim = getattr(ctx.intent, "destination", None)
    name = str(eff.get("zone_name") or "Darkness")
    rows = movable(engine, ctx.actor, name)
    if aim is None or not rows:
        ctx.rider(f"No {name} of yours to move.")
        return
    zone = min(rows, key=lambda row: (engine.grid.distance_ft(row.center, aim), row.zone_id))
    if eff.get("choose_zone"):
        from .needle import CHOICE, ask, checkpoint_id

        eligible = sorted((row for row in rows if engine.grid.distance_ft(row.center, aim) <= int(eff.get("max_ft") or 30)),
                          key=lambda row: row.zone_id)
        selected = ask(engine, ctx.intent, checkpoint_id(engine, "ROLLING_BLACKOUT_AREA", ctx.actor.entity_id),
            ctx.actor, CHOICE + "rolling_blackout_area", [row.zone_id for row in eligible],
            labels={row.zone_id: f"{name} centered at ({row.center.x}, {row.center.y})" for row in eligible},
            preferred=[zone.zone_id], prompt=f"Rolling Blackout: {ctx.actor.display_name} moves Darkness; choose the area to move up to 30 feet")
        if not selected:
            return
        zone = engine.state.zones[selected[0]]
    if engine.grid.distance_ft(zone.center, aim) > int(eff.get("max_ft") or 30):
        ctx.rider(f"{name} moves at most {int(eff.get('max_ft') or 30)} feet.")
        return
    ctx.actor.turn_flags[f"moved_zone:{name}"] = True  # Smoke Veil: once during each turn
    _recenter(engine, zone, aim)
    republish(engine, zone, ctx.source)


# ------------------------------------------------------------------------------------------------ Creeping Lethargy
def _moment(engine: Any, creature: Any) -> str | None:
    """Whether the save being resolved was made as the creature started its turn inside, or as it entered."""
    for event in reversed(engine.events[-40:]):
        if event.event_type == "PASSIVE_TRIGGERED" and creature.entity_id in (event.target_ids or ()):
            return str((event.payload or {}).get("moment") or "")
    return None


@effect("lethargy")
def lethargy(ctx: Any, eff: dict[str, Any]) -> None:
    engine, creature = ctx.engine, ctx.target
    if creature is None or not creature.active:
        return
    lethargic = any(condition.condition_id == LETHARGIC for condition in creature.conditions.values())
    if lethargic and _moment(engine, creature) == "start":
        from .. import typed_executor

        if typed_executor.condition_immune(engine, creature, "unconscious"):
            return
        engine._apply_condition(creature, ASLEEP, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"sleep": "creeping_lethargy", "until_round": engine.state.round_number + 10,
                                      "label": "Asleep (Creeping Lethargy): wakes on a save at the start of its turn, on taking damage, or starting a turn outside"})
        creature.reaction_available = False
        return
    if not lethargic:
        engine._apply_condition(creature, LETHARGIC, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Lethargic: an Action or a Bonus Action on its turn, not both (until it starts a turn outside the Darkness)"})


@effect("lethargy_wake")
def lethargy_wake(ctx: Any, eff: dict[str, Any]) -> None:
    creature = ctx.target
    if creature is not None:
        _wake(ctx.engine, creature, ctx.source)


def _wake(engine: Any, creature: Any, source: str) -> None:
    for iid, condition in list(creature.conditions.items()):
        if condition.condition_id == ASLEEP and (condition.data or {}).get("sleep") == "creeping_lethargy":
            _drop_instance(engine, creature, iid, source)


@hook("candidate_allowed")
def dark_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Clinging Darkness only where a creature stands; Rolling Blackout only within 30 feet of a Darkness it can move; a
    Lethargic creature's Action or Bonus Action, not both."""
    if action is None:
        return None
    effects = ((action.parameters or {}).get("typed") or {}).get("effects") or []
    if any(isinstance(row, dict) and row.get("type") == "cling_zone" for row in effects):
        aim = getattr(candidate, "destination", None)
        if aim is None or not any(row.active and engine._footprint_intersects(row, (aim,)) for row in engine.state.actors.values()):
            return False
    if getattr(action, "parameters", None) and action.parameters.get("rolling_blackout"):
        if not movable(engine, actor):
            return False
        aim = getattr(candidate, "destination", None)
        if aim is None or engine.grid.distance_ft(actor.position, aim) > 120 or \
                all(engine.grid.distance_ft(zone.center, aim) > 30 for zone in movable(engine, actor)):
            return False
    if not any(condition.condition_id == LETHARGIC for condition in actor.conditions.values()):
        return None
    economy = getattr(action.economy, "value", action.economy)
    if economy == "BONUS_ACTION" and not actor.action_available:
        return False  # it took an Action this turn
    if economy == "ACTION" and not actor.bonus_action_available:
        return False  # it took a Bonus Action this turn
    return None


# ------------------------------------------------------------------------------------------------ turn boundaries
@hook("turn_start")
def dark_turn_start(engine: Any, actor: Any) -> None:
    """Starting a turn outside the Darkness ends Creeping Lethargy's penalty and its sleep; so does a minute asleep."""
    held = [(iid, condition) for iid, condition in actor.conditions.items()
            if condition.condition_id == LETHARGIC or (condition.condition_id == ASLEEP and (condition.data or {}).get("sleep") == "creeping_lethargy")]
    if not held:
        return
    outside = not _inside_any(engine, actor, _zones_with(engine, "Creeping Lethargy"))
    for iid, condition in held:
        expired = condition.condition_id == ASLEEP and engine.state.round_number >= int((condition.data or {}).get("until_round") or 0)
        if outside or expired:
            _drop_instance(engine, actor, iid, "passive:TAL_DARK_CREEPING_LETHARGY")


@hook("turn_end")
def dark_turn_end(engine: Any, actor: Any) -> None:
    # Fearful Darkness: "Frightened until it ends its turn outside the Darkness".
    fearful = _zones_with(engine, "Fearful Darkness")
    sources = {zone.source_definition_id for zone in engine.state.zones.values() if "Fearful Darkness" in (zone.trigger_profile.get("talents") or [])}
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id == FRIGHTENED and condition.source_definition_id in sources and (condition.data or {}).get("fearful_darkness"):
            if not _inside_any(engine, actor, [zone for zone in fearful if zone.source_definition_id == condition.source_definition_id]):
                _drop_instance(engine, actor, iid, "passive:TAL_DARK_FEARFUL_DARKNESS")
    # Clinging Darkness: an unwilling creature repeats its Wisdom save at the end of each of its turns.
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id != CLINGS:
            continue
        zone = engine.state.zones.get(str((condition.data or {}).get("zone_id") or ""))
        owner = engine.state.actors.get(condition.source_actor_id)
        if zone is None or not zone.active or owner is None or zone.trigger_profile.get("anchor_id") != actor.entity_id:
            _drop_instance(engine, actor, iid, "passive:TAL_DARK_CLINGING_DARKNESS")
            continue
        ctx = _context(engine, owner, zone, actor)
        if ctx is not None:
            from .. import typed_executor

            typed_executor.run_effects(ctx, [{"type": "save", "ability": "wis", "applies_to": "target", "on_fail": [],
                                              "on_success": [{"type": "release_zone", "zone_id": zone.zone_id}]}])


# ------------------------------------------------------------------------------------------------ Fearful Darkness
@effect("fearful_darkness")
def fearful_darkness(ctx: Any, eff: dict[str, Any]) -> None:
    """On a failed save: Frightened (of the Darkness's creator) until it ends a turn outside."""
    creature = ctx.target
    if creature is None or not creature.active:
        return
    from .. import typed_executor, typed_reactions

    if typed_executor.condition_immune(ctx.engine, creature, "frightened") or any(
            condition.condition_id == FRIGHTENED and (condition.data or {}).get("fearful_darkness") for condition in creature.conditions.values()):
        return
    if typed_reactions.offer_condition_gained(ctx.engine, creature, ctx.actor, "frightened"):
        return
    ctx.engine._apply_condition(creature, FRIGHTENED, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"fearful_darkness": True, "label": "Frightened until it ends its turn outside the Darkness"})


@effect("fearful_calm")
def fearful_calm(ctx: Any, eff: dict[str, Any]) -> None:
    """A successful save at the start of a later turn inside ends it."""
    creature = ctx.target
    if creature is None or _moment(ctx.engine, creature) != "start":
        return
    for iid, condition in list(creature.conditions.items()):
        if condition.condition_id == FRIGHTENED and (condition.data or {}).get("fearful_darkness") and condition.source_definition_id == ctx.source:
            _drop_instance(ctx.engine, creature, iid, ctx.source)


@hook("event")
def dark_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    for target_id in kwargs.get("target_ids") or ():
        creature = engine.state.actors.get(target_id)
        if creature is not None:
            _wake(engine, creature, "passive:TAL_DARK_CREEPING_LETHARGY")  # "It also wakes if it takes damage"


# ------------------------------------------------------------------------------------------------ Dark Slaughter
@hook("compile_block")
def dark_slaughter_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "dark_slaughter":
        return None
    return [{**row, "block": "dark_slaughter", "dice_by_cl": copy.deepcopy(spec.get("dice_by_cl") or [])}]


@hook("after_hit")
def dark_slaughter(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    rows = [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if row.get("block") == "dark_slaughter"]
    if not rows or not target.active:
        return
    from .. import senses, zones

    if not senses.meld_active(engine, actor, "TAL_DARK_DARK_SLAUGHTER"):
        return  # a Meld: only while this fighter has Dark Slaughter's own Meld active. Several Melds may be active at
        # once (owner 2026-09-29 struck the one-Meld rule); this asks only about this one (combat/senses.py).

    mine = [zone for zone in zones.typed_zones(engine) if zone.owner_id == actor.entity_id and (zone.trigger_profile.get("visual") or {}).get("darkness")
            and zones._inside(engine, actor, zone)]
    if not mine:
        return
    roll = next((event for event in reversed(engine.events[-30:]) if event.event_type == "ATTACK_ROLLED" and event.actor_id == actor.entity_id
                 and target.entity_id in (event.target_ids or ())), None)
    if roll is None:
        return
    payload = roll.payload or {}
    advantage = str(payload.get("mode") or "").upper() == "ADVANTAGE"
    from .. import stealth

    unseen = not stealth.sees(engine, target, actor)
    if not advantage and not unseen:
        return
    cl = int(ctx.numbers.get("cl") or 1)
    band = next(((count, sides) for low, high, count, sides in rows[0]["dice_by_cl"] if low <= cl <= high), None)
    if band is None:
        return
    count, sides = band
    if int(payload.get("natural_result") or 0) == 20:
        count *= 2  # "This damage is multiplied on a critical hit"
    # The attack's own damage type (the text names none: "it deals additional damage").
    dealt = next((event for event in reversed(engine.events[-30:]) if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == actor.entity_id
                  and target.entity_id in (event.target_ids or ())), None)
    kind_ = str(((dealt.payload or {}) if dealt is not None else {}).get("damage_type") or "")
    from .. import typed_executor

    sub = typed_executor.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    typed_executor.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": count, "sides": sides},
                                      **({"damage_types": [kind_.lower()]} if kind_ and kind_ != "UNTYPED" else {}), "evidence": "Dark Slaughter"}])


# ------------------------------------------------------------------------------------------------ Shadow Slick
@effect("skill_check")
def skill_check(ctx: Any, eff: dict[str, Any]) -> None:
    """The creature's ability check with a skill against the area maker's Cultivation Save DC (Shadow Slick: "a Dexterity
    (Acrobatics) check"); ``on_fail`` runs on it when it fails."""
    from dataclasses import replace
    from ..check_context import metadata_document
    ctx = replace(ctx, check_metadata=metadata_document(eff.get("metadata")))
    creature = ctx.actor if eff.get('applies_to') == 'self' else ctx.target
    if creature is None or not creature.active:
        return
    from .tabik_scoundrel import modifier, skill

    ability = str(eff.get("ability") or "DEX").upper()[:3]
    from ..ability_checks import ability_modifier

    fallback = ability_modifier(creature, ability,
        fallback=modifier(creature.dexterity_score) if ability == "DEX" else None)
    bonus = skill(ctx.engine, creature, str(eff.get("skill") or ""), fallback)
    dc = int(eff["dc"]) if "dc" in eff else int(ctx.numbers.get("save_dc") or 10)
    from ..typed_executor import check_modes
    from . import run

    # Preserve independent sources until all contextual benefits/penalties are
    # known; adding a mode after cancellation would lose that provenance.
    skill_name = str(eff.get("skill") or "") or None
    modes = check_modes(creature, ability, skill_name, engine=ctx.engine, against_creature=ctx.actor,
                        metadata=ctx.check_metadata)
    modes.update(m for m in run("skill_check_mode", ctx, creature, ability, skill_name)
                 if m in ("ADVANTAGE", "DISADVANTAGE"))
    mode = next(iter(modes)) if len(modes) == 1 else "NORMAL"

    # General, explicit inventory provenance. A skill label alone never names
    # an actual tool. Missing/uncarried references remain unknown and inert.
    from ..item_uses import tool_use
    from contextlib import nullcontext
    reason = f"CHECK:{ctx.source}:{eff.get('skill')}"
    used_tool = tool_use(ctx.engine, creature, eff)
    scope = ctx.engine.d20_scope({'kind': 'check', 'actor_id': creature.entity_id,
            'target_id': creature.entity_id, 'source_id': ctx.source,
            'reason': reason, 'skill': skill_name, 'ability': ability, 'dc': dc,
            'used_tool': used_tool}) if used_tool else nullcontext()
    with scope:
        roll = ctx.engine.roller.d20(modifier=bonus, actor_id=creature.entity_id, reason=reason,
                                     mode=mode)
    ctx.engine._record_roll(roll)
    from . import floored  # Complete Mandala Auspice (combat/ext/d20_floor.py)

    roll = floored(ctx.engine, creature, roll, dc)
    failed = roll.total < dc or False in run('check_success_allowed', ctx, creature,
        {'kind': 'check', 'ability': ability, 'skill': skill_name, 'metadata': ctx.check_metadata}, roll)
    ctx.engine._append_event("CHECK_ROLLED", ctx.source, actor_id=creature.entity_id, target_ids=(creature.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": not failed, "skill": eff.get("skill"),
                                      **({"check_metadata": ctx.check_metadata} if ctx.check_metadata else {})})
    if failed:
        from .. import typed_executor

        typed_executor.run_effects(ctx, [dict(row) for row in eff.get("on_fail") or []])


# ------------------------------------------------------------------------------------------------ Contesting Light
@hook("event")
def contesting_light(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"If a Light-sphere effect is created inside your Darkness, the creator of the Light effect makes a Cultivation Check
    against your Cultivation Save DC. Successful Check: Your Darkness is countered. Failed Check: The Light effect functions
    only as an ordinary light source and cannot illuminate your Darkness." A Radiance area made with its center inside an
    active Darkness: success removes that Darkness; a failure leaves both (lighting is not modelled on the table)."""
    if event_type != "ZONE_CREATED":
        return
    made = (kwargs.get("payload") or {}).get("zone") or {}
    zone_id = made.get("zone_id")
    if not zone_id or sum(1 for event in engine.events if event.event_type == "ZONE_CREATED" and (event.payload or {}).get("zone", {}).get("zone_id") == zone_id) != 1:
        return  # only when it is first made, not when it moves
    action = engine.action_catalog.get(str(made.get("source_definition_id") or ""))
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    if typed.get("sphere") != "tianxia.sphere.radiance":
        return
    creator = engine.state.actors.get(str(made.get("owner_id") or ""))
    center = made.get("center") or {}
    from .. import zones

    for darkness in zones.typed_zones(engine):
        if not (darkness.trigger_profile.get("visual") or {}).get("darkness") or darkness.owner_id == made.get("owner_id") or creator is None:
            continue
        if not any(cell.x == center.get("x") and cell.y == center.get("y") for cell in darkness.affected_cells):
            continue
        dc = int((darkness.trigger_profile.get("numbers") or {}).get("save_dc") or 10)
        numbers = typed.get("numbers") or {}
        roll = engine.roll_check(
            modifier=int(numbers.get('pb') or 2) + int(numbers.get('key_mod') or 0),
            actor_id=creator.entity_id,
            reason='CHECK:contesting_light',
        )
        engine._record_roll(roll)
        success = roll.total >= dc
        engine._append_event("CHECK_ROLLED", "passive:TAL_DARK_CONTESTING_LIGHT", actor_id=creator.entity_id, target_ids=(darkness.owner_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "skill": "Cultivation Check (Contesting Light)"})
        if success:
            zones.remove(engine, darkness, "COUNTERED")
        return


# ------------------------------------------------------------------------------------------------ Obfuscation
@hook("technique_used")
def obfuscation_is_a_rider(ctx: Any) -> None:
    """Obfuscation (augment, 1 CP) reads "Creatures and objects inside your Darkness, or affected by one of your
    Meld talents, cannot be located through ordinary scrying or divination."

    The table runs no scrying and no divination -- there is no such action a creature takes during a fight, and
    the talent rows that mention divination (Stored Glimpse, Shadow Walker's "Gain no precise scouting benefit")
    are themselves out-of-combat records.  So the printed effect is real but nothing on the table can resolve it,
    the same way Seal Art's tracking check is a rider (combat/ext/seal.py, "a rider").  The printed 1 CP is still
    correct and is still charged; what was wrong was that the charge passed with no word about what it bought.
    This states the effect in plain words at the moment it is bought, so no owner is ever charged for a silent
    nothing.  Only a use that actually carries the augment speaks, and only for a character whose catalog holds it.
    """
    if OBFUSCATION not in (ctx.typed.get("augments") or []):
        return
    ctx.rider("Obfuscation: creatures and objects inside this Darkness cannot be located through ordinary scrying or "
              "divination. The fight table has no scrying to resolve, so this one is settled between you and the GM "
              "between fights -- it does nothing on its own during this fight.")


# --------------------------------------------------------------------------------- how a Darkness is drawn
def _shaping_rows(profile: dict[str, Any]) -> set[str]:
    """The typed mechanic ids that shaped this area, read from the area's own stored provenance.

    Never matches display names: "Snagging Darkness" is what the sheet says, ``TAL_DARK_SNAGGING_DARKNESS``
    is what the rule is. An area saved before ``augment_ids`` existed simply offers fewer ids, and is drawn
    with the ordinary look rather than guessed at.
    """
    rows = {str(row.get("id")) for key in ("triggers", "inside") for row in profile.get(key) or [] if row.get("id")}
    rows |= {str(key) for key in profile.get("augment_ids") or []}
    rows.add(str((profile.get("source_profile") or {}).get("mechanic_id") or "") or "")
    rows.discard("")
    return rows


@hook("zone_visual")
def darkness_look(engine: Any, zone: Any) -> dict[str, Any] | None:
    """Which of the Dark sphere's three looks an area of magical darkness is painted with (owner 2026-10-03 03:38).

    Ordinary Darkness is a veil you can see the floor and the creatures through; Pure Darkness is almost pitch
    black; an area that snags or clings to what stands in it gets faint dark tentacles waving over it. Snagging
    and Clinging can ride on Pure Darkness (Pitch Black applies Pure Darkness in addition to one other talent),
    so the tentacles are reported separately and the client lays them over whichever shade it draws.

    ``zone`` is the serialised row the table is about to receive. Drawing only: no sight, fog or obscuration
    rule reads this, and the default for any other area is None.
    """
    profile = zone.get("trigger_profile") if isinstance(zone, dict) else None
    if not isinstance(profile, dict) or not (profile.get("visual") or {}).get("darkness"):
        return None  # smoke, fog and a wall of cloud are not a Darkness
    source = profile.get("source_profile") or {}
    rows = _shaping_rows(profile)
    if source.get("sphere_id") != DARK_SPHERE and not rows & DARKNESS_ROWS:
        return None  # another sphere's darkness keeps the single look it has always had
    grabbing = bool(rows & GRASPING_ROWS)
    return {"darkness_look": "pitch" if PURE_DARKNESS in rows else "tentacles" if grabbing else "veil",
            "darkness_tentacles": grabbing}
