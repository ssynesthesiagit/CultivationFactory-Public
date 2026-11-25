"""Rangefinding Breath (Sniper) resolves the target's range and cover, and marks the next shot as an Aimed Line.

Source (owner text: authority/typed_mechanics/rules_text.json TAL_SNIPER_RANGEFINDING_BREATH):
  "As a Bonus Action, choose one creature or object you can perceive within your weapon's long range.
   Until the end of your next turn, you know whether the target is within normal range, long range, or beyond the
   weapon's range. If the target remains within range and does not gain Total Cover, your next ranged attack against
   it gains an Aimed Line.
   If you also hold Martial Focus, you learn whether the target benefits from Half Cover, Three-Quarters Cover, or
   Total Cover against your current position."

How it runs
  * A Bonus Action button (feature block ``sniper_rangefinding``, combat/rules/feature_blocks.d) asks which of the
    shooter's ranged weapons to measure with -- only when more than one is in hand -- and then which creature that
    weapon reaches and the shooter can perceive. Every range figure is that weapon's own compiled
    ``range_ft``/``long_range_ft``, in feet, because the engine already measures distance in feet
    (``action_geometry.distance``); there is no invented fallback range. Objects are not targets at the table, so
    the choice is creatures, and the Aimed Line is not yet consumed by the abilities that read it: both clauses stay
    printed riders (reviewed_final.d/auto100_rangefinding.json).
  * The answer is read out in plain words -- which range band the target sits in and, while Martial Focus is held,
    how much cover it has -- so no GM judges either. The table re-measures whenever the answer can have changed (the
    marked target moves, or the shooter's next turn begins) and says so when the band or the cover has moved.
  * The printed rule makes two promises under two different conditions, so the table keeps two records on the shooter.
    Both last until the end of the shooter's *next* turn (``END_OF_SOURCE_TURN_AT:<turns_started + 1>``: the
    shooter's own turn counter plus one, read at the moment of the Breath -- a fixed ``:1`` ended it on the casting
    turn), and both name the target and the weapon they were measured with:
      - ``condition:typed.rangefinding_breath`` -- the knowledge, "Until the end of your next turn, you know whether
        the target is within normal range, long range, or beyond the weapon's range". That sentence is unconditional,
        and "beyond the weapon's range" is one of the three bands it reports, so this record is only ever ended by its
        own expiry (or the target leaving the fight). It deliberately outlives both failures of the shot below, and the
        qualifying shot, because the printed promise does.
      - ``condition:typed.aimed_line`` -- the conditional shot, "If the target remains within range and does not gain
        Total Cover, your next ranged attack against it gains an Aimed Line". It is dropped, naming the printed clause
        that failed, as soon as the target leaves the weapon's range or gains Total Cover, and by the shooter's next
        *ranged* attack against the named creature. An Aimed Line is printed by ten Sniper abilities (Phasic Shot,
        Killing Aperture, Perfect Shot, ...) that read it as "through an Aimed Line"; this module owns granting it, and
        those modules own what they do with it.
  * Perception is a condition of CHOOSING the target (the printed "one creature you can perceive"), so it filters the
    offered targets; it is not one of the printed ongoing conditions, so nothing after the setup cancels either record.
    A punch, or a shot at another creature, never spends the Aimed Line, and the shot re-checks range and Total Cover
    against the weapon actually used.

Why the typed row changed: the printed line grants "an Aimed Line", but the model row typed it as Advantage on the next
ranged attack. Advantage cancels *every* source of Disadvantage on that roll, which the printed rule never says, so
reviewed_final.d/auto100_rangefinding.json now types the printed effect instead.
Default-inert: without the feature row the shooter has no button, no condition and no rider.

Public queries this module owns, for the Aimed Line consumers a follow-up needs: ``ranged_weapons`` (the shooter's ranged weapons with their own ranges),
``ranged_attack`` (was that recorded attack delivered at range), ``attack_range`` (the weapon an attack used, with its
own ranges) and ``band_of`` (which band a distance falls in). They read the existing shared helpers --
``weapon_hits.available_weapons`` for possession, ``attack_provenance.ranged_attacks`` for delivery -- rather than
re-deciding either, and no other plug-in uses them yet, so they stay here instead of a shared helper module.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

BREATH = "TAL_SNIPER_RANGEFINDING_BREATH"
BLOCK = "sniper_rangefinding"
# The promised knowledge ("until the end of your next turn, you know ..."), unconditional and kept on its own.
MEASURED = "condition:typed.rangefinding_breath"
# The conditional shot ("if the target remains within range and does not gain Total Cover ..."), which the
# qualifying ranged attack spends.
AIMED = "condition:typed.aimed_line"
FOCUS = "resource:core.martial_focus"
# The engine adds these to a target's Armor Class against a ranged attack; the same numbers
# sniper_angles.current_cover reads, named for a player (arch guard: no cross-plug-in _names).
COVER_NAMES = {0: "no", 2: "Half Cover", 5: "Three-Quarters Cover"}
# Said whenever only the shot is lost, so the player is told the knowledge they were promised survives.
KEPT = ("You keep knowing how far away it is, and how much cover it has against you while you hold Martial "
        "Focus, until the end of your next turn.")


# -------------------------------------------------------------------------------------------------- the weapon's own range bands
def _typed_row(action: Any) -> dict[str, Any]:
    return (getattr(action, "parameters", None) or {}).get("typed") or {}


def _weapon_row(action: Any) -> dict[str, Any] | None:
    """One ranged weapon's name and its own normal/long range in feet, read from its compiled attack.

    Grip and action economy are left to the shot itself: knowing a weapon's range does not need the Attack action.
    """
    typed = _typed_row(action)
    long_ft = int(typed.get("long_range_ft") or typed.get("range_ft") or 0)
    if not typed.get("weapon") or not typed.get("range_ft") or long_ft <= 5:
        return None
    return {"name": action.display_name, "source_id": action.source_definition_id,
            "normal_ft": int(typed.get("range_ft") or 0), "long_ft": long_ft,
            "required": (getattr(action, "parameters", None) or {}).get("requires_condition")}


def _held(engine: Any, actor: Any, row: dict[str, Any]) -> bool:
    """An attack the shooter's own standing state forbids is not a weapon in hand (an improvised weapon left on the ground)."""
    return not row.get("required") or engine._has_condition(actor, str(row["required"]))


