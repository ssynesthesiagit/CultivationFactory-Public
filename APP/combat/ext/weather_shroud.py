"""Cloud Shroud: a private weather around one creature, its saving throws, and the Shroud talents.

Printed text (owner's Sphere Compendium, "Sphere of Weather"; ``APP/authority/typed_mechanics/rules_text.json``):

  Cloud Shroud        Action, 60 feet, one creature, Concentration up to 1 minute, 1 Cultivation Point. "Choose one
                      Weather Sign talent you know and apply its Shroud effect." "A creature can be under only one of
                      your Cloud Shrouds at a time." "a creature makes the listed saving throw when the Shroud is
                      placed and again at the end of each of its turns. A Shroud's damage or condition applies on a
                      failed save. A successful save prevents that round's damage or condition but does not end the
                      Shroud unless the Shroud says otherwise."
  Three-Success Escape  "If a Shroud no longer requires your Concentration because of a talent or feature, it ends
                      once the target has succeeded on three saving throws against it."
  Persistent Shroud   "spend 2 additional CP to make it last for its remaining duration without Concentration. A
                      persistent Shroud ends after the target succeeds on three saving throws against it. You may
                      have only one Persistent Shroud active at a time at Mortal Realm. If you create another, the
                      previous one ends."
  Pressure-Cracking Shroud  "When a creature fails a saving throw against your Cloud Shroud ..., you may spend 2 CP
                      to crack its resistance to that weather": it "loses Resistance to the Shroud's damage type"
                      until the end of your next turn. The spending is the owner's printed choice, so it is asked of
                      the owner rather than taken silently; the printed "while inside gathered weather of the same
                      sign" turns on a gathered-weather state this repository does not have, so it is put to the table
                      as a rider with the question.
  Severe Shroud       printed ("the first saving throw it makes against that Shroud has Disadvantage", plus a rider
                      per sign, while the target stands inside gathered weather of the same sign) and left to the table
                      with Pressure-Cracking's: there is no gathered-weather state to read, so nothing pretends to
                      decide it.
  Lightning Chooses the Rod  move your Thunder Shroud to another creature within 30 feet of the original target
                      without using an action, once per round; the new target "immediately makes the Shroud's
                      saving throw".

What this module does: one condition per target (``condition:typed.weather_shroud``) carries the printed sign, the
saving throw to repeat and the typed rows a failure or a success runs (the printed sign Shroud rows live in
``combat/ext/weather_signs.py``, written in the engine's own typed vocabulary, so a Shroud's outcome goes through
the same save, Resistance, condition-reaction and damage paths as every other typed ability). The throw itself goes
through the engine's shared save orchestration (``typed_executor.typed_save_modifiers`` and ``settle_typed_save``,
the same pair block_save and the defending contests use), so a Defensive Weather Mantle, a Dry Sign advantage or any
other plug-in's save bonus reaches a Shroud throw and the throw notifies the same subscribers as every other save.
The throw repeats at the end of each of the shrouded creature's turns, because the engine's own repeat save ends the
condition on the first success and the printed Shroud does not. The Persistent Shroud's success counter is
integers and strings, so a table commit and reload keeps them.

Ownership: Cloud Shroud is a base ability granted automatically; the Shroud talents are feature-block rows
(``combat/rules/feature_blocks.d/auto13_weather.json``). Every hook returns early without them, so a creature that
owns no Shroud talent and casts no Shroud is untouched.

Hooks: compile_action, compile_actions, compile_block, turn_start, turn_end, attack_mode, save,
condition_attempt, candidate_allowed, button_description.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook
from . import weather_signs
from .choice_costs import payable
from .needle import CHOICE, ask, checkpoint_id
from .retained_updates import record_instance_update

BASE = "WEATHER_BASE_CLOUD_SHROUD"
SHROUD = "condition:typed.weather_shroud"
PERSISTENT = "TAL_WEATHER_PERSISTENT_SHROUD"
CRACKING = "TAL_WEATHER_PRESSURE_CRACKING_SHROUD"
ROD = "TAL_WEATHER_LIGHTNING_CHOOSES_THE_ROD"
BLOCK = "weather"
_CP = "resource:core.qi"
#: The damage types a printed Shroud deals, which is what Pressure-Cracking suppresses.
_SHROUD_DAMAGE_TYPES = ("fire", "thunder", "cold", "necrotic", "poison", "lightning")


def rows_of(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    """The owned feature-block rows of one Weather Shroud talent (combat/ext/weather_signs.py owns the marker)."""
    return weather_signs.rows_of(engine, actor, kind)


def _owned_kind(engine: Any, actor: Any, kind: str) -> bool:
    return weather_signs.owns(engine, actor, kind)


def shrouds(actor: Any, owner: str | None = None) -> list[Any]:
    """Every Cloud Shroud on a creature, or only that owner's."""
    return [c for c in actor.conditions.values()
            if c.condition_id == SHROUD and (owner is None or c.source_actor_id == owner)]


