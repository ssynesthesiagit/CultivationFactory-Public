"""Music (rider lane 10, 2026-09-29): the Measure, its Phrases, Chords and Domains. Rules text: the owner's Sphere Compendium, "Music"
(authority/typed_mechanics/rules_text.json).

Dissonant Note, Heartstring Severing Prelude and Soul-Sundering Note choose one creature, including self or an ally, through the
native recipient rules with harmful Charm safeguards. Concerto of Broken Breath and Soul-Sundering Note ask their user to choose
one damage type per activation; every recipient and save branch shares it. AI uses the first printed type without private defenses.

Keep the Measure    "Begin a Music performance ... Duration: 1 minute ... the performance ends early if you become Incapacitated or if a
                    required sound/rhythm source is suppressed": the ``music_measure`` row puts "Keeping the Measure" on its user for ten
                    rounds; Incapacitated (or Stunned, Paralyzed, Unconscious, Petrified) or Silenced ends it.
                    Opening Phrase ("Use this only while you Keep the Measure ... A creature can benefit from Opening Phrase only once per
                    round") and Rhythmic Guard ("You must be Keeping the Measure") are offered only then.
Battle Cadence      stays the bodyb variant "Keep the Measure + Battle Cadence" (its modifier on Keep the Measure).
Auras (zone "inside" rules, read by the hooks here from the creature's own condition rules):
                    ``music_speed`` feet of Speed, ``music_ac`` Armor Class, ``music_weapon_attack`` added to weapon attack rolls,
                    ``music_mercy`` (a marker: Symphony's Movement of Mercy is up), ``music_dissonant`` (a marker: its Difficult Terrain is
                    for enemies only).
Marks on the singer's audience (``music_mark``: its user and allies within the printed distance, a condition that ends with the
Concentration): War Song and March of the Immortal Host (Speed, weapon attack, Advantage rows in the mark's rule), Rallying Song
(+1 to saves against Charmed; once per round an affected ally's failed save against Charmed or Frightened takes the singer's
Proficiency Bonus -- a d20 rule of combat/ext/d20_rewrite.py), Shared Measure. "A creature can benefit from only one War Song at a
time": a new one replaces another singer's.
Hits              March: "once per turn after hitting with a weapon attack, move 5 feet without provoking Opportunity Attacks"; Shared Measure:
                    "Once per round, when one affected creature hits with an attack, another affected creature may move 5 feet without provoking"
                    (the nearest other one to the creature struck); Weapon Hymn: "Once per turn when it hits, add 1d6 Thunder or Psychic damage"
                    (the wielder carries the hymn; the table does not track which of its weapons was touched). Free movement is the Command
                    Banner's own (combat/ext/banner.py _grant_step).
Turn ends         Healing Hymn: "At the end of each of your turns, choose one creature within 30 feet ... It regains HP ... only once per short
                    rest" (the most hurt creature of its side that has not had it this fight); Symphony, Movement of Mercy: "choose up to your
                    Proficiency Bonus allies inside. Each regains 2d8 + your Music key ability modifier HP ... only once during the Symphony".
Bell of Warning  "Use Bell of Warning once per round" (a Reaction is otherwise one per turn: the round number is kept on the singer
                    and spent when the Reaction resolves) and "gain +2 AC against the triggering attack" (the AC belongs to that one
                    incoming attack, through combat/ext/next_attack_ac.py, not to the rest of the turn).
Immortal Funeral Bell  enemies inside "cannot regain HP more than once per round": the healing_pending seam lets the first Hit Point
                    grant that lands on a covered enemy stand and spends that enemy's one healing for the round; later grants are cut off.
                    The bell's own conditions say which creatures it reached; the printed aura moves with its singer, so being inside it
                    now is read again (the printed radius around the singer) for every healing.
Soul-Stirring Refrain  "Choose one creature that can hear ... If the target is unwilling, it makes a Wisdom saving throw. A willing
                    target may choose to fail."  The printed gate is combat/ext/willing_targets.py's ``choose_willing`` row (the option's own
                    target, asked to accept, with a "(any creature)" variant for a target that is not an ally): acceptance applies the
                    emotion with no save and no repeat save, a refusal makes the printed Wisdom save and its effects land on a failure
                    with the printed "an unwilling target repeats the saving throw".
Soul-Stirring Refrain, Fury  "adds your Proficiency Bonus to one weapon damage roll each turn" (attack_damage_bonus adds it to the roll the
                    attack is already making -- the weapon's own damage type and the bearer stay the attacker -- reserved for that
                    creature and charged by attack_result, so a miss gives it back; the shared per-turn clock means an Opportunity Attack on
                    another creature's turn has its own roll) and "Disadvantage on attack rolls against targets other than the nearest
                    creature" (attack_mode, every creature at the smallest distance is nearest, so a tie penalises neither).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

M = "tianxia.talent.music."
KEEP, OPENING = "MUSIC_BASE_KEEP_THE_MEASURE", "MUSIC_BASE_OPENING_PHRASE"
CADENCE, HYMN, SHARED, MARCH, WAR, RALLY = M + "battle_cadence", M + "healing_hymn", M + "shared_measure", M + "march_of_the_immortal_host", \
    M + "war_song", M + "rallying_song"
WEAPON_HYMN, GUARD, SYMPHONY, HARMONIZING = M + "weapon_hymn", M + "rhythmic_guard", M + "symphony_of_heaven_and_earth", M + "harmonizing_breath"
MEASURE = "condition:typed.music_measure"
BELL = M + "bell_of_warning"
OPENING_SAVE = "condition:typed.music_opening_save"
OPENING_CONCENTRATION = "condition:typed.music_opening_concentration"
HYMN_MARK = "condition:typed.music_weapon_hymn"
FUNERAL_BELL = M + "immortal_funeral_bell"
REFRAIN = M + "soul_stirring_refrain"
FUNERAL_HEALED = "_round_music_funeral_bell_healed"
ENDERS = (".incapacitated", ".stunned", ".paralyzed", ".unconscious", ".petrified", ".silenced")

CREATURE_NOTES = {M + name for name in (
    "dissonant_note", "heartstring_severing_prelude", "soul_sundering_note")}
DAMAGE_NOTES = {M + "concerto_of_broken_breath", M + "soul_sundering_note"}


@hook("compile_action")
def music_one_creature(action: Any, info: dict[str, Any]) -> Any | None:
    """Printed 'one creature' includes allies and self; retain harmful Charm gates.

    Only an owned compiled note opts in. Native recipient admission still checks
    range, knowledge, hearing and defenses for every offered recipient.
    """
    if (action.parameters.get("typed") or {}).get("source") not in CREATURE_NOTES:
        return None
    return action.model_copy(update={"target_kind": "ANY_CREATURE",
                                     "parameters": {**action.parameters, "harmful": True}})


@hook("damage_type_choice")
def music_damage_choice(ctx: Any, kinds: list[str], targets: list[Any]) -> str | None:
    """One type per activation, shared by full/half damage and every cone recipient.

    AI keeps the printed first type: this preference reads no private defenses,
    save results or unobserved creatures. Both types remain available to players.
    """
    source = str(ctx.typed.get("source") or "")
    if source not in DAMAGE_NOTES:
        return None
    key = "music_damage_type"
    if key in ctx.damage_cache:
        return ctx.damage_cache[key]
    from .needle import ask
    from .choice_prompt import action_context
    from ..target_knowledge import located

    known = [t for t in targets if located(ctx.engine, ctx.actor, t)]
    audience = ", ".join(t.display_name for t in known) or "creatures affected by this note"
    subject = ctx.target if ctx.target in known else None
    presentation = action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id,
                                  subject or ctx.actor, action=ctx.action)
    if subject is None:
        presentation["affected_id"] = ""
    chosen = ask(ctx.engine, ctx.intent, "TECHNIQUE_USE", ctx.actor,
                 "choice:needle.music_damage_type", kinds,
                 labels={kind: kind.title() + " damage" for kind in kinds},
                 preferred=kinds[:1], name=ctx.action.display_name + " damage", feature_id=source,
                 prompt_context=presentation,
                 prompt=f"{ctx.action.display_name}: choose the damage type for {audience}. "
                        "This type applies to all creatures affected by this use, including half damage on a successful save. "
                        "The choice has no additional cost beyond the action's Cultivation Points (CP).")
    ctx.damage_cache[key] = chosen[0] if chosen else kinds[0]
    return ctx.damage_cache[key]


@hook('decision_text')
def hymn_choice_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, str] | None:
    if context.get('reaction_source_id') != 'choice:needle.music_healing_hymn':
        return None
    actor = engine.state.actors.get(context.get('reactor_id'))
    if actor is None or _action(engine, actor, HYMN) is None:
        return None
    return {'feature_id': HYMN, 'cost': 'No additional resource or Reaction cost',
            'table_note': 'The activation cost was paid when Healing Hymn began. This turn-end healing choice is free.'}


def _measure(actor: Any) -> Any | None:
    return next((c for c in actor.conditions.values() if c.condition_id == MEASURE), None)


def _rules(actor: Any) -> list[dict[str, Any]]:
    from ..typed_executor import condition_rules

    return condition_rules(actor)


def _owns(engine: Any, actor: Any, feature: str) -> bool:
    return any(feature in str(a) for a in (*actor.action_ids, *actor.reaction_ids, *actor.passive_ids)) or \
        any(str(row.get("feature_id") or "") == feature for store in ("typed_passive_rows", "typed_reaction_rows")
            for row in (getattr(engine, store, {}) or {}).get(actor.entity_id, []))


def _context(engine: Any, owner: Any, action: Any, subject: Any) -> Any:
    from ..typed_executor import Context

    typed = dict(((action.parameters or {}).get("typed") or {}) if action is not None else {})
    from .rider_choices import intent_for
    return Context(engine, owner, action, intent_for(engine), typed, [subject], subject, {})


def _action(engine: Any, actor: Any, feature: str) -> Any | None:
    return engine.action_catalog.get(next((a for a in actor.action_ids if feature in a), ""))


def _nearest(engine: Any, origin: Any, pool: list[Any]) -> list[Any]:
    return sorted(pool, key=lambda other: (engine._distance_actor_to_actor(origin, other), other.entity_id))


# ------------------------------------------------------------------------------------------------ the Measure
@effect("music_measure")
def keep_the_measure(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import clock_expiry

    engine, actor = ctx.engine, ctx.actor
    engine._remove_condition(actor, MEASURE, ctx.source)
    engine._apply_condition(actor, MEASURE, ctx.source, actor.entity_id, expires_on=clock_expiry(engine, "minutes", 1) or "UNTIL_REMOVED",
                            data={"label": "Keeping the Measure"})


@hook("event")
def measure_broken(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED":
        return
    subject = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    condition_id = str((kwargs.get("payload") or {}).get("condition_id") or "")
    if subject is not None and condition_id.endswith(ENDERS) and _measure(subject) is not None:
        engine._remove_condition(subject, MEASURE, condition_id)
        note(engine, f"passive:{KEEP}", subject, f"{subject.display_name}'s Measure ends ({condition_id.rsplit('.', 1)[-1]}).")


@hook("candidate_allowed")
def phrases_need_the_measure(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    source = str(typed.get("source") or getattr(action, "source_definition_id", ""))
    if OPENING in source:
        if _measure(actor) is None:
            return False
        target = next(iter(getattr(candidate, "target_ids", None) or ()), actor.entity_id)
        subject = engine.state.actors.get(target)
        return False if subject is not None and subject.turn_flags.get("_round_music_opening_received") == engine.state.round_number else None
    if HARMONIZING in source and any(row.get("type") == "temp_hp" for row in typed.get("effects") or []):
        # "If none apply, the target gains Temporary HP equal to twice your Proficiency Bonus."
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), actor.entity_id))
        if target is not None and any(c.condition_id.endswith((".frightened", ".charmed")) for c in target.conditions.values()):
            return False
    return None


@hook("row_allowed")
def guard_needs_the_measure(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    return False if str(row.get("feature_id") or "") == GUARD and _measure(actor) is None else None


@hook("ally_row_allowed")
def warning_before_first_action(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    """Bell of Warning's attack benefit requires a hearing creature that has not acted.

    Read the replayed journal, including prior rounds, rather than a turn flag
    that resets. Turn start and off-turn reactions do not themselves count as
    acting; accepted movement/actions and ending a turn do. Free setting-only
    selectors are bookkeeping. No new saved state is needed.
    """
    if row.get("feature_id") != BELL:
        return None
    from ..typed_executor import cant_hear
    from .setting_choices import is_setting_action

    if cant_hear(subject):
        return False
    for event in engine.events:
        if event.actor_id != subject.entity_id:
            continue
        if event.event_type == "TURN_ENDED":
            return False
        if event.event_type == "INTENT_ACCEPTED" and (event.payload or {}).get("kind") in (
                "ACTION", "BONUS_ACTION", "MOVE", "HOLD_POSITION", "END_TURN"):
            if not is_setting_action(engine.action_catalog.get(event.source_definition_id)):
                return False
    return None


BELL_ROUND = "_round_music_bell_of_warning"


@hook("effect_allowed")
def bell_ac_needs_an_attack(ctx: Any, effect: dict[str, Any]) -> bool | None:
    """Bell of Warning: "+2 AC against the triggering attack" belongs to the attack that triggered it.

    The bell also answers a creature rolling Initiative, and there is no attack to add the Armour Class to:
    the row is left alone and one plain line says so (the bell's Initiative benefit is a separate reminder).
    Only the bell's own row is touched.
    """
    if effect.get("type") != "ac_bonus" or effect.get("duration") != "triggering_attack":
        return None
    if BELL not in str(ctx.source):
        return None
    if ctx.typed.get("triggering_attack_spec") is not None:
        return None
    note(ctx.engine, f"passive:{BELL}", ctx.actor, BELL_INITIATIVE_TRIGGER)
    return False


BELL_INITIATIVE_TRIGGER = ("Bell of Warning was rung as a creature rolled Initiative, so there was no attack for "
                           "its +2 Armour Class to answer; nothing changed that time.")


@hook("row_allowed")
def bell_once_per_round(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """Bell of Warning: "Use Bell of Warning once per round."

    A Reaction is otherwise one per turn, so the singer could ring it on someone
    else's turn and again on their own inside the same round. The round number is
    kept on the singer (an integer turn flag, saved with the fight), and the flag
    is spent when the Reaction resolves.
    """
    if row.get("feature_id") != BELL:
        return None
    return False if actor.turn_flags.get(BELL_ROUND) == engine.state.round_number else None


@hook("event")
def bell_spent_this_round(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "REACTION_RESOLVED" or kwargs.get("source_definition_id") != BELL:
        return
    actor = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if actor is not None:
        actor.turn_flags[BELL_ROUND] = int(engine.state.round_number)


@effect("music_opening_save")
def opening_save(ctx: Any, eff: dict[str, Any]) -> None:
    """Opening Phrase: "the target adds your Proficiency Bonus to one saving throw against Charmed or Frightened before the start of your next
    turn" (``save`` below uses it up); with ``"concentration": true``, "... to one Concentration saving throw before the start of your next
    turn" (rider lane C14: the all-source ``save_bonus`` seam adds it to the engine's own Concentration save, and the SAVE_ROLLED event
    of that save uses it up)."""
    subject = ctx.target or ctx.actor
    pb = int(ctx.numbers.get("pb") or 2)
    ctx.engine._remove_condition(subject, OPENING_SAVE, ctx.source)
    if eff.get("concentration"):
        ctx.engine._remove_condition(subject, OPENING_CONCENTRATION, ctx.source)
    label = f"+{pb} to one Concentration saving throw" if eff.get("concentration") else f"+{pb} to one save against Charmed or Frightened"
    ctx.engine._apply_condition(subject, OPENING_SAVE, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": label, "bonus": pb, **({"concentration": 1} if eff.get("concentration") else {})})


def _concentration_bonus(subject: Any) -> Any | None:
    return next((c for c in subject.conditions.values() if (c.condition_id == OPENING_CONCENTRATION or (c.condition_id == OPENING_SAVE and (c.data or {}).get("concentration")))), None)


@hook("save_bonus_details")
def opening_concentration_bonus(engine: Any, target: Any, ability: str, dc: Any, source_id: Any, intent: Any) -> dict[str, Any] | None:
    from ..gate2_engine import SYSTEM_CONCENTRATION

    held = _concentration_bonus(target) if source_id == SYSTEM_CONCENTRATION else None
    if held is None:
        return None
    bonus = int((held.data or {}).get("bonus") or 0)
    # The general save receipt freezes proposals before d20 rewrites. Qualify
    # this contribution by instance so a replacement granted mid-save survives.
    return {"bonus": bonus, "contributions": {f"music_opening:{held.instance_id}": bonus}} if bonus else None


@hook('concentration_save_sources')
def opening_concentration_source(engine: Any, target: Any) -> list[dict[str, str]] | None:
    """Attribute the same actual Opening Phrase bonus used by the native save."""
    held = _concentration_bonus(target)
    if held is None or int((held.data or {}).get('bonus') or 0) <= 0:
        return None
    if not held.source_actor_id or not held.source_definition_id:
        return None
    return [{'actor_id': held.source_actor_id, 'source_id': held.source_definition_id}]


@hook("event", nested=True)
def opening_concentration_used(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The Concentration save that got the bonus uses it up."""
    if event_type != "SAVE_ROLLED":
        return
    from ..gate2_engine import SYSTEM_CONCENTRATION

    # Earlier event hooks may append conditions/logs (or roll another save). Match the delivered
    # roll, rather than the mutable event tail or simply the latest SAVE_ROLLED.
    roll_id = (kwargs.get("payload") or {}).get("roll_id")
    if not roll_id:
        return
    rolled = next((event for event in reversed(engine.events)
                   if event.event_type == event_type and event.actor_id == kwargs.get("actor_id")
                   and (event.payload or {}).get("roll_id") == roll_id), None)
    if rolled is None or rolled.source_definition_id != SYSTEM_CONCENTRATION:
        return
    subject = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if subject is None:
        return
    contributions = (rolled.payload or {}).get("save_bonus_contributions") or {}
    for iid, condition in list(subject.conditions.items()):
        if (condition.condition_id == OPENING_CONCENTRATION
                or (condition.condition_id == OPENING_SAVE and (condition.data or {}).get("concentration"))) \
                and contributions.get(f"music_opening:{iid}"):
            del subject.conditions[iid]
            engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=subject.entity_id,
                                 target_ids=(subject.entity_id,), payload={"condition_id": condition.condition_id, "instance_id": iid, "reason": "CONSUMED"})


