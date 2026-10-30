"""Shared destructible walls (consumers: Force second pass and native wall attacks).

Walls you can break, walls you lay out, and walls the built-in AI raises (docket 2026-09-28; owner 2026-09-27: "Walls:
attack/break sections (AC/HP per section from the texts) ... let the owner draw a wall's direction/bends; AI raising walls
tactically"). The walls themselves are combat/zones.py's; their numbers are combat/rules/terrain.json's "walls".

  Attack a wall section   an Action: its best weapon's attacks (Extra Attack included) against a solid wall's
                          5-foot section within its reach or range. The wall's AC and hit points come from its text,
                          worked out with its creator's numbers: per section ("Each section has AC 15, Hit Points equal
                          to 20 + twice your Cultivation Level": Raise the Load-Bearing Wall, Force Wall, Glacier Wall,
                          Humble Wall) or for the whole wall ("The wall has: AC 15; HP equal to 10 x your CL": Lava Wall,
                          Scripture Wall, Puzzle Wall), with its immunities, resistances and vulnerabilities. A destroyed
                          section opens; a destroyed wall ends (and leaves what it leaves, like Lava Wall's Obsidian).
                          A wall whose text prints no AC (Dune Wall) or no hit points (Talisman Wall) is the GM's.
  Wall point              free, player only: its next wall runs from the square it is raised at through the points laid
                          out, in order (combat/zones.py wall_cells_for); "Clear wall points" forgets them.
  tactical()              for the built-in AI: a wall raised where it cuts the line between the caster and enemies at a
                          distance is worth raising when it screens two or more of them, or one while the caster is at
                          half its hit points or less (the three best squares; placing it on enemies was already offered).
"""

from __future__ import annotations

import re
from typing import Any

from . import effect, hook, run, run_strict, transform_last

SECTION_KEY = "sections"      # trigger_profile: {"x,y": damage taken} for a wall whose hit points are per section
WALL_KEY = "wall_damage"      # trigger_profile: damage the whole wall has taken


def _formula(text: Any, numbers: dict[str, Any]) -> int | None:
    """"15", "12+pb", "20+2*cl", "save_dc" with the wall creator's numbers."""
    if text is None:
        return None
    total = 0
    for term in str(text).replace(" ", "").split("+"):
        value = 1
        for factor in term.split("*"):
            if re.fullmatch(r"\d+", factor):
                value *= int(factor)
            else:
                value *= int(numbers.get(factor) or {"pb": 2, "cl": 1, "save_dc": 10}.get(factor, 0))
        total += value
    return total


def stats(zone: Any) -> dict[str, Any] | None:
    """The wall's AC and hit points (None when the text prints neither, or the wall is not solid)."""
    rule = (zone.trigger_profile.get("wall") or {}).get("object") or {}
    numbers = zone.trigger_profile.get("numbers") or {}
    ac, hp = _formula(rule.get("ac"), numbers), _formula(rule.get("hp"), numbers)
    if ac is None or hp is None:
        return None
    return {"ac": ac, "hp": hp, "scope": rule.get("scope") or "section", "immune": [str(kind).upper() for kind in rule.get("immune") or []],
            "vulnerable": [str(kind).upper() for kind in rule.get("vulnerable") or []],
            "resist_mundane": [str(kind).upper() for kind in rule.get("resist_mundane") or []],
            **({"resist": [str(kind).upper() for kind in rule["resist"]]} if rule.get("resist") else {})}  # plain Resistance (Force Wall; rider lane 10)


def defense_stats(ctx: Any, zone: Any) -> dict[str, Any] | None:
    """Per-hit wall defenses; subscribers qualify defenses without changing the saved base wall."""
    row = stats(zone)
    if row is None:
        return None
    return transform_last("wall_defenses", ctx, zone, row)


def section_at(engine: Any, cell: Any) -> tuple[Any, Any] | None:
    """The attackable wall and section in that square."""
    from .. import zones

    for zone in zones.typed_zones(engine):
        if not zone.trigger_profile.get("wall") or stats(zone) is None:
            continue
        opened = {tuple(row["cell"]) for row in zone.trigger_profile.get("openings") or []}
        for section in zone.affected_cells:
            if (section.x, section.y) == (cell.x, cell.y) and (section.x, section.y) not in opened:
                return zone, section
    return None


