"""The Illusion sphere's figments and False Premises (owner 2026-09-29: "i want everything we can automated"): a figment is an image on the
map that nobody is bound to believe; a False Premise is what it puts in a creature's head.  Owner rules:
LocalSources/04_spheres_talents/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md ("Illusion": Using Illusions in Play, Core Illusion Rules --
False Premises, Figments, Concentration --, Base Sphere Abilities: Create Figment, Plant False Premise, Misdirection Responses; and the talents
Control Figment, Selective Premise, Potent Phantasm, Greater Illusion, Veiled Illusion) and authority/typed_mechanics/rules_text.json
(TAL_ILLUSION_*).  Where the text is silent a default is named below; Spheres 5e and D&D 5.5e were not needed.

What a figment is: "an external illusion that creates the appearance, sound, scent, touch, taste, aura, or apparent presence of something
that is not actually there ... does not have mass, Hit Points, AC ... cannot attack, hold a door, carry a creature, block a corridor ... or
provide real Cover".  Here it is a placement (combat/ext/placed.py): a typed zone, tag "figment", the squares of its cube, drawn on the table
with a hover text; it never blocks movement, sight or attacks.

AUTO41 (2026-10-05) extends the same placement implementation: Minor Illusion
uses a 5-foot, 100-round image without Concentration and Bonus Action 5-foot
movement/detail changes; Selective Premise asks for perceived recipients and
separate recognition/immunity choices at creation. Study is a normal Action
against one visible placement using Intelligence (Investigation). Recognition,
successful Study and chosen immunity are distinct per-image creature lists.
Potent Phantasm continues after recognition, with Advantage after successful
Study, and its conditions end at the affected creature's next turn start.
False Premise is a mark, associated with the image when exactly one qualifies.
Only matching recognition clears that mark; ambiguous image provenance and
acting-as-real trigger timing remain report blockers. Existing figment control,
concentration, setup payments and response implementations are retained.

Shared figment_actions API used by illusion_riders to build figment actions with the same ownership and placement contract. Figment in turn queries illusion_riders response_limit and senses_free; neither module accesses the other's private state.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, placed

SPHERE = "tianxia.sphere.illusion"
SETUP = "condition:typed.figment_setup"
CREATE = "TAL_ILLUSION_CREATE_FIGMENT"
CONTROL = "TAL_ILLUSION_CONTROL_FIGMENT"
SELECTIVE = "TAL_ILLUSION_SELECTIVE_PREMISE"
POTENT = "TAL_ILLUSION_POTENT_PHANTASM"
GREATER = "TAL_ILLUSION_GREATER_ILLUSION"
VEILED = "TAL_ILLUSION_VEILED_ILLUSION"
MINOR = "TAL_ILLUSION_MINOR_ILLUSION"
PERMANENT = "tianxia.talent.illusion.permanent_illusion"
STUDY = "system:combat.study_figment"
MINOR_DETAILS = {"image": "a Small image", "sound": "a brief repeating sound", "smell": "a smell",
                 "temperature": "apparent temperature", "texture": "a simple texture",
                 "aura": "a superficial spiritual impression", "pair": "two details of one small scene"}
PREMISE = "False Premise"

RANGE_FT = 60  # Create Figment, Control Figment and Plant False Premise: "Range: 60 feet"
ROUNDS = 100  # "Concentration, up to 10 minutes"
SIZE_ROWS = [(1, 4, 10), (5, 10, 15), (11, 16, 20), (17, 99, 25)]  # "Maximum Figment Size" by CL
LARGER_ROWS = [(1, 4, 20), (5, 10, 30), (11, 16, 40), (17, 99, 50)]  # "Increase the figment's maximum area by one step"
PSYCHIC_DICE = [(1, 10, 1), (11, 16, 2), (17, 99, 3)]  # "1d4 at CL 5, 2d4 at CL 11, and 3d4 at CL 17" (d4s below CL 5: one)
PHANTASM = {"deaf": (1, "Deafened", None), "psychic": (2, "Psychic damage", GREATER), "poison": (2, "Poisoned", GREATER),
            "fear": (2, "Frightened", VEILED), "blind": (3, "Blinded", None)}
CONDITIONS = {"deaf": "deafened", "poison": "poisoned", "fear": "frightened", "blind": "blinded"}
RESPONSES = {"opening": "False Opening", "angle": "Wrong Angle", "timing": "Lost Timing", "step": "Stolen Step"}
TOGGLES = {"senses": ("sight and sound (1 CP)", 1), "larger": ("larger cube (1 CP)", 1), "free": ("no Concentration (2 CP)", 2)}


# ------------------------------------------------------------------------------------------------ the kit an illusionist owns
def _kit(engine: Any, owner: Any) -> dict[str, Any] | None:
    for action in engine.action_catalog.values():
        params = action.parameters or {}
        if action.owner_id == owner.entity_id and params.get("figment_kit"):
            typed = params.get("typed") or {}
            return {"action": action, "owned": set(params.get("figment_owned") or ()), "numbers": typed.get("numbers") or {},
                    "pool": params.get("figment_pool") or "resource:core.qi", "source": action.source_definition_id,
                    "control": params.get("figment_control")}
    return None


def _config(owner: Any) -> dict[str, Any]:
    for condition in owner.conditions.values():
        if condition.condition_id == SETUP:
            return dict(condition.data or {})
    return {}


def _cl(kit: dict[str, Any]) -> int:
    return int(kit["numbers"].get("cl") or 1)


def _phantasm(kit: dict[str, Any], config: dict[str, Any]) -> str | None:
    """The chosen Potent Phantasm option, when the talent (and the talent an option asks for) is owned."""
    choice = config.get("phantasm")
    if choice not in PHANTASM or POTENT not in kit["owned"]:
        return None
    need = PHANTASM[choice][2]
    return choice if need is None or need in kit["owned"] else None


def _cost(kit: dict[str, Any], config: dict[str, Any], free_senses: bool = False) -> int:
    total = sum(price for key, (_label, price) in TOGGLES.items() if config.get(key) and not (key == "senses" and free_senses))
    choice = _phantasm(kit, config)
    return total + (PHANTASM[choice][0] if choice else 0) + (8 if config.get("permanent") and PERMANENT in kit["owned"] else 0)


def creation_costs(engine: Any, actor: Any, action: Any) -> tuple[tuple[str, int], ...]:
    """Quote the payments for Create Figment and its linked variants.

    Native action costs use the engine's public cost modifiers; selected options
    retain their separate payment and Court's free sight/sound rule. Used by
    figment candidate filtering, including Substantial Phantasm.
    """
    from .illusion_riders import senses_free

    costs = tuple(engine.effective_costs(actor, action.source_definition_id, action.costs))
    kit = _kit(engine, actor)
    if kit is None:
        return costs
    return costs + ((kit["pool"], _cost(kit, _config(actor), senses_free(engine, actor))),)


def _size(kit: dict[str, Any], config: dict[str, Any]) -> int:
    return placed.cl_row(_cl(kit), LARGER_ROWS if config.get("larger") else SIZE_ROWS)


def creation_cells(engine: Any, owner: Any, cell: Any) -> list[Any]:
    """Public, pure footprint preview for a figment's current creation options."""
    from ..gate2_runtime_models import Position
    kit = _kit(engine, owner)
    return [Position(x=x, y=y) for x, y in _cube(engine, cell, _size(kit, _config(owner)))] if kit else []


