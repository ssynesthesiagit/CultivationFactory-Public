"""Phoenix Rebirth Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Phoenix Rebirth Body (Rebirth Embers and the five features, with their Normalized
Procedures). Rebirth Embers (resource:named.rebirth_ember, maximum PB) use this module's native event producers and
subpath_pools.gain for their shared cap/round clock; Ash-Shedding
Reversal is a d20 rewrite rule (combat/ext/d20_rewrite_rules.py). Owned rows: ``{"type": "path_passive", "kind": "phoenix",
"role": "cinder" | "flame_wing"}``; Rebirth from Cinders' Reaction runs ``rebirth_from_cinders``.

Cinder Blood       at the start of your turn (not at 0 HP), 1 Ember (asked) for 1d8 + CON Hit Points (2d8 at CL11, 3d8 at CL17).
Flame-Wing Rush    after that healing restores Hit Points: a move of up to half your Speed without provoking (asked), and the first
                   unarmed hit this turn deals + 2d8 Fire or Radiant.
Rebirth from Cinders  its Reaction (6 Stamina, at least 3 Embers, once per scene) replaces the lethal packet with half maximum HP,
                   before its secondary effects: every Ember is
                   consumed, you stand, Blinded, Deafened, Frightened, Paralyzed, Poisoned, Restrained and Stunned end, each
                   hostile creature within 20 feet makes a Dexterity save (8d8 Fire or Radiant and pushed 10 feet, or half), you may
                   move up to your Speed without provoking. Instant death cannot be replaced. The native checkpoint shares
                   reaction-plan consent, costs and scene limits; source flags and condition rules bar forbidden recovery.
Every hook returns early for a creature without these rows.
"""

from __future__ import annotations

from typing import Any
from contextvars import ContextVar

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.phoenix_rebirth_body.feature."
EMBER = "resource:named.rebirth_ember"
WING = "condition:typed.flame_wing_charge"
REBIRTH = PREFIX + "rebirth_from_cinders"
REBIRTH_CHECKPOINT = "PHOENIX_REBIRTH"
FURNACE = PREFIX + "furnace_without_fuel"
EMBER_CONDITIONS = {"blinded", "deafened", "frightened", "poisoned", "restrained", "stunned"}
_WING_MOVE = ContextVar("phoenix_wing_movement", default=None)
LEVELS = {"cinder_blood": 3, "ash_shedding_reversal": 6, "flame_wing_rush": 10,
          "furnace_without_fuel": 14, "rebirth_from_cinders": 18}


