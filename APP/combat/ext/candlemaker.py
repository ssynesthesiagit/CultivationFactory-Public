"""Candlemaker (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "16. Candlemaker": Soul Candle, Soul-Wick Marks, CL3 Wick of the Self, CL6
Candle Against the Dark, CL10 Funeral Light, CL14 Last Flame, CL18 Thousand-Year Lantern, Normalized Execution Notes).
No Spheres 5e or D&D 5.5e counterpart. Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json
(Candle Against the Dark keeps its ``d20_rewrite`` row); hooks return early without them.

The Soul Candle is a held Cultivation Asset ("The candle can be held, worn, mounted in a lantern, or placed in an adjacent space"):
its Hit Points are a pool on its keeper (``resource:named.soul_candle``, 5 x Proficiency Bonus, made by the 1-minute vigil before
the fight) and "within 30 feet of you or your Soul Candle" is measured from the keeper. Moving the candle away (Bonus Action,
1 Resonance) and attacks aimed at the candle itself are the GM's. At 0 Hit Points the candle is out: a candle destroyed by damage
also deals its keeper 2 x Proficiency Bonus Psychic damage and ends all its Soul-Wick Marks; Last Flame's "extinguished" candle
does not (judgment: the printed text keeps the two apart).

What runs:
  * Soul-Wick Marks: counted (up to three per creature, one added per creature per turn, the scene), and they count as your
    Resonance Mark (typed_executor.bears_mark). Placed by the Candle Marking Rite (Wick of the Self: Bonus Action, 1 Resonance,
    60 feet, Wisdom save; Disadvantage when the target is Bloodied, has failed an Int/Wis/Cha save since the end of your last turn,
    or has lost Concentration this fight) and by the Lantern.
  * Candle Against the Dark (combat/ext/d20_rewrite_rules.py rerolls; the Temporary HP there): then Burn Bright (the candle takes
    2 x Proficiency Bonus; the protected creature has Advantage on its next save against the same source before the end of its
    next turn) or Take the Soot (you become Resonance Marked by the hostile source until the end of your next turn and are
    Disquieted: Disadvantage on your next Concentration save before then). Asked; the AI burns bright while the candle can take it.
  * Funeral Light, Funeral Candle: typed; if the target is concentrating it also has Disadvantage on its next Concentration save.
  * Last Flame (Reaction, 6 Resonance): a creature within 30 feet about to drop to 0 HP is left at 1 HP, cannot benefit from being
    Hidden or Invisible until the end of its next turn, and gains Borrowed Final Breath; the candle is extinguished (0 HP). Once per
    fight for each creature. Asked; the AI saves its own side.
  * Thousand-Year Lantern (Action, 10 Resonance, the scene): the candle's Hit Points double; a 30-foot field around its keeper where
    allies have Advantage on death saves and Int/Wis/Cha saves; when an ally in it succeeds on such a save, one hostile creature in
    it gains a Soul-Wick Mark or suffers your Spiritual Pressure (asked). Last Wick Extinguishes: once per activation, a free
    button while the Lantern stands (see the action's own text).

Additional automation (A2GTRA1): Last Flame can ignore a failed death save,
including a natural one's two failures. Borrowed Final Breath is collected by
the shared lifecycle helper on the next zero-HP episode. A Lantern records
which fields deferred that debt and grants it when those fields end.

Plug-in surface: effects candle_sustained, candle_lantern, candle_last_wick, candle_last_wick_used; hooks compile_resources,
compile_actions, mark_apply, mark_consume, save, after_save_resolved, would_drop, candidate_allowed. Public helpers: ``candle_hp``, ``burn``.
Shared helpers used: spirit_traditions (row/context/pick_creature/can_react), stacking_marks (count/add/spend), needle.ask.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.candlemaker.feature."
WICK = TRADITION + "wick_of_the_self"
CANDLE_FEATURE = TRADITION + "candle_against_the_dark"
FUNERAL = TRADITION + "funeral_light"
LAST_FLAME = TRADITION + "last_flame"
LANTERN = TRADITION + "thousand_year_lantern"
SOUL_WICK = "Soul-Wick Mark"
POOL = "resource:named.soul_candle"
RESONANCE = "resource:core.resonance"
BURN_BRIGHT = "condition:typed.candle_burn_bright"
DISQUIETED = "condition:typed.concentration_mode"
BORROWED = "condition:typed.borrowed_final_breath"
DEFERRED_BREATH = "condition:typed.lantern_deferred_breath"
LAST_FLAME_USED = "condition:typed.last_flame_used"
LANTERN_UP = "condition:typed.thousand_year_lantern"
LAST_WICK_USED = "condition:typed.last_wick_used"
MENTAL = ("INT", "WIS", "CHA")
_OWNED = (WICK, CANDLE_FEATURE, FUNERAL, LAST_FLAME, LANTERN)


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _pb(actor: Any) -> int:
    return int(getattr(actor, "proficiency_bonus", 0) or 0) or 2


def keeps_candle(engine: Any, actor: Any) -> bool:
    return actor is not None and POOL in (actor.resource_maximums or {})


def candle_hp(actor: Any) -> int:
    return int((actor.resources or {}).get(POOL, 0))


# --------------------------------------------------------------------------------------------------------- Soul Candle
@hook("compile_resources")
def soul_candle(info: dict[str, Any]) -> list[Any] | None:
    if not any(feature in (info.get("owned_ids") or []) for feature in _OWNED):
        return None
    from ..gate2_runtime_models import ResourceDefinition

    pb = int(info.get("pb") or 2)
    # 5 x PB; room for the Thousand-Year Lantern's doubling ("Its Asset Hit Points double for the duration").
    return [ResourceDefinition(resource_id=POOL, initial=5 * pb, maximum=10 * pb)]


def burn(engine: Any, keeper: Any, amount: int, source: str, *, extinguish: bool = False) -> None:
    """Damage (or, with ``extinguish``, put out) the keeper's Soul Candle; a candle destroyed by damage burns its keeper and ends
    its Soul-Wick Marks."""
    held = candle_hp(keeper)
    if held <= 0:
        return
    spent = held if extinguish else min(held, max(0, int(amount)))
    if spent:
        engine._spend_resource(keeper, POOL, spent, source)
    if candle_hp(keeper) > 0:
        return
    if extinguish:
        note(engine, source, keeper, f"{keeper.display_name}'s Soul Candle is extinguished.")
        return
    note(engine, source, keeper, f"{keeper.display_name}'s Soul Candle is destroyed: {2 * _pb(keeper)} Psychic damage to its keeper, and its Soul-Wick Marks end.")
    for creature in engine.state.actors.values():
        from .stacking_marks import count, spend

        held_marks = count(engine, keeper, creature, SOUL_WICK)
        if held_marks:
            spend(engine, keeper, creature, SOUL_WICK, source, held_marks)
    engine._commit_damage(keeper, 2 * _pb(keeper), "PSYCHIC", source, keeper.entity_id, engine._active_intent, reaction_depth=2)


# ------------------------------------------------------------------------------------------------------- Soul-Wick Marks
@hook("mark_apply")
def soul_wick_mark(ctx: Any, row: dict[str, Any], subject: Any, expires: str, data: dict[str, Any] | None) -> bool | None:
    """Counted Soul-Wick Marks: at most three from you on one creature, and no more than one added to it per turn."""
    if str(row.get("mark") or "") != SOUL_WICK:
        return None
    from .stacking_marks import add, count

    flag = f"soul_wick_added:{subject.entity_id}"
    if ctx.actor.turn_flags.get(flag) or count(ctx.engine, ctx.actor, subject, SOUL_WICK) >= 3:
        return True  # handled: nothing more this turn / at the maximum
    ctx.actor.turn_flags[flag] = True
    add(ctx.engine, ctx.actor, subject, SOUL_WICK, 1, ctx.source)
    return True


@hook("mark_consume")
def spend_soul_wick(ctx: Any, row: dict[str, Any], subject: Any) -> bool | None:
    if str(row.get("mark") or "") != SOUL_WICK:
        return None
    from .stacking_marks import spend

    return spend(ctx.engine, ctx.actor, subject, SOUL_WICK, ctx.source, max(1, int(row.get("count") or 1)))


def wicks(engine: Any, keeper: Any, creature: Any) -> int:
    from .stacking_marks import count

    return count(engine, keeper, creature, SOUL_WICK)


def _failed_mental_since(engine: Any, creature: Any, keeper: Any, *, whole_scene: bool = False) -> bool:
    """Whether ``creature`` failed an Int/Wis/Cha save since the end of ``keeper``'s last turn (or during the fight)."""
    for event in reversed(engine.events):
        if not whole_scene and event.event_type == "TURN_ENDED" and event.actor_id == keeper.entity_id:
            return False
        if event.event_type == "SAVE_ROLLED" and event.actor_id == creature.entity_id:
            payload = event.payload or {}
            ability = str(payload.get("reason") or "").rsplit(":", 1)[-1].upper()[:3]
            if ability in MENTAL and payload.get("success") is False:
                return True
    return False


