"""Thousand-Eyed Calamity Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Thousand-Eyed Calamity Body (Open Eyes, Too Many Open Eyes, the five features and their
Normalized Procedures). Owned rows: ``{"type": "path_passive", "kind": "calamity", "role": "appraisal" | "hundred" | "killing_line"}``;
Thousand-Eyed Revelation is the named state "thousand_eyed_revelation"; Eye beneath the Skin's Reaction runs ``eye_beneath``,
Hundred Eyes Open's runs ``hundred_eyes_answer``.

Open Eyes           at the start of your turn (asked, 0 to PB, the last number preferred) — every Eye while the Revelation lasts,
                    none while Too Many Open Eyes locks them. 3+: a creature gets no Advantage against you merely from being
                    unseen; 4+: Blindsight 20 feet (40 with Hundred Eyes Open); 6+: Truesight 30 feet. Unconscious closes them.
Too Many Open Eyes  failing a save against Blinded with 3+ Eyes open: 2d8 Psychic per Eye beyond the second, every Eye closes,
                    none opens until the end of your next turn.
Calamity Appraisal  at the start of your turn (asked) one creature within 60 feet is Appraised (a typed mark,
                    ``condition:typed.mark.appraised_target.<you>``) until the start of your next turn; the log reads out its AC, its
                    highest and lowest Strength/Dexterity/Constitution save and whether it is above half its Hit Points; once
                    per turn on a hit against it + PB. One Appraised creature (PB during the Revelation).
Eye beneath the Skin  the Reaction (1 Stamina, once per round) as an attack against you would hit: + PB AC against that attack
                    only; if it then misses, the attacker is Appraised until the end of your next turn, you may move 5 feet
                    without provoking, and it gets no Advantage from being unseen against you until your next turn ends.
Read the Killing Line  once per turn after a hit on an Appraised creature (asked; 1 Stamina, or none once a turn during the
                    Revelation): Piercing Appraisal (+ 2d8 of the hit's type or Force) or Denied Escape (no Reactions until the
                    start of its next turn). Exposed Meridian shares that use: after your Body Refining feature rolls its
                    identified lowest physical save, subtract 1d4 and recheck the DC through d20_rewrite's signed save bonus.
Hundred Eyes Open   (4+ Eyes) its Reaction when your Appraised creature moves, attacks or uses a technique within 60 feet
                    (1 Stamina, once per round): move 15 feet, an unarmed strike if it is in reach, Disadvantage on its next
                    attack roll, or + PB on your next save this turn (asked).
Thousand-Eyed Revelation  the state: every Eye open, attack rolls against you get no Advantage from the conditions that would
                    give it, PB Appraised creatures, the exact Strength/Dexterity/Constitution save bonuses in the log, once per
                    turn + 4d8 Psychic or Force on a hit against an Appraised creature; Calamity Gaze (Action while it lasts,
                    3 Stamina, 60-foot cone, Wisdom save: 8d8 Psychic, Appraised for the state's duration, cannot hide its
                    Invisibility from you, no Reactions until the start of its next turn; or half and Appraised until the start
                    of your next turn).
Every hook returns early for a creature without these rows or state.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.thousand_eyed_calamity_body.feature."
REVELATION = "thousand_eyed_revelation"
EYES = "_round_open_eyes"          # {"count": n, "locked_until": turn number or 0}; "_round_" keys survive the turn reset
SENSE_SOURCE = PREFIX + "open_eyes"
STAMINA = "resource:core.stamina"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "calamity"}


def _revelation(engine: Any, actor: Any) -> Any:
    from .states import active

    return active(engine, actor, REVELATION) if actor is not None else None


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def eyes(actor: Any) -> int:
    return int((actor.turn_flags.get(EYES) or {}).get("count") or 0)


def _mark_id(owner: Any) -> str:
    from ..typed_executor import mark_condition_id

    return mark_condition_id("Appraised Target", owner.entity_id)  # the name the Hundred Eyes Open reading requires


def appraised_by(target: Any, owner: Any) -> bool:
    return target is not None and any(c.condition_id == _mark_id(owner) for c in target.conditions.values())


# ------------------------------------------------------------------------------------------------------------ Open Eyes
def _set_eyes(engine: Any, actor: Any, count: int) -> None:
    record = dict(actor.turn_flags.get(EYES) or {})
    record["count"] = max(0, int(count))
    actor.turn_flags[EYES] = record
    from ..senses import SENSE

    for iid, held in list(actor.conditions.items()):
        if held.condition_id == SENSE and held.source_definition_id == SENSE_SOURCE:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", SENSE_SOURCE, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": SENSE, "instance_id": iid, "reason": "EYES"})
    senses = []
    if count >= 4:
        senses.append(("blindsight", 40 if "hundred" in _roles(engine, actor) else 20))
    if count >= 6:
        senses.append(("truesight", 30))
    for sense, feet in senses:
        engine._apply_condition(actor, SENSE, SENSE_SOURCE, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"sense": sense, "range_ft": feet, "label": f"Open Eyes: {sense.title()} {feet} ft"})


def _choose_eyes(engine: Any, actor: Any, intent: Any) -> None:
    from .needle import ask, checkpoint_id

    record = actor.turn_flags.get(EYES) or {}
    most = int(actor.proficiency_bonus or 2)
    if int(record.get("locked_until") or 0) >= int(actor.turns_started):
        _set_eyes(engine, actor, 0)  # "cannot open another until the end of your next turn"
        return
    if _revelation(engine, actor) is not None:
        _set_eyes(engine, actor, most)  # "All Eyes open"
        return
    options = [str(n) for n in range(most + 1)]
    benefit = {0: "closed", 1: "cannot be Surprised", 2: "+ Advantage on sight Perception", 3: "+ no Advantage from being unseen",
               4: "+ Blindsight", 5: "+ see the Invisible (GM)", 6: "+ Truesight 30 ft"}
    labels = {o: f"{o} Eyes ({benefit[min(int(o), 6)]})" for o in options}
    picked = ask(engine, intent, checkpoint_id(engine, "open_eyes", actor.entity_id), actor, "choice:needle.open_eyes", options, labels=labels,
                 preferred=[str(min(most, eyes(actor)))] if actor.turn_flags.get(EYES) else [str(most)], target_id=actor.entity_id,
                 name="Open Eyes", prompt="Open Eyes: how many Eyes are open this turn? (3 or more risk Too Many Open Eyes when Blinded)")
    _set_eyes(engine, actor, int(picked[0]) if picked and picked[0] in options else (eyes(actor) if actor.turn_flags.get(EYES) else most))


@hook("after_save_resolved")
def too_many_open_eyes(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Failing a save against Blinded with 3 or more Eyes open: 2d8 Psychic per Eye beyond the second, all close, a lockout."""
    if not failed or subject is None or "appraisal" not in _roles(ctx.engine, subject) or "blinded" not in {str(n).lower() for n in named or ()}:
        return
    count = eyes(subject)
    if count < 3:
        return
    from ..gate2_runtime_models import DiceSpec

    engine = ctx.engine
    roll = engine.roller.roll(DiceSpec(count=2 * (count - 2), sides=8, modifier=0), actor_id=subject.entity_id, reason=f"DAMAGE:{PREFIX}too_many_open_eyes")
    engine._record_roll(roll)
    _set_eyes(engine, subject, 0)
    subject.turn_flags[EYES] = {**(subject.turn_flags.get(EYES) or {}), "locked_until": int(subject.turns_started) + 1}
    note(engine, PREFIX + "too_many_open_eyes", subject, f"Too Many Open Eyes: {subject.display_name}'s Eyes burn shut.", (subject.entity_id,))
    before = subject.current_hp  # one unavoidable backlash packet: nothing reduces it
    subject.current_hp = max(0, before - int(roll.total))
    engine._append_event("DAMAGE_COMMITTED", PREFIX + "too_many_open_eyes", actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                         payload={"rolled_or_pending_damage": int(roll.total), "reduced_to": int(roll.total), "temporary_hp_absorbed": 0,
                                  "hp_damage": before - subject.current_hp, "damage_type": "PSYCHIC", "remaining_hp": subject.current_hp, "gate_damage": True})
    if subject.current_hp == 0:
        engine._defeat(subject, PREFIX + "too_many_open_eyes")
        engine._check_victory()


