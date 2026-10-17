"""Imbuement's Place Mandate and Fray Mandate (rider lane C5, owner 2026-09-30: "i want everything we can automated").

The printed rule (Sphere of Imbuement): "Place Mandate ... You place one beneficial Imbue option you know into the target Vessel.
Choose one Imbue talent you know and apply its listed effect." / "Fray Mandate ... Choose one Fray talent you know and apply its
listed effect. A creature receives a Wisdom saving throw ... At the end of each of its turns, an affected creature may repeat the
saving throw, ending the effect". The compiler used to merge every known talent's effects into one Place Mandate and one Fray
Mandate (all options at once, the Fray ones whatever the save).

Here each known option is its own button: "Place Mandate: Quicken", "Fray Mandate: Slow". The talents' reviewed rows carry them as
``mandate_option`` markers (inert when a row runs):

    {"type": "mandate_option", "side": "imbue" | "fray", "label": "Quicken", "vessel": "creature" | "weapon" | "armor",
     "effects": [...],                 # typed rows put on the target (the bearer, for a weapon or armor Vessel)
     "choose": {"name": "...", "choices": [{"id", "label", "effects"}], "ai": "first" | "lowest_save"},   # "Choose one ...":
                                       # asked of the caster when the Mandate lands (the built-in AI picks by "ai")
     "cost": [["cp", 2]],              # an Augment's printed CP (a separate "+ Augment" button when "augment" names it)
     "augment": "Augment 2 CP",
     "riders": ["..."]}                # what the table leaves to the GM

Both keep the base abilities' Action, 30-foot range (120 with Sovereign of the True Name of Things) and Concentration, up to 10
minutes; the Fray ones wrap their rows in a Wisdom save whose failure starts a repeat-save group (rider_repeat_group: a success at
the end of the target's turn ends the Mandate on it). Mandate Load: placing a Mandate beyond your Load ends your oldest one (1 by
default; Layered Mandate and Qi-Written Mandate +1 each, Sovereign +PB -- their "load" feature rows); a set Mandate (Set Mandate, kept
without Concentration by combat/ext/persist_augment.py) still counts and can be the oldest one ended.

Weapon and armor Vessels: ``mandate_vessel`` puts a condition on the bearer naming the chosen weapon (asked of the caster), read
by the hooks below for that weapon's own typed attacks (attack_bonus, attack_mode, attack_damage_bonus, after_hit) and for AC.
A creature whose attacks are not typed (a native stat block) has no weapon to name: those Frays land on nothing (GM).

Default-inert: characters without the block rows get no buttons, and the hooks return early unless the creature bears one of
these conditions.

Court of Ten Thousand Mandates (AUTO20f1). Its free Mandate is a real Mandate the table charges for with no Action, so the
Mandate it places belongs to *that* button: the chosen option's own rows run in the free button's context, which is what the
caster is Concentrating on, so dropping Concentration, Mandate Load and Counter-Mandate all reach it. The chosen option is
still held to its own printed target rule (a Place Mandate on a willing ally, a Fray Mandate on a hostile creature) and to
"inside the Court"; the Court does not override either. The family is chosen once, as the Court is created, and goes when the
Court goes.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from . import effect, hook, note

BLOCK = "imbuement_mandate"
IMBUEMENT = "tianxia.sphere.imbuement"
VESSEL = "condition:typed.mandate_vessel"
FRAY_ANCHOR = "fray_mandate"
_SAVES = (("STR", "Strength"), ("DEX", "Dexterity"), ("CON", "Constitution"), ("INT", "Intelligence"), ("WIS", "Wisdom"), ("CHA", "Charisma"))


@hook("compile_block")
def mandate_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind") or "mandate", "load": spec.get("load") or 0}]


def _rows(info_or_engine: Any, actor_id: str | None = None) -> list[dict[str, Any]]:
    if isinstance(info_or_engine, dict):
        return [row for row in info_or_engine.get("passives") or [] if row.get("block") == BLOCK]
    from ..typed_reactions import _rows as rows

    return list(rows(info_or_engine, actor_id or "", BLOCK))


def _court(engine: Any, actor: Any) -> Any:
    """The caster's own standing Court of Ten Thousand Mandates (an active area of theirs whose ability carries a
    ``mandate_load`` row), or None. The Mandate Load bonus and the Court's free Mandate and its temporary hit points all
    read the same Court through this one query."""
    for zone in engine.state.zones.values():
        if not zone.active or zone.owner_id != actor.entity_id:
            continue
        typed = ((getattr(engine.action_catalog.get(zone.source_definition_id), "parameters", None) or {}).get("typed") or {})
        if any(isinstance(row, dict) and row.get("type") == "mandate_load" for row in typed.get("effects") or []):
            return zone
    return None


def _court_row(engine: Any, zone: Any) -> dict[str, Any]:
    """The ``mandate_load`` row of the ability that made ``zone``: the Court's printed radius and its temporary hit points,
    both read from that one row so every check on "inside the Court" agrees (AUTO20f1: ``ZoneState`` carries
    ``radius_cells``, not ``radius_ft``, so a check written against the zone raised ``AttributeError`` on every candidate
    listing and the printed "inside the Court" was never enforced)."""
    typed = ((getattr(engine.action_catalog.get(zone.source_definition_id), "parameters", None) or {}).get("typed") or {})
    return next((row for row in typed.get("effects") or []
                 if isinstance(row, dict) and row.get("type") == "mandate_load"), {})


def _inside_court(engine: Any, actor: Any, zone: Any, target: Any) -> bool:
    """Whether ``target`` stands inside ``zone``: within its printed radius of the caster who owns it."""
    if target is None or not getattr(target, "active", False):
        return False
    reach = int(_court_row(engine, zone).get("radius_ft") or 30)
    return engine._distance_actor_to_actor(actor, target) <= reach


def load(engine: Any, actor: Any, pb: int) -> int:
    """Mandate Load: 1, +1 Layered Mandate, +1 Qi-Written Mandate, +PB Sovereign of the True Name of Things, +PB while your Court
    of Ten Thousand Mandates stands (an active area of yours whose ability carries a ``mandate_load`` row)."""
    total = 1
    for row in _rows(engine, actor.entity_id):
        total += pb if row.get("load") == "pb" else int(row.get("load") or 0)
    return total + (pb if _court(engine, actor) is not None else 0)


@effect("mandate_load")
def mandate_load_row(ctx: Any, eff: dict[str, Any]) -> None:
    """Marker: "your Mandate Load increases by your Proficiency Bonus" while this ability's area stands (load above)."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