def _lost_concentration(engine: Any, creature: Any) -> bool:
    return any(event.event_type == "CONCENTRATION_ENDED" and event.actor_id == creature.entity_id for event in engine.events)


def vulnerable(engine: Any, keeper: Any, creature: Any, *, whole_scene: bool = False) -> bool:
    """"Bloodied, has failed an Intelligence, Wisdom, or Charisma saving throw since the end of your last turn (Candle Marking Rite) /
    during the scene (Last Wick Extinguishes), has lost Concentration, or has had a supernatural defense suppressed during the scene"
    (the last is the GM's)."""
    return (creature.current_hp <= creature.maximum_hp // 2 or _failed_mental_since(engine, creature, keeper, whole_scene=whole_scene)
            or _lost_concentration(engine, creature))


@hook("save")
def marking_rite_disadvantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if st.feature_of(ctx.action) != WICK or subject is ctx.actor or not vulnerable(ctx.engine, ctx.actor, subject):
        return None
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}


# ------------------------------------------------------------------------------------------------ Candle Against the Dark
def after_candle(engine: Any, keeper: Any, protected: Any, source_id: str | None, source_actor: Any, feature: str) -> None:
    """After Candle Against the Dark's reroll: Burn Bright or Take the Soot (called by d20_rewrite_rules' rule)."""
    if keeper is None or not keeper.active:
        return
    burnable = candle_hp(keeper) > 0
    options = [*(["burn"] if burnable else []), "soot"]
    labels = {"burn": f"Burn Bright: the Soul Candle takes {2 * _pb(keeper)} damage; {protected.display_name} has Advantage on its next save "
                      "against the same source before the end of its next turn",
              "soot": "Take the Soot: you become Resonance Marked by the hostile source until the end of your next turn and suffer "
                      "Disquieted (Disadvantage on your next Concentration save before then); the candle takes no damage"}
    from . import needle

    preferred = ["burn"] if burnable and candle_hp(keeper) > 2 * _pb(keeper) else ["soot"]
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "CANDLE_AFTER", protected.entity_id), keeper,
                        "choice:needle.candlemaker.candle_after", options, labels={k: labels[k] for k in options}, preferred=preferred,
                        prompt=f"Candle Against the Dark protected {protected.display_name}: choose Burn Bright or Take the Soot.",
                        name="Candle Against the Dark", feature_id=feature, target_id=protected.entity_id)
    pick = chosen[0] if chosen else preferred[0]
    if pick == "burn":
        burn(engine, keeper, 2 * _pb(keeper), feature)
        ctx = st.context(engine, keeper, _base_action(engine, feature), [protected])
        expires = _te().effect_expiry(ctx, {"duration": {"kind": "until_end_of_next_turn"}}, protected, condition=True)
        engine._apply_condition(protected, BURN_BRIGHT, feature, keeper.entity_id, expires_on=expires,
                                data={"source_id": str(source_id or ""), "label": "Burn Bright: Advantage on the next save against the same source"})
        note(engine, feature, keeper, f"Burn Bright: the Soul Candle burns for {protected.display_name}.", (protected,))
        return
    marker = source_actor if source_actor is not None and source_actor.team_id != keeper.team_id else None
    ctx = st.context(engine, marker or keeper, _base_action(engine, feature), [keeper])
    if marker is not None:
        _te().block_mark(ctx, {"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"}})
    own = st.context(engine, keeper, _base_action(engine, feature), [keeper])
    expires = _te().effect_expiry(own, {"duration": {"kind": "until_end_of_your_next_turn"}}, keeper, condition=True)
    engine._apply_condition(keeper, DISQUIETED, feature, keeper.entity_id, expires_on=expires,
                            data={"rule": {"concentration_mode": "DISADVANTAGE", "next": True},
                                  "label": "Disquieted (Take the Soot): Disadvantage on the next Concentration save"})
    note(engine, feature, keeper, f"Take the Soot: {keeper.display_name} takes the soot for {protected.display_name}.", (protected,))


