"""Mudang (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, "Mudang": Trance Rhythm, CL3 Spirit Dance, CL6 Possession Trance, CL10 Gut of
Revealed Guests, CL14 Greater Spirit Possession, CL18 Grand Mudang Procession). No Spheres 5e or D&D 5.5e counterpart.

Trance Rhythm (tradition text): a pool (resource:named.trance_rhythm), 0 at the start of the fight, maximum PB. Once on each of your
turns you gain 1 when: you move at least 10 feet while your Spirit Dance lasts; a hostile creature fails a save against one of your
Spirit Awakening features; or an action of yours that spent Resonance heals, shields or frees another creature.

What runs:
  * Spirit Dance (typed options, Bonus Action, 1 Resonance, the fight): the first Dance Step comes with it; "Dance Step: <Step>"
    (free, once on each of your turns while you dance) chooses the next. Warding Step -- you and one ally within 10 feet (asked) add
    half your PB (rounded up) to your first Int/Wis/Cha save before the start of your next turn; Guiding Step -- one creature within
    30 feet (asked) moves up to 10 feet where you choose, not using its Reaction, and only where no hostile creature other than one you
    Resonance Marked could make an Opportunity Attack; Settling Step -- one willing creature within 10 feet (you included) suppresses
    one Frightened or Spiritual Pressure effect until the start of your next turn.
  * Possession Trance (typed options, Bonus Action, 2 Resonance + 1 Trance Rhythm, the fight): one Guest Seat; "Change Guest Seat:
    <Seat>" (Bonus Action, 1 Trance Rhythm). Road Guest -- Speed +10 and nonmagical difficult terrain ignored; once on each of your
    turns after you have moved 20 feet, an ally that was next to you when that move began may move 5 feet with you (asked). Guardian
    Guest -- 2 x PB Temporary HP when it enters; once per round the first Psychic, Necrotic or Radiant damage to you or an ally within
    10 feet is reduced by your Wisdom modifier. Healing Guest -- once on each of your turns, after your Settling Step or a healing
    action of yours on a creature, it regains PB Hit Points or gains PB Temporary HP (asked; once per round for each creature).
    Watchful Guest adds 10-foot Spiritual Sense and Advantage on Perception against recorded spirits/possession. Surprise has no
    engine state. Prepared Gut Circle and petitions are implemented separately in mudang_ritual.py.
  * Grand Mudang Procession (Action, 10 Resonance, a square within 30 feet): a Grand Spirit Procession object (AC your DC, 10 x PB HP;
    its court's damage type asked). "Procession: Spirit Strike" (Bonus Action: a Cultivation Attack on a creature within 15 feet of
    it, 4d10 + Wisdom), "Procession: Communal Mending" (Bonus Action: a creature within 15 feet of it regains 3d8 + Wisdom and may
    repeat a save against a hostile Charmed or Frightened; once for each creature), "Move the Procession" (free, once on each of
    your turns, up to 40 feet), "Dismiss the Procession" (free). At 0 Hit Points it disperses: 4d10 Psychic to you that nothing
    reduces, and it cannot be called again this fight.

Plug-in surface: effects mudang_dance, mudang_seat, mudang_procession, mudang_expression; hooks compile_actions, candidate_allowed, save,
event, turn_start, technique_used, after_save_resolved, incoming_damage, speed, opportunity_allowed, sense_range, ability_check_mode. Public helper: ``gain_rhythm``.
Shared helpers used: spirit_traditions (context/numbers/feature_action/is_spirit_feature/affected_by/pick_creature/routes/choose_route/
remove), suppressed_effects (lifetime/restore), typed_reactions.opportunity_reach, needle, typed_executor.
"""

from __future__ import annotations

