"""Heaven-Devouring Black Cauldron, slice 1: the CL18 Cauldron field.

Ownership comes from compiled progression rows (combat/subpath_acquisition.py
and the sheet's recorded acquisition), never from a Sphere or a name. This
slice carries the capstone field only, as one implementation per printed
behaviour:

* The creator's own compiled action places the field. Its zone is the engine's
  own (compiled zone_spec, combat/zones.py create) -- the plug-in adds the
  profile tag, the hostile difficult terrain, the entry/start trigger and the
  damage principle chosen at creation. It never creates a second zone.
* The Cauldron Anchor is one ordinary object placed by
  combat/asset_anchor_runtime.py at the field's centre, with its printed
  stat block, and retired when the field ends.
* A hostile creature that enters the field or starts its turn there makes a
  Constitution save against the creator's technique save DC: 5d8 of the
  chosen type (half on a success), loses 1 Cultivation Point and cannot regain
  any until the start of its next turn; a creature with none left takes an
  extra 2d8. Once per turn per creature, per the engine's own trigger ledger.
* Once per scene: the scene ledger is a scene-bound condition, so a reloaded or
  replayed fight keeps it and a new scene starts with it free.
* The anchor moves up to 20 feet once during the creator's turn, without an
  action, as a setting action of its own.

The field's later consumption clauses (Feed on Expenditure, Cauldron
Protection, Swallow the Art, Devour the Lesser, essence storage and the
anchor's ruin backlash) belong to later slices and are not implemented here.
"""
from copy import deepcopy
from pathlib import Path

from . import effect, hook
from .needle import ask, checkpoint_id, condition
from .passive_rows import row_of
from ..path_numbers import numbers_for_compile

PARENT = "tianxia.subpath.qi.heaven_devouring_black_cauldron"
PREFIX = PARENT + ".feature."
FIELD = PREFIX + "heaven_devouring_cauldron"
TIERS = {FIELD: 18}
QI = "resource:core.qi"
USED = "condition:typed.black_cauldron_field_used"
GROUP = PARENT
BLOCK = "black_cauldron"
FIELD_TYPE = "choice:needle.black_cauldron_field_type"
TYPES = ("NECROTIC", "FORCE")


def owned(engine, actor, feature=FIELD):
    """The compiled progression row for one Cauldron feature, if the actor owns it at its printed tier."""
    from ..cultivation_access import effective_cl
    row = row_of(engine, actor.entity_id, BLOCK, feature.removeprefix(PREFIX))
    if row is None or effective_cl(engine, actor, int(row["numbers"]["cl"])) < TIERS[feature]:
        return None
    return row


def numbers(engine, actor):
    """The owning Path's numbers, suppressed to the actor's effective CL when that is lower."""
    row = owned(engine, actor)
    if row is None:
        return {}
    from ..cultivation_access import effective_cl
    values = dict(row["numbers"])
    level = effective_cl(engine, actor, int(values["cl"]))
    if level < int(values["cl"]):
        values["cl"] = level
        values["pb"] = min(int(values["pb"]), 2 + max(0, level - 1) // 4)
        values["save_dc"] = 8 + int(values["pb"]) + int(values["key_mod"])
    return values


def fields(engine, owner):
    """The field zones this creature created that are still standing."""
    return [zone for zone in engine.state.zones.values() if zone.active and zone.owner_id == owner.entity_id
            and (zone.trigger_profile.get("profile") or {}).get("black_cauldron") == 1]


def in_field(engine, owner, target):
    from ..zones import actor_inside_zone
    return any(actor_inside_zone(engine, target, zone) for zone in fields(engine, owner))


def used(actor):
    """Whether this scene's one field has already been placed."""
    return condition(actor, USED) is not None


def turn_id(engine):
    current = engine.state.actors.get(engine.state.current_actor_id)
    return f"{engine.state.round_number}:{engine.state.current_actor_id}:{current.turns_started if current else 0}"


def ask_field_type(engine, actor):
    """The creator's choice of the field's damage principle (printable wording, stable choice id)."""
    picked = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "black_cauldron_field_type", actor.entity_id), actor, FIELD_TYPE, list(TYPES),
                 labels={"NECROTIC": "Necrotic", "FORCE": "Force"},
                 prompt="Heaven-Devouring Cauldron: choose the field's damage principle.",
                 name="Heaven-Devouring Cauldron", feature_id=FIELD)
    return picked[0] if picked else TYPES[0]


