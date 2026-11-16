"""Soulstring Dancer (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Soulstring Dancer: Choreography Strings, CL3 Threaded Step, CL6 Stolen Rhythm, CL10
Marionette Defense, CL14 Dance of Borrowed Limbs, CL18 Theater of Strings). No Spheres 5e or D&D 5.5e counterpart. Ownership rows:
combat/rules/feature_blocks.d/riders_c8.json (Threaded Step, Marionette Defense).

Choreography Strings (tradition text): the counted mark "Choreography String" (combat/ext/stacking_marks.py) -- up to three from you on a
creature, one placed a turn, the fight. When a creature fails a save against your Spirit Awakening feature you may place one (asked). A
bearer may use its Action ("Shake a Choreography String") for a Wisdom save against your Save DC; a success removes one String.

What runs:
  * Threaded Step: placing that String, you may move the creature 5 feet where you choose (forced, no Opportunity Attacks; a creature
    known to be of your CL or higher may make a Wisdom save to stay put). Dancer's Counterstep (once per round, asked, no Reaction):
    a String bearer moves willingly within 30 feet of you -- you move 5 feet without provoking.
  * Stolen Rhythm (typed, Bonus Action, 60 feet, 3 Resonance, a String bearer): Wisdom save. Failed: one String is consumed and you
    choose two effects until the start of your next turn (Speed -10, no Reactions, Disadvantage on its next weapon attack; the other
    three are the GM's) -- or, with three Strings, Catch the Beat: all three for Speed 0. Succeeded: one effect, no String spent.
  * Marionette Defense (Reaction, 4 Resonance, asked): you are hit while a String bearer within 30 feet could have been the attack's
    target -- it makes a Wisdom save (a willing ally may fail). Failed: a String is consumed, you move up to 10 feet without provoking,
    and the attack is turned from you (the GM applies the same roll to that creature). Succeeded: +2 AC against the attack, and a 5-foot
    move after it.
  * Dance of Borrowed Limbs (typed, Action, 60 feet, 6 Resonance, Concentration, a bearer of two Strings): Wisdom save. Failed: a String
    is consumed; at the start of each of its turns you choose a command (asked): Speed -10 for the turn, a 10-foot move you choose, fall
    Prone, or its Reaction spent; it repeats the save at the end of its turns (a success ends it and removes a String). Succeeded: a
    Spiritual Pressure effect.
  * Theater of Strings (typed zone, Action, 10 Resonance, the fight, 30 feet around you): a hostile creature starting its turn there that
    bears your Resonance Mark or failed your Spirit Awakening save since its last turn may receive a String (asked, once a round); once
    per round when a creature in it moves or attacks, you may move another String bearer 5 feet (asked); hostile String bearers make no
    Opportunity Attacks against you. "Final Choreography: <sequence>" (once, a bearer of three Strings in it): Wisdom save; failed, all
    three are consumed and Empty Turn (it loses its next Action), Broken Formation (a half-Speed move you choose and no Reactions until
    the end of its next turn) or Kneeling Beat (Prone, Speed 0 until the end of its next turn, and a Spiritual Pressure effect);
    succeeded, one String is removed and two different Spiritual Pressure effects.

Plug-in surface: effects string_rhythm, string_dance, string_theater, string_final, string_shake; hooks mark_apply, mark_consume,
after_save_resolved, event, hit_response, turn_start, turn_end, opportunity_allowed, compile_actions, candidate_allowed, match_start,
additional_actions. Public helper: ``strings``. Shared helpers used: spirit_traditions (context/numbers/feature_action/feature_of/
is_spirit_feature/pick_creature/routes/choose_route/can_react/save/remove/data_of/set_data), stacking_marks, rider_movement.step,
needle, zones.typed_zones, typed_executor.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.soulstring_dancer.feature."
THREADED = TRADITION + "threaded_step"
RHYTHM = TRADITION + "stolen_rhythm"
MARIONETTE = TRADITION + "marionette_defense"
BORROWED = TRADITION + "dance_of_borrowed_limbs"
THEATER = TRADITION + "theater_of_strings"
STRING = "Choreography String"
RESONANCE = "resource:core.resonance"
PUPPET = "condition:typed.borrowed_limbs"
EMPTY_TURN = "condition:typed.empty_turn"
SHAKE = "system:combat.shake_a_choreography_string"
_PENDING_HIT = "_marionette_pending"
# The engine preserves keys containing _round_ at turn start. Eligibility lasts
# until the target's turn ends, independently for each source dancer.
_FAILED_SAVE = "failed_spirit_save_round_:"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def strings(engine: Any, owner: Any, creature: Any) -> int:
    from .stacking_marks import count

    return count(engine, owner, creature, STRING) if owner is not None and creature is not None else 0


def _cl(engine: Any, creature: Any) -> int | None:
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == creature.entity_id), None)
    return int(bundle["cl"]) if bundle and bundle.get("cl") else None


def _ctx(engine: Any, dancer: Any, feature: str, targets: list[Any], intent: Any = None) -> Any:
    return st.context(engine, dancer, st.feature_action(engine, dancer, feature), targets, st.numbers(engine, dancer), intent)


def _place(engine: Any, dancer: Any, creature: Any, intent: Any, feature: str) -> None:
    _te().run_effects(_ctx(engine, dancer, feature, [creature], intent),
                      [{"type": "mark", "mark": STRING, "applies_to": "target", "duration": {"kind": "until_removed"}, "evidence": "place one Choreography String"}])


def _consume(engine: Any, dancer: Any, creature: Any, number: int, source: str) -> bool:
    from .stacking_marks import spend

    return spend(engine, dancer, creature, STRING, source, number)


def _walk(engine: Any, chooser: Any, mover: Any, feet: int, intent: Any, checkpoint: str, prompt: str, feature: str, *, stay: bool = True) -> None:
    spots = {c: v for c, v in st.routes(engine, mover, feet).items() if c != mover.position}
    path = st.choose_route(engine, chooser, spots, intent, checkpoint=checkpoint, prompt=prompt, name=prompt.split(":")[0], feature=feature, stay=stay) if spots else None
    if path is not None:
        from .rider_movement import step

        step(engine, mover, list(path), feature)


# ---------------------------------------------------------------------------------------------------------- Strings
@hook("mark_apply")
def choreography_string(ctx: Any, row: dict[str, Any], subject: Any, expires: str, data: dict[str, Any] | None) -> bool | None:
    """"A creature can bear up to three Choreography Strings from you ... You can place no more than one String on the same creature per turn.\""""
    if str(row.get("mark") or "") != STRING:
        return None
    from .stacking_marks import add

    flag = f"string_added:{subject.entity_id}"
    if ctx.actor.turn_flags.get(flag) or strings(ctx.engine, ctx.actor, subject) >= 3:
        return True
    ctx.actor.turn_flags[flag] = True
    add(ctx.engine, ctx.actor, subject, STRING, 1, ctx.source)
    return True


