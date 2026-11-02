"""Sand sphere riders (rider lane C4, 2026-09-30; owner: "i want everything we can automated, keep going until its only the
non-combat ones left"). Printed text: authority/typed_mechanics/rules_text.json. Shared Sand Terrain queries live in
combat/ext/sand_terrain.py; the Buried state in combat/ext/sand_burial.py. Every hook returns early unless the creature
owns the ability (its compiled action or reaction row) or holds a condition one of these abilities put on it.

- Dune Bank (reaction, "You or a creature within 5 feet of Sand Terrain you control is targeted by an attack roll ... The
  target gains Half Cover against the triggering attack. The sand bank collapses immediately after the attack resolves. At
  CL 11, if the target is standing in Deep or Storming Sand Terrain you control, the target instead gains Three-Quarters
  Cover"): effect ``sand_bank_cover`` puts +2 (or +5) AC on the attacked creature for that one attack roll; row_allowed /
  ally_row_allowed keep the row to a target within 5 feet of the reactor's Sand Terrain. Glass Mirage Reflection's
  successful save ("you gain Half Cover against the triggering effect") uses the same effect, and its row is kept to a
  reactor within 5 feet of its own Sand Terrain.
- Target limits (candidate_allowed), from the printed Target lines: Sand Drag "One creature standing on Sand Terrain you
  control"; Sand Coffin "One Buried creature in Sand Terrain you control"; Glass Prison "One Buried creature or one
  creature standing in Deep Sand Terrain you control".
- Glass Prison: "While restrained this way, it has Half Cover" (+2 AC and +2 Dexterity saves while its Restrained lasts)
  and "takes Piercing damage equal to your CL the first time each turn it makes an attack ... or attempts to escape"
  (attack_sequence_start and the Buried/grapple escape Actions; techniques with somatic movement stay with the GM).
- Devouring Dune Mouth: "As a Bonus Action while the effect lasts, you may force each hostile Buried creature in the area to
  repeat the save. On a failure, it takes 3d8 Bludgeoning damage": a compiled Bonus Action offered while its area is up,
  resolved by ``sand_zone_targets`` (creatures in the user's own area of a named ability, optionally bearing a condition).
- Gather Sand: "As a Bonus Action on later turns, you may move one square of Sand Terrain created by this use up to 10 feet"
  (20 feet with Dune-Heart Sand: "You may move one Sand Terrain square you control up to 20 feet when you use Gather Sand's
  Bonus Action movement"): a compiled Bonus Action moving one of its one-square Gather Sand areas (the ``move_zone`` effect)
  to an unoccupied square within reach.
- Thousand-Mile Sandstorm Body: "ranged weapon attacks that pass through the area are made with Disadvantage unless the
  attacker is you or a creature you designate" (attack_mode: the straight line between them crosses the storm; the user and
  its allies are the designated creatures).
- Event-driven states (each ability's own ``state`` row, combat/ext/states.py): Sand Shell's retaliation while its Temporary
  HP last (once a round, first melee hitter; the shell ends with its Temporary HP); Sand Clone Decoy's step and Storming square
  after the first miss by 5 or more (truesight/tremorsense/blindsight attackers may save to ignore it); Sand-Sovereign
  Incarnation's 10-foot step and Shallow square after a melee miss. Steps ask the owner (Ask me / AI) and use reaction_move.
- Glass Edge Scripture (feature block glass_edge): Scour-tagged damage to a Buried creature leaves glassy grains that cut for
  PB + key ability modifier Piercing the first time it moves 5 feet or more before the owner's next turn.
- Erode the Path of Return (feature block sand_erode): teleport_gate on a hostile creature's own teleport within 120 feet;
  the owner may spend its Reaction and 3 CP; failed Dexterity/Charisma save: the teleport fails or is tracked; success: it
  cannot be Invisible to the owner until the owner's next turn starts (masked_conditions).
- Erosion Scripture's Armor Abrasion (effect ``sand_abrasion``): the AC penalty never takes AC below 10 + Dexterity modifier.
"""
from __future__ import annotations

from typing import Any
from copy import deepcopy
from dataclasses import replace

from . import effect, hook
from .ability_source import mechanic_of
from .sand_terrain import sand_zones, standing_in, within_ft


@hook("compile_action")
def sand_reviewed_packets(action: Any, info: dict[str, Any]) -> Any:
    """Seal AUTO50 choices/eligibility in new packets; saved packets stay intact."""
    typed = (action.parameters or {}).get("typed") or {}
    rows = typed.get("effects") or []
    edge_owned = "TAL_SAND_GLASS_EDGE_SCRIPTURE" in info.get("owned_ids", ())
    choice = edge_owned and int((typed.get("numbers") or {}).get("cl") or 1) >= 5 and mechanic_of(action) in _SCOUR
    storm = mechanic_of(action) == STORM
    volley = any(row.get("type") == "sand_nearby_targets" for row in rows)
    if not choice and not volley and not storm:
        return None
    parameters = deepcopy(action.parameters)
    packet = parameters["typed"]
    if storm and packet.get("zone_spec"):
        packet["zone_spec"]["profile"] = {**(packet["zone_spec"].get("profile") or {}), "sand_designation": 1}
    if volley:
        # Mentioning Sand Terrain in the target clause does not create terrain.
        packet.pop("zone_spec", None)
    if choice:
        packet["effects"] = [{"type": "sand_glass_choice", "effects": packet["effects"]}]
    return action.model_copy(update={"parameters": parameters})


@effect("sand_glass_choice")
def glass_choice(ctx: Any, spec: dict[str, Any]) -> None:
    """Choose once per use, including all save branches and area recipients."""
    from ..typed_executor import run_effects

    run_effects(ctx, _glass_rows(ctx, spec))


