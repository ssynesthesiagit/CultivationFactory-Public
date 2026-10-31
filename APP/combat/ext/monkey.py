"""Monkey Style's Monkey Chain (rider lane 10, 2026-09-29): the caper, Monkey Links, the base and talent Finishes, and the Monkey Style
talents that answer a miss. Rules text: the owner's Sphere Compendium, "Monkey Style" ("THE MONKEY CHAIN"; the talents in
authority/typed_mechanics/rules_text.json).

  Creating a link  "While Capering Footwork or another Monkey Style Opener is active, you may create one Monkey Link per turn when you do one
                   of the following: move at least 10 feet before making an attack or forcing a save; change elevation by at least 5 feet;
                   climb, hang, swing, or balance on terrain; move through a hostile creature's space or the space of a larger creature;
                   interact with a prop ...; cause a creature to miss you with an opportunity attack; succeed on a Monkey Style check, save
                   contest, or Trick effect. You can hold only one Monkey Link at a time unless a talent says otherwise. A Monkey Link lasts
                   until the end of your current turn."
                   -- the table creates one when you attack or force a save after moving 10 feet this turn, when you pass through a
                   larger creature's space under the caper, and when a creature misses you with an opportunity attack; elevation, climbing
                   and props are the GM's (a player may say so: see below).
  Spending a link  "Once per turn, when you hit with a Monkey Style attack, force a creature to fail a Monkey Style saving throw, or complete a
                   Monkey Style movement sequence, you may spend your Monkey Link on one of the following base finishes. SLIP: Move 5 feet
                   without provoking opportunity attacks ... LAUGH: One creature you affected ... cannot take Reactions until the start of
                   its next turn. SNATCH: ... one accessible unattended object ... TAP: Deal extra Bludgeoning damage equal to your
                   Proficiency Bonus with one staff, improvised weapon, Unarmed Strike, or Monkey Style Special Attack that hits this turn."
                   "Unless a talent says otherwise: you can spend only one Monkey Link per turn; you cannot use the same Finish more than
                   once per turn."
                   -- after a hit with a staff, an Unarmed Strike or an improvised weapon while the caper is on (Laughing Staff and
                   Borrowed Weapon), the holder may spend the link on Tap, Laugh or Slip (asked; the AI taps); Snatch is the GM's. A Monkey
                   Style special attack spends it on its own printed Finish instead (``monkey_finish``: Laughing Trip, Vaulting Strike,
                   Golden Hoop Staff, Stone-Skipping Strike's ricochet, Staff of the Laughing Sage's Staff Finish).

Talents read here: Capering Footwork (the caper itself: ``monkey_caper``, until the end of your turn; ignoring difficult terrain is the
typed rule for that condition in combat/rules/typed_conditions.json, and passing through a larger creature's space is ``passage``),
Mischievous Feint (a link bound to the baited target on a failed save), Drunken Monkey Stance (a 5-foot step when a melee attack misses
you; once a round a link when a creature misses you; ends when you are Incapacitated or Restrained), Court of the Laughing Sage (two links
held; once a turn a 10-foot step after an enemy misses you; the first attack each enemy makes at you on its turn: a Wisdom save or
Disadvantage; movement through hostile spaces), Great Sage Equal to Heaven (two links per turn made and spent; Uncatchable once a turn
after a miss or a successful Dexterity save -- a 15-foot step, a melee attack or a link; Laugh at Heaven once per transformation;
movement through hostile spaces at no extra cost), Staff of the Laughing Sage (its four Staff Finishes), Laughing Trip (Disadvantage on
its save after a climb-through), High Branch Guard (its step makes a link under the caper), Impossible Ape Reversal, Laughing Theft of
Timing and Monkey Catches the Moon (their printed "choose" lists, ``reversal``), Borrowed Treasure and Hundred-Handed Trickster (the
steal contest, ``borrow``). A "Monkey Link (GM)" free button makes a link the table cannot see the cause of (climbing, a prop), within the
same once-per-turn limit.

The printed "choose" lists also say what each option really is. ``monkey_melee`` is an option's "make one melee weapon attack" and uses the
fighter's own readied weapon; ``monkey_improvised`` is an option's "make one improvised-weapon attack" and uses the fighter's own
improvised-weapon attack (thrown when the printed range asks for it), with the recipient the printed words choose: the named creature
when the option names one, otherwise a creature the owner picks from those in range. "One" is one attack: both helpers narrow the copied
attack sequence to a single attack (``_one_attack_only``), so a fighter whose own Attack action swings more than once (Extra Attack, which
combat's compiler bakes into that action's attack ``count``) is not handed extra attacks by a printed option.

Laughing Theft of Timing reserves the roll it is about to shape, not "a roll": the creature, the round, the slot, its own 1d6 and the
number of events the fight had recorded when it rolled. It is settled on that attempt's own recorded roll -- an attack from the documented
``attack_result`` seam, a saving throw from ``after_save_resolved`` -- so the printed "if the triggering roll fails because of this
penalty" is answered for the roll the 1d6 actually broke, and a hit owes nothing and clears the reservation. The printed scope "a creature
you affected with a Monkey Style Trick, Finish, or feint this turn" reads what this fighter did: an event it caused on that creature, a
Finish it spent against it, or a saving throw it forced (the ``save`` seam is the only place that knows who forced one).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

LINK = "condition:typed.monkey_link"
CAPER = "condition:typed.monkey_caper"
DRUNKEN = "TAL_MONKEY_STYLE_DRUNKEN_MONKEY_STANCE"
COURT = "TAL_MONKEY_STYLE_COURT_OF_THE_LAUGHING_SAGE"
SAGE = "TAL_MONKEY_STYLE_GREAT_SAGE_EQUAL_TO_HEAVEN"
STAFF_SAGE = "TAL_MONKEY_STYLE_STAFF_OF_THE_LAUGHING_SAGE"
GUARD = "TAL_MONKEY_STYLE_HIGH_BRANCH_GUARD"
TRIP = "TAL_MONKEY_STYLE_LAUGHING_TRIP"
REVERSAL = "TAL_MONKEY_STYLE_IMPOSSIBLE_APE_REVERSAL"
THEFT = "TAL_MONKEY_STYLE_LAUGHING_THEFT_OF_TIMING"
MOON = "TAL_MONKEY_STYLE_MONKEY_CATCHES_THE_MOON"
TREASURE = "TAL_MONKEY_STYLE_BORROWED_TREASURE"
TRICKSTER = "TAL_MONKEY_STYLE_HUNDRED_HANDED_TRICKSTER"
SPHERE = "tianxia.sphere.monkey_style"
_STAFFISH = ("staff", "quarterstaff", "gun", "bo ", "spear", "polearm", "qiang", "pole")
# A Fighter's turn_flags prefix: the id of a creature this fighter put a Monkey Style Finish on earlier this turn
# (written by spend()). The value is the actual round/slot, not an owner-turn boolean: "this turn" ends when ANY
# creature's turn ends. Old booleans are not proof of a current-turn effect; the event scan can still establish one.
FINISHED_ON = "monkey_finish_on:"
# A Fighter's turn_flags prefix, on the same clock: the ids of the creatures this fighter forced to make a saving throw with
# a Monkey Style Trick, Finish or feint (written by trick_or_finish_forced_save, because a SAVE_ROLLED event names the creature
# that made the save and the ability that asked, never the fighter that used it).
AFFECTED_ON = "monkey_trick_save_on:"


def _turn_stamp(engine: Any) -> str:
    """Primitive, reload-safe identity of the current creature's turn."""
    return f"{engine.state.round_number}:{engine.state.current_slot_index}"


def _active(actor: Any, feature: str) -> bool:
    return any(feature in str(c.source_definition_id) for c in actor.conditions.values()) or \
        any(feature in str(m.source_definition_id) for m in actor.modifiers.values())


def _caper(actor: Any) -> bool:
    return any(c.condition_id == CAPER for c in actor.conditions.values())


def _court(engine: Any, actor: Any) -> Any | None:
    from .. import zones

    return next((zone for zone in zones.typed_zones(engine) if zone.active and zone.owner_id == actor.entity_id and COURT in str(zone.source_definition_id)), None)


def _sage(actor: Any) -> bool:
    return _active(actor, SAGE)


def hold_cap(engine: Any, actor: Any) -> int:
    """"You can hold only one Monkey Link at a time unless a talent says otherwise" (the Court: up to two)."""
    return 2 if _court(engine, actor) is not None else 1


def per_turn(actor: Any) -> int:
    """Great Sage: "you may create up to two Monkey Links per turn and spend up to two Monkey Links per turn"."""
    return 2 if _sage(actor) else 1


def links(actor: Any) -> list[tuple[str, Any]]:
    return [(iid, c) for iid, c in actor.conditions.items() if c.condition_id == LINK]


def _count(actor: Any, key: str) -> int:
    return int(actor.turn_flags.get(key) or 0)


def create(engine: Any, actor: Any, source: str, why: str, *, until_next: bool = False, only_target: str | None = None,
           counted: bool = True) -> bool:
    """One more Monkey Link, if the actor may hold it (and, for the base rule, has not made its one this turn)."""
    from .effect_durations import token

    if not actor.active or len(links(actor)) >= hold_cap(engine, actor):
        return False
    if counted and _count(actor, "monkey_links_made") >= per_turn(actor):
        return False
    if counted:
        actor.turn_flags["monkey_links_made"] = _count(actor, "monkey_links_made") + 1
    turn = int(actor.turns_started) + (1 if until_next or engine.state.current_actor_id != actor.entity_id else 0)
    engine._apply_condition(actor, LINK, source, actor.entity_id, expires_on=token("end", actor.entity_id, turn),
                            data={"label": "Monkey Link" + (" (until the end of your next turn)" if until_next else ""),
                                  **({"only_target": only_target} if only_target else {})})
    note(engine, source, actor, f"{actor.display_name} creates a Monkey Link ({why}).")
    return True


def _can_create(engine: Any, actor: Any) -> bool:
    """Whether offering Link creation can change the table state right now."""
    return (actor.active and len(links(actor)) < hold_cap(engine, actor)
            and _count(actor, "monkey_links_made") < per_turn(actor))


def can_spend(engine: Any, actor: Any, target: Any = None) -> bool:
    if _count(actor, "monkey_links_spent") >= per_turn(actor):
        return False
    return any(not (c.data or {}).get("only_target") or target is None or (c.data or {}).get("only_target") == target.entity_id for _i, c in links(actor))


