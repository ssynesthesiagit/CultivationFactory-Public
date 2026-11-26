"""Heartbinder (Spirit Awakening subpath): Vow Marks, Devotion, Stand Together, Heart's Rebuke's Devotion ward, Borrowed Courage,
Chain of Devotion and Unbroken Vow (sys-resources-states 2026-09-29, system D2).

Source: owner text, LocalSources/03_paths/Spirit/Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "Heartbinder" (Vow Marks,
Devotion, CL3 Vow Mark / Stand Together, CL6 Heart's Rebuke, CL10 Borrowed Courage, CL14 Chain of Devotion, CL18 Unbroken Vow, "Normalized
Vow Procedures": Qualifying Devotion Event, Damage Transfer). None has a Spheres 5e or D&D 5.5e counterpart.

What runs:
  * Vow Mark (the rite): "The rite costs no Resonance outside immediate danger. During combat ... it requires an Action and 2 Resonance."
    The fight's first turn works the rite outside danger for free on the Heartbinder's nearest typed teammates (up to PB Vow Marks);
    in combat the "Vow Mark" action places one (the ordinary ``mark`` effect: its cap is PB, the oldest ends). Both need a willing creature:
    only teammates are offered. The text gives no range; 30 feet (an ally reach the rest of the tradition uses) is a judgment.
  * Devotion (pool ``resource:named.devotion``, maximum PB, 0 at the start): +1 "no more than once per turn" when a qualifying event
    from a nonallied hostile source or an uncontrolled hazard pays a real cost. Automated triggers: a damage share (combat/ext/
    damage_sharing.py's ``damage_shared`` hook) where the Heartbinder uses its Reaction to protect a marked creature, or a marked creature
    takes damage in place of another marked one; Heart's Rebuke; Unbroken Vow; a Chain reroll. Not automated: the Courage Shared /
    "meaningful promise" / save-against-fear bullets (GM lines: they need a marked creature's own saves and a scene objective).
  * Stand Together: when the Heartbinder, or a Vow-Marked ally within 30 feet of it, places a Resonance Mark on a hostile creature it may
    spend 1 Devotion to give one Vow-Marked ally within 30 feet Temporary HP = Wisdom modifier + PB, once per round per recipient. The
    built-in AI always spends and picks the most hurt recipient that would gain from it; a player set to Ask me is asked (STAND_TOGETHER).
  * Heart's Rebuke: the row is the generic reaction (a hostile creature damages a Vow-Marked one within 60 feet: Wisdom save, 4d8 + Wisdom,
    half and PB Temporary HP on a save). The ``devotion_ward`` effect adds "if you spend 1 Devotion ... the protected creature also gains
    Advantage on the next Intelligence, Wisdom, or Charisma saving throw it makes against the triggering creature before the end of its
    next turn" (spent when the Heartbinder has Devotion; a player set to Ask me is asked, DEVOTION_SPEND). The Devotion is spent before
    the Rebuke's own +1 is gained.
  * Borrowed Courage: Courage Shared ends Frightened, gives 2 x PB + Wisdom modifier Temporary HP and lets the target stand from Prone
    free (the parser had read "stand from Prone" as *imposing* Prone). Devotion Release spends up to 3 Devotion, one distinct benefit per
    point: heal Wisdom-modifier HP, then +1 to Int/Wis/Cha saves until the start of the Heartbinder's next turn; the "move 10 feet without
    Opportunity Attacks" and "learn a recovery route" benefits stay GM riders (the Heartbinder simply spends only for what runs).
    Target: a Vow-Marked creature within 60 feet (never the Heartbinder itself, which bears no mark of its own).
    Hold the Heart / Bear It With Me need effect suppression and transfer (system G).
  * Chain of Devotion (Action, 6 Resonance, Concentration): links up to PB selected willing Vow-Marked creatures,
    optionally including the Heartbinder (the text names no range). While at least two linked creatures are within 60 feet each linked creature gets +1 to Int,
    Wis and Cha saves; the damage half is combat/ext/damage_sharing.py (its CHAIN condition); once per round when a linked creature fails
    an Int/Wis/Cha save another linked creature within 60 feet that has 1 Devotion and its Reaction may spend both to reroll it (only a
    Heartbinder holds Devotion, so it is the Heartbinder). The condition ends with the Heartbinder's Concentration. Not automated: Chain
    Anchor (a 8 x PB HP object that keeps the Chain without Concentration), the 1-mile sense and the free emotional impression.
  * Unbroken Vow: on the Heartbinder's reaction row (generic ``ally_drop_to_zero``) the target is kept at 1 HP for the hit
    (``hold_at_1hp``) and put under DELAY until the end of its next turn: further damage cannot take it below 1 HP; when the delay ends
    with it still at 1 HP the consequence occurs (it drops to 0 HP -- this engine has no death state, so "convert death into
    unconsciousness" (The Bond Refuses, success) and the failed check end the same way). Healing above 1 HP in the delay cancels it.
    Not automated: the Exhaustion + 3 Devotion extension, The Bond Refuses roll and its Vow Scar, the Unbroken Bond Field contributions,
    protection from possession or soul displacement, and any consequence but the drop to 0 HP.
Damage during the delay is capped through the ``damage_pending`` hook, which sees only damage dealt during an action with an intent
(turn-start hazards and burning skip it: a documented limit).

Plug-in surface: effects devotion_ward, devotion_chain, devotion_release, unbroken_vow_delay; hooks event (fight-start rite, Stand Together,
the delay's end), damage_shared (new, documented in combat/ext/__init__.py), damage_pending, save, after_save, candidate_allowed,
ai_candidate_allowed.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from .damage_sharing import CHAIN

TRADITION = "tianxia.tradition.spirit.heartbinder.feature."
VOW_MARK = TRADITION + "vow_mark"
REBUKE = TRADITION + "heart_s_rebuke"
COURAGE = TRADITION + "borrowed_courage"
CHAIN_OF_DEVOTION = TRADITION + "chain_of_devotion"
UNBROKEN_VOW = TRADITION + "unbroken_vow"
DEVOTION = "resource:named.devotion"
MARK = "Vow Mark"
WARD = "condition:typed.heart_s_rebuke_ward"
DELAY = "condition:typed.unbroken_vow_delay"
MENTAL = ("INT", "WIS", "CHA")
RESONANCE_MARKS = ("resonance", "resonance_mark", "resonance_marked")  # the slugs the Spirit features name their Resonance Mark by
RANGE_FT = 30  # Vow Mark rite reach (judgment) and Stand Together's "within 30 feet"


# ------------------------------------------------------------------------------------------------------ small helpers
def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _typed(action: Any) -> dict[str, Any]:
    return (getattr(action, "parameters", None) or {}).get("typed") or {}


def _pb(actor: Any) -> int:
    return int(actor.proficiency_bonus)


def is_heartbinder(actor: Any) -> bool:
    return actor.active and actor.resource_maximums.get(DEVOTION, 0) > 0


def _heartbinders(engine: Any) -> list[Any]:
    return [actor for actor in engine.state.actors.values() if is_heartbinder(actor)]


def marked_by(actor: Any, owner: Any) -> bool:
    return _te().bears_mark(actor, owner.entity_id, MARK)


def _marked(engine: Any, owner: Any) -> list[Any]:
    """Every active creature of the owner's team bearing the owner's Vow Mark, nearest first."""
    return sorted((a for a in engine.state.actors.values() if a.active and a.entity_id != owner.entity_id and a.team_id == owner.team_id and marked_by(a, owner)),
                  key=lambda a: (engine.grid.distance_ft(a.position, owner.position), a.entity_id))


def _key_mod(engine: Any, actor: Any) -> int:
    from .eye_common import numbers_of

    return int(numbers_of(engine, actor).get("key_mod") or 0)


def _knows(engine: Any, actor: Any, feature_id: str) -> bool:
    return any(action.owner_id == actor.entity_id and str(_typed(action).get("source") or "").split("#")[0] == feature_id for action in engine.action_catalog.values())


def _ask(engine: Any, actor: Any, feature_id: str, label: str) -> bool:
    from .. import typed_reactions

    return typed_reactions._consent(engine, {"feature_id": feature_id, "ask": True}, actor, label)


def _hostile(engine: Any, owner: Any, source_actor_id: str | None) -> bool:
    """"a nonallied hostile source or an uncontrolled hazard" (Qualifying Devotion Event): no creature at all is a hazard."""
    source = engine.state.actors.get(source_actor_id) if source_actor_id else None
    return source is None or source.team_id != owner.team_id


def gain(engine: Any, owner: Any, source: str, why: str) -> bool:
    """+1 Devotion, "no more than once per turn" (each creature's turn of the round is one turn)."""
    if not is_heartbinder(owner):
        return False
    stamp = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    if owner.turn_flags.get("once_per_round:devotion_turn") == stamp:
        return False
    owner.turn_flags["once_per_round:devotion_turn"] = stamp  # a key that survives the turn's reset
    before = owner.resources.get(DEVOTION, 0)
    engine._gain_resource(owner, DEVOTION, 1, source)
    if owner.resources.get(DEVOTION, 0) > before:
        note(engine, source, owner, f"{owner.display_name} gains 1 Devotion ({why}); now {owner.resources[DEVOTION]}.")
    return True


# ------------------------------------------------------------------------------------------------------ the Vow Mark rite
def _rite_at_fight_start(engine: Any) -> None:
    typed_ids = getattr(engine, "typed_actor_ids", set())
    for owner in list(engine.state.actors.values()):
        if not owner.active or not _knows(engine, owner, VOW_MARK):
            continue
        friends = sorted((a for a in engine.state.actors.values() if a.active and a.team_id == owner.team_id and a.entity_id != owner.entity_id
                          and a.entity_id in typed_ids and not marked_by(a, owner)),
                         key=lambda a: (engine.grid.distance_ft(a.position, owner.position), a.entity_id))
        room = max(0, _pb(owner) - len(_marked(engine, owner)))
        bound = friends[:room]
        for friend in bound:
            engine._apply_condition(friend, _te().mark_condition_id(MARK, owner.entity_id), VOW_MARK, owner.entity_id, expires_on="UNTIL_REMOVED")
        if bound:
            note(engine, VOW_MARK, owner, f"{owner.display_name} shares the Vow Mark rite with {', '.join(f.display_name for f in bound)} "
                                          "(a 1-minute rite worked before the fight, no Resonance).", tuple(bound))


# ------------------------------------------------------------------------------------------------------ Stand Together
def _stand_together(engine: Any, kwargs: dict[str, Any]) -> None:
    condition_id = str((kwargs.get("payload") or {}).get("condition_id") or "")
    if not condition_id.startswith(_te().MARK_PREFIX) or condition_id[len(_te().MARK_PREFIX):].split(".", 1)[0] not in RESONANCE_MARKS:
        return
    placer = engine.state.actors.get(kwargs.get("actor_id") or "")
    marked = next((engine.state.actors.get(target_id) for target_id in kwargs.get("target_ids") or ()), None)
    if placer is None or marked is None:
        return
    for owner in _heartbinders(engine):
        if marked.team_id == owner.team_id or not (placer is owner or (marked_by(placer, owner) and engine.grid.distance_ft(placer.position, owner.position) <= RANGE_FT)):
            continue
        amount = max(0, _key_mod(engine, owner)) + _pb(owner)
        options = [a for a in _marked(engine, owner) if engine.grid.distance_ft(a.position, owner.position) <= RANGE_FT
                   and a.turn_flags.get("once_per_round:stand_together") != engine.state.round_number and a.temporary_hp < amount]
        if owner.resources.get(DEVOTION, 0) < 1 or not options or not _ask(engine, owner, VOW_MARK, "STAND_TOGETHER"):
            continue
        ally = min(options, key=lambda a: ((a.current_hp + a.temporary_hp) / max(1, a.maximum_hp), a.entity_id))
        engine._spend_resource(owner, DEVOTION, 1, VOW_MARK)
        ally.turn_flags["once_per_round:stand_together"] = engine.state.round_number  # "only once per round"
        engine._grant_temp_hp(ally, amount, VOW_MARK, owner.entity_id)
        note(engine, VOW_MARK, owner, f"Stand Together: {owner.display_name} spends 1 Devotion and {ally.display_name} gains {amount} Temporary HP "
                                       f"({placer.display_name} placed a Resonance Mark on {marked.display_name}).", (ally,))


# ------------------------------------------------------------------------------------------------------ Unbroken Vow's delay
def _delay_ends(engine: Any, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if payload.get("condition_id") != DELAY or not payload.get("checkpoint"):
        return  # removed early (healed, or replaced), not run out
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is None or not target.active:
            continue
        if target.current_hp > 1:
            note(engine, UNBROKEN_VOW, target, f"Unbroken Vow ends: {target.display_name} was healed past 1 Hit Point, so the delayed consequence no longer applies.", (target,))
            continue
        note(engine, UNBROKEN_VOW, target, f"Unbroken Vow ends: {target.display_name} is still at 1 Hit Point, so the delayed consequence occurs "
                                            "(it falls to 0 Hit Points).", (target,))
        engine._damage_unreduced = target.entity_id
        try:
            engine._commit_damage(target, target.current_hp + target.temporary_hp, "UNTYPED", UNBROKEN_VOW, target.entity_id, None, reaction_depth=2)
        finally:
            engine._damage_unreduced = None


@hook("event")
def on_event(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "TURN_STARTED" and (kwargs.get("payload") or {}).get("initial") and not getattr(engine, "_hb_rite_done", False):
        engine._hb_rite_done = True
        _rite_at_fight_start(engine)
    elif event_type == "CONDITION_APPLIED":
        _stand_together(engine, kwargs)
    elif event_type == "CONDITION_REMOVED":
        _delay_ends(engine, kwargs)


# ------------------------------------------------------------------------------------------------------ Devotion from a share
@hook("damage_shared")
def devotion_from_a_share(engine: Any, taker: Any, target: Any, row: dict[str, Any], source_actor_id: str | None, taken: int) -> None:
    """Qualifying Devotion Event: "you use a Reaction ... to protect a marked creature from a hostile source", or "a Vow-Marked creature
    willingly takes damage ... to protect another marked creature" (it must take some: a real cost)."""
    for owner in _heartbinders(engine):
        if not _hostile(engine, owner, source_actor_id) or not marked_by(target, owner):
            continue
        if taker is owner or (taken > 0 and marked_by(taker, owner)):
            gain(engine, owner, VOW_MARK, f"{taker.display_name} protects {target.display_name}")


# ------------------------------------------------------------------------------------------------------ Heart's Rebuke's ward
@effect("devotion_ward")
def devotion_ward(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner, trigger = ctx.engine, ctx.actor, ctx.target
    protected = engine.state.actors.get(ctx.typed.get("protects") or "")
    if protected is None or trigger is None:
        return
    if owner.resources.get(DEVOTION, 0) >= 1 and _ask(engine, owner, REBUKE, "DEVOTION_SPEND"):
        engine._spend_resource(owner, DEVOTION, 1, REBUKE)
        for held in list(protected.conditions.values()):
            if held.condition_id == WARD and (held.data or {}).get("against") == trigger.entity_id:
                engine._remove_condition(protected, WARD, REBUKE)
        engine._apply_condition(protected, WARD, REBUKE, owner.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN", data={
            "against": trigger.entity_id, "label": f"Heart's Rebuke ward ({trigger.display_name})",
            "reading": f"Advantage on its next Intelligence, Wisdom or Charisma saving throw against {trigger.display_name}, before the end of its next turn."})
        note(engine, REBUKE, owner, f"{owner.display_name} spends 1 Devotion: {protected.display_name} has Advantage on its next Intelligence, Wisdom or "
                                    f"Charisma save against {trigger.display_name}.", (protected,))
    if _hostile(engine, owner, trigger.entity_id):
        gain(engine, owner, REBUKE, f"protecting {protected.display_name} from {trigger.display_name}")


# ------------------------------------------------------------------------------------------------------ Borrowed Courage
@effect("devotion_release")
def devotion_release(ctx: Any, eff: dict[str, Any]) -> None:
    """Devotion Release: up to 3 Devotion, one distinct benefit per point -- the Heartbinder's choice (asked; rider lane C8 2026-09-30: it
    was picked for the player). The AI takes the heal when it heals and the save bonus; "the target may move 10 feet without provoking
    Opportunity Attacks" is a move the target's side chooses."""
    from . import needle, save_bonus_status
    from . import spirit_traditions as st

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    mod = _key_mod(engine, owner)
    available = int(owner.resources.get(DEVOTION, 0))
    if available < 1:
        note(engine, COURAGE, owner, f"{owner.display_name} has no Devotion to spend on {target.display_name}.", (target,))
        return
    benefits = {"heal": f"{target.display_name} regains {mod} Hit Points", "move": f"{target.display_name} may move 10 feet without provoking Opportunity Attacks",
                "saves": f"{target.display_name} gains +1 to Intelligence, Wisdom and Charisma saves until the start of your next turn"}
    preferred = (["heal"] if mod > 0 and target.current_hp < target.maximum_hp else []) + ["saves"]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "DEVOTION_RELEASE", target.entity_id), owner, "choice:needle.heartbinder.devotion_release",
                        list(benefits), labels=benefits, preferred=preferred[:min(3, available)], minimum=1, maximum=min(3, available),
                        default_count=min(len(preferred), available), prompt=f"Devotion Release: spend up to {min(3, available)} Devotion, one benefit each.",
                        name="Devotion Release", feature_id=COURAGE, target_id=target.entity_id)
    picked = [key for key in chosen if key in benefits][:min(3, available)] or preferred[:min(3, available)]
    engine._spend_resource(owner, DEVOTION, len(picked), COURAGE)
    said = []
    for benefit in picked:
        if benefit == "heal":
            _te().block_healing(ctx, {"type": "healing", "applies_to": "ally", "flat": 0, "formula": "key_ability_modifier"})
            said.append(f"regains {mod} Hit Points")
        elif benefit == "saves":
            engine._apply_condition(target, save_bonus_status.CONDITION, COURAGE, owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN", data={
                "rule": {"save_bonus": {"bonus": 1, "abilities": list(MENTAL), "against": [], "family": ""}},
                "label": "+1 to Intelligence, Wisdom and Charisma saves (Devotion Release)"})
            said.append("gains +1 to Intelligence, Wisdom and Charisma saves until the start of the Heartbinder's next turn")
        else:
            routes = {cell: v for cell, v in st.routes(engine, target, 10).items() if cell != target.position}
            path = st.choose_route(engine, target, routes, ctx.intent, checkpoint="DEVOTION_RELEASE_MOVE",
                                   prompt=f"Devotion Release: {target.display_name} may move 10 feet without provoking.", name="Devotion Release",
                                   feature=COURAGE) if routes else None
            if path is not None:
                from .rider_movement import step

                step(engine, target, list(path), COURAGE)
            said.append("may move 10 feet without provoking")
    note(engine, COURAGE, owner, f"Devotion Release: {owner.display_name} spends {len(picked)} Devotion and {target.display_name} " + " and ".join(said) + ".", (target,))