def _markers(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The Shroud's own effect rows, failure and success together (the rows that carry a condition)."""
    data = data or {}
    return [*(data.get("fail") or []), *(data.get("success") or [])]


#: The printed Shroud marker conditions, read from the live creature rather than from the Shroud's stored rows, so a
#: marker the engine has already removed cannot still be applied, and one the printed words limit to "the next"
#: save or attack is used up by the save or attack it spoiled.
def markers(subject: Any, name: str) -> list[Any]:
    """The live ``condition:typed.<name>`` markers on a creature, most recent last."""
    return [c for c in subject.conditions.values() if c.condition_id == f"condition:typed.{name}"]


def _spend_marker(engine: Any, subject: Any, condition: Any, reason: str = "CONSUMED") -> None:
    """End one "the next ..." marker, the way save_against consumes its own one-shot rows."""
    if subject.conditions.pop(condition.instance_id, None) is not None:
        engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id,
                             target_ids=(subject.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": condition.instance_id,
                                      "reason": reason})


def sign_of(shroud: Any) -> str:
    """The printed sign id a shroud carries ("" for an old saved fight or a GM-run sign)."""
    return str((shroud.data or {}).get("sign") or "")


def _log(engine: Any, source: str, actor_id: str, target_ids: tuple[str, ...], text: str) -> None:
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=actor_id, target_ids=target_ids, payload={"log": text})


def _remove(engine: Any, holder: Any, shroud: Any, reason: str) -> None:
    if holder.conditions.pop(shroud.instance_id, None) is not None:
        engine._append_event("CONDITION_REMOVED", shroud.source_definition_id, actor_id=shroud.source_actor_id,
                             target_ids=(holder.entity_id,),
                             payload={"condition_id": SHROUD, "instance_id": shroud.instance_id, "reason": reason})