@hook("mark_consume")
def spend_string(ctx: Any, row: dict[str, Any], subject: Any) -> bool | None:
    if str(row.get("mark") or "") != STRING:
        return None
    return _consume(ctx.engine, ctx.actor, subject, max(1, int(row.get("count") or 1)), ctx.source)


def _dancers(engine: Any) -> list[Any]:
    return [a for a in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if st.row(engine, a, "threaded_step") is not None]


@hook("after_save_resolved")
def place_on_failure(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """"A creature gains one String when it fails a saving throw against one of your Spirit Awakening features and you choose to place one"
    -- with Threaded Step's 5-foot move."""
    from . import needle

    engine, dancer = ctx.engine, ctx.actor
    if not failed or subject is None or dancer is None or subject.team_id == dancer.team_id or not subject.active or not st.is_spirit_feature(ctx.action):
        return
    if st.row(engine, dancer, "threaded_step") is None:
        return
    subject.turn_flags[_FAILED_SAVE + dancer.entity_id] = engine.state.round_number
    if strings(engine, dancer, subject) >= 3 or dancer.turn_flags.get(f"string_added:{subject.entity_id}"):
        return
    if not needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "PLACE_STRING", subject.entity_id), dancer, "choice:needle.soulstring.place",
                      ["place"], labels={"place": f"Place a Choreography String on {subject.display_name} (Threaded Step: and move it 5 feet)"},
                      preferred=["place"], allow_decline=True, prompt=f"{subject.display_name} failed its save.", name="Threaded Step", feature_id=THREADED,
                      target_id=subject.entity_id):
        return
    _place(engine, dancer, subject, ctx.intent, THREADED)
    theirs, mine = _cl(engine, subject), int(st.numbers(engine, dancer).get("cl") or 1)
    if theirs is not None and theirs >= mine and not st.save(_ctx(engine, dancer, THREADED, [subject], ctx.intent), subject, "wis"):
        return  # a creature of equal or higher Source CL may make a Strength or Wisdom save to ignore the forced movement
    _walk(engine, dancer, subject, 5, ctx.intent, "THREADED_STEP", f"Threaded Step: move {subject.display_name} 5 feet?", THREADED)


