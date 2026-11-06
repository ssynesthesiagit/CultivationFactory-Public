"""Guardian chassis: Interpose, Held Harm and the talents built on them (rider lane C16, 2026-09-30; owner: fill the sphere chassis
from the owner's books, do not ask). Rules text: the owner's Sphere Compendium, "Sphere of Guardian", Core Guardian Rules (Held Harm
and Interpose are printed there, not in the typed authority) and the talents below (authority/typed_mechanics/rules_text.json).

Who has it: every Guardian. A character owning either Guardian Practice carries a compiled ``guardian`` row of kind ``guardian_core``
(Challenge Practice) or ``patrol_practice`` (Patrol Practice) -- combat/rules/feature_blocks.d/riders_c16.json, compiled by
combat/ext/guardian.py. Every hook below returns at once for a creature without one, so other creatures and older fights are untouched.

Interpose -- "Reaction. Trigger: One ally within 10 feet is targeted by an attack roll. Range: 10 feet. Move up to 10 feet into one legal
  unoccupied space adjacent to the ally. This movement does not provoke opportunity attacks. If you are a legal target for the
  triggering attack, become its target instead." A provider of combat/ext/redirection.py (the one owner of retarget_attack), so it
  answers typed and legacy attacks as they are declared, before the d20. Asked of the Guardian (Use / Decline); the built-in AI
  interposes when it has more Hit Points or a better Armor Class than the ally. Players choose any offered square next to the ally;
  AI prefers a square from which the Guardian is a legal target, the shortest move first. Not offered for an attacker the Guardian
  cannot see ("attacks you cannot perceive"); area and saving-throw effects never reach it (they are not attack rolls).
  Bodyguard -- "its range increases to 20 feet; you may move up to 20 feet when using it; gain Resistance to the triggering attack's
  damage until that attack resolves". Its declaration spec owns the Resistance; only damage with that confirmed
  attack's provenance (including its typed on-hit damage) receives it. Misses, cancellations, nested attacks and
  separate damage never leave a turn-wide benefit. attack_defenses is the public shared helper.
  Court of the Unbroken Gate -- "Use Interpose once per round without spending your Reaction" (used before the Reaction).
  Guardian's Focus -- "you successfully use Interpose" (it became the target) / "a creature Challenged by you is reduced to 0 HP":
  regain Martial Focus if absent, once per round.

Held Harm -- "a Held Harm Pool with a maximum equal to 3 x your Cultivation Level. Whenever you would take damage, apply Resistance,
  Immunity, and ordinary reductions first. You may then redirect any amount of the remaining damage into your Held Harm Pool, up to its
  remaining capacity ... At the end of each of your turns: take all damage stored in your Held Harm Pool as one damage instance; this
  damage bypasses Resistance, Immunity, and damage reduction; this damage cannot be redirected into Held Harm again; then reduce your
  Held Harm Pool to 0." The ``final_damage`` hook (after every defence and reaction, before Temporary HP) asks how much to hold (all
  that fits, half, or none; the built-in AI holds all that fits). The pool is a condition on the Guardian ("Held Harm: N damage held
  back"); "Temporary HP can absorb this end-of-turn damage normally"; "healing that would restore HP above your maximum instead reduces
  your Held Harm by the excess amount" (HEALING_APPLIED). Deep Reservoir: maximum + CL. Court of the Unbroken Gate: maximum + CL.
  Durable -- "When you fail a saving throw against one of the following, you may reserve 10 points of empty space in your Held Harm Pool
  ... delay the effect until the end of your next turn. The reserved space counts against your Held Harm maximum ... is released when
  the delayed effect resolves." Cold Iron Call -- a supernatural effect that does not merely deal damage: reserve 5 x the originator's
  Proficiency Bonus and delay its non-damaging portion the same way (not an area's whole effect, a Domain or a Secret Inheritance).
  Both through the ``condition_state`` hook: the condition is not applied; a "Delayed: <condition>" record keeps the exact typed row and
  numbers, and at the end of the Guardian's next turn the row runs again on it (its stated duration counted from then). "You may
  voluntarily release one Durable effect without spending an Action. It applies immediately": the no-action button "Release a delayed
  effect now".
  Punishment Returned -- a melee weapon attack or Unarmed Strike hit while the pool holds damage, Martial Focus, once per round: the
  target's Constitution save against your Cultivation Save DC, failed: additional damage equal to the held damage, of the attack's
  type; success: half. Or transmit one delayed effect instead: the target makes that effect's own save at its own DC; either way the
  delayed effect ends for you. Asked; the built-in AI deals the damage.

Court of the Unbroken Gate (its own state ``court_of_the_unbroken_gate``, ending if you are Incapacitated): you -- forced movement 20
  feet shorter, Advantage on saves and escape checks against Grappled, Prone and Restrained; allies inside its 30-foot aura -- +1 AC,
  Advantage on saves against Frightened, forced movement 10 feet shorter, Half Cover against ranged attacks within 10 feet of you;
  enemies inside -- the squares next to you are difficult terrain (an aura area worked out from the fight, never stored).

Stored data is integers and strings only (the delayed row is kept as JSON text).
"""

