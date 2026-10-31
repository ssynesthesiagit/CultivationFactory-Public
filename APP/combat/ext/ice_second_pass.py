"""Printed Ice Insights and winter aftermath on sealed, source-owned rows.

Shared API: preserve_space is called by ice_fracture before an Ice shatter ends
a cell; scholar_space is called by ice_lattice after Crystallize Path creates
its normal spaces. Both use evented state and existing choices.

The base lattice/Fracture implementation remains ice_lattice/ice_fracture.
This module uses their public queries, not current authority in saved fights.
"""
from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id
from .passive_rows import row_of

BLOCK = "ice_insights"
WINTER = "insight.winter-tempered-body"
WASTE = "insight.shatter-without-waste"
FOOT = "insight.ice-sure-footwork"
SCHOLAR = "insight.lattice-scholar"
USED = "condition:typed.winter_sure_foot_used"
CRUCIBLE = "condition:typed.winter_crucible"
ICEFALL = "TAL_ICE_WORLD_FANG_ICEFALL"
PALACE = "TAL_ICE_PALACE_WHERE_FOOTSTEPS_BECOME_WALLS"


@hook("compile_block")
def compile_insights(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, "block": BLOCK, "kind": row["feature_id"],
                 "pb": int(numbers["pb"]), "cl": int(numbers["cl"]),
                 "key_mod": int(numbers.get("key_mod") or 0), "second_pass": 1}]


def owned(engine, actor, feature):
    return row_of(engine, actor.entity_id, BLOCK, feature)


def touches_own_lattice(engine, actor):
    from .ice_fracture import lattice_zones
    cells = set(engine._actor_cells(actor))
    return any(p.z == actor.position.z and (p.x, p.y) in cells
               for z in lattice_zones(engine, actor.entity_id) for p in z.affected_cells)


def ice_ground(engine, actor, *, mundane=False):
    from .. import zones
    from ..falling import supported
    if not supported(engine, actor):
        return False
    if not mundane:
        if touches_own_lattice(engine, actor):
            return True
    cells = set(engine._actor_cells(actor))
    for zone in zones.typed_zones(engine):
        if mundane and not zone.trigger_profile.get("map"):
            continue
        names = {str(n).lower() for n in zone.trigger_profile.get("terrain") or []}
        material = str((zone.trigger_profile.get("visual") or {}).get("material") or "").lower()
        if (names & {"ice", "snow", "mundane ice", "mundane snow"} or material in {"ice", "snow"}) \
                and cells & {(p.x, p.y) for p in zone.affected_cells} and actor.position.z == zone.center.z:
            return True
    return False


