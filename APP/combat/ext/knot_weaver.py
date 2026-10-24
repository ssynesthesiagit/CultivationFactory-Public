"""Knot Weaver (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Knot Weaver: Observed Ties, Knot Tension, CL3 Red Thread Sense, CL6 Tie the
Moment, CL10 Binding Knot, CL14 Sever the False Thread, CL18 Knot of Inevitability). No Spheres 5e or D&D 5.5e counterpart.
Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json (Red Thread Sense for Ties and Tension, Tie
the Moment); the actions need none.

Observed Ties (tradition text): up to PB relationships you have diagnosed, each between two creatures in the fight, for the fight;
recording one more ends the oldest (asked which). The table cannot see relationships: Red Thread Sense asks you for the other side
and the GM confirms the tie is real. Knot Tension: a pool (resource:named.knot_tension), 0 to start, maximum PB.

What runs:
  * Red Thread Sense (Action, 60 feet, 1 Resonance): record an Observed Tie between the target and the creature you name. Tug the
    Visible Thread (once per turn, when your Resonance Mark lands on a creature in a Tie; asked): it moves 5 feet toward or away from
    the other side.
  * Knot Tension: +1 (at most 1 a turn) when a hostile creature within 60 feet acts through its Tie -- its Action or Bonus Action
    attacks, damages, saves against or heals the other side of the Tie.
  * Tie the Moment (Reaction, 3 Resonance or 1 Knot Tension; asked): a Resonance Marked creature within 60 feet in a Tie makes an
    attack roll or saving throw -- subtract 1d6 before the outcome; or it willingly moves 10 feet or more -- the move ends 10 feet
    short (it steps back along its path), or, if it moved away from the other side, it is pulled 5 feet back toward it.
  * Binding Knot (Action, 60 feet, 5 Resonance, the fight): the two sides of one of your Ties (asked which Tie); each creature not on
    your side makes a Charisma save (yours count as willing); both fail or consent -> a Knot of your chosen form: Burden (once per
    round when one side takes Psychic, Force or Necrotic damage, the other takes Wisdom + PB Psychic), Distance (a side ending its
    turn more than 60 feet from the other makes a Charisma save or has Speed 0 until the start of its next turn and is pulled 10 feet
    toward it), Guardian (once per round when one side takes damage, the other may use its Reaction to take half of it instead). An
    unwilling side repeats the save at the end of its turns; a success breaks the Knot.
  * Sever the False Thread (Action, 60 feet, 6 Resonance): one Charmed or Frightened a hostile creature put on a creature -- a
    Cultivation Check (d20 + PB + Wisdom) against its DC: success ends it if its source's CL is below yours, else suppresses it (for
    the fight if equal, until the end of your next turn if higher); failure gives the creature Advantage on its next save against it.
  * Knot of Inevitability (Bonus Action, 60 feet, 10 Resonance and all Knot Tension, at least 1; a Resonance Marked creature in a
    Tie): a Great Knot Anchor object within 30 feet (AC your DC, 8 x PB Hit Points; destroying it ends the Knot) and one consequence
    (asked): Remain (it cannot willingly move more than 30 feet from the other side), Face (while the other side is a legal target,
    its hostile actions target only that side), Protect (it cannot willingly harm the other side, and uses its Reaction to cut one
    blow to that side by 2 x PB). Its Charisma save at creation and at the end of each of its turns: failed, bound until the next
    save (three failures against a lower-CL Weaver: bound while the Anchor stands); success, resists until the start of its next
    turn and suffers two different Spiritual Pressure effects.

Plug-in surface: effects knot_red_thread, knot_binding, knot_sever, knot_inevitability; hooks mark_applied, action_completed, d20_bonus,
event, incoming_damage, turn_end, candidate_allowed. Public helpers: ``ties``, ``other_side``, ``gain_tension``. Shared helpers used:
spirit_traditions (row/context/numbers/feature_action/can_react/pick_creature/routes/save/remove/suppress), end_effect (found/
source_cl/remove_instance/suppress), rider_movement.forced_route, needle.ask, d20_rewrite.context_of, typed_executor.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

COERCIVE_CONDITIONS = ["charmed", "frightened", "captivated", "possessed", "possession", "compulsion", "emotional_manipulation", "hostile_sympathetic_link", "false_memory_bond"]

TRADITION = "tianxia.tradition.spirit.knot_weaver.feature."
SENSE = TRADITION + "red_thread_sense"
TIE_MOMENT = TRADITION + "tie_the_moment"
BINDING = TRADITION + "binding_knot"
SEVER = TRADITION + "sever_the_false_thread"
INEVITABLE = TRADITION + "knot_of_inevitability"
TIE = "condition:typed.observed_tie"
KNOT = "condition:typed.binding_knot"
GREAT = "condition:typed.great_knot"
ANCHOR = "object:typed.great_knot:"
TENSION = "resource:named.knot_tension"
RESONANCE = "resource:core.resonance"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def ties(weaver: Any) -> list[Any]:
    return sorted((c for c in weaver.conditions.values() if c.condition_id == TIE and c.source_actor_id == weaver.entity_id), key=lambda c: c.applied_sequence)


def other_side(engine: Any, weaver: Any, creature: Any) -> list[Any]:
    """The creatures tied to ``creature`` in the weaver's Observed Ties."""
    out = []
    for tie in ties(weaver):
        a, b = (tie.data or {}).get("a"), (tie.data or {}).get("b")
        if creature.entity_id in (a, b):
            other = engine.state.actors.get(b if a == creature.entity_id else a)
            if other is not None and other.active:
                out.append(other)
    return out


