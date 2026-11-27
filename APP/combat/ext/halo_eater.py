"""Halo Eater (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Halo Eater: Stolen Radiance, Qualifying Radiance, CL3 Taste the Radiance, CL6
Bite the Halo, CL10 Stolen Benediction, CL14 Crown of Borrowed Light, CL18 Empty Heaven Maw). No Spheres 5e or D&D 5.5e counterpart.
Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json (Taste the Radiance, Stolen Benediction);
the actions need none.

Qualifying radiance, as the table sees it: a supernatural blessing or ward is a beneficial effect on the creature that its own side
put there (a buff condition, AC, resistance, immunity or Speed -- combat/ext/end_effect.py ``found(..., select="beneficial")``);
receiving healing or Temporary Hit Points from a technique counts as gaining it. The GM rules out mundane ones.

Stolen Radiance (tradition text): a pool (resource:named.stolen_radiance), 0 to start, maximum PB, for the fight.

What runs:
  * Stolen Radiance: +1 when a hostile creature within 60 feet that you can see is healed or gains Temporary Hit Points from a
    technique, gains a beneficial effect from its own side, or loses one to your Halo Eater features (no more than 1 a turn).
  * At that moment you may use your Reaction (asked; the AI tastes): Taste the Radiance (1 Resonance) -- Temporary HP = PB and the
    creature is savored until the end of your next turn (your Halo Eater features treat it as Resonance Marked); or Stolen
    Benediction (3 Resonance and 1 Stolen Radiance) -- Restoring (you or an ally within 30 feet regains 2d8 + Wisdom), Warding (2 x
    PB + Wisdom Temporary HP and Advantage on the next Int/Wis/Cha save before the end of its next turn), Cleansing (end your
    Charmed or Frightened) or Reflecting (the creature is Resonance Marked; already marked: your chosen Spiritual Pressure).
    Taste the Radiance also answers your Resonance Mark landing on a creature carrying radiance.
  * Bite the Halo (Action, 60 feet, 3 Resonance; a savored or Resonance Marked creature, or one carrying radiance): Charisma save --
    failed, 4d8 + Wisdom Psychic or Radiant (the better-landing) and one of its radiance effects (asked) ends if its source's CL is
    below yours, else is suppressed until the end of your next turn, with a repeat save each target turn end; +1 Stolen Radiance. Success: half.
  * Crown of Borrowed Light (Bonus Action, 6 Resonance, the fight; a 40-foot field of its light that moves with you): Resistance to
    Radiant and Psychic for you; once on each of your turns when your Spirit Awakening feature damages a savored or marked creature,
    an ally in the field gains Wisdom + PB Temporary HP, and if it carries radiance it suffers your chosen Spiritual Pressure. Facets,
    one per Stolen Radiance spent (up to 3, asked): Sanctuary (+1 to allies' Int/Wis/Cha saves in the field), Hunger (the first time
    each round a hostile creature in the field gains radiance, PB Psychic and savored), False Grace (Reaction, 2 Resonance: an ally
    in the field that would drop to 0 Hit Points drops to 1; the Facet is then lost; once per creature).
  * Empty Heaven Maw (Action, 90 feet, 10 Resonance and all your Stolen Radiance, at least 1; a savored or marked creature carrying
    radiance): Charisma save -- failed, 10d10 + Wisdom Psychic or Radiant; one radiance effect per Stolen Radiance spent (up to
    three, asked) ends (source CL below yours), is suppressed for the fight (equal) or until the end of your next turn (higher); you
    regain half the damage dealt (up to half your Hit Point maximum). Equal-source scene suppression allows an optional
    Charisma save at each target turn end; three successes restore one selected expression. Success: half, and one ordinary
    effect is suppressed until the start of your next turn.

Plug-in surface: effects halo_bite, halo_crown, halo_maw; hooks event, damage_dealt, save, incoming_damage, would_drop, turn_end,
candidate_allowed. Shared helpers used: spirit_traditions (row/context/numbers/feature_action/can_react/save/remove/pick_creature/
routes), end_effect (found/source_cl/remove_instance/suppress), needle.ask, stealth.sees, zones.typed_zones, typed_executor.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.halo_eater.feature."
TASTE = TRADITION + "taste_the_radiance"
BITE = TRADITION + "bite_the_halo"
BENEDICTION = TRADITION + "stolen_benediction"
CROWN = TRADITION + "crown_of_borrowed_light"
MAW = TRADITION + "empty_heaven_maw"
RADIANCE = "resource:named.stolen_radiance"
RESONANCE = "resource:core.resonance"
SAVORED = "condition:typed.savored"
CROWN_STATE = "condition:typed.crown_of_borrowed_light"
BENEFIT = {"select": "beneficial"}


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def radiance_on(engine: Any, creature: Any) -> list[tuple[str, str, Any]]:
    """Its qualifying radiance as the table sees it: beneficial effects its own side put on it."""
    from .end_effect import found

    return found(engine, creature, BENEFIT)


def savored(creature: Any, eater_id: str) -> bool:
    return any(c.condition_id == SAVORED and c.source_actor_id == eater_id for c in creature.conditions.values())


def _claimed(engine: Any, eater: Any, creature: Any) -> bool:
    """"can target a savored creature as though it were Resonance Marked by you"."""
    return savored(creature, eater.entity_id) or _te().bears_mark(creature, eater.entity_id, "Resonance")


def gain_radiance(engine: Any, eater: Any, source: str) -> bool:
    token = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    if eater.turn_flags.get("radiance_round_gained") == token or eater.resources.get(RADIANCE, 0) >= eater.resource_maximums.get(RADIANCE, 0):
        return False
    eater.turn_flags["radiance_round_gained"] = token  # "no more than 1 per turn"
    engine._gain_resource(eater, RADIANCE, 1, source)
    return True


def _savor(engine: Any, eater: Any, creature: Any) -> None:
    for held in [c for c in creature.conditions.values() if c.condition_id == SAVORED and c.source_actor_id == eater.entity_id]:
        st.remove(engine, creature, held, "REPLACED")
    ctx = st.context(engine, eater, st.feature_action(engine, eater, TASTE), [creature], st.numbers(engine, eater))
    expires = _te().effect_expiry(ctx, {"duration": {"kind": "until_end_of_your_next_turn"}}, creature, condition=True)
    engine._apply_condition(creature, SAVORED, TASTE, eater.entity_id, expires_on=expires,
                            data={"label": f"Savored by {eater.display_name} (its Halo Eater features treat it as Resonance Marked)"})


# ------------------------------------------------------------------------------------------------ radiance moments
def _gained_radiance(event_type: str, kwargs: dict[str, Any], engine: Any) -> Any:
    """The creature that just gained qualifying radiance in this event, or None."""
    payload = kwargs.get("payload") or {}
    target = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    if target is None:
        return None
    source = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if event_type in ("HEALING_APPLIED", "TEMP_HP_GRANTED"):
        return target if int(payload.get("after") or 0) > int(payload.get("before") or 0) else None
    if event_type == "CONDITION_APPLIED" and source is not None and source.team_id == target.team_id:
        held = target.conditions.get(str(payload.get("instance_id") or ""))
        from .end_effect import helpful

        return target if held is not None and helpful(held, "condition") and not str(held.condition_id).startswith(_te().MARK_PREFIX) else None
    if event_type == "MODIFIER_APPLIED" and source is not None and source.team_id == target.team_id:
        held = target.modifiers.get(str(payload.get("modifier_id") or ""))
        from .end_effect import helpful

        return target if held is not None and helpful(held, "modifier") else None
    return None


@hook("event")
def radiance_moment(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ("HEALING_APPLIED", "TEMP_HP_GRANTED", "CONDITION_APPLIED", "MODIFIER_APPLIED"):
        return
    payload = kwargs.get("payload") or {}
    if event_type == "CONDITION_APPLIED" and str(payload.get("condition_id") or "").startswith(_te().MARK_PREFIX):
        _marked_while_radiant(engine, kwargs)
        return
    creature = _gained_radiance(event_type, kwargs, engine)
    if creature is None or not creature.active:
        return
    from .. import stealth

    for eater in list(engine.state.actors.values()):
        if not eater.active or eater.team_id == creature.team_id or st.row(engine, eater, "taste_the_radiance") is None:
            continue
        if engine._distance_actor_to_actor(eater, creature) > 60 or not stealth.sees(engine, eater, creature):
            continue
        gain_radiance(engine, eater, TASTE)
        _hunger(engine, creature)
        _answer(engine, eater, creature, benediction=True)


def _marked_while_radiant(engine: Any, kwargs: dict[str, Any]) -> None:
    """Taste the Radiance also triggers when a creature "becomes Resonance Marked by you while carrying qualifying radiance"."""
    creature = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    eater = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if (creature is None or eater is None or not creature.active or eater.team_id == creature.team_id or st.row(engine, eater, "taste_the_radiance") is None
            or not radiance_on(engine, creature) or engine._distance_actor_to_actor(eater, creature) > 60):
        return
    _answer(engine, eater, creature, benediction=False)


def _answer(engine: Any, eater: Any, creature: Any, *, benediction: bool) -> None:
    if not st.can_react(eater):
        return
    options: dict[str, str] = {}
    if eater.resources.get(RESONANCE, 0) >= 1:
        options["taste"] = f"Taste the Radiance (1 Resonance): {eater.display_name} gains Temporary HP and {creature.display_name} is savored"
    if benediction and st.row(engine, eater, "stolen_benediction") is not None and eater.resources.get(RESONANCE, 0) >= 3 and eater.resources.get(RADIANCE, 0) >= 1:
        options.update({"restoring": "Stolen Benediction, Restoring (3 Resonance, 1 Stolen Radiance): you or an ally within 30 feet regains 2d8 + Wisdom",
                        "warding": "Stolen Benediction, Warding: 2 x PB + Wisdom Temporary HP and Advantage on the next Int/Wis/Cha save",
                        "cleansing": "Stolen Benediction, Cleansing: end your Charmed or Frightened",
                        "reflecting": f"Stolen Benediction, Reflecting: {creature.display_name} is Resonance Marked (or gets a Spiritual Pressure effect)"})
        if not any(c.condition_id.rsplit(".", 1)[-1] in ("charmed", "frightened") for c in eater.conditions.values()):
            options.pop("cleansing")
    if not options:
        return
    from . import needle

    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "HALO_REACTION", creature.entity_id), eater,
                        "choice:needle.halo_eater.reaction", list(options), labels=options, preferred=["taste"] if "taste" in options else [],
                        allow_decline=True, default="first" if "taste" in options else "decline", name="Halo Eater",
                        feature_id=TASTE, target_id=creature.entity_id,
                        prompt=f"{creature.display_name} is touched by radiance. Use your Reaction?")
    if not chosen or chosen[0] not in options:
        return
    pick = chosen[0]
    with activation(engine, eater, TASTE if pick == "taste" else BENEDICTION):
        eater.reaction_available = False
        feature = TASTE if pick == "taste" else BENEDICTION
        engine._append_event("REACTION_RESOLVED", feature, actor_id=eater.entity_id, target_ids=(creature.entity_id,),
                             payload={"checkpoint": "RADIANCE", "reaction_name": "Taste the Radiance" if pick == "taste" else "Stolen Benediction"})
        numbers = st.numbers(engine, eater)
        wis, pb = int(numbers.get("key_mod") or 0), int(numbers.get("pb") or 2)
        if pick == "taste":
            engine._spend_resource(eater, RESONANCE, 1, TASTE)
            engine._grant_temp_hp(eater, pb, TASTE, eater.entity_id)  # "These Temporary Hit Points do not stack with themselves"
            _savor(engine, eater, creature)
            return
        engine._spend_resource(eater, RESONANCE, 3, BENEDICTION)
        engine._spend_resource(eater, RADIANCE, 1, BENEDICTION)
        ctx = st.context(engine, eater, st.feature_action(engine, eater, BENEDICTION), [creature], numbers)
        if pick in ("restoring", "warding"):
            near = [a for a in engine.state.actors.values() if a.active and a.team_id == eater.team_id and (a is eater or engine._distance_actor_to_actor(eater, a) <= 30)]
            ally = st.pick_creature(engine, engine._active_intent, eater, near, checkpoint="BENEDICTION_ALLY", choice_id="choice:needle.halo_eater.benediction_ally",
                                    prompt="Stolen Benediction: you or which ally within 30 feet?", name="Stolen Benediction", feature_id=BENEDICTION,
                                    preferred=min(near, key=lambda a: (a.current_hp - a.maximum_hp, a.entity_id)))
            if ally is None:
                return
            sub = st.context(engine, eater, ctx.action, [ally], numbers)
            if pick == "restoring":
                _te().run_effects(sub, [{"type": "healing", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "formula": "key_ability_modifier",
                                         "evidence": "regains Hit Points equal to 2d8 + Wisdom modifier"}])
            else:
                engine._grant_temp_hp(ally, 2 * pb + wis, BENEDICTION, eater.entity_id)
                _te().run_effects(sub, [{"type": "advantage", "applies_to": "target", "on": "its next Intelligence, Wisdom, or Charisma saving throw",
                                         "duration": {"kind": "until_end_of_next_turn"},
                                         "evidence": "Advantage on the next Intelligence, Wisdom, or Charisma saving throw made before the end of its next turn"}])
        elif pick == "cleansing":
            held = next((c for _, c in sorted(eater.conditions.items()) if c.condition_id.rsplit(".", 1)[-1] in ("charmed", "frightened")), None)
            if held is not None:
                st.remove(engine, eater, held, "CLEANSED")
        else:
            rows = [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "impose one ordinary Spiritual Pressure effect on it"}] \
                if _te().bears_mark(creature, eater.entity_id, "Resonance") else \
                [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                  "evidence": "The triggering creature becomes Resonance Marked by you"}]
            _te().run_effects(ctx, rows)


# ---------------------------------------------------------------------------------------------------------- Bite the Halo, Maw
def _pick_effects(engine: Any, eater: Any, target: Any, count: int, intent: Any, name: str, feature: str) -> list[tuple[str, str, Any]]:
    from . import needle
    from .end_effect import found

    rows = found(engine, target, BENEFIT)
    if not rows or count <= 0:
        return []
    ids = [f"e{i}" for i in range(len(rows))]
    labels = {f"e{i}": _label(kind, item) for i, (kind, _key, item) in enumerate(rows)}
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, f"{name.upper().replace(' ', '_')}_EFFECTS", target.entity_id), eater,
                        f"choice:needle.halo_eater.{feature.rsplit('.', 1)[-1]}_effects", ids, labels=labels, preferred=ids[:count],
                        minimum=1, maximum=min(count, len(ids)), default_count=min(count, len(ids)),
                        prompt=f"{name}: which of {target.display_name}'s radiance effects?", name=name, feature_id=feature, target_id=target.entity_id)
    picked = [rows[ids.index(i)] for i in chosen if i in ids][:count]
    return picked or rows[:count]


def _label(kind: str, item: Any) -> str:
    if kind == "condition":
        return str(item.condition_id).rsplit(".", 1)[-1].replace("_", " ").title()
    return f"{str(item.target_field).replace('_', ' ')} {item.value}"


def _unmake(ctx: Any, target: Any, row: tuple[str, str, Any], *, equal_rounds: int, scene: bool = False) -> str:
    """End lower-source effects; suppress equal ones for a scene or N turns.

    Higher-source effects retain their existing next-turn-end boundary.
    """
    from .end_effect import SUPPRESSED_FLAG, remove_instance, source_cl, suppress

    kind, key, item = row
    mine = int((ctx.numbers or {}).get("cl") or 1)
    theirs = source_cl(ctx, item)
    if theirs < mine:
        remove_instance(ctx, target, kind, key, item)
        return "ended"
    equal_scene = scene and theirs == mine
    suppress(target, kind, key, item, rounds=equal_rounds if theirs == mine else 1, by=ctx.actor, engine=ctx.engine,
             boundary="scene" if equal_scene else "end")
    if equal_scene:
        target.turn_flags[SUPPRESSED_FLAG][-1].update(
            maw_source=ctx.actor.entity_id, maw_dc=int(ctx.numbers.get("save_dc") or 0), maw_successes=0)
    if not scene and theirs == mine:
        target.turn_flags[SUPPRESSED_FLAG][-1].update(
            bite_source=ctx.actor.entity_id, bite_dc=int(ctx.numbers.get("save_dc") or 0))
    return "suppressed"


@hook("turn_end")
def bite_repeat_save(engine: Any, target: Any) -> None:
    """Each live Bite suppression repeats its saved DC, independently of Maw."""
    from .end_effect import SUPPRESSED_FLAG, restore_suppressed

    for row in list(target.turn_flags.get(SUPPRESSED_FLAG, [])):
        if not row.get("bite_source"):
            continue
        item = (target.conditions if row["kind"] == "condition" else target.modifiers).get(row["key"])
        source = engine.state.actors.get(row["bite_source"])
        if item is None:
            restore_suppressed(engine, target, row)
        elif source is not None and target.active:
            numbers = {**st.numbers(engine, source), "save_dc": int(row["bite_dc"])}
            ctx = st.context(engine, source, st.feature_action(engine, source, BITE), [target], numbers, engine._active_intent)
            if not st.save(ctx, target, "cha"):
                restore_suppressed(engine, target, row)


@effect("halo_bite")
def bite(ctx: Any, row: dict[str, Any]) -> None:
    engine, eater, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    failed = st.save(ctx, target, "cha",
                     on_fail=[{"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "formula": "key_ability_modifier",
                               "damage_types": ["psychic", "radiant"], "evidence": "4d8 + Wisdom modifier Psychic or Radiant damage, your choice"}],
                     on_success=[{"type": "half_damage", "applies_to": "target", "evidence": "The target takes half damage."}])
    if not failed or not target.active:
        return
    for picked in _pick_effects(engine, eater, target, 1, ctx.intent, "Bite the Halo", BITE):
        how = _unmake(ctx, target, picked, equal_rounds=1)
        note(engine, BITE, eater, f"Bite the Halo: {target.display_name}'s {_label(picked[0], picked[2])} is {how}.", (target,))
        gain_radiance(engine, eater, BITE)  # "If you end or suppress a qualifying effect, gain 1 Stolen Radiance"


@effect("halo_maw")
def maw(ctx: Any, row: dict[str, Any]) -> None:
    engine, eater, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    spent = int(eater.resources.get(RADIANCE, 0) or 0)
    if spent:
        engine._spend_resource(eater, RADIANCE, spent, MAW)  # "and all remaining Stolen Radiance"
    hp_before = target.current_hp
    failed = st.save(ctx, target, "cha",
                     on_fail=[{"type": "damage", "applies_to": "target", "dice": {"count": 10, "sides": 10}, "formula": "key_ability_modifier",
                               "damage_types": ["psychic", "radiant"], "evidence": "10d10 + Wisdom modifier Psychic or Radiant damage, your choice"}],
                     on_success=[{"type": "half_damage", "applies_to": "target", "evidence": "The target takes half damage."}])
    dealt = max(0, hp_before - target.current_hp)
    if failed:
        for picked in _pick_effects(engine, eater, target, min(3, max(1, spent)), ctx.intent, "Empty Heaven Maw", MAW):
            how = _unmake(ctx, target, picked, equal_rounds=1, scene=True)
            note(engine, MAW, eater, f"Empty Heaven Maw: {target.display_name}'s {_label(picked[0], picked[2])} is {how}.", (target,))
        heal = min(dealt // 2, eater.maximum_hp // 2)  # "half the damage actually dealt, to a maximum of half your Hit Point maximum"
        if heal > 0:
            from . import life_state

            life_state.heal_to(engine, eater, heal, MAW, eater.entity_id)
    else:
        from .end_effect import suppress

        for kind, key, item in _pick_effects(engine, eater, target, 1, ctx.intent, "Empty Heaven Maw", MAW):
            suppress(target, kind, key, item, rounds=1, by=eater, engine=engine, boundary="start")


@hook("turn_end")
def maw_repeat_save(engine: Any, target: Any) -> None:
    """Optional target-owned saves; progress belongs to the suppressing source.

    Each source's three successful saves restore one still-live expression,
    then reset progress for its remaining expressions. Expired rows disappear
    without restoring their original effect. Only Maw-tagged scene rows act.
    """
    from . import needle
    from .end_effect import SUPPRESSED_FLAG, restore_suppressed

    rows = [r for r in target.turn_flags.get(SUPPRESSED_FLAG, []) if r.get("maw_source")]
    for row in rows:
        if row["key"] not in (target.conditions if row["kind"] == "condition" else target.modifiers):
            restore_suppressed(engine, target, row)
    rows = [r for r in target.turn_flags.get(SUPPRESSED_FLAG, []) if r.get("maw_source")]
    for source_id in dict.fromkeys(r["maw_source"] for r in rows):
        source = engine.state.actors.get(source_id)
        if source is None or not target.active:
            continue
        group = [r for r in rows if r["maw_source"] == source_id]
        progress = int(group[0].get("maw_successes", 0))
        chosen = needle.ask(
            engine, engine._active_intent, needle.checkpoint_id(engine, "MAW_REPEAT", source_id), target,
            "choice:needle.halo_eater.maw_repeat", ["save"],
            labels={"save": f"Repeat the Charisma save (no action or resource cost; {progress}/3 successes)"},
            preferred=["save"], allow_decline=True, name="Empty Heaven Maw", feature_id=MAW,
            target_id=target.entity_id,
            prompt=f"Empty Heaven Maw by {source.display_name} suppressed {target.display_name}'s radiance. "
                   "At the end of your turn, you may repeat its Charisma save at no cost. "
                   "Three successes restore one expression; otherwise it stays suppressed for this fight or until it expires.")
        if not chosen:
            continue
        numbers = {**st.numbers(engine, source), "save_dc": int(group[0]["maw_dc"])}
        ctx = st.context(engine, source, st.feature_action(engine, source, MAW), [target], numbers, engine._active_intent)
        if st.save(ctx, target, "cha"):
            continue
        progress += 1
        for row in group:
            row["maw_successes"] = progress
        if progress < 3:
            continue
        ids = [str(i) for i in range(len(group))]
        labels = {}
        for i, row in enumerate(group):
            label = row["original"].replace("condition:typed.", "").replace("_", " ").title()
            if row["kind"] == "modifier":
                item = target.modifiers[row["key"]]
                label = ("Speed in feet" if row["original"] == "speed_ft" else label) + f": {item.value}"
            labels[str(i)] = label
        picked = needle.ask(
            engine, engine._active_intent, needle.checkpoint_id(engine, "MAW_RESTORE", source_id), target,
            "choice:needle.halo_eater.maw_restore", ids, labels=labels, preferred=ids[:1],
            minimum=1, maximum=1, name="Empty Heaven Maw", feature_id=MAW, target_id=target.entity_id,
            prompt=f"Empty Heaven Maw: {target.display_name} succeeded three times. Choose one suppressed expression to restore "
                   "at no cost, with its original remaining duration.")
        restore_suppressed(engine, target, group[int(picked[0])])
        for row in group:
            row["maw_successes"] = 0


@hook("candidate_allowed")
def halo_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    feature = st.feature_of(action) if action is not None else ""
    if feature not in (BITE, MAW):
        return None
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if target is None:
        return False
    if feature == BITE:  # "savored by you, Resonance Marked by you, or visibly carries qualifying radiance"
        return None if _claimed(engine, actor, target) or radiance_on(engine, target) else False
    if actor.resources.get(RADIANCE, 0) < 1:
        return False  # "all remaining Stolen Radiance, minimum 1"
    return None if _claimed(engine, actor, target) and radiance_on(engine, target) else False


# ---------------------------------------------------------------------------------------------------------- Crown of Borrowed Light
def _crown(owner: Any) -> Any:
    return next((c for c in owner.conditions.values() if c.condition_id == CROWN_STATE and c.source_actor_id == owner.entity_id), None)


def _in_crown(engine: Any, owner: Any, creature: Any) -> bool:
    from .. import zones

    crown = _crown(owner)
    zone = next((z for z in zones.typed_zones(engine) if crown is not None and z.owner_id == owner.entity_id
                 and z.source_definition_id == crown.source_definition_id), None)
    return zone is not None and engine._footprint_intersects(creature, zone.affected_cells)


def _facets(owner: Any) -> list[str]:
    crown = _crown(owner)
    return list((st.data_of(owner, crown).get("facets") or []) if crown is not None else [])


@effect("halo_crown")
def crown(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, owner = ctx.engine, ctx.actor
    facets = {"sanctuary": "Facet of Sanctuary (+1 to allies' Int/Wis/Cha saves in the field)",
              "hunger": "Facet of Hunger (a hostile creature gaining radiance in the field takes PB Psychic and is savored)",
              "false_grace": "Facet of False Grace (Reaction, 2 Resonance: an ally that would drop to 0 drops to 1)"}
    radiance = int(owner.resources.get(RADIANCE, 0) or 0)
    picked = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "CROWN_FACETS", owner.entity_id), owner, "choice:needle.halo_eater.facets",
                        list(facets), labels=facets, preferred=["sanctuary", "false_grace", "hunger"][:min(3, radiance)], minimum=0, maximum=min(3, radiance),
                        default="all", allow_decline=True, prompt=f"Crown of Borrowed Light: spend Stolen Radiance (you have {radiance}), one Facet each.",
                        name="Crown of Borrowed Light", feature_id=CROWN) if radiance else []
    picked = [key for key in picked if key in facets][:min(3, radiance)]
    if picked:
        engine._spend_resource(owner, RADIANCE, len(picked), CROWN)
    held = _crown(owner)
    if held is not None:
        st.remove(engine, owner, held, "REPLACED")
    engine._apply_condition(owner, CROWN_STATE, ctx.source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"facets": picked, "graced": [], "label": "Crown of Borrowed Light: " + (", ".join(k.replace("_", " ").title() for k in picked) or "no Facet")})


@hook("incoming_damage")
def crown_resistance(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    if amount <= 1 or str(damage_type).upper() not in ("RADIANT", "PSYCHIC") or _crown(target) is None:
        return None
    return amount - amount // 2  # "You have Resistance to Radiant and Psychic damage"


@hook("damage_dealt")
def crown_feeds(ctx: Any, target: Any, amount: int) -> None:
    engine, owner = ctx.engine, ctx.actor
    if (_crown(owner) is None or amount <= 0 or target is None or target.team_id == owner.team_id or not st.is_spirit_feature(ctx.action)
            or owner.turn_flags.get("crown_fed") or engine.state.current_actor_id != owner.entity_id or not _claimed(engine, owner, target)):
        return
    owner.turn_flags["crown_fed"] = True  # "Once on each of your turns"
    allies = [a for a in engine.state.actors.values() if a.active and a.team_id == owner.team_id and _in_crown(engine, owner, a)]
    ally = st.pick_creature(engine, ctx.intent, owner, allies, checkpoint="CROWN_TEMP_HP", choice_id="choice:needle.halo_eater.crown_ally",
                            prompt="Crown of Borrowed Light: which ally in the field gains Temporary Hit Points (Wisdom + PB)?", name="Crown of Borrowed Light",
                            feature_id=CROWN, preferred=min(allies, key=lambda a: (a.current_hp - a.maximum_hp, a.entity_id), default=None))
    numbers = st.numbers(engine, owner)
    if ally is not None:
        engine._grant_temp_hp(ally, int(numbers.get("key_mod") or 0) + int(numbers.get("pb") or 2), CROWN, owner.entity_id)
    if target.active and radiance_on(engine, target):
        _te().run_effects(st.context(engine, owner, engine.action_catalog.get(_crown(owner).source_definition_id) or ctx.action, [target], numbers, ctx.intent),
                          [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "impose one ordinary Spiritual Pressure effect on it"}])


@hook("save")
def sanctuary(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None or str(ability or "").upper()[:3] not in ("INT", "WIS", "CHA"):
        return None
    bonus = sum(1 for owner in ctx.engine.state.actors.values() if owner.active and owner.team_id == subject.team_id and owner is not subject
                and "sanctuary" in _facets(owner) and _in_crown(ctx.engine, owner, subject))
    return {"bonus": min(1, bonus), "modes": []} if bonus else None


def _hunger(engine: Any, creature: Any) -> None:
    for owner in engine.state.actors.values():
        if (not owner.active or owner.team_id == creature.team_id or "hunger" not in _facets(owner) or not _in_crown(engine, owner, creature)
                or creature.turn_flags.get(f"hunger_round_{owner.entity_id}") == engine.state.round_number):
            continue
        creature.turn_flags[f"hunger_round_{owner.entity_id}"] = engine.state.round_number  # "The first time each round"
        numbers = st.numbers(engine, owner)
        _te().run_effects(st.context(engine, owner, st.feature_action(engine, owner, CROWN), [creature], numbers),
                          [{"type": "damage", "applies_to": "target", "flat": int(numbers.get("pb") or 2), "damage_types": ["psychic"],
                            "evidence": "it takes Psychic damage equal to your Proficiency Bonus"}])
        _savor(engine, owner, creature)


@hook("would_drop")
def false_grace(engine: Any, target: Any, pending: int, source_actor_id: str | None) -> int | None:
    for owner in engine.state.actors.values():
        crown_state = _crown(owner)
        if (crown_state is None or "false_grace" not in _facets(owner) or owner.team_id != target.team_id or owner is target or not st.can_react(owner)
                or owner.resources.get(RESONANCE, 0) < 2 or target.entity_id in (st.data_of(owner, crown_state).get("graced") or [])
                or not _in_crown(engine, owner, target)):
            continue
        from . import needle

        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "FALSE_GRACE", target.entity_id), owner, "choice:needle.halo_eater.false_grace",
                            ["grace"], labels={"grace": f"False Grace (Reaction, 2 Resonance): {target.display_name} drops to 1 Hit Point instead; the Facet is lost"},
                            prompt=f"{target.display_name} would drop to 0 Hit Points.", preferred=["grace"], allow_decline=True, name="Crown of Borrowed Light",
                            feature_id=CROWN, target_id=target.entity_id)
        if not chosen:
            continue
        with activation(engine, owner, CROWN):
            engine._spend_resource(owner, RESONANCE, 2, CROWN)
            owner.reaction_available = False
            st.set_data(owner, crown_state, facets=[f for f in _facets(owner) if f != "false_grace"],
                        graced=[*(st.data_of(owner, crown_state).get("graced") or []), target.entity_id])
            engine._append_event("REACTION_RESOLVED", CROWN, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                                 payload={"checkpoint": "DROP_TO_ZERO", "reaction_name": "False Grace"})
            return max(0, target.current_hp + target.temporary_hp - 1)
    return None