from __future__ import annotations

from ..paid_relocation import activation

import json
from typing import Any

from . import effect, hook, note
from .guardian import CHALLENGED, row
from .needle import CHOICE, ask, checkpoint_id, incapacitated
from .redirection import legal_target, provider

FOCUS = "resource:core.martial_focus"
HELD = "condition:typed.held_harm"
DELAY = "condition:typed.guardian_delay"
HELD_SOURCE = "system:guardian.held_harm"
INTERPOSE = "GUARDIAN_CORE_INTERPOSE"
COURT = "court_of_the_unbroken_gate"
COURT_ID = "TAL_GUARDIAN_COURT_OF_THE_UNBROKEN_GATE"
DURABLE_ID, COLD_IRON_ID = "TAL_GUARDIAN_DURABLE", "TAL_GUARDIAN_COLD_IRON_CALL"
PUNISHMENT_ID = "TAL_GUARDIAN_PUNISHMENT_RETURNED"
DURABLE_CONDITIONS = {"blinded", "charmed", "deafened", "frightened", "paralyzed", "petrified", "poisoned", "restrained", "stunned",
                      "unconscious"}
COURT_RESISTS = {"grappled", "prone", "restrained"}


# ------------------------------------------------------------------------------------------------ who is a Guardian
def core_row(engine: Any, actor: Any) -> dict[str, Any] | None:
    """The Guardian's compiled core row (either Practice), or None for any other creature."""
    if actor is None:
        return None
    return row(engine, actor, "guardian_core") or row(engine, actor, "patrol_practice")


def cultivation_level(engine: Any, actor: Any) -> int:
    """Compiled Guardian level for Held Harm and Patrol scaling; 1 without a core row.

    Used by guardian_chassis and guardian_patrol. Callers gate ability behavior
    on their owning rows; this helper only reads the saved compiled numbers.
    """
    return int((core_row(engine, actor) or {}).get("cl") or 1)


def _guardians(engine: Any) -> list[Any]:
    rows = getattr(engine, "typed_passive_rows", {}) or {}
    return [actor for actor_id, owned in sorted(rows.items()) if (actor := engine.state.actors.get(actor_id)) is not None
            and any(r.get("block") == "guardian" and r.get("kind") in ("guardian_core", "patrol_practice") for r in owned)]


def court_active(engine: Any, actor: Any) -> bool:
    from .states import active

    return active(engine, actor, COURT) is not None


def _round_key(engine: Any) -> int:
    return int(engine.state.round_number)


def regain_focus(engine: Any, guardian: Any, why: str) -> None:
    """Guardian's Focus: regain Martial Focus if it is absent, once per round (shared with combat/ext/guardian_patrol.py)."""
    owned = row(engine, guardian, "guardians_focus")
    if owned is None or not guardian.active or guardian.resources.get(FOCUS, 0) >= 1 or FOCUS not in guardian.resources:
        return
    if guardian.turn_flags.get("guardian_round_focus") == _round_key(engine):
        return
    guardian.turn_flags["guardian_round_focus"] = _round_key(engine)
    engine._gain_resource(guardian, FOCUS, 1, str(owned.get("feature_id")))
    note(engine, str(owned.get("feature_id")), guardian, f"Guardian's Focus: {guardian.display_name} regains Martial Focus ({why}).")