# ---------------------------------------------------------------------------------------------------------- events: Counterstep, Theater
@hook("event")
def string_motion(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from . import needle

    payload = kwargs.get("payload") or {}
    mover = engine.state.actors.get(kwargs.get("actor_id") or "") if event_type == "MOVEMENT_COMMITTED" else None
    if mover is not None and (payload.get("forced") or payload.get("dragged_by") or engine.state.current_actor_id != mover.entity_id):
        if any(dancer.active and dancer.team_id != mover.team_id for dancer in _dancers(engine)):
            mover.turn_flags["moved_unwillingly_round_"] = engine.state.round_number  # for Theater of Strings: "moved unwillingly during the round"
    elif mover is not None:
        for dancer in _dancers(engine):
            # Dancer's Counterstep: once a round, when a creature bearing one of your Strings moves willingly inside 30 feet
            if (mover is None or mover is dancer or not dancer.active or strings(engine, dancer, mover) < 1 or engine._distance_actor_to_actor(dancer, mover) > 30
                    or dancer.turn_flags.get("counterstep_round_") == engine.state.round_number or engine.state.current_actor_id != mover.entity_id):
                continue
            if any(r.get("no_actions") or r.get("speed_zero") for r in _te().condition_rules(dancer)):
                continue  # "you cannot use it while Incapacitated or Restrained"
            dancer.turn_flags["counterstep_round_"] = engine.state.round_number
            _walk(engine, dancer, dancer, 5, engine._active_intent, "COUNTERSTEP", "Dancer's Counterstep: move 5 feet?", THREADED)
    motion_event = event_type in ("MOVEMENT_COMMITTED", "ATTACK_ROLLED", "STOOD_UP") or (
        event_type == "CONDITION_APPLIED" and str(payload.get("condition_id") or "").endswith(".prone"))
    if motion_event:
        actor_id = next(iter(kwargs.get("target_ids") or ()), "") if event_type == "CONDITION_APPLIED" else kwargs.get("actor_id")
        actor = engine.state.actors.get(actor_id or "")
        for dancer in _dancers(engine):
            zone = _theater(engine, dancer)
            if zone is None or actor is None:
                continue
            from ..spatial_areas import zone_contains
            if not zone_contains(engine, actor, zone):
                continue
            # "Once per round when a creature in the field moves, attacks ... you may move another String-bearing creature 5 feet"
            state = _theater_state(dancer)
            if state is None or st.data_of(dancer, state).get("moved_round") == engine.state.round_number:
                continue
            bearers = [c for c in engine.state.actors.values() if c.active and c is not actor and strings(engine, dancer, c) >= 1]
            other = st.pick_creature(engine, engine._active_intent, dancer, bearers, checkpoint="THEATER_MOVE", choice_id="choice:needle.soulstring.theater_move",
                                     prompt="Theater of Strings: move another String bearer 5 feet?", name="Theater of Strings", feature_id=THEATER, allow_decline=True)
            if other is None:
                continue
            st.set_data(dancer, state, moved_round=engine.state.round_number)
            _walk(engine, dancer, other, 5, engine._active_intent, "THEATER_STEP", f"Theater of Strings: move {other.display_name} where?", THEATER, stay=False)


# ---------------------------------------------------------------------------------------------------------- Stolen Rhythm
RHYTHMS = {"slow": "Speed reduced by 10 feet", "still": "cannot take Reactions", "clumsy": "Disadvantage on the next weapon attack",
           "no_help": "cannot benefit from an ally's Help (the GM's)", "heavy_rise": "5 more feet to stand or change elevation",
           "one_mode": "cannot use the same movement mode twice this turn (the GM's)"}


def _rhythm_rows(picks: list[str]) -> list[dict[str, Any]]:
    until = {"kind": "until_start_of_your_next_turn"}
    rows = {"slow": {"type": "speed", "applies_to": "target", "flat": -10, "duration": until, "evidence": "Speed reduced by 10 feet"},
            "still": {"type": "reaction_denied", "applies_to": "target", "duration": until, "evidence": "cannot take Reactions"},
            "clumsy": {"type": "disadvantage", "applies_to": "target", "on": "its next attack roll", "duration": until, "evidence": "Disadvantage on the next weapon attack"},
            "heavy_rise": {"type": "standing_burden", "applies_to": "target", "extra_ft": 5, "elevation": True, "duration": until,
                           "evidence": "must spend 5 additional feet of movement to stand from Prone"}}
    return [rows[p] if p in rows else {"type": "rider", "evidence": f"Stolen Rhythm: {RHYTHMS[p]}."} for p in picks]


@effect("string_rhythm")
def stolen_rhythm(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, dancer = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    if target is None or not target.active:
        return
    had = strings(engine, dancer, target)
    failed = st.save(ctx, target, "wis")
    if failed and had >= 3 and needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "CATCH_THE_BEAT", target.entity_id), dancer, "choice:needle.soulstring.catch",
                                          ["catch"], labels={"catch": f"Catch the Beat: consume all three Strings; {target.display_name}'s Speed becomes 0"},
                                          preferred=["catch"], allow_decline=True, prompt="Stolen Rhythm", name="Stolen Rhythm", feature_id=RHYTHM):
        _consume(engine, dancer, target, 3, RHYTHM)
        _te().run_effects(ctx, [{"type": "speed", "applies_to": "target", "becomes": 0, "duration": {"kind": "until_start_of_your_next_turn"},
                                 "evidence": "make its Speed 0 until the start of your next turn"}])
        return
    count = 2 if failed else 1
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "STOLEN_RHYTHM", target.entity_id), dancer, "choice:needle.soulstring.rhythm",
                        list(RHYTHMS), labels=RHYTHMS, preferred=["still", "slow"][:count], minimum=count, maximum=count, default="all",
                        prompt=f"Stolen Rhythm: choose {count} effect{'s' if count > 1 else ''} on {target.display_name}.", name="Stolen Rhythm", feature_id=RHYTHM,
                        target_id=target.entity_id)
    picks = [p for p in (chosen or ["still", "slow"][:count]) if p in RHYTHMS][:count]
    if failed:
        _consume(engine, dancer, target, 1, RHYTHM)
    _te().run_effects(ctx, _rhythm_rows(picks))


