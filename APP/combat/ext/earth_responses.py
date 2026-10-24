"""Shared Earth response API, consumed by earth_flying and elements_earth.
rows, marked, spend_mark, response_context, response_available and save_dc
preserve the owning module's native mark transaction and once-round semantics.

Earth's Burden Marks and Earth Responses (rider lane 9, 2026-09-29; owner: "i want everything we can automated").  Sphere
Compendium, Earth (owner's text: authority/typed_mechanics/rules_text.json, EARTH_BASE_SPENDING_A_BURDEN_MARK and the talents below).
Set Foundation (a zone), Weight-Seeking Clod and the rest place the marks; this module spends them.  Rows: feature block "lane9_earth"
(combat/rules/feature_blocks.d/riders_lane9.json).  A Burden Mark "lasts until the end of your next turn" (typed_conditions
mark_durations) and you keep at most PB of them (the oldest ends).

Foundation Spaces: your Set Foundation and Earth Domain areas, and your own space during Deep Root Stance, with Mountain-Root Body, and
(with the spaces within 10 feet) during Incarnation of the Patient Mountain -- only your own space in a turn you moved more than half your
Speed.

Spending a Burden Mark: "Once per round, when a marked creature or object you can perceive performs a triggering act, you may spend its
Burden Mark without using an Action. Choose one Earth Response appropriate to the trigger."
  Anchor Step        the marked creature's turn starts: its movement this turn drops by 10 feet (20 at CL 11); on forced movement, the push
                     is 10 (20) feet shorter (asked; the AI keeps the mark for Drag Down).
  Drag Down          it willingly moves 5 feet or more: Strength save or it falls Prone (Speed 0 for the turn if already Prone); a success
                     costs it 5 feet of movement.
  Bear the Blow      it damages you, or an ally within 5 feet of you or on your Foundation: -1d8 (2d8 at CL 5, 3d8 at CL 11, 4d8 at CL 17)
                     + your key modifier.
  Shift the Load     it hits a creature of your side: before damage, that creature gains PB + key Temporary HP (twice on your Foundation)
                     (asked; the AI keeps the mark for Bear the Blow).
  Raise the Ridge    it makes a ranged attack roll at your side: a ridge gives Half Cover (-2 on the roll).
  Settle the Impact  it would push or pull a creature of your side: 10 (20 at CL 11) feet less.
Earth Domain: once per round a hostile creature inside that forces movement on another meets Settle the Impact without a mark.
Talents: Sinking Foot Rebuke (after Anchor Step or Drag Down: no Dash this turn, or Disadvantage on its next Dexterity save), Landslide
Argument (moving 10 feet across your Foundation spends the mark: Dexterity save, Prone, a 15-foot slide away from you and 3d8
Bludgeoning; a success still slides it 5 feet), Deep Root Stance (forced movement on you is 5 feet shorter, 10 at CL 10; a creature that
misses you in melee gains a mark), Mountain-Root Body (its own space is Foundation; its Dodge mark is auto_lane4's), Earth Domain (a hostile
creature that willingly moves 10 feet inside gains a mark), The Grave Refuses the Step (Reaction, 2 CP: a creature teleporting out of your
Foundation makes a Charisma save or stays; a success gives it a mark and no Reactions until the start of its next turn).

Judgment calls: as Ice's Catch Step, Anchor Step is decided as the marked creature's turn starts; "your side" is your team; a slide goes
straight away from you. Sinking Foot Rebuke asks its owner for the additional penalty;
automatic owners retain the historical Dexterity-save penalty on a Prone creature and otherwise prevent Dash.

Set Foundation's own surface rules: the table asks for the spaces and the printed Cultivation-Level count, and the mark rule reads
"a creature you did not designate as safe" as your own team (the creatures you designated safe). Disconnected platforms, elevated ground
and Body Refining's contact restrictions are not something the current surface query can prove (AUTO39 seam E1, unbuilt), so they are
not restated as a GM reminder here: the common arena floor is the only legal surface these fights can present.
"""

from __future__ import annotations

from ..technique_interception import native_reaction

from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id

BLOCK = "lane9_earth"
T = "TAL_EARTH_"
BASE = "EARTH_BASE_SPENDING_A_BURDEN_MARK"
MARK = "Burden Mark"
C = "condition:typed."
STANCE, INCARNATION, SLOW_DEX = C + "deep_root", C + "patient_mountain", C + "sinking_dex"
FOUNDATION_SOURCES = {"EARTH_BASE_SET_FOUNDATION", T + "EARTH_DOMAIN_COURT_OF_BEARING_GROUND", T + "SINK_THE_WHEEL_RUT", T + "EARTHBIND_LINE"}
DOMAIN = T + "EARTH_DOMAIN_COURT_OF_BEARING_GROUND"


def rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    result = [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "cl": int(numbers.get("cl") or 1),
               "key_mod": int(numbers.get("key_mod") or 0), "keeps_compiling": bool(spec.get("keeps_compiling"))}]
    if spec.get("kind") == "burden":
        result.append({**row, "block": "mark_caps", "caps": {"burden mark": int(numbers.get("pb") or 2)}})
    return result


