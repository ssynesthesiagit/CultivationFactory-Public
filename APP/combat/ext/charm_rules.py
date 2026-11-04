"""What a Charmed, Captivated or otherwise "barred" creature may not do, and what ends it early (rider lane 3, 2026-09-29).

The owner's Beauty text (Sphere Compendium, "Charmed", "Captivated", "Charm Immunity and Beauty"): "A creature Charmed by you cannot willingly
attack you while the condition lasts ... Beauty charms are fragile. Unless a talent says otherwise, a Beauty charm ends early if you or your
allies damage the Charmed creature or force it to make a saving throw that deals damage." "A Captivated creature is not fully Charmed. Instead,
until the effect ends: it has Disadvantage on Wisdom (Perception) checks to notice creatures other than you; it cannot make Opportunity Attacks
against creatures other than you; the first time on each of its turns that it targets a creature other than you with an attack or hostile action,
it must make a Wisdom saving throw ... Captivated ends early if you become Hidden from the creature, if the creature can no longer perceive you, or
if you or your allies damage it." The engine already barred attacks on one's charmer; Captivated's rules and the additional Beauty
restrictions/early endings were still GM work.

A condition (or the ``creature_bar`` effect's own condition) carries a ``bar`` in its data, put there by the effect that imposed it
(``condition_data`` on a ``condition`` row, typed_executor.block_condition); the creature that imposed it is the condition's source ("you").

  attack            "source": may not attack the source (its attack candidates aimed at it are not offered, nor an opportunity attack against it)
                    "any": may not make attacks at all ("cannot willingly make attacks")
  damaging_saves    with attack "any": nor an ability that forces a saving throw that deals damage
  unless            lifts an additional ban: "harmed_since_turn" -- it or one of its allies was damaged since the end of its last turn
  fragile           ends the condition when damaged: "source" (by the source), "source_side" (by the source or one of the source's allies), "any" (by anyone)
  penalty           {"mode": "DISADVANTAGE", "vs": "others", "first": "turn" | "once"}: Disadvantage on its attack rolls against every creature but the
                    source -- all of them, the first each of its turns ("turn"), or only the first before the condition ends ("once")
  captivated        true: Disadvantage on its Wisdom (Perception) checks to search for a hidden creature other than the source, no Opportunity Attacks against
                    anyone but the source, and the condition ends when it can no longer perceive the source (movement/condition events and turn start)
                    (the hostile-action save/retargeting remains a GM rider in the locked declaration engine)
  repeat_on_ally_harm  repeats its original save when the source's side damages its ally (Tears Like Pearls)
  immune_on_save    grants immunity to this source ability after a successful repeated save (Beauty That Ends War)
  one_activity     only move OR Action OR Bonus Action on its turn (Overwhelmed by Splendor)
  declare_save     {"ability", "dc", "vs", "perception", "on_success", "immune_until", "passes", "resists"}: the printed
                    "the first time on each of its turns that it declares a hostile action, it must make a Wisdom
                    saving throw" (AUTO52). See "the declaration save" below.
  retaliate        {"damage", "damage_type", "vs", "first"}: the printed "the first time on each of its turns that it
                    damages a creature other than you, it takes <damage> <damage_type> damage" (AUTO52, Beauty That
                    Judges). See "the judged wound" below.

THE DECLARATION SAVE (AUTO52, 2026-10-05).  Owner's Beauty text: Captivated (Key Terms, and every Beauty talent that
Captivates) "the first time on each of its turns that it targets a creature other than you with an attack or hostile
action, it must make a Wisdom saving throw ... on failure it must choose you if legal, choose a legal non-hostile
action, or lose that attack or hostile action"; Beauty Beyond Form "The first time on each of its turns that it targets
one of your allies with an attack or damaging effect, it must repeat the saving throw. On a failure, it loses that
attack or damaging effect. On a success, it acts normally and the Charmed condition ends"; Awe Before Violence "the
first time on each creature's turn that a creature that can perceive you targets you with an attack, it must make a
Wisdom saving throw ... On a successful save, it can attack you normally and is immune to this talent until the start of
its next turn" and "A creature that succeeds on three saving throws against this talent during the same scene becomes
immune to your Awe Before Violence for 24 hours".

A bar's ``declare_save`` keys, all optional: ``ability`` (default "wis"), ``dc`` (the applier's Cultivation Save DC;
rows omit it and ``declare_dc`` below stamps the caster's own onto the bar when the condition lands, as ``repeat_save``
does), ``vs`` ("others", the default, for a creature other than the applier; "source" for the applier itself),
``perception`` (the attacker must be able to perceive the applier when it declares), ``on_success``
("end_condition" ends the bar, Beauty Beyond Form), ``immune_until`` ("start_of_source_next_turn"),
``resists`` (the ability name immunity is keyed to, when it differs from the bar's own source) and ``passes`` (how
many successful declarations make the attacker immune for a night, the printed three).  Which side carries the bar
decides where it is read: a ``vs: "others"`` bar (Captivated, Charmed) is that creature's own rule about what it
declares and is read only when it is the attacker; a ``vs: "source"`` bar (Awe Before Violence's self aura) is a rule
about the creature being attacked and is read only on the defender.  ``remedy`` is the printed failure consequence and
is the only key that differs between rules: ``"choose"`` (Captivated -- "on failure it must choose you if legal, choose a
legal non-hostile action, or lose that attack or hostile action") makes the creature decide; a bar with no ``remedy``
keeps the bare loss its own text prints (Beauty Beyond Form -- "On a failure, it loses that attack or damaging effect"),
which is also what every saved fight and every row written before this key existed gets.  ``turn_flags`` are the
printed once-each-turn clock, so no stored state is added for it.

The printed save is asked at the attack's *declaration* -- the engine's ``retarget_attack`` checkpoint, reached by
native, typed and opportunity attacks alike -- because the Captivated consequence "it must choose you if legal"
changes who the attack hits, and only this checkpoint can change a target before the die is rolled.  This plug-in
registers a *constraint* on the shared owner combat/ext/redirection.py (the one owner of that hook) rather than a
second owner: a constraint is a rule about what the attacker may declare, and it is asked before the ordinary
redirection providers, which answer for the defender.  Winner-takes-first used to let Defensive Rider, Meat Shield,
Misdirected Attack or Harmonious Body re-aim a Captivated creature's first attack without ever running its save.
A failure whose remedy is ``redirect`` really re-aims the attack at the applier (the engine records
ATTACK_RETARGETED and rolls against it); a failure whose remedy is ``lost`` records that in the clock and the
``before_attack`` answer turns this one attack into the documented ``{"force_miss": True}`` miss -- no die or Armor
Class is touched -- and returns None, so a defender's own printed redirection is still answered for that attack.
"Choose you if legal" is offered only when the engine's own recipient query and its own redirected-
target test both accept the applier, so a returned target is one the resolver will take rather than one it rejects.

A constraint's answer settles what the attacker may declare and nothing more (AUTO52r3f1).  The attack then faces the
creature the answer names, and *its* own printed defensive redirection is answered for the attack it now faces -- the
shared owner asks its providers with the resulting defender, without asking this constraint stage again -- so a captive
aimed at a charmer who owns Meat Shield is still offered Reactive Cover, and one aimed at a charmer who rides is still
offered Defensive Rider.  The recorded loss is likewise spent on the attack whose save failed, whoever that attack ends
up facing: ``before_attack`` matches the recorded clock entry rather than re-reading the declaration predicate against
the current defender, so a redirection cannot cancel a loss the creature already chose.

The third printed consequence, "choose a legal non-hostile action", is NOT offered: the engine has no seam that cancels
a declared attack and hands the creature a replacement action, so offering it would spend the attack and promise
something that does not happen.  It stays a lock-round rider until that general seam exists; the plug-in records this in
its report rather than in a log line a player could believe.  The printed rule says nothing about the creature's
*later* declarations, so nothing else leaves the menu.  Default-inert: a bar without ``declare_save`` gets no answer,
and a fight saved before this change carries no such bar.

THE JUDGED WOUND (AUTO52).  Beauty That Judges: "While judged, the first time on each of its turns that it damages a
creature other than you, it takes Psychic damage equal to your Proficiency Bonus + your key ability modifier".  A bar's
``retaliate`` carries the amount already resolved by ``judged_wound`` (the caster's numbers at the time the condition
landed, stored as an integer on the bar, so it survives a table commit and reload) and the damage type.  It is answered
from ``damage_dealt``, the typed damage pipeline after defences, so the wound is ordinary damage with its own
Resistance, Temporary HP, Concentration check and defeat -- and because it is not raised inside an event hook, the
downstream damage riders still see it.

``creature_bar`` {"applies_to": "target", "bar": {...}, "duration": ..., "label": "..."} puts a bar on a creature that has no Charmed to carry it
("cannot willingly attack you until the start of its next turn").  ``if_perceives`` {"effects": [...]} runs the nested effects only for the targets that
can see the creature using the ability ("when a hostile creature starts its turn in the aura and can perceive you, it must make a Wisdom saving throw").  Hooks: ``candidate_allowed``, ``opportunity_allowed``, ``attack_mode``,
``stealth_search_mode``, ``event`` (fragile; a spent "once"), ``turn_start``; nothing new in the framework.
"""
from typing import Any