# ---------------------------------------------------------------------------------------------------------- Marionette Defense
@hook("hit_response")
def marionette_defense(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    """Marionette Defense (Reaction, 4 Resonance), on a hit against you while a creature bearing one of your Choreography Strings
    is within 30 feet."""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _PENDING_HIT)
    from . import needle

    dancer = target
    if (st.row(engine, dancer, "marionette_defense") is None or attacker is None or not st.can_react(dancer) or dancer.resources.get(RESONANCE, 0) < 4
            or attacker.team_id == dancer.team_id):
        return None
    reach = int(spec.get("range_ft") or spec.get("reach_ft") or 5)
    bearers = [c for c in engine.state.actors.values() if c.active and c is not dancer and c is not attacker and strings(engine, dancer, c) >= 1
               and engine._distance_actor_to_actor(dancer, c) <= 30 and engine._distance_actor_to_actor(attacker, c) <= reach]
    if not bearers:
        return None
    chosen = st.pick_creature(engine, engine._active_intent, dancer, bearers, checkpoint="MARIONETTE_DEFENSE", choice_id="choice:needle.soulstring.marionette",
                              prompt=f"Marionette Defense (Reaction, 4 Resonance): {attacker.display_name} hits you -- which String bearer takes its place?",
                              name="Marionette Defense", feature_id=MARIONETTE, allow_decline=True)
    if chosen is None:
        return None
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, dancer, MARIONETTE, independent=True):
        dancer.reaction_available = False
        engine._spend_resource(dancer, RESONANCE, 4, MARIONETTE)
        engine._append_event("REACTION_RESOLVED", MARIONETTE, actor_id=dancer.entity_id, target_ids=(chosen.entity_id,),
                             payload={"checkpoint": "ATTACK_HIT", "reaction_name": "Marionette Defense"})
        willing = chosen.team_id == dancer.team_id and needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "DANCE_PARTNER", chosen.entity_id), chosen,
                                                                  "choice:needle.soulstring.partner", ["fail"], labels={"fail": "Dance Partner: fail the save willingly"},
                                                                  preferred=["fail"], allow_decline=True, prompt="Marionette Defense", name="Marionette Defense",
                                                                  feature_id=MARIONETTE)
        failed = True if willing else st.save(_ctx(engine, dancer, MARIONETTE, [chosen]), chosen, "wis")
        if failed:
            _consume(engine, dancer, chosen, 1, MARIONETTE)
            _walk(engine, dancer, dancer, 10, engine._active_intent, "MARIONETTE_MOVE", "Marionette Defense: move up to 10 feet?", MARIONETTE)
            note(engine, MARIONETTE, dancer, f"Marionette Defense: {attacker.display_name}'s attack (total {total}) turns to {chosen.display_name}"
                                             + (" (Dance Partner: it has Resistance to the damage)" if willing else "") + " -- the GM applies it.", (chosen, attacker))
            from ..attack_outcomes import unconditional_miss

            return unconditional_miss()
        from ..paid_relocation import capture, retain
        retain(engine, (_PENDING_HIT, dancer.entity_id), capture(engine))
        engine.__dict__[_PENDING_HIT] = dancer.entity_id
        if natural == 20 or total >= effective_ac + 2:
            return None
        return effective_ac + 2, False  # "You gain +2 AC against the triggering attack"