@hook("compile_actions")
def mandate_actions(info: dict[str, Any]) -> list[Any] | None:
    rows = _rows(info)
    if not any(row.get("kind") == "base" for row in rows):
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    mechanics = info["mechanics"]
    reach = 120 if any(row.get("kind") == "sovereign" for row in rows) else 30
    primary = RESOURCE_IDS.get(info.get("primary") or "qi") or "resource:core.qi"
    out = []
    for row in sorted(rows, key=lambda r: str(r["feature_id"])):
        mechanic = mechanics.get(row["feature_id"]) or {}
        for option in mechanic.get("effects") or []:
            if not isinstance(option, dict) or option.get("type") != "mandate_option":
                continue
            for augmented in ([False, True] if option.get("augment") else [False]):
                out.append(_action(info, row["feature_id"], option, augmented, reach, primary, ActionDefinition, EconomyKind))
    if any(row.get("kind") == "counter" for row in rows):
        # Counter-Mandate (1 CP, 30 feet): against another cultivator's Mandate on an ally or on a foe.
        for side, target_kind in (("ally", "ALLY_OR_SELF"), ("foe", "HOSTILE_ENTITY")):
            typed = {"effects": [{"type": "counter_mandate", "evidence": "Make an Imbuement Check against the effect's DC. Success: the target effect ends."}],
                     "numbers": dict(info.get("numbers") or {}), "duration": {"kind": "instant"}, "riders": [
                         "If you know the matching opposite Mandate, you may immediately apply it as part of the same action if the target is legal and fails any required saving throw (use its own button).",
                         "Against a similar enhancement or degradation that is not an Imbuement Mandate, the GM makes the check."],
                     "sphere": IMBUEMENT, "source": "IMBUEMENT_BASE_COUNTER_MANDATE", "range_ft": reach}
            out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mandate.counter.{side}",
                                        display_name="Counter-Mandate" + (": free an ally" if side == "ally" else ": strip a foe"),
                                        owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind=target_kind,
                                        range_ft=reach, costs=((primary, 1),),
                                        parameters={"typed": typed, "expected_damage": 0, "counter_mandate": True,
                                                    "description": "Imbuement Check against another cultivator's Mandate on the creature; on a success the Mandate ends (1 CP)."}))
    frays = [action for action in out if (action.parameters["typed"].get("mandate") or {}).get("side") == "fray" and not action.source_definition_id.endswith(".augmented")]
    if any(row.get("kind") == "twin_fray" for row in rows) and len(frays) >= 2:
        # Twin Fray: "When you use Fray Mandate, you may spend 2 CP to apply two different Fray options you know to the same target."
        typed = {"effects": [{"type": "twin_fray", "evidence": "The target makes one Wisdom saving throw unless a Fray option calls for a different "
                                                                "saving throw. On a success, both effects fail. On a failure, both apply."}],
                 "numbers": dict(info.get("numbers") or {}), "duration": {"kind": "minutes", "amount": 10, "concentration": True}, "riders": [],
                 "sphere": IMBUEMENT, "source": "tianxia.talent.imbuement.twin_fray", "mandate": {"side": "fray", "label": "Twin Fray"}, "range_ft": reach}
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mandate.fray.twin_fray", display_name="Fray Mandate: Twin Fray (2 CP)",
                                    owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                                    range_ft=reach, costs=((primary, 2),), concentration=True,
                                    parameters={"typed": typed, "expected_damage": 0, "mandate": True,
                                                "description": "Two different Fray options you know on one creature, one saving throw (2 CP)."}))
    imbues = [action for action in out if (action.parameters["typed"].get("mandate") or {}).get("side") == "imbue"
              and not action.source_definition_id.endswith(".augmented")]
    if any(row.get("kind") == "layered" for row in rows) and len(imbues) >= 2:
        # Layered Mandate: "When you apply Place Mandate to a willing target, you may spend 1 CP to apply two different Imbue
        # options you know with the same action."
        typed = {"effects": [{"type": "layered_mandate", "evidence": "Apply two different Imbue options you know to the one willing "
                                                                                "target, with this one Action. The target makes no saving throw: the printed "
                                                                                "trigger is a willing target."}],
                 "numbers": dict(info.get("numbers") or {}), "duration": {"kind": "minutes", "amount": 10, "concentration": True}, "riders": [],
                 "sphere": IMBUEMENT, "source": "tianxia.talent.imbuement.layered_mandate", "mandate": {"side": "imbue", "label": "Layered Mandate"},
                 "range_ft": reach}
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mandate.imbue.layered",
                                    display_name="Place Mandate: Layered Mandate (1 CP)",
                                    owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF",
                                    range_ft=reach, costs=((primary, 1),), concentration=True,
                                    parameters={"typed": typed, "expected_damage": 0, "mandate": True,
                                                "description": "Two different Imbue options you know on one willing target, with this one "
                                                               "Action (1 CP). No saving throw."}))
    families = {str((action.parameters["typed"] or {}).get("source") or "") for action in out
                if ((action.parameters or {}).get("typed") or {}).get("mandate", {}).get("side") in ("imbue", "fray")}
    families = {key for key in families if key in mechanics}  # a printed Mandate family is the talent its options come from
    if families and _court_action(info, mechanics):
        typed = {"effects": [{"type": "court_free_mandate", "evidence": "Once on each of your turns, while your Court of Ten Thousand Mandates stands, "
                                                                             "use one Place Mandate or Fray Mandate from the family you chose, without spending an Action."}],
                 "numbers": dict(info.get("numbers") or {}), "duration": {"kind": "minutes", "amount": 10, "concentration": True}, "riders": [],
                 "sphere": IMBUEMENT, "source": "tianxia.talent.imbuement.court_of_ten_thousand_mandates",
                 "mandate": {"side": "court_free"}, "range_ft": reach}
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mandate.court.free",
                                    display_name="Court of Ten Thousand Mandates: Free Mandate",
                                    owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="ANY_CREATURE",
                                    range_ft=reach, costs=(), concentration=True,
                                    parameters={"typed": typed, "expected_damage": 0, "mandate": True, "court_free_mandate": True,
                                                "description": "While your Court stands: one Place Mandate or Fray Mandate from the family you chose, "
                                                               "on a creature inside the Court, without spending an Action (once each turn)."}))
    return out or None


def _court_action(info: dict[str, Any], mechanics: dict[str, Any]) -> str:
    """The Court of Ten Thousand Mandates talent this character owns, or "" (its printed free Mandate is then absent)."""
    for key in info["owned_ids"]:
        if (mechanics.get(key) or {}).get("sphere_id") == IMBUEMENT and (mechanics.get(key) or {}).get("name") == "Court of Ten Thousand Mandates":
            return key
    return ""