@hook("compile_block")
def weather_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The one compiled ownership marker for the Weather sphere (combat/rules/feature_blocks.d/auto13_weather.json).

    Only this module answers the "weather" block, so one talent produces one row; ``weather_signs.rows_of`` is the
    shared reader both Weather modules use.
    """
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "field_policy": 1}] if block == BLOCK else None


# ------------------------------------------------------------------------------- the cast
@hook("compile_action")
def shroud_action(action: Any, info: dict[str, Any]) -> Any:
    """Give the printed Cloud Shroud its saving throw: the base ability carries no typed effects at all."""
    typed = (action.parameters or {}).get("typed") or {}
    if BASE not in info["owned_ids"] or typed.get("source") != BASE or typed.get("effects"):
        return None
    return action.model_copy(update={"parameters": {**action.parameters, "typed": {
        **typed, "effects": [{"type": "weather_cloud_shroud", "applies_to": "target"}],
        "duration": {**(typed.get("duration") or {"kind": "minutes", "amount": 1}), "concentration": True}}}})


@hook("compile_actions")
def shroud_variants(info: dict[str, Any]) -> list[Any] | None:
    """The printed Shroud casts: any creature rather than only allies, and the two talent augmentations.

    The base ability carries no typed effects at all, so this module supplies them (the compiler runs
    ``compile_actions`` before ``compile_action``, so the variants cannot read them off the base action).
    Persistent Shroud and Pressure-Cracking Shroud are separate buttons, so the printed extra Cultivation Points
    are quoted and paid before the saving throw is rolled.
    """
    if BASE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    base = next((a for a in info["actions"] if ((a.parameters or {}).get("typed") or {}).get("source") == BASE), None)
    if base is None:
        return None

    def with_effects(cast: Any, **flags: Any) -> Any:
        typed = (cast.parameters or {}).get("typed") or {}
        row = {"type": "weather_cloud_shroud", "applies_to": "target", **flags}
        duration = {**(typed.get("duration") or {"kind": "minutes", "amount": 1}),
                    "concentration": not flags.get("persistent")}
        return cast.model_copy(update={"parameters": {**cast.parameters, "typed": {**typed, "effects": [row], "duration": duration}}})

    additions: list[Any] = []
    casts: list[Any] = [base]
    if base.target_kind == "ALLY_OR_SELF":
        # "Target: One creature or unattended object": the same Shroud aimed at anyone in range.
        wide = base.model_copy(update={
            "source_definition_id": base.source_definition_id + "#any_creature",
            "display_name": base.display_name + " (any creature)", "target_kind": "HOSTILE_ENTITY"})
        additions.append(wide)
        casts.append(wide)
    if PERSISTENT in info["owned_ids"]:
        for cast in list(casts):
            persistent = with_effects(cast, persistent=True)
            costs = {pool: amount + 2 for pool, amount in (cast.costs or ())}
            additions.append(persistent.model_copy(update={
                "source_definition_id": cast.source_definition_id + ".persistent",
                "display_name": cast.display_name + " + Persistent Shroud", "costs": tuple(costs.items())}))
            casts.append(additions[-1])
    if CRACKING in info["owned_ids"]:
        for cast in list(casts):
            additions.append(with_effects(cast, cracking=True).model_copy(update={
                "source_definition_id": cast.source_definition_id + ".cracking",
                "display_name": cast.display_name + " + Pressure-Cracking Shroud"}))
    if ROD in info["owned_ids"]:
        # Lightning Chooses the Rod: a no-cost button the table only offers while a Thunder Shroud can move.
        additions.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.weather.thunder_shroud_move",
            display_name="Move Thunder Shroud", owner_id=info["actor_id"], economy=EconomyKind.NONE,
            resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
            parameters={"typed": {"source": BASE + "#move", "sphere": weather_signs.SPHERE, "numbers": info["numbers"],
                                  "effects": [{"type": "weather_thunder_shroud_move", "moving": True}],
                                  "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0}))
    return additions or None


@hook("candidate_allowed")
def rod_requires_one_thunder_shroud(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Lightning Chooses the Rod is only offered with exactly one movable Thunder Shroud this round."""
    effects = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or []
    if not any(e.get("type") == "weather_thunder_shroud_move" for row in effects for e in row.get("effects", [row])):
        return None
    if actor.turn_flags.get("weather_rod_round") == engine.state.round_number:
        return False
    found = [(creature, c) for creature in engine.state.actors.values()
             for c in shrouds(creature, actor.entity_id) if sign_of(c) == "thunder" and creature.active]
    if len(found) != 1 or not candidate.target_ids:
        return False
    return engine._distance_actor_to_actor(found[0][0], engine.state.actors[candidate.target_ids[0]]) <= 30


def sign_menu(ctx: Any, target: Any, name: str) -> str | None:
    """The printed "Choose one Weather Sign talent you know", asked once per Shroud cast."""
    options = weather_signs.names()
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "SHROUD_SIGN", target.entity_id), ctx.actor,
                 CHOICE + "weather_shroud_sign", options,
                 labels={option: f"{weather_signs.sign(option).get('name')}: {weather_signs.PLAIN.get(option, '')}"
                         for option in options},
                 target_id=target.entity_id, name=name, feature_id=BASE,
                 prompt=(f"{name}: choose the Weather Sign talent you wrap {target.display_name} in. Your character must "
                         f"have taken that Weather Sign talent. The Shroud makes that sign's saving throw when placed and at "
                         f"the end of each of its turns."))
    return str(picked[0]) if picked else None


