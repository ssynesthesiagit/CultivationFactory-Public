"""Sovereign Will (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, "02. Sovereign Will": Mandate, CL3 Commanding Voice, CL6 Break Their Will, CL10 Edict
of Heaven, CL14 Retainer of the Empty Throne, CL18 Hegemon's Domain). No Spheres 5e or D&D 5.5e counterpart. Ownership rows:
combat/rules/feature_blocks.d/riders_c8.json (Break Their Will, Hegemon's Domain).

Mandate (tradition text): a pool (resource:named.mandate), maximum PB, 0 at the start of the fight. +1 when a hostile creature fails a save
against your Sovereign Will feature, or a hostile creature bearing your Resonance Mark is defeated -- once per creature per fight.

What runs:
  * Commanding Voice (typed options, one per command; 1 Resonance, or 1 Mandate against a creature you Resonance Marked with Break Their
    Will): Wisdom save. Failed -- your Resonance Mark (and Mandate), and at the start of its next turn: Approach (it moves toward you or an
    ally you name, up to its Speed), Flee (away from you, up to its Speed), Halt (Speed 0), Kneel (it falls Prone), Silence (no speech or
    audible techniques), Yield (it takes the Dodge action and makes no attacks); each lasts to the end of that turn. Drop is the GM's.
    Succeeded -- a Spiritual Pressure effect.
  * Break Their Will: Submission Shock (Reaction, 1 Mandate, asked) when a hostile creature within 60 feet is defeated or fails a save
    against Commanding Voice: another hostile creature within 30 feet of it makes a Wisdom save (once per round each) -- failed, Dazed
    by Submission until the end of its next turn (no Reactions, half Speed, an Action or a Bonus Action but not both); succeeded, a
    Spiritual Pressure effect.
  * Edict of Heaven (typed; 5 Resonance, or 3 Resonance and 2 Mandate): the edict and the creatures within 60 feet (asked), each a
    Charisma save. Failed until the start of your next turn: No Advance / No Escape (no move that ends closer to / farther from the creature
    you designate), No Reaction, No Violence (no attacks or damaging techniques), No Speech (silenced), No Passage (no teleporting; the
    threshold is the GM's), No <Expression> (the named action it used this fight is not offered). Succeeded: a Spiritual Pressure effect.
  * Retainer of the Empty Throne (typed, Bonus Action, 2 Resonance, a square within 30 feet): a Retainer object (AC your DC, 6 x PB HP;
    its damage type asked). Once on each of your turns after Commanding Voice, Mind Spike, Domain Pressure or Edict of Heaven (asked):
    Spectral Strike (a Cultivation Attack on a creature within 30 feet of it, 2d8 + Wisdom) or Interpose (an ally within 5 feet of it
    gains 2 x PB Temporary HP). "Move the Retainer" (free, once a turn, 30 feet). Destroyed: dormant for the fight.
  * Hegemon's Domain: using Domain Manifestation you may pay 4 more Resonance (asked). A hostile creature starting its turn in the Domain
    makes a Charisma save (once a turn): failed -- half Speed and no Reactions until the start of its next turn, and the Court Tax the
    first time that turn it acts against you (it pays 1 more of a printed cost, asked, or takes 2d10 + Wisdom Psychic); succeeded -- you
    choose Speed -10 or no Reactions until the start of its next turn. "Edict of Heaven (Absolute Edict)" once: no Resonance, the whole
    Domain, obeyed until the end of each target's next turn.

Plug-in surface: effects sovereign_command, sovereign_edict, sovereign_retainer; hooks compile_actions, candidate_allowed, event,
turn_start, turn_end, after_save_resolved, action_completed, technique_used, before_attack. Shared helpers used: spirit_traditions
(context/numbers/feature_action/feature_of/pick_creature/routes/choose_route/can_react/save/remove/data_of/set_data), needle,
zones.typed_zones, rider_movement.step, typed_executor.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.sovereign_will.feature."
VOICE = TRADITION + "commanding_voice"
BREAK = TRADITION + "break_their_will"
EDICT = TRADITION + "edict_of_heaven"
RETAINER = TRADITION + "retainer_of_the_empty_throne"
HEGEMON = TRADITION + "hegemon_s_domain"
DOMAIN_MANIFESTATION = "tianxia.path.spirit_awakening.feature.domain_manifestation"
MIND_SPIKE = "tianxia.path.spirit_awakening.feature.mind_spike"
DOMAIN_PRESSURE = "tianxia.path.spirit_awakening.feature.domain_pressure"
MANDATE = "resource:named.mandate"
RESONANCE = "resource:core.resonance"
COMMANDED = "condition:typed.sovereign_command"
OBEYING = "condition:typed.sovereign_obeying"
DAZED = "condition:typed.dazed_by_submission"
EDICTED = "condition:typed.sovereign_edict"
HEGEMONY = "condition:typed.hegemons_domain"
COURT = "condition:typed.court_of_submission"
RETAINER_OBJ = "object:typed.empty_throne_retainer:"
RETAINER_GONE = "condition:typed.retainer_dormant"
COMMANDS = ("approach", "flee", "halt", "kneel", "silence", "yield", "drop")
EDICTS = {"no_advance": "No Advance", "no_escape": "No Escape", "no_reaction": "No Reaction", "no_violence": "No Violence",
          "no_speech": "No Speech", "no_passage": "No Passage", "named": "No [Named Expression]"}


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _numbers(engine: Any, actor: Any) -> dict[str, Any]:
    return st.numbers(engine, actor)


def _ctx(engine: Any, sovereign: Any, feature: str, targets: list[Any], intent: Any = None) -> Any:
    return st.context(engine, sovereign, st.feature_action(engine, sovereign, feature), targets, _numbers(engine, sovereign), intent)


def gain_mandate(engine: Any, sovereign: Any, source_creature: Any, why: str) -> None:
    """"You can gain Mandate from a given creature only once per scene.\""""
    if MANDATE not in sovereign.resources or sovereign.resources.get(MANDATE, 0) >= sovereign.resource_maximums.get(MANDATE, 0):
        return
    given = list(sovereign.turn_flags.get("mandate_from_round_") or [])
    if source_creature.entity_id in given:
        return
    sovereign.turn_flags["mandate_from_round_"] = [*given, source_creature.entity_id]
    engine._gain_resource(sovereign, MANDATE, 1, VOICE)
    note(engine, VOICE, sovereign, f"{sovereign.display_name} gains 1 Mandate ({why}).")


