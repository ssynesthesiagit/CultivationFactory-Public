"""Dreamweaver (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "01. Dreamweaver": Dream Threads, CL3 Dream Stitch, CL6 Unreality Bites Back, CL10
Waking Dream Revision, CL14 Eternal Dream Refuge, CL18 World of One, Normalized Execution Notes). No Spheres 5e or D&D 5.5e counterpart.
Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json (Waking Dream Revision keeps its
``d20_rewrite`` row of auto_H1.json); every hook returns early without them.

What runs:
  * Dream Threads: the "Dream Thread" mark (one on a creature, up to your Proficiency Bonus at once -- the oldest ends -- the scene).
  * Dream Stitch (Reaction, 1 Resonance): a perceived creature within 60 feet declares an attack; before the roll it has Disadvantage.
    An attack already rolling with Disadvantage instead subtracts PB through the ordinary signed d20-bonus receipt.
    If it misses you choose: Resonance Marked by you, or a Dream Thread on it. Asked; the AI stitches attacks on itself or its allies.
  * Unreality Bites Back (Reaction, 2 Resonance): when a creature escapes your World of One, it makes a Wisdom save -- 3d10 Psychic,
    Resonance Marked, your Spiritual Pressure and a Dream Thread on a failure; half and a Dream Thread on a success. The escape stands.
  * Waking Dream Revision: Rehearse Success is combat/ext/d20_rewrite_rules.py; Rehearse Failure (a hostile creature bearing your Dream
    Thread within 60 feet succeeds on a d20 Test: it rerolls; 3 Resonance, your Reaction, the same once-per-round limit) is here.
    Lucid Resistance: Advantage on your saves against sleep (Unconscious) and against Dreams-sphere, Dream Eater and Dreamweaver effects.
  * Eternal Dream Refuge (6 Resonance, once per fight, asked): instead of leaving the fight at 0 Hit Points you lie Unconscious and
    Stable in a 20-foot Dream Refuge for up to 3 rounds; your body has Resistance to damage other than Psychic and Force; a hostile
    creature that enters it or starts its turn there makes a Wisdom save -- Dream Sleep (Unconscious until the end of its next turn
    or until damaged) on a failure, Speed -10 and no Reactions until the start of its next turn on a success. An ally in it can use its
    Action for Refuge Recall ("speak your name and a shared memory"): you wake with 2 x Proficiency Bonus Hit Points. After the third
    round you wake with 1 Hit Point and a level of Exhaustion.
  * World of One (Concentration): a creature bearing your Dream Thread has Disadvantage on the first save. Failed: Incapacitated and
    Prone in its personal dream; at the end of each of its turns 6d10 Psychic, then one escape attempt (a Wisdom save, or an
    Intelligence (Investigation) / Wisdom (Insight) / Charisma (Persuasion) check against your Cultivation Save DC -- its choice, asked,
    the AI takes its best); damage to its body gives the next attempt Advantage. Success: half, your Spiritual Pressure and a Dream Thread
    (asked).

An adjacent creature may spend an Action to wake Dream Sleep; automatic owners choose allies only.

Plug-in surface: effects dreamweaver_wake, dreamweaver_world, dreamweaver_refuge_sleep, dreamweaver_recall; hooks before_attack, event, save, zero_hp,
incoming_damage, turn_start, turn_end, match_start, additional_actions, compile_actions (Dream-Thread Passage: a Bonus Action,
1 Resonance, a creature bearing your Dream Thread cannot benefit from Hidden/Invisible against you until the end of your turn). Shared helpers used: spirit_traditions (row/context/can_react/
feature_of), d20_rewrite (Rule/register/row_holders), life_state (wants_dying/restore_hp/UNCONSCIOUS), needle.ask, zones.create.
"""

from __future__ import annotations

from ..paid_relocation import activation, capture, causal_scope, retain, take, preserve_pending

from typing import Any