def _resolve(value: Any, numbers: dict[str, Any]) -> Any:
    """The character's own numbers in an option's rows: "@pb", "@half_pb", "@cl", "@key"; a "by_cl" table [[low, high, n], ...]
    beside a key "<key>_by_cl" sets that key for the character's Cultivation Level."""
    cl, pb = int(numbers.get("cl") or 1), int(numbers.get("pb") or 2)
    if isinstance(value, list):
        return [_resolve(item, numbers) for item in value]
    if isinstance(value, dict):
        out = {key: _resolve(item, numbers) for key, item in value.items()}
        for key in [key for key in out if key.endswith("_by_cl")]:
            out[key[:-len("_by_cl")]] = next((int(n) for low, high, n in out.pop(key) if int(low) <= cl <= int(high)), out.get(key[:-len("_by_cl")]))
        return out
    if isinstance(value, str) and value in ("@pb", "@half_pb", "@cl", "@key"):
        return {"@pb": pb, "@half_pb": pb // 2, "@cl": cl, "@key": int(numbers.get("key_mod") or 0)}[value]
    return value


def _action(info: dict[str, Any], feature_id: str, option: dict[str, Any], augmented: bool, reach: int, primary: str,
            ActionDefinition: Any, EconomyKind: Any) -> Any:
    side = option.get("side") or "imbue"
    label = str(option["label"])
    option = _resolve(copy.deepcopy(option), info.get("numbers") or {})
    rows = copy.deepcopy(option.get("augment_effects") if augmented and option.get("augment_effects") else option.get("effects") or [])
    choose = option.get("augment_choose") if augmented and option.get("augment_choose") else option.get("choose")
    if choose:
        rows = [{**copy.deepcopy(choose), "type": "mandate_choice", "name": f"{'Place' if side == 'imbue' else 'Fray'} Mandate: {label}"}, *rows]
    if option.get("vessel") in ("weapon", "armor", "ranged_weapon"):
        rows = [{"type": "mandate_vessel", "vessel": option["vessel"], "name": label, "rows": rows}]
    if side == "fray":
        ability = str(option.get("save") or "wis")
        rows = [{"type": "save", "ability": ability, "applies_to": "target", "dc": "technique_save_dc",
                 "evidence": f"A creature receives a {dict(_SAVES).get(ability.upper(), 'Wisdom')} saving throw (Fray Mandate).",
                 "on_fail": [{"type": "rider_repeat_group", "name": f"Fray Mandate: {label}", "effects": [
                     {"type": "condition", "condition": FRAY_ANCHOR, "applies_to": "target", "repeat_save": {"ability": ability.upper(), "when": "end"},
                      "condition_data": {"label": f"Fray Mandate: {label} (a Wisdom save at the end of each of its turns ends it)"},
                      "evidence": "At the end of each of its turns, an affected creature may repeat the saving throw, ending the effect on a success."},
                     *rows]}],
                 "on_success": []}]
    name = f"{'Place' if side == 'imbue' else 'Fray'} Mandate: {label}" + (f" + {option.get('augment')}" if augmented else "")
    costs = tuple((primary if resource == "cp" else resource, int(amount)) for resource, amount in (option.get("cost") or []) if augmented or not option.get("augment"))
    target_kind = "ALLY_OR_SELF" if side == "imbue" else "HOSTILE_ENTITY"
    typed = {"effects": rows, "numbers": dict(info.get("numbers") or {}), "duration": {"kind": "minutes", "amount": 10, "concentration": True},
             "riders": list(option.get("riders") or []), "sphere": IMBUEMENT, "source": feature_id, "mandate": {"side": side, "label": label},
             "range_ft": reach}
    if augmented:
        typed["augment"] = str(option.get("augment") or "")  # what the printed Augment adds, for the hooks that honour it
    description = (option.get("augment_description") if augmented and option.get("augment_description") else None) \
        or option.get("description") or f"{name}: {option.get('summary') or ''}".strip(": ")
    return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mandate.{side}.{_slug(label)}{'.augmented' if augmented else ''}",
                            display_name=name, owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED",
                            target_kind=target_kind, range_ft=reach, costs=costs, concentration=True,
                            parameters={"typed": typed, "expected_damage": 0, "mandate": True, "description": description})


@effect("mandate_option")
def mandate_option(ctx: Any, eff: dict[str, Any]) -> None:
    """A marker read at compile time (mandate_actions); nothing to do when a talent's own row runs."""


@effect("vessel_rule")
def vessel_rule(ctx: Any, eff: dict[str, Any]) -> None:
    """Read by mandate_vessel (the bearer's condition data); nothing to do on its own."""


@effect("if_concentrating")
def if_concentrating(ctx: Any, eff: dict[str, Any]) -> None:
    """{"type": "if_concentrating", "effects": [...]}: "If the target is Concentrating, it also ..." (Cloud)."""
    from ..typed_executor import run_effects

    if ctx.target is not None and ctx.target.concentration is not None:
        run_effects(ctx, copy.deepcopy(eff.get("effects") or []))


@effect("twin_fray")
def twin_fray(ctx: Any, eff: dict[str, Any]) -> None:
    """Pick two different Fray options you know; one saving throw (per save ability named) decides both."""
    from ..typed_executor import run_effects
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    target = _subject(ctx)
    options = {key: action for key, action in sorted(ctx.engine.action_catalog.items())
               if action.owner_id == ctx.actor.entity_id and key != ctx.source and not key.endswith(".augmented")
               and (((action.parameters or {}).get("typed") or {}).get("mandate") or {}).get("side") == "fray"}
    if target is None or len(options) < 2:
        return
    ids = list(options)
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "TWIN_FRAY", ctx.source, target.entity_id), ctx.actor, CHOICE + "twin_fray", ids,
                 labels={key: options[key].display_name for key in ids}, minimum=2, maximum=2, name="Twin Fray",
                 prompt=f"Twin Fray on {target.display_name}: choose two different Fray options.",
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target))
    chosen = list(dict.fromkeys(picked or ids[:2]))[:2]
    if len(chosen) < 2:
        chosen = ids[:2]
    saves: dict[str, dict[str, Any]] = {}
    for key in chosen:
        save = copy.deepcopy((options[key].parameters["typed"].get("effects") or [{}])[0])
        ability = str(save.get("ability") or "wis").lower()
        group = (save.get("on_fail") or [{}])[0]
        if ability not in saves:
            saves[ability] = save
        else:
            first = saves[ability]["on_fail"][0]
            first["effects"] = [*first["effects"], *[row for row in group.get("effects") or [] if row.get("condition") != FRAY_ANCHOR]]
            first["name"] = "Twin Fray"
    run_effects(ctx, list(saves.values()))


@effect("layered_mandate")
def layered_mandate(ctx: Any, eff: dict[str, Any]) -> None:
    """"Layered Mandate: When you apply Place Mandate to a willing target, you may spend 1 CP to apply two different Imbue options
    you know with the same action."

    Both chosen options' own compiled rows run on the one willing target under this button's single Concentration, so each option
    brings its own printed effect (and its own "choose one" pick, or its own Mandate Vessel) exactly as its own button would. There
    is no saving throw: the printed trigger is a *willing* target, so an unwilling one is not a legal target for this button.
    """
    from ..typed_executor import run_effects
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    target = _subject(ctx)
    options = {key: action for key, action in sorted(ctx.engine.action_catalog.items())
               if action.owner_id == ctx.actor.entity_id and key != ctx.source and not key.endswith(".augmented")
               and (((action.parameters or {}).get("typed") or {}).get("mandate") or {}).get("side") == "imbue"}
    if target is None or len(options) < 2:
        return
    ids = list(options)
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "LAYERED_MANDATE", ctx.source, target.entity_id), ctx.actor,
                 CHOICE + "layered_mandate", ids, labels={key: options[key].display_name for key in ids}, minimum=2, maximum=2,
                 name="Layered Mandate",
                 prompt=(f"Layered Mandate on {target.display_name}: choose two different Imbue options to apply with this one Action."),
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target))
    chosen = list(dict.fromkeys(picked or ids[:2]))[:2]
    if len(chosen) < 2:
        chosen = ids[:2]
    rows: list[dict[str, Any]] = []
    for key in chosen:
        typed = ((options[key].parameters or {}).get("typed") or {})
        rows.extend(copy.deepcopy(typed.get("effects") or []))
    run_effects(ctx, rows)