def _cube(engine: Any, cell: Any, size_ft: int) -> list[tuple[int, int]]:
    """The squares of a cube of ``size_ft`` centred on the square (near-top-left of the four for an even cube), inside the map."""
    side = max(1, size_ft // 5)
    x0, y0 = cell.x - (side - 1) // 2, cell.y - (side - 1) // 2
    cells = [(x, y) for x in range(x0, x0 + side) for y in range(y0, y0 + side) if engine.grid.in_bounds((x, y))]
    return [(cell.x, cell.y)] + [c for c in cells if c != (cell.x, cell.y)]  # the chosen square first: it is the zone's centre


def _figments(engine: Any, actor: Any, who: str = "controller") -> list[Any]:
    """The active figments an actor controls (``who`` "controller") or made or controls (``who`` "either"), oldest first."""
    out = []
    for zone in placed.of(engine, "figment"):
        d = placed.data(zone)
        mine = d.get("controller") == actor.entity_id or (who == "either" and d.get("creator") == actor.entity_id)
        if mine:
            out.append(zone)
    return out


def _distance_to(engine: Any, actor: Any, zone: Any) -> int:
    return min(engine.grid.distance_ft(actor.position, cell) for cell in zone.affected_cells)


def _nearest(engine: Any, zones: list[Any], cell: Any) -> Any | None:
    """The figment covering the square, else the one nearest it (creation order breaks a tie)."""
    if not zones:
        return None
    return min(zones, key=lambda zone: (min(engine.grid.distance_ft(cell, c) for c in zone.affected_cells), int(zone.zone_id.rsplit(":", 1)[-1])))


def _recognizes(zone: Any, creature: Any) -> bool:
    d = placed.data(zone)
    return creature.entity_id == d.get("creator") or creature.entity_id in (d.get("recognized") or ())


def _sees_figment(engine: Any, owner: Any, target: Any) -> bool:
    """A creature "that can perceive the figment" and has not recognized it: one of the owner's figments in its line of sight."""
    return any(not placed.data(zone).get("minor") and not _recognizes(zone, target) and any(engine._line_of_sight_actor_to_cell(target, cell) for cell in (zone.center,))
               for zone in _figments(engine, owner, "either"))


def _hostile(owner: Any, other: Any) -> bool:
    return other.active and other.team_id != owner.team_id


def _log(engine: Any, source: str, owner: Any, text: str, targets: Any = ()) -> None:
    placed.note(engine, source, owner, text, targets=targets)


def _name(owner: Any, size: int, d: dict[str, Any]) -> str:
    if d.get("minor"):
        return f"{owner.display_name}'s Minor Illusion ({MINOR_DETAILS.get(d.get('detail'), 'one detail')}; 5-foot cube; no substance or cover)"
    bits = [f"{size}-foot cube", "sight and sound" if d.get("senses") else "sight or sound"]
    if d.get("phantasm"):
        bits.append(f"Potent Phantasm: {PHANTASM[d['phantasm']][1]}")
    return f"{owner.display_name}'s figment ({', '.join(bits)}; an image: no substance, no cover, nothing blocks)"


# ------------------------------------------------------------------------------------------------------------ the buttons
@hook("compile_actions")
def figment_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if SPHERE not in info["spheres"]:
        return None
    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    owned = set(info["owned_ids"]) | {CREATE}  # a base ability of the sphere ("All practitioners ... gain the following abilities")
    out: list[Any] = []

    def make(key: str, name: str, effects: list[dict[str, Any]], economy: Any = EconomyKind.NONE, target: str = "SELF",
             range_ft: int | None = None, **params: Any) -> Any:
        return ActionDefinition(
            source_definition_id=f"action:typed.{short}.{key}", display_name=name, owner_id=actor_id, economy=economy, resolution_kind="TYPED",
            target_kind=target, range_ft=range_ft,
            parameters={"typed": {"effects": effects, "numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "source": SPHERE,
                        # the compiler tags a sphere's talent with "sphere" too; a Foundation that reads "CP spent on a technique of the Sphere"
                        # (Glass Reflection, Old Light, ...) finds the technique by it
                        "sphere": SPHERE},
                        "expected_damage": 0, "player_only": True, **params})

    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    out.append(make("figment.create", "Create Figment", [{"type": "figment_create"}], EconomyKind.ACTION, "CELL", RANGE_FT, any_cell=True,
                    figment_kit=True, figment_create=True, figment_owned=sorted(owned), figment_pool=pool,
                    figment_control=f"action:typed.{short}.figment.control"))
    out.append(make("figment.move", "Move Figment", [{"type": "figment_move"}], EconomyKind.ACTION, "CELL", RANGE_FT, any_cell=True, figment_move=True))
    out.append(make("figment.dismiss", "Dismiss Figment", [{"type": "figment_dismiss"}], EconomyKind.NONE, "CELL", 600, any_cell=True,
                    figment_dismiss=True))
    out.append(make("figment.keep", f"Keep a figment without Concentration ({TOGGLES['free'][1]} CP)", [{"type": "figment_keep"}], EconomyKind.NONE, "CELL", 600,
                    any_cell=True, figment_keep=True))
    if CONTROL in owned:
        out.append(make("figment.control", "Control Figment (1 CP)", [{"type": "figment_control"}], EconomyKind.ACTION, "CELL", RANGE_FT, any_cell=True,
                        figment_control_button=True))
    for key, (label, _price) in TOGGLES.items():
        out.append(make(f"figment.set.{key}", f"Figment: {label}", [{"type": "figment_setup_pick", "field": key}], setting_only=True))
    if POTENT in owned:
        for value, (price, label, need) in PHANTASM.items():
            if need is None or need in owned:
                out.append(make(f"figment.set.phantasm.{value}", f"Figment: Potent Phantasm, {label} ({price} CP)",
                                [{"type": "figment_setup_pick", "field": "phantasm", "value": value}], setting_only=True))
        out.append(make("figment.set.phantasm.none", "Figment: no Potent Phantasm", [{"type": "figment_setup_pick", "field": "phantasm", "value": None}], setting_only=True))
    if SELECTIVE in owned:
        out.append(make("figment.set.selective", "Figment: Selective Premise (choose creatures when created)", [{"type": "figment_setup_pick", "field": "selective"}], setting_only=True))
    if PERMANENT in owned:
        out.append(make("figment.set.permanent", "Figment: Permanent Illusion (8 CP)",
                        [{"type": "figment_setup_pick", "field": "permanent"}], setting_only=True,
                        description="Toggle this setting for future figment creations. It does not create an illusion now. Each creation costs 8 extra cultivation points, fixes the illusion's boundary, and lasts without Concentration or its normal expiry until you dismiss it or it is dispelled."))
    if MINOR in owned:
        out.append(make("figment.minor.create", "Minor Illusion", [{"type": "figment_create", "minor": 1}],
                        EconomyKind.ACTION, "CELL", RANGE_FT, any_cell=True, figment_create=True, figment_minor=True))
        out.append(make("figment.minor.move", "Move Minor Illusion (up to 5 feet)", [{"type": "figment_move", "minor": 1}],
                        EconomyKind.BONUS_ACTION, "CELL", RANGE_FT, any_cell=True, figment_move=True, figment_minor=True))
        out.append(make("figment.minor.detail", "Change Minor Illusion detail", [{"type": "figment_minor_detail"}],
                        EconomyKind.BONUS_ACTION, "CELL", RANGE_FT, any_cell=True, figment_minor_detail=True))
    out.append(make("figment.premise", "False Premise (a creature acts on the figment)", [{"type": "save", "ability": "wis", "on_fail": [{"type": "figment_premise"}]}],
                    EconomyKind.NONE, "HOSTILE_ENTITY", 600, figment_premise=True))
    out.append(make("figment.plant", "Plant False Premise", [{"type": "save", "ability": "wis", "on_fail": [{"type": "figment_premise", "planted": True}]}],
                    EconomyKind.ACTION, "HOSTILE_ENTITY", RANGE_FT, figment_plant=True))
    for name, label in RESPONSES.items():
        out.append(make(f"figment.response.{name}", f"Misdirection Response: {label}", [{"type": "figment_response", "response": name}],
                        EconomyKind.NONE, "HOSTILE_ENTITY", 600, figment_response=name))
    return out


@effect("figment_setup_pick")
def setup_pick(ctx: Any, eff: dict[str, Any]) -> None:
    kit = _kit(ctx.engine, ctx.actor)
    config = _config(ctx.actor)
    field = str(eff["field"])
    config[field] = (not config.get(field)) if field in TOGGLES or field in {"selective", "permanent"} else eff.get("value")
    parts = [label.split(" (")[0] for key, (label, _p) in TOGGLES.items() if config.get(key)]
    choice = _phantasm(kit, config) if kit is not None else None
    if choice:
        parts.append(f"Potent Phantasm: {PHANTASM[choice][1]}")
    if config.get("selective"):
        parts.append("Selective Premise")
    if config.get("permanent"):
        parts.append("Permanent Illusion: future creations cost +8 CP and last without Concentration until dismissed or dispelled")
    price = _cost(kit, config) if kit is not None else 0
    config["label"] = "Figment: " + (", ".join(parts) if parts else "plain") + (f" ({price} CP)" if price else "")
    ctx.engine._remove_condition(ctx.actor, SETUP, ctx.source)
    ctx.engine._apply_condition(ctx.actor, SETUP, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data=config)


@hook("button_description")
def control_description(row: dict[str, Any]) -> str | None:
    from ..rule_help import printed_rule_text

    parameters = row.get("parameters") or {}
    typed = parameters.get("typed") or {}
    effects = [effect for effect in typed.get("effects") or [] if isinstance(effect, dict)]
    if not (any(key.startswith('figment_') and value for key, value in parameters.items())
            or any(str(effect.get('type') or '').startswith('figment_') for effect in effects)):
        return None
    kinds = {eff.get("type") for eff in effects}
    setup = next((eff for eff in effects if eff.get("type") == "figment_setup_pick"), None)
    if setup and setup.get("field") == "permanent":
        return ("Toggle this setting for future figment creations; it does not create an illusion now. "
                "Each creation costs 8 extra cultivation points, fixes the illusion's boundary, and lasts without "
                "Concentration or its normal expiry until you dismiss it or it is dispelled.")
    if "figment_minor_detail" in kinds:
        return "Bonus Action: change one minor sensory detail of your Minor Illusion within 60 feet. No cost."
    if "figment_move" in kinds:
        if (row.get("parameters") or {}).get("figment_minor"):
            return "Bonus Action: move your Minor Illusion up to 5 feet, keeping it within 60 feet. No cost."
        return "Action: move a figment you created or control to a point within 60 feet, while you are within range of it. You may change its appearance to make the movement look natural. No extra cultivation points.\n\n" + printed_rule_text(CREATE)
    if "figment_dismiss" in kinds:
        return "No action or cost: dismiss a figment you created or control. The image or sound disappears immediately."
    if "figment_keep" in kinds:
        return "On your turn, spend 2 cultivation points without taking an action: your chosen figment lasts for its remaining duration without Concentration.\n\n" + printed_rule_text(CREATE)
    if "figment_response" in kinds:
        eff = next(eff for eff in effects if eff.get("type") == "figment_response")
        name = RESPONSES.get(str(eff.get("response")), "Misdirection Response")
        return (f"No action, once per round: use {name} on a creature with a False Premise from you; that false belief ends. "
                "The table applies responses on your turn, rather than interrupting the triggering roll. It does not run Wrong Angle on ability checks, cancel a triggering Reaction, or move an ally with Stolen Step.\n\n"
                + printed_rule_text("TAL_ILLUSION_MISDIRECTION_RESPONSES"))
    save = next((eff for eff in effects if eff.get("type") == "save"
                 and any(isinstance(child, dict) and child.get("type") == "figment_premise" for child in eff.get("on_fail") or [])), None)
    if save:
        planted = any(isinstance(child, dict) and child.get("planted") for child in save.get("on_fail") or [])
        head = ("Action: plant a false cue in a creature within 60 feet." if planted else
                "No action: choose a creature acting on your figment as though it were real. Whether it qualifies needs a player's ruling; the table does not check that for you.")
        return (head + f" It makes a Wisdom save, DC {(typed.get('numbers') or {}).get('save_dc')}. "
                "Failure gives it a False Premise (a false belief you can exploit with a Misdirection Response) until the start of your next turn; success leaves it unaffected.\n\n"
                + printed_rule_text(CREATE))
    return None


@hook("candidate_allowed")
def figment_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    if not any(params.get(key) for key in ("figment_create", "figment_move", "figment_dismiss", "figment_control_button", "figment_premise",
                                            "figment_plant", "figment_response", "figment_keep", "figment_minor_detail")):
        return None
    kit = _kit(engine, actor)
    if kit is None:
        return False
    aim = getattr(candidate, "destination", None)
    target = engine.state.actors.get((candidate.target_ids or ("",))[0])
    if params.get("figment_create"):
        totals: dict[str, int] = {}
        for pool, amount in (((kit["pool"], 8),) if params.get("figment_minor") and _config(actor).get("permanent") and PERMANENT in kit["owned"]
                             else () if params.get("figment_minor") else creation_costs(engine, actor, action)):
            totals[pool] = totals.get(pool, 0) + amount
        if aim is None or any(actor.resources.get(pool, 0) < amount for pool, amount in totals.items()):
            return False
        return engine.grid.distance_ft(actor.position, aim) <= RANGE_FT and engine._line_of_sight_actor_to_cell(actor, aim)
    if params.get("figment_move"):
        return aim is not None and _mover(engine, actor, aim, minor=bool(params.get("figment_minor"))) is not None
    if params.get("figment_minor_detail"):
        return aim is not None and _mover(engine, actor, aim, minor=True, detail=True) is not None
    if params.get("figment_dismiss"):
        return aim is not None and _nearest(engine, _figments(engine, actor, "either"), aim) is not None and engine.state.current_actor_id == actor.entity_id
    if params.get("figment_keep"):
        mine = [zone for zone in _figments(engine, actor, "either") if not placed.data(zone).get("free")]
        return (aim is not None and _nearest(engine, mine, aim) is not None and engine.state.current_actor_id == actor.entity_id
                and actor.resources.get(kit["pool"], 0) >= TOGGLES["free"][1])
    if params.get("figment_control_button"):
        if aim is None or actor.resources.get(kit["pool"], 0) < 1:
            return False
        return _seizable(engine, actor, aim) is not None
    if target is None or not _hostile(actor, target):
        return False
    if params.get("figment_premise"):
        return _sees_figment(engine, actor, target) and not _premised(target, actor)
    if params.get("figment_plant"):
        return (engine.grid.distance_ft(actor.position, target.position) <= RANGE_FT and engine._line_of_sight_actor_to_cell(actor, target.position)
                and not _premised(target, actor))
    from .illusion_riders import response_limit

    return _premised(target, actor) and _responses_used(engine, actor) < response_limit(engine, actor)  # Sovereign Illusion Incarnation: two


def _premised(target: Any, owner: Any) -> bool:
    from ..typed_executor import bears_mark

    return bears_mark(target, owner.entity_id, PREMISE)


# ------------------------------------------------------------------------------------------- making, moving, ending, seizing
def _mover(engine: Any, actor: Any, cell: Any, *, minor: bool = False, detail: bool = False) -> Any | None:
    """The figment "Move Figment" moves: one the actor controls and is within range of, that the square is within range of."""
    if engine.grid.distance_ft(actor.position, cell) > RANGE_FT or not engine._line_of_sight_actor_to_cell(actor, cell):
        return None
    near = [zone for zone in _figments(engine, actor) if _distance_to(engine, actor, zone) <= RANGE_FT
            and bool(placed.data(zone).get("minor")) == minor
            and (detail or not placed.data(zone).get("permanent"))
            and (not minor or detail or engine.grid.distance_ft(zone.center, cell) <= 5)]
    return _nearest(engine, near, cell)


def _seizable(engine: Any, actor: Any, cell: Any) -> Any | None:
    """The figment "Control Figment" reaches: one in range (nearest square) that the actor can perceive and does not control yet."""
    near = [zone for zone in placed.of(engine, "figment") if placed.data(zone).get("controller") != actor.entity_id
            and _distance_to(engine, actor, zone) <= RANGE_FT and engine._line_of_sight_actor_to_cell(actor, zone.center)]
    return _nearest(engine, near, cell)


@effect("figment_create")
def create(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    kit, cell = _kit(engine, owner), getattr(ctx.intent, "destination", None)
    if kit is None or cell is None:
        ctx.rider("Create Figment: no square was chosen.")
        return
    config = _config(owner)
    minor = bool(eff.get("minor"))
    if minor and MINOR not in kit["owned"]:
        return
    if minor:
        config = {"selective": config.get("selective", 0), "free": 1, "permanent": config.get("permanent", 0)}
    from .illusion_riders import senses_free

    permanent = bool(config.get("permanent") and PERMANENT in kit["owned"])
    price = (8 if permanent else 0) if minor else _cost(kit, config, senses_free(engine, owner))
    if price:
        engine._spend_resource(owner, kit["pool"], price, ctx.source)
    size = 5 if minor else _size(kit, config)
    choice = _phantasm(kit, config)
    detail = _detail(ctx, "create") if minor else ""
    recognized, immune = _selective(ctx, kit, config)
    d = {"state": "figment", "creator": owner.entity_id, "controller": owner.entity_id, "size_ft": size, "senses": bool(config.get("senses")),
         "free": bool(config.get("free") or permanent), "permanent": int(permanent), "phantasm": choice, "recognized": recognized, "cl": _cl(kit),
         "save_dc": int(kit["numbers"].get("save_dc") or 10), "immune": immune, "studied": [],
         "minor": int(minor), "detail": detail}
    if minor:
        d["free"], d["senses"] = 1, 0
    zid = placed.new_id(engine, owner, "figment")
    triggers = ([{"id": "figment:phantasm", "name": "Potent Phantasm", "on": ["start"], "who": "any",
                  "effects": [{"type": "figment_phantasm", "zone": zid}]}] if choice else [])
    zone = placed.place(engine, owner, source=kit["source"], tag="figment", cells=_cube(engine, cell, size), zone_id=zid, name=_name(owner, size, d),
                        numbers=kit["numbers"], duration_rounds=None if permanent else ROUNDS, color="#9a7fd1", material="generic", shape="placed", size_ft=5,
                        triggers=triggers, concentration=not d["free"], placed=d)
    if not d["free"]:
        engine._start_concentration(owner, kit["source"])  # "Concentration": a new one past the limit ends the one held longest
        if owner.concentration is not None:
            owner.concentration.zone_id = zone.zone_id
    names = [engine.state.actors[i].display_name for i in recognized]
    _log(engine, ctx.source, owner, f"{owner.display_name} makes a figment ({size}-foot cube) at ({cell.x}, {cell.y})" + (f", Potent Phantasm: {PHANTASM[choice][1]}" if choice else "")
         + (f"; {', '.join(names)} see through it" if names else "") + (" (it lasts without Concentration)" if d["free"] else "") + ".")


@effect("figment_move")
def move(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner, cell = ctx.engine, ctx.actor, getattr(ctx.intent, "destination", None)
    zone = _mover(engine, owner, cell, minor=bool(eff.get("minor"))) if cell is not None else None
    if zone is None:
        ctx.rider("Move Figment: no figment of yours is within range of that square.")
        return
    before, d = zone.center, placed.data(zone)
    placed.reshape(engine, zone, cells=_cube(engine, cell, int(d.get("size_ft") or 10)), center=cell)
    _log(engine, ctx.source, owner, f"{owner.display_name} moves the figment from ({before.x}, {before.y}) to ({cell.x}, {cell.y}); its look moves naturally with it.")


def _end(engine: Any, zone: Any, reason: str) -> None:
    """A figment ends: the Concentration of its creator (and of a controller that took it over) goes with it."""
    for holder in engine.state.actors.values():
        conc = holder.concentration
        if conc is not None and conc.zone_id == zone.zone_id:
            engine._end_concentration(holder, reason)
    if zone.active:
        placed.drop(engine, zone, reason)


@effect("figment_keep")
def keep(ctx: Any, eff: dict[str, Any]) -> None:
    """Create Figment, augment 2 CP: "The figment lasts for its remaining duration without Concentration. You may apply this augment on
    your turn after creating the figment without using an Action." (Choosing it while creating is the "no Concentration" setup button.)"""
    engine, owner, cell = ctx.engine, ctx.actor, getattr(ctx.intent, "destination", None)
    kit = _kit(engine, owner)
    mine = [zone for zone in _figments(engine, owner, "either") if not placed.data(zone).get("free")]
    zone = _nearest(engine, mine, cell) if kit is not None and cell is not None else None
    if zone is None:
        ctx.rider("Keep a figment: none of yours needs Concentration.")
        return
    engine._spend_resource(owner, kit["pool"], TOGGLES["free"][1], ctx.source)
    for holder in engine.state.actors.values():  # the Concentration on it (its creator's, or a controller's) is over, the figment stays
        conc = holder.concentration
        if conc is not None and conc.zone_id == zone.zone_id:
            conc.zone_id = None
            engine._end_concentration(holder, "FIGMENT_KEPT")
    zone.concentration_link = False
    placed.update(engine, zone, free=True, control_sequence=None)
    _log(engine, ctx.source, owner, f"{owner.display_name}'s figment at ({zone.center.x}, {zone.center.y}) now lasts without Concentration.")


@effect("figment_dismiss")
def dismiss(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner, cell = ctx.engine, ctx.actor, getattr(ctx.intent, "destination", None)
    zone = _nearest(engine, _figments(engine, owner, "either"), cell) if cell is not None else None
    if zone is None:
        return
    _end(engine, zone, "DISMISSED")
    _log(engine, ctx.source, owner, f"{owner.display_name} lets the figment at ({zone.center.x}, {zone.center.y}) fade.")


@effect("figment_control")
def control(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner, cell = ctx.engine, ctx.actor, getattr(ctx.intent, "destination", None)
    kit = _kit(engine, owner)
    zone = _seizable(engine, owner, cell) if kit is not None and cell is not None else None
    if zone is None:
        ctx.rider("Control Figment: no figment of another's is in range.")
        return
    engine._spend_resource(owner, kit["pool"], 1, ctx.source)
    d = placed.data(zone)
    dc = int(d.get("save_dc") or 10)  # the creator's Cultivation Save DC
    creator = engine.state.actors.get(str(d.get("creator")))
    # "Make a Cultivation Check against the creator's Cultivation Save DC": the printed rider requires all
    # applicable Advantage, Disadvantage, bonuses and check floors, so use the shared check resolver.
    from ..typed_executor import check_modes
    from .ability_source import cultivation_check_detail

    modes = check_modes(owner, None, None, engine=engine, against_creature=creator)
    roll, success = cultivation_check_detail(engine, owner, dict(ctx.numbers or {}), dc, ctx.source,
                                             "Cultivation Check (Control Figment)", modes)
    if not success:
        _log(engine, ctx.source, owner, f"{owner.display_name} fails to seize the figment (Cultivation Check {roll.total} against {dc}).")
        return
    seq = None
    if not d.get("free"):
        engine._start_concentration(owner, kit["control"] or ctx.source)  # "If the figment required Concentration, you must assume Concentration over it."
        seq = owner.concentration.started_sequence if owner.concentration is not None else None
    placed.update(engine, zone, controller=owner.entity_id, control_sequence=seq)
    _log(engine, ctx.source, owner, f"{owner.display_name} seizes the figment (Cultivation Check {roll.total} against {dc}): it moves and ends at their word, with its creator's CL, duration and senses.")


@hook("event")
def control_lapses(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"you control the figment for as long as you maintain Concentration": when the controller's Concentration ends, the figment is its
    creator's again (it lasts as long as the creator's Concentration)."""
    payload = kwargs.get("payload") or {}
    if event_type == "ZONE_REMOVED":  # the figment is gone (its creator's Concentration ended, it faded, time ran out): so is the controller's hold
        zone = engine.state.zones.get(str(payload.get("zone_id")))
        d = placed.data(zone) if zone is not None else {}
        holder = engine.state.actors.get(str(d.get("controller")))
        if d.get("tag") == "figment" and d.get("control_sequence") is not None and holder is not None and holder.concentration is not None \
                and holder.concentration.started_sequence == d.get("control_sequence"):
            engine._end_concentration(holder, "FIGMENT_ENDED")
        return
    if event_type != "CONCENTRATION_ENDED":
        return
    event = kwargs.get("originating_event")
    source = str(kwargs.get("source_definition_id") or getattr(event, "source_definition_id", ""))
    actor_id = kwargs.get("actor_id") or getattr(event, "actor_id", None)
    if not source.endswith(".figment.control"):
        return
    for zone in placed.of(engine, "figment"):
        d = placed.data(zone)
        if d.get("control_sequence") is not None and d.get("control_sequence") == payload.get("started_sequence") and d.get("controller") == actor_id:
            placed.update(engine, zone, controller=d.get("creator"), control_sequence=None)
            _log(engine, source, engine.state.actors[actor_id], "The figment returns to its creator: its controller's Concentration ended.")


# ---------------------------------------------------------------------------------------- Potent Phantasm, False Premise, responses
@effect("figment_phantasm")
def phantasm(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    engine, target = ctx.engine, ctx.target
    zone = engine.state.zones.get(str(eff.get("zone")))
    if zone is None or not zone.active or target is None:
        return
    d = placed.data(zone)
    if target.entity_id == d.get("creator") or target.entity_id in d.get("immune", ()):
        return
    choice = d.get("phantasm")
    if choice == "psychic":
        fail = {"type": "damage", "applies_to": "target", "dice": {"count": placed.cl_row(int(d.get("cl") or 1), PSYCHIC_DICE), "sides": 4}, "flat": 0,
                "formula": "none", "damage_types": ["psychic"]}
    elif choice in CONDITIONS:
        fail = {"type": "condition", "applies_to": "target", "condition": CONDITIONS[choice], "expires_on": "START_OF_TARGET_NEXT_TURN"}
    else:
        return
    _log(engine, ctx.source, ctx.actor, f"{target.display_name} starts its turn inside {ctx.actor.display_name}'s figment: Potent Phantasm ({PHANTASM[choice][1]}), Intelligence save.", targets=(target,))
    from copy import copy
    inner = copy(ctx)
    inner.typed = {**ctx.typed, "figment_zone": zone.zone_id}
    run_effects(inner, [{"type": "save", "ability": "int", "on_fail": [fail]}])


@effect("figment_premise", harmful=True)
def premise(ctx: Any, eff: dict[str, Any]) -> None:
    """The failed Wisdom save: the target "gains one False Premise from you until the start of your next turn" (a mark of the illusionist's)."""
    from ..typed_executor import mark_condition_id

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or _premised(target, owner):  # "a creature can be affected by only one False Premise from you at a time"
        return
    engine._apply_condition(target, mark_condition_id(PREMISE, owner.entity_id), ctx.source, owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": f"False Premise from {owner.display_name}",
                                  **({"figment_zone": seen[0].zone_id} if not eff.get("planted") and len(seen := [
                                      z for z in _figments(engine, owner, "either") if not _recognizes(z, target)
                                      and engine._line_of_sight_actor_to_cell(target, z.center)]) == 1 else {})})
    how = "planted by" if eff.get("planted") else "from"
    _log(engine, ctx.source, owner, f"{target.display_name} gains a False Premise {how} {owner.display_name}: it ends when they use a Misdirection Response, when the "
         f"creature recognizes the illusion, or at the start of their next turn. (Whether it is acting on the figment as if real is the GM's call.)", targets=(target,))


@effect("figment_response")
def response(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import mark_condition_id, run_effects

    from . import illusion_riders

    engine, owner, target, kind = ctx.engine, ctx.actor, ctx.target, str(eff.get("response"))
    if target is None or not _premised(target, owner) or _responses_used(engine, owner) >= illusion_riders.response_limit(engine, owner):
        ctx.rider("Misdirection Response: it needs a creature with a False Premise from you, and only one a round.")
        return
    owner.turn_flags["figment_response_round_count"] = f"{engine.state.round_number}:{_responses_used(engine, owner) + 1}"
    owner.turn_flags["figment_response_round_used"] = engine.state.round_number  # "only one Misdirection Response per round"
    mark = next((row for row in target.conditions.values() if row.condition_id == mark_condition_id(PREMISE, owner.entity_id)), None)
    premise_source = str(mark.source_definition_id) if mark is not None else ""
    if not illusion_riders.keeps_premise(ctx, owner, target):  # Premise Chain, the Court of False Premises
        engine._remove_condition(target, mark_condition_id(PREMISE, owner.entity_id), ctx.source)  # "ends immediately after you trigger a Misdirection Response"
    inner = placed.context(engine, owner, ctx.source, ctx.numbers, [target], action=ctx.action)
    if kind == "opening":
        run_effects(inner, [{"type": "advantage", "applies_to": "target", "on": "the next attack roll against it", "duration": "until_start_of_next_turn"}])
    elif kind == "angle":
        run_effects(inner, [{"type": "disadvantage", "applies_to": "target", "on": "its next attack roll", "duration": "until_start_of_next_turn"}])
    elif kind == "timing":
        run_effects(inner, [{"type": "condition", "applies_to": "target", "condition": "reaction_denied", "expires_on": "END_OF_HOLDER_NEXT_TURN"}])
    else:
        run_effects(inner, [{"type": "speed", "applies_to": "target", "flat": -10, "duration": "until_start_of_next_turn"}])
    _log(engine, ctx.source, owner, f"{owner.display_name} triggers {RESPONSES[kind]} on {target.display_name}: its False Premise ends.", targets=(target,))
    illusion_riders.second_response(ctx, owner, target, kind, premise_source)  # Impossible Premise: two different Responses


def _responses_used(engine: Any, owner: Any) -> int:
    """Misdirection Responses this owner has triggered this round (a "_round_" flag: "round:count")."""
    value = str(owner.turn_flags.get("figment_response_round_count") or "")
    round_now, _, count = value.partition(":")
    if round_now == str(engine.state.round_number) and count.isdigit():
        return int(count)
    return 1 if owner.turn_flags.get("figment_response_round_used") == engine.state.round_number else 0


def _detail(ctx: Any, phase: str) -> str:
    from .needle import CHOICE, ask, checkpoint_id
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'MINOR_DETAIL', ctx.actor.entity_id, phase),
                 ctx.actor, CHOICE + 'minor_detail', list(MINOR_DETAILS), labels=MINOR_DETAILS,
                 preferred=['image'], prompt=f'Minor Illusion: {ctx.actor.display_name} chooses a sensory detail for this image within 60 feet. No cost.')
    return (picked or ['image'])[0]


def _selective(ctx: Any, kit: dict[str, Any], config: dict[str, Any]) -> tuple[list[str], list[str]]:
    from .needle import CHOICE, ask, checkpoint_id
    from ..target_knowledge import can_see
    if not config.get('selective') or SELECTIVE not in kit['owned']:
        return [], []
    subjects = [a for a in ctx.engine.state.actors.values() if a.active
                and can_see(ctx.engine, ctx.actor, a)]
    labels = {a.entity_id: a.display_name for a in subjects}
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'SELECTIVE_FIGMENT', ctx.actor.entity_id),
                   ctx.actor, CHOICE + 'selective_figment', list(labels), labels=labels, minimum=0,
                   maximum=min(len(subjects), int(kit['numbers'].get('pb') or 2)), allow_decline=True,
                   preferred=[a.entity_id for a in subjects if a.team_id == ctx.actor.team_id],
                   automatic_options=[a.entity_id for a in subjects if a.team_id == ctx.actor.team_id],
                   prompt=f'Selective Premise: {ctx.actor.display_name} creates this illusion. Choose up to {kit["numbers"].get("pb", 2)} creatures you perceive; no extra action or cost.')
    recognized, immune = [], []
    for subject in subjects:
        if subject.entity_id not in selected:
            continue
        options = ['recognize'] if _phantasm(kit, config) == 'psychic' else ['recognize', 'immune']
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'SELECTIVE_MODE', subject.entity_id),
                     ctx.actor, CHOICE + 'selective_mode', options,
                     labels={'recognize': 'Recognizes this illusion as false', 'immune': 'Immune to this illusion’s harmless or hindering effects'},
                     preferred=['recognize'], target_id=subject.entity_id,
                     prompt=f'Selective Premise: choose how this new illusion affects {subject.display_name} for its duration. No extra action or cost.')
        (immune if picked == ['immune'] else recognized).append(subject.entity_id)
    return recognized, immune


