"""Defensive Discipline: the standing "Choose one Defensive Discipline" of a save_rescue block (automation lane AUTO1,
2026-10-04; the same class corkboard #397 reported on Cultivated Response).

Every Path that answers a failed saving throw by cultivation instead of saving-throw proficiency prints a build-time
choice of one ability -- Tempered Response (Body Refining, CL1): "Choose one Defensive Discipline. Rooted Frame: your
chosen saving throw is Strength. Flowing Frame: ... Dexterity. Enduring Frame: ... Constitution"; Cultivated Response
(Qi Cultivation) prints the same shape over Dexterity, Intelligence and Charisma. The menu itself -- which
Disciplines a feature offers and the saving throw each one covers -- is the reviewed record's own ``disciplines``
data (see ``_menu``), never a parse of those printed sentences (PRIVCONV2). combat/typed_reactions.py compiles a
``choose_one`` save_rescue row down to the numerically weakest of its abilities (the tie broken alphabetically), so the
printed choice was never offered and the fighter's build silently decided it.

This module owns that choice for any save_rescue block whose feature_blocks spec says ``choose_one``, so a new Path
discipline needs no code:

  * ``compile_actions`` gives its owner one free SELF button per printed ability, named in the player's own words
    ("Tempered Response: Strength (Rooted Frame)"). The button stores the pick as a typed condition that survives a
    table commit and a reload (a string, nothing else).
  * ``match_start``/``turn_start`` and ``save_mode`` narrow the compiled save_rescue row to the recorded ability.
    The before-save seam restores an off-turn choice after cold reload too. A recorded choice always
    wins; an AI owner with nothing recorded keeps the compiler's existing weakest-ability row.
  * The buttons are ``setting_only``, free, and never offered to AI. They record one initial build choice during
    first-turn setup before spending the Action; they cannot replace a recorded choice or be used on later turns.
    Extra-discipline progression remains unsupported and is not claimed by this selector.
  * ``save_rescue_abilities`` offers the same pick when a failed save first
    needs it. Both transports read ``chosen``; either persisted record closes
    both menus and governs the rescue row after reload. Neither replaces a pick.

Inert for any creature without such a block, for an old saved fight whose row was compiled with a single ability and no
recorded pick (it keeps that one ability), and for a feature whose block spec is not ``choose_one``. No saved-fight lock
file is read or written; the row narrowing is engine-local, the same pattern combat/ext/ability_lockout.py uses for
legacy owners.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from . import effect, hook

BLOCK = "save_rescue"
CHOICE_PREFIX = "condition:typed.defensive_discipline:"
SOURCE_PREFIX = "action:typed."

# The player's own words for a saving throw. A Discipline's own name is not written here: it is the reviewed
# record's ``disciplines`` data (see _menu), so the printed words live once, in the authority.
ABILITY_NAMES = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
                 "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}


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
    printed = {code: title for title, code in _menu(feature_id)}.get(ability)
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
                            "typed": {"effects": [{"type": "defensive_discipline_choice",
                                                   "feature": feature_id, "ability": ability}],
                                      "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}}))
    return out or None


def _description(feature_id: str, ability: str) -> str:
    from ..typed_reactions import rules as block_rules

    spec = block_rules()["features"][feature_id]
    resource = str(spec.get("resource") or "stamina").title()
    action = "Use your Reaction and spend" if spec.get("reaction", True) else "Spend"
    return (f"Choose {ABILITY_NAMES[ability]} as your permanent Defensive Discipline during your first-turn setup. "
            f"Choosing costs no action or resource and cannot replace a previous choice. "
            f"When you fail a {ABILITY_NAMES[ability]} saving throw, {action} {spec.get('cost', 1)} {resource} "
            f"to add your Proficiency Bonus, once per round. This may turn the failure into a success.")


def _can_choose(engine: Any, actor: Any, feature_id: str) -> bool:
    return (chosen(engine, actor, feature_id) is None
            and actor.turns_started <= 1
            and actor.action_available and bool(_rows(engine, actor, feature_id)))


@hook("candidate_allowed")
def discipline_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    for row in ((getattr(action, "parameters", {}) or {}).get("typed") or {}).get("effects") or []:
        if row.get("type") == "defensive_discipline_choice":
            return _can_choose(engine, actor, str(row.get("feature") or ""))
    return None


@effect("defensive_discipline_choice")
def defensive_discipline_choice(ctx: Any, eff: dict[str, Any]) -> None:
    feature_id, ability = str(eff.get("feature") or ""), str(eff.get("ability") or "").upper()
    if (feature_id not in _specs() or ability not in _specs()[feature_id]
            or not _can_choose(ctx.engine, ctx.actor, feature_id)):
        return
    ctx.engine._remove_condition(ctx.actor, _condition(feature_id), ctx.source)
    ctx.engine._apply_condition(ctx.actor, _condition(feature_id), ctx.source, ctx.actor.entity_id,
                                expires_on="UNTIL_REMOVED",
                                data={"ability": ability, "feature_id": feature_id,
                                      "label": _label(feature_id, ability)})
    _narrow(ctx.engine, ctx.actor, feature_id)


def _narrow(engine: Any, actor: Any, feature_id: str) -> None:
    """Point the compiled rescue row at the recorded ability.

    A fight saved before this module has no recorded pick, so ``_recorded`` returns None and the row it was saved
    with -- the compiler's single weakest ability -- keeps working unchanged.
    """
    chosen = _recorded(engine, actor, feature_id)
    if not chosen:
        return
    for row in _rows(engine, actor, feature_id):
        row["abilities"] = [chosen]


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


@lru_cache(maxsize=512)
def _menu(feature_id: str) -> tuple[tuple[str, str], ...]:
    """``((discipline name, ability code), ...)`` from the feature's reviewed typed record.

    The menu is data: ``"disciplines": [{"name": "Rooted Frame", "ability": "STR"}, ...]`` on the reviewed record
    (authority/typed_mechanics/reviewed_final.d/*.json, carried into
    authority/Tianxia_Typed_Mechanics_Authority_R1.json by tools/build_typed_mechanics_authority.py). It used to be
    parsed out of the printed text -- "### Rooted Frame" over "Your chosen saving throw is Strength." -- which is
    prose: the public copy of the rules scrambles it, and then a fighter had no Disciplines at all (PRIVCONV2).
    """
    from ..typed_numbers import authority_mechanics

    try:
        record = (authority_mechanics() or {}).get(feature_id) or {}
    except Exception:
        return ()
    options: list[tuple[str, str]] = []
    for row in record.get("disciplines") or ():
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        ability = str(row.get("ability") or "").strip().upper()
        if name and ability in ABILITY_NAMES:
            options.append((name, ability))
    return tuple(options)


def printed_options(feature_id: str) -> list[tuple[str, str]]:
    """``[(discipline name, ability code)]`` in printed order, from the feature's reviewed typed record.

    Reads the record the fight already reads rather than a copy of it, so a renamed or extra Discipline needs no
    edit here. Returns [] when the record states no option (the caller then keeps the compiled default)."""
    return list(_menu(feature_id))


def label(name: str, ability: str, row: dict[str, Any]) -> str:
    """The button text a player reads: the printed Discipline name and the saving throw it covers."""
    spelled = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
               "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}.get(ability, ability)
    return f"{name}: {spelled} saving throws"


def _discipline_rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    rows = (getattr(engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, [])
    return [row for row in rows if row.get("block") == "save_rescue" and row.get("choose_one") and row.get("choices")]


def chosen(engine: Any, actor: Any, feature_id: str) -> str | None:
    """Read either approved transport's persisted choice for this feature.

    Turn flags reset at turn start and service reloads need not retain old events.
    A normal condition record survives both through the existing event reducer.
    """
    codes = {code for _name, code in _menu(feature_id)}
    for record in actor.conditions.values():
        if (not (record.data or {}).get("suppressed") and
                ((record.condition_id == RECORD and record.source_definition_id == feature_id)
                 or record.condition_id == _condition(feature_id))):
            value = record.data.get("ability")
            if value in codes:
                return str(value)
    return None


@hook("choice_reactors")
def discipline_owners(engine: Any) -> tuple[str, ...]:
    """Enroll owned build choices even when ordinary reactions are set to Auto."""
    return tuple(actor.entity_id for actor in engine.state.actors.values()
                 if any(len(_menu(str(row.get("feature_id") or ""))) > 1
                        and chosen(engine, actor, str(row["feature_id"])) is None
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
    options = _menu(feature_id)
    if len(options) < 2:
        return None  # the printed text states no menu; the compiled default stands
    codes = [code for _name, code in options]
    picked = chosen(engine, target, feature_id)
    if picked is None:
        from .needle import ask, checkpoint_id
        from .choice_prompt import action_context

        default = str((row.get("abilities") or [codes[0]])[0]).upper()
        context = engine.d20_context() or {}
        source_id = str(context.get("source_id") or "")
        source_actor = engine.state.actors.get(context.get("source_actor_id"))
        prompt_context = action_context(engine, source_actor, source_id, target)
        resource = str(row.get("resource_id") or "").rsplit(".", 1)[-1].replace("_", " ").title()
        cost = int(row.get("cost") or 0)
        response_action = "also uses your Reaction" if row.get("reaction") else "uses no action"
        action_name = prompt_context["action_name"] or "the effect"
        answer = ask(engine, engine._active_intent,
                     checkpoint_id(engine, "defensive_discipline", feature_id, target.entity_id), target,
                     f"{CHOICE}{feature_id}", codes,
                     labels={code: label(name, code, row) for name, code in options},
                     preferred=[default], target_id=target.entity_id, default="decline",
                     name=str(row.get("name") or "Defensive Discipline"), feature_id=feature_id,
                     prompt_context={**prompt_context, "cost": "Choosing costs no action or resource."},
                     prompt=f"{row.get('name') or 'Your Defensive Discipline'}: choose which saving throw it covers. "
                            f"{target.display_name} failed a saving throw against {action_name}. "
                            "Your choice lasts for this fight and costs no action or resource. "
                            f"When that saving throw fails, using the response spends {cost} {resource}, "
                            f"your cultivation energy, to add +{row.get('bonus', 0)} to the result, once per round. "
                            f"Using the response {response_action}.")
        picked = answer[0] if answer and answer[0] in codes else None
        if picked is None:
            return None  # nobody answered (an old saved fight, a probe): keep the compiled default
        picked_name = next(name for name, code in options if code == picked)
        engine._apply_condition(target, RECORD, feature_id, target.entity_id, expires_on="UNTIL_REMOVED",
                                data={"ability": picked, "label": f"{row.get('name') or 'Defensive Discipline'}: "
                                      f"{label(picked_name, picked, row)} for this fight"})
        engine._append_event("PASSIVE_TRIGGERED", feature_id, actor_id=target.entity_id,
                             target_ids=(target.entity_id,), payload={"trigger": "Defensive Discipline chosen",
                                                                     "ability": picked})
    return [picked]
