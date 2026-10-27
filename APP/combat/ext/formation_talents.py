"""Formation talents (Sphere Compendium, Formations).  Built on combat/ext/formations.py, which owns the array itself (its zone, its
Eye, Combat Array, Pulse, Collapse, the six Basic Patterns, Binding, Sealing Gate).  Owner's text first; nothing here is invented.

  Layered Pattern    a second Pattern Layer when you set an array, +2 CP        (setup toggle, then Set Array)
  Line Array         the array is a line (Combat: 30 feet long, 5 feet wide), its Eye at one end       (setup toggle)
  Gate Keeper        creatures keyed to your arrays: chosen when you set one, or a Bonus Action within 120 feet of it
  Reinforced Nodes   Nodes and Eyes have CL more Hit Points; a Reaction and 1 CP leaves one at 1 HP  (formations.last_stand)
  Array Repair       an Action, 60 feet, 1 CP: heal a damaged Node or Eye of yours 2d8/3d8/4d8 + key modifier, or end its disruption
  Disrupt Node       an Action, 60 feet: a Formation Check against the creator's Formation Save DC disrupts a Node or Eye
  Formation Compass  an Action, 60 feet: study an array (Formation Check, with Advantage) and learn one thing about it
  Shifting Gates     a Bonus Action: until your next turn a hostile creature that crosses the array's boundary makes a Dexterity save
  Formation Step     a Bonus Action: teleport to an unoccupied space in the array you started your turn in
  Collapsing Exit    when you collapse your own array, one willing creature inside it moves 10 feet without Opportunity Attacks

The setup toggles are free (no action): each stores what the next Set Array should do in a ``formation_setup`` condition, the way
combat/zones.py's Shape Darkness stores its choice, so the table shows it and hovering it says what it will do.

Shared Formation-family API. The Formation-talents plug-in next door, combat/ext/formation_masters.py, adds its own Domains
and toggles to the same talent rows and builds its rows with this module's public builder, never an underscore-prefixed one:
build_action is the single ActionDefinition builder both plug-ins use, so a talent's cost, duration and owner are written one
way. combat/ext/formations.py owns the array itself and exposes the rest of the family API (see its docstring). A further
family member must use these public names and be recorded here.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from . import formations as F

RELAY = "condition:typed.formation_thread_relay"
RELAY_SOURCE = "tianxia.talent.formations.formation_thread_relay"
FLOW_LINE = 'tianxia.talent.formations.flow_line_strike'


@hook('compile_action')
def relay_permission(action: Any, info: dict[str, Any]) -> Any | None:
    """Bind full Relay permission to new owned Pulses; old catalogs stay inert."""
    typed = action.parameters.get('typed') or {}
    if RELAY_SOURCE not in (info.get('owned_ids') or []) or typed.get('source') != 'formation_pulse':
        return None
    return action.model_copy(update={'parameters': {**action.parameters,
        'typed': {**typed, 'formation_relay_techniques': 1}}})


@hook('compile_action')
def flow_line_data(action: Any, info: dict[str, Any]) -> Any | None:
    """Seal reviewed between-Nodes damage on new owned Killing Line Pulses."""
    if FLOW_LINE not in (info.get('owned_ids') or []) or action.parameters.get('pattern') != 'killing_line':
        return None
    modifier = ((info.get('mechanics') or {}).get(FLOW_LINE, {}).get('modifier') or {})
    if modifier.get('between_nodes_bonus') != 'pb':
        return None
    typed = action.parameters.get('typed') or {}
    return action.model_copy(update={'parameters': {**action.parameters,
        'typed': {**typed, 'formation_between_nodes_bonus': int(info.get('pb') or 0)}}})


@hook('attack_damage')
def between_nodes_damage(ctx: Any, dice: Any) -> Any | None:
    """Flow Line Strike: PB on its real Pulse hit strictly between live Nodes.

    New sealed metadata gates the effect. Declared Flow Line crossings remain
    separate: neither old movement nor arbitrary node links are invented.
    Stored-force releases do not use this native Pulse attack and cannot receive this.
    """
    bonus = ctx.typed.get('formation_between_nodes_bonus')
    from ..gate2_runtime_models import DiceSpec
    if (not bonus or ctx.typed.get('source') != 'formation_pulse' or ctx.action.parameters.get('pattern') != 'killing_line'
            or not isinstance(dice, DiceSpec) or dice.count <= 0 or dice.sides <= 0 or ctx.target is None):
        return None
    zone = ctx.engine.state.zones.get(ctx.damage_cache.get('formation_zone'))
    if zone is None or not zone.active or zone.owner_id != ctx.actor.entity_id:
        return None
    from itertools import combinations
    nodes = [o for o in F.objects_of(ctx.engine, zone) if (o.component or {}).get('role') == 'node'
             and not o.destroyed and not F.disrupted(o)]
    for a, b in combinations(nodes, 2):
        ax, ay, bx, by = a.position.x, a.position.y, b.position.x, b.position.y
        for x, y in ctx.engine._actor_cells(ctx.target):
            if ((x,y) not in ((ax,ay),(bx,by)) and (x-ax)*(by-ay) == (y-ay)*(bx-ax)
                    and min(ax,bx) <= x <= max(ax,bx) and min(ay,by) <= y <= max(ay,by)):
                return dice.model_copy(update={'modifier': dice.modifier + int(bonus)})
    return None


@hook("technique_used")
def thread_relay(ctx: Any) -> None:
    """Offer one keyed ally a single remote Cultivation Attack after a Pulse.

    The grant uses evented conditions and the existing effect_origins geometry
    contract. Newly sealed Pulses also grant one non-Secret sphere technique.
    """
    from ..action_geometry import record_for
    origin = record_for(ctx.engine, ctx.actor, ctx.action.source_definition_id)
    if origin and str(origin.get("id", "")).startswith("relay:"):
        for condition in list(ctx.actor.conditions.values()):
            if condition.condition_id.startswith(RELAY + ".") and str(origin["id"]).startswith("relay:" + condition.instance_id + "|"):
                ctx.engine._remove_condition(ctx.actor, condition.condition_id, ctx.source)
        return
    if ctx.typed.get("source") != "formation_pulse":
        return
    zone = ctx.engine.state.zones.get(ctx.damage_cache.get("formation_zone", ""))
    if zone is None or "formation_thread_relay" not in F.talents_of(F.record(zone).get("numbers")):
        return
    from .needle import CHOICE, ask, checkpoint_id
    allies = sorted((a for a in ctx.engine.state.actors.values()
                     if a.active and a.entity_id != ctx.actor.entity_id and a.team_id == ctx.actor.team_id
                     and F.inside(ctx.engine, a, zone) and F.keyed(ctx.engine, zone, a)), key=lambda a: a.entity_id)
    if not allies:
        return
    techniques = int(bool(ctx.typed.get('formation_relay_techniques')))
    use = 'Cultivation Attack or non-Secret technique' if techniques else 'Cultivation Attack'
    prompt = (f"Formation Thread Relay: after your Pulse, choose a keyed ally inside this array. They may start one {use} at its Eye or a Node until the start of your next turn, at no extra cost for the relay. The attack or technique still uses its normal action and cost. They must still perceive the target; range and targeting are measured from the chosen Eye or Node."
              if techniques else "Formation Thread Relay: choose an ally in this array after your Pulse. Their next chosen Cultivation Attack may start at its Eye or a Node, until your next turn; no extra cost.")
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "FORMATION_RELAY", ctx.actor.entity_id),
                   ctx.actor, CHOICE + "formation_thread_relay", [a.entity_id for a in allies],
                   labels={a.entity_id: f"{a.display_name}: one {use} from an Array Eye or Node" for a in allies},
                   name="Formation Thread Relay", feature_id=RELAY_SOURCE, allow_decline=True,
                   prompt=prompt)
    if selected:
        ally = ctx.engine.state.actors[selected[0]]
        ctx.engine._apply_condition(ally, RELAY + "." + str(ctx.engine.state.event_sequence + 1), RELAY_SOURCE, ctx.actor.entity_id,
                                   expires_on="START_OF_SOURCE_NEXT_TURN",
                                   data={"zone_id": zone.zone_id, **({'techniques': 1} if techniques else {}), "label": f"Formation Thread Relay: one {use} from this array's Eye or Node, "
                                         f"until the start of {ctx.actor.display_name}'s next turn"})

SETUP_COND = f"condition:typed.{F.SETUP}"
EXIT_COND = "condition:typed.formation_exit"
STEP_RANGE_FT = 60
STUDY_RANGE_FT = 60
REPAIR_RANGE_FT = 60
DISRUPT_RANGE_FT = 60
KEY_RANGE_FT = 120
F.REPLACED.update({"array_repair", "disrupt_node", "formation_compass", "formation_step", "shifting_gates", "gate_keeper", "layered_pattern",
                   "line_array"})

COMPASS = {"eye": "find its Eye", "node": "find a Node", "layer": "learn a Pattern Layer", "concentration": "learn whether it needs Concentration",
           "collapse": "learn how it would collapse"}


def build_action(info: dict[str, Any], numbers: dict[str, Any], sid: str, name: str, economy: str, kind: str, range_ft: int | None, effects: list[dict[str, Any]],
            tag: str, *, costs: tuple[Any, ...] = (), extra: dict[str, Any] | None = None) -> Any:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": effects, "numbers": dict(numbers), "duration": {"kind": "instant"}, "riders": [], "source": f"formation_{tag}",
             "sphere": F.SPHERE, "typing_status": "formation_plugin", "coverage": "FULL"}
    return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.formation.{sid}", display_name=name, owner_id=info["actor_id"],
                            economy=EconomyKind[economy], resolution_kind="TYPED", target_kind=kind, range_ft=range_ft, costs=costs,
                            parameters={"typed": typed, "expected_damage": 0, "player_only": True, F.TAG: tag,
                                        **({"setting_only": True} if tag == "setup" and kind == "SELF" else {}), **(extra or {})})


@hook("compile_actions")
def compile_actions(info: dict[str, Any]) -> list[Any] | None:
    if F.BASE_SET not in (info.get("owned_ids") or []) and F.SPHERE not in (info.get("spheres") or []):
        return None
    talents = set(F.owned_talents(info))
    cl = int(info["numbers"].get("cl") or 1)
    pool = F.pool_of(info)
    numbers = {**info["numbers"], "formation_talents": sorted(talents), "formation_pool": pool}
    out: list[Any] = []
    toggles = False
    if "layered_pattern" in talents and cl >= 5:
        toggles = True
        for pattern in F.known_patterns(info):
            for damage_type in (F.killing_types(info) if pattern == "killing_line" else (None,)):
                label = F.PATTERNS[pattern]["name"] + (f" ({damage_type.title()})" if damage_type else "")
                out.append(build_action(info, numbers, f"setup.layer.{pattern}" + (f".{damage_type}" if damage_type else ""), f"Next array: second layer, {label}",
                                   "NONE", "SELF", None, [{"type": "formation_setup", "op": "layer", "pattern": pattern, "damage_type": damage_type,
                                                          "evidence": "Layered Pattern: add a second Pattern Layer you know when you set an array; +2 CP"}], "setup",
                                   extra={"description": f"Add {label} as a second layer of your next array for 2 extra CP; each Pulse uses one layer unless another feature allows more."}))
    if "line_array" in talents:
        toggles = True
        out.append(build_action(info, numbers, "setup.line", "Next array: shape it as a line", "NONE", "SELF", None,
                           [{"type": "formation_setup", "op": "line", "evidence": "Line Array: shape the array as a line instead of a circle"}], "setup"))
    if "gate_keeper" in talents:
        toggles = True
        out.append(build_action(info, numbers, "setup.key", "Next array: key a creature", "NONE", "HOSTILE_ENTITY", None,
                           [{"type": "formation_setup", "op": "key", "evidence": "Gate Keeper: when you set an array, choose creatures you can see; they are keyed to it"}], "setup"))
        for op, words in (("add", "Key a creature to your arrays"), ("remove", "Unkey a creature from your arrays")):
            out.append(build_action(info, numbers, f"keying.{op}", f"Gate Keeper: {words}", "BONUS_ACTION", "HOSTILE_ENTITY", KEY_RANGE_FT,
                               [{"type": "formation_keying", "op": op, "evidence": "Gate Keeper: as a Bonus Action within 120 feet of the array, add or remove one creature you can see from the keyed list"}],
                               "keying", extra={"op": op}))
    if toggles or talents & {"court_of_the_ninefold_array", "sovereign_of_the_world_diagram", "elemental_killing_array"}:
        out.append(build_action(info, numbers, "setup.clear", "Next array: clear my choices", "NONE", "SELF", None,
                           [{"type": "formation_setup", "op": "clear", "evidence": "the choices made for the next array are dropped"}], "setup"))
    if "array_repair" in talents and cl >= 5:
        for mode, words in (("restore", "restore Hit Points"), ("undisrupt", "end a disruption")):
            out.append(build_action(info, numbers, f"repair.{mode}", f"Array Repair: {words}", "ACTION", "ALLY_OR_SELF", REPAIR_RANGE_FT, [], "repair",
                               costs=((pool, 1),), extra={"mode": mode}))
    if "disrupt_node" in talents:
        out.append(build_action(info, numbers, "disrupt", "Disrupt Node", "ACTION", "HOSTILE_ENTITY", DISRUPT_RANGE_FT, [], "disrupt"))
    if "formation_compass" in talents:
        for fact, words in COMPASS.items():
            out.append(build_action(info, numbers, f"compass.{fact}", f"Formation Compass: {words}", "ACTION", "CELL", STUDY_RANGE_FT,
                               [{"type": "formation_compass", "fact": fact, "evidence": "Formation Compass: study one array within 60 feet; a Formation Check against the creator's Formation Save DC"}],
                               "compass", extra={"any_cell": True, "fact": fact}))
    if "shifting_gates" in talents:
        out.append(build_action(info, numbers, "shifting", "Shifting Gates", "BONUS_ACTION", "CELL", F.PULSE_RANGE_FT,
                           [{"type": "formation_shifting", "evidence": "Shifting Gates: one of your arrays within 120 feet, until the start of your next turn"}],
                           "shifting", extra={"any_cell": True}))
    if ("formation_step" in talents and cl >= 5) or ("court_of_the_ninefold_array" in talents and cl >= 12):  # (the Court: "you may use Formation Step inside without the talent")
        out.append(build_action(info, numbers, "step", "Formation Step", "BONUS_ACTION", "CELL", STEP_RANGE_FT,
                           [{"type": "formation_step", "evidence": "Formation Step: teleport to an unoccupied space inside the same array"}], "step", extra={"any_cell": True}))
    return out or None


# ------------------------------------------------------------------------------------------------ legality
def _mine(engine: Any, actor: Any, obj: Any) -> bool:
    return obj is not None and (obj.component or {}).get(F.KEY) is not None and obj.owner_id == actor.entity_id and not obj.destroyed


def _hers(engine: Any, actor: Any, aim: Any, within: int, *, any_owner: bool = False) -> Any:
    """The array (the actor's, or anyone's) whose squares hold this one, within reach of the actor."""
    for zone in F.arrays(engine, None if any_owner else actor.entity_id):
        if (aim.x, aim.y) in F.cells_of(zone) and engine._distance_actor_to_cell(actor, zone.center) <= within:
            return zone
    return None


@hook("candidate_allowed")
def candidate_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    tag = (action.parameters or {}).get(F.TAG)
    if tag in ("repair", "disrupt"):  # only ever a Node or Eye
        return None if (candidate.metadata or {}).get("object_target") else False
    if tag == "compass":
        return None if candidate.destination is not None and _hers(engine, actor, candidate.destination, STUDY_RANGE_FT, any_owner=True) is not None else False
    if tag == "shifting":
        zone = _hers(engine, actor, candidate.destination, F.PULSE_RANGE_FT) if candidate.destination is not None else None
        return None if zone is not None and not F.record(zone).get("shifting") else False
    if tag == "keying":
        victim = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
        near = [zone for zone in F.arrays(engine, actor.entity_id) if engine._distance_actor_to_cell(actor, zone.center) <= KEY_RANGE_FT]
        if victim is None or not near:
            return False
        listed = any(victim.entity_id in (F.record(zone).get("keyed") or []) for zone in near)
        return None if listed == (action.parameters.get("op") == "remove") else False
    if tag == "step":
        return None if step_zone(engine, actor, candidate.destination) is not None else False
    if tag == "setup" and (action.parameters.get("typed") or {}).get("effects", [{}])[0].get("op") == "key":
        victim = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
        return None if victim is not None and victim.entity_id not in (F.setup_of(actor).get("keyed") or []) else False
    return None


@hook("object_targets")
def object_targets(engine: Any, actor: Any, action: Any) -> list[str] | None:
    tag = (action.parameters or {}).get(F.TAG)
    if tag == "repair":
        want_disrupted = action.parameters.get("mode") == "undisrupt"
        out = []
        for zone in F.arrays(engine, actor.entity_id):
            for obj in F.objects_of(engine, zone):
                if _mine(engine, actor, obj) and (F.disrupted(obj) if want_disrupted else int(obj.current_hp or 0) < int(obj.maximum_hp or 0)):
                    out.append(obj.object_id)
        return out or None
    if tag == "disrupt":
        out = []
        for zone in F.arrays(engine):
            owner = engine.state.actors.get(zone.owner_id)
            if owner is not None and owner.team_id != actor.team_id:
                out.extend(obj.object_id for obj in F.objects_of(engine, zone) if not obj.destroyed and not F.disrupted(obj))
        return out or None
    return None


# ------------------------------------------------------------------------------------------------ Array Repair, Disrupt Node
@hook("object_action")
def object_action(engine: Any, actor: Any, action: Any, obj: Any, candidate: Any, intent: Any) -> bool | None:
    tag = (action.parameters or {}).get(F.TAG)
    if tag not in ("repair", "disrupt") or not (obj.component or {}).get(F.KEY):
        return None
    numbers = (action.parameters.get("typed") or {}).get("numbers") or {}
    label = F.part_name(engine, obj)
    if tag == "repair":
        if action.parameters.get("mode") == "undisrupt":
            engine._update_object(obj.model_copy(update={"component": {**obj.component, "disrupted_by": None}}), action.source_definition_id, actor.entity_id)
            F.say(engine, action.source_definition_id, actor.entity_id, f"Array Repair: {label} is no longer disrupted.")
            return True
        from ..gate2_runtime_models import DiceSpec

        cl = int(numbers.get("cl") or 1)
        count = 4 if cl >= 17 else 3 if cl >= 11 else 2  # "2d8 + your Formation key ability modifier; 3d8 at CL 11, 4d8 at CL 17"
        roll = engine.roller.roll(DiceSpec(count=count, sides=8, modifier=int(numbers.get("key_mod") or 0)), actor_id=actor.entity_id,
                                  reason=f"HEALING:{action.source_definition_id}:{obj.object_id}")
        engine._record_roll(roll)
        healed = min(int(obj.maximum_hp or 0) - int(obj.current_hp or 0), max(0, int(roll.total)))
        engine._update_object(obj.model_copy(update={"current_hp": int(obj.current_hp or 0) + healed}), action.source_definition_id, actor.entity_id)
        F.say(engine, action.source_definition_id, actor.entity_id, f"Array Repair: {label} regains {healed} HP ({int(obj.current_hp or 0) + healed} of {obj.maximum_hp}).")
        return True
    zone = engine.state.zones.get(obj.component[F.KEY])
    dc = int((F.record(zone).get("numbers") or {}).get("save_dc") or 10) if zone is not None else 10
    if not F.formation_check(engine, actor, numbers, dc, action.source_definition_id, f"disrupt {label}"):
        F.say(engine, action.source_definition_id, actor.entity_id, f"Disrupt Node: {label} holds (DC {dc}).")
        return True
    engine._update_object(obj.model_copy(update={"component": {**obj.component, "disrupted_by": actor.entity_id}}), action.source_definition_id, actor.entity_id)
    F.say(engine, action.source_definition_id, actor.entity_id, f"Disrupt Node: {label} is disrupted until the start of {actor.display_name}'s next turn.")
    if zone is not None and zone.active:
        record = F.record(zone)
        eye = engine.state.objects.get(record.get("eye") or "")
        nodes = [engine.state.objects.get(oid) for oid in record.get("nodes") or []]
        off = sum(1 for node in nodes if node is None or node.destroyed or F.disrupted(node))
        enough = int(record.get("collapse_at") or -(-2 * len(nodes) // 3)) if nodes else 0
        from . import formation_masters

        if F.disrupted(eye) and formation_masters.hold(engine, zone, action.source_definition_id):
            F.say(engine, action.source_definition_id, actor.entity_id, "The array holds for now (the Eye of the Formation Master).")
        elif F.disrupted(eye) or (nodes and off >= enough):
            # "If this disruption would leave the array without enough Nodes or without a functioning Eye, the array becomes unstable."
            F.save_zone(engine, zone, action.source_definition_id, {**record, "unstable": {"dc": int(numbers.get("save_dc") or 10), "by": actor.entity_id}})
            F.say(engine, action.source_definition_id, actor.entity_id, "The array is unstable: at the start of its creator's next turn the creator must pass a Formation Check "
                                                                       f"(DC {int(numbers.get('save_dc') or 10)}) or it collapses.")
    return True


# ------------------------------------------------------------------------------------------------ setup toggles, keying
@hook("button_selection")
def setup_selection(parameters: dict[str, Any]) -> dict[str, Any] | None:
    pick = next((eff for eff in (parameters.get("typed") or {}).get("effects") or [] if eff.get("type") == "formation_setup"), {})
    op = pick.get("op")
    if op == "domain_layer":
        return {"condition": SETUP_COND, "contains": {"domain_layers": [pick.get("pattern"), pick.get("damage_type")]}}
    equals = {"layer": {"layer": pick.get("pattern"), "layer_type": pick.get("damage_type")},
              "element": {"element": pick.get("element")}, "line": {"line": True}}.get(op)
    return {"condition": SETUP_COND, "equals": equals} if equals else None


@effect("formation_setup")
def formation_setup(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    data = dict(F.setup_of(actor))
    op = str(eff.get("op"))
    if op == "clear":
        data, said = {}, "Your choices for the next array are cleared."
    elif op == "layer":
        data["layer"], data["layer_type"] = eff.get("pattern"), eff.get("damage_type")
        said = f"Your next array gets a second layer: {F.PATTERNS[str(eff.get('pattern'))]['name']} (+2 CP)."
    elif op == "domain_layer":  # Court of the Ninefold Array (two layers), Sovereign of the World-Diagram (three): the layers of the next Domain
        picked = [row for row in data.get("domain_layers") or [] if row[0] != eff.get("pattern")]
        data["domain_layers"] = [*picked, [eff.get("pattern"), eff.get("damage_type")]][-3:]
        said = "Your next Domain gets the layers: " + ", ".join(F.PATTERNS[str(row[0])]["name"] for row in data["domain_layers"]) + "."
    elif op == "element":  # Elemental Killing Array
        data["element"] = eff.get("element")
        said = f"Your next Killing Line gets the {str(eff.get('element')).title()} rider."
    elif op == "line":
        data["line"] = not data.get("line")
        said = "Your next array will be a line." if data["line"] else "Your next array will be a circle."
    else:
        victim = ctx.target or (ctx.targets[0] if ctx.targets else None)
        if victim is None:
            return
        data["keyed"] = sorted({*(data.get("keyed") or []), victim.entity_id})
        said = f"{victim.display_name} will be keyed to your next array."
    if F.has_condition(actor, F.SETUP) is not None:
        engine._remove_condition(actor, SETUP_COND, ctx.source)
    if data:
        data["reading"] = "; ".join(part for part in (
            f"second layer: {F.PATTERNS[data['layer']]['name']}" if data.get("layer") else "", "a line" if data.get("line") else "",
            "Domain layers: " + ", ".join(F.PATTERNS[str(row[0])]["name"] for row in data["domain_layers"]) if data.get("domain_layers") else "",
            f"{str(data['element']).title()} rider" if data.get("element") else "",
            f"{len(data.get('keyed') or [])} keyed" if data.get("keyed") else "") if part)
        engine._apply_condition(actor, SETUP_COND, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED", data=data)
    ctx.rider(said)


@effect("formation_keying")
def formation_keying(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    victim = ctx.target or (ctx.targets[0] if ctx.targets else None)
    if victim is None:
        return
    add = str(eff.get("op")) == "add"
    done = 0
    for zone in F.arrays(engine, actor.entity_id):
        if engine._distance_actor_to_cell(actor, zone.center) > KEY_RANGE_FT:
            continue
        listed = list(F.record(zone).get("keyed") or [])
        listed = sorted({*listed, victim.entity_id}) if add else [key for key in listed if key != victim.entity_id]
        F.save_zone(engine, zone, ctx.source, {**F.record(zone), "keyed": listed})
        done += 1
    from .. import zones

    zones.sync_inside(engine, ctx.source)
    ctx.rider(f"{victim.display_name} is {'keyed to' if add else 'no longer keyed to'} your {done} array{'s' if done != 1 else ''} within 120 feet.")


# ------------------------------------------------------------------------------------------------ Formation Compass
@effect("formation_compass")
def formation_compass(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    aim = getattr(ctx.intent, "destination", None)
    zone = _hers(engine, actor, aim, STUDY_RANGE_FT, any_owner=True) if aim is not None else None
    if zone is None:
        ctx.rider("No array there to study.")
        return
    record = F.record(zone)
    dc = int((record.get("numbers") or {}).get("save_dc") or 10)
    # "You gain Advantage on checks made to identify a formation, locate its Array Eye, locate its Nodes, or understand its trigger."
    if not F.formation_check(engine, actor, ctx.numbers, dc, ctx.source, "study the array", mode="ADVANTAGE"):
        ctx.rider(f"Formation Compass: the array at ({zone.center.x},{zone.center.y}) keeps its secrets (DC {dc}).")
        return
    fact, seen = str(eff.get("fact")), dict(record.get("studied") or {})
    known = list(seen.get(actor.entity_id) or [])
    if fact == "eye":
        said = f"its Eye is at ({zone.center.x},{zone.center.y})"
    elif fact == "node":
        nodes = [engine.state.objects.get(oid) for oid in record.get("nodes") or []]
        fresh = [node for node in nodes if node is not None and not node.destroyed and node.object_id not in known]
        said = f"a Node is at ({fresh[0].position.x},{fresh[0].position.y})" if fresh else "it has no Node you have not already found"
        known += [fresh[0].object_id] if fresh else []
    elif fact == "layer":
        fresh = [layer for layer in record.get("layers") or [] if layer not in known]
        said = f"it holds a {F.PATTERNS[fresh[0]]['name']} layer" if fresh else "it has no layer you have not already learned"
        known += [fresh[0]] if fresh else []
    elif fact == "concentration":
        said = "it needs its creator's Concentration" if record.get("mode") == "combat" else "it needs no Concentration"
    else:
        parts = ["its Eye being destroyed"]
        if record.get("mode") == "combat":
            parts.append("its creator losing Concentration")
        if record.get("nodes"):
            parts.append(f"{int(record.get('collapse_at') or -(-2 * len(record['nodes']) // 3))} of its Nodes being destroyed")
        parts.append("its creator setting more arrays than their Formation Load")
        said = f"it would collapse on {parts[len(known) % len(parts)]}"
        known.append(parts[len(known) % len(parts)])
    F.save_zone(engine, zone, ctx.source, {**record, "studied": {**seen, actor.entity_id: known}})
    ctx.rider(f"Formation Compass: you learn that {said}.")


# ------------------------------------------------------------------------------------------------ Shifting Gates
@effect("formation_shifting")
def formation_shifting(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    aim = getattr(ctx.intent, "destination", None)
    zone = _hers(engine, actor, aim, F.PULSE_RANGE_FT) if aim is not None else None
    if zone is None:
        ctx.rider("No array of yours there.")
        return
    profile = dict(zone.trigger_profile)
    profile["triggers"] = [*(profile.get("triggers") or []), {"id": "formation:shifting_gates", "name": "Shifting Gates", "on": ["enter"], "who": "hostile",
                                                              "effects": [{"type": "formation_shift", "evidence": "Shifting Gates: a hostile creature that crosses the boundary makes a Dexterity saving throw"}]}]
    zone.trigger_profile = profile
    F.save_zone(engine, zone, ctx.source, {**F.record(zone), "shifting": True})
    ctx.rider(f"The gates of the array at ({zone.center.x},{zone.center.y}) shift until the start of your next turn: keyed creatures cross freely; "
              "a hostile creature crossing the boundary makes a Dexterity save.")


@effect("formation_shift")
def formation_shift(ctx: Any, eff: dict[str, Any]) -> None:
    """Shifting Gates: "a hostile creature crossing the boundary makes a Dexterity saving throw. Failed Save: its movement ends at the
    boundary. Successful Save: its Speed is reduced by 10 feet until the start of its next turn"."""
    from ..typed_executor import run_effects

    engine, creature, owner = ctx.engine, ctx.target, ctx.actor
    zone = next((zone for zone in F.arrays(engine, owner.entity_id) if F.record(zone).get("shifting") and F.inside(engine, creature, zone)), None)
    if zone is None or creature is None:
        return
    dc = int((F.record(zone).get("numbers") or {}).get("save_dc") or 10)
    roll = engine._roll_save(creature, "DEX", dc, "formation:shifting_gates")
    if roll is not None and int(roll.total) >= dc:
        run_effects(ctx, [{"type": "speed", "amount": -10, "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN",
                           "evidence": "Successful Save: its Speed is reduced by 10 feet until the start of its next turn"}])
        return
    creature.movement_remaining_ft = 0
    F.say(engine, "formation:shifting_gates", owner.entity_id, f"Shifting Gates: {creature.display_name}'s movement ends at the array's boundary.")