def _owns(engine: Any, actor: Any, feature: str) -> bool:
    """Whether ``actor`` compiled ``feature`` into any passive row (Mountain-Root Body is auto_lane4's block)."""
    return any(row.get("feature_id") == feature for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


def _row(engine: Any, caster: Any) -> dict[str, Any]:
    found = rows(engine, caster, "burden")
    return found[0] if found else {}


def _casters(engine: Any) -> list[Any]:
    return [a for a in engine.state.actors.values() if a.active and rows(engine, a, "burden")]


def _held(actor: Any, condition_id: str) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def _mark_id(owner_id: str) -> str:
    from ..typed_executor import mark_condition_id

    return mark_condition_id(MARK, owner_id)


def marked(actor: Any, owner_id: str) -> bool:
    return any(c.condition_id == _mark_id(owner_id) for c in actor.conditions.values())


def _feature(engine: Any, source: Any) -> str:
    action = engine.action_catalog.get(str(source or ""))
    return str((((action.parameters or {}).get("typed") or {}).get("source") or "")) if action is not None else ""


def _movement_this_turn(actor: Any) -> int:
    """Read integer movement memory, including the earlier saved pair format."""
    moved = actor.turn_flags.get("earth_moved_ft", 0)
    if isinstance(moved, list):
        return int(moved[1]) if len(moved) == 2 and moved[0] == actor.turns_started else 0
    return int(moved) if actor.turn_flags.get("earth_moved_turn") == actor.turns_started else 0


def _ctx(engine: Any, actor: Any, other: Any, feature: str, name: str) -> Any:
    from .. import typed_reactions

    return typed_reactions._generic_context(engine, actor, other, {"feature_id": feature, "name": name, "effects": [], "numbers": {}})


@effect("earth_foundation_mark")
def foundation_mark(ctx: Any, eff: dict[str, Any]) -> None:
    """Set Foundation: "When a creature you did not designate as safe willingly moves at least 10 feet across, out of, or through your
    Foundation Spaces during one turn, you may give that creature one Burden Mark. This can happen only once per creature per turn."
    The willing 10-foot crossing and the once per creature per turn are the zone's ``move_through`` rule (combat/zones.py on_moved:
    forced movement never counts; one firing per creature per turn); you and your side are the creatures you designate as safe; the
    mark is your choice (asked; the built-in AI gives it). Rider lane C13, 2026-09-30."""
    from .rider_choices import pick

    engine, caster, mover = ctx.engine, ctx.actor, ctx.target
    if mover is None or not mover.active or caster is None or mover.team_id == caster.team_id or marked(mover, caster.entity_id):
        return
    chosen = pick(engine, caster, "earth_foundation_mark", "Set Foundation", ["mark"], subject=mover, preferred=["mark"],
                  labels={"mark": f"Give {mover.display_name} a Burden Mark (it crossed 10 feet of your Foundation)"},
                  trigger=f"{mover.display_name} moves across your Foundation")
    if chosen:
        give_mark(engine, caster, mover, ctx.source)


def give_mark(engine: Any, caster: Any, subject: Any, source: str, *, hostile_only: bool = True) -> None:
    from ..typed_executor import block_mark

    if subject is None or not subject.active or (hostile_only and subject.team_id == caster.team_id) or marked(subject, caster.entity_id):
        return
    block_mark(_ctx(engine, caster, subject, source, MARK), {"type": "mark", "mark": MARK, "applies_to": "target", "duration": {"kind": "until_removed"}})



def spend_mark(engine: Any, caster: Any, subject: Any, source: str) -> None:
    """Spend through the native mark path, including owned mark-spent riders."""
    from ..typed_executor import block_spend_mark
    block_spend_mark(_ctx(engine, caster, subject, source, "Burden Mark"),
                     {"type": "spend_mark", "mark": MARK, "applies_to": "target"})


def _roll(engine: Any, actor: Any, count: int, sides: int, reason: str) -> int:
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=0), actor_id=actor.entity_id, reason=reason)
    engine._record_roll(roll)
    return int(roll.total)


def _dc(engine: Any, actor: Any) -> int:
    for action in engine.action_catalog.values():
        if action.owner_id == actor.entity_id:
            numbers = ((action.parameters or {}).get("typed") or {}).get("numbers") or {}
            if numbers.get("save_dc"):
                return int(numbers["save_dc"])
    return 10


def _cells_of(engine: Any, actor: Any) -> set[tuple[int, int]]:
    return {tuple(c) for c in engine._actor_cells(actor)}


def foundation_cells(engine: Any, caster: Any) -> set[tuple[int, int]]:
    from .. import zones

    cells: set[tuple[int, int]] = set()
    for zone in zones.typed_zones(engine):
        if zone.active and zone.owner_id == caster.entity_id and _feature(engine, zone.source_definition_id) in FOUNDATION_SOURCES:
            cells |= {(c.x, c.y) for c in zone.affected_cells}
    if _held(caster, STANCE) or _owns(engine, caster, T + "MOUNTAIN_ROOT_BODY"):
        cells |= _cells_of(engine, caster)
    for held in _held(caster, INCARNATION):
        cells |= _cells_of(engine, caster)
        speed = engine._effective_speed(caster) if hasattr(engine, "_effective_speed") else 30
        if _movement_this_turn(caster) <= speed // 2:  # "the emanation shrinks to your own space"
            reach = 10 // engine.grid.square_size_ft
            x0, y0 = caster.position.x, caster.position.y
            cells |= {(x, y) for x in range(x0 - reach, x0 + reach + 1) for y in range(y0 - reach, y0 + reach + 1)}
    return cells


def _on_foundation(engine: Any, caster: Any, creature: Any) -> bool:
    return bool(_cells_of(engine, creature) & foundation_cells(engine, caster))


# ------------------------------------------------------------------------------------------------ spending
def _can_spend(engine: Any, caster: Any) -> bool:
    return caster.active and caster.turn_flags.get("earth_spent_round") != engine.state.round_number and caster.turn_flags.get("_round_earth_response") != engine.state.round_number