@effect("weather_cloud_shroud")
def place_shroud(ctx: Any, spec: dict[str, Any]) -> None:
    """Place one creature's Cloud Shroud with the printed sign, and roll its first saving throw."""
    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    sign_id = str(spec.get("sign") or "") or sign_menu(ctx, target, ctx.action.display_name)
    row = weather_signs.sign(sign_id)
    if row is None:
        return
    numbers = ctx.numbers or {}
    cl = int(numbers.get("cl") or 1)
    printed = weather_signs.shroud_rows(sign_id, cl)
    if not printed:
        return
    spec = {**spec, "sign": sign_id}
    persistent = bool(spec.get("persistent"))
    replaced: list[Any] = []
    if persistent and cl <= 4:
        # "You may have only one Persistent Shroud active at a time at Mortal Realm. If you create another, the
        # previous one ends": the new Shroud replaces the old one, which is a limit on what is active, not a
        # one-use allowance, so nothing is spent and nothing is refused.
        for holder in engine.state.actors.values():
            for other in shrouds(holder, owner.entity_id):
                if (other.data or {}).get("persistent") and other is not None:
                    replaced.append((holder, other))
                    _remove(engine, holder, other, "REPLACED")
    for shroud in shrouds(target, owner.entity_id):
        _remove(engine, target, shroud, "REPLACED")
    data = {"sign": sign_id, "dc": int(numbers.get("save_dc") or 10), "successes": 0,
            "save": printed["save"], "fail": printed["fail"], "success": printed["success"],
            "persistent": 1 if persistent else 0,
            "speed_halved_below_ft": int(printed.get("speed_halved_below_ft") or 0),
            # The printed "Concentration, up to 1 minute"; a Persistent Shroud lasts that same remaining duration
            # without needing Concentration.
            "expiry_round": engine.state.round_number + weather_signs.MINUTE_ROUNDS,
            "expiry_slot": engine.state.current_slot_index,
            "label": f"Cloud Shroud ({row.get('name')}): a {printed['save']} saving throw when it is placed and at the end "
                     f"of each of its turns; a failure runs this sign's Shroud effect. It lasts up to 1 minute."
                     + (" It needs no Concentration, and it also ends after three successful saves." if persistent else "")}
    if not persistent:
        # Which Concentration this Shroud is holding, so the minute's own clock (expire_shrouds) releases exactly that one
        # and leaves any other state the owner was sustaining alone. A Persistent Shroud holds none.
        data["concentration_started_sequence"] = (owner.concentration.started_sequence
                                                  if owner.concentration is not None else None)
    engine._apply_condition(target, SHROUD, ctx.source, owner.entity_id,
                            expires_on="UNTIL_REMOVED" if persistent else "CONCENTRATION_END", data=data)
    shroud = next((c for c in shrouds(target, owner.entity_id)), None)
    if shroud is None:
        return
    for holder, other in replaced:
        _log(engine, ctx.source, owner.entity_id, (holder.entity_id,),
             f"Cloud Shroud: {holder.display_name}'s earlier Persistent Shroud ends, because {owner.display_name} may "
             "keep only one active at a time at Mortal Realm.")
    _log(engine, ctx.source, owner.entity_id, (target.entity_id,),
         f"{ctx.action.display_name}: {target.display_name} is wrapped in a {row.get('name')} Shroud. It makes a "
         f"{printed['save']} saving throw now and at the end of each of its turns."
         + (" It needs no Concentration for the rest of its minute, and it ends after three successful saves."
            if persistent else ""))
    throw(engine, owner, target, ctx.source, shroud, cracking=bool(spec.get("cracking")))


