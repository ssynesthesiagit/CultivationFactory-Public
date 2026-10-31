"""The after-roll window of a journey check: "add a die after the d20, before the result is declared".

Combat has this window already: ``d20_bonus`` runs after the d20 is drawn and before the outcome is consumed, the roller sees
the roll, a player-owned bonus is asked and an AI owner decides for itself (combat/ext/sect_stewardship.py
``after_roll_merit`` is the model). The journey has no ask, so the same contract is a saved state:

* Opens: a journey check (the consumer) rolls its d20 and calls ``open_window`` with the roll, the DC and whether the DC is
  known to the roller. ``journey_roll_offers(session, window)`` is asked once for everything that could be added now; each
  offer is a die or flat bonus with its cost and a one-per-roll ``group`` (printed "you cannot add more than one ...").
* Sees: the owner sees the roll's total, its natural d20, and the DC only when ``dc_known`` is set; everyone else sees
  nothing of a check whose DC its owner does not know (``journey_view``): the recorded task keeps no such DC, and the
  events of that check carry no total, no natural die and no outcome for anyone but its owner. The offers are recomputed
  against the running total after every addition, like ``d20_bonus``.
* Decides: a manual owner answers with the ``roll_decide`` command (an offer id, or empty to decline); until then that creature's
  other journey commands are refused (journey.JourneySession.command), so nothing is done with a roll whose result is not yet
  declared. The scenario owner has one way out: the ``cancel_check`` fact closes an open window and settles the roll with
  the total it already has. A LOCAL_AUTO owner decides at once: it adds the cheapest offer that can still turn a failure it can see into a
  success, and otherwise declines. Nobody is asked about a roll that has no offer.
* Closes: when the owner declines, or no offer is left, ``journey_roll_finish(session, actor_id, window)`` runs for the consumer
  that opened it, with the final total. Dice go through a saved-counter roller, so cold replay repeats them.

``journey_roll_offers`` and ``journey_roll_finish`` are the hooks; ``roll_check`` is the generic journey ability check a GM
calls for (``check_task`` fact) so any ability check talent has a roll to attach to. Shared helper ``open_window``; consumers:
combat/ext/thread_handling.py (Threadwork's difficult check) and this module's ``roll_check``. Pending state is the actor's
``pending_roll`` and lives only for the open window.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from . import hook, query, run_strict
from ..journey import integer, require

RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "journey_rolls.json"
_CACHE: dict = {}
ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")


def rules() -> dict:
    mtime = RULES_PATH.stat().st_mtime_ns
    if _CACHE.get("mtime") != mtime:
        _CACHE.update(mtime=mtime, data=json.loads(RULES_PATH.read_text(encoding="utf-8")))
    return _CACHE["data"]


def _owned(session, aid) -> set:
    return set(session.state["actors"][aid]["bundle"].get("journey_rolls", {}).get("owned", ()))


def _cp_resource(session, aid) -> str:
    primary = session.state["actors"][aid]["bundle"].get("journey_rolls", {}).get("primary", "qi")
    return rules()["cp_resources"][str(primary).lower()]


@hook("compile_bundle")
def seal(bundle, info):
    """Seal what a journey check needs for owners of an adding feature; never grants a feature."""
    ids = set(info["owned_ids"]) & {row["feature"] for row in rules()["adders"]}
    if not ids:
        return None
    return {**bundle, "journey_rolls": {"owned": sorted(ids), "primary": info["primary"], "pb": int(info["numbers"].get("pb", 0)),
                                        "ability_mods": dict(info["mods"])}}


def _cost(session, aid, row) -> list:
    cost = row["cost"]
    return [[_cp_resource(session, aid) if "cp" in cost else cost["resource"], cost.get("cp", cost.get("amount", 0))]]


def _pool_die_faces(actor, row) -> int:
    """The size of the pool die a row spends, inside the printed bounds.

    A Merit Die is a d4 that grows one step at a time to a maximum of d10
    (combat/ext/sect_stewardship.py, ``merit_die_faces``); a stored pool outside those bounds
    must never offer a d0 or a d99.
    """
    from .sect_stewardship import merit_die_faces
    return merit_die_faces(actor["resources"].get(row["sides_from"]))


def _fits(row, window) -> bool:
    context = window["context"]
    return (not row.get("abilities") or context.get("ability") in row["abilities"]) \
        and (not row.get("tags_any") or set(row["tags_any"]) & set(context.get("tags", ())))


@hook("journey_roll_offers")
def offers(session, window):
    """This module's own rows: owned feature, a check it names, the cost affordable, its group not yet used on this roll."""
    aid, actor = window["actor_id"], session.state["actors"][window["actor_id"]]
    used = {entry["group"] for entry in window["added"]}
    result = []
    for row in rules()["adders"]:
        if row["feature"] not in _owned(session, aid) or row["group"] in used or not _fits(row, window):
            continue
        cost = _cost(session, aid, row)
        if any(actor["resources"].get(resource, 0) < amount for resource, amount in cost):
            continue
        sides = row.get("sides") or _pool_die_faces(actor, row)
        result.append({"id": row["id"], "label": row["label"], "sides": sides, "cost": cost, "group": row["group"]})
    return result