def _base_action(engine: Any, feature: str) -> Any:
    base = next(iter(engine.action_catalog.values()))
    return base.model_copy(update={"source_definition_id": feature, "display_name": feature.rsplit(".", 1)[-1].replace("_", " ").title(),
                                   "parameters": {"typed": {"numbers": {}, "effects": [], "riders": []}}})


@hook("save")
def burn_bright_advantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    held = [(iid, c) for iid, c in subject.conditions.items() if c.condition_id == BURN_BRIGHT
            and str((c.data or {}).get("source_id") or "") in (ctx.source, str(getattr(ctx.actor, "entity_id", "")))]
    if not held:
        return None
    iid, condition = held[0]
    subject.conditions.pop(iid)
    ctx.engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id,
                             target_ids=(subject.entity_id,), payload={"condition_id": BURN_BRIGHT, "instance_id": iid, "reason": "CONSUMED"})
    return {"bonus": 0, "modes": ["ADVANTAGE"]}


# ------------------------------------------------------------------------------------------------------------ Funeral Light
@effect("candle_sustained")
def sustained(ctx: Any, row: dict[str, Any]) -> None:
    """"If the target is sustained by ... Concentration ..., it has Disadvantage on the next saving throw ... to maintain that
    specific expression before the end of its next turn" (the other sustaining sources are the GM's)."""
    subject = ctx.target
    if subject is None or not subject.active or subject.concentration is None:
        return
    expires = _te().effect_expiry(ctx, {"duration": {"kind": "until_end_of_next_turn"}}, subject, condition=True)
    ctx.engine._apply_condition(subject, DISQUIETED, ctx.source, ctx.actor.entity_id, expires_on=expires,
                                data={"rule": {"concentration_mode": "DISADVANTAGE", "next": True},
                                      "label": "Funeral Candle: Disadvantage on the next Concentration save"})