@effect('figment_minor_detail')
def minor_detail(ctx: Any, eff: dict[str, Any]) -> None:
    cell = getattr(ctx.intent, 'destination', None)
    zone = _mover(ctx.engine, ctx.actor, cell, minor=True, detail=True) if cell is not None else None
    if zone is not None:
        detail = _detail(ctx, 'change')
        placed.reshape(ctx.engine, zone, name=_name(ctx.actor, 5, {**placed.data(zone), 'detail': detail}), detail=detail)
        _log(ctx.engine, ctx.source, ctx.actor, f'Minor Illusion: {ctx.actor.display_name} changes one detail to {MINOR_DETAILS[detail]}.')


@hook('match_start')
def install_study(engine: Any) -> None:
    engine.action_catalog[STUDY] = _study_action(STUDY, '*', {})


def _study_action(source: str, owner: str, numbers: dict[str, Any]) -> Any:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return ActionDefinition(
        source_definition_id=source, display_name='Study an illusion', owner_id=owner, economy=EconomyKind.ACTION,
        resolution_kind='TYPED', target_kind='SELF', parameters={'illusion_study': 1, 'expected_damage': 0,
        'typed': {'effects': [{'type': 'figment_study'}], 'numbers': numbers, 'duration': {'kind': 'instant'}, 'riders': []}})


