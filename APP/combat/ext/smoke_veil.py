"""The Smoke Veil's own printed shape, density and second veil (AUTO43 automation lane, 2026-10-05).

Rules text (owner's Sphere Compendium, "Sphere of Smoke", authority/typed_mechanics/rules_text.json):

  Smoke Veil    "You create a veil of real supernatural smoke in an unoccupied space you can see within range. The area
                 is Lightly Obscured. ... At CL 5, the area becomes two connected 10-foot cubes. At CL 11, it becomes
                 three connected 10-foot cubes. At CL 17, it becomes four connected 10-foot cubes."
  Dense Smoke   "Dense smoke is Heavily Obscured for creatures that rely on sight."
  Dense Veil    "When you create or move your Smoke Veil, it becomes Dense until the start of your next turn. If you
                 maintain the same Smoke Veil without moving it on your next turn, it remains Dense."
  Second Veil   "When you create a Smoke Veil, create one additional 5-foot cube of smoke within 30 feet of the original
                 veil. This second veil follows the same duration and concentration. At CL 5, the second veil becomes a
                 10-foot cube."
  Wall of Smoke "When you create Smoke Veil, arrange its cubes as a wall. Each cube must share a face with another cube.
                 While the wall is Dense, ranged attacks that pass through at least two of its cubes have Disadvantage if
                 the attacker relies on sight."

Blacken the Flame
                 "You gain a new Smoke Response. Action Type: Reaction. Trigger: Fire damage is dealt inside your Smoke
                 Veil or through your Smoke Veil. Spend one Smoke Trace on the source, target, or affected space.
                 Reduce the Fire damage dealt to one creature or object by: 1d6 + your key ability modifier. The
                 reduction increases to 2d6 at CL 5, 3d6 at CL 11, and 4d6 at CL 17."
  Smother the Breath
                 "Failed Save: ... It has Disadvantage on the triggering d20 Test if the trigger includes one. If the
                 trigger does not include a d20 Test, the creature cannot take Reactions until the start of its next
                 turn."

How each printed line is resolved:

  cubes        The printed CL table is typed data (``blocks_by_cl`` on the area, authority/typed_mechanics/reviewed_final.d
               /auto_smoke.json) read by the general area seam combat/factory_compiler.py ``_area_blocks_for_cl``. The
               geometry is general as well: combat/zones.py ``block_cells`` lays ``blocks`` cube-shaped blocks of ``size_ft``
               in one straight run whose blocks share a face, across the line from the area's user through its aim point,
               so the veil reads as the screen its printed words describe ("arrange its cubes as a wall", each cube sharing
               a face with another). One block is the plain cube, so a record with no table is unchanged. The count is an
               integer in the area's own profile, so a table commit and reload keep the same squares.
  Dense        Dense smoke is Heavily Obscured, which combat/zones.py ``_heavy`` already applies: an attack at a creature
               inside a Dense area has Disadvantage and an attack out of it has Advantage. The printed window is a
               refresh, not a lapse -- creating or moving the veil makes it Dense, and maintaining the same veil without
               moving it "remains Dense" at the start of the owner's next turn, so a veil of a Dense Veil owner is Dense for
               as long as it stands (its Concentration, or a move that recreates it, are the only things that end or restart
               it). That is one written value on the area (``obscured: heavy``), not a per-turn timer: it survives a table
               commit and reload and schedules no event.
  second cube  The extra cube is a second area of the same name, size and duration, sharing the first's Concentration, so
               ending Concentration ends both (combat/zones.py create's concentration_link). The printed text says "within
               30 feet of the original veil" and names no square, so the square is the owner's to pick, asked through the
               bounded choice transport (``needle.ask``, the same Ask me / Auto channel a reaction uses) with every free
               square within 30 feet of the veil offered and the veil's own squares removed. The options ride the
               established ``needle.cell_id`` grid id, so the table offers the legal squares highlighted on the main map
               to click (combat/choice_presentation.py decodes them), and each is labelled with its distance east/west
               and north/south of the first veil in feet, which names one square and only that square. A player is
               asked; an AI answers for itself; declining -- or a fight nobody is answering -- leaves the one veil Smoke
               Veil already made.
  wall         The inherited wall reader checks crossing, but does not enforce the printed two-cube,
               Dense-only, ranged-only condition. Wall of Smoke remains CORE pending that shared attack geometry work.

Inert without the owning talent: each effect is registered under its own type and does nothing unless the reviewed
modifier or failed-save row that carries it was compiled onto that character's own abilities, and the one hook
(``final_damage``) asks combat/ext/fight_ownership.py ``owns_block`` before it does anything. No other character, no
other ability and no old saved fight changes. This module registers four effect types, one ``compile_block`` row, one
``final_damage`` subscriber and one ``choice_reactors`` query (who the table may have to ask, see ``soot_owners``).
"""