# ------------------------------------------------------------------------------------------------------ Heart's Rebuke's Rebukes
APPROACH = "condition:typed.do_not_approach"


@effect("heart_rebuke")
def heart_rebuke(ctx: Any, eff: dict[str, Any]) -> None:
    """"suffers one Rebuke until the start of its next turn" -- the Heartbinder's choice (asked; rider lane C8 2026-09-30: the typing
    always imposed Feel What You Caused). The AI takes Feel What You Caused."""
    from . import needle
    from . import spirit_traditions as st

    engine, owner, trigger = ctx.engine, ctx.actor, ctx.target
    intent = ctx.intent or engine._active_intent  # a generic reaction row runs without its own intent
    protected = engine.state.actors.get(ctx.typed.get("protects") or "")
    if trigger is None or not trigger.active:
        return
    options = {"feel": "Feel What You Caused: Disadvantage on the next attack roll it makes",
               "remembers": "The Bond Remembers: it becomes Resonance Marked for the scene",
               **({"alarm": f"Shared Alarm: {protected.display_name} may move up to half its Speed without provoking its Opportunity Attacks",
                   "approach": f"Do Not Approach: it cannot willingly move closer to {protected.display_name}"} if protected is not None else {})}
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "HEART_REBUKE", trigger.entity_id), owner, "choice:needle.heartbinder.rebuke",
                        list(options), labels=options, preferred=["feel"], prompt=f"Heart's Rebuke: which Rebuke does {trigger.display_name} suffer?",
                        name="Heart's Rebuke", feature_id=REBUKE, target_id=trigger.entity_id)
    pick = chosen[0] if chosen and chosen[0] in options else "feel"
    if pick == "feel":
        _te().run_effects(ctx, [{"type": "disadvantage", "applies_to": "target", "on": "the next attack roll it makes", "duration": "until_start_of_next_turn",
                                 "evidence": "It has Disadvantage on the next attack roll it makes"}])
    elif pick == "remembers":
        _te().run_effects(ctx, [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_removed"},
                                 "evidence": "It becomes Resonance Marked for the scene"}])
    elif pick == "alarm":
        half = engine._effective_speed(protected) // 2
        routes = {cell: v for cell, v in st.routes(engine, protected, half).items() if cell != protected.position} if half > 0 else {}
        path = st.choose_route(engine, protected, routes, intent, checkpoint="SHARED_ALARM", prompt=f"Shared Alarm: where does {protected.display_name} move?",
                               name="Heart's Rebuke", feature=REBUKE) if routes else None
        if path is not None:
            from .rider_movement import step

            step(engine, protected, list(path), REBUKE)
    else:
        expires = _te().effect_expiry(ctx, {"duration": {"kind": "until_start_of_next_turn"}}, trigger, condition=True)
        engine._apply_condition(trigger, APPROACH, REBUKE, owner.entity_id, expires_on=expires or "START_OF_TARGET_NEXT_TURN",
                                data={"protected": protected.entity_id, "label": f"Do Not Approach: it cannot willingly move closer to {protected.display_name}"})