# ------------------------------------------------------------------------------------------------ Guardian's Focus
@hook("resolution_final")
def maneuver_focus(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    """Actual successful ordinary Grapple/Shove outcomes while Patrol is active.

    New sealed rows opt in. Condition immunity or a blocked push does not invent
    success; only the actual action's applied condition/movement earns Focus.
    """
    owned = row(engine, actor, "guardians_focus")
    if owned is None or not owned.get("maneuver_focus") or not actor.active:
        return
    from .guardian_patrol import patrol

    if patrol(actor) is None:
        return
    option = ((action.parameters or {}).get("typed") or {}).get("unarmed_option")
    if option not in {"grapple", "shove_prone", "shove_push"}:
        return
    target_ids = set(candidate.target_ids or ())
    for event in reversed(engine.events):
        if event.event_type == "INTENT_ACCEPTED":
            break
        if event.source_definition_id != action.source_definition_id:
            continue
        payload = event.payload or {}
        condition = {"grapple": "condition:typed.grappled", "shove_prone": "condition:typed.prone"}.get(option)
        applied = (condition and event.event_type == "CONDITION_APPLIED"
                   and payload.get("condition_id") == condition and target_ids.intersection(event.target_ids))
        moved = (option == "shove_push" and event.event_type == "MOVEMENT_COMMITTED"
                 and event.actor_id in target_ids and payload.get("forced") and len(payload.get("path") or ()) > 1)
        if applied or moved:
            regain_focus(engine, actor, "a successful Grapple or Shove while Patrol is active")
            return


# ------------------------------------------------------------------------------------------------ Interpose
def _interpose_range(engine: Any, guardian: Any) -> int:
    return 20 if row(engine, guardian, "bodyguard") is not None else 10


def _free_court_use(engine: Any, guardian: Any) -> bool:
    return court_active(engine, guardian) and guardian.turn_flags.get("guardian_round_court_interpose") != _round_key(engine)


def _armor(engine: Any, actor: Any) -> int:
    return int(actor.armor_class) + int(engine._ac_modifier(actor))


def _spots(engine: Any, guardian: Any, ally: Any, attacker: Any, range_ft: int | None, budget: int) -> list[tuple[Any, tuple[Any, ...]]]:
    """The square Interpose moves to: next to the ally, reachable within ``budget``, from which the Guardian is a legal target of
    the attack (else any square next to the ally); the shortest move first."""
    from .granted_moves import destinations

    def beside(position: Any) -> bool:
        cells = engine._actor_cells(guardian, position)
        ally_cells = set(engine._actor_cells(ally))
        return not (set(cells) & ally_cells) and engine.grid.distance_between_cell_sets_ft(cells, ally_cells) <= 5

    spots = destinations(engine, guardian, budget, beside)
    if not spots:
        return None

    def targetable(position: Any) -> bool:
        start = guardian.position
        guardian.position = position
        try:
            return legal_target(engine, attacker, guardian, range_ft)
        finally:
            guardian.position = start

    # Prefer legal attack targets while retaining all reachable beside squares
    # for a player-owned destination choice.
    return sorted(spots, key=lambda spot: not targetable(spot[0]))


@provider(50)
def interpose(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    from .. import stealth
    from ..typed_reactions import _can_react

    if not getattr(engine, "typed_passive_rows", None):
        return None
    for guardian in sorted(_guardians(engine), key=lambda g: (engine._distance_actor_to_actor(g, defender), g.entity_id)):
        if (guardian.entity_id in (attacker.entity_id, defender.entity_id) or not guardian.active or incapacitated(guardian)
                or guardian.team_id != defender.team_id or attacker.team_id == guardian.team_id):
            continue
        free = _free_court_use(engine, guardian)
        if not free and not _can_react(engine, guardian):
            continue
        reach = _interpose_range(engine, guardian)
        if engine._distance_actor_to_actor(guardian, defender) > reach or not stealth.sees(engine, guardian, attacker):
            continue
        spots = _spots(engine, guardian, defender, attacker, context.get("range_ft"), reach)
        if not spots:
            continue
        destination, path, _cost = spots[0]
        action = engine.action_catalog.get(context.get("source_id") or "")
        attack_name = getattr(action, "display_name", None) or "attack"
        cost = "no Reaction (Court of the Unbroken Gate, once per round)" if free else "your Reaction"
        moving = destination != guardian.position
        prompt = (f"Interpose ({cost}): {attacker.display_name} is attacking {defender.display_name} with {attack_name}. "
                  + (f"Step {engine.grid.distance_ft(guardian.position, destination)} feet to {defender.display_name}'s side and take the "
                     "attack yourself? The move provokes no opportunity attacks." if moving else "Take the attack yourself?"))
        wants = (guardian.current_hp > defender.current_hp) or (_armor(engine, guardian) > _armor(engine, defender))
        picked = ask(engine, intent, checkpoint_id(engine, "INTERPOSE", guardian.entity_id, attacker.entity_id, defender.entity_id),
                     guardian, CHOICE + "interpose", ["interpose"],
                     labels={"interpose": f"Interpose: take {attacker.display_name}'s attack instead of {defender.display_name}"},
                     prompt=prompt, preferred=["interpose"], allow_decline=True, automatic=wants, target_id=guardian.entity_id,
                     default="decline" if not wants else "first", name="Interpose")
        if picked != ["interpose"]:
            continue
        if len(spots) > 1:
            from .needle import cell_id
            by_square = {cell_id(position): (position, route) for position, route, _cost in spots}
            destinations = sorted(by_square)
            square = ask(engine, intent, checkpoint_id(engine, "INTERPOSE_DESTINATION", guardian.entity_id, attacker.entity_id,
                                                       defender.entity_id), guardian, CHOICE + "interpose_destination", destinations,
                         labels={key: "Move to " + key.removeprefix("cell:") for key in destinations}, target_id=guardian.entity_id,
                         preferred=[cell_id(destination)],
                         name="Interpose destination", prompt=f"Interpose: choose which open square beside {defender.display_name} to move to.")
            if not square or square[0] not in by_square:
                continue
            destination, path = by_square[square[0]]
        return _do_interpose(engine, guardian, attacker, defender, destination, path, free, context)
    return None


def _do_interpose(engine: Any, guardian: Any, attacker: Any, defender: Any, destination: Any, path: tuple[Any, ...], free: bool,
                  context: dict[str, Any]) -> dict[str, Any] | None:
    from .granted_moves import commit

    with activation(engine, guardian, INTERPOSE):
        if free:
            guardian.turn_flags["guardian_round_court_interpose"] = _round_key(engine)
        else:
            guardian.reaction_available = False
        engine._append_event("REACTION_RESOLVED", INTERPOSE, actor_id=guardian.entity_id, target_ids=(attacker.entity_id, defender.entity_id),
                             payload={"reaction": "interpose", "free": int(free), "gate3_reaction_available_after": bool(guardian.reaction_available)})
        commit(engine, guardian, path, INTERPOSE)
        if not legal_target(engine, attacker, guardian, context.get("range_ft")):
            note(engine, INTERPOSE, guardian, f"Interpose: {guardian.display_name} steps beside {defender.display_name} but cannot be the "
                 f"target of {attacker.display_name}'s attack from there; it goes on against {defender.display_name}.", (attacker, defender))
            return None
        if row(engine, guardian, "bodyguard") is not None:
            from .attack_defenses import grant_resistance

            spec = context.get("attack_spec")
            if spec is not None:
                grant_resistance(spec, guardian, "TAL_GUARDIAN_BODYGUARD")
        note(engine, INTERPOSE, guardian, f"Interpose: {guardian.display_name} steps in and becomes the target of {attacker.display_name}'s "
             f"attack instead of {defender.display_name}" + (" (Bodyguard: Resistance to its damage)." if row(engine, guardian, "bodyguard")
                                                             else "."), (attacker, defender))
        regain_focus(engine, guardian, "a successful Interpose")
        return {"source_id": INTERPOSE, "target_id": guardian.entity_id, "cover_bonus": 0}


# ------------------------------------------------------------------------------------------------ Held Harm
def _held(actor: Any) -> Any | None:
    return next((c for c in actor.conditions.values() if c.condition_id == HELD), None)


def stored(actor: Any) -> int:
    held = _held(actor)
    return int((held.data or {}).get("stored") or 0) if held is not None else 0


def delays(actor: Any) -> list[Any]:
    return sorted((c for c in actor.conditions.values() if c.condition_id == DELAY), key=lambda c: (c.applied_sequence, c.instance_id))


def reserved(actor: Any) -> int:
    return sum(int((c.data or {}).get("reserve") or 0) for c in delays(actor))


def maximum(engine: Any, actor: Any) -> int:
    cl = cultivation_level(engine, actor)
    return 3 * cl + (cl if row(engine, actor, "deep_reservoir") is not None else 0) + (cl if court_active(engine, actor) else 0)


def room(engine: Any, actor: Any) -> int:
    return max(0, maximum(engine, actor) - stored(actor) - reserved(actor))


def _set_stored(engine: Any, actor: Any, amount: int, source: str) -> None:
    from .rider_support import remove_instance

    old = _held(actor)
    if old is not None:
        remove_instance(engine, actor, old.instance_id, source)
    if amount > 0:
        engine._apply_condition(actor, HELD, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"stored": int(amount),
                                      "label": f"Held Harm: {amount} damage held back. {actor.display_name} takes it all at once at the end "
                                               f"of its turn, ignoring Resistance (pool {maximum(engine, actor)})"})


@hook("final_damage")
def hold_harm(engine: Any, target: Any, amount: int, damage_type: str, source_id: str, source_actor_id: str, intent: Any) -> dict[str, Any] | None:
    if amount <= 0 or source_id == HELD_SOURCE or not target.active or core_row(engine, target) is None:
        return None
    # The final_damage hook has no transactional post-reduction packet. Until
    # Astra supplies damage_deferral, do not create a delayed liability here.
    note(engine, HELD_SOURCE, target, f"Held Harm is unavailable for {target.display_name}'s incoming damage until damage reductions can be applied before damage is deferred.")
    return None
    space = room(engine, target)
    if space <= 0:
        return None
    most = min(space, int(amount))
    labels = {f"hold:{amount}": f"Hold back {amount} damage (taken at the end of your turn)"
              for amount in range(1, most + 1)}
    # Keep the established shortcut for existing table clients and AI policy.
    labels["all"] = f"Hold back {most} of it (taken at the end of your turn)"
    who = engine.state.actors.get(source_actor_id)
    picked = ask(engine, intent, checkpoint_id(engine, "HELD_HARM", target.entity_id, source_id), target, CHOICE + "held_harm",
                 list(labels), labels=labels, preferred=["all"], allow_decline=True, name="Held Harm", target_id=target.entity_id,
                 prompt=f"Held Harm: {target.display_name} is about to take {amount} damage from {getattr(engine.action_catalog.get(source_id), 'display_name', None) or 'the triggering action'}"
                        f"{' from ' + who.display_name if who is not None and who is not target else ''}. Choose how many points "
                        f"to hold back, up to {most} (pool room: {space}). Held damage is not taken now: it is taken all at once "
                        f"at the end of {target.display_name}'s turn, ignoring Resistance. Decline to take it all now. No action or cost.")
    choice = picked[0] if picked else "none"
    held = most if choice == "all" else int(choice[5:]) if choice.startswith("hold:") and choice[5:].isdigit() else 0
    if held <= 0:
        return None
    total = stored(target) + held
    _set_stored(engine, target, total, HELD_SOURCE)
    note(engine, HELD_SOURCE, target, f"Held Harm: {target.display_name} holds back {held} of {amount} damage; {total} held in all, "
         f"taken at the end of its turn.", (), held=held)
    return {"amount": int(amount) - held}


@hook("turn_end")
def take_held_harm(engine: Any, actor: Any) -> None:
    if core_row(engine, actor) is None:
        return
    for delay in delays(actor):
        if int(actor.turns_started) >= int((delay.data or {}).get("due") or 0):
            release(engine, actor, delay, "the end of its next turn")
    amount = stored(actor)
    if amount <= 0:
        return
    _set_stored(engine, actor, 0, HELD_SOURCE)
    if not actor.active:
        return
    note(engine, HELD_SOURCE, actor, f"Held Harm: at the end of its turn {actor.display_name} takes the {amount} damage it held back "
         "(ignoring Resistance and damage reduction).", (), held=amount)
    previous = engine.__dict__.get("_damage_unreduced")
    engine._damage_unreduced = actor.entity_id  # "bypasses Resistance, Immunity, and damage reduction"
    try:
        engine._commit_damage(actor, amount, "UNTYPED", HELD_SOURCE, actor.entity_id, None, reaction_depth=2)
    finally:
        engine._damage_unreduced = previous


@hook("event")
def guardian_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "HEALING_APPLIED":
        payload = kwargs.get("payload") or {}
        excess = int(payload.get("offered") or 0) - (int(payload.get("after") or 0) - int(payload.get("before") or 0))
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            held = stored(target) if target is not None else 0
            if excess > 0 and held > 0:
                left = max(0, held - excess)
                _set_stored(engine, target, left, HELD_SOURCE)
                note(engine, HELD_SOURCE, target, f"Held Harm: healing beyond {target.display_name}'s maximum takes {held - left} off the "
                     f"damage it holds ({left} left).")
    elif event_type == "DAMAGE_COMMITTED" and int((kwargs.get("payload") or {}).get("remaining_hp", 1) or 0) <= 0:
        for target_id in kwargs.get("target_ids") or ():  # Guardian's Focus: "a creature Challenged by you is reduced to 0 HP"
            target = engine.state.actors.get(target_id)
            for guardian_id in sorted({c.source_actor_id for c in (target.conditions.values() if target else ()) if c.condition_id == CHALLENGED}):
                guardian = engine.state.actors.get(guardian_id)
                if guardian is not None:
                    regain_focus(engine, guardian, f"{target.display_name}, Challenged by it, dropped to 0 HP")


# ------------------------------------------------------------------------------------------------ Durable and Cold Iron Call
def _supernatural(ctx: Any) -> bool:
    """A typed technique (a cultivation attack or a save), not a weapon or unarmed strike, a core Shove/Grapple or a mundane item."""
    typed = ctx.typed or {}
    if typed.get("mundane") or typed.get("weapon") or str(ctx.action.source_definition_id).startswith(("action:typed.core", "unarmed")):
        return False
    attack = (ctx.attack_effect or {}).get("attack_kind") if isinstance(ctx.attack_effect, dict) else None
    return attack is None or str(attack).startswith("cultivation")


def _excluded(ctx: Any) -> bool:
    """Cold Iron Call does not delay "an entire area of effect ... a Domain; a Secret Inheritance"."""
    name = f"{ctx.action.display_name} {(ctx.typed or {}).get('source') or ''}".lower()
    return bool(((ctx.typed or {}).get("area") or {}).get("size_ft")) or "domain" in name or "secret inheritance" in name


@hook("condition_state")
def delay_condition(ctx: Any, subject: Any, eff: dict[str, Any]) -> dict[str, Any] | bool | None:
    engine = ctx.engine
    if engine.__dict__.get("_guardian_releasing") or subject is None or subject is ctx.actor or core_row(engine, subject) is None:
        return None
    note(engine, DELAY, subject, f"Delaying a condition on {subject.display_name} is unavailable until cures can remove a delayed condition.", (ctx.actor,))
    return None
    name = str(eff.get("condition") or "").lower()
    offers: list[tuple[int, str]] = []
    if row(engine, subject, "durable") is not None and ctx.failed_save and name in DURABLE_CONDITIONS:
        offers.append((10, DURABLE_ID))
    if row(engine, subject, "cold_iron_call") is not None and ctx.actor.team_id != subject.team_id and _supernatural(ctx) and not _excluded(ctx):
        offers.append((5 * int((ctx.numbers or {}).get("pb") or ctx.actor.proficiency_bonus or 2), COLD_IRON_ID))
    offers = [offer for offer in offers if offer[0] <= room(engine, subject)]
    if not offers:
        return None
    reserve, talent = min(offers)
    label = name.replace("_", " ").title()
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "GUARDIAN_DELAY", subject.entity_id, name), subject, CHOICE + "guardian_delay",
                 ["delay"], labels={"delay": f"Delay {label} until the end of your next turn ({reserve} Held Harm space)"},
                 prompt=f"{'Durable' if talent == DURABLE_ID else 'Cold Iron Call'}: {ctx.actor.display_name}'s {ctx.action.display_name} "
                        f"would make {subject.display_name} {label}. Reserve {reserve} points of Held Harm space to delay it until the end of "
                        f"{subject.display_name}'s next turn? It then applies as normal. No action.",
                 preferred=["delay"], allow_decline=True, target_id=subject.entity_id, name="Delay a condition")
    if picked != ["delay"]:
        return None
    numbers = {key: int(value) for key, value in (ctx.numbers or {}).items() if key in ("save_dc", "pb", "cl", "key_mod") and isinstance(value, int)}
    engine._apply_condition(subject, DELAY, talent, subject.entity_id, expires_on="UNTIL_REMOVED", data={
        "reserve": int(reserve), "condition": name, "due": int(subject.turns_started) + 1, "source_actor": ctx.actor.entity_id,
        "action": ctx.action.source_definition_id, "row": json.dumps(eff, sort_keys=True), "numbers": json.dumps(numbers, sort_keys=True),
        "origin_save": json.dumps(dict(ctx.origin_save or {}), sort_keys=True),
        "label": f"Delayed: {label} from {ctx.actor.display_name}'s {ctx.action.display_name}. It applies at the end of "
                 f"{subject.display_name}'s next turn ({reserve} Held Harm space reserved until then)"})
    note(engine, talent, subject, f"{'Durable' if talent == DURABLE_ID else 'Cold Iron Call'}: {subject.display_name} delays {label} until "
         f"the end of its next turn ({reserve} Held Harm space reserved).", (ctx.actor,))
    return False