def spend(engine: Any, actor: Any, source: str, target: Any = None, finish: str = "") -> bool:
    if not can_spend(engine, actor, target):
        return False
    held = sorted(links(actor), key=lambda row: (not (row[1].data or {}).get("only_target"), row[1].applied_sequence))
    iid, condition = next(((i, c) for i, c in held if not (c.data or {}).get("only_target") or target is None
                           or (c.data or {}).get("only_target") == target.entity_id))
    actor.conditions.pop(iid, None)
    engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,), payload={"condition_id": LINK, "instance_id": iid})
    actor.turn_flags["monkey_links_spent"] = _count(actor, "monkey_links_spent") + 1
    if finish:
        actor.turn_flags[f"monkey_finish_used:{finish}"] = True
        if target is not None and target.active:
            # Every base Finish, Staff Finish and special attack's own Finish spends a link here against one creature:
            # this is the printed "a creature you affected with a Monkey Style ... Finish" record Laughing Theft of
            # Timing reads (their own events carry the weapon's source, which says nothing about a Finish).
            actor.turn_flags[FINISHED_ON + target.entity_id] = _turn_stamp(engine)
    note(engine, source, actor, f"{actor.display_name} spends a Monkey Link" + (f" on {finish}" if finish else "") + ".")
    return True


# ------------------------------------------------------------------------------------------ moving through creatures
def _larger(engine: Any, mover: Any, occupant: Any) -> bool:
    """The printed comparison "creatures larger than you", read from the recorded footprint both sides actually occupy."""
    from .. import dynamic_size

    rank = {name: number for number, name in enumerate(dynamic_size.CATEGORIES)}
    return rank.get(dynamic_size.current_category(engine, occupant), 0) > rank.get(dynamic_size.current_category(engine, mover), 0)


@hook("pass_through")
def passage(engine: Any, mover: Any, occupant: Any) -> str | None:
    """Capering Footwork: "you may move through the spaces of creatures larger than you, treating hostile spaces as difficult
    terrain". Court of the Laughing Sage: the same while its Domain stands. Great Sage Equal to Heaven: "ability to move through
    hostile spaces without spending extra movement". None for anyone who does not own the talent, so ordinary movement is unchanged.
    The caper also ignores difficult terrain while it lasts (the ``ignore_difficult`` rule on its own condition), which is what makes
    its "difficult terrain" pass-through cost nothing, exactly as the two printed lines read together."""
    if not mover.active or occupant is None or not getattr(occupant, "active", True):
        return None
    hostile = occupant.team_id != mover.team_id
    if hostile and _sage(mover):
        return "free"
    if _caper(mover) and _larger(engine, mover, occupant):
        return "difficult"
    if hostile and _court(engine, mover) is not None:
        return "difficult"
    return None


@hook("pass_through_entered")
def passage_makes_a_link(engine: Any, mover: Any, occupant: Any, intent: Any) -> None:
    """Resolve passage Link grants once: Capering Footwork grants its Link, while transformed hostile passage asks the
    printed optional question. Combining both conditions still produces at most one Link decision."""
    if mover is None or occupant is None or not mover.active or not occupant.active:
        return
    hostile = mover.team_id != occupant.team_id
    caper_grant = _caper(mover) and (hostile or _larger(engine, mover, occupant))
    form_grant = hostile and _transformed(mover)
    if form_grant:
        if not _can_create(engine, mover):
            return
        from .rider_choices import pick
        selected = pick(engine, mover, "monkey_beast_form_link", "Seventy-Two Earthly Transformations",
                        ["create_link"], labels={"create_link": "Create a Monkey Link for your other Monkey Style talents"},
                        subject=mover, trigger=f"you moved through {occupant.display_name}'s space while transformed",
                        preferred=["create_link"], optional=True, intent=intent,
                        prompt=(f"Seventy-Two Earthly Transformations: You moved through {occupant.display_name}'s "
                                "space while transformed. Would you like to create a Monkey Link? It lasts until "
                                "the end of your turn and can be spent on your Monkey Style talents."))
        if selected:
            create(engine, mover, f"passive:{TRANSFORM}", "its beast form slipped through a hostile space")
        return
    if caper_grant:
        create(engine, mover, f"passive:{SPHERE}", f"it passed through {occupant.display_name}'s space")


def _moved_this_turn(engine: Any, actor: Any) -> int:
    total = 0
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED" and event.actor_id == actor.entity_id:
            break
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id:
            total += int((event.payload or {}).get("cost_ft") or 0)
    return total


# ------------------------------------------------------------------------------------------------------------------ the caper
@effect("monkey_caper")
def caper(ctx: Any, eff: dict[str, Any]) -> None:
    """Capering Footwork (or another Opener) is active until the end of your turn: links can be made and spent."""
    ctx.engine._remove_condition(ctx.actor, CAPER, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CAPER, ctx.source, ctx.actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"label": "Capering Footwork: Monkey Links can be made and spent this turn"})


@effect("monkey_link_gm")
def gm_link(ctx: Any, eff: dict[str, Any]) -> None:
    """A link the table cannot see the cause of (a climb, a swing, a prop, a hostile creature's space): the player says so."""
    if _caper(ctx.actor):
        create(ctx.engine, ctx.actor, ctx.source, "the caper")


@effect("monkey_bait")
def bait(ctx: Any, eff: dict[str, Any]) -> None:
    """Mischievous Feint: "choose one creature within range that can see or hear you ... Wisdom saving throw. Failed Save: You create a Monkey
    Link. The link can be spent only against that target before the end of your turn." The owner chooses the recipient."""
    from ..typed_executor import Context, run_effects

    engine, actor = ctx.engine, ctx.actor
    near = sorted([other for other in engine.state.actors.values() if other.active and other.team_id != actor.team_id
                   and engine.grid.distance_ft(other.position, actor.position) <= int(eff.get("range_ft") or 30)],
                  key=lambda other: (engine.grid.distance_ft(other.position, actor.position), other.entity_id))
    if not near:
        return
    from .rider_choices import pick
    selected = pick(engine, actor, "monkey_bait", "Mischievous Feint", [o.entity_id for o in near],
                    labels={o.entity_id: f"Bait {o.display_name}" for o in near}, subject=actor,
                    trigger=ctx.action.display_name, preferred=[near[0].entity_id], optional=False, intent=ctx.intent)
    target = engine.state.actors[selected[0]]
    actor.turn_flags[FINISHED_ON + target.entity_id] = _turn_stamp(engine)  # the printed feint, on this creature's turn
    before = len(engine.events)
    run_effects(Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}), [{"type": "save", "ability": "wis", "on_fail": [], "on_success": []}])
    rolled = next((e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED"), None)
    if rolled is not None and not (rolled.payload or {}).get("success"):
        create(engine, actor, ctx.source, f"Mischievous Feint baited {target.display_name}", only_target=target.entity_id)


def _qualifying_move(ctx: Any) -> None:
    actor = ctx.actor
    if _caper(actor) and _moved_this_turn(ctx.engine, actor) >= 10:
        create(ctx.engine, actor, ctx.source, "it moved 10 feet before striking")


@hook("attack_mode")
def link_on_attack(ctx: Any, target: Any) -> None:
    _qualifying_move(ctx)
    return None


@hook("save")
def link_on_forced_save(ctx: Any, subject: Any, ability: str, named: Any) -> None:
    if subject is not None and subject.team_id != ctx.actor.team_id:
        _qualifying_move(ctx)
    return None


def climbed_through(engine: Any, mover: Any, other: Any) -> bool:
    """Whether ``mover`` changed elevation or walked through ``other``'s space earlier this turn, read from the movement the
    fight has already recorded (Laughing Trip's printed qualification, High Branch Guard's printed elevation)."""
    cells = {(int(x), int(y)) for x, y in engine._actor_cells(other)}
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED" and event.actor_id == mover.entity_id:
            break
        if event.event_type != "MOVEMENT_COMMITTED" or event.actor_id != mover.entity_id:
            continue
        path = [point for point in ((event.payload or {}).get("path") or []) if isinstance(point, dict)]
        if any((int(point.get("x") or 0), int(point.get("y") or 0)) in cells for point in path):
            return True
        if len({int(point.get("z") or 0) for point in path}) > 1:
            return True
    return False


@hook("save")
def trip_disadvantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Laughing Trip: "If the attack was made after changing elevation or moving through the target's space, the target has
    Disadvantage on this saving throw." Nothing for any other save, and nothing when the printed qualification is not met."""
    if TRIP not in str(ctx.source) or subject is None or str(ability).upper() != "DEX":
        return None
    return {"modes": ["DISADVANTAGE"]} if climbed_through(ctx.engine, ctx.actor, subject) else None


# ------------------------------------------------------------------------------------------------------------------ finishes
def _monkey_attack(ctx: Any) -> bool:
    """A staff, an Unarmed Strike or an improvised weapon (Laughing Staff and Borrowed Weapon), or a Monkey Style special attack."""
    source = str(ctx.source)
    if "MONKEY_STYLE" in source or ".monkey_style." in source:
        return True
    typed = ctx.typed or {}
    if any(isinstance(e, dict) and e.get("attack_kind") == "unarmed" for e in typed.get("effects") or []) or "unarmed" in source or "improvised" in source:
        return True
    name = str(getattr(ctx.action, "display_name", "")).lower()
    return typed.get("weapon") is not None and any(word in name for word in _STAFFISH)


def _has_own_finish(ctx: Any) -> bool:
    return "monkey_finish" in str((ctx.typed or {}).get("effects"))


@hook("after_hit")
def base_finish(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or not _caper(actor) or not _monkey_attack(ctx) or _has_own_finish(ctx) or not can_spend(engine, actor, target):
        return
    _choose_and_run(ctx, target)


def _base(ctx: Any, target: Any, which: str) -> None:
    from ..typed_executor import Context, _deal, run_effects

    engine, actor = ctx.engine, ctx.actor
    if which == "tap":
        _deal(ctx, target, int(actor.proficiency_bonus or 2), "BLUDGEONING")
    elif which == "laugh":
        run_effects(Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}),
                    [{"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn"}])
    elif which == "slip":
        _step(ctx, actor, target, 5, "Slip Finish")


def _step_prompt(why: str, ctx: Any, mover: Any, feet: int, away_from: Any) -> str:
    """The question a printed "move up to N feet" asks: which ability, whose action, which creature, and how far. Staying
    put is one of the offered cells, so the question also appears when the fighter may not step."""
    action = str(getattr(ctx.action, "display_name", "") or "")
    lead = f"{why}: " if why and why not in action else ""
    return f"{lead}{action or why} by {ctx.actor.display_name} affecting {mover.display_name}" \
           + (f" (other creature: {away_from.display_name})" if away_from is not None else "") \
           + f"; step up to {feet} feet?"


def _step(ctx: Any, mover: Any, away_from: Any, feet: int, why: str, *, near: set[tuple[int, int]] | None = None,
          provokes: bool = False, ignore_oa_from: tuple[str, ...] = ()) -> str | None:
    """One printed movement grant, asked as free cells and resolved through shared native paths/reactions.
    By default every creature is exempt; a selective clause passes ``provokes=True`` and the exempt creature ids.
    Staying put is one of
    those cells ("move up to" permits zero feet), so a fighter who may not step still answers this question. Returns the
    chosen cell option, or None when the question was not answered at all (declined, or no cells offered).
    ``near`` is a set of (x, y) cells the printed words need the fighter to end beside: it only steers the AI's own
    default choice, never the options offered."""
    from .needle import CHOICE, ask, checkpoint_id, cell_id as _cell_id, cell_options as _cell_options
    from . import granted_moves

    engine = ctx.engine
    # This menu remains a same-level step. Preserve the shared route's movement
    # mode and cost so terrain, occupancy and other creatures' reactions are native.
    routes = {cell: (path, cost) for cell, path, cost in granted_moves.destinations(
        engine, mover, feet, lambda cell: cell.z == mover.position.z)}
    cells = {cell: cost for cell, (_, cost) in routes.items()}
    if not cells:
        return None
    options, labels = _cell_options(engine, mover, cells)
    if near:
        away = min(cells, key=lambda cell: (min(engine.grid.distance_cells(cell, want) for want in near), cell.y, cell.x))
    else:
        away = max(cells, key=lambda cell: (engine.grid.distance_ft(away_from.position, cell) if away_from is not None else 0, -cell.y, -cell.x))
    picked = ask(engine, getattr(ctx, "intent", None), checkpoint_id(engine, "MONKEY_STEP", mover.entity_id), mover, CHOICE + "monkey_step", options,
                 labels=labels, preferred=[_cell_id(away)], allow_decline=True,
                 prompt=_step_prompt(why, ctx, mover, feet, away_from))
    if picked and picked[0] != _cell_id(mover.position):
        destination = next(cell for cell in cells if _cell_id(cell) == picked[0])
        start = mover.position
        granted_moves.commit(engine, mover, routes[destination][0], getattr(ctx, "source", "system:monkey"),
                             budget_ft=feet, provokes=provokes, ignore_oa_from=ignore_oa_from,
                             intent=getattr(ctx, "intent", None))
        if mover.position != start:
            note(engine, getattr(ctx, "source", "system:monkey"), mover, f"{why}: {mover.display_name} slips away.")
    return picked[0] if picked else None


@effect("monkey_finish")
def talent_finish(ctx: Any, eff: dict[str, Any]) -> None:
    """A Monkey Style special attack's own Finish: "If you have a Monkey Link, you may spend it to ..." -- the nested effects run only when a
    link is spent here (the AI spends it)."""
    from ..typed_executor import run_effects

    target = ctx.target
    if target is None or not target.active or not can_spend(ctx.engine, ctx.actor, target):
        return
    if eff.get("requires_active") and not _active(ctx.actor, str(eff["requires_active"])):
        return  # Golden Hoop Staff: only while the staff is empowered
    from .rider_choices import pick
    if not pick(ctx.engine, ctx.actor, "monkey_talent_finish", ctx.action.display_name + " Finish", ["spend"],
                labels={"spend": "Spend your Monkey Link"}, subject=target,
                trigger=f"{ctx.action.display_name} hits {target.display_name}", intent=ctx.intent):
        return
    if not spend(ctx.engine, ctx.actor, ctx.source, target, str(eff.get("finish") or "")):
        return
    run_effects(ctx, list(eff.get("effects") or []))


@effect("monkey_link_reaction")
def link_reaction(ctx: Any, eff: dict[str, Any]) -> None:
    """A Reversal's "create a Monkey Link that lasts until the end of your next turn" (Snatch and Scatter)."""
    create(ctx.engine, ctx.actor, ctx.source, "a Reversal", until_next=True, counted=False)


@effect("monkey_ricochet")
def ricochet(ctx: Any, eff: dict[str, Any]) -> None:
    """Stone-Skipping Strike: "ricochet the object toward another creature within 10 feet of the target. Make a second attack roll. Second Hit:
    Deal 1d6 + Monkey Style key ability modifier Bludgeoning damage" (2d6 at CL 5, 3d6 at CL 11, 4d6 at CL 17)."""
    from ..typed_executor import Context, run_effects

    engine, actor, first = ctx.engine, ctx.actor, ctx.target
    if first is None:
        return
    others = sorted([other for other in engine.state.actors.values() if other.active and other.team_id != actor.team_id and other is not first
                     and engine.grid.distance_ft(other.position, first.position) <= 10], key=lambda other: (other.current_hp, other.entity_id))
    if not others:
        return
    second = others[0]
    run_effects(Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [second], second, {}),
                [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
                  "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 6}, "formula": "key_ability_modifier",
                              "damage_types": ["bludgeoning"], "dice_by_cl": [[1, 4, 1, 6], [5, 10, 2, 6], [11, 16, 3, 6], [17, 20, 4, 6]]}]}])


