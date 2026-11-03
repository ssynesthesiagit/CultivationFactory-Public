"""Yokai Channeler (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Yokai Channeler: Choose a Yokai Lineage, Lineage Table, CL3 Yokai Mask, CL6
Unmasking, CL10 Yokai's Bargain, CL14 True Yokai Form, CL18 Yokai Lord, Natural Weapon Damage Types). No Spheres 5e or D&D 5.5e
counterpart. Ownership row: combat/rules/feature_blocks.d/riders_c8.json (Yokai Mask: the plug-in answers).

The lineage. "At CL3, choose Kitsune, Tengu, Kappa, or Jorogumo. The choice cannot normally be changed." The Factory sheet does not
record it, so the table keeps it for the fight: the setting buttons "Yokai Lineage: <name>" (free, before anything else), or the question
the first time Unmasking needs it. Once chosen it stays (``condition:typed.yokai_lineage``). Damage affinities: Kitsune Psychic or Fire,
Tengu Thunder or Force, Kappa Cold or Bludgeoning, Jorogumo Poison or Psychic.

What runs:
  * Tengu Mask subtracts 10 x PB feet from effective falling distance. True Form (including Lord) grants Kitsune fly 40 feet with
    hover, or Tengu fly 50 feet, only while the transformation persists. These are physical flight profiles.
  * Yokai Mask, Lineage Gift (a Reaction for 1 Resonance, asked): Tengu -- when you are pushed or would be knocked Prone, move 10 feet
    to a legal space and remain standing; Kappa -- when you or an adjacent ally would be pushed or pulled, that movement is 10 feet
    shorter and the creature shifts 5 feet to another legal adjacent space; Jorogumo -- once on each of your turns when you Resonance
    Mark a creature you may reduce its Speed by 5 feet until the mark ends (asked, no Reaction or cost).
  * Unmasking (Bonus Action, 2 Resonance, the scene): the natural weapon's damage type is chosen (your lineage's affinities, or
    Piercing, Slashing or Bludgeoning; asked) and "Yokai Natural Weapon" (Action, reach 5 feet, Wisdom, 1d8 + Wisdom) is offered while it
    lasts. Once on each of your turns when it hits or a creature fails its save against your Mind Spike, Proficiency Bonus damage of
    your lineage affinity. Unmasked Lineage Gift: Kitsune -- after that damage a foxfire double until the start of your next turn (the
    first attack against you has Disadvantage; on a miss you step 5 feet, asked); Tengu -- after a 15-foot straight-line move, your next
    natural-weapon hit that turn adds 1d8 Thunder and can push 10 feet (asked); Kappa -- Advantage on saves and escape checks and saves
    against Grappled and Restrained, and once a turn on a natural-weapon hit a Grapple (asked: Strength or Dexterity save against 8 +
    your Cultivation Attack Modifier); Jorogumo -- once a turn on a natural-weapon hit a Silk Thread until the end of your next turn
    (its invisibility does not count against you, and its first escape check or save against your hold has Disadvantage).
  * True Yokai Form (Action, 6 Resonance, the scene): Unmasking's benefits without its cost, the natural weapon die 1d10, Resistance to one
    of your affinities (asked), and the lineage package: Kitsune Ninefold Feint (once a round when an attack misses you, step up to 15
    feet and put a Foxfire Sign on the attacker until the end of your next turn; asked); Tengu Mountain Wind Cut (once on each of your
    turns after moving 20 feet, a natural-weapon hit adds 2d8 and a Strength save or Prone / pushed 15 feet, your choice); Kappa River
    Lock (a creature you grapple cannot teleport unless its CL is higher or it succeeds on a Charisma save); Jorogumo "Grand Silk"
    (Action: a 20-foot-square web within 60 feet for the fight -- difficult terrain for enemies, a Dexterity save or Restrained until the
    end of its next turn on entering or starting there; one at a time).
  * Yokai Lord (Bonus Action, 10 Resonance, the scene): True Yokai Form and the Yokai Court, whose Lineage Apotheosis is offered once in
    the activation: "Heaven-Scouring Descent" (Tengu: fly up to 50 feet without provoking, a Cultivation Attack for 4d10 + Wisdom Thunder or
    Force against each hostile creature passed within 5 feet, up to PB of them), "Court Beneath the River" (Kappa: a 30-foot-radius court
    within 60 feet, difficult terrain for enemies, a Charisma save for a hostile teleport across its edge), "Web of a Hundred Names"
    (Jorogumo: up to PB creatures within 60 feet make a Dexterity save or have Speed 0 until they break the silk -- "Break the Hundred Names
    Silk", an Action for the save again -- or the Thread Anchor, AC your DC and 3 x PB Hit Points, is destroyed).

Plug-in surface: effects yokai_lineage_pick, yokai_unmask, yokai_grand_silk, yokai_descent, yokai_river_court, yokai_hundred_names,
yokai_break_silk; hooks compile_actions, candidate_allowed, attack_damage, attack_damage_types, after_hit, after_save_resolved,
before_attack, event, condition_attempt, forced_movement_reduction, mark_applied, speed, save, escape_mode, escape_save_mode,
masked_conditions, teleport_gate, match_start, additional_actions. Shared helpers used: spirit_traditions (row/context/numbers/
feature_of/feature_action/routes/choose_route/can_react/save/remove/data_of/set_data), needle (ask/checkpoint_id), rider_movement.step,
hold_still.moved_ft, zones.create, stealth.sees, typed_executor.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.yokai_channeler.feature."
MASK = TRADITION + "yokai_mask"
UNMASK = TRADITION + "unmasking"
TRUE_FORM = TRADITION + "true_yokai_form"
LORD = TRADITION + "yokai_lord"
MIND_SPIKE = "tianxia.path.spirit_awakening.feature.mind_spike"
RESONANCE = "resource:core.resonance"
LINEAGE = "condition:typed.yokai_lineage"
UNMASKED = "condition:typed.yokai_unmasked"
TRUE = "condition:typed.true_yokai_form"
DOUBLE = "condition:typed.foxfire_double"
COURT = "condition:typed.yokai_court"
WEB = "condition:typed.hundred_names_silk"
ANCHOR = "object:typed.hundred_names_anchor:"
BREAK_WEB = "system:combat.break_the_hundred_names_silk"
SIGN = "Foxfire Sign"
SILK = "Silk Thread"
LINEAGES = {"kitsune": ("Kitsune", ("psychic", "fire")), "tengu": ("Tengu", ("thunder", "force")),
            "kappa": ("Kappa", ("cold", "bludgeoning")), "jorogumo": ("Jorogumo", ("poison", "psychic"))}
PHYSICAL = ("piercing", "slashing", "bludgeoning")
_FOXFIRE = "_c8_yokai_foxfire"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _held(creature: Any, condition_id: str, source: str | None = None) -> list[Any]:
    return [c for c in creature.conditions.values() if c.condition_id == condition_id and (source is None or c.source_actor_id == source)]


def lineage_of(actor: Any) -> str | None:
    held = next(iter(_held(actor, LINEAGE)), None)
    return str((held.data or {}).get("lineage")) if held is not None else None


def _form(actor: Any) -> Any:
    """The Unmasking or True Yokai Form the creature is in (True Form: "the benefits of Unmasking without paying its cost")."""
    return next(iter(_held(actor, TRUE) or _held(actor, UNMASKED)), None)


@hook("flight")
def true_form_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    if not _held(actor, TRUE):
        return None
    lineage = lineage_of(actor)
    if lineage == "kitsune":
        return {"fly_speed_ft": 40, "flight_hover": True}
    if lineage == "tengu":
        return {"fly_speed_ft": 50}
    return None


@hook("falling_damage_distance")
def tengu_fall_distance(engine: Any, actor: Any, distance_ft: int, fall: Any, intent: Any) -> int | None:
    if lineage_of(actor) != "tengu" or st.row(engine, actor, "yokai_mask") is None:
        return None
    return max(0, distance_ft - 10 * _pb(engine, actor))


def _set_lineage(engine: Any, actor: Any, key: str, source: str) -> None:
    if key in LINEAGES and lineage_of(actor) is None:
        engine._apply_condition(actor, LINEAGE, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"lineage": key, "label": f"Yokai lineage: {LINEAGES[key][0]}"})


def ensure_lineage(engine: Any, actor: Any, intent: Any) -> str | None:
    """The lineage, asked the first time it matters when the setting was not used."""
    from . import needle

    if lineage_of(actor) is None:
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "YOKAI_LINEAGE", actor.entity_id), actor, "choice:needle.yokai.lineage",
                            list(LINEAGES), labels={k: v[0] for k, v in LINEAGES.items()}, preferred=["kitsune"], name="Yokai Mask (lineage)",
                            feature_id=MASK, prompt="Your yokai lineage, chosen at CL3 (it stays for the fight)?")
        _set_lineage(engine, actor, chosen[0] if chosen and chosen[0] in LINEAGES else "kitsune", MASK)
    return lineage_of(actor)


def _pb(engine: Any, actor: Any) -> int:
    return int(st.numbers(engine, actor).get("pb") or 2)


def _is_weapon(action: Any) -> bool:
    return bool(((getattr(action, "parameters", None) or {}).get("yokai")) == "weapon")


@effect("yokai_lineage_pick")
def lineage_pick(ctx: Any, row: dict[str, Any]) -> None:
    _set_lineage(ctx.engine, ctx.actor, str(row.get("lineage") or ""), ctx.source)


# ---------------------------------------------------------------------------------------------------------- Unmasking
@effect("yokai_unmask")
def unmask(ctx: Any, row: dict[str, Any]) -> None:
    """"Choose an appropriate bite, claw, horn ... when you activate Unmasking" -- its damage type is chosen then and lasts until it ends."""
    from . import needle

    engine, actor = ctx.engine, ctx.actor
    lineage = ensure_lineage(engine, actor, ctx.intent)
    if lineage is None:
        return
    affinities = LINEAGES[lineage][1]
    kinds = list(dict.fromkeys([*affinities, *PHYSICAL]))
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "YOKAI_WEAPON", actor.entity_id), actor, "choice:needle.yokai.weapon_type", kinds,
                        labels={k: f"{k.title()} ({'lineage affinity' if k in affinities else 'bite, claw, tail or blow'})" for k in kinds},
                        preferred=[affinities[0]], name="Unmasking", feature_id=UNMASK, prompt="Your natural weapon's damage type?")
    kind = chosen[0] if chosen and chosen[0] in kinds else affinities[0]
    affinity = kind if kind in affinities else affinities[0]
    if kind not in affinities:
        picked = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "YOKAI_AFFINITY", actor.entity_id), actor, "choice:needle.yokai.affinity",
                            list(affinities), labels={k: k.title() for k in affinities}, preferred=[affinities[0]], name="Unmasking", feature_id=UNMASK,
                            prompt="Your lineage affinity for the extra damage?")
        affinity = picked[0] if picked and picked[0] in affinities else affinities[0]
    held_id = TRUE if row.get("form") == "true" else UNMASKED
    for old in _held(actor, held_id):
        st.remove(engine, actor, old, "REPLACED")
    engine._apply_condition(actor, held_id, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"type": kind, "affinity": affinity, "label": f"{'True Yokai Form' if held_id == TRUE else 'Unmasked'} ({LINEAGES[lineage][0]}): "
                                                                               f"natural weapon {kind.title()}"})
    if held_id == TRUE:
        # "Resistance to Psychic or Fire damage, chosen when you transform" (each lineage's two affinities)
        picked = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "YOKAI_RESISTANCE", actor.entity_id), actor, "choice:needle.yokai.resistance",
                            list(affinities), labels={k: f"Resistance to {k.title()} damage" for k in affinities}, preferred=[affinities[0]],
                            name="True Yokai Form", feature_id=TRUE_FORM, prompt="True Yokai Form: resistance to which damage?")
        resist = picked[0] if picked and picked[0] in affinities else affinities[0]
        _te().run_effects(st.context(engine, actor, ctx.action, [actor], ctx.numbers, ctx.intent),
                          [{"type": "resistance", "applies_to": "self", "damage_types": [resist], "duration": {"kind": "until_removed"},
                            "evidence": f"Resistance to {resist.title()} damage, chosen when you transform"}])
    if row.get("lord"):
        for old in _held(actor, COURT):
            st.remove(engine, actor, old, "REPLACED")
        engine._apply_condition(actor, COURT, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": f"Yokai Lord ({LINEAGES[lineage][0]}): the Yokai Court"})


@hook("attack_damage")
def natural_die(ctx: Any, dice: Any) -> Any:
    """True Yokai Form: "your natural weapon die becomes 1d10"."""
    if not _is_weapon(ctx.action) or not _held(ctx.actor, TRUE) or dice is None:
        return None
    return dice.model_copy(update={"sides": 10})


@hook("attack_damage_types")
def natural_type(ctx: Any, attack: Any, kinds: Any) -> list[str] | None:
    form = _form(ctx.actor) if _is_weapon(ctx.action) else None
    return [str((form.data or {}).get("type") or "bludgeoning").upper()] if form is not None else None


def _extra(ctx: Any, target: Any) -> None:
    """"Once on each of your turns when you hit with the natural weapon or a creature fails its save against Mind Spike, deal additional
    damage equal to your Proficiency Bonus of your lineage affinity.\""""
    engine, actor = ctx.engine, ctx.actor
    form = _form(actor)
    if form is None or target is None or not target.active or engine.state.current_actor_id != actor.entity_id or actor.turn_flags.get("c8_yokai_extra"):
        return
    actor.turn_flags["c8_yokai_extra"] = True
    affinity = str((form.data or {}).get("affinity") or "psychic")
    _te().run_effects(st.context(engine, actor, ctx.action, [target], ctx.numbers, ctx.intent),
                      [{"type": "damage", "applies_to": "target", "flat": _pb(engine, actor), "damage_types": [affinity],
                        "evidence": "additional damage equal to your Proficiency Bonus of your lineage affinity"}])
    if lineage_of(actor) == "kitsune":
        for old in _held(actor, DOUBLE):
            st.remove(engine, actor, old, "REPLACED")
        engine._apply_condition(actor, DOUBLE, UNMASK, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "Foxfire double: the first attack against you has Disadvantage"})


@hook("after_hit")
def natural_hit(ctx: Any, target: Any, kind: str) -> None:
    if not _is_weapon(ctx.action) or _form(ctx.actor) is None:
        return
    _extra(ctx, target)
    lineage = lineage_of(ctx.actor)
    if lineage == "tengu":
        _tengu_strike(ctx, target)
        _mountain_wind_cut(ctx, target)
    elif lineage == "kappa":
        _kappa_grapple(ctx, target)
    elif lineage == "jorogumo" and not ctx.actor.turn_flags.get("c8_yokai_silk") and target.active:
        ctx.actor.turn_flags["c8_yokai_silk"] = True
        _te().run_effects(st.context(ctx.engine, ctx.actor, ctx.action, [target], ctx.numbers, ctx.intent),
                          [{"type": "mark", "mark": SILK, "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                            "evidence": "place a Silk Thread on the target until the end of your next turn"}])


@hook("after_save_resolved")
def mind_spike_failed(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    if failed and subject is not None and st.feature_of(ctx.action) == MIND_SPIKE and _form(ctx.actor) is not None:
        _extra(ctx, subject)


# ---------------------------------------------------------------------------------------------------------- Kitsune: the foxfire double
@hook("before_attack")
def foxfire_double(engine: Any, attacker: Any, defender: Any, intent: Any, context: Any) -> dict[str, Any] | None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _FOXFIRE)
    if defender is None or attacker is None:
        return None
    held = next(iter(_held(defender, DOUBLE)), None)
    if held is None:
        return None
    st.remove(engine, defender, held, "STRUCK")  # "The first attack against you before then has Disadvantage"
    engine.__dict__[_FOXFIRE] = (attacker.entity_id, defender.entity_id)
    return {"mode": "DISADVANTAGE"}


def _step(engine: Any, walker: Any, chooser: Any, feet: int, intent: Any, checkpoint: str, prompt: str, feature: str) -> bool:
    spots = {c: v for c, v in st.routes(engine, walker, feet).items() if c != walker.position}
    path = st.choose_route(engine, chooser, spots, intent, checkpoint=checkpoint, prompt=prompt, name=prompt.split(":")[0], feature=feature, stay=False) if spots else None
    if path is None:
        return False
    from .rider_movement import step

    step(engine, walker, list(path), feature)
    return True


@hook("event")
def yokai_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _FOXFIRE)
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    payload = kwargs.get("payload") or {}
    if event_type == "ATTACK_ROLLED" and engine.__dict__.get(_FOXFIRE):
        attacker_id, defender_id = engine.__dict__.pop(_FOXFIRE)
        defender = engine.state.actors.get(defender_id)
        if actor is not None and actor.entity_id == attacker_id and defender is not None and payload.get("provisional_hit") is False and defender.active:
            _step(engine, defender, defender, 5, engine._active_intent, "FOXFIRE_STEP", "Foxfire double: step 5 feet?", UNMASK)
    if event_type == "ATTACK_ROLLED" and payload.get("provisional_hit") is False:
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is not None and actor is not None:
                _ninefold_feint(engine, target, actor)
    if event_type == "OBJECT_UPDATED":
        _anchor_broken(engine, kwargs)
    if event_type == "MOVEMENT_COMMITTED" and actor is not None:
        if payload.get("forced"):
            _wind_perched(engine, actor)
        elif engine.state.current_actor_id == actor.entity_id and lineage_of(actor) == "tengu" and _form(actor) is not None:
            if _straight_ft(engine, payload.get("path") or []) >= 15:
                actor.turn_flags["c8_tengu_dash"] = True  # "After you move at least 15 feet in a straight line"
    if event_type == "CONDITION_REMOVED":
        name = str(payload.get("condition_id") or "")
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is not None:
                for key in [k for k in target.turn_flags if k.startswith("_round_c8_thread_slow:")]:
                    owner = key.split(":", 1)[1]
                    if name == _te().mark_condition_id("Resonance", owner) and not _te().bears_mark(target, owner, "Resonance"):
                        target.turn_flags.pop(key, None)  # "until the mark ends"


def _straight_ft(engine: Any, path: list[Any]) -> int:
    from math import gcd

    from ..gate2_runtime_models import Position

    cells = [Position(x=int(p["x"]), y=int(p["y"])) for p in path if isinstance(p, dict)]
    if len(cells) < 2:
        return 0
    steps = set()
    for a, b in zip(cells, cells[1:]):
        dx, dy = b.x - a.x, b.y - a.y
        g = gcd(abs(dx), abs(dy)) or 1
        steps.add((dx // g, dy // g))
    return engine.grid.distance_ft(cells[0], cells[-1]) if len(steps) == 1 else 0


def _tengu_strike(ctx: Any, target: Any) -> None:
    from . import needle

    engine, actor = ctx.engine, ctx.actor
    if not actor.turn_flags.pop("c8_tengu_dash", None) or not target.active:
        return
    sub = st.context(engine, actor, ctx.action, [target], ctx.numbers, ctx.intent)
    _te().run_effects(sub, [{"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "damage_types": ["thunder"], "evidence": "an extra 1d8 Thunder damage"}])
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "TENGU_PUSH", target.entity_id), actor, "choice:needle.yokai.tengu_push", ["push"],
                        labels={"push": f"Push {target.display_name} 10 feet"}, preferred=["push"], allow_decline=True, name="Unmasking (Tengu)", feature_id=UNMASK,
                        target_id=target.entity_id, prompt="Tengu dive: push the target 10 feet?")
    if chosen and chosen[0] == "push" and target.active:
        _te().run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away", "evidence": "can push the target 10 feet"}])


def _kappa_grapple(ctx: Any, target: Any) -> None:
    """"Once per turn on a natural-weapon hit, you may Grapple the target using your Cultivation Attack Modifier in place of Athletics"
    (the 2024 Grapple: a Strength or Dexterity save against 8 + that modifier)."""
    from . import needle

    engine, actor = ctx.engine, ctx.actor
    if actor.turn_flags.get("c8_kappa_grapple") or not target.active:
        return
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "KAPPA_GRAPPLE", target.entity_id), actor, "choice:needle.yokai.kappa_grapple", ["grapple"],
                        labels={"grapple": f"Grapple {target.display_name}"}, preferred=["grapple"], allow_decline=True, name="Unmasking (Kappa)", feature_id=UNMASK,
                        target_id=target.entity_id, prompt="Kappa grip: Grapple the target?")
    if not chosen or chosen[0] != "grapple":
        return
    actor.turn_flags["c8_kappa_grapple"] = True
    numbers = {**(ctx.numbers or {}), "save_dc": 8 + int((ctx.numbers or {}).get("attack_bonus") or st.numbers(engine, actor).get("attack_bonus") or 0)}
    sub = st.context(engine, actor, ctx.action, [target], numbers, ctx.intent)
    _te().run_effects(sub, [{"type": "save", "applies_to": "target", "ability": "str_or_dex",
                             "on_fail": [{"type": "condition", "applies_to": "target", "condition": "grappled", "until_escape": True, "evidence": "Grappled"}]}])


@hook("save")
def kappa_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is not None and lineage_of(subject) == "kappa" and _form(subject) is not None and set(named or ()) & {"grappled", "restrained"}:
        return {"bonus": 0, "modes": ["ADVANTAGE"]}  # "Advantage on checks and saves against Grappled and Restrained"
    return None


def _hold_mode(engine: Any, escaper: Any, grips: Any) -> str | None:
    names = {str(getattr(g, "condition_id", "")).rsplit(".", 1)[-1] for g in (grips.values() if isinstance(grips, dict) else grips or ())}
    if lineage_of(escaper) == "kappa" and _form(escaper) is not None and names & {"grappled", "restrained"}:
        return "ADVANTAGE"
    holders = {getattr(g, "source_actor_id", None) for g in (grips.values() if isinstance(grips, dict) else grips or ())}
    for owner in holders:
        silk = next((c for c in escaper.conditions.values() if c.condition_id == _te().mark_condition_id(SILK, owner)), None)
        if silk is not None and not st.data_of(escaper, silk).get("spent"):
            st.set_data(escaper, silk, spent=True)  # "Disadvantage on the first check or save it makes to escape"
            return "DISADVANTAGE"
    return None


@hook("escape_mode")
def escape_check(engine: Any, escaper: Any, grips: Any) -> str | None:
    return _hold_mode(engine, escaper, grips)


@hook("escape_save_mode")
def escape_save(engine: Any, escaper: Any, grips: Any) -> str | None:
    return _hold_mode(engine, escaper, grips)


@hook("masked_conditions")
def silk_sees(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """Silk Thread: "it cannot benefit from invisibility against you"."""
    out: dict[str, set[str]] = {}
    for threaded, other in ((attacker, target), (target, attacker)):
        if threaded is None or other is None or not _te().bears_mark(threaded, other.entity_id, SILK):
            continue
        hidden = {iid for iid, c in threaded.conditions.items() if str(c.condition_id).endswith(".invisible")}
        if hidden:
            out[threaded.entity_id] = hidden
    return out or None


# ---------------------------------------------------------------------------------------------------------- Yokai Mask: lineage gifts
def _gift_ready(engine: Any, owner: Any, lineage: str) -> bool:
    return (st.row(engine, owner, "yokai_mask") is not None and lineage_of(owner) == lineage and st.can_react(owner)
            and int(owner.resources.get(RESONANCE, 0) or 0) >= 1)


def _ask_gift(engine: Any, owner: Any, subject: Any, intent: Any, key: str, label: str, prompt: str) -> bool:
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, key.upper(), subject.entity_id, len(engine.events)), owner, f"choice:needle.yokai.{key}", [key],
                        labels={key: label}, preferred=[key], allow_decline=True, name="Yokai Mask (Lineage Gift)", feature_id=MASK, target_id=subject.entity_id,
                        prompt=prompt)
    if not chosen or chosen[0] != key:
        return False
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, owner, MASK, independent=True):
        engine._spend_resource(owner, RESONANCE, 1, MASK)
        owner.reaction_available = False
        engine._append_event("REACTION_RESOLVED", MASK, actor_id=owner.entity_id, target_ids=(subject.entity_id,),
                             payload={"checkpoint": key.upper(), "reaction_name": label})
        from ..paid_relocation import capture, retain
        retain(engine, ("yokai_gift", owner.entity_id, subject.entity_id, key), capture(engine))
        return True


def _wind_perched(engine: Any, owner: Any) -> None:
    """Tengu: "As a Reaction when pushed ... spend 1 Resonance to move 10 feet to a legal space and remain standing\""""
    if not _gift_ready(engine, owner, "tengu"):
        return
    if _ask_gift(engine, owner, owner, engine._active_intent, "wind_perched", "Wind-Perched Step (1 Resonance)",
                 "Wind-Perched Step: you were pushed. Move 10 feet to a legal space and stay on your feet?"):
        from ..paid_relocation import causal_scope, take
        with causal_scope(engine, take(engine, ("yokai_gift", owner.entity_id, owner.entity_id, "wind_perched"))):
            _step(engine, owner, owner, 10, engine._active_intent, "WIND_PERCHED_STEP", "Wind-Perched Step: move where?", MASK)