def throw(engine: Any, owner: Any, target: Any, source: str, shroud: Any, *,
          cracking: bool = False) -> None:
    """One Cloud Shroud saving throw with the printed outcomes, through the engine's shared save orchestration.

    ``typed_executor.typed_save_modifiers`` names what the throw is about (its own printed conditions and damage
    types) and collects every plug-in's bonus, Advantage and Disadvantage; ``settle_typed_save`` is what notifies the
    shared save subscribers and lets them settle the outcome. That is the same pair ``block_save`` and the defending
    contests use, so a Defensive Weather Mantle or a Dry Sign advantage reaches a Shroud throw as it reaches any
    other save. A failure runs the sign's Shroud rows; a success prevents that round's damage or condition and counts
    towards the Persistent Shroud's three-success escape.
    """
    from .. import typed_executor as te

    if not target.active:
        return
    data = shroud.data
    dc = int(data.get("dc") or 10)
    ability = str(data.get("save") or "CON")
    ctx = _context(engine, owner, source, target, str(data.get("sign") or ""))
    # The printed rows that wait for "the start of your next turn" are the Shroud owner's own turn, not the creature the
    # Shroud is on (whose turns the throw repeats on), so they are pointed at the owner's own turn clock afresh.
    owner_token = weather_signs.owner_start(engine, owner)
    fail_rows = weather_signs.anchored(list(data.get("fail") or []), owner_token)
    success_rows = weather_signs.anchored(list(data.get("success") or []), owner_token)
    shaped, named, plug_in_named, pressed = te.typed_save_modifiers(ctx, target, ability, fail_rows, success_rows)
    modes = list(shaped.get("modes") or [])
    from .weather_fields import severity
    severe = (not data.get("first_save_done") and weather_signs.owns(engine, owner, "severe_shroud")
              and severity(engine, None, target, str(data.get("sign") or "")))
    if severe:
        modes.append("DISADVANTAGE")
    if weather_signs.owns(engine, owner, "severe_shroud") and not data.get("first_save_done"):
        data["first_save_done"] = 1
        record_instance_update(engine, target, "condition", shroud.instance_id, shroud)
    mode = modes[0] if len(set(modes)) == 1 else None
    record = engine._roll_save(target, ability, dc - int(shaped["bonus"]), source, extra_mode=mode,
                               roll_context={"source_actor_id": owner.entity_id,
                                             "named": sorted(str(n) for n in named),
                                             "save_modes": sorted(set(modes))})
    if record is None:
        return
    failed = record.total < dc - int(shaped["bonus"])
    failed = te.settle_typed_save(ctx, target, ability, record, failed, named, plug_in_named, pressed)
    if failed:
        _fail(ctx, target, shroud, fail_rows, cracking=cracking)
        if severe:
            from .weather_fields import severe_rider
            severe_rider(ctx, target, str(data.get("sign") or ""))
        return
    te.run_effects(ctx, success_rows)
    data["successes"] = int(data.get("successes") or 0) + 1

    # The counter is fight state, so it is recorded as a retained instance update: the reducer rebuilds it on
    # replay instead of finding a state the event log cannot reproduce.
    record_instance_update(engine, target, "condition", shroud.instance_id, shroud)
    if data.get("persistent") and int(data["successes"]) >= 3:
        _log(engine, source, owner.entity_id, (target.entity_id,),
             f"Cloud Shroud: {target.display_name} has saved three times against it, so the Shroud ends.")
        _remove(engine, target, shroud, "THREE_SUCCESSES")


def _fail(ctx: Any, target: Any, shroud: Any, rows: list[dict[str, Any]], *, cracking: bool) -> None:
    """A failed Cloud Shroud throw: the sign's printed Shroud effect, then its optional talents."""
    from .. import typed_executor as te
    from . import effect_durations

    engine, owner, data = ctx.engine, ctx.actor, shroud.data
    te.run_effects(ctx, rows)
    _black_ice_restrained(ctx, target, data)
    if not cracking or not weather_signs.owns(engine, owner, "pressure_cracking_shroud"):
        return
    from .weather_fields import severity
    field_policy = any(row.get("field_policy") == 1 for row in rows_of(engine, owner, "pressure_cracking_shroud"))
    if field_policy and not severity(engine, None, target, str(data.get("sign") or "")):
        return
    kind = _damage_type(data)
    payment = payable(owner, _CP, 2)
    if kind is None or payment is None:
        return
    sign_name = (weather_signs.sign(str(data.get("sign") or "")) or {}).get("name", "Weather")
    if not field_policy:
        # Preserve the exact legacy cast text and emission timing.
        ctx.rider(f"Pressure-Cracking Shroud: the printed wording applies only while {target.display_name} is standing "
                  f"inside gathered weather of the same sign ({sign_name}); there is no gathered-weather state here, so "
                  "confirm that at the table.")
    # "you may spend 2 CP to crack its resistance": the spending is the owner's decision, asked of the owner on
    # their turn and on anyone else's (an AI owner answers for itself, as every other choice does).
    asked = ask(engine, ctx.intent, checkpoint_id(engine, "CRACKING_CP", shroud.instance_id), owner,
                CHOICE + "weather_cracking_spend", ["spend"],
                labels={"spend": f"Spend 2 Cultivation Points to crack {target.display_name}'s Resistance to "
                                 f"{kind.lower()} damage"},
                target_id=target.entity_id, name="Pressure-Cracking Shroud",
                feature_id=CRACKING, payment=payment,
                prompt=(f"Pressure-Cracking Shroud: {target.display_name} failed its saving throw against your "
                        f"{sign_name} Shroud. If it is standing inside gathered weather of that sign, you may spend "
                        f"2 Cultivation Points to crack its resistance: until the end of your next turn it loses "
                        f"Resistance to {kind.lower()} damage."))
    if not asked:
        return
    payment.pay(engine, owner, ctx.source)
    # The engine's own suppression path (typed_reactions.defend reads a "resistance_suppressed" modifier), so the
    # target's Resistance returns by itself when the printed duration ends: "until the end of your next turn" is the
    # end of the owner's own next turn, which only the round clock can name exactly.
    engine._add_modifier(target, ctx.source, "resistance_suppressed", "SET", kind, "SELF",
                         expires_on=effect_durations.token("end", owner.entity_id, int(owner.turns_started) + 1))
    _log(engine, ctx.source, owner.entity_id, (target.entity_id,),
         f"Pressure-Cracking Shroud: {target.display_name} loses Resistance to {kind.lower()} damage until the end of "
         "your next turn.")


