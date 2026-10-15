"""Special Attacks replace one attack of the Attack action (rider lane C13, 2026-09-30; owner: "i want everything we can automated,
keep going until its only the non-combat ones left").

Printed rule (Brute and Wrestling, "Special Attacks"): "When a talent says it is a Special Attack, replace one attack when you take the
Attack action unless the talent explicitly uses a different Action Type"; the abilities themselves say "Timing Detail: Special Attack" or
"Replace one attack when you take the Attack action" (Brutal Shove, Spear Thrust, Batter, Water Lash, ...). On this table such an ability
is its own Action button, so a character with Extra Attack lost the rest of its Attack action by using one.

Now, when an Action-economy ability whose printed text says so resolves, a character whose Attack action has N attacks (its compiled
``extra_attack`` row) may still make the other N - 1 this turn: each of its basic weapon attacks gets a "... (rest of the Attack action)"
button, one attack per use, offered only while attacks remain (a turn flag that ends with the turn). A Special Attack that already makes
every attack of the Attack action itself (a weapon-delivered one: factory_compiler._deliver_with_weapons) grants nothing more.

Which abilities are Special Attacks is read from the printed rules text (authority/typed_mechanics/rules_text.json), never from ids.
Hooks: compile_actions (the buttons, only for a character with Extra Attack), action_completed (start the count), candidate_allowed,
technique_used (count down). Inert for every character without Extra Attack.

Shared replacement_actions(info) creates the canonical one-at-a-time remaining
weapon attacks. sniper_precision reuses it for new sealed Snipe replacements.
parameters.replaces_attack=1 is the general explicit replacement marker read by
_special; absent marker retains the historical printed Special Attack query.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import hook, note

REST = "attack_action_rest"
FLAG = "special_attack_rest"   # a plain turn flag: it ends with the turn
_PRINTED = re.compile(r"Timing Detail:\s*Special Attack|\bis a Special Attack\b|Replace one attack (?:when you take the Attack action|with one attack)", re.I)
_RULES = Path(__file__).resolve().parents[2] / "authority" / "typed_mechanics" / "rules_text.json"


@lru_cache(maxsize=1)
def special_ids() -> frozenset[str]:
    """The mechanics whose printed text makes them a Special Attack."""
    texts = json.loads(_RULES.read_text(encoding="utf-8"))
    return frozenset(key for key, text in texts.items() if isinstance(text, str) and _PRINTED.search(text))


def _attacks(rows: Any) -> int:
    return max([1, *(int(row.get("attacks") or 1) for row in rows or [] if row.get("block") == "extra_attack")])


def attacks_of(engine: Any, actor: Any) -> int:
    return _attacks((getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


@hook("compile_actions")
def rest_of_the_attack_action(info: dict[str, Any]) -> list[Any] | None:
    if _attacks(info.get("passives")) <= 1 or not (special_ids() & set(info["owned_ids"])):
        return None
    return replacement_actions(info)


def replacement_actions(info: dict[str, Any]) -> list[Any] | None:
    """Shared canonical rest buttons; special_attacks and sniper_precision own eligibility."""
    if _attacks(info.get("passives")) <= 1:
        return None
    import copy

    from ..gate2_runtime_models import EconomyKind
    from .weapon_actions import weapon_attacks

    out = []
    for action, typed, attack, _kind in weapon_attacks(info.get("actions") or [], info["actor_id"]):
        one = copy.deepcopy(typed)
        # The weapon-delivery contract (combat/ext/__init__.py): weapon_hits.available_weapons/weapon_identity treat this copy as that
        # weapon, and weapon_actions.weapon_attacks does not offer it again as a weapon of its own.
        one["weapon_source_id"] = action.source_definition_id
        one["variant_of"] = action.source_definition_id
        one["effects"] = [{**copy.deepcopy(effect), "count": 1} if effect is attack else copy.deepcopy(effect) for effect in typed.get("effects") or []]
        out.append(action.model_copy(update={
            "source_definition_id": f"{action.source_definition_id}.{REST}", "display_name": f"{action.display_name} (rest of the Attack action)",
            "economy": EconomyKind.NONE,
            "parameters": {**action.parameters, "typed": one, REST: True,
                           "expected_damage": int(int(action.parameters.get("expected_damage") or 0) / max(1, int(attack.get("count") or 1))),
                           "description": "One more attack of your Attack action, after a Special Attack replaced one of its attacks."}}))
    return out or None


@hook('maneuvers')
def remaining_replacements(info):
    """Every explicitly single-slot replacement stays selectable in later slots.

    Runs after the native Unarmed Strike options have been composed. Legacy
    catalogs without replaces_attack retain their original automatic followups.
    Existing peer replacement actions are deduplicated by their exact ID.
    """
    if _attacks(info.get('passives')) <= 1:
        return None
    from copy import deepcopy
    from ..gate2_runtime_models import EconomyKind
    existing = {a.source_definition_id for a in info['actions']}
    actions = []
    # Ordinary weapon attacks remain available for all unspent slots too.
    for action in replacement_actions(info) or []:
        if action.source_definition_id not in existing:
            actions.append(action)
            existing.add(action.source_definition_id)
    for action in info['actions']:
        if action.parameters.get('replaces_attack') != 1 or action.economy != EconomyKind.ACTION:
            continue
        identity = action.source_definition_id + '.remaining_attack'
        if identity in existing:
            continue
        params = deepcopy(action.parameters)
        params[REST] = True
        actions.append(action.model_copy(update={'source_definition_id': identity, 'economy': EconomyKind.NONE,
            'display_name': action.display_name + ' (remaining attack)', 'parameters': params}))
    return {'actions': actions, 'rows': []}


def _special(action: Any) -> bool:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    return (getattr(action, "parameters", None) or {}).get("replaces_attack") == 1 or str(typed.get("option_of") or typed.get("source") or "") in special_ids()


@hook("action_completed")
def special_attack_made(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    if str(economy).upper() != "ACTION":
        return
    action = engine.action_catalog.get(source_definition_id)
    if action is None or not _special(action):
        return
    attacks = attacks_of(engine, actor)
    typed = (action.parameters or {}).get("typed") or {}
    own = max(1, sum(int(e.get("count") or 1) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"))
    left = attacks - own
    if left <= 0:
        return
    actor.turn_flags[FLAG] = left
    note(engine, source_definition_id, actor, f"{action.display_name} replaced one attack of {actor.display_name}'s Attack action: "
                                              f"{left} more attack{'s' if left > 1 else ''} this turn.")


@hook("candidate_allowed")
def rest_left(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get(REST):
        return None
    return int(actor.turn_flags.get(FLAG) or 0) > 0


@hook("technique_used")
def rest_spent(ctx: Any) -> None:
    if not (getattr(ctx.action, "parameters", None) or {}).get(REST):
        return
    ctx.actor.turn_flags[FLAG] = max(0, int(ctx.actor.turn_flags.get(FLAG) or 0) - 1)