import math
from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.mudang.feature."
DANCE = TRADITION + "spirit_dance"
TRANCE = TRADITION + "possession_trance"
GRAND = TRADITION + "grand_mudang_procession"
RHYTHM = "resource:named.trance_rhythm"
RESONANCE = "resource:core.resonance"
DANCING = "condition:typed.spirit_dance"
WARDED = "condition:typed.warding_step"
SETTLED = "condition:typed.settling_step"
SEAT = "condition:typed.guest_seat"
PROCESSION = "object:typed.grand_procession:"
DISPERSED = "condition:typed.procession_dispersed"
MENDED = "condition:typed.communal_mending"
STEPS = ("Warding Step", "Guiding Step", "Settling Step")
SEATS = ("Road Guest", "Watchful Guest", "Guardian Guest", "Healing Guest")
COURT = ("psychic", "necrotic", "radiant", "thunder", "force")


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _name(condition: Any) -> str:
    return str(condition.condition_id or "").rsplit(".", 1)[-1].lower()


def _numbers(engine: Any, actor: Any) -> dict[str, Any]:
    return st.numbers(engine, actor)


def _held(actor: Any, condition_id: str) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == condition_id and c.source_actor_id == actor.entity_id), None)


def _is_mudang(engine: Any, actor: Any) -> bool:
    return actor is not None and RHYTHM in (actor.resource_maximums or {})


def gain_rhythm(engine: Any, mudang: Any, why: str) -> None:
    """"Once on each of your turns, you gain 1 Trance Rhythm when at least one of the following occurs"."""
    if not _is_mudang(engine, mudang) or engine.state.current_actor_id != mudang.entity_id or mudang.turn_flags.get("trance_rhythm_gained"):
        return
    if mudang.resources.get(RHYTHM, 0) >= mudang.resource_maximums.get(RHYTHM, 0):
        return
    mudang.turn_flags["trance_rhythm_gained"] = True
    engine._gain_resource(mudang, RHYTHM, 1, DANCE)
    note(engine, DANCE, mudang, f"{mudang.display_name} gains 1 Trance Rhythm ({why}).")


