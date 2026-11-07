"""Choose-N menus (owner 2026-09-29: "i want everything we can automated"; BLOCKED_SYSTEMS.md "choose-N menus").
Shared public helpers serve Iron Fist riders, Forms, Diagnosis and their placement/menu consumers.

Printed abilities that say "Choose three effects:" / "each target may choose two:" / "choose three Former-Life Mantles" list
their options and let the user take exactly N of them.  The existing "Choose one" ability (factory_compiler, one action per
option) cannot express that: N of M would be dozens of actions.  Here the ability stays ONE action and its typed effects are
tagged with the option they belong to:

    {"type": "menu", "id": "<menu id>", "count": 3, "label": "Choose three effects", "options": ["A", "B", ...],
     "default": ["A", "B", "C"], "cast_only": true}          the menu itself (first in the ability's effects)
    {"type": "condition", ..., "menu": "<menu id>", "option": "A"}   an effect that runs only when option A is picked
    {..., "menu": "<menu id>", "option": "A", "menu_success": true}  the same on the "Successful Save: Choose one" branch: it runs
                                     for the first picked option (in printed order, among the menu's ``success_options``) only

A fighter's picks are a free choice kept until changed (like Shape Darkness and the augments): one free button per option,
"Choose <ability>: <option>" -- picking one that is not chosen replaces the one chosen longest ago, so exactly N stay chosen.
Nothing chosen (the AI, or a player who never opened it) means the ``default`` list, else the first N options.

A zone's menu options can also change the area itself: the ``zone`` effect lists ``menu_parts`` -- {"menu", "option",
"difficult", "obscured", "inside": [...], "triggers": [...]} -- and the area made carries the parts of the picked options
only (combat/zones.py create -> ``zone_parts`` below).  The picks are frozen when the area is made.

Rules sources are named at each typed entry (authority/typed_mechanics/reviewed_final.d/sys_menus-forms.json).
Shared preference helper: effect_choices uses public picks() for AI/default
post-resolution selections; it still asks player owners after the trigger.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

MENU = "condition:typed.menu"


def _walk(effects: Any):
    for row in effects or []:
        if isinstance(row, dict):
            yield row
            for key in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _walk(row.get(key))


def catalog(engine: Any) -> dict[str, dict[str, Any]]:
    """{menu id: its menu row}, read once from the action catalog."""
    cached = engine.__dict__.get("_menu_catalog")
    if cached is None:
        cached = {}
        for action in engine.action_catalog.values():
            for row in _walk(((action.parameters or {}).get("typed") or {}).get("effects")):
                if row.get("type") == "menu" and row.get("id"):
                    cached.setdefault(str(row["id"]), row)
            row = (action.parameters or {}).get("menu_row")  # a menu of a passive feature, carried by its own buttons (combat/ext/mantles.py)
            if row and row.get("id"):
                cached.setdefault(str(row["id"]), row)
        engine.__dict__["_menu_catalog"] = cached
    return cached


def _stored(actor: Any, menu_id: str) -> list[str] | None:
    for condition in actor.conditions.values():
        if condition.condition_id == MENU and (condition.data or {}).get("menu") == menu_id:
            return list((condition.data or {}).get("picks") or [])
    return None


def default_picks(menu: dict[str, Any]) -> list[str]:
    options = [str(label) for label in menu.get("options") or []]
    count = int(menu.get("count") or len(options))
    return list(dict.fromkeys(label for label in [*(menu.get("default") or []), *options] if label in options))[:count]


def picks(engine: Any, actor: Any, menu_id: str) -> list[str]:
    menu = catalog(engine).get(menu_id)
    if menu is None:
        return []
    stored = _stored(actor, menu_id)
    options = [str(label) for label in menu.get("options") or []]
    chosen = [label for label in stored if label in options] if stored is not None else default_picks(menu)
    return list(dict.fromkeys(chosen))[: int(menu.get("count") or len(options))]


def picked(ctx: Any, row: dict[str, Any]) -> bool:
    """Whether an effect tagged with a menu option runs now (run_effects): its option is one of its user's picks.

    ``menu_success``: the effect is what a successful save (or a miss) still leaves -- "Successful Save: Choose one."  Nothing
    printed says which of the picks the user takes then, so it is the first one, in the order the options are printed, that the
    menu's ``success_options`` (every option unless the text excludes some: "other than Stunned") allows."""
    menu_id, option = str(row.get("menu")), str(row.get("option"))
    chosen = picks(ctx.engine, ctx.actor, menu_id)
    if not row.get("menu_success"):
        return option in chosen
    menu = catalog(ctx.engine).get(menu_id) or {}
    allowed = menu.get("success_options") or menu.get("options") or []
    first = next((label for label in allowed if label in chosen), None)
    return first == option


def pick(engine: Any, actor: Any, menu_id: str, option: str, source: str) -> list[str]:
    """Choose an option: it replaces the pick chosen longest ago when N are already chosen."""
    menu = catalog(engine).get(menu_id)
    if menu is None or option not in (menu.get("options") or []):
        return []
    now = picks(engine, actor, menu_id)
    if option in now:
        return now
    count = int(menu.get("count") or len(now) + 1)
    now = [*now, option][-count:]
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id == MENU and (condition.data or {}).get("menu") == menu_id:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid})
    engine._apply_condition(actor, MENU, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"menu": menu_id, "menu_name": menu.get("name"), "picks": now,
                                  "label": f"{menu.get('name') or menu_id}: {'; '.join(now)}"})
    return now


