"""Ways out that an effect gives the creature it holds (rider lane C12, 2026-09-30 -- shared system).

Printed holds often give the held creature (or a creature next to it) its own Action to end them: "A Restrained creature can use
its Action to repeat the saving throw" (Frozen Meridian Bind), "A creature may use an Action to make a Strength (Athletics)
check against your Cultivation Save DC, ending the Restrained condition on itself or one adjacent creature" (Heaven-Crushing
Shield Descent), "A restrained target may also use its Action to make a Strength or Charisma check" (Constellation Prison),
"until it successfully Studies the illusion. A creature Grappled this way may make a free Study check at the end of each of
its turns" (Substantial Phantasm; Studying an Illusion: an Intelligence (Investigation) check against your Cultivation Save DC).
The table could not give an action to a creature that does not own the ability; the ``additional_actions`` hook now can, so
this module turns such a line into data:

  {"type": "escape_option", "guards": ["restrained"],      put right after the hold's condition rows (same save branch); the
                                                            newest instance of each named condition from this user and ability
   "kind": "check" | "save",                               an ability check, or a repeat of the saving throw
   "abilities": ["STR", "CHA"], "skill": "Athletics",       the player chooses; AI prefers the better success chance
   "skills": {"STR": "Athletics", "DEX": "Acrobatics"},     a skill per ability ("a Strength (Athletics) or Dexterity
                                                            (Acrobatics) check": the Chains sphere's Escape Attempts; C15)
   "help": true,                                            a creature next to the held one may use its own Action instead
   "end_of_turn": true,                                     also a free attempt at the end of each of the held creature's turns
   "name": "Constellation Prison"}                          how the button and the log name the hold

The DC is the user's Cultivation Save DC (its compiled save_dc). The record is a small condition on the held creature
(``condition:typed.escape_option``: strings and integers only), so a saved fight keeps it. Buttons:
  "Break free"                       Action, the held creature; asks which hold when it has several
  "Help a creature next to you break free"   Action, aimed at an adjacent ally whose hold allows help (the table aims
                                     helping actions at allies; "a creature" in the print is normally the held one's ally)
Success ends exactly the guarded condition instances (and the record); failure spends the Action. The record goes by itself
when the hold ends some other way. The roll is the shared ability-check path (ability modifier, check bonuses, check modes,
check floors); skill proficiency is not added, as for every other escape check on this table. Nothing is offered to a creature
that holds no record, and no ability without an ``escape_option`` row is affected.

Impaling Garden's older single-ability escape (combat/ext/restraint_riders.py, "Escape source restraint", data inside its
Restrained) is left as it is so its saved fights replay unchanged; it could move onto this record later.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

OPTION = "condition:typed.escape_option"
SELF_ACTION = "system:combat.escape_option.self"
HELP_ACTION = "system:combat.escape_option.help"
SOURCE = "system:escape_option"
ASSIST = "condition:typed.escape_assistance"
_ABILITY = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution", "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}


def _condition_id(name: str) -> str:
    name = str(name).strip()
    return name if name.startswith("condition:") else f"condition:typed.{name.lower()}"


def options(actor: Any) -> list[tuple[str, Any]]:
    """The escape records a creature holds now, oldest first."""
    rows = [(key, c) for key, c in actor.conditions.items() if c.condition_id == OPTION and (c.data or {}).get("guards")]
    return sorted(rows, key=lambda pair: (int(pair[1].applied_sequence or 0), pair[0]))


def _live(actor: Any, record: Any) -> bool:
    return any(iid in actor.conditions for iid in (record.data or {}).get("guards") or [])


def _skill(data: dict[str, Any], ability: str) -> str:
    """The skill a check with ``ability`` uses for this hold: its own per-ability skill, else the one skill."""
    return str((data.get("skills") or {}).get(ability) or data.get("skill") or "")


def _describe(data: dict[str, Any], action_cost: str = "Action", include_extras: bool = True) -> str:
    if data.get("skills") and data.get("kind") != "save":
        named = " or ".join(f"{_ABILITY.get(a, a)}" + (f" ({_skill(data, a)})" if _skill(data, a) else "") for a in data.get("abilities") or [])
        how = f"make a {named} check against DC {data['dc']}"
    else:
        abilities = " or ".join(_ABILITY.get(a, a) for a in data.get("abilities") or [])
        skill = f" ({data['skill']})" if data.get("skill") else ""
        how = (f"repeat the {abilities} saving throw (DC {data['dc']})" if data.get("kind") == "save"
               else f"make a {abilities}{skill} check against DC {data['dc']}")
    article = "an" if action_cost[:1].lower() in "aeiou" else "a"
    text = f"{data.get('name') or 'This hold'}: use {article} {action_cost} to {how}; success ends it."
    if include_extras and data.get("help"):
        text += (" An adjacent ally may use Help (an Action) to give your next escape check Advantage."
                 if data.get("help_mode") == "advantage" else
                 " A creature next to you can try it for you with its own Action.")
    if include_extras and data.get("end_of_turn"):
        text += " You may also choose a free try at the end of each of your turns."
    return text


def attempt_description(data: dict[str, Any], action_cost: str = "Action") -> str:
    """Describe only the roll a caller is offering, at that caller's action cost."""
    return _describe(data, action_cost=action_cost, include_extras=False)


