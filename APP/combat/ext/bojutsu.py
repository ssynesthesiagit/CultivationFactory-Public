"""Staff-bound Bojutsu riders, read from hash-bound owned mechanic markers.

Staff identification uses the owner's weapon proficiency group and item tags,
never the display name of an attack. Staff Form offers the original ability
and Constitution variants; on-turn reach variants leave off-turn reach intact.
Flowing Spin copies that Staff's die, properties and modifiers, floors the die
at d6 and makes one Bonus Action attack after an actual Staff Attack-action
roll. Sweeping Strike offers its paid save and exactly one failed-save result
after a Staff hit. Repositioning uses a shortest legal physical path, limited
by the distance between the selected spaces, and emits forced movement.

No Staff carried, old typing, or a non-Staff attack leaves these hooks inert.
Staff of One supplies its AC bonus only while a Staff remains wielded, and
Advantage only to a Staff Opportunity Attack or a save retaining that Staff.
Deflecting Staff uses damage_pending for the actual ranged weapon-hit packet,
after ordinary defenses and before Temporary HP/HP, paying one Stamina and one
Reaction at most once per round. The evented round marker survives reload.
Separate on-hit effects, spell attacks and unknown projectile delivery stay
inert. Opt-in zero-damage choices use the same player-owned checkpoint: legal
physical movement (not forced or teleported) or ally Half Cover. Catching and
placing a projectile remain named GM choices until its item/free-hand identity
is represented; neither choice creates an item. Cover uses the table's ranged
attack cover hook and expires at the interceptor's next turn start.
Integrated fist benefits remain separately adjudicated; no Sphere is granted.
Heavenly Staff Barrier's opt-in marker starts its ten-round clock and its
once-per-turn hit menu applies one printed result. Opt-in Staff reach variants
and the pure opportunity_profile hook supply its temporary reach to existing
Staff OAs. While the Barrier is on and a Staff is wielded (rider lane C7), the
wielder and allies within 10 feet have Half Cover against ranged weapon attacks
(the cover hook, read from the attack actually resolving; energy/cultivation
attacks and unknown native attacks get none), and a creature hit by the
wielder's Staff Opportunity Attack has Speed 0 until the end of the current turn
(movement already under way finishes: the locked movement loop has no per-step
stop). Selecting a Staff OA when the default best attack is unarmed, entry
interception and the restricted extra Reaction remain lock-round work.
"""
from __future__ import annotations

from ..paid_relocation import activation

import copy
from typing import Any

from . import effect, hook

PREFIX = "tianxia.subpath.body.bojutsu.feature."
ATTACKED = "condition:typed.bojutsu_staff_attack_action"
SWEEP_USED = "condition:typed.bojutsu_sweep_used"
DEFLECT_USED = "condition:typed.bojutsu_deflect_used"
DEFLECT_COVER = "condition:typed.bojutsu_deflect_cover"
BARRIER = "condition:typed.bojutsu_barrier"
BARRIER_USED = "condition:typed.bojutsu_barrier_hit_used"
BARRIER_AC = "condition:typed.bojutsu_barrier_ac"


def _typed(action):
    return (action.parameters or {}).get("typed") or {}


def _staff(typed):
    from ..factory_compiler import _weapon_rules
    from factory_authoring.starting_kits import _authorities

    item_id = str(typed.get("bojutsu_item") or typed.get("source") or "")
    item = _authorities()[1].get(item_id) or {}
    tags = str(item.get("tags") or "").lower().replace(",", " ").split()
    group = ((_weapon_rules().get("proficiency") or {}).get("groups") or {}).get("staff") or []
    return any(e.get("type") == "attack" and e.get("attack_kind") == "weapon" for e in typed.get("effects") or []) and (
            item_id.split(".")[-1] in group or "staff" in tags or
            str(item.get("srd_price_equivalent") or "").lower() == "quarterstaff") and bool(typed.get("weapon"))


def _rows(engine, actor, kind):
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "bojutsu" and row.get("kind") == kind]


