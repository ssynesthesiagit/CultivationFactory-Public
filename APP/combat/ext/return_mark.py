"""The Space sphere's Safe Return Mark (owner 2026-09-29: "i want everything we can automated"): a marked space to teleport back to.  Owner rules:
LocalSources/04_spheres_talents/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md ("Safe Return Mark", Anchor Art) and
authority/typed_mechanics/rules_text.json.  Where the text is silent a default is named below; Spheres 5e and D&D 5.5e were not needed.

Rules (Bonus Action, Range: Self, Duration: 1 minute, Cost: 1 CP):
- "Mark your current space as a return point."  A placement (combat/ext/placed.py, tag "return") on the map for 1 minute (10 rounds).  Default:
  a new mark replaces the creature's old one (the text sets no number of marks).
- "Once before the mark ends, when you use Fold Step, Blink Guard, Short Swap, or another Fold Art, you may instead teleport to the marked space if
  it is within 120 feet and unoccupied."  A second button per Fold Art the creature knows: "Fold Step to the Safe Return Mark (1 CP)" (Bonus Action) and
  "Short Swap to the Safe Return Mark (1 CP)" (Action) cost what the Art costs and put the creature on the mark instead of where the Art would (a
  teleport like any other: combat/ext/seal.py's sealed roads and the teleport rules apply).  Blink Guard is a Reaction whose destination its own
  answer picks and the other Fold Arts are not listed by name: not offered (a rider). At CL 10, Short Swap also offers
  its printed Bonus Action form for 2 CP (A2SPACE). The mark is used up by the jump.
- "If the marked space becomes occupied, sealed, or invalid, the mark ends."  It ends when a creature other than the marker ends a move on it (the
  square is then occupied); sealed and invalid are the GM's (a rider).  The marker may stand on it: it was marked from there.

Buttons (a player's; the built-in AI never teleports, combat/gate4_context.py).  Hooks added to the framework by this module: none (it uses
``compile_actions``, ``candidate_allowed`` and ``event``; the jump goes through typed_executor._teleport, so ``teleport_gate`` applies).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, placed

SAFE = "tianxia.talent.space.safe_return_mark"
ARTS = {"TAL_SPACE_FOLD_STEP": ("Fold Step", "BONUS_ACTION", 1), "tianxia.talent.space.short_swap": ("Short Swap", "ACTION", 1)}
MARK_CP = 1  # "Cost: 1 CP."
RANGE_FT = 120  # "within 120 feet"
ROUNDS = 10  # "Duration: 1 minute"
COLOR = "#5cc7c7"


def _kit(engine: Any, owner: Any) -> dict[str, Any] | None:
    for action in engine.action_catalog.values():
        params = action.parameters or {}
        if action.owner_id == owner.entity_id and params.get("return_kit"):
            typed = params.get("typed") or {}
            return {"action": action, "numbers": typed.get("numbers") or {}, "pool": params.get("return_pool") or "resource:core.qi",
                    "source": action.source_definition_id}
    return None


def _mark(engine: Any, owner: Any) -> Any | None:
    rows = placed.of(engine, "return", owner_id=owner.entity_id)
    return rows[-1] if rows else None


def _cell(zone: Any) -> Any:
    return zone.center


@hook("compile_actions")
def return_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned = set(info["owned_ids"])
    if SAFE not in owned:
        return None
    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")

    def make(key: str, name: str, effects: list[dict[str, Any]], economy: Any, **params: Any) -> Any:
        return ActionDefinition(
            source_definition_id=f"action:typed.{short}.{key}", display_name=name, owner_id=actor_id, economy=economy, resolution_kind="TYPED",
            target_kind="SELF", range_ft=None,
            parameters={"typed": {"effects": effects, "numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "source": SAFE},
                        "expected_damage": 0, "player_only": True, "return_kit": True, "return_pool": pool, **params})

    out = [make("return.mark", f"Safe Return Mark ({MARK_CP} CP)", [{"type": "return_mark"}], EconomyKind.BONUS_ACTION, return_button="mark")]
    swap_cl = next((int(((action.parameters or {}).get("typed") or {}).get("numbers", {}).get("cl") or 1)
                    for action in info.get("actions") or []
                    if ((action.parameters or {}).get("typed") or {}).get("source") == "tianxia.talent.space.short_swap"),
                   int(numbers.get("cl") or 1))
    for art_id, (label, economy, price) in ARTS.items():
        if art_id in owned:
            out.append(make(f"return.{label.lower().replace(' ', '_')}", f"{label} to the Safe Return Mark ({price} CP)", [{"type": "return_jump", "price": price}],
                            EconomyKind[economy], return_button="jump", return_price=price))
            if art_id == "tianxia.talent.space.short_swap" and swap_cl >= 10:
                out.append(make("return.short_swap_bonus", "Short Swap to the Safe Return Mark (Bonus Action, 2 CP)",
                                [{"type": "return_jump", "price": 2}], EconomyKind.BONUS_ACTION,
                                return_button="jump", return_price=2))
    return out


@hook("candidate_allowed")
def return_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    button = params.get("return_button")
    if not button:
        return None
    have = actor.resources.get(params.get("return_pool") or "resource:core.qi", 0)
    if button == "mark":
        return have >= MARK_CP
    zone = _mark(engine, actor)
    if zone is None or have < int(params.get("return_price") or 1):
        return False
    from ..typed_executor import condition_rules

    cell = _cell(zone)
    return (cell != actor.position and engine.grid.distance_ft(actor.position, cell) <= RANGE_FT and not placed.occupied(engine, cell)
            and not any(row.get("no_teleport") for row in condition_rules(actor)))


@effect("return_mark")
def mark(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    if kit is None:
        return
    engine._spend_resource(owner, kit["pool"], MARK_CP, ctx.source)
    for old in placed.of(engine, "return", owner_id=owner.entity_id):
        placed.drop(engine, old, "REPLACED")
    here = owner.position
    placed.place(engine, owner, source=kit["source"], tag="return", cells=here, numbers=kit["numbers"], duration_rounds=ROUNDS, color=COLOR,
                 name=f"{owner.display_name}'s Safe Return Mark (1 minute; a Fold Art can take them back here from within {RANGE_FT} feet)",
                 placed={"owner": owner.entity_id})
    placed.note(engine, ctx.source, owner, f"{owner.display_name} marks ({here.x}, {here.y}) as a return point for 1 minute.")


@effect("return_jump")
def jump(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    engine, owner = ctx.engine, ctx.actor
    kit, zone = _kit(engine, owner), _mark(engine, owner)
    if kit is None or zone is None:
        ctx.rider("Safe Return Mark: there is no mark to return to.")
        return
    engine._spend_resource(owner, kit["pool"], int(eff.get("price") or 1), ctx.source)
    cell = _cell(zone)
    typed_executor._teleport(ctx, cell)
    if owner.position == cell:
        placed.drop(engine, zone, "USED")  # "Once before the mark ends"
        placed.note(engine, ctx.source, owner, f"{owner.display_name} returns to the mark at ({cell.x}, {cell.y}); the mark is used up.")
    else:
        placed.note(engine, ctx.source, owner, f"{owner.display_name} cannot get back to the mark at ({cell.x}, {cell.y}); it stands.")


@hook("event")
def marks_taken(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"If the marked space becomes occupied ... the mark ends."  A creature other than its marker that ends a move on it takes it."""
    if event_type != "MOVEMENT_COMMITTED" or not placed.of(engine, "return"):
        return None
    from ..gate2_runtime_models import Position

    path = (kwargs.get("payload") or {}).get("path") or []
    if not path:
        return None
    last = path[-1]
    end = last if isinstance(last, Position) else Position(x=int(last["x"]), y=int(last["y"])) if isinstance(last, dict) else Position(x=int(last[0]), y=int(last[1]))
    for zone in placed.of(engine, "return"):
        if zone.owner_id != kwargs.get("actor_id") and zone.center == end:
            placed.drop(engine, zone, "OCCUPIED")
            owner = engine.state.actors.get(zone.owner_id)
            if owner is not None:
                placed.note(engine, zone.source_definition_id, owner, f"{owner.display_name}'s Safe Return Mark ends: another creature stands on the marked space.")
    return None