@hook("after_hit_choice")
def touch_carried(ctx: Any, target: Any, kind: str) -> None:
    """Touch-Carried Mandate: "When you hit a creature with a weapon attack, unarmed strike, natural weapon, or spell attack, you may
    spend 1 CP to apply one Fray Mandate you know to the target as part of the same attack."""
    engine, actor = ctx.engine, ctx.actor
    if not target.active or ctx.typed.get("mandate") or not any(row.get("kind") == "touch_carried" for row in _rows(engine, actor.entity_id)):
        return
    from ..factory_compiler import RESOURCE_IDS

    pool = next((pool for pool in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance") if int(actor.resources.get(pool, 0)) >= 1), None)
    frays = {key: action for key, action in sorted(engine.action_catalog.items())
             if action.owner_id == actor.entity_id and not key.endswith(".augmented") and not key.endswith(".twin_fray")
             and (((action.parameters or {}).get("typed") or {}).get("mandate") or {}).get("side") == "fray"}
    if pool is None or not frays or ctx.damage_cache.get(("touch_carried", target.entity_id)):
        return
    ctx.damage_cache[("touch_carried", target.entity_id)] = True
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    ids = list(frays)
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "TOUCH_CARRIED", ctx.source, target.entity_id), actor, CHOICE + "touch_carried", ids,
                 labels={key: f"{frays[key].display_name} (1 CP)" for key in ids}, allow_decline=True, name="Touch-Carried Mandate",
                 prompt=f"Touch-Carried Mandate: {ctx.action.display_name} hit {target.display_name}. Spend 1 CP to carry a Fray Mandate?",
                 prompt_context=action_context(engine, actor, ctx.source, target))
    if not picked:
        return
    source = picked[0]
    action = frays[source]
    engine._spend_resource(actor, pool, 1, f"{source}.touch_carried")
    engine._start_concentration(actor, source)
    from ..typed_executor import Context, run_effects
    from .weapon_hits import weapon_identity

    fray = Context(engine, actor, action, ctx.intent, copy.deepcopy((action.parameters or {}).get("typed") or {}), [target], target, {})
    weapon = weapon_identity(ctx) if kind in ("weapon", "unarmed") else None
    if weapon and any(c.condition_id == VESSEL and c.source_actor_id == actor.entity_id and (c.data or {}).get("weapon") == weapon
                      for c in actor.conditions.values()):
        fray.damage_cache["touch_carried_disadvantage"] = target.entity_id
    run_effects(fray, fray.typed.get("effects") or [])
    fray.rider(f"Touch-Carried Mandate: {action.display_name} rides {ctx.action.display_name} (1 CP).")
    mandate_load(fray)


@hook("save")
def touch_carried_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """"The target has Disadvantage on its first saving throw against the Fray Mandate" (a weapon bearing your Imbue)."""
    if subject is None or ctx.damage_cache.get("touch_carried_disadvantage") != subject.entity_id:
        return None
    ctx.damage_cache.pop("touch_carried_disadvantage", None)
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}


def foreign_mandates(engine: Any, caster: Any, subject: Any) -> dict[str, tuple[Any, Any]]:
    """{mandate action id: (its creator, the action)} for the other cultivators' Mandates the subject bears."""
    found = {}
    rows = [*subject.conditions.values(), *subject.modifiers.values()]
    for row in rows:
        source = str(getattr(row, "source_definition_id", "") or "")
        action = engine.action_catalog.get(source)
        typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
        creator = engine.state.actors.get(getattr(action, "owner_id", "") or "")
        if typed.get("mandate") and creator is not None and creator.entity_id != caster.entity_id:
            found[source] = (creator, action)
    return found


@hook("candidate_allowed")
def counter_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get("counter_mandate"):
        return None
    targets = [engine.state.actors.get(target_id) for target_id in getattr(candidate, "target_ids", None) or ()]
    return bool(targets) and all(target is not None and foreign_mandates(engine, actor, target) for target in targets)