@hook("compile_bundle")
def seal_body_profile(bundle: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    if not any(str(r.get("feature_id", "")).startswith(PREFIX) for r in [*bundle.get("typed_passives", ()), *bundle.get("typed_reactions", ())]):
        return bundle
    from copy import deepcopy
    bundle = deepcopy(bundle)
    paths = (info["owner_sheet"].get("path_and_subpath") or {}).get("paths") or []
    body = next((p for p in paths if p.get("path_id") == "tianxia.path.body_refining"), None)
    cl = int(body["effective_cl"]) if body else int(info["numbers"].get("cl", 1))
    bundle["phoenix_body_cl"] = cl
    con = int(info["numbers"].get("con_mod", 0))
    bundle["phoenix_body_profile"] = {"cl": cl, "con_mod": con,
                                      "save_dc": 8 + int(info["numbers"].get("pb", 2)) + con}
    for key in ("typed_passives", "typed_reactions"):
        bundle[key] = [r for r in bundle.get(key, ()) if not str(r.get("feature_id", "")).startswith(PREFIX)
                       or cl >= LEVELS.get(str(r["feature_id"]).removeprefix(PREFIX), 99)]
    return bundle


def _fire_terrain(engine: Any, zone: Any) -> bool:
    from ..zones import terrain_rules
    rules = terrain_rules().get("terrains", {})
    return any(rules.get(name, {}).get("material") == "fire" for name in zone.trigger_profile.get("terrain", ()))


@hook("difficult_zone_exempt")
def wing_terrain(engine: Any, actor: Any, zone: Any) -> bool | None:
    if _WING_MOVE.get() == (id(engine), actor.entity_id) and _fire_terrain(engine, zone):
        return True
    return None


@hook("effect_subject_allowed")
def wing_flame(ctx: Any, row: dict[str, Any], actor: Any) -> bool | None:
    if _WING_MOVE.get() != (id(ctx.engine), actor.entity_id):
        return None
    from .damage_delivery import area
    from ..zones import typed_zones
    zone = next((z for z in typed_zones(ctx.engine) if z.zone_id == area(ctx.engine)), None)
    if zone is None or not _fire_terrain(ctx.engine, zone):
        return None
    if row.get("type") in {"damage", "extra_damage", "half_damage"} and {str(k).lower() for k in row.get("damage_types", ())} == {"fire"}:
        return False
    if row.get("type") == "condition" and row.get("condition") == "burning":
        return False
    return None


def _owns(engine: Any, actor: Any, source: str) -> bool:
    return any(row.get("feature_id") == source for row in engine.typed_passive_rows.get(actor.entity_id, ())) or any(
        action.owner_id == actor.entity_id and (action.parameters.get("typed") or {}).get("source") == source
        for action in engine.action_catalog.values())


def _family_owner(engine: Any, actor: Any) -> bool:
    return any(str(row.get("feature_id", "")).startswith(PREFIX) for row in (
        *engine.typed_passive_rows.get(actor.entity_id, ()),
        *engine.typed_reaction_rows.get(actor.entity_id, ())))


def _hostile_source(engine: Any, actor: Any, source_actor_id: str | None) -> bool:
    source = engine.state.actors.get(source_actor_id)
    if source is None or source.entity_id == actor.entity_id:
        return False
    # The common record excludes controlled creatures; a team change does not
    # remove the native summoning/control provenance.
    if source.summon or (source.owner_id and source.owner_id != source.entity_id):
        return False
    if source.team_id != actor.team_id:
        return True
    from .needle import ask, checkpoint_id
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "phoenix_hostile_source", actor.entity_id), actor,
                 "choice:needle.phoenix_hostile_source", ["hostile", "excluded"], default="decline", automatic_options=[],
                 name="Rebirth Embers", target_id=actor.entity_id,
                 labels={"hostile": "This was hostile force, not a willing ally, controlled creature, cost or farming source",
                         "excluded": "Exclude: willing ally, controlled creature, cost, self-damage or farming"},
                 prompt=f"Rebirth Embers: {source.display_name} affected {actor.display_name}. Being on the same team does not establish willingness. Confirm whether this was qualifying hostile force; self-damage, willing allies, controlled creatures, feature costs and farming never grant an Ember.")
    return picked == ["hostile"]


def _gain_ember(engine: Any, actor: Any, source: str, sequence: int) -> None:
    from .subpath_pools import gain
    if gain(engine, actor, EMBER, source):
        actor.turn_flags["_round_phoenix_qualifying_event"] = int(sequence)
        actor.turn_flags["_round_phoenix_qualifying_source"] = source