# ------------------------------------------------------------------------------------------------------------------ misses
@hook("after_miss")
def answers_a_miss(ctx: Any, target: Any) -> None:
    """A creature missed ``target`` (a Monkey Style fighter): the opportunity-attack link, Drunken Monkey Stance, the Court's step, Uncatchable."""
    engine, attacker = ctx.engine, ctx.actor
    if target is None or not target.active or attacker.team_id == target.team_id:
        return
    melee = not (ctx.typed or {}).get("range_ft")
    opportunity = bool((ctx.typed or {}).get("opportunity_of")) or "opportunity" in str(ctx.source)
    if opportunity and _caper(target):
        create(engine, target, f"passive:{SPHERE}", f"{attacker.display_name}'s opportunity attack missed")
    if _active(target, DRUNKEN):
        key = f"monkey_round_drunken_link:{engine.state.round_number}"
        if not target.turn_flags.get(key):
            target.turn_flags[key] = True
            create(engine, target, f"passive:{DRUNKEN}", "Drunken Monkey Stance: a miss", until_next=True, counted=False)
        if melee:
            _step(ctx, target, attacker, 5, "Drunken Monkey Stance")
    court = _court(engine, target)
    if court is not None and not target.turn_flags.get("monkey_court_step"):
        target.turn_flags["monkey_court_step"] = True
        _step(ctx, target, attacker, 10, "Court of the Laughing Sage")
    _uncatchable(ctx, target, attacker)


def _one_attack_only(typed: dict[str, Any]) -> dict[str, Any]:
    """The copied attack sequence of a printed "make one ... attack", narrowed to the single attack the text asks for.

    Combat's compiler bakes a fighter's Extra Attack into the attack action's own rows (``count``, and a
    ``count_by_cl`` scale the executor applies at :1309-1313), so copying that action wholesale would hand the
    owner every extra swing and every extra damage packet a printed option never promised. Non-attack rows
    (the thrown improvised weapon's own follow-ups) are left exactly as compiled.
    """
    effects = []
    for effect in typed.get("effects") or []:
        if isinstance(effect, dict) and effect.get("type") == "attack":
            limited = {**effect, "count": 1}
            limited.pop("count_by_cl", None)
            effect = limited
        effects.append(effect)
    return {**typed, "effects": effects}


def melee_attack(ctx: Any, attacker: Any, target: Any, why: str) -> bool:
    """One "make one melee weapon attack" from a printed option, run as the attacker's own real weapon action inside the
    caller's accepted transaction (the shared shape combat/ext/needle.py uses for a riposte). Used by Great Sage Equal to
    Heaven's Uncatchable, Impossible Ape Reversal and Laughing Theft of Timing; it refuses when the target is out of reach."""
    import copy

    from . import needle
    from ..typed_executor import Context, run_effects

    if attacker is None or target is None or not attacker.active or attacker.team_id == target.team_id:
        return False
    action = needle.melee_weapon_action(ctx.engine, attacker)
    if action is None:
        return False
    if not _legal_weapon_target(ctx.engine, attacker, target, action):
        note(ctx.engine, ctx.source, attacker, f"{why}: {target.display_name} is out of reach, so there is no attack.")
        return False
    typed = _one_attack_only(copy.deepcopy((action.parameters or {}).get("typed") or {}))
    note(ctx.engine, ctx.source, attacker, f"{why}: {attacker.display_name} attacks {target.display_name}.")
    from ..target_knowledge import attack_aim
    with attack_aim(ctx.engine, attacker, target, action):
        run_effects(Context(ctx.engine, attacker, action, getattr(ctx, "intent", None), typed, [target], target, {}), typed.get("effects") or [])
    return True


def _improvised_action(engine: Any, actor: Any, *, thrown: bool) -> Any | None:
    """The fighter's own improvised-weapon attack action (combat's compiled "Improvised weapon attack"/"Improvised weapon
    thrown"), or None when the fighter has no improvised-weapon action compiled at all."""
    found = []
    for action in engine.action_catalog.values():
        if action.owner_id != actor.entity_id or not isinstance(action.parameters, dict):
            continue
        typed = action.parameters.get("typed") or {}
        if str(typed.get("source") or "") != "improvised_weapon":
            continue
        if bool(typed.get("long_range_ft") or typed.get("range_ft")) == thrown:
            found.append(action)
    return min(found, key=lambda action: len(action.display_name)) if found else None


def improvised_sides(ctx: Any) -> int:
    """The printed damage die of a Monkey Style improvised weapon: the base rule's 1d6 "unless their normal damage would
    be higher", Improvised Master's 1d8 (1d10 at CL 11), and the "at least 1dN" of an active Great Sage Equal to Heaven
    (1d12) or Hundred-Handed Trickster (1d8)."""
    master = _row(ctx.engine, ctx.actor, "improvised_master")
    level = int(((ctx.typed or {}).get("numbers") or {}).get("cl") or 1)
    sides = (10 if level >= 11 else 8) if master else 6
    if _active(ctx.actor, SAGE):
        sides = max(sides, 12)
    if _active(ctx.actor, TRICKSTER):
        sides = max(sides, 8)
    return sides


def improvised_attack(ctx: Any, target: Any, why: str, *, thrown: bool = False) -> bool:
    """One printed "make one improvised-weapon attack", run as the fighter's own improvised-weapon attack inside the
    caller's accepted transaction. ``thrown`` uses the thrown action (the printings that name a range from you rather than
    reach, "using the projectile or a nearby object"). The damage die is the printed Monkey Style improvised weapon."""
    import copy

    from ..typed_executor import Context, run_effects

    engine, actor = ctx.engine, ctx.actor
    if actor is None or target is None or not actor.active or actor.team_id == target.team_id:
        return False
    action = _improvised_action(engine, actor, thrown=thrown) or _improvised_action(engine, actor, thrown=not thrown)
    if action is None:
        note(engine, ctx.source, actor, f"{why}: you have no improvised weapon to attack with.")
        return False
    if not _legal_weapon_target(engine, actor, target, action):
        note(engine, ctx.source, actor, f"{why}: {target.display_name} is out of range, so there is no attack.")
        return False
    typed = _one_attack_only(copy.deepcopy((action.parameters or {}).get("typed") or {}))
    damage = dict(typed.get("weapon", {}).get("damage") or {})
    damage["count"], damage["sides"] = 1, max(int(damage.get("sides") or 0), improvised_sides(ctx))
    typed["weapon"] = {**(typed.get("weapon") or {}), "damage": damage}
    note(engine, ctx.source, actor, f"{why}: {actor.display_name} attacks {target.display_name} with an improvised weapon.")
    from ..target_knowledge import attack_aim
    with attack_aim(engine, actor, target, action):
        run_effects(Context(engine, actor, action, getattr(ctx, "intent", None), typed, [target], target, {}), typed.get("effects") or [])
    return True