def _approach_blocked(engine: Any, actor: Any, candidate: Any) -> bool:
    """Do Not Approach: a move of its own that ends closer to the protected creature is not offered."""
    destination = getattr(candidate, "destination", None)
    if destination is None or str(getattr(getattr(candidate, "kind", None), "value", getattr(candidate, "kind", ""))) != "MOVE":
        return False
    for held in actor.conditions.values():
        protected = engine.state.actors.get(str((held.data or {}).get("protected") or "")) if held.condition_id == APPROACH else None
        if protected is not None and engine._distance_actor_to_actor(actor, protected, actor_position=destination) < engine._distance_actor_to_actor(actor, protected):
            return True
    return False


# ------------------------------------------------------------------------------------------------------ Chain of Devotion
def _link(actor: Any) -> Any | None:
    return next((c for c in actor.conditions.values() if c.condition_id == CHAIN), None)


def _owner_id(condition: Any) -> str | None:
    return ((condition.data or {}).get("share") or {}).get("owner")


def _linked_near(engine: Any, subject: Any) -> list[Any]:
    """The other creatures of the subject's Chain within 60 feet of it."""
    mine = _link(subject)
    if mine is None:
        return []
    return sorted((a for a in engine.state.actors.values() if a.active and a.entity_id != subject.entity_id and (_link(a) is not None)
                   and _owner_id(_link(a)) == _owner_id(mine) and engine.grid.distance_ft(a.position, subject.position) <= 60),
                  key=lambda a: (engine.grid.distance_ft(a.position, subject.position), a.entity_id))


