"""Thrum of the Grave (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Thrum of the Grave: Gravebeats, CL3 Gravebeat, CL6 Dead March, CL10 Burial Drum, CL14
Call the Unquiet, CL18 The Earth Beats Once). No Spheres 5e or D&D 5.5e counterpart.

Gravebeats (tradition text): a pool (resource:named.gravebeat), maximum PB, 0 at the start of the fight. +1, no more than once per turn,
when within 60 feet a hostile creature bearing your Resonance Mark becomes Bloodied, a hostile creature is defeated, or a hostile
creature fails to regain Hit Points because of your Burial Drum, or a labelled hostile undead, haunt or possessed creature fails
your saving throw. Dismissal or Unconsciousness ends the Gravebeat rhythm.

What runs:
  * Gravebeat (typed, Bonus Action, 1 Resonance, the fight): once a turn your Psychic or Necrotic damage to a hostile creature bearing your
    Resonance Mark adds your PB; when a hostile creature within 30 feet becomes Bloodied or is defeated you may Resonance Mark a hostile
    creature within 10 feet of it (asked, no action).
  * Dead March (typed, Action, 60 feet, 3 Resonance): Wisdom save; failed -- a March you choose (asked): Toward the Grave (it spends its
    Reaction, if it has one, moving up to half its Speed where you choose), Fall Into Step (no Reactions, Speed -15 until the start of your
    next turn), March Past the Living (it moves up to half its Speed away from a creature you name), Kneel to the Beat (Prone if it is
    Bloodied, Frightened or bears two of your marks); succeeded -- Speed -10 until the start of your next turn. Processional Chain (asked):
    up to 2 Gravebeats for as many more creatures within 15 feet of the first.
  * Burial Drum (typed zone, 20 feet around you, Concentration): a hostile creature in it about to regain Hit Points makes a Wisdom save
    once a turn (the ``healing_received`` hook) -- failed, no Hit Points (and 2 x PB Necrotic if it is Frightened, Dying or bears your
    Resonance Mark); succeeded, half. "Burial Drum: Beat of Interment" (free, once on each of your turns, 1 Gravebeat): a hostile creature
    in it makes a Constitution save -- 3d8 + Wisdom and no Reactions until the start of its next turn, or half.
  * Call the Unquiet (Action, 6 Resonance, a square within 60 feet): an Unquiet Echo object (AC your DC, 6 x PB HP) with a Death Memory
    (asked): Mourner's Cry (once a turn a creature within 15 feet of it failing your Wisdom save is Frightened until the end of its next
    turn) or Unfinished Violence (once a turn +2d8 to your Psychic or Necrotic damage to a marked hostile creature within 15 feet of it);
    Soldier's March and Grave Keeper are the GM's. "Unquiet Echo: Grave Cry" (free, once a turn, 1 Gravebeat: a creature within 30 feet
    of it -- Wisdom save, 3d8 Psychic and Frightened, or half), "Direct the Unquiet Echo" (Bonus Action, 30 feet).
  * The Earth Beats Once (typed options Necrotic/Psychic, Action, 90 feet, 10 Resonance, a Bloodied or Resonance Marked hostile
    creature): up to 3 Gravebeats (asked); Constitution save -- failed, 12d10 + Wisdom, no healing until the end of its next turn, Prone,
    and one consequence per Gravebeat (asked: Speed 0 until the start of your next turn, loses Concentration, a Grave Fracture of
    difficult terrain); succeeded, half, its next healing halved. Battlefield Afterbeat: hostile creatures of your choice within 20 feet
    of it make a Wisdom save -- 5d10 and no Reactions until the start of their next turn, or half.

Plug-in surface: effects thrum_gravebeat, thrum_march, thrum_drum, thrum_echo, thrum_earth; hooks event, damage_dealt,
healing_received, after_save_resolved, compile_actions, candidate_allowed. Shared helpers used: spirit_traditions (context/numbers/
feature_action/feature_of/pick_creature/routes/choose_route/save/remove/data_of/set_data), needle, zones (create, typed_zones),
rider_movement.step, typed_executor.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.thrum_of_the_grave.feature."
GRAVEBEAT = TRADITION + "gravebeat"
MARCH = TRADITION + "dead_march"
DRUM = TRADITION + "burial_drum"
UNQUIET = TRADITION + "call_the_unquiet"
EARTH = TRADITION + "the_earth_beats_once"
BEATS = "resource:named.gravebeat"
RESONANCE = "resource:core.resonance"
THRUMMING = "condition:typed.gravebeat_rhythm"
ECHO = "object:typed.unquiet_echo:"
MEMORIES = {"soldier": "Soldier's March", "mourner": "Mourner's Cry", "keeper": "Grave Keeper", "violence": "Unfinished Violence"}


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _numbers(engine: Any, actor: Any) -> dict[str, Any]:
    return st.numbers(engine, actor)


def _ctx(engine: Any, thrum: Any, feature: str, targets: list[Any], intent: Any = None) -> Any:
    return st.context(engine, thrum, st.feature_action(engine, thrum, feature), targets, _numbers(engine, thrum), intent)


def _held(creature: Any, condition_id: str) -> Any:
    return next((c for c in creature.conditions.values() if c.condition_id == condition_id and c.source_actor_id == creature.entity_id), None)


def _thrums(engine: Any) -> list[Any]:
    return [a for a in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if BEATS in a.resources and a.active]


def gain_beat(engine: Any, thrum: Any, why: str) -> None:
    """"You gain 1 Gravebeat when one of the following occurs within 60 feet, no more than once per turn\""""
    current = engine.state.actors.get(engine.state.current_actor_id or "")
    key = f"{engine.state.current_actor_id}:{int(getattr(current, 'turns_started', 0) or 0)}"
    if thrum.turn_flags.get("gravebeat_turn_round_") == key or thrum.resources.get(BEATS, 0) >= thrum.resource_maximums.get(BEATS, 0):
        return
    thrum.turn_flags["gravebeat_turn_round_"] = key
    engine._gain_resource(thrum, BEATS, 1, GRAVEBEAT)
    note(engine, GRAVEBEAT, thrum, f"{thrum.display_name} gains 1 Gravebeat ({why}).")