def _offer(engine: Any, caster: Any, subject: Any, response: str, label: str, *, want: bool = True, free: bool = False) -> bool:
    from ..senses import perceives

    if not perceives(engine, caster, subject):
        return False
    if not free and (not marked(subject, caster.entity_id) or not _can_spend(engine, caster)):
        return False
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "EARTH_RESPONSE", caster.entity_id, subject.entity_id, response), caster,
                 CHOICE + "earth_response", [response], labels={response: label}, allow_decline=True, target_id=subject.entity_id,
                 default="first" if want else "decline", prompt=f"{subject.display_name} ({'Earth Domain' if free else 'Burden Mark'}): {label}?",
                 name="Earth Response: " + label, feature_id=BASE)
    if not picked:
        return False
    if not free:
        caster.turn_flags["earth_spent_round"] = engine.state.round_number
        caster.turn_flags["_round_earth_response"] = engine.state.round_number
        spend_mark(engine, caster, subject, BASE)
    note(engine, BASE, caster, f"Earth Response: {label} ({subject.display_name}).")
    for held in _held(caster, INCARNATION):
        engine._grant_temp_hp(caster, int(_row(engine, caster).get("pb", 2)), T + "INCARNATION_OF_THE_PATIENT_MOUNTAIN", caster.entity_id)
    return True



def response_context(engine: Any, owner: Any, subject: Any, feature: str, name: str) -> Any:
    """Public Earth response context for extension consumers."""
    return _ctx(engine, owner, subject, feature, name)


def response_available(engine: Any, owner: Any) -> bool:
    """Read Earth's shared once-round mark response allowance."""
    return _can_spend(engine, owner)


def save_dc(engine: Any, owner: Any) -> int:
    """Earth save DC sealed into this owner's action catalog."""
    return _dc(engine, owner)


def _sinking_foot(engine: Any, caster: Any, subject: Any, response: str) -> None:
    if not rows(engine, caster, "sinking_foot") or not subject.active:
        return
    from .rider_choices import pick
    from .effect_durations import token

    prone = any(c.expires_on == 'STAND_UP' for c in subject.conditions.values())
    options = ['DASH', 'DEX', *(['STAND'] if prone else [])]
    chosen = pick(engine, caster, 'sinking_foot', 'Sinking Foot Rebuke', options,
        subject=subject, optional=False, preferred=['DEX' if prone else 'DASH'],
        prompt=f'Sinking Foot Rebuke after {response} affects {subject.display_name}. '
               'Choose one extra penalty; no Action or Cultivation Point cost.',
        labels={'DASH': 'Cannot Dash until this turn ends',
                'DEX': 'Disadvantage on its next Dexterity save before your next turn starts',
                'STAND': 'Standing from Prone costs 5 extra feet until this turn ends'})
    if not chosen:
        return
    if chosen[0] == 'DEX':
        engine._apply_condition(subject, SLOW_DEX, T + "SINKING_FOOT_REBUKE", caster.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "Sinking Foot Rebuke: Disadvantage on its next Dexterity saving throw"})
    else:
        stand = chosen[0] == 'STAND'
        engine._apply_condition(subject, C + ('sinking_stand' if stand else 'no_dash'), T + "SINKING_FOOT_REBUKE", caster.entity_id,
                                expires_on=token("end", subject.entity_id, int(subject.turns_started)),
                                data=({'label': 'Sinking Foot Rebuke: standing costs 5 extra feet this turn'} if stand else
                                      {"rule": {"no_dash": True}, "label": "Sinking Foot Rebuke: no Dash this turn"}))


@hook('stand_extra_cost')
def sinking_stand_cost(engine: Any, actor: Any) -> int | None:
    return 5 if _held(actor, C + 'sinking_stand') else None


# ------------------------------------------------------------------------------------------------ the triggers
@hook("turn_start")
def anchor_step(engine: Any, actor: Any) -> None:
    for caster in _casters(engine):
        if caster.team_id == actor.team_id or not marked(actor, caster.entity_id):
            continue
        cl = int(_row(engine, caster).get("cl", 1))
        feet = 20 if cl >= 11 else 10
        if _offer(engine, caster, actor, "anchor", f"Anchor Step: {feet} feet less movement this turn", want=False):
            actor.movement_remaining_ft = max(0, int(actor.movement_remaining_ft) - feet)
            _sinking_foot(engine, caster, actor, 'Anchor Step')