@effect("escape_option")
def escape_option(ctx: Any, row: dict[str, Any]) -> None:
    names = [str(name) for name in row.get("guards") or []]
    if not names:
        return
    subjects = [ctx.target] if ctx.target is not None else list(ctx.targets or [])
    for subject in subjects:
        if subject is None or not subject.active:
            continue
        guards = []
        for name in names:
            wanted = _condition_id(name)
            found = [(int(c.applied_sequence or 0), iid) for iid, c in subject.conditions.items()
                     if c.condition_id == wanted and c.source_definition_id == ctx.source and c.source_actor_id == ctx.actor.entity_id]
            if found:
                guards.append(max(found)[1])
        if not guards:
            continue  # it saved, or an immunity kept the hold off
        data = {"guards": sorted(guards), "kind": "save" if row.get("kind") == "save" else "check",
                "abilities": [str(a).upper() for a in row.get("abilities") or ["STR"]], "skill": str(row.get("skill") or ""),
                **({"skills": {str(a).upper(): str(k) for a, k in row["skills"].items()}} if row.get("skills") else {}),
                "dc": int(ctx.numbers.get("save_dc") or 10), "name": str(row.get("name") or ctx.action.display_name),
                "help": 1 if row.get("help") else 0, "end_of_turn": 1 if row.get("end_of_turn") else 0}
        if row.get("help_mode") == "advantage":
            data["help_mode"] = "advantage"
        if row.get("skill_proficiency"):
            data["skill_proficiency"] = 1
        data["label"] = _describe(data)
        ctx.engine._apply_condition(subject, OPTION, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data=data)


