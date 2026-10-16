"""Still-Water Draw Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Still-Water Draw Body (the five features and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "still_water", "role": "first_cut" | "moon"}``; Drawn from Stillness also carries the
integrated-weapon row ``{"kind": "integrated_weapon", "group": "blade", "choose": 1}`` (combat/ext/integrated_weapons.py), whose
chosen weapon is the Draw Weapon (``chosen_items``: the sheet does not record the pick). Empty-Scabbard Step's Reaction runs
``empty_scabbard_step``; Heaven Divided Before Sound's action runs ``heaven_divided``.

First Cut          a Draw Weapon hit produced by your first attack roll this turn (a Reaction on another creature's turn uses
                   that turn): + Proficiency Bonus Slashing or Force, then an asked move of up to 5 feet without provoking.
Empty-Scabbard Step  before a melee attack against you is rolled: an asked move of up to 10 feet (the executor re-checks reach
                   and sight, so an attack that no longer reaches misses); if that attack then misses while the attacker is
                   within your Draw Weapon's reach, one Draw Weapon attack against it (a Granted Attack).
One Breath, Three Horizons  "One Breath, Three Horizons (<Draw Weapon>)": an Attack action of at least two attacks spends two of
                   them (and 2 Stamina, once per turn) on a 30-foot line (its reviewed save row, with the Draw Weapon's die),
                   then an asked move of up to half your Speed to a space next to the line, then the Attack action's other
                   attacks against creatures you choose (combat/ext/attack_lines.py, the shared helper).
Still-Water Posture  at the start of your turn (asked): Speed 0 until your first Draw Weapon attack resolves; that attack has
                   Advantage, and on a hit + 3d8 Slashing or Force, no Reactions for the target until the start of its next
                   turn and an asked move of up to half your Speed. Willing movement or a teleport first ends the posture.
Heaven Divided Before Sound  a straight line to the aimed space (through hostile creatures, stopped by walls; a standing blocking
                   object on the line is attacked first and passed if destroyed): one Draw Weapon attack (+ 6d8 Slashing or
                   Force) against each creature chosen among those crossed or within 5 feet (up to Proficiency Bonus, barriers
                   counting), then a Constitution save for each creature hit: Speed 0 and no Reactions until the end of its
                   next turn, or Speed halved until the start of its next turn.
Every hook returns early for a creature without these rows or actions.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.still_water_draw_body.feature."
DRAWN = PREFIX + "drawn_from_stillness"
ONE_BREATH = PREFIX + "one_breath_three_horizons"
POSTURE = "condition:typed.still_water_posture"
STILLED = "heaven_divided_stilled"
STAMINA = "resource:core.stamina"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "still_water"}


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _item(typed: dict[str, Any]) -> str:
    return str((typed or {}).get("source") or "").rsplit(".", 1)[-1]


def draw_item(engine: Any, actor: Any) -> str | None:
    """The Draw Weapon's item (Drawn from Stillness owners only)."""
    if "first_cut" not in _roles(engine, actor):
        return None
    from .integrated_weapons import chosen_items

    mine = [a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id and str(getattr(a.economy, "value", a.economy)) == "ACTION"]
    found = chosen_items(mine, "blade", 1)
    return found[0] if found else None


def _is_draw(engine: Any, actor: Any, typed: dict[str, Any]) -> bool:
    item = draw_item(engine, actor)
    return bool(item) and bool((typed or {}).get("weapon")) and _item(typed) == item


def _draw_attacks(engine: Any, actor: Any) -> dict[str, Any]:
    """The Draw Weapon's melee attack actions (the plain one and its "(Constitution)"/"(Dexterity)" variants)."""
    item = draw_item(engine, actor)
    out = {}
    for action in sorted(engine.action_catalog.values(), key=lambda a: a.source_definition_id):
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id != actor.entity_id or not item or _item(typed) != item or not typed.get("weapon") or typed.get("range_ft") \
                or (action.parameters or {}).get("player_only") or str(getattr(action.economy, "value", action.economy)) != "ACTION":
            continue
        if "#" in action.source_definition_id and "#integrated" not in action.source_definition_id:
            continue
        if any(isinstance(e, dict) and e.get("type") == "attack" for e in typed.get("effects") or []):
            out[action.source_definition_id] = action
    return out