from __future__ import annotations

from ..paid_relocation import activation

import copy
from typing import Any

from . import effect, hook

#: The records whose printed lines this module resolves, named for the evidence a reader needs.
VEIL = "SMOKE_BASE_SMOKE_VEIL"
DENSE = "TAL_SMOKE_DENSE_VEIL"
SECOND = "TAL_SMOKE_SECOND_VEIL"

SECOND_CHOICE = "choice:needle.smoke_second_veil"
SECOND_REACH_FT = 30  # "within 30 feet of the original veil"


@hook("match_start")
def record_cube_placement_policy(engine: Any) -> None:
    """Bind whole-cube placement for new fights; unstamped saves keep clipped cubes."""
    if not any(row.get("id") == SECOND for bundle in engine.typed_bundle_documents
               for row in bundle.get("modifiers") or []):
        return
    for event in engine.events:
        if event.event_type == "MATCH_CREATED":
            event.payload["smoke_cube_placement_policy"] = 1
            return


def whole_cube_placement(engine: Any) -> bool:
    """Read this fight's genesis, including after commit/reload; no new state schema."""
    return any(event.event_type == "MATCH_CREATED" and
               event.payload.get("smoke_cube_placement_policy") == 1
               for event in engine.events)


def veils(engine: Any, actor: Any) -> list[Any]:
    """Every Smoke Veil the actor has standing, newest first (shared with the tests)."""
    from .. import zones

    return [zone for zone in zones.typed_zones(engine)
            if zone.owner_id == actor.entity_id and VEIL in (zone.source_definition_id or "")
            and (zone.trigger_profile.get("name") or "") == "Smoke Veil" and zone.active
            and not zone.trigger_profile.get("anchor_id")]


def _just_made(engine: Any, actor: Any, source: str) -> Any | None:
    """The area this activation just made: the newest one of the activating action's own source."""
    from .. import zones

    made = [zone for zone in zones.typed_zones(engine)
            if zone.owner_id == actor.entity_id and zone.source_definition_id == source and zone.active]
    return made[-1] if made else None


@effect("smoke_dense_veil")
def dense_veil(ctx: Any, eff: dict[str, Any]) -> None:
    """Dense Veil: the veil this activation made (or moved) is Dense -- Heavily Obscured -- and stays so while it
    stands, because maintaining the same veil without moving it keeps it Dense. One written value; no timer."""
    from .. import zones

    veil = _just_made(ctx.engine, ctx.actor, ctx.source)
    if veil is None:
        ctx.rider("Dense Veil needs the Smoke Veil area.")
        return
    if veil.trigger_profile.get("obscured") == "heavy":
        return  # already Dense; republishing an unchanged area would only add noise to the log
    profile = copy.deepcopy(veil.trigger_profile)
    profile["obscured"] = "heavy"
    profile["visual"] = {**(profile.get("visual") or {}), "obscured": "heavy"}
    veil.trigger_profile = profile
    ctx.engine._append_event("ZONE_CREATED", ctx.source, actor_id=ctx.actor.entity_id,
                             payload={"zone": veil.model_dump(mode="json")})
    zones.sync_inside(ctx.engine, ctx.source)