def _is_sovereign_feature(action: Any) -> bool:
    return st.feature_of(action).startswith(TRADITION)


# ---------------------------------------------------------------------------------------------------------- Mandate and Submission Shock
@hook("after_save_resolved")
def sovereign_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    engine, sovereign = ctx.engine, ctx.actor
    if not failed or subject is None or sovereign is None or subject.team_id == sovereign.team_id:
        return
    if _is_sovereign_feature(ctx.action):
        gain_mandate(engine, sovereign, subject, f"{subject.display_name} failed a save against your Sovereign Will feature")
    if st.feature_of(ctx.action) == VOICE:
        _submission_shock(engine, subject, ctx.intent)


@hook("event")
def sovereign_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "ENTITY_DEFEATED":
        fallen = engine.state.actors.get(kwargs.get("actor_id") or "")
        if fallen is None or fallen.summon is not None:
            return
        for sovereign in engine.state.actors.values():
            if sovereign.active and sovereign.team_id != fallen.team_id and MANDATE in sovereign.resources and _te().bears_mark(fallen, sovereign.entity_id, "Resonance"):
                gain_mandate(engine, sovereign, fallen, f"{fallen.display_name}, bearing your Resonance Mark, fell")
        _submission_shock(engine, fallen, engine._active_intent)
        return
    if event_type == "OBJECT_UPDATED":
        _retainer_destroyed(engine, kwargs)