# --------------------------------------------------------------------------------------------------------------- Last Flame
@hook("would_drop")
def last_flame(engine: Any, target: Any, pending: int, source_actor_id: str) -> int | None:
    if not target.active or any(c.condition_id == LAST_FLAME_USED for c in target.conditions.values()):
        return None
    for keeper in engine.state.actors.values():
        if (not keeper.active or st.row(engine, keeper, "last_flame") is None or candle_hp(keeper) <= 0 or not st.can_react(keeper)
                or keeper.resources.get(RESONANCE, 0) < 6 or engine.grid.distance_ft(keeper.position, target.position) > 30):
            continue
        from . import needle

        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "LAST_FLAME", target.entity_id), keeper,
                            "choice:needle.candlemaker.last_flame", ["flame"],
                            labels={"flame": f"Last Flame: {target.display_name} drops to 1 Hit Point instead (6 Resonance, your Reaction; "
                                             "your Soul Candle is extinguished)"},
                            prompt=f"{target.display_name} would drop to 0 Hit Points within 30 feet of {keeper.display_name}. Use Last Flame?",
                            preferred=["flame"] if target.team_id == keeper.team_id else [], allow_decline=True,
                            default="first" if target.team_id == keeper.team_id else "decline", name="Last Flame", feature_id=LAST_FLAME,
                            target_id=target.entity_id)
        if not chosen:
            continue
        with activation(engine, keeper, LAST_FLAME):
            engine._spend_resource(keeper, RESONANCE, 6, LAST_FLAME)
            keeper.reaction_available = False
            burn(engine, keeper, 0, LAST_FLAME, extinguish=True)
            engine._apply_condition(target, LAST_FLAME_USED, LAST_FLAME, keeper.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": "Protected by Last Flame this fight (once per creature)"})
            ctx = st.context(engine, keeper, _base_action(engine, LAST_FLAME), [target])
            _te().run_effects(ctx, [{"type": "deny_invisible", "applies_to": "target", "duration": {"kind": "until_end_of_next_turn"},
                                     "evidence": "wrapped in visible soul-flame and cannot benefit from being Hidden or Invisible"}])
            grant_borrowed_breath(engine, keeper, target)
            note(engine, LAST_FLAME, keeper, f"Last Flame: {target.display_name} is wrapped in soul-flame and holds at 1 Hit Point.", (target,))
            return max(0, int(target.current_hp) - 1)
    return None


# ------------------------------------------------------------------------------------------------------ Thousand-Year Lantern
def _lanterns(engine: Any) -> list[tuple[Any, Any]]:
    from .. import zones

    out = []
    for zone in zones.typed_zones(engine):
        action = engine.action_catalog.get(zone.source_definition_id)
        keeper = engine.state.actors.get(zone.owner_id)
        if keeper is not None and st.feature_of(action) == LANTERN:
            out.append((keeper, zone))
    return out


def _in_lantern(engine: Any, creature: Any) -> bool:
    return any(engine._footprint_intersects(creature, zone.affected_cells) and keeper.team_id == creature.team_id
               for keeper, zone in _lanterns(engine))


@effect("candle_lantern")
def lantern(ctx: Any, row: dict[str, Any]) -> None:
    keeper = ctx.actor
    held = candle_hp(keeper)
    if held > 0:
        ctx.engine._gain_resource(keeper, POOL, held, ctx.source)  # "Its Asset Hit Points double for the duration"
    for iid, condition in list(keeper.conditions.items()):
        if condition.condition_id == LAST_WICK_USED and condition.source_actor_id == keeper.entity_id:
            keeper.conditions.pop(iid)
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=keeper.entity_id, target_ids=(keeper.entity_id,),
                                     payload={"condition_id": LAST_WICK_USED, "instance_id": iid, "reason": "REPLACED"})