@effect("smoke_second_veil")
def second_veil(ctx: Any, eff: dict[str, Any]) -> None:
    """Second Veil: "When you create a Smoke Veil, create one additional 5-foot cube of smoke within 30 feet of the
    original veil. This second veil follows the same duration and concentration. At CL 5, the second veil becomes a
    10-foot cube." One extra area, its size the printed CL table says (``size_ft_by_cl`` on the effect, read the way
    combat/factory_compiler.py ``_area_size_for_cl`` reads the same rows), on a square the owner picks; declining leaves
    the single printed veil."""
    from .. import zones
    from .needle import ask, cell_id, checkpoint_id

    first = _just_made(ctx.engine, ctx.actor, ctx.source)
    if first is None:
        ctx.rider("Second Veil needs the Smoke Veil area.")
        return
    cl = int(((ctx.typed or {}).get("numbers") or {}).get("cl") or 1)
    size = _second_size(eff, cl)
    reach = int(eff.get("within_ft") or SECOND_REACH_FT)
    occupied = {(cell.x, cell.y) for cell in first.affected_cells}
    squares = sorted((square for square in _free_squares(ctx, first, reach, size)
                      if (square.x, square.y) not in occupied),
                     key=lambda square: (ctx.engine.grid.distance_ft(first.center, square), square.x, square.y))
    # The established grid option id (combat/ext/needle.py ``cell_id``), which combat/choice_presentation.py
    # ``option_cell`` decodes, so this choice reaches the table as a real point-to-place question: the legal squares
    # are highlighted on the main map and clicked instead of read off a list. A private id spelled
    # "smoke-square:x:y" decodes to nothing, so the same question would have arrived as a flat list of words with no
    # map behind it.
    option_id = cell_id
    if not squares:
        if whole_cube_placement(ctx.engine):
            ctx.rider(f"Second Veil: no second {size}-foot cube of smoke is created because no unoccupied, "
                      f"unblocked space within {reach} feet of your Smoke Veil fits the whole cube inside the battlefield.")
        else:
            ctx.rider(f"Second Veil: every square within {reach} feet of your Smoke Veil is taken, so no second cube fits.")
        return
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "smoke_second_veil", ctx.source), ctx.actor,
                 SECOND_CHOICE, [option_id(square) for square in squares],
                 labels={option_id(square): _square_words(square, first.center, ctx.engine) for square in squares},
                 minimum=0, maximum=1, allow_decline=True, automatic=False, default="decline",
                 name="Second Veil", feature_id=SECOND,
                 prompt=(f"Second Veil: choose where to place the second cube of smoke, within {reach} feet of your "
                         f"Smoke Veil. It is {size} feet on a side"
                         f"{' at Cultivation Level 5 or higher' if size > 5 else ''}, lasts as long as the first veil and "
                         "shares your Concentration on it. Each option names how far the cube's middle square sits east "
                         "or west and north or south of your first veil, so every one is a different square. "
                         "Decline to leave one veil."))
    picked = next((square for square in squares if option_id(square) in chosen), None)
    if picked is None:
        return
    profile = copy.deepcopy(first.trigger_profile)
    profile.update({"shape": "cube", "size_ft": size, "blocks": 1, "second_veil": 1})
    _place(ctx, first, profile, zones._cells(ctx.engine, picked, {"shape": "cube", "size_ft": size}), picked)


def _second_size(eff: dict[str, Any], cl: int) -> int:
    """"create one additional 5-foot cube of smoke ... At CL 5, the second veil becomes a 10-foot cube." The table is
    typed data on the effect (``size_ft_by_cl`` rows ``[low_cl, high_cl, feet]``, the same shape and meaning
    combat/factory_compiler.py ``_area_size_for_cl`` reads); ``size_ft`` is the printed base when no row matches."""
    size = int(eff.get("size_ft") or 5)
    for low, high, feet in eff.get("size_ft_by_cl") or []:
        if int(low) <= cl <= int(high):
            return int(feet)
    return size


