"""Sky Mantle, its Weather Sign benefits and the Mantle talents that read the sign.

The owner's authority has no Weather Sign talent records, so this module reads the six printed Weather Signs from
``combat/ext/weather_signs.py`` and applies what Sky Mantle prints:

  Sky Mantle (base)   "choose one Weather Sign talent you know. The target gains that sign's Mantle effect" -- the
                      sign is chosen by name from the printed six (compendium: "choose one of the following"), active
                      weather or forced with 1 additional CP as printed, and the sign's Mantle effect now runs
                      (Wind's Speed, Rain's escape checks and fire Resistance, Cold's ice-terrain, Heat's
                      Temporary Hit Points, Dry's saves and carrying, Thunder's storm saves).
  Defensive Weather   "it has Advantage if the Mantle's sign matches or opposes the effect's sign" -- the ``save``
                      hook, read from the conditions and damage types typed_executor already named for the save.
  Weatherproof Mantle "Choose one Weather Sign talent you know. The Mantle effect of that sign also grants Resistance
                      to one damage type while the sign is active" -- the sign is chosen once per purchase and kept for
                      the fight, the printed Resistance per sign is condition rule data (the shared
                      ``damage_defenses`` path in combat/ext/standard_conditions.py), Thunder's "lightning or thunder
                      damage, chosen when the Mantle is placed" is asked of the one placing it, and what the engine's
                      damage-type Resistances cannot name (Dry's "necrotic damage from desiccation") is said plainly to
                      the table instead of quietly widened to every such damage.
  Weather Backlash    "When a creature with your Sky Mantle is hit by a melee attack while the Mantle's sign is
                      active, the attacker takes damage equal to your Proficiency Bonus", typed by sign and once
                      per round per mantled creature -- the ``after_hit`` hook; Thunder's own printed Mantle burn
                      ("once during the Mantle") is resolved by the same hook, once per Mantle.
  Shared Weather Favor "you may spend 1 additional CP to target one additional willing creature within 30 feet"
                      (up to three more at Foundation Realm) with the same sign -- extra target variants of the cast,
                      the three-recipient one compiled only for a character at Foundation Realm or above. One cast is
                      one sign, one forced-sign Cultivation Point and one Concentration however many recipients it
                      reaches; a recipient who refuses simply does not get the Mantle.
  Quick Mantle        the cast as a Bonus Action, and one free combat cast per short rest.
  Lingering Mantle    2 additional CP for the cast's own duration without Concentration; at Mortal Realm a new
                      lingering cast ends the owner's previous lingering cast, even on another creature.

Every hook returns early unless the creature owns the printed row it reads, so a character without a Weather Mantle
is untouched and an old saved fight (no ``data["sign"]``) keeps exactly the behaviour it had: a GM-run sign with no
sign benefit. Both hooks are documented in combat/ext/__init__.py.
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from . import weather_signs
from .needle import CHOICE, ask, checkpoint_id
from .retained_updates import record_instance_update

BASE = "WEATHER_BASE_SKY_MANTLE"
MANTLE = "condition:typed.sky_mantle"
QUICK = "TAL_WEATHER_QUICK_MANTLE"
LINGERING = "TAL_WEATHER_LINGERING_MANTLE"
SHARED_FAVOR = "TAL_WEATHER_SHARED_WEATHER_FAVOR"
WEATHERPROOF = "TAL_WEATHER_WEATHERPROOF_MANTLE"
BACKLASH = "TAL_WEATHER_WEATHER_BACKLASH"
FREE_CAST = "resource:weather.quick_mantle"
SIGN_CHOICE = CHOICE + "sky_mantle_sign"
WEATHERPROOF_SIGN_CHOICE = CHOICE + "sky_mantle_weatherproof_sign"

#: "Active" keeps the printed 1 additional CP for a sign that is not already active; "force" spends it.
ACTIVE, FORCE = "active", "force"

#: The modifier field that remembers which Weather Sign one Weatherproof Mantle purchase covers. "Choose one Weather Sign
#: talent you know ... You may take this talent more than once, choosing a different Weather Sign each time": a purchase is
#: for one sign, and this is where the table's choice is written down so a later cast of another sign gets no Resistance
#: from it. The engine ignores an unknown modifier field (nothing else reads it), so it is inert bookkeeping.
WEATHERPROOF_FIELD = "weatherproof_sign"


def _cast_id(ctx: Any) -> str:
    """What names this one cast of Sky Mantle, however many recipients it reaches.

    The action's own intent does: it is the same for every recipient of one cast, and different for the next cast of the
    same button. (It is deliberately read from the intent rather than from the choice transport's cache, which outlives the
    transaction a paused choice is re-run from: what has already happened in *this* cast is a question about the fight
    state, and the Mantle each recipient wears records the cast that placed it.)
    """
    intent = ctx.intent or getattr(ctx.engine, "_active_intent", None)
    return str(getattr(intent, "intent_id", "") or f"event:{ctx.engine.state.event_sequence}")


def _cast_checkpoint(ctx: Any, name: str) -> str:
    """One question per cast: asking again with the same checkpoint returns the answer already given."""
    return ":".join(["WEATHER", name, _cast_id(ctx)])


@hook("compile_action")
def defer_mantle_concentration(action: Any, info: dict[str, Any]) -> Any:
    """Start the owned Mantle's Concentration only after recipient consent.

    Refusing a new Mantle must not end an existing one. The executor normally
    starts Concentration before effects, so this plug-in defers that step.
    """
    typed = (action.parameters or {}).get("typed") or {}
    if BASE not in info["owned_ids"] or not str(typed.get("source", "")).startswith(BASE) \
            or not any(row.get("type") == "choose_willing" for row in typed.get("effects") or []):
        return None
    parameters = copy.deepcopy(action.parameters)
    parameters["typed"]["duration"]["concentration"] = False
    for row in parameters["typed"]["effects"]:
        for spec in row.get("effects", []):
            if spec.get("type") == "weather_sky_mantle" and not spec.get("lingering") and not spec.get("refresh"):
                spec["deferred_concentration"] = 1
    return action.model_copy(update={"parameters": parameters})


@hook("compile_resources")
def quick_mantle_allowance(info: dict[str, Any]) -> list[Any] | None:
    """One free combat cast per short rest; combat has no in-fight rests.

    The ordinary evented resource cost survives reload and turn changes. New
    fights start with one use, like other rest-limited combat allowances.
    """
    if QUICK not in info["owned_ids"] or BASE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ResourceDefinition

    return [ResourceDefinition(resource_id=FREE_CAST, initial=1, maximum=1)]


def _owned(info: dict[str, Any]) -> bool:
    return BASE in info["owned_ids"]


def _mantles(actor: Any, owner: str) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == MANTLE and c.source_actor_id == owner]


def all_mantles(actor: Any) -> list[Any]:
    """Every Sky Mantle on a creature, whoever placed it (used by Weather Backlash and by the sign readers)."""
    return [c for c in actor.conditions.values() if c.condition_id == MANTLE]


def sign_of(mantle: Any) -> str:
    """The printed sign id a mantle carries, or "" for an old saved fight or a GM-run sign."""
    return str((mantle.data or {}).get("sign") or "")


def _remove(engine: Any, holder: Any, mantle: Any, reason: str) -> None:
    if holder.conditions.pop(mantle.instance_id, None) is not None:
        engine._append_event("CONDITION_REMOVED", mantle.source_definition_id, actor_id=mantle.source_actor_id,
                             target_ids=(holder.entity_id,), payload={"condition_id": MANTLE, "instance_id": mantle.instance_id, "reason": reason})


@hook("compile_actions")
def mantle_actions(info: dict[str, Any]) -> list[Any] | None:
    if not _owned(info):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    base = next((a for a in info["actions"] if ((a.parameters or {}).get("typed") or {}).get("source") == BASE), None)
    if base is None:
        return None

    additions = [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.weather.refresh_mantle", display_name="Refresh Mantle",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF",
        costs=base.costs,
        parameters={"typed": {"source": BASE + "#refresh", "sphere": "tianxia.sphere.weather", "numbers": info["numbers"],
                              "effects": [{"type": "weather_sky_mantle", "refresh": True}],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0})]
    if QUICK in info["owned_ids"]:
        for cast in info["actions"]:
            typed = (cast.parameters or {}).get("typed") or {}
            if typed.get("source") != BASE:
                continue
            for suffix, name, economy, free in (
                ("quick", "Quick Mantle", EconomyKind.BONUS_ACTION, False),
                ("free", "Sky Mantle (free once per short rest)", EconomyKind.ACTION, True),
                ("quick_free", "Quick Mantle (free once per short rest)", EconomyKind.BONUS_ACTION, True),
            ):
                parameters = copy.deepcopy(cast.parameters)
                variant = parameters["typed"]
                variant["source"] = BASE + "#" + suffix
                for spec in variant["effects"][0]["effects"]:
                    if spec.get("type") == "weather_sky_mantle":
                        spec.update(quick=economy == EconomyKind.BONUS_ACTION, free=free,
                                    cp_pool=cast.costs[0][0] if cast.costs else None)
                additions.append(cast.model_copy(update={
                    "source_definition_id": cast.source_definition_id + "." + suffix,
                    "display_name": name, "economy": economy, "parameters": parameters,
                    "costs": ((FREE_CAST, 1),) if free else cast.costs,
                }))
    if LINGERING in info["owned_ids"]:
        # Choose the augment in the action menu before paying costs or starting
        # Concentration. This also preserves any separately held technique.
        for cast in [*info["actions"], *additions]:
            parameters = copy.deepcopy(cast.parameters)
            typed = parameters.get("typed") or {}
            rows = typed.get("effects") or []
            nested = rows[0].get("effects", rows) if rows else []
            spec = next((e for e in nested
                         if e.get("type") == "weather_sky_mantle" and not e.get("refresh")), None)
            if spec is None:
                continue
            cp = spec.get("cp_pool") or (cast.costs[0][0] if cast.costs else None)
            if cp is None:
                continue
            spec.update(lingering=True, cp_pool=cp)
            typed["source"] += "#lingering"
            typed["duration"]["concentration"] = False
            costs = dict(cast.costs)
            costs[cp] = costs.get(cp, 0) + 2
            additions.append(cast.model_copy(update={
                "source_definition_id": cast.source_definition_id + ".lingering",
                "display_name": cast.display_name + " + Lingering Mantle",
                "parameters": parameters, "costs": tuple(costs.items()),
            }))
    # Shared Weather Favor: the printed extra willing targets, all on the same sign. Each extra is its own
    # choose_willing row, so every recipient is asked (combat/ext/willing_targets.py) and the sign is reused.
    # "spend 1 additional CP to target one additional willing creature within 30 feet" is any owner's; the
    # three-recipient version is printed for Foundation Realm and above, so it is compiled only for a character whose
    # Cultivation Level has reached Foundation Realm (combat/ext/weather_signs.py.realm_at).
    if SHARED_FAVOR in info["owned_ids"]:
        cl = int((info.get("numbers") or {}).get("cl") or 1)
        foundation = weather_signs.BANDS.index(weather_signs.realm_at(cl)) >= 1
        for cast in info["actions"]:
            typed = (cast.parameters or {}).get("typed") or {}
            if typed.get("source") != BASE:
                continue  # the printed augment of the ordinary cast; the Quick/Lingering variants keep their own menus
            cp = next((pool for pool, _ in (cast.costs or ()) if pool), None)
            if cp is None:
                continue
            for extra, more in (row for row in ((1, 1), (3, 2)) if row[0] == 1 or foundation):
                parameters = copy.deepcopy(cast.parameters)
                variant = parameters["typed"]
                primary = next((spec for spec in variant.get("effects") or []
                                if spec.get("type") == "choose_willing"), None)
                if primary is None or not primary.get("effects"):
                    continue
                rows = [{**copy.deepcopy(primary), "effects": [{**copy.deepcopy(primary["effects"][0]), "shared_favor": extra}]}]
                for _ in range(extra):
                    rows.append({"type": "choose_willing", "target_only": False, "allow_hostile_target": True, "range_ft": 30,
                                 "evidence": "one additional willing creature within 30 feet",
                                 "effects": [{"type": "weather_sky_mantle", "shared_favor": extra}]})
                variant["effects"] = rows
                costs = {pool: amount + more for pool, amount in (cast.costs or ())}
                label = "one more" if extra == 1 else "three more"
                additions.append(cast.model_copy(update={
                    "source_definition_id": cast.source_definition_id + f".shared{extra}",
                    "display_name": f"{cast.display_name} + Shared Weather Favor ({label})",
                    "parameters": parameters, "costs": tuple(costs.items())}))
    from .willing_targets import willing_non_allies
    # Preserve the existing ally/self refresh path. Non-allies use the same
    # consent transport as casts, with eligibility checked through the wrapper.
    refresh = additions[0]
    parameters = copy.deepcopy(refresh.parameters)
    parameters["typed"]["effects"] = [{
        "type": "choose_willing", "target_only": True, "allow_hostile_target": True,
        "range_ft": 5, "effects": parameters["typed"]["effects"],
    }]
    # The offered target must be within the same Touch range as consent.
    consenting_refresh = refresh.model_copy(update={"parameters": parameters, "range_ft": 5})
    additions.extend(willing_non_allies({**info, "actions": [consenting_refresh, *additions[1:]]}) or [])
    return additions


@hook("candidate_allowed")
def refresh_requires_mantle(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    effects = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or []
    if not any(e.get("type") == "weather_sky_mantle" and e.get("refresh")
               for row in effects for e in row.get("effects", [row])):
        return None
    return bool(candidate.target_ids and _mantles(engine.state.actors[candidate.target_ids[0]], actor.entity_id))


@hook("button_description")
def mantle_description(row: dict[str, Any]) -> str | None:
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    spec = next((e for row in effects for e in (row.get("effects", [row]))
                 if e.get("type") == "weather_sky_mantle"), None)
    if spec is None:
        return None
    if spec.get("refresh"):
        return ("Bonus Action, 1 Cultivation Point: change one of your existing Sky Mantles to another Weather Sign you know. "
                "Use an active sign or spend 1 additional Cultivation Point to force it. Its original duration and need for Concentration stay unchanged.")
    timing = "Bonus Action" if spec.get("quick") else "Action"
    cost = "no base Cultivation Point cost, once per short rest" if spec.get("free") else "1 Cultivation Point"
    duration = "Concentration, up to 1 minute"
    limit = ""
    if spec.get("lingering"):
        cost += " plus 2 Cultivation Points for Lingering Mantle"
        duration = "1 minute without Concentration"
        limit = " At Mortal Realm (cultivation levels 1–4), it also ends your previous Lingering Mantle on any creature."
    extra = ""
    if spec.get("shared_favor"):
        more = "one" if spec["shared_favor"] == 1 else "three"
        extra = (f" Plus {more} other willing creature{'s' if more == 'three' else ''} within 30 feet on the same sign"
                 f" (Shared Weather Favor, {1 if more == 'one' else 2} extra Cultivation Points already paid).")
    return (f"{timing}, Touch, {cost}: place a Weather Sign you know on one willing creature; {duration}. "
            "Use an active sign or spend 1 additional Cultivation Point to force it. It replaces your previous Mantle on that creature. "
            "The mantled creature gains that sign's printed benefit, and has Advantage on saving throws against a Weather effect "
            "whose sign matches or opposes it; the ten-minute ritual is outside combat." + limit + extra)


# --------------------------------------------------------------------------------------------- the printed sign choice

def _options(cp: bool) -> list[str]:
    """One printed option per Weather Sign and per way of paying for it ("active" or forced with 1 CP)."""
    modes = [ACTIVE] + ([FORCE] if cp else [])
    return [f"{sign}:{mode}" for sign in weather_signs.names() for mode in modes]


def _labels() -> dict[str, str]:
    out: dict[str, str] = {}
    for sign_id in weather_signs.names():
        row = weather_signs.sign(sign_id) or {}
        summary = (row.get("mantle") or {}).get("plain") or ""
        out[f"{sign_id}:{ACTIVE}"] = f"{row.get('name')}: {summary} (that sign is active here, no extra Cultivation Point)"
        out[f"{sign_id}:{FORCE}"] = f"{row.get('name')}: {summary} (forced by you, 1 extra Cultivation Point)"
    return out


def _prompt(name: str, target_name: str, refresh: bool, can_force: bool, shared: Any = None) -> str:
    return (f"{name}: choose the Weather Sign talent {target_name} is wrapped in. Your character must have taken that "
            "Weather Sign talent; each option says what that sign does."
            + (" Pick a sign that is already active where the creature stands, or force one through your own cultivation "
               "for 1 extra Cultivation Point." if can_force
               else " Pick a sign that is already active where the creature stands (forcing one costs 1 extra Cultivation Point, "
                    "which you do not have).")
            + (" The Mantle keeps its original duration and its need for Concentration." if refresh
               else " It lasts Concentration, up to 1 minute, unless you pay Lingering Mantle.")
            + (" Every other willing creature you pick for Shared Weather Favor receives the same sign." if shared else ""))


@effect("weather_sky_mantle")
def place_or_refresh(ctx: Any, spec: dict[str, Any]) -> None:
    """One cast: ask the sign once, pay the forced-sign point once, then wrap each consenting creature in it.

    "All targets must receive the same Weather Sign" is a rule about the cast, not about each recipient, so the sign, the
    optional Cultivation Point that forces it and the Concentration the Mantle needs are all settled on the first
    recipient and reused for the rest (see ``_cast_id``).
    """
    targets = [t for t in ([ctx.target] if ctx.target is not None else list(ctx.targets or [])) if t is not None]
    if not targets:
        targets = [ctx.actor]
    cp = spec.get("cp_pool") or (ctx.action.costs[0][0] if ctx.action.costs else None)
    can_force = bool(cp) and ctx.actor.resources.get(cp, 0) >= 1
    if spec.get("refresh") and not _mantles(targets[0], ctx.actor.entity_id):
        return
    name = ctx.action.display_name
    cast = _cast_id(ctx)
    chosen = ask(ctx.engine, ctx.intent, _cast_checkpoint(ctx, "SKY_MANTLE_SIGN"), ctx.actor,
                 SIGN_CHOICE, _options(bool(cp)), labels=_labels(),
                 target_id=targets[0].entity_id, name=name, feature_id=BASE,
                 prompt=_prompt(name, targets[0].display_name, bool(spec.get("refresh")), can_force, spec.get("shared_favor")))
    if not chosen:
        return
    sign_id, _, mode = str(chosen[0]).partition(":")
    if weather_signs.sign(sign_id) is None:
        return
    first = not _placed_this_cast(ctx, cast)
    if first and mode == FORCE:
        ctx.engine._spend_resource(ctx.actor, cp, 1, ctx.source)
    for target in targets:
        _one(ctx, target, spec, sign_id, mode, name, cast=cast, concentrate=first)


def _placed_this_cast(ctx: Any, cast: str) -> bool:
    """Whether this cast has already placed one of its own Mantles, which settles its sign, payment and Concentration."""
    return any((mantle.data or {}).get("cast") == cast
               for holder in ctx.engine.state.actors.values() for mantle in _mantles(holder, ctx.actor.entity_id))


def _one(ctx: Any, target: Any, spec: dict[str, Any], sign_id: str, mode: str, name: str, *,
         cast: str = "", concentrate: bool = False) -> None:
    """Place (or re-sign) one mantled creature's Sky Mantle with the printed sign's benefit already attached."""
    held = _mantles(target, ctx.actor.entity_id)
    row = weather_signs.sign(sign_id) or {}
    numbers = ctx.numbers or {}
    weatherproof = _weatherproof_sign(ctx, sign_id)
    if spec.get("refresh"):
        mantle = held[0]
        mantle.data["sign_supply"] = mode
        mantle.data.update(_sign_data(ctx, sign_id, mode, numbers, weatherproof))
        record_instance_update(ctx.engine, target, "condition", mantle.instance_id, mantle)
        _log(ctx.engine, ctx.source, ctx.actor.entity_id, (target.entity_id,),
             f"{name}: {target.display_name}'s Sky Mantle now carries {row.get('name')}, and that sign's printed benefit applies. "
             "Its original duration and need for Concentration are unchanged.")
        return
    if concentrate and spec.get("deferred_concentration"):
        ctx.engine._start_concentration(ctx.actor, ctx.source)
    if spec.get("lingering") and int(numbers.get("cl") or 1) <= 4:
        for holder in ctx.engine.state.actors.values():
            for mantle in _mantles(holder, ctx.actor.entity_id):
                if mantle.data.get("lingering"):
                    _remove(ctx.engine, holder, mantle, "REPLACED")
    for mantle in held:
        _remove(ctx.engine, target, mantle, "REPLACED")
    data = {**_sign_data(ctx, sign_id, mode, numbers, weatherproof),
            "cast": cast,
            "expiry_round": ctx.engine.state.round_number + 10,
            "expiry_slot": ctx.engine.state.current_slot_index,
            "label": f"Sky Mantle ({row.get('name')}): {(row.get('mantle') or {}).get('plain') or ''}"}
    if spec.get("lingering"):
        data["lingering"] = 1
    else:
        # Which Concentration this Mantle is holding, so the minute's own clock (expire_mantles) releases exactly that one.
        held_concentration = ctx.actor.concentration
        data["concentration_started_sequence"] = (held_concentration.started_sequence
                                                  if held_concentration is not None else None)
    ctx.engine._apply_condition(target, MANTLE, ctx.source, ctx.actor.entity_id,
                                expires_on=ctx.expires_on() if spec.get("lingering") else "CONCENTRATION_END", data=data)
    paid = "forced through your own cultivation for 1 extra Cultivation Point" if mode == FORCE else "that sign is already active here"
    _log(ctx.engine, ctx.source, ctx.actor.entity_id, (target.entity_id,),
         f"{name}: {target.display_name} is wrapped in {row.get('name')} ({paid}). "
         f"{(row.get('mantle') or {}).get('plain') or ''}")


def _weatherproof_signs(engine: Any, owner: Any) -> list[str]:
    """The Weather Signs this owner's Weatherproof Mantle purchases cover, as the table chose them."""
    return sorted({str(modifier.value) for modifier in owner.modifiers.values()
                   if modifier.target_field == WEATHERPROOF_FIELD})


