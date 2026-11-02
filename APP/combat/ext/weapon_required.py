"""A talent that strikes with an approved Spear or a saber needs one (fight audit 2026-09-29: Mo Ruo, carrying a staff,
spent his Reaction and a Spear Resource on Intercepting Thrust four times for no damage -- "No approved Spear weapon
found"). Such an ability (an ``attach_spear_weapon``/``bind_spear_weapon``/``attach_saber_weapon`` effect, combat/ext/martial_spear.py and
wenxue_sabers.py) is not offered, and such a reaction does not fire, while the fighter has no such weapon."""

from __future__ import annotations

from typing import Any

from . import hook
from .martial_spear import SPEAR_WORDS
from .wenxue_sabers import SABER_WORDS
from .weapon_hits import available_weapons
from ..hook_queries import actor_action

NEEDS = {"attach_spear_weapon": SPEAR_WORDS, "bind_spear_weapon": SPEAR_WORDS,
         "attach_saber_weapon": SABER_WORDS}


def _needed(effects: Any) -> set[str]:
    found: set[str] = set()
    stack = [effects]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if item.get("type") in NEEDS:
                found.add(item["type"])
            stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
        elif isinstance(item, list):
            stack.extend(item)
    return found


def _carries(engine: Any, actor: Any, words: tuple[str, ...]) -> bool:
    return bool(available_weapons(engine, actor, words))


def _armed_for(engine: Any, actor: Any, effects: Any) -> bool:
    from .saber_learning import saber_action
    return all(any(saber_action(a) for a in available_weapons(engine, actor).values())
               if kind == "attach_saber_weapon" else _carries(engine, actor, NEEDS[kind])
               for kind in _needed(effects))


@hook("candidate_allowed", query_key=actor_action)
def offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    effects = ((action.parameters or {}).get("typed") or {}).get("effects")
    return None if not effects or _armed_for(engine, actor, effects) else False


@hook("row_allowed")
def reaction(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    effects = row.get("effects")
    return None if not effects or _armed_for(engine, actor, effects) else False
