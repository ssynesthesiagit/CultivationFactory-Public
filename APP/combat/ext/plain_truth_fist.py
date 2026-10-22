"""Plain-Truth Fist (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, "33. Plain-Truth Fist": Open Declaration, Credence, CL3 Word and Hand, CL6 Unspoken
Intention Made Visible, CL10 Deed Follows Word, CL14 Heaven Rejects the Feint, CL18 Hall of Spoken Deeds). No Spheres 5e or D&D 5.5e
counterpart. Ownership rows: combat/rules/feature_blocks.d/riders_c8.json (Word and Hand, Unspoken Intention, Heaven Rejects the Feint
keeps compiling for Call the False Form).

Credence (tradition text): a pool (resource:named.credence), 0 at the start of the fight, maximum PB; completing an Open Declaration
gains 1, no more than once per turn.

What runs:
  * Open Declaration: "Open Declaration: Challenge / Pursuit / Guard / Break" (free, before you move or take an Action or Bonus Action
    on your turn; one a turn; it ends at the end of the turn). Completed: Challenge -- a Martial Strike (a weapon or unarmed attack)
    damages the named hostile creature; Pursuit -- you move 15+ feet this turn and end 10+ feet closer to it than you began; Guard
    (a willing ally within 30 feet) -- at the end of your turn you are within 10 feet of it and this turn you damaged a hostile creature
    that hurt or held it since your last turn, gave it Temporary HP, freed it of a condition or took the Dodge action; Break (a hostile
    creature holding Concentration, or grappling or restraining one of your side) -- that Concentration, Grapple or Restraint ends.
  * Truth-Forged Strike (once on each of your turns, asked, 1 Credence you had before the strike): after your Martial Strike damages
    a hostile creature -- Challenge +1d8 Psychic and no Reactions until the start of your next turn; Pursuit a 10-foot move toward the
    declared creature (no Opportunity Attack from it; only where no other foe could make one); Guard the declared ally gains Wisdom +
    PB Temporary HP and may stand up; Break +2d8 Psychic or Force to the declared creature, its Concentration save with Disadvantage.
  * Unspoken Intention Made Visible (Reaction, 2 Resonance, asked): a hostile creature bearing your Resonance Mark begins its turn within
    60 feet -- its Wisdom save. Succeeded: one Spiritual Pressure effect. Failed: it chooses an Intent (asked of its controller) --
    Strike (its first hostile attack or single-target save technique must include the named creature), Advance, Withdraw, Invoke (its
    first action is not an ordinary weapon attack), Hold, or doing nothing. An incompatible act brings Contradiction (once): 3d8
    Psychic, no Reactions until the start of its next turn, Disadvantage on an incompatible attack, Advantage for the targets of an
    incompatible technique; then the Intent ends.
  * Deed Follows Word (typed options, Action, 5 Resonance, 1-3 Credence asked): a move of 10 feet per Credence toward the deed (no
    Opportunity Attacks; only where no foe other than the declared one could make one), then one weapon or unarmed attack (asked) with
    your Cultivation attack bonus; a hit adds 3d8 + 1d8 per Credence Psychic or Force (asked) and its completion: Challenge -- Resonance
    Mark for the fight and Disadvantage on its attacks on others until the start of your next turn; Pursuit -- a step to a square next to
    it; Guard -- the ally gains 2 x PB + Wisdom Temporary HP, a 10-foot move without provoking and Advantage on its next Int/Wis/Cha
    save; Break -- a Cultivation Check against the target's Save DC ends its Concentration. A miss allows a 5-foot step toward it.
  * Heaven Rejects the Feint: Unbroken Word (while you declare, Advantage on your first save each turn against being moved, Grappled,
    Restrained, Frightened or Charmed); Contradiction Leaves an Opening (once per round, asked: half your Speed toward it, Mind Spike one
    die fewer, a weapon attack in reach, or two Spiritual Pressure effects).
  * Hall of Spoken Deeds (typed zone, Concentration): a hostile creature starting its turn in it makes a Wisdom save (after two
    successes it is no longer bound automatically) -- failed, it chooses an Intent as above; succeeded, one Spiritual Pressure effect.
    An ally starting its turn in it may declare Challenge, Pursuit, Guard or Hold (asked) and, completing it, chooses one benefit (a
    10-foot move without provoking, 2 x PB Temporary HP, or Advantage on its next Int/Wis/Cha save). The first time each round you
    complete a declaration or a hostile creature suffers Contradiction in it, +1 Credence. "Deed Follows Word (Hall): <deed>" once on
    each of your turns without Resonance. "Final Pronouncement: Face Me / Do Not Flee / Release What Is Not Yours / Speak the Deed"
    (free, once, a Resonance Marked hostile creature in it; CHA save): Face Me -- it cannot target another creature with a hostile
    single-target effect while you are in its range; Release -- one Grapple or Restraint it holds ends (asked); the others are the
    GM's. A Witness Stone object (AC your DC, 8 x PB HP); destroying it ends the Hall.

Plug-in surface: effects truth_declare, truth_deed, truth_deed_hit, truth_hall, truth_pronounce; hooks compile_actions, candidate_allowed, event, turn_start, turn_end,
technique_start, damage_dealt, before_attack, save, after_save_resolved. Shared helpers used: spirit_traditions (row/context/numbers/
feature_action/pick_creature/routes/choose_route/save/can_react/mind_spike/remove), typed_reactions (triggered_context/
opportunity_reach), end_effect.cultivation_dc, needle, zones.typed_zones, typed_executor.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st
from .challenge_conditions import DEED_CHALLENGE_SOURCE, is_deed_challenge

TRADITION = "tianxia.tradition.spirit.plain_truth_fist.feature."
WORD = TRADITION + "word_and_hand"
INTENTION = TRADITION + "unspoken_intention_made_visible"
DEED = DEED_CHALLENGE_SOURCE
FEINT = TRADITION + "heaven_rejects_the_feint"
HALL = TRADITION + "hall_of_spoken_deeds"
CREDENCE = "resource:named.credence"
RESONANCE = "resource:core.resonance"
DECLARED = "condition:typed.open_declaration"
COMPLETED = "condition:typed.completed_declaration"
INTENT = "condition:typed.bound_intent"
CHALLENGED = "condition:typed.challenged"
HALL_SAVES = "condition:typed.hall_intention_saves"
STONE = "object:typed.witness_stone:"
DEEDS = ("Challenge", "Pursuit", "Guard", "Break")
INTENTS = ("strike", "advance", "withdraw", "invoke", "hold", "nothing")
DEFENSIVE = ("dodge", "ready", "help", "search", "hold position")
_HOLDS = ("condition:core.grappled", "condition:typed.grappled", "condition:typed.restrained")


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _held(creature: Any, condition_id: str, source_id: str | None = None) -> Any:
    return next((c for c in creature.conditions.values() if c.condition_id == condition_id and (source_id is None or c.source_actor_id == source_id)), None)


def _pb(engine: Any, actor: Any) -> int:
    return int(st.numbers(engine, actor).get("pb") or 2)


def _event_source(engine: Any) -> str:
    """The source id of the event being announced (the event hook's keywords do not carry it)."""
    return str(engine.events[-1].source_definition_id if engine.events else "")


def _martial(action: Any) -> bool:
    """A Martial Strike: a weapon or unarmed attack (not a cultivation technique's attack)."""
    if action is None:
        return False
    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("weapon"):
        return True
    return any(isinstance(r, dict) and r.get("type") == "attack" and not str(r.get("attack_kind") or "").startswith("cultivation")
               for r in typed.get("effects") or [])


def _gain(engine: Any, fist: Any, why: str, *, flag: str = "credence_gained") -> None:
    if CREDENCE not in fist.resources or fist.resources.get(CREDENCE, 0) >= fist.resource_maximums.get(CREDENCE, 0):
        return
    if flag == "credence_gained" and fist.turn_flags.get(flag):
        return  # "You can gain Credence no more than once per turn."
    fist.turn_flags[flag] = True
    engine._gain_resource(fist, CREDENCE, 1, WORD)
    note(engine, WORD, fist, f"{fist.display_name} gains 1 Credence ({why}).")


# ---------------------------------------------------------------------------------------------------------- Open Declaration
def declaration(fist: Any) -> Any:
    return _held(fist, DECLARED, fist.entity_id)


def _complete(engine: Any, fist: Any, held: Any, why: str) -> None:
    data = st.data_of(fist, held)
    if data.get("completed"):
        return
    st.set_data(fist, held, completed=True)
    for old in [c for c in fist.conditions.values() if c.condition_id == COMPLETED and c.source_actor_id == fist.entity_id]:
        st.remove(engine, fist, old, "REPLACED")
    engine._apply_condition(fist, COMPLETED, WORD, fist.entity_id, expires_on="UNTIL_REMOVED",
                            data={"deed": data.get("deed"), "subject": data.get("subject"), "label": f"Last completed declaration: {data.get('deed')}"})
    note(engine, WORD, fist, f"{fist.display_name} completes the declaration ({data.get('deed')}: {why}).")
    if data.get("hall"):
        owner = engine.state.actors.get(str(data["hall"]))
        if owner is not None:
            _hall_benefit(engine, fist, owner)  # "Its declaration does not create your Credence."
        return
    _gain(engine, fist, f"{data.get('deed')} completed")
    if _in_hall(engine, fist, fist):
        _gain(engine, fist, "a declaration completed in the Hall", flag=f"hall_declaration_round_{engine.state.round_number}")


@effect("truth_declare")
def declare(ctx: Any, row: dict[str, Any]) -> None:
    engine, fist = ctx.engine, ctx.actor
    subject = ctx.target or next(iter(ctx.targets or ()), None)
    if subject is None:
        return
    fist.turn_flags["declared"] = True  # "You can have one Open Declaration at a time."
    hold = next((iid for c in engine.state.actors.values() if c.team_id == fist.team_id for iid, h in c.conditions.items()
                 if h.source_actor_id == subject.entity_id and h.condition_id in _HOLDS), None) if row.get("deed") == "Break" else None
    engine._apply_condition(fist, DECLARED, WORD, fist.entity_id, expires_on="UNTIL_REMOVED",
                            data={"deed": row.get("deed"), "subject": subject.entity_id, "turn": int(fist.turns_started), "hold": hold,
                                  "start_distance": engine._distance_actor_to_actor(fist, subject), "moved": 0,
                                  "since": int(fist.turn_flags.get("truth_turn_events") or len(engine.events)),
                                  "label": f"Open Declaration: {row.get('deed')} ({subject.display_name})"})


def _affected_since(engine: Any, subject_id: str, since: int) -> set[str]:
    """Hostile creatures that damaged, moved, restrained or otherwise affected ``subject_id`` since your previous turn."""
    out = set()
    for event in engine.events[since:]:
        if subject_id in (event.target_ids or ()) and event.event_type in ("DAMAGE_COMMITTED", "CONDITION_APPLIED", "MOVEMENT_COMMITTED", "MODIFIER_APPLIED"):
            source = engine.state.actors.get(event.actor_id or "")
            if source is not None and engine.state.actors.get(subject_id) is not None and source.team_id != engine.state.actors[subject_id].team_id:
                out.add(source.entity_id)
    return out


@hook("event")
def declaration_progress(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    fist = engine.state.actors.get(engine.state.current_actor_id or "")
    held = declaration(fist) if fist is not None else None
    if held is None or st.data_of(fist, held).get("completed"):
        return
    data = st.data_of(fist, held)
    deed, subject = data.get("deed"), engine.state.actors.get(str(data.get("subject") or ""))
    payload = kwargs.get("payload") or {}
    if subject is None:
        return
    if event_type == "DAMAGE_COMMITTED" and kwargs.get("actor_id") == fist.entity_id and int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) > 0:
        source = engine.action_catalog.get(_event_source(engine))
        victim = next(iter(kwargs.get("target_ids") or ()), None)
        if deed == "Challenge" and victim == subject.entity_id and _martial(source):
            _complete(engine, fist, held, "a Martial Strike damaged it")
        elif deed == "Guard" and victim in _affected_since(engine, subject.entity_id, int(data.get("since") or 0)):
            st.set_data(fist, held, guarded=True)
    elif event_type == "MOVEMENT_COMMITTED" and kwargs.get("actor_id") == fist.entity_id and not payload.get("forced"):
        moved = int(data.get("moved") or 0) + int(payload.get("planned_cost_ft") or payload.get("cost_ft") or 0)
        st.set_data(fist, held, moved=moved)
        if deed == "Pursuit" and moved >= 15 and engine._distance_actor_to_actor(fist, subject) <= int(data.get("start_distance") or 0) - 10:
            _complete(engine, fist, held, "it moved 15 feet and closed 10")
    elif deed == "Guard" and kwargs.get("actor_id") == fist.entity_id and subject.entity_id in (kwargs.get("target_ids") or ()) \
            and event_type in ("TEMP_HP_GRANTED", "CONDITION_REMOVED", "HEALING_APPLIED"):
        st.set_data(fist, held, guarded=True)  # Temporary HP, a freed condition or care from your feature
    elif deed in ("Guard", "Hold") and event_type == "INTENT_ACCEPTED" and kwargs.get("actor_id") == fist.entity_id:
        action = engine.action_catalog.get(_event_source(engine))
        name = str(getattr(action, "display_name", "") or "").lower()
        if deed == "Guard" and name == "dodge":
            st.set_data(fist, held, guarded=True)  # "take the Dodge or Ready action while it remains meaningfully threatened"
        elif deed == "Hold" and name in DEFENSIVE:
            st.set_data(fist, held, guarded=True)  # Hold: "take a primarily defensive, observational, recovery, or preparation action"
    elif deed == "Break" and event_type in ("CONCENTRATION_ENDED", "CONDITION_REMOVED"):
        ended = kwargs.get("actor_id") == subject.entity_id if event_type == "CONCENTRATION_ENDED" else (
            str(payload.get("condition_id") or "") in _HOLDS and data.get("hold") and data.get("hold") == str(payload.get("instance_id") or ""))
        if ended:
            _complete(engine, fist, held, "the named effect ended")


@hook("turn_start")
def turn_marker(engine: Any, actor: Any) -> None:
    if st.row(engine, actor, "word_and_hand") is None and not any(
        fist.active and fist.team_id == actor.team_id and _in_hall(engine, fist, actor)
        for fist in engine.state.actors.values()
    ):
        return
    actor.turn_flags["truth_turn_events"] = len(engine.events)


@hook("turn_end")
def declaration_ends(engine: Any, actor: Any) -> None:
    """"It ends at the end of the turn" (Guard is judged then); a bound Intent ends with its creature's turn."""
    held = declaration(actor)
    if held is not None:
        data = st.data_of(actor, held)
        subject = engine.state.actors.get(str(data.get("subject") or ""))
        if (data.get("deed") == "Guard" and data.get("guarded") and not data.get("completed") and subject is not None
                and engine._distance_actor_to_actor(actor, subject) <= 10):
            _complete(engine, actor, held, "it stood guard within 10 feet")
        elif (data.get("deed") == "Hold" and data.get("guarded") and not data.get("completed")
              and max(abs(actor.position.x - int(data.get("x", 0))), abs(actor.position.y - int(data.get("y", 0)))) * engine.grid.square_size_ft <= 5):
            _complete(engine, actor, held, "it held its ground")
        st.remove(engine, actor, held, "TURN_ENDED")
    for bound in [c for c in actor.conditions.values() if c.condition_id == INTENT]:
        st.remove(engine, actor, bound, "TURN_ENDED")


# ---------------------------------------------------------------------------------------------------------- Truth-Forged Strike
@hook("technique_start")
def credence_before(engine: Any, actor: Any, action: Any) -> None:
    """Truth-Forged Strike: the Credence spent must have been held before the strike; Credence gained by the strike itself is not
    spent on it."""
    if st.row(engine, actor, "word_and_hand") is None:
        return None
    actor.turn_flags["credence_before_strike"] = int(actor.resources.get(CREDENCE, 0))
    return None


def _expression(fist: Any) -> tuple[str | None, str | None]:
    held = declaration(fist) or _held(fist, COMPLETED, fist.entity_id)
    data = st.data_of(fist, held) if held is not None else {}
    return data.get("deed"), data.get("subject")


@hook("damage_dealt")
def truth_forged_strike(ctx: Any, target: Any, amount: int) -> None:
    from . import needle
    from .choice_prompt import action_context

    engine, fist = ctx.engine, ctx.actor
    if (st.row(engine, fist, "word_and_hand") is None or amount <= 0 or target is None or target.team_id == fist.team_id
            or engine.state.current_actor_id != fist.entity_id or fist.turn_flags.get("truth_forged") or not _martial(ctx.action)):
        return
    if min(int(fist.resources.get(CREDENCE, 0)), int(fist.turn_flags.get("credence_before_strike", fist.resources.get(CREDENCE, 0)))) < 1:
        return
    deed, subject_id = _expression(fist)
    subject = engine.state.actors.get(str(subject_id or ""))
    if deed is None:
        return
    numbers = st.numbers(engine, fist)
    guard_hp = int(numbers.get("key_mod") or 0) + int(numbers.get("pb") or 2)
    text = {"Challenge": f"deal an extra 1d8 Psychic damage to {target.display_name}; it cannot take Reactions until the start of your next turn",
            "Pursuit": f"move up to 10 feet now toward {getattr(subject, 'display_name', 'the declared creature')} "
                       "(or to another adjacent space if already adjacent), without provoking opportunity attacks from it",
            "Guard": f"{getattr(subject, 'display_name', 'the declared ally')} gains {guard_hp} Temporary Hit Points "
                     "(until used up or replaced) and may stand from Prone now without spending movement",
            "Break": f"deal an extra 2d8 Psychic or Force damage now to {getattr(subject, 'display_name', 'the declared creature')}; "
                     "it has Disadvantage on any Concentration save caused by this damage"}[deed]
    prompt_context = {**action_context(engine, fist, ctx.action.source_definition_id, target),
                      "cost": "1 Credence", "paying_pool": CREDENCE}
    if not needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "TRUTH_FORGED", target.entity_id), fist, "choice:needle.plain_truth.truth_forged",
                      ["use"], labels={"use": f"Truth-Forged Strike (1 Credence, {deed}): {text}"}, preferred=["use"], allow_decline=True,
                      prompt=f"Truth-Forged Strike: {fist.display_name}'s {ctx.action.display_name} damaged {target.display_name}. "
                             f"Spend 1 Credence (points earned by completing Open Declarations) for {deed}: {text}? "
                             "Once on each of your turns; the point must have been earned before this strike.",
                      name="Truth-Forged Strike", feature_id=WORD, target_id=target.entity_id, prompt_context=prompt_context):
        return
    fist.turn_flags["truth_forged"] = True  # "Once on each of your turns"
    engine._spend_resource(fist, CREDENCE, 1, WORD)
    sub = st.context(engine, fist, st.feature_action(engine, fist, WORD), [target], st.numbers(engine, fist), ctx.intent)
    if deed == "Challenge":
        _te().run_effects(sub, [{"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "damage_types": ["psychic"],
                                 "evidence": "Deal an additional 1d8 Psychic damage."},
                                {"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"},
                                 "evidence": "The damaged creature cannot take Reactions until the start of your next turn."}])
    elif deed == "Pursuit" and subject is not None:
        _step_toward(engine, fist, subject, 10, ctx.intent, "TRUTH_PURSUIT", "Truth-Forged Strike (Pursuit)")
    elif deed == "Guard" and subject is not None and subject.active:
        numbers = st.numbers(engine, fist)
        engine._grant_temp_hp(subject, int(numbers.get("key_mod") or 0) + int(numbers.get("pb") or 2), WORD, fist.entity_id)
        prone = next((c for c in subject.conditions.values() if str(c.condition_id).rsplit(".", 1)[-1] == "prone"), None)
        if prone is not None and needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "WITNESS_STANDS", subject.entity_id), subject,
                                            "choice:needle.plain_truth.stand", ["stand"], labels={"stand": "Stand up without spending movement"},
                                            preferred=["stand"], allow_decline=True, prompt="The Witness Stands", name="Truth-Forged Strike", feature_id=WORD):
            st.remove(engine, subject, prone, "STOOD")
    elif deed == "Break" and subject is not None and subject.active:
        kind = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "TRUTH_BREAK", subject.entity_id), fist, "choice:needle.plain_truth.break_type",
                          ["psychic", "force"], labels={"psychic": "Psychic", "force": "Force"}, preferred=["force"], prompt="Nothing False Remains Whole: damage type?",
                          name="Truth-Forged Strike", feature_id=WORD)
        rows = [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": [(kind or ["force"])[0]],
                 "evidence": "Deal an additional 2d8 Psychic or Force damage"}]
        if subject.concentration is not None:
            rows.insert(0, {"type": "disadvantage", "applies_to": "target", "on": "its next Concentration saving throw", "duration": {"kind": "until_end_of_your_next_turn"},
                            "evidence": "Concentrating: Disadvantage on the save this damage forces."})
        _te().run_effects(st.context(engine, fist, st.feature_action(engine, fist, WORD), [subject], st.numbers(engine, fist), ctx.intent), rows)