def _marked(creature: Any, thrum: Any) -> bool:
    return _te().bears_mark(creature, thrum.entity_id, "Resonance")


# ---------------------------------------------------------------------------------------------------------- Gravebeats and Gravebeat
@hook("event")
def thrum_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "CONDITION_APPLIED" and str((kwargs.get("payload") or {}).get("condition_id") or "").endswith((".unconscious", ".life_unconscious")):
        for target_id in kwargs.get("target_ids") or ():
            actor = engine.state.actors.get(target_id)
            held = _held(actor, THRUMMING) if actor is not None else None
            if held is not None:
                st.remove(engine, actor, held, "UNCONSCIOUS")
        return
    if event_type not in ("DAMAGE_COMMITTED", "ENTITY_DEFEATED"):
        return
    payload = kwargs.get("payload") or {}
    if event_type == "ENTITY_DEFEATED":
        fallen = engine.state.actors.get(kwargs.get("actor_id") or "")
        events = [(fallen, "defeated")] if fallen is not None and fallen.summon is None else []
    else:
        events = []
        for target_id in kwargs.get("target_ids") or ():
            victim = engine.state.actors.get(target_id)
            if victim is None or int(payload.get("hp_damage") or 0) <= 0:
                continue
            before = victim.current_hp + int(payload.get("hp_damage") or 0)
            if before > victim.maximum_hp // 2 >= victim.current_hp:
                events.append((victim, "bloodied"))  # "becomes Bloodied"
    for victim, what in events:
        for thrum in _thrums(engine):
            if victim.team_id == thrum.team_id or engine._distance_actor_to_actor(thrum, victim) > 60:
                continue
            if what == "defeated" or _marked(victim, thrum):
                gain_beat(engine, thrum, f"{victim.display_name} {'fell' if what == 'defeated' else 'became Bloodied'}")
            if _held(thrum, THRUMMING) is not None and engine._distance_actor_to_actor(thrum, victim) <= 30:
                _mark_near(engine, thrum, victim)


