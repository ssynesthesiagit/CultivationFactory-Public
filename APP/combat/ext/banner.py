"""Banner Cultivator placements, objects and recipient-owned movement.

Raise the Standard creates one nonblocking projected object: Medium, AC 14,
3 x Qi CL HP, Poison/Psychic immunity and source CL. Its standard placement
ends when it is destroyed, dismissed or expires; moves keep the object and aura
at the same point. The existing carried-banner placement follows its bearer.
Physical inventory selection, legal carrying, item-property binding and a real
Domain Armament remain unimplemented and explicit in reviewed authority riders.

Rally chooses allies inside the aura, grants native Temporary HP once per round,
and offers each an immediate physical step. Advance Together, Officer's Command,
Formation Maneuver, Imperial Advance, Follow the Victor and Standard Cannot Fall
share rider_step's native optional movement. The recipient chooses its route;
unused grants are not stored. Standard Cannot Fall records its one-use allowance
before the hit but offers movement only after HP commits. All movement retains
native occupancy, terrain, hazards and the printed Opportunity Attack exemption.

Imperial Standard chooses its defense recipients, grants difficult-terrain
exemptions and protects its projected Banner against destruction by a lower-CL
source through the general object_hp_floor seam. Imperial Advance and Follow the
Victor ask the owner to choose allies. Automatic rosters contain perceived allies;
hostile ranking never reads unseen creatures. Temporary auras and once limits keep
the existing native round/turn ledger. Hold Formation retains its typed save
checkpoint and ordinary Reaction/resource payment.

Remaining: physically bound real items, traversed Banner flight routes, Clear
Signal, Guarded against non-opportunity Reaction attacks, and broader native-save
Hold Formation integration. These are not silently reported as full automation.
Hooks use existing compile_actions, candidate_allowed, ac, speed, save, after_save,
turn_start_choice, event, difficult_exempt and reaction_subject_allowed contracts.
"""

from __future__ import annotations

from ..paid_relocation import activation

from .map_positions import map_position

import itertools
from typing import Any

from . import effect, hook, placed

P = "tianxia.subpath.qi.banner_cultivator.feature."
RAISE, RALLY, ADVANCING, FOURFOLD, IMPERIAL = (P + name for name in ("raise_the_standard", "rally_the_line", "advancing_standard", "fourfold_formation",
                                                                    "imperial_standard_of_heaven"))
SETUP = "condition:typed.banner_orders"
STEP = "condition:typed.banner_step"
SPENT = "condition:typed.banner_imperial_spent"
BRACE = "condition:typed.banner_brace"
STANCES = {"forward": "Forward", "guarded": "Guarded", "steady": "Steady", "signal": "Clear Signal"}
MANEUVERS = {"auto": "automatic", "step": "move the ally 5 feet", "temp": "Temporary Hit Points", "push": "push the damaged creature 5 feet",
             "deny": "no Reactions for the damaged creature", "banner": "move the banner up to 10 feet",
             "off": "no maneuver (no extra effect)"}
ORDERS = {"auto": "Best fit", "reposition": "Reposition", "seize": "Seize the Opening", "brace": "Brace", "rise": "Rise", "courage": "Remember Courage",
          "shift": "Shift the Standard"}
RANGE_FT = 30  # Raise the Standard: "Range: 30 feet"
ROUNDS = 4800  # "Duration: 8 hours" in six-second rounds
MINUTE = 10  # "1 minute"
AURA = {"base": 15, "advancing": 20, "imperial": 40}  # the aura's feet ("aura 15 feet"; "Aura increases to 20 feet"; "Aura becomes 40 feet")
COLOR = "#d4a72c"


# ------------------------------------------------------------------------------------------------------------ the kit
def _kit(engine: Any, owner: Any) -> dict[str, Any] | None:
    for action in engine.action_catalog.values():
        params = action.parameters or {}
        if action.owner_id == owner.entity_id and params.get("banner_kit"):
            typed = params.get("typed") or {}
            return {"action": action, "owned": set(params.get("banner_owned") or ()), "numbers": typed.get("numbers") or {},
                    "pool": params.get("banner_pool") or "resource:core.qi", "source": action.source_definition_id}
    return None


def _config(owner: Any) -> dict[str, Any]:
    for condition in owner.conditions.values():
        if condition.condition_id == SETUP:
            return dict(condition.data or {})
    return {}


def _pb(kit: dict[str, Any]) -> int:
    return int(kit["numbers"].get("pb") or 2)


def _banner(engine: Any, owner: Any) -> Any | None:
    rows = placed.of(engine, "standard", owner_id=owner.entity_id)
    return rows[-1] if rows else None


def _on(engine: Any, d: dict[str, Any], key: str) -> bool:
    """Whether a timed part of the banner (``advancing_until``, ``imperial_until``) is still running."""
    until = d.get(key)
    return until is not None and engine.state.round_number < int(until)


def _now(engine: Any, zone: Any, key: str) -> bool:
    return _on(engine, placed.data(zone), key)


def _aura(engine: Any, zone: Any) -> int:
    return AURA["imperial"] if _now(engine, zone, "imperial_until") else AURA["advancing"] if _now(engine, zone, "advancing_until") else AURA["base"]


def _stances(engine: Any, zone: Any) -> list[str]:
    return list(STANCES) if _now(engine, zone, "imperial_until") else list(placed.data(zone).get("stances") or [])


def _covers(engine: Any, zone: Any, creature: Any) -> bool:
    """A creature inside the aura: within its feet of the banner's square (the banner's owner and its allies)."""
    owner = engine.state.actors.get(zone.owner_id)
    obj=engine.state.objects.get('object:banner:'+zone.zone_id)
    if obj and (obj.destroyed or obj.suppressed):return False
    from ..spatial_areas import actor_in_area
    return (owner is not None and owner.active and creature.active and owner.team_id == creature.team_id
            and actor_in_area(engine,creature,zone.center,zone.center,{'shape':'sphere','size_ft':_aura(engine,zone)}))