@hook("after_save_resolved")
def lantern_answers(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    engine = ctx.engine
    if failed or str(ability or "").upper()[:3] not in MENTAL or not subject.active:
        return
    for keeper, zone in _lanterns(engine):
        if keeper.team_id != subject.team_id or not engine._footprint_intersects(subject, zone.affected_cells):
            continue
        cells = zone.affected_cells
        hostiles = [c for c in engine.state.actors.values() if c.active and c.team_id != keeper.team_id and engine._footprint_intersects(c, cells)]
        foe = st.pick_creature(engine, ctx.intent, keeper, hostiles, checkpoint="LANTERN_ANSWER", choice_id="choice:needle.candlemaker.lantern",
                               prompt=f"Thousand-Year Lantern: {subject.display_name} succeeded on its save. Which hostile creature in the field "
                                      "gains a Soul-Wick Mark (or your Spiritual Pressure if it already has three)?",
                               name="Thousand-Year Lantern", feature_id=LANTERN, allow_decline=True,
                               preferred=next(iter(sorted(hostiles, key=lambda c: (wicks(engine, keeper, c) >= 3, c.entity_id))), None))
        if foe is None:
            continue
        sub = st.context(engine, keeper, engine.action_catalog.get(zone.source_definition_id) or _base_action(engine, LANTERN), [foe],
                         (zone.trigger_profile.get("numbers") or {}))
        if wicks(engine, keeper, foe) < 3 and not keeper.turn_flags.get(f"soul_wick_added:{foe.entity_id}"):
            _te().block_mark(sub, {"type": "mark", "mark": SOUL_WICK, "applies_to": "target"})
        else:
            _te().run_effects(sub, [{"type": "spiritual_pressure", "applies_to": "target"}])
        return


@hook("compile_actions")
def last_wick_action(info: dict[str, Any]) -> list[Any] | None:
    if LANTERN not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    numbers = info["numbers"]
    out = []
    for damage in ("psychic", "fire", "necrotic"):
        effects = [{"type": "save", "applies_to": "target", "ability": "wis", "dc": "technique_save_dc",
                    "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 10, "sides": 10}, "formula": "key_ability_modifier",
                                 "damage_types": [damage], "evidence": "It takes 10d10 + Wisdom modifier damage"},
                                {"type": "candle_last_wick", "applies_to": "target", "failed": True}],
                    "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": [damage]},
                                   {"type": "candle_last_wick", "applies_to": "target", "failed": False}]},
                   {"type": "candle_last_wick_used"}]
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.last_wick_extinguishes.{damage}",
            display_name=f"Last Wick Extinguishes ({damage.title()})", owner_id=info["actor_id"], economy=EconomyKind.ACTION,
            resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60, costs=(("resource:core.resonance", 6),),
            parameters={"typed": {"effects": effects, "numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "source": LANTERN},
                        "expected_damage": 55, "candle_last_wick": True,
                        "description": "Thousand-Year Lantern, once per activation (Action, 6 Resonance, 60 feet): a hostile creature bearing three "
                                       "Soul-Wick Marks that is Bloodied, failed an Int/Wis/Cha save this fight, or lost Concentration makes a "
                                       f"Wisdom save: 10d10 + Wisdom modifier {damage.title()} and all its Soul-Wick Marks consumed (and its "
                                       "Concentration ends), or half and one mark."}))
    return out


