"""Dream Eater (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "09. Dream Eater": Nightmare Scars, Dream Morsels, CL3 Dream Walker, CL6
Nightmare Touch, CL10 Stolen Dreams, CL14 Sleeping Curse, CL18 Dream Eater Ascension). No Spheres 5e or D&D 5.5e counterpart.
Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json; every hook returns early without them
(the Nightmare Scar's save rule reads the Scar condition itself, placed only by a Dream Eater).

What runs:
  * Nightmare Scar (mark "Nightmare Scar", one from you at a time): the first save the scarred creature makes in the fight against
    Frightened, sleep (Unconscious) or one of its scarrer's Dream Eater features has Disadvantage; the Scar stays but that is spent
    (the fight is the Long Rest's span).
  * Dream Morsels (``resource:named.dream_morsel``, maximum Proficiency Bonus, 0 at the start): +1 the first time in the fight a
    hostile creature fails a save against your Dream Eater feature while Unconscious, Incapacitated, Frightened or bearing your Scar
    (once per creature per fight); Nightmare Touch also gives one when its target was one of those.
  * Dream Walker (action use, 60 feet, 1 Resonance): only a sleeping (Unconscious) or Resonance Marked creature; a failed Wisdom save
    places your Resonance Mark (the rest is the dream conversation: the GM's).
  * Nightmare Touch: 30 feet against a sleeping or Resonance Marked creature, touch otherwise. Feed on Resistance: when an already
    scarred hostile creature succeeds on the save, you may spend 1 Dream Morsel to impose your Spiritual Pressure and keep the Scar's
    first-save Disadvantage unspent (asked).
  * Predatory Trace: a diagnosis of a creature bearing your Nightmare Touch Scar (Soul Gaze, and any later Read the Spirit or
    dream-diagnosis producer through the general ``diagnosis_reveal`` hook) names your spiritual signature unless you defeat it
    with a Cultivation Check against the diagnosis's Source DC.
  * Stolen Dreams (once per turn, 2 Resonance or 1 Dream Morsel): when a creature bearing your Scar fails a save against Mind Spike,
    Domain Pressure or a Dream Eater feature, you steal a Dream Fragment (asked; the AI pays when it can) -- up to your Wisdom
    modifier (minimum 1) kept, the oldest released. "Spend a Stolen Dream: confront the dreamer" (Bonus Action): the original
    creature has Disadvantage on its next attack roll or save against you before the end of your next turn.
  * Sleeping Curse (Concentration): Cursed Sleep -- Unconscious and Prone until your Concentration ends or it saves at the end of one
    of its turns; damage gives it an immediate repeat save with Advantage. Once on each of your turns while it sleeps: Feed (1 Dream
    Morsel: 3d10 Psychic, you gain half as Temporary HP) or Maintain Stillness (its next end-of-turn save is skipped; not on
    consecutive turns). Successful save: Drowsy until the end of its next turn (Speed halved, no Reactions, your Spiritual Pressure).
  * Dream Eater Ascension: only a sleeping, Incapacitated, Cursed-Sleeping, or Scarred-and-Resonance-Marked creature; spend up to 3
    Dream Morsels (asked; with 2+ the save has Disadvantage against a sleeping or helpless target). Failed save: 10d10 Psychic, a
    Consumption (asked; Defining Hope -- Disadvantage on its saves against Frightened for the rest of the fight -- runs, the others
    are the GM's) and a Devoured Dream: Temporary HP equal to half the damage. Successful save: half, your Spiritual Pressure and a
    free Dream Fragment.

Plug-in surface: effects dream_walker_mark, dream_touch, dream_cursed_sleep, dream_feed, dream_stillness, dream_confront,
dream_ascension; hooks compile_actions, save, after_save_resolved, turn_end, event, candidate_allowed, attack_mode,
diagnosis_reveal.
Shared helpers used: spirit_traditions (row/feature_of/context/pick_creature), needle.ask.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.dream_eater.feature."
WALKER = TRADITION + "dream_walker"
TOUCH = TRADITION + "nightmare_touch"
STOLEN = TRADITION + "stolen_dreams"
CURSE = TRADITION + "sleeping_curse"
ASCENSION = TRADITION + "dream_eater_ascension"
SCAR = "Nightmare Scar"
MORSEL = "resource:named.dream_morsel"
RESONANCE = "resource:core.resonance"
FRAGMENT = "condition:typed.stolen_dream"
CONFRONTED = "condition:typed.dream_confronted"
CURSED = "condition:typed.cursed_sleep"
HOPELESS = "condition:typed.devoured_hope"
MIND_SPIKE = "tianxia.path.spirit_awakening.feature.mind_spike"
DOMAIN_PRESSURE = "tianxia.path.spirit_awakening.feature.domain_pressure"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _remove(engine: Any, holder: Any, condition: Any, reason: str) -> None:
    for iid, held in list(holder.conditions.items()):
        if held is condition:
            holder.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=held.source_actor_id,
                                 target_ids=(holder.entity_id,), payload={"condition_id": held.condition_id, "instance_id": iid, "reason": reason})


def _is_dream_feature(action: Any) -> bool:
    return st.feature_of(action).startswith(TRADITION)


def _scars(creature: Any) -> list[Any]:
    prefix = _te().mark_condition_id(SCAR, "")
    return [c for c in creature.conditions.values() if c.condition_id.startswith(prefix)]


def scarred_by(creature: Any, owner: Any) -> bool:
    return _te().bears_mark(creature, owner.entity_id, SCAR)


def _asleep(creature: Any) -> bool:
    return any(_is_sleep_effect(c) for c in creature.conditions.values())


def _is_sleep_effect(condition: Any) -> bool:
    """Recognize sleep-owned states without waking unrelated unconscious creatures."""
    if condition.condition_id in (CURSED, "condition:typed.nightmare_sleep"):
        return True
    if condition.condition_id != "condition:typed.unconscious":
        return False
    data = condition.data or {}
    label = str(data.get("label") or "").lower()
    source = str(condition.source_definition_id or "").lower()
    return "sleep" in label or any(word in source for word in ("sleep", "dream", "nightmare"))


def _helpless(creature: Any) -> bool:
    from ..typed_executor import condition_rules

    return _asleep(creature) or any(rule.get("no_actions") for rule in condition_rules(creature))


def _frightened(creature: Any) -> bool:
    return any(c.condition_id == "condition:typed.frightened" for c in creature.conditions.values())


def _gain_morsel(engine: Any, owner: Any, creature: Any, source: str) -> None:
    """One Dream Morsel from a creature per fight, up to the pool's maximum."""
    if MORSEL not in owner.resources or any(c.condition_id == "condition:typed.dream_morsel_taken" and (c.data or {}).get("from") == creature.entity_id
                                            and c.source_actor_id == owner.entity_id for c in owner.conditions.values()):
        return
    engine._apply_condition(owner, "condition:typed.dream_morsel_taken", source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"from": creature.entity_id, "label": f"Dream Morsel already taken from {creature.display_name} this fight"})
    if owner.resources.get(MORSEL, 0) < owner.resource_maximums.get(MORSEL, 0):
        engine._gain_resource(owner, MORSEL, 1, source)
        note(engine, source, owner, f"{owner.display_name} gains a Dream Morsel from {creature.display_name}.", (creature,))