@effect("counter_mandate")
def counter_mandate(ctx: Any, eff: dict[str, Any]) -> None:
    """"Make an Imbuement Check against the effect's DC. If the effect has no listed DC, use ... 10 + the creator's Proficiency Bonus +
    key ability modifier. Success: the target effect ends ... Failure: nothing happens and CP is spent." A Fray Mandate's DC is its
    Wisdom save's (the creator's Cultivation Save DC); an Imbue has none listed."""
    from .. import concentration, typed_executor
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    target = _subject(ctx)
    found = foreign_mandates(ctx.engine, ctx.actor, target) if target is not None else {}
    if not found:
        return
    ids = sorted(found)
    if len(ids) > 1:
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "COUNTER_MANDATE", ctx.source, target.entity_id), ctx.actor, CHOICE + "counter_mandate",
                     ids, labels={key: found[key][1].display_name for key in ids}, name="Counter-Mandate",
                     prompt=f"Counter-Mandate on {target.display_name}: choose the Mandate to end.",
                     prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target))
        ids = picked or ids
    source = ids[0]
    creator, action = found[source]
    numbers = ((action.parameters or {}).get("typed") or {}).get("numbers") or {}
    side = (((action.parameters or {}).get("typed") or {}).get("mandate") or {}).get("side")
    dc = int(numbers.get("save_dc") or 10) if side == "fray" else 10 + int(numbers.get("pb") or 2) + int(numbers.get("key_mod") or 0)
    modifier = int(ctx.numbers.get("pb") or 2) + int(ctx.numbers.get("key_mod") or 0)
    roll = ctx.engine.roller.d20(modifier=modifier, actor_id=ctx.actor.entity_id, reason=f"CHECK:{ctx.source}:imbuement",
                                 mode=typed_executor.check_mode(ctx.actor, str(ctx.numbers.get("key_ability") or "INT").upper()[:3], engine=ctx.engine))
    ctx.engine._record_roll(roll)
    success = roll.total >= dc
    ctx.engine._append_event("CHECK_ROLLED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "skill": "Imbuement Check"})
    if not success:
        ctx.rider(f"Counter-Mandate: {action.display_name} holds (the CP is spent).")
        return
    if creator.concentration is not None and creator.concentration.source_definition_id == source:
        ctx.engine._end_concentration(creator, "COUNTERED")
    else:
        for iid, state in concentration.held(creator):
            if state.source_definition_id == source:
                concentration.end_held(ctx.engine, creator, iid, "COUNTERED")
                break
    for iid, condition in list(target.conditions.items()):  # anything of it that outlasts its creator's Concentration
        if condition.source_definition_id == source:
            ctx.engine._remove_condition(target, condition.condition_id, ctx.source)
    for mid, modifier in list(target.modifiers.items()):
        if modifier.source_definition_id == source:
            target.modifiers.pop(mid)
            ctx.engine._append_event("MODIFIER_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                     payload={"modifier_id": mid, "reason": "COUNTERED"})
    ctx.rider(f"Counter-Mandate: {action.display_name} ends on {target.display_name}.")


def _subject(ctx: Any) -> Any:
    """The creature a Mandate button was aimed at; an ally-or-self button aimed at its user may carry no target of its own."""
    if ctx.target is not None:
        return ctx.target
    if len(ctx.targets or []) == 1:
        return ctx.targets[0]
    return ctx.actor if str(getattr(ctx.action, "target_kind", "")).endswith("ALLY_OR_SELF") else None


# ------------------------------------------------------------------------------------------------ choices
@effect("mandate_choice")
def mandate_choice(ctx: Any, eff: dict[str, Any]) -> None:
    """"Choose Intelligence, Wisdom, or Charisma" and the like: the caster picks when the Mandate lands."""
    from ..typed_executor import run_effects

    run_effects(ctx, choose(ctx, eff))


def choose(ctx: Any, eff: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows of the caster's pick among a mandate_choice's choices (asked; the AI takes its ``ai`` preference)."""
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    target = _subject(ctx)
    choices = {str(row["id"]): row for row in eff.get("choices") or []}
    if not choices or target is None:
        return []
    order = list(choices)
    if eff.get("ai") == "lowest_save":
        order.sort(key=lambda key: int(target.saving_throws.get(key, 0)))
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "MANDATE_CHOICE", ctx.source, target.entity_id), ctx.actor,
                 CHOICE + "mandate_choice", list(choices), labels={key: str(row.get("label") or key) for key, row in choices.items()},
                 preferred=order[:1], name=str(eff.get("name") or ctx.action.display_name),
                 prompt=f"{eff.get('name') or ctx.action.display_name} on {target.display_name}: {eff.get('prompt') or 'choose one'}.",
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target))
    chosen = choices[(picked or order[:1])[0]]
    ctx.rider(f"{eff.get('name') or ctx.action.display_name}: {chosen.get('label')}.")
    return copy.deepcopy(chosen.get("effects") or [])


# ------------------------------------------------------------------------------------------------ weapon and armor Vessels
def _weapons(engine: Any, bearer: Any, vessel: str) -> dict[str, Any]:
    from .weapon_hits import available_weapons
    from ..weapon_delivery import delivery_kind

    held = {}
    for key, action in available_weapons(engine, bearer).items():
        typed = (action.parameters or {}).get("typed") or {}
        if typed.get("unarmed_option") or ".improvised." in key or not any(
                delivery_kind(typed, row, action.parameters) == 'weapon'
                for row in typed.get('effects') or [] if row.get('type') == 'attack'):
            continue
        if vessel == "ranged_weapon" and not (typed.get("range_ft") or key.endswith("#thrown")):
            continue
        held[key] = action
    return held


@effect("mandate_vessel")
def mandate_vessel(ctx: Any, eff: dict[str, Any]) -> None:
    """Put a weapon or armor Mandate on the bearer: {"vessel": "weapon" | "ranged_weapon" | "armor", "name", "rows": [...]}.
    The rows' own ``vessel_*`` rows become the bearer's condition data; other rows run on the bearer."""
    from ..typed_executor import effect_expiry, run_effects
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    bearer = _subject(ctx)
    if bearer is None or not bearer.active:
        return
    weapon_id = ""
    if eff.get("vessel") != "armor":
        held = _weapons(ctx.engine, bearer, str(eff.get("vessel")))
        if not held:
            ctx.rider(f"{ctx.action.display_name}: {bearer.display_name} holds no weapon this table can name (the GM applies it).")
            return
        ids = sorted(held)
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "MANDATE_VESSEL", ctx.source, bearer.entity_id), ctx.actor,
                     CHOICE + "mandate_vessel", ids, labels={key: held[key].display_name for key in ids}, name=ctx.action.display_name,
                     prompt=f"{ctx.action.display_name}: choose the weapon of {bearer.display_name} that holds the Mandate.",
                     prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, bearer))
        weapon_id = (picked or ids[:1])[0]
    rule = {}
    rest = []
    rows = []
    for row in eff.get("rows") or []:
        rows.extend(choose(ctx, row) if row.get("type") == "mandate_choice" else [row])
    for row in rows:
        if row.get("type") == "vessel_rule":
            rule.update({key: value for key, value in row.items() if key not in ("type", "evidence")})
        else:
            rest.append(row)
    if rule:
        numbers = ctx.numbers
        for key in ("attack_bonus", "damage_bonus", "ac_bonus", "reduce_damage"):
            if rule.get(key) in ("pb", "half_pb", "key"):
                rule[key] = {"pb": int(numbers.get("pb") or 2), "half_pb": int(numbers.get("pb") or 2) // 2,
                             "key": int(numbers.get("key_mod") or 0)}[rule[key]]
        name = str(eff.get("name") or ctx.action.display_name)
        weapon_name = getattr(ctx.engine.action_catalog.get(weapon_id), "display_name", "armor") if weapon_id else "armor"
        ctx.engine._apply_condition(bearer, VESSEL, ctx.source, ctx.actor.entity_id,
                                    expires_on=effect_expiry(ctx, eff, bearer, condition=True),
                                    data={"weapon": weapon_id, "rule": {"mandate_vessel": rule}, "name": name,
                                          "label": f"{name} ({re.sub(r' attack$', '', weapon_name)})"})
    if rest:
        run_effects(ctx, rest)


def _vessel_rules(engine: Any, bearer: Any, ctx: Any = None, weapon: str | None = None) -> list[tuple[Any, dict[str, Any]]]:
    """The bearer's Mandate Vessel rules that apply to this attack's weapon (or every armor rule when ctx is None and
    ``weapon`` is None). ``weapon`` names the physical weapon of an attack the engine is rolling without a typed Context."""
    if ctx is not None:
        from .weapon_hits import weapon_identity

        weapon = weapon_identity(ctx)
    found = []
    for condition in bearer.conditions.values():
        if condition.condition_id != VESSEL:
            continue
        rule = ((condition.data or {}).get("rule") or {}).get("mandate_vessel") or {}
        vessel = str((condition.data or {}).get("weapon") or "")
        if (weapon is None and not vessel) or (weapon is not None and vessel and vessel == weapon):
            found.append((condition, rule))
    return found


def _once(bearer: Any, condition: Any, what: str) -> bool:
    key = f"mandate_once:{condition.source_definition_id}:{what}"
    if bearer.turn_flags.get(key):
        return False
    bearer.turn_flags[key] = True
    return True


@hook("attack_bonus")
def vessel_attack_bonus(ctx: Any, actor: Any) -> int | None:
    if not any(c.condition_id == VESSEL for c in ctx.actor.conditions.values()):
        return None
    total = sum(int(rule.get("attack_bonus") or 0) for _condition, rule in _vessel_rules(ctx.engine, ctx.actor, ctx))
    return total or None


@hook("attack_mode")
def vessel_attack_mode(ctx: Any, target: Any) -> str | None:
    if not any(c.condition_id == VESSEL for c in ctx.actor.conditions.values()):
        return None
    modes = {rule.get("attack_mode") for _condition, rule in _vessel_rules(ctx.engine, ctx.actor, ctx)} - {None}
    return next(iter(modes)) if len(modes) == 1 else None


@hook("attack_damage_bonus")
def vessel_damage_bonus(ctx: Any, target: Any, eff: dict[str, Any]) -> int | None:
    if not any(c.condition_id == VESSEL for c in ctx.actor.conditions.values()):
        return None
    total = 0
    for condition, rule in _vessel_rules(ctx.engine, ctx.actor, ctx):
        total += int(rule.get("damage_bonus") or 0)
        if rule.get("once_damage_bonus") and _once(ctx.actor, condition, "bonus"):
            value = rule["once_damage_bonus"]
            total += int(ctx.numbers.get("pb") or 2) if value == "pb" else int(ctx.numbers.get("key_mod") or 0) if value == "key" else int(value or 0)
        if rule.get("reduce_damage") and _once(ctx.actor, condition, "reduce"):
            total -= int(rule["reduce_damage"])
    return total or None


@hook("after_hit")
def vessel_extra_dice(ctx: Any, target: Any, kind: str) -> None:
    """"Once per turn, an attack with the Vessel deals an extra 1d6 damage of the chosen type" (Elemental Mantle)."""
    if not any(c.condition_id == VESSEL for c in ctx.actor.conditions.values()) or not target.active:
        return
    from ..gate2_runtime_models import DiceSpec

    for condition, rule in _vessel_rules(ctx.engine, ctx.actor, ctx):
        extra = rule.get("once_extra_dice")
        if not extra or not _once(ctx.actor, condition, "dice"):
            continue
        roll = ctx.engine.roller.roll(DiceSpec(count=int(extra["count"]), sides=int(extra["sides"]), modifier=0), actor_id=ctx.actor.entity_id,
                                      reason=f"DAMAGE:{condition.source_definition_id}:vessel")
        ctx.engine._record_roll(roll)
        ctx.engine._commit_damage(target, int(roll.total), str(extra.get("type") or "FORCE").upper(), f"{condition.source_definition_id}.vessel",
                                  ctx.actor.entity_id, None, reaction_depth=0)


@hook("ac")
def vessel_armor(engine: Any, target: Any) -> int:
    if not any(c.condition_id == VESSEL for c in target.conditions.values()):
        return 0
    return sum(int(rule.get("ac_bonus") or 0) for _condition, rule in _vessel_rules(engine, target))


# ------------------------------------------------------------------------------------------------ Sharpen and Dull on critical hits
def _attacked_weapon(engine: Any, actor: Any) -> str:
    """The physical weapon of the attack the engine is rolling right now, or "" (the `critical_range` and `critical_cancel`
    hooks get the attack's spec, not the typed Context that weapon_hits.weapon_identity reads)."""
    from ..weapon_delivery import physical_weapon_id

    frame = engine.d20_context() or {}
    source = str(frame.get("source_id") or "")
    if not source or frame.get("kind") not in ("attack", None):
        return ""
    action = engine.action_catalog.get(source)
    if action is None or action.owner_id != actor.entity_id:
        return ""
    typed = (action.parameters or {}).get("typed") or {}
    return physical_weapon_id(source, action.parameters) if typed.get("weapon") else ""


@hook("attack_critical_range")
def sharpen_critical_range(engine: Any, actor: Any, target: Any, spec: dict[str, Any]) -> int | None:
    """Sharpen: "attacks with the Vessel score a critical hit on a roll of 19 or 20." The engine widens the range of a
    confirmed hit (combat/critical_attacks.py lowest -> attack_critical_range), so this is the printed 19."""
    weapon = _attacked_weapon(engine, actor)
    if not weapon:
        return None
    return max([int(rule.get("critical_lowest") or 0) for _condition, rule in _vessel_rules(engine, actor, weapon=weapon)] or [0]) or None


@hook("critical_cancel")
def dull_no_critical(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], roll: Any, intent: Any) -> bool:
    """Dull: "attacks made with it cannot score critical hits." The engine asks before the damage roll and turns the
    confirmed critical into a normal hit (combat/critical_attacks.py resolve). No choice is offered: the printed rule
    removes the critical, it does not spend anything."""
    weapon = _attacked_weapon(engine, attacker)
    if not weapon:
        return False
    return any(rule.get("no_critical") for _condition, rule in _vessel_rules(engine, attacker, weapon=weapon))


_WHY_TEXT = {"RECHECK": "it survived the saving throw it was allowed to repeat",
             "COUNTERED": "another cultivator countered it",
             "FLOOR_SPENT": "its one replacement was used and nothing was spent to keep it",
             "MANDATE_LOAD": "it was the oldest of the caster's Mandates"}


def _expose_augment(engine: Any, subject: Any, ability: str) -> dict[str, Any] | None:
    """The augmented Expose Mandate whose printed Disadvantage is waiting on ``subject`` for this ability, or None.

    Read from the condition the Disadvantage actually left behind (``condition:typed.save_against``, applied by
    typed_executor.block_advantage and spent by combat/ext/save_against.py), then from that ability's own compiled rows:
    the Mandate is named "Expose" and carries the printed Augment. Nothing here is keyed on a talent id.
    """
    from ..typed_executor import is_active_typed_condition
    from .save_against import CONDITION

    code = str(ability or "").upper()[:3]
    for condition in subject.conditions.values():
        if condition.condition_id != CONDITION or not is_active_typed_condition(condition):
            continue
        rule = ((condition.data or {}).get("rule") or {}).get("save_against") or {}
        abilities = list(rule.get("abilities") or [])
        if rule.get("mode") != "DISADVANTAGE" or (abilities and code not in abilities):
            continue
        action = engine.action_catalog.get(condition.source_definition_id)
        typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
        if (typed.get("mandate") or {}).get("label") != "Expose" or not typed.get("augment"):
            continue
        return {"caster": condition.source_actor_id, "source": condition.source_definition_id,
                "dc": int((typed.get("numbers") or {}).get("save_dc") or 16)}
    return None


@hook("save", priority=-10)
def expose_marks_its_own_disadvantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Remember that this very saving throw is the one an augmented Expose made harder, so ``after_save`` knows the failure
    came from it. Returns nothing: the Disadvantage itself is the Mandate's own row, read and spent by save_against.

    ``priority=-10`` (the documented seam in ``ext/__init__.py``: a negative priority runs before ordinary observers) is
    required, not cosmetic. Expose's Disadvantage is a one-shot "next saving throw" condition, and ``save_against`` spends it
    during this same ``save`` run. At the default priority 0 this hook landed either side of that spender depending on which
    plug-in was imported first, so the Expose recheck silently never fired in some sessions (AUTO20 2026-10-04: importing
    ``tests/test_save_against.py`` first was enough to stop it). Running ahead of the spender makes it deterministic.
    """
    if subject is None or subject.active:
        found = _expose_augment(ctx.engine, subject, ability)
        if found is not None:
            ctx.damage_cache[("expose_recheck", subject.entity_id, str(ability or "").upper()[:3])] = found
    return None


@hook("after_save")
def expose_recheck(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Expose's Augment (2 CP): "each time the target fails a saving throw because of this Disadvantage, it may repeat the
    Wisdom saving throw against this Mandate, ending it on a success."

    Only a failure on a save an augmented Expose actually worsened opens the way out (``save`` above marks it), so a
    saving throw the Mandate did not touch never does. The repeat is the target's choice: asked for a player, answered for
    the AI, and a decline leaves the failure standing.
    """
    from . import needle

    engine = ctx.engine
    if not failed or subject is None or not subject.active:
        return
    mandate = ctx.damage_cache.pop(("expose_recheck", subject.entity_id, str(ability or "").upper()[:3]), None)
    if mandate is None:
        return
    caster = engine.state.actors.get(mandate["caster"]) or ctx.actor
    source, dc = str(mandate["source"]), int(mandate["dc"])
    picked = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "EXPOSE_RECHECK", source, subject.entity_id),
                        subject, needle.CHOICE + "expose_recheck", ["repeat", "accept"],
                        labels={"repeat": f"Repeat the Wisdom saving throw against {caster.display_name}'s Expose "
                                        f"(the Mandate ends on a success, DC {dc})",
                                "accept": "Accept the failure; the Mandate continues"},
                        preferred=["repeat"], allow_decline=True, name="Expose: repeat the saving throw",
                        prompt=(f"{caster.display_name}'s Expose is what made this {ability} saving throw harder. "
                                f"{subject.display_name} may repeat the Wisdom saving throw against that Mandate and end it on a success."),
                        automatic=subject.team_id != caster.team_id, default="accept", target_id=caster.entity_id)
    if not picked or picked[0] != "repeat":
        return
    roll = engine._roll_save(subject, "WIS", dc, source, roll_context={"source_actor_id": caster.entity_id,
                                                                       "named": ["expose"]})
    if roll.total >= dc:
        _end_mandate(engine, caster, source, subject, "RECHECK")
    else:
        note(engine, source, subject, f"{subject.display_name}'s repeated Wisdom saving throw fails; Expose holds.", (caster,))


def _end_mandate(engine: Any, caster: Any, source: str, subject: Any, why: str) -> None:
    """End one Mandate on one creature: its Concentration first, then anything of it that outlasted that Concentration
    (the same removal Counter-Mandate uses). ``why`` is the engine's own reason code; the line the players read is
    ``_WHY_TEXT``, so an internal code never reaches the log (AUTO20f1: "Mandate ends (recheck)" did)."""
    from .. import concentration

    if caster.concentration is not None and caster.concentration.source_definition_id == source:
        engine._end_concentration(caster, why)
    else:
        for iid, state in concentration.held(caster):
            if state.source_definition_id == source:
                concentration.end_held(engine, caster, iid, why)
                break
    for iid, condition in list(subject.conditions.items()):
        if condition.source_definition_id == source:
            engine._remove_condition(subject, condition.condition_id, source)
    for mid, modifier in list(subject.modifiers.items()):
        if modifier.source_definition_id == source:
            subject.modifiers.pop(mid)
            engine._append_event("MODIFIER_REMOVED", source, actor_id=caster.entity_id, target_ids=(subject.entity_id,),
                                 payload={"modifier_id": mid, "reason": why})
    note(engine, source, subject,
         f"{subject.display_name}'s Mandate ends ({_WHY_TEXT.get(why, 'it is no longer in effect')}).", (caster,))


@hook("damage_reduction")
def vessel_guard(engine: Any, target: Any, damage_type: str, typed: dict[str, Any], source_actor_id: str | None, applied: bool = False) -> int:
    """Guardian Shell: "the bearer reduces incoming damage by your Proficiency Bonus once per round"."""
    if not any(c.condition_id == VESSEL for c in target.conditions.values()):
        return 0
    flag = f"mandate_guard_round_{engine.state.round_number}"
    amount = max([int(rule.get("reduce_incoming") or 0) for _condition, rule in _vessel_rules(engine, target)] or [0])
    if not amount or target.turn_flags.get(flag):
        return 0
    if applied:
        target.turn_flags[flag] = True
    return amount


def _court_temp_hp(ctx: Any, mandate: dict[str, Any] | None = None) -> None:
    """Court of Ten Thousand Mandates: "when a willing creature inside the Court receives one of your Imbue Mandates, it gains
    temporary hit points equal to your key ability modifier".

    ``mandate`` names the Mandate actually landing, when it is not this button's own: the Court's free Mandate button is
    ``court_free``, but the Mandate it places is still one of your Imbue Mandates, so it earns the same temporary hit points
    when it is a Place Mandate on a willing creature inside the Court."""
    target = _subject(ctx)
    if (mandate if mandate is not None else ctx.typed.get("mandate") or {}).get("side") != "imbue" \
            or target is None or not target.active:
        return
    engine, actor = ctx.engine, ctx.actor
    zone = _court(engine, actor)
    if zone is None or not _inside_court(engine, actor, zone, target):
        return
    row = _court_row(engine, zone)
    if row.get("temp_hp"):
        amount = int(ctx.numbers.get("key_mod") or 0)
        if amount > 0:
            engine._grant_temp_hp(target, amount, zone.source_definition_id, actor.entity_id)


# ------------------------------------------------------------------------------------------------ the Court's free Mandate
COURT_FREE = "condition:typed.imbuement_court_family"
_FREE_FLAG = "imbuement_court_free_mandate"


def _known_families(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    """{talent id: its Place/Fray Mandate buttons}: a printed Mandate family is the talent its options come from
    ("Sharpen and Dull" holds Sharpen and Dull), read from each button's own typed source, so no family name is written here."""
    found: dict[str, dict[str, Any]] = {}
    for key, action in sorted(engine.action_catalog.items()):
        typed = (action.parameters or {}).get("typed") or {}
        side = (typed.get("mandate") or {}).get("side")
        if action.owner_id != actor.entity_id or side not in ("imbue", "fray") or typed.get("sphere") != IMBUEMENT:
            continue
        source = str(typed.get("source") or "")
        if not source.startswith("tianxia.talent.") or key.endswith((".augmented", ".twin_fray", ".layered")):
            continue  # a composite button (Twin Fray, Layered Mandate) is not a Mandate family of its own
        found.setdefault(source, {})[key] = action
    return found


def _family_label(row: dict[str, Any]) -> str:
    """A family as the sheet prints its options ("Sharpen or Dull"), from the buttons' own names."""
    names = sorted({str(action.display_name).split(": ", 1)[-1] for action in row.values()})
    return " or ".join(names)


def _legal_on(engine: Any, caster: Any, action: Any, target: Any) -> bool:
    """Whether the caster may aim this Mandate button at ``target``: the button's own printed target rule, read from the
    ``target_kind`` the compiler gave it (a Place Mandate "can target one willing creature" is ``ALLY_OR_SELF``; a Fray
    Mandate "can target one creature" is ``HOSTILE_ENTITY``).

    The Court's free button is ``ANY_CREATURE``, because the Court allows either kind -- but the Court does not override the
    Mandate's own target rule, so the chosen option is still held to it (AUTO20f1: running a Place Mandate's rows on a
    hostile, or a Fray Mandate's on an ally, put a Mandate where its own button would never have offered one)."""
    from ..relations import ALLY, relation

    kind = str(getattr(action, "target_kind", "") or "ANY_CREATURE")
    if kind.endswith("ALLY_OR_SELF"):
        return relation(engine, target, caster) == ALLY
    if kind.startswith("HOSTILE_ENTITY"):
        return relation(engine, target, caster) != ALLY
    return True


def _free_options(engine: Any, caster: Any, family: str, target: Any) -> dict[str, Any]:
    """The chosen family's buttons that may be aimed at ``target``."""
    families = _known_families(engine, caster)
    row = families.get(family) or {}
    return {key: action for key, action in row.items() if _legal_on(engine, caster, action, target)}


@hook("technique_used")
def court_family_choice(ctx: Any) -> None:
    """"When you create the Court, choose one Mandate family you know": asked once, as the Court is created, and
    remembered on the caster (a string, so it survives a table commit) for exactly as long as that Court stands.

    Creation-only, and never keyed on a talent id: the choice belongs to the Court that was just made, so it runs only
    when the technique that was used is the one whose area now stands. (AUTO20f1: asking on every ``technique_used`` re-asked
    the question every turn and let the stored family change mid-fight, which the printed "When you create the Court" does not
    allow. ``court_family_ends`` below takes the answer away again when the Court ends.)"""
    engine, actor = ctx.engine, ctx.actor
    zone = _court(engine, actor)
    families = _known_families(engine, actor)
    if zone is None or not families or zone.source_definition_id != ctx.source:
        return
    source = zone.source_definition_id
    labels = {key: _family_label(row) for key, row in sorted(families.items())}
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    order = list(labels)
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "COURT_FAMILY", source, actor.entity_id), actor,
                 CHOICE + "court_family", order, labels=labels, preferred=order[:1], name="Court of Ten Thousand Mandates",
                 prompt=("Your Court of Ten Thousand Mandates is up. Which Mandate family may you use from it once each turn "
                         "without spending an Action?"),
                 prompt_context=action_context(engine, actor, ctx.source, actor))
    family = (picked or order[:1])[0]
    for condition in list(actor.conditions.values()):
        if condition.condition_id == COURT_FREE:
            engine._remove_condition(actor, condition.condition_id, source)
    engine._apply_condition(actor, COURT_FREE, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"family": family, "label": f"Court of Ten Thousand Mandates ({labels[family]})",
                                  "reading": f"Once on each of your turns you may use one {labels[family]} Mandate from this Court without "
                                             "spending an Action, on a creature inside the Court."})
    note(engine, source, actor, f"The Court's free Mandate each turn is {labels[family]}.", ())