def _die(session, aid, sides: int, reason: str) -> int:
    from ..gate2_rolls import DeterministicRollAuthority
    from ..gate2_runtime_models import DiceSpec

    store = session.state["actors"][aid].setdefault("material_preparation", {})
    roller = DeterministicRollAuthority(json.dumps([session.state["journey_id"], aid, "afterroll"]))
    roller.counter = store.get("journey_roll_counter", 0)
    roll = roller.roll(DiceSpec(count=1, sides=sides, modifier=0), actor_id=aid, reason=reason)
    store["journey_roll_counter"] = roller.counter
    return int(roll.total)


def _all_offers(session, window) -> list:
    return [offer for reply in query("journey_roll_offers", session, window) for offer in (reply or ())]


def _apply(session, aid, window, offer) -> None:
    actor = session.state["actors"][aid]
    for resource, amount in offer["cost"]:
        require(actor["resources"].get(resource, 0) >= amount, "You cannot pay for that.")
        actor["resources"][resource] -= amount
    value = _die(session, aid, offer["sides"], "AFTERROLL:" + offer["id"])
    window["total"] += value
    window["added"].append({"offer": offer["id"], "group": offer["group"], "value": value})
    session.emit("ROLL_BONUS_ADDED", aid, offer=offer["id"], value=value, sides=offer["sides"],
                  dc_known=int(window["dc_known"]))


def _auto_pick(window, offers_now):
    """A seat that decides for itself: only a failure it can see, and the cheapest offer that could still reach the DC."""
    if not window["dc_known"] or window["total"] >= window["dc"]:
        return None
    useful = [o for o in offers_now if window["total"] + o["sides"] >= window["dc"]]
    return min(useful, key=lambda o: (sum(a for _, a in o["cost"]), o["sides"]), default=None)


def open_window(session, aid, *, consumer: str, roll: dict, dc: int, dc_known: bool, context: dict, data: dict | None = None) -> bool:
    """Open the window for a rolled check. True when it closed at once, False when the owner has to decide."""
    window = {"consumer": consumer, "actor_id": aid, "roll": roll, "total": int(roll["total"]), "natural": roll.get("natural_result"),
              "dc": int(dc), "dc_known": int(bool(dc_known)), "context": context, "added": [], "data": dict(data or {})}
    return _advance(session, aid, window)


def _advance(session, aid, window) -> bool:
    actor = session.state["actors"][aid]
    current = _all_offers(session, window)
    if current and actor["control_mode"] == "LOCAL_AUTO":
        while current:
            pick = _auto_pick(window, current)
            if pick is None:
                break
            _apply(session, aid, window, pick)
            current = _all_offers(session, window)
        current = []
    if current:
        actor["pending_roll"] = {**window, "offers": current}
        session.emit("ROLL_WINDOW_OPENED", aid, consumer=window["consumer"], dc_known=int(window["dc_known"]))
        return False
    actor.pop("pending_roll", None)
    window["added"] = list(window["added"])
    handled = run_strict("journey_roll_finish", session, aid, window)
    require(any(reply is True for reply in handled), "Nothing finished that roll.")
    return True