def _mark_near(engine: Any, thrum: Any, victim: Any) -> None:
    """Gravebeat: "you may place a Resonance Mark on one hostile creature within 10 feet of it without using an action.\""""
    near = [c for c in engine.state.actors.values() if c.active and c.team_id != thrum.team_id and (c is victim or engine._distance_actor_to_actor(victim, c) <= 10)]
    chosen = st.pick_creature(engine, engine._active_intent, thrum, near, checkpoint="GRAVEBEAT_MARK", choice_id="choice:needle.thrum.mark",
                              prompt=f"Gravebeat: {victim.display_name} falters -- Resonance Mark a hostile creature within 10 feet of it?",
                              name="Gravebeat", feature_id=GRAVEBEAT, allow_decline=True)
    if chosen is not None:
        _te().run_effects(_ctx(engine, thrum, GRAVEBEAT, [chosen]), [{"type": "mark", "mark": "Resonance", "applies_to": "target",
                                                                      "duration": {"kind": "until_end_of_your_next_turn"}, "evidence": "place a Resonance Mark"}])


@effect("thrum_gravebeat")
def gravebeat(ctx: Any, row: dict[str, Any]) -> None:
    held = _held(ctx.actor, THRUMMING)
    if held is None:
        ctx.engine._apply_condition(ctx.actor, THRUMMING, GRAVEBEAT, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data={"label": "Gravebeat"})


def _last_damage_type(engine: Any, target: Any) -> str:
    last = next((e for e in reversed(engine.events) if e.event_type == "DAMAGE_COMMITTED" and target.entity_id in (e.target_ids or ())), None)
    return str(((last.payload or {}).get("damage_type") if last is not None else "") or "").upper()


@hook("damage_dealt")
def grave_damage(ctx: Any, target: Any, amount: int) -> None:
    engine, thrum = ctx.engine, ctx.actor
    if amount <= 0 or target is None or target.team_id == thrum.team_id or _last_damage_type(engine, target) not in ("PSYCHIC", "NECROTIC") or not _marked(target, thrum):
        return
    kind = _last_damage_type(engine, target).lower()
    turn_key = f"{engine.state.current_actor_id}:{engine.state.round_number}"
    if _held(thrum, THRUMMING) is not None and thrum.turn_flags.get("gravebeat_damage_round_") != turn_key:
        thrum.turn_flags["gravebeat_damage_round_"] = turn_key  # "Once per turn ... add your Proficiency Bonus to the damage"
        _te().run_effects(st.context(engine, thrum, ctx.action, [target], ctx.numbers, ctx.intent),
                          [{"type": "damage", "applies_to": "target", "flat": int(_numbers(engine, thrum).get("pb") or 2), "damage_types": [kind],
                            "evidence": "add your Proficiency Bonus to the damage"}])
    echo = echo_of(engine, thrum)
    if (echo is not None and (echo.component or {}).get("memory") == "violence" and _near(engine, echo, target, 15)
            and thrum.turn_flags.get("unfinished_violence_round_") != turn_key):
        thrum.turn_flags["unfinished_violence_round_"] = turn_key  # Unfinished Violence: "Once per turn ... add 2d8 damage"
        _te().run_effects(st.context(engine, thrum, ctx.action, [target], ctx.numbers, ctx.intent),
                          [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": [kind], "evidence": "add 2d8 damage"}])


# ---------------------------------------------------------------------------------------------------------- Dead March
MARCHES = {"grave": "Toward the Grave: it spends its Reaction moving up to half its Speed where you choose",
           "step": "Fall Into Step: no Reactions and Speed -15 until the start of your next turn",
           "past": "March Past the Living: it moves up to half its Speed away from a creature you name",
           "kneel": "Kneel to the Beat: it falls Prone (if it is Bloodied, Frightened or bears two of your marks)"}


def _march_one(engine: Any, thrum: Any, ctx: Any, target: Any) -> None:
    from . import needle
    from .rider_movement import step

    sub = st.context(engine, thrum, ctx.action, [target], ctx.numbers, ctx.intent)
    until = {"kind": "until_start_of_your_next_turn"}
    if not st.save(sub, target, "wis"):
        _te().run_effects(sub, [{"type": "speed", "applies_to": "target", "flat": -10, "duration": until, "evidence": "Its Speed is reduced by 10 feet until the start of your next turn."}])
        return
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "DEAD_MARCH", target.entity_id), thrum, "choice:needle.thrum.march",
                        list(MARCHES), labels=MARCHES, preferred=["step"], prompt=f"Dead March: {target.display_name} failed -- choose a March.", name="Dead March",
                        feature_id=MARCH, target_id=target.entity_id)
    pick = chosen[0] if chosen and chosen[0] in MARCHES else "step"
    half = max(5, engine._effective_speed(target) // 2)
    if pick == "step":
        _te().run_effects(sub, [{"type": "reaction_denied", "applies_to": "target", "duration": until, "evidence": "It cannot take Reactions"},
                                {"type": "speed", "applies_to": "target", "flat": -15, "duration": until, "evidence": "its Speed is reduced by 15 feet"}])
    elif pick == "grave":
        if not target.reaction_available:
            return  # "It uses its Reaction, if available"
        target.reaction_available = False
        spots = {c: v for c, v in st.routes(engine, target, half).items() if c != target.position}
        path = st.choose_route(engine, thrum, spots, ctx.intent, checkpoint="TOWARD_THE_GRAVE", prompt=f"Toward the Grave: move {target.display_name} where?",
                               name="Dead March", feature=MARCH, stay=False) if spots else None
        if path is not None:
            step(engine, target, list(path), MARCH)
    elif pick == "past":
        others = [c for c in engine.state.actors.values() if c.active and c is not target]
        away = st.pick_creature(engine, ctx.intent, thrum, others, checkpoint="MARCH_PAST", choice_id="choice:needle.thrum.march_past",
                                prompt="March Past the Living: away from whom?", name="Dead March", feature_id=MARCH, preferred=thrum)
        away = away or thrum
        routes = st.routes(engine, target, half)
        best = max(routes, key=lambda c: (engine.grid.distance_ft(c, away.position), -routes[c][1]))
        if best != target.position:
            step(engine, target, list(routes[best][0]), MARCH)
    elif pick == "kneel":
        marks = sum(1 for c in target.conditions.values() if c.condition_id.startswith(_te().MARK_PREFIX) and c.source_actor_id == thrum.entity_id)
        if target.current_hp <= target.maximum_hp // 2 or any(str(c.condition_id).endswith(".frightened") for c in target.conditions.values()) or marks >= 2:
            _te().run_effects(sub, [{"type": "condition", "applies_to": "target", "condition": "prone", "duration": {"kind": "until_removed"}, "evidence": "it falls Prone"}])


@effect("thrum_march")
def dead_march(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, thrum = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    if target is None or not target.active:
        return
    extra: list[Any] = []
    beats = min(2, int(thrum.resources.get(BEATS, 0)))
    near = [c for c in engine.state.actors.values() if c.active and c is not target and c.team_id != thrum.team_id and engine._distance_actor_to_actor(target, c) <= 15]
    if beats and near:
        ids = [c.entity_id for c in near]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "PROCESSIONAL_CHAIN", thrum.entity_id), thrum, "choice:needle.thrum.chain",
                            ids, labels={c.entity_id: c.display_name for c in near}, preferred=ids[:beats], minimum=1, maximum=min(beats, len(ids)), allow_decline=True,
                            prompt="Processional Chain: spend a Gravebeat for each more creature within 15 feet?", name="Dead March", feature_id=MARCH)
        extra = [c for c in near if c.entity_id in (chosen or [])][:beats]
        if extra:
            engine._spend_resource(thrum, BEATS, len(extra), MARCH)
    for creature in [target, *extra]:
        _march_one(engine, thrum, ctx, creature)