@hook("event", nested=True)
def expire_scene_embers(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MATCH_ENDED":
        return
    # A bound journey can continue the same scene across encounters. Its
    # resources already round-trip through journey_resume/start_combat.
    if any(b.get("journey_setup") is not None for b in engine.typed_bundle_documents):
        return
    for actor in engine.state.actors.values():
        if not _family_owner(engine, actor):
            continue
        amount = int(actor.resources.get(EMBER, 0))
        if amount:
            engine._spend_resource(actor, EMBER, amount, "system:phoenix_scene_end")
        for flag in ("_round_pool_gain:" + EMBER, "_round_phoenix_qualifying_event", "_round_phoenix_qualifying_source"):
            actor.turn_flags.pop(flag, None)


def _journey_owner(session: Any, aid: str) -> bool:
    bundle = session.state["actors"][aid]["bundle"]
    return any(str(r.get("feature_id", "")).startswith(PREFIX) for r in (
        *bundle.get("typed_passives", ()), *bundle.get("typed_reactions", ())))


@hook("journey_options")
def scene_boundary_option(session: Any, aid: str) -> Any:
    if session.state["phase"] != "travel" or not _journey_owner(session, aid):
        return None
    return [{"id": "phoenix_scene_boundary", "kind": "phoenix_scene_boundary", "source": PREFIX.removesuffix(".feature."),
             "auto_select": 0, "payload": {"confirm_scene_ended": 1},
             "label": "GM: end the current Phoenix Rebirth scene for this journey's creatures. Clear all Rebirth Embers and refresh Rebirth from Cinders for the next scene; this restores no Hit Points or Stamina."}]


@hook("journey_command")
def declare_scene_boundary(session: Any, aid: str, kind: str, payload: dict[str, Any]) -> bool | None:
    if kind != "phoenix_scene_boundary":
        return None
    from ..journey import require
    require(_journey_owner(session, aid) and session.state["phase"] == "travel", "Choose a Phoenix Rebirth practitioner outside combat.")
    require(set(payload) == {"confirm_scene_ended"} and type(payload["confirm_scene_ended"]) is int
            and payload["confirm_scene_ended"] == 1, "Explicitly confirm that this continuous scene has ended.")
    for other_id, actor in session.state["actors"].items():
        if not _journey_owner(session, other_id):
            continue
        actor["resources"][EMBER] = 0
        # Native once-per-scene uses are compiled resource costs. Reset only
        # this family's scene use, never its Stamina or rest-based resources.
        use_ids = {cost["resource_id"] for row in actor["bundle"].get("typed_reactions", ())
                   if row.get("feature_id") == REBIRTH for cost in row.get("costs", ())
                   if str(cost.get("resource_id", "")).startswith("resource:uses.")}
        for resource in actor["bundle"]["actor_template"]["resources"]:
            if resource["resource_id"] in use_ids:
                actor["resources"][resource["resource_id"]] = int(resource["maximum"])
        session.emit("PHOENIX_SCENE_ENDED", other_id, authority=aid,
                     text=f"The GM ended the continuous scene for {actor['name']}: Rebirth Embers are cleared and Rebirth from Cinders is available in the next scene. No healing or Stamina recovery.")
    return True


@hook("save_roll_tags")
def ash_save_categories(ctx: Any, subject: Any, ability: str, named: Any) -> Any:
    if subject is not None and _owns(ctx.engine, subject, PREFIX + "ash_shedding_reversal"):
        return frozenset(n for n in named if n.startswith("category:"))
    return None


@hook("before_damage_defenses")
def furnace_packet(engine: Any, actor: Any, amount: int, kind: str, source: str, source_actor_id: str) -> None:
    if str(kind).upper() != "FIRE" or not _owns(engine, actor, FURNACE):
        return
    from ..pending_damage import packet_scratch
    from ..typed_reactions import preview_damage_without
    scratch = packet_scratch(engine)
    if scratch is not None:
        scratch["phoenix_before_immunity"] = preview_damage_without(
            engine, actor, amount, kind, source, source_actor_id,
            excluded_feature_ids=(FURNACE, PREFIX + "cinder_blood"))


@hook("event", nested=True)
def ember_damage(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    from ..pending_damage import current, packet_scratch
    packet, scratch = current(engine), packet_scratch(engine)
    flags = packet.source_flags if packet else frozenset()
    if flags & {"voluntary", "training", "self_inflicted", "resource_farming", "feature_cost"}:
        return
    payload = kwargs.get("payload") or {}
    for aid in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(aid)
        if actor is None or EMBER not in actor.resources or not _family_owner(engine, actor):
            continue
        if actor.turn_flags.get("_round_pool_gain:" + EMBER) == int(engine.state.round_number):
            continue
        source = str(kwargs.get("source_definition_id") or "")
        pb = int(actor.proficiency_bonus)
        fire = str(payload.get("damage_type")).upper() == "FIRE" and _owns(engine, actor, FURNACE)
        before_immunity = int((scratch or {}).get("phoenix_before_immunity", 0))
        if int(payload.get("hp_damage") or 0) < pb and not (fire and before_immunity >= pb):
            continue
        hostile = _hostile_source(engine, actor, kwargs.get("actor_id"))
        qualifies = hostile and int(payload.get("hp_damage") or 0) >= pb
        if fire and before_immunity >= pb:
            if hostile:
                qualifies = True
            else:
                from .damage_delivery import area, hazard, AREA
                from ..zones import typed_zones
                zone = next((z for z in typed_zones(engine) if z.zone_id == area(engine)), None)
                if hazard(engine) == AREA and zone is not None and zone.active:
                    from .needle import ask, checkpoint_id
                    picked = ask(engine, _intent(engine), checkpoint_id(engine, "phoenix_hazard", aid), actor,
                                 "choice:needle.phoenix_hazard", ["genuine", "farming"], default="decline", automatic_options=[],
                                 labels={"genuine": "A genuine active Fire hazard, not maintained to farm Embers", "farming": "Exclude this source: harmless or maintained to farm Embers"},
                                 name="Furnace Without Fuel", feature_id=FURNACE, target_id=aid,
                                 prompt=f"Furnace Without Fuel: this active Fire hazard would deal at least {pb} damage to {actor.display_name} before immunity. Is it a genuine hazard, rather than a source maintained solely to farm Embers?")
                    qualifies = picked == ["genuine"]
        if qualifies:
            _gain_ember(engine, actor, source, engine.state.event_sequence)


@hook("save_final")
def remember_save_start(ctx: Any, actor: Any, ability: str, named: Any, failed: bool) -> None:
    if not failed or actor is None or EMBER not in actor.resources or ctx.save_result is None or not _family_owner(ctx.engine, actor):
        return
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_phoenix_save_events")
    ctx.engine.__dict__.setdefault("_phoenix_save_events", {})[ctx.save_result.roll_id] = int(ctx.engine.state.event_sequence)


@hook("save_effects_settled")
def ember_condition(ctx: Any, actor: Any, ability: str, failed: bool) -> None:
    if actor is None or EMBER not in actor.resources or ctx.save_result is None:
        return
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_phoenix_save_events")
    records = ctx.engine.__dict__.get("_phoenix_save_events", {})
    start = records.pop(ctx.save_result.roll_id, None)
    if not records:
        ctx.engine.__dict__.pop("_phoenix_save_events", None)
    if start is None or not failed:
        return
    if actor.turn_flags.get("_round_pool_gain:" + EMBER) == int(ctx.engine.state.round_number):
        return
    if any(c.condition_id.rsplit(".", 1)[-1] in EMBER_CONDITIONS and c.applied_sequence > start
           and c.source_actor_id == ctx.actor.entity_id and c.source_definition_id == ctx.source for c in actor.conditions.values()) \
            and _hostile_source(ctx.engine, actor, ctx.actor.entity_id):
        _gain_ember(ctx.engine, actor, ctx.source, ctx.engine.state.event_sequence)


@hook("row_allowed")
def native_rebirth_only(engine: Any, reactor: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") == REBIRTH and row.get("native_checkpoint") != REBIRTH_CHECKPOINT:
        return False
    return None


@hook("lethal_damage")
def replace_lethal_damage(engine: Any, actor: Any, amount: int, damage_type: str, source_id: str, attacker_id: str, intent: Any) -> Any:
    """Use the defended packet, after all reductions and earlier replacements."""
    from ..damage_allocation import lethal_threshold
    from .life_state import massive
    from ..pending_damage import current
    from ..typed_executor import condition_rules
    from ..typed_reactions import checkpoint_response, commit_checkpoint_response
    from .needle import ask, checkpoint_id
    from .states import context

    hp_loss = lethal_threshold(engine, actor, amount, attacker_id, source_id=source_id, damage_type=damage_type)
    if hp_loss < actor.current_hp or hp_loss - actor.current_hp >= massive(engine, actor):
        return None
    packet = current(engine)
    if packet and packet.source_flags & {"instant_death", "total_bodily_destruction", "erasure", "prevents_recovery", "zero_hp_replaced"}:
        return None
    if any(r.get("death_prevention_denied") or r.get("healing_denied") for r in condition_rules(actor)):
        return None
    attacker = engine.state.actors.get(attacker_id)
    row = checkpoint_response(engine, actor, actor, attacker, REBIRTH, REBIRTH_CHECKPOINT)
    if row is None:
        return None
    action = engine.action_catalog.get(source_id)
    trigger = action.display_name if action else "the damaging effect"
    chosen = ask(engine, intent, checkpoint_id(engine, REBIRTH_CHECKPOINT, actor.entity_id), actor,
                 "choice:needle.rebirth", ["rebirth"], allow_decline=True,
                 name="Rebirth from Cinders", feature_id=REBIRTH, target_id=actor.entity_id,
                 prompt=f"Rebirth from Cinders: {trigger} would reduce {actor.display_name} to 0 Hit Points. Spend your Reaction, 6 Stamina and all Rebirth Embers (at least 3), once this scene, to return to half maximum Hit Points, stand, shed conditions, burst and move?",
                 labels={"rebirth": "Spend 6 Stamina, all Embers and your Reaction: Rebirth from Cinders"})
    if not chosen:
        return None
    from ..paid_relocation import activation
    with activation(engine, actor, REBIRTH, independent=True):
        commit_checkpoint_response(engine, actor, actor, row, REBIRTH_CHECKPOINT)
        ctx = context(engine, actor, REBIRTH, [actor], row["numbers"])
        ctx.intent = intent
        rebirth_from_cinders(ctx, {})
    return {"replaced": True}


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "phoenix"}


def _cl(engine: Any, actor: Any) -> int:
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor.entity_id), None)
    return int((bundle or {}).get("phoenix_body_cl", (bundle or {}).get("cl", 1)))