@hook("match_start")
def _install(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    common = {"economy": EconomyKind.ACTION, "resolution_kind": "TYPED", "owner_id": "*"}
    engine.action_catalog[SELF_ACTION] = ActionDefinition(
        source_definition_id=SELF_ACTION, display_name="Break free", target_kind="SELF", **common,
        parameters={"typed": {"effects": [{"type": "escape_option_attempt"}], "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "escape_option": "self",
                    "description": "Use your Action to try to end a hold on you, as the hold's own text allows (a check or a repeated save)."})
    engine.action_catalog[HELP_ACTION] = ActionDefinition(
        source_definition_id=HELP_ACTION, display_name="Help a creature next to you break free", target_kind="ALLY_OR_SELF", range_ft=5,
        **common, parameters={"typed": {"effects": [{"type": "escape_option_attempt"}], "numbers": {}, "duration": {"kind": "instant"},
                                        "riders": []},
                              "expected_damage": 0, "escape_option": "help",
                              "description": "Use your Action to try to free an ally next to you from a hold whose text lets another creature help."})


def _helpable(engine: Any, helper: Any, held: Any) -> bool:
    from .help_policy import allowed
    return allowed(engine, helper, held) and held is not helper and held.active and any((c.data or {}).get("help") and _live(held, c) for _k, c in options(held)) \
        and engine._distance_actor_to_actor(helper, held) <= 5


@hook("additional_actions")
def _offered(engine: Any, actor: Any) -> list[str]:
    if SELF_ACTION not in engine.action_catalog:
        return []
    out = []
    if any(_live(actor, c) for _k, c in options(actor)):
        out.append(SELF_ACTION)
    if any(_helpable(engine, actor, other) for other in engine.state.actors.values() if other is not actor):
        out.append(HELP_ACTION)
    return out


@hook("candidate_allowed")
def _allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    kind = (getattr(action, "parameters", None) or {}).get("escape_option")
    if kind == "self":
        return any(_live(actor, c) for _k, c in options(actor))
    if kind == "help":
        targets = [engine.state.actors.get(t) for t in getattr(candidate, "target_ids", None) or ()]
        return bool(targets) and all(t is not None and _helpable(engine, actor, t) for t in targets)
    return None


@hook("button_description")
def _button(action: dict[str, Any]) -> str | None:
    parameters = (action or {}).get("parameters") or {}
    return parameters.get("description") if parameters.get("escape_option") else None


def attempt(ctx: Any, roller: Any, held: Any, key: str, record: Any) -> bool:
    """One try: ``roller`` rolls (the held creature, or a helper for a check). Success ends the guarded holds and the record."""
    from copy import copy
    from ..typed_executor import rules, check_modes
    from ..ability_checks import ability_modifier, ordinary_check_bonus
    from .needle import ask, checkpoint_id
    from .condition_ownership import remove_instance
    from .escape_checks import escape_hook_modes, resolve_escape_check

    data = record.data or {}
    dc = int(data.get("dc") or 10)
    abilities = [a for a in data.get("abilities") or ["STR"] if a in _ABILITY] or ["STR"]
    engine = ctx.engine
    grips = [held.conditions[iid] for iid in data.get("guards") or [] if iid in held.conditions]
    hazards = {c.condition_id.removeprefix("condition:typed.") for c in grips}
    # Only the selected hold supplies hazard scope, including custom conditions
    # that carry the complete base Grappled/Restrained rule.
    for grip in grips:
        rule = (grip.data or {}).get("rule") or {}
        for name in ("grappled", "restrained"):
            base = rules()["conditions"][name]
            if all(rule.get(k) == v for k, v in base.items()):
                hazards.add(name)

    def preference(ability: str) -> float:
        if data.get("kind") == "save":
            return held.saving_throws.get(ability, 0)
        modes = check_modes(roller, ability, _skill(data, ability) or None,
                            engine=engine, hazards=tuple(sorted(hazards)))
        modes.update(escape_hook_modes(engine, roller, grips, ability, _skill(data, ability) or None))
        bonus = ability_modifier(roller, ability)
        if data.get("skill_proficiency"):
            bonus = ordinary_check_bonus(engine, roller, ability, _skill(data, ability),
                                         numbers={"ability_mods": {ability: bonus}})
        chance = min(20, max(0, 21 + bonus - dc)) / 20
        if modes == {"ADVANTAGE"}:
            return 1 - (1 - chance) ** 2
        if modes == {"DISADVANTAGE"}:
            return chance ** 2
        return chance

    ability = abilities[0]
    if len(abilities) > 1:
        ability = max(abilities, key=preference)
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "escape_ability", held.entity_id, key),
                     roller, "choice:needle.escape_ability", abilities,
                     preferred=[ability], labels={a: _ABILITY[a] for a in abilities},
                     prompt=f"{data.get('name') or 'This hold'} — {ctx.action.display_name} by {roller.display_name}: "
                            f"choose the ability for the {'saving throw' if data.get('kind') == 'save' else 'check'} "
                            f"to free {held.display_name} (DC {dc}). Success ends this hold; "
                            "no cultivation-point or Stamina cost.")
        ability = (picked or [ability])[0]
    if data.get("kind") == "save":
        # Recorded save holds use the same escape-specific modifiers as direct
        # escape saves. Scope those modifiers to the live instances guarded by
        # this record; keep the record's source and DC for roll provenance.
        from .escape_checks import resolve_escape_save
        live_grips = [held.conditions[iid] for iid in data.get("guards") or []
                      if iid in held.conditions]
        success = resolve_escape_save(engine, held, ability, dc,
                                      record.source_definition_id, live_grips)
    else:
        check_ctx = copy(ctx)
        check_ctx.actor = roller
        bonus = ability_modifier(roller, ability)
        if data.get("skill_proficiency"):
            bonus = ordinary_check_bonus(engine, roller, ability, _skill(data, ability),
                                         numbers={"ability_mods": {ability: bonus}})
        success = resolve_escape_check(
            check_ctx, {"bonus": bonus},
            dc, grips, tuple(sorted(hazards)), target_id=held.entity_id, source_id=record.source_definition_id,
            source_actor_id=record.source_actor_id, check_ability=ability, check_skill=_skill(data, ability) or None,
            check_name=f"{data.get('name') or 'Hold'}: {_ABILITY.get(ability, ability)}"
                       + (f" ({_skill(data, ability)})" if _skill(data, ability) else ""))
    for iid, assistance in list(held.conditions.items()):
        if assistance.condition_id == ASSIST and assistance.data.get("escape_record") == key:
            remove_instance(engine, held, iid, ctx.source)
    who = held.display_name if roller is held else f"{roller.display_name} helps {held.display_name}, who"
    if success:
        from .hold_escapes import escaped, how_for

        freed = [held.conditions[iid] for iid in data.get("guards") or [] if iid in held.conditions]
        for iid in data.get("guards") or []:
            if iid in held.conditions:
                remove_instance(engine, held, iid, ctx.source)
        if key in held.conditions:
            remove_instance(engine, held, key, ctx.source)
        note(engine, ctx.source, roller, f"{who} breaks free of {data.get('name') or 'the hold'}.", targets=[held])
        escaped(engine, held, freed, how_for(ability, held, roller), by=roller, source=ctx.source,
                way="save" if data.get("kind") == "save" else "check")
    else:
        note(engine, ctx.source, roller, f"{who} fails to break free of {data.get('name') or 'the hold'}.", targets=[held])
    return success