@hook("forced_distance")
def earth_forced(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    cut = 0
    for held in _held(mover, STANCE):
        cut += 10 if int((held.data or {}).get("cl") or 1) >= 10 else 5  # Deep Root Stance
    if source is not None:
        for caster in _casters(engine):
            if mover.team_id != caster.team_id or source.team_id == caster.team_id:
                continue
            cl = int(_row(engine, caster).get("cl", 1))
            feet = 20 if cl >= 11 else 10
            free = _domain_free(engine, caster, source)
            if _offer(engine, caster, source, "settle", f"Settle the Impact: the push is {feet} feet shorter", free=free):
                if free:
                    caster.turn_flags["earth_domain_free"] = engine.state.round_number
                cut += feet
                if cut >= int(distance_ft or 0) and mover.active:
                    # "If this reduces the displacement to 0, the displaced creature or object may immediately move 5 feet without
                    # provoking Opportunity Attacks from the marked target." (rider lane C13: the displaced creature's controller
                    # picks the square or stays; the free step provokes no Opportunity Attack at all.)
                    from .rider_choices import step

                    step(engine, mover, "earth_settle_step", "Settle the Impact", source, 5, f"reaction:{BASE}")
                break
    return cut or None


def _domain_free(engine: Any, caster: Any, creature: Any) -> bool:
    from .. import zones

    if caster.turn_flags.get("earth_domain_free") == engine.state.round_number or marked(creature, caster.entity_id):
        return False
    return any(z.active and z.owner_id == caster.entity_id and _feature(engine, z.source_definition_id) == DOMAIN and zones._inside(engine, creature, z)
               for z in zones.typed_zones(engine))


@hook("damage_pending")
def bear_the_blow(engine: Any, target: Any, pending: int, source_definition_id: Any, source_actor_id: Any) -> int | None:
    attacker = engine.state.actors.get(str(source_actor_id or ""))
    if attacker is None or pending <= 0:
        return None
    for caster in _casters(engine):
        if target.team_id != caster.team_id or not marked(attacker, caster.entity_id):
            continue
        if target is not caster and engine._distance_actor_to_actor(caster, target) > 5 and not _on_foundation(engine, caster, target):
            continue
        row = _row(engine, caster)
        cl, key = int(row.get("cl", 1)), int(row.get("key_mod", 0))
        if _offer(engine, caster, attacker, "bear", "Bear the Blow: the damage drops"):
            cut = _roll(engine, caster, 1 if cl < 5 else 2 if cl < 11 else 3 if cl < 17 else 4, 8, "BEAR_THE_BLOW") + key
            from .attack_reduction import remember
            return remember(engine, target, pending, max(0, pending - cut), [(cut, ())])
    return None


@hook("hit_response")
def shift_the_load(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> Any:
    for caster in _casters(engine):
        if target.team_id != caster.team_id or not marked(attacker, caster.entity_id):
            continue
        row = _row(engine, caster)
        amount = max(1, int(row.get("pb", 2)) + int(row.get("key_mod", 0)))
        if _on_foundation(engine, caster, target):
            amount *= 2
        if _offer(engine, caster, attacker, "shift", f"Shift the Load: {target.display_name} gains {amount} Temporary HP", want=False):
            engine._grant_temp_hp(target, amount, BASE, caster.entity_id)
    return None


@hook("attack_bonus")
def raise_the_ridge(ctx: Any, actor: Any) -> int | None:
    engine = ctx.engine
    ranged = ctx.typed.get("range_ft") is not None and int(ctx.typed.get("range_ft") or 0) > 5
    target = ctx.target
    if not ranged or target is None:
        return None
    for caster in _casters(engine):
        if target.team_id == caster.team_id and actor.team_id != caster.team_id and marked(actor, caster.entity_id):
            if _offer(engine, caster, actor, "ridge", "Raise the Ridge: Half Cover against the attack"):
                return -2
    return None


@hook("save")
def sinking_dex(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if str(ability).upper()[:3] == "DEX" and _held(subject, SLOW_DEX):
        ctx.engine._remove_condition(subject, SLOW_DEX, T + "SINKING_FOOT_REBUKE")
        return {"bonus": 0, "modes": ["DISADVANTAGE"]}
    return None


@hook("event")
def earth_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type == "MOVEMENT_COMMITTED" and not engine.__dict__.get("_earth_moving"):
        mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
        path = [(int(p["x"]), int(p["y"])) for p in payload.get("path") or [] if isinstance(p, dict)]
        if mover is None or not mover.active or len(path) < 2:
            return
        feet = (len(path) - 1) * engine.grid.square_size_ft
        owns_incarnation = bool(_held(mover, INCARNATION)) or any(
            action.owner_id == mover.entity_id and ((action.parameters or {}).get("typed") or {}).get("source") == T + "INCARNATION_OF_THE_PATIENT_MOUNTAIN"
            for action in engine.action_catalog.values()
        )
        if owns_incarnation and engine.state.current_actor_id == mover.entity_id and not payload.get("forced"):
            mover.turn_flags["earth_moved_ft"] = _movement_this_turn(mover) + feet
            mover.turn_flags["earth_moved_turn"] = mover.turns_started
        engine.__dict__["_earth_moving"] = True
        try:
            _moved(engine, mover, path, feet, bool(payload.get("forced")))
        finally:
            engine.__dict__["_earth_moving"] = False
    elif event_type == "CONDITION_APPLIED" and str(payload.get("condition_id") or "").startswith(_mark_id("")[:-1]):
        _mark_cap(engine, str(payload.get("condition_id")))


def _moved(engine: Any, mover: Any, path: list[tuple[int, int]], feet: int, forced: bool) -> None:
    from .. import zones

    willing = not forced and engine.state.current_actor_id == mover.entity_id
    for caster in _casters(engine):
        if caster.team_id == mover.team_id:
            continue
        cells = foundation_cells(engine, caster)
        across = sum(engine.grid.square_size_ft for a, b in zip(path, path[1:]) if a in cells or b in cells)
        for zone in zones.typed_zones(engine):
            if willing and zone.active and zone.owner_id == caster.entity_id and _feature(engine, zone.source_definition_id) == DOMAIN:
                inside = {(c.x, c.y) for c in zone.affected_cells}
                if sum(engine.grid.square_size_ft for a, b in zip(path, path[1:]) if a in inside or b in inside) >= 10:
                    give_mark(engine, caster, mover, DOMAIN)  # "when a hostile creature willingly moves at least 10 feet while touching the area"
        if not marked(mover, caster.entity_id):
            continue
        if across >= 10 and rows(engine, caster, "landslide"):
            _landslide(engine, caster, mover)
            continue
        if willing and feet >= 5 and _offer(engine, caster, mover, "drag", "Drag Down: Strength save or it falls Prone"):
            dc = _dc(engine, caster)
            roll = engine._roll_save(mover, "STR", dc, T + "DRAG_DOWN")
            if roll is not None and int(roll.total) < dc:
                if any(c.condition_id.endswith(".prone") for c in mover.conditions.values()):
                    mover.movement_remaining_ft = 0
                else:
                    from ..typed_executor import run_effects

                    run_effects(_ctx(engine, caster, mover, BASE, "Drag Down"), [{"type": "condition", "condition": "prone", "applies_to": "target"}])
            else:
                mover.movement_remaining_ft = max(0, int(mover.movement_remaining_ft) - 5)
            _sinking_foot(engine, caster, mover, 'Drag Down')


def _landslide(engine: Any, caster: Any, mover: Any) -> None:
    from ..typed_executor import run_effects

    spend_mark(engine, caster, mover, T + "LANDSLIDE_ARGUMENT")  # "spend its Burden Mark"
    dc = _dc(engine, caster)
    roll = engine._roll_save(mover, "DEX", dc, T + "LANDSLIDE_ARGUMENT")
    failed = roll is not None and int(roll.total) < dc
    ctx = _ctx(engine, caster, mover, T + "LANDSLIDE_ARGUMENT", "Landslide Argument")
    note(engine, T + "LANDSLIDE_ARGUMENT", mover, f"Landslide Argument: the ground slides under {mover.display_name}.")
    if failed:
        run_effects(ctx, [{"type": "condition", "condition": "prone", "applies_to": "target"},
                          {"type": "forced_movement", "distance_ft": 15, "direction": "away", "applies_to": "target"}])
        engine._commit_damage(mover, _roll(engine, caster, 3, 8, "LANDSLIDE_ARGUMENT"), "BLUDGEONING", T + "LANDSLIDE_ARGUMENT", caster.entity_id, None, reaction_depth=1)
    else:
        run_effects(ctx, [{"type": "forced_movement", "distance_ft": 5, "direction": "away", "applies_to": "target"}])


def _mark_cap(engine: Any, condition_id: str) -> None:
    """"You can maintain a number of Burden Marks equal to your Proficiency Bonus": a new one past the limit ends the oldest."""
    owner = next((a for a in engine.state.actors.values() if _mark_id(a.entity_id) == condition_id), None)
    row = _row(engine, owner) if owner is not None else {}
    if not row:
        return
    placed = sorted(((c.applied_sequence, bearer) for bearer in engine.state.actors.values() for c in bearer.conditions.values()
                     if c.condition_id == condition_id), key=lambda r: r[0])
    from ..typed_executor import mark_capacity
    cap = mark_capacity(_ctx(engine, owner, owner, BASE, MARK), MARK) or int(row.get("pb", 2))
    for _, bearer in placed[:max(0, len(placed) - cap)]:
        engine._remove_condition(bearer, condition_id, BASE)


# ------------------------------------------------------------------------------------------------ talents
@hook("after_miss_choice")
def missed_the_mountain(ctx: Any, target: Any, spec: dict[str, Any]) -> None:
    from .rider_choices import pick

    engine, attacker = ctx.engine, ctx.actor
    melee = spec.get("reach_ft") is not None or spec.get("range_ft") is None
    if target is None or not target.active or not attacker.active or target.team_id == attacker.team_id:
        return
    if melee and _held(target, STANCE) and not marked(attacker, target.entity_id):
        chosen = pick(engine, target, "deep_root_miss", "Deep Root Stance", ["MARK"], subject=attacker,
            preferred=["MARK"], labels={"MARK": "Give a Burden Mark; no Action or CP cost"},
            trigger=f"{ctx.action.display_name}: {attacker.display_name} misses you with a melee attack")
        if chosen:
            give_mark(engine, target, attacker, T + "DEEP_ROOT_STANCE")


@hook("technique_used")
def earth_used(ctx: Any) -> None:
    source = str(ctx.typed.get("source") or "")
    if source == T + "DEEP_ROOT_STANCE":
        ctx.engine._apply_condition(ctx.actor, STANCE, source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"cl": int(ctx.numbers.get("cl") or 1), "label": "Deep Root Stance: its space is a Foundation Space"})
    elif source == T + "INCARNATION_OF_THE_PATIENT_MOUNTAIN":
        ctx.engine._apply_condition(ctx.actor, INCARNATION, source, ctx.actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                    data={"label": "Incarnation of the Patient Mountain: Foundation Spaces within 10 feet"})


@hook("teleport_gate")
def grave_refuses(ctx: Any, start: Any, destination: Any) -> bool | None:
    """The Grave Refuses the Step: Reaction, 2 CP -- a creature teleporting out of your Foundation makes a Charisma save or stays."""
    from .. import typed_reactions
    from .d20_rewrite import pool_id

    engine, mover = ctx.engine, ctx.actor
    for caster in [a for a in engine.state.actors.values() if a.active and rows(engine, a, "grave")]:
        if caster.team_id == mover.team_id:
            continue
        cp = pool_id(caster, "cp")
        if ((start.x, start.y) not in foundation_cells(engine, caster) or cp is None or caster.resources.get(cp, 0) < 2
                or not typed_reactions.can_react(engine, caster, rows(engine, caster, "grave")[0])):
            continue
        picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "GRAVE_REFUSES", caster.entity_id, mover.entity_id), caster,
                     CHOICE + "grave_refuses", ["use"], labels={"use": "The Grave Refuses the Step (Reaction, 2 CP)"}, allow_decline=True,
                     target_id=mover.entity_id, prompt=f"{mover.display_name} teleports out of your Foundation: The Grave Refuses the Step?")
        if not picked:
            continue
        row = rows(engine, caster, "grave")[0]
        with native_reaction(engine, caster, mover, {**row,
                "feature_id": T + "THE_GRAVE_REFUSES_THE_STEP", "name": "The Grave Refuses the Step",
                "numbers": {key: row[key] for key in ("cl", "pb", "key_mod")},
                "costs": [{"resource_id": cp, "amount": 2}]}) as reaction:
            if reaction is None:
                continue
            engine._spend_resource(caster, cp, 2, T + "THE_GRAVE_REFUSES_THE_STEP")
            caster.reaction_available = False
            engine._append_event("REACTION_WINDOW_OPENED", T + "THE_GRAVE_REFUSES_THE_STEP", actor_id=caster.entity_id, target_ids=(mover.entity_id,),
                                 payload={"checkpoint": "TELEPORT"})
            dc = _dc(engine, caster)
            roll = engine._roll_save(mover, "CHA", dc, T + "THE_GRAVE_REFUSES_THE_STEP")
            if roll is not None and int(roll.total) < dc:
                note(engine, T + "THE_GRAVE_REFUSES_THE_STEP", mover, f"The Grave Refuses the Step: {mover.display_name} stays where it stood.")
                return False
            give_mark(engine, caster, mover, T + "THE_GRAVE_REFUSES_THE_STEP")
            from .effect_durations import token

            engine._apply_condition(mover, C + "reaction_denied", T + "THE_GRAVE_REFUSES_THE_STEP", caster.entity_id,
                                    expires_on=token("start", mover.entity_id, int(mover.turns_started) + 1), data={"label": "No Reactions"})
    return None