# ---------------------------------------------------------------------------------------------------------- Trance Rhythm triggers
@hook("event")
def rhythm_and_road(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    payload = kwargs.get("payload") or {}
    if (mover is None or not _is_mudang(engine, mover) or engine.state.current_actor_id != mover.entity_id
            or payload.get("forced") or payload.get("dragged_by")):
        return
    feet = int(payload.get("planned_cost_ft") or payload.get("cost_ft") or 0)
    if feet <= 0:
        return
    before = int(mover.turn_flags.get("mudang_moved_ft") or 0)
    mover.turn_flags["mudang_moved_ft"] = before + feet
    if _held(mover, DANCING) is not None and before + feet >= 10:
        gain_rhythm(engine, mover, "moving 10 feet in the dance")  # "You move at least 10 feet while consciously maintaining a dance"
    seat = _held(mover, SEAT)
    if seat is not None and (seat.data or {}).get("seat") == "Road Guest" and before + feet >= 20 and not mover.turn_flags.get("road_guest_carry"):
        path = payload.get("path") or []
        start = path[0] if path else None
        _road_carry(engine, mover, start)


@hook("after_save_resolved")
def rhythm_from_a_failed_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """"A meaningful hostile creature fails a saving throw against one of your Spirit Awakening features"."""
    if failed and subject is not None and ctx.actor is not None and subject.team_id != ctx.actor.team_id and st.is_spirit_feature(ctx.action):
        gain_rhythm(ctx.engine, ctx.actor, f"{subject.display_name} failed a save")


_HELPED = {"HEALING_APPLIED", "TEMP_HP_GRANTED", "CONDITION_REMOVED"}


@hook("technique_used")
def rhythm_from_care(ctx: Any) -> None:
    """"You spend Resonance to protect, diagnose, stabilize, exorcise, or heal another creature" -- and the Healing Guest."""
    engine, mudang = ctx.engine, ctx.actor
    if not _is_mudang(engine, mudang):
        return
    helped = [engine.state.actors.get(t) for e in st.activation_events(engine, ctx) if e.event_type in _HELPED and e.source_definition_id == ctx.source
              for t in e.target_ids]
    helped = list({c.entity_id: c for c in helped if c is not None and c.active and c.team_id == mudang.team_id}.values())
    paid = int(dict(getattr(ctx.action, "costs", None) or ()).get(RESONANCE) or 0) > 0
    if paid and any(c is not mudang for c in helped):
        gain_rhythm(engine, mudang, "spending Resonance to care for another")
    healed = [c for c in helped if any(e.event_type == "HEALING_APPLIED" and c.entity_id in e.target_ids and e.source_definition_id == ctx.source
                                       for e in st.activation_events(engine, ctx))]
    if healed:
        _healing_guest(engine, mudang, healed, ctx.intent)


# ---------------------------------------------------------------------------------------------------------- Spirit Dance
def _allies(engine: Any, mudang: Any, feet: int, *, with_self: bool) -> list[Any]:
    return [c for _, c in sorted(engine.state.actors.items()) if c.active and c.team_id == mudang.team_id and (with_self or c is not mudang)
            and engine._distance_actor_to_actor(mudang, c) <= feet]


def _guided_routes(engine: Any, mudang: Any, mover: Any) -> dict[Any, Any]:
    """Guiding Step: the creature moves up to 10 feet; only a square it can reach without passing through the Opportunity Attack
    reach of a spirit, an incorporeal undead, or another creature that is not Resonance Marked by the Mudang is offered."""
    from .. import typed_reactions

    te = _te()
    threats = [(c, int(typed_reactions.opportunity_reach(engine, c) or 5)) for c in engine.state.actors.values()
               if c.active and c.team_id != mover.team_id and c.reaction_available and not te.bears_mark(c, mudang.entity_id, "Resonance")]
    out = {}
    for cell, (path, cost) in st.routes(engine, mover, 10).items():
        if cell == mover.position:
            continue
        leaves = any(engine.grid.distance_ft(a, foe.position) <= reach < engine.grid.distance_ft(b, foe.position)
                     for foe, reach in threats for a, b in zip(path, path[1:]))
        if not leaves:
            out[cell] = (path, cost)
    return out


def _dance_step(ctx: Any, step: str) -> None:
    from . import needle
    from .suppressed_effects import lifetime

    engine, mudang = ctx.engine, ctx.actor
    mudang.turn_flags["dance_step"] = True  # "Choose one Dance Step ... again at the start of each of your turns"
    numbers = ctx.numbers or _numbers(engine, mudang)
    if step == "Warding Step":
        bonus = math.ceil(int(numbers.get("pb") or 2) / 2)
        ally = st.pick_creature(engine, ctx.intent, mudang, _allies(engine, mudang, 10, with_self=False), checkpoint="WARDING_STEP",
                                choice_id="choice:needle.mudang.warding_step", prompt="Warding Step: which ally within 10 feet shares the ward?",
                                name="Warding Step", feature_id=DANCE)
        for creature in [mudang, *([ally] if ally is not None else [])]:
            engine._apply_condition(creature, WARDED, DANCE, mudang.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"bonus": bonus, "label": f"Warding Step: +{bonus} to its first Intelligence, Wisdom or Charisma save"})
    elif step == "Guiding Step":
        movers = [c for c in _allies(engine, mudang, 30, with_self=True) if _guided_routes(engine, mudang, c)]
        mover = st.pick_creature(engine, ctx.intent, mudang, movers, checkpoint="GUIDING_STEP", choice_id="choice:needle.mudang.guiding_step",
                                 prompt="Guiding Step: who moves 10 feet?", name="Guiding Step", feature_id=DANCE, allow_decline=True)
        if mover is not None:
            path = st.choose_route(engine, mudang, _guided_routes(engine, mudang, mover), ctx.intent, checkpoint="GUIDING_STEP_TO",
                                   prompt=f"Guiding Step: where does {mover.display_name} move?", name="Guiding Step", feature=DANCE, stay=False)
            if path is not None:
                from .rider_movement import step as walk

                walk(engine, mover, list(path), DANCE)
    elif step == "Settling Step":
        options = [(c, h) for c in _allies(engine, mudang, 10, with_self=True) for _, h in sorted(c.conditions.items())
                   if _name(h) == "frightened" or str(h.condition_id).startswith("condition:typed.spirit_awakening_pressure")]
        if not options:
            return
        ids = [f"s{i}" for i in range(len(options))]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "SETTLING_STEP", mudang.entity_id), mudang, "choice:needle.mudang.settling_step",
                            ids, labels={f"s{i}": f"{c.display_name}: {_name(h).replace('_', ' ').title()}" for i, (c, h) in enumerate(options)},
                            preferred=ids[:1], prompt="Settling Step: which fear or pressure is settled until the start of your next turn?",
                            name="Settling Step", feature_id=DANCE)
        creature, held = options[ids.index(chosen[0])] if chosen and chosen[0] in ids else options[0]
        iid = next(k for k, h in creature.conditions.items() if h is held)
        clock = lifetime(engine, creature, held)
        creature.conditions.pop(iid)
        engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=mudang.entity_id, target_ids=(creature.entity_id,),
                             payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "SUPPRESSED"})
        engine._apply_condition(creature, SETTLED, DANCE, mudang.entity_id, expires_on="UNTIL_REMOVED",
                                data={"condition": held.model_dump(mode="json"), "lifetime": clock,
                                      "label": f"{_name(held).replace('_', ' ').title()} settled until the start of {mudang.display_name}'s next turn"})
        _healing_guest(engine, mudang, [creature], ctx.intent)


