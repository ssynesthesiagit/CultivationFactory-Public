"""Warleader Shouts beyond Fierce Shout (sys-resources-states 2026-09-29; owner text: Tianxia Sphere Compendium, Warleader).

Every Shout is an Action row typed in authority/typed_mechanics/reviewed_final.d/sys_resources-states.json whose first effect is
{"type": "warleader_shout"} (combat/ext/warleader.py: the audience, a log line, the once-per-rest marker); what each Shout does to
its audience or to the hostile creatures in its area is this file's effects and hooks, or the ordinary typed ones.

Call Attention -- "Until the start of your next turn: affected allies gain Advantage on Dexterity (Stealth) checks; you automatically
  fail Dexterity (Stealth) checks; the first enemy that targets an affected ally other than you with an attack roll does so with
  Disadvantage if it can see or hear you." The Advantage is the ordinary typed check-mode effect. ``warleader_call_attention``
  puts a "leader" mark on the caster (``hide_check_override`` makes its Hide check a 0) and an "armed" mark that lists the affected
  allies; ``attack_mode`` turns the first attack a hostile creature that perceives the caster makes against one of them into a
  Disadvantage one and takes the armed mark off (it is the first enemy, once).
Frightful Roar -- Wisdom save; Frightened of you until the end of your next turn; "it must use its movement to move away from you by
  the safest available route if it can do so"; CL 11+, already Frightened and failing: 1 minute and a repeated save at the end of each
  of its turns. ``warleader_terror`` applies the condition through the ordinary condition block (so immunities and reactions still
  apply) and a "terror" mark that ``candidate_allowed`` reads: on its own turn the creature is offered only steps that end farther from
  the Shout's user, and may not end its turn (or hold still) while such a step is left. The table has no other flee rule.
Thunder Banner Cry -- typed with ordinary blocks (save, damage, push, Deafened with its repeated save, half damage on a success).
Darklands Cry -- ``warleader_exhaust``: one level of Exhaustion (combat/ext/forged_exhaustion.py) on a failed save, once per creature
  per leader ("once per long rest"; no long rest passes in a fight, so a mark stays for the fight).
Rallying Speech -- the ordinary typed Advantage against Charmed and Frightened for 1 minute; once per short rest per creature
  (the ``once`` mark of warleader.py).
Rousing Claxon -- Temporary HP equal to your Proficiency Bonus (ordinary block); ``warleader_claxon`` puts a condition on each
  affected ally for the fight ("for 1 hour") and ``save`` / ``attack_bonus`` / ``check_bonus`` / ``speed`` give back what one level of
  Exhaustion took (2 on a d20 Test, 5 feet of Speed) while the ally has a level. Exhaustion is never removed. Roaring Reservoir's own
  temporary level is not reduced ("cannot be reduced or ignored by Warleader talents").
Focusing Cry -- ``warleader_focusing_cry``: up to half your Proficiency Bonus (rounded up) affected allies, never yourself, that have
  no Martial Focus get one. The text leaves the choice to the leader; the table takes the nearest allies that lack Focus.
Harangue -- ``warleader_harangue``: each affected ally rolls one new saving throw against one ongoing effect that has a save (the one
  with the lowest DC) at its original DC; a success ends it; a failure changes nothing ("does not worsen"). Only allies that actually
  rolled are marked for the once-per-short-rest limit.
Roaring Reservoir -- ``compile_actions`` adds a copy of every Shout that costs Martial Focus without the cost; using it puts a level
  of Exhaustion on the leader until the end of its next turn (a condition; when it ends the level is taken off again).
Quick Commands (Shout half) -- a copy of every Shout as a Bonus Action that costs one extra Martial Focus.
War Drum Cadence -- after a Shout, a leader holding Martial Focus may expend it for an echo at the start of its next turn, without an
  Action: Temporary HP equal to your Proficiency Bonus, or +10 feet of Speed, or Advantage on the next save against Charmed or
  Frightened before the start of its next turn, for the allies (not the leader) the same shape reaches from where it then stands. A
  player is offered the three in turn (Use / Don't); the built-in AI takes the Temporary HP.
Recall Spirit and Unending Loyalty are not automated: a creature that died cannot be brought back (Gate 3's reducer has no
  ENTITY_REVIVED event, and it is a saved-fight lock file).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import forged_exhaustion, warleader as wl

BASE = "tianxia.talent.warleader."
FOCUS = wl.FOCUS
LEADER_MARK = "condition:typed.warleader_call_leader"
ARMED = "condition:typed.warleader_call_armed"
TERROR = "condition:typed.warleader_terror"
DARKLANDS = "condition:typed.warleader_darklands_spent"
CLAXON = "condition:typed.warleader_claxon"
RESERVOIR = "condition:typed.warleader_reservoir"
ECHO = "condition:typed.warleader_echo"
FRIGHTENED = "condition:typed.frightened"
ECHO_ASKS = (("temp_hp", "WAR_DRUM_TEMP_HP"), ("speed", "WAR_DRUM_SPEED"), ("advantage", "WAR_DRUM_ADVANTAGE"))
ECHO_TEXT = {"temp_hp": "Temporary HP equal to the leader's Proficiency Bonus", "speed": "+10 feet Speed until the end of the turn",
             "advantage": "Advantage on the next saving throw against Charmed or Frightened before the start of the leader's next turn"}


def _shout_row(action: Any) -> dict[str, Any] | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
    return next((row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "warleader_shout"), None)


def _held(actor: Any, condition_id: str) -> Any | None:
    return next((condition for condition in actor.conditions.values() if condition.condition_id == condition_id), None)


# ------------------------------------------------------------------------------------------------------ Call Attention
@effect("warleader_call_attention")
def call_attention(ctx: Any, eff: dict[str, Any]) -> None:
    engine, leader = ctx.engine, ctx.actor
    affected = [ally.entity_id for ally in wl.audience(ctx) if ally is not leader]
    expiry = "START_OF_SOURCE_NEXT_TURN"
    for condition_id in (LEADER_MARK, ARMED):
        engine._remove_condition(leader, condition_id, ctx.source)
    engine._apply_condition(leader, LEADER_MARK, ctx.source, leader.entity_id, expires_on=expiry,
                            data={"label": "Call Attention: automatically fails Stealth",
                                  "reading": "Automatically fails Dexterity (Stealth) checks until the start of its next turn."})
    engine._apply_condition(leader, ARMED, ctx.source, leader.entity_id, expires_on=expiry,
                            data={"affected": affected, "label": "Call Attention: draws the first attack",
                                  "reading": "The first enemy that can see or hear this creature and attacks one of the allies it called (other than "
                                             "itself) does so with Disadvantage. Used up by that attack."})


@hook("hide_check_override")
def call_attention_hide(engine: Any, actor: Any) -> int | None:
    return 0 if _held(actor, LEADER_MARK) is not None else None  # "you automatically fail Dexterity (Stealth) checks"


@hook("attack_mode")
def call_attention_disadvantage(ctx: Any, target: Any) -> str | None:
    engine, attacker = ctx.engine, ctx.actor
    for leader in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if leader.team_id == attacker.team_id or not leader.active or target.entity_id == leader.entity_id:
            continue
        armed = _held(leader, ARMED)
        if armed is None or target.entity_id not in (armed.data or {}).get("affected", ()):
            continue
        if not wl.perceives(engine, leader, attacker):  # "if it can see or hear you"
            continue
        engine._remove_condition(leader, ARMED, ctx.source)  # the first enemy, once
        note(engine, "warleader:call_attention", leader, f"{attacker.display_name} attacks {target.display_name} with Disadvantage "
                                                         f"({leader.display_name}'s Call Attention).", (attacker, target))
        return "DISADVANTAGE"
    return None


# ------------------------------------------------------------------------------------------------------ Frightful Roar
@effect("warleader_terror")
def terror(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te

    engine, leader, subject = ctx.engine, ctx.actor, ctx.target
    base = next((row for row in eff.get("effects") or [] if isinstance(row, dict) and row.get("type") == "condition"), None)
    if base is None or subject is None:
        return
    row = dict(base)
    if int(ctx.numbers.get("cl") or 1) >= 11 and _held(subject, FRIGHTENED) is not None:
        # "At CL 11+, a creature that is already Frightened and fails this save is Frightened for 1 minute instead. It repeats the save at
        # the end of each of its turns, ending the effect on itself on a success."
        row.update(duration="one_minute", repeat_save={"ability": "WIS", "when": "end"})
    te.block_condition(ctx, row)
    if not any(c.condition_id == FRIGHTENED and c.source_actor_id == leader.entity_id for c in subject.conditions.values()):
        return  # immune, or a reaction stopped it
    engine._remove_condition(subject, TERROR, ctx.source)
    engine._apply_condition(subject, TERROR, ctx.source, leader.entity_id, expires_on=te.effect_expiry(ctx, row, subject, condition=True) or "END_OF_HOLDER_NEXT_TURN",
                            data={"label": f"Frightful Roar: must flee {leader.display_name}",
                                  "reading": f"While Frightened by {leader.display_name}'s Roar this creature must use its movement to move away from "
                                             f"{leader.display_name} by the safest available route if it can."})
    note(engine, "warleader:frightful_roar", leader, f"{subject.display_name} is Frightened of {leader.display_name} and must flee"
                                                     + (" (1 minute, repeats the save each turn)." if row.get("repeat_save") else "."), (subject,))


def _fled(engine: Any, actor: Any, leader: Any, destination: Any) -> bool:
    return engine._distance_actor_to_actor(actor, leader, actor_position=destination) > engine._distance_actor_to_actor(actor, leader)


@hook("candidate_allowed")
def terror_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    mark = _held(actor, TERROR)
    if mark is None or engine.state.current_actor_id != actor.entity_id:
        return None
    leader = engine.state.actors.get(mark.source_actor_id)
    if leader is None or not leader.active or leader.entity_id == actor.entity_id:
        return None
    if not any(c.condition_id == FRIGHTENED and c.source_actor_id == leader.entity_id for c in actor.conditions.values()):
        return None  # the fear was ended (a repeated save, a rescue) before the mark ran out
    kind = getattr(candidate.kind, "value", candidate.kind)
    if kind == "MOVE":
        destination = getattr(candidate, "destination", None)
        return None if destination is None else _fled(engine, actor, leader, destination)
    if kind in ("END_TURN", "HOLD_POSITION", "TAKE_NO_OPTIONAL_ACTION") and actor.movement_remaining_ft > 0 and not getattr(engine, "_wl_probing", False):
        engine._wl_probing = True  # is there a step away left? (asks for the moves again, which the mark filters the same way)
        try:
            can_flee = any(getattr(other.kind, "value", other.kind) == "MOVE" for other in engine.legal_candidates())
        finally:
            engine._wl_probing = False
        return not can_flee
    return None


# ------------------------------------------------------------------------------------------------------ Darklands Cry
@effect("warleader_exhaust")
def darklands(ctx: Any, eff: dict[str, Any]) -> None:
    engine, leader, subject = ctx.engine, ctx.actor, ctx.target
    if subject is None or not subject.active:
        return
    if any(c.condition_id == DARKLANDS and c.source_actor_id == leader.entity_id for c in subject.conditions.values()):
        note(engine, "warleader:darklands_cry", leader, f"{subject.display_name} has already taken Exhaustion from {leader.display_name}'s "
                                                          "Darklands Cry (once per long rest).", (subject,))
        return
    engine._apply_condition(subject, DARKLANDS, ctx.source, leader.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Darklands Cry (Exhaustion taken)",
                                  "reading": f"Has gained a level of Exhaustion from {leader.display_name}'s Darklands Cry and cannot again until a long rest."})
    forged_exhaustion.add(engine, subject, 1, ctx.source)
    note(engine, "warleader:darklands_cry", leader, f"{subject.display_name} gains a level of Exhaustion (Darklands Cry).", (subject,))


# ------------------------------------------------------------------------------------------------------ Rousing Claxon
@effect("warleader_claxon")
def claxon(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te

    engine, leader = ctx.engine, ctx.actor
    for ally in wl.audience(ctx):
        engine._remove_condition(ally, CLAXON, ctx.source)
        engine._apply_condition(ally, CLAXON, ctx.source, leader.entity_id, expires_on=te.clock_expiry(engine, "one_hour") or "UNTIL_REMOVED",
                                data={"label": "Rousing Claxon: Exhaustion counts one lower",
                                      "reading": "For 1 hour treats its Exhaustion level as 1 lower (minimum 0). Does not remove Exhaustion."})
        if engine.state.current_actor_id == ally.entity_id and _relief(ally):
            ally.movement_remaining_ft += 5
    note(engine, "warleader:rousing_claxon", leader, f"{leader.display_name}'s Rousing Claxon: affected allies treat their Exhaustion as one level lower.")


def _relief(actor: Any) -> bool:
    """Whether Rousing Claxon takes a level off this creature's Exhaustion now: it has the condition and a level that is not Roaring
    Reservoir's own (which no Warleader talent can reduce)."""
    if _held(actor, CLAXON) is None:
        return False
    temporary = sum(int((c.data or {}).get("levels") or 0) for c in actor.conditions.values() if c.condition_id == RESERVOIR)
    return forged_exhaustion.level(actor) - temporary >= 1