@hook("condition_application_attempt")
def sure_foot(engine, subject, condition_id, source, source_actor_id):
    if condition_id not in {"condition:typed.prone", "condition:core.prone"} or not owned(engine, subject, WINTER) \
            or any(c.condition_id == USED for c in subject.conditions.values()) or not ice_ground(engine, subject):
        return None
    # Name the action that would knock the subject down, so an off-turn or
    # AI-driven prompt still says what is happening to this creature.
    action = (getattr(engine, "action_catalog", {}) or {}).get(str(source))
    trigger = getattr(action, "display_name", None)
    if not trigger and str(source) == "ICE_BASE_SPENDING_A_FRACTURE_MARK":
        # Nested Shatter Space effects carry the base response source rather
        # than a registered action id. Keep the off-turn prompt player-facing.
        trigger = "Shatter Space (Ice Fracture Response)"
    if not trigger:
        trigger = "an effect"
    picked = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "winter_foot", subject.entity_id, source), subject,
                 CHOICE + "winter_foot", ["stay"], labels={"stay": "Stay on your feet (once this fight)"},
                 allow_decline=True, name="Sure Foot on Winter", feature_id=WINTER,
                 prompt_context={"action_name": trigger, "source_definition_id": str(source)},
                 prompt=f"{trigger} would knock {subject.display_name} Prone on ice, snow, or Frost Lattice. "
                        "Use Sure Foot on Winter to stay standing? No action or CP; once this fight. "
                        "Damage and forced movement still happen.")
    if not picked:
        return None
    engine._apply_condition(subject, USED, WINTER, subject.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Sure Foot on Winter used this fight"})
    note(engine, WINTER, subject, "Sure Foot on Winter: stays standing; damage and movement are unchanged.")
    return False


@hook("temp_hp_offered_bonus")
def winter_hp(engine, subject, amount, source, source_actor_id, *, consume=True):
    row = owned(engine, subject, WINTER)
    action = engine.action_catalog.get(source)
    feature = str(((action.parameters or {}).get("typed") or {}).get("source") or source) if action else str(source)
    if not row or amount <= 0 or not feature.startswith(("ICE_", "TAL_ICE_")):
        return None
    # "grants you": the Insight belongs to the recipient, irrespective of who
    # made the Ice grant. One recipient cannot claim it twice in this activation.
    intent = getattr(engine, "_active_intent", None)
    key = f"{getattr(intent, 'intent_id', '')}:{source}:{source_actor_id}"
    if intent is None or subject.turn_flags.get("ice_hp_bonus_round_activation") == key:
        return None
    if consume:
        subject.turn_flags["ice_hp_bonus_round_activation"] = key
    return row["pb"]


@hook("difficult_exempt")
def footwork_terrain(engine, actor):
    if not owned(engine, actor, FOOT):
        return None
    from .. import zones, motion
    cells = set()
    for zone in zones.map_zones(engine):
        names = {str(n).lower() for n in zone.trigger_profile.get("terrain") or []}
        material = str((zone.trigger_profile.get("visual") or {}).get("material") or "").lower()
        if names & {"ice", "snow", "mundane ice", "mundane snow"} or material in {"ice", "snow"}:
            cells.update((p.x, p.y) for p in zone.affected_cells)
    return motion.TerrainExemption(cells, nonmagical_only=True)


@hook("stand_cost")
def footwork_stand(engine, actor, normal_cost):
    if not owned(engine, actor, FOOT):
        return None
    if owned(engine, actor, "TAL_ICE_SURE_FOOTED_DISCIPLE") and touches_own_lattice(engine, actor):
        return 5


@hook("check_hazard_mode")
def scholar_check(engine, actor, ability, skill, hazards):
    topics = {"magical_terrain", "ice_structure", "crystalline_formation"}
    relevant = topics.intersection(hazards) or ("battlefield_array" in hazards and
                {"lines", "angles", "repeating_patterns"}.intersection(hazards))
    if owned(engine, actor, SCHOLAR) and ability == "INT" and str(skill).lower() in {"arcana", "investigation"} \
            and relevant:
        return "ADVANTAGE"


def scholar_space(ctx):
    """The Insight's optional extra visible surface, with its shorter clock."""
    if owned(ctx.engine, ctx.actor, SCHOLAR):
        extra_space(ctx, SCHOLAR)


def extra_space(ctx, feature, parent=None):
    from ..senses import perceives_cell
    from ..targeting import line_of_effect
    from ..gate2_runtime_models import Position, ZoneState
    from .. import zones
    from .ice_lattice import counted_spaces, lattice_limit
    from .ice_fracture import rows

    engine, caster = ctx.engine, ctx.actor
    options = {}
    for x in range(engine.grid.width):
        for y in range(engine.grid.height):
            levels = {0}
            for bottom, top in engine.grid.terrain_spans.get("BLOCKED", {}).get((x, y), []):
                if top is not None and top % 5 == 0:
                    levels.add(top // 5)
            for z in sorted(levels):
                p = Position(x=x, y=y, z=z)
                if engine.grid.distance_ft(caster.position, p) <= 60 and perceives_cell(engine, caster, p) and line_of_effect(engine, caster, destination=p) \
                        and not engine.grid.terrain_at((x, y, z), "BLOCKED"):
                    options[f"cell:{x},{y}" + (f",{z}" if z else "")] = p
    if not options:
        return
    scholar = feature == SCHOLAR
    label = "Lattice Scholar" if scholar else "Immortal Winter Crucible"
    selected = ask(engine, ctx.intent, checkpoint_id(engine, "scholar_space" if scholar else "crucible_space", caster.entity_id), caster,
                   CHOICE + ("scholar_space" if scholar else "crucible_space"), list(options),
                   labels={k: f"Extra Lattice Space ({p.x}, {p.y}, {p.z})" for k, p in options.items()},
                   allow_decline=scholar, name=label, feature_id=feature,
                   prompt=f"{label}: choose one extra visible Lattice Space within 60 feet" +
                          (", or decline. No extra action or CP. This extra space ends at the end of your next turn." if scholar
                           else ". No extra action or CP. It has the creation's lifetime."))
    if not selected:
        return
    p = options[selected[0]]
    exempt = bool(parent and parent.trigger_profile.get("lattice_cap_exempt"))
    if not exempt:
        found = counted_spaces(engine, caster.entity_id)
        cap = lattice_limit(ctx.numbers) + (int(ctx.numbers.get("pb") or 0) if rows(engine, caster, "nascent") else 0)
        for old in found[:max(0, len(found) + 1 - cap)]:
            zones.remove(engine, old, "LATTICE_LIMIT")
    profile = {"kind": "TYPED", "name": label, "lattice_space": True, "lattice_cap_exempt": exempt,
               "numbers": dict(ctx.numbers), "terrain": [], "triggers": [], "inside": [], "visual": {"material": "ice"}}
    if scholar:
        profile["end_after_owner_turn"] = caster.turns_started + 1
    elif parent:
        for k in ("start_of_owner_turn", "end_after_owner_turn"):
            if k in parent.trigger_profile:
                profile[k] = parent.trigger_profile[k]
        if parent.concentration_link:
            profile["ends_with"] = parent.zone_id
    zone = ZoneState(zone_id=f"zone:lattice:extra:{engine.state.event_sequence + 1}",
                     source_definition_id=ctx.source, owner_id=caster.entity_id, center=p, radius_cells=0,
                     affected_cells=(p,), concentration_link=False,
                     duration_rounds=parent.duration_rounds if parent else None,
                     created_round=engine.state.round_number, trigger_profile=profile)
    engine.state.zones[zone.zone_id] = zone
    engine._append_event("ZONE_CREATED", ctx.source, actor_id=caster.entity_id, payload={"zone": zone.model_dump(mode="json")})


@hook("zone_created")
def crucible_area_extra(ctx, zone):
    from .ice_fracture import LATTICE_SOURCES
    if str(ctx.typed.get("source") or "") in LATTICE_SOURCES and any(
            c.condition_id == CRUCIBLE for c in ctx.actor.conditions.values()):
        if str(ctx.typed.get("source") or "") in {"TAL_ICE_WORLD_FANG_ICEFALL", "TAL_ICE_ICE_DOMAIN_PALACE_OF_WRITTEN_WINTER", "TAL_ICE_THE_WORLD_BECOMES_A_SINGLE_CRYSTAL"}:
            zone.trigger_profile["lattice_cap_exempt"] = True
        extra_space(ctx, "TAL_ICE_IMMORTAL_WINTER_CRUCIBLE", zone)


def table_turn_key(engine):
    actor = engine.state.actors.get(engine.state.current_actor_id)
    return f"{engine.state.round_number}:{engine.state.current_actor_id}:{actor.turns_started if actor else 0}"


def preserve_space(engine, zone, cell):
    """Optional replacement only for an Ice shatter's own ending."""
    owner = engine.state.actors.get(zone.owner_id)
    row = owned(engine, owner, WASTE) if owner else None
    if not row or owner.turn_flags.get("ice_preserve_turn") == table_turn_key(engine):
        return False
    from .. import zones
    profile = zone.trigger_profile
    next_end = owner.turns_started + 1
    # "If it would already end at or before that time ... no effect."
    if profile.get("start_of_owner_turn") and profile["start_of_owner_turn"] <= next_end \
            or profile.get("end_after_owner_turn") and profile["end_after_owner_turn"] <= next_end:
        return False
    if zone.duration_rounds is not None and zone.created_round + zone.duration_rounds <= engine.state.round_number + 1:
        return False
    picked = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "preserve_lattice", zone.zone_id, cell), owner, CHOICE + "preserve_lattice",
                 ["keep"], labels={"keep": "Keep this space until the end of your next turn"},
                 allow_decline=True, name="Shatter Without Waste", feature_id=WASTE,
                 prompt=f"Shatter Without Waste: keep Lattice Space ({cell[0]}, {cell[1]}) instead of ending it? "
                        "No action or CP; once per turn. Its remaining duration becomes the end of your next turn.")
    if not picked:
        return False
    owner.turn_flags["ice_preserve_turn"] = table_turn_key(engine)
    # Individual cells in a larger lattice need their own deadline. Split just
    # this cell, retaining the rest of the original area and its lifetime.
    p = next(p for p in zone.affected_cells if (p.x, p.y) == cell)
    if len(zone.affected_cells) > 1:
        zone.affected_cells = tuple(q for q in zone.affected_cells if (q.x, q.y) != cell)
        zone.trigger_profile["footprint_is_authoritative"] = True
        engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})
        kept = zone.model_copy(deep=True)
        kept.zone_id = f"zone:lattice:preserved:{engine.state.event_sequence + 1}"
        kept.center, kept.affected_cells = p, (p,)
        if zone.concentration_link:
            # Concentration owns the original zone id. The preserved cell is
            # dependent on that parent, not a second concentration root.
            kept.concentration_link = False
            kept.trigger_profile["ends_with"] = zone.zone_id
        kept.trigger_profile["footprint_is_authoritative"] = True
        engine.state.zones[kept.zone_id] = kept
    else:
        kept = zone
    kept.trigger_profile["footprint_is_authoritative"] = True
    kept.duration_rounds = None
    kept.trigger_profile.pop("start_of_owner_turn", None)
    kept.trigger_profile["end_after_owner_turn"] = next_end
    engine._append_event("ZONE_CREATED", kept.source_definition_id, actor_id=kept.owner_id, payload={"zone": kept.model_dump(mode="json")})
    return True


