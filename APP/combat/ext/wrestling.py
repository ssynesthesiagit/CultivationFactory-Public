"""Wrestling riders (rider lane C2, 2026-09-30: "i want everything we can automated").  Rules text: the owner's Sphere Compendium,
"Wrestling" (authority/typed_mechanics/rules_text.json).  Apply a Slam itself is combat/ext/gu_wrestling.py; the typed Slams it now runs
(Hammerlock, Joint-Locking Scripture, Meridian-Crushing Clinch ...) leave the conditions this module reads.

Effects
  wrestling_hold  {"hold": "hammerlock" | "weapon_disadvantage" | "no_bonus_action"} on the Slammed creature until the start of the user's
                  next turn: Hammerlock's Disadvantage on checks to escape the user's grapple (``escape_mode``), Joint-Locking Scripture's
                  Disadvantage on weapon attack rolls (``attack_mode``), Meridian-Crushing Clinch's "cannot take Bonus Actions"
                  (``candidate_allowed``).
Owned rows (combat/rules/feature_blocks.d/riders_c2.json, block "wrestling"; every hook returns early without the row or the condition)
  iron_clinch     while it Grapples a creature: +1 AC against that creature (``hit_response``), Advantage on saves against forced
                  movement that creature causes (``save``).
  court           Court of the Closed Distance (while its state is on): a melee miss by a creature within reach lets you step 5 feet
                  without Opportunity Attacks; once per turn a failed save against your Grapple option or a failed escape check from
                  your grapple regains Martial Focus; a creature you Grapple gives you Half Cover against other ranged attackers.
  slip_and_strike after you voluntarily release a grapple: "Slip and Strike: Strike the Released Creature", a Bonus Action weapon attack
                  against it before the end of your turn.
  suplex          Mountain-Crashing Suplex: a slam that stops against an obstacle deals 1d8 more Bludgeoning.
  wrestling_release  effect: end only this creature's grapple by the user (Hard Whip, Mountain-Crashing Suplex).
  choke_hold      Choke Hold applied on consecutive rounds: choking -- one Exhaustion level at the end of each of its turns; the levels
                  it gained from this hold go away once the hold is gone at the end of the choker's turn.
Shared public helper apply_choke_hold is used by gu_wrestling's Slam effect;
it owns persisted round history and source-specific suffocation recovery.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

BLOCK = "wrestling"
HOLD = "condition:typed.wrestling_hold"
GRAPPLED = "condition:typed.grappled"
FOCUS = "resource:core.martial_focus"
COURT = "condition:typed.state.court_of_the_closed_distance"
CHOKE, CHOKING = "condition:typed.choke_hold", "condition:typed.choking"
CHOKE_HISTORY = "condition:typed.choke_history"
SLIP = "wrestling_slip_target"
LABELS = {"hammerlock": "Hammerlock: Disadvantage on checks to escape the grapple",
          "weapon_disadvantage": "Joint lock: Disadvantage on weapon attack rolls",
          "no_bonus_action": "Cannot take Bonus Actions (until the start of the holder's next turn)"}


def row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    from .passive_rows import row_of

    return row_of(engine, actor.entity_id, BLOCK, kind)


def _grapples(engine: Any, grappler: Any, other: Any) -> bool:
    return any(c.condition_id == GRAPPLED and c.source_actor_id == grappler.entity_id for c in other.conditions.values())


def _turn(engine: Any) -> int:
    return int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)


@hook("compile_block")
def wrestling_block(block: str, spec: dict[str, Any], row_: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row_, "block": BLOCK, "kind": spec.get("kind"), **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]


@hook("compile_action")
def wrestling_physical_windows(action: Any, info: dict[str, Any]) -> Any:
    typed = (action.parameters or {}).get("typed") or {}
    source = typed.get("source")
    if source not in ("TAL_WRESTLING_OPENING_STRIKE", "TAL_WRESTLING_GROUND_GAME"):
        return None
    additions = {"auto37_hold_window": True}
    if source == "TAL_WRESTLING_OPENING_STRIKE":
        additions["physical_grapple"] = True
    return action.model_copy(update={"parameters": {**action.parameters, "typed": {**typed, **additions}}})


@hook("damage_dealt")
def opening_strike_window(ctx: Any, target: Any, amount: int) -> None:
    if amount <= 0 or row(ctx.engine, ctx.actor, "opening_strike") is None or not ctx.typed.get("weapon"):
        return
    from ..weapon_delivery import delivery_kind
    if delivery_kind(ctx.typed, getattr(ctx, "attack_effect", None) or {}, ctx.action.parameters) != "weapon":
        return
    ctx.actor.turn_flags["auto37_opening:" + target.entity_id] = _turn(ctx.engine)


@hook("turn_start")
def ground_game_start(engine: Any, actor: Any) -> None:
    if row(engine, actor, "ground_game") is not None:
        actor.turn_flags["auto37_ground_targets"] = "|".join(sorted(
            other.entity_id for other in engine.state.actors.values() if _grapples(engine, actor, other)))


@hook("candidate_allowed")
def wrestling_hold_windows(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (action.parameters or {}).get("typed") or {} if action is not None else {}
    if not typed.get("auto37_hold_window"):
        return None
    targets = [engine.state.actors.get(tid) for tid in candidate.target_ids]
    if typed.get("source") == "TAL_WRESTLING_OPENING_STRIKE":
        return None if targets and all(t is not None and actor.turn_flags.get("auto37_opening:" + t.entity_id) == _turn(engine)
                                      for t in targets) else False
    return None if targets and all(t is not None and t.entity_id in str(actor.turn_flags.get("auto37_ground_targets") or "").split("|")
                                  and _grapples(engine, actor, t) for t in targets) else False


@hook("event", nested=True)
def ground_game_reaction(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED" or (kwargs.get("payload") or {}).get("condition_id") != GRAPPLED:
        return
    from ..typed_executor import Context, condition_rules, run_effects
    from .needle import CHOICE, ask, checkpoint_id

    for tid in kwargs.get("target_ids") or ():
        owner = engine.state.actors.get(tid)
        if owner is None or row(engine, owner, "ground_game") is None or not owner.reaction_available:
            continue
        if any(r.get("no_reactions") for r in condition_rules(owner)):
            continue
        held = owner.conditions.get(str((kwargs.get("payload") or {}).get("instance_id") or ""))
        source = engine.state.actors.get(held.source_actor_id) if held is not None else None
        # "When one creature successfully grapples you" -- any Grapple that reaches you opens this
        # Reaction, however the grapple arrived. The printed line asks for no empty hand, no limb and
        # no physical grapple, so a magical or projectile Grapple is offered the same save, and the
        # start-of-turn Bonus Action branch (which never asked about hands either) agrees with it.
        if held is None or source is None or not source.active or source is owner:
            continue
        action = next((a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id
                       and ((a.parameters or {}).get("typed") or {}).get("source") == "TAL_WRESTLING_GROUND_GAME"
                       and ((a.parameters or {}).get("typed") or {}).get("auto37_hold_window")), None)
        if action is None:
            continue
        intent = getattr(engine, "_active_intent", None)
        if not ask(engine, intent, checkpoint_id(engine, "GROUND_GAME", owner.entity_id, source.entity_id), owner,
                   CHOICE + "ground_game", ["use"], allow_decline=True, name="Ground Game", feature_id="TAL_WRESTLING_GROUND_GAME",
                   target_id=source.entity_id, labels={"use": "Spend your Reaction: the grappler saves or falls Prone"},
                   prompt=f"Ground Game: {source.display_name} successfully Grapples {owner.display_name}. Spend your Reaction "
                          "to make it choose a Strength or Dexterity save against your Wrestling save DC? Failure knocks it Prone."):
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, owner, "TAL_WRESTLING_GROUND_GAME", independent=True):
            owner.reaction_available = False
            engine._append_event("REACTION_RESOLVED", "TAL_WRESTLING_GROUND_GAME", actor_id=owner.entity_id,
                                 target_ids=(source.entity_id,), payload={"ability": "Ground Game", "checkpoint": "GRAPPLE_ESTABLISHED"})
            typed = action.parameters["typed"]
            run_effects(Context(engine, owner, action, intent, typed, [source], source, {}), typed.get("effects") or [])


# ------------------------------------------------------------------------------------------------ Slam holds
@effect("wrestling_hold")
def hold(ctx: Any, eff: dict[str, Any]) -> None:
    kind = str(eff.get("hold") or "")
    from .. import typed_executor as te

    # "until the start of the user's next turn", unless the ability that placed this hold counts that turn in more than
    # one of the user's turns (the general effect_turns hook; Berserker's Beat Down).
    expires = te.counted_turns(ctx, eff, "START_OF_SOURCE_NEXT_TURN")
    for subject in ctx.targets or ([ctx.target] if ctx.target else []):
        if subject is None or not subject.active:
            continue
        for condition in list(subject.conditions.values()):
            if condition.condition_id == HOLD and condition.source_actor_id == ctx.actor.entity_id and (condition.data or {}).get("hold") == kind:
                ctx.engine._remove_condition(subject, HOLD, condition.source_definition_id)
        ctx.engine._apply_condition(subject, HOLD, ctx.source, ctx.actor.entity_id, expires_on=expires,
                                    data={"hold": kind, "label": LABELS.get(kind, "Wrestling hold")})


def _holds(creature: Any, kind: str) -> list[Any]:
    return [c for c in creature.conditions.values() if c.condition_id == HOLD and (c.data or {}).get("hold") == kind]


@hook("escape_mode")
def hammerlock(engine: Any, escaper: Any, grips: Any) -> str | None:
    """Hammerlock: "the target has Disadvantage on checks made to escape your grapple\"."""
    holders = {c.source_actor_id for c in _holds(escaper, "hammerlock")}
    if not holders:
        return None
    sources = {getattr(g, "source_actor_id", None) for g in (grips.values() if isinstance(grips, dict) else grips or ())}
    return "DISADVANTAGE" if holders & sources else None