# ---------------------------------------------------------------------------------------------- compile
@hook("compile_acquisition_ids")
def acquisition_ids(owner_sheet):
    """A recorded Subpath selection grants its printed progression at compile time only."""
    from ..subpath_acquisition import acquired_features
    grants = acquired_features(owner_sheet, Path(__file__).resolve().parents[2])
    return [feature for feature in grants if feature in TIERS] or None


@hook("compile_passives")
def acquire(rows, info):
    """One passive row per attained Cauldron tier, carrying the owning Path's numbers."""
    if not any(feature in info["owned_ids"] for feature in TIERS):
        return rows
    values = numbers_for_compile(info)
    additions = [{"block": BLOCK, "feature_id": feature, "kind": feature.removeprefix(PREFIX),
                  "numbers": dict(values), "choice_owner": True}
                 for feature, tier in TIERS.items() if feature in info["owned_ids"] and int(values["cl"]) >= tier]
    return [*rows, *additions]


def field_zone_spec():
    """The field as the engine's own zone: profile tag, hostile difficult ground, one entry/start pulse."""
    return {"name": "Heaven-Devouring Cauldron", "shape": "cylinder", "size_ft": 30, "height_ft": 40,
            "placed": 1, "difficult": "hostile",
            "duration": {"kind": "minutes", "amount": 1, "concentration": True},
            "profile": {"black_cauldron": 1},
            "triggers": [{"id": "cauldron_entry_start", "name": "Heaven-Devouring Cauldron",
                          "on": ["enter", "start"], "who": "hostile",
                          "effects": [{"type": "black_cauldron_pulse"}]}]}


@hook("compile_action")
def native_action(action, info):
    """The compiled capstone action becomes the field's own row: a 2x2 anchor and one tagged zone."""
    if action.parameters.get("black_cauldron_move"):
        return None
    typed = action.parameters.get("typed") or {}
    source = typed.get("option_of") or typed.get("source")
    if source != FIELD:
        return None
    params = deepcopy(action.parameters)
    values = numbers_for_compile(info)
    params["typed"] = {**params["typed"], "numbers": values, "manual_inline_choice": True,
                       "effects": [], "riders": [], "zone_spec": field_zone_spec()}
    # The anchor is a Large projected Cultivation Asset: enumerate only squares whose
    # 2x2 volume is free, in range and in sight (combat/cell_placement.py), so a legal
    # candidate always places the anchor it promises.
    params["cell_placement"] = {"width_cells": 2, "height_cells": 2}
    # The persisted source scene ledger owns the once-per-scene limit (USED below); a
    # match-long use pool would still be empty in the next scene.
    counter = "resource:uses." + action.source_definition_id
    costs = tuple((pool, amount) for pool, amount in action.costs if pool != counter)
    return action.model_copy(update={"parameters": params, "costs": costs})


@hook("compile_actions")
def utility_actions(info):
    """Move Cauldron Anchor: a table setting of its own, no action and no cost."""
    if FIELD not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    values = numbers_for_compile(info)
    if int(values["cl"]) < TIERS[FIELD]:
        return None
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.black_cauldron.move",
        display_name="Move Cauldron Anchor", owner_id=info["actor_id"], economy=EconomyKind.NONE,
        resolution_kind="TYPED", target_kind="SELF",
        # Its own set-source id, never the field's: the compiler seals a zone_spec for any
        # row whose source is a mechanic, and this setting does not make a zone.
        parameters={"black_cauldron_move": True,
                    "typed": {"source": "black_cauldron_move", "feature_id": FIELD, "numbers": values,
                              "manual_inline_choice": True,
                              "effects": [{"type": "black_cauldron_move"}], "riders": [],
                              "duration": {"kind": "instant"}}})]