def end_half(engine, owner):
    from .ice_fracture import lattice_zones
    from .. import zones
    options = {f"{z.zone_id}:{i}": (z, p) for z in lattice_zones(engine, owner.entity_id)
               for i, p in enumerate(z.affected_cells)}
    count = len(options) // 2
    if not count:
        return
    selected = ask(engine, getattr(engine, "_active_intent", None),
                   checkpoint_id(engine, "crucible_half", owner.entity_id), owner,
                   CHOICE + "crucible_half", list(options),
                   labels={k: f"End Lattice Space ({p.x}, {p.y}, {p.z})" for k, (z, p) in options.items()},
                   minimum=count, maximum=count, default_count=count, name="Immortal Winter Crucible",
                   feature_id="TAL_ICE_IMMORTAL_WINTER_CRUCIBLE",
                   prompt=f"Immortal Winter Crucible ends. Choose {count} of your {len(options)} active Lattice Spaces to end now. No extra cost.")
    chosen = {k for k in selected}
    for zone in list(lattice_zones(engine, owner.entity_id)):
        keep = tuple(p for i, p in enumerate(zone.affected_cells) if f"{zone.zone_id}:{i}" not in chosen)
        if keep == zone.affected_cells:
            continue
        if not keep:
            zones.remove(engine, zone, "CRUCIBLE_ENDED")
        else:
            zone.trigger_profile["footprint_is_authoritative"] = True
            zone.affected_cells = keep
            engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=owner.entity_id, payload={"zone": zone.model_dump(mode="json")})