def _weatherproof_sign(ctx: Any, sign_id: str) -> bool:
    """Whether one Weatherproof Mantle purchase covers this sign, asking once if it has not been said yet.

    "Choose one Weather Sign talent you know. The Mantle effect of *that sign* also grants Resistance ... You may take this
    talent more than once, choosing a different Weather Sign each time": owning the talent is not enough, the purchase is
    for one sign. The answer is written on the owner so a later cast of a different sign gets nothing from this purchase.
    """
    if not weather_signs.owns(ctx.engine, ctx.actor, "weatherproof_mantle"):
        return False
    if sign_id in _weatherproof_signs(ctx.engine, ctx.actor):
        return True
    if _weatherproof_signs(ctx.engine, ctx.actor):
        return False  # the purchase is already spent on another sign
    who = ctx.target.display_name if ctx.target is not None else ctx.actor.display_name
    name = ctx.action.display_name
    options = weather_signs.names()
    picked = ask(ctx.engine, ctx.intent, _cast_checkpoint(ctx, "WEATHERPROOF_SIGN"), ctx.actor,
                 WEATHERPROOF_SIGN_CHOICE, options,
                 labels={value: f"Weatherproof Mantle: {who} gains the {weather_signs.sign(value).get('name')} "
                                 f"Mantle effect's printed Resistance while that sign is active" for value in options},
                 target_id=ctx.target.entity_id if ctx.target is not None else None, name=name, feature_id=WEATHERPROOF,
                 prompt=(f"{name}: your Weatherproof Mantle is for one Weather Sign talent, and every Mantle of a "
                         f"different sign gets nothing from it. Choose which sign this purchase covers for {who}."))
    if not picked or weather_signs.sign(str(picked[0])) is None:
        return False
    ctx.engine._add_modifier(ctx.actor, WEATHERPROOF, WEATHERPROOF_FIELD, "ADD", str(picked[0]), "SELF",
                             expires_on="UNTIL_REMOVED")
    _log(ctx.engine, ctx.source, ctx.actor.entity_id, (ctx.target.entity_id,) if ctx.target is not None else (),
         f"Weatherproof Mantle: the purchase covers {weather_signs.sign(str(picked[0])).get('name')}, so a Mantle of "
         "another sign gains nothing from it.")
    return str(picked[0]) == sign_id