def _delay_context(engine: Any, holder: Any, delay: Any, target: Any) -> tuple[Any, dict[str, Any]] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..typed_executor import Context

    data = delay.data or {}
    source = engine.state.actors.get(str(data.get("source_actor") or ""))
    if source is None:
        return None
    action = engine.action_catalog.get(str(data.get("action") or "")) or ActionDefinition(
        source_definition_id=str(data.get("action") or DELAY), display_name="Delayed effect", owner_id=source.entity_id,
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    typed = dict(((action.parameters or {}).get("typed") or {}))
    typed["numbers"] = {**(typed.get("numbers") or {}), **json.loads(str(data.get("numbers") or "{}"))}
    origin = json.loads(str(data.get("origin_save") or "{}")) or None
    ctx = Context(engine, source, action, None, typed, [target], target, {}, failed_save=True if origin else None, origin_save=origin)
    return ctx, json.loads(str(data.get("row") or "{}"))


def release(engine: Any, holder: Any, delay: Any, why: str) -> None:
    """Apply a delayed condition to its holder now and free its reserved space."""
    from ..typed_executor import run_effects
    from .rider_support import remove_instance

    built = _delay_context(engine, holder, delay, holder)
    remove_instance(engine, holder, delay.instance_id, str(delay.source_definition_id))
    if built is None or not holder.active:
        return
    ctx, eff = built
    note(engine, str(delay.source_definition_id), holder, f"{holder.display_name}'s delayed {str((delay.data or {}).get('condition') or '').title()} "
         f"applies now ({why}).")
    engine._guardian_releasing = True
    try:
        run_effects(ctx, [{**eff, "applies_to": "target"}])
    finally:
        engine._guardian_releasing = False


@effect("guardian_release_delay")
def release_now(ctx: Any, eff: dict[str, Any]) -> None:
    pending = delays(ctx.actor)
    if pending:
        release(ctx.engine, ctx.actor, pending[0], "released early by choice")


@hook("compile_actions")
def release_button(info: dict[str, Any]) -> list[Any] | None:
    """Durable / Cold Iron Call: "You may voluntarily release one Durable effect without spending an Action. It applies immediately."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned = set(info.get("owned_ids") or ())
    if not owned & {DURABLE_ID, COLD_IRON_ID}:
        return None
    typed = {"effects": [{"type": "guardian_release_delay", "applies_to": "self"}], "numbers": info["numbers"],
             "duration": {"kind": "instant"}, "range_ft": None, "source": DURABLE_ID if DURABLE_ID in owned else COLD_IRON_ID,
             "riders": []}
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.granted.guardian_release_delay", owner_id=info["actor_id"],
        display_name="Release a delayed effect now (Durable: it applies at once; no action)", economy=EconomyKind.NONE,
        resolution_kind="TYPED", target_kind="SELF", parameters={"typed": typed, "expected_damage": 0, "target_requires_condition": DELAY})]


@hook("ai_candidate_allowed")
def ai_keeps_delays(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The built-in AI lets a delayed effect run its course; releasing early is a player's choice."""
    return False if str(getattr(action, "source_definition_id", "")).endswith(".granted.guardian_release_delay") else None


# ------------------------------------------------------------------------------------------------ Punishment Returned
@hook("after_hit")
def punishment_returned(ctx: Any, target: Any, kind: str) -> None:
    from dataclasses import replace

    from ..typed_executor import run_effects

    engine, me = ctx.engine, ctx.actor
    owned = row(engine, me, "punishment_returned")
    if (owned is None or kind not in ("weapon", "unarmed") or target is None or not target.active or target.team_id == me.team_id
            or (ctx.typed or {}).get("range_ft") or str(ctx.action.source_definition_id).endswith("#thrown")):
        return
    held = stored(me)
    if held <= 0 or me.resources.get(FOCUS, 0) < 1 or me.turn_flags.get("guardian_round_punishment") == _round_key(engine):
        return
    labels = {"damage": f"{target.display_name} makes a Constitution save or takes {held} extra damage (half on a success)"}
    for delay in delays(me):
        labels[f"transmit:{delay.instance_id}"] = (f"Transmit your delayed {str((delay.data or {}).get('condition') or '').title()} to "
                                                   f"{target.display_name} instead (it makes that effect's own save)")
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "PUNISHMENT_RETURNED", me.entity_id, target.entity_id), me,
                 CHOICE + "punishment_returned", list(labels), labels=labels, preferred=["damage"], allow_decline=True,
                 name="Punishment Returned", target_id=me.entity_id,
                 prompt=f"Punishment Returned (spend Martial Focus, once per round): you hit {target.display_name} while holding {held} "
                        "damage in your Held Harm pool. Return it?")
    if not picked or picked[0] not in labels:
        return
    me.turn_flags["guardian_round_punishment"] = _round_key(engine)
    engine._spend_resource(me, FOCUS, 1, PUNISHMENT_ID)
    one = replace(ctx, target=target, targets=[target], failed_save=None, origin_save=None)
    if picked[0] == "damage":
        dealt = next((e for e in reversed(engine.events[-30:]) if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == me.entity_id
                      and target.entity_id in (e.target_ids or ())), None)
        kind_of = str((dealt.payload or {}).get("damage_type") or "bludgeoning").lower() if dealt is not None else "bludgeoning"
        run_effects(one, [{"type": "save", "ability": "con", "applies_to": "target",
                           "evidence": "Punishment Returned: Constitution save; failed, the held damage again; success, half",
                           "on_fail": [{"type": "damage", "applies_to": "target", "flat": held, "damage_types": [kind_of],
                                        "evidence": f"Punishment Returned: {held} damage, the amount in the Held Harm pool"}],
                           "on_success": [{"type": "half_damage"}]}])
        return
    delay = next((d for d in delays(me) if picked[0] == f"transmit:{d.instance_id}"), None)
    if delay is None:
        return
    built = _delay_context(engine, me, delay, target)
    from .rider_support import remove_instance

    remove_instance(engine, me, delay.instance_id, PUNISHMENT_ID)  # "the delayed effect ends for you"
    if built is None:
        return
    source_ctx, eff = built
    origin = json.loads(str((delay.data or {}).get("origin_save") or "{}"))
    numbers = {**(one.typed.get("numbers") or {})}
    if origin.get("dc"):
        numbers["save_dc"] = int(origin["dc"])  # "using its original DC where available or your Cultivation Save DC otherwise"
    sender = replace(one, typed={**one.typed, "numbers": numbers})
    run_effects(sender, [{"type": "save", "ability": str(origin.get("ability") or "con").lower(), "applies_to": "target",
                          "evidence": "Punishment Returned: the transmitted effect's own saving throw",
                          "on_fail": [{**eff, "applies_to": "target"}], "on_success": []}])