@hook("attack_mode")
def locked_weapon_arm(ctx: Any, target: Any) -> str | None:
    """Joint-Locking Scripture: "has Disadvantage on weapon attack rolls\"."""
    if not _holds(ctx.actor, "weapon_disadvantage"):
        return None
    attack = getattr(ctx, "attack_effect", None) or {}
    weapon = bool(ctx.typed.get("weapon")) and not str(attack.get("attack_kind") or "").startswith("cultivation")
    return "DISADVANTAGE" if weapon or attack.get("attack_kind") == "weapon" else None


@hook("candidate_allowed")
def locked_no_bonus(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Meridian-Crushing Clinch: "cannot take Bonus Actions\"."""
    if action is None or not _holds(actor, "no_bonus_action"):
        return None
    return False if str(getattr(getattr(action, "economy", None), "value", getattr(action, "economy", ""))).endswith("BONUS_ACTION") else None


# ------------------------------------------------------------------------------------------------ Iron Clinch
@hook("hit_response")
def iron_clinch_ac(engine: Any, attacker: Any, target: Any, spec: Any, total: int, natural: Any, effective_ac: int) -> Any:
    """"gain +1 AC against that creature" (a creature Grappled by you): a hit that the +1 would have stopped misses."""
    if row(engine, target, "iron_clinch") is None or not _grapples(engine, target, attacker) or natural == 20:
        return None
    if int(total) < int(effective_ac) + 1:
        return (int(effective_ac) + 1, False)
    return None


@hook("save")
def iron_clinch_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """"gain Advantage on saving throws against forced movement caused by that creature\"."""
    if "forced_movement" not in set(named or ()) or row(ctx.engine, subject, "iron_clinch") is None or not _grapples(ctx.engine, subject, ctx.actor):
        return None
    return {"modes": ["ADVANTAGE"]}


# ------------------------------------------------------------------------------------------------ Court of the Closed Distance
def _court(engine: Any, actor: Any) -> bool:
    return row(engine, actor, "court") is not None and any(c.condition_id == COURT for c in actor.conditions.values())


@hook("after_miss_choice")
def court_step(ctx: Any, target: Any, spec: dict[str, Any]) -> None:
    """"when one creature within reach misses you with a melee attack, move 5 feet toward it without provoking opportunity attacks\"."""
    engine, attacker = ctx.engine, ctx.actor
    if not _court(engine, target) or not target.active or not attacker.active or attacker.team_id == target.team_id:
        return
    reach = engine._typed_opportunity_reach(target) or 5
    if "ranged" in str((getattr(ctx, "attack_effect", None) or {}).get("attack_kind") or "") or engine._distance_actor_to_actor(target, attacker) > reach:
        return
    from .needle import ask, cell_id, checkpoint_id, free_cells, position_of, step_to

    here = engine.grid.distance_ft(target.position, attacker.position)
    cells = [cell for cell in free_cells(engine, target, 5) if cell != target.position and engine.grid.distance_ft(cell, attacker.position) < here]
    if not cells:
        return
    options = [cell_id(cell) for cell in sorted(cells, key=lambda cell: (cell.y, cell.x))]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "Court of the Closed Distance", target.entity_id, attacker.entity_id), target,
                 "choice:needle.wrestling_court_step", options, labels={o: f"Step to {o.split(':', 1)[1]}" for o in options}, allow_decline=True,
                 default="decline", name="Court of the Closed Distance", target_id=attacker.entity_id,
                 prompt=f"Court of the Closed Distance: {attacker.display_name}'s {ctx.action.display_name} missed {target.display_name}; "
                        "step 5 feet toward it without provoking Opportunity Attacks? This costs no action or resource.")
    if picked:
        step_to(engine, target, position_of(picked[0]), "TAL_WRESTLING_COURT_OF_THE_CLOSED_DISTANCE")