def _clear_paths(engine: Any, walker: Any, mover: Any, feet: int, allowed_id: str | None) -> dict[Any, Any]:
    """Squares ``mover`` can reach within ``feet`` without leaving the reach of a hostile creature other than ``allowed_id`` (which may
    make no Opportunity Attack for this move either)."""
    from .. import typed_reactions

    threats = [(c, int(typed_reactions.opportunity_reach(engine, c) or 5)) for c in engine.state.actors.values()
               if c.active and c.team_id != mover.team_id and c.reaction_available and c.entity_id != allowed_id]
    out = {}
    for cell, (path, cost) in st.routes(engine, mover, feet).items():
        if cell == mover.position:
            continue
        if not any(engine.grid.distance_ft(a, foe.position) <= reach < engine.grid.distance_ft(b, foe.position)
                   for foe, reach in threats for a, b in zip(path, path[1:])):
            out[cell] = (path, cost)
    return out


def _step_toward(engine: Any, fist: Any, subject: Any, feet: int, intent: Any, checkpoint: str, name: str, *, feature: str = WORD) -> None:
    now = engine._distance_actor_to_actor(fist, subject)
    spots = {c: v for c, v in _clear_paths(engine, fist, fist, feet, subject.entity_id).items()
             if engine._footprint_intersects(subject, [c]) is False and (engine.grid.distance_ft(c, subject.position) < now or engine.grid.distance_ft(c, subject.position) <= 5)}
    if not spots:
        return
    near = min(spots, key=lambda c: (engine.grid.distance_ft(c, subject.position), spots[c][1]))
    path = st.choose_route(engine, fist, spots, intent, checkpoint=checkpoint, prompt=f"{name}: move toward {subject.display_name}?", name=name,
                           feature=feature, preferred=near)
    if path is not None:
        from .rider_movement import step as walk

        walk(engine, fist, list(path), feature)