def _sign_data(ctx: Any, sign_id: str, mode: str, numbers: dict[str, Any], weatherproof: bool) -> dict[str, Any]:
    """The stored data of a Sky Mantle: its printed sign, its benefit, and the printed rule row it grants.

    Integers and strings only, so a saved fight reloads with the same sign, Speed bonus and defenses.
    """
    row = weather_signs.sign(sign_id) or {}
    mantle = row.get("mantle") or {}
    cl = int(numbers.get("cl") or 1)
    resistances = [str(kind).upper() for kind in mantle.get("damage_resistances") or ()]
    # Rain's "Resistance to fire damage while the weather around it is Precipitation severity 1 or higher, or while you
    # force the sign with Cultivation Points": the gathered-weather half needs the field this repository has no state for,
    # so the forced half is read from the sign's own row and only that half is automated.
    if mode == FORCE:
        resistances += [str(kind).upper() for kind in mantle.get("forced_damage_resistances") or ()]
    resistances += [str(kind).upper() for kind in (weather_signs.by_realm(mantle.get("damage_resistances_by_realm"), cl) or ())]
    advantage = {str(name).lower() for name in (mantle.get("save_advantage") or ())}
    advantage |= {str(name).lower() for name in (weather_signs.by_realm(mantle.get("save_advantage_by_realm"), cl) or ())}
    chosen = ""
    if weatherproof:
        proof = row.get("weatherproof") or {}
        # "Thunder grants Resistance to lightning or thunder damage, chosen when the Mantle is placed": the only
        # printed choice, and it is asked of the one placing the Mantle, on a placed cast and on a refresh alike.
        options = [str(kind).upper() for kind in proof.get("choose_damage_types") or ()]
        if options:
            picked = _ask_weatherproof(ctx, sign_id, options)
            chosen = str(picked).upper() if picked in options else ""
        # The printed Resistance of the chosen sign, without the sign's own Mantle Resistance twice over.
        granted = {str(kind).upper() for kind in mantle.get("damage_resistances") or ()} | set(resistances)
        for kind in [chosen, *(str(value).upper() for value in proof.get("damage_resistances") or ())]:
            if kind and kind not in granted:
                granted.add(kind)
                resistances.append(kind)
        advantage |= {str(value).lower() for value in proof.get("save_advantage") or ()}
        who = ctx.target.display_name if ctx.target is not None else ctx.actor.display_name
        for line in proof.get("manual") or ():
            # Each printed line carries its own reason in its own words. A line that is about a whole Resistance (Dry's
            # "necrotic damage from desiccation") says so itself; a line about a saving throw (Heat's "cold weather
            # hazards") is not a Resistance at all and must not be handed the Resistance's explanation.
            ctx.rider(f"Weatherproof Mantle: {who} gains {row.get('name')}'s printed benefit "
                      f"{proof.get('plain') or ''} The game cannot decide this one, so it is the table's to settle: "
                      f"{line}.")
    who = ctx.target.display_name if ctx.target is not None else ctx.actor.display_name
    for line in mantle.get("manual") or ():
        if sign_id == "rain" and "gathered" in line.lower() and ctx.typed.get("weather_field_policy") == 1:
            continue  # weather_fields.gathered_rain_mantle queries current Rain dynamically
        # Cold's restricted difficult terrain and Dry's carrying bonus: printed, and beyond what the engine models.
        ctx.rider(f"Sky Mantle: {who} gains {row.get('name')}'s printed benefit {line}.")
    rule: dict[str, Any] = {}
    if resistances:
        rule["damage_resistances"] = sorted(set(resistances))
    if mantle.get("death_save_advantage"):
        # "Advantage on death saving throws": combat/ext/life_state._modes reads this printed rule off the creature.
        rule["death_save_mode"] = {"mode": "ADVANTAGE"}
    speed = weather_signs.by_realm(mantle.get("speed_ft"), cl)
    return {"sign": sign_id, "forced": 1 if mode == FORCE else 0, "sign_supply": mode,
            "realm": weather_signs.realm_at(cl), "rule": rule, "speed_ft": int(speed or 0),
            "save_advantage": sorted(advantage), "weatherproof": chosen,
            "death_save_advantage": 1 if mantle.get("death_save_advantage") else 0,
            "escape_advantage": 1 if mantle.get("escape_advantage") else 0,
            "temp_hp": int(numbers.get("pb") or 0) if mantle.get("temp_hp") else 0,
            "opportunity_disadvantage_ft": int(mantle.get("opportunity_disadvantage_ft") or 0)}