def gain_tension(engine: Any, weaver: Any, source: str) -> bool:
    token = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    if weaver.turn_flags.get("knot_round_tension") == token or weaver.resources.get(TENSION, 0) >= weaver.resource_maximums.get(TENSION, 0):
        return False
    weaver.turn_flags["knot_round_tension"] = token  # "no more than 1 Knot Tension per turn"
    engine._gain_resource(weaver, TENSION, 1, source)
    return True


def _pos(cell: Any) -> Any:
    from ..gate2_runtime_models import Position

    return Position(x=int(cell[0]), y=int(cell[1]))


def _nudge_path(engine: Any, creature: Any, toward: Any, feet: int, *, closer: bool) -> list[Any]:
    """A straight forced path of up to ``feet`` that brings ``creature`` closer to (or farther from) ``toward``."""
    path = [creature.position]
    for _ in range(max(1, feet // engine.grid.square_size_ft)):
        here = path[-1]
        options = [_pos((here.x + dx, here.y + dy)) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
        options = [p for p in options if engine.grid.step_legal(here, p, occupied_cells=engine._occupied_cells_except(creature.entity_id),
                                                               footprint=engine._footprint(creature))]
        now = engine._distance_actor_to_actor(creature, toward, actor_position=here)
        scored = sorted(options, key=lambda p: (engine._distance_actor_to_actor(creature, toward, actor_position=p) * (1 if closer else -1), p.y, p.x))
        best = next((p for p in scored if (engine._distance_actor_to_actor(creature, toward, actor_position=p) < now) == closer
                     and engine._distance_actor_to_actor(creature, toward, actor_position=p) != now), None)
        if best is None or (closer and engine._distance_actor_to_actor(creature, toward, actor_position=best) < 5):
            break
        path.append(best)
    return path


def _shove(engine: Any, weaver: Any, creature: Any, toward: Any, feet: int, closer: bool, source: str) -> None:
    from .rider_movement import forced_route

    path = _nudge_path(engine, creature, toward, feet, closer=closer)
    if len(path) > 1:
        forced_route(engine, creature, path, source, weaver)


# ---------------------------------------------------------------------------------------------------------- Red Thread Sense
@effect("knot_red_thread")
def red_thread(ctx: Any, row: dict[str, Any]) -> None:
    engine, weaver, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    others = [c for c in engine.state.actors.values() if c.active and c is not target]
    other = st.pick_creature(engine, ctx.intent, weaver, others, checkpoint="RED_THREAD_OTHER", choice_id="choice:needle.knot_weaver.other_side",
                             prompt=f"Red Thread Sense: {target.display_name} is tied to whom? (The GM confirms the relationship.)", name="Red Thread Sense",
                             feature_id=SENSE, preferred=min((c for c in others if c.team_id == target.team_id), key=lambda c: (engine._distance_actor_to_actor(target, c), c.entity_id), default=None))
    if other is None:
        return
    held = ties(weaver)
    for tie in held:
        if {(tie.data or {}).get("a"), (tie.data or {}).get("b")} == {target.entity_id, other.entity_id}:
            st.remove(engine, weaver, tie, "REPLACED")
            held = ties(weaver)
    limit = max(1, int(st.numbers(engine, weaver).get("pb") or 2))
    if len(held) >= limit:  # "Recording a new Tie beyond your maximum ends one of your choice"
        from . import needle

        ids = [f"t{i}" for i in range(len(held))]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "TIE_TO_END", weaver.entity_id), weaver, "choice:needle.knot_weaver.end_tie",
                            ids, labels={f"t{i}": str((t.data or {}).get("label")) for i, t in enumerate(held)}, preferred=ids[:1],
                            prompt="Observed Ties are full: which one ends?", name="Red Thread Sense", feature_id=SENSE)
        st.remove(engine, weaver, held[ids.index(chosen[0])] if chosen and chosen[0] in ids else held[0], "REPLACED")
    engine._apply_condition(weaver, TIE, SENSE, weaver.entity_id, expires_on="UNTIL_REMOVED",
                            data={"a": target.entity_id, "b": other.entity_id, "label": f"Observed Tie: {target.display_name} and {other.display_name}"})


@hook("mark_applied")
def tug_the_thread(ctx: Any, name: str, subject: Any) -> None:
    """Tug the Visible Thread: once per turn when you place or refresh a Resonance Mark on a creature in one of your Ties."""
    engine, weaver = ctx.engine, ctx.actor
    te = _te()
    if (subject is None or not subject.active or st.row(engine, weaver, "red_thread_sense") is None or weaver.turn_flags.get("tugged_thread")
            or te.mark_condition_id(str(name), weaver.entity_id) != te.mark_condition_id("Resonance", weaver.entity_id)):
        return
    others = other_side(engine, weaver, subject)
    if not others:
        return
    from . import needle

    other = others[0]
    options = {"toward": f"Move {subject.display_name} 5 feet toward {other.display_name}", "away": f"Move {subject.display_name} 5 feet away from {other.display_name}"}
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "TUG_THREAD", subject.entity_id), weaver, "choice:needle.knot_weaver.tug",
                        list(options), labels=options, preferred=[], allow_decline=True, default="decline", name="Tug the Visible Thread",
                        feature_id=SENSE, target_id=subject.entity_id, prompt="Tug the Visible Thread?")
    if not chosen or chosen[0] not in options:
        return
    weaver.turn_flags["tugged_thread"] = True  # "Once per turn"
    _shove(engine, weaver, subject, other, 5, chosen[0] == "toward", SENSE)