@hook("save")
def claxon_save(ctx: Any, subject: Any, ability: str, named: set[str]) -> dict[str, Any] | None:
    return {"bonus": 2} if _relief(subject) else None


@hook("attack_bonus")
def claxon_attack(ctx: Any, actor: Any) -> int | None:
    return 2 if _relief(actor) else None


@hook("check_bonus")
def claxon_check(ctx: Any, actor: Any) -> int | None:
    return 2 if _relief(actor) else None


@hook("speed")
def claxon_speed(engine: Any, actor: Any) -> int | None:
    return 5 if _relief(actor) else None


# ------------------------------------------------------------------------------------------------------ Focusing Cry
@effect("warleader_focusing_cry")
def focusing_cry(ctx: Any, eff: dict[str, Any]) -> None:
    engine, leader = ctx.engine, ctx.actor
    count = (int(leader.proficiency_bonus) + 1) // 2  # "half your Proficiency Bonus, rounded up"
    lacking = [ally for ally in wl.audience(ctx) if ally is not leader and FOCUS in ally.resources and ally.resources.get(FOCUS, 0) < 1]
    chosen = sorted(lacking, key=lambda ally: (engine._distance_actor_to_actor(leader, ally), ally.entity_id))[:count]
    for ally in chosen:
        engine._gain_resource(ally, FOCUS, 1, ctx.source)
    note(engine, "warleader:focusing_cry", leader,
         f"{leader.display_name}'s Focusing Cry restores Martial Focus to " + (", ".join(ally.display_name for ally in chosen) if chosen else "no one (every affected ally holds Focus)") + ".",
         tuple(chosen))