@hook("event")
def eyes_close_when_unconscious(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED" or not str((kwargs.get("payload") or {}).get("condition_id") or "").endswith("unconscious"):
        return
    actor = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    if actor is not None and eyes(actor):
        _set_eyes(engine, actor, 0)


def _advantage_rule(held: Any, *, attacker_side: bool, within_5: bool) -> bool:
    from ..typed_executor import CONDITION_PREFIX, is_active_typed_condition, rules

    if not is_active_typed_condition(held):
        return False

    name = held.condition_id[len(CONDITION_PREFIX):] if held.condition_id.startswith(CONDITION_PREFIX) else ""
    row = {**(rules()["conditions"].get(name) or {}), **((held.data or {}).get("rule") or {})}
    if attacker_side:
        return row.get("attacks_have") == "ADVANTAGE"
    return row.get("attacked_with") == "ADVANTAGE" or (within_5 and row.get("attacked_within_5ft") == "ADVANTAGE")


@hook("masked_conditions")
def unseen_gives_no_advantage(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    # The engine's square probe (senses.perceives_cell) is not a creature: it has no team, no Eyes and no
    # Appraised mark, so it can never be the unseen attacker or the unseen target this rule is about. Ask
    # first, before any attribute of a full creature is read (MMX105, live log flood on round 24).
    from ..senses import is_creature

    if not is_creature(attacker) or not is_creature(target):
        return None
    if attacker.team_id == target.team_id:
        return None
    out: dict[str, set[str]] = {}
    from ..senses import rules as sense_rules

    hidden = set(sense_rules().get("hidden_conditions") or [])
    watch = target.turn_flags.get("_round_eye_beneath_unseen") or {}
    if eyes(target) >= 3 or attacker.entity_id in (watch.get("ids") or []):  # "do not gain Advantage merely by being unseen"
        out[attacker.entity_id] = {iid for iid, held in attacker.conditions.items() if held.condition_id in hidden}
    if _revelation(engine, target) is not None:  # "Attack rolls against you cannot gain Advantage"
        near = engine._distance_actor_to_actor(attacker, target) <= 5
        out.setdefault(attacker.entity_id, set()).update(iid for iid, held in attacker.conditions.items() if _advantage_rule(held, attacker_side=True, within_5=near))
        out[target.entity_id] = {iid for iid, held in target.conditions.items() if _advantage_rule(held, attacker_side=False, within_5=near)}
    for who, viewer in ((target, attacker), (attacker, target)):  # Calamity Gaze: "cannot become Invisible to you"
        if _gazed_by(who, viewer):
            out.setdefault(who.entity_id, set()).update(iid for iid, held in who.conditions.items() if held.condition_id == "condition:typed.invisible")
    return {k: v for k, v in out.items() if v} or None


def _gazed_by(creature: Any, owner: Any) -> bool:
    return any(held.condition_id == _mark_id(owner) and (held.data or {}).get("gazed") for held in creature.conditions.values())


# ------------------------------------------------------------------------------------------------- Calamity Appraisal
def _save_bands(target: Any) -> tuple[list[str], list[str]]:
    saves = {k: int((target.saving_throws or {}).get(k, 0)) for k in ("STR", "DEX", "CON")}
    hi, lo = max(saves.values()), min(saves.values())
    return [k for k, v in saves.items() if v == hi], [k for k, v in saves.items() if v == lo]


def appraise(engine: Any, owner: Any, target: Any, source: str, *, expires_on: str, gazed: bool = False) -> None:
    """Mark ``target`` Appraised by ``owner`` (replacing the oldest past the limit) and read it out."""
    limit = int(owner.proficiency_bonus or 2) if _revelation(engine, owner) is not None else 1
    mark = _mark_id(owner)
    held = sorted(((c, iid, h) for c in engine.state.actors.values() for iid, h in c.conditions.items() if h.condition_id == mark and c.entity_id != target.entity_id),
                  key=lambda row: str(row[1]))
    for creature, iid, _h in held[: max(0, len(held) - limit + 1)]:
        del creature.conditions[iid]
        engine._append_event("CONDITION_REMOVED", source, actor_id=owner.entity_id, target_ids=(creature.entity_id,),
                             payload={"condition_id": mark, "instance_id": iid, "reason": "REPLACED"})
    for iid, h in list(target.conditions.items()):
        if h.condition_id == mark:
            del target.conditions[iid]
    engine._apply_condition(target, mark, source, owner.entity_id, expires_on=expires_on,
                            data={"label": f"Appraised by {owner.display_name}", "gazed": gazed})
    high, low = _save_bands(target)
    exact = (" Saves: " + ", ".join(f"{k} {int((target.saving_throws or {}).get(k, 0)):+d}" for k in ("STR", "DEX", "CON"))) if _revelation(engine, owner) else ""
    band = "above" if target.current_hp * 2 > target.maximum_hp else "at or below"
    note(engine, source, owner, f"Calamity Appraisal: {target.display_name} — AC {target.armor_class}; highest physical save {'/'.join(high)}, lowest "
         f"{'/'.join(low)}; {band} half its Hit Points.{exact}", (target.entity_id,))


@hook("turn_start_choice")
def open_eyes_and_appraise(engine: Any, actor: Any) -> None:
    roles = _roles(engine, actor)
    if "appraisal" not in roles or not actor.active:
        return
    from .needle import ask, checkpoint_id

    intent = _intent(engine)
    _choose_eyes(engine, actor, intent)
    foes = {c.entity_id: c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.entity_id != actor.entity_id
            and engine._distance_actor_to_actor(actor, c) <= 60 and engine._line_of_sight_actor_to_actor(actor, c)}
    if not foes:
        return
    order = sorted(foes, key=lambda k: (foes[k].team_id == actor.team_id, engine._distance_actor_to_actor(actor, foes[k]), k))
    picked = ask(engine, intent, checkpoint_id(engine, "calamity_appraisal", actor.entity_id), actor, "choice:needle.calamity_appraisal", order,
                 labels={k: foes[k].display_name for k in order}, allow_decline=True, preferred=order[:1], target_id=actor.entity_id,
                 name="Calamity Appraisal", prompt="Calamity Appraisal: which creature within 60 feet do you Appraise until your next turn?")
    if picked and picked[0] in foes:
        appraise(engine, actor, foes[picked[0]], PREFIX + "calamity_appraisal", expires_on="START_OF_SOURCE_NEXT_TURN")


@hook("after_hit")
def appraised_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or not appraised_by(target, actor):
        return
    roles = _roles(engine, actor)
    from .. import typed_executor as te

    weapon = ctx.typed.get("weapon") or {}
    kinds = [str(k).lower() for k in (weapon.get("damage_types") or [weapon.get("damage_type") or "force"])]
    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    stamp = _stamp(engine)
    if "appraisal" in roles and actor.turn_flags.get("_round_appraisal_hit") != stamp:
        actor.turn_flags["_round_appraisal_hit"] = stamp
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": int(actor.proficiency_bonus or 2), "damage_types": [*kinds, "force"],
                              "evidence": "Calamity Appraisal: + Proficiency Bonus"}])
    if _revelation(engine, actor) is not None and target.active and actor.turn_flags.get("_round_revelation_hit") != stamp:
        actor.turn_flags["_round_revelation_hit"] = stamp
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": ["psychic", "force"],
                              "evidence": "Thousand-Eyed Revelation: + 4d8"}])
    if "killing_line" in roles and target.active and actor.turn_flags.get("_round_killing_line") != stamp:
        _killing_line(ctx, sub, target, kinds)


