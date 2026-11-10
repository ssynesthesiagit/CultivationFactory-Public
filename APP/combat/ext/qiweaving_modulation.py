"""Qiweaving Modulation riders (rider lane C11, 2026-09-30): Retune Current and Stabilizing Circuit.

Source (owner text, authority/typed_mechanics/rules_text.json):
  Retune Current (Modulation, +1 CP): "When you activate a sphere technique that deals Acid, Cold, Fire, Lightning, Necrotic,
    Psychic, Radiant, or Thunder damage, choose one damage type from that list that another sphere you know could plausibly
    produce. Change one damage roll of the technique to the chosen damage type. Retune Current cannot create a damage type that
    none of your known spheres can justify."
  Stabilizing Circuit: "When you apply Stable Modulation, you may also add your Proficiency Bonus to the first Concentration saving
    throw made for that technique before the start of your next turn. If another effect already adds your Proficiency Bonus to
    that save, do not add it twice."

How it runs.
  Retune Current: its typed modifier (reviewed_final.d/riders_c11.json) carries ``any_sphere`` and ``target_requires`` (general
  compiler flags, combat/factory_compiler._meets_requirements), so its variant exists only on a technique of any Sphere you know
  that deals one of the eight listed types. ``compile_action`` then widens the first such damage row of the variant to a choice:
  its own type plus each listed type that a technique of *another* Sphere you know deals (the typed authority of that Sphere --
  "could plausibly produce"). The table picks the type exactly as it picks every printed damage-type choice (owner 2026-09-26,
  typed_executor.choose_damage_type: the one that lands hardest on the targets, never a resisted one while another is open).
  With no other Sphere that justifies a listed type the variant is not offered (``candidate_allowed``).
  Stabilizing Circuit: feature block ``qiweaving_modulation`` (combat/rules/feature_blocks.d/riders_c11.json). After a Stable
  Modulation variant resolves for its owner (``technique_used``), the owner carries "Stabilizing Circuit" until the start of their
  next turn; the first Concentration save made while that technique is the one they are concentrating on (a damaging hit ends only
  the most recent technique, combat/concentration.py) gets +Proficiency Bonus (``d20_bonus``, a logged D20_REWRITTEN bonus) and
  uses it up. Factory characters add no Proficiency Bonus to saving throws otherwise (factory_compiler: no save proficiencies), so
  "do not add it twice" never applies at the table.
Default-inert: nothing happens for a fighter without the feature row or without a Retune Current variant.
"""

from __future__ import annotations

import json
from typing import Any

from . import hook
from .condition_ownership import remove_instance

RETUNE = "TAL_QIWEAVING_RETUNE_CURRENT"
STABLE = "TAL_QIWEAVING_STABLE_MODULATION"
BLOCK = "qiweaving_modulation"
CIRCUIT = "condition:typed.stabilizing_circuit"
RETUNE_TYPES = ("ACID", "COLD", "FIRE", "LIGHTNING", "NECROTIC", "PSYCHIC", "RADIANT", "THUNDER")
CONCENTRATION_SAVE = "SAVE:system:combat.concentration:CON"
_MECHANICS: dict[str, Any] = {}


def _mechanics() -> dict[str, Any]:
    if not _MECHANICS:
        from .. import factory_compiler

        _MECHANICS.update(json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())["mechanics"])
    return _MECHANICS


def _walk(rows: Any):
    for row in rows or []:
        if isinstance(row, dict):
            yield row
            for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _walk(row.get(branch) if isinstance(row.get(branch), list) else [])


def _sphere_damage_types(sphere: str) -> set[str]:
    """Every listed type a technique of this Sphere deals (its effects, options and modifier effects)."""
    found: set[str] = set()
    for mechanic in _mechanics().values():
        if mechanic.get("sphere_id") != sphere:
            continue
        rows = [*(mechanic.get("effects") or []), *((mechanic.get("modifier") or {}).get("effects") or []),
                *(row for option in mechanic.get("options") or [] for row in option.get("effects") or [])]
        for row in _walk(rows):
            if row.get("type") in ("damage", "extra_damage"):
                found |= {str(kind).upper() for kind in row.get("damage_types") or []} & set(RETUNE_TYPES)
    return found