# Round 2: printed automatic defenses and attack decisions, using existing seams.
MULE = T + 'MULE_SHOULDER_METHOD'
WEIGHT = T + 'WEIGHT_SEAL_STRIKE'
WEIGHT_CHECK = C + 'earth_weight_check'
REMEMBERS = T + 'BURIED_FOUNDATION_REMEMBERS'
VISITS = C + 'earth_foundation_visits'


def _weight_check_action(engine, source):
    action = engine.action_catalog.get(source)
    name = str(getattr(action, 'display_name', '')).lower()
    return ('shove' in name or 'grapple' in name) and 'escape' not in name


@hook('after_hit_choice')
def weight_seal_choice(ctx, target, kind):
    from .ability_source import mechanic_of
    from ..attack_notifications import is_melee_hit
    from .rider_choices import pick
    from ..typed_executor import run_effects
    if not rows(ctx.engine, ctx.actor, 'weight_seal') or target is None:
        return
    if mechanic_of(ctx.action) != 'EARTH_BASE_WEIGHT_SEEKING_CLOD' and not is_melee_hit(ctx):
        return
    # Arena ground is the common surface; disconnected/elevated surfaces remain an explicit blocker.
    if ctx.actor.position.z or target.position.z:
        return
    chosen = pick(ctx.engine, ctx.actor, 'weight_seal', 'Weight-Seal Strike', ['SPEED', 'JUMP', 'CHECK'],
        subject=target, optional=False, preferred=['SPEED'], labels={
            'SPEED': 'Reduce Speed by 5 feet', 'JUMP': 'Prevent jumping',
            'CHECK': 'Disadvantage on the next check to Shove or Grapple'},
        trigger=f'{ctx.action.display_name} hits {target.display_name} on the same ground; no extra Action or CP; lasts until your next turn')
    choice = (chosen or ['SPEED'])[0]
    if choice == 'SPEED':
        run_effects(ctx, [{'type': 'speed', 'flat': -5, 'applies_to': 'target', 'expires_on': 'START_OF_SOURCE_NEXT_TURN'}])
    elif choice == 'JUMP':
        ctx.engine._apply_condition(target, C + 'earth_no_jump', WEIGHT, ctx.actor.entity_id,
            expires_on='START_OF_SOURCE_NEXT_TURN', data={'rule': {'no_jumping': 1}, 'label': 'Weight-Seal Strike: cannot jump until the attacker’s next turn'})
    else:
        ctx.engine._apply_condition(target, WEIGHT_CHECK, WEIGHT, ctx.actor.entity_id,
            expires_on='START_OF_SOURCE_NEXT_TURN', data={'label': 'Weight-Seal Strike: disadvantage on next check to Shove or Grapple'})