def _submission_shock(engine: Any, trigger: Any, intent: Any) -> None:
    """Submission Shock: "Choose another hostile creature within 30 feet of the triggering creature ... It makes a Wisdom saving throw.\""""
    for sovereign in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if (st.row(engine, sovereign, "break_their_will") is None or sovereign.team_id == trigger.team_id or not st.can_react(sovereign)
                or sovereign.resources.get(MANDATE, 0) < 1 or engine._distance_actor_to_actor(sovereign, trigger) > 60):
            continue
        others = [c for c in engine.state.actors.values() if c.active and c is not trigger and c.team_id != sovereign.team_id
                  and engine._distance_actor_to_actor(trigger, c) <= 30
                  and int(c.turn_flags.get("submission_shock_round_") or 0) != engine.state.round_number]
        target = st.pick_creature(engine, intent, sovereign, others, checkpoint="SUBMISSION_SHOCK", choice_id="choice:needle.sovereign.submission_shock",
                                  prompt=f"Submission Shock (Reaction, 1 Mandate): {trigger.display_name} breaks -- who else feels it?",
                                  name="Submission Shock", feature_id=BREAK, allow_decline=True)
        if target is None:
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, sovereign, BREAK, independent=True):
            sovereign.reaction_available = False
            engine._spend_resource(sovereign, MANDATE, 1, BREAK)
            target.turn_flags["submission_shock_round_"] = engine.state.round_number  # "A creature can be targeted by Submission Shock only once per round."
            engine._append_event("REACTION_RESOLVED", BREAK, actor_id=sovereign.entity_id, target_ids=(target.entity_id,),
                                 payload={"checkpoint": "SUBMISSION", "reaction_name": "Submission Shock"})
            sub = _ctx(engine, sovereign, BREAK, [target], intent)
            if st.save(sub, target, "wis"):
                gain_mandate(engine, sovereign, target, f"{target.display_name} failed against Submission Shock")  # a Sovereign Will feature (it has no action of its own)
                engine._apply_condition(target, DAZED, BREAK, sovereign.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                                        data={"rule": {"no_reactions": True}, "label": "Dazed by Submission: no Reactions, half Speed, an Action or a Bonus Action but not both"})
                _te().run_effects(sub, [{"type": "speed", "applies_to": "target", "halved": True, "duration": {"kind": "until_end_of_next_turn"}, "evidence": "its Speed is halved"}])
            else:
                _te().run_effects(sub, [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "It suffers one ordinary Spiritual Pressure effect."}])
            return


@hook("action_completed")
def dazed_economy(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    """Dazed by Submission: "can take either an Action or a Bonus Action on its turn but not both\""""
    if not any(c.condition_id == DAZED for c in actor.conditions.values()):
        return
    kind = str(economy or "").split(".")[-1].upper()
    if kind == "ACTION":
        actor.bonus_action_available = False
    elif kind == "BONUS_ACTION":
        actor.action_available = False


# ---------------------------------------------------------------------------------------------------------- Commanding Voice
@effect("sovereign_command")
def command(ctx: Any, row: dict[str, Any]) -> None:
    engine, sovereign = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    if target is None or not target.active:
        return
    kind = str(row.get("command"))
    if not st.save(ctx, target, "wis"):
        _te().run_effects(ctx, [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "On a successful save, choose one ordinary Spiritual Pressure effect."}])
        return
    _te().run_effects(ctx, [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                             "evidence": "the target also becomes Resonance Marked by you"}])
    toward = None
    if kind == "approach":
        allies = [c for c in engine.state.actors.values() if c.active and c.team_id == sovereign.team_id]
        point = st.pick_creature(engine, ctx.intent, sovereign, allies, checkpoint="APPROACH_POINT", choice_id="choice:needle.sovereign.approach",
                                 prompt=f"Approach: {target.display_name} moves toward whom?", name="Commanding Voice", feature_id=VOICE, preferred=sovereign)
        toward = (point or sovereign).entity_id
    engine._apply_condition(target, COMMANDED, VOICE, sovereign.entity_id, expires_on="UNTIL_REMOVED",
                            data={"command": kind, "toward": toward, "turn": int(target.turns_started),
                                  "label": f"Commanded ({kind.title()}) by {sovereign.display_name}: on its next turn"})


def _obey_move(engine: Any, creature: Any, sovereign: Any, toward: Any, away: bool) -> None:
    from .rider_movement import step

    speed = engine._effective_speed(creature)
    routes = st.routes(engine, creature, speed) if speed > 0 else {}
    if not routes:
        return
    anchor = engine.state.actors.get(str(toward or "")) or sovereign
    here = engine._distance_actor_to_actor(creature, anchor)
    if away:
        best = max(routes, key=lambda c: (engine.grid.distance_ft(c, anchor.position), -routes[c][1]))
        good = engine.grid.distance_ft(best, anchor.position) > here
    else:
        best = min(routes, key=lambda c: (engine.grid.distance_ft(c, anchor.position), routes[c][1]))
        good = engine.grid.distance_ft(best, anchor.position) < here
    if good and best != creature.position:
        step(engine, creature, list(routes[best][0]), VOICE)
        creature.movement_remaining_ft = max(0, int(creature.movement_remaining_ft) - int(routes[best][1]))