def _free_squares(ctx: Any, veil: Any, reach: int, size: int) -> list[Any]:
    """Every unoccupied in-grid square a cube of ``size`` feet fits on within ``reach`` feet of the veil."""
    from .. import zones
    from .map_positions import map_position

    engine = ctx.engine
    square = engine.grid.square_size_ft
    per = max(1, size // square)
    taken = engine._occupied_cells_except(ctx.actor.entity_id)
    blocked = set(getattr(engine.grid, "blocked", None) or ())
    span = max(1, int(reach) // square)
    out = []
    for dy in range(-span, span + 1):
        for dx in range(-span, span + 1):
            centre = map_position(engine, veil.center.x + dx, veil.center.y + dy, z=veil.center.z)
            if centre is None or engine.grid.distance_ft(veil.center, centre) > reach:
                continue
            footprint = {(centre.x + ox, centre.y + oy)
                         for ox in range(-(per // 2), per - per // 2) for oy in range(-(per // 2), per - per // 2)}
            if whole_cube_placement(engine) and not all(engine.grid.in_bounds(cell) for cell in footprint):
                continue
            if blocked & footprint or taken & footprint:
                continue
            if not zones._cells(engine, centre, {"shape": "cube", "size_ft": size}):
                continue
            out.append(centre)
    return out


def _place(ctx: Any, veil: Any, profile: dict[str, Any], cells: Any, center: Any) -> None:
    """Put the second area on the square its owner picked, sharing the first veil's Concentration.

    ``center`` is the square the owner chose, not the first cell of the footprint: a 10-foot cube covers four
    5-foot squares, and recording a corner as the area's centre would put a later re-centring (or a stored-cell read)
    a whole cube off. The centre is the chosen square, which is the square the printed line names."""
    from .. import zones
    from ..gate2_runtime_models import ZoneState

    engine = ctx.engine
    zone = ZoneState(
        zone_id=f"zone:typed:{ctx.actor.entity_id}:{engine.state.event_sequence + 1}", source_definition_id=ctx.source,
        owner_id=ctx.actor.entity_id, center=center, radius_cells=0, affected_cells=cells,
        concentration_link=bool(veil.concentration_link), duration_rounds=veil.duration_rounds,
        created_round=engine.state.round_number, trigger_profile=profile)
    engine.state.zones[zone.zone_id] = zone
    engine._append_event("ZONE_CREATED", ctx.source, actor_id=ctx.actor.entity_id,
                         payload={"zone": zone.model_dump(mode="json")})
    zones.sync_inside(engine, ctx.source)


def _square_words(square: Any, origin: Any, engine: Any) -> str:
    """A square in the words a player would use -- "the square 10 feet east and 5 feet south of your Smoke Veil" --
    rather than the map's own x and y numbers, which are an internal space id and mean nothing to a reader.

    Both axes are always given, each in feet, because one is not enough to tell two squares apart: a single compass
    octant collapses every unequal offset onto one bearing, so a square three squares east and one north and a square
    three squares east and one south were both "east" and, at the same distance, read identically -- two different
    destinations offered as the same choice. East/west and north/south are stated separately, so the pair names one
    square and only that square. The distance is the map's own measure."""
    dx, dy = square.x - origin.x, square.y - origin.y
    if dx == 0 and dy == 0:
        return "the square your Smoke Veil already covers"
    foot = int(engine.grid.square_size_ft)
    parts = []
    if dx:
        parts.append(f"{abs(dx) * foot} feet {'east' if dx > 0 else 'west'}")
    if dy:
        parts.append(f"{abs(dy) * foot} feet {'south' if dy > 0 else 'north'}")
    return f"the square {' and '.join(parts)} of your Smoke Veil"


SMOTHER = "TAL_SMOKE_SMOTHER_THE_BREATH"


@effect("smoke_smother_failure")
def smother_failure(ctx: Any, eff: dict[str, Any]) -> None:
    """Smother the Breath's failed save: "It has Disadvantage on the triggering d20 Test if the trigger includes one. If
    the trigger does not include a d20 Test, the creature cannot take Reactions until the start of its next turn."
    One printed outcome, two readings, and which one applies is read rather than guessed: while the creature's own
    attack roll is still pending (combat/typed_executor.py's declared-attack window, which a ``hit``-kind trigger opens
    before the roll) the cough costs it that roll; otherwise the trigger is a spoken or breath technique with no d20
    Test of its own and the cough takes its Reaction away. Never both."""
    from ..typed_executor import run_effects

    pending = getattr(ctx.engine, "_typed_pending_attack", None)
    source = str(ctx.typed.get("triggering_source_id") or (pending or {}).get("attacker") or "")
    if pending and source and pending.get("attacker") == source:
        run_effects(ctx, [{"type": "disadvantage", "applies_to": "attacker", "on": "the triggering attack roll",
                           "duration": "instant",
                           "evidence": "It has Disadvantage on the triggering d20 Test (the attack it was making when it spoke)."}])
        return
    run_effects(ctx, [{"type": "condition", "applies_to": "target", "condition": "reaction_denied",
                       "expires_on": "START_OF_TARGET_NEXT_TURN",
                       "evidence": "It cannot take Reactions until the start of its next turn."}])


#: Blacken the Flame, the one Smoke Response that answers damage instead of an attack roll. Its ownership row lives in
#: combat/rules/feature_blocks.d/auto43_smoke.json (``block``), read through combat/ext/fight_ownership.py owns_block,
#: because the printed trigger compiles to no action or reaction row of its own.
BLACKEN = "TAL_SMOKE_BLACKEN_THE_FLAME"
BLACKEN_BLOCK = "smoke_fire_soot"
TRACE = "Smoke Trace"


@hook("compile_block")
def smoke_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Blacken the Flame's own row, so this fight records that its owner has it (see BLACKEN_BLOCK).

    The printed activation is a Reaction ("Action Type: Reaction"), so the row carries the ordinary Reaction costs it
    answers through: the printed CL dice are resolved here, from the typed record the compiler supplied with this row
    (``numbers``'s ``record``, the same authority ``compile_character``'s ``typed_authority`` selected), so the fight
    does not keep a second copy of the printed numbers, the compiler's chosen authority is the one that is used, and
    the owner's key ability modifier comes from the row's own numbers."""
    if block != BLACKEN_BLOCK:
        return None
    return [{**row, "block": BLACKEN_BLOCK, "kind": str(spec.get("kind") or "soot_fire_damage"),
             "dice": _printed_dice(numbers.get("record"), numbers.get("cl")),
             "key_mod": int(numbers.get("key_mod") or 0),
             **({"effects": [{"type": "response_use", "group": spec["response_group"], "name": "Smoke Response"}]}
                if spec.get("response_group") else {})}]


def _printed_dice(record: Any, cl: Any) -> dict[str, int]:
    """"The reduction increases to 2d6 at CL 5, 3d6 at CL 11, and 4d6 at CL 17" -- read from the typed record the
    compiler handed this row (authority/typed_mechanics/reviewed_final.d/auto_smoke.json, TAL_SMOKE_BLACKEN_THE_FLAME's
    ``damage_modifier``) with the shared CL reader every other printed CL table uses, so the printed numbers live in
    the reviewed data only. ``1d6`` is the printed default below the first band. A record that states no table at all
    keeps that default."""
    from factory_authoring.typed_mechanics import dice_for_cl

    for effect in (record or {}).get("effects") or []:
        if not isinstance(effect, dict) or effect.get("type") != "damage_modifier":
            continue
        dice = dice_for_cl(effect.get("dice_by_cl"), int(cl or 1)) or effect.get("dice") or {}
        return {"count": int(dice.get("count") or 1), "sides": int(dice.get("sides") or 6)}
    return {"count": 1, "sides": 6}


def _soot_numbers(engine: Any, owner: Any, row: dict[str, Any]) -> tuple[int, int, int]:
    """The printed reduction as (dice count, sides, key modifier) for this owner, from the fight's own row.

    A row compiled by this hook carries the resolved ``dice`` and ``key_mod``, and those are what a new fight uses: one
    authority read at compile time, nothing re-resolved later. A fight saved before this hook existed carries a row
    with neither field, and new compilation cannot reach back into it. Those older rows read their Cultivation Level
    and key ability modifier from the owner's own compiled action numbers -- the numbers the fight was itself built
    with, still stored in its action catalog -- exactly as that saved fight did before, so reloading it keeps the
    reduction it was playing with (``3d6 + 3`` at CL 11) instead of silently dropping to the ``1d6 + 0`` default.
    """
    dice = dict(row.get("dice") or {})
    if dice:
        return int(dice.get("count") or 1), int(dice.get("sides") or 6), int(row.get("key_mod") or 0)
    numbers = _compiled_numbers(engine, owner)
    return _printed_dice(_blacken_record(), int(numbers.get("cl") or 1))["count"], 6, int(numbers.get("key_mod") or 0)


def _compiled_numbers(engine: Any, owner: Any) -> dict[str, Any]:
    """The typed numbers this owner's own compiled action was built with, as the fight already stores them.

    Read from the fight's action catalog rather than recompiled from the character sheet, because a saved fight's
    numbers are the ones it is playing with; a character whose sheet has since changed must not shift a fight in
    progress."""
    for action in engine.action_catalog.values():
        if action.owner_id == owner.entity_id:
            numbers = ((action.parameters or {}).get("typed") or {}).get("numbers")
            if numbers:
                return dict(numbers)
    return {}


def _blacken_record() -> dict[str, Any]:
    """Blacken the Flame's reviewed typed record, read from the built authority file.

    Only the damage-time path for a row saved before this hook (see :func:`_soot_numbers`) needs it: such a row kept no
    numbers of its own, so its Cultivation Level is the fight's own and the printed dice that go with it come from the
    authority as they always did. Compilation itself never reads the file -- it uses the record the compiler supplied."""
    from ..factory_compiler import TYPED_AUTHORITY

    import json
    from pathlib import Path

    return (json.loads(Path(TYPED_AUTHORITY).read_bytes())["mechanics"] or {}).get(BLACKEN) or {}


def _covered_by_veil(engine: Any, owner: Any, *creatures: Any) -> bool:
    """Whether the target or whoever dealt the damage to it stands inside one of ``owner``'s Smoke Veils -- the
    printed "Fire damage is dealt inside your Smoke Veil or through your Smoke Veil"."""
    from .. import zones

    return any(zones._inside(engine, creature, veil) for veil in veils(engine, owner)
               for creature in creatures if creature is not None and creature.active)


def _through_veil(engine: Any, owner: Any, source: Any, target: Any) -> bool:
    """The printed second half of Blacken the Flame's trigger: "Fire damage is dealt inside your Smoke Veil *or through
    your Smoke Veil*." A packet that did not start inside the veil still answers it when its line of effect crosses one
    of the owner's veils, read with the engine's own crossing line (combat/space.py ``ray``, the reader
    combat/zones.py ``_through_obscuring_wall`` uses), so fire that travels *through* the smoke is sooted exactly as
    fire that starts inside it. Needs a source and a target on the map to have a line at all.

    Nothing here asks whether anybody can see through the smoke. ``combat/senses.py`` ``pierces_wall`` is the engine's
    *visibility* exception -- Blindsight and Truesight looking through a wall that hides without blocking, which is what
    Wall of Smoke's "if the attacker relies on sight" is about -- and the printed Blacken trigger names no sight at
    all: it is about where the fire travelled, not who could watch it. Reusing that reader here meant a fire attack
    crossing the veil stopped qualifying whenever its source happened to have qualifying Blindsight, which the printed
    line never says. What a veil does to a fire packet is the same whether or not the thrower can see through it."""
    from ..space import ray

    if source is None or target is None or not (source.active and target.active):
        return False
    squares = [{(cell.x, cell.y) for cell in veil.affected_cells} for veil in veils(engine, owner)]
    if not squares:
        return False
    return any((x, y) in cells for (x, y, _z) in ray(source.position, target.position)[1:-1] for cells in squares)


@hook("final_damage", priority=5)
def blacken_the_flame(engine: Any, target: Any, amount: int, damage_type: str, source_id: str,
                      source_actor_id: str, intent: Any) -> dict[str, Any] | None:
    """Blacken the Flame: "Action Type: Reaction. Trigger: Fire damage is dealt inside your Smoke Veil or through your
    Smoke Veil. Spend one Smoke Trace on the source, target, or affected space. Reduce the Fire damage dealt to one
    creature or object by: 1d6 + your key ability modifier."

    A reaction is a question, and this one answers damage that lands anywhere on the map rather than an attack roll
    against the reactor, so it has no runnable reaction trigger on this table (combat/reaction_trigger_phrases.json
    classifies "Fire damage is dealt inside your Smoke Veil" as unsupported). The reduction runs through the engine's
    own ``final_damage`` seam instead -- the strict transactional checkpoint every damage packet reaches after all
    defences and reactions and before hit points are committed, typed abilities included (combat/typed_executor.py
    ``_commit_damage`` and combat/gate2_engine.py ``final_damage``) -- and it is the owner's decision there: a player is
    asked, an AI answers for itself, declining spends nothing (see :func:`soot_owners` for how the table learns whose
    question to put to a player). The prompt names the ability, the action that triggered
    it and the creature it caught, in the words the fight itself publishes them.

    It is a *Reaction*, and it is paid like one. Eligibility is the engine's own admission for an owned reaction
    (combat/typed_reactions.py ``_can_react``: alive, not denied Reactions by a condition such as Smother the Breath's,
    and with a Reaction left this round), and payment is that module's own ``_open`` / ``spend_reaction``, so the use is
    recorded as a reaction use, the owner's Reaction is already spent for anything this one triggers, and a saved fight
    shows it like any other Reaction. Nothing here is free: the printed Smoke Trace is a *second*, separate cost and is
    spent through the engine's own condition removal. Newly compiled rows share the response_use round allowance with the other Smoke Responses. The dice come from the row this hook compiled; a fight saved before the hook existed
    carries no such row numbers, and :func:`_soot_numbers` keeps that fight on the numbers it is already playing."""
    if int(amount) <= 0 or str(damage_type or "").upper() != "FIRE" or not getattr(target, "active", False):
        return None
    from .fight_ownership import block_rows
    from .needle import ask, checkpoint_id
    from .. import typed_reactions
    from ..typed_executor import bears_mark, mark_condition_id

    source_actor = engine.state.actors.get(source_actor_id or "")
    for owner in sorted(engine.state.actors.values(), key=lambda creature: creature.entity_id):
        if not owner.active:
            continue
        row = next(iter(block_rows(engine, owner, BLACKEN_BLOCK)), None)
        if row is None or not typed_reactions._can_react(engine, owner, row):  # owns it, and can pay a Reaction for it
            continue
        if not (_covered_by_veil(engine, owner, target, source_actor)
                or _through_veil(engine, owner, source_actor, target)):
            continue
        bearer = next((creature for creature in (source_actor, target)
                       if creature is not None and bears_mark(creature, owner.entity_id, TRACE)), None)
        if bearer is None:
            continue
        count, sides, bonus = _soot_numbers(engine, owner, row)
        who = getattr(source_actor, "display_name", None)
        action = _action_words(engine, source_id)
        chosen = ask(engine, intent, checkpoint_id(engine, "blacken_the_flame", target.entity_id, source_id), owner,
                     "choice:needle.smoke_blacken_the_flame", ["blacken"],
                     labels={"blacken": f"soot the fire: -{count}d{sides} + {bonus}"}, minimum=1, maximum=1,
                     allow_decline=True, automatic=False, default="decline", name="Blacken the Flame",
                     feature_id=BLACKEN, target_id=target.entity_id,
                     prompt=(f"Blacken the Flame: {target.display_name} is taking {amount} Fire damage"
                             f"{f' from {who}' if who and who is not target else ''}"
                             f"{f' with {action}' if action else ''} inside or through your Smoke Veil. "
                             f"Spend your Reaction and one of your Smoke Traces to reduce it by {count}d{sides} + {bonus}? "
                             "Decline to take the damage as it is."))
        if "blacken" not in chosen:
            continue
        with activation(engine, owner, BLACKEN):
            typed_reactions._open(engine, row, owner, (target.entity_id,), "FINAL_DAMAGE")
            typed_reactions.spend_reaction(engine, owner, row)
            engine._remove_condition(bearer, mark_condition_id(TRACE, owner.entity_id), BLACKEN)
            if row.get('effects'):
                from .response_limits import consume
                consume(engine, owner, row['effects'][0]['group'], BLACKEN, 'Smoke Response')
            cut = min(int(amount), _cut(engine, owner, count, sides, bonus))
            return {"amount": int(amount) - cut}
    return None


@hook("choice_reactors")
def soot_owners(engine: Any) -> tuple[str, ...]:
    """The fighters who could be asked Blacken the Flame's question in this fight: the ones whose own compiled
    ownership row is the one :func:`blacken_the_flame` asks (the same reader, so a fighter is enrolled exactly when
    the plug-in would ask it).

    This is the documented ``choice_reactors`` query (combat/ext/__init__.py): a pure "this creature may have a
    choice put to it" answer the service reads when it works out who to pause for, and nothing else. The service
    enrolls only fighters a player controls at this table and answers for the rest itself, and the question's own
    checkpoint still decides whether it is actually reached -- so this says who *might* be asked, never that they
    are. Default-inert: a creature without Blacken the Flame's row is never named, so no other character, no other
    ability and no AI fighter changes.

    It exists because an AI-controlled action is resolved somewhere else. On a player's own turn the table asks
    every manual fighter's question (combat/gate5_service.py ``_run_preview``'s provider, reached by
    ``submit_intent``: anything not LOCAL_AUTO or API_AUTO is asked), but when somebody *else's* action is being
    stepped the service first runs that action on a throwaway copy to discover player-owned prompts
    (``_ask_during_ai_step``) -- and it only looks for them among the fighters some plug-in enrolled here. Without
    this, a manual fighter's Blacken on an AI's turn was not asked at all: the AI controller answered it on the
    player's behalf, and a yes would have spent the player's Reaction and the player's Smoke Trace. Naming the
    fighter, rather than the question, is deliberate: the service's rule is one question per player, so anything else
    that fighter is asked during another creature's action is asked of them too, which is what a player at the table
    is there for."""
    from .fight_ownership import block_rows

    return tuple(sorted(actor.entity_id for actor in engine.state.actors.values()
                        if block_rows(engine, actor, BLACKEN_BLOCK)))


def _action_words(engine: Any, source_id: str) -> str:
    """The name of the action that dealt this damage, as the table shows it ("Burning Flame"), or "" when the packet
    came from something with no compiled action behind it.

    The printed trigger is "Fire damage is dealt ...", so the thing that triggered it is an action, and a player
    deciding whether to spend a Reaction needs to know which one -- the ability's internal id means nothing on a sheet.
    The fight's own action catalog already carries the readable name it was published under, so the prompt quotes it
    rather than inventing one."""
    action = engine.action_catalog.get(str(source_id or ""))
    name = str(getattr(action, "display_name", "") or "").strip()
    if not name or name.startswith("system:"):
        return ""
    return name


def _cut(engine: Any, owner: Any, count: int, sides: int, bonus: int) -> int:
    """Roll the printed reduction and record it, so the fight log shows what the soot took off."""
    from ..typed_executor import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=int(count), sides=int(sides), modifier=int(bonus)), actor_id=owner.entity_id,
                              reason="DAMAGE_REDUCED", mode="BLACKEN_THE_FLAME")
    engine._record_roll(roll)
    return int(roll.total)


WITNESS = "TAL_SMOKE_SOOT_MARKED_WITNESS"
REVEALED = "condition:typed.smoke_witness_reveal"
WITNESS_RANGE_FT = 120  # "you know its location while it remains within range" (the printed 120 feet)

#: The concealment kinds the printed line names: "smoke, fog, mist, steam, or nonmagical darkness".
#: The first four are matched by the area's own name (a Smoke Veil, a fog bank, a steam cloud);
#: darkness additionally has to be nonmagical, which combat/ext/darkness_scope.py ``scope`` says.
SOOT_FAMILY = ("smoke", "fog", "mist", "steam")


@effect("smoke_witness_reveal")
def witness_reveal(ctx: Any, eff: dict[str, Any]) -> None:
    """Soot-Marked Witness: "Until the start of your next turn, the target cannot be Hidden from you
    solely because it is concealed by smoke, fog, mist, steam, or nonmagical darkness. If it was
    Hidden from you solely for one or more of those reasons, it immediately ceases to be Hidden from
    you, and you know its location while it remains within range."

    The source-owned mark expires at START_OF_SOURCE_NEXT_TURN. The location-only
    pinpoint_target query and personal Hidden mask below never exempt visual
    obscurement: normal unseen-target penalties and sight requirements still apply.
    Other observers retain the target's stored Hidden condition.
    """
    target = ctx.target
    if target is None or not target.active:
        return
    engine = ctx.engine
    engine._apply_condition(target, REVEALED, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"owner": ctx.actor.entity_id,
                                  "range_ft": WITNESS_RANGE_FT,
                                  "label": f"Soot-Marked Witness: {ctx.actor.display_name} knows this creature's location "
                                           "within 120 feet through smoke, fog, mist, steam or nonmagical darkness "
                                           f"until the start of {ctx.actor.display_name}'s next turn; "
                                           "this grants no sight and keeps normal unseen-target penalties"})


def _witness_location(engine: Any, viewer: Any, seen: Any) -> bool:
    """Personal location through listed concealment, without bypassing other causes."""
    from .. import senses, stealth, zones

    if seen is None or viewer is None or not (seen.active and viewer.active):
        return False
    mark = next((condition for condition in seen.conditions.values()
                 if condition.condition_id == REVEALED
                 and condition.source_actor_id == viewer.entity_id), None)
    if mark is None:
        return False
    reach = int((mark.data or {}).get("range_ft") or WITNESS_RANGE_FT)
    if int(engine._distance_actor_to_actor(viewer, seen)) > reach:
        return False
    if not senses.physical_sight(engine, viewer, seen):
        return False  # Total Cover is not a listed concealment cause.
    if any(c.condition_id == "condition:typed.invisible" for c in seen.conditions.values()):
        return False
    iid = stealth.hidden(seen)
    if iid:
        data = seen.conditions[iid].data or {}
        basis = str(data.get("hiding_basis") or "visual_concealment,sound_reliance").split(",")
        if "visual_concealment" not in basis or data.get("inside"):
            return False  # Independently supported hiding is not defeated.
    blockers = []
    from ..space import ray
    for zone in zones.typed_zones(engine):
        profile = zone.trigger_profile or {}
        wall = profile.get("wall") or {}
        if wall.get("obscures"):
            who = wall["obscures"]
            owner = engine.state.actors.get(zone.owner_id)
            if who == "hostile" and owner and not zones.hostile_to(engine, zone, viewer):
                continue
            if zones.obscurement_ignored(engine, zone, viewer, seen) or zones.obscuration_ignored(engine, zone, viewer, seen):
                continue
            if senses.pierces_wall(engine, zone, viewer, seen):
                continue  # a wall the viewer already sees through is no blocker (zones._through_obscuring_wall agrees)
            cells = {(p.x, p.y) for p in zone.affected_cells}
            height = wall.get("height_ft")
            base = wall.get("base_altitude_ft", zone.center.z * 5)
            if any((x, y) in cells and (height is None or base <= z * 5 < base + height)
                   for x, y, z in ray(viewer.position, seen.position)[1:-1]):
                blockers.append(zone)
        elif (profile.get("obscured") == "heavy" or (profile.get("visual") or {}).get("darkness")):
            if zones.blocks_view(engine, zone, viewer, seen):
                blockers.append(zone)
    if zones.observer_blocked(engine, viewer, seen):
        return False
    # A hidden creature with no qualifying scene cause cannot be explained by
    # this ability. A visible marked creature's location is already available.
    return (bool(blockers) or iid is None) and all(_listed_concealment(engine, z) for z in blockers)


@hook("pinpoint_target")
def witness_location(engine: Any, viewer: Any, seen: Any) -> bool | None:
    """Know the marked creature's location, never gain sight through its screen."""
    return True if _witness_location(engine, viewer, seen) else None


@hook("masked_conditions")
def witness_hidden_mask(engine: Any, attacker: Any, target: Any) -> dict[str, Any]:
    """Suppress only personal Hidden; area penalties remain independently active."""
    from .. import stealth

    masks = {}
    for viewer, seen in ((attacker, target), (target, attacker)):
        if _witness_location(engine, viewer, seen) and (iid := stealth.hidden(seen)):
            masks[seen.entity_id] = {iid}
    return {"conditions": masks, "visual": False}


def _listed_concealment(engine: Any, zone: Any) -> bool:
    """Whether an area hides by one of the printed kinds: smoke, fog, mist, steam, or nonmagical
    darkness. A smoke-family area qualifies by its name (a Smoke Veil, a fog bank, a mist, a steam
    cloud); darkness qualifies only when it is nonmagical, which combat/ext/darkness_scope.py
    ``scope`` reads from the area's own tier and source."""
    from .darkness_scope import scope

    profile = zone.trigger_profile or {}
    visual = profile.get("visual") or {}
    name = str(profile.get("name") or "").lower()
    material = str(visual.get("material") or (profile.get("wall") or {}).get("material") or "").lower()
    if any(kind in name or kind in material for kind in SOOT_FAMILY):
        return True
    if visual.get("darkness"):
        return scope(engine, zone) == "ordinary"
    return False