@hook("damage_defenses")
def weatherproof_defense(engine: Any, target: Any, damage_type: str, typed: Any, source_actor_id: str | None) -> list[dict[str, Any]] | None:
    """Weatherproof Mantle's Wind Sign: "Resistance to nonmagical ranged weapon damage".

    The printed benefit is about the attack, not the damage type, so it cannot live in the Mantle's condition rule data:
    a blanket Resistance to every damage type a bow can deal would be broader than the printed words. The engine's shared
    defense seam is asked instead, and answers only for a ranged weapon attack that is not magical, on a creature wearing
    a Wind Mantle whose sign one of the owner's Weatherproof purchases covers. Inert without that row.
    """
    if not typed or damage_type is None:
        return None
    attacks = {str(row.get("attack_kind") or "") for row in typed.get("effects") or [] if row.get("type") == "attack"}
    if "weapon" not in attacks or not typed.get("mundane"):
        return None
    try:  # "ranged": the attack names a range beyond a weapon's reach rather than the reach it is made at
        if not typed.get("range_ft") or int(typed["range_ft"]) <= 5:
            return None
    except (TypeError, ValueError):
        return None
    if not _wind_is_weatherproofed(engine, target):
        return None
    return [{"kind": "resistance", "damage_types": [str(damage_type).upper()], "feature_id": WEATHERPROOF,
             "attack_kinds": ["weapon"]}]