# ---------------------------------------------------------------------------------------------------------- Burial Drum
def drum_of(engine: Any, thrum: Any) -> Any:
    from .. import zones

    return next((z for z in zones.typed_zones(engine) if z.owner_id == thrum.entity_id and st.feature_of(engine.action_catalog.get(z.source_definition_id)) == DRUM), None)


@hook("healing_received")
def burial_drum(engine: Any, subject: Any, amount: int) -> int | None:
    """"When a hostile creature in the aura would regain Hit Points, it makes a Wisdom saving throw" (once per turn)."""
    for thrum in _thrums(engine):
        zone = drum_of(engine, thrum)
        if zone is None or subject.team_id == thrum.team_id or not engine._footprint_intersects(subject, zone.affected_cells):
            continue
        current = engine.state.actors.get(engine.state.current_actor_id or "")
        key = f"{engine.state.current_actor_id}:{int(getattr(current, 'turns_started', 0) or 0)}"
        if subject.turn_flags.get("burial_drum_save_round_") == key:
            return None
        subject.turn_flags["burial_drum_save_round_"] = key
        sub = _ctx(engine, thrum, DRUM, [subject])
        if not st.save(sub, subject, "wis"):
            return amount // 2  # "Successful Save: The healing is halved."
        gain_beat(engine, thrum, f"{subject.display_name} failed to regain Hit Points")
        from .creature_kinds import matches
        if matches(subject, ["undead", "possessed", "death-sustained"]) or _marked(subject, thrum) or subject.life_state == "DYING" or any(str(c.condition_id).endswith(".frightened") for c in subject.conditions.values()):
            _te().run_effects(sub, [{"type": "damage", "applies_to": "target", "flat": 2 * int(_numbers(engine, thrum).get("pb") or 2), "damage_types": ["necrotic"],
                                     "evidence": "it also takes Necrotic or Psychic damage equal to 2 x Proficiency Bonus"}])
        return 0
    return None