@hook("turn_start")
def obey(engine: Any, actor: Any) -> None:
    for held in [c for c in actor.conditions.values() if c.condition_id == COMMANDED]:
        data = held.data or {}
        sovereign = engine.state.actors.get(held.source_actor_id or "")
        st.remove(engine, actor, held, "OBEYED")
        if sovereign is None or not actor.active:
            continue
        kind = data.get("command")
        rule = {"halt": {"speed_zero": True}, "silence": {"silenced": True}}.get(kind, {})
        engine._apply_condition(actor, OBEYING, VOICE, sovereign.entity_id, expires_on="UNTIL_REMOVED",
                                data={"command": kind, **({"rule": rule} if rule else {}), "label": f"Obeying {sovereign.display_name}: {str(kind).title()} this turn"})
        if kind in ("approach", "flee"):
            _obey_move(engine, actor, sovereign, data.get("toward"), kind == "flee")
        elif kind == "kneel":
            _te().run_effects(_ctx(engine, sovereign, VOICE, [actor]), [{"type": "condition", "applies_to": "target", "condition": "prone",
                                                                          "duration": {"kind": "until_removed"}, "evidence": "Fall Prone"}])
        elif kind == "yield":
            engine._apply_condition(actor, "condition:core.dodge", VOICE, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN")  # "Take the Dodge action"
            actor.action_available = False
        elif kind == "drop":
            st.drop_held(engine, actor, actor, VOICE, triggering_command="Commanding Voice: Drop")


@hook("stand_allowed")
def commanded_kneel(engine: Any, actor: Any) -> bool | None:
    """Kneel: do not stand until the commanded turn has ended."""
    return False if any(c.condition_id == OBEYING and (c.data or {}).get("command") == "kneel"
                        for c in actor.conditions.values()) else None


@hook("turn_end")
def obeyed(engine: Any, actor: Any) -> None:
    for held in [c for c in actor.conditions.values() if c.condition_id == OBEYING]:
        st.remove(engine, actor, held, "TURN_ENDED")  # "until the end of the turn"


# ---------------------------------------------------------------------------------------------------------- Edict of Heaven
@effect("sovereign_edict")
def edict(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, sovereign = ctx.engine, ctx.actor
    absolute = bool(row.get("absolute"))
    domain = _hegemony_zone(engine, sovereign) if absolute else None
    if absolute:
        held = _held(sovereign, HEGEMONY)
        if held is not None:
            st.set_data(sovereign, held, absolute_used=True)  # "Once during each activation of Hegemon's Domain"
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "EDICT_KIND", sovereign.entity_id), sovereign, "choice:needle.sovereign.edict",
                        list(EDICTS), labels=EDICTS, preferred=["no_violence"], prompt="Edict of Heaven: declare which edict?", name="Edict of Heaven", feature_id=EDICT)
    kind = chosen[0] if chosen and chosen[0] in EDICTS else "no_violence"
    reach = [c for _, c in sorted(engine.state.actors.items()) if c.active and c is not sovereign
             and (engine._footprint_intersects(c, domain.affected_cells) if domain is not None else engine._distance_actor_to_actor(sovereign, c) <= 60)]
    ids = [c.entity_id for c in reach]
    hostile = [c.entity_id for c in reach if c.team_id != sovereign.team_id]
    picked = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "EDICT_TARGETS", sovereign.entity_id), sovereign, "choice:needle.sovereign.edict_targets",
                        ids, labels={c.entity_id: c.display_name for c in reach}, preferred=hostile, minimum=1, maximum=max(1, len(ids)), default="all",
                        prompt=f"Edict of Heaven ({EDICTS[kind]}): which creatures?", name="Edict of Heaven", feature_id=EDICT) if ids else []
    targets = [c for c in reach if c.entity_id in (picked or hostile)]
    designated, named = None, None
    if kind in ("no_advance", "no_escape"):
        pick = st.pick_creature(engine, ctx.intent, sovereign, [c for c in engine.state.actors.values() if c.active], checkpoint="EDICT_DESIGNATE",
                                choice_id="choice:needle.sovereign.designate", prompt=f"{EDICTS[kind]}: relative to which creature?", name="Edict of Heaven",
                                feature_id=EDICT, preferred=sovereign)
        designated = (pick or sovereign).entity_id
    if kind == "named":
        used = sorted({str(getattr(engine.action_catalog.get(e.source_definition_id), "display_name", "") or "") for e in engine.events
                       if e.event_type == "INTENT_ACCEPTED" and e.actor_id in {c.entity_id for c in targets}} - {"", "End turn", "Hold position"})
        if used:
            names = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "EDICT_NAME", sovereign.entity_id), sovereign, "choice:needle.sovereign.named",
                               used, labels={n: n for n in used}, preferred=used[:1], prompt="No [Named Expression]: forbid which one you saw it use?",
                               name="Edict of Heaven", feature_id=EDICT)
            named = (names or used[:1])[0]
    rule = {"no_reaction": {"no_reactions": True}, "no_speech": {"silenced": True}, "no_passage": {"no_teleport": True}}.get(kind, {})
    for target in targets:
        sub = st.context(engine, sovereign, ctx.action, [target], ctx.numbers, ctx.intent)
        if not st.save(sub, target, "cha"):
            _te().run_effects(sub, [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "the target resists the edict but suffers one ordinary Spiritual Pressure effect"}])
            continue
        engine._apply_condition(target, EDICTED, EDICT, sovereign.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN" if absolute else "START_OF_SOURCE_NEXT_TURN",
                                data={"edict": kind, "designated": designated, "named": named, **({"rule": rule} if rule else {}),
                                      "label": f"Edict of Heaven: {EDICTS[kind] if kind != 'named' else f'No {named}'}"})
        if target.team_id != sovereign.team_id:
            gain_mandate(engine, sovereign, target, f"{target.display_name} failed against your edict")