def _court_focus(engine: Any, actor: Any, why: str) -> None:
    if actor.turn_flags.get("wrestling_round_court_focus") == _turn(engine) or FOCUS not in actor.resources:
        return
    if int(actor.resources.get(FOCUS) or 0) >= 1:
        return
    actor.turn_flags["wrestling_round_court_focus"] = _turn(engine)
    engine._gain_resource(actor, FOCUS, 1, "passive:TAL_WRESTLING_COURT_OF_THE_CLOSED_DISTANCE")
    from . import note

    note(engine, "TAL_WRESTLING_COURT_OF_THE_CLOSED_DISTANCE", actor, f"Court of the Closed Distance: {actor.display_name} regains Martial Focus ({why}).")


@hook("after_save")
def court_grapple_failed(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """"once per turn when one creature fails a save against your Grapple option ... regain Martial Focus\"."""
    if not failed or not _court(ctx.engine, ctx.actor) or "grappled" not in {str(n).lower() for n in named or ()}:
        return
    _court_focus(ctx.engine, ctx.actor, f"{subject.display_name} failed its save against the Grapple")


@hook("event")
def court_escape_failed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"... or fails an escape check" against your grapple."""
    if event_type != "CHECK_ROLLED" or (kwargs.get("payload") or {}).get("success") is not False:
        return
    escaper = engine.state.actors.get(kwargs.get("actor_id"))
    source = str(getattr(engine.events[-1], "source_definition_id", "") or "") if engine.events else ""  # the event just written
    if escaper is None or "escape" not in source:
        return
    for other in engine.state.actors.values():
        if other is not escaper and _court(engine, other) and _grapples(engine, other, escaper):
            _court_focus(engine, other, f"{escaper.display_name} failed to escape")


@hook("cover")
def court_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    """"one Grappled creature of your choice grants you Half Cover against creatures other than itself" (the table's cover hook serves
    ranged attacks)."""
    if not _court(engine, target):
        return None
    shield = [other for other in engine.state.actors.values() if other.active and other is not attacker and _grapples(engine, target, other)]
    return 2 if shield else None


# ------------------------------------------------------------------------------------------------ Slip and Strike
@hook("event")
def slip_release(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"When you voluntarily release a grapple": the Release grapple action's own removal."""
    if event_type != "CONDITION_REMOVED" or (kwargs.get("payload") or {}).get("condition_id") != GRAPPLED:
        return
    event = kwargs.get("originating_event")
    source = kwargs.get("source_definition_id") or getattr(event, "source_definition_id", "")
    if not str(source).endswith(".release_grapple"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None or row(engine, actor, "slip_and_strike") is None:
        return
    released = next(iter(kwargs.get("target_ids") or ()), None)
    if released:
        actor.turn_flags[SLIP] = released


@hook("compile_actions")
def slip_action(info: dict[str, Any]) -> list[Any] | None:
    import copy

    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if "TAL_WRESTLING_SLIP_AND_STRIKE" not in set(info.get("owned_ids") or ()):
        return None
    melee = [a for a in info.get("actions") or () if ".weapon." in a.source_definition_id and "#" not in a.source_definition_id
             and ((a.parameters or {}).get("typed") or {}).get("weapon") and not ((a.parameters or {}).get("typed") or {}).get("range_ft")]
    if not melee:
        return None
    base = max(melee, key=lambda a: int((a.parameters or {}).get("expected_damage") or 0))
    parameters = copy.deepcopy(base.parameters)
    parameters.update({"requires_turn_flag": SLIP, "slip_and_strike": True})
    return [base.model_copy(update={"source_definition_id": f"action:typed.{info['short']}.wrestling.slip_and_strike",
                                    "display_name": f"Slip and Strike: {base.display_name} against the released creature",
                                    "economy": EconomyKind.BONUS_ACTION, "parameters": parameters})]


@hook("candidate_allowed")
def slip_target(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not ((getattr(action, "parameters", None) or {}).get("slip_and_strike")):
        return None
    wanted = actor.turn_flags.get(SLIP)
    return bool(wanted) and tuple(getattr(candidate, "target_ids", None) or ()) == (wanted,)


@hook("technique_used")
def slip_used(ctx: Any) -> None:
    if (ctx.action.parameters or {}).get("slip_and_strike"):
        ctx.actor.turn_flags.pop(SLIP, None)


# ------------------------------------------------------------------------------------------------ Mountain-Crashing Suplex
@hook("collision")
def suplex_obstacle(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    """"If the destination contains an ordinary solid obstacle, the target takes +1d8 Bludgeoning damage" (the obstacle's share is the
    objects system's where one is on the map)."""
    if ctx.typed.get("source") != "TAL_WRESTLING_MOUNTAIN_CRASHING_SUPLEX" or not target.active:
        return
    from .. import typed_executor as te

    te.run_effects(te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}),
                   [{"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "damage_types": ["bludgeoning"],
                     "evidence": "Mountain-Crashing Suplex: slammed into an obstacle, +1d8 Bludgeoning"}])


# ------------------------------------------------------------------------------------------------ Hard Whip
_HARD_WHIP_DIRS = {"north": (0, -1), "north-east": (1, -1), "east": (1, 0), "south-east": (1, 1),
                   "south": (0, 1), "south-west": (-1, 1), "west": (-1, 0), "north-west": (-1, -1)}


def first_step_open(engine: Any, target: Any, step: tuple[int, int]) -> bool:
    """Whether ``target`` can actually take one square from where it stands in the heading ``step``.

    Named helper shared by this module's Hard Whip direction menu, which offers only headings that
    really move the released creature. It asks the ordinary question the ordinary route asks: the same
    board-edge clamp ``combat.typed_executor._push`` applies, then the same
    ``grid.volume_step_legal`` gate over everything but the mover itself and its own footprint. A
    heading that fails here would stop the route on its very first square and spend the action for no
    travel, so the table does not offer it as an ordinary choice. Only the first square is checked: a
    route that starts legal and is stopped later is a real move and keeps the ordinary legal-route and
    Impact Collision handling untouched. Read-only: it neither moves a creature nor records anything.
    """
    from ..gate2_runtime_models import Position

    here = target.position
    nxt = Position(x=max(0, here.x + int(step[0])), y=max(0, here.y + int(step[1])), z=here.z)
    return bool(engine.grid.volume_step_legal(here, nxt, occupied_cells=engine._occupied_volumes_except(target.entity_id),
                                             footprint=engine._footprint(target)))


@hook("forced_movement_direction")
def hard_whip_direction(ctx: Any, target: Any, distance_ft: int) -> tuple[int, int] | None:
    """Hard Whip: "Move the target up to 10 feet in one legal direction other than directly upward".

    The printed line hands the choice of direction to the user of the Slam, so the table asks which way
    to send the released creature. Straight up is not a direction this grid moves a creature in, and a
    heading the board blocks is not a "legal direction" either, so the menu offers only the headings the
    released creature can genuinely travel (first_step_open). The route, the moved creature's own
    defenses and any Impact Collision stay exactly as they are for any other push, and a route that
    starts open and is blocked later still stops where the ordinary rules stop it. If every heading is
    blocked the creature simply does not travel -- "up to 10 feet" includes zero -- and the table says so
    instead of asking a question whose every answer would waste the action. Inert for anyone who does not
    own Hard Whip, and for every other forced movement on the table.
    """
    if ctx.typed.get("source") != "TAL_WRESTLING_HARD_WHIP" or not target.active:
        return None
    from .needle import CHOICE, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    away = ((target.position.x > actor.position.x) - (target.position.x < actor.position.x),
            (target.position.y > actor.position.y) - (target.position.y < actor.position.y))
    open_dirs = [name for name, step in _HARD_WHIP_DIRS.items() if first_step_open(engine, target, step)]
    if not open_dirs:
        note(engine, ctx.source, actor, f"Hard Whip ends {actor.display_name}'s grapple of {target.display_name}, but every direction "
                                       f"is blocked, so {target.display_name} is not moved.", (target,))
        return away or None
    preferred = [name for name in open_dirs if _HARD_WHIP_DIRS[name] == away][:1]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "HARD_WHIP", actor.entity_id, target.entity_id), actor,
                 CHOICE + "hard_whip_direction", open_dirs,
                 labels={name: name.replace("-", " ").title() for name in open_dirs},
                 name="Hard Whip: choose the direction", feature_id="TAL_WRESTLING_HARD_WHIP",
                 target_id=target.entity_id, preferred=preferred, automatic=True, default="first",
                 prompt=f"Hard Whip by {actor.display_name} sends {target.display_name} up to 10 feet. "
                        f"Choose which way to move {target.display_name}; straight up is not allowed, and only directions with "
                        "clear floor are offered. The move does not provoke Opportunity Attacks, and costs no extra movement.")
    # Default when nobody chooses (an AI user, or a question nobody answered): straight away from the
    # user, which is how this Slam used to resolve. Only when that very direction is blocked does the
    # menu's first open heading stand in, so a legal move is still made.
    chosen = (picked or preferred or open_dirs)[0]
    return _HARD_WHIP_DIRS.get(chosen)


