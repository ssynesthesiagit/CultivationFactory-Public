"""Shared effect-instance API for effect_transfer, halo_eater, end_effect and path_riders.

found lists source-qualified stored effects; source_action and condition_rule
inspect their represented provenance; remove_instance eventfully removes only
the selected instance. cultivation_dc and suppress also serve effect_transfer.

End (or suppress) an ongoing effect on a creature with a check against the effect's own save DC (lane 1 automation,
2026-09-29): Silence-Breaking Note ("Make a Music Check against the opposing effect's Cultivation Save DC. Success: End the
effect ... If no opposing DC exists, use DC 15.") and Wound Memory Suturing ("Make a Cultivation Check against the effect's
save DC. Success: The effect ends on the target. Failure: The effect is suppressed until the end of the target's next
turn.") -- both were GM lines because nothing let one creature take a hostile effect off another with a roll.

System G (sys/resources-states 2026-09-29) widened it to the other owner-text suppressions that name conditions or modifiers:
Reopen the Living Meridian ("Choose one ongoing effect that blocks, suppresses, scrambles, seals, or damages the target's
ability to spend CP, use a sphere talent, maintain Concentration, speak, breathe, or move normally. Make a Cultivation Check
against the effect's save DC. Success: The effect is suppressed for 1 minute. Failure: ... until the end of the target's next
turn."), the Heartbinder's Hold the Heart ("Suppress one ordinary charm ... until the end of your next turn. Against a
Restricted or equal-Source-CL effect, make a Cultivation Check.") and Internal Hammer ("Failed Save: Choose one ongoing
physical or martial effect affecting the target ... Suppress that effect until the end of the target's next turn").

Effect type "end_effect" (an ability's typed effect):
  {"type": "end_effect", "applies_to": "target",
   "conditions": ["silenced"],            # typed conditions it can end (condition:typed.<name>)
   "modifiers": ["healing_reduction"],    # modifier fields it can end (Wound Memory Suturing's "halves healing")
   "categories": ["cp", "speech"],        # named groups of the above (CATEGORIES below: Reopen's "spend CP ... speak, breathe, move")
   "select": "hostile" | "any" | "beneficial",   # whose effects: put there by the other side (default), by anyone, or its own side's
                                                 # helpful ones (Internal Hammer's stance/guard/body enhancement)
   "check": {"name": "Music Check", "default_dc": 15, "double_pb_from_cl": 15,
             "ordinary_below_cl": true},  # no check against an effect whose source's CL is below the user's (Hold the Heart's "ordinary")
                                          # -- leave "check" out and it works without a roll (Internal Hammer's failed save)
   "on_success": "end" | "suppress", "success_rounds": 10,     # "1 minute" is ten rounds
   "on_failure": "suppress" | "none", "failure_rounds": null,  # null: until the end of the holder's next turn
   "until": "holder" | "actor" | "actor_start",  # whose turn ends the suppression: the affected creature's (default) or the
                                          # user's -- "actor_start": until the START of the user's next turn (rider lane C11,
                                          # Formation-Piercing Point), restored by turn_start instead of turn_end
   "failure_advantage": {"against": ["turbulent"]}}   # a failed check gives the holder Advantage on saves against these conditions
                                                       # until the start of the user's next turn (Calm the Wild Meridian)
Categories ``speed`` and ``movement`` additionally select live positive
``condition.data.speed_penalty_group`` / ``speed_penalty_ft`` contributions via
``motion.grouped_speed_penalty``. Each source-qualified instance is a separate
choice, including weaker contributions in the same group. Suppressed or
Speed-floor-ignored contributions are not current reductions. The narrow speed
category retains held_fast/no_dash and speed_ft/speed_halved; movement retains
its broader movement locks. Source/team and declared eligibility filters still
apply, and removing one instance never removes the rest of its penalty group.
Optional ``provenance`` restricts removal to reviewed source speed rows whose
``provenance`` matches one of its tags. Missing or ambiguous source provenance
stays a GM rider, never automatic removal. ``choose_instance`` asks the acting
player to select one eligible instance (AI uses the ordinary automatic choice).
Candidates require a matching or unknown instance; explicitly nonmatching
provenance alone does not offer an action that cannot end anything.
``bodily_only`` restricts removal to the bearer's own temporary bodily or martial
state -- a stance, guard, body enhancement, rage-like state, mobility technique
or temporary damage reduction (Internal Hammer's printed list, read with its
rider's "does not suppress Domains, Secret Inheritances, permanent
transformations, artifacts, or effects that do not depend on the target's bodily
or spiritual structure"). It asks the shared reviewed reader in
``source_eligibility.py``: a protected printed category, a benefit with no
lifetime of its own, and an unattributable source are all never suppressed. A
source the table cannot read is a GM decision, exactly as ``provenance`` is.
These options are inert for existing rows that omit them; Meridian Stitch is the
first consumer of ``provenance``, and Internal Hammer the first of ``bodily_only``. No eligibility is
inferred from an ability name or flavour text.
Otherwise the effect chosen is the oldest of those kinds the target bears that the ``select`` allows; the DC is the save DC of the
technique that put it there (the compiled action's numbers), else the check's default_dc.  The check is d20 + Proficiency
Bonus + the key ability modifier (the same Cultivation Check the Contesting Light plug-in rolls), plus Proficiency Bonus twice
from ``double_pb_from_cl``.

Hook use: candidate_allowed -- an ability with an end_effect row is offered only against a creature that bears something it
can end (a Silence-Breaking Note with nothing silenced is not a choice); turn_end -- a suppressed effect comes back when the
turn that ends its suppression ends (the affected creature's own or the user's, or its Nth one for "1 minute"), if it has not
run out meanwhile.  A suppressed effect stays on the creature under a renamed condition / modifier field, so the engine goes on
ageing it and every rule that reads the real name ignores it meanwhile.  ``suppress`` (below) is what effect_transfer.py uses
for Bear It With Me's "if you are immune, the effect remains suppressed on the original creature".
Not modeled (GM riders): "permanent" curses / deviations / scattered foundations / crippled realms (nothing here is typed as
one, so nothing here can be picked), Restricted tags and higher authority tiers beyond the Source-CL comparison, and a target's
own save repeating (a condition that carries ``repeat_save`` keeps rolling it at its bearer's turn end, suppressed or not).
Determinism: only the engine's evented roller and events; state changes are one dict removal or a rename, both logged.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note, run as run_hooks

SUPPRESSED_FLAG = "typed_round_suppressed"  # "_round_" keys survive turn resets
SUPPRESSED = "suppressed:"
CONDITION_PREFIX = "condition:typed."

# Reopen the Living Meridian's "spend CP, use a sphere talent, maintain Concentration, speak, breathe, or move normally": the
# typed conditions (combat/rules/typed_conditions.json) and modifier fields that take one of those away.  "charm" is Hold the
# Heart's "charm ... obsession ... identity-confusion" (the table's mental-hold conditions).  A bodily hold (grappled, pinned)
# or a paralysis is not an "ongoing effect that seals movement" in the talent's sense, so movement lists only the effect-made ones.
CATEGORIES: dict[str, dict[str, tuple[str, ...]]] = {
    "cp": {"conditions": ("no_cp_regain", "hollowed"), "modifiers": ()},
    "talent": {"conditions": ("silenced", "speech_knot", "hollowed", "reaction_denied"), "modifiers": ()},
    "concentration": {"conditions": ("sickened", "bell_rung", "concentration_mode"), "modifiers": ()},
    "speech": {"conditions": ("silenced", "speech_knot", "choke_hold"), "modifiers": ()},
    "breath": {"conditions": ("smothered", "choke_hold"), "modifiers": ()},
    "speed": {"conditions": ("held_fast", "no_dash"), "modifiers": ("speed_halved", "speed_ft")},
    "movement": {"conditions": ("held_fast", "restrained", "pinning_volley", "no_dash", "cannot_teleport", "rest_hold"),
                 "modifiers": ("speed_halved", "speed_ft")},
    "charm": {"conditions": ("charmed", "captivated"), "modifiers": ()},
}
# What counts as a helpful effect on its own bearer (Internal Hammer's stance, guard, body enhancement, mobility technique or
# temporary damage reduction; Steal Ongoing Technique's "beneficial"). Conditions
# require a positive mechanic or an explicit effect_kind in typed_conditions.json
# (also allowed in an instance's rule). An empty/unknown rule is not a benefit.
# effect_kind: defense / benefit / structural; structural relationships are never
# selectable buffs. defensive_only narrows a beneficial end_effect to defenses
# and typed stances, leaving offensive/mobility buffs alone.
BENEFIT_FIELDS = ("armor_class", "armor_class_vs_melee", "armor_class_vs_ranged", "damage_resistance", "damage_resistance_next", "damage_immunity", "speed_ft")
DEFENSE_FIELDS = tuple(field for field in BENEFIT_FIELDS if field != "speed_ft")
_BOOKKEEPING = ("mark.", "suppressed.", "concentration_held")
_TAKES_AWAY = ("speed_zero", "no_actions", "no_reactions", "no_cp_regain", "save_mode", "cant_hear", "no_dash", "no_teleport")

# The reviewed eligibility filters an end_effect row can declare. Each answers True (this instance may be
# ended), False (it may not) or None (the table cannot tell, so the caller keeps it a GM decision).
_FILTERS = ("provenance", "bodily_only")
_FILTER_KEYS = frozenset(_FILTERS)
_ELIGIBILITY_QUESTIONS = {
    "provenance": "comes from a wound, tendon injury, pressure disruption, or meridian constriction",
    "bodily_only": ("is an ongoing physical or martial effect of that creature's own body, such as a stance, guard, "
                    "body enhancement, rage-like state, mobility technique, or temporary damage reduction"),
}
def condition_rule(item: Any, name: str) -> dict[str, Any]:
    from ..typed_executor import rules  # the owner-editable rules file, re-read when it changes

    declared = rules()["conditions"].get(name) or {}
    own = (item.data or {}).get("rule")
    combined = {**declared, **(own if isinstance(own, dict) else {})}
    # A rider's extra benefit cannot turn its structural bond into a buff.
    if declared.get("effect_kind") == "structural":
        combined["effect_kind"] = "structural"
    return combined


def helpful(item: Any, kind: str, *, defensive_only: bool = False) -> bool:
    """Is this condition / modifier of benefit to whoever bears it (the stance, guard, buff and ward kinds, not a mark or a drawback)."""
    if kind == "condition":
        from ..typed_executor import is_active_typed_condition

        if not is_active_typed_condition(item):
            return False
        name = str(item.condition_id)
        if not name.startswith(CONDITION_PREFIX):
            return False
        name = name[len(CONDITION_PREFIX):]
        if name.startswith(_BOOKKEEPING) or name == "concentration_held":
            return False
        rule = _condition_rule(item, name)
        classification = rule.get("effect_kind")
        if classification == "structural":
            return False
        defense = classification == "defense" or name.startswith("stance.") or any(
            rule.get(key) for key in ("resistance", "damage_reduction", "ac_bonus", "cover", "stance", "condition_immunities")) \
            or rule.get("attacked_with") == "DISADVANTAGE" \
            or "ADVANTAGE" in (rule.get("save_mode") or {}).values() \
            or (rule.get("save_against") or {}).get("mode") == "ADVANTAGE"
        if defensive_only:
            return defense
        if defense or classification == "benefit":
            return True
        return (rule.get("attacks_have") == "ADVANTAGE" or bool(rule.get("ignore_difficult"))
                or "ADVANTAGE" in (rule.get("check_mode") or {}).values()
                or (rule.get("check_against") or {}).get("mode") == "ADVANTAGE") \
            and not any(rule.get(key) for key in _TAKES_AWAY if key != "save_mode")
    field = str(item.target_field)
    if field not in BENEFIT_FIELDS:
        return False
    if defensive_only and field not in DEFENSE_FIELDS:
        return False
    return not (isinstance(item.value, int) and item.value <= 0) if field in ("armor_class", "armor_class_vs_melee", "armor_class_vs_ranged", "speed_ft") else True


def _sources_ok(engine: Any, holder: Any, item: Any, select: str) -> bool:
    source = engine.state.actors.get(str(getattr(item, "source_actor_id", "") or ""))
    if select == "any":
        return True
    if select == "beneficial":
        return source is not None and source.team_id == holder.team_id
    return source is not None and source.team_id != holder.team_id


def _hostile(engine: Any, holder: Any, item: Any) -> bool:
    source = engine.state.actors.get(str(getattr(item, "source_actor_id", "") or ""))
    return source is not None and source.team_id != holder.team_id


def _kinds(eff: dict[str, Any]) -> tuple[set[str], set[str]]:
    conditions = {str(name).lower() for name in eff.get("conditions") or []}
    fields = {str(name) for name in eff.get("modifiers") or []}
    for name in eff.get("categories") or []:
        group = CATEGORIES.get(str(name)) or {}
        conditions |= set(group.get("conditions") or ())
        fields |= set(group.get("modifiers") or ())
    return {f"{CONDITION_PREFIX}{name}" for name in conditions}, fields


def found(engine: Any, holder: Any, eff: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """(kind, key, item) for each effect of the kinds ``eff`` names that ``select`` allows on ``holder``."""
    from ..motion import grouped_speed_penalty

    conditions, fields = _kinds(eff)
    # Semantic categories include numeric condition data, not ability IDs. The
    # speed category is shared with Meridian's menu and removal row; movement
    # also reaches these reductions. Keep all ordinary source/filter checks.
    grouped_speed = bool({"speed", "movement"}.intersection(eff.get("categories") or []))
    select = str(eff.get("select") or "hostile")
    every = select == "beneficial" and not conditions and not fields
    out = []
    for key, condition in holder.conditions.items():
        grouped_match = grouped_speed and grouped_speed_penalty(engine, holder, condition) > 0
        if (every or condition.condition_id in conditions or grouped_match) and _sources_ok(engine, holder, condition, select) \
                and (select != "beneficial" or helpful(condition, "condition", defensive_only=bool(eff.get("defensive_only")))):
            out.append(("condition", key, condition))
    for key, modifier in holder.modifiers.items():
        if (every or modifier.target_field in fields) and _sources_ok(engine, holder, modifier, select) \
                and (select != "beneficial" or helpful(modifier, "modifier", defensive_only=bool(eff.get("defensive_only")))) \
                and not (modifier.target_field == "speed_ft" and select != "beneficial" and isinstance(modifier.value, int) and modifier.value >= 0):
            out.append(("modifier", key, modifier))
    if not _FILTER_KEYS.isdisjoint(eff):
        out = [row for row in out if eligibility(engine, row[2], eff) is True]
    if eff.get("magical_only"):
        from .area_suppression import effect_mundane

        out = [row for row in out if effect_mundane(engine, row[2].source_definition_id,
                                                   row[2].source_actor_id) is False]
    return out


def source_provenance(engine: Any, item: Any) -> str | None:
    """Reviewed provenance of an unambiguous compiled speed effect, else unknown.

    The instance retains its compiled action id through persistence. Inspect only
    that action's executed effects, not other options or the whole talent text.
    Multiple speed rows with differing/missing tags cannot establish provenance.
    """
    action = engine.action_catalog.get(item.source_definition_id)
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    tags = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "speed":
                tags.append(value.get("provenance"))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(typed.get("effects") or [])
    return str(tags[0]) if tags and tags[0] and all(tag == tags[0] for tag in tags) else None


# The reviewed eligibility filters an end_effect row can declare. Each answers True (this instance may be
# ended), False (it may not) or None (the table cannot tell, so the caller keeps it a GM decision).
def _eligibility_question(eff: dict[str, Any]) -> str:
    """What the GM is being asked, in the printed words of the filters the row declares."""
    asked = [_ELIGIBILITY_QUESTIONS[key] for key in _FILTERS if eff.get(key)]
    return " and ".join(asked) if asked else "is one of the effects this ability may touch"


def eligibility(engine: Any, item: Any, eff: dict[str, Any]) -> bool | None:
    """What the row's own eligibility filters say about one stored instance, or None when undecided.

    Every declared filter must accept the instance; the first that cannot decide leaves the answer None, so
    an unknown source is never silently treated as eligible (Meridian Stitch's wound/tendon/pressure/
    meridian tags, and Internal Hammer's ``bodily_only``).
    """
    if eff.get("provenance"):
        provenance = source_provenance(engine, item)
        if provenance is None:
            return None
        if provenance not in eff["provenance"]:
            return False
    if eff.get("bodily_only"):
        from .source_eligibility import bodily_effect

        return bodily_effect(engine, item)
    return True


def _undecided(engine: Any, holder: Any, eff: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """Instances the row's eligibility filters cannot classify: known-good apart, left to the GM."""
    if _FILTER_KEYS.isdisjoint(eff):
        return []
    loose = {key: value for key, value in eff.items() if key not in _FILTER_KEYS}
    return [row for row in found(engine, holder, loose) if eligibility(engine, row[2], eff) is None]


def source_action(ctx: Any, item: Any) -> Any:
    return ctx.engine.action_catalog.get(str(getattr(item, "source_definition_id", "") or ""))


def cultivation_dc(engine: Any, creature: Any) -> int:
    """A creature's Cultivation Save DC: the best save DC among its own compiled techniques, else 8 + Proficiency Bonus."""
    best = 0
    for action in engine.action_catalog.values():
        if action.owner_id == creature.entity_id:
            best = max(best, int((((action.parameters or {}).get("typed") or {}).get("numbers") or {}).get("save_dc") or 0))
    return best or 8 + int(creature.proficiency_bonus)


def _dc(ctx: Any, item: Any, check: dict[str, Any]) -> int:
    """The effect's save DC: its technique's own; else the check's printed fallback (Silence-Breaking Note's 15); else the
    Cultivation Save DC of whoever put it there."""
    action = _source_action(ctx, item)
    numbers = (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("numbers") or {}) if action is not None else {}
    if numbers.get("save_dc") or check.get("default_dc"):
        return int(numbers.get("save_dc") or check["default_dc"])
    source = ctx.engine.state.actors.get(str(getattr(item, "source_actor_id", "") or ""))
    return cultivation_dc(ctx.engine, source) if source is not None else 15


def known_source_cl(ctx: Any, item: Any) -> int | None:
    """Retained Source CL, else immutable compiled source authority; unknown stays unknown.

    Shared by explicit authority-gated cleansing effects. Unlike a current actor
    bundle, these sources identify the effect that was actually applied.
    """
    value = (getattr(item, 'data', None) or {}).get('source_cl')
    if type(value) is int and value >= 1:
        return value
    action = source_action(ctx, item)
    numbers = (((getattr(action, 'parameters', None) or {}).get('typed') or {}).get('numbers') or {})
    value = numbers.get('cl')
    if type(value) is int and value >= 1:
        return value
    # Some older plug-ins store the mechanic/source name rather than the catalog
    # action id (Hunger's Elemental Gut resistance names the Mantle). Resolve that
    # name only when every action carrying it agrees on one Source CL.
    engine = getattr(ctx, 'engine', ctx)
    source_id = str(getattr(item, 'source_definition_id', '') or '')
    found = {(typed.get('numbers') or {}).get('cl')
             for candidate in (getattr(engine, 'action_catalog', None) or {}).values()
             for typed in [((getattr(candidate, 'parameters', None) or {}).get('typed') or {})]
             if source_id and source_id in (typed.get('source'), typed.get('option_of'))
             and type((typed.get('numbers') or {}).get('cl')) is int
             and (typed['numbers']['cl'] or 0) >= 1}
    return found.pop() if len(found) == 1 else None


def source_cl(ctx: Any, item: Any) -> int:
    """The Cultivation Level behind an effect: its technique's own (compiled numbers), else its caster's."""
    action = _source_action(ctx, item)
    numbers = (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("numbers") or {}) if action is not None else {}
    if numbers.get("cl"):
        return int(numbers["cl"])
    bundle = next((row for row in getattr(ctx.engine, "typed_bundle_documents", ()) or ()
                   if row.get("actor_id") == str(getattr(item, "source_actor_id", "") or "")), None)
    return int((bundle or {}).get("cl") or 1)


def remove_instance(ctx: Any, holder: Any, kind: str, key: str, item: Any) -> None:
    if kind == "condition":
        ctx.engine._remove_condition_instance(holder, key, ctx.source, actor_id=ctx.actor.entity_id,
            payload={"condition_id": item.condition_id, "instance_id": key, "reason": "ENDED"}, expected=item)
    else:
        ctx.engine._remove_modifier_instance(holder, key, ctx.source, actor_id=ctx.actor.entity_id,
            payload={"modifier_id": key, "reason": "ENDED"}, expected=item)


# Shared effect-instance API for effect_transfer, halo_eater, end_effect and path_riders. These are the
# public names: found (the instances an effect can end), name (a stored benefit's player-facing label),
# condition_rule, source_action, remove_instance, suppress, restore_suppressed. effect_transfer imports
# found and name directly, so no private spelling of them is kept.
_condition_rule = condition_rule
_source_action = source_action
_remove = remove_instance


def _record_instance(engine: Any, holder: Any, kind: str, key: str, item: Any) -> None:
    """Upsert the retained instance without delivering fresh-application hooks.

    Suppression and restoration keep its identity, source, data and expiry; a
    log alone cannot reproduce a changed condition id or modifier field. The
    documented retained update marker keeps application subscribers inert.
    """
    from .retained_updates import record_instance_update

    record_instance_update(engine, holder, kind, key, item)


def suppress(holder: Any, kind: str, key: str, item: Any, *, rounds: int = 1, by: Any = None, engine: Any = None,
             boundary: str = "end", at: str | None = None) -> None:
    """Suppress until the end of ``by``'s Nth next turn (default: holder).

    Pass ``engine`` to event both the rename and its eventual restoration using
    existing applied-instance events. Historical callers omit it unchanged;
    Halo Eater uses the evented path for conditions and modifiers. Relative
    expiry remains on the original object and keeps aging while hidden.
    ``boundary`` is end (legacy default), start, or scene (no timed return).
    Scene callers restore selected rows through ``restore_suppressed``; original
    instance expiry still applies. These options serve Halo Eater and other
    source rules that specify a different suppression boundary.
    """
    # C11 retained records use at; C8 uses boundary. Both describe one clock.
    if at is not None:
        boundary = at
    if boundary not in ("end", "start", "scene"):
        raise ValueError(f"Unsupported suppression boundary: {boundary}")
    if kind == "condition":
        original, item.condition_id = item.condition_id, item.condition_id.replace(CONDITION_PREFIX, f"{CONDITION_PREFIX}suppressed.", 1)
    else:
        original, item.target_field = item.target_field, SUPPRESSED + item.target_field
    ender = by or holder
    rows = list(holder.turn_flags.get(SUPPRESSED_FLAG) or [])
    rows.append({"kind": kind, "key": key, "original": original, "turn": int(ender.turns_started) + max(1, int(rounds)), "by": ender.entity_id,
                 **({"boundary": boundary} if boundary != "end" else {}),
                 **({"evented": 1} if engine is not None else {})})
    holder.turn_flags[SUPPRESSED_FLAG] = rows
    if engine is not None:
        record_instance(engine, holder, kind, item)


def record_instance(engine: Any, holder: Any, kind: str, item: Any) -> None:
    """Record a retained rename for Halo Eater and timed suppression restoration.

    The shared retained-update marker keeps fresh-application subscribers inert.
    """
    key = item.instance_id if kind == "condition" else item.modifier_id
    _record_instance(engine, holder, kind, key, item)


def name(item: Any, kind: str) -> str:
    raw = str(item.condition_id if kind == "condition" else item.target_field)
    return raw.replace(CONDITION_PREFIX, "").replace("_", " ")


def describe(engine: Any, kind: str, item: Any) -> str:
    """One stored benefit in player language, for any plug-in that reports what a creature really bears.

    Public seam for readers of ``found`` (Eight-Gate Diagnosis's "is it maintaining an ongoing bodily or martial
    enhancement?"); it resolves the effect's own compiled technique so a state marker reports its real benefit
    instead of an internal name.
    """
    return _effect_description(item, kind, engine.action_catalog.get(str(getattr(item, "source_definition_id", "") or "")))


def _effect_description(item: Any, kind: str, source: Any = None) -> str:
    """Describe a stored benefit in player language for choose_instance menus."""
    if kind == "modifier":
        field = str(item.target_field).replace("_", " ")
        value = item.value
        if field.startswith("damage resistance"):
            return f"resistance to {str(value).replace('_', ' ')} damage"
        if field.startswith("armor class"):
            return f"{field.title()} {value:+}"
        if field == "speed ft":
            return f"Speed {value:+} feet"
        return f"{field.title()}: {value}"

    if (item.data or {}).get("speed_penalty_group"):
        return f"Speed reduced by {item.data['speed_penalty_ft']} feet"
    raw_name = str(item.condition_id).removeprefix(CONDITION_PREFIX)
    name = raw_name.replace("_", " ").replace(".", " ")
    rule = condition_rule(item, raw_name)
    ability_names = {"str": "Strength", "dex": "Dexterity", "con": "Constitution",
                     "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}
    target_names = {"forced_movement": "forced movement", "prone": "being knocked Prone",
                    "grappled": "being Grappled"}
    save_against = rule.get("save_against") or {}
    check_against = rule.get("check_against") or {}
    advantage = []
    for against, value in ((save_against, "saving throws"), (check_against, "ability checks")):
        if str(against.get("mode") or "").upper() == "ADVANTAGE":
            targets = against.get("against") or []
            if targets:
                target = ", ".join(target_names.get(str(entry), str(entry).replace("_", " ")) for entry in targets)
                advantage.append(f"Advantage on {value} against {target}")
            else:
                advantage.append(f"Advantage on {value}")
    for key, label in (("save_mode", "saving throws"), ("check_mode", "ability checks")):
        modes = rule.get(key) or {}
        if isinstance(modes, dict):
            for ability, mode in modes.items():
                if str(mode).upper() == "ADVANTAGE":
                    ability_name = ability_names.get(str(ability).lower(), str(ability).title())
                    advantage.append(f"Advantage on {ability_name} {label}")
    if advantage:
        return "; ".join(advantage)
    if raw_name.startswith("state.") and source is not None:
        # State markers can stand alongside the actual numeric benefits of the
        # same typed effect. Describe those sibling rows instead of exposing the
        # internal state marker as if it were the benefit.
        typed = ((source.parameters or {}).get("typed") or {})
        for wrapper in typed.get("effects") or []:
            if not isinstance(wrapper, dict) or wrapper.get("type") != "singleton_benefit":
                continue
            siblings = wrapper.get("effects") or []
            state_names = {str(row.get("name") or "") for row in siblings
                           if isinstance(row, dict) and row.get("type") == "state"}
            if raw_name.removeprefix("state.") not in state_names:
                continue
            descriptions = []
            for row in siblings:
                if not isinstance(row, dict) or row.get("type") in ("state", "gravity_mode_change"):
                    continue
                if row.get("type") == "advantage" and row.get("on"):
                    descriptions.append("Advantage when " + str(row["on"]))
                elif row.get("type") == "speed":
                    amount = int(row.get("flat") or 0)
                    if amount:
                        descriptions.append(f"Speed {'increases' if amount > 0 else 'decreases'} by {abs(amount)} feet")
                elif row.get("evidence"):
                    descriptions.append(str(row["evidence"]))
            if descriptions:
                return "; ".join(descriptions)
    # The source technique plus a plain condition name is still meaningful when
    # the rules store a named state without a numeric mechanic.
    return name.removeprefix("state ").title() + " state"


def _choice_outcome(ctx: Any, holder: Any, eff: dict[str, Any]) -> str:
    def suppression_duration(rounds_value: Any) -> str:
        rounds, by, _ = _when(eff, ctx, holder, rounds_value)
        if rounds == 1:
            return f"until the end of {by.display_name}'s next turn"
        if rounds >= 10:
            return "for 1 minute"
        return f"for {rounds} rounds"

    success = (f"suppressed {suppression_duration(eff.get('success_rounds'))}"
               if eff.get("on_success", "end") == "suppress" else "ended")
    if eff.get("check") is None:
        return success

    outcome = f"if the check succeeds, it is {success}"
    if eff.get("on_failure") == "suppress":
        outcome += f"; if it fails, it is suppressed {suppression_duration(eff.get('failure_rounds'))}"
    else:
        outcome += "; if it fails, it stays active"
    return outcome


def _check(ctx: Any, holder: Any, item: Any, check: dict[str, Any]) -> bool:
    if check.get("ordinary_below_cl") and source_cl(ctx, item) < int(ctx.numbers.get("cl") or 0):
        return True  # an ordinary effect of a lower source needs no roll
    dc = _dc(ctx, item, check)
    modifier = int(ctx.numbers.get("pb") or 2) + int(ctx.numbers.get("key_mod") or 0) + sum(run_hooks("check_bonus", ctx, ctx.actor))
    if check.get("double_pb_from_cl") and int(ctx.numbers.get("cl") or 0) >= int(check["double_pb_from_cl"]):
        modifier += 2 * int(ctx.numbers.get("pb") or 2)
    from ..support_values import condition_purpose_from, offered_bonus, settled
    purpose = condition_purpose_from(ctx.engine, ctx.actor, holder, ctx.source, item)
    original = modifier
    if purpose is not None:
        modifier += offered_bonus(ctx.engine, ctx.actor, holder, ctx.source, purpose, modifier, consume=True)
    roll = ctx.engine.roll_check(modifier=modifier, actor_id=ctx.actor.entity_id, reason=f'CHECK:{ctx.source}')
    ctx.engine._record_roll(roll)
    success = roll.total >= dc
    ctx.engine._append_event("CHECK_ROLLED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(holder.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success,
                                      "skill": check.get("name") or "Cultivation Check"})
    if purpose is not None:
        settled(ctx.engine, ctx.actor, holder, ctx.source, purpose, original, modifier, int(roll.total))
    return success


def _when(eff: dict[str, Any], ctx: Any, holder: Any, rounds: Any) -> tuple[int, Any, str]:
    """(rounds, whose turn, wording) for a suppression: until the end of the holder's next turn unless ``rounds`` or ``until`` say more."""
    by = ctx.actor if eff.get("until") in ("actor", "actor_start") else holder
    count = int(rounds or 1)
    if eff.get("until") == "actor_start" and count == 1:
        return count, by, f"until the start of {by.display_name}'s next turn"
    wording = "for 1 minute" if count >= 10 else f"until the end of {'its' if by is holder else by.display_name + chr(39) + 's'} next turn" if count == 1 \
        else f"for {count} rounds"
    return count, by, wording


@effect("end_effect")
def end_effect(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    check = eff.get("check")
    for holder in typed_executor._default_subject(ctx, eff, harmful=False):
        if holder is None or not holder.active:
            continue
        eligible = found(ctx.engine, holder, eff)
        for kind, _, unknown in _undecided(ctx.engine, holder, eff):
            ctx.rider(f"{ctx.action.display_name}: GM decides whether {holder.display_name}'s {name(unknown, kind)} "
                      f"{_eligibility_question(eff)}; it remains in place.")
        if not eligible:
            # A row that declares an eligibility filter explains itself: the player is told what it needed,
            # so "there is no such effect" is never read as "this creature bears nothing".
            undecided = _undecided(ctx.engine, holder, eff)
            ctx.rider("No effect was changed automatically; the GM must identify an eligible effect." if undecided
                      else "There is no such effect on the target that an opposing creature put there." if not eff.get("select") or eff.get("select") == "hostile"
                      else f"There is no effect on {holder.display_name} that {ctx.action.display_name} can touch:"
                      f" it needs one that {_eligibility_question(eff)}." if not undecided and _FILTER_KEYS.intersection(eff)
                      else "There is no such effect on the target.")
            continue
        kind, key, item = eligible[0]
        if eff.get("choose_instance"):
            from .needle import CHOICE, ask, checkpoint_id

            labels = {}
            outcome = _choice_outcome(ctx, holder, eff)
            descriptions = {}
            for found_kind, found_key, found_item in eligible:
                source = ctx.engine.action_catalog.get(found_item.source_definition_id)
                owner = ctx.engine.state.actors.get(found_item.source_actor_id)
                descriptions[found_key] = (f"{getattr(source, 'display_name', name(found_item, found_kind))} from "
                                           f"{getattr(owner, 'display_name', 'unknown source')}: "
                                           f"{_effect_description(found_item, found_kind, source)}; {outcome}")
            totals = {label: sum(candidate == label for candidate in descriptions.values())
                      for label in descriptions.values()}
            seen = {}
            for found_kind, found_key, _ in eligible:
                label = descriptions[found_key]
                if totals[label] > 1:
                    seen[label] = seen.get(label, 0) + 1
                    label += f" (copy {seen[descriptions[found_key]]} of {totals[descriptions[found_key]]})"
                labels[found_key] = label
            selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "end_effect", holder.entity_id),
                           ctx.actor, CHOICE + "end_effect", list(labels), labels=labels,
                           target_id=holder.entity_id, name=ctx.action.display_name,
                           prompt=f"{ctx.action.display_name}: choose one eligible effect on {holder.display_name}. "
                                  f"The choice will be {outcome}.")
            if not selected:
                continue
            kind, key, item = next(row for row in eligible if row[1] == selected[0])
        label = name(item, kind)
        success = _check(ctx, holder, item, check) if check is not None else True
        if success and eff.get("on_success", "end") != "suppress":
            _remove(ctx, holder, kind, key, item)
            note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} ends {holder.display_name}'s {label}.", (holder,))
        elif success or eff.get("on_failure") == "suppress":
            rounds, by, wording = _when(eff, ctx, holder, eff.get("success_rounds") if success else eff.get("failure_rounds"))
            suppress(holder, kind, key, item, engine=ctx.engine, rounds=rounds, by=by,
                     at="start" if eff.get("until") == "actor_start" else "end")
            note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} suppresses {holder.display_name}'s {label} {wording}.", (holder,))
        else:
            note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name}'s check fails to move {holder.display_name}'s {label}.", (holder,))
        if not success and eff.get("failure_advantage"):
            _steady(ctx, holder, label, eff["failure_advantage"])