def _killing_line(ctx: Any, sub: Any, target: Any, kinds: list[str]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    free = _revelation(engine, actor) is not None and actor.turn_flags.get("_round_killing_line_free") != _stamp(engine)
    if not free and int(actor.resources.get(STAMINA, 0) or 0) < 1:
        return
    labels = {"piercing": "Piercing Appraisal: + 2d8", "denied": "Denied Escape: no Reactions until the start of its next turn"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "killing_line", target.entity_id), actor, "choice:needle.read_the_killing_line", list(labels),
                 labels=labels, allow_decline=True, default="decline", target_id=target.entity_id, name="Read the Killing Line",
                 prompt=f"Read the Killing Line: {ctx.action.display_name} hit the Appraised {target.display_name}"
                        f"{' (no Stamina this turn)' if free else ' (1 Stamina)'}. Choose one, or decline.")
    if not picked or picked[0] not in labels:
        return
    actor.turn_flags["_round_killing_line"] = _stamp(engine)
    if free:
        actor.turn_flags["_round_killing_line_free"] = _stamp(engine)
    else:
        engine._spend_resource(actor, STAMINA, 1, PREFIX + "read_the_killing_line")
    if picked[0] == "piercing":
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": [*kinds, "force"],
                              "evidence": "Read the Killing Line: Piercing Appraisal + 2d8"}])
    else:
        te.run_effects(sub, [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])