@hook("defense_description")
def weatherproof_description(engine: Any, target: Any) -> list[dict[str, Any]] | None:
    """Wind's Weatherproof Resistance as the Defences card names it: the same gate the damage hook uses, with the
    printed qualifier, since the card has no attack to weigh.  Every damage type: weatherproof_defense resists whatever
    type such an attack deals."""
    if not _wind_is_weatherproofed(engine, target):
        return None
    return [{"feature_id": WEATHERPROOF, "damage_types": ["ALL"],
             "note": "only against nonmagical ranged weapon attacks"}]

def _wind_is_weatherproofed(engine: Any, target: Any) -> bool:
    """Whether the creature wears a Wind Mantle on the sign one of its owner's Weatherproof purchases covers."""
    for mantle in all_mantles(target):
        if sign_of(mantle) != "wind":
            continue
        owner = engine.state.actors.get(mantle.source_actor_id)
        if owner is not None and "wind" in _weatherproof_signs(engine, owner):
            return True
    return False


def _ask_weatherproof(ctx: Any, sign_id: str, options: list[str]) -> str | None:
    """Weatherproof Mantle's printed choice, asked of the one placing the Mantle."""
    name = ctx.action.display_name
    who = ctx.target.display_name if ctx.target is not None else ctx.actor.display_name
    asked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "WEATHERPROOF_TYPE", who), ctx.actor,
                CHOICE + "sky_mantle_weatherproof", options,
                labels={value: f"Weatherproof Mantle: {who} has Resistance to {value.lower()} damage" for value in options},
                target_id=ctx.target.entity_id if ctx.target is not None else None, name=name, feature_id=WEATHERPROOF,
                prompt=(f"{name}: Weatherproof Mantle makes the {weather_signs.sign(sign_id).get('name')} Mantle effect "
                        f"grant Resistance to lightning or thunder damage, chosen when the Mantle is placed. Choose the "
                        f"damage type {who} resists while that sign is active."))
    return str(asked[0]) if asked else None