@hook("condition_attempt")
def perched_against_prone(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    """Tengu: "As a Reaction when ... knocked Prone, spend 1 Resonance to move 10 feet to a legal space and remain standing\""""
    engine = ctx.engine
    if subject is None or str(effect_row.get("condition") or "").lower() != "prone" or ctx.actor.team_id == subject.team_id or not _gift_ready(engine, subject, "tengu"):
        return None
    if not _ask_gift(engine, subject, subject, ctx.intent, "wind_perched", "Wind-Perched Step (1 Resonance)",
                     "Wind-Perched Step: you would be knocked Prone. Move 10 feet to a legal space and stay on your feet?"):
        return None
    from ..paid_relocation import causal_scope, take
    with causal_scope(engine, take(engine, ("yokai_gift", subject.entity_id, subject.entity_id, "wind_perched"))):
        _step(engine, subject, subject, 10, ctx.intent, "WIND_PERCHED_STEP", "Wind-Perched Step: move where?", MASK)
        return False


@hook("forced_movement_reduction")
def river_body(ctx: Any, subject: Any) -> int | None:
    """Kappa: "As a Reaction when you or an adjacent ally would be moved, spend 1 Resonance to reduce that movement by 10 feet and shift
    the creature 5 feet to another legal adjacent space.\""""
    engine = ctx.engine
    if subject is None or ctx.actor.team_id == subject.team_id:
        return None
    for owner in list(engine.state.actors.values()):
        if (not owner.active or owner.team_id != subject.team_id or not _gift_ready(engine, owner, "kappa")
                or (owner is not subject and engine._distance_actor_to_actor(owner, subject) > 5)):
            continue
        if not _ask_gift(engine, owner, subject, ctx.intent, "river_body", "River Body (1 Resonance)",
                         f"River Body: {subject.display_name} would be moved. Take 10 feet off it and shift it 5 feet?"):
            continue
        from ..paid_relocation import causal_scope, take
        with causal_scope(engine, take(engine, ("yokai_gift", owner.entity_id, subject.entity_id, "river_body"))):
            _step(engine, subject, owner, 5, ctx.intent, "RIVER_BODY_SHIFT", "River Body: shift where?", MASK)
            return 10
    return None


@hook("mark_applied")
def wall_clinging_thread(ctx: Any, name: str, subject: Any) -> None:
    """Jorogumo: "Once on each of your turns when you Resonance Mark a creature, you may reduce its Speed by 5 feet until the mark ends.\""""
    from . import needle

    engine, owner = ctx.engine, ctx.actor
    if (str(name or "").strip().lower() not in ("resonance", "resonance mark") or st.row(engine, owner, "yokai_mask") is None or lineage_of(owner) != "jorogumo"
            or engine.state.current_actor_id != owner.entity_id or owner.turn_flags.get("c8_jorogumo_thread") or subject is owner):
        return
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "WALL_CLINGING_THREAD", subject.entity_id), owner, "choice:needle.yokai.thread_slow", ["slow"],
                        labels={"slow": f"Reduce {subject.display_name}'s Speed by 5 feet until the mark ends"}, preferred=["slow"], allow_decline=True,
                        name="Yokai Mask (Wall-Clinging Thread)", feature_id=MASK, target_id=subject.entity_id, prompt="Wall-Clinging Thread: slow the marked creature?")
    if chosen and chosen[0] == "slow":
        owner.turn_flags["c8_jorogumo_thread"] = True
        subject.turn_flags[f"_round_c8_thread_slow:{owner.entity_id}"] = True