def _legal_weapon_target(engine: Any, actor: Any, target: Any, action: Any) -> bool:
    """Shared attack policy: footprint reach or known aim, and line of effect."""
    from ..targeting import reason, in_range
    from ..target_knowledge import knowledge

    known = knowledge(engine, actor, target, action) if action is not None and target is not None else None
    return bool(action is not None and actor.active and target is not None and known is not None
                and (known.mode == 'LAST_OBSERVED' or target.active)
                and actor.team_id != target.team_id
                and reason(engine, actor, target, action) is None
                and in_range(engine, actor, target, action))


def _weapon_target_label(engine: Any, actor: Any, target: Any, action: Any, weapon: str, *, duplicate=False) -> str:
    """Describe the offered aim without disclosing a concealed creature's position."""
    from ..target_knowledge import knowledge
    from ..targeting import remembered_square_label
    known = knowledge(engine, actor, target, action)
    if known is not None and known.mode == 'LAST_OBSERVED':
        return f'{remembered_square_label(engine, actor, target)} with your {weapon} weapon'
    where = f' at square {target.position.x},{target.position.y}' if duplicate else ''
    if where and target.position.z:
        where += f' on level {target.position.z}'
    return f'Attack {target.display_name}{where} with your {weapon} weapon'


def _uncatchable(ctx: Any, sage: Any, foe: Any) -> None:
    """Great Sage Equal to Heaven, Uncatchable: "Once per turn when an enemy misses you or you succeed on a Dexterity saving throw, choose one:
    move up to 15 feet without provoking opportunity attacks; make one melee weapon attack; create a Monkey Link." All three are the table's."""
    if not _sage(sage) or sage.turn_flags.get("monkey_uncatchable"):
        return
    from .needle import CHOICE, ask, checkpoint_id
    from .needle import melee_weapon_action
    from collections import Counter

    sage.turn_flags["monkey_uncatchable"] = True
    step_id = "Move up to 15 feet without provoking opportunity attacks"
    weapon = melee_weapon_action(ctx.engine, sage)
    recipients = sorted([other for other in ctx.engine.state.actors.values()
                         if _legal_weapon_target(ctx.engine, sage, other, weapon)],
                        key=lambda other: other.entity_id)
    attacks = {f"attack:{other.entity_id}": other for other in recipients}
    names = Counter(other.display_name for other in recipients)
    attack_labels = {}
    for option, other in attacks.items():
        attack_labels[option] = _weapon_target_label(ctx.engine, sage, other, weapon, 'melee',
                                                    duplicate=names[other.display_name] > 1)
    link_id = "Create a Monkey Link (it lasts until the end of your current turn, and you may spend it on a Finish)"
    options = [step_id, *attacks, link_id]
    picked = ask(ctx.engine, getattr(ctx, "intent", None), checkpoint_id(ctx.engine, "UNCATCHABLE", sage.entity_id), sage, CHOICE + "monkey_uncatchable",
                 options, labels={step_id: step_id, link_id: link_id,
                                  **attack_labels},
                 name="Uncatchable",
                 preferred=[link_id], allow_decline=True,
                 prompt=f"Uncatchable: {ctx.action.display_name} affecting {sage.display_name}; choose one")
    if picked[:1] == [step_id]:
        _step(ctx, sage, foe, 15, "Uncatchable")
    elif picked and picked[0] in attacks:
        melee_attack(ctx, sage, attacks[picked[0]], "Uncatchable")
    elif picked[:1] == [link_id]:
        create(ctx.engine, sage, f"passive:{SAGE}", "Uncatchable", until_next=False, counted=False)