@effect("mudang_dance")
def dance(ctx: Any, row: dict[str, Any]) -> None:
    if row.get("begin"):
        held = _held(ctx.actor, DANCING)
        if held is None:
            ctx.engine._apply_condition(ctx.actor, DANCING, DANCE, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data={"label": "Spirit Dance"})
    _dance_step(ctx, str(row.get("step")))


@hook("save")
def warding(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if str(ability or "").upper()[:3] not in ("INT", "WIS", "CHA") or subject is None:
        return None
    for iid, held in list(subject.conditions.items()):
        if held.condition_id == WARDED:
            subject.conditions.pop(iid)  # Warding Step is spent by the first INT, WIS or CHA save that uses it
            ctx.engine._append_event("CONDITION_REMOVED", DANCE, actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                                     payload={"condition_id": WARDED, "instance_id": iid, "reason": "CONSUMED"})
            return {"bonus": int((held.data or {}).get("bonus") or 1)}
    return None


@hook("turn_start")
def settled_returns(engine: Any, actor: Any) -> None:
    """Settling Step: "until the start of your next turn"."""
    from .suppressed_effects import restore

    for holder in list(engine.state.actors.values()):
        for iid, held in list(holder.conditions.items()):
            if held.condition_id == SETTLED and held.source_actor_id == actor.entity_id:
                holder.conditions.pop(iid)
                engine._append_event("CONDITION_REMOVED", DANCE, actor_id=actor.entity_id, target_ids=(holder.entity_id,),
                                     payload={"condition_id": SETTLED, "instance_id": iid, "reason": "ENDED"})
                restore(engine, holder, (held.data or {}).get("condition") or {}, (held.data or {}).get("lifetime") or {})


# ---------------------------------------------------------------------------------------------------------- Possession Trance
@effect("mudang_seat")
def seat(ctx: Any, row: dict[str, Any]) -> None:
    engine, mudang = ctx.engine, ctx.actor
    held = _held(mudang, SEAT)
    if held is not None:
        st.remove(engine, mudang, held, "CHANGED")  # this feature hosts only one Guest Seat at a time
    chosen = str(row.get("seat"))
    from .source_records import apply_expression
    apply_expression(ctx, mudang, SEAT, category="possession_entry", ordinary=1, source=TRANCE, exclusive_group=SEAT,
                     data={"seat": chosen, "ends_with_scene": 1, "persists_while_inactive": 1,
                           **({"rule": {"ignore_difficult": True}} if chosen == "Road Guest" else {}),
                           "label": f"Possession Trance: {chosen}"})
    if chosen == "Guardian Guest":
        engine._grant_temp_hp(mudang, 2 * int((ctx.numbers or _numbers(engine, mudang)).get("pb") or 2), TRANCE, mudang.entity_id)


@hook("speed")
def road_guest_speed(engine: Any, actor: Any) -> int | None:
    held = _held(actor, SEAT)
    return 10 if held is not None and (held.data or {}).get("seat") == "Road Guest" else None


@hook("ability_check_mode")
def watchful_guest_perception(engine: Any, actor: Any, ability: str, skill: str, against: Any) -> str | None:
    from .creature_kinds import matches

    held = _held(actor, SEAT)
    if (held is not None and (held.data or {}).get("seat") == "Watchful Guest"
            and str(skill).casefold() == "perception"
            and matches(against, ("spirit", "ghost", "incorporeal undead", "possession entity", "possessed"))):
        return "ADVANTAGE"
    return None


def _road_carry(engine: Any, mudang: Any, start: Any) -> None:
    """Road Guest: once a turn, after moving 20 feet or more, the Mudang may carry one willing adjacent ally 5 feet along."""
    if not isinstance(start, dict):
        return
    near = [c for c in engine.state.actors.values() if c.active and c.team_id == mudang.team_id and c is not mudang
            and any(max(abs(x - int(start.get("x", 0))), abs(y - int(start.get("y", 0)))) <= 1 for x, y in engine._actor_cells(c))]
    if not near:
        return
    mudang.turn_flags["road_guest_carry"] = True
    ally = st.pick_creature(engine, engine._active_intent, mudang, near, checkpoint="ROAD_GUEST", choice_id="choice:needle.mudang.road_guest",
                            prompt="Road Guest: which ally moves 5 feet with you?", name="Road Guest", feature_id=TRANCE, allow_decline=True)
    if ally is None:
        return
    spots = {c: v for c, v in st.routes(engine, ally, 5).items() if c != ally.position}
    path = st.choose_route(engine, mudang, spots, engine._active_intent, checkpoint="ROAD_GUEST_TO", prompt=f"Road Guest: where does {ally.display_name} move?",
                           name="Road Guest", feature=TRANCE, stay=False) if spots else None
    if path is not None:
        from .rider_movement import step as walk

        walk(engine, ally, list(path), TRANCE)


@hook("incoming_damage")
def guardian_guest(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    """Guardian Guest: once a round, the first Psychic, Necrotic or Radiant damage taken by the Mudang or an ally within 10 feet is
    cut by the Mudang's Wisdom modifier."""
    if amount <= 0 or str(damage_type).upper() not in ("PSYCHIC", "NECROTIC", "RADIANT"):
        return None
    for mudang in engine.state.actors.values():
        held = _held(mudang, SEAT)
        if (held is None or (held.data or {}).get("seat") != "Guardian Guest" or not mudang.active or mudang.team_id != target.team_id
                or engine._distance_actor_to_actor(mudang, target) > 10 or st.data_of(mudang, held).get("round") == engine.state.round_number):
            continue
        st.set_data(mudang, held, round=engine.state.round_number)
        wis = int(_numbers(engine, mudang).get("key_mod") or 0)
        return min(amount, max(0, wis))
    return None


def _healing_guest(engine: Any, mudang: Any, creatures: list[Any], intent: Any) -> None:
    """Healing Guest: once on each of your turns, after Settling Step or a healing procedure on a creature, it regains PB Hit Points or gains
    that many Temporary Hit Points; once per round for each creature."""
    from . import needle

    held = _held(mudang, SEAT)
    if held is None or (held.data or {}).get("seat") != "Healing Guest" or mudang.turn_flags.get("healing_guest"):
        return
    fresh = [c for c in creatures if c.active and (c.turn_flags.get("healing_guest_round") != engine.state.round_number)]
    creature = st.pick_creature(engine, intent, mudang, fresh, checkpoint="HEALING_GUEST", choice_id="choice:needle.mudang.healing_guest",
                                prompt="Healing Guest: who receives the guest's care?", name="Healing Guest", feature_id=TRANCE, allow_decline=True,
                                preferred=fresh[0] if fresh else None)
    if creature is None:
        return
    mudang.turn_flags["healing_guest"] = True
    creature.turn_flags["healing_guest_round"] = engine.state.round_number
    pb = int(_numbers(engine, mudang).get("pb") or 2)
    pick = needle.ask(engine, intent, needle.checkpoint_id(engine, "HEALING_GUEST_WHAT", creature.entity_id), mudang, "choice:needle.mudang.healing_guest_what",
                      ["heal", "temp"], labels={"heal": f"{creature.display_name} regains {pb} Hit Points", "temp": f"{creature.display_name} gains {pb} Temporary Hit Points"},
                      preferred=["heal" if creature.current_hp < creature.maximum_hp else "temp"], prompt="Healing Guest: which care?", name="Healing Guest",
                      feature_id=TRANCE, target_id=creature.entity_id)
    if (pick[0] if pick else "heal") == "temp":
        engine._grant_temp_hp(creature, pb, TRANCE, mudang.entity_id)
    else:
        _te().run_effects(st.context(engine, mudang, st.feature_action(engine, mudang, TRANCE), [creature], _numbers(engine, mudang)),
                          [{"type": "healing", "applies_to": "target", "flat": pb, "evidence": "it regains Hit Points equal to your Proficiency Bonus"}])


# ---------------------------------------------------------------------------------------------------------- Grand Mudang Procession
def procession_of(engine: Any, mudang: Any) -> Any:
    return next((o for o in engine.state.objects.values() if o.object_id.startswith(PROCESSION) and o.owner_id == mudang.entity_id and not o.destroyed), None)


def _near_procession(engine: Any, obj: Any, creature: Any, feet: int) -> bool:
    """Within ``feet`` of the Huge (15-foot) Procession: its 3 x 3 squares around the square it was placed on."""
    size = engine.grid.square_size_ft
    return any(max(abs(x - obj.position.x), abs(y - obj.position.y)) - 1 <= feet // size for x, y in engine._actor_cells(creature))


@effect("mudang_procession")
def procession(ctx: Any, row: dict[str, Any]) -> None:
    from ..gate2_runtime_models import RuntimeObjectState
    from . import needle

    engine, mudang = ctx.engine, ctx.actor
    spot = getattr(ctx, "destination", None) or getattr(ctx.intent, "destination", None)
    if spot is None:
        return
    old = procession_of(engine, mudang)
    if old is not None:
        engine._update_object(old.model_copy(update={"destroyed": True, "component": {**(old.component or {}), "dismissed": True}}), ctx.source, mudang.entity_id)
    court = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "PROCESSION_COURT", mudang.entity_id), mudang, "choice:needle.mudang.court",
                       list(COURT), labels={k: k.title() for k in COURT}, preferred=["psychic"], name="Grand Mudang Procession", feature_id=GRAND,
                       prompt="Grand Mudang Procession: the invited court's Spirit Strike deals which damage?")
    for creature in engine.state.actors.values():  # a new activation: Communal Mending may be received again
        for held in [c for c in creature.conditions.values() if c.condition_id == MENDED and c.source_actor_id == mudang.entity_id]:
            st.remove(engine, creature, held, "NEW_PROCESSION")
    numbers = ctx.numbers or _numbers(engine, mudang)
    hp = 10 * int(numbers.get("pb") or 2)
    engine._update_object(RuntimeObjectState(object_id=f"{PROCESSION}{mudang.entity_id}:{engine.state.event_sequence}", object_kind="GRAND_SPIRIT_PROCESSION",
                                             position=spot, unattended=False, flammable=False, owner_id=mudang.entity_id, ac=int(numbers.get("save_dc") or 10),
                                             current_hp=hp, maximum_hp=hp, damage_immunities=("POISON",),
                                             component={"label": f"{mudang.display_name}'s Grand Spirit Procession (Huge)",
                                                        "court": (court[0] if court else "psychic"), "resist": ["PSYCHIC", "NECROTIC", "RADIANT"]}), ctx.source, mudang.entity_id)


@effect("mudang_expression")
def expression(ctx: Any, row: dict[str, Any]) -> None:
    engine, mudang = ctx.engine, ctx.actor
    obj = procession_of(engine, mudang)
    mode = row.get("mode")
    if obj is None:
        return
    if mode == "move":
        spot = getattr(ctx, "destination", None) or getattr(ctx.intent, "destination", None)
        mudang.turn_flags["procession_moved"] = True
        if spot is not None:
            engine._update_object(obj.model_copy(update={"position": spot}), ctx.source, mudang.entity_id)
        return
    if mode == "dismiss":
        engine._update_object(obj.model_copy(update={"destroyed": True, "component": {**(obj.component or {}), "dismissed": True}}), ctx.source, mudang.entity_id)
        return
    target = next(iter(_te()._default_subject(ctx, row, harmful=mode == "strike")), None)
    if target is None:
        return
    if mode == "strike":
        court = str((obj.component or {}).get("court") or "psychic")
        _te().run_effects(ctx, [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1, "applies_to": "target",
                                 "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 10}, "formula": "key_ability_modifier",
                                             "damage_types": [court], "evidence": f"4d10 + Wisdom modifier {court.title()} damage"}]}])
        return
    engine._apply_condition(target, MENDED, GRAND, mudang.entity_id, expires_on="UNTIL_REMOVED", data={"label": "Communal Mending received this Procession"})
    _te().run_effects(ctx, [{"type": "healing", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "formula": "key_ability_modifier",
                             "evidence": "regains 3d8 + Wisdom modifier Hit Points"}])
    afflicted = next((c for _, c in sorted(target.conditions.items()) if _name(c) in ("charmed", "frightened")
                      and (lambda s: s is not None and s.team_id != target.team_id)(engine.state.actors.get(c.source_actor_id or ""))), None)
    if afflicted is not None:
        from . import needle

        if needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "COMMUNAL_MENDING", target.entity_id), target, "choice:needle.mudang.mending_save",
                      ["repeat"], labels={"repeat": f"Repeat your save against {_name(afflicted).title()}"}, preferred=["repeat"], allow_decline=True,
                      prompt="Communal Mending: repeat a save?", name="Communal Mending", feature_id=GRAND):
            origin = (afflicted.data or {}).get("origin_save") or {}
            dc = int(origin.get("dc") or 10)
            roll = engine._roll_save(target, str(origin.get("ability") or "WIS").upper()[:3], dc, GRAND)
            if roll is not None and roll.total >= dc:
                st.remove(engine, target, afflicted, "SAVED")