def _stamp(engine):
    return [engine.state.round_number, engine.state.current_slot_index, engine.state.current_actor_id]


def _wielded_staff(engine, actor):
    """Return ordinary carried Staff actions not disabled by disarm/theft."""
    disabled = {c.data.get("disables_action") for c in actor.conditions.values()}
    return [action for action in engine.action_catalog.values()
            if action.owner_id == actor.entity_id and action.economy.value == "ACTION"
            and "#" not in action.source_definition_id and action.source_definition_id not in disabled
            and not (action.parameters or {}).get("requires_held_weapon") and _staff(_typed(action))]


@hook("ac")
def staff_of_one_ac(engine, actor):
    bonus = int(bool(_rows(engine, actor, "one") and _wielded_staff(engine, actor)))
    bonus += int(any(c.condition_id == BARRIER_AC for c in actor.conditions.values()))
    return bonus or None


@hook("attack_mode")
def staff_opportunity_advantage(ctx, target):
    if (_rows(ctx.engine, ctx.actor, "one") and _staff(ctx.typed)
            and ctx.typed.get("opportunity_of") in {a.source_definition_id for a in _wielded_staff(ctx.engine, ctx.actor)}
            and getattr(ctx.engine, "_typed_oa_attacker", None) == ctx.actor.entity_id):
        return "ADVANTAGE"
    return None


@hook("save")
def retain_staff_save(ctx, subject, ability, named):
    if "disarmed" not in named or not _rows(ctx.engine, subject, "one"):
        return None
    # Match the executor's selected weapon, including its prior-owner recovery
    # case. Wielding a Staff does not protect a different weapon from disarm.
    if any(c.data.get("held_by") == subject.entity_id for c in ctx.actor.conditions.values()):
        return None
    from ..typed_executor import _best_weapon_action

    selected = _best_weapon_action(ctx.engine, subject)
    if selected in {a.source_definition_id for a in _wielded_staff(ctx.engine, subject)}:
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@effect("bojutsu")
def marker(ctx, row):
    """Owned Bojutsu marker; barrier activation starts its source clock."""
    if row.get("kind") == "barrier":
        from .effect_durations import round_token

        ctx.engine._remove_condition(ctx.actor, BARRIER, ctx.source)
        ctx.engine._apply_condition(ctx.actor, BARRIER, ctx.source, ctx.actor.entity_id,
            expires_on=round_token(ctx.engine, 10), data={"label": "Heavenly Staff Barrier"})