@hook("turn_start")
def gates_settle(engine: Any, actor: Any) -> None:
    """Shifting Gates lasts "until the start of your next turn"."""
    for zone in F.arrays(engine, actor.entity_id):
        if F.record(zone).get("shifting"):
            zone.trigger_profile = {**zone.trigger_profile, "triggers": [row for row in zone.trigger_profile.get("triggers") or [] if row.get("id") != "formation:shifting_gates"]}
            F.save_zone(engine, zone, "formation:shifting_gates", {**F.record(zone), "shifting": False})


# ------------------------------------------------------------------------------------------------ Formation Step
def step_zone(engine: Any, actor: Any, destination: Any) -> Any:
    """The array Formation Step would move the actor within: an owned or allied keyed array that it started its turn inside, holding the destination,
    with the square free.  Once until the start of its next turn."""
    if destination is None or actor.turn_flags.get("formation_step_used"):
        return None
    if not engine.grid.placement_legal(destination, footprint=engine._footprint(actor), occupied_cells=engine._occupied_cells_except(actor.entity_id)):
        return None
    began = actor.turn_flags.get("formation_step_zones") or []
    for zone in F.arrays(engine):
        if not (zone.owner_id == actor.entity_id or (F.keyed(engine, zone, actor) and engine.state.actors[zone.owner_id].team_id == actor.team_id)):
            continue
        if "formation_step" not in F.talents_of(F.record(zone).get("numbers")) and (F.record(zone).get("domain") != "sovereign" and not (F.record(zone).get("domain") == "court" and zone.owner_id == actor.entity_id)):
            continue  # (the talent, or inside a Court of the Ninefold Array)
        if zone.zone_id in began and (destination.x, destination.y) in F.cells_of(zone) and F.inside(engine, actor, zone):
            return zone
    return None