from . import effect, hook, note, ai_controlled
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.dreamweaver.feature."
STITCH = TRADITION + "dream_stitch"
UNREALITY = TRADITION + "unreality_bites_back"
REVISION = TRADITION + "waking_dream_revision"
REFUGE = TRADITION + "eternal_dream_refuge"
WORLD = TRADITION + "world_of_one"
THREAD = "Dream Thread"
RESONANCE = "resource:core.resonance"
IN_WORLD = "condition:typed.world_of_one"
REFUGE_ON = "condition:typed.dream_refuge"
REFUGE_USED = "condition:typed.dream_refuge_used"
DREAM_SLEEP = "condition:typed.dream_sleep"
RECALL = "system:combat.dream_refuge_recall"
_STITCHED = "_c8_dream_stitch"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _remove(engine: Any, holder: Any, condition: Any, reason: str) -> None:
    for iid, held in list(holder.conditions.items()):
        if held is condition:
            holder.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=held.source_actor_id,
                                 target_ids=(holder.entity_id,), payload={"condition_id": held.condition_id, "instance_id": iid, "reason": reason})


def _ctx(engine: Any, actor: Any, feature: str, targets: list[Any], intent: Any = None) -> Any:
    return st.context(engine, actor, st.feature_action(engine, actor, feature), targets, st.numbers(engine, actor), intent)


def thread(ctx: Any, subject: Any) -> None:
    _te().block_mark(st.context(ctx.engine, ctx.actor, ctx.action, [subject], ctx.numbers, ctx.intent),
                     {"type": "mark", "mark": THREAD, "applies_to": "target", "evidence": "Create a Dream Thread"})


def _saved(engine: Any, before: int, subject: Any) -> bool | None:
    rolled = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == subject.entity_id]
    return bool((rolled[-1].payload or {}).get("success")) if rolled else None


# ---------------------------------------------------------------------------------------------------------------- Dream Stitch
@hook("before_attack")
def dream_stitch(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    if attacker is None or defender is None:
        return None
    from ..target_knowledge import can_see

    for weaver in engine.state.actors.values():
        if (not weaver.active or (ai_controlled(engine, weaver) and weaver.team_id == attacker.team_id) or st.row(engine, weaver, "dream_stitch") is None or not st.can_react(weaver)
                or weaver.resources.get(RESONANCE, 0) < 1 or engine.grid.distance_ft(weaver.position, attacker.position) > 60):
            continue
        from . import needle
        from ..target_knowledge import can_see
        if not can_see(engine, weaver, attacker):
            continue
        # Ask the same source-aware mode query used by strike resolution. Named
        # removals (such as Far Shot's long-range exception) need this strike's
        # provenance or the reaction can offer the wrong branch.
        from .. import attack_modes
        source_id = context.get("source_id")
        ranged = bool(context["ranged"])
        removed = attack_modes.removed(engine, attacker, defender, ranged=ranged)
        provenance = attack_modes.provenance_for(engine, attacker, defender, source_id)
        already_disadvantaged = engine._attack_mode(attacker, defender, removed=removed,
                                                    provenance=provenance) == "DISADVANTAGE"
        protects = defender.team_id == weaver.team_id
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "DREAM_STITCH", attacker.entity_id, context.get("attack_index", 1)), weaver,
                            "choice:needle.dreamweaver.dream_stitch", ["stitch"],
                            labels={"stitch": (f"Dream Stitch: subtract {int(st.numbers(engine, weaver).get('pb') or 2)} from {attacker.display_name}'s attack roll (1 Resonance, your Reaction)"
                                                   if already_disadvantaged else f"Dream Stitch: Disadvantage on {attacker.display_name}'s attack (1 Resonance, your Reaction)")},
                            prompt=(f"{attacker.display_name} attacks {defender.display_name}. It already has Disadvantage; Dream Stitch subtracts your Proficiency Bonus from its attack roll. "
                                    if already_disadvantaged else f"{attacker.display_name} attacks {defender.display_name}. Use Dream Stitch? ") + "If it misses, you may Resonance Mark "
                                   "it or put a Dream Thread on it.", preferred=["stitch"] if protects else [], allow_decline=True,
                            default="first" if protects else "decline", name="Dream Stitch", feature_id=STITCH, target_id=attacker.entity_id)
        if not chosen:
            continue
        with activation(engine, weaver, STITCH):
            engine._spend_resource(weaver, RESONANCE, 1, STITCH)
            weaver.reaction_available = False
            engine._append_event("REACTION_RESOLVED", STITCH, actor_id=weaver.entity_id, target_ids=(attacker.entity_id,),
                                 payload={"checkpoint": "ATTACK_DECLARED", "reaction_name": "Dream Stitch"})
            preserve_pending(engine, _STITCHED)
            engine.__dict__[_STITCHED] = {"weaver": weaver.entity_id, "attacker": attacker.entity_id,
                                          "roll": f"ATTACK:{context.get('source_id')}:{context.get('attack_index', 1)}",
                                          "intent_id": getattr(intent, "intent_id", None),
                                          "penalty": int(st.numbers(engine, weaver).get("pb") or 2) if already_disadvantaged else 0}
            retain(engine, _STITCHED, capture(engine))
            return {"mode": "DISADVANTAGE", "disadvantage_penalty": -int(st.numbers(engine, weaver).get("pb") or 2)}
    return None