def _steady(ctx: Any, holder: Any, name: str, rule: dict[str, Any]) -> None:
    """Calm the Wild Meridian's "Failed Check: The instability remains, but creatures of your choice inside the affected area have
    Advantage on saving throws against it until the start of your next turn": the holder gets Advantage on saves against what the
    named conditions impose (combat/ext/save_against.py reads it)."""
    against = [str(value).lower() for value in rule.get("against") or []]
    ctx.engine._apply_condition(holder, "condition:typed.save_against", ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"rule": {"save_against": {"mode": "ADVANTAGE", "against": against, "abilities": [], "next": False}},
                                      "label": f"Advantage on saving throws against {', '.join(against) or name} until the start of {ctx.actor.display_name}'s next turn"})
    note(ctx.engine, ctx.source, ctx.actor, f"{holder.display_name} has Advantage on saving throws against {name} until the start of "
         f"{ctx.actor.display_name}'s next turn.", (holder,))


@hook("candidate_allowed")
def offered_only_against_something_to_end(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    rows = [row for row in _end_rows(typed.get("effects") or [])] + [row for option in typed.get("options") or []
                                                                      for row in _end_rows(option.get("effects") or [])]
    if not rows:
        return None
    holders = [engine.state.actors[t] for t in candidate.target_ids or () if t in engine.state.actors] or [actor]
    for holder in holders:
        for row in rows:
            instances = found(engine, holder, {k: v for k, v in row.items() if k not in _FILTER_KEYS})
            # An unclassifiable instance remains reachable as a GM decision; known
            # ineligible ones cannot justify spending an Action.
            if any(eligibility(engine, item, row) is not False for _, _, item in instances):
                return None
    return False


def _end_rows(effects: list[Any]) -> list[dict[str, Any]]:
    return [row for row in effects if isinstance(row, dict) and row.get("type") == "end_effect"]


def restore_suppressed(engine: Any, holder: Any, row: dict[str, Any]) -> None:
    """Restore one selected live suppression row and retire its clock.

    Halo Eater's three-success restoration and this module's timed hooks share
    this evented path. Missing/expired instances are retired, never recreated.
    """
    item = (holder.conditions if row["kind"] == "condition" else holder.modifiers).get(row["key"])
    holder.turn_flags[SUPPRESSED_FLAG] = [r for r in holder.turn_flags.get(SUPPRESSED_FLAG, []) if r != row]
    if item is None:
        return
    if row["kind"] == "condition":
        item.condition_id = row["original"]
    else:
        item.target_field = row["original"]
    record_instance(engine, holder, row["kind"], item)


def _return_at(engine: Any, actor: Any, boundary: str, *, nominal: bool = False) -> None:
    from .effect_durations import custom_turn_due
    for holder in list(engine.state.actors.values()):
        rows = list(holder.turn_flags.get(SUPPRESSED_FLAG) or [])
        if not rows:
            continue
        for row in rows:
            ender = row.get("by") or holder.entity_id
            if (row.get("boundary", row.get("at", "end")) != boundary or ender != actor.entity_id
                    or not custom_turn_due(actor, row["turn"], holder.turn_flags, "suppression:" + row["key"], nominal=nominal)):
                continue
            restore_suppressed(engine, holder, row)


@hook("turn_end")
def suppressed_effects_return(engine: Any, actor: Any) -> None:
    _return_at(engine, actor, "end")


@hook("turn_start")
def suppressed_effects_return_at_start(engine: Any, actor: Any) -> None:
    _return_at(engine, actor, "start")


@hook("nominal_slot_boundary")
def nominal_return(engine: Any, actor: Any, checkpoint: str) -> None:
    _return_at(engine, actor, "start" if checkpoint == "START_OF_TURN" else "end", nominal=True)