def exposed_meridian_guard(engine: Any, holder: Any, rc: Any) -> bool:
    """Read the Killing Line's save option shares the hit options' turn limit."""
    from .spirit_traditions import feature_of

    actor, target = holder.actor, rc.roller
    action = engine.action_catalog.get(rc.source_id)
    mechanic = feature_of(action) if action is not None else ""
    physical = ("STR", "DEX", "CON")
    return (rc.source_actor is actor and appraised_by(target, actor)
            and mechanic.startswith(("tianxia.path.body_refining.", "tianxia.subpath.body."))
            and rc.ability in physical
            and target.saving_throws.get(rc.ability, 0) == min(target.saving_throws.get(a, 0) for a in physical)
            and actor.turn_flags.get("_round_killing_line") != _stamp(engine))


def exposed_meridian_ai(engine: Any, holder: Any, rc: Any) -> bool:
    """Conserve the shared use unless subtracting 1d4 could turn success into failure."""
    return rc.dc is not None and rc.dc <= rc.total < rc.dc + 4


def exposed_meridian_penalty(engine: Any, holder: Any, rc: Any) -> int:
    from ..gate2_runtime_models import DiceSpec

    holder.actor.turn_flags["_round_killing_line"] = _stamp(engine)
    if _revelation(engine, holder.actor) is not None:
        holder.actor.turn_flags["_round_killing_line_free"] = _stamp(engine)
    roll = engine.roller.roll(DiceSpec(count=1, sides=4, modifier=0), actor_id=holder.actor.entity_id,
                              reason="Read the Killing Line: Exposed Meridian")
    engine._record_roll(roll)
    return -int(roll.total)