def _violent(engine: Any, action: Any, target: Any, actor: Any) -> bool:
    typed = (action.parameters or {}).get("typed") or {}
    rows = [r for r in (typed.get("effects") or []) if isinstance(r, dict)]
    if str(getattr(action, "resolution_kind", "")) != "TYPED" and str(getattr(action, "target_kind", "")).endswith("HOSTILE_ENTITY"):
        return True  # a weapon or natural attack of a creature the table runs itself
    if any(r.get("type") in ("attack", "damage") for r in rows) or int((action.parameters or {}).get("expected_damage") or 0) > 0:
        return True
    return typed.get("weapon") is not None and target is not None and target.team_id != actor.team_id


def _edict_blocks(engine: Any, actor: Any, candidate: Any, action: Any) -> bool:
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    spot = getattr(candidate, "destination", None)
    for held in [c for c in actor.conditions.values() if c.condition_id in (EDICTED, OBEYING)]:
        data = held.data or {}
        if held.condition_id == OBEYING:
            if data.get("command") == "yield" and action is not None and _violent(engine, action, target, actor):
                return True  # Yield: "do not make hostile attacks until the end of the turn"
            continue
        kind = data.get("edict")
        if kind == "no_violence" and action is not None and _violent(engine, action, target, actor):
            return True
        if kind == "named" and action is not None and str(action.display_name) == str(data.get("named")):
            return True
        if kind in ("no_advance", "no_escape") and spot is not None:
            other = engine.state.actors.get(str(data.get("designated") or ""))
            if other is None:
                continue
            now, then = engine._distance_actor_to_actor(actor, other), engine.grid.distance_ft(spot, other.position)
            if (kind == "no_advance" and then < now) or (kind == "no_escape" and then > now):
                return True
    return False


# ---------------------------------------------------------------------------------------------------------- Retainer of the Empty Throne
def retainer_of(engine: Any, sovereign: Any) -> Any:
    return next((o for o in engine.state.objects.values() if o.object_id.startswith(RETAINER_OBJ) and o.owner_id == sovereign.entity_id and not o.destroyed), None)


@effect("sovereign_retainer")
def retainer(ctx: Any, row: dict[str, Any]) -> None:
    from ..gate2_runtime_models import RuntimeObjectState
    from . import needle

    engine, sovereign = ctx.engine, ctx.actor
    mode = row.get("mode") or "manifest"
    obj = retainer_of(engine, sovereign)
    spot = getattr(ctx, "destination", None) or getattr(ctx.intent, "destination", None)
    if mode == "manifest":
        if spot is None:
            return
        if obj is not None:
            engine._update_object(obj.model_copy(update={"destroyed": True, "component": {**(obj.component or {}), "dismissed": True}}), RETAINER, sovereign.entity_id)
        kinds = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "RETAINER_TYPE", sovereign.entity_id), sovereign, "choice:needle.sovereign.retainer_type",
                           ["psychic", "necrotic", "radiant"], labels={"psychic": "Psychic", "necrotic": "Necrotic", "radiant": "Radiant"}, preferred=["psychic"],
                           prompt="Your Retainer's Spectral Strike deals which damage (chosen when it was created)?", name="Retainer of the Empty Throne", feature_id=RETAINER)
        numbers = ctx.numbers or _numbers(engine, sovereign)
        hp = 6 * int(numbers.get("pb") or 2)
        engine._update_object(RuntimeObjectState(object_id=f"{RETAINER_OBJ}{sovereign.entity_id}:{engine.state.event_sequence}", object_kind="EMPTY_THRONE_RETAINER",
                                                 position=spot, unattended=False, flammable=False, owner_id=sovereign.entity_id, ac=int(numbers.get("save_dc") or 10),
                                                 current_hp=hp, maximum_hp=hp, damage_immunities=("POISON",),
                                                 component={"label": f"{sovereign.display_name}'s Retainer", "damage_type": (kinds or ["psychic"])[0]}), RETAINER, sovereign.entity_id)
    elif mode == "move" and obj is not None:
        sovereign.turn_flags["retainer_moved"] = True
        if spot is not None:
            engine._update_object(obj.model_copy(update={"position": spot}), RETAINER, sovereign.entity_id)