@hook("before_target_reactions")
def glass_choice_before_targets(ctx: Any) -> None:
    """Choose before zone creation so subsequent turn/entry packets keep the type."""
    rows = ctx.typed.get("effects") or []
    if len(rows) == 1 and rows[0].get("type") == "sand_glass_choice":
        ctx.typed["effects"] = _glass_rows(ctx, rows[0])


def _glass_rows(ctx: Any, spec: dict[str, Any]) -> list[dict[str, Any]]:
    from .needle import ask, checkpoint_id, CHOICE

    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "glass_edge_type", ctx.source), ctx.actor,
                 CHOICE + "glass_edge_type", ["slashing", "piercing"], minimum=1, maximum=1,
                 labels={"slashing": "Slashing damage", "piercing": "Piercing damage"},
                 prompt=f"Glass Edge Scripture: choose the damage type for {ctx.action.display_name}. No extra cost.")
    rows = deepcopy(spec.get("effects") or [])
    def visit(values: list[dict[str, Any]]) -> None:
        for row in values:
            if row.get("type") in ("damage", "extra_damage", "half_damage"):
                row["damage_types"] = [chosen[0]]
            for key in ("effects", "on_hit", "on_miss", "on_fail", "on_success"):
                visit(row.get(key) or [])
            for trigger in row.get("triggers") or []:
                visit(trigger.get("effects") or [])
    visit(rows)
    if ctx.typed.get("zone_spec"):
        zone = deepcopy(ctx.typed["zone_spec"])
        visit([zone])
        ctx.typed["zone_spec"] = zone
    return rows


@effect("sand_nearby_targets")
def sand_nearby_targets(ctx: Any, spec: dict[str, Any]) -> None:
    """Needle Volley uses actual active Sand Terrain, including another caster's."""
    from .. import zones
    from .sand_terrain import is_sand
    from .rider_outcomes import targets

    terrain = [z for z in zones.typed_zones(ctx.engine) if is_sand(ctx.engine, z)]
    eligible = [actor for actor in ctx.engine.state.actors.values() if actor.active
                and ctx.engine._distance_actor_to_actor(ctx.actor, actor) <= int(spec["range_ft"])
                and any(z.affected_cells and ctx.engine.grid.distance_between_cell_sets_ft(
                    ctx.engine._effect_volume(actor), z.affected_cells) <= int(spec["near_sand_ft"]) for z in terrain)]
    targets(replace(ctx, targets=eligible), {**spec, "area_only": True})

BANK = "condition:typed.sand_bank"
DUNE_BANK, MIRAGE = "TAL_SAND_DUNE_BANK", "TAL_SAND_GLASS_MIRAGE_REFLECTION"
DRAG, COFFIN, PRISON = "TAL_SAND_SAND_DRAG", "TAL_SAND_SAND_COFFIN", "TAL_SAND_GLASS_PRISON"
MOUTH, GATHER, HEART = "TAL_SAND_DEVOURING_DUNE_MOUTH", "SAND_BASE_GATHER_SAND", "TAL_SAND_DUNE_HEART_SAND"
STORM = "TAL_SAND_THOUSAND_MILE_SANDSTORM_BODY"
BURIED, RESTRAINED = "condition:typed.buried", "condition:typed.restrained"




# ------------------------------------------------------------------------------------------------ Dune Bank / Glass Mirage
@effect("sand_bank_cover")
def bank_cover(ctx: Any, row: dict[str, Any]) -> None:
    """{"type": "sand_bank_cover", "amount": 2, "upgrade": {"min_cl": 11, "amount": 5, "strengths": ["deep", "storming"]}}:
    the creature the pending attack targets gains that much AC against this one attack roll."""
    pending = getattr(ctx.engine, "_typed_pending_attack", None) or {}
    target = ctx.engine.state.actors.get(pending.get("target") or "") or ctx.actor
    amount, upgrade = int(row.get("amount") or 2), row.get("upgrade") or {}
    if upgrade and int(ctx.numbers.get("cl") or 1) >= int(upgrade.get("min_cl") or 99) and standing_in(
            ctx.engine, ctx.actor.entity_id, target, set(upgrade.get("strengths") or ())):
        amount = int(upgrade["amount"])
    cover = "Three-Quarters Cover" if amount >= 5 else "Half Cover"
    ctx.engine._apply_condition(target, BANK, ctx.source, ctx.actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"amount": amount, "label": f"{cover} (+{amount} AC) against the attack now being made ({ctx.action.display_name})"})


@hook("ac")
def bank_ac(engine: Any, target: Any) -> int | None:
    total = sum(int((c.data or {}).get("amount") or 0) for c in target.conditions.values() if c.condition_id == BANK)
    return total or None