def _profile(engine: Any, actor: Any) -> dict[str, Any]:
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor.entity_id), {})
    return dict(bundle.get("phoenix_body_profile", {}))


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _move(engine: Any, intent: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    if name != "Flame-Wing Rush":
        return _move_inner(engine, intent, mover, feet, choice_id, name)
    token = _WING_MOVE.set((id(engine), mover.entity_id))
    try:
        _move_inner(engine, intent, mover, feet, choice_id, name)
    finally:
        _WING_MOVE.reset(token)


def _move_inner(engine: Any, intent: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from ..granted_movement import routes, resolve_path
    from .needle import cell_id

    paths = {cell_id(cell): path for cell, (path, cost, mode) in routes(engine, mover, feet, mode="walk").items()} if feet > 0 else {}
    if not paths:
        return
    picked = ask(engine, intent, checkpoint_id(engine, "phoenix_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        source = PREFIX + {"Flame-Wing Rush": "flame_wing_rush", "Rebirth from Cinders": "rebirth_from_cinders"}[name]
        resolve_path(engine, mover, paths[picked[0]], source, feet=feet, intent=intent, provokes=False, mode="walk")


@hook("turn_start_choice")
def cinder_blood(engine: Any, actor: Any) -> None:
    roles = _roles(engine, actor)
    if "cinder" not in roles or not actor.active or actor.current_hp <= 0 or int(actor.resources.get(EMBER, 0) or 0) < 1 or actor.turn_flags.get("phoenix_cinder_used"):
        return
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .states import context

    cl = _cl(engine, actor)
    dice = 3 if cl >= 17 else 2 if cl >= 11 else 1
    intent = _intent(engine)
    picked = ask(engine, intent, checkpoint_id(engine, "cinder_blood", actor.entity_id), actor, "choice:needle.cinder_blood", ["heal"],
                 labels={"heal": f"Spend 1 Rebirth Ember: regain {dice}d8 + Constitution modifier Hit Points"}, allow_decline=True,
                 automatic_options=["heal"] if actor.current_hp < actor.maximum_hp else [],
                 target_id=actor.entity_id, name="Cinder Blood", feature_id=PREFIX + "cinder_blood",
                 prompt=f"Cinder Blood: at the start of {actor.display_name}'s turn, spend 1 Rebirth Ember to regain {dice}d8 + Constitution modifier Hit Points? This costs no action or Stamina and can happen only once this turn.")
    if not picked:
        return
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, actor, PREFIX + "cinder_blood", independent=True):
        actor.turn_flags["phoenix_cinder_used"] = 1
        engine._spend_resource(actor, EMBER, 1, PREFIX + "cinder_blood")
        before = actor.current_hp
        ctx = context(engine, actor, PREFIX + "cinder_blood", [actor], {"pb": int(actor.proficiency_bonus or 2), "cl": cl})
        from ..gate2_runtime_models import ActionDefinition, EconomyKind
        ctx.action = ActionDefinition(source_definition_id=PREFIX + "cinder_blood", display_name="Cinder Blood", owner_id=actor.entity_id,
                                      economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF")
        ctx.typed["source"] = PREFIX + "cinder_blood"
        ctx.intent = intent
        con = _profile(engine, actor).get("con_mod")
        if con is None:
            con = next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") or 0)
                    for a in engine.action_catalog.values() if a.owner_id == actor.entity_id and (((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") is not None), 0)
        te.run_effects(ctx, [{"type": "healing", "applies_to": "self", "dice": {"count": dice, "sides": 8}, "flat": con,
                              "evidence": "Cinder Blood"}])
        if "flame_wing" in roles and actor.current_hp > before:
            _move(engine, intent, actor, int(engine._effective_speed(actor)) // 2, "choice:needle.flame_wing_move", "Flame-Wing Rush")
            engine._apply_condition(actor, WING, PREFIX + "flame_wing_rush", actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                    data={"source_cl": cl, "label": "Flame-Wing Rush: the first unarmed hit this turn deals + 2d8 Fire or Radiant"})


@hook("after_hit")
def flame_wing_hit(ctx: Any, target: Any, kind: str) -> None:
    held = next((c for c in ctx.actor.conditions.values() if c.condition_id == WING), None)
    if held is None or kind != "unarmed" or target is None or "flame_wing" not in _roles(ctx.engine, ctx.actor):
        return
    ctx.actor.conditions.pop(held.instance_id)
    ctx.engine._append_event("CONDITION_REMOVED", PREFIX + "flame_wing_rush", actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                             payload={"condition_id": WING, "instance_id": held.instance_id, "reason": "CONSUMED"})
    from .. import typed_executor as te
    from .life_state import additional_hit_component, HIT_COMPONENT_FLAG
    packets = []
    for event in reversed(ctx.engine.events):
        if event.event_type == "ATTACK_ROLLED" and event.actor_id == ctx.actor.entity_id:
            break
        if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == ctx.actor.entity_id and target.entity_id in event.target_ids:
            packets.append(event.payload)
    before = int(packets[-1].get("hp_before", target.current_hp)) if packets else target.current_hp
    applied = sum(int(p.get("hp_damage", 0)) for p in packets)
    with additional_hit_component(ctx.engine, target, before, applied):
        te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={},
                                         critical_hit=False, continue_after_defeat=True,
                                         damage_source_flags=(HIT_COMPONENT_FLAG,)),
                      [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["fire", "radiant"],
                        "evidence": "Flame-Wing Rush: + 2d8"}])


@effect("rebirth_from_cinders")
def rebirth_from_cinders(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    left = int(actor.resources.get(EMBER, 0) or 0)
    if left:
        engine._spend_resource(actor, EMBER, left, PREFIX + "rebirth_from_cinders")  # "Consume all Embers" (3 were the cost)
    before = actor.current_hp
    actor.current_hp = max(1, int(actor.maximum_hp) // 2)
    engine._append_event("HIT_POINTS_REPLACED", REBIRTH, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"before": before, "after": actor.current_hp, "reason": "ZERO_HP_REPLACEMENT"})
    from ..posture import stand_up
    stand_up(engine, actor, source_id=REBIRTH, cost=0, ignore_speed=True)
    for iid, held in list(actor.conditions.items()):
        if held.condition_id.rsplit(".", 1)[-1] in ("blinded", "deafened", "frightened", "paralyzed", "poisoned", "restrained", "stunned"):
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", PREFIX + "rebirth_from_cinders", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "REBIRTH"})
    from ..targeting import line_of_effect
    from ..senses import perceives
    foes = [c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.team_id != actor.team_id
            and engine._distance_actor_to_actor(actor, c) <= 20 and line_of_effect(engine, actor, target=c)]
    if foes:
        from .needle import ask, checkpoint_id
        selected = ask(engine, ctx.intent, checkpoint_id(engine, "rebirth_targets", actor.entity_id), actor,
                       "choice:needle.rebirth_targets", [c.entity_id for c in foes], minimum=0, maximum=len(foes), default="all",
                       preferred=[c.entity_id for c in foes if perceives(engine, actor, c)],
                       labels={c.entity_id: f"Include {c.display_name} in the 20-foot Rebirth burst" for c in foes},
                       name="Rebirth from Cinders", feature_id=REBIRTH, target_id=actor.entity_id,
                       prompt=f"Rebirth from Cinders: choose which hostile creatures within 20 feet of {actor.display_name} take the burst. Failure: 8d8 damage and a 10-foot push; success: half damage, no push.")
        foes = [c for c in foes if c.entity_id in selected]
        damage = ask(engine, ctx.intent, checkpoint_id(engine, "rebirth_damage", actor.entity_id), actor,
                     "choice:needle.rebirth_damage", ["fire", "radiant"], name="Rebirth from Cinders", feature_id=REBIRTH,
                     prompt=f"Rebirth from Cinders: choose Fire or Radiant damage for {actor.display_name}'s entire burst.")
        kind = damage[0] if damage else "fire"
        from ..gate2_runtime_models import ActionDefinition, EconomyKind

        action = ActionDefinition(source_definition_id=PREFIX + "rebirth_from_cinders", display_name="Rebirth from Cinders", owner_id=actor.entity_id,
                                  economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
        numbers = {**ctx.numbers, **_profile(engine, actor)}
        burst = te.Context(engine, actor, action, ctx.intent, {"effects": [], "numbers": numbers, "duration": {"kind": "instant"}, "riders": [],
                                                               "_area_centre": (actor.position.x, actor.position.y)}, foes, None, {})
        te.run_effects(burst, [{"type": "save", "ability": "dex", "evidence": "Rebirth from Cinders: Dexterity saving throw",
                                "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 8, "sides": 8}, "damage_types": [kind]},
                                            {"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away_center"}],
                                "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": [kind]}]}])
    _move(engine, ctx.intent, actor, int(engine._effective_speed(actor)), "choice:needle.rebirth_move", "Rebirth from Cinders")
    note(engine, PREFIX + "rebirth_from_cinders", actor, f"Rebirth from Cinders: {actor.display_name} rises from the ashes.")