@hook('skill_check_mode')
def weight_check_mode(ctx, subject, ability, skill):
    if _held(subject, WEIGHT_CHECK) and _weight_check_action(ctx.engine, ctx.source):
        return 'DISADVANTAGE'


@hook('event')
def weight_check_spent(engine, event_type, kwargs):
    from .condition_ownership import remove_instance
    if event_type != 'CHECK_ROLLED' or not _weight_check_action(engine, kwargs.get('source_definition_id')):
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is not None:
        for held in list(_held(actor, WEIGHT_CHECK)):
            remove_instance(engine, actor, held.instance_id, WEIGHT)


def _mule_eligible(ctx, subject):
    from .ability_source import mechanic_of
    if not rows(ctx.engine, subject, 'mule') or subject.turn_flags.get('_round_mule_shoulder_used'):
        return False
    # Source-qualified defense: Earth itself is explicit; other weight/Force source
    # classification needs an authored delivery tag and is reported as a remaining seam.
    source = mechanic_of(ctx.action)
    if not source.startswith('EARTH_') and not source.startswith('TAL_EARTH_'):
        return False
    return True


def _mule_ignore(ctx, subject, name):
    subject.turn_flags['_round_mule_shoulder_used'] = 1
    note(ctx.engine, MULE, subject, f'Mule-Shoulder Method: {subject.display_name} ignores {name} from Earth once this short rest.')


@hook('condition_state')
def mule_condition(ctx, subject, effect):
    name = str(effect.get('condition') or '').lower()
    if name in ('prone', 'grappled') and _mule_eligible(ctx, subject):
        _mule_ignore(ctx, subject, name)
        return False


@hook('mark_apply')
def mule_mark(ctx, effect, subject, expires, data):
    if effect.get('mark') == MARK and _mule_eligible(ctx, subject):
        _mule_ignore(ctx, subject, 'a Burden Mark')
        return True


@hook('movement_step')
@hook('forced_movement_step')
def foundation_remembers(engine, mover, previous, nxt, intent):
    from .rider_choices import pick
    from .condition_ownership import refresh_owned
    for owner in engine.state.actors.values():
        if not owner.active or not rows(engine, owner, 'remembers'):
            continue
        cells = foundation_cells(engine, owner)
        cell = (nxt.x, nxt.y)
        if cell not in cells:
            continue
        record = next((c for c in owner.conditions.values() if c.condition_id == VISITS), None)
        history = dict(record.data) if record is not None else {}
        key = f'visit:{mover.entity_id}:{nxt.x}:{nxt.y}'
        prior = history.get(key)
        history[key] = int(engine.state.round_number)
        history['label'] = 'Buried Foundation Remembers: remembered visits to your ground'
        refresh_owned(engine, owner, VISITS, owner.entity_id, REMEMBERS)
        engine._apply_condition(owner, VISITS, REMEMBERS, owner.entity_id, expires_on='UNTIL_REMOVED', data=history)
        if prior is not None and engine.state.round_number - int(prior) <= 14400:
            note(engine, REMEMBERS, owner, f'Buried Foundation Remembers: {mover.display_name} returned to this space within 24 hours.')
            if mover.team_id != owner.team_id and not marked(mover, owner.entity_id):
                chosen = pick(engine, owner, 'foundation_remembers', 'Buried Foundation Remembers', ['MARK'],
                    subject=mover, preferred=['MARK'], trigger=f'{mover.display_name} returns to a remembered Foundation Space',
                    labels={'MARK': 'Give a Burden Mark (Earth weight); no Action or CP cost'})
                if chosen:
                    give_mark(engine, owner, mover, REMEMBERS)