@effect("devotion_chain")
def devotion_chain(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    for creature in engine.state.actors.values():
        held = _link(creature)
        if held is not None and _owner_id(held) == owner.entity_id:
            engine._remove_condition(creature, CHAIN, ctx.source)  # casting it again replaces the old chain
    from . import needle
    from ..target_knowledge import can_see

    friends = [owner, *_marked(engine, owner)]
    ids = [a.entity_id for a in friends]
    automatic_ids = [a.entity_id for a in friends if a is owner or can_see(engine, owner, a)]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "DEVOTION_CHAIN_MEMBERS", owner.entity_id), owner,
                        "choice:needle.heartbinder.chain_members", ids,
                        labels={a.entity_id: a.display_name for a in friends}, preferred=automatic_ids[:_pb(owner)],
                        automatic_options=automatic_ids,
                        minimum=0, maximum=min(len(ids), _pb(owner)), default="all", allow_decline=True,
                        prompt=f"Chain of Devotion: choose up to {_pb(owner)} willing Vow-Marked creatures, including yourself.",
                        name="Chain of Devotion", feature_id=CHAIN_OF_DEVOTION) if ids else []
    linked = [a for a in friends if a.entity_id in chosen]
    if len(linked) < 2:
        note(engine, ctx.source, owner, "Chain of Devotion needs at least two chosen creatures; no Chain forms.")
        return
    for creature in linked:
        engine._apply_condition(creature, CHAIN, ctx.source, owner.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED", data={
            "share": {"owner": owner.entity_id}, "label": "Devotion Chain",
            "reading": f"Linked by {owner.display_name}: +1 to Intelligence, Wisdom and Charisma saves while another linked creature is within 60 feet; once per round "
                       "another linked creature within 60 feet may take up to half of damage in its place, or spend 1 Devotion and its Reaction to "
                       "reroll a failed Intelligence, Wisdom or Charisma save. Ends with the Heartbinder's Concentration."})
    note(engine, ctx.source, owner, f"{owner.display_name} raises a Devotion Chain linking {', '.join(c.display_name for c in linked)}.", tuple(linked))