@hook("technique_used")
def retainer_expression(ctx: Any) -> None:
    """Retainer expression: once a turn, when Commanding Voice, Mind Spike, Domain Pressure or Edict of Heaven is used, one
    Retainer expression is chosen."""
    from . import needle

    engine, sovereign = ctx.engine, ctx.actor
    feature = st.feature_of(ctx.action)
    if feature not in (VOICE, MIND_SPIKE, DOMAIN_PRESSURE, EDICT) or sovereign.turn_flags.get("retainer_expression"):
        return
    obj = retainer_of(engine, sovereign)
    if obj is None:
        return
    size = engine.grid.square_size_ft
    near = lambda c, feet: any(max(abs(x - obj.position.x), abs(y - obj.position.y)) * size <= feet for x, y in engine._actor_cells(c))  # noqa: E731
    foes = [c for c in engine.state.actors.values() if c.active and c.team_id != sovereign.team_id and near(c, 30)]
    friends = [c for c in engine.state.actors.values() if c.active and c.team_id == sovereign.team_id and near(c, 5)]
    options = {**({"strike": "Spectral Strike: a Cultivation Attack from the Retainer"} if foes else {}),
               **({"interpose": f"Interpose: an ally beside it gains {2 * int(_numbers(engine, sovereign).get('pb') or 2)} Temporary Hit Points"} if friends else {})}
    if not options:
        return
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "RETAINER_EXPRESSION", sovereign.entity_id), sovereign, "choice:needle.sovereign.retainer",
                        list(options), labels=options, preferred=list(options)[:1], allow_decline=True, prompt="Retainer of the Empty Throne: an expression?",
                        name="Retainer of the Empty Throne", feature_id=RETAINER)
    if not chosen or chosen[0] not in options:
        return
    sovereign.turn_flags["retainer_expression"] = True
    if chosen[0] == "strike":
        target = st.pick_creature(engine, ctx.intent, sovereign, foes, checkpoint="RETAINER_STRIKE", choice_id="choice:needle.sovereign.retainer_target",
                                  prompt="Spectral Strike: at whom?", name="Retainer of the Empty Throne", feature_id=RETAINER, preferred=foes[0])
        if target is not None:
            kind = str((obj.component or {}).get("damage_type") or "psychic")
            _te().run_effects(_ctx(engine, sovereign, RETAINER, [target], ctx.intent),
                              [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1, "applies_to": "target",
                                "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "formula": "key_ability_modifier",
                                            "damage_types": [kind], "evidence": "2d8 + Wisdom modifier damage"}]}])
    else:
        ally = st.pick_creature(engine, ctx.intent, sovereign, friends, checkpoint="RETAINER_INTERPOSE", choice_id="choice:needle.sovereign.interpose",
                                prompt="Interpose: which ally?", name="Retainer of the Empty Throne", feature_id=RETAINER, preferred=friends[0])
        if ally is not None:
            engine._grant_temp_hp(ally, 2 * int(_numbers(engine, sovereign).get("pb") or 2), RETAINER, sovereign.entity_id)


def _retainer_destroyed(engine: Any, kwargs: dict[str, Any]) -> None:
    obj = (kwargs.get("payload") or {}).get("object") or {}
    if not str(obj.get("object_id") or "").startswith(RETAINER_OBJ) or (obj.get("component") or {}).get("dismissed"):
        return
    if not (obj.get("destroyed") or (obj.get("current_hp") is not None and int(obj.get("current_hp") or 0) <= 0)):
        return
    sovereign = engine.state.actors.get(str(obj.get("owner_id") or ""))
    stored = engine.state.objects.get(str(obj.get("object_id")))
    if stored is not None:
        engine._update_object(stored.model_copy(update={"component": {**(stored.component or {}), "dismissed": True}}), RETAINER, stored.owner_id)
    if sovereign is not None:  # a destroyed Retainer stays dormant until a Full Cultivation Session is completed
        engine._apply_condition(sovereign, RETAINER_GONE, RETAINER, sovereign.entity_id, expires_on="UNTIL_REMOVED", data={"label": "Your Retainer is dormant this fight"})