@hook("event")
def marionette_after(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"... and may move 5 feet after it resolves.\""""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _PENDING_HIT)
    if event_type not in ("DAMAGE_COMMITTED", "ATTACK_ROLLED") or not engine.__dict__.get(_PENDING_HIT):
        return
    if event_type == "ATTACK_ROLLED" and (kwargs.get("payload") or {}).get("provisional_hit"):
        return
    dancer = engine.state.actors.get(engine.__dict__.pop(_PENDING_HIT))
    if dancer is not None and dancer.active:
        from ..paid_relocation import causal_scope, take
        with causal_scope(engine, take(engine, (_PENDING_HIT, dancer.entity_id))):
            _walk(engine, dancer, dancer, 5, engine._active_intent, "MARIONETTE_AFTER", "Marionette Defense: move 5 feet?", MARIONETTE)


# ---------------------------------------------------------------------------------------------------------- Dance of Borrowed Limbs
COMMANDS = {"slow": "lose 10 feet of Speed this turn", "walk": "move up to 10 feet along a path you choose", "prone": "fall Prone", "drop": "drop one removable held object",
            "reaction": "spend its Reaction on a harmless gesture"}


@effect("string_dance")
def borrowed_limbs(ctx: Any, row: dict[str, Any]) -> None:
    engine, dancer = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    if target is None or not target.active:
        return
    if not st.save(ctx, target, "wis"):
        _te().run_effects(ctx, [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "The target suffers one ordinary Spiritual Pressure effect"}])
        return
    _consume(engine, dancer, target, 1, BORROWED)
    engine._apply_condition(target, PUPPET, ctx.source, dancer.entity_id, expires_on="CONCENTRATION_END" if dancer.concentration is not None else "UNTIL_REMOVED",
                            data={"label": f"Dance of Borrowed Limbs: {dancer.display_name} commands its body at the start of its turns"})