# ---------------------------------------------------------------------------------------------------------- Knot Tension
def _activation(engine: Any, actor: Any) -> list[Any]:
    for index in range(len(engine.events) - 1, -1, -1):
        if engine.events[index].event_type == "INTENT_ACCEPTED" and engine.events[index].actor_id == actor.entity_id:
            return engine.events[index:]
    return []


@hook("action_completed")
def through_the_tie(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    if actor is None:
        return
    events = None
    for weaver in engine.state.actors.values():
        if not weaver.active or weaver.team_id == actor.team_id or st.row(engine, weaver, "red_thread_sense") is None:
            continue
        others = {o.entity_id for o in other_side(engine, weaver, actor)}
        if not others or engine._distance_actor_to_actor(weaver, actor) > 60:
            continue
        events = events if events is not None else _activation(engine, actor)
        if any(e.event_type in ("ATTACK_ROLLED", "DAMAGE_COMMITTED", "HEALING_APPLIED", "TEMP_HP_GRANTED", "CONDITION_APPLIED", "MODIFIER_APPLIED")
               and others & set(e.target_ids or ()) or (e.event_type == "SAVE_ROLLED" and e.actor_id in others) for e in events):
            gain_tension(engine, weaver, SENSE)  # "acts through an Observed Tie"


# ---------------------------------------------------------------------------------------------------------- Tie the Moment
def _pay_options(weaver: Any) -> list[str]:
    return [*(["tension"] if weaver.resources.get(TENSION, 0) >= 1 else []), *(["resonance"] if weaver.resources.get(RESONANCE, 0) >= 3 else [])]


def _pay(engine: Any, weaver: Any, how: str, what: str, creature: Any) -> None:
    if how == "tension":
        engine._spend_resource(weaver, TENSION, 1, TIE_MOMENT)
    else:
        engine._spend_resource(weaver, RESONANCE, 3, TIE_MOMENT)
    weaver.reaction_available = False
    engine._append_event("REACTION_RESOLVED", TIE_MOMENT, actor_id=weaver.entity_id, target_ids=(creature.entity_id,),
                         payload={"checkpoint": what, "reaction_name": "Tie the Moment"})


def _tugger(engine: Any, creature: Any) -> list[tuple[Any, list[Any]]]:
    out = []
    for weaver in engine.state.actors.values():
        if (not weaver.active or weaver.team_id == creature.team_id or st.row(engine, weaver, "tie_the_moment") is None or not st.can_react(weaver)
                or not _pay_options(weaver) or engine._distance_actor_to_actor(weaver, creature) > 60
                or not _te().bears_mark(creature, weaver.entity_id, "Resonance")):
            continue
        others = other_side(engine, weaver, creature)
        if others:
            out.append((weaver, others))
    return out


def _ask_pay(engine: Any, weaver: Any, creature: Any, options: dict[str, str], intent: Any, preferred: list[str], key: str) -> tuple[str, str] | None:
    from . import needle

    pays = _pay_options(weaver)
    labelled = {f"{k}|{p}": f"{v} ({'1 Knot Tension' if p == 'tension' else '3 Resonance'})" for k, v in options.items() for p in pays}
    order = [f"{k}|{p}" for k in preferred for p in pays]
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, f"TIE_THE_MOMENT_{key}", creature.entity_id), weaver, "choice:needle.knot_weaver.tie_the_moment",
                        list(labelled), labels=labelled, preferred=order[:1], allow_decline=True, default="first" if order else "decline",
                        automatic=bool(order), name="Tie the Moment", feature_id=TIE_MOMENT, target_id=creature.entity_id,
                        prompt=f"Tie the Moment (your Reaction): tug {creature.display_name}'s thread?")
    if not chosen or chosen[0] not in labelled:
        return None
    what, how = chosen[0].split("|", 1)
    return what, how