# ------------------------------------------------------------------------------------------------ Court of the Unbroken Gate
def _courts(engine: Any) -> list[Any]:
    return [g for g in _guardians(engine) if g.active and court_active(engine, g)]


def _in_court(engine: Any, guardian: Any, creature: Any, feet: int = 30) -> bool:
    return creature.active and engine._distance_actor_to_actor(guardian, creature) <= feet


@hook("forced_movement_reduction")
def court_holds_ground(ctx: Any, subject: Any) -> int | None:
    best = 0
    for guardian in _courts(ctx.engine):
        if guardian.entity_id == subject.entity_id:
            best = max(best, 20)  # "Reduce forced movement affecting you by 20 feet"
        elif guardian.team_id == subject.team_id and _in_court(ctx.engine, guardian, subject):
            best = max(best, 10)  # allies inside: "Reduce forced movement affecting them by 10 feet"
    return best or None


@hook("ac")
def court_ac(engine: Any, target: Any) -> int:
    return 1 if any(g.entity_id != target.entity_id and g.team_id == target.team_id and _in_court(engine, g, target)
                    for g in _courts(engine)) else 0


@hook("cover")
def court_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    return 2 if any(g.entity_id != target.entity_id and g.team_id == target.team_id and _in_court(engine, g, target, 10)
                    for g in _courts(engine)) else None