def _puppeteer(engine: Any, creature: Any) -> tuple[Any, Any]:
    held = next((c for c in creature.conditions.values() if c.condition_id == PUPPET), None)
    dancer = engine.state.actors.get(held.source_actor_id or "") if held is not None else None
    if dancer is not None and (dancer.concentration is None or not dancer.active):
        st.remove(engine, creature, held, "CONCENTRATION_ENDED")
        return None, None
    return held, dancer


@hook("turn_start")
def puppet_turn(engine: Any, actor: Any) -> None:
    from . import needle

    for held in [c for c in actor.conditions.values() if c.condition_id == EMPTY_TURN]:
        actor.action_available = False  # Empty Turn: "It loses its Action on its next turn"
        st.remove(engine, actor, held, "USED")
    held, dancer = _puppeteer(engine, actor)
    if held is None or dancer is None or not actor.active:
        _theater_placement(engine, actor)
        return
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "BORROWED_LIMBS", actor.entity_id), dancer, "choice:needle.soulstring.command",
                        list(COMMANDS), labels=COMMANDS, preferred=["reaction"], prompt=f"Dance of Borrowed Limbs: command {actor.display_name}'s body.",
                        name="Dance of Borrowed Limbs", feature_id=BORROWED, target_id=actor.entity_id)
    pick = chosen[0] if chosen and chosen[0] in COMMANDS else "reaction"
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, dancer, BORROWED, independent=True):
        sub = _ctx(engine, dancer, BORROWED, [actor])
        if pick == "slow":
            _te().run_effects(sub, [{"type": "speed", "applies_to": "target", "flat": -10, "duration": {"kind": "until_end_of_next_turn"}, "evidence": "lose 10 feet of Speed"}])
        elif pick == "walk":
            _walk(engine, dancer, actor, 10, engine._active_intent, "BORROWED_WALK", f"Dance of Borrowed Limbs: move {actor.display_name} where?", BORROWED, stay=False)
        elif pick == "prone":
            _te().run_effects(sub, [{"type": "condition", "applies_to": "target", "condition": "prone", "duration": {"kind": "until_removed"}, "evidence": "fall Prone"}])
        elif pick == "drop":
            st.drop_held(engine, dancer, actor, BORROWED, triggering_command="Dance of Borrowed Limbs: Drop")
        else:
            actor.reaction_available = False  # "spend its Reaction making a harmless involuntary gesture"
    _theater_placement(engine, actor)


@hook("turn_end")
def puppet_saves(engine: Any, actor: Any) -> None:
    """Puppet: the target repeats the save at the end of each of its turns, and each success ends one remaining String, the whole
    feature ending when none is left."""
    # Clear the interval before resolving end-turn saves: a new failure at this
    # boundary qualifies for the following turn. Old unowned flags cannot safely
    # identify a dancer, so ignore them for placement and retire them here too.
    for key in list(actor.turn_flags):
        if key.startswith(_FAILED_SAVE) or key == "failed_spirit_save_round_":
            actor.turn_flags.pop(key)
    held, dancer = _puppeteer(engine, actor)
    if held is None or dancer is None:
        return
    if not st.save(_ctx(engine, dancer, BORROWED, [actor]), actor, "wis"):
        st.remove(engine, actor, held, "SAVED")
        _consume(engine, dancer, actor, 1, BORROWED)


# ---------------------------------------------------------------------------------------------------------- Theater of Strings
THEATER_STATE = "condition:typed.theater_of_strings"