@hook("candidate_allowed")
def lantern_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = (getattr(action, "parameters", None) or {}) if action is not None else {}
    feature = st.feature_of(action) if action is not None else ""
    if feature == LANTERN and not params.get("candle_last_wick"):
        return None if candle_hp(actor) > 0 else False  # "Requirement: A functioning Soul Candle"
    if feature == FUNERAL and str(((params.get("typed") or {}).get("option_label")) or "").startswith("Funeral Candle"):
        # "Choose one hostile creature bearing at least one Soul-Wick Mark"
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
        return None if target is None or wicks(engine, actor, target) >= 1 else False
    if not params.get("candle_last_wick"):
        return None
    if not any(keeper is actor for keeper, _zone in _lanterns(engine)):
        return False
    if any(c.condition_id == LAST_WICK_USED and c.source_actor_id == actor.entity_id for c in actor.conditions.values()):
        return False
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if target is None:
        return None
    return None if wicks(engine, actor, target) >= 3 and vulnerable(engine, actor, target, whole_scene=True) else False


@effect("candle_last_wick_used")
def last_wick_used(ctx: Any, row: dict[str, Any]) -> None:
    ctx.engine._apply_condition(ctx.actor, LAST_WICK_USED, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Last Wick Extinguishes used this activation"})


@effect("candle_last_wick")
def last_wick(ctx: Any, row: dict[str, Any]) -> None:
    from .stacking_marks import spend

    subject = ctx.target
    if subject is None:
        return
    held = wicks(ctx.engine, ctx.actor, subject)
    if not row.get("failed"):
        if held:
            spend(ctx.engine, ctx.actor, subject, SOUL_WICK, ctx.source, 1)
        ctx.rider(f"Last Wick Extinguishes: {subject.display_name}'s identified sustaining expression flickers until the start of its next turn (the GM applies it).")
        return
    if held:
        spend(ctx.engine, ctx.actor, subject, SOUL_WICK, ctx.source, held)
    if subject.active and subject.concentration is not None:
        ctx.engine._end_concentration(subject, "LAST_WICK_EXTINGUISHES")
        note(ctx.engine, ctx.source, ctx.actor, f"Last Wick Extinguishes: {subject.display_name}'s Concentration gutters out.", (subject,))
    else:
        ctx.rider(f"Last Wick Extinguishes: choose one sustaining expression of {subject.display_name} you identified. Compare its Source CL -- the "
                  "cultivation level of the ability that created the effect -- with your own. An ordinary one from a lower Source CL ends. A Restricted "
                  "one -- one that its own printed rules list as Restricted, because that teaching is controlled or guarded (a sect, guild, school, "
                  "shrine or lineage that limits who may learn it) rather than open to anyone, so judge it by that rule and not by how dangerous it looks "
                  "-- or any one from an equal Source CL, is suppressed for the scene; two successful end-of-turn saves restore it. One from a higher "
                  "Source CL loses one printed benefit until the end of its next turn, subject to a Cultivation Check (the GM applies it).")


@hook("death_save_failure")
def last_flame_failed_death_save(engine: Any, target: Any, natural: int, source: str) -> bool | None:
    """The whole triggering failure is ignored, including a natural one's two failures."""
    if any(c.condition_id == LAST_FLAME_USED for c in target.conditions.values()):
        return None
    from . import needle
    for keeper in engine.state.actors.values():
        if (not keeper.active or st.row(engine, keeper, "last_flame") is None or candle_hp(keeper) <= 0 or
                not st.can_react(keeper) or keeper.resources.get(RESONANCE, 0) < 6 or
                engine.grid.distance_ft(keeper.position, target.position) > 30):
            continue
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "LAST_FLAME_DEATH_SAVE", target.entity_id),
                            keeper, "choice:needle.candlemaker.last_flame_death_save", ["flame"],
                            labels={"flame": "Ignore this failed death saving throw (6 Resonance, Reaction; extinguish your Soul Candle)"},
                            preferred=["flame"] if keeper.team_id == target.team_id else [], allow_decline=True,
                            default="first" if keeper.team_id == target.team_id else "decline", name="Last Flame",
                            feature_id=LAST_FLAME, target_id=target.entity_id,
                            prompt=f"{target.display_name} failed a death saving throw. Use Last Flame?")
        if not chosen:
            continue
        with activation(engine, keeper, LAST_FLAME):
            engine._spend_resource(keeper, RESONANCE, 6, LAST_FLAME)
            keeper.reaction_available = False
            burn(engine, keeper, 0, LAST_FLAME, extinguish=True)
            engine._apply_condition(target, LAST_FLAME_USED, LAST_FLAME, keeper.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": "Protected by Last Flame this fight (once per creature)"})
            ctx = st.context(engine, keeper, _base_action(engine, LAST_FLAME), [target])
            _te().run_effects(ctx, [{"type": "deny_invisible", "applies_to": "target", "duration": {"kind": "until_end_of_next_turn"}}])
            grant_borrowed_breath(engine, keeper, target)
            note(engine, LAST_FLAME, keeper, f"Last Flame ignores {target.display_name}'s failed death saving throw.", (target,))
            return True
    return None


@hook("event", priority=100)
def borrowed_final_breath(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A fresh zero-HP episode owes one failure; ordinary unconsciousness does not."""
    if event_type != "LIFE_STATE_CHANGED" or not (kwargs.get("payload") or {}).get("fresh_zero_hp"):
        return
    target = engine.state.actors.get(kwargs.get("actor_id"))
    if target is None or target.life_state not in ("DYING", "CONSCIOUS"):
        return
    collect_borrowed_breath(engine, target)


@hook("zero_hp_default", priority=100)
def borrowed_dying_episode(engine: Any, target: Any, source: str, intent: Any) -> None:
    """The default lifecycle has prepared its fresh death-save record by now."""
    from . import life_state
    if life_state.wants_dying(engine, target):
        collect_borrowed_breath(engine, target)


def collect_borrowed_breath(engine: Any, target: Any) -> None:
    held = next((c for c in target.conditions.values() if c.condition_id == BORROWED), None)
    if held is None:
        return
    from . import life_state
    life_state.add_failed_death_save(engine, target, held.source_definition_id)
    st.remove(engine, target, held, "BORROWED_BREATH_SPENT")
    note(engine, held.source_definition_id, target, f"Borrowed Final Breath: {target.display_name} gains one failed death saving throw.")


def grant_borrowed_breath(engine: Any, keeper: Any, target: Any) -> None:
    """Hold the debt until the protecting Lantern field actually ends."""
    fields = [zone.zone_id for owner, zone in _lanterns(engine)
              if owner.team_id == target.team_id and engine._footprint_intersects(target, zone.affected_cells)]
    engine._apply_condition(target, DEFERRED_BREATH if fields else BORROWED, LAST_FLAME, keeper.entity_id,
                            expires_on="UNTIL_REMOVED", data={"lantern_fields": fields,
                            "label": "Borrowed Final Breath deferred until the Lantern ends" if fields else
                                     "Borrowed Final Breath: the next drop to 0 HP gives one failed death save"})


@hook("event")
def deferred_lantern_breath(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Leaving the field is not ending it; each recorded protecting field must end."""
    if event_type != "ZONE_REMOVED":
        return
    zone_id = (kwargs.get("payload") or {}).get("zone_id")
    for target in engine.state.actors.values():
        for held in list(target.conditions.values()):
            if held.condition_id != DEFERRED_BREATH or zone_id not in (held.data or {}).get("lantern_fields", []):
                continue
            fields = [z for z in held.data["lantern_fields"] if z != zone_id and
                      engine.state.zones.get(z) is not None and engine.state.zones[z].active]
            if fields:
                continue
            st.remove(engine, target, held, "LANTERN_ENDED")
            if target.active:
                engine._apply_condition(target, BORROWED, LAST_FLAME, held.source_actor_id, expires_on="UNTIL_REMOVED",
                                        data={"label": "Borrowed Final Breath: the next drop to 0 HP gives one failed death save"})