def _black_ice_restrained(ctx: Any, target: Any, data: dict[str, Any]) -> None:
    """Cold Sign's Black Ice: "If this reduces its Speed to less than 5 feet, it is Restrained" until its next turn."""
    from .. import typed_executor as te

    limit = int(data.get("speed_halved_below_ft") or 0)
    if not limit or ctx.engine._effective_speed(target) >= limit:
        return
    te.run_effects(ctx, [{"type": "condition", "applies_to": "target", "condition": "restrained",
                          "expires_on": weather_signs.TARGET_NEXT_START,
                          "evidence": "its Speed was halved below 5 feet, so it is Restrained until the start of its next turn"}])
    _log(ctx.engine, ctx.source, ctx.actor.entity_id, (target.entity_id,),
         f"Cloud Shroud: halving {target.display_name}'s Speed left it under 5 feet, so it is Restrained until the start "
         "of its next turn.")


def _damage_type(data: dict[str, Any]) -> str | None:
    """The Shroud's printed damage type ("the Shroud's damage type"), which Pressure-Cracking suppresses."""
    for row in data.get("fail") or []:
        for kind in row.get("damage_types") or ():
            if str(kind).lower() in _SHROUD_DAMAGE_TYPES:
                return str(kind).upper()
    return None


def _context(engine: Any, owner: Any, source: str, target: Any, sign_id: str) -> Any:
    """A typed context for the Shroud's own rows, so they resolve through the ordinary typed effect pipeline."""
    from .. import typed_executor as te

    action = engine.action_catalog.get(source) or engine.action_catalog.get(BASE)
    typed = {"source": source, "sphere": weather_signs.SPHERE, "weather_sign": sign_id, "effects": [], "weapon": None, "weather_shroud_roll": 1,
             "numbers": dict(((action.parameters or {}).get("typed") or {}).get("numbers") or {}),
             "duration": {"kind": "instant"}, "riders": []}
    return te.Context(engine, owner, action, getattr(engine, "_active_intent", None), typed, [target], target, {})


@hook("turn_start")
def expire_shrouds(engine: Any, actor: Any) -> None:
    """A Cloud Shroud's printed "up to 1 minute", for both the ordinary and the Persistent kind.

    Concentration only ever ends a Shroud early; the minute is its own printed clock, so it is swept here the way
    ``weather_mantle.expire_mantles`` sweeps the Lingering Mantle's, and a Concentration-backed Shroud takes its
    owner's Concentration with it when the minute is up.
    """
    from .. import concentration

    now = (engine.state.round_number, engine.state.current_slot_index)
    for holder in engine.state.actors.values():
        for shroud in list(holder.conditions.values()):
            if shroud.condition_id != SHROUD:
                continue
            deadline = shroud.data.get("expiry_round")
            if deadline is None:  # an old saved Shroud, placed before this clock existed
                continue
            if now < (int(deadline), int(shroud.data.get("expiry_slot") or 0)):
                continue
            owner = engine.state.actors.get(shroud.source_actor_id)
            started = (shroud.data or {}).get("concentration_started_sequence")
            if owner is not None and started is not None and not (shroud.data or {}).get("persistent"):
                held = owner.concentration
                if held is not None and held.started_sequence == started:
                    engine._end_concentration(owner, "DURATION_ENDED")
                else:
                    for key, one in concentration.held(owner):
                        if one.started_sequence == started:
                            concentration.end_held(engine, owner, key, "DURATION_ENDED")
                            break
            _remove(engine, holder, shroud, "DURATION_ENDED")