# ------------------------------------------------------------------------------------------------------------- Nightmare Scar
@hook("save")
def scar_first_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    named = {str(n) for n in (named or ())}
    out: dict[str, Any] | None = None
    for scar in _scars(subject):
        data = scar.data or {}
        if data.get("spent"):
            continue
        owner = ctx.engine.state.actors.get(scar.source_actor_id)
        dreamy = owner is not None and ctx.actor is owner and _is_dream_feature(ctx.action)
        if not (dreamy or "frightened" in named or "unconscious" in named):
            continue
        if ctx.engine.__dict__.get("_c8_keep_scar") == subject.entity_id:
            out = {"bonus": 0, "modes": ["DISADVANTAGE"]}
            continue
        _remove(ctx.engine, subject, scar, "SPENT")
        ctx.engine._apply_condition(subject, scar.condition_id, scar.source_definition_id, scar.source_actor_id, expires_on=scar.expires_on,
                                    data={**data, "spent": 1, "label": "Nightmare Scar (its first-save Disadvantage is spent this fight)"})
        out = {"bonus": 0, "modes": ["DISADVANTAGE"]}
    return out


@hook("after_save_resolved")
def morsels_and_theft(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    engine, owner = ctx.engine, ctx.actor
    if subject is None or owner is None or subject.team_id == owner.team_id:
        return
    feature = st.feature_of(ctx.action)
    dreamy = feature.startswith(TRADITION)
    if dreamy and st.row(engine, owner, "dream_walker") is not None and failed and (
            _helpless(subject) or _frightened(subject) or scarred_by(subject, owner)):
        _gain_morsel(engine, owner, subject, feature)
    if feature == TOUCH and not failed and scarred_by(subject, owner) and owner.resources.get(MORSEL, 0) >= 1:
        _feed_on_resistance(ctx, subject)
    if failed and (dreamy or feature in (MIND_SPIKE, DOMAIN_PRESSURE)) and st.row(engine, owner, "stolen_dreams") is not None \
            and scarred_by(subject, owner) and not owner.turn_flags.get("stolen_dreams"):
        _steal(ctx, subject)


def _feed_on_resistance(ctx: Any, subject: Any) -> None:
    from . import needle

    engine, owner = ctx.engine, ctx.actor
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "FEED_ON_RESISTANCE", subject.entity_id), owner,
                        "choice:needle.dream_eater.feed_on_resistance", ["feed"],
                        labels={"feed": f"Spend 1 Dream Morsel: {subject.display_name} suffers your Spiritual Pressure and its Scar keeps "
                                        "its first-save Disadvantage"},
                        prompt=f"Feed on Resistance: {subject.display_name}, scarred, resisted Nightmare Touch.", preferred=["feed"],
                        allow_decline=True, name="Feed on Resistance", feature_id=TOUCH, target_id=subject.entity_id)
    if not chosen:
        return
    engine._spend_resource(owner, MORSEL, 1, TOUCH)
    for scar in _scars(subject):
        if scar.source_actor_id == owner.entity_id and (scar.data or {}).get("spent"):
            _remove(engine, subject, scar, "RESTORED")
            data = {k: v for k, v in (scar.data or {}).items() if k != "spent"}
            engine._apply_condition(subject, scar.condition_id, scar.source_definition_id, scar.source_actor_id, expires_on=scar.expires_on,
                                    data={**data, "label": "Nightmare Scar"})
    _te().run_effects(st.context(engine, owner, ctx.action, [subject], ctx.numbers, ctx.intent), [{"type": "spiritual_pressure", "applies_to": "target"}])