@hook("d20_bonus")
def tug_the_roll(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    if engine.__dict__.get("_c8_tugging") or roll.natural_result is None:
        return None
    from .d20_rewrite import context_of

    rc = context_of(engine, roll)
    if rc is None or rc.kind not in ("attack", "save"):
        return None
    for weaver, others in _tugger(engine, rc.roller):
        target_number = rc.ac if rc.kind == "attack" else rc.dc
        worth = target_number is not None and 0 <= int(roll.total) - int(target_number) < 6 and rc.natural != 20
        picked = _ask_pay(engine, weaver, rc.roller, {"subtract": "Subtract 1d6 from the roll"}, intent, ["subtract"] if worth else [], "ROLL")
        if picked is None:
            continue
        with activation(engine, weaver, TIE_MOMENT):
            _pay(engine, weaver, picked[1], "D20_BONUS", rc.roller)
            from ..gate2_runtime_models import DiceSpec

            engine.__dict__["_c8_tugging"] = True
            try:
                die = engine.roller.roll(DiceSpec(count=1, sides=6, modifier=0), actor_id=weaver.entity_id, reason=f"D20_BONUS:{TIE_MOMENT}")
            finally:
                engine.__dict__.pop("_c8_tugging", None)
            engine._record_roll(die)
            note(engine, TIE_MOMENT, weaver, f"Tie the Moment: -{die.total} on {rc.roller.display_name}'s roll.", (rc.roller,))
            return {"source_id": TIE_MOMENT, "bonus": -int(die.total)}
    return None


@hook("event")
def tug_the_move(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    path = payload.get("path") or []
    if (mover is None or not mover.active or payload.get("forced") or payload.get("dragged_by") or "planned_cost_ft" not in payload
            or (len(path) - 1) * engine.grid.square_size_ft < 10):
        return  # "willingly moves 10 feet or more" (a move of its own)
    for weaver, others in _tugger(engine, mover):
        start = _pos((path[0]["x"], path[0]["y"]))
        away = any(engine._distance_actor_to_actor(mover, o) > engine._distance_actor_to_actor(mover, o, actor_position=start) for o in others)
        options = {"shorten": "Its move ends 10 feet short", **({"pull": f"Pull it 5 feet back toward {others[0].display_name}"} if away else {})}
        picked = _ask_pay(engine, weaver, mover, options, engine._active_intent, ["pull"] if away else [], "MOVE")
        if picked is None:
            continue
        with activation(engine, weaver, TIE_MOMENT):
            _pay(engine, weaver, picked[1], "MOVEMENT", mover)
            if picked[0] == "pull":
                _shove(engine, weaver, mover, others[0], 5, True, TIE_MOMENT)
            else:
                back = [_pos((p["x"], p["y"])) for p in path][-3::-1][:1]
                if back and engine.grid.placement_legal(back[0], footprint=engine._footprint(mover), occupied_cells=engine._occupied_cells_except(mover.entity_id)):
                    from . import needle

                    needle.step_to(engine, mover, back[0], TIE_MOMENT)
            return


# ---------------------------------------------------------------------------------------------------------- Binding Knot
def _knots(engine: Any, creature: Any) -> list[tuple[Any, Any, Any]]:
    """(weaver, knot condition, other side) for every Binding Knot the creature is a side of."""
    out = []
    for weaver in engine.state.actors.values():
        for knot in [c for c in weaver.conditions.values() if c.condition_id == KNOT and c.source_actor_id == weaver.entity_id]:
            a, b = (knot.data or {}).get("a"), (knot.data or {}).get("b")
            if creature.entity_id in (a, b):
                other = engine.state.actors.get(b if a == creature.entity_id else a)
                if other is not None:
                    out.append((weaver, knot, other))
    return out


@effect("knot_binding")
def binding(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, weaver = ctx.engine, ctx.actor
    held = [t for t in ties(weaver) if all(engine.state.actors.get((t.data or {}).get(k)) is not None for k in ("a", "b"))]
    if not held:
        return
    ids = [f"t{i}" for i in range(len(held))]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "BINDING_TIE", weaver.entity_id), weaver, "choice:needle.knot_weaver.binding_tie",
                        ids, labels={f"t{i}": str((t.data or {}).get("label")) for i, t in enumerate(held)}, preferred=ids[:1],
                        prompt="Binding Knot: which Observed Tie?", name="Binding Knot", feature_id=BINDING)
    tie = held[ids.index(chosen[0])] if chosen and chosen[0] in ids else held[0]
    sides = [engine.state.actors[(tie.data or {})["a"]], engine.state.actors[(tie.data or {})["b"]]]
    unwilling = [s for s in sides if s.team_id != weaver.team_id]
    if any(engine._distance_actor_to_actor(weaver, s) > 60 for s in sides):
        return
    for side in unwilling:
        if not st.save(ctx, side, "cha"):
            note(engine, BINDING, weaver, f"Binding Knot: {side.display_name} resists (Charisma save).", (side,))
            return  # "If both fail or consent"
    forms = {"burden": "Burden Knot: Psychic, Force or Necrotic to one side sends Wisdom + PB Psychic to the other (once per round)",
             "distance": "Distance Knot: a side ending its turn more than 60 feet from the other saves or stops and is pulled 10 feet toward it",
             "guardian": "Guardian Knot: once per round, one side may take half the other's damage with its Reaction"}
    preferred = ["guardian"] if not unwilling else ["burden"]
    form = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "BINDING_FORM", weaver.entity_id), weaver, "choice:needle.knot_weaver.binding_form",
                      list(forms), labels=forms, preferred=preferred, prompt="Binding Knot: which form?", name="Binding Knot", feature_id=BINDING)
    pick = form[0] if form and form[0] in forms else preferred[0]
    engine._apply_condition(weaver, KNOT, ctx.source, weaver.entity_id, expires_on="UNTIL_REMOVED",
                            data={"a": sides[0].entity_id, "b": sides[1].entity_id, "form": pick, "unwilling": [s.entity_id for s in unwilling],
                                  "label": f"Binding Knot ({pick.title()}): {sides[0].display_name} and {sides[1].display_name}"})