@hook("after_save")
def sage_saves(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Great Sage: Uncatchable after a successful Dexterity save; Laugh at Heaven: "Once during the transformation, when you fail a saving throw,
    choose to succeed instead." """
    if subject is None or not _sage(subject):
        return
    if not failed and str(ability).upper().startswith("DEX"):
        _uncatchable(ctx, subject, ctx.actor)
        return
    if failed and not any(c.condition_id == "condition:typed.monkey_laughed" for c in subject.conditions.values()):
        from .needle import CHOICE, ask, checkpoint_id

        picked = ask(ctx.engine, getattr(ctx, "intent", None), checkpoint_id(ctx.engine, "LAUGH_AT_HEAVEN", subject.entity_id), subject,
                     CHOICE + "monkey_laugh_at_heaven", ["succeed", "keep"], labels={"succeed": "Laugh at Heaven: succeed instead", "keep": "Keep the failure"},
                     preferred=["succeed"], prompt="Laugh at Heaven (once per transformation)?")
        if picked[:1] != ["succeed"]:
            return
        ctx.engine.__dict__.setdefault("_typed_roll_outcome", {})
        ctx.engine._typed_roll_outcome[subject.entity_id] = "success"
        ctx.engine._apply_condition(subject, "condition:typed.monkey_laughed", f"passive:{SAGE}", subject.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": "Laugh at Heaven used"})
        note(ctx.engine, f"passive:{SAGE}", subject, f"Laugh at Heaven: {subject.display_name} succeeds instead.")


@hook("before_attack")
def court_first_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """Court of the Laughing Sage: "The first time an enemy attacks you during each of its turns, it makes a Wisdom saving throw. Failed Save:
    The attack has Disadvantage." """
    if defender is None or attacker is None or attacker.team_id == defender.team_id or _court(engine, defender) is None:
        return None
    if engine.state.current_actor_id != attacker.entity_id:
        return None
    key = f"monkey_court_first:{defender.entity_id}"
    if attacker.turn_flags.get(key):
        return None
    attacker.turn_flags[key] = True
    from .needle import save_dc

    dc = save_dc(engine, defender)
    roll = engine._roll_save(attacker, "WIS", dc, f"passive:{COURT}")
    if roll is not None and roll.total < dc:
        return {"mode": "DISADVANTAGE"}
    return None


@hook("event")
def drunken_ends(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Drunken Monkey Stance: "The stance ends early if you are Incapacitated, Restrained, or unable to move." """
    if event_type != "CONDITION_APPLIED":
        return
    for target_id in kwargs.get("target_ids") or ():
        holder = engine.state.actors.get(target_id)
        if holder is None or not _active(holder, DRUNKEN):
            continue
        from .needle import incapacitated

        restrained = any(c.condition_id.endswith(".restrained") for c in holder.conditions.values())
        if incapacitated(holder) or restrained:
            for mid, modifier in list(holder.modifiers.items()):
                if DRUNKEN in str(modifier.source_definition_id):
                    del holder.modifiers[mid]
                    engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=holder.entity_id, target_ids=(holder.entity_id,),
                                         payload={"modifier_id": mid, "reason": "STANCE_ENDED"})
            for iid, condition in list(holder.conditions.items()):
                if DRUNKEN in str(condition.source_definition_id):
                    holder.conditions.pop(iid, None)
                    engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=holder.entity_id, target_ids=(holder.entity_id,),
                                         payload={"condition_id": condition.condition_id, "instance_id": iid})
            note(engine, f"passive:{DRUNKEN}", holder, "Drunken Monkey Stance ends.")


@hook("compile_actions")
def gm_link_button(info: dict[str, Any]) -> list[Any] | None:
    if SPHERE not in info.get("spheres", ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.monkey_link_gm", display_name="Monkey Link (climb, swing, prop: GM)", owner_id=info["actor_id"],
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "monkey_link_gm"}], "numbers": info.get("numbers") or {}, "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "player_only": True, "requires_condition": CAPER,
                    "description": "During the caper: create your Monkey Link for something the table does not track (a climb, a swing, a change of elevation, "
                                   "a prop, a hostile creature's space) -- one per turn."})]


# ------------------------------------------------------------------------------------------------ rows, staff finishes, special attacks
def _row(engine: Any, actor: Any, kind: str) -> bool:
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
    return any(row.get("block") == "monkey" and row.get("kind") == kind for row in rows)


@hook("compile_block")
def monkey_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": "monkey", "kind": spec.get("kind"), **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}] if block == "monkey" else None


STAFF_FINISHES = {"sweeping_tail": "Sweeping Tail: push it 10 feet", "crooked_branch": "Crooked Branch: pull it 10 feet",
                  "peach_tap": "Peach-Stealing Tap: it cannot take Reactions", "upside_down": "Upside-Down Strike: move 10 feet away from it"}


def _finish_options(ctx: Any, target: Any) -> dict[str, str]:
    actor = ctx.actor
    out = {"tap": f"Tap Finish: +{actor.proficiency_bonus} Bludgeoning", "laugh": f"Laugh Finish: {target.display_name} cannot take Reactions",
           "slip": "Slip Finish: move 5 feet without opportunity attacks from it"}
    if _row(ctx.engine, actor, "improvised_master") and "improvised" in str(ctx.source):
        out["tap"] = f"Tap Finish: +1d6 + {actor.proficiency_bonus} Bludgeoning (Improvised Master)"
    name = str(getattr(ctx.action, "display_name", "")).lower()
    if _row(ctx.engine, actor, "staff_sage") and (ctx.typed or {}).get("weapon") is not None and any(word in name for word in _STAFFISH):
        out.update(STAFF_FINISHES)  # Staff of the Laughing Sage: "once per turn on hit while Capering Footwork is active ... one Staff Finish"
    return out


def _run_finish(ctx: Any, target: Any, which: str) -> None:
    from ..typed_executor import Context, run_effects
    from ..gate2_runtime_models import DiceSpec

    engine, actor = ctx.engine, ctx.actor
    sub = Context(engine, actor, ctx.action, ctx.intent, {**(ctx.typed or {}), "_area_centre": None}, [target], target, {})
    if which == "tap" and _row(engine, actor, "improvised_master") and "improvised" in str(ctx.source):
        roll = engine.roller.roll(DiceSpec(count=1, sides=6, modifier=int(actor.proficiency_bonus or 2)), actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}:tap")
        engine._record_roll(roll)
        from ..typed_executor import _deal

        _deal(ctx, target, int(roll.total), "BLUDGEONING")
    elif which == "sweeping_tail":
        run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"}])
    elif which == "crooked_branch":
        run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "toward"}])
    elif which == "peach_tap":
        run_effects(sub, [{"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn"}])
    elif which == "upside_down":
        _step(ctx, actor, target, 10, "Upside-Down Strike")
    else:
        _base(ctx, target, which)


# The base finish hook picks among these when Staff of the Laughing Sage or Improvised Master adds to them.
def _choose_and_run(ctx: Any, target: Any) -> None:
    from .needle import CHOICE, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    offered = {key: label for key, label in _finish_options(ctx, target).items() if not actor.turn_flags.get(f"monkey_finish_used:{key}")}
    if not offered:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "MONKEY_FINISH", actor.entity_id, target.entity_id), actor, CHOICE + "monkey_finish",
                 list(offered), labels=offered, preferred=list(offered)[:1], allow_decline=True,
                 prompt=f"Monkey Link Finish: {ctx.action.display_name} hits {target.display_name}. Spend your Monkey Link?",
                 target_id=target.entity_id)
    if picked and spend(engine, actor, ctx.source, target, picked[0]):
        _run_finish(ctx, target, picked[0])


@effect("monkey_spend_link")
def spend_link(ctx: Any, eff: dict[str, Any]) -> None:
    """A Monkey Style ability that spends a link as part of it (Heaven-Uprooting Staff's wider radius)."""
    spend(ctx.engine, ctx.actor, ctx.source, None, str(eff.get("finish") or ""))


@hook("maneuvers")
def uprooting_with_a_link(info: dict[str, Any]) -> dict[str, Any] | None:
    """Heaven-Uprooting Staff: "If you spend a Monkey Link as part of this Action, increase the radius by 10 feet." -- a second button, offered while
    a link is held, whose area is 40 feet and which spends it."""
    import copy

    made = []
    for action in info.get("actions") or ():
        if "TAL_MONKEY_STYLE_HEAVEN_UPROOTING_STAFF" not in str(action.source_definition_id) or "#" in str(action.source_definition_id):
            continue
        parameters = copy.deepcopy(action.parameters)
        typed = parameters["typed"]
        area = dict(typed.get("area") or {})
        area["size_ft"] = int(area.get("size_ft") or 30) + 10
        typed["area"] = area
        typed["effects"] = [{"type": "monkey_spend_link", "finish": "heaven_uprooting"}, *typed.get("effects", [])]
        parameters["requires_condition"] = LINK
        made.append(type(action)(source_definition_id=f"{action.source_definition_id}#monkey_link", display_name=f"{action.display_name} (Monkey Link: 40 feet)",
                                 owner_id=action.owner_id, economy=action.economy, resolution_kind=action.resolution_kind, target_kind=action.target_kind,
                                 range_ft=action.range_ft, radius_ft=(action.radius_ft or 0) + 10 if getattr(action, "radius_ft", None) else getattr(action, "radius_ft", None),
                                 costs=action.costs, parameters=parameters))
    return {"actions": made} if made else None


@hook("candidate_allowed")
def vaulting_needs_the_run(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Vaulting Strike: "Requirement: You moved at least 10 feet this turn before making the attack." """
    if "TAL_MONKEY_STYLE_VAULTING_STRIKE" not in str(getattr(action, "source_definition_id", "")):
        return None
    return None if _moved_this_turn(engine, actor) >= 10 else False


# ------------------------------------------------------------------------------------------------ Thousand-Monkey Uprising
UPRISING = "TAL_MONKEY_STYLE_THOUSAND_MONKEY_UPRISING"


def _uprising_of(engine: Any, creature: Any, *, hostile: bool) -> tuple[Any, Any] | None:
    from .. import zones

    for zone in zones.typed_zones(engine):
        if not zone.active or UPRISING not in str(zone.source_definition_id):
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not owner.active or (owner.team_id != creature.team_id) != hostile:
            continue
        if any((c.x, c.y) == (creature.position.x, creature.position.y) for c in zone.affected_cells):
            return owner, zone
    return None


@hook("cover")
def uprising_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    """Thousand-Monkey Uprising: "allies gain Half Cover" inside the aura."""
    return 2 if target is not None and _uprising_of(engine, target, hostile=False) is not None else None


def _uprising_link(engine: Any, owner: Any, why: str) -> None:
    key = f"monkey_round_uprising_link:{engine.state.round_number}"
    if not owner.turn_flags.get(key):
        owner.turn_flags[key] = True
        create(engine, owner, f"passive:{UPRISING}", why, until_next=True, counted=False)


UPRISING_MENU = "monkey_uprising_fail"


def _uprising_test(engine: Any, enemy: Any, owner: Any, why: str) -> None:
    """"The first time each turn an enemy inside the aura moves or attacks, it makes a Wisdom saving throw. Failed Save: Choose one: fall Prone;
    drop one held object; Speed becomes 0 until the end of the turn; take 3d8 Psychic or Bludgeoning damage." The owner chooses after failure."""
    key = f"monkey_uprising_tested:{owner.entity_id}:{engine.state.round_number}:{engine.state.current_slot_index}"
    if enemy.turn_flags.get(key):
        return
    enemy.turn_flags[key] = True
    from ..typed_executor import Context, run_effects

    action = engine.action_catalog.get(next((a for a in owner.action_ids if UPRISING in a), ""))
    if action is None:
        return
    from .rider_choices import intent_for
    typed = dict((action.parameters or {}).get("typed") or {})
    note(engine, f"passive:{UPRISING}", owner, f"Thousand-Monkey Uprising: {enemy.display_name} {why} inside the aura.", (enemy.entity_id,))
    run_effects(Context(engine, owner, action, intent_for(engine), typed, [enemy], enemy, {}),
                [{"type": "save", "ability": "wis", "on_fail": [{"type": "monkey_uprising_consequence", "trigger": why}], "on_success": []}])


@effect("monkey_uprising_consequence")
def uprising_consequence(ctx: Any, eff: dict[str, Any]) -> None:
    """The owner chooses only after the failed save. Event-hook damage stays with the GM."""
    from . import menus
    from .rider_choices import pick
    from ..typed_executor import run_effects
    enemy, owner, engine = ctx.target, ctx.actor, ctx.engine
    if enemy is None:
        return
    picked = pick(engine, owner, UPRISING_MENU, "Thousand-Monkey Uprising",
                  ["Fall Prone", "Drop one held object", "Speed 0", "3d8 damage"], subject=enemy,
                  trigger=f"{enemy.display_name} {eff.get('trigger') or 'acts'} inside the aura and fails its Wisdom save", optional=False,
                  preferred=menus.picks(engine, owner, UPRISING_MENU) or ["Fall Prone"], intent=ctx.intent)[0]
    _uprising_link(engine, owner, f"{enemy.display_name} failed its save in the aura")
    if picked == "3d8 damage" and getattr(engine, "_ext_in_event", False):
        ctx.rider(f"Thousand-Monkey Uprising: GM resolves 3d8 Psychic or Bludgeoning damage to {enemy.display_name}; "
                  "event-triggered damage needs lock round 3's downstream dispatch seam.")
        return
    row = {"Fall Prone": {"type": "condition", "applies_to": "target", "condition": "prone"},
           "Drop one held object": {"type": "condition", "applies_to": "target", "condition": "disarmed"},
           "Speed 0": {"type": "speed", "applies_to": "target", "becomes": 0, "expires_on": "END_OF_CURRENT_TURN"},
           "3d8 damage": {"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["psychic", "bludgeoning"]}}[picked]
    run_effects(ctx, [row])


@hook("before_attack")
def uprising_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    found = _uprising_of(engine, attacker, hostile=True) if attacker is not None else None
    if found is not None:
        _uprising_test(engine, attacker, found[0], "attacks")
    return None


@hook("event")
def uprising_watch(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "MOVEMENT_COMMITTED":
        mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
        payload = kwargs.get("payload") or {}
        if mover is None or not mover.active or payload.get("footprint_step") or int(payload.get("cost_ft") or 0) <= 0:
            return
        found = _uprising_of(engine, mover, hostile=True)
        if found is not None:
            _uprising_test(engine, mover, found[0], "moves")
        return
    if event_type in ("SAVE_ROLLED", "CONDITION_APPLIED"):
        target = engine.state.actors.get(str(kwargs.get("actor_id") if event_type == "SAVE_ROLLED" else next(iter(kwargs.get("target_ids") or ()), "")))
        if target is None:
            return
        payload = kwargs.get("payload") or {}
        if event_type == "SAVE_ROLLED" and payload.get("success") is not False:
            return
        if event_type == "CONDITION_APPLIED" and not str(payload.get("condition_id") or "").endswith((".prone", ".disarmed")):
            return
        found = _uprising_of(engine, target, hostile=True)
        if found is not None:
            _uprising_link(engine, found[0], f"{target.display_name} faltered in the aura")


@hook("after_miss")
def uprising_miss(ctx: Any, target: Any) -> None:
    found = _uprising_of(ctx.engine, ctx.actor, hostile=True)
    if found is not None:
        _uprising_link(ctx.engine, found[0], f"{ctx.actor.display_name} missed in the aura")


# ------------------------------------------------------------------------------------------------ Mirror-Monkey Technique
MIRROR = "condition:typed.monkey_mirror"
MIRROR_TALENT = "TAL_MONKEY_STYLE_MIRROR_MONKEY_TECHNIQUE"


def _mirror(actor: Any) -> tuple[str, Any] | None:
    return next(((iid, c) for iid, c in actor.conditions.items() if c.condition_id == MIRROR), None)


def _set_images(engine: Any, actor: Any, images: int, source: str, expires: str | None = None) -> None:
    found = _mirror(actor)
    previous = found[1] if found and expires is None else None
    expires = expires or (found[1].expires_on if found else "CONCENTRATION_END")
    if found:
        actor.conditions.pop(found[0], None)
        engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": MIRROR, "instance_id": found[0]})
    from .effect_durations import apply_condition_preserving_clock
    apply_condition_preserving_clock(engine, actor, previous, MIRROR, source, actor.entity_id, expires_on=expires,
                            data={"label": f"Mirror-Monkey Technique: {images} afterimage(s)", "images": images})


@effect("monkey_mirror")
def mirror(ctx: Any, eff: dict[str, Any]) -> None:
    """Mirror-Monkey Technique: "Create two afterimages in spaces within 10 feet of you" (Concentration, up to 1 minute); as a Bonus Action
    while it remains, "recreate all missing afterimages" (``refresh``)."""
    if eff.get("refresh") and _mirror(ctx.actor) is None:
        return
    _set_images(ctx.engine, ctx.actor, 2, ctx.source, None if eff.get("refresh") else "CONCENTRATION_END")


@hook("before_attack")
def mirror_decoy(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """"When you are targeted by an attack, roll 1d6. 1-2: The attack targets an afterimage. 3-6: The attack targets you. An afterimage disappears
    when it is targeted." -- an afterimage struck makes the attack miss you; "If an enemy destroys an afterimage while Capering Footwork is active
    or while Drunken Monkey Stance is active, you create a Monkey Link." """
    found = _mirror(defender) if defender is not None else None
    if found is None or int((found[1].data or {}).get("images") or 0) <= 0 or attacker is None or attacker.team_id == defender.team_id:
        return None
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=1, sides=6, modifier=0), actor_id=defender.entity_id, reason=f"MIRROR:{MIRROR_TALENT}")
    engine._record_roll(roll)
    if int(roll.total) > 2:
        return None
    _set_images(engine, defender, int(found[1].data.get("images") or 0) - 1, f"passive:{MIRROR_TALENT}")
    engine.__dict__["_monkey_decoy"] = (attacker.entity_id, defender.entity_id)
    note(engine, f"passive:{MIRROR_TALENT}", defender, f"{attacker.display_name} strikes one of {defender.display_name}'s afterimages.")
    if _caper(defender) or _active(defender, DRUNKEN):
        create(engine, defender, f"passive:{MIRROR_TALENT}", "an afterimage was destroyed", counted=False)
    return {}


@hook("hit_response")
def decoy_misses(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: Any, effective_ac: int) -> Any:
    from ..attack_outcomes import unconditional_miss

    if engine.__dict__.get("_monkey_decoy") == (attacker.entity_id, target.entity_id):
        engine.__dict__.pop("_monkey_decoy", None)
        return unconditional_miss()
    return None


@hook("event")
def decoy_clears(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type in ("ATTACK_ROLLED",) and engine.__dict__.get("_monkey_decoy"):
        payload = kwargs.get("payload") or {}
        if payload.get("natural_result") is not None and not payload.get("provisional_hit", True):
            engine.__dict__.pop("_monkey_decoy", None)


@hook("compile_actions")
def mirror_refresh(info: dict[str, Any]) -> list[Any] | None:
    if MIRROR_TALENT not in info.get("owned_ids", ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.monkey_mirror_refresh", display_name="Mirror-Monkey: recreate afterimages", owner_id=info["actor_id"],
        economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "monkey_mirror", "refresh": True}], "numbers": info.get("numbers") or {}, "duration": {"kind": "instant"},
                              "riders": []}, "expected_damage": 0, "requires_condition": MIRROR,
                    "description": "Mirror-Monkey Technique: recreate all missing afterimages (Bonus Action)."})]


# ----------------------------------------------------------------------------------------- printed "choose" lists
# Impossible Ape Reversal ("Failed Save: Choose two:" / "Successful Save: Choose one option instead."), Laughing Theft of
# Timing ("choose one" once the penalty has made the roll fail) and Monkey Catches the Moon ("choose one" after the step).
# ONE implementation for all three: the ability's own typed rows carry a menu row and one entry per printed option, and the
# owner is asked when the ability resolves; the rows of the chosen options run in printed order. ``share`` names the row
# that holds the options, so a "Failed Save:" and a "Successful Save:" branch state the same list once. ``gm`` names the
# options the table still cannot run, and its line is said only when that option was actually picked.
def _find_keyed(rows: Any, key: str) -> dict[str, Any] | None:
    """The one effect row carrying ``key``, found in the ability's own rows or the save branches inside them."""
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        if row.get("key") == key:
            return row
        for field in ("on_fail", "on_success", "on_hit", "on_miss", "effects"):
            if found := _find_keyed(row.get(field), key):
                return found
    return None


def _options_of(ctx: Any, eff: dict[str, Any]) -> dict[str, Any]:
    rows = eff.get("effects_by_option") or {}
    if rows or not eff.get("share"):
        return rows
    shared = _find_keyed((ctx.typed or {}).get("effects"), str(eff["share"]))
    return (shared or {}).get("effects_by_option") or {}


def _ask_and_run(ctx: Any, eff: dict[str, Any], target: Any, *, optional: bool = False) -> list[str]:
    """Ask the printed list and run the chosen options. Returns the labels actually taken."""
    from . import menus
    from .rider_choices import pick
    from ..typed_executor import run_effects

    engine, actor = ctx.engine, ctx.actor
    rows = _options_of(ctx, eff)
    labels = list(rows)
    if not labels:
        return []
    menu_id = str(eff.get("menu") or f"monkey_{eff.get('share') or eff.get('key')}")
    count = max(1, min(int(eff.get("count") or 1), len(labels)))
    # "Choose two:" is a question with two answers: both bounds are the printed count, so neither the transport nor the
    # owner may answer with one, and the question says how many it wants instead of a bare "Choose an option".
    picked = pick(engine, actor, menu_id, str(eff.get("name") or ctx.action.display_name), labels,
                  labels={label: str((eff.get("labels") or {}).get(label) or label) for label in labels},
                  subject=target if target is not None else actor,
                  trigger=str(eff.get("trigger") or f"{ctx.action.display_name} used by {actor.display_name}"),
                  optional=optional, maximum=count, minimum=count,
                  choose=f"Choose {count} of these {len(labels)} results.",
                  preferred=menus.picks(engine, actor, menu_id) or labels[:count], intent=getattr(ctx, "intent", None))
    chosen = picked or ([] if optional else labels[:count])
    for label in chosen:
        note(engine, ctx.source, actor, f"{ctx.action.display_name}: {label}.")
        said = (eff.get("gm") or {}).get(label)
        for line in ([*said] if isinstance(said, list) else ([said] if said else [])):
            ctx.rider(str(line))
        run_effects(ctx, list(rows.get(label) or []))
    return chosen


@effect("monkey_choose")
def choose(ctx: Any, eff: dict[str, Any]) -> None:
    """One printed "Choose one:" / "Choose two:" list, asked when the ability is used."""
    _ask_and_run(ctx, eff, ctx.target, optional=bool(eff.get("optional")))


@effect("monkey_step")
def step_option(ctx: Any, eff: dict[str, Any]) -> None:
    """Asked movement grant: defaults to full OA immunity; typed ``ignore_oa_from: target`` exempts only that creature."""
    feet = eff.get("feet")
    if str(feet) == "half_speed":
        feet = max(0, ctx.engine._effective_speed(ctx.actor) // 2)
    ignored = (ctx.target.entity_id,) if eff.get("ignore_oa_from") == "target" and ctx.target is not None else ()
    _step(ctx, ctx.actor, ctx.target, int(feet or 0), str(eff.get("why") or ctx.action.display_name),
          provokes=bool(eff.get("provokes", False)), ignore_oa_from=ignored)


@effect("monkey_melee")
def melee_option(ctx: Any, eff: dict[str, Any]) -> None:
    """A printed melee attack; ``improvised`` also offers the owner's own improvised weapon, as Reversal permits."""
    why = str(eff.get("why") or ctx.action.display_name)
    if not eff.get("improvised"):
        melee_attack(ctx, ctx.actor, ctx.target, why)
        return
    from .needle import melee_weapon_action
    from .rider_choices import pick, trigger_name

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    options = []
    if _legal_weapon_target(engine, actor, target, melee_weapon_action(engine, actor)):
        options.append("melee")
    if _legal_weapon_target(engine, actor, target, _improvised_action(engine, actor, thrown=False)):
        options.append("improvised")
    if not options:
        note(engine, ctx.source, actor, f"{why}: no melee or improvised weapon can reach the triggering creature.")
        return
    selected = pick(engine, actor, "monkey_weapon", why, options,
                    labels={kind: _weapon_target_label(engine, actor, target,
                        melee_weapon_action(engine, actor) if kind == 'melee' else _improvised_action(engine, actor, thrown=False), kind)
                        for kind in options},
                    subject=target, trigger=trigger_name(engine), preferred=options[:1],
                    optional=False, intent=getattr(ctx, "intent", None))
    if selected == ["improvised"]:
        improvised_attack(ctx, target, why)
    elif selected == ["melee"]:
        melee_attack(ctx, actor, target, why)


@effect("monkey_improvised")
def improvised_option(ctx: Any, eff: dict[str, Any]) -> None:
    """An option's "make one improvised-weapon attack against <printed recipient>". A ``range_ft`` is how the print
    that read "a creature within N feet" hands the choice to the owner, who picks from the creatures in that range; with no
    range the option names its creature, so that one is used as it stands.

    The question names what the reaction answered: the printed ability, the attack that missed (read from the roll the
    fight recorded, ``_missed_attack``) and the creature that attack actually missed -- the ally the printed words call
    "the missed ally", which ``protects`` carries -- not whichever enemy happens to be nearest.
    """
    why = str(eff.get("why") or ctx.action.display_name)
    reach = int(eff.get("range_ft") or 0)
    target = ctx.target if not reach else None
    if target is not None and (not target.active or target.team_id == ctx.actor.team_id):
        return
    if reach:
        from .rider_choices import pick
        from ..target_knowledge import knowledge

        missed = _missed_ally(ctx)
        engine, actor = ctx.engine, ctx.actor
        thrown = bool(eff.get("thrown"))
        action = (_improvised_action(engine, actor, thrown=thrown)
                  or _improvised_action(engine, actor, thrown=not thrown))
        recipients = []
        for other in engine.state.actors.values():
            if not _legal_weapon_target(engine, actor, other, action):
                continue
            known = knowledge(engine, actor, other, action)
            # The printed cap is additional to the weapon's shared range policy.
            # Both membership and ordering use the accepted aim, never hidden movement.
            distance = (engine._effect_distance_to_cell(actor, known.position)
                        if known.mode == 'LAST_OBSERVED' else engine._effect_distance(actor, other))
            if distance <= reach:
                recipients.append((distance, other.entity_id, other))
        near = [other for _, _, other in sorted(recipients)]
        if not near:
            return
        if len(near) == 1:
            target = near[0]
        else:
            from collections import Counter
            names = Counter(other.display_name for other in near)
            shot = _missed_attack(ctx.engine, ctx.target, missed)
            chosen = pick(ctx.engine, ctx.actor, str(eff.get("menu") or "monkey_improvised_target"), why,
                          [other.entity_id for other in near],
                          labels={other.entity_id: _weapon_target_label(engine, actor, other, action, 'improvised',
                                      duplicate=names[other.display_name] > 1)
                                  for other in near},
                          subject=missed or near[0],
                          trigger=("the missed ranged attack"
                                   + (f" by {ctx.target.display_name}" if ctx.target is not None and ctx.target.active else "")
                                   + (f" ({shot})" if shot else "")), optional=False,
                          choose=f"Choose the creature within {reach} feet to attack.", preferred=[near[0].entity_id],
                          intent=getattr(ctx, "intent", None))
            target = ctx.engine.state.actors.get(chosen[0]) if chosen else None
    if target is None:
        return
    improvised_attack(ctx, target, why, thrown=bool(eff.get("thrown")))


def _missed_ally(ctx: Any) -> Any:
    """The creature the printed "the missed attack's ... ally" names: ``protects``, the ally a bystander's reaction shields
    (combat/typed_reactions.py's ally_missed), or the reaction's own subject where there is no other."""
    return ctx.engine.state.actors.get(str((ctx.typed or {}).get("protects") or "")) or ctx.target


def _missed_attack(engine: Any, attacker: Any, missed: Any) -> str:
    """The name of the attack that missed, read from the roll the fight recorded, in a player's words
    (``combat/history_text.history_name``); "" when the fight recorded no such roll to read."""
    from ..history_text import history_name

    for event in reversed(engine.events):
        if event.event_type != "ATTACK_ROLLED" or (attacker is not None and event.actor_id != attacker.entity_id):
            continue
        if missed is not None and missed.entity_id not in (event.target_ids or ()):
            continue
        action = engine.action_catalog.get(event.source_definition_id)
        return history_name(event.source_definition_id, {event.source_definition_id: action.display_name} if action else {})
    return ""


# ---------------------------------------------------------------------------------- Laughing Theft of Timing (a roll first)
PENDING = "monkey_theft_pending"     # the roll this fighter is penalising: "<the creature rolling>:<round>:<slot>:<the 1d6>:<events recorded>"
PENALTY = "monkey_theft_penalty"     # the 1d6 this fighter's penalty just rolled (reaction_amount), an integer


@hook("reaction_amount")
def theft_penalty(engine: Any, actor: Any, row: dict[str, Any], effect: dict[str, Any]) -> int | None:
    """Laughing Theft of Timing's printed "Roll 1d6 and subtract the result from the triggering d20 roll", rolled once here
    and remembered, because the printed list runs only if that penalty is what made the roll fail (``theft`` stores it with
    the roll it is about to shape). None for every other reaction row, so no other ability's amount changes."""
    if str(row.get("feature_id") or "") != THEFT or str(effect.get("type") or "") != "attack_modifier":
        return None
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=1, sides=6, modifier=0), actor_id=actor.entity_id, reason=f"REACTION:{THEFT}")
    engine._record_roll(roll)
    actor.turn_flags[PENALTY] = int(roll.total)
    return int(roll.total)


@effect("monkey_theft")
def theft(ctx: Any, eff: dict[str, Any]) -> None:
    """Laughing Theft of Timing answers a roll BEFORE it is made, so the printed "if the triggering roll fails because of
    this penalty" list can only run afterwards: reserve the roll that is about to happen -- the creature rolling it, the
    round, the slot and how many events the fight had recorded when its 1d6 was rolled, plus that 1d6, all in one string
    of ids and integers -- and let ``_settle_theft`` answer from the recorded roll of that very attempt."""
    other = ctx.target          # the creature about to roll: this reaction's own subject
    if other is None or not other.active:
        return
    amount = int(ctx.actor.turn_flags.pop(PENALTY, 0) or 0)
    if amount <= 0:
        return
    ctx.actor.turn_flags[PENDING] = ":".join(str(part) for part in (other.entity_id, int(ctx.engine.state.round_number),
                                                                   int(ctx.engine.state.current_slot_index), amount,
                                                                   len(ctx.engine.events)))


def _reserved(actor: Any) -> tuple[str, int, int, int, int] | None:
    """The roll a fighter has reserved (its 1d6 was about to shape it): the creature rolling, the round, the slot, the
    penalty and the number of events the fight had recorded when it was rolled. None for no reservation, or for one this
    build cannot read, which simply settles nothing."""
    parts = str(actor.turn_flags.get(PENDING) or "").rsplit(":", 4)   # an entity id may itself contain a colon
    if len(parts) != 5:
        return None
    try:
        return parts[0], *(int(part) for part in parts[1:])
    except ValueError:
        return None


def _waiting_on(engine: Any, roller: Any) -> list[tuple[Any, int, int]]:
    """Every fighter waiting on this creature's own roll in this very slot: the fighter, its 1d6 and that event count. The
    reservation names the round and the slot, so it cannot settle a later attempt or a different creature's roll."""
    if roller is None:
        return []
    waiting = []
    for actor in engine.state.actors.values():
        reserved = _reserved(actor) if actor.active else None
        if reserved is None:
            continue
        who, round_, slot, penalty, recorded = reserved
        if who == roller.entity_id and round_ == int(engine.state.round_number) and slot == int(engine.state.current_slot_index):
            waiting.append((actor, penalty, recorded))
    return waiting


def _attempt_index(engine: Any, roller: Any, recorded: int, kind: str, reason: str = "") -> int | None:
    """Where the fight recorded the roll of the attempt settling right now, and only when that attempt is the first
    ``kind`` of roll this creature made after its reservation (``recorded`` is how many events the fight had when the 1d6
    was rolled). An older roll of the same creature, and a later swing of the same creature (Extra Attack), are therefore
    never read as this reservation's own. None for no such roll."""
    for index in range(max(int(recorded), 0), len(engine.events)):
        event = engine.events[index]
        if event.event_type != kind or event.actor_id != roller.entity_id:
            continue
        return index if not reason or (event.payload or {}).get("reason") == reason else None
    return None


def _final_attack_numbers(engine: Any, roller: Any, index: int, payload: dict[str, Any]) -> tuple[int, int, bool]:
    """The numbers this one attack was really decided on: how high it rolled, how high the defence it actually faced had
    become by the end, and whether something made it miss whatever the roll. The ATTACK_ROLLED payload is the roll's own
    snapshot, written before every later correction and every defence, so the fight's own receipts for this attempt are
    read for what happened next, up to this creature's next swing -- which is ``attack_outcomes.attempt_end``, the same
    boundary the receipt itself is read inside: the attack's one outcome receipt (how high the AC really became -- every
    kind of defence publishes it, including a plug-in's own hit_response, while one that compared no AC publishes none), a
    post-roll correction that raised the roll (PASSIVE_TRIGGERED, ``attack_correction``), a defence that raised the AC the
    roll had to beat through a recorded recheck (``new_ac`` with ``hit_after_recheck`` False), and an unconditional forced
    miss (ATTACK_FORCED_MISS, which misses even a natural 20)."""
    from ..attack_outcomes import attempt_end, attack_outcome

    total, against, forced = int(payload.get("modified_total") or 0), int(payload.get("target_ac") or 0), False
    for position in range(index + 1, attempt_end(engine, roller.entity_id, index)):
        event = engine.events[position]
        body = event.payload or {}
        if event.event_type == "ATTACK_FORCED_MISS":
            forced = True             # the attack misses whatever it rolled, so no 1d6 decided that
            continue
        if body.get("attack_correction") and body.get("roll_id") == payload.get("roll_id"):
            total = int(body.get("modified_total") or total)     # a post-roll bonus raised the roll this attack used
        elif body.get("hit_after_recheck") is False and isinstance(body.get("new_ac"), int):
            against = max(against, int(body["new_ac"]))          # a defence raised the AC it had to beat
    receipt = attack_outcome(engine, roller.entity_id, index)
    if receipt is not None:
        against = max(against, int(receipt["armor_class"]))      # the defence's own outcome receipt, whatever its kind
    return total, against, forced


def _caused_the_failure(engine: Any, roller: Any, index: int, payload: dict[str, Any], penalty: int, kind: str) -> bool:
    """Whether this fighter's own 1d6 is what made that recorded roll fail: an attack roll whose penalized total is under
    the AC it ended up facing while its unpenalized total would have reached that same AC (a natural 1 misses whatever
    the penalty, and an attack something forced to miss misses whatever the 1d6 rolled), or a saving throw whose total is
    under the DC the penalty raised while it would have met the untouched DC. A roll that failed anyway was not this
    penalty's doing, and gets no printed list."""
    if penalty <= 0 or not payload:
        return False
    if kind == "ATTACK_ROLLED":
        total, against, forced = _final_attack_numbers(engine, roller, index, payload)
        return (not forced and int(payload.get("natural_result") or 0) != 1
                and total < against <= total + penalty)
    total, dc = int(payload.get("total") or 0), int(payload.get("dc") or 0)
    return total < dc <= total + penalty


def _settle_theft(ctx: Any, roller: Any, kind: str, *, failed: bool, reason: str = "") -> None:
    """Every Monkey Style fighter waiting on this exact roll, settled together and cleared on either outcome: a roll that
    did not fail owes nothing, and a roll that failed for some other reason is not this penalty's doing. Only the fighters
    whose own 1d6 turned this very failure are asked their printed question."""
    engine = ctx.engine
    if roller is None or not roller.active:
        return
    for watcher, penalty, recorded in _waiting_on(engine, roller):
        watcher.turn_flags.pop(PENDING, None)
        if not failed:
            continue
        index = _attempt_index(engine, roller, recorded, kind, reason)
        payload = {} if index is None else dict(engine.events[index].payload or {})
        if _caused_the_failure(engine, roller, index or 0, payload, penalty, kind):
            _ask_theft(ctx, watcher, roller)


def _ask_theft(ctx: Any, watcher: Any, other: Any) -> None:
    engine = ctx.engine
    row = next((r for r in (getattr(engine, "typed_reaction_rows", {}) or {}).get(watcher.entity_id, []) or []
                if str(r.get("feature_id")) == THEFT), None)
    eff = next((e for e in ((row or {}).get("effects") or []) if isinstance(e, dict) and e.get("type") == "monkey_theft"), None)
    if eff is None:
        return
    from ..typed_executor import Context

    action = engine.action_catalog.get(watcher.entity_id) or _any_action(engine, watcher)
    _ask_and_run(Context(engine, watcher, action, getattr(engine, "_active_intent", None), row or {}, [other], other, {}),
                 eff, other, optional=True)


def _any_action(engine: Any, actor: Any) -> Any:
    """A display source for a choice the reaction itself owns (no action of its own sits in the catalogue)."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return ActionDefinition(source_definition_id=f"reaction:typed.{THEFT}", display_name="Laughing Theft of Timing", owner_id=actor.entity_id,
                            economy=EconomyKind.REACTION, resolution_kind="TYPED", target_kind="SELF")


@hook("attack_result")
def theft_attack_outcome(ctx: Any, target: Any, hit: Any, critical: Any) -> None:
    """The penalized attack roll has its final outcome: the documented ``attack_result`` seam fires once per resolved typed
    attack, after every later correction (a rechecked AC, an interception), and ``ctx.attack_result`` is that attempt's own
    recorded roll. ``ctx.actor`` is the creature whose attack resolved -- the creature whose roll was penalised -- so a hit
    clears that fighter's reservation (a landed attack owes nothing, and the reservation must not be spent by a later swing)
    and a miss answers the printed list. combat/ext/__init__.py, ``attack_result``."""
    _settle_theft(ctx, ctx.actor, "ATTACK_ROLLED", failed=not bool(hit),
                  reason=str((ctx.attack_result or {}).get("reason") or ""))


@hook("after_save_resolved")
def theft_after_save(ctx: Any, subject: Any, ability: Any, named: Any, failed: bool) -> None:
    """The penalized saving throw has its final outcome (after every later override): the printed list is settled now.
    ``subject`` is the creature that made that save, which is the creature whose roll was penalised."""
    _settle_theft(ctx, subject, "SAVE_ROLLED", failed=bool(failed))


# ---------------------------------------------------------------------------------- Monkey Catches the Moon (a step first)
@effect("monkey_moon")
def moon(ctx: Any, eff: dict[str, Any]) -> None:
    """"Move up to 10 feet without provoking opportunity attacks. If you end this movement adjacent to the missed attack's
    path or target space, choose one: ..." -- the step first ("up to 10 feet" is zero feet too), then the printed list, said
    only when the fighter ended adjacent to where the shot flew through or to the space it was aimed at.
    ``protects`` is the ally the ranged attack missed (combat/typed_reactions.py ally_missed)."""
    engine, actor = ctx.engine, ctx.actor
    protects = engine.state.actors.get(str((ctx.typed or {}).get("protects") or "")) or ctx.target
    flight = _missed_flight(engine, ctx.target, protects)
    if not _step(ctx, actor, protects, 10, "Monkey Catches the Moon", near=flight):
        return
    if not _touches(engine, actor, flight):
        note(engine, ctx.source, actor, "Monkey Catches the Moon: you did not end next to where the missed shot flew or the space it "
                                       "was aimed at, so there is nothing to choose.")
        return
    _ask_and_run(ctx, eff, protects or ctx.target, optional=True)


def _missed_flight(engine: Any, attacker: Any, missed: Any) -> set[tuple[int, int]]:
    """The cells the printed "the missed attack's path or target space" names: the squares the shot flew through between
    the creature that fired and the creature it missed, and the space it was aimed at. The firing creature's own square is
    not part of the flight, so standing beside the attacker alone does not open the printed list."""
    cells: set[tuple[int, int]] = set()
    if missed is not None and missed.active:
        cells |= {(int(here[0]), int(here[1])) for here in engine._actor_cells(missed)}
    if attacker is not None and attacker.active and missed is not None and missed.active:
        cells |= {(int(here[0]), int(here[1])) for here in engine.grid.ray_cells(attacker.position, missed.position)[1:-1]}
    return cells


def _touches(engine: Any, mover: Any, cells: set[tuple[int, int]]) -> bool:
    """Whether ``mover``'s own space is adjacent (within one square) to any of ``cells``."""
    own = [(int(here[0]), int(here[1])) for here in engine._actor_cells(mover)]
    return any(engine.grid.distance_cells(here, want) <= 1 for here in own for want in cells)


COVER = "condition:typed.monkey_half_cover"


@effect("monkey_half_cover")
def half_cover(ctx: Any, eff: dict[str, Any]) -> None:
    """Monkey Catches the Moon: "give the missed ally Half Cover until the start of your next turn". The ally is the
    creature the ranged attack missed (``protects``, set by the ally_missed reaction), not the attacker."""
    from .effect_durations import token

    engine = ctx.engine
    ally = engine.state.actors.get(str((ctx.typed or {}).get("protects") or "")) or ctx.target
    if ally is None or not ally.active:
        return
    engine._apply_condition(ally, COVER, ctx.source, ally.entity_id,
                            expires_on=token("start", ctx.actor.entity_id, int(ctx.actor.turns_started) + 1),
                            data={"label": f"Half Cover (+2 AC against attacks and +2 to Dexterity saving throws) until the start of {ctx.actor.display_name}'s next turn",
                                  "from": ctx.actor.entity_id})


@hook("cover")
def moon_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    """The Half Cover Monkey Catches the Moon grants its missed ally: +2 AC against attacks while it lasts (D&D's Half Cover)."""
    if target is None:
        return None
    return 2 if any(condition.condition_id == COVER for condition in target.conditions.values()) else None


@hook("effect_cover")
def moon_spatial_cover(engine: Any, source: Any, target: Any, ray: Any) -> int | None:
    """The same Half Cover in explicit spatial queries; cover providers combine by maximum, never addition."""
    return moon_cover(engine, source, target)


@hook("save_bonus_details")
def moon_save_cover(engine: Any, target: Any, ability: str, dc: int, source_id: str, intent: Any) -> dict[str, Any] | None:
    """Half Cover's Dexterity bonus, once, from the actual save origin; unknown/non-spatial saves infer nothing."""
    if ability != "DEX" or moon_cover(engine, None, target) is None:
        return None
    context = engine.d20_context() or {}
    origins = context.get("effect_origin_cells") or []
    if not origins:
        return None
    bonus = engine.cover_from(origins, context.get("source_actor_id"), target)['bonus']
    return {"bonus": bonus, "contributions": {"cover": bonus}} if bonus else None


@hook("save")
def trick_or_finish_forced_save(ctx: Any, subject: Any, ability: Any, named: Any) -> None:
    """The printed scope "a creature you affected with a Monkey Style Trick, Finish, or feint this turn" also covers a
    saving throw this fighter forced. The ``save`` seam is the only place that knows who forced one: a SAVE_ROLLED event names
    the creature that made the save and the ability that asked for it, never the fighter that used it, so reading the event
    alone would let one Monkey Style fighter's save open another's reaction. The creature is therefore recorded here, on the
    fighter whose ability forced the save, beside the Finish record ``spend`` writes. Returns None for every other save, so
    no save's bonus or modes change."""
    if subject is None or ctx.actor.team_id == subject.team_id or not _a_trick_or_finish(ctx.source):
        return None
    ctx.actor.turn_flags[AFFECTED_ON + subject.entity_id] = _turn_stamp(ctx.engine)
    return None


@hook("reaction_subject_allowed")
def theft_subject(engine: Any, reactor: Any, other: Any, row: Any) -> bool | None:
    """Laughing Theft of Timing's printed scope: "a creature you affected with a Monkey Style Trick, Finish, or feint this
    turn". The reviewed trigger reading (authority/typed_mechanics/trigger_readings.jsonl) answers any enemy d20; this keeps
    the printed limit, read from what this fighter itself did this turn: it hit that creature with one of those features,
    spent a Finish against it, or forced it to make a saving throw (``trick_or_finish_forced_save`` records that last one).
    None for every other row."""
    if other is None or str((row or {}).get("feature_id")) != THEFT or not reactor.active:
        return None
    if reactor.team_id == other.team_id:
        return False
    return None if _affected_with_a_trick_or_finish(engine, reactor, other) else False


# Laughing Theft of Timing's printed scope is "a creature you affected with a Monkey Style Trick, Finish, or feint". These
# are the Monkey Style features whose own printed heading in APP/authority/typed_mechanics/rules_text.json carries a
# "- Trick" or "- Finish" tag, or whose printed Chain Role is Finish, plus Mischievous Feint (the printed "feint"); their
# mechanic id is the last part of the action id combat's compiler writes, which is what an event names them by. An ordinary
# weapon attack of this fighter's own is not among them and does not open the reaction.
TRICK_OR_FINISH = (
    "TAL_MONKEY_STYLE_BORROWED_TREASURE",
    "TAL_MONKEY_STYLE_DRUNKEN_MONKEY_STANCE",
    "TAL_MONKEY_STYLE_GOLDEN_HOOP_STAFF",
    "TAL_MONKEY_STYLE_HEAVEN_UPROOTING_STAFF",
    "TAL_MONKEY_STYLE_HUNDRED_HANDED_TRICKSTER",
    "TAL_MONKEY_STYLE_IMPOSSIBLE_APE_REVERSAL",
    "TAL_MONKEY_STYLE_IMPROVISED_MASTER",
    "TAL_MONKEY_STYLE_LAUGHING_THEFT_OF_TIMING",
    "TAL_MONKEY_STYLE_LAUGHING_TRIP",
    "TAL_MONKEY_STYLE_MISCHIEVOUS_FEINT",
    "TAL_MONKEY_STYLE_MONKEY_CATCHES_THE_MOON",
    "TAL_MONKEY_STYLE_SNATCH_AND_SCATTER",
    "TAL_MONKEY_STYLE_STONE_SKIPPING_STRIKE",
    "TAL_MONKEY_STYLE_TAIL_QI_HOOK",
    "TAL_MONKEY_STYLE_VAULTING_STRIKE",
)
# What the fight records when one of those features reaches a creature: a hit, a condition it put on it, or a
# Monkey Link Finish spent against it (spend() writes that one, because a Finish rides an ordinary weapon's events).
_AFFECTING = ("ATTACK_RESOLVED", "DAMAGE_COMMITTED", "CONDITION_APPLIED")


def _a_trick_or_finish(source: Any) -> bool:
    text = str(source)
    return any(text == feature or text.endswith(f".{feature}") or f".{feature}#" in text for feature in TRICK_OR_FINISH)


def _affected_with_a_trick_or_finish(engine: Any, reactor: Any, other: Any) -> bool:
    """Whether ``reactor`` has already affected ``other`` with a Monkey Style Trick, Finish or feint this turn, from what
    the fight itself has recorded FOR THAT FIGHTER: an event it caused on that creature, a Finish it spent a Monkey Link
    against, or a saving throw it forced (trick_or_finish_forced_save). Stamps and the event scan both refer to the
    current creature's turn, even when the reactor acted as a reaction during someone else's turn."""
    stamp = _turn_stamp(engine)
    if reactor.turn_flags.get(FINISHED_ON + other.entity_id) == stamp or reactor.turn_flags.get(AFFECTED_ON + other.entity_id) == stamp:
        return True
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED":
            return False
        if other.entity_id not in (event.target_ids or ()):
            continue
        if event.event_type in _AFFECTING and event.actor_id == reactor.entity_id and _a_trick_or_finish(event.source_definition_id):
            return True
    return False


# --------------------------------------------------------------------------- Seventy-Two Earthly Transformations (beast form)
TRANSFORM = "tianxia.talent.monkey_style.seventy_two_earthly_transformations"
BEAST_FORM = "condition:typed.monkey_beast_form"


@effect("monkey_transform")
def transform(ctx: Any, eff: dict[str, Any]) -> None:
    """Seventy-Two Earthly Transformations: the printed "Transform into one ordinary or supernatural beast form you have
    studied." The ability's own options carry supported printed template benefits, so this records the transformation
    itself and nothing about which beast was studied: the fighter chose the template by using that option, and the table
    does not track a studied-beast list (out-of-fight study is the Game Master's,
    combat/ext/activation_requirements.py admits the talent only when the character has it).

    The marker records the transformation for its printed duration. The table currently automates only the hostile-space
    passage trigger for a Monkey Link; other printed movement triggers remain Game Master resolved. Inert without the
    talent."""
    from ..typed_executor import effect_expiry

    actor = ctx.actor
    if actor is None or not actor.active:
        return
    expiry = effect_expiry(ctx, eff, actor, condition=True)
    ctx.engine._apply_condition(actor, BEAST_FORM, ctx.source, actor.entity_id, expires_on=expiry,
                                data={"label": "Seventy-Two Earthly Transformations"})
    note(ctx.engine, ctx.source, actor, f"{actor.display_name} takes a studied beast form.")


def _transformed(actor: Any) -> bool:
    return any(c.condition_id == BEAST_FORM for c in actor.conditions.values())
