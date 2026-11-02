"""Mushroom Dreamwalker (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Mushroom Dreamwalker: Dream-Spore Marks, Mycelial Nodes, CL3 Mycelial Dream, CL6
Spore Murmur, CL10 Under-Root Memory, CL14 Hallucinogenic Bloom, CL18 Fruiting Body of the Dream). No Spheres 5e or D&D 5.5e counterpart.

Dream-Spore Marks (tradition text): the counted mark "Dream-Spore Mark" (combat/ext/stacking_marks.py) -- up to three from you on a
creature, no more than one added to it per turn, for the fight; it counts as your Resonance Mark (rules/typed_conditions.json mark_counts_as).
Mycelial Nodes are planted by a 1-minute rite before a fight: the table has none, so every "from you or a Mycelial Node" is from you.

What runs:
  * Spore Touch (typed): a Constitution save or a willing creature -> one Dream-Spore Mark.
  * Spore Murmur (typed options, Poison or Psychic): on a failed save ``dream_murmur`` asks the Murmur (Heavy Cap, Whispering Gills,
    False Forest, Drowsing Root -- the next Wisdom save it makes against your Spirit Awakening feature has Disadvantage) and, when it
    already bore two or more of your marks, Hyphal Spread (asked: a creature within 10 feet of it makes a Constitution save; failed,
    one mark and 2 x PB Psychic).
  * Hallucinogenic Bloom (typed zone, hostile difficult terrain): a hostile creature entering it for the first time on a turn or
    starting its turn there (``dream_bloom``) makes a Wisdom save -- with Disadvantage on its first against the Bloom when it bears
    three of your marks. Failed: a Bloom effect you choose (asked) until the start of its next turn -- Lost Trail (no Reactions),
    Borrowed Forest (Disadvantage on its next attack roll), Sleep Beneath the Roots (Speed 0, and Incapacitated if it is Bloodied,
    bears three marks or is 5+ CL below you -- damage ends that) or Spore Communion (the GM's); a three-mark creature may pass a mark
    to another creature within 10 feet (asked). Succeeded: it ignores the Bloom's saves until the start of its next turn.
  * Fruiting Body of the Dream (typed zone, a 30-foot field on you): Blindsight 60 feet against creatures that are poisoned,
    frightened, charmed or bear your Resonance Mark (their Hidden and Invisible conditions do not count against you); "Spore Touch
    (Fruiting Body)" (Bonus Action, free, once on each of your turns); once per turn when a hostile creature in the field fails a save
    against your Spirit Awakening feature, an ally in the field (asked) regains PB + Wisdom Hit Points or ends one Frightened,
    Charmed or Poisoned (asked).

Plug-in surface: effects dream_murmur, dream_bloom; hooks mark_apply, mark_consume, save, after_save_resolved, event,
technique_used, compile_actions, candidate_allowed, masked_conditions, sense_rows, sense_grant_allowed. Public helper: ``spores``. Shared helpers used:
spirit_traditions (context/numbers/feature_action/feature_of/is_spirit_feature/pick_creature/save/remove), stacking_marks
(add/count/spend), needle, zones.typed_zones, typed_executor.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.mushroom_dreamwalker.feature."
DREAM = TRADITION + "mycelial_dream"
MURMUR = TRADITION + "spore_murmur"
BLOOM = TRADITION + "hallucinogenic_bloom"
FRUIT = TRADITION + "fruiting_body_of_the_dream"
SPORE = "Dream-Spore Mark"
RESONANCE = "resource:core.resonance"
DROWSING = "condition:typed.drowsing_root"
BLOOM_WARD = "condition:typed.bloom_ignored"
ROOT_SLEEP = "condition:typed.sleep_beneath_the_roots"
BLOOM_FIRST = "condition:typed.bloom_first_save"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def spores(engine: Any, owner: Any, creature: Any) -> int:
    from .stacking_marks import count

    return count(engine, owner, creature, SPORE) if owner is not None and creature is not None else 0


def _name(condition: Any) -> str:
    return str(condition.condition_id or "").rsplit(".", 1)[-1].lower()


# ---------------------------------------------------------------------------------------------------------- Dream-Spore Marks
@hook("mark_apply")
def dream_spore_mark(ctx: Any, row: dict[str, Any], subject: Any, expires: str, data: dict[str, Any] | None) -> bool | None:
    """"A creature can bear up to three Dream-Spore Marks from you. You can place no more than one Dream-Spore Mark on the same creature
    per turn unless a feature expressly says otherwise.\""""
    if str(row.get("mark") or "") != SPORE:
        return None
    from .stacking_marks import add

    flag = f"dream_spore_added:{subject.entity_id}"
    if (ctx.actor.turn_flags.get(flag) and not row.get("extra")) or spores(ctx.engine, ctx.actor, subject) >= 3:
        return True
    ctx.actor.turn_flags[flag] = True
    add(ctx.engine, ctx.actor, subject, SPORE, 1, ctx.source)
    return True


@hook("mark_consume")
def spend_dream_spore(ctx: Any, row: dict[str, Any], subject: Any) -> bool | None:
    if str(row.get("mark") or "") != SPORE:
        return None
    from .stacking_marks import spend

    return spend(ctx.engine, ctx.actor, subject, SPORE, ctx.source, max(1, int(row.get("count") or 1)))


def _mark(ctx: Any, subject: Any, *, extra: bool = False) -> None:
    _te().run_effects(st.context(ctx.engine, ctx.actor, ctx.action, [subject], ctx.numbers, ctx.intent),
                      [{"type": "mark", "mark": SPORE, "applies_to": "target", "duration": {"kind": "until_removed"}, "extra": extra,
                        "evidence": "gains one Dream-Spore Mark"}])


# ---------------------------------------------------------------------------------------------------------- Spore Murmur
MURMURS = {"heavy_cap": "Heavy Cap: its Speed is reduced by 15 feet", "whispering_gills": "Whispering Gills: it cannot take Reactions",
           "false_forest": "False Forest: Disadvantage on the next attack roll it makes",
           "drowsing_root": "Drowsing Root: Disadvantage on its next Wisdom save against your Spirit Awakening features"}


@effect("dream_murmur")
def murmur(ctx: Any, row: dict[str, Any]) -> None:
    """The failed save's Murmur (asked) and Hyphal Spread; runs before the new mark, so "already bears two or more" is read first."""
    from . import needle

    engine, walker = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    if target is None or not target.active:
        return
    had = spores(engine, walker, target)
    from .creature_kinds import matches
    options = {key: label for key, label in MURMURS.items()
               if key not in {"false_forest", "drowsing_root"} or not matches(target, "mindless")}
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "SPORE_MURMUR", target.entity_id), walker, "choice:needle.dreamwalker.murmur",
                        list(options), labels=options, preferred=["whispering_gills"], prompt=f"Spore Murmur: which Murmur for {target.display_name} "
                        "until the start of your next turn?", name="Spore Murmur", feature_id=MURMUR, target_id=target.entity_id)
    pick = chosen[0] if chosen and chosen[0] in options else "whispering_gills"
    until = {"kind": "until_start_of_your_next_turn"}
    rows = {"heavy_cap": [{"type": "speed", "applies_to": "target", "flat": -15, "duration": until, "evidence": "Its Speed is reduced by 15 feet."}],
            "whispering_gills": [{"type": "reaction_denied", "applies_to": "target", "duration": until, "evidence": "It cannot take Reactions."}],
            "false_forest": [{"type": "disadvantage", "applies_to": "target", "on": "its next attack roll", "duration": until,
                              "evidence": "It has Disadvantage on the next attack roll it makes."}],
            "drowsing_root": []}[pick]
    if pick == "drowsing_root":
        engine._apply_condition(target, DROWSING, MURMUR, walker.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": f"Drowsing Root: Disadvantage on its next Wisdom save against {walker.display_name}'s Spirit Awakening features"})
    else:
        _te().run_effects(st.context(engine, walker, ctx.action, [target], ctx.numbers, ctx.intent), rows)
    if had < 2:
        return
    # Hyphal Spread: "If the target already bears two or more Dream-Spore Marks when it fails, choose one creature within 10 feet of it."
    near = [c for _, c in sorted(engine.state.actors.items()) if c.active and c is not target and c is not walker
            and engine._distance_actor_to_actor(target, c) <= 10]
    spread = _spread_recipient(ctx, near, checkpoint="HYPHAL_SPREAD", choice_id="choice:needle.dreamwalker.hyphal_spread",
                               prompt="Hyphal Spread: which creature within 10 feet makes a Constitution save?", name="Hyphal Spread", feature_id=MURMUR)
    if spread is None:
        return
    sub = st.context(engine, walker, ctx.action, [spread], ctx.numbers, ctx.intent)
    if st.save(sub, spread, "con"):
        _mark(sub, spread)
        _te().run_effects(sub, [{"type": "damage", "applies_to": "target", "flat": 2 * int((ctx.numbers or {}).get("pb") or 2), "damage_types": ["psychic"],
                                 "evidence": "takes Psychic damage equal to 2 x Proficiency Bonus"}])


@hook("save")
def drowsing_root(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if str(ability or "").upper()[:3] != "WIS" or subject is None or ctx.actor is None or not st.is_spirit_feature(ctx.action):
        return None
    for iid, held in list(subject.conditions.items()):
        if held.condition_id == DROWSING and held.source_actor_id == ctx.actor.entity_id:
            subject.conditions.pop(iid)
            ctx.engine._append_event("CONDITION_REMOVED", MURMUR, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                                     payload={"condition_id": DROWSING, "instance_id": iid, "reason": "CONSUMED"})
            return {"bonus": 0, "modes": ["DISADVANTAGE"]}
    return None


# ---------------------------------------------------------------------------------------------------------- Hallucinogenic Bloom
BLOOMS = {"lost_trail": "Lost Trail: it cannot take Reactions", "borrowed_forest": "Borrowed Forest: Disadvantage on the first attack it makes",
          "sleep": "Sleep Beneath the Roots: its Speed becomes 0 (Incapacitated too if it is Bloodied, bears three marks or is far below you)",
          "communion": "Spore Communion: its surface emotions, hostile intention and direction are laid bare (the GM tells you)"}


@effect("dream_bloom")
def bloom(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, walker = ctx.engine, ctx.actor
    target = ctx.target or next(iter(ctx.targets or ()), None)
    if target is None or not target.active or target.team_id == walker.team_id:
        return
    if any(c.condition_id == BLOOM_WARD and c.source_actor_id == walker.entity_id for c in target.conditions.values()):
        return  # "It ignores the Bloom's saving throw effects until the start of its next turn"
    three = spores(engine, walker, target) >= 3
    first = not any(c.condition_id == BLOOM_FIRST and c.source_actor_id == walker.entity_id for c in target.conditions.values())
    if first:
        engine._apply_condition(target, BLOOM_FIRST, BLOOM, walker.entity_id, expires_on="UNTIL_REMOVED", data={"label": "Has saved against the Bloom"})
    sub = st.context(engine, walker, ctx.action, [target], ctx.numbers, ctx.intent)
    if three and first:  # "A creature bearing three Dream-Spore Marks makes its first save against the Bloom with Disadvantage."
        engine._apply_condition(target, DROWSING, BLOOM, walker.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "Disadvantage on its first save against the Bloom"})
    failed = st.save(sub, target, "wis")
    for held in [c for c in target.conditions.values() if c.condition_id == DROWSING and c.source_definition_id == BLOOM]:
        st.remove(engine, target, held, "UNUSED")
    if not failed:
        engine._apply_condition(target, BLOOM_WARD, BLOOM, walker.entity_id, expires_on="START_OF_TARGET_NEXT_TURN",
                                data={"label": "Ignores the Bloom's saves until the start of its next turn"})
        return
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "BLOOM_EFFECT", target.entity_id), walker, "choice:needle.dreamwalker.bloom",
                        list(BLOOMS), labels=BLOOMS, preferred=["sleep"], prompt=f"Hallucinogenic Bloom: {target.display_name} failed -- which Bloom effect?",
                        name="Hallucinogenic Bloom", feature_id=BLOOM, target_id=target.entity_id)
    pick = chosen[0] if chosen and chosen[0] in BLOOMS else "sleep"
    until = {"kind": "until_start_of_next_turn"}
    if pick == "lost_trail":
        _te().run_effects(sub, [{"type": "reaction_denied", "applies_to": "target", "duration": until, "evidence": "It cannot take Reactions"}])
        # "It cannot take Reactions and cannot willingly move closer to a creature you designate." The printed rule
        # names no alliance, no team and no perception limit, so eligibility is every active creature but the
        # affected one itself -- an enemy and a concealed ally are both printable designations and the player's to
        # make. The automatic (AI) chooser only *prefers* one of the walker's allies; a preference is not an
        # eligibility rule, so nothing is narrowed away from a human player.
        eligible = [c for _, c in sorted(engine.state.actors.items()) if c.active and c is not target]
        ally = next((c for c in eligible if c.team_id == walker.team_id), None)
        creature = st.pick_creature(engine, ctx.intent, walker, eligible, checkpoint="LOST_TRAIL_SUBJECT",
                                   choice_id="choice:needle.dreamwalker.lost_trail_subject", name="Lost Trail", feature_id=BLOOM,
                                   prompt=f"Lost Trail: which creature can {target.display_name} no longer approach?",
                                   preferred=ally)
        if creature is not None:
            from . import effect_durations

            # "until the start of its next turn" rides the affected creature's own turn counter
            # (effect_durations.holder_next_turn), never START_OF_TARGET_NEXT_TURN: that name is swept at the
            # start of the walker's next turn too, so a ban laid on during the target's own turn would end before
            # that turn came round again (bug 3, tests/test_expiry_names.py).
            engine._apply_condition(target, "condition:typed.no_approach", ctx.source, walker.entity_id,
                                    expires_on=effect_durations.holder_next_turn(target), data={"avoid": creature.entity_id,
                                    "label": f"Lost Trail: cannot willingly move closer to {creature.display_name}"})
    elif pick == "borrowed_forest":
        _te().run_effects(sub, [{"type": "disadvantage", "applies_to": "target", "on": "its next attack roll", "duration": until,
                                 "evidence": "The first attack it makes ... is made with Disadvantage"}])
    elif pick == "sleep":
        _te().run_effects(sub, [{"type": "speed", "applies_to": "target", "becomes": 0, "duration": until, "evidence": "Its Speed becomes 0."}])
        bloodied = target.current_hp <= target.maximum_hp // 2
        known = _cl(engine, target)
        far_below = known is not None and known + 5 <= int((ctx.numbers or {}).get("cl") or 1)  # "its Source CL is at least 5 lower than yours"
        if bloodied or three or far_below:
            engine._apply_condition(target, ROOT_SLEEP, BLOOM, walker.entity_id, expires_on="START_OF_TARGET_NEXT_TURN",
                                    data={"rule": {"counts_as_incapacitated": True, "no_actions": True, "no_reactions": True, "speed_zero": True},
                                          "label": "Sleep Beneath the Roots: Incapacitated until the start of its next turn (damage ends it)"})
    else:
        note(engine, BLOOM, walker, f"Spore Communion: {target.display_name}'s surface emotions, hostile intention and direction are laid bare (the GM tells you).", (target,))
    if three:
        _pass_a_mark(sub, target)