def hit_points_left(zone: Any, section: Any) -> int:
    row = stats(zone) or {"hp": 0, "scope": "section"}
    if row["scope"] == "wall":
        return row["hp"] - int(zone.trigger_profile.get(WALL_KEY) or 0)
    return row["hp"] - int((zone.trigger_profile.get(SECTION_KEY) or {}).get(f"{section.x},{section.y}") or 0)


# ------------------------------------------------------------------------------------------------ the actions
def _wall_names() -> set[str]:
    from .. import zones

    return set((zones.terrain_rules().get("walls") or {}))


@hook("compile_actions")
def wall_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    out = []
    # One "Attack a wall section" with its best weapon (the Attack action's attacks, Extra Attack included). The weapon
    # rides in "wall_weapon", not "weapon", so nothing that reads weapon attacks (opportunity attacks, masteries) sees it.
    weapons = []
    for row in info.get("actions") or []:
        typed = (row.parameters or {}).get("typed") or {}
        economy = getattr(row.economy, "value", row.economy)
        attack = next((effect for effect in typed.get("effects") or [] if isinstance(effect, dict) and effect.get("type") == "attack"), None)
        if (economy == "ACTION" and row.target_kind == "HOSTILE_ENTITY" and typed.get("weapon") and attack is not None
                and not typed.get("variant_of") and not str(typed.get("source") or "").startswith("improvised") and "#" not in row.source_definition_id):
            weapons.append((int(row.parameters.get("expected_damage") or 0), row.source_definition_id, row, typed, attack))
    if weapons:
        _value, _id, row, typed, attack = max(weapons, key=lambda item: (item[0], item[1]))
        name = row.display_name[:-len(" attack")] if row.display_name.endswith(" attack") else row.display_name
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.wall_attack", display_name="Attack a wall section", owner_id=row.owner_id,
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="CELL", range_ft=int(row.range_ft or 5),
            parameters={"typed": {"effects": [{"type": "wall_attack", "count": int(attack.get("count") or 1),
                                               "evidence": f"Attack one 5-foot section of a solid wall with {name} (its AC and hit points are its text's)."}],
                                  # Typed range is projectile delivery; catalog range also stores melee reach.
                                  "wall_melee": typed.get("range_ft") is None,
                                  "wall_weapon": dict(typed["weapon"]), "wall_weapon_source": _id, "mundane": typed.get("mundane"), "numbers": dict(typed.get("numbers") or {}),
                                  "duration": {"kind": "instant"}, "riders": [], "source": "wall_attack"},
                        "expected_damage": 0, "player_only": True, "any_cell": True, "wall_attack": True}))
    owned = info.get("owned_ids") or []
    walls = _wall_names()
    if any(str((info["mechanics"].get(record) or {}).get("name") or "").strip().lower() in walls for record in owned):
        for key, label, kind in (("wall_point", "Wall point", "CELL"), ("wall_clear", "Clear wall points", "SELF")):
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.{key}", display_name=label, owner_id=info["actor_id"],
                economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind=kind, range_ft=120 if kind == "CELL" else None,
                parameters={"typed": {"effects": [{"type": key}], "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                            "expected_damage": 0, "player_only": True, **({"any_cell": True} if kind == "CELL" else {}), "wall_plan": key}))
    return out or None


@hook("button_description")
def layout_description(row: dict[str, Any]) -> str | None:
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    kinds = {eff.get("type") for eff in effects}
    if "wall_point" in kinds:
        return "Free choice: select a square your next wall should pass through, in order (up to six points). The plan stays until you clear it; this does not raise the wall."
    if "wall_clear" in kinds:
        return "Free choice: clear the points you selected for your next wall. This does not remove a wall already on the map."
    return None


@hook("status_description")
def layout_status_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    """The wall-point selector stores a plan, without raising or altering a wall."""
    from .. import zones

    if row.get("condition_id") != zones.WALL_PLAN:
        return None
    return {"text": "These selected squares, in order, guide your next wall. Selecting points is free and does not raise a wall or change one already on the map. The plan stays until you clear it.",
            "source_ability": "Wall layout",
            "handling": "The table stores the selected points; activating the wall still uses its own action, range, cost and duration."}


@hook("candidate_allowed")
def wall_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = getattr(action, "parameters", None) or {}
    if parameters.get("wall_attack"):
        aim = getattr(candidate, "destination", None)
        return None if aim is not None and section_at(engine, aim) is not None else False
    if parameters.get("wall_plan") == "wall_point":
        from .. import zones

        aim = getattr(candidate, "destination", None)
        points = zones.wall_plan(actor)
        return None if aim is not None and len(points) < 6 and (aim.x, aim.y) not in points else False
    if parameters.get("wall_plan") == "wall_clear":
        from .. import zones

        return None if zones.wall_plan(actor) else False
    return None


@effect("wall_point")
def wall_point(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import zones

    aim = getattr(ctx.intent, "destination", None)
    if aim is None:
        return
    points = [list(point) for point in zones.wall_plan(ctx.actor)] + [[aim.x, aim.y]]
    zones.clear_wall_plan(ctx.engine, ctx.actor, ctx.source)
    ctx.engine._apply_condition(ctx.actor, zones.WALL_PLAN, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"points": points, "label": "Its next wall runs through " + ", ".join(f"({x},{y})" for x, y in points)})


@effect("wall_clear")
def wall_clear(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import zones

    zones.clear_wall_plan(ctx.engine, ctx.actor, ctx.source)


@effect("wall_attack")
def wall_attack(ctx: Any, eff: dict[str, Any]) -> None:
    from ..gate2_runtime_models import DiceSpec

    engine, actor = ctx.engine, ctx.actor
    aim = getattr(ctx.intent, "destination", None)
    weapon = (ctx.typed or {}).get("wall_weapon") or {}
    for index in range(int(eff.get("count") or 1)):
        found = section_at(engine, aim) if aim is not None else None
        if found is None:
            if index == 0:
                ctx.rider("No wall section there to attack.")
            return
        zone, section = found
        row = defense_stats(ctx, zone)
        roll = engine.roller.d20(
            modifier=int(ctx.numbers.get('attack_bonus') or 0),
            actor_id=actor.entity_id,
            reason=f'ATTACK:{ctx.source}:wall:{index + 1}',
            mode=engine.direct_attack_mode(actor),
        )
        engine._record_roll(roll)
        natural = int(roll.natural_result or 0)
        hit = natural != 1 and (natural == 20 or roll.total >= row["ac"])
        engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(),
                             payload={"actor": roll.model_dump(mode="json"), "dc": row["ac"], "success": hit, "check": "Attack on a wall section",
                                      "zone_id": zone.zone_id, "cell": [section.x, section.y]})
        if not hit:
            continue
        dice = DiceSpec(**weapon["damage"]) if weapon.get("damage") else DiceSpec(count=1, sides=4, modifier=0)
        damage = engine.roller.roll(dice, actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}:wall:{index + 1}", critical=natural == 20,
                                    fixed_damage=weapon.get("fixed_damage"))
        engine._record_roll(damage)
        kind = str(weapon.get("damage_type") or "UNTYPED").upper()
        kinds = [kind]
        for replacement in run_strict("attack_damage_types", ctx, {"attack_kind": "weapon"}, kinds):
            if replacement:
                kinds = list(replacement)
        if kinds != [kind]:
            from ..typed_executor import choose_damage_type
            kind = choose_damage_type(ctx, kinds, [])
        amount = int(damage.total)
        if kind in row["immune"]:
            amount = 0
        elif kind in row.get("resist", ()) or ((ctx.typed or {}).get("mundane") and ("ALL" in row["resist_mundane"] or kind in row["resist_mundane"])):
            amount //= 2  # "Resistances Bludgeoning, Piercing, Slashing" (Force Wall); "Resistance to nonmagical damage" (Lava Wall) / "from noncultivated attacks" (Puzzle Wall)
        if kind in row["vulnerable"]:
            amount *= 2
        amount *= int(row.get("damage_multiplier") or 1)
        _damage(engine, zone, section, amount, ctx.source, kind)
        if amount > 0:
            run_strict("wall_attack_damage", ctx, zone, section, amount,
                       (ctx.typed or {}).get("wall_melee") is True)
        if aim is None or section_at(engine, aim) is None:
            return  # it broke


def _damage(engine: Any, zone: Any, section: Any, amount: int, source: str, kind: str) -> None:
    from .. import zones

    row = stats(zone)
    key = f"{section.x},{section.y}"
    if row["scope"] == "wall":
        taken = int(zone.trigger_profile.get(WALL_KEY) or 0) + amount
        zone.trigger_profile = {**zone.trigger_profile, WALL_KEY: taken}
    else:
        sections = dict(zone.trigger_profile.get(SECTION_KEY) or {})
        taken = sections[key] = int(sections.get(key) or 0) + amount
        zone.trigger_profile = {**zone.trigger_profile, SECTION_KEY: sections}
    left = row["hp"] - taken
    engine._append_event("GM_RIDER", source, actor_id=engine.state.current_actor_id,
                         payload={"rider": f"{zone.trigger_profile.get('name') or 'Wall'}: {amount} {kind.lower()} damage to the "
                                           f"{'wall' if row['scope'] == 'wall' else 'section'} at ({section.x},{section.y}); "
                                           f"{max(0, left)} of {row['hp']} hit points left."})
    if left > 0:
        engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})
        return
    from . import run_checkpoint
    destroyed = zone.affected_cells if row["scope"] == "wall" else tuple(
        cell for cell in zone.affected_cells if (cell.x, cell.y) == (section.x, section.y))
    run_checkpoint("zone_cells_destroyed", engine, zone, destroyed)
    if row["scope"] == "wall":
        zones.remove(engine, zone, "DESTROYED")
        return
    zone.affected_cells = tuple(cell for cell in zone.affected_cells if (cell.x, cell.y) != (section.x, section.y))
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})
    if not zone.affected_cells:
        zones.remove(engine, zone, "DESTROYED")
    zones.sync_walls(engine)