def _banners_over(engine: Any, creature: Any) -> list[Any]:
    return [zone for zone in placed.of(engine, "standard") if _covers(engine, zone, creature)]


def _has_stance(engine: Any, creature: Any, stance: str) -> bool:
    return any(stance in _stances(engine, zone) for zone in _banners_over(engine, creature))


def _imperial_over(engine: Any, creature: Any) -> Any | None:
    """A chosen ally receiving Imperial Standard's defensive bonuses."""
    return next((zone for zone in _banners_over(engine, creature) if _now(engine, zone, "imperial_until") and creature.entity_id in placed.data(zone).get("imperial_chosen",[])), None)


def _imperial_aura_over(engine: Any, creature: Any) -> Any | None:
    """An ally in an active Imperial aura, whether chosen for defenses or not.

    Standard Cannot Fall protects every ally in the aura. The Imperial roster
    controls only the bonuses whose text says "chosen allies".
    """
    return next((zone for zone in _banners_over(engine, creature) if _now(engine, zone, "imperial_until")), None)


def _allies_in(engine: Any, zone: Any) -> list[Any]:
    return [c for c in engine.state.actors.values() if _covers(engine, zone, c)]


def _hostiles(engine: Any, owner: Any) -> list[Any]:
    from .. import stealth
    return [c for c in engine.state.actors.values() if c.active and c.team_id != owner.team_id and stealth.sees(engine,owner,c)]


def _nearest_foe_ft(engine: Any, owner: Any, cell: Any) -> int:
    return min((engine.grid.distance_ft(cell, foe.position) for foe in _hostiles(engine, owner)), default=999)


def _name(owner: Any, d: dict[str, Any], aura: int, stances: list[str], running: list[str]) -> str:
    kind = "real banner, carried" if d.get("carried") else "projected"
    shown = ", ".join(STANCES[s] for s in stances) or "no Stance"
    extra = "".join(f"; {label}" for label in running)
    return f"{owner.display_name}'s Command Banner ({kind}; aura {aura} ft; {shown}{extra}; it blocks nothing and gives no cover)"


def _refresh(engine: Any, zone: Any, owner: Any, *, centre: Any = None, **changes: Any) -> None:
    """Re-record the placement with its changes: its squares (the aura round the banner), its name and what it remembers."""
    d = {**placed.data(zone), **changes}
    d.pop("tag", None)
    centre = centre if centre is not None else zone.center
    aura = AURA["imperial"] if _on(engine, d, "imperial_until") else AURA["advancing"] if _on(engine, d, "advancing_until") else AURA["base"]
    stances = list(STANCES) if _on(engine, d, "imperial_until") else list(d.get("stances") or [])
    around = [(c.x, c.y) for c in placed.area(engine, centre, "sphere", aura)]
    cells = [(centre.x, centre.y)] + [c for c in around if c != (centre.x, centre.y)]
    running = [label for key, label in (("imperial_until", "Imperial Standard of Heaven"), ("advancing_until", "Advancing Standard")) if _on(engine, d, key)]
    placed.reshape(engine, zone, cells=cells, center=centre, name=_name(owner, d, aura, stances, running), profile={"size_ft": aura, "shape": "sphere"}, **d)


def _log(engine: Any, source: str, owner: Any, text: str, targets: Any = ()) -> None:
    placed.note(engine, source, owner, text, targets=targets)