@hook("state_event")
def winter_lifecycle(engine, event):
    from .ice_fracture import source_feature
    payload = event.payload or {}
    if event.event_type == "CONDITION_APPLIED" and payload.get("condition_id") == CRUCIBLE:
        holder = engine.state.actors.get(event.target_ids[0])
        condition = holder.conditions.get(payload.get("instance_id")) if holder else None
        if condition and condition.data.get("second_pass"):
            holder.turn_flags["ice_crucible_round_instance"] = condition.instance_id
    elif event.event_type == "CONDITION_REMOVED" and payload.get("condition_id") == CRUCIBLE:
        for holder in engine.state.actors.values():
            if holder.turn_flags.get("ice_crucible_round_instance") == payload.get("instance_id"):
                holder.turn_flags.pop("ice_crucible_round_instance", None)
                end_half(engine, holder)
    elif event.event_type == "ZONE_REMOVED" and payload.get("reason") == "SHATTERED":
        zone = engine.state.zones.get(payload.get("zone_id"))
        if zone:
            destroyed_spaces(engine, zone, zone.affected_cells)
    elif event.event_type == "MOVEMENT_COMMITTED" and not payload.get("teleport"):
        free_icefall(engine, event)
        palace_walls(engine, event)


@hook("zone_cells_destroyed")
def destroyed_spaces(engine, zone, cells):
    """A removed physical space, not an expiry, replacement or cap eviction."""
    from .ice_fracture import LATTICE_SOURCES, source_feature, fracture_numbers
    from ..target_knowledge import located
    owner = engine.state.actors.get(zone.owner_id)
    if not owner or not owner.turn_flags.get("ice_crucible_round_instance") or not (
            zone.trigger_profile.get("lattice_space") or source_feature(engine, zone.source_definition_id) in LATTICE_SOURCES):
        return
    for cell in cells:
        victims = [a for a in engine.state.actors.values() if a.active and a.team_id != owner.team_id
                   and located(engine, owner, a) and engine.grid.distance_ft(a.position, cell) <= 5]
        options = {a.entity_id: a for a in victims}
        if not options:
            continue
        picked = ask(engine, getattr(engine, "_active_intent", None),
                     checkpoint_id(engine, "crucible_damage", zone.zone_id, cell.model_dump(mode="json")), owner,
                     CHOICE + "crucible_damage", list(options),
                     labels={k: f"Deal damage to {a.display_name}" for k, a in options.items()},
                     automatic_options=list(options), allow_decline=True, name="Immortal Winter Crucible",
                     prompt="A Lattice Space you created was destroyed. Deal your Proficiency Bonus in Cold or Piercing damage to one hostile creature within 5 feet? No action or CP.")
        if not picked:
            continue
        victim = options[picked[0]]
        dtype = ask(engine, getattr(engine, "_active_intent", None),
                    checkpoint_id(engine, "crucible_type", zone.zone_id, cell.model_dump(mode="json")), owner,
                    CHOICE + "crucible_type", ["COLD", "PIERCING"], labels={"COLD": "Cold", "PIERCING": "Piercing"},
                    target_id=victim.entity_id, name="Immortal Winter Crucible",
                    prompt=f"Choose Cold or Piercing for Immortal Winter Crucible's damage to {victim.display_name}.")
        engine._commit_damage(victim, int(fracture_numbers(engine, owner).get("pb") or 2), dtype[0],
                              "TAL_ICE_IMMORTAL_WINTER_CRUCIBLE", owner.entity_id, None, reaction_depth=1)