# ------------------------------------------------------------------------------------------------ the AI raises a wall
def tactical(engine: Any, actor: Any, action: Any, out: list[Any]) -> list[Any]:
    """The built-in AI is offered a wall on empty ground only where it screens: the wall crosses the straight line from
    an enemy more than 5 feet away to the caster, and it blocks movement, sight or gives cover. Worth 4 per enemy screened
    (plus 4 while the caster is at half its hit points or less); two enemies, or one while it is hurt, or it is not
    offered. The three best squares (then by square) keep their place; the rest stay a player's choice."""
    from .. import zones

    typed = (action.parameters or {}).get("typed") or {}
    spec = typed.get("zone_spec") or {}
    rule = spec.get("wall") or {}
    if not (rule.get("blocks_movement") or rule.get("obscures") or rule.get("cover")):
        return out
    if any(zone.owner_id == actor.entity_id and zone.trigger_profile.get("wall") for zone in zones.typed_zones(engine)):
        return out  # one wall of its own at a time is enough for the AI
    from ..candidate_knowledge import roster
    observed = roster(engine)
    hostiles = [other for other in (engine.state.actors.values() if observed is None else observed)
                if other.active and other.team_id != actor.team_id]
    if not hostiles or any(engine._distance_actor_to_actor(actor, other) <= 5 for other in hostiles):
        return out
    hurt = actor.current_hp * 2 <= actor.maximum_hp
    size, thick = int(spec.get("size_ft") or 30), int(rule.get("thick_ft") or 5)
    scored = []
    for index, candidate in enumerate(out):
        if not (candidate.metadata or {}).get("empty_area") or candidate.destination is None:
            continue
        cells = {(cell.x, cell.y) for cell in zones.wall_cells(engine, actor.position, candidate.destination, size, thick)}
        if (actor.position.x, actor.position.y) in cells:
            continue
        screened = sum(1 for other in hostiles if cells & set(engine.grid.ray_cells(other.position, actor.position)[1:-1]))
        if screened >= 2 or (screened and hurt):
            scored.append((-(4 * screened + (4 if hurt else 0)), candidate.destination.x, candidate.destination.y, index))
    best = {index: -value for value, _x, _y, index in sorted(scored)[:3]}
    if not best:
        return out
    return [candidate.model_copy(update={"metadata": {"expected_damage": best[index], "hostiles_in_area": 0, "tactical_wall": True}})
            if index in best else candidate for index, candidate in enumerate(out)]


def damage_section(engine, zone, section, amount, source, kind):
    """Commit damage against the wall's frozen HP and open only a destroyed section."""
    _damage(engine, zone, section, amount, source, kind)