@hook("speed")
def thread_slow(engine: Any, actor: Any) -> int | None:
    slowed = [k.split(":", 1)[1] for k in actor.turn_flags if k.startswith("_round_c8_thread_slow:")]
    return -5 * sum(1 for owner in slowed if _te().bears_mark(actor, owner, "Resonance")) or None


# ---------------------------------------------------------------------------------------------------------- True Yokai Form
def _ninefold_feint(engine: Any, kitsune: Any, attacker: Any) -> None:
    """Kitsune True Form: "Once per round when an attack misses you, move up to 15 feet and create a Dream Thread-like foxfire sign on the
    attacker. The sign lasts until the end of your next turn\""""
    from . import needle

    if (lineage_of(kitsune) != "kitsune" or not _held(kitsune, TRUE) or not kitsune.active or attacker.team_id == kitsune.team_id
            or int(kitsune.turn_flags.get("_round_c8_ninefold") or 0) == engine.state.round_number):
        return
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "NINEFOLD_FEINT", attacker.entity_id, len(engine.events)), kitsune,
                        "choice:needle.yokai.ninefold", ["feint"], labels={"feint": "Move up to 15 feet and sign the attacker"}, preferred=["feint"], allow_decline=True,
                        name="True Yokai Form (Ninefold Feint)", feature_id=TRUE_FORM, target_id=attacker.entity_id, prompt="Ninefold Feint: the attack missed you.")
    if not chosen or chosen[0] != "feint":
        return
    kitsune.turn_flags["_round_c8_ninefold"] = engine.state.round_number
    _step(engine, kitsune, kitsune, 15, engine._active_intent, "NINEFOLD_STEP", "Ninefold Feint: move where?", TRUE_FORM)
    _te().run_effects(st.context(engine, kitsune, st.feature_action(engine, kitsune, TRUE_FORM), [attacker], st.numbers(engine, kitsune), engine._active_intent),
                      [{"type": "mark", "mark": SIGN, "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                        "evidence": "a foxfire sign on the attacker until the end of your next turn"}])


def _mountain_wind_cut(ctx: Any, target: Any) -> None:
    """Tengu True Form: "Once on each of your turns after moving at least 20 feet, one creature you hit with your natural weapon takes an
    extra 2d8 damage and must succeed on a Strength saving throw or fall Prone or be pushed 15 feet, your choice.\""""
    from . import needle
    from .hold_still import moved_ft

    engine, actor = ctx.engine, ctx.actor
    if not _held(actor, TRUE) or actor.turn_flags.get("c8_wind_cut") or engine.state.current_actor_id != actor.entity_id or moved_ft(engine, actor) < 20 or not target.active:
        return
    actor.turn_flags["c8_wind_cut"] = True
    kind = str((_form(actor).data or {}).get("type") or "slashing")
    sub = st.context(engine, actor, ctx.action, [target], ctx.numbers, ctx.intent)
    _te().run_effects(sub, [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": [kind], "evidence": "an extra 2d8 damage"}])
    if not target.active or not st.save(sub, target, "str"):
        return
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "MOUNTAIN_WIND_CUT", target.entity_id), actor, "choice:needle.yokai.wind_cut", ["prone", "push"],
                        labels={"prone": "It falls Prone", "push": "It is pushed 15 feet"}, preferred=["prone"], name="True Yokai Form (Mountain Wind Cut)",
                        feature_id=TRUE_FORM, target_id=target.entity_id, prompt="Mountain Wind Cut: it failed its save.")
    if chosen and chosen[0] == "push":
        _te().run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 15, "direction": "away", "evidence": "pushed 15 feet"}])
    else:
        _te().run_effects(sub, [{"type": "condition", "applies_to": "target", "condition": "prone", "duration": {"kind": "until_removed"}, "evidence": "fall Prone"}])