@hook("turn_start")
def began_inside(engine: Any, actor: Any) -> None:
    actor.turn_flags["formation_step_zones"] = [zone.zone_id for zone in F.arrays(engine)
        if F.inside(engine, actor, zone) and (zone.owner_id == actor.entity_id or F.keyed(engine, zone, actor))]


SHARED_STEP = "system:formation.keyed_step"


@hook("match_start")
def install_keyed_step(engine: Any) -> None:
    """One shared catalog definition; live array ownership supplies eligibility."""
    if not any(action.parameters.get(F.TAG) in ("step", "domain") for action in engine.action_catalog.values()):
        return
    action = build_action({"short": "shared", "actor_id": "*"}, {}, "keyed_step", "Formation Step (Bonus Action)",
        "BONUS_ACTION", "CELL", (engine.grid.width + engine.grid.height) * engine.grid.square_size_ft,
        [{"type": "formation_step", "evidence": "A keyed ally starting inside the same array may teleport within it as a Bonus Action"}],
        "step", extra={"any_cell": True, "player_only": False, "ai_empty_area_filter": False})
    engine.action_catalog[SHARED_STEP] = action.model_copy(update={"source_definition_id": SHARED_STEP})


@hook("additional_actions")
def offer_keyed_step(engine: Any, actor: Any) -> list[str]:
    if SHARED_STEP not in engine.action_catalog or actor.turn_flags.get("formation_step_used"):
        return []
    # Keep the owner's existing row, but grant the missing row to allies and
    # the Sovereign Eye. The native candidate gate rechecks the landing space.
    if any(engine.action_catalog.get(sid) is not None and engine.action_catalog[sid].parameters.get(F.TAG) == "step"
           for sid in actor.action_ids):
        return []
    began = actor.turn_flags.get("formation_step_zones") or []
    for zone in F.arrays(engine):
        owner = engine.state.actors.get(zone.owner_id)
        profile = F.record(zone)
        if (owner is not None and owner.team_id == actor.team_id and F.keyed(engine, zone, actor)
                and zone.zone_id in began and F.inside(engine, actor, zone)
                and ("formation_step" in F.talents_of(profile.get("numbers")) or profile.get("domain") == "sovereign")):
            return [SHARED_STEP]
    return []