def line(menu: dict[str, Any], chosen: list[str]) -> str:
    return f"{menu.get('name') or 'Choices'} ({menu.get('label') or 'chosen'}): {'; '.join(chosen)}."


@effect("menu")
def run_menu(ctx: Any, eff: dict[str, Any]) -> None:
    """The menu's own line: what was chosen (the tagged effects that follow run only for those)."""
    chosen = picks(ctx.engine, ctx.actor, str(eff.get("id")))
    ctx.rider(line(eff, chosen))
    for label in chosen:  # an option the table cannot run for itself is a GM line, said only when it was picked
        if (eff.get("gm") or {}).get(label):
            ctx.rider(f"{label}: {eff['gm'][label]}")


@effect("menu_pick")
def run_pick(ctx: Any, eff: dict[str, Any]) -> None:
    chosen = pick(ctx.engine, ctx.actor, str(eff.get("menu")), str(eff.get("option")), ctx.source)
    menu = catalog(ctx.engine).get(str(eff.get("menu"))) or {}
    ctx.rider(f"{menu.get('name') or 'Choices'}: {'; '.join(chosen)}." if chosen else "That is not one of the choices.")


@hook("button_selection")
def menu_selection(parameters: dict[str, Any]) -> dict[str, Any] | None:
    pick = next((eff for eff in (parameters.get("typed") or {}).get("effects") or [] if eff.get("type") == "menu_pick"), None)
    return {"condition": MENU, "equals": {"menu": pick["menu"]}, "contains": {"picks": pick["option"]}} if pick else None


def toggle_actions(info: dict[str, Any], row: dict[str, Any], *, carry: bool = False) -> list[Any]:
    """A free button "Choose <name>: <option>" for each option of one menu row.  ``carry``: the menu belongs to a passive feature that
    has no action of its own, so the buttons carry the menu row (``parameters.menu_row``) for ``catalog`` to find."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    out = []
    for label in row.get("options") or []:
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.menu.{_slug(row['id'])}.{_slug(label)}",
            display_name=f"Choose {row.get('name')}: {label}", owner_id=info["actor_id"], economy=EconomyKind.NONE,
            resolution_kind="TYPED", target_kind="SELF",
            parameters={"setting_only": True, "typed": {"effects": [{"type": "menu_pick", "menu": row["id"], "option": label}], "numbers": info["numbers"],
                                  "duration": {"kind": "instant"}, "riders": []},
                        "expected_damage": 0, "player_only": True, "menu_toggle": row["id"], "menu_option": label,
                        **({"menu_row": row} if carry else {}),
                        "description": f"{row.get('label') or 'Choose'} for your next {row.get('name')} (free; it stays until you change it). "
                                       f"Choosing one that is not chosen replaces the one chosen longest ago."}))
    return out


@hook("compile_actions")
def toggles(info: dict[str, Any]) -> list[Any] | None:
    """A free button for each option of each menu the character's own abilities carry."""
    out = []
    seen: set[str] = set()
    for mechanic_id in info["owned_ids"]:
        mechanic = info["mechanics"].get(mechanic_id) or {}
        rows = [*(mechanic.get("effects") or []), *((mechanic.get("modifier") or {}).get("effects") or []),
                *[row for option in mechanic.get("options") or [] for row in option.get("effects") or []]]  # a Talent's own menu (Bell-Ringing Body Shot)
        for row in _walk(rows):
            if row.get("type") != "menu" or not row.get("id") or row["id"] in seen:
                continue
            seen.add(row["id"])
            # Reactions and triggered No Action abilities have no cast action for catalog to read.
            out.extend(toggle_actions(info, row, carry=(mechanic.get("activation") or {}).get("economy") in ("reaction", "no_action")))
    return out or None


def _slug(text: Any) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def zone_parts(ctx: Any, spec: dict[str, Any]) -> dict[str, Any]:
    """The zone spec with the parts of the picked options merged in (combat/zones.py create)."""
    parts = spec.get("menu_parts") or []
    if not parts:
        return spec
    chosen = {(str(part.get("menu")), str(part.get("option"))) for part in parts
              if str(part.get("option")) in picks(ctx.engine, ctx.actor, str(part.get("menu")))}
    live = [part for part in parts if (str(part.get("menu")), str(part.get("option"))) in chosen]
    out = {key: value for key, value in spec.items() if key != "menu_parts"}
    for part in live:
        if part.get("difficult") and not out.get("difficult"):
            out["difficult"] = part["difficult"]
        if part.get("obscured") and not out.get("obscured"):
            out["obscured"] = part["obscured"]
    out["inside"] = [*(spec.get("inside") or []), *[copy.deepcopy(rule) for part in live for rule in part.get("inside") or []]]
    out["triggers"] = [*(spec.get("triggers") or []), *[copy.deepcopy(trigger) for part in live for trigger in part.get("triggers") or []]]
    return out