def _cl(engine: Any, creature: Any) -> int | None:
    """A Factory character's Cultivation Level (its compiled bundle); None when the table does not know it."""
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == creature.entity_id), None)
    return int(bundle["cl"]) if bundle and bundle.get("cl") else None


def _pass_a_mark(ctx: Any, target: Any) -> None:
    """"When such a creature fails, you may consume one mark to place one Dream-Spore Mark on another creature within 10 feet of it.\""""
    from .stacking_marks import spend

    engine, walker = ctx.engine, ctx.actor
    near = [c for _, c in sorted(engine.state.actors.items()) if c.active and c is not target and c is not walker
            and engine._distance_actor_to_actor(target, c) <= 10 and spores(engine, walker, c) < 3]
    other = _spread_recipient(ctx, near, checkpoint="BLOOM_SPREAD", choice_id="choice:needle.dreamwalker.bloom_spread",
                              prompt=f"Hallucinogenic Bloom: move one of {target.display_name}'s marks to a creature within 10 feet?",
                              name="Hallucinogenic Bloom", feature_id=BLOOM)
    if other is not None and spend(engine, walker, target, SPORE, BLOOM, 1):
        _mark(st.context(engine, walker, ctx.action, [other], ctx.numbers, ctx.intent), other, extra=True)