# ---------------------------------------------------------------------------------------------------------- Intents and Contradiction
def _bind(engine: Any, fist: Any, foe: Any, intent: Any, source: str) -> None:
    """The failed save: "the target chooses one Intent below that it is presently capable of attempting" (asked of its controller)."""
    from . import needle

    others = sorted([c for c in engine.state.actors.values() if c.active and c.team_id != foe.team_id and engine._distance_actor_to_actor(foe, c) <= 60],
                    key=lambda c: (engine._distance_actor_to_actor(foe, c), c.entity_id))[:4]
    options: dict[str, str] = {}
    for c in others:
        options[f"strike:{c.entity_id}"] = f"Strike Intent: my first hostile attack or technique includes {c.display_name}"
    for c in others:
        options[f"advance:{c.entity_id}"] = f"Advance Intent: move 10 feet and end 5 feet closer to {c.display_name} before moving away"
        options[f"withdraw:{c.entity_id}"] = f"Withdraw Intent: my first move ends 5 feet farther from {c.display_name}"
    options.update({"invoke": "Invoke Intent: my first Action or Bonus Action activates a technique, not a weapon attack",
                    "hold": "Hold Intent: stay within 5 feet until I take a defensive action (Dodge, Ready, Help, Search)",
                    "nothing": "Take no Action and make no voluntary movement"})
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "INTENT_CHOICE", foe.entity_id), foe, "choice:needle.plain_truth.intent",
                        list(options), labels=options, preferred=list(options)[:1], prompt=f"{fist.display_name}'s Unspoken Intention: choose your Intent.",
                        name="Unspoken Intention Made Visible", feature_id=INTENTION)
    pick = chosen[0] if chosen and chosen[0] in options else list(options)[0]
    kind, _, subject = pick.partition(":")
    engine._apply_condition(foe, INTENT, source, fist.entity_id, expires_on="UNTIL_REMOVED",
                            data={"intent": kind, "subject": subject or None, "x": foe.position.x, "y": foe.position.y, "moved": 0,
                                  "start_distance": engine._distance_actor_to_actor(foe, engine.state.actors[subject]) if subject else None,
                                  "label": options[pick]})
    note(engine, source, fist, f"{foe.display_name} chooses: {options[pick]}.", (foe,))