def _theater(engine: Any, dancer: Any) -> Any:
    from .. import zones

    return next((z for z in zones.typed_zones(engine) if z.owner_id == dancer.entity_id and st.feature_of(engine.action_catalog.get(z.source_definition_id)) == THEATER), None)


def _theater_state(dancer: Any) -> Any:
    return next((c for c in dancer.conditions.values() if c.condition_id == THEATER_STATE and c.source_actor_id == dancer.entity_id), None)


@hook("stand_cost")
def theater_standing(engine: Any, actor: Any, normal_cost: int) -> int | None:
    """You and willing allies in the field can stand using 5 feet."""
    from ..spatial_areas import zone_contains
    return 5 if any(d.team_id == actor.team_id and (zone := _theater(engine, d)) is not None
                    and zone_contains(engine, actor, zone) for d in _dancers(engine)) else None


@effect("string_theater")
def theater(ctx: Any, row: dict[str, Any]) -> None:
    held = _theater_state(ctx.actor)
    if held is not None:
        st.remove(ctx.engine, ctx.actor, held, "REPLACED")
    ctx.engine._apply_condition(ctx.actor, THEATER_STATE, THEATER, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data={"label": "Theater of Strings"})


def _theater_placement(engine: Any, actor: Any) -> None:
    """Theater of Strings: at the start of a hostile creature's turn in the field the dancer may put one Choreography String on it
    when it is Resonance Marked by the dancer, failed a Spirit Awakening save since its last turn ended, or moved unwillingly during
    the round."""
    from . import needle

    for dancer in _dancers(engine):
        zone = _theater(engine, dancer)
        if zone is None or actor.team_id == dancer.team_id or not actor.active or not engine._footprint_intersects(actor, zone.affected_cells):
            continue
        key = f"theater_string_round_{actor.entity_id}"
        if dancer.turn_flags.get(key) == engine.state.round_number or strings(engine, dancer, actor) >= 3:
            continue
        if not (_te().bears_mark(actor, dancer.entity_id, "Resonance") or actor.turn_flags.get(_FAILED_SAVE + dancer.entity_id)
                or actor.turn_flags.get("moved_unwillingly_round_") == engine.state.round_number):
            continue
        if needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "THEATER_STRING", actor.entity_id), dancer, "choice:needle.soulstring.theater_string",
                      ["place"], labels={"place": f"Place a Choreography String on {actor.display_name}"}, preferred=["place"], allow_decline=True,
                      prompt="Theater of Strings", name="Theater of Strings", feature_id=THEATER, target_id=actor.entity_id):
            from ..paid_relocation import activation as relocation_activation
            with relocation_activation(engine, dancer, THEATER, independent=True):
                dancer.turn_flags[key] = engine.state.round_number
                _place(engine, dancer, actor, engine._active_intent, THEATER)


@hook("opportunity_allowed")
def no_strike_at_the_dancer(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """"Hostile String-bearing creatures cannot take Opportunity Attacks against you.\""""
    if mover is None or reactor is None or _theater(engine, mover) is None or reactor.team_id == mover.team_id:
        return None
    return False if strings(engine, mover, reactor) >= 1 else None


FINALS = {"empty": "Empty Turn: it loses its Action on its next turn", "broken": "Broken Formation: move it half its Speed, and no Reactions until the end of its next turn",
          "kneeling": "Kneeling Beat: Prone, Speed 0 until the end of its next turn, and a Spiritual Pressure effect"}


@effect("string_final")
def final_choreography(ctx: Any, row: dict[str, Any]) -> None:
    engine, dancer = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    held = _theater_state(dancer)
    if target is None or held is None:
        return
    st.set_data(dancer, held, final_used=True)  # "Once during the activation"
    if not st.save(ctx, target, "wis"):
        _consume(engine, dancer, target, 1, THEATER)
        _te().run_effects(ctx, [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "two different ordinary Spiritual Pressure effects"},
                                {"type": "spiritual_pressure", "applies_to": "target", "different": True, "evidence": "until the start of its next turn"}])
        return
    _consume(engine, dancer, target, 3, THEATER)
    until = {"kind": "until_end_of_next_turn"}
    sequence = row.get("sequence")
    if sequence == "empty":
        engine._apply_condition(target, EMPTY_TURN, THEATER, dancer.entity_id, expires_on="UNTIL_REMOVED", data={"label": "Empty Turn: it loses its next Action"})
    elif sequence == "broken":
        _walk(engine, dancer, target, max(5, engine._effective_speed(target) // 2), ctx.intent, "BROKEN_FORMATION", f"Broken Formation: move {target.display_name} where?",
              THEATER, stay=False)
        _te().run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "duration": until, "evidence": "it cannot take Reactions until the end of its next turn"}])
    else:
        _te().run_effects(ctx, [{"type": "condition", "applies_to": "target", "condition": "prone", "duration": {"kind": "until_removed"}, "evidence": "It falls Prone"},
                                {"type": "speed", "applies_to": "target", "becomes": 0, "duration": until, "evidence": "its Speed becomes 0 until the end of its next turn"},
                                {"type": "spiritual_pressure", "applies_to": "target", "evidence": "it suffers one Spiritual Pressure effect"}])