@hook("event")
def bank_collapses(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"The sand bank collapses immediately after the attack resolves": spent by the attack roll it was raised against."""
    if event_type != "ATTACK_ROLLED":
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is not None and any(c.condition_id == BANK for c in target.conditions.values()):
            engine._remove_condition(target, BANK, "system:sand_bank.collapsed")


def _attacked(engine: Any, fallback: Any) -> Any:
    pending = getattr(engine, "_typed_pending_attack", None) or {}
    return engine.state.actors.get(pending.get("target") or "") or fallback


@hook("row_allowed")
def bank_row(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    feature = row.get("feature_id")
    if feature == DUNE_BANK:
        return within_ft(engine, actor.entity_id, _attacked(engine, actor), 5) or False
    if feature == MIRAGE:
        return within_ft(engine, actor.entity_id, actor, 5) or False  # "while you are within 5 feet of Sand Terrain ... you created"
    return None


@hook("ally_row_allowed")
def bank_ally(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") != DUNE_BANK:
        return None
    return within_ft(engine, reactor.entity_id, subject, 5) or False


# ------------------------------------------------------------------------------------------------ printed target limits
def _target_ok(engine: Any, actor: Any, mechanic: str, target: Any) -> bool:
    buried = any(c.condition_id == BURIED for c in target.conditions.values())
    if mechanic == DRAG:
        return standing_in(engine, actor.entity_id, target)
    if mechanic == COFFIN:
        return buried and standing_in(engine, actor.entity_id, target)
    if mechanic == PRISON:
        return buried or standing_in(engine, actor.entity_id, target, {"deep"})
    return True


@hook("candidate_allowed")
def sand_targets(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    parameters = action.parameters or {}
    if parameters.get("sand_compress"):
        return bool(_own_zones(engine, actor, MOUTH))
    if parameters.get("sand_move_square"):
        return _square_move_ok(engine, actor, candidate, int(parameters["sand_move_square"]))
    mechanic = mechanic_of(action)
    if mechanic not in (DRAG, COFFIN, PRISON):
        return None
    targets = [engine.state.actors.get(t) for t in (getattr(candidate, "target_ids", None) or ())]
    if not targets or any(t is None or not _target_ok(engine, actor, mechanic, t) for t in targets):
        return False
    return None


# ------------------------------------------------------------------------------------------------ Glass Prison
def _prisoned(engine: Any, actor: Any) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == RESTRAINED
            and mechanic_of(engine.action_catalog.get(c.source_definition_id)) == PRISON]


@hook("ac")
def prison_cover(engine: Any, target: Any) -> int | None:
    return 2 if _prisoned(engine, target) else None  # Half Cover


@hook("save")
def prison_dex(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    return {"bonus": 2} if str(ability).upper() == "DEX" and _prisoned(ctx.engine, subject) else None


def _prison_cut(engine: Any, actor: Any, why: str) -> None:
    """"takes Piercing damage equal to your CL the first time each turn it makes an attack ... or attempts to escape"."""
    rows = _prisoned(engine, actor)
    if not rows or not actor.active:
        return
    flag = f"sand_prison_cut_{engine.state.round_number}_{engine.state.current_slot_index}"
    if actor.turn_flags.get(flag):
        return
    actor.turn_flags[flag] = True
    condition = rows[0]
    owner = engine.state.actors.get(condition.source_actor_id)
    action = engine.action_catalog.get(condition.source_definition_id)
    if owner is None or action is None:
        return
    from ..typed_executor import Context, run_effects

    typed = {**(action.parameters or {}).get("typed", {}), "effects": [], "riders": []}
    ctx = Context(engine, owner, action, getattr(engine, "_active_intent", None), typed, [actor], actor, {})
    run_effects(ctx, [{"type": "damage", "applies_to": "target", "formula": "cl", "damage_types": ["piercing"],
                       "evidence": f"Glass Prison: the glass cuts {actor.display_name} as it {why} (Piercing damage equal to the CL)."}])


@hook("attack_sequence_start")
def prison_attack(ctx: Any) -> None:
    if _prisoned(ctx.engine, ctx.actor):
        _prison_cut(ctx.engine, ctx.actor, "attacks")


@hook("technique_start")
def prison_escape(engine: Any, actor: Any, action: Any) -> None:
    parameters = (action.parameters or {}) if action is not None else {}
    effects = (parameters.get("typed") or {}).get("effects") or []
    escaping = parameters.get("sand_dig_free") or parameters.get("source_restraint_escape") or any(
        isinstance(row, dict) and row.get("type") in ("escape_grapple", "escape_source_restraint", "escape_binding", "trap_escape")
        for row in effects)
    if escaping and _prisoned(engine, actor):
        _prison_cut(engine, actor, "tries to escape")
    return None


# ------------------------------------------------------------------------------------------------ Devouring Dune Mouth / Gather Sand
def _own_zones(engine: Any, actor: Any, mechanic: str) -> list[Any]:
    from .. import zones

    return [zone for zone in zones.typed_zones(engine) if zone.owner_id == actor.entity_id
            and mechanic_of(engine.action_catalog.get(zone.source_definition_id)) == mechanic]


@effect("sand_zone_targets")
def zone_targets(ctx: Any, row: dict[str, Any]) -> None:
    """{"type": "sand_zone_targets", "zone_of": <mechanic id>, "condition": "buried" (optional), "hostile_only": true,
    "effects": [...]}: the nested effects against every creature standing in the user's own active area of that ability
    (and bearing the condition, when named)."""
    from dataclasses import replace

    from ..typed_executor import run_effects

    cells = {(cell.x, cell.y) for zone in _own_zones(ctx.engine, ctx.actor, str(row.get("zone_of") or "")) for cell in zone.affected_cells}
    wanted = f"condition:typed.{row['condition']}" if row.get("condition") else None
    pool = [actor for actor in sorted(ctx.engine.state.actors.values(), key=lambda a: a.entity_id)
            if actor.active and actor.entity_id != ctx.actor.entity_id and cells & set(ctx.engine._actor_cells(actor))
            and (not row.get("hostile_only") or actor.team_id != ctx.actor.team_id)
            and (wanted is None or any(c.condition_id == wanted for c in actor.conditions.values()))]
    if pool:
        run_effects(replace(ctx, targets=pool, target=pool[0] if len(pool) == 1 else None), row.get("effects") or [])


def _source_action(info: dict[str, Any], mechanic: str) -> Any:
    return next((a for a in info["actions"] if mechanic_of(a) == mechanic or str(a.source_definition_id).endswith("." + mechanic)), None)


@hook("compile_actions")
def sand_follow_ups(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    made = []
    mouth = _source_action(info, MOUTH) if MOUTH in info["owned_ids"] else None
    if mouth is not None:
        typed = (mouth.parameters or {}).get("typed") or {}
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.sand_compress", display_name="Devouring Dune Mouth: compress the dune",
            owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {"effects": [{"type": "sand_zone_targets", "zone_of": MOUTH, "condition": "buried", "hostile_only": True,
                                               "evidence": "force each hostile Buried creature in the area to repeat the save",
                                               "effects": [{"type": "save", "ability": "str", "dc": "technique_save_dc", "on_fail": [
                                                   {"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8},
                                                    "damage_types": ["bludgeoning"], "evidence": "On a failure, it takes 3d8 Bludgeoning damage as the dune compresses."}],
                                                   "on_success": []}]}],
                                  "numbers": dict(typed.get("numbers") or info["numbers"]), "duration": {"kind": "instant"}, "riders": [],
                                  "source": MOUTH, "sphere": typed.get("sphere")},
                        "expected_damage": 13, "sand_compress": True, "delivers_strike": True,
                        "description": "Bonus Action while your Devouring Dune Mouth lasts: each hostile creature Buried in its area makes a "
                                       "Strength saving throw against your save DC; on a failure it takes 3d8 Bludgeoning damage."}))
    gather = _source_action(info, GATHER) if GATHER in info["owned_ids"] else None
    if gather is not None:
        feet = 20 if HEART in info["owned_ids"] else 10
        typed = (gather.parameters or {}).get("typed") or {}
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.sand_move_square", display_name="Gather Sand: move a square of sand",
            owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="CELL", range_ft=60 + feet,
            parameters={"typed": {"effects": [{"type": "move_zone", "zone_name": "Gather Sand", "max_ft": feet,
                                               "evidence": f"move one square of Sand Terrain created by Gather Sand up to {feet} feet"}],
                                  "numbers": dict(typed.get("numbers") or info["numbers"]), "duration": {"kind": "instant"}, "riders": [],
                                  "source": GATHER, "sphere": typed.get("sphere")},
                        "expected_damage": 0, "player_only": True, "any_cell": True, "sand_move_square": feet,
                        "description": f"Bonus Action: move one square of Sand Terrain you made with Gather Sand up to {feet} feet to an "
                                       "unoccupied square."}))
    return made or None


def _square_move_ok(engine: Any, actor: Any, candidate: Any, feet: int) -> bool:
    aim = getattr(candidate, "destination", None)
    if aim is None or any(row.active and engine._footprint_intersects(row, (aim,)) for row in engine.state.actors.values()):
        return False  # "A square cannot move through a creature's space"
    squares = [zone for zone in _own_zones(engine, actor, GATHER) if len(zone.affected_cells) == 1]
    return any(0 < engine.grid.distance_ft(zone.center, aim) <= feet for zone in squares)


# ------------------------------------------------------------------------------------------------ Thousand-Mile Sandstorm Body
@hook("attack_mode")
def storm_ranged(ctx: Any, target: Any) -> str | None:
    typed = ctx.typed or {}
    weapon = typed.get("weapon")
    if ctx.engine is None:
        return None
    attacker, engine = ctx.actor, ctx.engine
    for zone in _storms(engine):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or attacker.entity_id == owner.entity_id:
            continue
        profile = zone.trigger_profile.get("profile") or {}
        if profile.get("sand_designation"):
            from ..weapon_delivery import delivery_kind
            attack = getattr(ctx, "attack_effect", None) or {}
            kind = attack.get("attack_kind") or ctx.action.parameters.get("attack_kind")
            if (delivery_kind(typed, attack, ctx.action.parameters) != "weapon"
                    or kind in ("melee", "weapon_melee") or not typed.get("range_ft", ctx.action.range_ft)):
                continue  # explicit melee/null range is never inferred from the catalog's targeting reach
            if attacker.entity_id in profile.get("ranged_exempt", []):
                continue
        elif (not weapon or int(typed.get("range_ft") or ctx.action.range_ft or 5) <= 5
              or attacker.team_id == owner.team_id):
            continue  # frozen legacy storm: retain the original range and team rule
        cells = {(cell.x, cell.y) for cell in zone.affected_cells}
        line = {(c.x, c.y) if hasattr(c, "x") else tuple(c) for c in engine.grid.ray_cells(attacker.position, target.position)}
        if cells & line:
            return "DISADVANTAGE"
    return None


def _storms(engine: Any) -> list[Any]:
    from .. import zones

    return [zone for zone in zones.typed_zones(engine) if mechanic_of(engine.action_catalog.get(zone.source_definition_id)) == STORM]


# ------------------------------------------------------------------------------------------------ states read by event hooks
SHELL, DECOY, SOVEREIGN = "TAL_SAND_SAND_SHELL", "TAL_SAND_SAND_CLONE_DECOY", "TAL_SAND_SAND_SOVEREIGN_INCARNATION"
EDGE, ERODE = "TAL_SAND_GLASS_EDGE_SCRIPTURE", "TAL_SAND_ERODE_THE_PATH_OF_RETURN"
GRAINS, CLINGING = "condition:typed.sand_glass_grains", "condition:typed.sand_clinging"
_SCOUR = {"SAND_BASE_SCOURING_HAND", "TAL_SAND_ABRADING_WARD", "TAL_SAND_ERODE_THE_PATH_OF_RETURN", "TAL_SAND_EROSION_SCRIPTURE",
          "TAL_SAND_GLASS_DESERT_JUDGMENT", "TAL_SAND_GRIT_IN_THE_EYES", "TAL_SAND_SAND_NEEDLE_VOLLEY", "TAL_SAND_THOUSAND_MILE_SANDSTORM_BODY"}
# ^ the Sand talents printed with the Scour tag ("#### Abrading Ward - Scour"); Scouring Hand is the sphere's scouring base.


def _state(engine: Any, actor: Any, name: str) -> Any:
    from . import states

    return states.active(engine, actor, name)


def _owner_context(engine: Any, owner: Any, source_id: str, targets: list[Any]) -> Any:
    """A typed context of ``owner``'s compiled action ``source_id`` (its numbers), aimed at ``targets``, for an event hook."""
    from ..typed_executor import Context

    action = engine.action_catalog.get(source_id) or next(iter(engine.action_catalog.values()))
    typed = {**((action.parameters or {}).get("typed") or {}), "effects": [], "riders": []}
    return Context(engine, owner, action, getattr(engine, "_active_intent", None), typed,
                   list(targets), targets[0] if len(targets) == 1 else None, {})


def _melee_attack(engine: Any, source_id: str) -> bool:
    from .. import typed_reactions

    action = engine.action_catalog.get(source_id)
    if action is None:
        return False
    if action.resolution_kind == "TYPED":
        return typed_reactions.melee_weapon_source(engine, source_id)
    return action.resolution_kind in ("ATTACK", "MULTI_ATTACK") and action.range_ft is None


def _ask_yes(engine: Any, owner: Any, key: str, prompt: str, label: str, name: str) -> bool:
    from .needle import CHOICE, ask, checkpoint_id

    return bool(ask(engine, None, checkpoint_id(engine, key, owner.entity_id), owner, CHOICE + key, ["use"],
                    labels={"use": label}, preferred=["use"], allow_decline=True, prompt=prompt, name=name))


def _leave_square(engine: Any, owner: Any, source_id: str, strength: str, rounds: int) -> None:
    """One 5-foot square of Sand Terrain in ``owner``'s current space (before it steps away)."""
    from .. import zones

    ctx = _owner_context(engine, owner, source_id, [])
    ctx.intent = None
    terrain = f"{strength} sand terrain"
    zones.create(ctx, {"name": f"{strength.title()} Sand Terrain", "shape": "square", "size_ft": 5, "centered_on_self": True,
                       "duration": {"kind": "rounds", "amount": rounds}, "terrain": [terrain], "difficult": "hostile",
                       "obscured": "light" if strength == "storming" else None, "color": "#d8b56a", "visual": {"material": "sand"}})


def _step_away(engine: Any, owner: Any, attacker: Any, source_id: str, feet: int) -> None:
    from ..typed_executor import run_effects

    ctx = _owner_context(engine, owner, source_id, [attacker])
    run_effects(ctx, [{"type": "reaction_move", "distance_ft": feet, "direction": "away",
                       "evidence": f"move up to {feet} feet without provoking Opportunity Attacks"}])


@hook("event")
def sand_attack_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ("ATTACK_ROLLED", "DAMAGE_COMMITTED", "MOVEMENT_COMMITTED"):
        return
    # The event hook's kwargs leave out the positional source; it is the event just appended.
    last = engine.events[-1] if engine.events else None
    kwargs = {**kwargs, "source_definition_id": getattr(last, "source_definition_id", "") if getattr(last, "event_type", None) == event_type else ""}
    if event_type == "ATTACK_ROLLED":
        payload = kwargs.get("payload") or {}
        if payload.get("provisional_hit"):
            return
        attacker = engine.state.actors.get(kwargs.get("actor_id") or "")
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is not None and attacker is not None and target.active:
                _decoy(engine, target, attacker, payload)
                _sovereign_step(engine, target, attacker, kwargs.get("source_definition_id") or "")
    elif event_type == "DAMAGE_COMMITTED":
        _shell(engine, kwargs)
        _grains_cling(engine, kwargs)
    elif event_type == "MOVEMENT_COMMITTED":
        _grains_cut(engine, kwargs)


def _decoy(engine: Any, target: Any, attacker: Any, payload: dict[str, Any]) -> None:
    """Sand Clone Decoy: "the first attack roll against you that misses may instead strike the decoy. If the attack misses you
    by 5 or more, you may move up to 15 feet without provoking Opportunity Attacks, and the decoy collapses into Storming Sand
    Terrain in one 5-foot square. A creature with truesight, tremorsense, blindsight ... may make a Wisdom saving throw ...
    On a success, it ignores this decoy." """
    decoy = _state(engine, target, "sand_clone_decoy")
    if decoy is None or attacker.team_id == target.team_id:
        return
    from .. import senses

    sharp = {"truesight", "tremorsense", "blindsight"} & set(senses.of(engine, attacker))
    if sharp:
        dc = int((((engine.action_catalog.get(decoy.source_definition_id).parameters or {}).get("typed") or {}).get("numbers") or {}).get("save_dc") or 10) \
            if engine.action_catalog.get(decoy.source_definition_id) else 10
        roll = engine._roll_save(attacker, "WIS", dc, DECOY)
        if roll is not None and roll.total >= dc:
            return  # it sees through the silhouette: the decoy stays for another attacker
    engine._remove_condition(target, decoy.condition_id, DECOY)
    margin = int(payload.get("target_ac") or 0) - int(payload.get("modified_total") or 0)
    if margin < 5:
        return
    if _ask_yes(engine, target, "sand_decoy_step", f"Sand Clone Decoy: {attacker.display_name}'s attack missed {target.display_name} by {margin}. "
                f"Move up to 15 feet without provoking Opportunity Attacks (the decoy collapses into a square of Storming Sand)?",
                "Step away 15 feet", "Sand Clone Decoy"):
        _leave_square(engine, target, decoy.source_definition_id, "storming", 1)
        _step_away(engine, target, attacker, decoy.source_definition_id, 15)


def _sovereign_step(engine: Any, target: Any, attacker: Any, source_id: str) -> None:
    """Sand-Sovereign Incarnation: "when a creature misses you with a melee attack, you may move 10 feet without provoking
    Opportunity Attacks and leave one Shallow Sand Terrain square in your previous space"."""
    form = _state(engine, target, "sand_sovereign_incarnation")
    if form is None or attacker.team_id == target.team_id or not _melee_attack(engine, source_id):
        return
    if _ask_yes(engine, target, "sand_sovereign_step", f"Sand-Sovereign Incarnation: {attacker.display_name} missed {target.display_name} in melee. "
                "Move 10 feet without provoking Opportunity Attacks and leave a square of Shallow Sand behind?",
                "Step away 10 feet", "Sand-Sovereign Incarnation"):
        _leave_square(engine, target, form.source_definition_id, "shallow", 10)
        _step_away(engine, target, attacker, form.source_definition_id, 10)


def _shell(engine: Any, kwargs: dict[str, Any]) -> None:
    """Sand Shell: "While any of these Temporary HP remain, the first creature that hits you with a melee attack on each round takes
    Slashing damage equal to your Proficiency Bonus. The shell ends early if you ... lose all Temporary HP from the shell." """
    attacker = engine.state.actors.get(kwargs.get("actor_id") or "")
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        shell = _state(engine, target, "sand_shell") if target is not None else None
        if shell is None:
            continue
        payload = kwargs.get("payload") or {}
        had = int(payload.get("temporary_hp_absorbed") or 0) > 0 or target.temporary_hp > 0
        flag = f"sand_shell_round_{engine.state.round_number}"
        if (had and attacker is not None and attacker.active and attacker.team_id != target.team_id and not target.turn_flags.get(flag)
                and _melee_attack(engine, kwargs.get("source_definition_id") or "")):
            target.turn_flags[flag] = True
            from ..typed_executor import run_effects

            run_effects(_owner_context(engine, target, shell.source_definition_id, [attacker]),
                        [{"type": "damage", "applies_to": "target", "formula": "pb", "damage_types": ["slashing"],
                          "evidence": "Sand Shell: the first creature that hits you with a melee attack each round takes Slashing damage equal to your Proficiency Bonus"}])
        if target.temporary_hp <= 0 and target.entity_id in engine.state.actors:
            engine._remove_condition(target, shell.condition_id, SHELL)  # "lose all Temporary HP from the shell"


def _grains_cling(engine: Any, kwargs: dict[str, Any]) -> None:
    """Glass Edge Scripture: "when you deal Scouring damage to a creature that is Buried, you may cause glassy grains to cling to it.
    Until the start of your next turn, the first time the creature moves 5 feet or more, it takes Piercing damage equal to your
    Proficiency Bonus + your key ability modifier."

    The printed "you may" is the owner's decision, so it is asked at the committed-damage trigger (AUTO128).
    Declining leaves the creature unclinging. An AI owner takes the printed benefit by default. """
    from .. import typed_reactions
    from .needle import CHOICE, ask, checkpoint_id

    owner = engine.state.actors.get(kwargs.get("actor_id") or "")
    source = kwargs.get("source_definition_id") or ""
    if owner is None:
        return
    rows = typed_reactions._rows(engine, owner.entity_id, "glass_edge")
    if not rows:
        return
    # New rows seal the printed CL 5 prerequisite; frozen rows retain their original trigger.
    if any("ward_choice" in row for row in rows) and not any(row.get("ward_choice") for row in rows):
        return
    if mechanic_of(engine.action_catalog.get(source)) not in _SCOUR and source not in _SCOUR:
        return
    if int((kwargs.get("payload") or {}).get("hp_damage") or 0) + int((kwargs.get("payload") or {}).get("temporary_hp_absorbed") or 0) <= 0:
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is None or not target.active or not any(c.condition_id == BURIED for c in target.conditions.values()):
            continue
        if any(c.condition_id == GRAINS and c.source_actor_id == owner.entity_id for c in target.conditions.values()):
            continue
        numbers = (((engine.action_catalog.get(source).parameters or {}).get("typed") or {}).get("numbers") or {}) if engine.action_catalog.get(source) else {}
        if source == "TAL_SAND_ABRADING_WARD":
            from .fight_ownership import block_rows
            sealed = next((r for r in block_rows(engine, owner, "glass_edge") if r.get("ward_choice") and not r.get("held_back")), None)
            if sealed is not None:
                numbers = sealed
        amount = int(numbers.get("pb") or 2) + int(numbers.get("key_mod") or 0)
        # The printed trigger is damage dealt to a creature that is already Buried; the damage does not bury it.
        dealt_by = getattr(engine.action_catalog.get(source), "display_name", "") or "your Scouring sand"
        chosen = ask(engine, getattr(engine, "_active_intent", None),
                     checkpoint_id(engine, "glass_edge_cling", owner.entity_id, target.entity_id), owner,
                     CHOICE + "glass_edge_cling", ["cling", "leave"], minimum=1, maximum=1, preferred=["cling"],
                     name="Glass Edge Scripture", target_id=target.entity_id,
                     labels={"cling": f"Let the glassy grains cling ({amount} Piercing damage)",
                             "leave": "Leave it free of the grains"},
                     prompt=f"Glass Edge Scripture: {dealt_by} just damaged {target.display_name}, which is already "
                            f"Buried in sand. Let sharp glass grains stick to it? The first time it moves 5 feet or "
                            f"more before your next turn, it takes {amount} Piercing damage. This costs nothing extra.")
        if not chosen or chosen[0] != "cling":
            continue
        engine._apply_condition(target, GRAINS, EDGE, owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"amount": amount, "source_action": source,
                                      "label": "Glassy grains: the first time it moves 5 feet or more before its burier's next turn, Piercing damage"})