@hook("teleport_gate")
def river_lock(ctx: Any, start: Any, destination: Any) -> bool | None:
    """Kappa True Form, River Lock: "A creature Grappled by you cannot teleport ... unless its Source CL exceeds yours or it succeeds on a
    Charisma saving throw"; Court Beneath the River: "Hostile teleportation ... across its boundary require[s] a Charisma saving throw\""""
    engine, mover = ctx.engine, ctx.actor
    for owner in list(engine.state.actors.values()):
        if not owner.active or owner.team_id == mover.team_id or lineage_of(owner) != "kappa":
            continue
        locked = _held(owner, TRUE) and any(str(c.condition_id).endswith("grappled") and c.source_actor_id == owner.entity_id for c in mover.conditions.values())
        crossing = any(bool(_in_zone(z, start)) != bool(_in_zone(z, destination)) for z in _zones(engine, owner, "Court Beneath the River"))
        if not locked and not crossing:
            continue
        if locked and not crossing and int((ctx.numbers or {}).get("cl") or 0) > int(st.numbers(engine, owner).get("cl") or 0):
            continue
        if st.save(st.context(engine, owner, st.feature_action(engine, owner, TRUE_FORM if locked else LORD), [mover], st.numbers(engine, owner), ctx.intent), mover, "cha"):
            return False
    return None