def free_icefall(engine, event):
    from .ice_fracture import response_available, count_response, shatter_response, fracture_numbers, lattice_cells
    from .. import zones
    from ..target_knowledge import located
    from ..gate2_runtime_models import Position
    from ..spatial_areas import zone_contains
    mover = engine.state.actors.get(event.actor_id)
    if not mover or not mover.active:
        return
    path = [Position.model_validate(p) for p in event.payload.get("path") or []]
    for zone in zones.typed_zones(engine):
        if not zone.active or not zone.trigger_profile.get("ice_free_shatter"):
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if not owner or mover.team_id == owner.team_id:
            continue
        ft = 0
        checkpoint = None
        key = f"icefall_distance_round_{zone.zone_id}"
        before = int(mover.turn_flags.get(key) or 0)
        for a, b in zip(path, path[1:]):
            if not (zone_contains(engine, mover, zone, at=a) and zone_contains(engine, mover, zone, at=b)):
                continue
            step_ft = engine.grid.distance_ft(a, b)
            if before + ft < 10 <= before + ft + step_ft:
                checkpoint = b
            ft += step_ft
        if before < 0:
            continue  # first qualifying crossing already occurred, even if declined
        mover.turn_flags[key] = before + ft
        if before + ft < 10:
            continue
        mover.turn_flags[key] = -1
        if checkpoint is None or not response_available(engine, owner):
            continue
        perceived_mover = mover.model_copy(update={"position": checkpoint})
        if not located(engine, owner, perceived_mover):
            continue
        # Shatter Space requires an occupied Lattice Space. A qualifying path
        # checkpoint must still overlap the zone's real lattice footprint.
        if not (set(engine._actor_cells(mover, checkpoint)) & lattice_cells(engine, owner.entity_id)):
            continue
        picked = ask(engine, getattr(engine, "_active_intent", None),
                     checkpoint_id(engine, "icefall_free", zone.zone_id, mover.entity_id), owner,
                     CHOICE + "icefall_free", ["shatter"], allow_decline=True,
                     labels={"shatter": f"Shatter Space against {mover.display_name} without spending a mark"},
                     name="World-Fang Icefall", feature_id=ICEFALL, target_id=mover.entity_id,
                     prompt=f"{mover.display_name} first moved 10 feet through World-Fang Icefall. "
                            "Use Shatter Space now? No Fracture Mark, action or CP is spent; it counts against your once-per-round limit.")
        if picked:
            count_response(engine, owner)
            row = fracture_numbers(engine, owner)
            shatter_response(engine, owner, mover, int(row.get("cl") or 1), int(row.get("pb") or 2), at=checkpoint)