@hook("candidate_allowed")
def admission(engine, actor, candidate, action):
    """The field once per scene; the anchor move once per turn and only while a field stands."""
    if action is None:
        return None
    if action.parameters.get("black_cauldron_move"):
        return bool(fields(engine, actor)) and actor.turn_flags.get("black_cauldron_move") != turn_id(engine)
    typed = action.parameters.get("typed") or {}
    if typed.get("source") != FIELD:
        return None
    return bool(owned(engine, actor)) and not used(actor)


# ---------------------------------------------------------------------------------------------- the field
@hook("zone_creation_profile")
def stamp_field(zone, ctx):
    """Record the chosen principle on the field and on its one trigger, before the zone commits."""
    profile = zone.trigger_profile.get("profile") or {}
    if profile.get("black_cauldron") != 1:
        return None
    kind = ask_field_type(ctx.engine, ctx.actor)
    profile["kind"] = kind
    zone.trigger_profile["profile"] = profile
    for trigger in zone.trigger_profile.get("triggers") or []:
        for row in trigger.get("effects") or []:
            if row.get("type") == "black_cauldron_pulse":
                row["kind"] = kind
    return zone


@hook("zone_created")
def place_anchor(ctx, zone):
    """Place the Cauldron Anchor at the field's centre and spend the scene's one field."""
    profile = zone.trigger_profile.get("profile") or {}
    if profile.get("black_cauldron") != 1:
        return
    from .. import asset_anchor_runtime
    engine, actor = ctx.engine, ctx.actor
    values = numbers(engine, actor)
    anchor = asset_anchor_runtime.create(engine, actor, ctx.source,
        {"name": "Cauldron Anchor", "kind": "cultivation_asset", "ac": int(values["save_dc"]),
         "hp": 5 * int(values["cl"]), "source_cl": int(values["cl"]), "height_ft": 5, "group": GROUP,
         "saving_throw_bonus": int(values["key_mod"]) + int(values["pb"])},
        zone.center,
        component={"width_cells": 2, "length_cells": 2, "daemonic": 1, "black_cauldron": 1,
                   "key_mod": int(values["key_mod"]), "pb": int(values["pb"])})
    profile["anchor"] = anchor.object_id
    zone.trigger_profile["profile"] = profile
    engine._apply_condition(actor, USED, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
        data={"field_used": 1, "ends_with_scene": 1, "hidden": True,
              "label": "Heaven-Devouring Cauldron: this scene's field has been placed"})


@hook("presentation_hidden_conditions")
def conceal_ledger(engine, actor):
    """The scene ledger is internal bookkeeping, never a condition a player is told about."""
    return {held.instance_id for held in actor.conditions.values() if held.condition_id == USED}


@hook("event", nested=True)
def field_ended(engine, event_type, kwargs):
    """A field that ends takes its anchor with it (the engine ends the field for Concentration too)."""
    if event_type != "ZONE_REMOVED":
        return
    zone = engine.state.zones.get((kwargs.get("payload") or {}).get("zone_id"))
    if zone is None or (zone.trigger_profile.get("profile") or {}).get("black_cauldron") != 1:
        return
    from .. import asset_anchor_runtime
    profile = zone.trigger_profile["profile"]
    anchor = engine.state.objects.get(profile.get("anchor"))
    if anchor is not None and not anchor.destroyed:
        asset_anchor_runtime.retire(engine, anchor, zone.source_definition_id)


@effect("black_cauldron_pulse", harmful=True)
def field_pulse(ctx, row):
    """The field's entry/start save: 5d8 of its principle, half on a success; a failure also drains a point."""
    from ..typed_executor import run_effects
    kind = str(row["kind"]).lower()
    run_effects(ctx, [{"type": "save", "ability": "con",
        "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 5, "sides": 8}, "damage_types": [kind]},
                    {"type": "black_cauldron_drain", "kind": kind}],
        "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": [kind]}]}])