@hook("save")
def court_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    named = {str(name).lower() for name in named or ()}
    for guardian in _courts(ctx.engine):
        if guardian.entity_id == subject.entity_id and named & COURT_RESISTS:
            return {"bonus": 0, "modes": ["ADVANTAGE"]}
        if guardian.entity_id != subject.entity_id and guardian.team_id == subject.team_id and "frightened" in named \
                and _in_court(ctx.engine, guardian, subject):
            return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("escape_mode")
def court_escapes(engine: Any, escaper: Any, grips: Any) -> str | None:
    names = {str(getattr(grip, "condition_id", "")).rsplit(".", 1)[-1] for grip in (grips or ())}
    return "ADVANTAGE" if court_active(engine, escaper) and core_row(engine, escaper) is not None and names & COURT_RESISTS else None


@hook("zones", present=lambda engine: bool(_courts(engine)))
def court_ground(engine: Any) -> list[Any] | None:
    """Enemies inside the Court "treat spaces adjacent to you as difficult terrain" -- an aura worked out from the fight."""
    from .. import zones
    from ..gate2_runtime_models import Position, ZoneState

    out = []
    for guardian in _courts(engine):
        own = set(engine._actor_cells(guardian))
        cells = sorted({(x + dx, y + dy) for x, y in own for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - own)
        out.append(ZoneState(
            zone_id=f"zone:aura:{guardian.entity_id}:{COURT_ID}", source_definition_id=COURT_ID, owner_id=guardian.entity_id,
            center=guardian.position, radius_cells=1, affected_cells=tuple(Position(x=x, y=y) for x, y in cells if engine.grid.in_bounds((x, y))),
            concentration_link=False, duration_rounds=None, created_round=0,
            trigger_profile={"kind": zones.KIND, "name": "Court of the Unbroken Gate: difficult ground beside the Guardian for its enemies",
                             "terrain": [], "difficult": "hostile", "obscured": None, "color": zones.terrain_rules().get("default_color"),
                             "follows_owner": True, "shape": "emanation", "size_ft": 5, "triggers": [], "move_through": None, "talents": [],
                             "inside": [], "aura": True, "visual": {"material": "aura"}, "numbers": {}}))
    return out or None


# ------------------------------------------------------------------------------------------------ prompt text
_DECISIONS = {
    CHOICE + "interpose": {
        "name": "Interpose",
        "summary": "Move up to 10 feet (20 with Bodyguard) into a space next to the ally, without opportunity attacks. If the attacker can "
                   "legally attack you there, its attack targets you instead of the ally.",
        "rules": "Core Guardian Rules, Interpose: Reaction. Trigger: one ally within 10 feet is targeted by an attack roll. Move up to 10 feet "
                 "into one legal unoccupied space adjacent to the ally. This movement does not provoke opportunity attacks. If you are a legal "
                 "target for the triggering attack, become its target instead.",
        "limits": "Not against area or saving-throw effects, or an attacker you cannot see. Court of the Unbroken Gate: once per round without "
                  "your Reaction."},
    CHOICE + "held_harm": {
        "name": "Held Harm",
        "summary": "Damage you hold back is not taken now. At the end of your turn you take all of it at once, ignoring Resistance and damage "
                   "reduction (Temporary HP still absorbs it). Healing beyond your maximum HP lowers it.",
        "rules": "Core Guardian Rules, Held Harm: a pool of 3 x your Cultivation Level. After Resistance, Immunity and reductions, you may "
                 "redirect any amount of the remaining damage into the pool, up to its remaining capacity.",
        "cost": "None", "limits": "Up to the room left in the pool."},
    CHOICE + "guardian_delay": {
        "name": "Delay a condition",
        "summary": "The condition does not apply now. It applies at the end of your next turn, lasting as it says from then; the reserved "
                   "Held Harm space is freed when it does.",
        "cost": "Reserved Held Harm space (no action)"},
    CHOICE + "punishment_returned": {
        "name": "Punishment Returned",
        "summary": "The creature you hit makes a Constitution save: on a failure it takes extra damage equal to the damage held in your "
                   "Held Harm pool (half on a success), of the attack's type; the pool is not emptied. Or send it one of your delayed "
                   "effects: it makes that effect's own save.",
        "cost": "Martial Focus", "limits": "Once per round."},
}


@hook("decision_text")
def guardian_decision_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    choice = str(context.get("reaction_source_id") or "")
    found = _DECISIONS.get(choice)
    if found is None:
        return None
    text = dict(found)
    if choice == CHOICE + "interpose":
        actor = engine.state.actors.get(context.get("reactor_id"))
        free = actor is not None and _free_court_use(engine, actor)
        text["cost"] = "None (Court of the Unbroken Gate, once per round)" if free else "Your Reaction"
    return text