@hook("journey_command")
def command(session, aid, kind, payload):
    if kind == "roll_check":
        return _roll_check(session, aid, payload)
    if kind != "roll_decide":
        return None
    actor = session.state["actors"][aid]
    pending = actor.get("pending_roll")
    require(pending is not None and set(payload) == {"offer"} and isinstance(payload["offer"], str), "There is no open roll to decide.")
    window = {key: value for key, value in pending.items() if key != "offers"}
    if payload["offer"]:
        offer = next((o for o in pending["offers"] if o["id"] == payload["offer"]), None)
        require(offer is not None, "Choose one of the offered additions, or decline.")
        _apply(session, aid, window, offer)
        actor.pop("pending_roll", None)
        _advance(session, aid, window)
    else:
        session.emit("ROLL_BONUS_DECLINED", aid, consumer=window["consumer"], dc_known=int(window["dc_known"]))
        actor.pop("pending_roll", None)
        window["declined"] = 1
        # Closing: no further offers are asked of a declined window.
        handled = run_strict("journey_roll_finish", session, aid, window)
        require(any(reply is True for reply in handled), "Nothing finished that roll.")
    return True


@hook("journey_options")
def options(session, aid):
    pending = session.state["actors"][aid].get("pending_roll")
    if pending is None:
        return None
    actor_name = session.state["actors"][aid]["name"]
    check_name = pending["context"].get("description", "Threadwork check")
    offered_names = ", ".join(o["label"].split(":")[0] for o in pending["offers"])
    rows = [{"id": "rolldecide:" + o["id"], "kind": "roll_decide", "auto_select": 0, "payload": {"offer": o["id"]},
             "label": f"{actor_name}'s {check_name}: roll {pending['total']}" + (f" against DC {pending['dc']}" if pending["dc_known"] else "")
             + f". {o['label']} (a d{o['sides']}, after the d20, before the result is declared)."} for o in pending["offers"]]
    rows.append({"id": "rolldecide:none", "kind": "roll_decide", "auto_select": 0, "payload": {"offer": ""},
                 "label": f"{actor_name}'s {check_name}: decline {offered_names} and keep the roll ({pending['total']})."})
    return rows


@hook("journey_view")
def view(state, viewer_id):
    """Redact this plug-in's private check facts.

    A check whose DC its owner does not know is that owner's business: the recorded task
    carries no DC for anyone, and the events of that check (the roll, the added die, the
    outcome) are shown to its owner alone. A check with a known DC stays open to the table.
    """
    if not any("pending_roll" in a or "check_tasks" in a for a in state["actors"].values()):
        return None
    out = deepcopy(state)
    for aid, actor in out["actors"].items():
        pending = actor.pop("pending_roll", None)
        if pending is not None and aid == viewer_id:
            if not pending["dc_known"]:
                pending["dc"] = None
            actor["pending_roll"] = pending
        for task in (actor.get("check_tasks") or {}).values():
            if not task.get("dc_known"):
                task["dc"] = None
    out["events"] = [event for event in out["events"]
                     if event.get("dc_known", 1) or event["actor_id"] == viewer_id]
    return out


@hook("journey_admission")
def admit_task(session, aid, kind, payload, reason):
    """A GM-called ability check: ability, DC, whether the roller knows it, and the named situation tags."""
    if kind != "check_task":
        return None
    require("journey_rolls" in session.state["actors"][aid]["bundle"], "This creature has no feature that adds to journey checks.")
    require(set(payload) == {"id", "description", "ability", "dc", "dc_known", "tags", "proficient"} and isinstance(payload["id"], str) and payload["id"]
            and isinstance(payload["description"], str) and bool(payload["description"].strip())
            and payload["ability"] in ABILITIES and integer(payload["dc"], 1) and type(payload["dc_known"]) is bool
            and type(payload["proficient"]) is bool and isinstance(payload["tags"], list)
            and all(isinstance(t, str) and t for t in payload["tags"]), "Record a typed check: id, ability, DC, tags and proficiency.")
    tasks = session.state["actors"][aid].setdefault("check_tasks", {})
    require(payload["id"] not in tasks, "That check already exists.")
    tasks[payload["id"]] = {**payload, "done": 0}
    session.emit("CHECK_TASK_ADMITTED", aid, task_id=payload["id"], ability=payload["ability"],
                   dc_known=int(payload["dc_known"]))
    return True


