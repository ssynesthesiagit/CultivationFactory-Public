"""Defensive Discipline: the standing "Choose one Defensive Discipline" of a save_rescue block (automation lane AUTO1,
2026-10-04; the same class corkboard #397 reported on Cultivated Response).

Every Path that answers a failed saving throw by cultivation instead of saving-throw proficiency prints a build-time
choice of one ability -- Tempered Response (Body Refining, CL1): "Choose one Defensive Discipline. Rooted Frame: your
chosen saving throw is Strength. Flowing Frame: ... Dexterity. Enduring Frame: ... Constitution"; Cultivated Response
(Qi Cultivation) prints the same shape over Dexterity, Intelligence and Charisma. combat/typed_reactions.py compiles a
``choose_one`` save_rescue row down to the numerically weakest of its abilities (the tie broken alphabetically), so the
printed choice was never offered and the fighter's build silently decided it.

This module owns that choice for any save_rescue block whose feature_blocks spec says ``choose_one``, so a new Path
discipline needs no code:

  * ``compile_actions`` gives its owner one free SELF button per printed ability, named in the player's own words
    ("Tempered Response: Strength (Rooted Frame)"). The button stores the pick as a typed condition that survives a
    table commit and a reload (primitive strings and lists of strings).
  * ``match_start``/``turn_start`` and ``save_mode`` narrow the compiled save_rescue row to the recorded abilities.
    The before-save seam restores an off-turn choice after cold reload too. A recorded choice always
    wins; a caller without a choice transport keeps the compiler's existing weakest-ability row.
  * The buttons are ``setting_only`` and never offered to AI. They record the permitted distinct build choices. When a
    pick may be made is OWNER-PENDING and is not stated in the text; a recorded choice is never replaced by a later pick.
    Cultivated Response admits a second distinct choice at owning Qi Path CL15 and all three at CL20.
  * ``save_rescue_abilities`` offers the same pick when a failed save first
    needs it. Both transports read ``chosen_abilities``; the same persisted record closes
    both menus when capacity is filled and governs the rescue row after reload. Neither replaces a pick.

Inert for any creature without such a block, for an old saved fight whose row was compiled with a single ability and no
recorded pick (it keeps that one ability), and for a feature whose block spec is not ``choose_one``. No saved-fight lock
file is read or written; the row narrowing is engine-local, the same pattern combat/ext/ability_lockout.py uses for
legacy owners.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from . import effect, hook

BLOCK = "save_rescue"
CHOICE_PREFIX = "condition:typed.defensive_discipline:"
SOURCE_PREFIX = "action:typed."
CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"

# The player's own words, transcribed from each Path's printed disciplines. An ability with no printed name here is
# shown by its plain name, which is always understandable; nothing here decides anything.
ABILITY_NAMES = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
                 "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}
DISCIPLINE_NAMES = {
    "tianxia.path.body_refining.feature.tempered_response": {
        "STR": "Rooted Frame", "DEX": "Flowing Frame", "CON": "Enduring Frame"},
    "tianxia.path.qi_cultivation.feature.cultivated_response": {
        "DEX": "Reflexive Circulation", "INT": "Calculated Circulation", "CHA": "Imperious Circulation"},
}


def _specs():
    """The feature_blocks save_rescue specs that print a standing one-ability choice."""
    from ..typed_reactions import rules as block_rules

    out = {}
    for feature_id, spec in (block_rules().get("features") or {}).items():
        if isinstance(spec, dict) and spec.get("block") == BLOCK and spec.get("choose_one"):
            abilities = [str(ability).upper() for ability in spec.get("abilities") or []]
            if abilities:
                out[feature_id] = abilities
    return out


def _label(feature_id: str, ability: str) -> str:
    name = feature_id.rsplit(".", 1)[-1].replace("_", " ").title()
    printed = (DISCIPLINE_NAMES.get(feature_id) or {}).get(ability)
    shown = ABILITY_NAMES.get(ability, ability.title())
    return f"{name}: {shown} ({printed})" if printed else f"{name}: {shown}"


def _condition(feature_id: str) -> str:
    return CHOICE_PREFIX + feature_id.rsplit(".", 1)[-1]


def _recorded(engine: Any, actor: Any, feature_id: str) -> str | None:
    return chosen(engine, actor, feature_id)


def _rows(engine: Any, actor: Any, feature_id: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("feature_id") == feature_id]


@hook("compile_actions")
def discipline_choices(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned = [feature_id for feature_id in _specs() if feature_id in (info.get("owned_ids") or ())]
    out: list[Any] = []
    for feature_id in sorted(owned):
        for ability in _specs()[feature_id]:
            out.append(ActionDefinition(
                source_definition_id=f"{SOURCE_PREFIX}{info['short']}.defensive_discipline."
                                     f"{feature_id.rsplit('.', 1)[-1]}.{ability.lower()}",
                display_name=_label(feature_id, ability), owner_id=info["actor_id"],
                economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "player_only": True, "expected_damage": 0,
                            "setting_description": _description(feature_id, ability),
                            **({"discipline_capacity": _capacity_from_sheet(info, feature_id)}
                               if feature_id == CULTIVATED else {}),
                            "typed": {"effects": [{"type": "defensive_discipline_choice",
                                                   "feature": feature_id, "ability": ability}],
                                      "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}}))
    return out or None


def _description(feature_id: str, ability: str) -> str:
    from ..typed_reactions import rules as block_rules

    spec = block_rules()["features"][feature_id]
    resource = str(spec.get("resource") or "stamina").title()
    action = "Use your Reaction and spend" if spec.get("reaction", True) else "Spend"
    # Only printed facts here: the timing and cost of choosing are OWNER-PENDING (see the reviewed riders), so this
    # text does not state them.
    printed = DISCIPLINE_NAMES.get(feature_id, {}).get(ability)
    named = f" ({printed})" if printed else ""
    return (f"Choose {ABILITY_NAMES[ability]}{named} as a Defensive Discipline. "
            f"When you fail a {ABILITY_NAMES[ability]} saving throw, {action} {spec.get('cost', 1)} {resource} "
            f"to add your Proficiency Bonus, once per round. This may turn the failure into a success.")


def _capacity_from_sheet(info: dict[str, Any], feature_id: str) -> int:
    """Seal owning-Path attainment into the native compiled action, never global multiclass CL."""
    if feature_id != CULTIVATED:
        return 1
    sheet = info["owner_sheet"]
    paths = (sheet.get("path_and_subpath") or {}).get("paths") or []
    qi = next((p for p in paths if isinstance(p, dict)
               and p.get("path_id") == "tianxia.path.qi_cultivation"), {})
    # A legacy identity label cannot establish an effective owning Path level.
    # Unknown attainment retains the original single discipline.
    cl = qi.get("effective_cl", 0)
    return 3 if type(cl) is int and cl >= 20 else 2 if type(cl) is int and cl >= 15 else 1


def capacity(engine: Any, actor: Any, feature_id: str) -> int:
    """Read compiler-sealed capacity; old bundles retain one discipline."""
    for action in engine.action_catalog.values():
        if action.owner_id != actor.entity_id:
            continue
        parameters = action.parameters or {}
        effects = (parameters.get("typed") or {}).get("effects") or []
        if any(e.get("type") == "defensive_discipline_choice" and e.get("feature") == feature_id
               for e in effects):
            value = parameters.get("discipline_capacity", 1)
            return value if type(value) is int and value in (1, 2, 3) else 1
    return 1


def _can_choose(engine: Any, actor: Any, feature_id: str, ability: str = "") -> bool:
    picked = chosen_abilities(engine, actor, feature_id)
    return (len(picked) < capacity(engine, actor, feature_id)
            and (not ability or ability not in picked)
            and actor.turns_started <= 1
            and actor.action_available and bool(_rows(engine, actor, feature_id)))


@hook("candidate_allowed")
def discipline_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    for row in ((getattr(action, "parameters", {}) or {}).get("typed") or {}).get("effects") or []:
        if row.get("type") == "defensive_discipline_choice":
            return _can_choose(engine, actor, str(row.get("feature") or ""), str(row.get("ability") or ""))
    return None


@effect("defensive_discipline_choice")
def defensive_discipline_choice(ctx: Any, eff: dict[str, Any]) -> None:
    feature_id, ability = str(eff.get("feature") or ""), str(eff.get("ability") or "").upper()
    if (feature_id not in _specs() or ability not in _specs()[feature_id]
            or not _can_choose(ctx.engine, ctx.actor, feature_id, ability)):
        return
    _remember(ctx.engine, ctx.actor, feature_id, [*chosen_abilities(ctx.engine, ctx.actor, feature_id), ability])
    _narrow(ctx.engine, ctx.actor, feature_id)


def _narrow(engine: Any, actor: Any, feature_id: str) -> None:
    """Point the compiled rescue row at the recorded ability.

    A fight saved before this module has no recorded pick, so ``_recorded`` returns None and the row it was saved
    with -- the compiler's single weakest ability -- keeps working unchanged.
    """
    picked = chosen_abilities(engine, actor, feature_id)
    if not picked:
        return
    for row in _rows(engine, actor, feature_id):
        row["abilities"] = picked


@hook("match_start", priority=110)
def apply_recorded_disciplines(engine: Any) -> None:
    for actor in engine.state.actors.values():
        for feature_id in _specs():
            _narrow(engine, actor, feature_id)


@hook("turn_start", priority=110)
def apply_recorded_disciplines_at_turn_start(engine: Any, actor: Any) -> None:
    for feature_id in _specs():
        _narrow(engine, actor, feature_id)


@hook("save_mode", priority=110)
def apply_recorded_disciplines_before_save(engine: Any, target: Any, ability: str, dc: int,
                                          source_id: str, roll_context: dict[str, Any]) -> None:
    """Cold reload restores conditions after compilation; narrow before any off-turn save too."""
    for feature_id in _specs():
        _narrow(engine, target, feature_id)

RECORD = "condition:typed.defensive_discipline"
#: the choice id prefix this plug-in owns on the choice_checkpoints transport.
CHOICE = "choice:defensive_discipline."

#: a printed option's own heading and the saving throw it covers, e.g.
#: "### Rooted Frame" + "Your chosen saving throw is Strength."
_HEADING = re.compile(r"^#{2,6}\s*(?P<name>[^\n]+?)\s*$")
_COVERS = re.compile(
    r"\b(?:chosen saving throw is|discipline applies to|chosen saving throw covers)\s+"
    r"(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\b",
    re.I,
)
_ABILITY_CODE = {"STRENGTH": "STR", "DEXTERITY": "DEX", "CONSTITUTION": "CON", "INTELLIGENCE": "INT",
                 "WISDOM": "WIS", "CHARISMA": "CHA"}


@lru_cache(maxsize=512)
def _printed_options(feature_id: str) -> tuple[tuple[str, str], ...]:
    from ..factory_compiler import _rules_text

    try:
        text = str(_rules_text().get(feature_id) or "")
    except Exception:
        return ()
    options: list[tuple[str, str]] = []
    name = ""
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            name = heading.group("name").strip()
            continue
        covers = _COVERS.search(line)
        if covers and name:
            options.append((name, _ABILITY_CODE[covers.group(1).upper()]))
            name = ""
    return tuple(options)


def printed_options(feature_id: str) -> list[tuple[str, str]]:
    """``[(discipline name, ability code)]`` from the feature's own printed text, in printed order.

    Reads the owner's text rather than a copy of it, so a renamed or extra Discipline needs no edit here.
    Returns [] when the text states no option (the caller then keeps the compiled default)."""
    return list(_printed_options(feature_id))


def label(name: str, ability: str, row: dict[str, Any]) -> str:
    """The button text a player reads: the printed Discipline name and the saving throw it covers."""
    spelled = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
               "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}.get(ability, ability)
    return f"{name}: {spelled} saving throws"


def _discipline_rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    rows = (getattr(engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, [])
    return [row for row in rows if row.get("block") == "save_rescue" and row.get("choose_one") and row.get("choices")]


def chosen_abilities(engine: Any, actor: Any, feature_id: str) -> list[str]:
    """Both legacy single choices and the expanded primitive record survive cold reload."""
    codes = [code for _name, code in _printed_options(feature_id)]
    limit = capacity(engine, actor, feature_id)
    picked = []
    for record in actor.conditions.values():
        if (not (record.data or {}).get("suppressed") and
                ((record.condition_id == RECORD and record.source_definition_id == feature_id)
                 or record.condition_id == _condition(feature_id))):
            values = record.data.get("abilities") or [record.data.get("ability")]
            for value in values:
                if value in codes and value not in picked:
                    picked.append(value)
    if limit >= len(codes) and codes and _rows(engine, actor, feature_id):
        return [*picked, *(code for code in codes if code not in picked)]
    return picked[:limit]


def chosen(engine: Any, actor: Any, feature_id: str) -> str | None:
    """Compatibility reader for the original discipline; new consumers use chosen_abilities."""
    picked = chosen_abilities(engine, actor, feature_id)
    return picked[0] if picked else None


def _remember(engine: Any, actor: Any, feature_id: str, abilities: list[str]) -> None:
    for record in list(actor.conditions.values()):
        if ((record.condition_id == RECORD and record.source_definition_id == feature_id)
                or record.condition_id == _condition(feature_id)):
            # Remove only this feature's own instance: RECORD is shared by every defensive discipline
            # (e.g. Tempered Response), and _remove_condition would end all of them.
            engine._remove_condition_instance(actor, record.instance_id, record.source_definition_id, expected=record)
    engine._apply_condition(actor, RECORD, feature_id, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"ability": abilities[0], "abilities": abilities,
                                  "label": "; ".join(_label(feature_id, a) for a in abilities)})


@hook("choice_reactors")
def discipline_owners(engine: Any) -> tuple[str, ...]:
    """Enroll owned build choices even when ordinary reactions are set to Auto."""
    return tuple(actor.entity_id for actor in engine.state.actors.values()
                 if any(len(_printed_options(str(row.get("feature_id") or ""))) > 1
                        and len(chosen_abilities(engine, actor, str(row["feature_id"]))) < capacity(engine, actor, str(row["feature_id"]))
                        for row in _discipline_rows(engine, actor)))


@hook("choice_options")
def discipline_choice_options(engine: Any, intent: Any, checkpoint: str, reactor_id: str, choice_id: str,
                              context: dict[str, Any]) -> dict[str, Any] | None:
    """Transport for this plug-in's choice: the printed Discipline options as one-button choices.

    The table shows them as buttons and the local AI controller takes its preferred (first) option, which is the
    same ability the compiled stand-in already used, so an AI fighter's fight is unchanged until it answers."""
    if not str(choice_id).startswith(CHOICE) or not (context or {}).get("needle_options"):
        return None
    return {"option_ids": list(context["needle_options"]), "minimum_selections": 1, "maximum_selections": 1,
            "allow_decline": bool(context.get("allow_decline", False)),
            "automatic_use": bool(context.get("automatic", True)),
            **({"preferred_option_ids": list(context["preferred"])} if context.get("preferred") else {})}


