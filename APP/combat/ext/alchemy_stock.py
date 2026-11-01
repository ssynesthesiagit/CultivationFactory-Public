"""Reagent Stock and Sealed Dose Method (Alchemy; rider lane C10, 2026-09-30).

Owner text (authority/typed_mechanics/rules_text.json):
  Reagent Stock -- "During a Long Rest, you may prepare a number of Reagent Stock uses up to: Proficiency Bonus + Alchemy key
    ability modifier, minimum 1 ... A talent that spends Reagent Stock consumes one prepared use. Reagent Stock is not an item
    another creature can normally use unless a talent says so."
  Sealed Dose Method -- "Your Reagent Stock maximum increases by your Proficiency Bonus. In addition, one ally may carry one sealed
    dose you prepared. The ally can administer that dose as an Action if the dose is a Medicinal Smoke, Healing Pill, Antidote
    Pill, or another recipe the GM agrees is safe for field use."

How it runs
  * The pool ``resource:named.reagent_stock`` (declared by the typed costs "1 CP and one Reagent Stock") starts a fight full: the
    character prepared its uses at its last Long Rest (a fight happens inside one day). Its size is Proficiency Bonus + the
    Alchemy key ability modifier (the Path key ability the compiler's ``key_mod`` holds, as Field Formula's own "+ your Alchemy
    key ability modifier" rows read it), at least 1, plus the Proficiency Bonus with Sealed Dose Method. Before this every
    alchemist began with 0 and no Field Formula could be used. compile_resources sizes it (the named-pool seam in
    combat/ext/__init__.py); spending it is the ordinary typed cost.
  * Sealed Dose: the owner has one sealed dose (``resource:named.sealed_dose``, 1) and its bundle carries the dose action (so a
    reloaded fight has it; never offered to the owner itself). Every ally on its side is offered "Sealed Dose from <owner>:
    Medicinal Smoke" (an Action, additional_actions) until one of them uses it -- the ally who uses it is the one who carried it. It resolves the owner's own compiled Medicinal Smoke (Field Formula) with the owner's numbers: yourself or one ally within
    the formula's 60 feet. Healing Pill and Antidote Pill are recipes the table does not model as carried items, and "another
    recipe the GM agrees" stays with the GM.
Readings: the carried dose is the talent's own (it does not spend a prepared Reagent Stock use); the dose uses Medicinal Smoke's
range. Deterministic and evented: the dose is spent with the engine's ``_spend_resource`` on its owner.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

ALCHEMY = "tianxia.sphere.alchemy"
REAGENT_STOCK = "ALCHEMY_BASE_REAGENT_STOCK"
SEALED_DOSE = "TAL_ALCHEMY_SEALED_DOSE_METHOD"
STOCK = "resource:named.reagent_stock"
DOSE = "resource:named.sealed_dose"
DOSE_SUFFIX = ".alchemy.sealed_dose"  # action:typed.<short>.alchemy.sealed_dose, in its owner's bundle


def stock_size(pb: int, key_mod: int, sealed: bool) -> int:
    """Prepared Reagent Stock uses: Proficiency Bonus + key ability modifier (minimum 1), + Proficiency Bonus with Sealed Dose."""
    return max(1, int(pb) + int(key_mod)) + (int(pb) if sealed else 0)


@hook("compile_resources")
def resources(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ResourceDefinition

    owned = set(info.get("owned_ids") or [])
    if REAGENT_STOCK not in owned and ALCHEMY not in set(info.get("spheres") or ()):
        return None
    pb = int(info.get("pb") or 2)
    key_mod = int((info.get("numbers") or {}).get("key_mod") or 0)
    size = stock_size(pb, key_mod, SEALED_DOSE in owned)
    out = [ResourceDefinition(resource_id=STOCK, initial=size, maximum=size)]
    if SEALED_DOSE in owned:
        out.append(ResourceDefinition(resource_id=DOSE, initial=1, maximum=1))
    return out


def _medicinal_smoke(actions: list[Any]) -> Any | None:
    """The character's own Field Formula: Medicinal Smoke (not an augmented variant)."""
    return next((action for action in actions if "+" not in action.source_definition_id
                 and ((action.parameters or {}).get("typed") or {}).get("option_label") == "Medicinal Smoke"
                 and ((action.parameters or {}).get("typed") or {}).get("source") == "ALCHEMY_BASE_FIELD_FORMULA"), None)