@effect("thrum_drum")
def beat_of_interment(ctx: Any, row: dict[str, Any]) -> None:
    engine, thrum = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    thrum.turn_flags["beat_of_interment"] = True  # "Once on each of your turns"
    if target is None:
        return
    engine._spend_resource(thrum, BEATS, 1, DRUM)
    _te().run_effects(ctx, [{"type": "save", "ability": "con", "dc": "technique_save_dc", "applies_to": "target",
                             "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "formula": "key_ability_modifier", "damage_types": ["necrotic"],
                                          "evidence": "It takes 3d8 + Wisdom modifier Necrotic or Psychic damage"},
                                         {"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_next_turn"}, "evidence": "and cannot take Reactions"}],
                             "on_success": [{"type": "half_damage", "applies_to": "target", "evidence": "It takes half damage."}],
                             "evidence": "It makes a Constitution saving throw."}])


# ---------------------------------------------------------------------------------------------------------- Call the Unquiet
def echo_of(engine: Any, thrum: Any) -> Any:
    return next((o for o in engine.state.objects.values() if o.object_id.startswith(ECHO) and o.owner_id == thrum.entity_id and not o.destroyed), None)


def _near(engine: Any, obj: Any, creature: Any, feet: int) -> bool:
    from ..gate2_runtime_models import Position
    return any(engine.grid.distance_ft(obj.position, Position(x=x, y=y, z=z)) <= feet
               for x, y, z in engine._actor_volume(creature))


@hook("death_save_mode")
def grave_keeper(engine: Any, actor: Any) -> str | None:
    """Live Grave Keeper membership: beneficial choices affect allies only."""
    from ..effect_cover import rays
    return "ADVANTAGE" if any(thrum.team_id == actor.team_id and (echo := echo_of(engine, thrum)) is not None
        and (echo.component or {}).get("memory") == "keeper" and _near(engine, echo, actor, 10)
        and next(rays(engine, (echo.position,), engine._actor_volume(actor), purpose="effect"), None) is not None
        for thrum in _thrums(engine)) else None


@hook("object_damage_defenses")
def unquiet_defenses(engine: Any, actor: Any, obj: Any, packets: Any, source: Any) -> list[dict[str, Any]] | None:
    if not str(obj.object_id).startswith(ECHO) or obj.destroyed:
        return None
    return [{"kind": "resistance", "damage_types": ["NECROTIC", "PSYCHIC"]}]