@effect("icefall_lattice")
def icefall_created(ctx, spec):
    for zone in ctx.engine.state.zones.values():
        if zone.active and zone.source_definition_id == ctx.source and zone.owner_id == ctx.actor.entity_id:
            zone.trigger_profile["ice_free_shatter"] = 1
            zone.trigger_profile["difficult"] = "hostile"
            ctx.engine._append_event("ZONE_CREATED", ctx.source, actor_id=ctx.actor.entity_id, payload={"zone": zone.model_dump(mode="json")})


@effect("ice_winter_crucible")
def crucible_started(ctx, spec):
    ctx.engine._apply_condition(ctx.actor, CRUCIBLE, ctx.source, ctx.actor.entity_id,
                                expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                data={"second_pass": 1, "label": "Immortal Winter Crucible: extra lattice, free own-turn response, and destruction damage"})


def palace_walls(engine, event):
    """Post-movement wall panels at the path, with native wall defenses/lifetime."""
    from .. import zones
    from ..target_knowledge import located
    from ..senses import perceives_cell
    from ..targeting import line_of_effect
    from ..gate2_runtime_models import Position
    from ..typed_executor import Context
    from ..spatial_areas import zone_contains
    from ..gate2_runtime_models import ActionDefinition
    from .ice_fracture import DOMAIN, source_feature
    from .d20_rewrite import pool_id
    from .choice_costs import Payment

    mover = engine.state.actors.get(event.actor_id)
    path = [Position.model_validate(p) for p in (event.payload or {}).get("path") or []]
    if not mover or len(path) < 3:
        return
    for owner in engine.state.actors.values():
        row = owned(engine, owner, PALACE)
        if not row or not owner.active or owner.team_id == mover.team_id or not located(engine, owner, mover):
            continue
        domains = [z for z in zones.typed_zones(engine) if z.active and z.owner_id == owner.entity_id
                   and source_feature(engine, z.source_definition_id) == DOMAIN]
        ft = sum(engine.grid.distance_ft(a, b) for a, b in zip(path, path[1:])
                 if any(zone_contains(engine, mover, z, at=a) and zone_contains(engine, mover, z, at=b) for z in domains))
        if ft < 10:
            continue
        cp = pool_id(owner, "cp")
        if not cp or not engine._can_pay(owner, ((cp, 2),), source_id=PALACE):
            continue
        occupied = {cell for a in engine.state.actors.values() if a.active for cell in engine._actor_volume(a)}
        # Exact volumes enforce solid panels without projecting flying bodies
        # onto ground or granting a trigger outside the Domain's volume.
        options = {}
        for anchor in path:
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    for dz in range(-1, 2):
                        xyz = (anchor.x+dx, anchor.y+dy, anchor.z+dz)
                        if min(xyz) < 0 or not engine.grid.in_bounds(xyz[:2]) or xyz in occupied or engine.grid.terrain_at(xyz, 'BLOCKED'):
                            continue
                        p = Position(x=xyz[0], y=xyz[1], z=xyz[2])
                        supported = not p.z or any(engine.grid.terrain_at((p.x+sx, p.y+sy, p.z+sz), 'BLOCKED')
                            for sx, sy, sz in ((0,0,-1),(1,0,0),(-1,0,0),(0,1,0),(0,-1,0)))
                        if supported and perceives_cell(engine, owner, p) and line_of_effect(engine, owner, destination=p):
                            options[f"cell:{p.x},{p.y}" + (f",{p.z}" if p.z else "")] = p
        count = row["pb"]
        if len(options) < count:
            continue
        payment = Payment(cp, 2)
        selected = ask(engine, getattr(engine, '_active_intent', None),
                       checkpoint_id(engine, 'palace_panels', owner.entity_id, event.sequence), owner,
                       CHOICE+'palace_panels', list(options), labels={k:f"Glacier Wall panel ({p.x}, {p.y}, {p.z})" for k,p in options.items()},
                       minimum=count, maximum=count, default_count=count, allow_decline=True,
                       name='Palace Where Footsteps Become Walls', feature_id=PALACE, target_id=mover.entity_id, payment=payment,
                       prompt=f"{mover.display_name} moved at least 10 feet through your Ice Domain. Spend 2 CP, without an action, "
                              f"to create {count} Glacier Wall panels along or beside its path? They last until the start of your next turn.")
        if not selected:
            continue
        payment.pay(engine, owner, PALACE)
        wall = dict(zones.terrain_rules()['walls']['glacier wall'])
        wall['length_ft'] = 5
        wall['height_ft'] = 5
        # This talent explicitly lets its panels divide lines of sight.
        wall['see_through'] = False
        wall['blocks_sight'] = True
        # Build each real panel at one selected square, independent of the
        # ordinary wall-plan direction. Each selected panel has solid support.
        action = ActionDefinition(source_definition_id=PALACE, display_name='Palace Where Footsteps Become Walls',
                                  owner_id=owner.entity_id, economy='NONE', resolution_kind='TYPED', target_kind='SELF')
        ctx = Context(engine, owner, action, getattr(engine, '_active_intent', None),
                      {'source':PALACE,'numbers':{'pb':row['pb'],'cl':row['cl'],'key_mod':row['key_mod']},'effects':[]}, [])
        for key in selected:
            p = options[key]
            zone = zones.prospective_zone(ctx, {'name':'Glacier Wall panel', 'shape':'wall', 'size_ft':5,
                'wall':{**wall, 'base_altitude_ft':p.z*5},'duration':{'kind':'one_minute'},'color':'#bfe8ff'}, p)
            zone.affected_cells=(p,)
            zone.duration_rounds=None
            zone.trigger_profile.update(lattice_space=True,lattice_cap_exempt=True,start_of_owner_turn=owner.turns_started+1)
            engine.state.zones[zone.zone_id]=zone
            engine._append_event('ZONE_CREATED', PALACE, actor_id=owner.entity_id,payload={'zone':zone.model_dump(mode='json')})
        if any(c.condition_id == CRUCIBLE for c in owner.conditions.values()):
            extra_space(ctx, "TAL_ICE_IMMORTAL_WINTER_CRUCIBLE", zone)
        zones.sync_walls(engine)