@hook("event")
def stitch_missed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "ATTACK_ROLLED":
        return
    held = engine.__dict__.get(_STITCHED)
    payload = kwargs.get("payload") or {}
    if not held or kwargs.get("actor_id") != held["attacker"] or str(payload.get("reason") or "") != held["roll"]:
        return
    with causal_scope(engine, take(engine, _STITCHED)):
        preserve_pending(engine, _STITCHED)
        engine.__dict__.pop(_STITCHED, None)
        if payload.get("provisional_hit"):
            return
        weaver, attacker = engine.state.actors.get(held["weaver"]), engine.state.actors.get(held["attacker"])
        if weaver is None or attacker is None or not attacker.active:
            return
        from . import needle

        has_thread = _te().bears_mark(attacker, weaver.entity_id, THREAD)
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "DREAM_STITCH_MISS", attacker.entity_id), weaver,
                            "choice:needle.dreamweaver.stitch_miss", ["mark", "thread"],
                            labels={"mark": f"{attacker.display_name} becomes Resonance Marked by you", "thread": f"Create a Dream Thread on {attacker.display_name}"},
                            preferred=["mark" if has_thread else "thread"], prompt="Dream Stitch: the attack missed. Choose one.",
                            name="Dream Stitch", feature_id=STITCH, target_id=attacker.entity_id)
        pick = chosen[0] if chosen else ("mark" if has_thread else "thread")
        ctx = _ctx(engine, weaver, STITCH, [attacker])
        if pick == "mark":
            _te().block_mark(ctx, {"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"}})
        else:
            thread(ctx, attacker)


# --------------------------------------------------------------------------------------------------- Waking Dream Revision
def _thread_guard(engine: Any, holder: Any, rc: Any) -> bool:
    return rc.roller.team_id != holder.actor.team_id and _te().bears_mark(rc.roller, holder.actor.entity_id, THREAD)


def _register_rules() -> None:
    from .d20_rewrite import Rule, register

    register(Rule("waking_dream_rehearse_failure", "Waking Dream Revision (Rehearse Failure)", feature=REVISION,
                  rolls=("save", "attack", "check"), who="enemy", range_ft=60, see=True, when="succeeded", costs=((("resonance", 3),),),
                  reaction=True, limit="round", checkpoint="D20_REWRITE_ROLL", guard=_thread_guard))


_register_rules()