def bound_intent(creature: Any) -> Any:
    return next((c for c in creature.conditions.values() if c.condition_id == INTENT), None)


def _contradiction(engine: Any, foe: Any, held: Any, intent: Any) -> None:
    """"When it suffers Contradiction: it takes 3d8 Psychic damage; it cannot take Reactions until the start of its next turn ... After
    Contradiction resolves, the Intent ends\""""
    fist = engine.state.actors.get(held.source_actor_id or "")
    st.remove(engine, foe, held, "CONTRADICTION")
    if fist is None:
        return
    engine._append_event("GM_RIDER", INTENTION, actor_id=fist.entity_id, target_ids=(foe.entity_id,),
                         payload={"rider": f"{foe.display_name} acts against its Intent and suffers Contradiction."})
    sub = st.context(engine, fist, st.feature_action(engine, fist, INTENTION), [foe], st.numbers(engine, fist), intent)
    _te().run_effects(sub, [{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["psychic"], "evidence": "it takes 3d8 Psychic damage"},
                            {"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_next_turn"},
                             "evidence": "it cannot take Reactions until the start of its next turn"}])
    if _in_hall(engine, fist, foe):
        _gain(engine, fist, "Contradiction in the Hall", flag=f"hall_contradiction_round_{engine.state.round_number}")
    _opening(engine, fist, foe, intent)