@hook("event")
def burden_knot(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED" or str(kwargs.get("payload", {}).get("damage_type") or "").upper() not in ("PSYCHIC", "FORCE", "NECROTIC"):
        return
    if int((kwargs.get("payload") or {}).get("hp_damage") or 0) + int((kwargs.get("payload") or {}).get("temporary_hp_absorbed") or 0) <= 0:
        return
    victim = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    if victim is None:
        return
    for weaver, knot, other in _knots(engine, victim):
        if (knot.data or {}).get("form") != "burden" or not other.active or st.data_of(weaver, knot).get("burden_round") == engine.state.round_number:
            continue
        st.set_data(weaver, knot, burden_round=engine.state.round_number)  # "Once per round"
        numbers = st.numbers(engine, weaver)
        _te().run_effects(st.context(engine, weaver, engine.action_catalog.get(knot.source_definition_id) or st.feature_action(engine, weaver, BINDING), [other], numbers),
                          [{"type": "damage", "applies_to": "target", "flat": int(numbers.get("key_mod") or 0) + int(numbers.get("pb") or 2),
                            "damage_types": ["psychic"], "evidence": "the other linked creature takes Psychic damage equal to Wisdom modifier + Proficiency Bonus"}])


@hook("incoming_damage")
def guardian_knot(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    if amount <= 1 or engine.__dict__.get("_c8_guarding"):
        return None
    for weaver, knot, other in _knots(engine, target):
        if (knot.data or {}).get("form") != "guardian" or not other.active or not st.can_react(other) \
                or st.data_of(weaver, knot).get("guardian_round") == engine.state.round_number:
            continue
        from . import needle

        share = amount // 2
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "GUARDIAN_KNOT", target.entity_id), other, "choice:needle.knot_weaver.guardian",
                            ["take"], labels={"take": f"Guardian Knot (your Reaction): take {share} of the {amount} damage to {target.display_name}"},
                            prompt=f"{target.display_name} takes {amount} damage.", preferred=["take"], allow_decline=True, name="Guardian Knot",
                            feature_id=BINDING, target_id=target.entity_id)
        if not chosen:
            continue
        with activation(engine, other, BINDING):
            st.set_data(weaver, knot, guardian_round=engine.state.round_number)
            other.reaction_available = False
            engine.__dict__["_c8_guarding"] = True
            try:
                # The taken half is the same delivery as the incoming packet, so it keeps that packet's origin.
                from .. import pending_damage
                engine._commit_damage(other, share, str(damage_type).upper(), source_definition_id, source_actor_id or weaver.entity_id, engine._active_intent, reaction_depth=1,
                                      damage_origin=pending_damage.portion_origin(engine))
            finally:
                engine.__dict__.pop("_c8_guarding", None)
            return share
    return None