def exposed_meridian_costs(engine: Any, holder: Any, rc: Any) -> tuple:
    free = (_revelation(engine, holder.actor) is not None
            and holder.actor.turn_flags.get("_round_killing_line_free") != _stamp(engine))
    return () if free else ((("stamina", 1),),)


def register_exposed_meridian() -> None:
    from .d20_rewrite import Rule, register

    register(Rule("exposed_meridian", "Read the Killing Line (Exposed Meridian)", feature=PREFIX + "read_the_killing_line",
                  who="enemy", when="any", op="choose", choose=lambda engine, holder, rc: rc.natural,
                  costs_for=exposed_meridian_costs, guard=exposed_meridian_guard, bonus=exposed_meridian_penalty,
                  ai=exposed_meridian_ai,
                  checkpoint="D20_REWRITE_ROLL"))


register_exposed_meridian()


# ------------------------------------------------------------------------------------------------ Eye beneath the Skin
@effect("eye_beneath")
def eye_beneath(ctx: Any, row: dict[str, Any]) -> None:
    """Recorded when the Reaction is taken: its AC bonus is for that attack only; a miss grants the rest (after_miss)."""
    if ctx.target is not None:
        ctx.actor.turn_flags["_eye_beneath_watch"] = {"attacker": ctx.target.entity_id, "after": len(ctx.engine.events)}