@hook("damage_pending")
def deflecting_staff(engine, target, pending, source_definition_id, source_actor_id):
    """Intercept a represented ranged weapon packet; unrepresented delivery is inert."""
    from .. import typed_reactions
    from ..gate2_runtime_models import DiceSpec
    from .effect_durations import round_token
    from .needle import ask, checkpoint_id

    packet = getattr(engine, "_typed_damage_packet", None) or {}
    if (pending <= 0 or not target.active or not packet.get("weapon") or not packet.get("ranged")
            or packet.get("kind") != "weapon" or not packet.get("interceptable")
            or (packet.get("source"), packet.get("actor"), packet.get("target"))
            != (source_definition_id, source_actor_id, target.entity_id)):
        return None
    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return None
    incoming = engine.action_catalog.get(source_definition_id)
    action_name = incoming.display_name if incoming else str(source_definition_id)
    for actor in engine.state.actors.values():
        rows = _rows(engine, actor, "deflect")
        if (not rows or actor.team_id != target.team_id or not _wielded_staff(engine, actor)
                or engine._distance_actor_to_actor(actor, target) > 5
                or not typed_reactions._can_react(engine, actor)
                or actor.resources.get("resource:core.stamina", 0) < 1
                or any(c.condition_id == DEFLECT_USED and c.data.get("round") == engine.state.round_number
                       for c in actor.conditions.values())):
            continue
        row = rows[0]
        if not typed_reactions._subject_ok(engine, actor, engine.state.actors.get(source_actor_id), row):
            continue
        prompt = f"Deflecting Staff: reduce {action_name}'s damage to {target.display_name}?"
        selected = ask(engine, intent, checkpoint_id(engine, "bojutsu_deflect", target.entity_id), actor,
                       "choice:needle.bojutsu_deflect", ["Use Deflecting Staff"], allow_decline=True,
                       prompt=prompt, target_id=target.entity_id)
        if not selected:
            continue
        with activation(engine, actor, row["feature_id"]):
            typed_reactions._open(engine, row, actor, (target.entity_id,), "DAMAGE_APPLICATION",
                                  {"pending_damage": pending, "protects": target.entity_id})
            engine._spend_resource(actor, "resource:core.stamina", 1, row["feature_id"])
            engine._remove_condition(actor, DEFLECT_USED, row["feature_id"])
            engine._apply_condition(actor, DEFLECT_USED, row["feature_id"], actor.entity_id,
                                    expires_on=round_token(engine, 1), data={"round": engine.state.round_number})
            roll = engine.roller.roll(DiceSpec(count=2, sides=10, modifier=int(row["con_mod"])),
                                      actor_id=actor.entity_id, reason=f"DAMAGE_REDUCTION:{row['feature_id']}")
            engine._record_roll(roll)
            reduced = max(0, pending - max(0, roll.total))
            from .attack_reduction import remember
            reduced = remember(engine, target, pending, reduced, [(max(0, roll.total), ())], delivery='interceptable_weapon')
            engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=actor.entity_id,
                                 target_ids=(target.entity_id,), payload={"checkpoint": "DAMAGE_APPLICATION",
                                 "pending_before": pending, "pending_after": reduced, "reduction": pending - reduced,
                                 "protects": target.entity_id, "name": "Deflecting Staff"})
            if reduced == 0:
                if row.get("zero_choices"):
                    _deflect_result(engine, actor, target, intent, row, action_name)
                else:
                    engine._append_event("GM_RIDER", row["feature_id"], actor_id=actor.entity_id,
                    target_ids=(target.entity_id,), payload={"rider": "Deflecting Staff reduced damage to zero. Choose exactly one: "
                    "catch a holdable projectile with a free hand without duplicating it; deflect into an unoccupied space within "
                    "15 feet without attacking; move 5 feet along a legal route without provoking; or grant the protected ally "
                    "Half Cover until the start of your next turn. These follow-ups remain pending automation."})
            return reduced
    return None


def _deflect_routes(engine, actor, distance=5):
    """Bojutsu willing routes for Deflecting Staff and Heavenly Staff Barrier."""
    from .rider_movement import routes
    return routes(engine, actor, distance)


def _deflect_result(engine, actor, target, intent, row, action_name):
    """Exactly one printed result; unresolved object choices never mint items."""
    from .effect_durations import token
    from .needle import ask, checkpoint_id

    routes = _deflect_routes(engine, actor)
    options = []
    if target.entity_id != actor.entity_id:
        options.append("Grant Half Cover")
    if routes:
        options.append("Move 5 feet")
    options.extend(["Catch projectile", "Deflect projectile"])
    prompt = f"Deflecting Staff: {action_name} against {target.display_name} reduced to zero; choose one result."
    picked = ask(engine, intent, checkpoint_id(engine, "bojutsu_deflect_result", target.entity_id), actor,
                 "choice:needle.bojutsu_deflect_result", options, prompt=prompt, target_id=target.entity_id)
    if not picked:
        return
    source = row["feature_id"]
    if picked[0] == "Grant Half Cover":
        for iid, old in list(target.conditions.items()):
            if old.condition_id == DEFLECT_COVER and old.source_actor_id == actor.entity_id:
                del target.conditions[iid]
                engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id,
                    target_ids=(target.entity_id,), payload={"condition_id": DEFLECT_COVER, "instance_id": iid})
        engine._apply_condition(target, DEFLECT_COVER, source, actor.entity_id,
            expires_on=token("start", actor.entity_id, int(actor.turns_started) + 1),
            data={"label": "Deflecting Staff Half Cover", "cover": 2})
    elif picked[0] == "Move 5 feet":
        destination = ask(engine, intent, checkpoint_id(engine, "bojutsu_deflect_step", target.entity_id), actor,
            "choice:needle.bojutsu_deflect_step", sorted(routes), prompt=prompt + " Choose a legal destination.",
            labels={key: "Move to " + key.removeprefix("cell:") for key in routes},
            target_id=target.entity_id)
        if not destination:
            return
        _staff_step(engine, actor, routes[destination[0]], source)
    else:
        engine._append_event("GM_RIDER", source, actor_id=actor.entity_id, target_ids=(target.entity_id,),
            payload={"rider": f"Deflecting Staff — {picked[0]}: verify the discrete projectile's identity and "
                     "holdability/free hand or unoccupied destination within 15 feet. Item transfer/placement remains "
                     "unresolved; no item was created and no secondary attack was made."})


