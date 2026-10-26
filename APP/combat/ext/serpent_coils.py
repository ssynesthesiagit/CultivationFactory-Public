"""Seven-Coiled Serpent Spine: the Coils (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Seven-Coiled Serpent Spine ("Coil Rules" and the Coil features, with their
Normalized Procedures). Owned rows: ``{"type": "path_passive", "kind": "serpent_coils", "coils": 2 | 4 | 5 | 6 | 7}`` -- the
highest Coil each feature opens access to.

Coil record     condition "condition:typed.serpent_coils" (data.open: the highest open Coil; every lower one is open too). At the
                start of your turn, before other start-of-turn choices, the highest open Coil is asked (0 closes them all; none can
                be skipped). At the end of your turn, with 4-6 open, 1 Stamina upkeep; with all 7, 2 Stamina (asked: declining or
                being unable to pay closes them all). They close when you drop to 0 Hit Points.
Coil 1 Root     Advantage on saves and escapes against Grappled, Prone and forced movement.
Coil 2 Swift    Speed +10 feet; once per turn after a hit, move 5 feet without provoking (asked).
Coil 3 Crushing one size larger for your Grapples (size_steps); at the start of your turn, CON modifier Bludgeoning to one
                creature you Grapple (asked which when several; not an attack).
Coil 4 Striking once per turn on a hit, + 1d8 Bludgeoning or Force, 2d8 against a creature you Grapple.
Coil 6 Crowned  Blindsight 20 feet (a sense condition), Advantage on saves against Charmed and Frightened, +5 ft unarmed reach on your
                turn (state "crowned_serpent", reach_bonus); its once-a-round 10-foot follow is the compiled free row
                (``serpent_follow``, 1 Stamina) gated by row_allowed.
Coil 7 Heaven-Swallowing  Speed doubled, Resistance to all but Psychic and Void, + 2d8 Force on every unarmed hit, Grapples up to
                two sizes larger, Heaven-Swallowing Constriction (once per turn on a hit against a creature you Grapple, 2 Stamina,
                asked), and at the end of each turn 2d8 Force straight to your Hit Points (no reduction, no resources) before upkeep.
Every hook returns early for a creature without these rows or open Coils.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.seven_coiled_serpent_spine.feature."
COILS = "condition:typed.serpent_coils"
SOURCE = PREFIX + "coils"
STAMINA = "resource:core.stamina"
ALL_BUT = ("acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing", "poison", "radiant", "slashing", "thunder")


def access(engine: Any, actor: Any) -> int:
    return max([int(row.get("coils") or 0) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
                if row.get("block") == "path_rider" and row.get("kind") == "serpent_coils"] or [0])


def open_coils(actor: Any) -> int:
    held = next((c for c in actor.conditions.values() if c.condition_id == COILS), None)
    return int((held.data or {}).get("open") or 0) if held is not None else 0


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _grips(engine: Any, actor: Any) -> list[Any]:
    return [c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active
            and any(x.condition_id.endswith(".grappled") and x.source_actor_id == actor.entity_id for x in c.conditions.values())]


def set_open(engine: Any, actor: Any, count: int, why: str) -> None:
    """Record the highest open Coil and bring the Coils' lasting parts (sense, state, Resistances) in line with it."""
    from ..senses import SENSE
    from .states import PREFIX as STATE

    before = open_coils(actor)
    for iid, held in list(actor.conditions.items()):
        if held.condition_id == COILS or (held.source_definition_id == SOURCE and held.source_actor_id == actor.entity_id):
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", SOURCE, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": held.condition_id, "instance_id": iid, "reason": why})
    for mid, held in list(actor.modifiers.items()):
        if held.source_definition_id == SOURCE and held.source_actor_id == actor.entity_id:
            del actor.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", SOURCE, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"modifier_id": mid, "reason": why})
    if count <= 0:
        if before:
            note(engine, SOURCE, actor, f"Seven-Coiled Serpent Spine: {actor.display_name}'s Coils close ({why}).")
        return
    engine._apply_condition(actor, COILS, SOURCE, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"open": count, "label": f"Serpent Coils: {count} open"})
    if count >= 6:
        engine._apply_condition(actor, SENSE, SOURCE, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"sense": "blindsight", "range_ft": 20, "source": SOURCE, "label": "Crowned Serpent: Blindsight 20 feet"})
        engine._apply_condition(actor, STATE + "crowned_serpent", SOURCE, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Crowned Serpent", "name": "crowned_serpent"})
    if count >= 7:
        for kind in ALL_BUT:
            engine._add_modifier(actor, SOURCE, "damage_resistance", "ADD", kind.upper(), "SELF", expires_on="UNTIL_REMOVED")


@hook("turn_start_choice")
def choose_coils(engine: Any, actor: Any) -> None:
    most = access(engine, actor)
    if most <= 0 or not actor.active:
        return
    from .needle import ask, checkpoint_id

    current = open_coils(actor)
    options = [str(n) for n in range(0, most + 1)]
    labels = {str(n): ("Close every Coil" if n == 0 else f"Open Coils 1-{n}") for n in range(0, most + 1)}
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "serpent_coils", actor.entity_id), actor, "choice:needle.serpent_coils", options,
                 labels=labels, preferred=[str(current if current else min(most, 4))], target_id=actor.entity_id, name="Seven-Coiled Serpent Spine",
                 prompt="Seven-Coiled Serpent Spine: set your open Coils for this turn (upkeep at the end of your turn: 1 Stamina with 4-6 open, 2 with 7).")
    count = int((picked or [str(current)])[0])
    if count != current:
        set_open(engine, actor, count, "set at the start of the turn")
    crushing(engine, actor)