def band_of(distance_ft: int, normal_ft: int, long_ft: int) -> str:
    """Which printed band a distance falls in, from one weapon's own normal and long range figures."""
    if distance_ft > long_ft:
        return "beyond"
    return "long" if distance_ft > normal_ft else "normal"


def ranged_weapons(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    """Public: every ranged weapon the shooter holds, keyed by catalogue action id, longest reach first."""
    from .weapon_hits import available_weapons

    rows = {source: row for source, action in available_weapons(engine, actor).items()
            if (row := _weapon_row(action)) is not None and _held(engine, actor, row)}
    return dict(sorted(rows.items(), key=lambda item: (-item[1]["long_ft"], item[1]["name"])))


def ranged_attack(engine: Any, actor: Any, source_id: str) -> bool:
    """Public: whether this recorded attack was delivered at range, using the engine's own delivery query."""
    from ..attack_provenance import ranged_attacks

    return any(row.get("source_id") == source_id for row in ranged_attacks(engine, actor))


def attack_range(engine: Any, source_id: str) -> dict[str, Any]:
    """The weapon an already-recorded attack used, with its own normal/long range (variants keep the base's figures)."""
    row = _weapon_row(getattr(engine, "action_catalog", {}).get(source_id))
    return row if row is not None else {"name": "", "source_id": source_id, "normal_ft": 0, "long_ft": 0}


def _perceives(engine: Any, shooter: Any, target: Any) -> bool:
    from ..stealth import sees

    return sees(engine, shooter, target)


def _total_cover(engine: Any, shooter: Any, target: Any) -> bool:
    """Whether a wall or solid barrier leaves the target with Total Cover: no clear line reaches it at all."""
    from ..action_geometry import cells, volume

    elevated = shooter.position.z or target.position.z or engine.grid.finite_heights
    origin = volume(engine, shooter) if elevated else cells(engine, shooter)
    return bool(engine.cover_from(origin, shooter.entity_id, target, purpose="attack")["blocked"])


def _lost(measured: dict[str, Any]) -> str:
    """Why the printed Aimed Line no longer holds, in words a player reads; "" while it still does.

    Only the two conditions the printed shot names: staying within the measured weapon's range, and never gaining
    Total Cover. Perception gates choosing the target, not keeping the setup, so it is not one of these.
    """
    if measured["total_cover"]:
        return "it has gained Total Cover from a wall or solid barrier"
    if measured["band"] == "beyond":
        return "it is beyond your weapon's range"
    return ""


def _measure(engine: Any, shooter: Any, target: Any, normal_ft: int, long_ft: int) -> dict[str, Any]:
    """The printed answer right now: the range band (including beyond the weapon), and the cover against the shooter."""
    from .sniper_angles import current_cover

    return {"band": band_of(int(engine._effect_distance(shooter, target)), normal_ft, long_ft),
            "cover": int(current_cover(engine, shooter, target)),
            "focused": bool(shooter.resources.get(FOCUS, 0)),
            "total_cover": _total_cover(engine, shooter, target)}


def _tracked(engine: Any, entity_id: Any) -> Any | None:
    """The creature a record names, while it is still in the fight."""
    target = engine.state.actors.get(str(entity_id or ""))
    return target if target is not None and target.active else None


def _sentence(shooter: Any, target: Any, measured: dict[str, Any]) -> str:
    band = {"normal": "within normal range", "long": "at long range"}.get(measured["band"], "beyond your weapon's range")
    said = f"{target.display_name} is {band}"
    if measured["focused"]:
        cover = "Total Cover" if measured["total_cover"] else f"{COVER_NAMES.get(measured['cover'], 'no')} cover"
        said += f", with {cover} against you"
    return said + "."


@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": BLOCK}] if block == BLOCK else None


@hook("compile_actions")
def breath_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if not any(r.get("block") == BLOCK for r in info.get("passives", [])):
        return None
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.rangefinding_breath",
        display_name="Rangefinding Breath", owner_id=info["actor_id"],
        economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF", costs=(),
        parameters={"description": (
            "Bonus Action, no cultivation points. Choose one creature you can perceive within the long range of one of "
            "your ranged weapons. Until the end of your next turn you keep knowing whether it is within that weapon's "
            "normal range, at long range or beyond its range, and (while you hold Martial Focus) how much cover it has. "
            "While it stays within range and never gains Total Cover, your next ranged attack against it counts as an "
            "Aimed Line: a shot the Sniper talents that read an Aimed Line treat as aimed at that creature. If it "
            "leaves that range or gains Total Cover, the Aimed Line is lost, but you keep knowing its distance and "
            "cover until the end of your next turn."),
            "expected_damage": 1,
            "typed": {"source": BREATH, "effects": [{"type": "rangefinding_breath"}],
                      "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}})]


def _instances(actor: Any, kind: str = AIMED) -> list[tuple[str, Any]]:
    return [(iid, c) for iid, c in actor.conditions.items() if c.condition_id == kind]


def _either(actor: Any) -> list[tuple[str, Any]]:
    """Every record this ability left on the shooter, whichever of the two promises is still running."""
    return _instances(actor, MEASURED) + _instances(actor, AIMED)


@hook("button_description")
def breath_description(row: dict[str, Any]) -> str | None:
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    if any(eff.get("type") == "rangefinding_breath" for eff in effects):
        return ("Bonus Action: measure one creature you can perceive with one of your ranged weapons. Until the end of "
                "your next turn the table tells you which range band it is in -- within normal range, at long range or "
                "beyond your weapon -- and, while you hold Martial Focus, how much cover it has against you, and says so "
                "again whenever that changes. While it stays within that weapon's range and never gains Total Cover, "
                "your next ranged attack against it counts as an Aimed Line: a shot the Sniper talents that read an "
                "Aimed Line treat as aimed at that creature. If it leaves that range or gains Total Cover the Aimed Line "
                "is lost, and the next ranged attack against it spends it; either way you keep knowing its distance and "
                "cover until the end of your next turn. No cultivation points.")
    return None


@effect("rangefinding_breath")
def rangefinding_breath(ctx: Any, eff: dict[str, Any]) -> None:
    from .ability_source import has_row
    from .placed import note
    from .rider_choices import pick

    if not has_row(ctx.engine, ctx.actor.entity_id, BLOCK):
        return
    engine, shooter = ctx.engine, ctx.actor
    held = ranged_weapons(engine, shooter)
    if not held:
        note(engine, BREATH, shooter,
             "Rangefinding Breath measures a creature with a ranged weapon in your hands, and you are not holding one. "
             "Nothing is set up.", [])
        return
    weapon_id, weapon = next(iter(held.items()))
    cost = {"cost": "Bonus Action, no cultivation points; lasts until the end of your next turn"}
    if len(held) > 1:
        chosen = pick(engine, shooter, "rangefinding_weapon", "Rangefinding Breath", list(held),
                      labels={source: f"{row['name']}: normal range {row['normal_ft']} ft, long range {row['long_ft']} ft"
                              for source, row in held.items()},
                      subject=shooter, optional=False, preferred=[weapon_id],
                      trigger="Choose the ranged weapon you measure with", prompt_context=cost)
        if not chosen:
            return
        weapon_id, weapon = chosen[0], held[chosen[0]]
    normal_ft, long_ft = int(weapon["normal_ft"]), int(weapon["long_ft"])
    seen = [a for a in engine.state.actors.values()
            if a.active and a.entity_id != shooter.entity_id
            and int(engine._effect_distance(shooter, a)) <= long_ft and _perceives(engine, shooter, a)]
    if not seen:
        note(engine, BREATH, shooter,
             f"No creature you can perceive is within {weapon['name']}'s long range of {long_ft} feet. Nothing is set up.",
             [])
        return
    chosen = pick(engine, shooter, "rangefinding_breath", "Rangefinding Breath",
                  [a.entity_id for a in seen], labels={a.entity_id: a.display_name for a in seen},
                  subject=shooter, optional=False,
                  trigger=f"Choose the creature you measure with {weapon['name']} and set up an Aimed Line on",
                  prompt_context=cost)
    if not chosen:
        return
    target = engine.state.actors.get(chosen[0])
    if target is None:
        return
    measured = _measure(engine, shooter, target, normal_ft, long_ft)
    from .condition_ownership import remove_instance

    for kind in (MEASURED, AIMED):  # a second Breath replaces what the first measured
        for instance_id, _condition in _instances(shooter, kind):
            remove_instance(engine, shooter, instance_id, BREATH)
    # "Until the end of your next turn": the shooter's own turn counter, read now, plus one.
    expires_on = f"END_OF_SOURCE_TURN_AT:{int(shooter.turns_started) + 1}"
    shared = {"target": target.entity_id, "weapon": weapon_id, "weapon_name": weapon["name"],
              "normal_ft": normal_ft, "long_ft": long_ft}
    engine._apply_condition(shooter, MEASURED, ctx.source, shooter.entity_id, expires_on=expires_on,
                            data={**shared, "band": measured["band"], "cover": measured["cover"],
                                  "total_cover": int(measured["total_cover"]),
                                  "label": f"Rangefinding Breath: range and cover of {target.display_name}",
                                  "reading": (
                                      f"Until the end of your next turn you know whether {target.display_name} is within "
                                      f"{weapon['name']}'s normal range, at its long range or beyond its range, and, "
                                      "while you hold Martial Focus, how much cover it has against you. This knowledge "
                                      "does not end because the creature moves out of range, gains cover, or you spend "
                                      "the Aimed Line on your next ranged attack against it.")})
    if lost := _lost(measured):
        note(engine, BREATH, shooter,
             f"Rangefinding Breath: {_sentence(shooter, target, measured)} No Aimed Line is set up because {lost}. {KEPT}",
             [target])
        return
    engine._apply_condition(shooter, AIMED, ctx.source, shooter.entity_id, expires_on=expires_on,
                            data={**shared, "label": f"Aimed Line on {target.display_name}"})
    note(engine, BREATH, shooter,
         f"Rangefinding Breath: {_sentence(shooter, target, measured)} Your next ranged attack against it counts as an "
         "Aimed Line, until the end of your next turn.", [target])


# -------------------------------------------------------------------------------------------------- keeping the printed promise true
def _recheck(engine: Any, shooter: Any) -> None:
    """Re-measure what the Breath set up: the promised knowledge is refreshed, the Aimed Line is dropped when its
    printed conditions fail. The two records are independent -- neither loop touches the other's record."""
    from .condition_ownership import remove_instance
    from .placed import note

    _retain_legacy_measurement(engine, shooter)
    for instance_id, condition in _instances(shooter, MEASURED):
        target = _tracked(engine, condition.data.get("target"))
        if target is None:
            remove_instance(engine, shooter, instance_id, BREATH)
            continue
        measured = _measure(engine, shooter, target, int(condition.data.get("normal_ft") or 0),
                            int(condition.data.get("long_ft") or 0))
        if (measured["band"], measured["cover"], int(measured["total_cover"])) == (
                condition.data.get("band"), condition.data.get("cover"), condition.data.get("total_cover", 0)):
            continue  # the printed answer has not moved, and the window is not over
        condition.data = {**condition.data, "band": measured["band"], "cover": measured["cover"],
                          "total_cover": int(measured["total_cover"])}
        from .retained_updates import record_instance_update

        record_instance_update(engine, shooter, "condition", instance_id, condition)
        note(engine, BREATH, shooter, f"Rangefinding Breath: now {_sentence(shooter, target, measured)}", [target])

    for instance_id, condition in _instances(shooter, AIMED):
        target = _tracked(engine, condition.data.get("target"))
        if target is None:
            remove_instance(engine, shooter, instance_id, BREATH)
            continue
        measured = _measure(engine, shooter, target, int(condition.data.get("normal_ft") or 0),
                            int(condition.data.get("long_ft") or 0))
        lost = _lost(measured)
        if not lost:
            continue
        remove_instance(engine, shooter, instance_id, BREATH)
        note(engine, BREATH, shooter,
             f"Rangefinding Breath: the Aimed Line on {target.display_name} is lost, because {lost}. {KEPT}", [target])


def _retain_legacy_measurement(engine: Any, shooter: Any) -> None:
    """Old saves stored both promises on Aimed Line. Split only those records, retaining their original expiry.

    New Aimed Lines omit band/cover; this is default-inert for them and every unrelated condition.
    """
    for _iid, condition in _instances(shooter):
        data = condition.data
        if "band" not in data or "cover" not in data:
            continue
        if any(c.data.get("target") == data.get("target") for _key, c in _instances(shooter, MEASURED)):
            continue
        target = _tracked(engine, data.get("target"))
        if target is not None:
            engine._apply_condition(shooter, MEASURED, condition.source_definition_id, condition.source_actor_id,
                                    expires_on=condition.expires_on,
                                    data={**data, "label": f"Rangefinding Breath: range and cover of {target.display_name}"})


@hook("state_event")
def keep_the_promise_true(engine: Any, event: Any) -> None:
    """The marked target can move, and the shooter's next turn is when the printed knowledge comes due again.

    Either record counts: the knowledge outlives the Aimed Line, so it keeps being refreshed on its own.
    """
    if event.event_type == "TURN_STARTED":
        shooter = engine.state.actors.get(event.actor_id)
        if shooter is not None and _either(shooter) and not (event.payload or {}).get("initial"):
            _recheck(engine, shooter)
    elif event.event_type == "MOVEMENT_COMMITTED":
        for shooter in list(engine.state.actors.values()):
            held = _either(shooter)
            if held and (any(str(c.data.get("target")) == event.actor_id for _iid, c in held)
                         or event.actor_id == shooter.entity_id):
                _recheck(engine, shooter)


@hook("state_event")
def aimed_spent_on_the_marked_shot(engine: Any, event: Any) -> None:
    """The printed line is "your next ranged attack against it": only that shot spends the Aimed Line."""
    if event.event_type != "ATTACK_ROLLED" or not event.target_ids:
        return
    shooter = engine.state.actors.get(event.actor_id)
    if shooter is None:
        return
    from .condition_ownership import remove_instance
    from .placed import note

    _retain_legacy_measurement(engine, shooter)
    for instance_id, condition in _instances(shooter):
        target = engine.state.actors.get(str(condition.data.get("target") or ""))
        if target is None or target.entity_id not in event.target_ids:
            continue
        if not ranged_attack(engine, shooter, event.source_definition_id):
            continue  # a punch or a shot elsewhere keeps the Aimed Line for the next ranged attack
        weapon = attack_range(engine, event.source_definition_id)
        measured = _measure(engine, shooter, target, int(weapon["normal_ft"]), int(weapon["long_ft"]))
        lost = _lost(measured)
        remove_instance(engine, shooter, instance_id, BREATH)
        note(engine, BREATH, shooter,
             ((f"Rangefinding Breath: your shot at {target.display_name} counts as an Aimed Line, and the setup is spent. "
               f"{KEPT}") if not lost else
              (f"Rangefinding Breath: the Aimed Line on {target.display_name} is spent on this shot but gains nothing, "
               f"because {lost}. {KEPT}")), [target])
