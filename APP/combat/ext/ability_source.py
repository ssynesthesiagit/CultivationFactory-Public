"""Small public helpers shared by the rider lane C4 plug-ins (rider lane C4, 2026-09-30): sand_riders.py, sand_burial.py,
void_riders.py and later spheres. Pure queries except ``cultivation_check``, which rolls and records one evented check.

- ``mechanic_of(action)``: the printed ability a compiled action resolves (its typed ``option_of`` or ``source``), "" for none.
- ``mechanic_at(engine, source_id)``: the same for a source id seen on an event or condition (a zone trigger id is resolved to
  its action by dropping the ``:suffix``).
- ``is_path_or_subpath_feature(record_id)``: whether a record id is one of a creature's own Path or Subpath features. Used by
  save_trigger_riders (Domain Manifestation's free Spiritual Pressure) and ability_lockout's Path filter.
- ``has_row(engine, actor_id, block)``: whether the creature's compiled bundle carries a feature row of that block
  (combat/rules/feature_blocks.d markers); fights compiled before the marker existed have none.
- ``escape_bonus(engine, actor)``: the better of Athletics or Acrobatics for an escape check (a Factory fighter's compiled escape
  bonus, else the better of its Strength and Dexterity modifiers).
- ``cultivation_check(engine, actor, numbers, dc, source, check_name, modes)``: a Cultivation Check (d20 + Proficiency Bonus + key
  ability modifier + check_bonus hooks, check_floor applied) against ``dc``, recorded as CHECK_ROLLED; True on success.
  ``numbers`` are the roller's own compiled numbers (a native creature without them rolls d20 + 0). ``modes`` are
  independent unresolved modes the printed text requires, combined with native check rules before drawing.
- ``cultivation_check_detail(...)``: the same check, returning ``(roll, success)`` for callers that report the total.
- ``combine_modes(modes)``: one d20 mode from unresolved modes; Advantage and Disadvantage cancel.
"""
from __future__ import annotations

from typing import Any


def mechanic_of(action: Any) -> str:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
    return str(typed.get("option_of") or typed.get("source") or "")


# A Path record is filed under "tianxia.path.*" and a Subpath under "tianxia.subpath.*". The Spirit
# Awakening subpaths the owner's Path text names (Dream Eater, Echo-Step Disciple, ...) are filed
# under "tianxia.tradition.*", so all three namespaces are one creature's own Path/Subpath features.
PATH_SUBPATH_PARTS = (".path.", ".subpath.", ".tradition.")


def is_path_or_subpath_feature(record_id: Any) -> bool:
    """Whether ``record_id`` names one of a creature's own Path or Subpath features.

    Sphere talents ("TAL_*", "tianxia.talent.*"), sphere records and Foundation base abilities are
    not one, however the same character uses them.
    """
    text = str(record_id or "")
    return any(part in text for part in PATH_SUBPATH_PARTS)


def attack_target_key(ctx: Any, target: Any) -> str:
    """Attack/target identity shared by Brute riders and Hammer collision guards.

    String cache keys survive the executor's on-hit cache copy. The event
    sequence separates successive attacks (or Brutal Shove contests, rider lane C16), even when their action is the same;
    derived Dominoes attacks cannot replace their parent shove's identity.
    """
    sequence = next((event.sequence for event in reversed(ctx.engine.events)
                     if event.event_type in ("ATTACK_ROLLED", "CHECK_ROLLED") and event.actor_id == ctx.actor.entity_id
                     and event.source_definition_id == ctx.source and target.entity_id in event.target_ids), 0)
    return f"{sequence}:{target.entity_id}"


def mechanic_at(engine: Any, source_id: str) -> str:
    source = str(source_id or "")
    action = engine.action_catalog.get(source) or engine.action_catalog.get(source.split(":zone")[0].split(":own")[0].split("#")[0])
    return mechanic_of(action) if action is not None else ""


def source_label(engine: Any, source_id: str) -> str:
    """Readable benefit source for Void's shared benefit_suppression helper.

    Resolve catalog actions (including their zone/variant suffixes), then an
    owner's printed ability heading. Unknown sources never expose transport IDs.
    """
    from ..rule_help import printed_rule_text

    source = str(source_id or "")
    action = engine.action_catalog.get(source)
    if action is None:
        key = max((key for key in engine.action_catalog
                   if source.startswith(key + ":") or source.startswith(key + "#")), key=len, default="")
        action = engine.action_catalog.get(key)
    if action is not None and action.display_name:
        return str(action.display_name)
    text = printed_rule_text(source)
    heading = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), "")
    return heading or "an unnamed temporary effect"