@hook("cover")
def deflect_cover(engine, attacker, target):
    """The selected ally's Half Cover; the engine takes the best cover, not a sum."""
    return 2 if any(c.condition_id == DEFLECT_COVER for c in target.conditions.values()) else None


def _staff_step(engine, actor, path, source):
    """Commit willing movement for both Bojutsu menus without ordinary OAs."""
    from .rider_movement import step
    step(engine, actor, path, source)


def _barrier_active(engine, actor):
    return bool(_rows(engine, actor, "barrier") and actor.active and _wielded_staff(engine, actor)
            and any(c.condition_id == BARRIER for c in actor.conditions.values()))


def _barrier_reach_active(engine, actor):
    return _barrier_active(engine, actor) and any(row.get("staff_reach") for row in _rows(engine, actor, "barrier"))


@hook("opportunity_profile")
def barrier_opportunity_profile(engine, actor, action):
    """Pure Staff-only OA profile; dormant without an active opted-in Barrier."""
    if not _barrier_reach_active(engine, actor) or not _staff(_typed(action)):
        return None
    staffs = _wielded_staff(engine, actor)
    staff = next((s for s in staffs if s.source_definition_id == _typed(action).get("opportunity_of")), None)
    if staff is None:
        return None
    reach = int(staff.range_ft or 5) + 5
    if engine.state.current_actor_id == actor.entity_id and _rows(engine, actor, "form"):
        reach += 5
    return action.model_copy(update={"range_ft": reach})