@hook('compile_actions')
def compile_study(info: dict[str, Any]) -> list[Any]:
    # Seal the ordinary check modifier separately from saving-throw proficiency.
    return [_study_action(f"action:typed.{info['short']}.study_figment", info['actor_id'],
                          {'ability_mods': dict(info['mods'])})]


def _studyable(engine: Any, actor: Any) -> list[Any]:
    from ..senses import perceives_cell
    return [z for z in placed.of(engine, 'figment') if actor.entity_id != placed.data(z).get('creator')
            and actor.entity_id not in placed.data(z).get('studied', ())
            and perceives_cell(engine, actor, z.center)]


def _study_bonus(engine: Any, actor: Any, numbers: dict[str, Any]) -> int | None:
    from ..ability_checks import ordinary_check_bonus
    return ordinary_check_bonus(engine, actor, 'INT', 'Investigation', numbers=numbers)


@hook('additional_actions')
def offer_study(engine: Any, actor: Any) -> list[str]:
    if any((engine.action_catalog.get(a).parameters or {}).get('illusion_study')
           for a in actor.action_ids if a in engine.action_catalog):
        return []
    return [STUDY] if (STUDY in engine.action_catalog and _studyable(engine, actor)
                      and _study_bonus(engine, actor, {}) is not None) else []