def _mechanic_of(action_id: str) -> str:
    """"action:typed.<short>.<mechanic id>[#option]" -> the mechanic id."""
    parts = str(action_id).split(".", 2)
    return parts[2].split("#")[0] if len(parts) == 3 else ""


@hook("compile_action")
def retune_choices(action: Any, info: dict[str, Any]) -> Any:
    typed = (action.parameters or {}).get("typed") or {}
    if (typed.get("modifier") or {}).get("id") != RETUNE:
        return None
    own = (_mechanics().get(_mechanic_of(typed.get("variant_of") or "")) or {}).get("sphere_id")
    spheres = ((info.get("owner_sheet") or {}).get("spheres_and_talents") or {}).get("sphere_record_ids") or []
    justified: set[str] = set()
    for sphere in spheres:
        if sphere != own:
            justified |= _sphere_damage_types(sphere)
    parameters = json.loads(json.dumps(action.parameters))
    effects = parameters["typed"]["effects"]
    row = next((row for row in _walk(effects) if row.get("type") in ("damage", "extra_damage") and not row.get("weapon_damage")
                and {str(kind).upper() for kind in row.get("damage_types") or []} & set(RETUNE_TYPES)), None)
    kinds = [str(kind).upper() for kind in (row or {}).get("damage_types") or []]
    extra = [kind for kind in RETUNE_TYPES if kind in justified and kind not in kinds]
    parameters["typed"]["retune_types"] = extra
    if row is not None and extra:
        row["damage_types"] = [*kinds, *extra]
        # Preserve an explicit "or" choice even with a single alternative.
        # Otherwise a parent line such as "damage and apply Burn" is read as
        # simultaneous damage types by the shared damage-choice parser.
        choices = ' or '.join(k.title() for k in [*kinds, *extra])
        row["evidence"] = f"{row.get('evidence') or ''} (Retune Current: choose {choices} for this damage roll)".strip()
    return action.model_copy(update={"parameters": parameters})


@hook("candidate_allowed")
def retune_needs_a_type(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if (typed.get("modifier") or {}).get("id") != RETUNE:
        return None
    return bool(typed.get("retune_types"))


# ------------------------------------------------------------------------------------------------ Stabilizing Circuit
@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2)}]


def _row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    from .. import typed_reactions

    return next((row for row in typed_reactions._rows(engine, actor.entity_id, BLOCK) if row.get("kind") == kind), None)


@hook("technique_used")
def stable_applied(ctx: Any) -> None:
    if (ctx.typed.get("modifier") or {}).get("id") != STABLE:
        return
    row = _row(ctx.engine, ctx.actor, "stabilizing_circuit")
    if row is None:
        return
    for key, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == CIRCUIT:
            remove_instance(ctx.engine, ctx.actor, key, ctx.source)
    pb = int(row.get("pb") or ctx.actor.proficiency_bonus)
    ctx.engine._apply_condition(
        ctx.actor, CIRCUIT, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
        data={"technique": ctx.source, "bonus": pb, "label": "Stabilizing Circuit",
              "reading": f"+{pb} (Proficiency Bonus) on the first Concentration saving throw for {ctx.action.display_name} "
                         "before the start of your next turn."})


@hook("d20_bonus")
def circuit_bonus(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    if roll.reason != CONCENTRATION_SAVE:
        return None
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None or actor.concentration is None:
        return None
    held = actor.concentration.source_definition_id
    found = next(((key, condition) for key, condition in actor.conditions.items()
                  if condition.condition_id == CIRCUIT and (condition.data or {}).get("technique") == held), None)
    if found is None:
        return None
    key, condition = found
    remove_instance(engine, actor, key, str(condition.source_definition_id))
    return {"source_id": "TAL_QIWEAVING_STABILIZING_CIRCUIT", "bonus": int((condition.data or {}).get("bonus") or 0)}