@hook("event")
def roots_wake(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Sleep Beneath the Roots: "Damage ends the Incapacitated state.\""""
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        for held in [c for c in (target.conditions.values() if target is not None else ()) if c.condition_id == ROOT_SLEEP]:
            st.remove(engine, target, held, "DAMAGED")


# ---------------------------------------------------------------------------------------------------------- Fruiting Body of the Dream
def field_of(engine: Any, walker: Any) -> Any:
    from .. import zones

    return next((z for z in zones.typed_zones(engine) if z.owner_id == walker.entity_id and st.feature_of(engine.action_catalog.get(z.source_definition_id)) == FRUIT), None)


def _in(engine: Any, zone: Any, creature: Any) -> bool:
    return zone is not None and creature is not None and engine._footprint_intersects(creature, zone.affected_cells)


_SENSED = ("poisoned", "frightened", "charmed")


def fruiting_qualified(engine: Any, walker: Any, creature: Any) -> bool:
    """The five represented categories, shared by pairwise masks and observer grants.

    Mark ownership/equivalence belongs to typed_executor, including Dream-Spore.
    Empty terrain never supplies a qualifying creature. Other printed states
    remain outside this predicate.
    """
    return bool(walker is not None and creature is not None
                and not getattr(creature, "perception_cell", False)
                and field_of(engine, walker) is not None
                and engine._distance_actor_to_actor(walker, creature) <= 60
                and (any(_name(c) in _SENSED for c in creature.conditions.values())
                     or _te().bears_mark(creature, walker.entity_id, "Resonance")))


@hook("sense_rows")
def fruiting_sense_rows(engine: Any, walker: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Qualify only retained Fruiting grants; preserve timed source/range and other senses."""
    if not any(row.get("feature_id") == FRUIT for row in rows):
        return None
    marks = _te().mark_requirement_ids("Resonance", walker.entity_id)
    return [{**row, "against_conditions": sorted(set(row.get("against_conditions") or ()) | marks)}
            if row.get("feature_id") == FRUIT else row for row in rows]


@hook("sense_grant_allowed")
def fruiting_sense_grant(engine: Any, walker: Any, grant: dict[str, Any], creature: Any) -> bool | None:
    """Live source qualification before range merging; unrelated grants are inert.

    A no-target query retains restricted metadata, never unrestricted sight.
    Preserve the existing condition-list behaviour for states outside this lane.
    """
    if grant.get("feature_id") != FRUIT:
        return None
    if field_of(engine, walker) is None or getattr(creature, "perception_cell", False):
        return False
    if creature is None:
        return None
    if fruiting_qualified(engine, walker, creature):
        return True
    # The stored grant already supported Unconscious; do not adjudicate sleeping
    # equivalence or remove that existing permission in this observer-only lane.
    return None if any(c.condition_id in (grant.get("against_conditions") or ())
                       for c in creature.conditions.values()) else False


@hook("masked_conditions")
def fruiting_blindsight(engine: Any, attacker: Any, target: Any) -> dict[str, Any] | None:
    """"You have Blindsight 60 feet against sleeping, poisoned, frightened, charmed, ... Resonance Marked, or Dream-Spore-marked creatures.\""""
    if attacker is None or target is None:
        return None
    for walker, other in ((attacker, target), (target, attacker)):
        unseen = {iid for iid, c in other.conditions.items() if c.condition_id in ("condition:typed.hidden", "condition:typed.invisible")}
        if unseen and fruiting_qualified(engine, walker, other):
            return {"conditions": {other.entity_id: unseen}, "visual": False}
    return None


@hook("compile_actions")
def fruiting_buttons(info: dict[str, Any]) -> list[Any] | None:
    if FRUIT not in info["owned_ids"] or DREAM not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    rows = [{"type": "save", "ability": "con", "dc": "technique_save_dc", "applies_to": "target", "harmful": True,
             "on_fail": [{"type": "mark", "mark": SPORE, "applies_to": "target", "duration": {"kind": "until_removed"}, "evidence": "Place one Dream-Spore Mark on it"}],
             "on_success": [], "evidence": "It makes a Constitution saving throw."}]
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.dreamwalker.free_spore_touch", display_name="Spore Touch (Fruiting Body)",
                             owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=30,
                             parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": DREAM, "effects": rows},
                                         "expected_damage": 0, "dreamwalker": "free_spore_touch",
                                         "description": "Fruiting Body of the Dream: Spore Touch once on each of your turns without spending Resonance "
                                                        "(a Constitution save; failed, one Dream-Spore Mark)."})]