@hook("save")
def music_save_bonus(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    wanted = {str(name).lower() for name in named or ()}
    bonus = 0
    if wanted & {"charmed", "frightened"}:
        held = next((iid for iid, c in subject.conditions.items() if c.condition_id == OPENING_SAVE
                     and not (c.data or {}).get("concentration")), None)
        if held is not None:
            condition = subject.conditions.pop(held)
            bonus += int((condition.data or {}).get("bonus") or 0)
            ctx.engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                                     payload={"condition_id": OPENING_SAVE, "instance_id": held, "reason": "CONSUMED"})
    for rule in _rules(subject):
        for name, amount in (rule.get("music_save_bonus") or {}).items():
            if name in wanted:
                bonus += int(amount)
    return {"bonus": bonus, "modes": []} if bonus else None


@effect("music_opening_concentration")
def opening_concentration(ctx: Any, eff: dict[str, Any]) -> None:
    """Adapt the C13 saved row to the single Opening Phrase implementation."""
    opening_save(ctx, {**eff, "concentration": True})


# ------------------------------------------------------------------------------------------------ marks on the audience
@effect("music_mark")
def music_mark(ctx: Any, eff: dict[str, Any]) -> None:
    """``{"type": "music_mark", "mark": "<slug>", "range_ft": 30, "count": "pb"|None, "rule": {...}}``: the user and its allies within range
    carry the mark until the user's Concentration ends; for ``count`` the owner chooses recipients. A creature carries one of each mark (a new singer's
    replaces another's)."""
    engine, actor = ctx.engine, ctx.actor
    from .music_insights import owned, ENSEMBLE
    condition_id = f"condition:typed.{eff['mark']}"
    reach = int(eff.get("range_ft") or 30)
    pool = [a for a in engine.state.actors.values() if a.active and a.team_id == actor.team_id and engine._distance_actor_to_actor(actor, a) <= reach]
    if eff['mark'] == 'music_shared_measure':
        from ..typed_executor import cant_hear
        from ..target_knowledge import located
        from ..targeting import line_of_effect
        pool = [a for a in engine.state.actors.values() if a.active
                and engine._distance_actor_to_actor(actor, a) <= reach
                and line_of_effect(engine, actor, target=a)
                and (located(engine, a, actor) or not cant_hear(a))]
    chosen = [actor, *[a for a in _nearest(engine, actor, pool) if a is not actor]]
    if eff.get("count") == "pb":
        from .rider_choices import pick
        capacity = max(1, int(ctx.numbers.get("pb") or 2)) + (
            1 if eff["mark"] == "music_shared_measure" and owned(engine, actor, ENSEMBLE) else 0)
        selected = pick(engine, actor, "music_audience", ctx.action.display_name, [a.entity_id for a in chosen],
                        labels={a.entity_id: f"Affect {a.display_name}" for a in chosen}, subject=actor,
                        trigger=ctx.action.display_name, maximum=capacity,
                        choose=(f"Choose up to {capacity} willing creatures that can perceive you."
                                if eff["mark"] == "music_shared_measure" else "Choose an option."),
                        preferred=[a.entity_id for a in chosen if a.team_id == actor.team_id], intent=ctx.intent,
                        automatic_options=[a.entity_id for a in chosen if a.team_id == actor.team_id and located(engine, actor, a)]
                        if eff['mark'] == 'music_shared_measure' else None)
        chosen = [engine.state.actors[aid] for aid in selected]
    expires = "CONCENTRATION_END" if (ctx.typed.get("duration") or {}).get("concentration") else "UNTIL_REMOVED"
    for subject in chosen:
        if eff["mark"] == "music_shared_measure" and subject is not actor:
            from .willing_targets import asks_consent
            if not asks_consent(engine, ctx.intent, subject, "Shared Measure",
                                f"{actor.display_name} offers Shared Measure to {subject.display_name}. Accept this shared performance? No Reaction cost.",
                                prefer_accept=subject.team_id == actor.team_id, asker=actor):
                continue
        engine._remove_condition(subject, condition_id, ctx.source)
        engine._apply_condition(subject, condition_id, ctx.source, actor.entity_id, expires_on=expires,
                                data={"label": str(eff.get("label") or eff["mark"].replace("_", " ").title()), "rule": dict(eff.get("rule") or {})})