@hook("turn_end")
def knot_turn_end(engine: Any, actor: Any) -> None:
    for weaver, knot, other in list(_knots(engine, actor)):
        data = knot.data or {}
        ctx = st.context(engine, weaver, engine.action_catalog.get(knot.source_definition_id) or st.feature_action(engine, weaver, BINDING), [actor],
                         st.numbers(engine, weaver))
        if data.get("form") == "distance" and actor.active and other.active and engine._distance_actor_to_actor(actor, other) > 60:
            if st.save(ctx, actor, "cha", on_fail=[{"type": "speed", "applies_to": "target", "becomes": 0, "duration": {"kind": "until_start_of_next_turn"},
                                                    "evidence": "its Speed becomes 0 until the start of its next turn"}]):
                _shove(engine, weaver, actor, other, 10, True, BINDING)
        if actor.entity_id in (data.get("unwilling") or []) and actor.active and not st.save(ctx, actor, "cha"):
            st.remove(engine, weaver, knot, "BROKEN")  # "breaking its side on a success"
            note(engine, BINDING, weaver, f"{actor.display_name} breaks the Binding Knot.")
    for great in [c for c in actor.conditions.values() if c.condition_id == GREAT]:
        _great_save(engine, actor, great)


# ---------------------------------------------------------------------------------------------------------- Sever the False Thread
@effect("knot_sever")
def sever(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle
    from .end_effect import cultivation_dc, found, remove_instance, source_cl, suppress

    engine, weaver, target = ctx.engine, ctx.actor, ctx.target
    rows = [r for r in found(engine, target, {"conditions": COERCIVE_CONDITIONS, "select": "hostile"})] if target else []
    if not rows:
        return
    ids = [f"e{i}" for i in range(len(rows))]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "SEVER_WHICH", target.entity_id), weaver, "choice:needle.knot_weaver.sever",
                        ids, labels={f"e{i}": item.condition_id.rsplit(".", 1)[-1].title() for i, (_k, _key, item) in enumerate(rows)}, preferred=ids[:1],
                        prompt=f"Sever the False Thread: which tie on {target.display_name}?", name="Sever the False Thread", feature_id=SEVER, target_id=target.entity_id)
    kind, key, item = rows[ids.index(chosen[0])] if chosen and chosen[0] in ids else rows[0]
    source = engine.state.actors.get(item.source_actor_id or "")
    dc = int(((item.data or {}).get("origin_save") or {}).get("dc") or (cultivation_dc(engine, source) if source is not None else 15))
    numbers = st.numbers(engine, weaver)
    roll = engine.roll_check(
        modifier=int(numbers.get('pb') or 2) + int(numbers.get('key_mod') or 0),
        actor_id=weaver.entity_id,
        reason=f'CHECK:{SEVER}',
    )
    engine._record_roll(roll)
    engine._append_event("CHECK_ROLLED", SEVER, actor_id=weaver.entity_id, payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": roll.total >= dc,
                                                                                  "check": "Cultivation Check (Sever the False Thread)"})
    if roll.total < dc:
        _te().run_effects(st.context(engine, weaver, ctx.action, [target], numbers, ctx.intent),
                          [{"type": "advantage", "applies_to": "target", "on": f"its next saving throw against being {item.condition_id.rsplit('.', 1)[-1].title()}",
                            "duration": {"kind": "until_removed"}, "evidence": "The target gains Advantage on its next saving throw against that tie"}])
        return
    theirs, mine = source_cl(ctx, item), int(numbers.get("cl") or 1)
    if theirs < mine:
        remove_instance(ctx, target, kind, key, item)  # "An ordinary lower-Source-CL false or coercive tie ends"
    else:
        suppress(target, kind, key, item, rounds=100 if theirs == mine else 1, by=weaver)