def _opening(engine: Any, fist: Any, foe: Any, intent: Any) -> None:
    """Contradiction Leaves an Opening: once a round, when a creature suffers Contradiction from Unspoken Intention, one option is
    picked."""
    from . import needle

    if st.row(engine, fist, "heaven_rejects_the_feint") is None or not fist.active or not foe.active or fist.turn_flags.get("opening_round") == engine.state.round_number:
        return
    weapon = _weapon_attack(engine, fist, foe)
    options = {"move": f"Move up to half your Speed toward {foe.display_name} (it makes no Opportunity Attack)",
               "mind_spike": f"Mind Spike {foe.display_name} (one die fewer)",
               **({"attack": f"Attack {foe.display_name} with {weapon.display_name}"} if weapon is not None else {}),
               "pressure": f"Two different Spiritual Pressure effects on {foe.display_name}"}
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "CONTRADICTION_OPENING", foe.entity_id), fist, "choice:needle.plain_truth.opening",
                        list(options), labels=options, preferred=["mind_spike"], allow_decline=True, prompt="Contradiction Leaves an Opening",
                        name="Contradiction Leaves an Opening", feature_id=FEINT, target_id=foe.entity_id)
    if not chosen or chosen[0] not in options:
        return
    fist.turn_flags["opening_round"] = engine.state.round_number
    pick = chosen[0]
    if pick == "move":
        _step_toward(engine, fist, foe, max(5, engine._effective_speed(fist) // 2), intent, "OPENING_MOVE", "Contradiction Leaves an Opening", feature=FEINT)
    elif pick == "mind_spike":
        st.mind_spike(engine, fist, foe, intent, dice_delta=-1)
    elif pick == "attack" and weapon is not None:
        st.run_action(engine, fist, weapon, foe, intent)
    else:
        sub = st.context(engine, fist, st.feature_action(engine, fist, FEINT), [foe], st.numbers(engine, fist), intent)
        _te().run_effects(sub, [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "two different ordinary Spiritual Pressure effects"},
                                {"type": "spiritual_pressure", "applies_to": "target", "different": True, "evidence": "as one exceptional package"}])


def _weapon_attack(engine: Any, fist: Any, foe: Any) -> Any:
    own = [a for a in engine.action_catalog.values() if a.owner_id == fist.entity_id and (a.parameters or {}).get("typed", {}).get("weapon")
           and "#" not in a.source_definition_id and engine._target_in_range(fist, foe, a)]
    return max(own, key=lambda a: int((a.parameters or {}).get("expected_damage") or 0), default=None)


@hook("before_attack")
def intent_on_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    held = bound_intent(attacker) if attacker is not None else None
    if held is None or defender is None or defender.team_id == attacker.team_id:
        return _challenged(engine, attacker, defender, context)
    data = st.data_of(attacker, held)
    kind = data.get("intent")
    if kind == "strike":
        if defender.entity_id == data.get("subject"):
            st.remove(engine, attacker, held, "KEPT")  # its first hostile attack includes that subject
            return _challenged(engine, attacker, defender, context)
        _contradiction(engine, attacker, held, intent)
        return {"mode": "DISADVANTAGE"}  # "an incompatible attack has Disadvantage"
    if kind == "invoke" and not data.get("invoked") and _martial(engine.action_catalog.get(str(context.get("source_id") or ""))):
        _contradiction(engine, attacker, held, intent)
        return {"mode": "DISADVANTAGE"}
    if kind == "nothing":
        _contradiction(engine, attacker, held, intent)
        return {"mode": "DISADVANTAGE"}
    return _challenged(engine, attacker, defender, context)


@hook("save")
def intent_on_technique(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Strike Intent: its first "single-target hostile technique" must include the subject; Invoke is kept by a technique; an
    incompatible technique gives its targets Advantage."""
    foe = ctx.actor
    held = bound_intent(foe) if foe is not None else None
    extra = _unbroken_word(ctx, subject, named)
    if held is None or subject is None or subject.team_id == foe.team_id:
        return extra
    data = st.data_of(foe, held)
    if data.get("intent") == "invoke":
        st.remove(ctx.engine, foe, held, "KEPT")
        return extra
    if data.get("intent") == "strike" and len(ctx.targets or ()) <= 1:
        if subject.entity_id == data.get("subject"):
            st.remove(ctx.engine, foe, held, "KEPT")
            return extra
        _contradiction(ctx.engine, foe, held, ctx.intent)
        return {"bonus": int((extra or {}).get("bonus") or 0), "modes": [*((extra or {}).get("modes") or []), "ADVANTAGE"]}
    if data.get("intent") == "nothing":
        _contradiction(ctx.engine, foe, held, ctx.intent)
        return {"bonus": int((extra or {}).get("bonus") or 0), "modes": [*((extra or {}).get("modes") or []), "ADVANTAGE"]}
    return extra


@hook("event")
def intent_on_move(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    held = bound_intent(mover) if mover is not None else None
    if held is None:
        return
    data = st.data_of(mover, held)
    kind = data.get("intent")
    if event_type == "INTENT_ACCEPTED":
        action = engine.action_catalog.get(_event_source(engine))
        name = str(getattr(action, "display_name", "") or "").lower()
        if kind == "hold" and name in DEFENSIVE:
            st.remove(engine, mover, held, "KEPT")
        elif kind == "invoke" and action is not None and not _martial(action) and str(getattr(action, "resolution_kind", "")) == "TYPED" \
                and str(getattr(action, "economy", "")).split(".")[-1] in ("ACTION", "BONUS_ACTION"):
            st.remove(engine, mover, held, "KEPT")
        return
    payload = kwargs.get("payload") or {}
    if event_type != "MOVEMENT_COMMITTED" or payload.get("forced") or payload.get("dragged_by") or engine.state.current_actor_id != mover.entity_id:
        return
    moved = int(data.get("moved") or 0) + int(payload.get("planned_cost_ft") or payload.get("cost_ft") or 0)
    st.set_data(mover, held, moved=moved)
    subject = engine.state.actors.get(str(data.get("subject") or ""))
    here = engine._distance_actor_to_actor(mover, subject) if subject is not None else None
    start = int(data.get("start_distance") or 0)
    broke = False
    if kind == "nothing":
        broke = True
    elif kind == "hold":
        broke = max(abs(mover.position.x - int(data.get("x", 0))), abs(mover.position.y - int(data.get("y", 0)))) * engine.grid.square_size_ft > 5
    elif kind == "advance" and here is not None:
        if moved >= 10 and here <= start - 5:
            st.remove(engine, mover, held, "KEPT")
            return
        broke = here > start
    elif kind == "withdraw" and here is not None:
        if here >= start + 5:
            st.remove(engine, mover, held, "KEPT")
            return
        broke = True  # "Its first voluntary movement must end at least 5 feet farther from that subject"
    if broke:
        _contradiction(engine, mover, held, engine._active_intent)


def _challenged(engine: Any, attacker: Any, defender: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """Deed Follows Word (Challenge): the challenged attacker has Disadvantage on attacks aimed at anyone but the Fist while the
    Fist is still a legal target."""
    if attacker is None or defender is None:
        return None
    from ..attack_declaration import can_target

    for held in attacker.conditions.values():
        if not is_deed_challenge(held):
            continue
        fist = engine.state.actors.get(held.source_actor_id or "")
        if fist is None or not fist.active or defender.entity_id == fist.entity_id:
            continue
        if can_target(engine, attacker, fist, context["source_id"], action=context.get("action"),
                      typed=context.get("typed"), effect=context.get("effect"), index=context.get("attack_index", 1)):
            return {"mode": "DISADVANTAGE"}
    return None


@hook("turn_start")
def unspoken_intention(engine: Any, actor: Any) -> None:
    """Unspoken Intention (Reaction, 2 Resonance) when a meaningful hostile creature bearing the Fist's Resonance Mark starts its turn
    within 60 feet -- and the Hall's Hostile Intention at the start of each hostile creature's turn in the Hall."""
    from . import needle

    if not actor.active:
        return
    te = _te()
    for fist in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if fist.team_id == actor.team_id or not fist.active:
            continue
        hall = _hall(engine, fist)
        if hall is not None and _in_zone(engine, hall, actor) and bound_intent(actor) is None:
            from ..paid_relocation import activation as relocation_activation
            with relocation_activation(engine, fist, HALL, independent=True):
                _hostile_intention(engine, fist, actor, hall)
                continue
        if (st.row(engine, fist, "unspoken_intention_made_visible") is None or not st.can_react(fist) or fist.resources.get(RESONANCE, 0) < 2
                or not te.bears_mark(actor, fist.entity_id, "Resonance") or engine._distance_actor_to_actor(fist, actor) > 60 or bound_intent(actor) is not None):
            continue
        if not needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "UNSPOKEN_INTENTION", actor.entity_id), fist,
                          "choice:needle.plain_truth.unspoken_intention", ["use"], preferred=["use"], allow_decline=True,
                          labels={"use": f"Unspoken Intention Made Visible (Reaction, 2 Resonance): {actor.display_name} makes a Wisdom save"},
                          prompt=f"{actor.display_name} begins its turn bearing your Resonance Mark.", name="Unspoken Intention Made Visible",
                          feature_id=INTENTION, target_id=actor.entity_id):
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, fist, INTENTION, independent=True):
            fist.reaction_available = False
            engine._spend_resource(fist, RESONANCE, 2, INTENTION)
            engine._append_event("REACTION_RESOLVED", INTENTION, actor_id=fist.entity_id, target_ids=(actor.entity_id,),
                                 payload={"checkpoint": "TURN_START", "reaction_name": "Unspoken Intention Made Visible"})
            sub = st.context(engine, fist, st.feature_action(engine, fist, INTENTION), [actor], st.numbers(engine, fist))
            if st.save(sub, actor, "wis"):
                _bind(engine, fist, actor, engine._active_intent, INTENTION)
            else:
                _te().run_effects(sub, [{"type": "spiritual_pressure", "applies_to": "target", "duration": {"kind": "until_start_of_next_turn"},
                                         "evidence": "Impose one ordinary Spiritual Pressure effect until the start of its next turn."}])
                note(engine, INTENTION, fist, f"{actor.display_name}'s first intention is laid bare (the GM tells you whether it means to attack, move, "
                                              "invoke, defend or escape).", (actor,))
            break


# ---------------------------------------------------------------------------------------------------------- Heaven Rejects the Feint
_UNBROKEN = {"forced_movement", "grappled", "restrained", "frightened", "charmed"}


def _unbroken_word(ctx: Any, subject: Any, named: Any) -> dict[str, Any] | None:
    """Unbroken Word: with an active Open Declaration, Advantage on the first save each turn against an effect that would stop the
    deed being completed by moving the Fist against its will or by imposing Grappled, Restrained, Frightened or Charmed."""
    engine = ctx.engine
    if subject is None or st.row(engine, subject, "heaven_rejects_the_feint") is None or declaration(subject) is None:
        return None
    if not ({str(n).lower() for n in named or ()} & _UNBROKEN) or subject.turn_flags.get("unbroken_word"):
        return None
    subject.turn_flags["unbroken_word"] = True
    return {"bonus": 0, "modes": ["ADVANTAGE"]}


# ---------------------------------------------------------------------------------------------------------- Deed Follows Word
@effect("truth_deed")
def deed(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle
    from .. import typed_reactions

    engine, fist = ctx.engine, ctx.actor
    named = ctx.target or next(iter(ctx.targets or ()), None)
    kind = str(row.get("deed") or "Challenge")
    if named is None:
        return
    most = min(3, int(fist.resources.get(CREDENCE, 0)))
    if most < 1:
        return
    counts = [str(n) for n in range(1, most + 1)]
    picked = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "DEED_CREDENCE", fist.entity_id), fist, "choice:needle.plain_truth.deed_credence",
                        counts, labels={n: f"Spend {n} Credence (move {10 * int(n)} feet; +{n}d8)" for n in counts}, preferred=[counts[-1]],
                        prompt=f"Deed Follows Word ({kind}): how much Credence?", name="Deed Follows Word", feature_id=DEED)
    spent = int((picked or [counts[-1]])[0])
    engine._spend_resource(fist, CREDENCE, spent, DEED)
    toward = named
    _step_toward(engine, fist, toward, 10 * spent, ctx.intent, "DEED_MOVE", "Deed Follows Word", feature=DEED)
    if kind == "Guard":
        foes = [c for c in engine.state.actors.values() if c.active and c.team_id != fist.team_id and c.entity_id in _affected_since(engine, named.entity_id, 0)]
        target = st.pick_creature(engine, ctx.intent, fist, foes, checkpoint="DEED_GUARD_TARGET", choice_id="choice:needle.plain_truth.guard_target",
                                  prompt=f"Deed Follows Word (Guard): strike which creature that threatened {named.display_name}?", name="Deed Follows Word",
                                  feature_id=DEED)
    else:
        target = named
    if target is None or not target.active:
        return  # no legal attack target: the activation fails once its movement is done
    strike = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "DEED_STRIKE", fist.entity_id), fist, "choice:needle.plain_truth.deed_strike",
                        ["weapon", "unarmed"], labels={"weapon": "Strike with your weapon", "unarmed": "Unarmed Strike"}, preferred=["weapon"],
                        prompt="Deed Follows Word: with what?", name="Deed Follows Word", feature_id=DEED)
    how = (strike or ["weapon"])[0]
    kinds = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "DEED_DAMAGE", fist.entity_id), fist, "choice:needle.plain_truth.deed_damage",
                       ["psychic", "force"], labels={"psychic": "Psychic", "force": "Force"}, preferred=["force"], prompt="Deed Follows Word: extra damage type?",
                       name="Deed Follows Word", feature_id=DEED)
    attack = {"type": "attack", "attack_kind": "unarmed" if how == "unarmed" else "melee_weapon", "strike_with": how, "count": 1,
              "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 3 + spent, "sides": 8}, "damage_types": [(kinds or ["force"])[0]],
                          "evidence": "plus 3d8 + 1d8 per Credence spent Psychic or Force damage"},
                         {"type": "truth_deed_hit", "applies_to": "target", "deed": kind, "subject": named.entity_id}]}
    inner = typed_reactions.triggered_context(engine, fist, target, {"feature_id": DEED, "name": "Deed Follows Word",
                                                                     "numbers": dict(ctx.numbers or {}), "effects": [attack]}, ctx.intent)
    inner.typed["numbers"] = {**inner.typed.get("numbers", {}), "attack_bonus": int((ctx.numbers or {}).get("attack_bonus") or 0)}  # "Use your Cultivation Attack Modifier"
    before = len(engine.events)
    _te().run_effects(inner, [attack])
    hit = any(e.event_type == "ATTACK_ROLLED" and (e.payload or {}).get("provisional_hit") for e in engine.events[before:])
    if not hit and named.active:
        _step_toward(engine, fist, named, 5, ctx.intent, "DEED_MISS", "Deed Follows Word (miss)", feature=DEED)  # "You may move 5 feet toward"


@effect("truth_deed_hit")
def deed_hit(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle
    from .end_effect import cultivation_dc

    engine, fist = ctx.engine, ctx.actor
    target = ctx.target or next(iter(ctx.targets or ()), None)
    kind = row.get("deed")
    named = engine.state.actors.get(str(row.get("subject") or ""))
    if target is None:
        return
    numbers = st.numbers(engine, fist)
    if kind == "Challenge":
        _te().run_effects(ctx, [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_removed"},
                                 "evidence": "The target becomes Resonance Marked for the scene."}])
        engine._apply_condition(target, CHALLENGED, DEED, fist.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": f"Deed Follows Word: Disadvantage on attacks against anyone but {fist.display_name} "
                                               f"while {fist.display_name} is a legal target. Lasts until the start of "
                                               f"{fist.display_name}'s next turn"})
    elif kind == "Pursuit":
        _step_toward(engine, fist, target, 30, ctx.intent, "DEED_PURSUIT", "Deed Follows Word (Pursuit)", feature=DEED)
    elif kind == "Guard" and named is not None and named.active and engine._distance_actor_to_actor(fist, named) <= 30:
        engine._grant_temp_hp(named, 2 * int(numbers.get("pb") or 2) + int(numbers.get("key_mod") or 0), DEED, fist.entity_id)
        _te().run_effects(st.context(engine, fist, ctx.action, [named], numbers, ctx.intent),
                          [{"type": "advantage", "applies_to": "target", "on": "its next Intelligence, Wisdom, or Charisma saving throw",
                            "duration": {"kind": "until_start_of_your_next_turn"}, "evidence": "Advantage on its next Intelligence, Wisdom, or Charisma saving throw"}])
        spots = {c: v for c, v in st.routes(engine, named, 10).items() if c != named.position}
        path = st.choose_route(engine, fist, spots, ctx.intent, checkpoint="DEED_GUARD_MOVE", prompt=f"Deed Follows Word (Guard): move {named.display_name} 10 feet?",
                               name="Deed Follows Word", feature=DEED) if spots else None
        if path is not None:
            from .rider_movement import step as walk

            walk(engine, named, list(path), DEED)
    elif kind == "Break" and target.concentration is not None:
        dc = cultivation_dc(engine, target)
        roll = engine.roll_check(
            modifier=int(numbers.get('pb') or 2) + int(numbers.get('key_mod') or 0),
            actor_id=fist.entity_id,
            reason=f'CHECK:{DEED}',
        )
        engine._record_roll(roll)
        engine._append_event("CHECK_ROLLED", DEED, actor_id=fist.entity_id, target_ids=(target.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": roll.total >= dc, "check": "Cultivation Check (Break)"})
        if roll.total >= dc:
            engine._end_concentration(target, "BROKEN")  # "end an ordinary lower-authority effect" (its Concentration)


# ---------------------------------------------------------------------------------------------------------- Hall of Spoken Deeds
def _hall(engine: Any, fist: Any) -> Any:
    from .. import zones

    return next((z for z in zones.typed_zones(engine) if z.owner_id == fist.entity_id and st.feature_of(engine.action_catalog.get(z.source_definition_id)) == HALL), None)


def _in_zone(engine: Any, zone: Any, creature: Any) -> bool:
    return zone is not None and creature is not None and engine._footprint_intersects(creature, zone.affected_cells)


def _in_hall(engine: Any, fist: Any, creature: Any) -> bool:
    return _in_zone(engine, _hall(engine, fist), creature)


def _hostile_intention(engine: Any, fist: Any, foe: Any, hall: Any) -> None:
    """Hall's Hostile Intention: at the start of a hostile creature's turn in the Hall it makes a Wisdom save (two successes and it
    is no longer bound automatically)."""
    saves = next((c for c in foe.conditions.values() if c.condition_id == HALL_SAVES and c.source_actor_id == fist.entity_id), None)
    if saves is not None and int(st.data_of(foe, saves).get("successes") or 0) >= 2:
        return
    sub = st.context(engine, fist, st.feature_action(engine, fist, HALL), [foe], st.numbers(engine, fist))
    if st.save(sub, foe, "wis"):
        _bind(engine, fist, foe, engine._active_intent, HALL)
        return
    if saves is None:
        engine._apply_condition(foe, HALL_SAVES, HALL, fist.entity_id, expires_on="UNTIL_REMOVED", data={"successes": 1, "label": "Resisted the Hall once"})
    else:
        st.set_data(foe, saves, successes=int(st.data_of(foe, saves).get("successes") or 0) + 1)
    _te().run_effects(sub, [{"type": "spiritual_pressure", "applies_to": "target", "duration": {"kind": "until_start_of_next_turn"},
                             "evidence": "You may impose one ordinary Spiritual Pressure effect until its next turn starts"}])


@effect("truth_hall")
def hall_stone(ctx: Any, row: dict[str, Any]) -> None:
    """A visible Witness Stone appears in an unoccupied space within 30 feet of the Hall's centre."""
    from ..gate2_runtime_models import RuntimeObjectState

    engine, fist = ctx.engine, ctx.actor
    zone = _hall(engine, fist)
    if zone is None:
        return
    taken = ({(o.position.x, o.position.y) for o in engine.state.objects.values() if not o.destroyed}
             | set(engine._occupied_cells_except(fist.entity_id)) | set(engine._actor_cells(fist)))
    spot = next((c for c in sorted(zone.affected_cells, key=lambda c: (engine.grid.distance_ft(c, zone.center), c.y, c.x))
                 if (c.x, c.y) not in taken and (c.x, c.y) not in engine.grid.blocked), zone.center)
    hp = 8 * int((ctx.numbers or {}).get("pb") or 2)
    engine._update_object(RuntimeObjectState(object_id=f"{STONE}{fist.entity_id}:{engine.state.event_sequence}", object_kind="WITNESS_STONE", position=spot,
                                             unattended=False, flammable=False, owner_id=fist.entity_id, ac=int((ctx.numbers or {}).get("save_dc") or 10),
                                             current_hp=hp, maximum_hp=hp, component={"label": "Witness Stone (Hall of Spoken Deeds)", "zone_id": zone.zone_id, "resist": ["PSYCHIC"]}),
                          ctx.source, fist.entity_id)


@hook("event")
def stone_breaks(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"Destroying or fully suppressing the Stone ends the Domain.\""""
    if event_type != "OBJECT_UPDATED":
        return
    obj = (kwargs.get("payload") or {}).get("object") or {}
    if not str(obj.get("object_id") or "").startswith(STONE) or not (obj.get("destroyed") or (obj.get("current_hp") is not None and int(obj.get("current_hp") or 0) <= 0)):
        return
    fist = engine.state.actors.get(str(obj.get("owner_id") or ""))
    if fist is not None and fist.concentration is not None and st.feature_of(engine.action_catalog.get(fist.concentration.source_definition_id)) == HALL:
        engine._end_concentration(fist, "WITNESS_STONE_DESTROYED")


# ---------------------------------------------------------------------------------------------------------- buttons and gates
@hook("compile_actions")
def truth_buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned, out = info["owned_ids"], []
    if WORD in owned:
        texts = {"Challenge": "name one hostile creature; complete it by damaging that creature with a Martial Strike this turn.",
                 "Pursuit": "name one hostile creature; complete it by moving at least 15 feet and ending at least 10 feet closer to it.",
                 "Guard": "name one willing ally within 30 feet; stay within 10 feet of it and protect it this turn.",
                 "Break": "name one hostile creature holding Concentration, a Grapple or a Restraint; complete it by ending that effect this turn."}
        for kind in DEEDS:
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.plain_truth.declare.{kind.lower()}", display_name=f"Open Declaration: {kind}",
                owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED",
                target_kind="ALLY_OR_SELF" if kind == "Guard" else "HOSTILE_ENTITY", range_ft=30 if kind == "Guard" else 120,
                parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": WORD,
                                      "effects": [{"type": "truth_declare", "applies_to": "target", "deed": kind, **({"harmful": True} if kind != "Guard" else {})}]},
                            "expected_damage": 0, "plain_truth": f"declare.{kind.lower()}",
                            "description": f"Open Declaration (free, before you move or act this turn): {texts[kind]} Completing it gains 1 Credence."}))
    if HALL in owned:
        for key, label in PRONOUNCEMENTS.items():
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.plain_truth.pronounce.{key}", display_name=f"Final Pronouncement: {label}",
                owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=120,
                parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": HALL,
                                      "effects": [{"type": "truth_pronounce", "applies_to": "target", "harmful": True, "pronouncement": key}]},
                            "expected_damage": 0, "plain_truth": f"pronounce.{key}",
                            "description": f"Hall of Spoken Deeds (once during the Hall, free): {label} -- a Resonance Marked hostile creature in the Hall makes a "
                                           "Charisma save; failed, it lasts until the start of your next turn; succeeded, one Spiritual Pressure effect."}))
    if HALL in owned and DEED in owned:
        deed = info["mechanics"].get(DEED) or {}
        for option in deed.get("options") or []:
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.plain_truth.hall_deed.{str(option.get('label')).lower()}",
                display_name=f"Deed Follows Word (Hall): {option.get('label')}", owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED",
                target_kind="ALLY_OR_SELF" if option.get("label") == "Guard" else "HOSTILE_ENTITY", range_ft=60,
                parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": DEED,
                                      "effects": list(option.get("effects") or [])}, "expected_damage": 0, "plain_truth": "hall_deed",
                            "description": "Hall of Spoken Deeds -- Deed Without Hesitation: Deed Follows Word without its Resonance cost, once on each of your turns."}))
    return out or None