# --------------------------------------------------------------------------------------------- the printed sign benefits

def _weather_source(ctx: Any) -> bool:
    """Whether the save now pending came from a Weather sphere ability."""
    typed = getattr(ctx, "typed", None) or {}
    return bool(typed.get("sphere") == weather_signs.SPHERE) or str(ctx.source or "").startswith(("WEATHER", "TAL_WEATHER"))


def _cause(ctx: Any) -> tuple[str, bool]:
    """The effect that caused the save now pending, as the two words ``weather_signs.source_kinds`` reads.

    ``ctx.source`` is the *rider's* own id when a named rider caused the save and the action's own id otherwise, so the
    action's display name is only read when the save is the action's own. That matters because a display name belongs to
    the parent action: a rider that carries no weather of its own must not inherit the weather of a parent called
    "Gather Storm" or "Blizzard Prayer", or an unrelated save would be read as that sign's printed hazard.
    """
    rider = str(getattr(ctx, "effect_source", "") or "")
    source = rider or str(getattr(ctx, "source", "") or "")
    ability = "" if rider else str(getattr(getattr(ctx, "action", None), "display_name", "") or "")
    return f"{source} {ability}", _weather_source(ctx)


def _log(engine: Any, source: str, actor_id: str, target_ids: tuple[str, ...], text: str) -> None:
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=actor_id, target_ids=target_ids, payload={"log": text})