# --------------------------------------------------------------------------------------------------------------- Stolen Dreams
def fragments(owner: Any) -> list[Any]:
    return sorted((c for c in owner.conditions.values() if c.condition_id == FRAGMENT and c.source_actor_id == owner.entity_id),
                  key=lambda c: c.applied_sequence)


def add_fragment(engine: Any, owner: Any, creature: Any, source: str) -> None:
    held = fragments(owner)
    limit = max(1, int(_wis_mod(engine, owner)))
    while len(held) >= limit:
        _remove(engine, owner, held.pop(0), "RELEASED")  # "When you exceed the limit, release one existing fragment"
    engine._apply_condition(owner, FRAGMENT, source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"creature": creature.entity_id, "label": f"Stolen Dream from {creature.display_name}"})


def _wis_mod(engine: Any, owner: Any) -> int:
    for action_id in owner.action_ids:
        action = engine.action_catalog.get(action_id)
        numbers = (((action.parameters or {}).get("typed") or {}).get("numbers") if action is not None else None) or {}
        if "key_mod" in numbers:
            return int(numbers["key_mod"])  # a Spirit Awakener's key ability is Wisdom
    return 1


def _steal(ctx: Any, subject: Any) -> None:
    from . import needle

    engine, owner = ctx.engine, ctx.actor
    ways = [*(["morsel"] if owner.resources.get(MORSEL, 0) >= 1 else []), *(["resonance"] if owner.resources.get(RESONANCE, 0) >= 2 else [])]
    if not ways:
        return
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "STOLEN_DREAMS", subject.entity_id), owner,
                        "choice:needle.dream_eater.stolen_dreams", ways,
                        labels={"morsel": "Steal a Dream Fragment for 1 Dream Morsel", "resonance": "Steal a Dream Fragment for 2 Resonance"},
                        prompt=f"Stolen Dreams: {subject.display_name}, bearing your Nightmare Scar, failed its save. Steal a Dream Fragment?",
                        preferred=["resonance" if "resonance" in ways else ways[0]], allow_decline=True, name="Stolen Dreams", feature_id=STOLEN,
                        target_id=subject.entity_id)
    if not chosen:
        return
    owner.turn_flags["stolen_dreams"] = True
    if chosen[0] == "morsel":
        engine._spend_resource(owner, MORSEL, 1, STOLEN)
    else:
        engine._spend_resource(owner, RESONANCE, 2, STOLEN)
    add_fragment(engine, owner, subject, STOLEN)
    note(engine, STOLEN, owner, f"{owner.display_name} steals a Dream Fragment from {subject.display_name}.", (subject,))