@hook("candidate_allowed")
def fruiting_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or (action.parameters or {}).get("dreamwalker") != "free_spore_touch":
        return None
    return None if field_of(engine, actor) is not None and not actor.turn_flags.get("free_spore_touch") else False


@hook("technique_used")
def free_touch_used(ctx: Any) -> None:
    if (ctx.action.parameters or {}).get("dreamwalker") == "free_spore_touch":
        ctx.actor.turn_flags["free_spore_touch"] = True  # "once on each of your turns"


@hook("after_save_resolved")
def fruiting_restoration(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """"Once per turn when a hostile creature in the field fails a saving throw against one of your Spirit Awakening features, choose one
    ally in the field. It regains Hit Points equal to Proficiency Bonus + Wisdom modifier, or ends one ordinary Frightened, Charmed, Poisoned
    ... effect.\""""
    from . import needle

    engine, walker = ctx.engine, ctx.actor
    if not failed or walker is None or subject is None or subject.team_id == walker.team_id or not st.is_spirit_feature(ctx.action):
        return
    zone = field_of(engine, walker)
    current = engine.state.actors.get(engine.state.current_actor_id or "")
    key = (engine.state.current_actor_id, int(getattr(current, "turns_started", 0) or 0))  # "Once per turn"
    if zone is None or not _in(engine, zone, subject) or tuple(zone.trigger_profile.get("restored_turn") or ()) == key:
        return
    allies = [c for _, c in sorted(engine.state.actors.items()) if c.active and c.team_id == walker.team_id and _in(engine, zone, c)]
    hurt = sorted(allies, key=lambda c: (c.current_hp - c.maximum_hp, c.entity_id))
    ally = st.pick_creature(engine, ctx.intent, walker, hurt, checkpoint="FRUITING_RESTORE", choice_id="choice:needle.dreamwalker.restore",
                            prompt=f"Fruiting Body: {subject.display_name} failed -- which ally in the field is restored?", name="Fruiting Body of the Dream",
                            feature_id=FRUIT, preferred=hurt[0] if hurt else None)
    if ally is None:
        return
    zone.trigger_profile = {**zone.trigger_profile, "restored_turn": list(key)}
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=walker.entity_id, payload={"zone": zone.model_dump(mode="json")})
    afflicted = [c for _, c in sorted(ally.conditions.items()) if _name(c) in _SENSED]
    numbers = st.numbers(engine, walker)
    amount = int(numbers.get("pb") or 2) + int(numbers.get("key_mod") or 0)
    options = {"heal": f"{ally.display_name} regains {amount} Hit Points",
               **{f"end{i}": f"End {ally.display_name}'s {_name(c).title()}" for i, c in enumerate(afflicted)}}
    pick = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "FRUITING_RESTORE_WHAT", ally.entity_id), walker, "choice:needle.dreamwalker.restore_what",
                      list(options), labels=options, preferred=["end0" if afflicted else "heal"], prompt="Fruiting Body: which restoration?",
                      name="Fruiting Body of the Dream", feature_id=FRUIT, target_id=ally.entity_id)
    choice = pick[0] if pick and pick[0] in options else "heal"
    if choice == "heal":
        _te().run_effects(st.context(engine, walker, st.feature_action(engine, walker, FRUIT), [ally], numbers),
                          [{"type": "healing", "applies_to": "target", "flat": amount, "evidence": "regains Proficiency Bonus + Wisdom modifier Hit Points"}])
    else:
        st.remove(engine, ally, afflicted[int(choice[3:])], "RESTORED")


def _spread_recipient(ctx: Any, near: list[Any], *, checkpoint: str, choice_id: str, prompt: str, name: str, feature_id: str) -> Any:
    from . import needle
    enemies = [c.entity_id for c in near if c.team_id != ctx.actor.team_id]
    by_id = {c.entity_id: c for c in near}
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, checkpoint, feature_id), ctx.actor,
        choice_id, list(by_id), labels={aid: c.display_name for aid, c in by_id.items()}, prompt=prompt,
        preferred=enemies[:1], automatic_options=enemies, allow_decline=True,
        default="first" if enemies else "decline", name=name, feature_id=feature_id)
    return by_id.get(chosen[0]) if chosen else None