def _pick_draw(engine: Any, intent: Any, actor: Any, target: Any, name: str) -> Any:
    from .needle import ask, checkpoint_id

    attacks = _draw_attacks(engine, actor)
    if len(attacks) <= 1:
        return next(iter(attacks.values()), None)
    preferred = [k for k in attacks if k.endswith("#integrated_con")] or list(attacks)
    picked = ask(engine, intent, checkpoint_id(engine, "draw_attack", target.entity_id), actor, "choice:needle.draw_weapon_attack", sorted(attacks),
                 labels={k: a.display_name for k, a in attacks.items()}, preferred=preferred[:1], target_id=target.entity_id, name=name,
                 prompt=f"{name}: which Draw Weapon attack against {target.display_name}?")
    return attacks.get(picked[0] if picked else preferred[0]) or attacks[preferred[0]]


def _granted(engine: Any, actor: Any, action: Any, target: Any, intent: Any, extra_hits: list[dict[str, Any]] = ()) -> None:
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    attack = next((copy.deepcopy(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return
    attack.update(count=1, granted_attack_root=True)
    attack["on_hit"] = [*(attack.get("on_hit") or []), *copy.deepcopy(list(extra_hits))]
    te.run_effects(te.Context(engine, actor, action, intent, {**typed, "effects": [attack], "granted_attack": True}, [target], target, {}), [attack])


def _free_move(engine: Any, intent: Any, mover: Any, feet: int, choice_id: str, name: str, *, near: Any = None) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(engine, mover, feet) if feet > 0 else {}
    if near is not None:
        paths = {k: p for k, p in paths.items() if any(engine.grid.distance_ft(p[-1], cell) <= engine.grid.square_size_ft for cell in near)}
    if not paths:
        return
    picked = ask(engine, intent, checkpoint_id(engine, "still_water_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: move up to {feet} feet without provoking Opportunity Attacks?")
    if picked and picked[0] in paths:
        step(engine, mover, paths[picked[0]], PREFIX + "still_water")


def _rolls_this_turn(engine: Any, actor: Any) -> int:
    count = 0
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED":
            break
        if event.event_type == "ATTACK_ROLLED" and event.actor_id == actor.entity_id:
            count += 1
    return count


def _end_posture(engine: Any, actor: Any, reason: str) -> bool:
    for iid, held in list(actor.conditions.items()):
        if held.condition_id == POSTURE and held.source_definition_id == PREFIX + "moon_reflected_before_motion":
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", PREFIX + "moon_reflected_before_motion", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": POSTURE, "instance_id": iid, "reason": reason})
            return True
    return False


def _in_posture(actor: Any) -> bool:
    return any(c.condition_id == POSTURE for c in actor.conditions.values())


# ------------------------------------------------------------------------------------------- First Cut and the posture
@hook("after_hit")
def draw_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or target.team_id == actor.team_id or not _is_draw(engine, actor, ctx.typed):
        return
    from .. import typed_executor as te

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    first_cut = _rolls_this_turn(engine, actor) == 1 and actor.turn_flags.get("_round_first_cut") != _stamp(engine)
    if first_cut:
        actor.turn_flags["_round_first_cut"] = _stamp(engine)
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": int(actor.proficiency_bonus or 2), "damage_types": ["slashing", "force"],
                              "evidence": "First Cut: + Proficiency Bonus"}])
    posture = _in_posture(actor)
    if posture and target.active:
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["slashing", "force"],
                              "evidence": "Still-Water Posture: + 3d8"},
                             {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    if posture:
        _end_posture(engine, actor, "ATTACK_RESOLVED")
    moves = [*([(5, "choice:needle.first_cut_move", "First Cut")] if first_cut else []),
             *([(int(engine._effective_speed(actor)) // 2, "choice:needle.still_water_posture_move", "Still-Water Posture")] if posture else [])]
    dash = actor.turn_flags.get("_still_water_dash")
    if isinstance(dash, list):
        dash.extend(moves)  # during Heaven Divided's straight line: offered once the line ends
        return
    for feet, choice_id, name in moves:
        if actor.active:
            _free_move(engine, ctx.intent, actor, feet, choice_id, name)


@hook("attack_mode")
def posture_advantage(ctx: Any, target: Any) -> str | None:
    if _in_posture(ctx.actor) and _is_draw(ctx.engine, ctx.actor, ctx.typed):
        return "ADVANTAGE"
    return None


@hook("attack_resolved")
def posture_spent(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    """A missed Draw Weapon attack also restores the Speed (no damage, Reaction denial or move). Empty-Scabbard Step's watch
    ends with the attack it answered."""
    if not hit and _in_posture(ctx.actor) and _is_draw(ctx.engine, ctx.actor, ctx.typed):
        _end_posture(ctx.engine, ctx.actor, "ATTACK_RESOLVED")
    if hit and target is not None and (target.turn_flags.get("_scabbard_watch") or {}).get("attacker") == ctx.actor.entity_id:
        target.turn_flags.pop("_scabbard_watch", None)


@hook("turn_start_choice")
def enter_posture(engine: Any, actor: Any) -> None:
    if "moon" not in _roles(engine, actor) or not actor.active or not _draw_attacks(engine, actor):
        return
    from .needle import ask, checkpoint_id

    intent = getattr(engine, "_active_intent", None)
    picked = ask(engine, intent, checkpoint_id(engine, "still_water_posture", actor.entity_id), actor, "choice:needle.still_water_posture", ["enter"],
                 labels={"enter": "Enter Still-Water Posture: Speed 0 until your first Draw Weapon attack, which has Advantage (+ 3d8 on a hit)"},
                 allow_decline=True, default="decline", target_id=actor.entity_id, name="Moon Reflected Before Motion",
                 prompt="Moon Reflected Before Motion: enter Still-Water Posture this turn?")
    if picked:
        engine._apply_condition(actor, POSTURE, PREFIX + "moon_reflected_before_motion", actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"label": "Still-Water Posture: Speed 0 until your first Draw Weapon attack (Advantage, + 3d8 on a hit)"})


@hook("event")
def posture_broken(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"Any willing movement, teleportation, or spatial relocation before that attack ends the posture immediately"."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    payload = kwargs.get("payload") or {}
    if actor is not None and not payload.get("forced") and _in_posture(actor):
        _end_posture(engine, actor, "MOVED")


# ------------------------------------------------------------------------------------------------ Empty-Scabbard Step
@effect("empty_scabbard_step")
def empty_scabbard_step(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    engine, me, attacker = ctx.engine, ctx.actor, ctx.target
    if attacker is None:
        return
    paths = routes(engine, me, 10)
    if paths:
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "empty_scabbard", me.entity_id), me, "choice:needle.empty_scabbard_step", sorted(paths),
                     allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=me.entity_id,
                     name="Empty-Scabbard Step",
                     prompt=f"Empty-Scabbard Step: move up to 10 feet before {attacker.display_name}'s attack is rolled (out of its reach, it misses).")
        if picked and picked[0] in paths:
            step(engine, me, paths[picked[0]], PREFIX + "empty_scabbard_step")
    me.turn_flags["_scabbard_watch"] = {"attacker": attacker.entity_id, "after": len(engine.events)}


@hook("after_miss")
def scabbard_counter(ctx: Any, target: Any) -> None:
    engine, attacker = ctx.engine, ctx.actor
    watch = (target.turn_flags.get("_scabbard_watch") or {}) if target is not None else {}
    if watch.get("attacker") != attacker.entity_id:
        return
    target.turn_flags.pop("_scabbard_watch", None)
    rolled = [e for e in engine.events[int(watch.get("after") or 0):] if e.event_type == "ATTACK_ROLLED" and e.actor_id == attacker.entity_id]
    if len(rolled) != 1 or not target.active or not attacker.active:
        return  # not the attack the step answered
    action = _pick_draw(engine, ctx.intent, target, attacker, "Empty-Scabbard Step")
    if action is None or engine._distance_actor_to_actor(target, attacker) > int(action.range_ft or 5):
        return
    _granted(engine, target, action, attacker, ctx.intent)


# ------------------------------------------------------------------------------------------ One Breath, Three Horizons
@hook("compile_actions")
def one_breath_actions(info: dict[str, Any]) -> list[Any] | None:
    """The Draw Weapon's Attack action with two of its attacks spent on the line (combat/ext/attack_lines.py)."""
    if ONE_BREATH not in info["owned_ids"] or DRAWN not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import EconomyKind
    from .attack_lines import line_variants
    from .integrated_weapons import chosen_items

    items = chosen_items([a for a in info["actions"] if a.economy == EconomyKind.ACTION], "blade", 1)
    bases = [a for a in info["actions"] if items and _item((a.parameters or {}).get("typed") or {}) == items[0]
             and not ((a.parameters or {}).get("typed") or {}).get("range_ft")]
    return line_variants(info, ONE_BREATH, bases, replace=2, area={"shape": "line", "size_ft": 30, "width_ft": 5}, stamina=2,
                         name="One Breath, Three Horizons", move="half_speed_beside_line") or None


@hook("candidate_allowed")
def heaven_divided_square(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    if params.get("heaven_divided") and getattr(candidate, "destination", None) is not None and not engine.grid.placement_legal(
            candidate.destination, footprint=engine._footprint(actor), occupied_cells=engine._occupied_cells_except(actor.entity_id)):
        return False  # "An unoccupied space within 120 feet"
    return None


@hook("compile_actions")
def heaven_divided_aim(info: dict[str, Any]) -> None:
    """Heaven Divided Before Sound is aimed at any square in range and sight (gate4_engine any_cell), not only near a creature."""
    for action in info["actions"]:
        if ((action.parameters or {}).get("typed") or {}).get("source") == PREFIX + "heaven_divided_before_sound" and action.target_kind == "CELL":
            action.parameters["any_cell"] = True  # this character's own action, being compiled
            action.parameters["heaven_divided"] = True


# ----------------------------------------------------------------------------------------- Heaven Divided Before Sound
def _line(start: Any, end: Any) -> list[Any]:
    from ..gate2_runtime_models import Position

    cells, x, y = [start], start.x, start.y
    dx, dy = abs(end.x - x), -abs(end.y - y)
    sx, sy = (1 if end.x > x else -1), (1 if end.y > y else -1)
    err = dx + dy
    while (x, y) != (end.x, end.y):
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
        cells.append(Position(x=x, y=y))
    return cells


def _barrier(engine: Any, cell: Any) -> Any:
    return next((o for o in engine.state.objects.values() if o.position == cell and not o.destroyed and (o.component or {}).get("blocks")
                 and o.current_hp is not None), None)


def _cut_barrier(ctx: Any, action: Any, obj: Any) -> None:
    """"Make one Draw Weapon attack against it before moving through. On a hit, deal normal damage plus 6d8"."""
    from ..gate2_runtime_models import DiceSpec
    from .objects import deal

    engine, actor = ctx.engine, ctx.actor
    typed = (action.parameters or {}).get("typed") or {}
    weapon = typed.get("weapon") or {}
    bonus = int((typed.get("numbers") or {}).get("attack_bonus") or 0)
    roll = engine.roller.d20(
        modifier=bonus,
        actor_id=actor.entity_id,
        reason=f'ATTACK:{ctx.source}:object',
        mode=engine.direct_attack_mode(actor),
    )
    engine._record_roll(roll)
    natural = int(roll.natural_result or 0)
    hit = natural != 1 and (natural == 20 or roll.total >= int(obj.ac or 10))
    engine._append_event("ATTACK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(obj.object_id,),
                         payload={**roll.model_dump(mode="json"), "modified_total": int(roll.total), "target_ac": int(obj.ac or 10), "cover_bonus": 0,
                                  "provisional_hit": hit, "object_id": obj.object_id})
    if not hit:
        return
    main = engine.roller.roll(DiceSpec(**weapon["damage"]) if weapon.get("damage") else DiceSpec(count=1, sides=4, modifier=0),
                              actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}:object", critical=natural == 20)
    engine._record_roll(main)
    extra = engine.roller.roll(DiceSpec(count=6, sides=8, modifier=0), actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}:object:6d8", critical=natural == 20)
    engine._record_roll(extra)
    deal(engine, actor, obj, [(int(main.total), str(weapon.get("damage_type") or "SLASHING").upper()), (int(extra.total), "FORCE")], ctx.source)


@effect("heaven_divided_hit")
def heaven_divided_hit(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.target is not None:
        hits = ctx.actor.turn_flags.setdefault("_heaven_divided_hits", [])
        if ctx.target.entity_id not in hits:
            hits.append(ctx.target.entity_id)


@effect("heaven_divided")
def heaven_divided(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .effect_durations import token
    from .needle import ask, checkpoint_id
    from .rider_movement import step

    engine, actor = ctx.engine, ctx.actor
    aim = ctx.damage_cache.get("_checkpoint_aim") or ctx.destination
    if aim is None or aim == actor.position:
        return
    line = _line(actor.position, aim)[: int(row.get("range_ft") or 120) // engine.grid.square_size_ft + 1]
    pb = int(actor.proficiency_bonus or 2)
    near = {}
    for other in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not other.active or other.team_id == actor.team_id:
            continue
        spots = [(engine.grid.distance_ft(cell, spot), i) for i, cell in enumerate(line[1:], start=1) for spot in engine._actor_cells(other)]
        best = min(spots) if spots else None
        if best is not None and best[0] <= 5:
            near[other.entity_id] = best[1]
    chosen: list[str] = []
    if near:
        order = sorted(near, key=lambda k: (near[k], k))
        chosen = ask(engine, ctx.intent, checkpoint_id(engine, "heaven_divided", actor.entity_id), actor, "choice:needle.heaven_divided_targets", order,
                     labels={k: engine.state.actors[k].display_name for k in order}, minimum=1, maximum=min(pb, len(order)), allow_decline=True,
                     default_count=min(pb, len(order)), target_id=actor.entity_id, name="Heaven Divided Before Sound",
                     prompt=f"Heaven Divided Before Sound: choose up to {pb} creatures on or beside the line to cut.") or []
    first = next((engine.state.actors[k] for k in chosen), None)
    action = _pick_draw(engine, ctx.intent, actor, first or actor, "Heaven Divided Before Sound") if (chosen or any(_barrier(engine, c) for c in line)) else None
    budget = pb - len(chosen)
    actor.turn_flags["_heaven_divided_hits"] = []
    extra = [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 6, "sides": 8}, "damage_types": ["slashing", "force"],
              "evidence": "Heaven Divided Before Sound: + 6d8"}, {"type": "heaven_divided_hit"}]
    walked = [actor.position]
    actor.turn_flags["_still_water_dash"] = []
    for i, cell in enumerate(line[1:], start=1):
        if not actor.active or engine.state.terminal_result is not None or actor.position != walked[-1]:
            break  # something else moved the user off the line
        if not engine.grid.step_legal(actor.position, cell, occupied_cells=set(), footprint=engine._footprint(actor)):
            obj = _barrier(engine, cell)
            if obj is None or action is None or budget < 1:
                break  # a wall, total cover or a barrier it cannot cut: end before it
            budget -= 1
            _cut_barrier(ctx, action, obj)
            if not engine.grid.step_legal(actor.position, cell, occupied_cells=set(), footprint=engine._footprint(actor)):
                break  # it survived
        step(engine, actor, [actor.position, cell], PREFIX + "heaven_divided_before_sound")
        if actor.position != cell:
            break
        walked.append(cell)
        for foe_id in [k for k in chosen if near[k] == i]:
            foe = engine.state.actors[foe_id]
            if foe.active and action is not None:
                _granted(engine, actor, action, foe, ctx.intent, extra)
    # "cannot end in an occupied space": back to the last free square it crossed
    occupied = engine._occupied_cells_except(actor.entity_id)
    if actor.active and not engine.grid.placement_legal(actor.position, footprint=engine._footprint(actor), occupied_cells=occupied):
        back = next((c for c in reversed(walked[:-1]) if engine.grid.placement_legal(c, footprint=engine._footprint(actor), occupied_cells=occupied)), None)
        if back is not None:
            idx = walked.index(back)
            step(engine, actor, list(reversed(walked[idx:])), PREFIX + "heaven_divided_before_sound")
    for feet, choice_id, name in actor.turn_flags.pop("_still_water_dash", None) or []:
        if actor.active:
            _free_move(engine, ctx.intent, actor, feet, choice_id, name)
    hits = [engine.state.actors[k] for k in actor.turn_flags.pop("_heaven_divided_hits", []) if k in engine.state.actors]
    for foe in hits:
        if not foe.active:
            continue
        sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [foe], foe, {})
        te.run_effects(sub, [{"type": "save", "ability": "con", "evidence": "Heaven Divided Before Sound: Constitution saving throw",
                              "on_fail": [{"type": "condition", "applies_to": "target", "condition": STILLED,
                                           "expires_on": token("end", foe.entity_id, int(foe.turns_started) + 1)}],
                              "on_success": [{"type": "speed", "applies_to": "target", "halved": True, "expires_on": "START_OF_TARGET_NEXT_TURN"}]}])
    if not hits and not chosen:
        note(engine, PREFIX + "heaven_divided_before_sound", actor, "Heaven Divided Before Sound: no creature was cut.")