@hook("after_hit")
def barrier_hit(ctx, target, kind):
    """Choose one after a Staff hit, once per current turn including AI turns."""
    if kind != "weapon" or not _staff(ctx.typed) or not _barrier_active(ctx.engine, ctx.actor):
        return
    if any(c.condition_id == BARRIER_USED for c in ctx.actor.conditions.values()):
        return
    from .. import typed_executor
    from .effect_durations import token
    from .needle import ask, checkpoint_id

    routes = _deflect_routes(ctx.engine, ctx.actor, 10)
    options = (["Push 10 feet", "No Reactions"] if target.active else [])
    if routes:
        options.append("Move 10 feet")
    options.append("Gain +1 AC")
    prompt = f"Heavenly Staff Barrier: {ctx.action.display_name} hit {target.display_name}; choose one result."
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "bojutsu_barrier_hit", target.entity_id), ctx.actor,
        "choice:needle.bojutsu_barrier_hit", options, prompt=prompt, target_id=target.entity_id)
    if not picked:
        return
    source = PREFIX + "heavenly_staff_barrier"
    current = ctx.engine.state.actors[ctx.engine.state.current_actor_id]
    ctx.engine._apply_condition(ctx.actor, BARRIER_USED, source, ctx.actor.entity_id,
        expires_on=token("end", current.entity_id, int(current.turns_started)),
        data={"label": "Heavenly Staff Barrier hit result used"})
    sub = ctx.on_hit_context(target, action=ctx.action.model_copy(update={'source_definition_id': source}), typed=ctx.typed, damage_cache={})
    if picked[0] == "Push 10 feet":
        typed_executor.run_effects(sub, [{"type": "forced_movement", "direction": "away", "distance_ft": 10,
                                        "applies_to": "target"}])
    elif picked[0] == "No Reactions":
        typed_executor.run_effects(sub, [{"type": "reaction_denied", "applies_to": "target",
                                        "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    elif picked[0] == "Gain +1 AC":
        ctx.engine._remove_condition(ctx.actor, BARRIER_AC, source)
        ctx.engine._apply_condition(ctx.actor, BARRIER_AC, source, ctx.actor.entity_id,
            expires_on=token("start", ctx.actor.entity_id, int(ctx.actor.turns_started) + 1),
            data={"label": "Heavenly Staff Barrier +1 AC", "amount": 1})
    else:
        destination = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "bojutsu_barrier_step", target.entity_id), ctx.actor,
            "choice:needle.bojutsu_barrier_step", sorted(routes), prompt=prompt + " Choose a legal destination.",
            labels={key: "Move to " + key.removeprefix("cell:") for key in routes},
            target_id=target.entity_id)
        if destination:
            _staff_step(ctx.engine, ctx.actor, routes[destination[0]], source)


@hook("compile_actions")
def compile_staff(info: dict[str, Any]):
    from ..gate2_runtime_models import EconomyKind

    specs = []
    for mid in info["owned_ids"]:
        mech = info["mechanics"].get(mid) or {}
        for spec in mech.get("effects") or []:
            if spec.get("type") == "bojutsu":
                row = {**copy.deepcopy(spec), "block": "bojutsu", "feature_id": mid, "name": mech["name"],
                       "numbers": copy.deepcopy(info["numbers"])}
                info["passives"].append(row)
                if row.get("kind") == "deflect":
                    row["con_mod"] = int(info["mods"].get("CON", 0))
                    row["choice_owner"] = True
                if row.get("kind") in {"barrier", "sweep"}:
                    row["choice_owner"] = True
                if row.get("kind") in {"deflect", "barrier", "sweep"}:
                    row["trigger_owner"] = "bojutsu"
                specs.append(row)
    kinds = {row["kind"] for row in specs}
    if not kinds:
        return None
    out = []
    for base in info["actions"]:
        typed = _typed(base)
        if not _staff(typed) or typed.get("range_ft") or base.economy != EconomyKind.ACTION:
            continue
        # A normal Attack action only, not an off-hand, granted or maneuver variant.
        if "#" in base.source_definition_id:
            continue
        variants = [base]
        if "form" in kinds:
            con = copy.deepcopy(typed)
            con["numbers"]["attack_bonus"] = info["numbers"]["attack_bonus"]
            con["weapon"]["damage"]["modifier"] = int(info["mods"].get("CON", 0)) + int(typed.get("magic_bonus") or 0)
            variants.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#bojutsu_con",
                "display_name": base.display_name + " (Constitution)", "parameters": {**base.parameters, "typed": con}}))
            out.append(variants[-1])
            for original in list(variants):
                extended = original.model_copy(update={"source_definition_id": original.source_definition_id + "#bojutsu_reach",
                    "display_name": original.display_name + " (on-turn reach)", "range_ft": int(original.range_ft or 5) + 5,
                    "parameters": {**original.parameters, "bojutsu_on_turn": True}})
                variants.append(extended)
                out.append(extended)
        if any(row.get("staff_reach") for row in specs if row["kind"] == "barrier"):
            for original in list(variants):
                extended = original.model_copy(update={
                    "source_definition_id": original.source_definition_id + "#bojutsu_barrier_reach",
                    "display_name": original.display_name + " (Barrier reach)",
                    "range_ft": int(original.range_ft or 5) + 5,
                    "parameters": {**original.parameters, "bojutsu_barrier_reach": True}})
                variants.append(extended)
                out.append(extended)
        if "flow" in kinds:
            for original in variants:
                flow = copy.deepcopy(_typed(original))
                flow["bojutsu_item"] = typed["source"]
                flow["source"] = PREFIX + "flowing_spin"
                flow.pop("opens", None)
                flow.pop("uses", None)
                flow["weapon"]["damage"]["sides"] = max(6, int(flow["weapon"]["damage"]["sides"]))
                attack = copy.deepcopy(next(e for e in flow["effects"] if e.get("type") == "attack"))
                attack.update(count=1, granted_attack_root=True)
                flow["effects"] = [attack]
                flow["granted_attack"] = True
                out.append(original.model_copy(update={
                    "source_definition_id": f"action:typed.{info['short']}.flowing_spin#{original.source_definition_id}",
                    "display_name": f"Flowing Spin: {original.display_name}", "economy": EconomyKind.BONUS_ACTION,
                    "costs": (("resource:core.stamina", 1),), "parameters": {**original.parameters, "typed": flow,
                        "bojutsu_flow": True, "bojutsu_weapon": base.source_definition_id}}))
    return out