@effect("thrum_echo")
def unquiet_echo(ctx: Any, row: dict[str, Any]) -> None:
    from ..gate2_runtime_models import RuntimeObjectState
    from . import needle

    engine, thrum = ctx.engine, ctx.actor
    mode = row.get("mode") or "call"
    obj = echo_of(engine, thrum)
    spot = getattr(ctx, "destination", None) or getattr(ctx.intent, "destination", None)
    if mode == "call":
        if spot is None:
            return
        if obj is not None:
            engine._update_object(obj.model_copy(update={"destroyed": True, "component": {**(obj.component or {}), "dismissed": True}}), UNQUIET, thrum.entity_id)
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "DEATH_MEMORY", thrum.entity_id), thrum, "choice:needle.thrum.memory",
                            list(MEMORIES), labels=MEMORIES, preferred=["violence"], prompt="Call the Unquiet: which Death Memory does the Echo carry?",
                            name="Call the Unquiet", feature_id=UNQUIET)
        numbers = ctx.numbers or _numbers(engine, thrum)
        hp = 6 * int(numbers.get("pb") or 2)
        engine._update_object(RuntimeObjectState(object_id=f"{ECHO}{thrum.entity_id}:{engine.state.event_sequence}", object_kind="UNQUIET_ECHO", position=spot,
                                                 unattended=False, flammable=False, owner_id=thrum.entity_id, ac=int(numbers.get("save_dc") or 10), current_hp=hp,
                                                 maximum_hp=hp, component={"label": f"Unquiet Echo ({MEMORIES[(chosen or ['violence'])[0]]})",
                                                                           "memory": (chosen or ["violence"])[0]}), UNQUIET, thrum.entity_id)
    elif mode == "direct" and obj is not None and spot is not None:
        engine._update_object(obj.model_copy(update={"position": spot}), UNQUIET, thrum.entity_id)
    elif mode == "cry" and obj is not None:
        thrum.turn_flags["grave_cry"] = True  # "Once on each of your turns"
        target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
        if target is None:
            return
        engine._spend_resource(thrum, BEATS, 1, UNQUIET)
        _te().run_effects(ctx, [{"type": "save", "ability": "wis", "dc": "technique_save_dc", "applies_to": "target",
                                 "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["psychic"], "evidence": "It takes 3d8 Psychic damage"},
                                             {"type": "condition", "applies_to": "target", "condition": "frightened", "duration": {"kind": "until_end_of_next_turn"},
                                              "evidence": "and becomes Frightened until the end of its next turn"}],
                                 "on_success": [{"type": "half_damage", "applies_to": "target", "evidence": "It takes half damage."}],
                                 "evidence": "The target makes a Wisdom saving throw."}])