# --------------------------------------------------------------------------- Wheel-Rut and Load-Bearing Back
RUT = T + 'SINK_THE_WHEEL_RUT'
RUT_WATCH = C + 'earth_rut_watch'


@effect('earth_rut_watch')
def rut_watch(ctx: Any, eff: dict[str, Any]) -> None:
    """A successful zone save starts counting subsequent inside-ground steps.

    Zone delivery supplies its exact area id, so overlapping owners cannot lend
    one another distance. A fresh successful save resets only that area's watch.
    """
    from .damage_delivery import frame
    from .effect_durations import token
    from .condition_ownership import remove_instance

    subject = ctx.target
    zone_id = frame(ctx.engine)['area']
    zone = ctx.engine.state.zones.get(zone_id)
    if subject is None or zone is None or not zone.active:
        return
    for held in _held(subject, RUT_WATCH):
        if held.data.get('zone') == zone_id:
            remove_instance(ctx.engine, subject, held.instance_id, RUT)
    current = ctx.engine.state.actors[ctx.engine.state.current_actor_id]
    ctx.engine._apply_condition(subject, RUT_WATCH, RUT, ctx.actor.entity_id,
        expires_on=token('end', current.entity_id, current.turns_started),
        data={'zone': zone_id, 'feet': 0,
              'label': 'Sink the Wheel-Rut: move 10 feet inside this area before this turn ends and gain a Burden Mark. '
                       'Its creator can spend the mark to slow you, trip you, or soften your blows.'})


@hook('movement_step')
@hook('forced_movement_step')
def rut_movement(engine: Any, mover: Any, previous: Any, destination: Any, intent: Any) -> None:
    """Count each landed step inside the ground area, willing or forced.

    The two step hooks are mutually exclusive. Zone entry resolves before this
    callback; requiring membership at both endpoints excludes the entry step.
    Shared volume membership includes a Large creature's overlapping footprint,
    while the base-plane check keeps airborne travel out of this ground rider.
    """
    from .condition_ownership import remove_instance
    from ..spatial_areas import zone_contains

    for held in list(_held(mover, RUT_WATCH)):
        zone = engine.state.zones.get(str(held.data.get('zone', '')))
        owner = engine.state.actors.get(held.source_actor_id)
        if zone is None or not zone.active or owner is None:
            remove_instance(engine, mover, held.instance_id, RUT)
            continue
        if previous.z != zone.center.z or destination.z != zone.center.z:
            continue
        if not zone_contains(engine, mover, zone, at=previous) or not zone_contains(engine, mover, zone, at=destination):
            continue
        feet = int(held.data.get('feet', 0)) + engine.grid.square_size_ft
        remove_instance(engine, mover, held.instance_id, RUT)
        if feet >= 10:
            give_mark(engine, owner, mover, RUT)
        else:
            engine._apply_condition(mover, RUT_WATCH, RUT, owner.entity_id,
                expires_on=held.expires_on, data={**held.data, 'feet': feet})


@effect('earth_load_mark')
def load_bearing_mark(ctx: Any, eff: dict[str, Any]) -> None:
    """Load-Bearing Back's existing ally-reaction passes its actual force source."""
    from ..senses import perceives

    source = ctx.engine.state.actors.get(ctx.typed.get('triggering_source_id'))
    if source is not None and (_held(ctx.actor, STANCE) or _on_foundation(ctx.engine, ctx.actor, ctx.actor)) \
            and perceives(ctx.engine, ctx.actor, source):
        give_mark(ctx.engine, ctx.actor, source, T + 'LOAD_BEARING_BACK', hostile_only=False)


# --------------------------------------------------------------------------- Packed Road Step
PACKED_ROAD = T + 'PACKED_ROAD_STEP'
PACKED_RECORD = C + 'earth_packed_road'
PACKED_LABEL = 'Packed Road Step'


def _packed_cl(engine: Any, owner: Any) -> int:
    found = rows(engine, owner, 'packed_road')
    return int(found[0].get('cl') or 1) if found else 1


def _packed_count(cl: int) -> int:
    """Printed: one willing creature, two at CL 5, three at CL 11."""
    return 3 if cl >= 11 else 2 if cl >= 5 else 1


def _packed_data(engine: Any, owner: Any) -> dict[str, Any]:
    """The live Packed Road Step record, or {} once it has ended.

    "Until the start of your next turn" is read from the owner's own turn counter, so the
    waiver ends when the owner's next turn begins and never lingers by accident."""
    held = next((c for c in owner.conditions.values()
                 if c.condition_id == PACKED_RECORD and c.source_actor_id == owner.entity_id), None)
    if held is None or owner.turns_started > int((held.data or {}).get('turn') or 0):
        return {}
    return dict(held.data or {})


def _packed_cells(raw: Any) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for pair in str(raw or '').split(';'):
        x, _, y = pair.partition(',')
        if x.strip().lstrip('-').isdigit() and y.strip().lstrip('-').isdigit():
            out.add((int(x), int(y)))
    return out