# ---------------------------------------------------------------------------------------------------------- Knot of Inevitability
def _great(creature: Any) -> Any:
    return next((c for c in creature.conditions.values() if c.condition_id == GREAT), None)


@effect("knot_inevitability")
def inevitability(ctx: Any, row: dict[str, Any]) -> None:
    from ..gate2_runtime_models import RuntimeObjectState
    from . import needle

    engine, weaver, target = ctx.engine, ctx.actor, ctx.target
    others = other_side(engine, weaver, target) if target is not None else []
    if not others:
        return
    other = others[0]
    spent = int(weaver.resources.get(TENSION, 0) or 0)
    if spent:
        engine._spend_resource(weaver, TENSION, spent, INEVITABLE)  # "and all remaining Knot Tension"
    consequences = {"remain": f"Remain: it cannot willingly move more than 30 feet from {other.display_name}",
                    "face": f"Face: while {other.display_name} is a legal target, its hostile actions target only {other.display_name}",
                    "protect": f"Protect: it cannot willingly harm {other.display_name} and must use its Reaction to cut one blow to it by 2 x PB"}
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "GREAT_KNOT", target.entity_id), weaver, "choice:needle.knot_weaver.inevitability",
                        list(consequences), labels=consequences, preferred=["protect"] if other.team_id == weaver.team_id else ["face"],
                        prompt=f"Knot of Inevitability: which consequence binds {target.display_name}?", name="Knot of Inevitability",
                        feature_id=INEVITABLE, target_id=target.entity_id)
    pick = chosen[0] if chosen and chosen[0] in consequences else "face"
    numbers = ctx.numbers or st.numbers(engine, weaver)
    hp = 8 * int(numbers.get("pb") or 2)
    near = [c for c, _v in st.routes(engine, target, 30).items()]
    spot = next((c for c in near if c != target.position), target.position)
    anchor = RuntimeObjectState(object_id=f"{ANCHOR}{weaver.entity_id}:{target.entity_id}:{engine.state.event_sequence}", object_kind="GREAT_KNOT_ANCHOR",
                                position=spot, unattended=True, flammable=False, owner_id=weaver.entity_id, ac=int(numbers.get("save_dc") or 10),
                                current_hp=hp, maximum_hp=hp, component={"great_knot_of": target.entity_id, "label": "Great Knot Anchor"})
    engine._update_object(anchor, ctx.source, weaver.entity_id)
    for held in [c for c in target.conditions.values() if c.condition_id == GREAT and c.source_actor_id == weaver.entity_id]:
        st.remove(engine, target, held, "REPLACED")
    engine._apply_condition(target, GREAT, ctx.source, weaver.entity_id, expires_on="UNTIL_REMOVED",
                            data={"other": other.entity_id, "consequence": pick, "anchor": anchor.object_id, "bound": False, "failures": 0,
                                  "label": f"Great Knot ({pick.title()}) toward {other.display_name}"})
    _great_save(engine, target, _great(target))