@hook("turn_end")
def repeat_shroud_save(engine: Any, actor: Any) -> None:
    """"a creature makes the listed saving throw when the Shroud is placed and again at the end of each of its turns"."""
    if not actor.active:
        return
    for shroud in shrouds(actor):
        owner = engine.state.actors.get(shroud.source_actor_id)
        if owner is None or weather_signs.sign(sign_of(shroud)) is None:
            continue
        throw(engine, owner, actor, shroud.source_definition_id, shroud,
              cracking=weather_signs.owns(engine, owner, "pressure_cracking_shroud"))


# ------------------------------------------------------------------------------- Lightning Chooses the Rod
@effect("weather_thunder_shroud_move")
def move_thunder_shroud(ctx: Any, spec: dict[str, Any]) -> None:
    """Lightning Chooses the Rod: move your Thunder Shroud to another creature near the old target, no action.

    "you may move your Thunder Shroud to another creature within 30 feet of the original target without using an
    action"; "The new target immediately makes the Shroud's saving throw"; "You may do this once per round."
    ``ctx.target`` is the creature the Shroud moves to; the Shroud it moves is the owner's own Thunder Shroud on
    another creature.
    """
    engine, owner, destination = ctx.engine, ctx.actor, ctx.target
    if destination is None or owner.turn_flags.get("weather_rod_round") == engine.state.round_number:
        return
    found = [(creature, c) for creature in engine.state.actors.values()
             for c in shrouds(creature, owner.entity_id) if sign_of(c) == "thunder" and creature.active]
    if len(found) != 1:
        return
    origin_holder, origin = found[0]
    if engine._distance_actor_to_actor(origin_holder, destination) > 30:
        ctx.rider(f"Lightning Chooses the Rod: {destination.display_name} is not within 30 feet of {origin_holder.display_name}.")
        return
    owner.turn_flags["weather_rod_round"] = engine.state.round_number
    data = dict(origin.data or {})
    expires = origin.expires_on
    _remove(engine, origin_holder, origin, "MOVED")
    moved = engine._apply_condition(destination, SHROUD, origin.source_definition_id, owner.entity_id,
                                    expires_on=expires, data=data) or next(
        (c for c in shrouds(destination, owner.entity_id)), None)
    _log(engine, origin.source_definition_id, owner.entity_id, (destination.entity_id,),
         f"Lightning Chooses the Rod: the Thunder Shroud moves from {origin_holder.display_name} to "
         f"{destination.display_name}, who makes the Shroud's saving throw now.")
    throw(engine, owner, destination, origin.source_definition_id, moved,
          cracking=weather_signs.owns(engine, owner, "pressure_cracking_shroud"))


# ------------------------------------------------------------------------------- the printed Shroud markers
def _ranged_weapon_attack(ctx: Any) -> bool:
    """Whether the attack now resolving is a ranged weapon attack, which is what Wind's Shroud prints.

    A melee blow is never affected (``thunder_charges.melee_attack`` is the shared melee test), and neither is a spell or
    an unarmed strike: the printed words are "ranged weapon attacks".
    """
    from .thunder_charges import melee_attack

    if melee_attack(ctx):
        return False
    kinds = {str((getattr(ctx, "attack_effect", None) or {}).get("attack_kind") or "").lower()}
    kinds |= {str(row.get("attack_kind") or "").lower() for row in (getattr(ctx, "typed", None) or {}).get("effects") or ()
              if isinstance(row, dict) and row.get("type") == "attack"}
    return "weapon" in kinds