@effect("black_cauldron_drain", harmful=True)
def field_drain(ctx, row):
    """Lose 1 Cultivation Point (the creature's own choice of pool), no recovery until its next turn; none left: 2d8."""
    from ..resource_labels import resource_name
    from ..typed_executor import run_effects
    from .cp_pools import all_of
    engine, target = ctx.engine, ctx.target
    pools = [pool for pool in all_of(target) if target.resources.get(pool, 0) > 0]
    if pools:
        picked = ask(engine, getattr(engine, "_active_intent", None),
                     checkpoint_id(engine, "black_cauldron_drain_pool", target.entity_id), target,
                     "choice:needle.black_cauldron_drain_pool", pools,
                     labels={pool: f"Lose 1 {resource_name(pool)}" for pool in pools},
                     prompt=f"Heaven-Devouring Cauldron: {target.display_name} loses 1 Cultivation Point; choose which pool it loses it from.",
                     name="Heaven-Devouring Cauldron", feature_id=FIELD)
        # The printed loss is not the creature's to refuse, so this question is not
        # declinable (combat/choice_checkpoints rejects a DECLINE for it) and ask therefore
        # always answers with one of the pools it was offered.
        engine._spend_resource(target, picked[0], 1, FIELD)
    run_effects(ctx, [{"type": "condition", "applies_to": "target", "condition": "no_cp_regain",
                       "expires_on": "START_OF_TARGET_NEXT_TURN",
                       "condition_label": "Heaven-Devouring Cauldron: cannot regain Cultivation Points until its next turn starts"}])
    if not pools:
        run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8},
                           "damage_types": [row["kind"]]}])


@effect("black_cauldron_move")
def move_anchor(ctx, row):
    """Move the anchor up to 20 feet, once during the creator's turn, without an action."""
    from .. import asset_anchor_runtime, zones
    from ..gate2_runtime_models import Position
    engine, owner = ctx.engine, ctx.actor
    if owner.turn_flags.get("black_cauldron_move") == turn_id(engine):
        return
    for zone in fields(engine, owner):
        anchor = engine.state.objects.get((zone.trigger_profile.get("profile") or {}).get("anchor"))
        if anchor is None or anchor.destroyed:
            continue
        options = {}
        for x in range(max(0, anchor.position.x - 4), min(engine.grid.width, anchor.position.x + 5)):
            for y in range(max(0, anchor.position.y - 4), min(engine.grid.height, anchor.position.y + 5)):
                for z in range(max(0, anchor.position.z - 4), anchor.position.z + 5):
                    point = Position(x=x, y=y, z=z)
                    if engine.grid.distance_ft(anchor.position, point) > 20:
                        continue
                    cells = [Position(x=x + dx, y=y + dy, z=z) for dx in range(2) for dy in range(2)]
                    if (asset_anchor_runtime.legal_placement(engine, cells, anchor.height_ft or 5,
                                                             ignore=(anchor.object_id,), require_support=False)
                            and engine.grid.line_of_physical_transmission(anchor.position, point)):
                        options[f"{x},{y},{z}"] = point
        picked = ask(engine, getattr(engine, "_active_intent", None),
                     checkpoint_id(engine, "black_cauldron_move", owner.entity_id), owner,
                     "choice:needle.black_cauldron_move_anchor", list(options),
                     labels={key: f"Square {point.x},{point.y}, {point.z * 5} feet high" for key, point in options.items()},
                     prompt=f"Heaven-Devouring Cauldron: move {owner.display_name}'s Cauldron Anchor up to 20 feet.",
                     name="Heaven-Devouring Cauldron", feature_id=FIELD)
        if not picked:
            return
        point = options[picked[0]]
        engine._update_object(anchor.model_copy(update={"position": point}), ctx.source, owner.entity_id)
        zone.center = point
        zone.affected_cells = zones.area_cells(engine, zone)
        engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=owner.entity_id,
                             payload={"zone": zone.model_dump(mode="json")})
        owner.turn_flags["black_cauldron_move"] = turn_id(engine)
        zones.sync_inside(engine, ctx.source)
        return