@hook("journey_admission")
def admit_cancel(session, aid, kind, payload, reason):
    """The scenario owner closes an open after-roll window: the roll stands as it is.

    A manual owner who never answers leaves the window open and that creature's journey
    commands refused, so the table needs one way out. The roll is settled with the total it
    already has: no new die is rolled, no offer is paid for, and the result is declared.
    """
    if kind != "cancel_check":
        return None
    require(not payload, "Closing an open roll takes no parameters.")
    actor = session.state["actors"][aid]
    pending = actor.get("pending_roll")
    require(pending is not None, "There is no open roll to close.")
    window = {key: value for key, value in pending.items() if key != "offers"}
    actor.pop("pending_roll", None)
    window["cancelled"] = 1
    session.emit("ROLL_WINDOW_CANCELLED", aid, consumer=window["consumer"], dc_known=int(window["dc_known"]))
    handled = run_strict("journey_roll_finish", session, aid, window)
    require(any(reply is True for reply in handled), "Nothing finished that roll.")
    return True


def _roll_check(session, aid, payload):
    from ..gate2_rolls import DeterministicRollAuthority

    require(set(payload) == {"task"} and isinstance(payload["task"], str), "Choose a recorded check.")
    actor = session.state["actors"][aid]
    task = actor.get("check_tasks", {}).get(payload["task"])
    require(task is not None and not task["done"], "Choose a recorded check you have not made.")
    require(not actor["incapacitated"], "An incapacitated creature cannot make a check.")
    sealed = actor["bundle"]["journey_rolls"]
    ability = task["ability"]
    proficient = task["proficient"]
    if "sect_check" in task["tags"]:
        from .sect_stewardship import sect_key_ability
        chosen = sect_key_ability(actor["resources"])
        require(chosen is not None, "Choose your Sect Stewardship ability before making a Sect Check.")
        ability, _ = chosen
        proficient = True
    bonus = int(sealed["ability_mods"][ability]) + (int(sealed["pb"]) if proficient else 0)
    store = actor.setdefault("material_preparation", {})
    roller = DeterministicRollAuthority(json.dumps([session.state["journey_id"], aid, "scenecheck"]))
    roller.counter = store.get("scene_check_counter", 0)
    roll = roller.d20(modifier=bonus, actor_id=aid, reason="CHECK:Scene:" + task["id"])
    store["scene_check_counter"] = roller.counter
    task["done"] = 1
    session.emit("CHECK_ROLLED", aid, task_id=task["id"], roll=roll.model_dump(mode="json"),
                   dc_known=int(task["dc_known"]))
    open_window(session, aid, consumer="scene_check", roll=roll.model_dump(mode="json"), dc=task["dc"], dc_known=task["dc_known"],
                context={"ability": ability, "tags": list(task["tags"]), "task": task["id"], "description": task["description"]}, data={"task": task["id"]})
    return True


@hook("journey_roll_finish")
def finish(session, aid, window):
    if window["consumer"] != "scene_check":
        return None
    task = session.state["actors"][aid]["check_tasks"][window["data"]["task"]]
    session.emit("CHECK_RESOLVED", aid, task_id=task["id"], total=window["total"], success=int(window["total"] >= task["dc"]),
                 added=[entry["offer"] for entry in window["added"]], dc_known=int(window["dc_known"]))
    return True


@hook("journey_options")
def check_options(session, aid):
    actor = session.state["actors"][aid]
    if session.state["phase"] != "travel" or actor["incapacitated"] or actor.get("pending_roll"):
        return None
    from .sect_stewardship import sect_key_ability
    return [{"id": "scenecheck:" + tid, "kind": "roll_check", "auto_select": int(actor["control_mode"] == "LOCAL_AUTO"), "payload": {"task": tid},
             "label": f"{actor['name']}: make the {task['description']} check."}
            for tid, task in sorted(actor.get("check_tasks", {}).items())
            if not task["done"] and ("sect_check" not in task["tags"] or sect_key_ability(actor["resources"]) is not None)]