def _great_save(engine: Any, target: Any, great: Any) -> None:
    """"The target makes a Charisma saving throw when the Knot is created and at the end of each of its turns"."""
    if great is None or not target.active:
        return
    weaver = engine.state.actors.get(great.source_actor_id or "")
    if weaver is None:
        return
    data = dict(great.data or {})
    if data.get("locked"):
        return  # three failures against a stronger Weaver: bound while the Anchor stands
    ctx = st.context(engine, weaver, engine.action_catalog.get(great.source_definition_id) or st.feature_action(engine, weaver, INEVITABLE), [target],
                     st.numbers(engine, weaver))
    failed = st.save(ctx, target, "cha", on_success=[
        {"type": "spiritual_pressure", "applies_to": "target", "evidence": "two different Spiritual Pressure effects"},
        {"type": "spiritual_pressure", "applies_to": "target", "different": True, "evidence": "two different Spiritual Pressure effects"}])
    data["bound"] = bool(failed)
    if failed:
        data["failures"] = int(data.get("failures") or 0) + 1
        theirs = next((int(((a.parameters or {}).get("typed") or {}).get("numbers", {}).get("cl") or 0) for a in engine.action_catalog.values()
                       if a.owner_id == target.entity_id and ((a.parameters or {}).get("typed") or {}).get("numbers", {}).get("cl")), 1)
        if data["failures"] >= 3 and theirs < int(st.numbers(engine, weaver).get("cl") or 1):
            data["locked"] = True
    great.data = data


def _binding(engine: Any, creature: Any) -> Any:
    great = _great(creature)
    if great is None or not (great.data or {}).get("bound"):
        return None
    anchor = engine.state.objects.get(str((great.data or {}).get("anchor") or ""))
    if anchor is None or anchor.destroyed:
        return None  # "Destroying the Anchor ends the Great Knot"
    return great


@hook("candidate_allowed")
def knot_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    feature = st.feature_of(action) if action is not None else ""
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if feature == BINDING:
        return None if any(all(engine.state.actors.get((t.data or {}).get(k)) is not None for k in ("a", "b")) for t in ties(actor)) else False
    if feature == SEVER:
        from .end_effect import found

        return None if target is not None and found(engine, target, {"conditions": COERCIVE_CONDITIONS, "select": "hostile"}) else False
    if feature == INEVITABLE:
        if actor.resources.get(TENSION, 0) < 1:
            return False  # "all remaining Knot Tension, minimum 1"
        return None if target is not None and _te().bears_mark(target, actor.entity_id, "Resonance") and other_side(engine, actor, target) else False
    great = _binding(engine, actor)
    if great is None:
        return None
    other = engine.state.actors.get(str((great.data or {}).get("other") or ""))
    if other is None or not other.active:
        return None
    consequence = (great.data or {}).get("consequence")
    destination = getattr(candidate, "destination", None)
    if consequence == "remain" and destination is not None and str(getattr(getattr(candidate, "kind", None), "value", "")) == "MOVE":
        return False if engine._distance_actor_to_actor(actor, other, actor_position=destination) > 30 else None
    targets = [engine.state.actors[t] for t in (getattr(candidate, "target_ids", None) or ()) if t in engine.state.actors]
    hostile = [t for t in targets if t.team_id != actor.team_id]
    if consequence == "face" and hostile and any(t is not other for t in hostile) and other.team_id != actor.team_id and action is not None \
            and engine._distance_actor_to_actor(actor, other) <= int(action.range_ft or action.reach_ft or 5):
        return False  # "cannot willingly target creatures other than the other side with hostile effects while that side remains a legal target"
    if consequence == "protect" and other in targets and action is not None and int((action.parameters or {}).get("expected_damage") or 0) > 0:
        return False  # "cannot willingly harm the other side"
    return None


@hook("incoming_damage")
def protect_the_other(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    if amount <= 0:
        return None
    for creature in engine.state.actors.values():
        great = _binding(engine, creature) if creature.active else None
        if great is None or (great.data or {}).get("consequence") != "protect" or (great.data or {}).get("other") != target.entity_id \
                or not st.can_react(creature) or creature is target:
            continue
        weaver = engine.state.actors.get(great.source_actor_id or "")
        with activation(engine, creature, INEVITABLE):
            creature.reaction_available = False  # "must use its Reaction, if available"
            cut = min(amount, 2 * int(st.numbers(engine, weaver).get("pb") or 2)) if weaver is not None else 0
            engine._append_event("REACTION_RESOLVED", INEVITABLE, actor_id=creature.entity_id, target_ids=(target.entity_id,),
                                 payload={"checkpoint": "DAMAGE_APPLICATION", "reaction_name": "Great Knot (Protect)", "reduction": cut})
            return cut
    return None