@hook("candidate_allowed")
def truth_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    if _face_me(engine, actor, candidate, action) is False:
        return False
    params = action.parameters or {}
    key = str(params.get("plain_truth") or "")
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    feature = st.feature_of(action)
    if key.startswith("pronounce."):
        zone = _hall(engine, actor)
        return None if (zone is not None and not zone.trigger_profile.get("pronounced") and target is not None and _in_zone(engine, zone, target)
                        and _te().bears_mark(target, actor.entity_id, "Resonance")) else False
    if feature == DEED or key == "hall_deed":
        if actor.resources.get(CREDENCE, 0) < 1:
            return False  # "Requirement: You have at least 1 Credence"
        if actor.turn_flags.get("hall_deed") and _hall(engine, actor) is not None:
            return False  # "Once on each of your turns ... You cannot also use a paid Deed Follows Word during that turn."
        if key == "hall_deed" and _hall(engine, actor) is None:
            return False
        if target is not None and any(isinstance(r, dict) and r.get("deed") == "Guard" for r in (params.get("typed") or {}).get("effects") or []) and target is actor:
            return False
        return None
    if key.startswith("declare."):
        if actor.turn_flags.get("declared") or not actor.action_available or not actor.bonus_action_available \
                or int(actor.movement_remaining_ft) < engine._effective_speed(actor):
            return False  # "before moving or taking an Action or Bonus Action"
        if target is None:
            return None
        if key == "declare.guard":
            return None if target is not actor and target.team_id == actor.team_id else False
        if key == "declare.break":
            holds = any(h.source_actor_id == target.entity_id and h.condition_id in _HOLDS for c in engine.state.actors.values()
                        if c.team_id == actor.team_id for h in c.conditions.values())
            return None if target.concentration is not None or holds else False
    return None