@hook("save")
def chain_and_ward(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if str(ability or "").upper()[:3] not in MENTAL:
        return None
    bonus = 1 if _linked_near(ctx.engine, subject) else 0  # "+1 ... while at least two linked creatures remain within 60 feet"
    warded = any(c.condition_id == WARD and (c.data or {}).get("against") == ctx.actor.entity_id for c in subject.conditions.values())
    return {"bonus": bonus, "modes": ["ADVANTAGE"] if warded else []} if bonus or warded else None


def _last_save(engine: Any, subject: Any) -> dict[str, Any] | None:
    return next(((event.payload or {}) for event in reversed(engine.events[-40:])
                 if event.event_type == "SAVE_ROLLED" and event.actor_id == subject.entity_id and (event.payload or {}).get("dc") is not None), None)


@hook("after_save")
def after_a_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """The ward is used up by the next save it covers; a failed mental save of a linked creature may be rerolled by another linked one."""
    from .. import typed_reactions

    engine, code = ctx.engine, str(ability or "").upper()[:3]
    if code not in MENTAL:
        return
    for held in list(subject.conditions.values()):
        if held.condition_id == WARD and (held.data or {}).get("against") == ctx.actor.entity_id:
            engine._remove_condition(subject, WARD, REBUKE)  # "the next ... saving throw it makes against the triggering creature"
    link = _link(subject)
    if not failed or link is None or not subject.active or subject.team_id == ctx.actor.team_id:
        return
    owner = engine.state.actors.get(_owner_id(link) or "")
    key = f"once_per_round:chain_reroll:{_owner_id(link)}"
    if owner is None or owner.turn_flags.get(key) == engine.state.round_number or (getattr(engine, "_typed_roll_outcome", None) or {}).get(subject.entity_id) == "success":
        return
    rolled = _last_save(engine, subject)
    helper = next((a for a in _linked_near(engine, subject) if a.resources.get(DEVOTION, 0) >= 1 and typed_reactions._can_react(engine, a)), None)
    if rolled is None or helper is None or not _ask(engine, helper, CHAIN_OF_DEVOTION, "CHAIN_REROLL"):
        return
    with activation(engine, helper, CHAIN_OF_DEVOTION):
        typed_reactions._open(engine, {"feature_id": CHAIN_OF_DEVOTION, "block": "devotion_chain"}, helper, (subject.entity_id,), "SAVE_RESULT_BEFORE_DECLARED",
                              {"protects": subject.entity_id})
        engine._spend_resource(helper, DEVOTION, 1, CHAIN_OF_DEVOTION)
        owner.turn_flags[key] = engine.state.round_number  # "once per round" for the whole Chain
        dc = int(rolled["dc"])
        mode = rolled.get("mode") if rolled.get("mode") in ("ADVANTAGE", "DISADVANTAGE") else None
        fresh = engine._roll_save(subject, code, dc, ctx.source, extra_mode=mode)
        now_failed = fresh.total < dc
        engine._typed_roll_outcome = {**(getattr(engine, "_typed_roll_outcome", None) or {}), subject.entity_id: "failure" if now_failed else "success"}
        note(engine, CHAIN_OF_DEVOTION, helper, f"{helper.display_name} spends 1 Devotion and its Reaction: {subject.display_name} rerolls the {code} save "
                                                f"({rolled.get('total')} -> {fresh.total} against DC {dc}) and " + ("still fails." if now_failed else "succeeds."), (subject,))
        if marked_by(subject, helper) and _hostile(engine, helper, ctx.actor.entity_id):
            gain(engine, helper, CHAIN_OF_DEVOTION, f"protecting {subject.display_name}")


# ------------------------------------------------------------------------------------------------------ Unbroken Vow
@effect("unbroken_vow_delay")
def unbroken_vow(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    engine._remove_condition(target, DELAY, ctx.source)
    engine._apply_condition(target, DELAY, ctx.source, owner.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN", data={
        "label": "Unbroken Vow", "reading": f"{owner.display_name}'s Unbroken Vow holds it at 1 Hit Point until the end of its next turn: damage cannot take it lower. "
                                            "If it is still at 1 Hit Point then, the consequence occurs (it falls to 0 Hit Points)."})
    note(engine, ctx.source, owner, f"{owner.display_name} spends 10 Resonance: Unbroken Vow holds {target.display_name} at 1 Hit Point until the end of its next turn.", (target,))
    gain(engine, owner, ctx.source, f"protecting {target.display_name}")


@hook("damage_pending")
def hold_during_the_delay(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str | None) -> int:
    if pending < 1 or not any(c.condition_id == DELAY for c in target.conditions.values()):
        return pending
    return min(pending, max(0, target.current_hp + target.temporary_hp - 1))


# ------------------------------------------------------------------------------------------------------ what is offered
def _effect_types(action: Any) -> set[str]:
    return {str(e.get("type")) for e in _typed(action).get("effects") or [] if isinstance(e, dict)}


@hook("candidate_allowed")
def allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if _approach_blocked(engine, actor, candidate):
        return False
    if action is None:  # a move or an end of turn has no action
        return None
    source = str(_typed(action).get("source") or action.source_definition_id or "").split("#")[0]
    if not source.startswith(TRADITION):
        return None
    targets = [engine.state.actors[t] for t in candidate.target_ids or () if t in engine.state.actors]
    if source == VOW_MARK:  # a willing teammate that does not bear the mark yet (a mark on oneself means nothing)
        return bool(targets) and all(t.entity_id != actor.entity_id and t.team_id == actor.team_id and not marked_by(t, actor) for t in targets)
    if source == COURAGE:  # "One willing Vow-Marked creature"
        return bool(targets) and all(marked_by(t, actor) for t in targets)
    if source == CHAIN_OF_DEVOTION:
        return bool(_marked(engine, actor))
    return None


@hook("ai_candidate_allowed")
def ai_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    source = str(_typed(action).get("source") or action.source_definition_id or "").split("#")[0]
    if not source.startswith(TRADITION):
        return None
    targets = [engine.state.actors[t] for t in candidate.target_ids or () if t in engine.state.actors]
    if source == VOW_MARK:
        return len(_marked(engine, actor)) < _pb(actor)  # a mark past the cap only replaces the oldest one
    if source == CHAIN_OF_DEVOTION:
        return not any(c.condition_id == CHAIN and _owner_id(c) == actor.entity_id for c in actor.conditions.values())
    if source == COURAGE:
        types = _effect_types(action)
        if "devotion_release" in types:
            mod = _key_mod(engine, actor)
            return actor.resources.get(DEVOTION, 0) >= 1 and any(t.current_hp < t.maximum_hp - max(0, mod) for t in targets)
        return any(any(c.condition_id.endswith(("frightened", "prone")) for c in t.conditions.values()) or t.current_hp * 2 <= t.maximum_hp for t in targets)
    return None