def _zones(engine: Any, owner: Any, name: str) -> list[Any]:
    return [z for z in engine.state.zones.values() if z.active and z.owner_id == owner.entity_id and (z.trigger_profile or {}).get("name") == name]


def _in_zone(zone: Any, cell: Any) -> bool:
    return cell is not None and any((c.x, c.y) == (cell.x, cell.y) for c in zone.affected_cells)


def _end_zone(engine: Any, owner: Any, zone: Any) -> None:
    zone.active = False
    engine._append_event("ZONE_REMOVED", zone.source_definition_id, actor_id=owner.entity_id, payload={"zone_id": zone.zone_id, "reason": "REPLACED"})


@effect("yokai_grand_silk")
def grand_silk(ctx: Any, row: dict[str, Any]) -> None:
    """Jorogumo True Form, Grand Silk: "create a 20-foot-square web zone within 60 feet until the end of the scene. The zone is difficult
    terrain for enemies. A creature that enters for the first time on a turn or starts there makes a Dexterity saving throw, becoming
    Restrained until the end of its next turn on a failure ... You can have one Grand Silk zone at a time.\""""
    from .. import zones

    engine, owner = ctx.engine, ctx.actor
    for old in _zones(engine, owner, "Grand Silk"):
        _end_zone(engine, owner, old)
    zones.create(ctx, {"shape": "cube", "size_ft": 20, "difficult": "hostile", "duration": {"kind": "scene"}, "name": "Grand Silk",
                       "triggers": [{"who": "hostile", "on": ["enter", "start"], "effects": [{"type": "save", "ability": "dex", "dc": "technique_save_dc", "on_fail": [
                           {"type": "condition", "applies_to": "target", "condition": "restrained", "duration": {"kind": "target_next_turn"},
                            "evidence": "Restrained until the end of its next turn"},
                           {"type": "escape_option", "guards": ["restrained"], "kind": "save", "abilities": ["DEX"],
                            "name": "Grand Silk", "evidence": "A creature can use its Action to repeat the save, ending the restraint on success."}]}]}]})