def has_row(engine: Any, actor_id: str, block: str) -> bool:
    from .. import typed_reactions

    return bool(typed_reactions._rows(engine, actor_id, block))


def compiled_feature_rows(engine: Any, actor_id: str, feature_id: str) -> tuple[dict[str, Any], ...]:
    """Exact owned passive/reaction rows, used by Karma's event-driven reactions.

    A related talent, sphere prefix or another actor's row is never ownership.
    Return the compiled rows without mutating them; callers retain their own
    block/kind/trigger requirements. Suitable for other event-driven plug-ins.
    """
    return tuple(row for store in ('typed_reaction_rows', 'typed_passive_rows')
                 for row in (getattr(engine, store, None) or {}).get(actor_id, ())
                 if row.get('feature_id') == feature_id)


def numbers_of(engine: Any, actor: Any) -> dict[str, Any]:
    """Personal numbers from sealed typed actions, also used by subject teleport gates.

    Void/other ability gates and typed_executor use the moved creature's values,
    independently of the controller that paid for a subject teleport.
    """
    for action_id in getattr(actor, "action_ids", ()) or ():
        action = engine.action_catalog.get(action_id)
        numbers = (((action.parameters or {}).get("typed") or {}).get("numbers") or {}) if action is not None else {}
        if numbers.get("save_dc") is not None:
            return dict(numbers)
    return {}


def escape_bonus(engine: Any, actor: Any) -> int:
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        numbers = (((action.parameters or {}).get("typed") or {}).get("numbers") or {}) if action is not None else {}
        if action_id.endswith(".escape_grapple") and "escape_bonus" in numbers:
            return int(numbers["escape_bonus"])
    from ..ability_checks import ability_modifier

    return max(ability_modifier(actor, "STR"), ability_modifier(actor, "DEX"))


def combine_modes(modes: Any) -> str:
    """One d20 mode from unresolved check modes: any Advantage and any Disadvantage cancel, otherwise the
    single surviving kind names the mode and none (or both) is NORMAL. Used by every Cultivation Check caller."""
    modes = set(modes or ())
    if "ADVANTAGE" in modes and "DISADVANTAGE" not in modes:
        return "ADVANTAGE"
    if "DISADVANTAGE" in modes and "ADVANTAGE" not in modes:
        return "DISADVANTAGE"
    return "NORMAL"


def cultivation_check_detail(engine: Any, actor: Any, numbers: dict[str, Any], dc: int, source: str,
                             check_name: str = "Cultivation Check", modes: Any = None) -> tuple[Any, bool]:
    """``cultivation_check`` with the rolled check returned, for callers that report the total.

    ``modes`` are unresolved check modes ("ADVANTAGE"/"DISADVANTAGE") from the actor's own scoped check
    rules and the ``ability_check_mode`` hooks; native actor-wide rules always apply. Check
    bonuses and d20 floors always apply.
    """
    from ..typed_executor import Context
    from . import floored, run

    action = engine.action_catalog.get(source) or next(iter(engine.action_catalog.values()))
    ctx = Context(engine, actor, action, None, {"numbers": dict(numbers)}, [actor], actor, {})
    modifier = int(numbers.get("pb") or 0) + int(numbers.get("key_mod") or 0) + sum(int(x) for x in run("check_bonus", ctx, actor) if isinstance(x, int))
    roll = engine.roll_check(modifier=modifier, actor_id=actor.entity_id, reason=f"CHECK:{source}", modes=modes or ())
    engine._record_roll(roll)
    roll = floored(engine, actor, roll, dc)
    success = roll.total >= dc
    engine._append_event("CHECK_ROLLED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": int(dc), "success": success, "check": check_name})
    return roll, success


def cultivation_check(engine: Any, actor: Any, numbers: dict[str, Any], dc: int, source: str, check_name: str = "Cultivation Check",
                      modes: Any = None) -> bool:
    """A Cultivation Check (d20 + Proficiency Bonus + key ability modifier + check_bonus hooks, Advantage or
    Disadvantage when ``modes`` names one, check_floor applied) against ``dc``, recorded as CHECK_ROLLED; True on success.
    ``numbers`` are the roller's own compiled numbers (a native creature without them rolls d20 + 0).
    """
    return cultivation_check_detail(engine, actor, numbers, dc, source, check_name, modes)[1]