@effect("dream_confront")
def confront(ctx: Any, row: dict[str, Any]) -> None:
    subject = ctx.target
    fragment = next((c for c in fragments(ctx.actor) if subject is not None and (c.data or {}).get("creature") == subject.entity_id), None)
    if fragment is None:
        return
    _remove(ctx.engine, ctx.actor, fragment, "SPENT")
    expires = _te().effect_expiry(ctx, {"duration": {"kind": "until_end_of_your_next_turn"}}, subject, condition=True)
    ctx.engine._apply_condition(subject, CONFRONTED, ctx.source, ctx.actor.entity_id, expires_on=expires,
                                data={"label": f"Confronted with a stolen dream: Disadvantage on its next attack or save against {ctx.actor.display_name}"})


def _consume_confronted(engine: Any, subject: Any, owner_id: str) -> bool:
    held = next((c for c in subject.conditions.values() if c.condition_id == CONFRONTED and c.source_actor_id == owner_id), None)
    if held is None:
        return False
    _remove(engine, subject, held, "CONSUMED")
    return True


@hook("attack_mode")
def confronted_attack(ctx: Any, target: Any) -> str | None:
    if target is None or not _consume_confronted(ctx.engine, ctx.actor, target.entity_id):
        return None
    return "DISADVANTAGE"


@hook("save")
def confronted_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None or not _consume_confronted(ctx.engine, subject, ctx.actor.entity_id):
        return None
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}


# --------------------------------------------------------------------------------------------------------- targets, actions
@hook("candidate_allowed")
def dream_targets(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    feature = st.feature_of(action)
    params = action.parameters or {}
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    te = _te()
    if params.get("dream_confront"):
        return None if target is not None and any((c.data or {}).get("creature") == target.entity_id for c in fragments(actor)) else False
    if params.get("dream_curse_option"):
        sleepers = [c for c in engine.state.actors.values() if any(x.condition_id == CURSED and x.source_actor_id == actor.entity_id for x in c.conditions.values())]
        if not sleepers or actor.turn_flags.get("dream_curse_option"):
            return False
        if params["dream_curse_option"] == "feed" and actor.resources.get(MORSEL, 0) < 1:
            return False
        return None if target is None or target in sleepers else False
    if target is None or feature not in (WALKER, TOUCH, CURSE, ASCENSION):
        return None
    marked = te.bears_mark(target, actor.entity_id, "Resonance")
    if feature == WALKER:
        return None if _asleep(target) or marked else False
    if feature == TOUCH:
        far = engine.grid.distance_ft(actor.position, target.position) > 5
        if _asleep(target) or marked:
            return None if engine.grid.distance_ft(actor.position, target.position) <= 30 else False
        return None if not far else False  # Unmarked, awake targets require touch range.
    if feature == CURSE:
        bloodied = target.current_hp <= target.maximum_hp // 2
        return None if bloodied or _frightened(target) or marked or scarred_by(target, actor) else False
    return None if _helpless(target) or (marked and scarred_by(target, actor)) else False


@hook("compile_actions")
def dream_actions(info: dict[str, Any]) -> list[Any] | None:
    owned = info["owned_ids"]
    out = []
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    base = {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}
    if STOLEN in owned:
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.dream_confront", display_name="Spend a Stolen Dream: confront the dreamer",
            owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60,
            parameters={"typed": {**base, "source": STOLEN, "effects": [{"type": "dream_confront", "applies_to": "target", "harmful": True}]},
                        "expected_damage": 0, "dream_confront": True,
                        "description": "Stolen Dreams (Bonus Action): release a Dream Fragment you stole from this creature: it has Disadvantage on "
                                       "its next attack roll or saving throw against you before the end of your next turn."}))
    if CURSE in owned:
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.dream_feed", display_name="Sleeping Curse: Feed", owner_id=info["actor_id"],
            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60,
            costs=(("resource:named.dream_morsel", 1),),
            parameters={"typed": {**base, "source": CURSE, "effects": [{"type": "dream_feed", "applies_to": "target", "harmful": True}]},
                        "expected_damage": 16, "dream_curse_option": "feed",
                        "description": "Sleeping Curse, once on each of your turns (1 Dream Morsel): the Cursed-Sleeping creature takes 3d10 Psychic "
                                       "damage and you gain Temporary Hit Points equal to half of it; the damage gives it a repeat save with Advantage."}))
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.dream_stillness", display_name="Sleeping Curse: Maintain Stillness",
            owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60,
            parameters={"typed": {**base, "source": CURSE, "effects": [{"type": "dream_stillness", "applies_to": "target", "harmful": True}]},
                        "expected_damage": 0, "dream_curse_option": "stillness",
                        "description": "Sleeping Curse, once on each of your turns: the sleeper does not repeat its save at the end of its next turn. "
                                       "Not on consecutive turns."}))
    return out or None