from . import effect, hook
from .redirection import constraint

CONDITION = "condition:typed.bar"
CHARMED, CAPTIVATED = "condition:typed.charmed", "condition:typed.captivated"


def bars(actor: Any):
    """(instance id, condition, bar) for each bar on the creature.

    Only a dict is a charm bar. Other conditions may use the same ``bar`` data key for a
    plain string (protection's Ward ``ward_apron`` stores "keep_out" / "no_closer"); those are
    not charm bars and must not reach the ``.get`` calls below (MAINREDGT5)."""
    for instance_id, held in actor.conditions.items():
        bar = (held.data or {}).get("bar")
        if isinstance(bar, dict) and bar:
            yield instance_id, held, bar


@effect("creature_bar")
def creature_bar(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    for subject in _default_subject(ctx, row, harmful=True):
        if subject.active:
            ctx.engine._apply_condition(subject, CONDITION, ctx.source, ctx.actor.entity_id,
                                        expires_on=effect_expiry(ctx, row, subject, condition=True) or "START_OF_SOURCE_NEXT_TURN",
                                        data={"bar": dict(row.get("bar") or {}), "label": str(row.get("label") or "Barred")})


# --------------------------------------------------------------------------------------------------------- what happened lately
def _since(engine: Any, sequence: int, kinds: tuple[str, ...]) -> list[Any]:
    """The events of these kinds after ``sequence`` (a cache per event count: the hooks ask at every decision)."""
    cache = engine.__dict__.setdefault("_bar_events", {})
    stamp = len(engine.events)
    if cache.get("stamp") != stamp:
        cache.clear()
        cache["stamp"] = stamp
    key = (sequence, kinds)
    if key not in cache:
        cache[key] = [event for event in engine.events if event.sequence > sequence and event.event_type in kinds]
    return cache[key]


def _lifted(engine: Any, holder: Any, held: Any, bar: dict[str, Any]) -> bool:
    unless = bar.get("unless")
    if unless == "harmed_since_turn":
        ended = max((event.sequence for event in engine.events if event.event_type == "TURN_ENDED" and event.actor_id == holder.entity_id), default=0)
        allies = {other.entity_id for other in engine.state.actors.values() if other.team_id == holder.team_id}
        return any(_damage(event.payload or {}) > 0 and set(event.target_ids or ()) & allies
                   for event in _since(engine, ended, ("DAMAGE_COMMITTED",)))
    return False


def _rows(action: Any) -> list[dict[str, Any]]:
    from ..typed_executor import _walk_rows

    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    return list(_walk_rows(typed.get("effects") or []))


def _attacks(action: Any) -> bool:
    return any(row.get("type") == "attack" for row in _rows(action))


def _forces_damaging_save(action: Any) -> bool:
    from .save_damage import has_damage

    rows = _rows(action)
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    return any(row.get("type") == "save" for row in rows) and has_damage(typed.get("effects"))


@hook("candidate_allowed")
def gate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    for _, held, bar in bars(actor):
        if bar.get("one_activity"):
            from .hold_still import moved_ft

            economy = getattr(getattr(action, "economy", None), "value", None)
            moving = str(getattr(candidate, "kind", "")).split(".")[-1] == "MOVE"
            if (moving and (not actor.action_available or not actor.bonus_action_available)) or (
                    economy == "ACTION" and (not actor.bonus_action_available or moved_ft(engine, actor) > 0)) or (
                    economy == "BONUS_ACTION" and (not actor.action_available or moved_ft(engine, actor) > 0)):
                return False
        if not bar.get("attack") or _lifted(engine, actor, held, bar):
            continue
        aimed = bar["attack"] == "any" or held.source_actor_id in (candidate.target_ids or ())
        if aimed and (_attacks(action) or (bar.get("damaging_saves") and _forces_damaging_save(action))):
            return False
    return None


@hook("opportunity_allowed")
def opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    for _, held, bar in bars(reactor):
        if bar.get("captivated") and mover.entity_id != held.source_actor_id:
            return False  # "it cannot make Opportunity Attacks against creatures other than you"
        if bar.get("attack") and not _lifted(engine, reactor, held, bar) and (bar["attack"] == "any" or mover.entity_id == held.source_actor_id):
            return False
    return None


@hook("reaction_subject_allowed")
def beauty_reaction(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    # Generic reactions have their own save interpreter; block_save's skip_if_immune is not on that path.
    if "BEAUTY_BASE_TURN_THE_BLADE_ASIDE" in str(row.get("feature_id") or "") and any(
            effect.get("skip_if_immune") == "charmed" for effect in row.get("effects") or []):
        from ..typed_executor import condition_immune

        if condition_immune(engine, other, "charmed"):
            return False
    return None


@hook("attack_mode")
def penalty(ctx: Any, target: Any) -> str | None:
    for instance_id, held, bar in bars(ctx.actor):
        rule = bar.get("penalty")
        if not rule or target.entity_id == held.source_actor_id:
            continue
        if rule.get("first") == "turn":
            if ctx.engine.state.current_actor_id != ctx.actor.entity_id:
                continue
            flag = f"bar_first:{instance_id}"
            if ctx.actor.turn_flags.get(flag):
                continue
            ctx.actor.turn_flags[flag] = True
        return str(rule.get("mode") or "DISADVANTAGE")
    return None


@hook("stealth_search_mode")
def notice(engine: Any, searcher: Any, hidden_foe: Any) -> str | None:
    for _, held, bar in bars(searcher):
        if bar.get("captivated") and hidden_foe.entity_id != held.source_actor_id:
            return "DISADVANTAGE"
    return None


@hook("save")
def fragile_damaging_save(ctx: Any, subject: Any, ability: str, named: Any) -> None:
    """Beauty's default fragility includes forcing a damaging save, even if resistance absorbs the resulting damage."""
    if "damaging_save" not in (named or ()):
        return
    for iid, held, bar in list(bars(subject)):
        if held.condition_id != CHARMED:
            continue  # Captivated and non-charm bars end on actual damage, not merely a damaging save.
        source = ctx.engine.state.actors.get(held.source_actor_id)
        if source is not None and (bar.get("fragile") == "source" and ctx.actor.entity_id == source.entity_id or
                                   bar.get("fragile") == "source_side" and ctx.actor.team_id == source.team_id):
            _drop(ctx.engine, subject, iid, held, "bar.damaging_save")


@effect("if_perceives")
def if_perceives(ctx: Any, row: dict[str, Any]) -> None:
    import copy
    from dataclasses import replace

    from .. import stealth
    from ..typed_executor import run_effects

    seers = [subject for subject in (list(ctx.targets) or ([ctx.target] if ctx.target else [])) if subject.active and stealth.sees(ctx.engine, subject, ctx.actor)]
    if seers:
        run_effects(replace(ctx, targets=seers, target=seers[0] if len(seers) == 1 else None), copy.deepcopy(row.get("effects") or []))


def _drop(engine: Any, holder: Any, instance_id: str, held: Any, why: str) -> None:
    if instance_id not in holder.conditions:
        return
    del holder.conditions[instance_id]
    engine._append_event("CONDITION_REMOVED", f"system:{why}", actor_id=held.source_actor_id, target_ids=(holder.entity_id,),
                         payload={"condition_id": held.condition_id, "instance_id": instance_id})


def _damage(payload: dict[str, Any]) -> int:
    return int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0)


def _repeat(engine: Any, holder: Any, iid: str, held: Any) -> None:
    save = (held.data or {}).get("origin_save") or (held.data or {}).get("repeat_save") or {}
    # Event-triggered repeats share the final outcome, removal and transactional
    # choice scopes with turn-triggered repeats. Keep this bar's WIS default.
    engine.resolve_repeat_save(holder, iid, held, {"ability": str(save.get("ability") or "WIS"),
                               "dc": int(save.get("dc") or 10)}, "ALLY_HARM")


def _save_immunity(engine: Any, holder: Any, source: str) -> None:
    from .resist_ability import CONDITION as RESIST, source_ability

    for _, held, bar in list(bars(holder)):
        if bar.get("immune_on_save") and held.source_definition_id == source:
            engine._apply_condition(holder, RESIST, source, held.source_actor_id, expires_on="UNTIL_REMOVED",
                data={"ability": source_ability(engine, source), "mode": "immune", "label": "Immune to Beauty That Ends War"})


@hook("event", nested=True)
def after_event(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "DAMAGE_COMMITTED":
        payload = kwargs.get("payload") or {}
        if _damage(payload) <= 0:
            return
        damager = engine.state.actors.get(kwargs.get("actor_id") or "")
        for target_id in kwargs.get("target_ids") or ():
            holder = engine.state.actors.get(target_id)
            for instance_id, held, bar in list(bars(holder)) if holder is not None else ():
                fragile = bar.get("fragile")
                source = engine.state.actors.get(held.source_actor_id)
                if fragile == "any" or (fragile == "source" and damager is not None and damager.entity_id == held.source_actor_id) or (
                        fragile == "source_side" and damager is not None and source is not None and damager.team_id == source.team_id):
                    _drop(engine, holder, instance_id, held, "bar.damaged")
        targets = [engine.state.actors[t] for t in kwargs.get("target_ids") or () if t in engine.state.actors]
        for holder in list(engine.state.actors.values()):
            for iid, held, bar in list(bars(holder)):
                source = engine.state.actors.get(held.source_actor_id)
                if source is None:
                    continue
                if bar.get("repeat_on_ally_harm") and damager is not None and damager.team_id == source.team_id and any(
                        t.team_id == holder.team_id and t.entity_id != holder.entity_id for t in targets):
                    _repeat(engine, holder, iid, held)
    elif event_type == "ATTACK_ROLLED":
        attacker = engine.state.actors.get(kwargs.get("actor_id") or "")
        for instance_id, held, bar in list(bars(attacker)) if attacker is not None else ():
            if (bar.get("penalty") or {}).get("first") == "once":
                _drop(engine, attacker, instance_id, held, "bar.spent")
    elif event_type == "SAVE_ROLLED" and (kwargs.get("payload") or {}).get("success"):
        holder = engine.state.actors.get(kwargs.get("actor_id") or "")
        if holder is not None:
            rolled = next((event for event in reversed(engine.events) if event.event_type == "SAVE_ROLLED" and event.actor_id == holder.entity_id
                           and (event.payload or {}).get("roll_id") == (kwargs.get("payload") or {}).get("roll_id")), None)
            from ..typed_executor import active_save_pending

            # Active saves already grant immunity in their typed on_success
            # branch, after final outcome overrides. Only repeated/legacy saves
            # need this event fallback; do not duplicate the active effect.
            if rolled is not None and not active_save_pending(engine, rolled.source_definition_id, holder.entity_id):
                _save_immunity(engine, holder, rolled.source_definition_id)
    if event_type in ("MOVEMENT_COMMITTED", "CONDITION_APPLIED", "CONDITION_REMOVED"):
        for holder in list(engine.state.actors.values()):
            _clear_unseen(engine, holder)


@hook("turn_start")
def turn_start(engine: Any, actor: Any) -> None:
    _clear_unseen(engine, actor)


def _clear_unseen(engine: Any, actor: Any) -> None:
    from .. import stealth

    for instance_id, held, bar in list(bars(actor)):
        source = engine.state.actors.get(held.source_actor_id)
        if bar.get("captivated") and (source is None or not source.active or source is not actor and (
                stealth.hidden(source) is not None or not source_perceived(engine, actor, source, held))):
            _drop(engine, actor, instance_id, held, "bar.unseen")  # "if you become Hidden from the creature, or it can no longer perceive you"


def source_perceived(engine: Any, holder: Any, source: Any, condition: Any) -> bool:
    """Live source perception for condition upkeep; unclaimed rows keep sight.

    Ability providers may supply another printed perception channel. This does
    not bypass a condition's independent Hidden, damage or duration endings.
    """
    from . import run_strict
    from .. import stealth

    replies = run_strict("condition_source_perceived", engine, holder, source, condition)
    if any(type(reply) is not bool for reply in replies):
        raise ValueError("condition_source_perceived must return None or bool")
    return any(replies) if replies else stealth.sees(engine, holder, source)


# --------------------------------------------------------------------------------------------------------- the declaration save
DECLARE = "declare_save"
FLAG = "bar_rule"         # actor.turn_flags prefix: the printed "the first time on each of its turns" clock
PASSES = "condition:typed.declaration_passes"


def _flag(instance_id: str) -> str:
    return f"{FLAG}:{instance_id}"


def _pending(instance_id: str) -> str:
    """The loss still owed to the attack being resolved. Cleared as soon as that attack takes it, so a second
    attack with the same source and index that turn is not lost by the first one's failure."""
    return f"{FLAG}_lost:{instance_id}"


def _declarations(engine: Any, attacker: Any, defender: Any) -> list[tuple[Any, str, Any, dict[str, Any]]]:
    """(holder, instance_id, held, rule) for every bar this declaration triggers, the attacker's own bars first.

    A bar rides the creature it was laid on: ``vs: "others"`` (Captivated, Charmed) is that creature's own rule about
    the actions it declares, so it is only read when that creature is the attacker -- being attacked is not a
    declaration. ``vs: "source"`` (a self aura, Awe Before Violence) is a rule about the creature being attacked, so
    it is only read on the defender.
    """
    from .resist_ability import resists, source_ability

    out = []
    for holder in (attacker, defender):
        if holder is None or not getattr(holder, "active", True):
            continue
        for instance_id, held, bar in bars(holder):
            rule = bar.get(DECLARE)
            if not isinstance(rule, dict) or held.source_actor_id not in engine.state.actors:
                continue
            aimed = defender is not None and defender.entity_id == held.source_actor_id
            if str(rule.get("vs") or "others").lower() == "source":
                if not aimed or holder is not defender:
                    continue
            elif aimed or holder is not attacker:
                continue
            if resists(held.source_actor_id, attacker, source_ability(engine, held.source_definition_id), "immune"):
                continue
            out.append((holder, instance_id, held, rule))
    return out


def _ability_name(engine: Any, held: Any) -> str:
    """The readable name of the ability whose bar this is, for the forced-miss receipt and the condition labels."""
    from .resist_ability import source_ability

    printed = source_ability(engine, held.source_definition_id)
    action = next((a for a in engine.action_catalog.values()
                   if str(((a.parameters or {}).get("typed") or {}).get("source") or "") == printed), None)
    name = action.display_name if action is not None else printed
    return name.split("+")[0].split(":")[0].strip()


def _roll(engine: Any, attacker: Any, held: Any, rule: dict[str, Any]) -> bool:
    """The printed saving throw, rolled the way every other save on this table is (modes, bonuses, immunity apply)."""
    dc = int(rule.get("dc") or 10)
    roll = engine._roll_save(attacker, str(rule.get("ability") or "WIS").upper(), dc, held.source_definition_id)
    return roll is None or roll.total < dc


def _immune(engine: Any, subject: Any, held: Any, rule: dict[str, Any], label: str, expires_on: str) -> None:
    from .resist_ability import CONDITION as RESIST

    engine._remove_condition(subject, RESIST, held.source_definition_id)
    engine._apply_condition(subject, RESIST, held.source_definition_id, held.source_actor_id, expires_on=expires_on,
                            data={"ability": str(rule.get("resists") or held.source_definition_id), "mode": "immune",
                                  "label": f"Immune to {label}"})


def _tally(engine: Any, attacker: Any, held: Any, rule: dict[str, Any], label: str) -> None:
    """"succeeds on three saving throws against this talent during the same scene becomes immune ... for 24 hours":
    one evented pass per success, so the count survives a table commit and reload without a mutable counter."""
    wanted = max(1, int(rule.get("passes") or 0))
    passes = sorted((c for c in attacker.conditions.values() if c.condition_id == PASSES
                     and c.source_actor_id == held.source_actor_id and c.source_definition_id == held.source_definition_id),
                    key=lambda c: int((c.data or {}).get("count") or 0))
    if any(int((c.data or {}).get("count") or 0) >= wanted for c in passes):
        return
    for old in passes:
        engine._remove_condition(attacker, PASSES, old.source_definition_id)
    count = (int((passes[-1].data or {}).get("count") or 0) if passes else 0) + 1
    engine._apply_condition(attacker, PASSES, held.source_definition_id, held.source_actor_id, expires_on="UNTIL_REMOVED",
                            data={"count": count, "label": f"{label}: {attacker.display_name} has saved against it {count} time(s)"})
    if count >= wanted:
        _immune(engine, attacker, held, rule, label, "UNTIL_REMOVED")  # 24 hours is the rest of the fight


@hook("condition_state")
def declare_dc(ctx: Any, subject: Any, effect: dict[str, Any]) -> dict[str, Any] | None:
    """Put the applier's own Cultivation Save DC on a bar's declaration save, as ``repeat_save`` does, so the later
    save is the printed "its own" difficulty however the condition was reached. The only answer for a bar row."""
    bar = ((effect.get("condition_data") or {}).get("bar") or {})
    rule = bar.get(DECLARE)
    if not isinstance(rule, dict):
        return None
    return {"data": {"bar": {**bar, DECLARE: {**rule, "dc": int(ctx.numbers.get("save_dc") or 10),
                                               "resists": str(rule.get("resists") or ctx.typed.get("source") or ctx.source)}}}}


@hook("condition_choice_owner")
def bar_choice_owner(engine: Any, actor: Any, condition: Any) -> bool | None:
    """A creature carrying a choice-bearing bar owns that decision, so the table asks it (checklist 9).

    The service enrols a manually controlled creature only when some general ownership hook says the decision
    belongs to it (``gate5_service._ask_reactors`` -> ``condition_choice_owner``). This condition *creates* the
    decision -- the printed Captivated save hands the creature the choice -- so it is the owner, whether or not
    the character has an unrelated Ask-me row, a setup task or a choice reactor. Only a bar that actually asks
    owns anything: a loss-only bar has no decision, so it stays out (None, the default-inert answer), and an AI
    bearer still answers automatically.
    """
    bar = (getattr(condition, "data", None) or {}).get("bar")
    if not isinstance(bar, dict):
        return None
    rule = bar.get(DECLARE)
    if isinstance(rule, dict) and not _loss_only(rule):
        return True
    return None


def _loss_only(rule: dict[str, Any]) -> bool:
    """Whether this bar's own printed failure only loses the attack or damaging effect.

    Captivated's failure is a choice the creature makes ("it must choose you if legal, choose a legal
    non-hostile action, or lose that attack or hostile action"), so only a bar that says so in typed data
    (``remedy: "choose"``) asks. Every other bar keeps the bare loss its own text prints -- Beauty Beyond Form's
    "On a failure, it loses that attack or damaging effect" -- and so does every bar written or saved before the
    key existed. A rule never inherits a choice it does not print.
    """
    return str(rule.get("remedy") or "").lower() != "choose"


def _applier(engine: Any, attacker: Any, held: Any, attack: str | None, action: Any,
             reach: int | None = None) -> Any | None:
    """The applier when the engine would accept this very attack aimed at it, else None (the printed "if legal").

    Two engine tests, both the resolver's own: the recipient query (``attack_declaration.can_target``) for "may
    this attack target that creature at all", and the acceptance test ``attack_declaration.declare`` applies to a
    redirected target (an active creature that is not the attacker, in sight, inside this attack's reach, measured
    the way the resolver measures it). Returning None rather than a target the resolver would reject keeps a
    printed "if legal" honest and keeps a fight from raising on an answer it gave itself.
    """
    from ..attack_declaration import can_target
    from .redirection import legal_target

    applier = engine.state.actors.get(held.source_actor_id)
    if applier is None or not attack:
        return None
    if not legal_target(engine, attacker, applier, reach):
        return None
    if reach is not None and engine._effect_distance(attacker, applier) > int(reach):
        return None
    if not can_target(engine, attacker, applier, attack, action=action, range_ft=reach):
        return None
    return applier


def _ask_remedy(engine: Any, attacker: Any, defender: Any, held: Any, intent: Any, label: str,
                attack: str | None, action: Any, applier: Any) -> str:
    """Which printed consequence a failed Captivated save gets: ``redirect`` (aim it at the applier) or ``lost``.

    Both are outcomes that really happen, which is why only these two are offered. ``redirect`` re-aims this very
    attack through the shared redirection provider, so the engine rolls it against the applier; ``lost`` makes
    this one attack a documented forced miss. The third printed consequence, "choose a legal non-hostile
    action", would need a seam that cancels a declared attack and hands the creature a replacement action --
    the engine has none, so it is withheld rather than promised (lock-round rider, see the module docstring).

    A player-owned creature decides (checklist 9). An AI one takes the printed first legal option and never
    pauses the fight, so a fight without a provider still runs.
    """
    from ..choice_checkpoints import dynamic_choice

    if applier is None or intent is None or not hasattr(engine, "_gate4_reaction_cache"):
        return "redirect" if applier is not None else "lost"
    if attacker.entity_id not in (getattr(engine, "typed_ask_reactors", ()) or ()):
        return "redirect"          # an AI creature takes the printed first legal option
    options = ["redirect", "lost"]
    # The table derives the question's action and its feature name from this metadata (combat/tabletop_service.py),
    # so the prompt names the attack being replaced, the charm that caused the save, and the creature it was aimed at.
    attack_name = getattr(action, "display_name", "") or ""
    aimed_at = getattr(defender, "display_name", "") or ""
    context = {"actor_id": attacker.entity_id,
               "action_actor_id": attacker.entity_id,
               "target_id": defender.entity_id if defender is not None else None,
               "affected_id": defender.entity_id if defender is not None else None,
               "ability": label, "name": label,
               "action_name": attack_name.split("+")[0].split(":")[0].strip(),
               "declaration_remedy_options": options,
               "labels": {"redirect": f"Aim {attack_name or 'this attack'} at {applier.display_name} instead",
                          "lost": f"Lose {attack_name or 'this attack'}: it misses, whatever it rolls"},
               # This question is asked of the creature that owns the choice, so "you" would mean the wrong
               # creature: the attack must be aimed at the charmer (applier), not at the reader.
               "prompt": f"{label}: {attacker.display_name} fails the Wisdom saving throw. It must aim "
                         f"{attack_name or 'that attack'} at {applier.display_name}"
                         + (f" instead of attacking {aimed_at}" if aimed_at else "")
                         + ", or lose that attack."}
    checkpoint = f"TYPED:{label} declaration@{engine.state.event_sequence}:{attacker.entity_id}"
    _, decision = dynamic_choice(engine, intent, checkpoint, attacker.entity_id,
                                 f"choice:{held.source_definition_id}.declaration", context,
                                 spec_override={"option_ids": options, "minimum_selections": 1,
                                                "maximum_selections": 1, "allow_decline": False,
                                                "automatic_use": True,
                                                "preferred_option_ids": ("redirect",)})
    if decision is not None and decision.selection != "DECLINE" and decision.option_ids:
        chosen = str(decision.option_ids[0])
        if chosen in options:
            return chosen
    return "redirect"


def _outcome_key(source_id: Any, index: Any) -> str:
    """The clock entry naming this exact attack, so a lost declaration loses only the attack that failed."""
    return f"{source_id}#{int(index or 1)}"


@constraint(10)
def declaration_redirect(engine: Any, attacker: Any, defender: Any, intent: Any,
                         context: dict[str, Any]) -> dict[str, Any] | None:
    """The printed declaration save, asked once per attacking creature per turn at the attack's own declaration.

    This is the engine's attack-declaration checkpoint (combat/attack_declaration.py), reached by native, typed
    and opportunity attacks alike and the only point before the die is rolled at which the target can change.
    Captivated's printed "it must choose you if legal" therefore really re-aims that attack here instead of
    only being written in a log line, and a loss is recorded for the ``before_attack`` hook to apply.

    It is registered on the *constraint* stage of the shared owner combat/ext/redirection.py, not as an ordinary
    redirection provider, because this is a rule about what the attacker may declare, while Defensive Rider,
    Meat Shield, Misdirected Attack and Harmonious Body answer for the defender. Winner-takes-first let any of
    them re-aim a Captivated creature's first attack without ever running its save, so the constraint stage is
    asked first and its answer settles that declaration: no other constraint is asked about it, so this save is
    never run twice on one attack and its once-each-turn clock is spent once. The attack it re-aims still faces
    the applier's own printed defences, which the owner answers against the creature this answer names. A failure
    with no printed choice -- the bare loss, and every old bar and saved fight -- returns None, which leaves the
    declared attack alone and lets the ordinary providers answer for the defender exactly as before.

    Default-inert: no ``declare_save`` bar on the attacker or the declared target answers nothing, and an empty
    constraint stage changes no attack at all.
    """
    from .. import stealth

    attack = context.get("source_id")
    key = _outcome_key(attack, context.get("attack_index", 1))
    reach = context.get("range_ft")
    for holder, instance_id, held, rule in _declarations(engine, attacker, defender):
        if attacker.turn_flags.get(_flag(instance_id)):
            continue  # already asked on this creature's turn
        if rule.get("perception") and not stealth.sees(engine, attacker, engine.state.actors[held.source_actor_id]):
            continue  # "a creature that can perceive you"
        attacker.turn_flags[_flag(instance_id)] = "asking"
        label = _ability_name(engine, held)
        if _roll(engine, attacker, held, rule):
            action = engine.action_catalog.get(attack) if attack else None
            applier = None if _loss_only(rule) else _applier(engine, attacker, held, attack, action, reach)
            remedy = _ask_remedy(engine, attacker, defender, held, intent, label, attack, action, applier)
            attacker.turn_flags[_flag(instance_id)] = f"{remedy}@{key}"
            if remedy != "redirect":
                attacker.turn_flags[_pending(instance_id)] = key
            if remedy == "redirect":
                engine._append_event("PASSIVE_TRIGGERED", held.source_definition_id, actor_id=attacker.entity_id,
                                     target_ids=(defender.entity_id,),
                                     payload={"declaration_save": True, "target_id": held.source_actor_id,
                                              "remedy": remedy,
                                              "log": f"{label}: {attacker.display_name} fails the saving throw and "
                                                     f"must aim that attack at {applier.display_name} instead of "
                                                     f"attacking {defender.display_name}."})
                return {"source_id": held.source_definition_id, "target_id": applier.entity_id, "cover_bonus": 0}
            engine._append_event("PASSIVE_TRIGGERED", held.source_definition_id, actor_id=attacker.entity_id,
                                 target_ids=(defender.entity_id,),
                                 payload={"declaration_save": True, "target_id": held.source_actor_id,
                                          "remedy": remedy,
                                          "log": f"{label}: {attacker.display_name} fails the saving throw and loses "
                                                 f"that attack against {defender.display_name}."})
            return None
        attacker.turn_flags[_flag(instance_id)] = f"saved@{key}"
        if rule.get("immune_until") == "start_of_source_next_turn":
            _immune(engine, attacker, held, rule, f"{label} until the start of its next turn", "START_OF_SOURCE_NEXT_TURN")
        if str(rule.get("on_success") or "") == "end_condition" and holder is attacker:
            _drop(engine, attacker, instance_id, held, "bar.declare_saved")
        if rule.get("passes"):
            _tally(engine, attacker, held, rule, label)
        break
    return None


def _owed_loss(attacker: Any, defender: Any, key: str) -> tuple[str, Any, dict[str, Any]] | None:
    """The (instance id, bar, rule) this exact attack owes a loss to, matched on the recorded clock alone (AUTO52r3f1).

    The loss was decided at the attack's own declaration, where the printed predicate was true: this bar did
    ask this creature, with this attack, and the creature chose to lose it.  Re-deriving that predicate against
    the *current* defender let a later redirection cancel the answer instead of spending it -- when the captive
    chose "lose it" and the charmer's own Defensive Rider then pulled the attack onto the charmer, the
    declaration predicate no longer held (that bar only speaks for attacks aimed away from its applier), so the
    recorded loss was silently dropped, left unspent on the clock, and the charmer was hit by an attack the
    creature had been told it lost.

    So the clock is the authority here, not the predicate: the flag names this bar and this attack, it is only
    ever written by the declaration stage after a real failure and a real choice, and it is cleared the moment
    that one attack takes the loss.  Both carriers are scanned (an ``vs: "others"`` bar rides the attacker, a
    ``vs: "source"`` bar the creature being attacked) exactly as the declaration stage scans them, so a bar that
    qualifies is found wherever it sits -- and a bar that never recorded a loss is still inert.
    """
    for holder in (attacker, defender):
        if holder is None or not getattr(holder, "active", True):
            continue
        for instance_id, held, bar in bars(holder):
            if attacker.turn_flags.get(_pending(instance_id)) != key:
                continue
            rule = bar.get(DECLARE)
            if isinstance(rule, dict):
                return instance_id, held, rule
    return None


@hook("before_attack")
def declare(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """The printed loss, for the attack whose declaration just failed, as the documented forced-miss outcome.

    The save itself is asked at the attack's declaration (see the module docstring). This hook turns only that
    one recorded "lost" declaration into a miss, for typed, native and opportunity attacks alike, without
    touching the die or the Armor Class, and leaves the menu and every later attack of the turn alone.

    What it matches is the recorded clock entry for this attack (see :func:`_owed_loss`), not a fresh reading of
    the declaration predicate: an attack a redirection has since aimed somewhere else is still the attack whose
    save failed, so a loss the creature chose is honoured whoever the attack ends up facing.
    """
    key = _outcome_key(context.get("source_id"), context.get("attack_index", 1))
    owed = _owed_loss(attacker, defender, key)
    if owed is None:
        return None
    instance_id, held, _rule = owed
    attacker.turn_flags.pop(_pending(instance_id), None)   # this one attack takes the loss, and no other
    return {"force_miss": True, "source_id": held.source_definition_id,
            "label": _ability_name(engine, held)}


# --------------------------------------------------------------------------------------------------------- the judged wound
def _wound(engine: Any, attacker: Any, rule: dict[str, Any], held: Any) -> None:
    """The printed "it takes <damage> <damage_type> damage", as ordinary damage from the caster's own ability."""
    amount = int(rule.get("damage") or 0)
    if amount <= 0 or not attacker.active:
        return
    kind = str(rule.get("damage_type") or "PSYCHIC").upper()
    engine._commit_damage(attacker, amount, kind, held.source_definition_id, held.source_actor_id,
                          getattr(engine, "_active_intent", None), reaction_depth=1)


@hook("damage_dealt")
def judged(ctx: Any, target: Any, amount: int) -> None:
    """"the first time on each of its turns that it damages a creature other than you, it takes ... damage"."""
    damager = ctx.actor
    for instance_id, held, bar in bars(damager):
        rule = bar.get("retaliate")
        if not isinstance(rule, dict) or target is None or target.entity_id == held.source_actor_id:
            continue
        if damager.turn_flags.get(_flag(instance_id)) and str(rule.get("first") or "turn") == "turn":
            continue  # "the first time on each of its turns"
        damager.turn_flags[_flag(instance_id)] = True
        _wound(ctx.engine, damager, rule, held)
        break


@hook("condition_state")
def judged_wound(ctx: Any, subject: Any, effect: dict[str, Any]) -> dict[str, Any] | None:
    """The printed amount is the caster's own Proficiency Bonus + key ability modifier, resolved once when the
    condition lands and stored as an integer so it survives a table commit and reload. The only answer for a bar row."""
    bar = ((effect.get("condition_data") or {}).get("bar") or {})
    rule = bar.get("retaliate")
    if not isinstance(rule, dict):
        return None
    amount = int(rule.get("flat") or 0) + ctx.formula(rule.get("formula") or "none")
    return {"data": {"bar": {**bar, "retaliate": {**rule, "damage": amount,
                                                  "resists": str(rule.get("resists") or ctx.typed.get("source") or ctx.source)}}}}