@hook('candidate_allowed')
def study_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if (getattr(action, 'parameters', None) or {}).get('illusion_study'):
        numbers = ((action.parameters or {}).get('typed') or {}).get('numbers') or {}
        return bool(_studyable(engine, actor)) and _study_bonus(engine, actor, numbers) is not None
    return None


@hook('source_unavailable')
def study_unavailable(engine: Any, actor: Any, action: Any) -> str | None:
    """The same check for the compact-menu header, before an image is chosen."""
    if not (getattr(action, 'parameters', None) or {}).get('illusion_study'):
        return None
    if not _studyable(engine, actor):
        return 'There is no illusion you can see that you have not already studied.'
    numbers = ((action.parameters or {}).get('typed') or {}).get('numbers') or {}
    return None if _study_bonus(engine, actor, numbers) is not None else 'You cannot make the Investigation check now.'


@hook('button_description')
def study_description(row: dict[str, Any]) -> str | None:
    if (row.get('parameters') or {}).get('illusion_study'):
        return 'Action: choose a figment you can see. Make an Intelligence (Investigation) check against its creator’s save DC. Success recognizes that image as false; future saves against its Potent Phantasm have Advantage. No cost.'
    return None


@effect('figment_study')
def study(ctx: Any, eff: dict[str, Any]) -> None:
    from .needle import CHOICE, ask, checkpoint_id
    from .escape_checks import resolve_escape_check
    from ..typed_executor import mark_condition_id
    zones = _studyable(ctx.engine, ctx.actor)
    bonus = _study_bonus(ctx.engine, ctx.actor, ctx.numbers)
    if not zones or bonus is None:
        return
    labels = {z.zone_id: str((z.trigger_profile or {}).get('name') or 'Figment') for z in zones}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'STUDY_FIGMENT', ctx.actor.entity_id),
                 ctx.actor, CHOICE + 'study_figment', list(labels), labels=labels, preferred=[zones[0].zone_id],
                 prompt=f'Study an illusion: {ctx.actor.display_name} spends an Action to inspect one image. Success recognizes only that illusion; no cultivation-point cost.')
    zone = next(z for z in zones if z.zone_id == (picked or [zones[0].zone_id])[0])
    d = placed.data(zone)
    if resolve_escape_check(ctx, {'bonus': bonus}, int(d.get('save_dc') or 10), [],
                            check_ability='INT', check_skill='Investigation', check_name='Study an illusion',
                            source_id=zone.source_definition_id, source_actor_id=zone.owner_id,
                            escape_hooks=False):
        placed.update(ctx.engine, zone, studied=sorted(set(d.get('studied') or []) | {ctx.actor.entity_id}),
                      recognized=sorted(set(d.get('recognized') or []) | {ctx.actor.entity_id}))
        cid = mark_condition_id(PREMISE, str(d.get('creator')))
        mark = next((c for c in ctx.actor.conditions.values() if c.condition_id == cid), None)
        if mark is not None and (mark.data or {}).get('figment_zone') == zone.zone_id:
            ctx.engine._remove_condition(ctx.actor, cid, ctx.source)
        _log(ctx.engine, ctx.source, ctx.actor, f'{ctx.actor.display_name} recognizes this figment as false.')


@hook('save')
def studied_phantasm_save(ctx: Any, subject: Any, ability: str, named: set[str]) -> dict[str, Any] | None:
    zone = ctx.engine.state.zones.get(str(ctx.typed.get('figment_zone') or ''))
    if zone is not None and zone.active and subject.entity_id in placed.data(zone).get('studied', ()):
        return {'modes': ['ADVANTAGE']}
    return None