# ---------------------------------------------------------------------------------------------------------- Yokai Lord
def _apotheosis_open(actor: Any) -> bool:
    court = next(iter(_held(actor, COURT)), None)
    return court is not None and not st.data_of(actor, court).get("apotheosis")


def _spend_apotheosis(actor: Any) -> None:
    court = next(iter(_held(actor, COURT)), None)
    if court is not None:
        st.set_data(actor, court, apotheosis=True)  # "Once during the activation"


@effect("yokai_descent")
def heaven_scouring_descent(ctx: Any, row: dict[str, Any]) -> None:
    """Tengu, Heaven-Scouring Descent: "move up to your fly Speed without provoking reactions and make one Cultivation Attack against every
    hostile creature whose space you pass within 5 feet of, maximum Proficiency Bonus targets. On a hit, deal 4d10 + Wisdom modifier Thunder
    or Force damage.\""""
    from . import needle
    from .rider_movement import step

    engine, owner = ctx.engine, ctx.actor
    spot = getattr(ctx.intent, "destination", None)
    routes = st.routes(engine, owner, 50, all_creatures=True)
    found = next(((path, cost) for cell, (path, cost) in routes.items() if spot is not None and (cell.x, cell.y) == (spot.x, spot.y)), None)
    if found is None:
        return
    _spend_apotheosis(owner)
    path = list(found[0])
    passed = [c for c in engine.state.actors.values() if c.active and c.team_id != owner.team_id
              and any(engine.grid.distance_ft(cell, c.position) <= 5 for cell in path)]
    step(engine, owner, path, LORD)
    pb = int(ctx.numbers.get("pb") or 2)
    if len(passed) > pb:
        ids = [c.entity_id for c in passed]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "DESCENT_TARGETS", owner.entity_id), owner, "choice:needle.yokai.descent", ids,
                            labels={c.entity_id: c.display_name for c in passed}, preferred=ids[:pb], minimum=1, maximum=pb, name="Heaven-Scouring Descent",
                            feature_id=LORD, prompt=f"Heaven-Scouring Descent: attack which {pb}?")
        passed = [c for c in passed if c.entity_id in (chosen or ids[:pb])][:pb]
    for creature in passed:
        _te().run_effects(st.context(engine, owner, ctx.action, [creature], ctx.numbers, ctx.intent),
                          [{"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "on_hit": [
                              {"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 10}, "formula": "key_ability_modifier",
                               "damage_types": ["thunder", "force"], "evidence": "4d10 + Wisdom modifier Thunder or Force damage"}]}])