@effect("music_ally_rule")
def music_ally_rule(ctx: Any, eff: dict[str, Any]) -> None:
    """Soul-Stirring Refrain's Courage and Calm: the target carries the emotion's rule while the Concentration lasts.

    ``repeat_save`` is the printed "At the end of each of its turns, an unwilling target repeats the
    saving throw, ending the effect on itself on a success": the engine reads it off the condition
    (gate2_engine), so a bearer that was made to save can shed the emotion at the end of its own turn.
    A row without it -- every mark that is not behind that printed save -- is unchanged.
    """
    subject = ctx.target or ctx.actor
    condition_id = f"condition:typed.{eff['mark']}"
    data: dict[str, Any] = {"label": eff["mark"].replace("music_", "").title(), "rule": dict(eff.get("rule") or {})}
    if eff.get("repeat_save"):
        data["repeat_save"] = {**eff["repeat_save"], "dc": int(ctx.numbers.get("save_dc") or 10)}
    ctx.engine._remove_condition(subject, condition_id, ctx.source)
    ctx.engine._apply_condition(subject, condition_id, ctx.source, ctx.actor.entity_id, expires_on="CONCENTRATION_END", data=data)


def _marked(actor: Any, slug: str) -> Any | None:
    return next((c for c in actor.conditions.values() if c.condition_id == f"condition:typed.{slug}"), None)