@hook("event")
def procession_disperses(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """At 0 Hit Points the Procession disperses: the Mudang takes 4d10 Psychic damage that nothing reduces, and Grand Mudang
    Procession cannot be used again until the Mudang completes a Full Cultivation Session."""
    if event_type != "OBJECT_UPDATED":
        return
    obj = (kwargs.get("payload") or {}).get("object") or {}
    if not str(obj.get("object_id") or "").startswith(PROCESSION) or (obj.get("component") or {}).get("dismissed"):
        return
    if not (obj.get("destroyed") or (obj.get("current_hp") is not None and int(obj.get("current_hp") or 0) <= 0)):
        return
    mudang = engine.state.actors.get(str(obj.get("owner_id") or ""))
    stored = engine.state.objects.get(str(obj.get("object_id")))
    if stored is not None:
        engine._update_object(stored.model_copy(update={"component": {**(stored.component or {}), "dismissed": True}}), GRAND, stored.owner_id)  # it breaks once (evented: the replay sees it)
    if mudang is None:
        return
    engine._apply_condition(mudang, DISPERSED, GRAND, mudang.entity_id, expires_on="UNTIL_REMOVED", data={"label": "Grand Mudang Procession dispersed this fight"})
    if not mudang.active:
        return
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=4, sides=10, modifier=0), actor_id=mudang.entity_id, reason=f"DAMAGE:{GRAND}")
    engine._record_roll(roll)
    engine.__dict__["_damage_unreduced"] = mudang.entity_id
    try:
        engine._commit_damage(mudang, int(roll.total), "PSYCHIC", GRAND, mudang.entity_id, engine._active_intent, reaction_depth=1)
    finally:
        if engine.__dict__.get("_damage_unreduced") == mudang.entity_id:
            engine.__dict__.pop("_damage_unreduced", None)