@hook("save")
def lucid_resistance(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    from .passive_rows import row_of

    if subject is None or row_of(ctx.engine, subject.entity_id, "d20_rewrite", "waking_dream_rehearse_success") is None:
        return None
    feature = st.feature_of(ctx.action)
    typed = (ctx.action.parameters or {}).get("typed") or {}
    dreamy = feature.startswith(("tianxia.tradition.spirit.dream_eater.", TRADITION)) or "dream" in str(typed.get("sphere") or "")
    if not (dreamy or "unconscious" in {str(n) for n in (named or ())}):
        return None
    return {"bonus": 0, "modes": ["ADVANTAGE"]}


# ---------------------------------------------------------------------------------------------------------------- World of One
@effect("dreamweaver_world")
def world_of_one(ctx: Any, row: dict[str, Any]) -> None:
    engine, subject = ctx.engine, ctx.target
    if subject is None or not subject.active:
        return
    te = _te()
    before = len(engine.events)
    engine.__dict__["_c8_world_disadvantage"] = subject.entity_id if te.bears_mark(subject, ctx.actor.entity_id, THREAD) else None
    try:
        te.block_save(ctx, {"type": "save", "applies_to": "target", "ability": "wis", "on_fail": [], "on_success": []})
    finally:
        engine.__dict__.pop("_c8_world_disadvantage", None)
    saved = _saved(engine, before, subject)
    if saved is None:
        return
    if saved:
        te.run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 10}, "damage_types": ["psychic"],
                              "evidence": "half of 6d10 Psychic damage"},
                             {"type": "spiritual_pressure", "applies_to": "target"}])
        from . import needle

        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "WORLD_THREAD", subject.entity_id), ctx.actor,
                            "choice:needle.dreamweaver.world_thread", ["thread"], labels={"thread": f"Create a Dream Thread on {subject.display_name}"},
                            preferred=["thread"], allow_decline=True, prompt="World of One: the target resisted. Create a Dream Thread on it?",
                            name="World of One", feature_id=WORLD, target_id=subject.entity_id)
        if chosen:
            thread(ctx, subject)
        return
    te.run_effects(ctx, [{"type": "condition", "applies_to": "target", "condition": "incapacitated", "evidence": "Its body becomes Incapacitated"},
                         {"type": "condition", "applies_to": "target", "condition": "prone", "evidence": "falls Prone if able"}])
    engine._apply_condition(subject, IN_WORLD, ctx.source, ctx.actor.entity_id, expires_on=ctx.expires_on() or "CONCENTRATION_END",
                            data={"dc": int(ctx.numbers.get("save_dc") or 10), "advantage": 0,
                                  "label": "World of One: drawn into a personal dream (6d10 Psychic at the end of each of its turns, then one escape attempt)"})


@hook("save")
def world_disadvantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    return {"bonus": 0, "modes": ["DISADVANTAGE"]} if ctx.engine.__dict__.get("_c8_world_disadvantage") == getattr(subject, "entity_id", None) else None


def _world(creature: Any) -> Any:
    return next((c for c in creature.conditions.values() if c.condition_id == IN_WORLD), None)


def _end_world(engine: Any, subject: Any, held: Any, reason: str) -> None:
    source, owner = held.source_definition_id, held.source_actor_id
    _remove(engine, subject, held, reason)
    for condition in [c for c in subject.conditions.values() if c.source_definition_id == source and c.source_actor_id == owner
                      and c.condition_id in ("condition:typed.incapacitated", "condition:typed.prone")]:
        _remove(engine, subject, condition, reason)
    note(engine, source, subject, f"{subject.display_name} escapes the World of One.")