# ---------------------------------------------------------------------------------------------------------- buttons and gates
@hook("match_start")
def shake_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[SHAKE] = ActionDefinition(
        source_definition_id=SHAKE, display_name="Shake a Choreography String", owner_id="*", economy=EconomyKind.ACTION, resolution_kind="TYPED",
        target_kind="SELF", parameters={"typed": {"effects": [{"type": "string_shake"}], "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
                                        "expected_damage": 0, "string_shake": True,
                                        "description": "You bear a Choreography String: use your Action for a Wisdom saving throw against the dancer's Cultivation "
                                                       "Save DC; a success removes one String."})


def _string_owners(engine: Any, actor: Any) -> list[Any]:
    return [d for d in _dancers(engine) if strings(engine, d, actor) >= 1]


@hook("additional_actions")
def shake_offered(engine: Any, actor: Any) -> list[str]:
    return [SHAKE] if _string_owners(engine, actor) else []


@effect("string_shake")
def shake(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    for dancer in _string_owners(engine, actor):
        if not st.save(_ctx(engine, dancer, THREADED, [actor], ctx.intent), actor, "wis"):
            _consume(engine, dancer, actor, 1, THREADED)  # "A creature can use an Action to attempt a Wisdom saving throw, removing one String on a success."
            note(engine, THREADED, actor, f"{actor.display_name} shakes off one of {dancer.display_name}'s Choreography Strings.")
        return


@hook("compile_actions")
def final_buttons(info: dict[str, Any]) -> list[Any] | None:
    if THEATER not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.soulstring.final.{key}", display_name=f"Final Choreography: {label.split(':')[0]}",
                             owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60,
                             parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": THEATER + ":final",
                                                   "effects": [{"type": "string_final", "applies_to": "target", "harmful": True, "sequence": key}]},
                                         "expected_damage": 0, "soulstring_final": key,
                                         "description": f"Theater of Strings (once; a creature in it bearing three of your Strings; Wisdom save): {label}. "
                                                        "On a success it loses one String and suffers two different Spiritual Pressure effects."})
            for key, label in FINALS.items()]


@hook("candidate_allowed")
def string_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    params = action.parameters or {}
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if params.get("soulstring_final"):
        zone, held = _theater(engine, actor), _theater_state(actor)
        if zone is None or held is None or st.data_of(actor, held).get("final_used") or target is None:
            return False
        return None if strings(engine, actor, target) >= 3 and engine._footprint_intersects(target, zone.affected_cells) else False
    feature = st.feature_of(action)
    if feature == RHYTHM and target is not None:
        return None if strings(engine, actor, target) >= 1 else False  # "Requirement: The target bears at least one Choreography String"
    if feature == BORROWED and target is not None:
        return None if strings(engine, actor, target) >= 2 else False  # "Requirement: The target bears at least two Choreography Strings"
    return None