def shrouded_ranged(ctx: Any, target: Any) -> str | None:
    """Wind Sign's Shroud: Disadvantage on the shrouded creature's ranged weapon attacks.

    The marker is the shrouded creature's own ("Disadvantage on ranged weapon attacks until the start of its next
    turn"), so it is read from the creature *making* the attack -- ``ctx.actor``, the attacker -- and not from its target:
    reading the target handed the penalty to whoever shot the shrouded creature and spent its own marker. Read from the
    live conditions so a marker that has already ended (or was ended early) no longer applies, and the "still has
    Disadvantage on its **next** ranged weapon attack" one is used up by the attack it spoiled.
    """
    if not _ranged_weapon_attack(ctx):
        return None
    for condition in markers(ctx.actor, "weather_ranged"):
        if (condition.data or {}).get("next"):
            _spend_marker(ctx.engine, ctx.actor, condition)
        return "DISADVANTAGE"
    return None


@hook("attack_mode")
def attributed_shrouded_ranged(ctx: Any, target: Any) -> dict[str, str] | None:
    """Attach transient weather provenance without changing the public query."""
    mode = shrouded_ranged(ctx, target)
    return {"mode": mode, "cause": "weather"} if mode else None


@hook("save")
def shroud_next_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Rain's "Disadvantage on the next saving throw it makes against a Cold Sign effect", and Dry's next Constitution save.

    Both are live one-shot markers, so the save they spoil spends them rather than every later save. A Cold Sign Shroud
    throw names its own sign on the context (``weather_sign``), because its printed rows are only a Speed change and so
    tell the engine nothing else about what the save is against.
    """
    signs = weather_signs.signs_of_save(named or set())
    save_sign = weather_signs.pending_sign(getattr(ctx, "typed", None))
    if save_sign:
        signs.add(save_sign)
    spent: list[Any] = []
    for name, applies in (("weather_cold_save", "cold" in signs),
                          ("weather_con_save", str(ability or "").upper() == "CON")):
        if not applies:
            continue
        for condition in markers(subject, name):
            spent.append(condition)
    if not spent:
        return None
    for condition in spent:
        _spend_marker(ctx.engine, subject, condition)
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}


@hook("condition_attempt")
def dry_shroud_poison(ctx: Any, subject: Any, effect: dict[str, Any]) -> bool | None:
    """Dry Sign's Shroud: "creatures immune to poison are immune to the Poisoned condition from this Shroud".

    Immunity, not Resistance: a creature that merely resists poison is still poisoned by the dust.
    """
    if effect.get("condition") != "poisoned" or subject is None:
        return None
    if str((getattr(ctx, "typed", None) or {}).get("weather_sign") or "") != "dry":
        return None
    from ..typed_executor import condition_immune

    immune = condition_immune(ctx.engine, subject, "poisoned")
    if not immune:
        immune = any(str(kind).upper() == "POISON" for kind in (getattr(subject, "damage_immunities", None) or ()))
    if not immune:
        immune = any(m.target_field == "damage_immunity" and str(m.value).upper() == "POISON"
                     for m in subject.modifiers.values())
    if immune:
        ctx.rider(f"Dry Sign Shroud: {subject.display_name} is immune to poison, so it is not Poisoned.")
        return False
    return None


@hook("button_description")
def shroud_description(row: dict[str, Any]) -> str | None:
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    spec = next((e for outer in effects for e in (outer.get("effects", [outer]) if isinstance(outer, dict) else [outer])
                 if isinstance(e, dict) and e.get("type") == "weather_cloud_shroud"), None)
    if spec is None:
        return None
    text = ("Action, 60 feet, 1 Cultivation Point: hang a private weather around one creature. It makes the saving throw of the "
            "Weather Sign you choose, now and at the end of each of its turns. A failed save runs that sign's Shroud effect; a "
            "successful save prevents that round's damage or condition without ending the Shroud. Concentration, up to 1 minute. "
            "A creature can be under only one of your Cloud Shrouds at a time.")
    if spec.get("persistent"):
        text += (" Plus 2 Cultivation Points: it lasts its remaining duration without Concentration and ends after the target "
                 "saves three times against it. At Mortal Realm (cultivation levels 1-4) only one of your Persistent Shrouds "
                 "may be active at a time.")
    if spec.get("cracking"):
        text += (" Pressure-Cracking Shroud: on a failed save you may spend 2 Cultivation Points to take away its Resistance "
                 "to that Shroud's damage type until the end of your next turn.")
    return text