@hook("turn_end")
def world_turn_end(engine: Any, actor: Any) -> None:
    from .effect_durations import apply_condition_preserving_clock
    held = _world(actor)
    if held is None or not actor.active:
        return
    owner = engine.state.actors.get(held.source_actor_id)
    if owner is None:
        return
    ctx = _ctx(engine, owner, WORLD, [actor])
    data = dict(held.data or {})
    _te().run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 6, "sides": 10}, "damage_types": ["psychic"],
                             "evidence": "At the end of each of its turns, the target takes 6d10 Psychic damage"}])
    held = _world(actor)
    if held is None or not actor.active:
        return
    data = dict(held.data or {})
    advantage = bool(data.get("advantage"))
    options = {"save": ("WIS", None, "Repeat the Wisdom saving throw"), "insight": ("WIS", "Insight", "Wisdom (Insight) check: reinterpret the dream-symbol"),
               "investigation": ("INT", "Investigation", "Intelligence (Investigation) check: identify the dream-symbol"),
               "persuasion": ("CHA", "Persuasion", "Charisma (Persuasion) check: bargain with the dream-symbol")}
    best = max(options, key=lambda k: (int((actor.saving_throws or {}).get(options[k][0], 0)) if k == "save" else _ability_mod(actor, options[k][0]), k))
    from . import needle

    chosen = needle.ask(engine, None, needle.checkpoint_id(engine, "WORLD_ESCAPE", actor.entity_id), actor, "choice:needle.dreamweaver.world_escape",
                        list(options), labels={k: v[2] for k, v in options.items()}, preferred=[best],
                        prompt=f"{actor.display_name} is trapped in a World of One: choose one way to try to escape"
                               + (" (with Advantage: its body was damaged)." if advantage else "."), name="World of One", feature_id=WORLD,
                        target_id=actor.entity_id)
    pick = chosen[0] if chosen else best
    if advantage:
        _remove(engine, actor, held, "UPDATED")
        apply_condition_preserving_clock(engine, actor, held, IN_WORLD, held.source_definition_id, held.source_actor_id, expires_on=held.expires_on, data={**data, "advantage": 0})
        held = _world(actor)
    dc = int(data.get("dc") or 10)
    ctx.typed["numbers"] = {**ctx.numbers, "save_dc": dc}  # the World's own DC, recorded when it began
    ability, skill, _label = options[pick]
    if pick == "save":
        before = len(engine.events)
        engine.__dict__["_c8_world_advantage"] = actor.entity_id if advantage else None
        try:
            _te().block_save(ctx, {"type": "save", "applies_to": "target", "ability": "wis", "on_fail": [], "on_success": []})
        finally:
            engine.__dict__.pop("_c8_world_advantage", None)
        escaped = bool(_saved(engine, before, actor))
    else:
        roll = engine.roll_check(modifier=_ability_mod(actor, ability), actor_id=actor.entity_id,
                                 reason=f"CHECK:{WORLD}:{skill}", ability=ability, skill=skill,
                                 modes=("ADVANTAGE",) if advantage else ())
        escaped = roll.total >= dc
        engine._append_event("CHECK_ROLLED", WORLD, actor_id=actor.entity_id,
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": escaped, "check": f"{ability} ({skill})"})
    if escaped and held is not None:
        _end_world(engine, actor, held, "ESCAPED")
        _unreality(engine, owner, actor)


def _ability_mod(actor: Any, ability: str) -> int:
    # The saving throw bonus is the best number the table keeps for a native creature's ability; proficiency may be in it.
    return int((actor.saving_throws or {}).get(ability, 0))


@hook("save")
def world_advantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    return {"bonus": 0, "modes": ["ADVANTAGE"]} if ctx.engine.__dict__.get("_c8_world_advantage") == getattr(subject, "entity_id", None) else None


@hook("event")
def body_damaged(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from .effect_durations import apply_condition_preserving_clock
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    for target_id in kwargs.get("target_ids") or ():
        creature = engine.state.actors.get(target_id)
        if creature is None:
            continue
        held = _world(creature)
        source = str(engine.events[-1].source_definition_id if engine.events else "")  # the event hook's keywords do not carry the source
        if held is not None and source != held.source_definition_id and not (held.data or {}).get("advantage"):
            _remove(engine, creature, held, "UPDATED")  # "Damage dealt to the target's body grants it Advantage on its next escape attempt"
            apply_condition_preserving_clock(engine, creature, held, IN_WORLD, held.source_definition_id, held.source_actor_id, expires_on=held.expires_on,
                                    data={**(held.data or {}), "advantage": 1})
        sleep = next((c for c in creature.conditions.values() if c.condition_id == DREAM_SLEEP), None)
        if sleep is not None:
            _wake_sleeper(engine, creature, sleep, "DAMAGED")


# ------------------------------------------------------------------------------------------------------ Unreality Bites Back
def _unreality(engine: Any, owner: Any, creature: Any) -> None:
    if owner is None or not owner.active or st.row(engine, owner, "unreality_bites_back") is None or not st.can_react(owner) \
            or owner.resources.get(RESONANCE, 0) < 2 or engine.grid.distance_ft(owner.position, creature.position) > 60:
        return
    from . import needle

    chosen = needle.ask(engine, None, needle.checkpoint_id(engine, "UNREALITY", creature.entity_id), owner, "choice:needle.dreamweaver.unreality",
                        ["bite"], labels={"bite": f"Unreality Bites Back: {creature.display_name} makes a Wisdom save (2 Resonance, your Reaction)"},
                        prompt=f"{creature.display_name} broke free of your dream-work. Make unreality bite back?", preferred=["bite"],
                        allow_decline=True, name="Unreality Bites Back", feature_id=UNREALITY, target_id=creature.entity_id)
    if not chosen:
        return
    with activation(engine, owner, UNREALITY):
        engine._spend_resource(owner, RESONANCE, 2, UNREALITY)
        owner.reaction_available = False
        ctx = _ctx(engine, owner, UNREALITY, [creature])
        _te().block_save(ctx, {"type": "save", "applies_to": "target", "ability": "wis",
                               "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 10}, "damage_types": ["psychic"]},
                                           {"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"}},
                                           {"type": "spiritual_pressure", "applies_to": "target"},
                                           {"type": "mark", "mark": THREAD, "applies_to": "target"}],
                               "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["psychic"]},
                                              {"type": "mark", "mark": THREAD, "applies_to": "target"}]})