@effect("yokai_river_court")
def court_beneath_the_river(ctx: Any, row: dict[str, Any]) -> None:
    """Kappa, Court Beneath the River: "a 30-foot-radius water court centered on a point within 60 feet. It lasts for the scene, is difficult
    terrain for enemies" (its boundary: river_lock above)."""
    from .. import zones

    _spend_apotheosis(ctx.actor)
    zones.create(ctx, {"shape": "sphere", "size_ft": 30, "difficult": "hostile", "duration": {"kind": "scene"}, "name": "Court Beneath the River"})


@effect("yokai_hundred_names")
def web_of_a_hundred_names(ctx: Any, row: dict[str, Any]) -> None:
    """Jorogumo, Web of a Hundred Names: "choose up to Proficiency Bonus creatures you can perceive within 60 feet. Each makes a Dexterity
    saving throw. On a failure ... Its Speed becomes 0 until it uses an Action to repeat the save or an ally destroys the thread Anchor, which
    has AC equal to your Cultivation Save DC and Hit Points equal to 3 x Proficiency Bonus.\""""
    from ..gate2_runtime_models import RuntimeObjectState
    from . import needle
    from .. import stealth

    engine, owner = ctx.engine, ctx.actor
    pb = int(ctx.numbers.get("pb") or 2)
    near = [c for c in engine.state.actors.values() if c.active and c is not owner and engine._distance_actor_to_actor(owner, c) <= 60 and stealth.sees(engine, owner, c)]
    if not near:
        return
    ids = [c.entity_id for c in near]
    foes = [c.entity_id for c in near if c.team_id != owner.team_id]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "HUNDRED_NAMES", owner.entity_id), owner, "choice:needle.yokai.hundred_names", ids,
                        labels={c.entity_id: c.display_name for c in near}, preferred=(foes or ids)[:pb], minimum=1, maximum=min(pb, len(ids)),
                        name="Web of a Hundred Names", feature_id=LORD, prompt=f"Web of a Hundred Names: bind up to {pb} creatures.")
    picked = [c for c in near if c.entity_id in (chosen or [])][:pb]
    if not picked:
        return
    _spend_apotheosis(owner)
    hp = 3 * pb
    anchor = RuntimeObjectState(object_id=f"{ANCHOR}{owner.entity_id}:{engine.state.event_sequence}", object_kind="HUNDRED_NAMES_ANCHOR", position=owner.position,
                                unattended=False, flammable=False, owner_id=owner.entity_id, ac=int(ctx.numbers.get("save_dc") or 10), current_hp=hp, maximum_hp=hp,
                                component={"label": "Thread Anchor (Web of a Hundred Names)"})
    engine._update_object(anchor, LORD, owner.entity_id)
    for creature in picked:
        if st.save(st.context(engine, owner, ctx.action, [creature], ctx.numbers, ctx.intent), creature, "dex"):
            engine._apply_condition(creature, WEB, LORD, owner.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"rule": {"speed_zero": True}, "anchor": anchor.object_id,
                                          "label": "Web of a Hundred Names: Speed 0 until it breaks the silk (Action, Dexterity save) or the Thread Anchor is destroyed"})


def _anchor_broken(engine: Any, kwargs: dict[str, Any]) -> None:
    obj = (kwargs.get("payload") or {}).get("object") or {}
    if not str(obj.get("object_id") or "").startswith(ANCHOR) or not (obj.get("destroyed") or int(obj.get("current_hp") or 0) <= 0):
        return
    for creature in list(engine.state.actors.values()):
        for held in [c for c in creature.conditions.values() if c.condition_id == WEB and (c.data or {}).get("anchor") == obj.get("object_id")]:
            st.remove(engine, creature, held, "ANCHOR_DESTROYED")