@hook("save_rescue_abilities")
def discipline_abilities(engine: Any, target: Any, row: dict[str, Any]) -> list[str] | None:
    """Narrow a printed choose-one save_rescue row to the discipline this fighter chose."""
    feature_id = str(row.get("feature_id") or "")
    if not feature_id or not _discipline_rows(engine, target):
        return None  # nothing of this kind is theirs
    options = _printed_options(feature_id)
    if len(options) < 2:
        return None  # the printed text states no menu; the compiled default stands
    codes = [code for _name, code in options]
    selected = chosen_abilities(engine, target, feature_id)
    while len(selected) < capacity(engine, target, feature_id):
        remaining = [code for code in codes if code not in selected]
        from .needle import ask, checkpoint_id
        from .choice_prompt import action_context

        default = next((code for code in row.get("abilities") or [] if code in remaining), remaining[0])
        context = engine.d20_context() or {}
        source_id = str(context.get("source_id") or "")
        source_actor = engine.state.actors.get(context.get("source_actor_id"))
        prompt_context = action_context(engine, source_actor, source_id, target)
        resource = str(row.get("resource_id") or "").rsplit(".", 1)[-1].replace("_", " ").title()
        cost = int(row.get("cost") or 0)
        response_action = "also uses your Reaction" if row.get("reaction") else "uses no action"
        action_name = prompt_context["action_name"] or "the effect"
        answer = ask(engine, engine._active_intent,
                     checkpoint_id(engine, "defensive_discipline",
                                   feature_id if not selected else f"{feature_id}.{len(selected)}", target.entity_id), target,
                     f"{CHOICE}{feature_id}", remaining,
                     labels={code: label(name, code, row) for name, code in options if code in remaining},
                     preferred=[default], target_id=target.entity_id, default="decline",
                     name=str(row.get("name") or "Defensive Discipline"), feature_id=feature_id,
                     prompt_context={**prompt_context, "cost": f"Spends {cost} {resource} when the response is used."},
                     prompt=f"{row.get('name') or 'Your Defensive Discipline'}: choose which saving throw it covers. "
                            f"{target.display_name} failed a saving throw against {action_name}. "
                            f"When that saving throw fails, using the response spends {cost} {resource}, "
                            f"your cultivation energy, to add +{row.get('bonus', 0)} to the result, once per round. "
                            f"Using the response {response_action}.")
        picked = answer[0] if answer and answer[0] in remaining else None
        if picked is None:
            return selected or None  # retain every recorded discipline if the extra choice is unanswered
        selected.append(picked)
        _remember(engine, target, feature_id, selected)
        engine._append_event("PASSIVE_TRIGGERED", feature_id, actor_id=target.entity_id,
                             target_ids=(target.entity_id,), payload={"trigger": "Defensive Discipline chosen",
                                                                     "ability": picked})
    return selected