# ---------------------------------------------------------------------------------------------------------- Eternal Dream Refuge
@hook("zero_hp")
def dream_refuge(engine: Any, target: Any, source_id: str, intent: Any) -> str | None:
    if st.row(engine, target, "eternal_dream_refuge") is None or target.resources.get(RESONANCE, 0) < 6:
        return None
    from . import life_state

    if life_state.wants_dying(engine, target) and engine.state.rules.get("zero_hp") != "dying_2024":
        return None  # historical explicit life-state ownership; ordinary service defaults yield to this refuge
    if any(c.condition_id in (life_state.UNCONSCIOUS, "condition:typed.unconscious") for c in target.conditions.values()):
        return None  # printed trigger: while conscious
    if any(c.condition_id == REFUGE_USED for c in target.conditions.values()):
        return None
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "DREAM_REFUGE", target.entity_id), target, "choice:needle.dreamweaver.refuge",
                        ["refuge"], labels={"refuge": "Eternal Dream Refuge (6 Resonance): lie Unconscious and Stable in a 20-foot Dream Refuge "
                                                      "for up to 3 rounds instead of leaving the fight"},
                        prompt=f"{target.display_name} drops to 0 Hit Points. Retreat into the Eternal Dream Refuge?", preferred=["refuge"],
                        allow_decline=True, name="Eternal Dream Refuge", feature_id=REFUGE, target_id=target.entity_id)
    if not chosen:
        return None
    with activation(engine, target, REFUGE):
        engine._spend_resource(target, RESONANCE, 6, REFUGE)
        engine._apply_condition(target, REFUGE_USED, REFUGE, target.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Eternal Dream Refuge used this fight"})
        engine._apply_condition(target, life_state.UNCONSCIOUS, REFUGE, target.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Unconscious in the Dream Refuge", "rule": {"no_actions": True, "no_reactions": True, "speed_zero": True,
                                      "attacked_with": "ADVANTAGE", "save_mode": {"STR": "AUTO_FAIL", "DEX": "AUTO_FAIL"}}})
        engine._apply_condition(target, REFUGE_ON, REFUGE, target.entity_id, expires_on="UNTIL_REMOVED",
                                data={"round": int(engine.state.round_number), "recalled": [],
                                      "label": "Dream Refuge (up to 3 rounds): Stable; Resistance to damage except Psychic and Force"})
        ctx = _ctx(engine, target, REFUGE, [], intent)
        from .. import zones

        zones.create(ctx, {"name": "Dream Refuge", "shape": "emanation", "size_ft": 20, "centered_on_self": True,
                           "duration": {"kind": "rounds", "amount": 3, "concentration": False}, "terrain": [], "difficult": None, "obscured": None,
                           "follows_owner": False, "visual": {"material": "spirit"},
                           "triggers": [{"id": "dream_refuge", "name": "Dream Refuge", "on": ["enter", "start"], "who": "hostile",
                                         "effects": [{"type": "save", "applies_to": "target", "ability": "wis",
                                                      "on_fail": [{"type": "dreamweaver_refuge_sleep", "applies_to": "target",
                                                                   "evidence": "falls into Dream Sleep until the end of its next turn"}],
                                                      "on_success": [{"type": "speed", "applies_to": "target", "flat": -10, "duration": "until_start_of_next_turn",
                                                                      "evidence": "its Speed is reduced by 10 feet"},
                                                                     {"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn",
                                                                      "evidence": "it cannot take Reactions until the start of its next turn"}]}]}]})
        note(engine, REFUGE, target, f"{target.display_name} sinks into the Eternal Dream Refuge (Stable for up to 3 rounds).")
        return "STABLE"