@hook("save")
def defensive_weather(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Sky Mantle's Defensive Weather, plus each sign's own printed saves.

    Defensive Weather applies when the pending save is a Weather effect whose sign the Mantle's sign matches or
    opposes. A sign's own printed saves (Thunder's "against being Deafened, Stunned or knocked Prone by thunder,
    lightning or storm effects", Dry's poison and thirst, Heat's cold-weather saves) apply only against the hazard they
    name *and* from the source the printed line requires, which ``weather_signs.hazard_matches`` reads from the
    conditions and damage types typed_executor already named for the save and from the save's own source.
    """
    if subject is None:
        return None
    modes: list[str] = []
    save_sign = weather_signs.pending_sign(getattr(ctx, "typed", None))
    signs = weather_signs.signs_of_save(named or set()) | ({save_sign} if save_sign else set())
    weather = bool(save_sign) or _weather_source(ctx)
    cause, weather_source = _cause(ctx)
    kinds = weather_signs.source_kinds(cause, save_sign=save_sign, named=named, weather_source=weather_source)
    for mantle in all_mantles(subject):
        sign_id = sign_of(mantle)
        if not sign_id:
            continue
        if weather and weather_signs.matches_or_opposes(sign_id, signs):
            modes.append("ADVANTAGE")
        if weather_signs.hazard_matches((mantle.data or {}).get("save_advantage"), named,
                                        save_sign=save_sign, kinds=kinds):
            modes.append("ADVANTAGE")
    return {"bonus": 0, "modes": sorted(set(modes))} if modes else None


@hook("speed")
def wind_mantle_speed(engine: Any, actor: Any) -> Any:
    """Wind Sign's "Borne on Wind": +10 feet Speed (the printed realm step), while that sign is active."""
    from ..speed_contributions import SpeedContribution

    feet = 0
    for mantle in all_mantles(actor):
        signed = int((mantle.data or {}).get("speed_ft") or 0)
        if signed:
            feet += signed
    if not feet:
        return None
    return SpeedContribution([("weather_mantle.speed", "Sky Mantle (the printed Weather Sign Speed bonus)", feet)])


@hook("event")
def count_movement(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Voluntary feet moved this turn, for Wind Mantle's Opportunity Attack Disadvantage.

    Only a creature actually wearing a Wind Mantle that prints the printed 10 feet is counted, so no other creature's
    turn flags are touched. Plain bookkeeping: the distance comes from the engine's own MOVEMENT_COMMITTED event and
    is kept in a turn flag, which the engine resets at the start of that creature's next turn.
    """
    if event_type != "MOVEMENT_COMMITTED" or kwargs.get("forced"):
        return
    actor = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if actor is None or not any(int((m.data or {}).get("opportunity_disadvantage_ft") or 0) for m in all_mantles(actor)):
        return
    moved = int((kwargs.get("payload") or {}).get("cost_ft") or 0)
    if moved > 0:
        actor.turn_flags["weather_moved_ft"] = int(actor.turn_flags.get("weather_moved_ft") or 0) + moved


@hook("attack_mode")
def wind_mantle_opportunity(ctx: Any, target: Any) -> str | None:
    """Wind Mantle: attacks that provoke an Opportunity Attack have Disadvantage once the bearer moved 10 feet.

    "Opportunity attacks against the mantled creature have Disadvantage if the mantled creature moved at least
    10 feet during the current turn" -- the reaction economy identifies the Opportunity Attack, and the distance
    comes from the movement this module counts (count_movement).
    """
    economy = str(getattr(getattr(ctx, "action", None), "economy", "") or "")
    if economy not in {"REACTION", "Reaction", "reaction"}:
        return None
    mantle = next((m for m in all_mantles(target)
                   if int((m.data or {}).get("opportunity_disadvantage_ft") or 0) > 0), None)
    if mantle is None:
        return None
    needed = int((mantle.data or {}).get("opportunity_disadvantage_ft") or 10)
    return "DISADVANTAGE" if int(target.turn_flags.get("weather_moved_ft") or 0) >= needed else None


@hook("turn_start")
def heat_mantle_temporary_hp(engine: Any, actor: Any) -> None:
    """Heat Sign's "Flame Zephyr": your Proficiency Bonus in Temporary Hit Points at the start of each of its turns.

    ``_grant_temp_hp`` keeps the higher total, which is the printed "These temporary hit points do not stack".
    """
    for mantle in all_mantles(actor):
        granted = int((mantle.data or {}).get("temp_hp") or 0)
        if granted > 0:
            engine._grant_temp_hp(actor, granted, mantle.source_definition_id, mantle.source_actor_id)


@hook("escape_mode")
def rain_mantle_escape(engine: Any, escaper: Any, grips: Any) -> str | None:
    """Rain Sign's "Mist-Wrapped Body": Advantage on ability checks made to escape a Grapple."""
    return "ADVANTAGE" if any(int((m.data or {}).get("escape_advantage") or 0) for m in all_mantles(escaper)) else None


@hook("after_hit")
def weather_backlash(ctx: Any, target: Any, kind: str) -> None:
    """Weather Backlash: a melee hit on a mantled creature deals the Mantle owner's Proficiency Bonus, typed by the sign.

    "the attacker takes damage equal to *your* Proficiency Bonus ... This damage can trigger only once per round per
    mantled creature": the bonus is the Mantle owner's, not the attacker's, and the limit is remembered per owner and
    mantled creature for as long as the fight lasts, so two hits that straddle the mantled creature's own turn still
    trigger it once, and replacing its Mantle neither resets nor duplicates the limit.
    """
    from .thunder_charges import melee_attack

    if target is None or not melee_attack(ctx):
        return
    for mantle in all_mantles(target):
        owner = ctx.engine.state.actors.get(mantle.source_actor_id)
        if owner is None:
            continue
        row = weather_signs.sign(sign_of(mantle))
        if row is None:
            continue
        pb = int(owner.proficiency_bonus)
        if weather_signs.owns(ctx.engine, owner, "weather_backlash"):
            backlash = (row.get("backlash") or {})
            flag = _round_flag(owner, target)
            if int(target.turn_flags.get(flag) or 0) != ctx.engine.state.round_number:
                target.turn_flags[flag] = ctx.engine.state.round_number
                _burn(ctx, owner, target, mantle, row.get("name"), backlash, pb,
                      f"weather_backlash:{owner.entity_id}", "once per round per mantled creature", BACKLASH)
        own = (row.get("mantle") or {}).get("melee_backlash") or {}
        if own and not int((mantle.data or {}).get("backlash_used") or 0):
            mantle.data["backlash_used"] = 1
            record_instance_update(ctx.engine, target, "condition", mantle.instance_id, mantle)
            # Thunder's own printed Mantle burn, not the Weather Backlash talent and not Weatherproof: it is granted by
            # the Sky Mantle cast that placed the Mantle, so it is asked under that cast.
            _burn(ctx, owner, target, mantle, row.get("name"), own, pb,
                  f"weather_thunder_backlash:{mantle.instance_id}", "once during the Mantle",
                  str(mantle.source_definition_id or BASE))


def _round_flag(owner: Any, target: Any) -> str:
    """The retained per-round marker for this owner's Backlash against this mantled creature.

    The key holds "_round_", so the engine's turn-start sweep keeps it (it clears anything else) and the round number in
    it is what makes the limit once per round rather than once per turn.
    """
    return f"_round_weather_backlash:{owner.entity_id}:{target.entity_id}"


def _burn(ctx: Any, owner: Any, target: Any, mantle: Any, sign_name: Any, spec: dict[str, Any], pb: int,
          flag: str, limit: str, feature: str) -> None:
    """One printed Backlash burn: the Mantle owner's Proficiency Bonus, in the sign's damage type, with its rider.

    ``feature`` is the printed benefit the burn belongs to, asked of the one placing it. The Weather Backlash talent is
    one printed benefit and carries its own id; Thunder's own Mantle burn is a different printed line ("Once during the
    Mantle, when the mantled creature is hit by a melee attack, the attacker takes lightning or thunder damage equal to
    your Proficiency Bonus"), which the Sky Mantle cast grants and which needs no talent at all, so it is asked under
    the Mantle that granted it rather than under the optional Weatherproof talent that has nothing to do with it.
    """
    engine = ctx.engine
    kinds = [str(value) for value in spec.get("damage_types") or []]
    if not kinds:
        return
    ability = "Weather Backlash" if feature == BACKLASH else f"{sign_name} Mantle"
    if len(kinds) > 1:
        picked = ask(engine, ctx.intent, checkpoint_id(engine, flag.replace(":", "_").upper(), mantle.instance_id),
                     owner, CHOICE + "weather_backlash_type", kinds,
                     labels={value: f"{ability} deals {value} damage" for value in kinds},
                     target_id=ctx.actor.entity_id, name=ability, feature_id=feature,
                     prompt=(f"{ability}: {ctx.actor.display_name} hit {target.display_name}, who wears "
                             f"{owner.display_name}'s {sign_name} Mantle, with a melee attack, so the Mantle deals "
                             f"{pb} damage back to {ctx.actor.display_name}. Choose the damage type ({limit})."))
        if picked:
            kinds = [str(picked[0])]
    engine._commit_damage(ctx.actor, pb, kinds[0].upper(), mantle.source_definition_id, owner.entity_id, None,
                          reaction_depth=1)
    rider = spec.get("condition") or {}
    if rider.get("condition"):
        data = {"label": f"Doused by Weather Backlash ({sign_name})",
                "rider_text": weather_signs.marker_label(rider["condition"])}
        engine._apply_condition(ctx.actor, "condition:typed.weather_backlash_" + str(rider["condition"]),
                                mantle.source_definition_id, owner.entity_id,
                                expires_on=str(rider.get("duration") or weather_signs.TARGET_NEXT_START), data=data)
    _log(engine, mantle.source_definition_id, owner.entity_id, (ctx.actor.entity_id, target.entity_id),
         f"{ability}: {target.display_name}'s {sign_name} Mantle, placed by {owner.display_name}, deals {pb} "
         f"{kinds[0]} damage to {ctx.actor.display_name}, who hit {target.display_name} with a melee attack "
         f"({limit}). {spec.get('plain') or ''}")


@hook("turn_start")
def expire_mantles(engine: Any, actor: Any) -> None:
    """Sky Mantle's printed "up to 1 minute", for the ordinary and the Lingering cast alike.

    Concentration only ever ends a Mantle early; the minute is its own printed clock, so it is swept here. A Mantle
    saved before this clock existed carries no ``expiry_round`` and is left exactly as the old fight left it.
    """
    from .. import concentration

    now = (engine.state.round_number, engine.state.current_slot_index)
    for holder in engine.state.actors.values():
        for mantle in list(holder.conditions.values()):
            if mantle.condition_id != MANTLE or (mantle.data or {}).get("expiry_round") is None:
                continue
            if now < (int(mantle.data["expiry_round"]), int(mantle.data.get("expiry_slot") or 0)):
                continue
            owner = engine.state.actors.get(mantle.source_actor_id)
            started = (mantle.data or {}).get("concentration_started_sequence")
            if owner is not None and started is not None:
                held = owner.concentration
                if held is not None and held.started_sequence == started:
                    engine._end_concentration(owner, "DURATION_ENDED")
                else:
                    for key, one in concentration.held(owner):
                        if one.started_sequence == started:
                            concentration.end_held(engine, owner, key, "DURATION_ENDED")
                            break
            _remove(engine, holder, mantle, "DURATION_ENDED")