@hook("event")
def court_family_ends(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The chosen family is part of the Court, so it ends with it: the Court running out of rounds, its Concentration
    breaking and anything else that removes the area all fire ``ZONE_REMOVED`` (combat/zones.py remove), and the answer
    goes with it. Without this the condition outlived its Court (``UNTIL_REMOVED``), so the sheet still showed a free
    Mandate the caster could not use and a new Court silently reused the old answer."""
    if event_type != "ZONE_REMOVED":
        return
    zone_id = str((kwargs.get("payload") or {}).get("zone_id") or "")
    source = str(kwargs.get("source_definition_id") or "")
    for actor in list(engine.state.actors.values()):
        for condition in list(actor.conditions.values()):
            if condition.condition_id != COURT_FREE or condition.source_actor_id != actor.entity_id:
                continue
            zone = engine.state.zones.get(zone_id)
            if zone is None or zone.source_definition_id != condition.source_definition_id or source != zone.source_definition_id:
                continue
            engine._remove_condition(actor, condition.condition_id, condition.source_definition_id)


def _family(engine: Any, actor: Any) -> str | None:
    """The Court family already chosen (asked once, as the Court was created)."""
    for condition in actor.conditions.values():
        if condition.condition_id == COURT_FREE and (condition.data or {}).get("family"):
            return str(condition.data["family"])
    return None


@hook("candidate_allowed")
def court_free_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The free Mandate is offered only while the caster's own Court stands, once each of their turns, only on a creature
    inside it, and only where at least one option of the chosen family is a legal target there."""
    if action is None or not (action.parameters or {}).get("court_free_mandate"):
        return None
    zone = _court(engine, actor)
    family = _family(engine, actor)
    if zone is None or not family or actor.turn_flags.get(f"{_FREE_FLAG}:{engine.state.round_number}"):
        return False
    targets = [engine.state.actors.get(entity_id) for entity_id in (getattr(candidate, "target_ids", None) or ())]
    targets = [target for target in targets if target is not None and target.active]
    if not targets:
        return False
    if not all(_inside_court(engine, actor, zone, target) for target in targets):
        return False
    return all(_free_options(engine, actor, family, target) for target in targets)


@effect("court_free_mandate")
def court_free_mandate(ctx: Any, eff: dict[str, Any]) -> None:
    """One Place Mandate or Fray Mandate from the chosen family, on the creature the free button was aimed at, without
    spending an Action. The chosen button's own rows run, so what lands is the printed Mandate, save and all.

    Those rows run in *this* context, not a copy of the chosen button's (AUTO20f1): the free button is what the table
    charged for and what the caster is Concentrating on, so the Mandate it places belongs to the free button too. Running a
    second context left the placed Mandate owned by its own button while the Concentration sat on the free one, so dropping
    Concentration left the Mandate running and nothing could end it.
    """
    from ..typed_executor import run_effects
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    target = _subject(ctx)
    zone, family = _court(engine, actor), _family(engine, actor)
    if target is None or not target.active or zone is None or not _inside_court(engine, actor, zone, target):
        return
    options = _free_options(engine, actor, str(family or ""), target)
    if not options:
        return
    ids = list(options)
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "COURT_FREE_MANDATE", ctx.source, target.entity_id), actor,
                 CHOICE + "court_free_mandate", ids, labels={key: options[key].display_name for key in ids},
                 preferred=ids[:1], name="Free Mandate", minimum=1, maximum=1,
                 prompt=(f"Your Court's free Mandate each turn ({_family_label(options)}): choose the Mandate to place on "
                         f"{target.display_name} without spending an Action."),
                 prompt_context=action_context(engine, actor, ctx.source, target))
    chosen = next((options[key] for key in ids if picked and key == picked[0]), None) or options[ids[0]]
    run_effects(ctx, copy.deepcopy((chosen.parameters or {}).get("typed", {}).get("effects") or []))
    _court_temp_hp(ctx, ((chosen.parameters or {}).get("typed") or {}).get("mandate") or {})
    ctx.rider(f"{chosen.display_name} from the Court's free Mandate ({_family_label(options)}) reaches "
              f"{target.display_name}: it costs no Action.")
    actor.turn_flags[f"{_FREE_FLAG}:{engine.state.round_number}"] = True