@hook("attack_resolved")
def eye_beneath_resolved(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    watch = (target.turn_flags.get("_eye_beneath_watch") or {}) if target is not None else {}
    if watch.get("attacker") != ctx.actor.entity_id:
        return
    target.turn_flags.pop("_eye_beneath_watch", None)
    engine = ctx.engine
    for mid, modifier in list(target.modifiers.items()):  # "Add Proficiency Bonus to AC against that attack" -- only that one
        if modifier.source_definition_id == PREFIX + "eye_beneath_the_skin" and modifier.target_field == "armor_class":
            del target.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", PREFIX + "eye_beneath_the_skin", actor_id=target.entity_id, target_ids=(target.entity_id,),
                                 payload={"modifier_id": mid, "reason": "ATTACK_RESOLVED"})
    if hit or not target.active:
        return
    from .effect_durations import token
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    attacker = ctx.actor
    appraise(engine, target, attacker, PREFIX + "eye_beneath_the_skin", expires_on=token("end", target.entity_id, int(target.turns_started) + 1))
    target.turn_flags["_round_eye_beneath_unseen"] = {"ids": [attacker.entity_id], "until": int(target.turns_started) + 1}
    paths = routes(engine, target, 5)
    if paths:
        picked = ask(engine, ctx.intent or _intent(engine), checkpoint_id(engine, "eye_beneath_move", target.entity_id), target, "choice:needle.eye_beneath_move",
                     sorted(paths), allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths},
                     target_id=target.entity_id, name="Eye beneath the Skin", prompt="Eye beneath the Skin: move 5 feet without provoking?")
        if picked and picked[0] in paths:
            step(engine, target, paths[picked[0]], PREFIX + "eye_beneath_the_skin")


@hook("turn_end")
def eye_beneath_expires(engine: Any, actor: Any, *, nominal: bool = False) -> None:
    from .effect_durations import custom_turn_due
    watch = actor.turn_flags.get("_round_eye_beneath_unseen") or {}
    if watch and custom_turn_due(actor, int(watch.get("until") or 0), actor.turn_flags, "eye_beneath", nominal=nominal):
        actor.turn_flags.pop("_round_eye_beneath_unseen", None)  # "before your next turn" ends with that turn