# ----------------------------------------------------------------------------------------------------------------- Dream Walker
@effect("dream_walker_mark")
def walker_mark(ctx: Any, row: dict[str, Any]) -> None:
    _te().block_mark(ctx, {"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                           "evidence": "Create a Resonance Mark on the dreamer"})


# ---------------------------------------------------------------------------------------------------------------- Nightmare Touch
@effect("dream_touch")
def touch_morsel(ctx: Any, row: dict[str, Any]) -> None:
    """"If the target was sleeping, helpless, Frightened, or already scarred and is meaningful and hostile, gain 1 Dream Morsel" (read
    before the save's own Scar)."""
    subject = ctx.target
    if subject is not None and _asleep(subject):
        ctx.damage_cache["dream_touch_sleep"] = True
    if subject is not None and subject.team_id != ctx.actor.team_id and (_helpless(subject) or _frightened(subject) or scarred_by(subject, ctx.actor)):
        _gain_morsel(ctx.engine, ctx.actor, subject, ctx.source)


@effect("dream_touch_waking")
def touch_waking(ctx: Any, row: dict[str, Any]) -> None:
    """Wake after damage; a morsel preserves sleep through this injury only."""
    subject = ctx.target
    if subject is None or not ctx.damage_cache.get("dream_touch_sleep"):
        return
    from . import needle
    keep = False
    had_sleep = any(_is_sleep_effect(held) for held in subject.conditions.values())
    if row.get("failed") and ctx.actor.resources.get(MORSEL, 0) >= 1:
        chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "TOUCH_SLEEP", subject.entity_id),
                            ctx.actor, "choice:needle.dream_eater.keep_sleep", ["keep"],
                            labels={"keep": "Spend 1 Dream Morsel to keep the creature asleep"}, preferred=["keep"],
                            allow_decline=True, name="Nightmare Touch", feature_id=TOUCH, target_id=subject.entity_id,
                            prompt=f"Keep {subject.display_name} asleep until the end of its next turn or damage from another source?")
        keep = bool(chosen)
        if keep:
            ctx.engine._spend_resource(ctx.actor, MORSEL, 1, ctx.source)
    for held in list(subject.conditions.values()):
        if _is_sleep_effect(held):
            _remove(ctx.engine, subject, held, "NIGHTMARE_TOUCH")
    if keep and subject.active and subject.current_hp > 0:
        _te().run_effects(ctx, [{"type": "condition", "condition": "unconscious", "applies_to": "target",
                               "duration": {"kind": "until_end_of_next_turn"}}])
        ctx.engine._apply_condition(subject, "condition:typed.nightmare_sleep", ctx.source, ctx.actor.entity_id,
                                    expires_on=_te().effect_expiry(ctx, {"duration": {"kind": "until_end_of_next_turn"}}, subject, condition=True),
                                    data={"label": "Nightmare sleep: damage from another source wakes you"})
    elif had_sleep:
        note(ctx.engine, ctx.source, ctx.actor, f"{subject.display_name} wakes after Nightmare Touch.", (subject,))