# ------------------------------------------------------------------------------------------------------------ the buttons
@hook("compile_actions")
def banner_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned = {mid for mid in info["owned_ids"] if mid in (RAISE, RALLY, ADVANCING, FOURFOLD, IMPERIAL)}
    if RAISE not in owned:
        return None
    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    out: list[Any] = []

    def make(key: str, name: str, effects: list[dict[str, Any]], economy: Any = EconomyKind.NONE, target: str = "SELF",
             range_ft: int | None = None, **params: Any) -> Any:
        return ActionDefinition(
            source_definition_id=f"action:typed.{short}.{key}", display_name=name, owner_id=actor_id, economy=economy, resolution_kind="TYPED",
            target_kind=target, range_ft=range_ft,
            parameters={"typed": {"effects": effects, "numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "source": RAISE},
                        "expected_damage": 0, "player_only": True, **params})

    out.append(make("banner.raise", "Manifest Command Banner (1 Qi)", [{"type": "banner_manifest"}], EconomyKind.BONUS_ACTION, "CELL", RANGE_FT, any_cell=True,
                    banner_kit=True, banner_owned=sorted(owned), banner_pool=pool, banner_button="raise"))
    out.append(make("banner.carry", "Empower a Real Banner you carry (1 Qi)", [{"type": "banner_manifest", "carried": True}], EconomyKind.BONUS_ACTION, "SELF",
                    banner_button="carry"))
    out.append(make("banner.dismiss", "Dismiss Command Banner", [{"type": "banner_dismiss"}], banner_button="dismiss"))
    # "Choose one Banner Stance when you manifest ... change once each turn"; Fourfold Formation: "two different Stances ... change either or both once".
    picks = list(itertools.combinations(STANCES, 2)) if FOURFOLD in owned else [(key,) for key in STANCES]
    for pick in picks:
        out.append(make("banner.stance." + ".".join(pick), "Banner Stance: " + " + ".join(STANCES[k] for k in pick), [{"type": "banner_stance", "stances": list(pick)}],
                        banner_button="stance"))
    if RALLY in owned:
        out.append(make("banner.rally", "Rally the Line (2 Qi)", [{"type": "banner_rally"}], EconomyKind.BONUS_ACTION, banner_button="rally"))
    if ADVANCING in owned:
        out.append(make("banner.advance", "Advancing Standard (4 Qi)", [{"type": "banner_advance"}], EconomyKind.BONUS_ACTION, banner_button="advance"))
        out.append(make("banner.move", "Move the Banner (up to 30 feet, free)", [{"type": "banner_move"}], EconomyKind.NONE, "CELL", 60, any_cell=True,
                        banner_button="move"))
        for key, label in MANEUVERS.items():
            out.append(make(f"banner.maneuver.{key}", f"Formation Maneuver: {label}", [{"type": "banner_maneuver_pick", "value": key}], banner_button="pick", setting_only=True))
    if IMPERIAL in owned:
        out.append(make("banner.imperial", "Imperial Standard of Heaven (8 Qi, once per scene)", [{"type": "banner_imperial"}], EconomyKind.BONUS_ACTION,
                        banner_button="imperial"))
    return out


@hook("candidate_allowed")
def banner_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    button = (getattr(action, "parameters", None) or {}).get("banner_button")
    if not button:
        return None
    kit = _kit(engine, actor)
    if kit is None:
        return False
    zone = _banner(engine, actor)
    have = actor.resources.get(kit["pool"], 0)
    aim = getattr(candidate, "destination", None)
    turn = engine.state.current_actor_id == actor.entity_id
    if button == "raise":
        return (aim is not None and have >= 1 and engine.grid.distance_ft(actor.position, aim) <= RANGE_FT and placed.free_square(engine, aim)
                and engine._line_of_sight_actor_to_cell(actor, aim))
    if button == "carry":
        return have >= 1
    if button == "dismiss":
        return zone is not None and turn
    if button == "stance":
        return zone is None or (turn and not actor.turn_flags.get("banner_stance_changed") and not _now(engine, zone, "imperial_until"))
    if button == "pick":
        return True
    if zone is None:
        return False
    if button == "rally":
        return have >= _rally_cost(engine, actor, zone) and any(_needs_rally(engine, c) for c in _allies_in(engine, zone))
    if button == "advance":
        return have >= 4 and not _now(engine, zone, "advancing_until") and not _now(engine, zone, "imperial_until")
    if button == "move":
        return (aim is not None and _now(engine, zone, "advancing_until") and not placed.data(zone).get("carried") and turn
                and actor.turn_flags.get("banner_moved") is None and _banner_move_ok(engine, actor, zone, aim, 30))
    if button == "imperial":
        return have >= 8 and not _now(engine, zone, "imperial_until") and not any(c.condition_id == SPENT for c in actor.conditions.values())
    return None


def _rally_cost(engine: Any, actor: Any, zone: Any) -> int:
    """"Rally the Line costs 0 Qi once per round" under Imperial Standard of Heaven."""
    free = _now(engine, zone, "imperial_until") and actor.turn_flags.get(f"banner_free_rally_round_{engine.state.round_number}") is None
    return 0 if free else 2


def _needs_rally(engine: Any, creature: Any) -> bool:
    """"A creature can receive the Temporary Hit Points from one Rally per round": not one already rallied this round (a key with "_round_" survives the turn reset)."""
    return not creature.turn_flags.get(f"banner_rallied_round_{engine.state.round_number}")


def _banner_move_ok(engine: Any, owner: Any, zone: Any, cell: Any, feet: int) -> bool:
    return (engine.grid.distance_ft(zone.center, cell) <= feet and engine.grid.distance_ft(owner.position, cell) <= 60
            and placed.free_square(engine, cell))


# ------------------------------------------------------------------------------------------- raising, choosing, dismissing
@effect("banner_manifest")
def manifest(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    cell = owner.position if eff.get("carried") else getattr(ctx.intent, "destination", None)
    if kit is None or cell is None:
        ctx.rider("Manifest Command Banner: no square was chosen.")
        return
    for old in placed.of(engine, "standard", owner_id=owner.entity_id):  # "You may maintain one Command Banner"
        placed.drop(engine, old, "REPLACED")
    engine._spend_resource(owner, kit["pool"], 1, ctx.source)
    stances = _chosen(_config(owner), kit)
    carried = bool(eff.get("carried"))
    aura = AURA["base"]
    cells = [(cell.x, cell.y)] + [c for c in ((p.x, p.y) for p in placed.area(engine, cell, "sphere", aura)) if c != (cell.x, cell.y)]
    data = {"owner": owner.entity_id, "stances": stances, "carried": carried, "advancing_until": None, "imperial_until": None, "held": []}
    zone = placed.place(engine, owner, source=kit["source"], tag="standard", cells=cells, numbers=kit["numbers"], duration_rounds=ROUNDS, shape="sphere", size_ft=aura,
                 name=_name(owner, data, aura, stances, []), color=COLOR, follows_owner=carried, placed=data)
    if not carried:
        from ..gate2_runtime_models import RuntimeObjectState
        from .objects import record_creator
        hp = 3 * int(kit['numbers'].get('cl') or 1)
        obj = RuntimeObjectState(object_id='object:banner:'+zone.zone_id,object_kind='command_banner',position=cell,
                                owner_id=owner.entity_id,unattended=True,flammable=False,ac=14,current_hp=hp,maximum_hp=hp,
                                damage_immunities=('POISON','PSYCHIC'),destroyed=False,
                                component=record_creator({'name':owner.display_name+"'s Command Banner",'blocks':False,'size':'medium',
                                                          'source_cl':int(kit['numbers'].get('cl') or 1),'banner_zone':zone.zone_id},RAISE))
        engine._update_object(obj,ctx.source,owner.entity_id)
    _log(engine, ctx.source, owner, f"{owner.display_name} {'empowers the banner they carry' if carried else 'plants a Command Banner'}: aura {aura} feet, "
         f"Stance: {', '.join(STANCES[s] for s in stances)}.")



@effect("banner_dismiss")
def dismiss(ctx: Any, eff: dict[str, Any]) -> None:
    zone = _banner(ctx.engine, ctx.actor)
    if zone is not None:
        placed.drop(ctx.engine, zone, "DISMISSED")
        _log(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} lets the Command Banner go.")


def _chosen(config: dict[str, Any], kit: dict[str, Any]) -> list[str]:
    """The Stances the owner has chosen: one, or two different ones with Fourfold Formation (a default: Forward, then Guarded)."""
    cap = 2 if FOURFOLD in kit["owned"] else 1
    picked = [s for s in dict.fromkeys(config.get("stances") or ["forward"]) if s in STANCES][:cap]
    for fill in ("forward", "guarded"):
        if len(picked) < cap and fill not in picked:
            picked.append(fill)
    return picked


@effect("banner_stance")
def stance(ctx: Any, eff: dict[str, Any]) -> None:
    """Banner Stance: "Change Banner Stance once during each turn without using an action" (Fourfold Formation: "change either or both once")."""
    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    if kit is None:
        return
    chosen = _chosen({"stances": [s for s in eff.get("stances") or () if s in STANCES]}, kit)
    zone = _banner(engine, owner)
    if zone is not None:
        owner.turn_flags["banner_stance_changed"] = True
        _refresh(engine, zone, owner, stances=chosen)
    _set_config(engine, owner, ctx.source, stances=chosen)
    _log(engine, ctx.source, owner, f"{owner.display_name}'s Banner Stance: {', '.join(STANCES[s] for s in chosen)}.")


def _set_config(engine: Any, owner: Any, source: str, **changes: Any) -> None:
    config = {**_config(owner), **changes}
    stances = [s for s in config.get("stances") or ["forward"] if s in STANCES]
    config["label"] = "Command Banner Stance: " + ", ".join(STANCES[s] for s in stances) + f"; Formation Maneuver: {MANEUVERS[config.get('maneuver') or 'auto']}"
    engine._remove_condition(owner, SETUP, source)
    engine._apply_condition(owner, SETUP, source, owner.entity_id, expires_on="UNTIL_REMOVED", data=config)


@effect("banner_maneuver_pick")
def maneuver_pick(ctx: Any, eff: dict[str, Any]) -> None:
    _set_config(ctx.engine, ctx.actor, ctx.source, maneuver=str(eff["value"]))


# ------------------------------------------------------------------------------------------------------- free steps
def _grant_step(engine: Any, ally: Any, feet: int, source: str, owner: Any) -> None:
    """Offer the recipient an immediate native physical step; declining stores nothing."""
    if feet <= 0 or not ally.active:
        return
    kit = _kit(engine, owner)
    if kit is None:
        return
    from .rider_step import step
    action = engine.action_catalog.get(source) or kit['action']
    labels = {'banner:advance_together':'Advance Together','banner:imperial_advance':'Imperial Advance',
              'banner:follow_the_victor':'Follow the Victor','banner:maneuver':'Formation Maneuver',
              IMPERIAL:'Standard Cannot Fall', FOURFOLD:"Officer's Command", RALLY:'Rally the Line'}
    label = labels.get(source, action.display_name)
    inner = placed.context(engine, ally, source, kit['numbers'], action=action.model_copy(update={'display_name':label}))
    step(inner, {'type':'rider_step','distance_ft':feet,'no_oa':True,'label':label})


@hook("turn_start_choice")
def turn_started(engine: Any, actor: Any) -> None:
    for zone in placed.of(engine, "standard"):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not owner.active:
            continue
        if actor is owner:
            if _now(engine, zone, "imperial_until"):
                _imperial_advance(engine, owner, zone)
        if _now(engine, zone, "advancing_until") and _covers(engine, zone, actor):
            _grant_step(engine, actor, 5, "banner:advance_together", owner)  # Advance Together: "may move 5 feet without provoking"


def _imperial_advance(engine: Any, owner: Any, zone: Any) -> None:
    """Imperial Advance: at the start of the owner's turns up to two allies in the aura -- the farthest from any foe (a default: the text lets
    the owner choose) -- may move 10 feet without provoking."""
    from .needle import ask, checkpoint_id
    from .. import stealth
    allies = [a for a in _allies_in(engine, zone) if a is not owner]
    perceived = [a.entity_id for a in allies if stealth.sees(engine, owner, a)]
    chosen = ask(engine, engine._active_intent, checkpoint_id(engine,'imperial_advance',zone.zone_id), owner,
                 'choice:needle.imperial_advance',[a.entity_id for a in allies],maximum=2,minimum=0,
                 default_count=min(2,len(perceived)),preferred=perceived,automatic_options=perceived,
                 labels={a.entity_id:a.display_name for a in allies},prompt='Imperial Advance: choose up to two allies to move now')
    picked = [engine.state.actors[aid] for aid in chosen]
    for ally in picked:
        _grant_step(engine, ally, 10, "banner:imperial_advance", owner)
    if picked:
        _log(engine, "banner:imperial_advance", owner, f"Imperial Advance: {', '.join(a.display_name for a in picked)} may move 10 feet without provoking.", targets=picked)


# ----------------------------------------------------------------------------------------------------------- the rally
@effect("banner_rally")
def rally(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    kit, zone = _kit(engine, owner), _banner(engine, owner)
    if kit is None or zone is None:
        ctx.rider("Rally the Line needs a Command Banner.")
        return
    cost = _rally_cost(engine, owner, zone)
    if cost:
        engine._spend_resource(owner, kit["pool"], cost, ctx.source)
    else:
        owner.turn_flags[f"banner_free_rally_round_{engine.state.round_number}"] = True
    amount = _pb(kit) + int(kit["numbers"].get("key_mod") or 0)
    from .needle import ask, checkpoint_id
    from .. import stealth
    eligible = [a for a in _allies_in(engine, zone) if _needs_rally(engine,a)]
    perceived = [a.entity_id for a in eligible if a is owner or stealth.sees(engine,owner,a)]
    selected = ask(engine,ctx.intent,checkpoint_id(engine,'rally_allies',zone.zone_id),owner,
                   'choice:needle.rally_allies',[a.entity_id for a in eligible],minimum=0,maximum=len(eligible),
                   default_count=len(perceived),preferred=perceived,automatic_options=perceived,
                   labels={a.entity_id:a.display_name for a in eligible},prompt='Rally the Line: choose allies who receive Temporary Hit Points and may step now')
    rallied = []
    for ally in [engine.state.actors[aid] for aid in selected]:
        if not _needs_rally(engine, ally):
            continue
        ally.turn_flags[f"banner_rallied_round_{engine.state.round_number}"] = True  # "one Rally per creature per round"
        if amount > 0:
            engine._grant_temp_hp(ally, amount, ctx.source, owner.entity_id)
        _grant_step(engine, ally, 5, ctx.source, owner)
        rallied.append(ally)
    _log(engine, ctx.source, owner, f"Rally the Line: {', '.join(a.display_name for a in rallied)} gain {amount} Temporary Hit Points and may move 5 feet without provoking.",
         targets=rallied)


# ---------------------------------------------------------------------------------------------- advancing and imperial
@effect("banner_advance")
def advance(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    kit, zone = _kit(engine, owner), _banner(engine, owner)
    if kit is None or zone is None:
        ctx.rider("Advancing Standard needs a Command Banner.")
        return
    engine._spend_resource(owner, kit["pool"], 4, ctx.source)
    _refresh(engine, zone, owner, advancing_until=engine.state.round_number + MINUTE)
    _log(engine, ctx.source, owner, "Advancing Standard: the aura grows to 20 feet for a minute; the banner flies (30 feet, Hover) and each ally in the aura may step 5 feet at the start of its turn.")


@effect("banner_move")
def move(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    zone, cell = _banner(engine, owner), getattr(ctx.intent, "destination", None)
    if zone is None or cell is None or not _banner_move_ok(engine, owner, zone, cell, 30):
        ctx.rider("Move the Banner: the square is out of reach.")
        return
    owner.turn_flags["banner_moved"] = True  # "Once during each turn, move the Banner up to 30 feet without using an action"
    _refresh(engine, zone, owner, centre=cell)
    _log(engine, ctx.source, owner, f"{owner.display_name} moves the Command Banner to ({cell.x}, {cell.y}).")


@effect("banner_imperial")
def imperial(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    kit, zone = _kit(engine, owner), _banner(engine, owner)
    if kit is None or zone is None:
        ctx.rider("Imperial Standard of Heaven needs a Command Banner.")
        return
    engine._spend_resource(owner, kit["pool"], 8, ctx.source)
    engine._apply_condition(owner, SPENT, ctx.source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Imperial Standard of Heaven used this scene"})  # "Limit: Once per scene": the fight is the scene
    from .needle import ask,checkpoint_id
    from .. import stealth
    allies=[a for a in engine.state.actors.values() if a.active and a.team_id==owner.team_id]
    perceived=[a.entity_id for a in allies if a is owner or stealth.sees(engine,owner,a)]
    chosen=ask(engine,ctx.intent,checkpoint_id(engine,'imperial_allies',zone.zone_id),owner,
               'choice:needle.imperial_allies',[a.entity_id for a in allies],minimum=0,maximum=len(allies),
               preferred=perceived,automatic_options=perceived,default_count=len(perceived),
               labels={a.entity_id:a.display_name for a in allies},prompt='Imperial Standard: choose allies who gain its defenses and ignore difficult terrain')
    until = engine.state.round_number + MINUTE
    _refresh(engine, zone, owner, imperial_until=until, advancing_until=until, held=[],imperial_chosen=chosen)
    _log(engine, ctx.source, owner, "Imperial Standard of Heaven: aura 40 feet for a minute, every Stance, +1 Armor Class and Advantage against Frightened, Prone and "
         "forced movement for the allies in it; Advancing Standard runs free; Rally the Line is free once a round; Officer's Command costs 1 Qi.")


# ------------------------------------------------------------------------------------------------- what a Stance gives
@hook("speed")
def forward_speed(engine: Any, actor: Any) -> int | None:
    return 5 if any(placed.of(engine, "standard")) and _has_stance(engine, actor, "forward") else None  # Forward: +5 feet of Speed


@hook("ac")
def guarded_ac(engine: Any, target: Any) -> int | None:
    if not placed.of(engine, "standard"):
        return None
    total = 0
    if getattr(engine, "_typed_oa_attacker", None) and _has_stance(engine, target, "guarded"):
        total += 1  # Guarded: "+1 AC against Opportunity Attacks"
    if _imperial_over(engine, target) is not None:
        total += 1  # Imperial Standard of Heaven: "Chosen allies gain +1 AC"
    return total or None


@hook("save")
def steady_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    engine = ctx.engine
    braced = [iid for iid, c in subject.conditions.items() if c.condition_id == BRACE]
    if braced:  # Brace is used up by the first saving throw
        condition = subject.conditions.pop(braced[0])
        engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": BRACE, "instance_id": braced[0], "reason": "CONSUMED"})
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    if not placed.of(engine, "standard") or ctx.actor.team_id == subject.team_id:
        return None
    words = {str(name).lower() for name in named or ()}
    if words & {"frightened", "prone"} and _has_stance(engine, subject, "steady"):
        return {"bonus": 0, "modes": ["ADVANTAGE"]}  # Steady: Advantage against being Frightened and knocked Prone
    if words & {"frightened", "prone", "forced_movement"} and _imperial_over(engine, subject) is not None:
        return {"bonus": 0, "modes": ["ADVANTAGE"]}  # Imperial Standard of Heaven: the same against forced movement too
    return None


@hook("after_save")
def hold_formation(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Hold Formation (Reaction, 1 Qi, once per round): an ally in the aura fails a save against Frightened, Prone or forced movement -- add the
    Proficiency Bonus; "not the same save more than once" (a save is one roll here), "not death, breakthrough or training checks"."""
    engine = ctx.engine
    if not failed or not placed.of(engine, "standard") or ctx.actor.team_id == subject.team_id:
        return
    if not ({str(name).lower() for name in named or ()} & {"frightened", "prone", "forced_movement"}):
        return
    from .. import typed_reactions

    last = next((e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED"), None)
    if last is None:
        return
    payload = last.payload or {}
    total, dc = int(payload.get("total") or 0), int(payload.get("dc") or 0)
    for zone in _banners_over(engine, subject):
        owner = engine.state.actors.get(zone.owner_id)
        kit = _kit(engine, owner) if owner is not None else None
        if kit is None or RALLY not in kit["owned"] or not owner.reaction_available or owner.turn_flags.get(f"banner_hold_round_{engine.state.round_number}"):
            continue
        if owner.resources.get(kit["pool"], 0) < 1 or total < 0 or total + _pb(kit) < dc:
            continue  # it would not turn the save (an automatic failure, total below 0, cannot be helped)
        row = {"feature_id": RALLY, "name": "Hold Formation", "ask": True}
        if not typed_reactions._can_react(engine, owner) or not typed_reactions._consent(engine, row, owner, "SAVE_FAILED"):
            continue
        with activation(engine, owner, RALLY):
            typed_reactions._open(engine, row, owner, (subject.entity_id,), "SAVE_FAILED")  # spends the Reaction
            engine._spend_resource(owner, kit["pool"], 1, RALLY)
            owner.turn_flags[f"banner_hold_round_{engine.state.round_number}"] = True  # "Limit: Once per round"
            engine._typed_roll_outcome = {**(getattr(engine, "_typed_roll_outcome", None) or {}), subject.entity_id: "success"}
            engine._append_event("REACTION_RESOLVED", RALLY, actor_id=owner.entity_id, target_ids=(subject.entity_id,), payload={"checkpoint": "SAVE_FAILED"})
            _log(engine, RALLY, owner, f"Hold Formation: {owner.display_name} adds {_pb(kit)} to {subject.display_name}'s save ({total} + {_pb(kit)} against {dc}): it succeeds.", targets=(subject,))
            return


# ------------------------------------------------------------------------------------------ Formation Maneuver and friends
@hook("event")
def damage_dealt(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type != "DAMAGE_COMMITTED" or int(payload.get("reduced_to") or 0) <= 0 or not placed.of(engine, "standard"):
        return None
    dealer, hurt = engine.state.actors.get(kwargs.get("actor_id") or ""), engine.state.actors.get((kwargs.get("target_ids") or ("",))[0])
    if dealer is None or hurt is None or not dealer.active or dealer.team_id == hurt.team_id:
        return None
    for zone in placed.of(engine, "standard"):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not _now(engine, zone, "advancing_until") or not _covers(engine, zone, dealer):
            continue
        key = f"banner_maneuver_round_{engine.state.round_number}_{engine.state.current_actor_id}"
        if owner.turn_flags.get(key):
            continue  # "Once per turn"
        owner.turn_flags[key] = True
        _maneuver(engine, owner, zone, dealer, hurt)
    return None


@hook("after_hit")
def follow_the_victor(ctx: Any, target: Any, kind: str) -> None:
    """Follow the Victor (once per round): after an ally in the aura hits a hostile, a different ally in the aura moves 5 feet."""
    engine, hitter, foe = ctx.engine, ctx.actor, target
    if foe is None or not hitter.active or hitter.team_id == foe.team_id or not placed.of(engine, "standard"):
        return
    for zone in placed.of(engine, "standard"):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not _now(engine, zone, "imperial_until") or not _covers(engine, zone, hitter):
            continue
        key = f"banner_victor_round_{engine.state.round_number}"
        if owner.turn_flags.get(key):
            continue
        others = [a for a in _allies_in(engine, zone) if a is not hitter]
        if not others:
            continue
        from .needle import ask,checkpoint_id
        from .. import stealth
        perceived=[a.entity_id for a in others if a is owner or stealth.sees(engine,owner,a)]
        selected=ask(engine,ctx.intent,checkpoint_id(engine,'follow_the_victor',zone.zone_id),owner,
                     'choice:needle.follow_the_victor',[a.entity_id for a in others],minimum=0,maximum=1,
                     preferred=perceived[:1],automatic_options=perceived,default_count=min(1,len(perceived)),
                     labels={a.entity_id:a.display_name for a in others},prompt='Follow the Victor: choose a different ally to step now')
        if not selected:continue
        # A voluntary decline does not expend the once-per-round allowance.
        owner.turn_flags[key] = True
        follower=engine.state.actors[selected[0]]
        _grant_step(engine, follower, 5, "banner:follow_the_victor", owner)
        _log(engine, "banner:follow_the_victor", owner, f"Follow the Victor: {follower.display_name} may move 5 feet without provoking.", targets=(follower,))


def _maneuver(engine: Any, owner: Any, zone: Any, ally: Any, hurt: Any) -> None:
    from ..typed_executor import run_effects

    choice = _config(owner).get("maneuver") or "auto"
    if choice == "off":
        return
    if choice == "auto":  # a default: Temporary Hit Points for a hurt ally, no Reactions for a foe that has one, else a step
        can_deny = hurt.reaction_available and hurt.active
        choice = "temp" if ally.current_hp * 2 <= ally.maximum_hp else "deny" if can_deny else "step"
    kit = _kit(engine, owner)
    source = "banner:maneuver"
    if choice == "step":
        _grant_step(engine, ally, 5, source, owner)
        text = f"{ally.display_name} may move 5 feet without provoking"
    elif choice == "temp" and kit is not None:
        engine._grant_temp_hp(ally, _pb(kit), source, owner.entity_id)
        text = f"{ally.display_name} gains {_pb(kit)} Temporary Hit Points"
    elif choice == "push":
        if engine._footprint(hurt).width_cells > engine._footprint(ally).width_cells + 1:
            return
        text = f"{hurt.display_name} is pushed 5 feet" if _push_from(engine, ally, hurt, source) else f"{hurt.display_name} has no room to be pushed"
    elif choice == "deny":
        inner = placed.context(engine, owner, source, (kit or {}).get("numbers") or {}, [hurt], action=(kit or {}).get("action"))
        run_effects(inner, [{"type": "condition", "applies_to": "target", "condition": "reaction_denied", "expires_on": "START_OF_TARGET_NEXT_TURN"}])
        text = f"{hurt.display_name} cannot take Reactions until the start of its next turn"
    else:
        cell = _best_cell(engine, owner, zone, 10, toward=ally)
        if cell is None:
            return
        _refresh(engine, zone, owner, centre=cell)
        text = f"the banner moves to ({cell.x}, {cell.y})"
    _log(engine, source, owner, f"Formation Maneuver ({MANEUVERS[choice]}): {text}.", targets=(ally, hurt))


def _push_from(engine: Any, pusher: Any, target: Any, source: str) -> bool:
    """A push of 5 feet directly away from the pusher, onto a free square (the engine's own forced move has no caster to push from here)."""
    from ..gate2_runtime_models import Position
    from . import vessel

    dx = (target.position.x > pusher.position.x) - (target.position.x < pusher.position.x)
    dy = (target.position.y > pusher.position.y) - (target.position.y < pusher.position.y)
    cell = map_position(engine, target.position.x + dx, target.position.y + dy)
    if cell is None or (dx, dy) == (0, 0) or not placed.free_square(engine, cell):
        return False
    vessel.shift(engine, target, cell, source)
    return True


def _best_cell(engine: Any, owner: Any, zone: Any, feet: int, toward: Any = None) -> Any | None:
    """A free square within ``feet`` of the banner that keeps the most allies in the aura, then nearest ``toward`` (or the nearest foe)."""
    from ..gate2_runtime_models import Position

    reach = feet // engine.grid.square_size_ft
    aura = _aura(engine, zone)
    best: tuple[Any, ...] | None = None
    for x in range(zone.center.x - reach, zone.center.x + reach + 1):
        for y in range(zone.center.y - reach, zone.center.y + reach + 1):
            cell = Position(x=x, y=y)
            if (x, y) == (zone.center.x, zone.center.y) or not placed.free_square(engine, cell) or engine.grid.distance_ft(zone.center, cell) > feet:
                continue
            inside = sum(1 for a in engine.state.actors.values() if a.active and a.team_id == owner.team_id and engine.grid.distance_ft(a.position, cell) <= aura)
            aim = engine.grid.distance_ft(cell, toward.position) if toward is not None else _nearest_foe_ft(engine, owner, cell)
            row = (-inside, aim, x, y)
            if best is None or row < best:
                best = row
    return Position(x=best[2], y=best[3]) if best is not None else None


# ---------------------------------------------------------------------------------------------- Officer's Command
@hook("reaction_subject_allowed")
def officers_command_subject(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    """Officer's Command answers an ally that begins its turn inside the aura of the reactor's own Command Banner (the reading's own 10 feet
    was a guess; the aura is the banner's)."""
    if row.get("feature_id") != FOURFOLD:
        return None
    zone = _banner(engine, reactor)
    return zone is not None and other is not None and _covers(engine, zone, other) and other is not reactor


@effect("banner_order")
def order(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects
    from .. import unmaking

    engine, owner, ally = ctx.engine, ctx.actor, ctx.target
    zone, kit = _banner(engine, owner), _kit(engine, owner)
    if zone is None or ally is None or kit is None or not _covers(engine, zone, ally):
        ctx.rider("Officer's Command: no ally begins its turn in the aura of a Command Banner.")
        return
    if _now(engine, zone, "imperial_until"):
        engine._gain_resource(owner, kit["pool"], 1, ctx.source)  # "Officer's Command costs 1 Qi" (the row paid its 2)
    kind = str(eff.get("order") or "auto")
    if kind == "auto":
        kind = "rise" if _prone(ally) else "courage" if _frightened(ally) else "seize"
    inner = placed.context(engine, owner, ctx.source, kit["numbers"], [ally], action=ctx.action)
    if kind == "reposition":
        _grant_step(engine, ally, 10, ctx.source, owner)
    elif kind == "seize":
        run_effects(inner, [{"type": "advantage", "applies_to": "target", "on": "its next attack roll", "duration": "until_end_of_turn"}])
    elif kind == "brace":
        # "Advantage on its next saving throw before the start of its following turn" (typed_executor's advantage effect only knows saves named by
        # condition, so the banner keeps its own condition and reads it in ``steady_save``).
        engine._remove_condition(ally, BRACE, ctx.source)
        engine._apply_condition(ally, BRACE, ctx.source, owner.entity_id, expires_on="START_OF_TARGET_NEXT_TURN",
                                data={"label": "Braced by Officer's Command: Advantage on its next saving throw"})
    elif kind == "rise":
        for condition in [c for c in ally.conditions.values() if c.condition_id.endswith(".prone")]:
            engine._remove_condition(ally, condition.condition_id, ctx.source)  # "Stand from Prone without spending movement"
    elif kind == "courage":
        _remember_courage(engine, owner, ally, ctx.source, unmaking.cultivation_level)
    elif kind == "shift":
        cell = _best_cell(engine, owner, zone, 20, toward=ally)
        if cell is not None:
            _refresh(engine, zone, owner, centre=cell)
    _log(engine, ctx.source, owner, f"Officer's Command ({ORDERS.get(kind, kind)}) for {ally.display_name}.", targets=(ally,))


def _prone(creature: Any) -> bool:
    return any(c.condition_id.endswith(".prone") for c in creature.conditions.values())


def _frightened(creature: Any) -> bool:
    return any(c.condition_id.endswith(".frightened") for c in creature.conditions.values())


def _remember_courage(engine: Any, owner: Any, ally: Any, source: str, level: Any) -> None:
    """"End a Frightened effect from a source of lower or equal Cultivation Level; against a higher CL, repeat the save with Advantage" (the save
    the effect came from, when it remembers one)."""
    mine = level(engine, owner)
    for iid, condition in list(ally.conditions.items()):
        if not condition.condition_id.endswith(".frightened"):
            continue
        source_actor = engine.state.actors.get(condition.source_actor_id or "")
        if source_actor is None or level(engine, source_actor) <= mine:
            engine._remove_condition(ally, condition.condition_id, source)
            continue
        save = (condition.data or {}).get("origin_save") or (condition.data or {}).get("repeat_save") or {}
        if save.get("ability") and save.get("dc"):
            roll = engine._roll_save(ally, str(save["ability"]).upper(), int(save["dc"]), source, extra_mode="ADVANTAGE")
            if roll.total >= int(save["dc"]):
                engine._remove_condition(ally, condition.condition_id, source)


# ------------------------------------------------------------------------------------------------ Standard Cannot Fall
@hook("would_drop")
def cannot_fall(engine: Any, target: Any, pending: int, source_actor_id: str | None) -> int | None:
    """Standard Cannot Fall: "The first time each ally in the aura would be reduced to 0 Hit Points without being killed outright, it remains at
    1 Hit Point and may move 5 feet without provoking.  Each ally can benefit once per activation."  Killed outright: the damage left over
    after 0 HP is at least its Hit Point maximum."""
    zone = _imperial_aura_over(engine, target)
    if zone is None or target.entity_id in (placed.data(zone).get("held") or ()):
        return None
    from ..damage_allocation import available_temporary_hp, maximum_packet_before_hp_floor
    temporary = available_temporary_hp(engine, target, pending, source_actor_id)
    if pending - temporary - target.current_hp >= target.maximum_hp:
        return None
    owner = engine.state.actors.get(zone.owner_id)
    placed.update(engine, zone, held=[*(placed.data(zone).get("held") or ()), target.entity_id])
    if owner is not None:
        _log(engine, IMPERIAL, owner, f"Standard Cannot Fall: {target.display_name} stays at 1 Hit Point and may move 5 feet without provoking.", targets=(target,))
        engine._apply_condition(target,STEP,IMPERIAL,owner.entity_id,expires_on='UNTIL_REMOVED',data={'feet':5,'pending_damage_step':True})
    return maximum_packet_before_hp_floor(engine, target, pending, 1, source_actor_id)


@hook('difficult_exempt')
def imperial_ground(engine, actor):
    if _imperial_over(engine, actor):
        from .. import zones
        return {(p.x,p.y) for z in zones.typed_zones(engine) if zones.zone_is_difficult(engine,z,actor) for p in z.affected_cells}


@hook('event')
def survival_step(engine,event_type,kwargs):
    if event_type != 'DAMAGE_COMMITTED':return
    for aid in kwargs.get('target_ids') or ():
        ally=engine.state.actors.get(aid)
        if not ally or ally.current_hp <= 0:continue
        for bar in list(ally.conditions.values()):
            if bar.condition_id != STEP or not bar.data.get('pending_damage_step'):continue
            owner=engine.state.actors.get(bar.source_actor_id or '')
            engine._remove_condition(ally,STEP,bar.source_definition_id)
            if owner:_grant_step(engine,ally,5,bar.source_definition_id,owner)


@hook('event',nested=True)
def banner_object_sync(engine,event_type,kwargs):
    payload=kwargs.get('payload') or {}
    if event_type == 'OBJECT_UPDATED':
        record=payload.get('object') or {}
        zid=(record.get('component') or {}).get('banner_zone')
        zone=engine.state.zones.get(zid or '')
        if zone and zone.active and record.get('destroyed'):placed.drop(engine,zone,'BANNER_DESTROYED')
    elif event_type in {'ZONE_CREATED','ZONE_REMOVED'}:
        zid=payload.get('zone_id') or (payload.get('zone') or {}).get('zone_id')
        if not zid:return
        obj=engine.state.objects.get('object:banner:'+zid)
        if not obj or obj.destroyed:return
        if event_type == 'ZONE_REMOVED':
            engine._update_object(obj.model_copy(update={'current_hp':0,'destroyed':True}),RAISE,obj.owner_id)
        else:
            zone=engine.state.zones.get(zid)
            if zone and obj.position != zone.center:
                engine._update_object(obj.model_copy(update={'position':zone.center}),RAISE,obj.owner_id)


@hook('object_hp_floor')
def imperial_banner_survival(engine,actor,obj,taken,source):
    zid=(obj.component or {}).get('banner_zone')
    zone=engine.state.zones.get(zid or '')
    if zone and zone.active and _now(engine,zone,'imperial_until'):
        from ..unmaking import cultivation_level
        action=engine.action_catalog.get(source)
        printed=((action.parameters or {}).get('typed') or {}).get('numbers',{}).get('cl') if action else None
        source_cl=printed if type(printed) is int and printed>0 else cultivation_level(engine,actor)
        if source_cl<int((obj.component or {}).get('source_cl') or 1):return 1