@hook("technique_used")
def deed_used(ctx: Any) -> None:
    key = str((ctx.action.parameters or {}).get("plain_truth") or "")
    if key == "hall_deed" or st.feature_of(ctx.action) == DEED:
        ctx.actor.turn_flags["hall_deed"] = True  # "You cannot also use a paid Deed Follows Word during that turn."


# ---------------------------------------------------------------------------------------------------------- the Hall: Willing Declarations
BENEFITS = {"move": "Move 10 feet without provoking Opportunity Attacks", "temp": "Gain Temporary Hit Points equal to 2 x the Fist's Proficiency Bonus",
            "save": "Advantage on your next Intelligence, Wisdom or Charisma save before the start of your next turn"}


def _ally_declares(engine: Any, fist: Any, ally: Any) -> None:
    """At the start of a chosen ally's turn in the Hall that ally may declare one deed: Challenge, Pursuit, Guard, Break or Hold."""
    from . import needle

    foes = sorted([c for c in engine.state.actors.values() if c.active and c.team_id != ally.team_id and engine._distance_actor_to_actor(ally, c) <= 60],
                  key=lambda c: (engine._distance_actor_to_actor(ally, c), c.entity_id))[:4]
    friends = [c for c in engine.state.actors.values() if c.active and c.team_id == ally.team_id and c is not ally and engine._distance_actor_to_actor(ally, c) <= 30][:3]
    options = {**{f"Challenge:{c.entity_id}": f"Challenge {c.display_name}" for c in foes}, **{f"Pursuit:{c.entity_id}": f"Pursue {c.display_name}" for c in foes},
               **{f"Guard:{c.entity_id}": f"Guard {c.display_name}" for c in friends}, f"Hold:{ally.entity_id}": "Hold (stay within 5 feet and defend)"}
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "HALL_DECLARATION", ally.entity_id), ally, "choice:needle.plain_truth.hall_declaration",
                        list(options), labels=options, preferred=list(options)[:1], allow_decline=True, name="Hall of Spoken Deeds", feature_id=HALL,
                        prompt=f"Hall of Spoken Deeds: declare a deed for this turn? ({fist.display_name}'s Hall)")
    if not chosen or chosen[0] not in options:
        return
    kind, _, subject_id = chosen[0].partition(":")
    subject = engine.state.actors[subject_id]
    engine._apply_condition(ally, DECLARED, HALL, ally.entity_id, expires_on="UNTIL_REMOVED",
                            data={"deed": kind, "subject": subject_id, "turn": int(ally.turns_started), "hall": fist.entity_id, "x": ally.position.x, "y": ally.position.y,
                                  "start_distance": engine._distance_actor_to_actor(ally, subject), "moved": 0, "since": len(engine.events),
                                  "label": f"Declared in the Hall: {options[chosen[0]]}"})