@hook("event")
def nightmare_sleep_damaged(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    for tid in kwargs.get("target_ids") or ():
        subject = engine.state.actors.get(tid)
        if subject is None:
            continue
        for sleep in list(subject.conditions.values()):
            if sleep.condition_id != "condition:typed.nightmare_sleep" or sleep.source_definition_id == kwargs.get("source_definition_id"):
                continue
            for held in list(subject.conditions.values()):
                if held is sleep or (held.condition_id == "condition:typed.unconscious" and held.source_definition_id == sleep.source_definition_id):
                    _remove(engine, subject, held, "DAMAGE_WAKES")


# -------------------------------------------------------------------------------------------------------- Predatory Trace
def _touch_scar(engine: Any, subject: Any, owner: Any) -> Any:
    """The Nightmare Scar ``owner`` placed on ``subject`` through Nightmare Touch (not another Dream Eater feature)."""
    from .ability_source import mechanic_at

    for scar in _scars(subject):
        if scar.source_actor_id == owner.entity_id and mechanic_at(engine, scar.source_definition_id) == TOUCH:
            return scar
    return None


@hook("diagnosis_reveal")
def predatory_trace(ctx: Any, subject: Any) -> str | None:
    """Predatory Trace: "Soul Gaze, Read the Spirit, and appropriate dream diagnosis can identify your
    spiritual signature unless you defeat the diagnosis with a Cultivation Check."

    Any diagnosis that asks this query about a creature bearing this Dream Eater's Nightmare Touch Scar
    answers for the scar: the Dream Eater makes the printed Cultivation Check (the printed sentence puts
    the check in the Dream Eater's hands) and the roll is recorded on the table. The DC is the diagnosis's
    own Source DC: the examining creature's Cultivation Save DC ("against its save DC", the printed Read
    the Spirit rule). A success hides the signature from that diagnosis; a failure lets it read who
    attacked the creature's sleep or fear. A creature gazing at its own scar is not a contest.

    Soul Gaze is the only automated route today. Only a diagnosis producer that asks the general
    ``diagnosis_reveal`` query reaches this provider, and Read the Spirit has no table producer in this
    build (its reveal is narrative, so the GM adjudicates that route), which the rider states plainly.
    Inert without an owned Nightmare Touch Scar (every other diagnosis is unchanged).
    """
    engine = ctx.engine
    if subject is None or ctx.actor is None:
        return None
    from .ability_source import cultivation_check_detail
    from .needle import save_dc

    lines = []
    for owner in engine.state.actors.values():  # ordinary actor order, so a reload replays the same rolls
        if owner is ctx.actor or not owner.active:
            continue
        if _touch_scar(engine, subject, owner) is None:
            continue
        roll, defeated = cultivation_check_detail(engine, owner, st.numbers(engine, owner), save_dc(engine, ctx.actor), TOUCH,
                                                  "Cultivation Check (Predatory Trace)")
        if defeated:
            lines.append(f"The Nightmare Scar on {subject.display_name} came from a Nightmare Touch, but its creator's "
                         f"spiritual signature stays hidden: they defeated this diagnosis with a Cultivation Check.")
        else:
            lines.append(f"The Nightmare Scar on {subject.display_name} carries {owner.display_name}'s spiritual signature: "
                         f"{owner.display_name} attacked its sleep or fear with Nightmare Touch.")
    return " ".join(lines) or None


# ---------------------------------------------------------------------------------------------------------------- Sleeping Curse
@effect("dream_cursed_sleep")
def cursed_sleep(ctx: Any, row: dict[str, Any]) -> None:
    subject = ctx.target
    if subject is None or not subject.active:
        return
    te = _te()
    te.run_effects(ctx, [{"type": "condition", "applies_to": "target", "condition": "unconscious", "evidence": "It is Unconscious"},
                         {"type": "condition", "applies_to": "target", "condition": "prone", "evidence": "falls Prone if able"}])
    ctx.engine._apply_condition(subject, CURSED, ctx.source, ctx.actor.entity_id, expires_on=ctx.expires_on() or "CONCENTRATION_END",
                                data={"dc": int(ctx.numbers.get("save_dc") or 10), "label": "Cursed Sleep: Unconscious; a Wisdom save at the end of each "
                                      "of its turns (or with Advantage when it takes damage) wakes it"})


def _wake(engine: Any, sleeper: Any, curse: Any, reason: str) -> None:
    source, owner = curse.source_definition_id, curse.source_actor_id
    _remove(engine, sleeper, curse, reason)
    for condition in [c for c in sleeper.conditions.values() if c.source_definition_id == source and c.source_actor_id == owner
                      and c.condition_id == "condition:typed.unconscious"]:
        _remove(engine, sleeper, condition, reason)
    note(engine, source, sleeper, f"{sleeper.display_name} wakes from the Cursed Sleep.")


def _curse_save(engine: Any, sleeper: Any, curse: Any, *, advantage: bool) -> None:
    owner = engine.state.actors.get(curse.source_actor_id)
    if owner is None:
        return
    action = st.feature_action(engine, owner, CURSE)
    ctx = st.context(engine, owner, action, [sleeper])
    ctx.typed["numbers"] = {**ctx.numbers, "save_dc": int((curse.data or {}).get("dc") or ctx.numbers.get("save_dc") or 10)}
    engine.__dict__["_c8_curse_advantage"] = sleeper.entity_id if advantage else None
    before = len(engine.events)
    try:
        _te().block_save(ctx, {"type": "save", "applies_to": "target", "ability": "wis", "on_fail": [], "on_success": []})
    finally:
        engine.__dict__.pop("_c8_curse_advantage", None)
    rolled = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == sleeper.entity_id]
    if rolled and (rolled[-1].payload or {}).get("success"):
        _wake(engine, sleeper, curse, "SAVED")


@hook("save")
def curse_advantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    return {"bonus": 0, "modes": ["ADVANTAGE"]} if ctx.engine.__dict__.get("_c8_curse_advantage") == getattr(subject, "entity_id", None) else None