@hook("compile_actions")
def dose_action(info: dict[str, Any]) -> list[Any] | None:
    """The sealed dose, compiled with its owner's bundle (so a reloaded fight has it): its owner's Medicinal Smoke, run by an ally."""
    from ..gate2_runtime_models import EconomyKind

    if SEALED_DOSE not in (info.get("owned_ids") or []):
        return None
    smoke = _medicinal_smoke(list(info.get("actions") or []))
    if smoke is None:
        return None
    identity = (info.get("owner_sheet") or {}).get("identity") or {}
    name = str(identity.get("name") or identity.get("display_name") or "Factory character")
    typed = copy.deepcopy((smoke.parameters or {}).get("typed") or {})
    typed["effects"] = [{"type": "alchemy_sealed_dose", "owner": info["actor_id"],
                         "evidence": "one ally may carry one sealed dose you prepared. The ally can administer that dose as an Action"},
                        *typed.get("effects", [])]
    typed.update(riders=[], source=SEALED_DOSE, coverage="FULL")
    typed.pop("option_of", None)
    typed.pop("option_label", None)
    return [smoke.model_copy(update={
        "source_definition_id": f"action:typed.{info['short']}{DOSE_SUFFIX}", "display_name": f"Sealed Dose from {name}: Medicinal Smoke",
        "economy": EconomyKind.ACTION, "costs": (),
        "parameters": {"typed": typed, "expected_damage": 0, "sealed_dose_of": info["actor_id"],
                       "description": (f"Administer the sealed dose {name} prepared (Sealed Dose Method): yourself or one ally within "
                                       f"{smoke.range_ft or 60} feet gains Temporary Hit Points, as {name}'s Medicinal Smoke. One dose, "
                                       "used once, by one ally.")}})]


def _doses(engine: Any) -> list[tuple[Any, str]]:
    """(owner, its dose action id) for each character with Sealed Dose Method (its bundle gave it the dose pool and action)."""
    out = []
    for _key, actor in sorted(engine.state.actors.items()):
        if DOSE in actor.resources:
            action_id = next((aid for aid in actor.action_ids if aid.endswith(DOSE_SUFFIX) and aid in engine.action_catalog), None)
            if action_id:
                out.append((actor, action_id))
    return out


def _dose_open(engine: Any, actor: Any, owner_id: str) -> bool:
    owner = engine.state.actors.get(owner_id)
    return (owner is not None and owner.entity_id != actor.entity_id and owner.team_id == actor.team_id
            and int(owner.resources.get(DOSE, 0)) > 0 and actor.active)


@hook("additional_actions")
def offered(engine: Any, actor: Any) -> list[str]:
    return [action_id for owner, action_id in _doses(engine) if _dose_open(engine, actor, owner.entity_id)]


@hook("candidate_allowed")
def allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    owner_id = ((getattr(action, "parameters", None) or {}).get("sealed_dose_of")) if action is not None else None
    if not owner_id:
        return None
    return None if _dose_open(engine, actor, owner_id) else False


@effect("alchemy_sealed_dose")
def administer(ctx: Any, row: dict[str, Any]) -> None:
    owner = ctx.engine.state.actors.get(str(row.get("owner") or ""))
    if owner is None or int(owner.resources.get(DOSE, 0)) <= 0:
        return
    ctx.engine._spend_resource(owner, DOSE, 1, ctx.source)
    ctx.rider(f"Sealed Dose Method: {ctx.actor.display_name} administers the sealed dose {owner.display_name} prepared.")