# ------------------------------------------------------------------------------------------------ Mandate Load
@hook("technique_used")
def mandate_load(ctx: Any) -> None:
    """Placing a Mandate beyond your Load ends the oldest one you hold."""
    if not ctx.typed.get("mandate"):
        return
    from .. import concentration

    engine, actor = ctx.engine, ctx.actor
    from .persist_augment import MANDATE, end_persisted, persisted

    held = [(iid, state) for iid, state in concentration.held(actor)
            if ((getattr(engine.action_catalog.get(state.source_definition_id), "parameters", None) or {}).get("typed") or {}).get("mandate")]
    # A set Mandate (Set Mandate, combat/ext/persist_augment.py) "still counts against Mandate Load".
    kept = persisted(engine, actor, MANDATE)
    current = 1 if actor.concentration is not None and actor.concentration.source_definition_id == ctx.source else 0
    _court_temp_hp(ctx)
    extra = len(held) + len(kept) + current - load(engine, actor, int(ctx.numbers.get("pb") or 2))
    oldest = sorted([(int(state.started_sequence), "held", iid, state.source_definition_id) for iid, state in held]
                    + [(int((row.data or {}).get("started") or 0), "set", iid, row.source_definition_id) for iid, row in kept])
    for _started, kind, iid, source in oldest[:max(0, extra)]:
        name = getattr(engine.action_catalog.get(source), "display_name", "a Mandate")
        if kind == "held":
            concentration.end_held(engine, actor, iid, "MANDATE_LOAD")
        else:
            end_persisted(engine, actor, iid, ctx.source, "MANDATE_LOAD")
        ctx.rider(f"Mandate Load: {name} ends (the oldest of your Mandates).")