def _answering_for_itself(engine: Any, creature: Any) -> bool:
    """Whether nobody answers for this creature, so its own controller picks every option it is
    offered (checklist 9: an AI actor decides automatically)."""
    return (getattr(engine, 'typed_control_modes', None) or {}).get(creature.entity_id) in ('LOCAL_AUTO', 'API_AUTO')


@hook('action_completed')
def packed_road_choice(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    """Packed Road Step: "When you create Foundation Spaces with Set Foundation, choose one willing
    creature you can see. Until the start of your next turn, that creature also ignores nonmagical
    difficult terrain in those spaces. At CL 5, choose two willing creatures. At CL 11, choose three."

    The waiver itself is the shared ``difficult_exempt`` query below (the ordinary movement-cost
    quote already honours it, so this reaches live movement pricing and candidate quotes together).
    Only this choice is new: the chosen creatures and the spaces they cover are recorded on the
    owner, so the engine resolves the printed effect instead of leaving it to the GM.

    The printed word is "willing", which the table cannot verify. A player is therefore offered
    every creature they can see and decides who is willing; the prompt names the word. An AI
    answers the same choice, and it only ever counts its own allies as willing -- spending the
    printed gift on an enemy would hand that enemy the movement benefit without its consent."""
    from ..target_knowledge import can_see
    from .condition_ownership import refresh_owned
    from .effect_durations import token
    from .needle import ask, checkpoint_id

    if not actor.active or not rows(engine, actor, 'packed_road'):
        return
    if _feature(engine, source_definition_id) != 'EARTH_BASE_SET_FOUNDATION':
        return
    cells = foundation_cells(engine, actor)
    if not cells:
        return
    count = _packed_count(_packed_cl(engine, actor))
    audience = [a for a in engine.state.actors.values() if a.active and can_see(engine, actor, a)]
    allies = [a for a in audience if a.team_id == actor.team_id]
    allies.sort(key=lambda a: (a.entity_id != actor.entity_id, a.display_name, a.entity_id))
    if _answering_for_itself(engine, actor):
        audience = allies  # the AI's own controller fills every slot it is given, so it is offered only willing allies
    else:
        rest = [a for a in audience if a not in allies]
        rest.sort(key=lambda a: a.display_name)
        audience = allies + rest
    picks = ask(engine, getattr(engine, '_active_intent', None),
                checkpoint_id(engine, 'packed_road', actor.entity_id, source_definition_id), actor,
                CHOICE + 'packed_road', [a.entity_id for a in audience],
                labels={a.entity_id: a.display_name for a in audience},
                minimum=0, maximum=count, default='all', name=PACKED_LABEL, feature_id=PACKED_ROAD,
                preferred=[a.entity_id for a in allies],
                prompt=f'{PACKED_LABEL}: choose up to {count} willing '
                       f'{"creature" if count == 1 else "creatures"} you can see '
                       f'(more from deeper cultivation: 2 at Cultivation Level 5, 3 at Cultivation Level 11). '
                       f'Each one moves through your Foundation Spaces -- the ground you claimed with Set Foundation -- '
                       f'without paying extra movement for nonmagical difficult terrain, such as loose rubble '
                       f'or sand. Magical difficult terrain still costs extra movement. '
                       f'It lasts until the start of your next turn and costs no '
                       f'Action or Cultivation Points.',
                prompt_context={'duration': 'until the start of your next turn'})
    refresh_owned(engine, actor, PACKED_RECORD, actor.entity_id, PACKED_ROAD)
    engine._apply_condition(actor, PACKED_RECORD, PACKED_ROAD, actor.entity_id,
        # "until the start of your next turn", by the owner's own turn counter: the engine's turn sweep
        # takes the record off and its pill with it, instead of leaving a spent benefit on the sheet.
        expires_on=token('start', actor.entity_id, int(actor.turns_started) + 1), data={
        # Capped here as well as in the menu: the printed count is a limit, not a suggestion.
        'chosen': ','.join(picks[:count]),
        'cells': ';'.join(f'{x},{y}' for x, y in sorted(cells)),
        'turn': int(actor.turns_started),
        'label': PACKED_LABEL + f': up to {count} chosen '
                f'{"creature moves" if count == 1 else "creatures move"} through the ground you claimed with Set '
                f'Foundation without extra movement for nonmagical difficult terrain; magical difficult terrain '
                f'still costs extra movement. Ends at the start of your next turn; no Action or Cultivation Point cost'})


@hook('difficult_exempt')
def packed_road_waiver(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    """Packed Road Step's two printed waivers.

    "Your movement through your own Foundation Spaces does not cost extra movement from
    nonmagical difficult terrain" is the owner's own Foundation Spaces. "That creature also
    ignores nonmagical difficult terrain in those spaces" is the record above, which ends at the
    start of the owner's next turn. Both are read together: a creature's own Foundation and every
    grant it has been given are one set of spaces, so the first grant does not hide the others.

    Both clauses say *nonmagical*, so only the table's own ground is waived
    (zones.nonmagical_difficult_cells): ground an ability made -- an Earthbind Line, a
    Difficult Terrain patch, a wall -- stays difficult for a creature Packed Road Step covers.
    Returning ``None`` (not an empty set) keeps every creature without the talent exactly as it
    was, including fights saved before this talent existed."""
    from .. import zones

    if actor is None or not actor.active:
        return None
    covered: set[tuple[int, int]] = set()
    if rows(engine, actor, 'packed_road'):
        covered |= foundation_cells(engine, actor)
    for owner in engine.state.actors.values():
        if not owner.active or not rows(engine, owner, 'packed_road'):
            continue
        data = _packed_data(engine, owner)
        if data and actor.entity_id in str(data.get('chosen') or '').split(','):
            covered |= _packed_cells(data.get('cells'))
    if not covered:
        return None  # nothing to waive: no zone walk for a creature no owner chose
    waived = covered & zones.nonmagical_difficult_cells(engine, actor)
    return waived or None