@hook("after_save_resolved")
def mourners_cry(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Mourner's Cry: "Once per turn when a creature within 15 feet of the Echo fails a Wisdom saving throw against you, it becomes Frightened
    of the Echo until the end of its next turn.\""""
    engine, thrum = ctx.engine, ctx.actor
    if not failed or subject is None or thrum is None or str(ability or "").upper()[:3] != "WIS" or subject.team_id == thrum.team_id:
        return
    echo = echo_of(engine, thrum) if BEATS in thrum.resources else None
    turn_key = f"{engine.state.current_actor_id}:{engine.state.round_number}"
    if echo is None or (echo.component or {}).get("memory") != "mourner" or not _near(engine, echo, subject, 15) or thrum.turn_flags.get("mourners_cry_round_") == turn_key:
        return
    thrum.turn_flags["mourners_cry_round_"] = turn_key
    _te().run_effects(_ctx(engine, thrum, UNQUIET, [subject], ctx.intent),
                      [{"type": "condition", "applies_to": "target", "condition": "frightened", "duration": {"kind": "until_end_of_next_turn"},
                        "evidence": "it becomes Frightened of the Echo until the end of its next turn"}])


# ---------------------------------------------------------------------------------------------------------- The Earth Beats Once
CONSEQUENCES = {"still": "Speed 0 until the start of your next turn", "unfocus": "It loses Concentration", "fracture": "A Grave Fracture under it (10-foot difficult terrain)"}


@effect("thrum_earth")
def earth_beats(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle
    from .. import zones

    engine, thrum = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    if target is None or not target.active:
        return
    kind = str(row.get("kind") or "necrotic")
    beats = min(3, int(thrum.resources.get(BEATS, 0)))
    picks: list[str] = []
    if beats:
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "EARTH_BEATS", target.entity_id), thrum, "choice:needle.thrum.consequences",
                            list(CONSEQUENCES), labels=CONSEQUENCES, preferred=list(CONSEQUENCES)[:beats], minimum=1, maximum=min(beats, len(CONSEQUENCES)),
                            allow_decline=True, prompt="The Earth Beats Once: spend a Gravebeat for each consequence (on a failed save)?", name="The Earth Beats Once",
                            feature_id=EARTH)
        picks = [p for p in (chosen or []) if p in CONSEQUENCES][:beats]
        if picks:
            engine._spend_resource(thrum, BEATS, len(picks), EARTH)
    if st.save(ctx, target, "con"):
        until = {"kind": "until_end_of_next_turn"}
        _te().run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 12, "sides": 10}, "formula": "key_ability_modifier", "damage_types": [kind],
                                 "evidence": f"It takes 12d10 + Wisdom modifier {kind.title()} damage"},
                                {"type": "healing_reduction", "applies_to": "target", "duration": until, "evidence": "it cannot regain Hit Points until the end of its next turn"},
                                {"type": "condition", "applies_to": "target", "condition": "prone", "duration": {"kind": "until_removed"}, "evidence": "and is knocked Prone"}])
        if "still" in picks:
            _te().run_effects(ctx, [{"type": "speed", "applies_to": "target", "becomes": 0, "duration": {"kind": "until_start_of_your_next_turn"}, "evidence": "reduce its Speed to 0"}])
        if "unfocus" in picks and target.concentration is not None:
            engine._end_concentration(target, "THE_EARTH_BEATS_ONCE")
        if "fracture" in picks:
            zones.create(ctx, {"shape": "sphere", "size_ft": 10, "difficult": "all", "duration": {"kind": "scene"}, "name": "Grave Fracture"})
    else:
        _half_damage(engine, thrum, ctx, target, kind)  # "Successful Save: It takes half damage"
        _te().run_effects(ctx, [{"type": "healing_reduction", "applies_to": "target", "duration": {"kind": "until_end_of_next_turn"},
                                 "evidence": "its next healing before the end of its next turn is halved"}])
    # Battlefield Afterbeat: "Every other hostile creature of your choice within 20 feet of the primary target ... makes a Wisdom saving throw."
    others = [c for c in engine.state.actors.values() if c.active and c is not target and c.team_id != thrum.team_id and engine._distance_actor_to_actor(target, c) <= 20]
    if others:
        ids = [c.entity_id for c in others]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "AFTERBEAT", thrum.entity_id), thrum, "choice:needle.thrum.afterbeat", ids,
                            labels={c.entity_id: c.display_name for c in others}, preferred=ids, minimum=1, maximum=len(ids), default="all", allow_decline=True,
                            prompt="Battlefield Afterbeat: which hostile creatures within 20 feet?", name="The Earth Beats Once", feature_id=EARTH)
        for creature in [c for c in others if c.entity_id in (chosen or [])]:
            _te().run_effects(st.context(engine, thrum, ctx.action, [creature], ctx.numbers, ctx.intent),
                              [{"type": "save", "ability": "wis", "dc": "technique_save_dc", "applies_to": "target",
                                "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 5, "sides": 10}, "damage_types": [kind], "evidence": "It takes 5d10 damage"},
                                            {"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_next_turn"}, "evidence": "and cannot take Reactions"}],
                                "on_success": [{"type": "half_damage", "applies_to": "target", "evidence": "It takes half damage."}],
                                "evidence": "It makes a Wisdom saving throw."}])


def _half_damage(engine: Any, thrum: Any, ctx: Any, target: Any, kind: str) -> None:
    """The successful save's half of 12d10 + Wisdom (rolled, then halved)."""
    from ..gate2_runtime_models import DiceSpec

    wis = int((ctx.numbers or _numbers(engine, thrum)).get("key_mod") or 0)
    roll = engine.roller.roll(DiceSpec(count=12, sides=10, modifier=wis), actor_id=thrum.entity_id, reason=f"DAMAGE:{EARTH}")
    engine._record_roll(roll)
    engine._commit_damage(target, max(0, int(roll.total)) // 2, kind.upper(), ctx.source, thrum.entity_id, ctx.intent, reaction_depth=1)


# ---------------------------------------------------------------------------------------------------------- buttons and gates
@hook("compile_actions")
def thrum_buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned, out = info["owned_ids"], []

    def button(key: str, name: str, economy: Any, target: str, range_ft: int | None, rows: list[dict[str, Any]], text: str, source: str) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.thrum.{key}", display_name=name, owner_id=info["actor_id"], economy=economy,
                                resolution_kind="TYPED", target_kind=target, range_ft=range_ft,
                                parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": source, "effects": rows},
                                            "expected_damage": 0, "thrum": key, "description": text})

    if DRUM in owned:
        out.append(button("interment", "Burial Drum: Beat of Interment", EconomyKind.NONE, "HOSTILE_ENTITY", 30, [{"type": "thrum_drum", "applies_to": "target", "harmful": True}],
                          "Burial Drum (free, once on each of your turns, 1 Gravebeat): a hostile creature in the aura makes a Constitution save; 3d8 + your Wisdom "
                          "modifier and no Reactions until the start of its next turn, or half.", DRUM))
    if UNQUIET in owned:
        out.append(button("cry", "Unquiet Echo: Grave Cry", EconomyKind.NONE, "HOSTILE_ENTITY", 120, [{"type": "thrum_echo", "applies_to": "target", "mode": "cry", "harmful": True}],
                          "Call the Unquiet (free, once on each of your turns, 1 Gravebeat): a creature within 30 feet of the Echo makes a Wisdom save; 3d8 Psychic "
                          "and Frightened until the end of its next turn, or half.", UNQUIET))
        out.append(button("direct", "Direct the Unquiet Echo", EconomyKind.BONUS_ACTION, "SELF", None,
                          [{"type": "thrum_echo", "applies_to": "self", "mode": "direct", "picks_destination": True, "distance_ft": 120}],
                          "Call the Unquiet (Bonus Action): the Unquiet Echo moves up to 30 feet.", UNQUIET))
    return out or None