# ------------------------------------------------------------------------------------------------------ Harangue
def _ongoing(ally: Any) -> list[tuple[str, Any]]:
    """The effects on this creature that a saving throw could end or resist, the easiest DC first."""
    from .repeat_saves import save_of as _save_of

    found = [(iid, c) for iid, c in ally.conditions.items() if c.condition_id.startswith("condition:typed.") and _save_of(c) is not None]
    return sorted(found, key=lambda pair: (int(_save_of(pair[1])["dc"]), pair[0]))


@effect("warleader_harangue")
def harangue(ctx: Any, eff: dict[str, Any]) -> None:
    from .repeat_saves import save_of as _save_of

    engine, leader = ctx.engine, ctx.actor
    for ally in wl.audience(ctx):
        ongoing = _ongoing(ally)
        if not ongoing:
            continue
        iid, condition = ongoing[0]
        save = _save_of(condition)
        dc = int(save["dc"])
        roll = engine._roll_save(ally, str(save["ability"]).upper(), dc, ctx.source)
        ended = roll.total >= dc and iid in ally.conditions
        if ended:
            ally.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=leader.entity_id, target_ids=(ally.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid, "harangue": True})
        engine._apply_condition(ally, wl.once_marker("harangue"), ctx.source, leader.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Harangue (used)", "reading": "Has benefited from Harangue and cannot again until a short rest."})
        label = str(condition.data.get("label") or condition.condition_id.rsplit(".", 1)[-1].replace("_", " ").title())
        note(engine, "warleader:harangue", leader, f"{ally.display_name} saves against {label} at DC {dc}: " + ("it ends." if ended else "it holds."), (ally,))


# ------------------------------------------------------------------------------------------------------ Roaring Reservoir, Quick Commands
def _clones(action: Any, *, reservoir: bool, quick: bool) -> Any | None:
    typed = (action.parameters or {}).get("typed") or {}
    costs = tuple(cost for cost in action.costs if not (reservoir and cost[0] == FOCUS))
    if reservoir and costs == tuple(action.costs):
        return None  # a Shout with no Focus cost has nothing to waive
    effects = list(typed.get("effects") or [])
    tag, label = [], []
    if reservoir:
        effects.append({"type": "warleader_reservoir", "applies_to": "self", "evidence": "Roaring Reservoir: no Martial Focus; Exhaustion +1 until the end of your next turn."})
        tag.append("reservoir")
        label.append("Roaring Reservoir")
    if quick:
        costs = (*costs, (FOCUS, 1))
        tag.append("quick")
        label.append("Bonus Action, 1 more Martial Focus")
    from ..gate2_runtime_models import EconomyKind

    return action.model_copy(update={
        "source_definition_id": action.source_definition_id + "".join(f"+{part}" for part in tag),
        "display_name": f"{action.display_name} ({', '.join(label)})", "costs": costs,
        "economy": EconomyKind.BONUS_ACTION if quick else action.economy,
        "parameters": {**action.parameters, "typed": {**typed, "effects": effects}}})


@hook("compile_actions")
def shout_variants(info: dict[str, Any]) -> list[Any] | None:
    reservoir, quick = BASE + "roaring_reservoir" in info["owned_ids"], BASE + "quick_commands" in info["owned_ids"]
    if not (reservoir or quick):
        return None
    shouts = [action for action in info["actions"] if _shout_row(action) is not None and "+" not in action.source_definition_id]
    made = []
    for action in shouts:
        for want_reservoir, want_quick in ((True, False), (False, True), (True, True)):
            if (want_reservoir and not reservoir) or (want_quick and not quick):
                continue
            clone = _clones(action, reservoir=want_reservoir, quick=want_quick)
            if clone is not None:
                made.append(clone)
    return (made + (wl.breath_support_shapes({**info, "actions": made}) or [])) or None


@effect("warleader_reservoir")
def reservoir(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te

    engine, leader = ctx.engine, ctx.actor
    expiry = te.effect_expiry(ctx, {"duration": "until_end_of_your_next_turn"}, leader, condition=True) or "END_OF_HOLDER_NEXT_TURN"
    engine._apply_condition(leader, RESERVOIR, ctx.source, leader.entity_id, expires_on=expiry,
                            data={"levels": 1, "label": "Roaring Reservoir: +1 Exhaustion",
                                  "reading": "One extra level of Exhaustion until the end of its next turn; no Warleader talent can reduce or ignore it."})
    forged_exhaustion.add(engine, leader, 1, ctx.source)
    note(engine, "warleader:roaring_reservoir", leader, f"{leader.display_name} shouts on Roaring Reservoir: +1 level of Exhaustion until the end of its next turn.")


@hook("event")
def reservoir_ends(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type != "CONDITION_REMOVED" or payload.get("condition_id") != RESERVOIR:
        return
    holder = engine.state.actors.get((kwargs.get("target_ids") or (None,))[0] or "")
    if holder is not None and holder.active:
        forged_exhaustion.add(engine, holder, -1, "warleader:roaring_reservoir")
        note(engine, "warleader:roaring_reservoir", holder, f"{holder.display_name}'s Roaring Reservoir Exhaustion ends.")


# ------------------------------------------------------------------------------------------------------ War Drum Cadence
@hook("technique_used")
def war_drum(ctx: Any) -> None:
    from .. import typed_reactions

    engine, leader = ctx.engine, ctx.actor
    if not any(isinstance(row, dict) and row.get("type") == "warleader_shout" for row in ctx.typed.get("effects") or []):
        return
    if not wl.knows(engine, leader, "war_drum_cadence") or leader.resources.get(FOCUS, 0) < 1 or _held(leader, ECHO) is not None:
        return
    row = {"feature_id": BASE + "war_drum_cadence", "ask": True}
    pick = next((kind for kind, checkpoint in ECHO_ASKS if typed_reactions._consent(engine, row, leader, checkpoint)), None)
    if pick is None:
        return
    engine._spend_resource(leader, FOCUS, 1, "warleader:war_drum_cadence")
    area, aim = wl.shout_area(ctx), ctx.typed.get("_area_aim")
    delta = [aim[0] - leader.position.x, aim[1] - leader.position.y] if aim else None
    engine._apply_condition(leader, ECHO, ctx.source, leader.entity_id, expires_on="UNTIL_REMOVED",
                            data={"echo": {"benefit": pick, "area": area, "aim_delta": delta},
                                  "label": "War Drum Cadence: echo at the start of your next turn",
                                  "reading": f"At the start of its next turn, without an Action, the Shout echoes to its allies: {ECHO_TEXT[pick]}."})
    note(engine, "warleader:war_drum_cadence", leader, f"{leader.display_name} spends Martial Focus: the Shout will echo at the start of its next turn ({ECHO_TEXT[pick]}).")


@hook("turn_start")
def war_drum_echo(engine: Any, actor: Any) -> None:
    from .. import typed_executor as te
    from types import SimpleNamespace

    pending = _held(actor, ECHO)
    if pending is None:
        return
    engine._remove_condition(actor, ECHO, "warleader:war_drum_cadence")
    if not actor.active:
        return
    echo = (pending.data or {}).get("echo") or {}
    delta = echo.get("aim_delta")
    # A Shout's remembered direction is a vector, not a landing square. Its end
    # can lie outside the battlefield after the leader moves; in_area needs only
    # x/y/z to test on-map allies. Do not build a validated Position for that
    # virtual end or clamp it (which would change the cone/line's direction).
    aim = SimpleNamespace(x=actor.position.x + int(delta[0]),
                          y=actor.position.y + int(delta[1]), z=0) if delta else None
    heard = [ally for ally in wl.audience_at(engine, actor, echo.get("area") or {"shape": "emanation", "size_ft": 15}, aim) if ally is not actor]
    pb, kind = int(actor.proficiency_bonus), echo.get("benefit")
    for ally in heard:
        if kind == "temp_hp":
            engine._grant_temp_hp(ally, pb, "warleader:war_drum_cadence", actor.entity_id)
        elif kind == "speed":
            ally.movement_remaining_ft += 10
        elif kind == "advantage":
            engine._apply_condition(ally, "condition:typed.save_against", "warleader:war_drum_cadence", actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"rule": {"save_against": {"mode": "ADVANTAGE", "against": te._save_against_keys("saving throws against charmed and frightened"),
                                                                    "abilities": [], "next": True}},
                                          "label": "Advantage on the next save against Charmed or Frightened (War Drum Cadence)"})
    note(engine, "warleader:war_drum_cadence", actor, f"War Drum Cadence echoes: {ECHO_TEXT.get(kind, 'nothing')} for "
                                                      + (", ".join(ally.display_name for ally in heard) or "no allies in reach") + ".", tuple(heard))


# ------------------------------------------------------------------------------------------------------ the built-in AI
@hook("ai_candidate_allowed")
def shout_restraint(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The built-in AI never ends a turn with an Action to spare (fight audit 2026-09-29), so it is kept from Shouts that would do nothing
    (a player's menu keeps them) and from the costlier copies while the plain one can be used."""
    row = _shout_row(action)
    if row is None:
        return None
    sid = action.source_definition_id
    if "+reservoir" in sid:  # the Exhaustion is only worth it when the Focus is not there for the plain Shout
        needed = 1 + sum(int(cost[1]) for cost in action.costs if cost[0] == FOCUS)
        if _held(actor, RESERVOIR) is not None or actor.resources.get(FOCUS, 0) >= needed:
            return False
    if "+quick" in sid and actor.action_available:
        return False
    slug, area = row.get("shout"), (((action.parameters or {}).get("typed") or {}).get("area") or {"shape": "emanation", "size_ft": 15})
    once = row.get("once") or row.get("once_only")
    heard = wl.audience_at(engine, actor, area, getattr(candidate, "destination", None), once)
    others = [ally for ally in heard if ally is not actor]
    if slug == "call_attention" and _held(actor, ARMED) is not None:
        return False
    if once and not heard:
        return False
    if slug == "harangue" and not any(_ongoing(ally) for ally in heard):
        return False
    if slug == "focusing_cry" and not any(FOCUS in ally.resources and ally.resources.get(FOCUS, 0) < 1 for ally in others):
        return False
    return None