@hook("candidate_allowed")
def allowed(engine, actor, candidate, action):
    if action is None:
        return None
    typed, params = _typed(action), action.parameters or {}
    if _rows(engine, actor, "flow") and typed.get("source") == PREFIX + "flowing_spin" and not params.get("bojutsu_flow"):
        return False
    if params.get("bojutsu_on_turn") and engine.state.current_actor_id != actor.entity_id:
        return False
    if params.get("bojutsu_barrier_reach") and not _barrier_reach_active(engine, actor):
        return False
    if params.get("bojutsu_flow"):
        if not any(c.condition_id == ATTACKED and c.data.get("stamp") == _stamp(engine) for c in actor.conditions.values()):
            return False
        if any(c.data.get("disables_action") == params["bojutsu_weapon"] for c in actor.conditions.values()):
            return False
    return None


@hook("event")
def record_attack_action(engine, event_type, kwargs):
    if event_type != "ATTACK_ROLLED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    source = engine.events[-1].source_definition_id
    action = engine.action_catalog.get(source)
    if actor is None or not _rows(engine, actor, "flow") or action is None:
        return
    typed = _typed(action)
    if action.economy.value != "ACTION" or engine.state.current_actor_id != actor.entity_id or not _staff(typed):
        return
    engine._remove_condition(actor, ATTACKED, source)
    engine._apply_condition(actor, ATTACKED, source, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"stamp": _stamp(engine), "label": "Staff Attack action made"})


@hook("after_hit")
def sweeping_strike(ctx, target, kind):
    if kind != "weapon" or not target.active or not _staff(ctx.typed):
        return
    from .. import typed_executor
    from .needle import ask, checkpoint_id

    for row in _rows(ctx.engine, ctx.actor, "sweep"):
        if ctx.actor.resources.get("resource:core.stamina", 0) < 1 or any(
                c.condition_id == SWEEP_USED and c.data.get("stamp") == _stamp(ctx.engine) for c in ctx.actor.conditions.values()):
            continue
        choice = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "bojutsu_sweep", target.entity_id), ctx.actor,
                     "choice:needle.bojutsu_sweep", ["Use Sweeping Strike"], allow_decline=True, target_id=target.entity_id,
                     prompt=f"Sweeping Strike: {ctx.action.display_name} hit {target.display_name}; spend 1 Stamina?")
        if not choice:
            return
        ctx.engine._spend_resource(ctx.actor, "resource:core.stamina", 1, row["feature_id"])
        ctx.engine._remove_condition(ctx.actor, SWEEP_USED, row["feature_id"])
        ctx.engine._apply_condition(ctx.actor, SWEEP_USED, row["feature_id"], ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"stamp": _stamp(ctx.engine), "label": "Sweeping Strike used this turn"})
        sub = ctx.on_hit_context(target, action=ctx.action, typed={**ctx.typed, 'numbers': row['numbers']}, damage_cache={})
        typed_executor.run_effects(sub, row["effects"])