@effect("dreamweaver_refuge_sleep")
def refuge_sleep(ctx: Any, row: dict[str, Any]) -> None:
    subject = ctx.target
    if subject is None or not subject.active:
        return
    expires = _te().effect_expiry(ctx, {"duration": {"kind": "until_end_of_next_turn"}}, subject, condition=True)
    ctx.engine._apply_condition(subject, "condition:typed.unconscious", ctx.source, ctx.actor.entity_id, expires_on=expires,
                                data={"label": "Dream Sleep"})
    ctx.engine._apply_condition(subject, DREAM_SLEEP, ctx.source, ctx.actor.entity_id, expires_on=expires,
                                data={"label": "Dream Sleep: Unconscious until the end of its next turn, damage, or an ally's Action wakes it"})


def _wake_sleeper(engine: Any, creature: Any, sleep: Any, reason: str) -> None:
    source, owner = sleep.source_definition_id, sleep.source_actor_id
    _remove(engine, creature, sleep, reason)
    for condition in [c for c in creature.conditions.values() if c.condition_id == "condition:typed.unconscious"
                      and c.source_definition_id == source and c.source_actor_id == owner]:
        _remove(engine, creature, condition, reason)


@hook("incoming_damage")
def refuge_resistance(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str) -> int:
    if amount <= 0 or not any(c.condition_id == REFUGE_ON for c in target.conditions.values()):
        return 0
    if str(damage_type or "").upper() in ("PSYCHIC", "FORCE"):
        return 0
    return amount - amount // 2  # Resistance: half, rounded down, remains


def _end_refuge(engine: Any, target: Any, hp: int, *, exhaustion: bool, reason: str) -> None:
    from . import life_state

    held = next((c for c in target.conditions.values() if c.condition_id == REFUGE_ON), None)
    if held is not None:
        _remove(engine, target, held, reason)
    from .. import zones

    for zone in zones.typed_zones(engine):
        if zone.owner_id == target.entity_id and zone.trigger_profile.get("name") == "Dream Refuge":
            zones.remove(engine, zone, reason)
    if target.current_hp <= 0 and target.active:
        life_state.restore_hp(engine, target, hp, REFUGE)
    if exhaustion:
        ctx = _ctx(engine, target, REFUGE, [target])
        _te().run_effects(ctx, [{"type": "exhaustion", "amount": 1, "applies_to": "self"}])


@hook("turn_start")
def refuge_timer(engine: Any, actor: Any) -> None:
    held = next((c for c in actor.conditions.values() if c.condition_id == REFUGE_ON), None)
    if held is None or not actor.active:
        return
    if int(engine.state.round_number) - int((held.data or {}).get("round") or 0) >= 3:
        _end_refuge(engine, actor, 1, exhaustion=True, reason="AWAKENED")  # "At the end of the third round ... 1 Hit Point, 1 level of Exhaustion"
        note(engine, REFUGE, actor, f"{actor.display_name} wakes from the Dream Refuge with 1 Hit Point and a level of Exhaustion.")


@hook("compile_actions")
def thread_passage(info: dict[str, Any]) -> list[Any] | None:
    if UNREALITY not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.dream_thread_passage", display_name="Dream-Thread Passage", owner_id=info["actor_id"],
        economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60, costs=(("resource:core.resonance", 1),),
        parameters={"typed": {"effects": [{"type": "exposed", "applies_to": "target", "benefits": "hidden_or_invisible", "against": "you",
                                           "duration": "until_end_of_turn", "evidence": "you may perceive that creature through ordinary darkness, "
                                           "invisibility, and non-total visual concealment"}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": [], "source": UNREALITY},
                    "expected_damage": 0, "target_requires_condition": _te().mark_condition_id(THREAD, info["actor_id"]),
                    "description": "Unreality Bites Back -- Dream-Thread Passage (Bonus Action, 1 Resonance): until the end of your turn, a creature "
                                   "bearing your Dream Thread within 60 feet cannot benefit from being Hidden or Invisible against you."})]