# ---------------------------------------------------------------------------------------------------------- Hegemon's Domain
def _held(creature: Any, condition_id: str) -> Any:
    return next((c for c in creature.conditions.values() if c.condition_id == condition_id and c.source_actor_id == creature.entity_id), None)


def _hegemony_zone(engine: Any, sovereign: Any) -> Any:
    from .. import zones

    if _held(sovereign, HEGEMONY) is None:
        return None
    return next((z for z in zones.typed_zones(engine) if z.owner_id == sovereign.entity_id
                 and st.feature_of(engine.action_catalog.get(z.source_definition_id)) == DOMAIN_MANIFESTATION), None)


@hook("technique_used")
def hegemon_transform(ctx: Any) -> None:
    """Hegemon's Domain: activating Domain Manifestation may spend 4 extra Resonance to turn it into Hegemon's Domain for the scene."""
    from . import needle

    engine, sovereign = ctx.engine, ctx.actor
    if st.feature_of(ctx.action) != DOMAIN_MANIFESTATION or st.row(engine, sovereign, "hegemon_s_domain") is None or sovereign.resources.get(RESONANCE, 0) < 4:
        return
    if not needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "HEGEMON", sovereign.entity_id), sovereign, "choice:needle.sovereign.hegemon",
                      ["hegemon"], labels={"hegemon": "Spend 4 more Resonance: Hegemon's Domain"}, preferred=["hegemon"], allow_decline=True,
                      prompt="Domain Manifestation", name="Hegemon's Domain", feature_id=HEGEMON):
        return
    engine._spend_resource(sovereign, RESONANCE, 4, HEGEMON)
    old = _held(sovereign, HEGEMONY)
    if old is not None:
        st.remove(engine, sovereign, old, "REPLACED")
    engine._apply_condition(sovereign, HEGEMONY, HEGEMON, sovereign.entity_id, expires_on="UNTIL_REMOVED", data={"label": "Hegemon's Domain"})


@hook("turn_start")
def court_of_submission(engine: Any, actor: Any) -> None:
    from . import needle

    if not actor.active:
        return
    for sovereign in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        zone = _hegemony_zone(engine, sovereign) if sovereign.team_id != actor.team_id else None
        if zone is None or not engine._footprint_intersects(actor, zone.affected_cells):
            continue
        sub = _ctx(engine, sovereign, HEGEMON, [actor])
        until = {"kind": "until_start_of_next_turn"}
        if st.save(sub, actor, "cha"):
            _te().run_effects(sub, [{"type": "speed", "applies_to": "target", "halved": True, "duration": until, "evidence": "Its Speed is halved"},
                                    {"type": "reaction_denied", "applies_to": "target", "duration": until, "evidence": "it cannot take Reactions"}])
            engine._apply_condition(actor, COURT, HEGEMON, sovereign.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                                    data={"turn": int(actor.turns_started), "label": f"Court Tax: acting against {sovereign.display_name} costs more this turn"})
        else:
            chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "COURT_SUCCESS", actor.entity_id), sovereign, "choice:needle.sovereign.court",
                                ["slow", "still"], labels={"slow": "Speed reduced by 10 feet", "still": "No Reactions"}, preferred=["still"],
                                prompt=f"Court of Submission: {actor.display_name} resisted -- choose one.", name="Hegemon's Domain", feature_id=HEGEMON)
            pick = (chosen or ["still"])[0]
            _te().run_effects(sub, [{"type": "speed", "applies_to": "target", "flat": -10, "duration": until, "evidence": "Speed reduced by 10 feet"}]
                              if pick == "slow" else [{"type": "reaction_denied", "applies_to": "target", "duration": until, "evidence": "no Reactions"}])
        return  # "A creature makes this save only once per turn"