# ------------------------------------------------------------------------------------------------ Choke Hold
def _remove_choke_conditions(engine: Any, target: Any, owner: str, *condition_ids: str) -> None:
    """Remove this holder's exact instances, preserving other holders and sources."""
    from .owned_effects import remove_conditions

    for condition in list(target.conditions.values()):
        if condition.source_actor_id == owner and condition.condition_id in condition_ids:
            remove_conditions(engine, target, condition.source_definition_id, owner, condition.condition_id)


def apply_choke_hold(ctx: Any, target: Any, *, breath_gate: bool = False) -> None:
    """Public Slam helper used by gu_wrestling. Save source/target/round history
    independently of the short hold; remove it on release or a missed round.
    Only levels caused by this source's choking are recovered.
    """
    engine, actor = ctx.engine, ctx.actor
    if breath_gate:
        from ..physiology import trait
        if trait(target, "breath_dependent") is False:
            note(engine, ctx.source, actor, f"Choke Hold has no effect on {target.display_name}, which does not need to breathe.", (target,))
            return
    previous = next((c for c in target.conditions.values() if c.condition_id == CHOKE_HISTORY
                     and c.source_actor_id == actor.entity_id), None)
    round_ = int(engine.state.round_number)
    last = int((previous.data or {}).get("last_round", -1)) if previous else -1
    levels = int((previous.data or {}).get("levels", 0)) if previous else 0
    is_choking = last == round_ - 1 or (last == round_ and any(
        c.condition_id == CHOKING and c.source_actor_id == actor.entity_id for c in target.conditions.values()))
    _remove_choke_conditions(engine, target, actor.entity_id, CHOKE_HISTORY, CHOKE)
    from .owned_effects import remove_conditions
    remove_conditions(engine, target, ctx.source, actor.entity_id, "condition:typed.silenced")
    engine._apply_condition(target, CHOKE_HISTORY, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"last_round": round_, "levels": levels,
                                  "label": "Repeated Choke Hold: suffocation ends on release or a skipped round"})
    engine._apply_condition(target, CHOKE, ctx.source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": "Choke Hold: cannot breathe, speak or use verbal spell components until the holder's next turn"})
    engine._apply_condition(target, "condition:typed.silenced", ctx.source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN")
    if is_choking:
        _remove_choke_conditions(engine, target, actor.entity_id, CHOKING)
        engine._apply_condition(target, CHOKING, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Choking (Choke Hold): +1 Exhaustion at each turn end; these levels end when breathing resumes"})


def _recover_choke(engine: Any, target: Any, history: Any) -> None:
    from .forged_exhaustion import add

    _remove_choke_conditions(engine, target, history.source_actor_id, CHOKE_HISTORY, CHOKE, CHOKING)
    from .owned_effects import remove_conditions
    remove_conditions(engine, target, history.source_definition_id, history.source_actor_id, "condition:typed.silenced")
    add(engine, target, -int(history.data.get("levels") or 0), history.source_definition_id)


@hook("event")
def choke_released(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A released/escaped grapple ends its own Choke Hold and recovers its levels."""
    if event_type != "CONDITION_REMOVED" or (kwargs.get("payload") or {}).get("condition_id") != GRAPPLED:
        return
    for tid in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(tid)
        if target is None:
            continue
        for history in list(target.conditions.values()):
            if history.condition_id == CHOKE_HISTORY and not any(c.condition_id == GRAPPLED
                    and c.source_actor_id == history.source_actor_id for c in target.conditions.values()):
                _recover_choke(engine, target, history)


@hook("turn_end")
def choking(engine: Any, actor: Any) -> None:
    """The choked creature's turn ends: one Exhaustion level while it is choking.  The choker's turn ends: a creature it no longer holds
    in a Choke Hold breathes again and loses the levels this hold gave it."""
    from .forged_exhaustion import add

    for history in list(actor.conditions.values()):
        if history.condition_id != CHOKE_HISTORY:
            continue
        if not all(any(c.condition_id == cid and c.source_actor_id == history.source_actor_id
                       for c in actor.conditions.values()) for cid in (CHOKE, CHOKING)):
            continue
        add(engine, actor, 1, history.source_definition_id)
        from .owned_effects import remove_conditions
        remove_conditions(engine, actor, history.source_definition_id, history.source_actor_id, CHOKE_HISTORY)
        engine._apply_condition(actor, CHOKE_HISTORY, history.source_definition_id, history.source_actor_id,
                                expires_on="UNTIL_REMOVED", data={**history.data, "levels": int(history.data.get("levels") or 0) + 1})
    for other in engine.state.actors.values():
        for history in list(other.conditions.values()):
            if history.condition_id == CHOKE_HISTORY and history.source_actor_id == actor.entity_id and not any(
                    c.condition_id == CHOKE and c.source_actor_id == actor.entity_id for c in other.conditions.values()):
                _recover_choke(engine, other, history)


@effect("wrestling_release")
def release_one(ctx: Any, eff: dict[str, Any]) -> None:
    """"End the grapple" -- only this creature's hold by the user (Hard Whip, Mountain-Crashing Suplex, Heaven-Lifting Throw)."""
    for subject in ctx.targets or ([ctx.target] if ctx.target else []):
        if subject is None:
            continue
        for iid, condition in list(subject.conditions.items()):
            if condition.condition_id in (GRAPPLED, "condition:typed.pinned") and condition.source_actor_id == ctx.actor.entity_id:
                subject.conditions.pop(iid)
                ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                                         payload={"condition_id": condition.condition_id, "instance_id": iid, "reason": "RELEASED"})