@hook("match_start")
def recall_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[RECALL] = ActionDefinition(
        source_definition_id=RECALL, display_name="Refuge Recall (speak their name and a shared memory)", owner_id="*", economy=EconomyKind.ACTION,
        resolution_kind="TYPED", target_kind="ALLY_OR_SELF", range_ft=20,
        parameters={"typed": {"effects": [{"type": "dreamweaver_recall", "applies_to": "target"}], "numbers": {}, "duration": {"kind": "instant"},
                              "riders": []}, "expected_damage": 0, "dream_recall": True,
                    "description": "Eternal Dream Refuge: speak the dreaming ally's name and one shared event to call them back -- they wake with "
                                   "2 x their Proficiency Bonus Hit Points and the Refuge ends. Once per creature for each Refuge."})


@hook("additional_actions")
def recall_offered(engine: Any, actor: Any) -> list[str]:
    from .. import zones

    for zone in zones.typed_zones(engine):
        owner = engine.state.actors.get(zone.owner_id)
        if (zone.trigger_profile.get("name") == "Dream Refuge" and owner is not None and owner is not actor and owner.team_id == actor.team_id
                and engine._footprint_intersects(actor, zone.affected_cells)):
            held = next((c for c in owner.conditions.values() if c.condition_id == REFUGE_ON), None)
            if held is not None and actor.entity_id not in ((held.data or {}).get("recalled") or []):
                return [RECALL]
    return []


@effect("dreamweaver_recall")
def recall(ctx: Any, row: dict[str, Any]) -> None:
    sleeper = ctx.target
    held = next((c for c in sleeper.conditions.values() if c.condition_id == REFUGE_ON), None) if sleeper is not None else None
    if held is None:
        return
    pb = int(getattr(sleeper, "proficiency_bonus", 2) or 2)
    _end_refuge(ctx.engine, sleeper, 2 * pb, exhaustion=False, reason="RECALLED")
    note(ctx.engine, REFUGE, ctx.actor, f"{ctx.actor.display_name} calls {sleeper.display_name} back from the Dream Refuge ({2 * pb} Hit Points).", (sleeper,))


WAKE_DREAM_SLEEP = "action:typed.dreamweaver.wake_dream_sleeper"


@hook("match_start")
def wake_sleep_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[WAKE_DREAM_SLEEP] = ActionDefinition(
        source_definition_id=WAKE_DREAM_SLEEP, display_name="Wake Dream-Sleeping Ally", owner_id="*",
        economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF", range_ft=5,
        parameters={"typed": {"effects": [{"type": "dreamweaver_wake_sleep", "applies_to": "target"}],
                               "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
                    "dreamweaver_wake_sleep": True, "expected_damage": 0,
                    "description": "Use your Action beside an ally in Dream Sleep to wake them. This does not end Cursed Sleep."})


@hook("additional_actions")
def wake_sleep_offered(engine: Any, actor: Any) -> list[str]:
    return [WAKE_DREAM_SLEEP] if any(
        other is not actor and other.active and other.team_id == actor.team_id
        and engine._distance_actor_to_actor(actor, other) <= 5 and _dream_sleep(other) is not None
        for other in engine.state.actors.values()) else []


def _dream_sleep(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == DREAM_SLEEP), None)


@hook("candidate_allowed")
def wake_sleep_target(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get("dreamweaver_wake_sleep"):
        return None
    target = engine.state.actors.get(next(iter(candidate.target_ids or ()), ""))
    return None if target is not None and target is not actor and target.team_id == actor.team_id and _dream_sleep(target) is not None else False


@effect("dreamweaver_wake_sleep")
def wake_sleep(ctx: Any, row: dict[str, Any]) -> None:
    target = ctx.target
    if target is None or target is ctx.actor or target.team_id != ctx.actor.team_id:
        return
    sleep = _dream_sleep(target)
    if sleep is not None and ctx.engine._distance_actor_to_actor(ctx.actor, target) <= 5:
        _wake_sleeper(ctx.engine, target, sleep, "ALLY_WAKENED")