def _hall_benefit(engine: Any, ally: Any, fist: Any) -> None:
    """The ally completes the declared deed before the turn ends: one benefit is chosen (one benefit a turn)."""
    from . import needle

    if ally.turn_flags.get("hall_benefit"):
        return
    ally.turn_flags["hall_benefit"] = True
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "HALL_BENEFIT", ally.entity_id), ally, "choice:needle.plain_truth.hall_benefit",
                        list(BENEFITS), labels=BENEFITS, preferred=["temp"], name="Hall of Spoken Deeds", feature_id=HALL, prompt="Your deed is done: choose a benefit.")
    pick = chosen[0] if chosen and chosen[0] in BENEFITS else "temp"
    if pick == "temp":
        engine._grant_temp_hp(ally, 2 * _pb(engine, fist), HALL, fist.entity_id)
    elif pick == "save":
        _te().run_effects(st.context(engine, fist, st.feature_action(engine, fist, HALL), [ally], st.numbers(engine, fist)),
                          [{"type": "advantage", "applies_to": "target", "on": "its next Intelligence, Wisdom, or Charisma saving throw",
                            "duration": {"kind": "until_start_of_next_turn"}, "evidence": "gain Advantage on its next Intelligence, Wisdom, or Charisma saving throw"}])
    else:
        spots = {c: v for c, v in st.routes(engine, ally, 10).items() if c != ally.position}
        path = st.choose_route(engine, ally, spots, engine._active_intent, checkpoint="HALL_BENEFIT_MOVE", prompt="Move 10 feet without provoking?",
                               name="Hall of Spoken Deeds", feature=HALL) if spots else None
        if path is not None:
            from .rider_movement import step as walk

            walk(engine, ally, list(path), HALL)


@hook("turn_start")
def hall_declarations(engine: Any, actor: Any) -> None:
    if not actor.active or declaration(actor) is not None:
        return
    for fist in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if fist is not actor and fist.team_id == actor.team_id and fist.active and _in_hall(engine, fist, actor):
            _ally_declares(engine, fist, actor)
            return


# ---------------------------------------------------------------------------------------------------------- the Hall: Final Pronouncement
PRONOUNCEMENTS = {"face": "Face Me", "flee": "Do Not Flee", "release": "Release What Is Not Yours", "speak": "Speak the Deed"}
PRONOUNCED = "condition:typed.final_pronouncement"


@effect("truth_pronounce")
def pronounce(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, fist = ctx.engine, ctx.actor
    target = ctx.target or next(iter(ctx.targets or ()), None)
    zone = _hall(engine, fist)
    if target is None or zone is None:
        return
    zone.trigger_profile = {**zone.trigger_profile, "pronounced": True}  # "Once during the activation"
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=fist.entity_id, payload={"zone": zone.model_dump(mode="json")})
    kind = str(row.get("pronouncement"))
    sub = st.context(engine, fist, st.feature_action(engine, fist, HALL), [target], st.numbers(engine, fist), ctx.intent)
    if not st.save(sub, target, "cha"):
        _te().run_effects(sub, [{"type": "spiritual_pressure", "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"},
                                 "evidence": "Save succeeds: it suffers one ordinary Spiritual Pressure effect until your next turn starts."}])
        return
    engine._apply_condition(target, PRONOUNCED, HALL, fist.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"pronouncement": kind, "label": f"Final Pronouncement: {PRONOUNCEMENTS.get(kind, kind)} (until the start of {fist.display_name}'s next turn)"})
    if kind == "release":
        holds = [(c, iid, h) for c in engine.state.actors.values() for iid, h in c.conditions.items() if h.source_actor_id == target.entity_id and h.condition_id in _HOLDS]
        if holds:
            ids = [f"h{i}" for i in range(len(holds))]
            chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "PRONOUNCE_RELEASE", target.entity_id), fist, "choice:needle.plain_truth.release",
                                ids, labels={f"h{i}": f"{c.display_name}: {str(h.condition_id).rsplit('.', 1)[-1].title()}" for i, (c, _iid, h) in enumerate(holds)},
                                preferred=ids[:1], prompt="Release What Is Not Yours: which hold is released?", name="Final Pronouncement", feature_id=HALL)
            creature, _iid, held = holds[ids.index(chosen[0])] if chosen and chosen[0] in ids else holds[0]
            st.remove(engine, creature, held, "RELEASED")
    elif kind in ("flee", "speak"):
        note(engine, HALL, fist, f"Final Pronouncement ({PRONOUNCEMENTS[kind]}): the GM applies it to {target.display_name}.", (target,))


def _face_me(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Face Me: while the Fist is a legal target, the creature cannot willingly aim a hostile single-target effect at anyone else."""
    held = next((c for c in actor.conditions.values() if c.condition_id == PRONOUNCED and (c.data or {}).get("pronouncement") == "face"), None)
    fist = engine.state.actors.get(held.source_actor_id or "") if held is not None else None
    targets = tuple(getattr(candidate, "target_ids", None) or ())
    if fist is None or not fist.active or len(targets) != 1 or targets[0] == fist.entity_id:
        return None
    other = engine.state.actors.get(targets[0])
    if other is None or other.team_id == actor.team_id or not engine._target_in_range(actor, fist, action):
        return None
    return False