def _court_tax(engine: Any, actor: Any, target: Any, intent: Any) -> None:
    """Court Tax: "the first time during the turn it attempts to act directly against you ... takes Psychic damage equal to 2d10 + Wisdom
    modifier before resolving the action" (a printed cost may be paid instead)."""
    from . import needle

    held = next((c for c in actor.conditions.values() if c.condition_id == COURT), None)
    sovereign = engine.state.actors.get(held.source_actor_id or "") if held is not None else None
    if held is None or sovereign is None or target is None or target.entity_id != sovereign.entity_id or int((held.data or {}).get("turn") or -1) != int(actor.turns_started):
        return
    st.remove(engine, actor, held, "TAXED")
    action = engine.action_catalog.get(str(engine.events[-1].source_definition_id if engine.events else ""))
    costs = [(rid, amt) for rid, amt in (getattr(action, "costs", None) or ()) if actor.resources.get(rid, 0) >= 1]
    if costs:
        rid = costs[0][0]
        if needle.ask(engine, intent, needle.checkpoint_id(engine, "COURT_TAX", actor.entity_id), actor, "choice:needle.sovereign.court_tax",
                      ["pay"], labels={"pay": f"Pay 1 more {rid.rsplit('.', 1)[-1].replace('_', ' ')}"}, preferred=["pay"], allow_decline=True,
                      prompt=f"Court Tax ({sovereign.display_name}'s Hegemon's Domain)", name="Hegemon's Domain", feature_id=HEGEMON):
            engine._spend_resource(actor, rid, 1, HEGEMON)
            return
    _te().run_effects(_ctx(engine, sovereign, HEGEMON, [actor], intent),
                      [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 10}, "formula": "key_ability_modifier", "damage_types": ["psychic"],
                        "evidence": "it instead takes 2d10 + Wisdom modifier Psychic damage before the action resolves"}])


@hook("before_attack")
def court_tax_on_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    if attacker is not None and any(c.condition_id == COURT for c in attacker.conditions.values()):
        _court_tax(engine, attacker, defender, intent)
    return None


@hook("event")
def court_tax_on_technique(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "INTENT_ACCEPTED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None or not any(c.condition_id == COURT for c in actor.conditions.values()):
        return
    action = engine.action_catalog.get(str(engine.events[-1].source_definition_id if engine.events else ""))
    if action is None or str(getattr(action, "resolution_kind", "")) != "TYPED" or (action.parameters or {}).get("typed", {}).get("weapon"):
        return  # attacks are taxed before their roll
    for target_id in kwargs.get("target_ids") or ():
        _court_tax(engine, actor, engine.state.actors.get(target_id), engine._active_intent)


# ---------------------------------------------------------------------------------------------------------- buttons and gates
@hook("compile_actions")
def sovereign_buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned, out = info["owned_ids"], []

    def button(key: str, name: str, economy: Any, target: str, range_ft: int | None, rows: list[dict[str, Any]], text: str, source: str) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.sovereign.{key}", display_name=name, owner_id=info["actor_id"], economy=economy,
                                resolution_kind="TYPED", target_kind=target, range_ft=range_ft,
                                parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": source, "effects": rows},
                                            "expected_damage": 0, "sovereign": key, "description": text})

    if RETAINER in owned:
        out.append(button("retainer_move", "Move the Retainer", EconomyKind.NONE, "SELF", None,
                          [{"type": "sovereign_retainer", "applies_to": "self", "mode": "move", "picks_destination": True, "distance_ft": 120}],
                          "Retainer of the Empty Throne (free, once on each of your turns): the Retainer moves up to 30 feet.", RETAINER))
    if HEGEMON in owned and EDICT in owned:
        out.append(button("absolute_edict", "Edict of Heaven (Absolute Edict)", EconomyKind.ACTION, "SELF", None,
                          [{"type": "sovereign_edict", "applies_to": "self", "absolute": True}],
                          "Hegemon's Domain (once): Edict of Heaven without Resonance on creatures anywhere in the Domain; a failed target obeys until the end of its "
                          "next turn.", EDICT))
    return out or None


@hook("candidate_allowed")
def sovereign_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if _edict_blocks(engine, actor, candidate, action):
        return False
    if action is None:
        return None
    params = action.parameters or {}
    key = str(params.get("sovereign") or "")
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    feature = st.feature_of(action)
    if feature == VOICE and any(rid == MANDATE for rid, _ in (action.costs or ())):
        # Command the Marked: Commanding Voice on a creature Resonance Marked by you may spend 1 Mandate instead
        return None if st.row(engine, actor, "break_their_will") is not None and target is not None and _te().bears_mark(target, actor.entity_id, "Resonance") else False
    if feature == RETAINER and not key:
        return False if any(c.condition_id == RETAINER_GONE and c.source_actor_id == actor.entity_id for c in actor.conditions.values()) else None
    if key == "retainer_move":
        obj, spot = retainer_of(engine, actor), getattr(candidate, "destination", None)
        return None if obj is not None and not actor.turn_flags.get("retainer_moved") and (spot is None or engine.grid.distance_ft(obj.position, spot) <= 30) else False
    if key == "absolute_edict":
        held = _held(actor, HEGEMONY)
        return None if held is not None and _hegemony_zone(engine, actor) is not None and not st.data_of(actor, held).get("absolute_used") else False
    return None