def crushing(engine: Any, actor: Any) -> None:
    if open_coils(actor) < 3:
        return
    held = _grips(engine, actor)
    if not held:
        return
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .states import context

    pick = held[0]
    if len(held) > 1:
        chosen = ask(engine, _intent(engine), checkpoint_id(engine, "crushing_serpent", actor.entity_id), actor, "choice:needle.crushing_serpent",
                     [c.entity_id for c in held], labels={c.entity_id: c.display_name for c in held}, target_id=actor.entity_id,
                     prompt="Crushing Serpent: which creature you Grapple takes your Constitution modifier in Bludgeoning damage?")
        pick = next((c for c in held if chosen and c.entity_id == chosen[0]), held[0])
    con = next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") or 0)
                for a in engine.action_catalog.values() if a.owner_id == actor.entity_id and (((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") is not None), 0)
    if con <= 0:
        return
    ctx = context(engine, actor, PREFIX + "third_and_fourth_coils", [pick], {"pb": int(actor.proficiency_bonus or 2)})
    ctx.intent = _intent(engine)
    te.run_effects(ctx, [{"type": "damage", "applies_to": "target", "flat": con, "damage_types": ["bludgeoning"], "evidence": "Crushing Serpent"}])


@hook("turn_end")
def upkeep(engine: Any, actor: Any) -> None:
    count = open_coils(actor)
    if count <= 0:
        return
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, actor, SOURCE, independent=True):
        if count >= 7 and actor.active:
            from ..gate2_runtime_models import DiceSpec

            roll = engine.roller.roll(DiceSpec(count=2, sides=8, modifier=0), actor_id=actor.entity_id, reason=f"DAMAGE:{PREFIX}seventh_coil")
            engine._record_roll(roll)
            before = actor.current_hp
            actor.current_hp = max(0, before - int(roll.total))
            engine._append_event("DAMAGE_COMMITTED", PREFIX + "seventh_coil_heaven_swallowing_serpent", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"rolled_or_pending_damage": int(roll.total), "reduced_to": int(roll.total), "temporary_hp_absorbed": 0,
                                          "hp_damage": before - actor.current_hp, "damage_type": "FORCE", "remaining_hp": actor.current_hp, "gate_damage": True})
            if actor.current_hp == 0:
                set_open(engine, actor, 0, "it dropped to 0 Hit Points")
                engine._defeat(actor, PREFIX + "seventh_coil_heaven_swallowing_serpent")
                engine._check_victory()
                return
        cost = 2 if count >= 7 else 1 if count >= 4 else 0
        if not cost:
            return
        if int(actor.resources.get(STAMINA, 0) or 0) < cost:
            set_open(engine, actor, 0, "the upkeep could not be paid")
            return
        from .needle import ask, checkpoint_id

        picked = ask(engine, _intent(engine), checkpoint_id(engine, "coil_upkeep", actor.entity_id), actor, "choice:needle.coil_upkeep", ["pay"],
                     labels={"pay": f"Pay {cost} Stamina to keep {count} Coils open"}, allow_decline=True, target_id=actor.entity_id,
                     name="Seven-Coiled Serpent Spine", prompt="Coil upkeep: pay, or every Coil closes.")
        if picked:
            engine._spend_resource(actor, STAMINA, cost, SOURCE)
        else:
            set_open(engine, actor, 0, "the upkeep was declined")


@hook("event")
def coils_close_at_zero(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is not None and actor.current_hp <= 0 and open_coils(actor):
            set_open(engine, actor, 0, "it dropped to 0 Hit Points")


# ----------------------------------------------------------------------------------------------------- benefits
@hook("speed")
def coil_speed(engine: Any, actor: Any) -> int | None:
    count = open_coils(actor)
    if count < 2:
        return None
    if count < 7:
        return 10  # Swift Serpent
    # "Double walking Speed after fixed additions": the Seventh Coil adds the walking Speed as it stands with Swift Serpent's +10.
    from ..motion import speed_adjustment
    return 10 + max(0, int(actor.speed_ft) + speed_adjustment(engine, actor) + 10)



@hook("save")
def coil_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None or ctx.actor is subject:
        return None
    count = open_coils(subject)
    names = set(named or ())
    if (count >= 1 and names & {"grappled", "prone", "forced_movement"}) or (count >= 6 and names & {"charmed", "frightened"}):
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("escape_mode")
def root_escape(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if open_coils(escaper) >= 1 else None


@hook("escape_save_mode")
def root_escape_save(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if open_coils(escaper) >= 1 else None


@hook("size_steps")
def coil_size(engine: Any, creature: Any, role: str, purposes: Any) -> int | None:
    if role != "act":
        return None
    count = open_coils(creature)
    if count < 3 or "grapple" not in purposes:
        return None
    return 2 if count >= 7 else 1  # Crushing Serpent's one size; the Seventh Coil's two (the higher, not added)


def _move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(ctx.engine, mover, feet)
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "serpent_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        step(ctx.engine, mover, paths[picked[0]], SOURCE)


@hook("after_hit")
def coil_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    count = open_coils(actor)
    if count <= 1 or target is None or target.team_id == actor.team_id:
        return
    from .. import typed_executor as te

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    gripped = any(c.condition_id.endswith(".grappled") and c.source_actor_id == actor.entity_id for c in target.conditions.values())
    if count >= 4 and target.active and actor.turn_flags.get("_round_striking_serpent") != _stamp(engine):
        actor.turn_flags["_round_striking_serpent"] = _stamp(engine)
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2 if gripped else 1, "sides": 8},
                              "damage_types": ["bludgeoning", "force"], "evidence": "Striking Serpent"}])
    if count >= 7 and kind == "unarmed" and target.active:
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["force"],
                              "evidence": "Heaven-Swallowing Serpent: + 2d8 Force"}])
    if count >= 7 and gripped and target.active and actor.turn_flags.get("_round_constriction") != _stamp(engine) \
            and int(actor.resources.get(STAMINA, 0) or 0) >= 2:
        from .needle import ask, checkpoint_id

        picked = ask(engine, ctx.intent, checkpoint_id(engine, "constriction", target.entity_id), actor, "choice:needle.heaven_swallowing_constriction",
                     ["constrict"], labels={"constrict": f"2 Stamina: {target.display_name} makes a Constitution save (6d8, no Reactions, Speed 0)"},
                     allow_decline=True, target_id=target.entity_id, name="Heaven-Swallowing Constriction", prompt="Heaven-Swallowing Constriction?")
        if picked:
            actor.turn_flags["_round_constriction"] = _stamp(engine)
            engine._spend_resource(actor, STAMINA, 2, PREFIX + "seventh_coil_heaven_swallowing_serpent")
            until = "START_OF_SOURCE_NEXT_TURN"
            te.run_effects(sub, [{"type": "save", "ability": "con", "evidence": "Heaven-Swallowing Constriction: Constitution saving throw",
                                  "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 6, "sides": 8}, "damage_types": ["bludgeoning", "force"]},
                                              {"type": "reaction_denied", "applies_to": "target", "expires_on": until},
                                              {"type": "speed", "applies_to": "target", "becomes": 0, "expires_on": until},
                                              {"type": "disadvantage", "applies_to": "target", "on": "Strength, Dexterity, and Constitution saving throws", "expires_on": until}],
                                  "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["bludgeoning", "force"]},
                                                 {"type": "speed", "applies_to": "target", "halved": True, "expires_on": until}]}])
    if count >= 2 and actor.turn_flags.get("_round_swift_serpent") != _stamp(engine) and engine.state.current_actor_id == actor.entity_id:
        actor.turn_flags["_round_swift_serpent"] = _stamp(engine)
        _move(sub, actor, 5, "choice:needle.swift_serpent_step", "Swift Serpent")