def _grains_cut(engine: Any, kwargs: dict[str, Any]) -> None:
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    if mover is None or len((kwargs.get("payload") or {}).get("path") or []) < 2:
        return
    for key, condition in list(mover.conditions.items()):
        if condition.condition_id != GRAINS:
            continue
        owner = engine.state.actors.get(condition.source_actor_id)
        engine._remove_condition(mover, GRAINS, EDGE)
        if owner is not None and mover.active:
            from ..typed_executor import run_effects

            run_effects(_owner_context(engine, owner, str(condition.data.get("source_action") or ""), [mover]),
                        [{"type": "damage", "applies_to": "target", "flat": int(condition.data.get("amount") or 0), "damage_types": ["piercing"],
                          "evidence": "Glass Edge Scripture: the glassy grains cut as it moves"}])
        break


@hook("compile_block")
def sand_blocks(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Markers for passive Sand talents read above (combat/rules/feature_blocks.d/riders_c4.json)."""
    if block in ("glass_edge", "sand_erode"):
        return [{**row, "block": block, "keeps_compiling": True,
                 **({"ward_choice": int(int(numbers.get("cl") or 1) >= 5), "pb": int(numbers.get("pb") or 0),
                     "key_mod": int(numbers.get("key_mod") or 0)} if block == "glass_edge" else {})}]
    return None


# ------------------------------------------------------------------------------------------------ Erode the Path of Return
@hook("teleport_gate")
def erode_path(ctx: Any, start: Any, destination: Any) -> bool | None:
    """Erode the Path of Return (Reaction, 3 CP, 120 feet): "A creature you can perceive teleports ... The triggering creature makes a
    Dexterity or Charisma saving throw, its choice. On a failed save, choose one: the movement fails and the triggering resource is
    spent; ... the creature completes the movement, but you learn its destination direction and distance ... On a successful save,
    the movement succeeds, but the creature cannot benefit from being Invisible against you until the start of your next turn".
    Automated for a creature's own teleport; the half-distance burial option and the burrow/invisible/leaving-sand triggers stay
    with the GM."""
    from .. import stealth, typed_reactions
    from .needle import CHOICE, ask, checkpoint_id

    engine, mover = ctx.engine, ctx.actor
    blocked = ("sand_erode_blocked", mover.entity_id)
    if ctx.damage_cache.get(blocked):
        return False  # the same activation's other teleport row: the movement already failed
    result = None
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if owner.team_id == mover.team_id or not owner.active or not owner.reaction_available:
            continue
        rows = typed_reactions._rows(engine, owner.entity_id, "sand_erode")
        if not rows or engine.grid.distance_ft(owner.position, start) > 120 or not stealth.sees(engine, owner, mover):
            continue
        pool = next((key for key in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance") if owner.resources.get(key, 0) >= 3), None)
        if pool is None:
            continue
        chosen = ask(engine, ctx.intent, checkpoint_id(engine, "sand_erode", owner.entity_id, mover.entity_id), owner, CHOICE + "sand_erode",
                     ["fail", "track"], labels={"fail": "On a failed save, its teleport fails", "track": "On a failed save, it arrives but you learn where (it leaves a trail)"},
                     preferred=["fail"], allow_decline=True, name="Erode the Path of Return",
                     prompt=f"Erode the Path of Return: {mover.display_name} is teleporting. Spend your Reaction and 3 CP to make it save "
                            "(Dexterity or Charisma)? On a success it still arrives but cannot be Invisible to you until your next turn starts.")
        if not chosen:
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, owner, ERODE, independent=True):
            owner.reaction_available = False
            engine._spend_resource(owner, pool, 3, ERODE)
            dc = next((int(((a.parameters or {}).get("typed") or {}).get("numbers", {}).get("save_dc") or 0)
                       for a in (engine.action_catalog.get(i) for i in owner.action_ids) if a is not None
                       and ((a.parameters or {}).get("typed") or {}).get("numbers", {}).get("save_dc")), 10)
            preferred = max(("DEX", "CHA"), key=lambda option: mover.saving_throws.get(option, 0))
            ability = ask(engine, ctx.intent,
                          checkpoint_id(engine, "sand_erode_save", owner.entity_id, mover.entity_id),
                          mover, CHOICE + "sand_erode_save", ["DEX", "CHA"],
                          labels={"DEX": "Dexterity saving throw", "CHA": "Charisma saving throw"},
                          preferred=[preferred], name="Erode the Path of Return: choose your save",
                          prompt=f"Erode the Path of Return: {owner.display_name} challenges {mover.display_name}'s "
                                 f"teleport from {ctx.action.display_name}. Choose Dexterity or Charisma for "
                                 f"{mover.display_name}'s saving throw (DC {dc}). On a failure, "
                                 + ("the teleport fails and its cost is still spent. " if chosen[0] == "fail" else
                                    f"the teleport succeeds, but {owner.display_name} learns the destination and "
                                    "a visible sand trail lasts until the end of their next turn. ")
                                 + f"On a success, the teleport succeeds, but {mover.display_name} cannot be "
                                   f"Invisible to {owner.display_name} until {owner.display_name}'s next turn starts. "
                                   "No additional action, Reaction or resource cost for choosing the save.")[0]
            roll = engine._roll_save(mover, ability, dc, ERODE)
            engine._append_event("REACTION_RESOLVED", ERODE, actor_id=owner.entity_id, target_ids=(mover.entity_id,),
                                 payload={"checkpoint": "TELEPORT", "save": ability, "dc": dc, "failed": roll is not None and roll.total < dc, "choice": chosen[0]})
            from . import note

            if roll is not None and roll.total < dc:
                if chosen[0] == "fail":
                    note(engine, ERODE, owner, f"Erode the Path of Return: {mover.display_name}'s teleport fails; what it spent is lost.", (mover,))
                    result = False
                else:
                    note(engine, ERODE, owner, f"Erode the Path of Return: {owner.display_name} learns where {mover.display_name} arrives; "
                                               f"it leaves a visible trail of sand until the end of {owner.display_name}'s next turn.", (mover,))
            else:
                engine._apply_condition(mover, CLINGING, ERODE, owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                        data={"against": owner.entity_id, "label": f"Sand clings to it: it cannot be Invisible to {owner.display_name} until {owner.display_name}'s next turn starts"})
            if result is False:
                ctx.damage_cache[blocked] = True
                return False
    return result


@hook("masked_conditions")
def clinging_sand(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    out: dict[str, set[str]] = {}
    for who, other in ((target, attacker), (attacker, target)):
        if any(c.condition_id == CLINGING and (c.data or {}).get("against") == other.entity_id for c in who.conditions.values()):
            rows = {key for key, c in who.conditions.items() if c.condition_id == "condition:typed.invisible"}
            if rows:
                out[who.entity_id] = rows
    return out or None


# ------------------------------------------------------------------------------------------------ Erosion Scripture
@effect("sand_abrasion")
def abrasion(ctx: Any, row: dict[str, Any]) -> None:
    """Erosion Scripture, Armor Abrasion: "its AC is reduced by 1 until the end of your next turn. This cannot reduce AC below 10 +
    Dexterity modifier unless the armor is broken or removed by other means." {"type": "sand_abrasion", "amount": 1, duration keys}:
    the ordinary AC penalty, skipped for a creature it would take below that floor."""
    from dataclasses import replace

    from ..ability_checks import ability_modifier
    from ..typed_executor import _default_subject, block_ac_bonus
    from . import note

    amount = int(row.get("amount") or 1)
    for subject in _default_subject(ctx, row, harmful=True):
        floor = 10 + ability_modifier(subject, "DEX")
        if subject.armor_class + ctx.engine._ac_modifier(subject) - amount < floor:
            note(ctx.engine, ctx.source, ctx.actor, f"Erosion Scripture: {subject.display_name}'s armor cannot be worn below AC 10 + its Dexterity modifier.", (subject,))
            continue
        block_ac_bonus(replace(ctx, target=subject, targets=[subject]),
                       {**{k: v for k, v in row.items() if k not in ("type", "amount")}, "type": "ac_bonus", "flat": -amount, "applies_to": "target"})


@hook("technique_used")
def sandstorm_designate(ctx: Any) -> None:
    """Seal explicit ranged-attack exemptions on this newly compiled storm only."""
    if mechanic_of(ctx.action) != STORM:
        return
    mine = [z for z in _storms(ctx.engine) if z.owner_id == ctx.actor.entity_id
            and z.source_definition_id == ctx.source
            and (z.trigger_profile.get("profile") or {}).get("sand_designation")]
    if not mine:
        return
    from ..target_knowledge import located
    from ..relations import ALLY, relation
    from .needle import CHOICE, ask, checkpoint_id
    options = [a.entity_id for a in ctx.engine.state.actors.values()
               if a.active and a.entity_id != ctx.actor.entity_id and located(ctx.engine, ctx.actor, a)]
    allies = [key for key in options if relation(ctx.engine, ctx.actor, ctx.engine.state.actors[key]) == ALLY]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "sandstorm_designated", ctx.source), ctx.actor,
                 CHOICE + "sandstorm_designated", options, maximum=max(1, len(options)), allow_decline=True,
                 labels={key: ctx.engine.state.actors[key].display_name for key in options},
                 preferred=allies, automatic_options=allies,
                 name="Thousand-Mile Sandstorm Body", feature_id=STORM,
                 prompt="Thousand-Mile Sandstorm Body: choose creatures whose ranged weapon attacks may pass through "
                        "your storm without Disadvantage. You are always exempt. Choosing nobody is allowed; "
                        "allies you leave out face the same Disadvantage as enemies. This costs nothing extra.")
    for zone in mine:
        zone.trigger_profile["profile"] = {**zone.trigger_profile["profile"], "ranged_exempt": list(chosen)}
        ctx.engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id,
                                 payload={"zone": zone.model_dump(mode="json")})


def ward_damage_type(engine: Any, owner: Any, target: Any) -> str:
    """Public Ward/Glass Edge adapter: the new owning row offers the printed Scour type choice.

    Legacy Glass Edge rows lack ward_choice and retain Slashing. No module cache or core patch.
    """
    from .fight_ownership import block_rows
    if not any(row.get("ward_choice") and not row.get("held_back") for row in block_rows(engine, owner, "glass_edge")):
        return "SLASHING"
    from .needle import CHOICE, ask, checkpoint_id
    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "glass_edge_ward_type", owner.entity_id, target.entity_id), owner,
                 CHOICE + "glass_edge_ward_type", ["slashing", "piercing"], minimum=1, maximum=1,
                 labels={"slashing": "Slashing damage", "piercing": "Piercing damage"}, preferred=["slashing"],
                 name="Glass Edge Scripture", target_id=target.entity_id,
                 prompt=f"Glass Edge Scripture: {target.display_name} starts its turn in your sand. "
                        "Choose Slashing or Piercing damage for Abrading Ward. This costs nothing extra.")
    return chosen[0].upper()


@hook("before_attack")
def sandstorm_native_attack(engine: Any, attacker: Any, defender: Any, intent: Any,
                            context: dict[str, Any]) -> dict[str, str] | None:
    """Native ranged weapons consume the same newly sealed designation ledger."""
    action = engine.action_catalog.get(context.get("source_id") or "")
    if action is None or action.resolution_kind not in ("ATTACK", "MULTI_ATTACK") or not action.range_ft:
        return None
    from ..weapon_delivery import delivery_kind
    parameters = action.parameters or {}
    if delivery_kind(parameters.get("typed") or {}, None, parameters) != "weapon":
        return None
    for zone in _storms(engine):
        profile = zone.trigger_profile.get("profile") or {}
        if not profile.get("sand_designation"):
            continue  # native legacy attacks did not consume this hook
        if attacker.entity_id == zone.owner_id or attacker.entity_id in profile.get("ranged_exempt", []):
            continue
        cells = {(c.x, c.y) for c in zone.affected_cells}
        line = {(c.x, c.y) if hasattr(c, "x") else tuple(c)
                for c in engine.grid.ray_cells(attacker.position, defender.position)}
        if cells & line:
            return {"mode": "DISADVANTAGE"}
    return None


@hook("event", nested=True)
def ward_glass_grains(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Ward damage inside turn_start reaches Glass Edge without opting old riders into nesting."""
    if (event_type != "DAMAGE_COMMITTED" or getattr(engine, "_ext_event_depth", 0) <= 1
            or kwargs.get("source_definition_id") != "TAL_SAND_ABRADING_WARD"):
        return
    from .fight_ownership import block_rows
    owner = engine.state.actors.get(kwargs.get("actor_id") or "")
    if owner is not None and any(row.get("ward_choice") and not row.get("held_back") for row in block_rows(engine, owner, "glass_edge")):
        _grains_cling(engine, kwargs)