@hook("speed")
def music_speed(engine: Any, actor: Any) -> int:
    rules = _rules(actor)
    halved = -(int(actor.speed_ft) // 2) if any(rule.get("music_speed_halved") for rule in rules) else 0  # Soul-Stirring Refrain, Sorrow
    return sum(int(rule.get("music_speed") or 0) for rule in rules) + halved


@hook("ac")
def music_ac(engine: Any, target: Any) -> int:
    return sum(int(rule.get("music_ac") or 0) for rule in _rules(target))


@hook("attack_bonus")
def music_weapon_attack(ctx: Any, actor: Any) -> int | None:
    if (ctx.typed or {}).get("weapon") is None:
        return None
    return sum(int(rule.get("music_weapon_attack") or 0) for rule in _rules(actor)) or None


@hook("difficult_exempt")
def dissonance_spares_friends(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    """Court of Resonant Measure, Dissonant Court: "Enemies inside ... suffer: difficult terrain"."""
    from .. import zones

    out: set[tuple[int, int]] = set()
    for zone in zones.typed_zones(engine):
        rows = [row for row in zone.trigger_profile.get("inside") or []
                if (row.get("rule") or {}).get("music_dissonant")]
        if zone.active and rows and not any(zones.continuous_rule_applies(engine, zone, actor, row) for row in rows):
            out |= {(cell.x, cell.y) for cell in zone.affected_cells}
    return out or None


# ------------------------------------------------------------------------------------------------ hits
@hook("after_hit")
def music_hits(ctx: Any, target: Any, kind: str) -> None:
    from ..typed_executor import run_effects
    from .rider_choices import pick, step
    from ..target_knowledge import located

    engine, actor = ctx.engine, ctx.actor
    if target is None:
        return
    weapon = kind in ("weapon", "unarmed")
    rows: list[dict[str, Any]] = []
    hymn = next((c for c in actor.conditions.values() if c.condition_id == HYMN_MARK), None)
    if weapon and hymn is not None and not actor.turn_flags.get("music_weapon_hymn_once"):
        actor.turn_flags["music_weapon_hymn_once"] = True
        rows.append({"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 6},
                     "damage_types": [str((hymn.data or {}).get("damage_type") or "thunder")], "evidence": "Weapon Hymn: +1d6"})
    if rows and target.active:
        run_effects(_context(engine, actor, ctx.action, target), rows)
    if (ctx.typed or {}).get("weapon") is not None and _marked(actor, "music_march") is not None and not actor.turn_flags.get("music_march_once"):
        if step(engine, actor, "music_march_step", "March of the Immortal Host", target, 5, f"passive:{MARCH}", ctx.intent):
            actor.turn_flags["music_march_once"] = True
    shared = _marked(actor, "music_shared_measure")
    if shared is not None:
        owner = engine.state.actors.get(shared.source_actor_id or "")
        key = "_round_music_shared"
        if owner is not None and owner.turn_flags.get(key) != engine.state.round_number:
            others = [a for a in engine.state.actors.values() if a.active and a is not actor and _marked(a, "music_shared_measure") is not None
                      and _marked(a, "music_shared_measure").source_actor_id == owner.entity_id]
            if others:
                others = _nearest(engine, target, others)
                chosen = pick(engine, owner, "music_shared_target", "Shared Measure", [a.entity_id for a in others],
                              labels={a.entity_id: f"Offer a 5-foot step to {a.display_name}" for a in others},
                              subject=target, trigger=f"{actor.display_name}'s {ctx.action.display_name} hits {target.display_name}",
                              preferred=[a.entity_id for a in others if a.team_id == owner.team_id][:1], intent=ctx.intent,
                              automatic_options=[a.entity_id for a in others if a.team_id == owner.team_id and located(engine, owner, a)])
                if chosen:
                    mover = engine.state.actors[chosen[0]]
                    if step(engine, mover, "music_shared_step", "Shared Measure", target, 5, f"passive:{SHARED}", ctx.intent):
                        owner.turn_flags[key] = engine.state.round_number


@effect("music_weapon_hymn")
def weapon_hymn(ctx: Any, eff: dict[str, Any]) -> None:
    """Weapon Hymn: the touched wielder's weapon and unarmed hits carry the hymn (one at a time) until the Concentration ends."""
    subject = ctx.target or ctx.actor
    ctx.engine._remove_condition(subject, HYMN_MARK, ctx.source)
    ctx.engine._apply_condition(subject, HYMN_MARK, ctx.source, ctx.actor.entity_id, expires_on="CONCENTRATION_END",
                                data={"label": f"Weapon Hymn ({eff.get('damage_type', 'thunder').title()})", "damage_type": eff.get("damage_type", "thunder")})


# ------------------------------------------------------------------------------------------------ turns
def _heal(engine: Any, owner: Any, feature: str, subject: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    action = _action(engine, owner, feature)
    if action is not None:
        run_effects(_context(engine, owner, action, subject), [row])


@hook("turn_end")
def songs_heal(engine: Any, actor: Any) -> None:
    if not actor.active:
        return
    from ..concentration import concentrating_on
    from .rider_choices import pick

    hymn = _action(engine, actor, HYMN)
    if hymn is not None and concentrating_on(actor, hymn.source_definition_id):
        pool = [a for a in engine.state.actors.values() if a.active
                and engine._distance_actor_to_actor(actor, a) <= 30 and not actor.turn_flags.get(f"_round_music_hymn:{a.entity_id}")]
        if pool:
            preferred = min(pool, key=lambda a: (a.team_id != actor.team_id, a.current_hp / max(1, a.maximum_hp), a.entity_id))
            chosen = pick(engine, actor, "music_healing_hymn", "Healing Hymn", [a.entity_id for a in pool],
                          labels={a.entity_id: f"Heal {a.display_name}" for a in pool}, subject=actor,
                          trigger=f"{actor.display_name} ends its turn", preferred=[preferred.entity_id],
                          automatic=preferred.team_id == actor.team_id and preferred.current_hp < preferred.maximum_hp,
                          prompt_context={"cost": "No additional cost; the performance is already active",
                                          "source_definition_id": hymn.source_definition_id,
                                          "action_name": "End turn", "action_actor_id": actor.entity_id})
            subject = engine.state.actors[chosen[0]] if chosen else None
        else:
            subject = None
        if subject is not None:
            actor.turn_flags[f"_round_music_hymn:{subject.entity_id}"] = True
            note(engine, f"passive:{HYMN}", actor, f"Healing Hymn: {subject.display_name} regains HP.", (subject.entity_id,))
            _heal(engine, actor, HYMN, subject, {"type": "healing", "applies_to": "target", "dice_by_cl": [[1, 10, 1, 8], [11, 16, 2, 8], [17, 20, 3, 8]],
                                                  "formula": "key_ability_modifier"})
    from .. import zones

    for zone in zones.typed_zones(engine):
        if not zone.active or zone.owner_id != actor.entity_id or SYMPHONY not in str(zone.source_definition_id) or \
                not any((row.get("rule") or {}).get("music_mercy") for row in zone.trigger_profile.get("inside") or []):
            continue
        key = f"_round_music_mercy:{zone.zone_id}:"  # "only once during the Symphony" (a "_round_" flag is kept for the fight)
        pool = [a for a in engine.state.actors.values() if a.active and a.team_id == actor.team_id and a.current_hp < a.maximum_hp
                and not actor.turn_flags.get(key + a.entity_id) and zones._inside(engine, a, zone)]
        pool = sorted(pool, key=lambda a: (a.current_hp / max(1, a.maximum_hp), a.entity_id))
        chosen = pick(engine, actor, "music_symphony_mercy", "Symphony of Heaven and Earth: Mercy", [a.entity_id for a in pool],
                      labels={a.entity_id: f"Heal {a.display_name}" for a in pool}, subject=actor,
                      trigger=f"{actor.display_name} ends its turn", maximum=max(1, int(actor.proficiency_bonus)),
                      preferred=[a.entity_id for a in pool[:max(1, int(actor.proficiency_bonus))]],
                      prompt_context={"cost": "No additional cost; the performance is already active",
                                      "source_definition_id": zone.source_definition_id,
                                      "action_name": "End turn", "action_actor_id": actor.entity_id}) if pool else []
        for target_id in chosen:
            subject = engine.state.actors[target_id]
            actor.turn_flags[key + subject.entity_id] = True
            _heal(engine, actor, SYMPHONY, subject, {"type": "healing", "applies_to": "target", "dice": {"count": 2, "sides": 8},
                                                     "formula": "key_ability_modifier"})
        if chosen:
            note(engine, f"passive:{SYMPHONY}", actor, "Symphony of Heaven and Earth, Movement of Mercy: allies inside regain HP.")


# ------------------------------------------------------------------------------------------------ Opening Phrase, War Song
@hook("technique_used")
def music_used(ctx: Any) -> None:
    source = str((ctx.typed or {}).get("source") or ctx.source)
    if OPENING in source:
        target = ctx.target or ctx.actor
        ctx.actor.turn_flags[f"_round_music_opening:{target.entity_id}"] = ctx.engine.state.round_number
        target.turn_flags["_round_music_opening_received"] = int(ctx.engine.state.round_number)


# ------------------------------------------------------------------------------------------------ Rallying Song
def _rallying_holders(engine: Any) -> list[Any]:
    from ..concentration import concentrating_on
    from .d20_rewrite import Holder

    found = []
    for actor_id, actor in sorted(engine.state.actors.items()):
        action = _action(engine, actor, RALLY) if actor.active else None
        if action is not None and concentrating_on(actor, action.source_definition_id):
            found.append(Holder(actor, RALLY, {}, RALLY, {"pb": int(actor.proficiency_bonus)}))
    return found


def _rallying_guard(engine: Any, holder: Any, rc: Any) -> bool:
    mark = _marked(rc.roller, "music_rallying_song")
    return bool({"charmed", "frightened"} & set(rc.named)) and mark is not None and mark.source_actor_id == holder.actor.entity_id


def _register_rallying() -> None:
    from .d20_rewrite import Rule, register

    register(Rule("music_rallying_song", "Rallying Song", rolls=("save",), who="team", range_ft=1000, when="failed", op="choose",
                  choose=lambda engine, holder, rc: rc.natural, bonus=lambda engine, holder, rc: int(holder.numbers.get("pb") or 2),
                  limit="round", checkpoint="D20_REROLL_ALLY", finder=_rallying_holders, guard=_rallying_guard))


_register_rallying()


# ------------------------------------------------------------------------------------------------ Immortal Funeral Bell
def _bell_ringing(engine: Any) -> list[tuple[Any, Any]]:
    """Every (singer, bell action) pair whose Immortal Funeral Bell is sounding right now."""
    from ..concentration import concentrating_on

    ringing = []
    for actor in engine.state.actors.values():
        if not actor.active:
            continue
        action = _action(engine, actor, FUNERAL_BELL)
        if action is not None and concentrating_on(actor, action.source_definition_id):
            ringing.append((actor, action))
    return ringing


def _covered_by_the_bell(engine: Any, subject: Any) -> bool:
    """Whether an Immortal Funeral Bell is ringing over ``subject`` at this moment.

    The printed membership is "Enemies inside" a 60-foot-radius aura centred on the singer, so it is
    read now rather than remembered: the bell has to be sounding (its singer holds its printed
    Concentration), the creature has to be one of the bell's enemies, and it has to be inside the
    printed radius around that singer. A creature that walks out from under the bell is no longer
    inside it, and one that walks in is.
    """
    from ..relations import ENEMY, relation

    if not subject.active:
        return False
    for singer, action in _bell_ringing(engine):
        radius = int(getattr(action, "radius_ft", None) or 60)  # the printed 60-foot-radius aura
        if relation(engine, singer, subject) == ENEMY and engine._distance_actor_to_actor(singer, subject) <= radius:
            return True
    return False


@hook("healing_pending")
def funeral_bell_one_heal_a_round(engine: Any, subject: Any, amount: int, healer: Any, source: Any, kind: str) -> int | None:
    """Immortal Funeral Bell: enemies inside "cannot regain HP more than once per round".

    The first Hit Point grant that lands on an enemy the bell is ringing over spends that enemy's one
    healing for the round (an integer turn flag, saved with the fight); a later grant to the same
    creature in the same round is cut off entirely. Allies, Temporary Hit Points, healing of 0
    points and a bell that is not ringing are untouched.
    """
    if kind != "hp" or amount <= 0 or not subject.active:
        return None
    if not _covered_by_the_bell(engine, subject):
        return None
    return amount if subject.turn_flags.get(FUNERAL_HEALED) == engine.state.round_number else None


@hook("event")
def funeral_bell_spent_healing(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Remember the one healing a round the bell allows each enemy it covers."""
    if event_type != "HEALING_APPLIED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("after") or 0) <= int(payload.get("before") or 0):
        return
    for target_id in kwargs.get("target_ids") or ():
        subject = engine.state.actors.get(target_id)
        if subject is not None and _covered_by_the_bell(engine, subject):
            subject.turn_flags[FUNERAL_HEALED] = int(engine.state.round_number)


# ------------------------------------------------------------------------------------------------ Soul-Stirring Refrain: Fury
FURY_DAMAGE = "typed_once_turn:music_fury_damage"  # "each turn": the shared clock every creature's turn resets
FURY_RESERVED = "_music_fury_reserved"  # resolution-local (a damage_cache), so a miss hands the roll back


def _fury(actor: Any) -> Any | None:
    return next((c for c in actor.conditions.values() if c.condition_id == "condition:typed.music_fury"), None)


def _fury_bonus(engine: Any, actor: Any) -> int | None:
    """The Proficiency Bonus Fury adds to the bearer's roll -- the singer's -- or None without a mark."""
    fury = _fury(actor)
    if fury is None or actor.turn_flags.get(FURY_DAMAGE):
        return None
    singer = engine.state.actors.get(fury.source_actor_id or "")
    return int(singer.proficiency_bonus) if singer is not None and singer.active else None


def _weapon_damage_roll(ctx: Any, effect: Any) -> bool:
    """Whether this attempt is rolling the damage of a weapon the bearer holds, or of an unarmed strike."""
    if (ctx.typed or {}).get("weapon") is not None:
        return True
    return (effect or {}).get("attack_kind") == "unarmed"


@hook("attack_damage_bonus")
def fury_one_damage_roll_a_turn(ctx: Any, target: Any, effect: Any) -> int | None:
    """Soul-Stirring Refrain, Fury: "The target adds your Proficiency Bonus to one weapon damage roll each turn."

    The answer is added to the roll the attack is already making, so the extra points keep the
    weapon's damage type (its Resistance and Immunity still answer them), the bearer stays the
    attacker of everything the hit causes, and nothing is rolled or resolved twice. The use is
    reserved here and charged by ``attack_result`` for the creature that was really damaged, so a
    miss gives the roll back; the clock is the shared per-turn one (combat/turn_uses.py), which is
    what "each turn" prints -- an Opportunity Attack on someone else's turn has its own roll, and a
    second hit on the same turn does not.
    """
    amount = _fury_bonus(ctx.engine, ctx.actor)
    if amount is None or not _weapon_damage_roll(ctx, effect) or ctx.damage_cache.get(FURY_RESERVED):
        return None
    ctx.damage_cache[FURY_RESERVED] = target.entity_id
    return amount


@hook("attack_result")
def fury_charges_the_reserved_roll(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    """The reserved weapon roll was really made: this turn's Fury is spent."""
    if not hit or ctx.damage_cache.get(FURY_RESERVED) is None:
        return
    if ctx.attack_damage_context is not None:  # a retargeted attempt reports the creature it hit
        target = ctx.engine.state.actors.get(ctx.attack_damage_context.target_id, target)
    if target is not None and ctx.damage_cache.get(FURY_RESERVED) == target.entity_id:
        ctx.actor.turn_flags[FURY_DAMAGE] = True
        ctx.damage_cache.pop(FURY_RESERVED, None)


@hook("after_miss")
def fury_gives_a_missed_roll_back(ctx: Any, target: Any) -> None:
    """No damage roll was made against that creature, so this turn's Fury is still unspent."""
    if ctx.damage_cache.get(FURY_RESERVED) == getattr(target, "entity_id", None):
        ctx.damage_cache.pop(FURY_RESERVED, None)


@hook("attack_mode")
def fury_away_from_the_nearest(ctx: Any, target: Any) -> str | None:
    """Soul-Stirring Refrain, Fury: "has Disadvantage on attack rolls against targets other than the
    nearest creature" -- the bearer's own attacks, whoever it aims them at. Two creatures at the
    same distance are both nearest, so neither of them is penalised."""
    engine, actor = ctx.engine, ctx.actor
    if _fury(actor) is None or target is None or not target.active:
        return None
    others = [other for other in engine.state.actors.values() if other.active and other is not actor]
    if not others:
        return None
    nearest = min(engine._distance_actor_to_actor(actor, other) for other in others)
    return None if engine._distance_actor_to_actor(actor, target) <= nearest else "DISADVANTAGE"