@hook("nominal_slot_boundary")
def nominal_eye(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint == "END_OF_TURN":
        eye_beneath_expires(engine, actor, nominal=True)


# ------------------------------------------------------------------------------------------------------ Hundred Eyes Open
@effect("hundred_eyes_answer")
def hundred_eyes_answer(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    engine, me, other = ctx.engine, ctx.actor, ctx.target
    if other is None:
        return
    strike = next((a for a in sorted(engine.action_catalog.values(), key=lambda a: a.source_definition_id) if a.owner_id == me.entity_id
                   and ".natural." in a.source_definition_id and "#" not in a.source_definition_id
                   and any(isinstance(e, dict) and e.get("attack_kind") == "unarmed" for e in ((a.parameters or {}).get("typed") or {}).get("effects") or [])), None)
    labels = {"move": "Move 15 feet without provoking", "disadvantage": f"Disadvantage on {other.display_name}'s next attack roll",
              "save": "+ Proficiency Bonus on your next saving throw this turn"}
    if strike is not None and other.active and engine._distance_actor_to_actor(me, other) <= int(strike.range_ft or 5):
        labels = {"strike": f"Make one unarmed strike against {other.display_name}", **labels}
    intent = ctx.intent or _intent(engine)
    picked = ask(engine, intent, checkpoint_id(engine, "hundred_eyes", me.entity_id), me, "choice:needle.hundred_eyes_open", list(labels), labels=labels,
                 target_id=me.entity_id, name="Hundred Eyes Open", prompt=f"Hundred Eyes Open: {other.display_name} acts under your eyes. Choose one.")
    choice = picked[0] if picked and picked[0] in labels else next(iter(labels))
    if choice == "move":
        paths = routes(engine, me, 15)
        pick = ask(engine, intent, checkpoint_id(engine, "hundred_eyes_move", me.entity_id), me, "choice:needle.hundred_eyes_move", sorted(paths),
                   allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=me.entity_id,
                   prompt="Hundred Eyes Open: move up to 15 feet without provoking.") if paths else None
        if pick and pick[0] in paths:
            step(engine, me, paths[pick[0]], PREFIX + "hundred_eyes_open")
    elif choice == "strike" and strike is not None:
        typed = (strike.parameters or {}).get("typed") or {}
        attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
        if attack is not None:
            attack.update(count=1, granted_attack_root=True)
            te.run_effects(te.Context(engine, me, strike, intent, {**typed, "effects": [attack], "granted_attack": True}, [other], other, {}), [attack])
    elif choice == "disadvantage":
        engine._add_modifier(other, PREFIX + "hundred_eyes_open", "attack_mode", "SET", "DISADVANTAGE", "NEXT_ATTACK", expires_on="CONSUMED")
    else:
        me.turn_flags["_round_hundred_eyes_save"] = _stamp(engine)


@hook("save")
def hundred_eyes_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if ctx is None or subject is None or subject.turn_flags.get("_round_hundred_eyes_save") != _stamp(ctx.engine):
        return None
    subject.turn_flags.pop("_round_hundred_eyes_save", None)
    return {"bonus": int(subject.proficiency_bonus or 2), "modes": []}


# ------------------------------------------------------------------------------------------------ Thousand-Eyed Revelation
@hook("compile_actions")
def calamity_gaze(info: dict[str, Any]) -> list[Any] | None:
    mid = PREFIX + REVELATION
    if mid not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"source": mid, "numbers": dict(info["numbers"]), "area": {"shape": "cone", "size_ft": 60}, "duration": {"kind": "instant"}, "riders": [],
             "effects": [{"type": "calamity_gaze"}]}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.{mid}.calamity_gaze", display_name="Calamity Gaze", owner_id=info["actor_id"],
                             economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="CELL", range_ft=60, costs=((STAMINA, 3),),
                             parameters={"typed": typed, "expected_damage": 36, "calamity_gaze": True, "delivers_strike": True})]


@hook("candidate_allowed")
def gaze_while_revealed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if (getattr(action, "parameters", None) or {}).get("calamity_gaze") and _revelation(engine, actor) is None:
        return False
    return None


@effect("calamity_gaze")
def calamity_gaze_effect(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    engine, owner = ctx.engine, ctx.actor
    state = _revelation(engine, owner)
    for foe in [t for t in (ctx.targets or []) if t.active and t.entity_id != owner.entity_id]:
        sub = te.Context(engine, owner, ctx.action, ctx.intent, ctx.typed, [foe], foe, {})
        te.run_effects(sub, [{"type": "save", "ability": "wis", "evidence": "Calamity Gaze: Wisdom saving throw",
                              "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 8, "sides": 8}, "damage_types": ["psychic"]},
                                          {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"},
                                          {"type": "gaze_appraise", "failed": True, "until": getattr(state, "expires_on", None)}],
                              "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["psychic"]},
                                             {"type": "gaze_appraise", "failed": False}]}])


@effect("gaze_appraise")
def gaze_appraise(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.target is None or not ctx.target.active:
        return
    until = str(row.get("until") or "") if row.get("failed") else ""
    appraise(ctx.engine, ctx.actor, ctx.target, PREFIX + "calamity_gaze", expires_on=until or "START_OF_SOURCE_NEXT_TURN", gazed=bool(row.get("failed")))