@hook("candidate_allowed")
def thrum_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    key = str((action.parameters or {}).get("thrum") or "")
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if st.feature_of(action) == EARTH and target is not None:
        # "Requirement: A Bloodied or Resonance Marked hostile creature standing on or touching earth ..."
        return None if target.current_hp <= target.maximum_hp // 2 or _marked(target, actor) else False
    if key == "interment":
        zone = drum_of(engine, actor)
        return None if zone is not None and actor.resources.get(BEATS, 0) >= 1 and not actor.turn_flags.get("beat_of_interment") and target is not None \
            and engine._footprint_intersects(target, zone.affected_cells) else False
    if key in ("cry", "direct"):
        obj = echo_of(engine, actor)
        if obj is None:
            return False
        if key == "cry":
            return None if actor.resources.get(BEATS, 0) >= 1 and not actor.turn_flags.get("grave_cry") and target is not None and _near(engine, obj, target, 30) else False
        spot = getattr(candidate, "destination", None)
        return None if spot is None or engine.grid.distance_ft(obj.position, spot) <= 30 else False
    return None


@hook("after_save_resolved")
def gravebeat_failed_spirit(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    from .creature_kinds import matches

    if (failed and subject is not None and subject.team_id != ctx.actor.team_id
            and BEATS in ctx.actor.resources
            and matches(subject, ["undead", "haunt", "possessed"])
            and ctx.engine._distance_actor_to_actor(ctx.actor, subject) <= 60):
        gain_beat(ctx.engine, ctx.actor, f"{subject.display_name} failed your saving throw")


@hook("death_save_failure")
def gravebeat_failed_death_save(engine: Any, target: Any, natural: int, source_id: str) -> None:
    """A hostile creature's failed death saving throw within 60 feet gives its Gravebeat owner a Gravebeat.

    The failure itself is not ignored, so this provider always returns None. Gravebeat's own once-per-turn
    and pool limits apply through gain_beat."""
    if target is None:
        return None
    for owner in _thrums(engine):
        if (owner.team_id != target.team_id and owner.active
                and engine._distance_actor_to_actor(owner, target) <= 60):
            gain_beat(engine, owner, f"{target.display_name} failed a death saving throw")
    return None


@hook("event", nested=True)
def gravebeat_unconscious(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED":
        return
    condition_id = (kwargs.get("payload") or {}).get("condition_id")
    if condition_id not in ("condition:typed.unconscious", "condition:typed.life_unconscious"):
        return
    for actor_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(actor_id)
        if actor is None:
            continue
        rhythm = _held(actor, THRUMMING)
        if rhythm is not None:
            st.remove(engine, actor, rhythm, "UNCONSCIOUS")


@hook("compile_actions")
def dismiss_gravebeat_action(info: dict[str, Any]) -> list[Any] | None:
    if GRAVEBEAT not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.dismiss_gravebeat", display_name="Dismiss Gravebeat",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "thrum_dismiss_rhythm", "applies_to": "self"}],
                               "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": GRAVEBEAT},
                    "expected_damage": 0, "thrum_dismiss": True, "description": "End your Gravebeat rhythm."})]


@hook("candidate_allowed")
def dismiss_gravebeat_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and (action.parameters or {}).get("thrum_dismiss"):
        return None if _held(actor, THRUMMING) is not None else False
    return None


@effect("thrum_dismiss_rhythm")
def dismiss_gravebeat(ctx: Any, row: dict[str, Any]) -> None:
    rhythm = _held(ctx.actor, THRUMMING)
    if rhythm is not None:
        st.remove(ctx.engine, ctx.actor, rhythm, "DISMISSED")