# ---------------------------------------------------------------------------------------------------------- buttons and gates
@hook("compile_actions")
def mudang_buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned, out = info["owned_ids"], []

    def button(key: str, name: str, economy: Any, target: str, rows: list[dict[str, Any]], text: str, source: str, *, range_ft: int | None = None,
               costs: tuple = ()) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mudang.{key}", display_name=name, owner_id=info["actor_id"],
                                economy=economy, resolution_kind="TYPED", target_kind=target, range_ft=range_ft, costs=costs,
                                parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": source,
                                                      "effects": rows}, "expected_damage": 0, "mudang": key, "description": text})

    if DANCE in owned:
        for step in STEPS:
            out.append(button(f"step.{step.split()[0].lower()}", f"Dance Step: {step}", EconomyKind.NONE, "SELF",
                              [{"type": "mudang_dance", "applies_to": "self", "step": step}],
                              f"Spirit Dance (free, once on each of your turns while you dance): this turn's Dance Step is {step}.", DANCE))
    if TRANCE in owned:
        for name in SEATS:
            out.append(button(f"seat.{name.split()[0].lower()}", f"Change Guest Seat: {name}", EconomyKind.BONUS_ACTION, "SELF",
                              [{"type": "mudang_seat", "applies_to": "self", "seat": name}],
                              f"Possession Trance (Bonus Action, 1 Trance Rhythm): your Guest Seat becomes the {name}.", TRANCE, costs=((RHYTHM, 1),)))
    if GRAND in owned:
        out.extend([
            button("strike", "Procession: Spirit Strike", EconomyKind.BONUS_ACTION, "HOSTILE_ENTITY",
                   [{"type": "mudang_expression", "applies_to": "target", "mode": "strike", "harmful": True}],
                   "Grand Mudang Procession (Bonus Action): a Cultivation Attack on a creature within 15 feet of the Procession, 4d10 + your Wisdom "
                   "modifier damage of its court's type.", GRAND, range_ft=120),
            button("mending", "Procession: Communal Mending", EconomyKind.BONUS_ACTION, "ALLY_OR_SELF",
                   [{"type": "mudang_expression", "applies_to": "target", "mode": "mending"}],
                   "Grand Mudang Procession (Bonus Action): a creature within 15 feet of the Procession regains 3d8 + your Wisdom modifier Hit Points "
                   "and may repeat a save against Charmed or Frightened (once for each creature).", GRAND, range_ft=120),
            button("move", "Move the Procession", EconomyKind.NONE, "SELF",
                   [{"type": "mudang_expression", "applies_to": "self", "mode": "move", "picks_destination": True, "distance_ft": 120}],
                   "Grand Mudang Procession (free, once on each of your turns): it moves up to 40 feet.", GRAND),
            button("dismiss", "Dismiss the Procession", EconomyKind.NONE, "SELF", [{"type": "mudang_expression", "applies_to": "self", "mode": "dismiss"}],
                   "Grand Mudang Procession (free): it ends cleanly.", GRAND),
        ])
    return out or None