@hook("match_start")
def break_the_silk_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[BREAK_WEB] = ActionDefinition(
        source_definition_id=BREAK_WEB, display_name="Break the Hundred Names Silk", owner_id="*", economy=EconomyKind.ACTION, resolution_kind="TYPED",
        target_kind="SELF", parameters={"typed": {"effects": [{"type": "yokai_break_silk"}], "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
                                        "expected_damage": 0, "description": "Web of a Hundred Names: repeat the Dexterity save; on a success your Speed is no longer 0."})


@hook("additional_actions")
def break_the_silk_offered(engine: Any, actor: Any) -> list[str]:
    return [BREAK_WEB] if _held(actor, WEB) else []


@effect("yokai_break_silk")
def break_the_silk(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    for held in list(_held(actor, WEB)):
        owner = engine.state.actors.get(held.source_actor_id or "")
        if owner is None or not st.save(st.context(engine, owner, st.feature_action(engine, owner, LORD), [actor], st.numbers(engine, owner), ctx.intent), actor, "dex"):
            st.remove(engine, actor, held, "BROKEN")


# ---------------------------------------------------------------------------------------------------------- buttons and gates
@hook("compile_actions")
def yokai_buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned = info["owned_ids"]
    if not any(f in owned for f in (MASK, UNMASK, TRUE_FORM, LORD)):
        return None
    numbers = info["numbers"]
    wis = int((numbers.get("ability_mods") or {}).get("WIS", numbers.get("key_mod", 0)) or 0)
    out = [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.yokai.lineage.{key}", display_name=f"Yokai Lineage: {label}", owner_id=info["actor_id"],
                            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                            parameters={"setting_only": True, "player_only": True, "yokai": "lineage",
                                        "typed": {"effects": [{"type": "yokai_lineage_pick", "lineage": key}], "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                                        "expected_damage": 0, "description": f"Your yokai lineage (chosen at CL3) is {label}: it stays for the fight."})
           for key, (label, _kinds) in LINEAGES.items()]
    if any(f in owned for f in (UNMASK, TRUE_FORM, LORD)):
        typed = {"effects": [{"type": "attack", "attack_kind": "melee", "count": 1, "on_hit": [{"type": "damage", "weapon_damage": True}]}],
                 "numbers": {**numbers, "attack_bonus": int(numbers.get("pb") or 2) + wis},
                 "weapon": {"damage": {"count": 1, "sides": 8, "modifier": wis}, "damage_types": [k.upper() for k in ("psychic", "fire", "thunder", "force", "cold", "bludgeoning", "poison", "piercing", "slashing")]},
                 "duration": {"kind": "instant"}, "range_ft": None, "riders": [], "source": UNMASK + ":natural_weapon", "attack_action": True}
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.yokai.natural_weapon", display_name="Yokai Natural Weapon", owner_id=info["actor_id"],
                                    economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
                                    parameters={"typed": typed, "yokai": "weapon", "expected_damage": 4 + wis,
                                                "description": "Unmasking: your natural weapon (reach 5 feet, Wisdom): 1d8 + Wisdom of the type you chose (1d10 in True Yokai Form)."}))
    def button(key: str, name: str, economy: Any, target: str, range_ft: int | None, rows: list[dict[str, Any]], text: str, source: str) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.yokai.{key}", display_name=name, owner_id=info["actor_id"], economy=economy,
                                resolution_kind="TYPED", target_kind=target, range_ft=range_ft,
                                parameters={"typed": {"numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "source": source, "effects": rows},
                                            "expected_damage": 0, "yokai": key, "description": text})

    if TRUE_FORM in owned or LORD in owned:
        out.append(button("grand_silk", "Grand Silk", EconomyKind.ACTION, "CELL", 60, [{"type": "yokai_grand_silk"}],
                          "Jorogumo True Form (Action): a 20-foot-square web within 60 feet for the fight; difficult terrain for enemies, and an enemy entering or "
                          "starting its turn there makes a Dexterity save or is Restrained until the end of its next turn. One at a time.", TRUE_FORM + ":grand_silk"))
    if LORD in owned:
        out.append(button("descent", "Heaven-Scouring Descent", EconomyKind.NONE, "SELF", None,
                          [{"type": "yokai_descent", "applies_to": "self", "picks_destination": True, "distance_ft": 50}],
                          "Tengu Yokai Lord (once in the activation): fly up to 50 feet without provoking and make a Cultivation Attack against each hostile "
                          "creature you pass within 5 feet of (up to your Proficiency Bonus of them): 4d10 + Wisdom Thunder or Force on a hit.", LORD + ":descent"))
        out.append(button("river_court", "Court Beneath the River", EconomyKind.NONE, "CELL", 60, [{"type": "yokai_river_court"}],
                          "Kappa Yokai Lord (once in the activation): a 30-foot-radius water court within 60 feet for the fight; difficult terrain for enemies, "
                          "and a hostile teleport across its edge needs a Charisma save.", LORD + ":river_court"))
        out.append(button("hundred_names", "Web of a Hundred Names", EconomyKind.NONE, "SELF", None, [{"type": "yokai_hundred_names"}],
                          "Jorogumo Yokai Lord (once in the activation): up to your Proficiency Bonus of creatures within 60 feet make a Dexterity save; on a failure "
                          "their Speed is 0 until they break the silk (Action, the save again) or the Thread Anchor (AC your DC, 3 x PB Hit Points) is destroyed.", LORD + ":hundred_names"))
    return out


_APOTHEOSES = {"descent": "tengu", "river_court": "kappa", "hundred_names": "jorogumo"}


@hook("candidate_allowed")
def yokai_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    kind = str(((getattr(action, "parameters", None) or {}).get("yokai")) or "")
    if kind == "lineage":
        return None if lineage_of(actor) is None else False  # "The choice cannot normally be changed."
    if kind == "weapon":
        return None if _form(actor) is not None else False
    if kind == "grand_silk":
        return None if _held(actor, TRUE) and lineage_of(actor) == "jorogumo" else False
    if kind in _APOTHEOSES:
        if not (_apotheosis_open(actor) and lineage_of(actor) == _APOTHEOSES[kind] and engine.state.current_actor_id == actor.entity_id):
            return False
        spot = getattr(candidate, "destination", None)
        if kind == "descent" and spot is not None:
            return None if any((c.x, c.y) == (spot.x, spot.y) for c in st.routes(engine, actor, 50, all_creatures=True)) else False
    return None