@hook("turn_end")
def curse_repeat(engine: Any, actor: Any) -> None:
    curse = next((c for c in actor.conditions.values() if c.condition_id == CURSED), None)
    if curse is None or not actor.active:
        return
    if (curse.data or {}).get("still"):
        data = {k: v for k, v in (curse.data or {}).items() if k != "still"}
        _remove(engine, actor, curse, "UPDATED")
        engine._apply_condition(actor, CURSED, curse.source_definition_id, curse.source_actor_id, expires_on=curse.expires_on, data=data)
        return  # Maintain Stillness: no repeat save this time
    _curse_save(engine, actor, curse, advantage=False)


@hook("event")
def curse_damaged(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED" or engine.__dict__.get("_c8_curse_busy"):
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    for target_id in kwargs.get("target_ids") or ():
        sleeper = engine.state.actors.get(target_id)
        curse = next((c for c in sleeper.conditions.values() if c.condition_id == CURSED), None) if sleeper is not None else None
        if curse is None or not sleeper.active:
            continue
        engine.__dict__["_c8_curse_busy"] = True
        try:
            _curse_save(engine, sleeper, curse, advantage=True)  # "It also immediately repeats the save with Advantage when it takes damage"
        finally:
            engine.__dict__.pop("_c8_curse_busy", None)


@effect("dream_feed")
def feed(ctx: Any, row: dict[str, Any]) -> None:
    ctx.actor.turn_flags["dream_curse_option"] = True
    subject = ctx.target
    if subject is None:
        return
    before = len(ctx.engine.events)
    _te().run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 10}, "damage_types": ["psychic"],
                             "evidence": "Feed: the sleeper takes 3d10 Psychic damage"}])
    dealt = sum(int((e.payload or {}).get("hp_damage") or 0) + int((e.payload or {}).get("temporary_hp_absorbed") or 0)
                for e in ctx.engine.events[before:] if e.event_type == "DAMAGE_COMMITTED" and subject.entity_id in e.target_ids
                and e.source_definition_id == ctx.source)
    if dealt // 2 > 0:
        ctx.engine._grant_temp_hp(ctx.actor, dealt // 2, ctx.source, ctx.actor.entity_id)


@effect("dream_stillness")
def stillness(ctx: Any, row: dict[str, Any]) -> None:
    actor, subject = ctx.actor, ctx.target
    last = actor.turn_flags.get("dream_round_stillness")
    if last is not None and int(last) == int(actor.turns_started) - 1:
        ctx.rider("Maintain Stillness cannot be chosen on consecutive turns.")
        return
    actor.turn_flags["dream_curse_option"] = True
    actor.turn_flags["dream_round_stillness"] = int(actor.turns_started)
    curse = next((c for c in subject.conditions.values() if c.condition_id == CURSED), None) if subject is not None else None
    if curse is None:
        return
    _remove(ctx.engine, subject, curse, "UPDATED")
    ctx.engine._apply_condition(subject, CURSED, curse.source_definition_id, curse.source_actor_id, expires_on=curse.expires_on,
                                data={**(curse.data or {}), "still": 1})


# -------------------------------------------------------------------------------------------------------------------- Ascension
@effect("dream_ascension")
def ascension(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, actor, subject = ctx.engine, ctx.actor, ctx.target
    if subject is None or not subject.active:
        return
    held = int(actor.resources.get(MORSEL, 0))
    spend = 0
    if held:
        options = [str(n) for n in range(0, min(3, held) + 1)]
        preferred = [str(min(2, held))] if _helpless(subject) else ["0"]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "DREAM_ASCENSION", subject.entity_id), actor,
                            "choice:needle.dream_eater.ascension_morsels", options,
                            labels={n: f"Spend {n} Dream Morsel{'s' if n != '1' else ''}" + (" (Disadvantage on its save if it is asleep or helpless)" if n in ("2", "3") else "") for n in options},
                            prompt=f"Dream Eater Ascension: spend how many Dream Morsels against {subject.display_name}?", preferred=preferred,
                            name="Dream Eater Ascension", feature_id=ASCENSION, target_id=subject.entity_id)
        spend = int(chosen[0]) if chosen else int(preferred[0])
        if spend:
            engine._spend_resource(actor, MORSEL, spend, ctx.source)
    disadvantage = spend >= 2 and _helpless(subject)
    engine.__dict__["_c8_ascension_disadvantage"] = subject.entity_id if disadvantage else None
    before = len(engine.events)
    try:
        _te().block_save(ctx, {"type": "save", "applies_to": "target", "ability": "wis",
                               "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 10, "sides": 10}, "damage_types": ["psychic"],
                                            "evidence": "The target takes 10d10 Psychic damage"}],
                               "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["psychic"]},
                                              {"type": "spiritual_pressure", "applies_to": "target"}]})
    finally:
        engine.__dict__.pop("_c8_ascension_disadvantage", None)
    rolled = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == subject.entity_id]
    failed = bool(rolled) and (rolled[-1].payload or {}).get("success") is False
    dealt = sum(int((e.payload or {}).get("hp_damage") or 0) + int((e.payload or {}).get("temporary_hp_absorbed") or 0)
                for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED" and subject.entity_id in e.target_ids)
    if not failed:
        add_fragment(engine, actor, subject, ctx.source)  # "you may steal one ordinary Dream Fragment ... without additional cost"
        return
    choices = {"hope": "Defining Hope: Disadvantage on its saves against Frightened for the rest of the fight",
               "memory": "Recent Memory (the GM removes one recent memory)", "rest": "Restful Dream (no Long Rest benefits until recovered)",
               "confidence": "Practiced Confidence (the GM suppresses one proficiency)",
               "prepared": "Prepared Dream (the GM suppresses one dream, memory or emotional technique it used)"}
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "DREAM_CONSUMPTION", subject.entity_id), actor,
                        "choice:needle.dream_eater.consumption", list(choices), labels=choices, preferred=["hope"],
                        prompt=f"Dream Eater Ascension: choose what you consume from {subject.display_name}.", name="Consumption",
                        feature_id=ASCENSION, target_id=subject.entity_id)
    pick = chosen[0] if chosen else "hope"
    if pick == "hope" and subject.active:
        engine._apply_condition(subject, "condition:typed.save_against", ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"rule": {"save_against": {"mode": "DISADVANTAGE", "against": ["frightened"], "abilities": [], "next": False}},
                                      "label": "Defining Hope devoured: Disadvantage on saves against Frightened"})
    else:
        ctx.rider(f"Dream Eater Ascension consumed {choices[pick]} from {subject.display_name}.")
    if dealt // 2 > 0:
        engine._grant_temp_hp(actor, dealt // 2, ctx.source, actor.entity_id)  # Devoured Dream: half the Psychic damage dealt
    engine._apply_condition(actor, "condition:typed.devoured_dream", ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"from": subject.entity_id, "label": f"Devoured Dream from {subject.display_name}"})