@hook("row_allowed")
def crowned_follow_open(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    if str(row.get("feature_id") or "") != PREFIX + "sixth_coil_crowned_serpent":
        return None
    return None if open_coils(actor) >= 6 else False


@effect("serpent_follow")
def serpent_follow(ctx: Any, row: dict[str, Any]) -> None:
    """Crowned Serpent: move up to 10 feet without provoking, ending closer to the creature that moved."""
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    other = ctx.target
    if other is None:
        return
    engine, actor = ctx.engine, ctx.actor
    now = engine._distance_actor_to_actor(actor, other)
    paths = {k: p for k, p in routes(engine, actor, 10).items() if engine.grid.distance_ft(p[-1], other.position) < now}
    if not paths:
        return
    if int(actor.resources.get(STAMINA, 0) or 0) < 1:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "crowned_follow", actor.entity_id), actor, "choice:needle.crowned_serpent_follow", sorted(paths),
                 allow_decline=True, labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=actor.entity_id,
                 preferred=[min(paths, key=lambda k: engine.grid.distance_ft(paths[k][-1], other.position))],
                 prompt=f"Crowned Serpent: follow {other.display_name} (up to 10 feet, ending closer)?")
    if picked and picked[0] in paths:
        engine._spend_resource(actor, STAMINA, 1, PREFIX + "sixth_coil_crowned_serpent")
        step(engine, actor, paths[picked[0]], PREFIX + "sixth_coil_crowned_serpent")


@hook("stand_cost")
def root_standing(engine: Any, actor: Any, normal_cost: int) -> int | None:
    return 5 if open_coils(actor) >= 1 else None


@hook("flight")
def seventh_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    if actor.active and open_coils(actor) >= 7:
        return {"fly_speed_ft": int(engine._effective_speed(actor)), "flight_hover": True}
    return None
