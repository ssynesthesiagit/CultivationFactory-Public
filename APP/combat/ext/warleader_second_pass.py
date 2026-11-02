"""Printed Command the Gap and combat portions of three Warleader Insights.

Shared API (warleader consumes these): standard_set(ctx, data) seals a chosen
Standard-Bearer recipient; fulfilled(engine, leader, subject, standard) consumes
that grant on a primary Standard benefit; voice_audience(ctx, found, aim, once)
limits the hearing exception to one visible ally. Choices use warleader.choose;
automatic options are filtered by allegiance and perception before selection.
Build ability-score increases and prerequisites remain sheet responsibilities.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook, note, warleader as wl
from .passive_rows import row_of

BLOCK = "warleader_second_pass"
GAP = wl.BASE_TALENT + "command_the_gap"
BEARER = "insight.standard-bearer-adept"
VOICE = "insight.voice-that-carries"
GRANT = "condition:typed.warleader_bearer"


def owns(engine: Any, actor: Any, feature: str) -> bool:
    return row_of(engine, actor.entity_id, BLOCK, feature) is not None


@hook("compile_block")
def compile_feature(block: str, spec: dict, row: dict, numbers: dict) -> list[dict] | None:
    if block != BLOCK:
        return None
    outcomes = {
        BEARER: "Once per round when you set a Standard, choose one Commanded ally to gain Temporary HP equal to your Proficiency Bonus. Fulfilling that Standard before your next turn grants one Momentum Mark, within the normal Momentum limits.",
        VOICE: "Your Shouts have five feet more radius. Choose one ally who cannot hear the Shout but can see you to receive its beneficial effects.",
        GAP: "Spend one Momentum Mark when an enemy moves within the reach of two Commanded allies: one ally may make an Opportunity Attack without using a Reaction, once per provoking creature each turn.",
        "insight.iron-captain": "Once per combat scene, spend one Momentum Mark to turn a critical hit against a Commanded ally beside another Commanded ally into a normal hit. This costs no Action or Reaction.",
    }
    return [{**row, "kind": row["feature_id"], "trigger_owner": BLOCK,
             "player_outcome": outcomes[row["feature_id"]]}]


@effect(BLOCK)
def declaration(ctx: Any, eff: dict) -> None:
    """Passive declaration; runtime ownership comes from the sealed feature row."""


def pick(engine: Any, leader: Any, intent: Any, feature: str, tag: str, creatures: list[Any], prompt: str) -> Any | None:
    if not creatures:
        return None
    # AI cannot choose an unseen creature just because the state contains it.
    from ..senses import perceives
    if wl.table_driven(engine, leader):
        perceived = {c.entity_id for c in creatures if perceives(engine, leader, c)}
        creatures = [c for c in creatures if c.entity_id == leader.entity_id or c.entity_id in perceived]
    if not creatures:
        return None
    creatures = sorted(creatures, key=lambda c: (engine._distance_actor_to_actor(leader, c), c.entity_id))
    asked, chosen = wl.choose(engine, leader, intent, tag, wl.CHOICE + tag.lower(),
                              [c.entity_id for c in creatures], labels={c.entity_id: c.display_name for c in creatures},
                              prompt=prompt, name=prompt, feature_id=feature)
    return next((c for c in creatures if c.entity_id == chosen), None) if asked else creatures[0]


def standard_set(ctx: Any, data: dict) -> None:
    engine, leader = ctx.engine, ctx.actor
    key = "once_per_round:wl_bearer"
    if not owns(engine, leader, BEARER) or leader.turn_flags.get(key) == engine.state.round_number:
        return
    allies = [c for c in engine.state.actors.values() if wl.commanded(engine, leader, data, c)]
    ally = pick(engine, leader, ctx.intent, BEARER, "WARLEADER_STANDARD_BEARER", allies,
                "Standard-Bearer Adept: choose one Commanded ally to gain Temporary HP")
    if ally is None:
        return
    leader.turn_flags[key] = engine.state.round_number
    # One outstanding selection per leader. Each leader's expiry is independent.
    for creature in engine.state.actors.values():
        for condition in list(creature.conditions.values()):
            if condition.condition_id.startswith(GRANT + ":") and condition.source_actor_id == leader.entity_id:
                engine._remove_condition(creature, condition.condition_id, BEARER)
    engine._grant_temp_hp(ally, wl.proficiency(leader), BEARER, leader.entity_id)
    engine._apply_condition(ally, GRANT + ":" + leader.entity_id, BEARER, leader.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"standard": data["standard"], "label": "Standard-Bearer Adept",
                                  "reading": "Fulfilling the chosen Standard grants the leader one Momentum Mark before its next turn."})


def fulfilled(engine: Any, leader: Any, subject: Any, standard: str) -> None:
    grant = next((c for c in subject.conditions.values() if c.condition_id.startswith(GRANT + ":")
                  and c.source_actor_id == leader.entity_id and c.data.get("standard") == standard), None)
    if grant is None:
        return
    engine._remove_condition(subject, grant.condition_id, BEARER)
    wl.gain_momentum(engine, leader, subject, "Standard-Bearer Adept: fulfilled the Standard")


@hook("compile_action")
def voice_radius(action: Any, info: dict) -> Any | None:
    typed = (action.parameters or {}).get("typed") or {}
    if VOICE not in info["owned_ids"] or not any(e.get("type") == "warleader_shout" for e in typed.get("effects") or [] if isinstance(e, dict)):
        return None
    area = dict(typed.get("area") or {})
    # Only the emanation has a radius; Breath Support's cone/line lengths stay printed.
    if area.get("shape") != "emanation":
        return None
    area["size_ft"] = int(area.get("size_ft") or 15) + 5
    return action.model_copy(update={"parameters": {**action.parameters, "typed": {**typed, "area": area}}})


def voice_audience(ctx: Any, found: list[Any], aim: Any, once: str | None) -> list[Any]:
    from ..typed_executor import cant_hear, in_area
    from ..target_knowledge import can_see
    from ..targeting import line_of_effect
    engine, leader = ctx.engine, ctx.actor
    if not owns(engine, leader, VOICE):
        return found
    # The extension grants only the beneficial portion. Harmful enemy targeting
    # remains the native Shout delivery and never consumes this ally selection.
    heard = [c for c in found if not cant_hear(c)]
    if any(e.get("type") == "warleader_shout" and e.get("hostile") for e in ctx.typed.get("effects") or [] if isinstance(e, dict)):
        return heard
    area = wl.shout_area(ctx)
    options = [c for c in engine.state.actors.values() if c.active and c.team_id == leader.team_id
               and cant_hear(c) and not (once and wl.has_benefited(c, once))
               and can_see(engine, c, leader) and line_of_effect(engine, leader, target=c)
               and (in_area(engine, leader.position, aim or leader.position, c.position, area)
                    if area.get("shape") in ("cone", "line") else engine._distance_actor_to_actor(leader, c) <= int(area.get("size_ft") or 15))]
    ally = pick(engine, leader, ctx.intent, VOICE, "WARLEADER_VOICE", options,
                "Voice That Carries: choose one ally who can see you to receive the Shout's benefits")
    return [*heard, ally] if ally is not None and ally not in heard else heard


@hook("movement_step")
def command_gap(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict | None:
    from .. import typed_reactions as tr
    from ..typed_executor import condition_rules
    from ..movement_steps import context
    from ..movement_steps import opportunity_exempt
    from ..senses import perceives
    from ..targeting import line_of_effect

    if not mover.active or context(engine, mover).get("forced"):
        return None
    token = f"{engine.state.round_number}:{engine.state.current_slot_index}:{engine.state.current_actor_id}"
    key = "typed_round_wl_gap_provoked"
    if mover.turn_flags.get(key) == token:
        return None
    for leader, data in sorted(wl.leaders(engine), key=lambda pair: pair[0].entity_id):
        if leader.team_id == mover.team_id or not owns(engine, leader, GAP) or leader.resources.get(wl.MOMENTUM, 0) < 1:
            continue
        if wl.table_driven(engine, leader) and not perceives(engine, leader, mover):
            continue
        allies = []
        for ally in engine.state.actors.values():
            if not wl.commanded(engine, leader, data, ally) or any(r.get("no_actions") for r in condition_rules(ally)):
                continue
            reach = tr.physical_melee_reach(engine, ally)
            if reach is None:
                continue
            if engine._distance_actor_to_actor(ally, mover) <= reach and line_of_effect(engine, ally, target=mover):
                allies.append(ally)
        if len(allies) < 2:
            continue
        # A granted free strike still obeys the movement step's per-attacker
        # waivers (Disengage, free-distance and named-attacker exemptions).
        eligible = [a for a in allies if not opportunity_exempt(engine, mover, a.entity_id)
                    and tr.wants_opportunity_attack(engine, a, mover, ask=False, uses_reaction=False)]
        ally = pick(engine, leader, intent, GAP, "WARLEADER_COMMAND_GAP", eligible,
                    f"Command the Gap: spend 1 Momentum Mark for an Opportunity Attack against {mover.display_name}")
        if ally is None:
            continue
        consent_display = {
            "display_name": "Command the Gap",
            "display_trigger": (f"{mover.display_name} moved within the reaches of {ally.display_name} "
                                "and another ally ordered by the Standard"),
            "display_summary": (f"Command the Gap lets you make one melee attack against {mover.display_name}. "
                                "Your leader spends 1 Momentum Mark; you do not spend a Reaction."),
            "display_cost": "No Reaction cost to the attacker; the leader spends 1 Momentum Mark",
            "display_uses_reaction": False,
            "display_rules": (f"Command the Gap lets you make one melee attack against {mover.display_name}. "
                              "Your leader spends 1 Momentum Mark; you do not spend a Reaction."),
        }
        if not tr.wants_opportunity_attack(engine, ally, mover, uses_reaction=False,
                                           consent_display=consent_display):
            continue
        mover.turn_flags[key] = token
        wl.spend_momentum(engine, leader, GAP)
        note(engine, GAP, leader, f"Command the Gap: {ally.display_name} attacks {mover.display_name} without using a Reaction.", (ally, mover))
        tr.opportunity_attack(engine, ally, mover, intent, uses_reaction=False)
        if not mover.active:
            return {"stop": True, "source_id": GAP, "label": "Command the Gap"}
        break
    return None


CAPTAIN = "insight.iron-captain"


@hook("critical_cancel")
def iron_captain(engine, attacker, target, spec, roll, intent):
    from .needle import ask
    from ..target_knowledge import can_see

    for leader, data in sorted(wl.leaders(engine), key=lambda pair: pair[0].entity_id):
        if not owns(engine, leader, CAPTAIN):
            continue
        if not wl.commanded(engine, leader, data, target) or not wl.adjacent_commanded(engine, leader, data, target):
            continue
        if leader.resources.get(wl.MOMENTUM, 0) < 1 or any(
                event.event_type == "PASSIVE_TRIGGERED" and event.actor_id == leader.entity_id
                and event.payload.get("feature_id") == CAPTAIN and event.payload.get("critical_turned_normal")
                for event in engine.events):
            continue
        if wl.table_driven(engine, leader) and not (can_see(engine, leader, attacker) and can_see(engine, leader, target)):
            continue
        selected = ask(engine, intent, f"IRON_CAPTAIN:{roll.roll_id}:{leader.entity_id}", leader,
            "choice:warleader.iron_captain", ["protect"], labels={"protect": "Spend 1 Momentum Mark; make this a normal hit"},
            prompt=f"{attacker.display_name}'s {spec.get('attack_name') or 'attack'} critically hits {target.display_name}, "
                   "beside another ally following your Standard. Spend 1 Momentum Mark to make it a normal hit before damage? "
                   "Iron Captain can be used once during this combat scene; it costs no Action or Reaction.",
            name="Iron Captain", feature_id=CAPTAIN, minimum=1, maximum=1, allow_decline=True,
            automatic=True, default="all", target_id=target.entity_id,
            prompt_context={"cost": "1 Momentum Mark; no Action or Reaction"})
        if not selected:
            continue
        if not wl.spend_momentum(engine, leader, CAPTAIN):
            continue
        engine._append_event("PASSIVE_TRIGGERED", CAPTAIN, actor_id=leader.entity_id,
            target_ids=(target.entity_id,), payload={"feature_id": CAPTAIN, "critical_turned_normal": True,
            "roll_id": roll.roll_id, "log": f"{leader.display_name} spends 1 Momentum Mark: Iron Captain turns "
                                           f"the critical hit against {target.display_name} into a normal hit."})
        return True
    return None