@hook("save")
def ascension_disadvantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    return {"bonus": 0, "modes": ["DISADVANTAGE"]} if ctx.engine.__dict__.get("_c8_ascension_disadvantage") == getattr(subject, "entity_id", None) else None


CURSE_INTERVENE = "action:typed.dream_eater.invoke_sleepers_bond"


@hook("match_start")
def sleep_intervention_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[CURSE_INTERVENE] = ActionDefinition(
        source_definition_id=CURSE_INTERVENE, display_name="Wake Cursed Sleeper: invoke their name or bond",
        owner_id="*", economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF", range_ft=5,
        parameters={"typed": {"effects": [{"type": "dream_curse_intervene", "applies_to": "target"}],
                               "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
                    "dream_curse_intervene": True, "expected_damage": 0,
                    "description": "Use your Action beside a Cursed-Sleeping ally to invoke their Soul Anchor, true name or meaningful bond. "
                                   "They immediately repeat the curse's Wisdom save, waking on a success."})


@hook("additional_actions")
def sleep_intervention_offered(engine: Any, actor: Any) -> list[str]:
    return [CURSE_INTERVENE] if any(
        other is not actor and other.active and other.team_id == actor.team_id
        and engine._distance_actor_to_actor(actor, other) <= 5
        and any(c.condition_id == CURSED for c in other.conditions.values())
        for other in engine.state.actors.values()) else []


@hook("candidate_allowed")
def sleep_intervention_target(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get("dream_curse_intervene"):
        return None
    target = engine.state.actors.get(next(iter(candidate.target_ids or ()), ""))
    return None if (target is not None and target is not actor and target.team_id == actor.team_id
                    and any(c.condition_id == CURSED for c in target.conditions.values())) else False


@effect("dream_curse_intervene")
def sleep_intervention(ctx: Any, row: dict[str, Any]) -> None:
    target = ctx.target
    if target is None or target is ctx.actor or target.team_id != ctx.actor.team_id:
        return
    curse = next((c for c in target.conditions.values() if c.condition_id == CURSED), None)
    if curse is not None and ctx.engine._distance_actor_to_actor(ctx.actor, target) <= 5:
        _curse_save(ctx.engine, target, curse, advantage=False)