@effect("escape_option_attempt")
def escape_option_attempt(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id

    helping = (ctx.action.parameters or {}).get("escape_option") == "help"
    held = ctx.target if helping else ctx.actor
    if held is None:
        return
    choices = [(k, c) for k, c in options(held) if _live(held, c) and (not helping or (c.data or {}).get("help"))]
    if not choices:
        return
    if len(choices) > 1:
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "escape_option", held.entity_id), held if not helping else ctx.actor,
                     "choice:needle.escape_option", [k for k, _c in choices],
                     labels={k: str((c.data or {}).get("label") or (c.data or {}).get("name")) for k, c in choices},
                     prompt=f"{ctx.action.display_name} by {ctx.actor.display_name}: choose which hold on {held.display_name} to try to end.")
        choices = [(k, c) for k, c in choices if k in (picked or [])][:1] or choices[:1]
    key, record = choices[0]
    if helping and record.data.get("help_mode") == "advantage":
        # Help grants the held creature a check; it never rolls for them or ends the hold.
        label = (f"{held.display_name}: {record.data['name']} — Advantage on the next escape check "
                 f"before the start of {ctx.actor.display_name}’s next turn.")
        ctx.engine._apply_condition(held, ASSIST, ctx.source, ctx.actor.entity_id,
                                    expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"escape_record": key, "guards": list(record.data["guards"]), "label": label})
        note(ctx.engine, ctx.source, ctx.actor,
             label,
             targets=[held])
        return
    attempt(ctx, ctx.actor, held, key, record)


def _sweep(engine: Any, actor: Any) -> None:
    from .condition_ownership import remove_instance

    for key, record in options(actor):
        if not _live(actor, record):
            remove_instance(engine, actor, key, SOURCE)
    # Assistance depends on a live escape record, so prune dead records first.
    for iid, assistance in list(actor.conditions.items()):
        if assistance.condition_id == ASSIST and assistance.data.get("escape_record") not in actor.conditions:
            remove_instance(engine, actor, iid, SOURCE)


@hook("event")
def _event(engine: Any, event_type: str, kwargs: Any) -> None:
    if event_type not in ("CONDITION_REMOVED", "TURN_STARTED", "TURN_ENDED", "CONCENTRATION_ENDED"):
        return
    for actor in list(engine.state.actors.values()):
        if any(c.condition_id in (OPTION, ASSIST) for c in actor.conditions.values()):
            _sweep(engine, actor)


@hook("turn_end")
def _free_try(engine: Any, actor: Any) -> None:
    """Offer the printed optional free attempt; AI accepts through the choice transport."""
    from .. import typed_executor
    from .needle import ask, checkpoint_id

    for key, record in options(actor):
        if not (record.data or {}).get("end_of_turn") or not _live(actor, record) or key not in actor.conditions:
            continue
        action = engine.action_catalog.get(SELF_ACTION)
        if action is None:
            return
        ctx = typed_executor.Context(engine, actor, action, getattr(engine, "_active_intent", None), {"numbers": {}}, [actor], actor)
        name = (record.data or {}).get("name") or "This hold"
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "escape_free", actor.entity_id, key), actor,
                     "choice:needle.escape_free", ["study"], allow_decline=True,
                     labels={"study": f"Study {name}: try to end the hold on {actor.display_name}"},
                     prompt=f"{name} — end of {actor.display_name}'s turn: make the optional free Study check? "
                            "Success ends this hold. No Action, cultivation-point or Stamina cost.")
        if not picked:
            continue
        attempt(ctx, actor, actor, key, record)


@hook("status_description")
def _status(engine: Any, holder: Any, row: Any, data: Any) -> dict[str, Any] | None:
    if (row or {}).get("condition_id") != OPTION:
        return None
    text = str((data or {}).get("label") or "")
    return {"text": text, "handling": "Use the Break free button (an Action) to try it; it goes away when the hold ends."} if text else None


@hook("escape_mode")
def assistance_mode(engine: Any, roller: Any, grips: list[Any]) -> str | None:
    ids = {c.instance_id for c in grips}
    if any(c.condition_id == ASSIST and ids.intersection(c.data.get("guards") or [])
           and c.data.get("escape_record") in roller.conditions for c in roller.conditions.values()):
        return "ADVANTAGE"
    return None