@effect("bojutsu_result")
def choose_result(ctx, row):
    from .. import typed_executor
    from .needle import ask, checkpoint_id

    options = row["options"]
    choice = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "bojutsu_result", ctx.target.entity_id), ctx.actor,
                 "choice:needle.bojutsu_result", [r["label"] for r in options], target_id=ctx.target.entity_id,
                 prompt=f"Sweeping Strike: {ctx.action.display_name} hit {ctx.target.display_name}; choose the failed-save result.")
    if choice:
        typed_executor.run_effects(ctx, next(r["effects"] for r in options if r["label"] == choice[0]))


@effect("bojutsu_reposition")
def reposition(ctx, row):
    from ..gate2_runtime_models import Position
    from .rider_movement import forced_route
    from .needle import ask, checkpoint_id, cell_id

    engine, target = ctx.engine, ctx.target
    if target is None or not target.active:
        return
    reach = int(ctx.action.range_ft or 5)
    paths = {}
    occupied = engine._occupied_cells_except(target.entity_id)
    for y in range(engine.grid.height):
        for x in range(engine.grid.width):
            cell = Position(x=x, y=y)
            if cell == target.position or engine._distance_actor_to_cell(ctx.actor, cell) > reach:
                continue
            distance = int(engine.grid.distance_ft(target.position, cell))
            found = engine.grid.shortest_path(target.position, cell, occupied_cells=occupied,
                max_cost_ft=distance, footprint=engine._footprint(target))
            if found is not None:
                paths[cell_id(cell)] = found[0]
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, "bojutsu_reposition", target.entity_id), ctx.actor,
                 "choice:needle.bojutsu_reposition", list(paths), target_id=target.entity_id,
                 labels={key: "Move to " + key.removeprefix("cell:") for key in paths},
                 prompt=f"Sweeping Strike: {ctx.action.display_name} hit {target.display_name}; choose its destination within your reach.")
    if not chosen:
        return
    forced_route(engine, target, paths[chosen[0]], ctx.source, ctx.actor)


def _staff_opportunity(ctx):
    return (_staff(ctx.typed) and getattr(ctx.engine, "_typed_oa_attacker", None) == ctx.actor.entity_id
            and ctx.typed.get("opportunity_of") in {a.source_definition_id for a in _wielded_staff(ctx.engine, ctx.actor)})


@hook("cover")
def barrier_cover(engine, attacker, target):
    """Heavenly Staff Barrier: "You and allies within 10 feet gain Half Cover against ranged weapon attacks and physical
    projectiles" -- the aura moves with the wielder; a ranged weapon attack is read from the attack now resolving."""
    from .attack_scope import current

    frame = current(engine)
    if target is None or frame is None or frame["actor_id"] != attacker.entity_id or frame["target_id"] != target.entity_id:
        return None
    action = engine.action_catalog.get(frame["source"])
    kind = str((frame.get("effect") or {}).get("attack_kind") or "")
    if action is None or not _typed(action).get("weapon") or kind.startswith("cultivation"):
        return None
    for owner in engine.state.actors.values():
        if owner.team_id == target.team_id and _barrier_active(engine, owner) and (
                owner.entity_id == target.entity_id or engine._distance_actor_to_actor(owner, target) <= 10):
            return 2
    return None


@hook("after_hit")
def barrier_opportunity_hit(ctx, target, kind):
    """"A creature hit by your Opportunity Attack has its Speed reduced to 0 for the remainder of the turn"."""
    if target is None or not target.active or not _barrier_active(ctx.engine, ctx.actor) or not _staff_opportunity(ctx):
        return
    from .. import typed_executor

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    typed_executor.run_effects(sub, [{"type": "speed", "applies_to": "target", "becomes": 0, "expires_on": "END_OF_CURRENT_TURN",
                                      "evidence": "Heavenly Staff Barrier: Speed 0 for the rest of the turn"}])