@effect("formation_step")
def formation_step(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import _teleport

    actor, aim = ctx.actor, getattr(ctx.intent, "destination", None)
    if F.has_condition(actor, "cannot_teleport") is not None:
        ctx.rider("Something blocks teleportation: the step fails.")
        return
    if step_zone(ctx.engine, actor, aim) is None:
        raise ValueError("Formation Step requires a free space inside the array where your turn began.")
    actor.turn_flags["formation_step_used"] = True
    _teleport(ctx, aim)


# ------------------------------------------------------------------------------------------------ Collapsing Exit
def after_collapse(ctx: Any, zone: Any) -> None:
    """Collapsing Exit: "When you collapse one of your own arrays, choose one willing creature inside it. That creature may immediately
    move up to 10 feet without provoking Opportunity Attacks. If the creature ends this movement outside the array's former area, it
    also gains Temporary HP equal to your Proficiency Bonus."  The creature is you if you stand inside, else an ally there."""
    engine, actor = ctx.engine, ctx.actor
    if "collapsing_exit" not in F.talents_of(ctx.numbers):
        return
    chosen = actor if F.inside(engine, actor, zone) else next(
        (other for other in engine.state.actors.values() if other.active and other.team_id == actor.team_id and F.inside(engine, other, zone)), None)
    if chosen is None:
        return
    pb = int(ctx.numbers.get("pb") or 0)
    engine._apply_condition(chosen, EXIT_COND, ctx.source, actor.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                            data={"cells": sorted(F.cells_of(zone)), "pb": pb})
    if chosen.entity_id == actor.entity_id:
        grant_step(engine, chosen, ctx.source)
        ctx.rider(f"Collapsing Exit: you may move up to 10 feet without Opportunity Attacks; ending outside the former area gives you {pb} Temporary HP.")
    else:
        engine._apply_condition(chosen, "condition:typed.formation_free_step", ctx.source, actor.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN")
        ctx.rider(f"Collapsing Exit: {chosen.display_name} may move up to 10 feet without Opportunity Attacks on its next turn; ending outside gives {pb} Temporary HP.")


def grant_step(engine: Any, creature: Any, source: str) -> None:
    creature.movement_remaining_ft += 10
    creature.turn_flags["oa_free_ft"] = int(creature.turn_flags.get("oa_free_ft") or 0) + 10
    engine._append_event("MOVEMENT_GRANTED", source, actor_id=creature.entity_id, payload={"distance_ft": 10})


def exit_landed(engine: Any, kwargs: dict[str, Any]) -> None:
    """The move a Collapsing Exit granted has been made: outside the former area, Temporary HP equal to the array owner's Proficiency Bonus."""
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    iid = F.has_condition(mover, "formation_exit") if mover is not None else None
    if iid is None or not (kwargs.get("payload") or {}).get("path"):
        return
    row = mover.conditions[iid]
    cells = {tuple(cell) for cell in (row.data or {}).get("cells") or []}
    engine._remove_condition(mover, EXIT_COND, "formation:collapsing_exit")
    if (mover.position.x, mover.position.y) not in cells:
        engine._grant_temp_hp(mover, int((row.data or {}).get("pb") or 0), "formation:collapsing_exit", row.source_actor_id)
        F.say(engine, "formation:collapsing_exit", row.source_actor_id, f"Collapsing Exit: {mover.display_name} ends outside the former array and gains {(row.data or {}).get('pb')} Temporary HP.")


@hook("event")
def on_event(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "MOVEMENT_COMMITTED":
        exit_landed(engine, kwargs)