@hook("candidate_allowed")
def mudang_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    params = action.parameters or {}
    key = str(params.get("mudang") or "")
    if st.feature_of(action) == GRAND and not key:
        return False if _held(actor, DISPERSED) is not None else None  # "You cannot use Grand Mudang Procession again until ..."
    if not key:
        return None
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if key.startswith("step."):
        return None if _held(actor, DANCING) is not None and not actor.turn_flags.get("dance_step") else False
    if key.startswith("seat."):
        held = _held(actor, SEAT)
        wanted = next(s for s in SEATS if s.split()[0].lower() == key.split(".", 1)[1])
        return None if held is not None and (held.data or {}).get("seat") != wanted else False
    obj = procession_of(engine, actor)
    if obj is None:
        return False
    if key in ("strike", "mending"):
        if target is None or not _near_procession(engine, obj, target, 15):
            return False
        if key == "mending" and any(c.condition_id == MENDED and c.source_actor_id == actor.entity_id for c in target.conditions.values()):
            return False  # "A creature can benefit from Communal Mending only once per activation"
    if key == "move":
        spot = getattr(candidate, "destination", None)
        if actor.turn_flags.get("procession_moved") or (spot is not None and engine.grid.distance_ft(obj.position, spot) > 40):
            return False
    return None


@hook("sense_range")
def watchful_guest_sense(engine: Any, actor: Any, sense: str) -> int:
    held = _held(actor, SEAT)
    return 10 if sense == "spiritual_sense" and held is not None and (held.data or {}).get("seat") == "Watchful Guest" else 0
