"""Passive and reaction building blocks for Factory characters (owner 2026-09-25: combat must fight at level).

Which feature uses which block, and its numbers, live in the owner-editable
``combat/rules/feature_blocks.json`` (a number written "typed" is read from the feature's typed record,
combat/typed_numbers.py).  The compiler resolves them per character
into the bundle (``typed_reactions`` and ``typed_passives``); the engine calls the
three checkpoint hooks below for Factory fighters only.  Every state change goes
through engine events (RESOURCE_SPENT, MODIFIER_APPLIED, REACTION_RESOLVED,
DAMAGE_COMMITTED), so saved fights replay unchanged.

The reaction policy is deliberately simple: react when it is affordable and
changes the outcome (a save turns into a success, a hit into a miss) or, for
damage soak and parries, when the hit is big enough to matter.  A free parry is
tried before a paid soak.

Passive blocks change the compiled actions (extra_attack, on_hit_damage) or are
checked when damage lands (resistance); already_applied marks features whose
effect is already in the sheet or the compiled actions (e.g. Unarmored Defense in the AC).
"""

from __future__ import annotations

import copy
import re
import json
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .resource_costs import as_dict as cost_dict
from .effect_harm import classify_effect, children as effect_children
from .typed_amounts import static_bonus

RULES_PATH = Path(__file__).resolve().parent / "rules" / "feature_blocks.json"
_CACHE: dict[str, Any] = {}


def rules() -> dict[str, Any]:
    """combat/rules/feature_blocks.json, with every combat/rules/feature_blocks.d/*.json's features merged in."""
    directory = RULES_PATH.parent / "feature_blocks.d"
    if not directory.is_dir():
        # Required rules data: a glob over a missing directory is empty, which silently drops every feature the
        # directory declares (their ids then compile to no row at all). Fail loud, naming the path.
        raise FileNotFoundError(f"required feature-block rules directory is missing: {directory}")
    extra = sorted(directory.glob("*.json"))
    mtime = (RULES_PATH.stat().st_mtime_ns, tuple((path.name, path.stat().st_mtime_ns) for path in extra))
    if _CACHE.get("mtime") != mtime:
        data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        for path in extra:
            data["features"] = {**data["features"], **(json.loads(path.read_text(encoding="utf-8")).get("features") or {})}
        _CACHE.update(mtime=mtime, data=data)
    return _CACHE["data"]


def _number(value: Any, *, pb: int, key_mod: int) -> int:
    if value == "pb":
        return pb
    if value == "key_mod":
        return key_mod
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- compile time
def _dice(text: Any) -> tuple[int, int]:
    parts = str(text or "").lower().split("d")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])
    return 0, 0


def attacks_for_cl(table: dict[str, Any], cl: int) -> int:
    attacks = 1
    for level, count in sorted((int(level), int(count)) for level, count in (table or {}).items()):
        if level <= cl:
            attacks = count
    return attacks


def _block_number(spec: dict[str, Any], field: str, default: Any, record: dict[str, Any] | None, *, pb: int, key_mod: int) -> int | None:
    """A block's number: an integer, "pb", "key_mod", or "typed" -- read from the feature's typed record (combat/typed_numbers.py;
    owner 2026-09-30, Qi Armor: an owner edit of the printed number reaches the table without a second copy here). None when a
    "typed" number is not stated once in the record: the block is then left out and the feature compiles from its record."""
    value = spec.get(field, default)
    if value == "typed":
        from .typed_numbers import typed_number

        return typed_number(record, field, resource=str(spec.get("resource") or ""))
    return _number(value, pb=pb, key_mod=key_mod)


def compile_blocks(mechanic_ids: list[str], *, pb: int, key_mod: int, saves: dict[str, int], resource_ids: dict[str, str], cl: int = 1,
                   armor: str | None = None, shield: bool = False, mechanics: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Resolve the character's features into reaction and passive rows for the bundle.

    ``armor`` is the worn body armour's category ("light", "medium", "heavy"), None when unarmoured. ``mechanics`` is the typed
    authority's records ("typed" block numbers read them); None reads the built authority file."""
    features = rules().get("features") or {}
    if mechanics is None and any(isinstance(spec, dict) and "typed" in spec.values() for spec in map(features.get, mechanic_ids)):
        from .typed_numbers import authority_mechanics

        mechanics = authority_mechanics()
    mechanics = mechanics or {}
    reactions: list[dict[str, Any]] = []
    passives: list[dict[str, Any]] = []
    automated: list[str] = []
    defended: list[str] = []
    for mechanic_id in dict.fromkeys(mechanic_ids):
        spec = features.get(mechanic_id)
        if not isinstance(spec, dict):
            continue
        block = spec.get("block")
        resource = resource_ids.get(str(spec.get("resource") or ""), "")
        row = {"feature_id": mechanic_id, "block": block, "resource_id": resource}
        # General feature-block opt-in: paid choices without a Reaction can use
        # the existing Auto / Ask me plan. Absent metadata preserves saved rows.
        if spec.get("optional"):
            row["optional"] = True
        record = mechanics.get(mechanic_id)
        if block == "damage_soak":
            row.update(max_spend=_number(spec.get("max_spend", "pb"), pb=pb, key_mod=key_mod), die=int(spec.get("die") or 10),
                       minimum_damage=int(spec.get("minimum_damage") or 1))
            reactions.append(row)
        elif block == "hit_ac":
            cheaper = spec.get("cost_from_cl")  # Qi Armor: "At CL10, Qi Armor costs 1 Qi"
            cost = int(cheaper[1]) if cheaper and cl >= int(cheaper[0]) else _block_number(spec, "cost", 1, record, pb=pb, key_mod=key_mod)
            ac = _block_number(spec, "ac", 2, record, pb=pb, key_mod=key_mod)
            if cost is None or ac is None:
                continue  # a "typed" number the record does not state
            row.update(cost=cost, ac=ac, ranged_only=bool(spec.get("ranged_only")))
            reactions.append(row)
        elif block == "save_rescue":
            abilities = [str(value).upper() for value in spec.get("abilities") or []]
            choose_one = bool(spec.get("choose_one")) and len(abilities) > 1
            if choose_one:
                # The printed "Choose one Defensive Discipline" (Tempered Response, Cultivated Response) is a
                # player-owned pick the sheet does not record. Keep every printed option on the row and let a
                # plug-in ask which one this fighter uses (combat/ext/defensive_disciplines.py); until it has
                # answered, the fighter's weakest listed save stands in, so nothing changes for an unanswered
                # fighter and an old saved fight reloads to exactly the row it was saved with.
                row["choose_one"] = True
                row["choices"] = list(abilities)
                abilities = [min(abilities, key=lambda ability: (saves.get(ability, 0), ability))]
            cost = _block_number(spec, "cost", 1, record, pb=pb, key_mod=key_mod)
            if cost is None:
                continue  # a "typed" number the record does not state
            row.update(abilities=abilities, cost=cost,
                       bonus=_number(spec.get("bonus", "pb"), pb=pb, key_mod=key_mod), reaction=bool(spec.get("reaction", True)),
                       sources=list(spec.get("sources") or []))  # only these saves (Nascent Soul: Concentration)
            extra = spec.get("plus_if_owned")  # Integrity Rejection: +PB more with Heaven-Recognized Vessel (sys-resources-states)
            if isinstance(extra, dict) and extra.get("feature") in mechanic_ids:
                row["bonus"] += _number(extra.get("bonus", "pb"), pb=pb, key_mod=key_mod)
            reactions.append(row)
        elif block == "damage_reduction":
            cost = _block_number(spec, "cost", 0, record, pb=pb, key_mod=key_mod)
            if cost is None:
                continue  # a "typed" number the record does not state
            row.update(dice=str(spec.get("dice") or ""), bonus=_number(spec.get("bonus", 0), pb=pb, key_mod=key_mod),
                       cost=cost, minimum_damage=int(spec.get("minimum_damage") or 1),
                       trigger=str(spec.get("trigger") or "melee_weapon_hit"))
            reactions.append(row)
        elif block in {"natural_weapon", "technique_potency"}:
            passives.append({**row, **{key: value for key, value in spec.items() if key not in {"block", "resource"}},
                             "bonus_value": _number(spec.get("bonus", 0), pb=pb, key_mod=key_mod)})
        elif block == "extra_attack":
            passives.append({**row, "attacks": attacks_for_cl(spec.get("attacks_by_cl") or {}, cl)})
        elif block == "resistance":
            passives.append({**row, "damage_types": [str(kind).upper() for kind in spec.get("damage_types") or []],
                             "mundane_only": bool(spec.get("mundane_only"))})
        elif block == "defense":
            # Always-on damage defences (owner 2026-09-26: "are damage types all tracked and resistances?").
            # Only the defence is automated: the feature's other parts (a trigger, a resource) still compile.
            for entry in spec.get("defenses") or []:
                needs = set(entry.get("requires") or [])
                if ("unarmored" in needs and armor) or ("no_heavy_armor" in needs and armor == "heavy"):
                    continue  # "while benefiting from Unarmored Defense" / "not wearing Heavy armor"
                if ("armored" in needs and not armor) or ("medium_or_heavy_armor" in needs and armor not in ("medium", "heavy")) \
                        or ("no_shield" in needs and shield):
                    continue  # "while wearing armor", "medium or heavy armor", "not wielding a Shield" (owner 2026-09-28)
                passives.append({**row, "kind": str(entry.get("kind") or "resistance"),
                                 "damage_types": [str(kind).upper() for kind in entry.get("damage_types") or []],
                                 "amount": _number(entry.get("amount", 0), pb=pb, key_mod=key_mod),
                                 "mundane_only": bool(entry.get("mundane_only")), "attacks_only": bool(entry.get("attacks_only")),
                                 "martial_focus": "martial_focus" in needs,
                                 # A dynamic, runtime "while <condition>" gate (body 2026-09-29, Berserk: "while
                                 # Adrenaline is active"), unlike the compile-time armor/shield requires above --
                                 # the condition can come and go within one fight, checked in _defense_applies.
                                 "requires_condition": entry.get("requires_condition"),
                                 "immune_below_cl": cl if entry.get("immune_below_source_cl") else 0,
                                 "attack_kinds": list(entry.get("attack_kinds") or []), "melee_only": bool(entry.get("melee_only")),
                                 "once_per_round": bool(entry.get("once_per_round")),
                                 # An alternate Armor Class calculation -- a feature that prints "your Armor Class
                                 # equals 10 + your Dexterity modifier + ...", which replaces a calculation instead of
                                 # adding to it (owner amendment R1) -- carries the constant it starts from and the
                                 # ability modifier it reads. combat/armour.alternate_ac_calculations resolves those into
                                 # whole numbers; no defense row ever adds one to a bonus.
                                 "ac_base": _number(entry.get("base", 0), pb=pb, key_mod=key_mod),
                                 "ac_ability": str(entry.get("ability") or "DEX").upper()[:3],
                                 "abilities": [str(value).upper()[:3] for value in entry.get("abilities") or []],
                                 "against": [str(value).lower() for value in entry.get("against") or []]})
            defended.append(mechanic_id)
            continue
        elif block == "on_hit_damage":
            passives.append({**row, "dice": str(spec.get("dice") or ""), "bonus_value": _number(spec.get("bonus", 0), pb=pb, key_mod=key_mod),
                             "damage_type": str(spec.get("damage_type") or "UNTYPED").upper(), "once_per_turn": bool(spec.get("once_per_turn", True)),
                             "attack_kinds": list(spec.get("attack_kinds") or ["weapon", "unarmed"])})
        elif block == "generate":
            # Foundation resource triggers (owner 2026-09-28): combat/pressure.py reads them.
            if resource:
                passives.append({**row, "on": list(spec.get("on") or []), "max": int(spec.get("max") or 1),
                                 "per_round": int(spec.get("per_round") or 0), "expires": spec.get("expires"),
                                 "refresh": bool(spec.get("refresh"))})  # "refresh expiration instead of stacking"
        elif block == "save_bonus":
            passives.append({**row, "abilities": list(spec.get("abilities") or []), "against": list(spec.get("against") or []),
                             "bonus": _number(spec.get("bonus", "pb"), pb=pb, key_mod=key_mod)})
        elif block == "unmaking":
            passives.append({**row, "kind": spec.get("kind")})  # combat/unmaking.py (Execution Through the Fault, Crack the Name)
        elif block == "granted_action":
            passives.append({**row, "action": spec.get("action") or {}})  # combat/factory_compiler.py builds it
        elif block == "opening":
            passives.append(row)  # Iron Fist's Opening and Open the Gate (combat/typed_executor.py open_guard)
        elif block == "motion":
            # Movement passives (owner 2026-09-28): combat/motion.py reads them.
            passives.extend({**row, "block": "motion", **{key: value for key, value in rule.items() if key != "block"}}
                            for rule in spec.get("rules") or [] if isinstance(rule, dict) and rule.get("kind"))
        elif block != "already_applied":
            from . import ext

            # ``record`` is this feature's own typed record, from the same authority the caller supplied
            # (combat/factory_compiler.py compile_character's ``typed_authority``). A plug-in that prints its numbers in
            # reviewed data reads them from the record the compiler was given, so an injected or revised authority
            # compiles its own numbers instead of today's file on disk. Default-inert: a hook that ignores the key
            # compiles exactly as before.
            made = [rows for rows in ext.run("compile_block", block, spec, row, {"pb": pb, "key_mod": key_mod, "cl": cl, "armor": armor, "shield": shield, "record": record}) if rows]
            if not made:
                continue
            passives.extend(entry for rows in made for entry in rows)  # a plug-in's own block (combat/ext)
            if any(entry.get("keeps_compiling") for rows in made for entry in rows):
                continue  # the feature is more than this row (an action, a modifier): it still compiles as it did
        automated.append(mechanic_id)
    return {"reactions": reactions, "passives": passives, "automated": automated, "defended": defended}


# ---------------------------------------------------------------- engine hooks
def _rows(engine: Any, actor_id: str, block: str) -> list[dict[str, Any]]:
    rows = [*(getattr(engine, "typed_reaction_rows", {}) or {}).get(actor_id, []), *(getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, [])]
    # The character's reaction plan (owner 2026-09-26, combat/factory_compiler.py _reaction_plan): a
    # reaction set to off never fires, and ranked ones are tried most important first (a stable sort, so
    # Auto -- no ranks -- keeps the compiled order).
    rows = sorted((row for row in rows if row.get("block") == block and not row.get("held_back")),
                  key=lambda row: row.get("priority", 0))
    from . import ext
    for replacement in ext.run_strict("reaction_rows", engine, actor_id, block, rows):
        if replacement is not None:
            rows = replacement
    return rows


# The attack sequence: declared (0) -> hit (1) -> damage (2).
_STAGE = {"attacked": 0, "hit": 1, "damaged": 2, "hit_ac": 1, "damage_reduction": 2, "damage_soak": 2}


def _stage(row: dict[str, Any]) -> int | None:
    return _STAGE.get(str(row.get("kind") if row.get("block") == "generic" else row.get("block")))


def _answer_ready(engine: Any, target: Any, attacker: Any | None, row: dict[str, Any], stage: int, info: dict[str, Any]) -> bool:
    """Whether ``row`` could still answer the attack now under way, at this moment or a later one; at
    this same moment it is checked exactly (would it turn this hit into a miss, is the damage above its
    minimum), since there it has either fired already or will be tried next."""
    at = _stage(row)
    if at is None or at < stage or not _can_react(engine, target, row) or _held_for_mark(engine, target, attacker, row):
        return False
    ranged, block = info.get("ranged"), row.get("block")
    if block == "hit_ac":
        if (row.get("ranged_only") and ranged is False) or not _holds(engine, target, row["resource_id"], row["cost"]):
            return False
        return not (at == stage and "total" in info and (info.get("natural", 0) >= int(info.get("critical_threshold", 20)) or info["total"] >= info["effective_ac"] + row["ac"]))
    if block in ("damage_reduction", "damage_soak"):
        if not _holds(engine, target, row["resource_id"], row["cost"] if block == "damage_reduction" else 1):
            return False
        if block == "damage_reduction" and row["trigger"] == "melee_weapon_hit" and ranged is True:
            return False
        return not (at == stage and "pending" in info and info["pending"] < row["minimum_damage"])
    if block != "generic" or not _can_trigger(engine, target, row) or not _generic_affordable(engine, target, row):
        return False
    # The same critical rule the offer path uses (owner 2026-10-02 MMX58, MMX53 review finding 2): a
    # row that cannot act against a natural 20 -- AC only, or AC plus a rider that waits for the miss --
    # is not "ready", so it must not make a lower-ranked reaction that CAN act (Parry) wait for it.
    if _skipped_by_critical(info.get("natural"), row, int(info.get("critical_threshold", 20))):
        return False
    if ranged is not None and not _generic_kind_ok(row, ranged=ranged, melee=not ranged):
        return False
    if not _generic_in_range(engine, target, attacker, row, subject=target, source=attacker) or not _subject_ok(engine, target, attacker, row):
        return False
    return not (at == stage == 2 and not _generic_damage_type_ok(engine, row))


def _outranked(engine: Any, target: Any, attacker: Any | None, row: dict[str, Any], stage: int, info: dict[str, Any]) -> bool:
    """The owner's order of importance: a ranked reaction waits while a more important one can still answer
    the same attack (e.g. Cloud-Sleeve Guard, ranked under Stamina Guard, is not spent before the roll while
    Stamina Guard is ready for the damage)."""
    if row.get("free") or "priority" not in row or _asking(engine, target, row):
        return False
    rows = (getattr(engine, "typed_reaction_rows", {}) or {}).get(target.entity_id, [])
    return any(other is not row and not other.get("held_back") and not other.get("free") and other.get("priority", 10**6) < row["priority"]
               and _answer_ready(engine, target, attacker, other, stage, info) for other in rows)


def _damage_answer_ready(engine: Any, target: Any, attacker: Any | None) -> bool:
    """Auto (owner 2026-09-26 "hold up and auto"): a damage soak or reduction this character could still
    use on the coming damage (Stamina Guard, a "when you take damage" reduction). An earlier reaction that
    cannot see the roll (Cloud-Sleeve Guard's -1d6 when the attack is declared) or only answers the hit
    (Spines Answer Violence) waits for it, instead of spending the Reaction first."""
    if not _can_react(engine, target):
        return False
    if any(_holds(engine, target, row["resource_id"], row["cost"]) and not _held_for_mark(engine, target, attacker, row)
           for row in _rows(engine, target.entity_id, "damage_reduction")):
        return True
    if any(_holds(engine, target, row["resource_id"], 1) and not _held_for_mark(engine, target, attacker, row)
           for row in _rows(engine, target.entity_id, "damage_soak")):
        return True
    # The full gate (a held resource, a once-per limit, a required mark), not only cost and range: Auto waited for a
    # guard that could never fire and lost both reactions (Astra's audit, 2026-09-26).
    return any(not row.get("free") and _can_trigger(engine, target, row) and _generic_affordable(engine, target, row)
               and _generic_in_range(engine, target, attacker, row, subject=target, source=attacker) and _subject_ok(engine, target, attacker, row)
               and any(isinstance(e, dict) and e.get("type") in ("damage_modifier", "half_damage") for e in row.get("effects") or [])
               for row in _generic_rows(engine, target.entity_id, "damaged"))


def declaration_priority_ok(engine: Any, target: Any, attacker: Any, row: dict[str, Any], *, ranged: bool) -> bool:
    """Shared pre-consent priority gate for typed and extension native declarations.

    My order reserves the Reaction for any higher-ranked available answer to
    this attack. Auto reserves it for an available damage guard; Ask me and
    free triggers retain their existing choice/economy policy. Consumers are
    on_attacked and flowing_river.native_response_declared. No payment occurs.
    """
    if "priority" in row:
        return not _outranked(engine, target, attacker, row, 0, {"ranged": ranged})
    return bool(row.get("free") or _asking(engine, target, row)
                or not _damage_answer_ready(engine, target, attacker))


def _typed(engine: Any, source_definition_id: str | None) -> dict[str, Any]:
    catalog = getattr(engine, "action_catalog", {}) or {}
    action = catalog.get(source_definition_id or "")
    if action is None:
        from . import ext

        aliases = ext.run_strict("damage_source_alias", engine, source_definition_id)
        if len(aliases) > 1:
            raise ValueError("one plugin must own a derived damage source")
        if aliases:
            action = catalog.get(aliases[0])
    return ((action.parameters or {}).get("typed") or {}) if action is not None else {}


def melee_weapon_source(engine: Any, source_definition_id: str | None) -> bool:
    """A Factory weapon or unarmed attack made in melee (not thrown)."""
    typed = _typed(engine, source_definition_id)
    kinds = {effect.get("attack_kind") for effect in typed.get("effects") or [] if effect.get("type") == "attack"}
    return bool(kinds & {"weapon", "unarmed"}) and not typed.get("range_ft")


def resists(engine: Any, target: Any, damage_type: str, source_definition_id: str | None) -> bool:
    """Passive resistance (e.g. Body Tempering: nonmagical Bludgeoning, Piercing and Slashing)."""
    return _defenses(engine, target, damage_type, source_definition_id, None)["resist"]


def resists_profile(engine: Any, target: Any, damage_type: str, profile: dict[str, Any]) -> bool:
    """Whether any effective Resistance covers this profile; does not consume it."""
    return resistance_profile(engine, target, damage_type, profile)["resist"]


def resistance_profile(engine: Any, target: Any, damage_type: str, profile: dict[str, Any], *,
                       excluded_feature_ids: tuple[str, ...] = (), source_id: str | None = None,
                       source_actor_id: str | None = None) -> dict[str, bool]:
    """Pure effective-resistance query for an explicit damage-source profile.

    Information abilities can ask about nonmagical damage or weapon attacks
    without inserting a fake action into a saved catalogue. The profile uses
    ordinary typed action fields (mundane, effects/attack_kind, range_ft).
    Conditions, passive rows, extension defenses and native actor resistances
    use the packet reader's normal eligibility and suppression rules. No packet
    is applied and no next-instance benefit is consumed. Returns ``resist`` for
    any effective Resistance, ``ordinary`` for Resistance that does not consume
    a next-instance group, and ``next_only`` when only that group covers it.
    Suppressed or ignored Resistance returns False for all three fields.
    """
    found = _defenses(engine, target, damage_type, source_id, source_actor_id, native=True, typed_profile=profile,
                      excluded_feature_ids=excluded_feature_ids)
    return {"resist": found["resist"], "ordinary": found["resistance_ordinary"],
            "next_only": found["resist"] and not found["resistance_ordinary"]}


# ---------------------------------------------------------------- opportunity attacks (owner 2026-09-26)
# The compiler gives every Factory fighter an "Opportunity Attack" reaction row (block "opportunity") that names a
# catalog-only action: one attack with its best melee weapon. It shows in the Reactions panel like any other.
def _opportunity_row(engine: Any, actor: Any) -> dict[str, Any] | None:
    return next(iter(_rows(engine, actor.entity_id, "opportunity")), None)


def _opportunity_profile(engine: Any, actor: Any, row: dict[str, Any]) -> tuple[Any, int]:
    """Resolve a temporary melee profile without changing saved rows or the catalog."""
    from . import ext

    action = engine.action_catalog[row["action_id"]]
    changed = False
    for point in ("opportunity_action", "opportunity_profile"):
        profiles = ext.run(point, engine, actor, action)
        if profiles:
            action, changed = profiles[0], True
    reach = int(action.range_ft or 5) if changed else int(row.get("reach_ft") or 5)
    # Legacy profile hooks express melee reach in range_ft. Native attack
    # validation reads reach_ft; keep the transient profile consistent without
    # rewriting the saved action or adding a condition-bound bonus twice.
    return action.model_copy(update={"reach_ft": reach}), reach


def physical_melee_reach(engine: Any, actor: Any) -> int | None:
    """Melee profile reach, independent of spent/disabled Reactions or reaction plans.

    Geometry consumers reuse the compiled melee profile, pure opportunity
    profile hooks, and current condition-bound attack-reach bonuses without
    asking whether an opportunity attack can fire. None means there is no
    compiled melee profile.
    """
    rows = (getattr(engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, [])
    row = next((r for r in rows if r.get("block") == "opportunity"), None)
    if row is None or row.get("action_id") not in (getattr(engine, "action_catalog", {}) or {}):
        return None
    action, base = _opportunity_profile(engine, actor, row)
    # Geometry consumers need the same condition-bound bonuses that govern
    # attack range, even when no Reaction is available to spend.
    from .attack_reach import maximum
    return maximum(engine, actor, action, base=base, opportunity=True)
def opportunity_reaction_row(engine: Any, actor: Any) -> dict[str, Any]:
    """Native OA waiver context; preserve the compiled weapon action and feature."""
    row = _opportunity_row(engine, actor) if actor.entity_id in getattr(engine, "typed_actor_ids", set()) else None
    return {**(row or {"feature_id": "reaction:core.opportunity_attack", "name": "Opportunity Attack", "block": "opportunity"}),
            "reaction_kind": "opportunity_attack"}


def opportunity_reach(engine: Any, actor: Any) -> int | None:
    """How far this fighter threatens, or None when it will not make opportunity attacks (off in its plan, or it
    cannot take reactions)."""
    row = _opportunity_row(engine, actor)
    if row is None or not _can_react(engine, actor, opportunity_reaction_row(engine, actor)) or row.get("action_id") not in (getattr(engine, "action_catalog", {}) or {}):
        return None
    from .attack_reach import maximum
    action, base = _opportunity_profile(engine, actor, row)
    return maximum(engine, actor, action, base=base, opportunity=True)


def opportunity_permitted_against(engine: Any, reactor: Any, mover: Any, *, uses_reaction: bool = True) -> bool:
    """Pure OA-specific prohibitions, shared by movement and explicit grants.

    Honors target-specific/global no-OA conditions, Charmed, subject reaction
    denial, opportunity_allowed vetoes and unseen-movement restrictions. Does
    not require leaving reach, inspect Reaction economy/plans, ask for consent,
    invoke opportunity_response, or spend. Explicit consumers combine this with
    can_use_reaction and their own reach/target rules, before offering and paying.
    """
    if any(c.condition_id == "condition:typed.charmed" and c.source_actor_id == mover.entity_id
           and (c.data or {}).get('allows_harming_source') is not True for c in reactor.conditions.values()):
        return False  # Charmed: it will not attack the charmer
    if any(c.condition_id == "condition:typed.no_opportunity_attacks" and (c.data or {}).get("against") in (None, mover.entity_id)
           for c in reactor.conditions.values()):
        return False  # Breath-Checking Strike, Hammer Rebuke ("against you": only that mover, combat/ext/blacksmith_rebuke.py)
    from . import unmaking

    if uses_reaction and unmaking.reactions_denied_against(reactor, mover):
        return False  # "cannot take Reactions against you"
    from . import ext

    if ext.any_false("opportunity_allowed", engine, reactor, mover):
        return False
    from . import motion

    if not motion.allows_opportunity_attack(engine, reactor, mover):
        return False  # Silent Step: not while the mover is unseen by it
    return True


def wants_opportunity_attack(engine: Any, reactor: Any, mover: Any, *, ask: bool = True, uses_reaction: bool = True,
                             consent_display: dict[str, Any] | None = None) -> bool:
    """Reaction plan eligibility; ask=False is strictly observational.

    Accepted attacks also offer the mover's optional protection response before
    reactor consent. This includes native steps and ability-granted attacks.
    """
    row = _opportunity_row(engine, reactor)
    if row is None or not _can_react(engine, reactor, opportunity_reaction_row(engine, reactor), uses_reaction=uses_reaction):
        return False
    if not opportunity_permitted_against(engine, reactor, mover, uses_reaction=uses_reaction):
        return False
    from . import ext

    if ask and ext.any_false("opportunity_response", engine, reactor, mover):
        return False
    if _asking(engine, reactor, row):
        # Removing the Reaction payment must not remove a manually controlled
        # creature's Ask-me decision. Payment and consent are separate parts of
        # an Opportunity Attack, including attacks granted for free.
        return _consent(engine, row, reactor, "LEAVE_REACH", trigger=consent_display) if ask else True
    if not uses_reaction:
        return True  # A free granted attack cannot spend the Reaction held for another trigger.
    if _held_for_mark(engine, reactor, mover, row):
        return False  # the Reaction is kept for a marked creature (step 15)
    if "priority" not in row:
        return True
    rows = [*(getattr(engine, "typed_reaction_rows", {}) or {}).get(reactor.entity_id, [])]
    return not any(other is not row and not other.get("held_back") and other.get("priority", 99) < row["priority"] for other in rows)


def opportunity_profile(engine: Any, actor: Any) -> tuple[dict[str, Any] | None, Any, int]:
    """Pure public profile for an explicitly granted Opportunity Attack.

    Factory actors return their owned reaction row and compiled attack. Native
    stock/runtime actors return a transient reaction row and their native attack
    spec. ``None`` means the actor has no supported melee profile. Explicit
    consumers still own target legality, consent and Reaction payment.
    """
    row = _opportunity_row(engine, actor)
    if row is None:
        from .gate2_engine import SYSTEM_OPPORTUNITY
        from .gate2_runtime_content import BASIC_MELEE
        if actor.entity_id in getattr(engine, "runtime_actor_ids", set()):
            spec = dict(engine.reaction_parameters.get("reaction:core.opportunity_attack", {}) or {})
            spec.setdefault("attack_bonus", 2)
            spec.setdefault("fixed_damage", 2)
            spec.setdefault("damage_type", "BLUDGEONING")
            reach = int(spec.get("reach_ft", 5))
        else:
            spec = dict(BASIC_MELEE.get(actor.entity_id) or {})
            reach = int(spec.get("reach_ft", 5)) if spec else 0
        if not spec:
            return None, None, 0
        row = {"feature_id": SYSTEM_OPPORTUNITY, "name": "Opportunity Attack",
               "block": "opportunity", "action_id": spec.get("source_definition_id", SYSTEM_OPPORTUNITY),
               "native_spec": spec, "reach_ft": reach,
               "effects": [{"type": "attack", "attack_kind": "weapon_melee", "count": 1}]}
        return row, spec, reach
    action, reach = _opportunity_profile(engine, actor, row)
    return row, action, reach


def opportunity_reaction_notice(engine: Any, actor: Any, target_ids: tuple[str, ...]) -> dict[str, Any] | None:
    """Build the complete public notice for a resolved OA, without changing its admission row.

    Reaction consumers that open a planned OA before executing it can publish
    the attack effects and the same source identity used by its roll. The
    planning row remains responsible for eligibility, waiver and payment.
    """
    row, action, _ = opportunity_profile(engine, actor)
    if row is None:
        return None
    if row.get("native_spec") is not None:
        from .gate2_engine import SYSTEM_OPPORTUNITY
        source_id = SYSTEM_OPPORTUNITY
        effects = row.get("effects") or []
        name = "Opportunity Attack"
    else:
        source_id = action.source_definition_id
        typed = action.parameters.get("typed") or {}
        effects = typed.get("effects") or []
        name = action.display_name
    return {**row, "feature_id": source_id, "name": name, "effects": effects,
            "target_ids": target_ids}


def opportunity_attack(engine: Any, reactor: Any, mover: Any, intent: Any, *, reach_ft: int | None = None,
                       reaction_opened: bool = False, trigger: str = "granted", uses_reaction: bool = True) -> None:
    """Resolve an explicitly granted OA using the Factory or native melee profile.

    ``reach_ft`` (general seam, rider lane C11) supports an attack the rule
    grants after forced movement took the target out of reach. ``reaction_opened``
    tells this resolver the caller already opened/published the paid Reaction.
    ``trigger`` names why this OA was granted: "movement" for a provoking step,
    "assistance" for a consensual grant, or "granted" by default for other rules.
    An immutable attack-completion notice captures this transient provenance
    before deferred delivery; native source identity alone is not a trigger.
    """
    from .paid_relocation import activation as relocation_activation

    row, profile, _ = opportunity_profile(engine, reactor)
    if row is None:
        return
    source = row["feature_id"] if row.get("native_spec") is not None else row["action_id"]
    attack_source = source if row.get("native_spec") is not None else profile.source_definition_id
    with relocation_activation(engine, reactor, source, independent=False), \
            opportunity_scope(engine, reactor, mover, trigger, attack_source):
        _opportunity_attack_in_scope(engine, reactor, mover, intent, reach_ft=reach_ft,
                                     reaction_opened=reaction_opened, uses_reaction=uses_reaction)


@contextmanager
def opportunity_scope(engine: Any, reactor: Any, target: Any, trigger: str, source: str):
    """Transient nested OA provenance; restores the parent on success or pause.

    Each frame names both participants and the attack source, so a different
    nested attack cannot inherit its trigger. Consumers read the completion notice, not this marker.
    """
    previous = getattr(engine, "_opportunity_attack_provenance", None)
    engine._opportunity_attack_provenance = (reactor.entity_id, target.entity_id, trigger, source)
    try:
        yield
    finally:
        engine._opportunity_attack_provenance = previous


def _opportunity_attack_in_scope(engine: Any, reactor: Any, mover: Any, intent: Any, *, reach_ft: int | None = None,
                                  reaction_opened: bool = False, uses_reaction: bool = True) -> None:
    row, profile, profiled_reach = opportunity_profile(engine, reactor)
    if row is None:
        return
    if row.get("native_spec") is not None:
        from .native_reactions import attack_scope
        from .gate2_engine import SYSTEM_OPPORTUNITY
        spec = dict(profile)
        spec["reach_ft"] = int(reach_ft if reach_ft is not None else profiled_reach)
        with attack_scope(engine, reactor, mover, SYSTEM_OPPORTUNITY, "Opportunity Attack",
                          runtime=reactor.entity_id in getattr(engine, "runtime_actor_ids", set()),
                          publish=uses_reaction and not reaction_opened):
            if reactor.entity_id in getattr(engine, "runtime_actor_ids", set()):
                from .character_runtime_adapter import CharacterCombatRuntimeEngine
                runtime = CharacterCombatRuntimeEngine.__new__(CharacterCombatRuntimeEngine)
                runtime.__dict__.update(engine.__dict__)
                CharacterCombatRuntimeEngine._resolve_character_attack(
                    runtime, reactor, mover, source_id=SYSTEM_OPPORTUNITY,
                    attack_bonus=int(spec.get("attack_bonus", 2)), damage=None,
                    damage_type=str(spec.get("damage_type", "BLUDGEONING")), intent=intent,
                    fixed_damage=int(spec.get("fixed_damage", 2)), ranged=False)
                engine.__dict__.update(runtime.__dict__)
            else:
                engine._resolve_attack_spec(reactor, mover, spec, intent, reaction_depth=1,
                                            source_definition_id=SYSTEM_OPPORTUNITY)
        return
    from .typed_executor import Context, run_effects
    action, profiled_reach = profile, profiled_reach
    if reach_ft is None and profiled_reach != int(row.get('reach_ft') or 5):
        # Dynamic opportunity-only reach must survive the shared reaction
        # attack check. Ordinary profiles retain their existing effect metadata.
        reach_ft = profiled_reach
    typed = dict(action.parameters.get("typed") or {})
    typed["reaction_attack"] = True
    if reach_ft is not None:
        action = action.model_copy(update={"reach_ft": int(reach_ft)})
        typed = {**typed, "reaction_attack": True,
                 "effects": [{**row, "reach_ft": int(reach_ft)} if isinstance(row, dict) and row.get("type") == "attack" else row
                             for row in typed.get("effects") or []]}
    previous, engine._typed_oa_attacker = getattr(engine, "_typed_oa_attacker", None), reactor.entity_id
    try:
        context = Context(engine, reactor, action, intent, typed, [mover], mover)
        from . import ext

        ext.run("opportunity_attempt", context, mover)
        # Gate2 already opened and paid for this Factory window. Publish its
        # accepted Reaction once, without adding another window or payment.
        if uses_reaction and not reaction_opened:
            publish_reaction_used(engine, reactor, {
                "feature_id": action.source_definition_id, "name": "Opportunity Attack",
                "effects": typed.get("effects") or [],
            })
        run_effects(context, typed.get("effects") or [])
    finally:
        engine._typed_oa_attacker = previous
    on_own_event(engine, reactor, mover, "own_action", accept=lambda row: row.get("action") == "opportunity_attack")


# ---------------------------------------------------------------- damage defences (owner 2026-09-26)
# The Tianxia order (Stamina Guard, Orbital Body): Immunity, then Resistance, then Vulnerability, then flat
# reductions.  Sources: modifiers from abilities in use (damage_immunity / damage_resistance /
# damage_vulnerability[_next], resistance_suppressed) and always-on rows ("resistance" and "defense" blocks).
def _source_attack_kinds(typed: dict[str, Any]) -> set[str]:
    return {str(effect.get("attack_kind") or "") for effect in typed.get("effects") or [] if effect.get("type") == "attack"}


def _counts_as_mundane(engine: Any, typed: dict[str, Any], source_actor_id: str | None) -> bool:
    """Whether this packet comes from a nonmagical attack, which is what a "nonmagical" defense is printed against.

    The saved action's own ``mundane`` flag answers first (absent is not nonmagical, as before). A plug-in may then say
    the attack counts as magical instead, whatever the weapon is: the ``attack_magical(engine, source_actor_id, typed)``
    hook. General on purpose -- any printed "your attacks count as magical" (Sovereign Needle Incarnation) registers it,
    and no ability is named here.
    """
    if typed.get("mundane"):
        from . import ext

        if source_actor_id and ext.has("attack_magical") and any(ext.run("attack_magical", engine, source_actor_id, typed)):
            return False
    return bool(typed.get("mundane"))


def _defense_applies(engine: Any, target: Any, row: dict[str, Any], kind: str, typed: dict[str, Any],
                     source_actor_id: str | None = None) -> bool:
    if kind not in row["damage_types"]:
        return False
    if row.get("mundane_only") and not _counts_as_mundane(engine, typed, source_actor_id):
        return False
    if row.get("attacks_only") and not _source_attack_kinds(typed):
        return False
    if row.get("attack_kinds") and not _source_attack_kinds(typed) & set(row["attack_kinds"]):
        return False
    if row.get("martial_focus") and target.resources.get("resource:core.martial_focus", 0) < 1:
        return False  # "while holding Martial Focus"
    if row.get("requires_condition") and not any(c.condition_id == row["requires_condition"] for c in target.conditions.values()):
        return False  # a generic "while <stance/condition>" gate (body 2026-09-29, Berserk: "while Adrenaline is active")
    return True


def _resistance_ignored(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str | None, target: Any = None) -> bool:
    """The damage's own ability ignores it (Targeted Assault's "ignore the target's Resistance ... for that attack"),
    or the attacker always does (Folded Edge, Hidden Spine: "melee attacks ignore ordinary Resistance").
    An ``ignore_resistance`` effect with ``if_marked`` does so only against a target that bears that mark of the attacker (riders lane 2
    2026-09-29, One-Inch Heavenquake: "ignoring Resistance to Bludgeoning and Force damage against an Opened target")."""
    from .typed_executor import _mark_slug, bears_mark, opened_before

    for effect in _walk_effects(typed.get("effects") or []):
        if effect.get("type") != "ignore_resistance" or kind not in [str(t).upper() for t in effect.get("damage_types") or []]:
            continue
        if effect.get("if_marked"):
            was = opened_before(engine, source_actor_id, target.entity_id) if target is not None and source_actor_id and _mark_slug(effect["if_marked"]) == "opened" else None
            if not (target is not None and source_actor_id and (was if was is not None else bears_mark(target, source_actor_id, str(effect["if_marked"])))):
                continue
        return True
    if not source_actor_id:
        return False
    from . import ext  # a plug-in's own reason (Edge Before Blood: the first hit with a set edge)
    # ``target`` is the creature taking this packet, so a plug-in can scope its bypass to one chosen
    # creature and one source ("your Spear talents against it", AUTO56f2 2026-10-05) instead of to everyone.
    if ext.has("resistance_ignored") and any(ext.run("resistance_ignored", engine, kind, typed, source_actor_id, target)):
        return True
    kinds = _source_attack_kinds(typed)
    for row in _rows(engine, source_actor_id, "defense"):
        if row["kind"] != "ignore_resistance" or kind not in row["damage_types"]:
            continue
        if row["attack_kinds"] and not kinds & set(row["attack_kinds"]):
            continue
        if row.get("melee_only") and typed.get("range_ft"):
            continue
        source = engine.state.actors.get(source_actor_id)  # "while <stance>" (Sovereign Iron-Body Incarnation)
        if row.get("requires_condition") and not (source is not None and any(c.condition_id == row["requires_condition"] for c in source.conditions.values())):
            continue
        return True
    return False


def _walk_effects(effects: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for effect in effects:
        if isinstance(effect, dict):
            out.append(effect)
            for key in ("on_hit", "on_miss", "on_fail", "on_success"):
                out.extend(_walk_effects(effect.get(key) or []))
    return out


def additional_defenses(engine, target, damage_type, source_definition_id, source_actor_id):
    """Optional data defenses shared by Factory and native packet readers."""
    from . import ext
    kind = str(damage_type).upper()
    typed = _typed(engine, source_definition_id)
    rows = []
    for answer in ext.run_strict('damage_defenses', engine, target, kind, typed, source_actor_id):
        if not isinstance(answer, list) or any(not isinstance(row, dict) for row in answer):
            raise ValueError('damage_defenses requires a list of defense rows')
        rows.extend(row for row in answer if _defense_applies(engine, target, row, kind, typed, source_actor_id))
    return rows


def damage_bonus_eligible(engine, target, damage_type, source_definition_id, source_actor_id):
    """Whether this packet can deal typed damage before damage-bonus riders are offered.

    This is a read-only preview of the same immunity rules used by ``defend``. It
    lets shared damage-bonus hooks honor triggers that require damage dealt while
    keeping all defense precedence and immunity bypasses centralized here.
    """
    typed_target = target.entity_id in getattr(engine, "typed_actor_ids", set())
    additional = None if typed_target else additional_defenses(
        engine, target, damage_type, source_definition_id, source_actor_id)
    defenses = _defenses(engine, target, damage_type, source_definition_id, source_actor_id,
                         additional=additional, native=not typed_target)
    return not defenses["immune"]


def _defenses(engine: Any, target: Any, damage_type: str, source_definition_id: str | None, source_actor_id: str | None, *, additional=None, native=False, typed_profile=None,
              excluded_feature_ids: tuple[str, ...] = ()) -> dict[str, Any]:
    from . import ext

    kind = str(damage_type).upper()
    typed = _typed(engine, source_definition_id) if typed_profile is None else typed_profile
    extra_rows = [row for group in ext.run("damage_defenses", engine, target, kind, typed, source_actor_id)
                  for row in (group or [])]
    rows = [row for row in (*_rows(engine, target.entity_id, "resistance"), *_rows(engine, target.entity_id, "defense"), *extra_rows)
            if row.get("kind", "resistance") not in ("ignore_resistance", "ac", "ac_calculation", "save_advantage") and _defense_applies(engine, target, row, kind, typed, source_actor_id)
            and not (row.get("once_per_round") and target.turn_flags.get(f"defense_round_used:{row['feature_id']}") == engine.state.round_number)]
    rows.extend(additional_defenses(engine, target, kind, source_definition_id, source_actor_id) if additional is None and typed_profile is None else additional or [])
    if excluded_feature_ids:
        rows = [row for row in rows if row.get('feature_id') not in excluded_feature_ids]
    modifiers = list(target.modifiers.items())
    source_cl = int((typed.get("numbers") or {}).get("cl") or 0)
    immune = any(m.target_field == "damage_immunity" and str(m.value) == kind for _, m in modifiers) or any(
        row.get("kind") == "immunity" or (row.get("immune_below_cl") and 0 < source_cl < row["immune_below_cl"]) for row in rows)
    # A source whose damage treats Immunity as Resistance (rider lane C7: Myriad-Venom Immortal's "Poison Immunity is treated as
    # Resistance, then your feature ignores that Resistance"): ext ``immunity_as_resistance``; absent: unchanged.
    as_resistance = bool(immune and source_actor_id and ext.has("immunity_as_resistance")
                         and any(ext.run("immunity_as_resistance", engine, kind, typed, source_actor_id, target)))
    if as_resistance:
        immune = False
    # Next-instance Resistance is one source-owned group, possibly covering several
    # damage types. Queries remain pure; defend consumes all types in a matching
    # group once the positive packet arrives. Ordinary Resistance is unchanged.
    next_groups = {(m.source_definition_id, m.source_actor_id) for _, m in modifiers
                   if m.target_field == "damage_resistance_next" and str(m.value) == kind}
    ordinary = as_resistance or any(m.target_field == "damage_resistance" and str(m.value) == kind for _, m in modifiers) or any(
        row.get("kind", "resistance") == "resistance" for row in rows)
    if native and target.entity_id in getattr(engine, 'runtime_actor_ids', set()):
        ordinary = ordinary or kind in {str(value).upper() for value in target.damage_resistances}
    resist = ordinary or bool(next_groups)
    suppressed = (any(m.target_field == "resistance_suppressed" and str(m.value) == kind for _, m in modifiers)
                  or _resistance_ignored(engine, kind, typed, source_actor_id, target)
                  or native and source_definition_id in getattr(engine, '_ignore_resistance_sources', set()))
    if resist and suppressed:
        resist = False
        ordinary = False
    once = [mid for mid, m in modifiers if m.target_field == "damage_vulnerability_next" and str(m.value) == kind]
    vulnerable = bool(once) or any(m.target_field == "damage_vulnerability" and str(m.value) == kind for _, m in modifiers) or any(
        row.get("kind") == "vulnerability" for row in rows)
    reduction = sum(int(row.get("amount") or 0) for row in rows if row.get("kind") == "reduction")
    # "Apply this reduction before Resistance" (Berserk, body 2026-09-29): a second, separate reduction kind
    # subtracted before the resist/vulnerable multiplication in defend() below, unlike the ordinary "reduction"
    # kind above (every already-shipped talent using it reduces after Resistance, so that ordering is unchanged).
    pre_reduction = sum(int(row.get("amount") or 0) for row in rows if row.get("kind") == "reduction_before_resistance")
    # A plug-in's flat reduction (Ironclad Line, combat/ext/warleader.py): ``damage_reduction`` hook, pure here (this also runs to
    # only weigh a damage type); defend() calls it once more with applied=True for the plug-in's own side effects.
    extra = sum(int(amount) for amount in ext.run("damage_reduction", engine, target, kind, typed, source_actor_id)) if ext.has("damage_reduction") else 0
    reduction += extra
    return {"immune": immune, "resist": resist, "resistance_suppressed": bool(suppressed), "resistance_ordinary": ordinary, "vulnerable": vulnerable, "once": once,
            "resistance_next": [mid for mid, m in modifiers if m.target_field == "damage_resistance_next"
                                and (m.source_definition_id, m.source_actor_id) in next_groups],
            "reduction": reduction, "pre_reduction": pre_reduction, "ext_reduction": extra,
            "per_round": [row["feature_id"] for row in rows if row.get("kind") == "reduction" and row.get("once_per_round")]}


def damage_factor(engine: Any, target: Any, damage_type: str, source_definition_id: str | None, source_actor_id: str | None) -> float:
    """How much of a packet of this type lands (0, 0.5, 1, 2), for choosing among "Fire or Cold" damage."""
    found = _defenses(engine, target, damage_type, source_definition_id, source_actor_id)
    if found["immune"]:
        return 0.0
    return (0.5 if found["resist"] else 1.0) * (2.0 if found["vulnerable"] else 1.0)


# ---------------------------------------------------------------- damage defence display (owner 2026-10-12, RESIST)
# The character sheet's Defences & Conditions card lists what a creature
# resists, is vulnerable to and is immune to.  This is a read-only
# projection of the same rows and modifiers defend() and condition_immune()
# weigh, so the card cannot disagree with the fight.  What only a
# particular attack knows -- its own "ignore Resistance", an attacker's
# penetration, a low cultivation level -- is settled when that attack
# resolves, so a defence those could touch is still listed: the creature
# does have it.

_DAMAGE_DEFENSE_MODIFIERS = {
    "damage_resistance": "resistances",
    "damage_resistance_next": "resistances",
    "damage_immunity": "immunities",
    "damage_vulnerability": "vulnerabilities",
    "damage_vulnerability_next": "vulnerabilities",
}

_DAMAGE_DEFENSE_ROWS = {"resistance": "resistances", "immunity": "immunities", "vulnerability": "vulnerabilities"}
# Flat reductions (defend() subtracts them) are listed in their own "reductions" tier as "<type> damage reduced by N";
# the value is the extra words a row of that kind adds.
_REDUCTION_ROWS = {"reduction": None, "reduction_before_resistance": "applied before Resistance"}
_SUPPRESSED_NOTE = "suppressed: ignored while the creature's Resistance is suppressed"


def _shows_without_attack(target: Any, row: dict[str, Any], kind: str) -> bool:
    """Whether a compiled row applies to the creature's own state, ignoring the attack it would answer.

    The attack-only gates (attacks_only, attack_kinds, mundane_only) need a real packet, so the card lists those
    rows with a qualifier note (``_row_note``).  The state gates (martial_focus, requires_condition) still decide.
    """
    if kind not in row["damage_types"]:
        return False
    if row.get("martial_focus") and target.resources.get("resource:core.martial_focus", 0) < 1:
        return False
    if row.get("requires_condition") and not any(c.condition_id == row["requires_condition"] for c in target.conditions.values()):
        return False
    return True


def _row_note(row: dict[str, Any]) -> str | None:
    """The printed qualifier of a conditional row, in the words the card shows."""
    parts = []
    if row.get("immune_below_cl"):
        parts.append("against creatures of a lower cultivation level")
    if row.get("mundane_only"):
        parts.append("only against nonmagical attacks")
    if row.get("attacks_only"):
        parts.append("only against attacks")
    if row.get("attack_kinds"):
        parts.append("only against " + " or ".join(str(kind).lower() for kind in row["attack_kinds"]) + " attacks")
    if row.get("requires_condition"):
        from .presentation import condition_label
        parts.append(f"while {condition_label(row['requires_condition']).lower()} is active")
    if row.get("martial_focus"):
        parts.append("while holding Martial Focus")
    return ", ".join(parts) or None


def _reduction_row_text(kind: Any, amount: Any, row: dict[str, Any]) -> tuple[str, str | None]:
    """The sentence a flat reduction shows on the card, and its qualifier (the printed condition plus its once-a-round limit)."""
    named = "All damage types" if str(kind).upper() == "ALL" else f"{str(kind).title()} damage"
    text = f"{named} reduced by {int(amount or 0)}"
    if _REDUCTION_ROWS[row.get("kind")]:
        text += f", {_REDUCTION_ROWS[row['kind']]}"
    parts = [part for part in (_row_note(row), "once per round" if row.get("once_per_round") else None) if part]
    return text, ", ".join(parts) or None


def _hook_defense_rows(engine: Any, target: Any, kind: str, described: set[str] | None = None) -> list[dict[str, Any]]:
    """The ``damage_defenses`` rows the card can name for one damage type, with no attack in hand.

    The card asks the same hook damage resolution asks, and with the same empty packet (no source definition, so an
    empty attack profile), so the two cannot disagree about which plug-ins answer.  It then keeps the rows whose
    remaining gates are about the creature itself (``_shows_without_attack``) and shows the attack-only gates as the
    printed qualifier (``_row_note``) instead of dropping a defence the creature really has: a row gated on
    ``mundane_only``, ``attacks_only`` or ``attack_kinds`` (Weatherproof Mantle's nonmagical ranged weapon Resistance)
    describes an attack that has not been rolled yet, not a benefit the creature lacks.  Display only: combat's own
    ``additional_defenses`` keeps filtering these rows for real packets.

    ``described`` holds the source ids a plug-in already names through the ``defense_description`` hook, so a plug-in
    that describes its own defence is listed once, in its own words.
    """
    from . import ext

    typed = _typed(engine, None)
    named_elsewhere = {str(feature) for feature in (described or set()) if feature}
    rows: list[dict[str, Any]] = []
    for answer in ext.run_strict('damage_defenses', engine, target, kind, typed, None):
        if not isinstance(answer, list) or any(not isinstance(row, dict) for row in answer):
            raise ValueError('damage_defenses requires a list of defense rows')
        for row in answer:
            feature = str(row.get("feature_id") or row.get("name") or "")
            if feature and feature in named_elsewhere:
                continue  # this plug-in names the defence itself, through defense_description
            if _shows_without_attack(target, row, kind):
                rows.append(row)
    return rows


def _lifetime_text(expires_on: Any, duration_text: Any, source: str = "the effect", target: Any = None,
                   holders: dict[str, str] | None = None, engine: Any = None) -> str | None:
    """When a temporary defence ends in the words the card shows: a turn boundary, "until used or removed" for a
    one-use benefit (the ``CONSUMED`` expiry, via ``duration_text``), or None for one that lasts until removed."""
    if not expires_on or expires_on == "UNTIL_REMOVED":
        return None
    return duration_text(expires_on, {}, {}, source, getattr(target, "display_name", "") if target else "",
                         holders or {}, engine)


def _until_text(modifier: Any, target: Any, engine: Any, holders: dict[str, str], duration_text: Any) -> str | None:
    return _lifetime_text(modifier.expires_on, duration_text, holders.get(modifier.source_actor_id) or "the effect",
                          target, holders, engine)


def defense_display(engine: Any, target: Any, names: dict[str, str] | None = None) -> dict[str, list[dict[str, Any]]]:
    """The creature's current Resistances, Vulnerabilities and Immunities, each with its source.

    ``{"resistances": [...], "vulnerabilities": [...], "immunities": [...], "reductions": [...]}`` where each row
    is ``{"damage_type"|"condition": str, "source": str|None, "until": str|None, "note": str|None}``
    -- the damage type or condition in the words a player reads, the ability or condition that
    grants it, when a temporary one ends (``None`` for one that lasts until removed), and a
    printed qualifier where the defence is conditional.  ``names`` maps a source id to the
    words the table shows for it (the service's action and feature names); an id it does not
    know reads as an active effect.  Pure: reads the actor's modifiers, compiled rows,
    condition rules and the standing ``damage_defenses`` answers, and changes no fight state.
    ``reductions`` lists flat damage reductions (Body Conditioning) as
    ``{"damage_type": "Bludgeoning damage reduced by 4", "source", "until": None, "note"}``.  They are a
    separate tier: a Resistance-piercing attack does not bypass them.
    """
    from . import presentation
    from .factory_compiler import _DAMAGE_TYPES
    from .status_text import duration_text
    from .typed_executor import condition_rule_instances

    def words(identifier: Any) -> str:
        """A readable stand-in for a source id the caller's names do not cover."""
        tail = str(identifier).split(":")[-1].split(".")[-1]
        return " ".join(part.capitalize() for part in tail.replace("-", "_").split("_") if part) or "Active effect"

    def source_of(identifier: Any) -> str:
        if not identifier:
            return "Active effect"
        return (names or {}).get(str(identifier)) or words(identifier)

    listed: dict[str, dict[str, list[tuple[str, str | None, str | None]]]] = {
        "resistances": {}, "vulnerabilities": {}, "immunities": {}}
    condition_immunities: dict[str, list[tuple[str, str | None, str | None]]] = {}
    reductions: list[tuple[str, str, str | None]] = []  # (sentence, source, qualifier)

    def add_reduction(kind: Any, amount: Any, row: dict[str, Any], source: str) -> None:
        text, note = _reduction_row_text(kind, amount, row)
        if (text, source, note) not in reductions:
            reductions.append((text, source, note))

    def add(tier: str, kind: Any, source: str, until: str | None = None, note: str | None = None) -> None:
        kind = str(kind or "").upper().strip()
        if not kind:
            return
        # "ALL" (every damage type) is kept as one row, listed as "All damage types".
        if tier == "resistances" and kind in suppressed_kinds:
            note = _SUPPRESSED_NOTE
        rows = listed[tier].setdefault(kind, [])
        if (source, until, note) not in rows:
            rows.append((source, until, note))

    # Active-effect modifiers: the temporary ones ("Vulnerability to the next
    # Fire damage it takes", a granted Resistance that ends at a turn
    # boundary) included, exactly as defend() weighs them.
    holders = {actor.entity_id: actor.display_name for actor in engine.state.actors.values()}
    # defend() drops every Resistance of a kind the creature has "resistance_suppressed" for (typed_reactions.defend).
    # The card reads that same fact so a suppressed benefit reads as suppressed, not as active.
    suppressed_kinds = {str(m.value).upper() for m in target.modifiers.values() if m.target_field == "resistance_suppressed"}
    for modifier in target.modifiers.values():
        if modifier.target_field == "condition_immunity":
            # A reviewed "Immunity to Poisoned" and its like (condition_immune's modifier read).
            source = source_of(modifier.source_definition_id)
            until = _until_text(modifier, target, engine, holders, duration_text)
            rows = condition_immunities.setdefault(str(modifier.value).lower(), [])
            if (source, until, None) not in rows:
                rows.append((source, until, None))
            continue
        tier = _DAMAGE_DEFENSE_MODIFIERS.get(modifier.target_field)
        if not tier:
            continue
        until = _until_text(modifier, target, engine, holders, duration_text)
        # defend() spends a "_next" defence on the next damage of that type, whatever its listed expiry says.
        once = "next damage of that type only" if modifier.target_field.endswith("_next") else None
        add(tier, modifier.value, source_of(modifier.source_definition_id), until, once)

    # Compiled condition-immunity rows ("Immunity to Poisoned" passives: the
    # ``condition_immunity`` block condition_immune reads).
    for row in _rows(engine, target.entity_id, "condition_immunity"):
        source = source_of(row.get("feature_id"))
        for name in row.get("conditions") or ():
            key = str(name).lower()
            rows = condition_immunities.setdefault(key, [])
            if (source, None, None) not in rows:
                rows.append((source, None, None))

    # Compiled always-on rows ("resistance" and "defense" blocks), gated the
    # way damage resolution gates them: an empty packet is no attack and no
    # mundane one, so attack-only and nonmagical-only rows stay off the card,
    # while a "while <condition>" or "while holding Martial Focus" row shows
    # only while its gate really holds.
    for row in (*_rows(engine, target.entity_id, "resistance"), *_rows(engine, target.entity_id, "defense")):
        row_kind = row.get("kind", "resistance")
        tier = _DAMAGE_DEFENSE_ROWS.get(row_kind)
        if not tier and row_kind not in _REDUCTION_ROWS:
            continue
        source = row.get("source") or source_of(row.get("feature_id"))
        note = _row_note(row)
        for kind in row.get("damage_types") or ():
            if _shows_without_attack(target, row, str(kind).upper()):
                if tier:
                    add(tier, kind, source, note=note)
                else:
                    add_reduction(kind, row.get("amount"), row, source)

    # Plug-in descriptions (the ``defense_description`` hook, ext/__init__.py): the defences a plug-in grants that the
    # compiled rows above cannot show without an attack in hand (Qi's Defensive Form, Death's Sovereign, Dark's Night).
    # Their source ids are remembered so the standing hook answers below do not list the same defence a second time.
    from . import ext
    described_features: set[str] = set()
    for described in ext.run("defense_description", engine, target) if ext.has("defense_description") else ():
        for row in described or ():
            source = row.get("source") or source_of(row.get("feature_id"))
            if row.get("feature_id") or row.get("name"):
                described_features.add(str(row.get("feature_id") or row.get("name")))
            until = _lifetime_text(row.get("expires_on"), duration_text, source, target, holders, engine)
            for kind in row.get("damage_types") or ():
                add("resistances", kind, source, until, row.get("note"))
            conditions = row.get("conditions")
            for name in ([conditions] if isinstance(conditions, str) else conditions or ()):
                rows = condition_immunities.setdefault(str(name).lower(), [])
                if (source, until, row.get("note")) not in rows:
                    rows.append((source, until, row.get("note")))

    # Conditions that carry their own defence rules (Petrified: Resistance to
    # every damage type and immunity to Poisoned), named as the condition
    # itself -- the pill the table already shows.
    every_kind: set[str] = set()
    for condition, row in condition_rule_instances(target, engine=engine):
        source = presentation.condition_label(condition.condition_id, condition.data)
        until = _lifetime_text(condition.expires_on, duration_text, source, target, holders, engine)
        resisted = [str(kind).upper() for kind in row.get("damage_resistances") or ()]
        if "ALL" in resisted:
            every_kind.update(_DAMAGE_TYPES)
            listed["resistances"].setdefault("ALL", []).append((source, until, None))
        else:
            for kind in resisted:
                add("resistances", kind, source, until)
        for name in row.get("condition_immunities") or ():
            key = str(name).lower()
            rows = condition_immunities.setdefault(key, [])
            if (source, until, None) not in rows:
                rows.append((source, until, None))

    def condition_source_of(kind: str) -> str | None:
        """The condition whose own rule names this damage type, if any."""
        for condition, row in condition_rule_instances(target, engine=engine):
            resisted = [str(named).upper() for named in row.get("damage_resistances") or ()]
            if kind in resisted or "ALL" in resisted:
                return presentation.condition_label(condition.condition_id, condition.data)
        return None

    # Standing answers from plug-ins (the ``damage_defenses`` hook): the same
    # rows damage resolution adds for a packet of each type, listed even when
    # they only answer for a kind of attack, with that attack named as the
    # qualifier (``_hook_defense_rows``).  A condition
    # that resists every damage type is listed once, as "All damage types",
    # so its per-type answers are not repeated type by type.
    for kind in _DAMAGE_TYPES:
        for row in _hook_defense_rows(engine, target, kind, described_features):
            row_kind = row.get("kind", "resistance")
            tier = _DAMAGE_DEFENSE_ROWS.get(row_kind)
            if not tier and row_kind not in _REDUCTION_ROWS:
                continue
            feature = row.get("feature_id") or row.get("name")
            if not feature:
                if kind in every_kind:
                    continue
                feature = condition_source_of(kind)
            source = source_of(feature) if feature else "Active effect"
            if not tier:
                for named in row.get("damage_types") or ():
                    add_reduction(named, row.get("amount"), row, source)
                continue
            note = _row_note(row)
            for named in row.get("damage_types") or ():
                add(tier, named, source, note=note)

    # A creature's own nature (a summon's form): no ability to name.
    for kind in target.damage_resistances:
        add("resistances", kind, None)

    def emitted(tier: str) -> list[dict[str, Any]]:
        out = []
        for kind in sorted(listed[tier]):
            if kind == "ALL":
                for source, until, note in listed[tier][kind]:
                    out.append({"damage_type": "All damage types", "source": source, "until": until, "note": note})
                continue
            for source, until, note in listed[tier][kind]:
                out.append({"damage_type": kind.title(), "source": source, "until": until, "note": note})
        return out

    return {
        "resistances": emitted("resistances"),
        "reductions": [{"damage_type": text, "source": source, "until": None, "note": note} for text, source, note in reductions],
        "vulnerabilities": emitted("vulnerabilities"),
        "immunities": [*emitted("immunities"), *(
            {"condition": name.title(), "source": source, "until": until, "note": note}
            for name in sorted(condition_immunities)
            for source, until, note in condition_immunities[name])],
    }


def defend(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str | None, source_actor_id: str | None, *, additional=None, native=False) -> int:
    """The damage a Factory fighter actually takes before reactions: called by the engine's damage commit."""
    from . import ext
    positive_incoming_instance = amount > 0

    from .ext.damage_transfer_scope import already_defended_packet, transfers_allowed

    if engine.__dict__.get("_damage_unreduced") == target.entity_id and already_defended_packet(engine, target):
        # Shares whose defenses already ran also received additions. A share
        # that bars reductions still receives additions once at commit.
        if amount > 0 and engine.__dict__.get("_damage_bonus_already_applied") != target.entity_id:
            amount += sum(int(part or 0) for part in ext.run("incoming_damage_bonus", engine, target, amount, damage_type,
                                                           source_definition_id, source_actor_id))
        ext.run("damage_defended", engine, target, damage_type, source_definition_id, source_actor_id,
                {"resist": False, "resistance_suppressed": True})
        return amount
    if amount > 0 and transfers_allowed(engine, target):
        # Source-owned adjustments affect the original packet once, before it
        # can be split. Recipient-owned defenses remain below the transfer.
        amount = max(0, amount - sum(int(part or 0) for part in ext.run("source_damage_reduction", engine, target, amount,
                                                                        damage_type, source_definition_id, source_actor_id)))
    if amount > 0 and transfers_allowed(engine, target) and ext.has("pre_defense_transfer"):
        # "pre_defense_transfer": a rule that moves part of this packet onto another creature before ANY of this target's own
        # defenses (Immunity, Resistance, Vulnerability, reductions) -- Shared Breath Guardian's "before applying the spirit's
        # Resistance, Immunity, or Vulnerability". Each answer is the points it took away (and already committed elsewhere);
        # the rest meets this target's defenses below.
        amount = max(0, amount - sum(int(part or 0) for part in ext.run("pre_defense_transfer", engine, target, amount,
                                                                        str(damage_type).upper(), source_definition_id,
                                                                        source_actor_id)))
    packet_rows: list[Any] = []
    if amount > 0:
        # Actual packet checkpoint, before one-packet defenses are consumed. Each provider is dispatched exactly once
        # (its response may spend a Reaction or Stamina); a None reply adds nothing, a list adds defense rows for this packet.
        # Quotes/AI estimates still use the pure _defenses query directly.
        for reply in ext.iter_strict_all("before_damage_defenses", engine, target, amount, str(damage_type).upper(),
                                         source_definition_id, source_actor_id):
            if reply is None:
                continue
            if not isinstance(reply, (list, tuple)):
                raise ValueError("before_damage_defenses must return None or defense rows")
            packet_rows.append(reply)
    found = _defenses(engine, target, damage_type, source_definition_id, source_actor_id, additional=additional, native=native)
    if amount > 0 and not found["immune"] and ext.has("before_damage_defenses"):
        extra = [row for group in packet_rows for row in group]
        if any(not isinstance(row, dict) or row.get("kind") not in {"resistance", "immunity", "reduction"} for row in extra):
            raise ValueError("before_damage_defenses requires defense rows")
        baseline = additional_defenses(engine, target, str(damage_type).upper(), source_definition_id, source_actor_id) if additional is None else additional
        found = _defenses(engine, target, damage_type, source_definition_id, source_actor_id,
                          additional=[*baseline, *extra], native=native)
    # A positive matching instance qualifies a one-use defense even when
    # Immunity or a later reduction prevents HP loss. Preserve that eligibility
    # before the defense callbacks settle, while leaving zero packets inert.
    consume_resistance_next = positive_incoming_instance and bool(found["resistance_next"])
    if found["immune"]:
        ext.run("damage_defended", engine, target, damage_type, source_definition_id, source_actor_id,
                {"resist": False, "resistance_suppressed": bool(found["resistance_suppressed"])})
        if consume_resistance_next:
            _consume_resistance_next(engine, target, found["resistance_next"])
        return 0
    from . import ext

    # Pure, target-bound additions share the triggering packet's defenses.
    # Plugins consume their next-use state only on a positive committed packet.
    if amount > 0:
        amount += sum(int(part or 0) for part in ext.run("incoming_damage_bonus", engine, target, amount, damage_type,
                                                       source_definition_id, source_actor_id))

    # "incoming_damage": a plug-in may take part of the packet off before Resistance. Each hook returns points of
    # damage to subtract, so several plug-ins add up regardless of order.
    amount = max(0, amount - sum(int(part or 0) for part in ext.run("incoming_damage", engine, target, amount, damage_type,
                                                                     source_definition_id, source_actor_id)))
    if found["pre_reduction"]:
        amount = max(0, amount - found["pre_reduction"])
    if found["resist"]:
        amount //= 2
    if found["vulnerable"]:
        amount *= 2
    if found["reduction"] and amount > 0:
        for feature in found["per_round"]:  # "once per round, when you take bludgeoning damage" (Padded Layers)
            target.turn_flags[f"defense_round_used:{feature}"] = engine.state.round_number
    for mid in found["once"]:  # "Vulnerability to the next ... damage it takes"
        modifier = target.modifiers.pop(mid, None)
        if modifier is not None:
            engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=target.entity_id,
                                 target_ids=(target.entity_id,), payload={"modifier_id": mid, "reason": "CONSUMED"})
    if found["ext_reduction"] and amount > 0:  # the plug-in's reduction really applied: let it record that (Momentum Marks)
        ext.run("damage_reduction", engine, target, str(damage_type).upper(), _typed(engine, source_definition_id), source_actor_id, True)
    # Settle one-instance Resistance after packet callbacks. Providers may need
    # the pre-consumption defense set to record why a reduction was eligible.
    if consume_resistance_next:
        _consume_resistance_next(engine, target, found["resistance_next"])
    ext.run("damage_defended", engine, target, damage_type, source_definition_id, source_actor_id,
            {"resist": bool(found["resist"]), "resistance_suppressed": bool(found["resistance_suppressed"])})
    pending = max(0, amount - found["reduction"])
    # Paid, packet-scoped responses compose with passive defenses and with
    # later damage reactions/final reductions. Each reply is a flat reduction,
    # rather than a competing final amount (see ext's documented contract).
    reductions = ext.run_strict("damage_response_reduction", engine, target, pending,
                                damage_type, source_definition_id, source_actor_id)
    if any(type(part) is not int or not 0 <= part <= pending for part in reductions):
        raise ValueError("damage_response_reduction requires bounded integer reductions")
    return max(0, pending - sum(reductions))


def _consume_resistance_next(engine: Any, target: Any, modifier_ids: list[str]) -> None:
    """Consume a qualifying one-instance Resistance group after defense callbacks."""
    for mid in modifier_ids:
        modifier = target.modifiers.pop(mid, None)
        if modifier is not None:
            engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=target.entity_id,
                                 target_ids=(target.entity_id,), payload={"modifier_id": mid, "reason": "CONSUMED"})


def _expire_marks(engine: Any) -> None:
    """Marks past their marker's printed deadline are removed before any mark is checked (Astra's audit, 2026-09-26)."""
    from .typed_executor import expire_marks

    expire_marks(engine)


def reaction_waived(engine: Any, actor: Any, row: dict[str, Any], *, commit: bool = False) -> bool:
    """Pure preview or one committed use of the first applicable Reaction grant."""
    from . import ext
    for reply in ext.iter_strict("reaction_spend", engine, actor, row, commit):
        if reply != "free" or not isinstance(reply, str):
            raise ValueError("reaction_spend must return None or 'free'")
        return True
    return False


def spend_reaction(engine: Any, actor: Any, row: dict[str, Any]) -> None:
    """Commit an accepted reaction once; its caller records the reaction receipt.

    Native OAs and rider-owned reactions use this after consent, before effects.
    Typed windows reserve before nested reactions; their caller consumes the
    same transaction-bound receipt instead of charging a waiver twice.
    """
    from .paid_relocation import preserve_pending
    preserve_pending(engine, "_typed_reaction_waived")
    if row.get("free"):
        return
    key = (actor.entity_id, str(row.get("feature_id") or ""))
    decided = engine.__dict__.setdefault("_typed_reaction_waived", {}).pop(key, None)
    if decided is not None and decided[0] == getattr(engine, "_transaction_id", None):
        if not decided[1]:
            actor.reaction_available = False
        return
    from . import ext
    if ext.any_false("row_allowed", engine, actor, row):
        raise ValueError("This reaction is not available")
    from .typed_executor import condition_rules
    if not actor.active or any(rule.get("no_reactions") for rule in condition_rules(actor)):
        raise ValueError("This creature cannot take Reactions")
    if row.get("free") or reaction_waived(engine, actor, row, commit=True):
        return
    if not actor.reaction_available:
        raise ValueError("This creature has already used its Reaction")
    actor.reaction_available = False


def can_react(engine: Any, actor: Any, row: dict[str, Any] | None = None, *, uses_reaction: bool = True) -> bool:
    """Whether ``actor`` may take a Reaction now (public name for plug-ins; see ``_can_react``)."""
    return _can_react(engine, actor, row, uses_reaction=uses_reaction)


def _can_react(engine: Any, actor: Any, row: dict[str, Any] | None = None, *, uses_reaction: bool = True) -> bool:
    from .typed_executor import condition_rules
    from . import ext

    if row is not None and ext.any_false("row_allowed", engine, actor, row):
        return False

    return actor.active and not any(rule.get("no_reactions" if uses_reaction else "no_actions") for rule in condition_rules(actor)) \
        and (not uses_reaction or actor.reaction_available or (row is not None and reaction_waived(engine, actor, row)))


def can_use_reaction(engine: Any, actor: Any, other: Any | None, row: dict[str, Any]) -> bool:
    """Shared admission for explicit reaction consumers such as Featherfall.

    Honors ordinary economy, disabling conditions, source/subject prohibitions,
    speech requirements and the saved reaction plan. Does not ask or spend.
    """
    return not row.get("held_back") and _can_react(engine, actor, row) and _subject_ok(engine, actor, other, row)


def open_reaction(engine: Any, row: dict[str, Any], actor: Any, target_ids: tuple[str, ...], checkpoint: str,
                  *, reaction_notice: dict[str, Any] | None = None) -> None:
    """Spend/record an admitted reaction and deliver native reaction-use riders.

    Explicit consumers (Featherfall) ask and pay their own source-defined costs
    before calling this; the outer action transaction owns pause/rollback.
    ``reaction_notice`` optionally supplies the resolved effect/source metadata
    to reaction listeners while ``row`` continues to govern admission/payment.
    """
    _open(engine, row, actor, target_ids, checkpoint, reaction_notice=reaction_notice)


def _uses_reaction(row: dict[str, Any]) -> bool:
    """Whether the row spends the Reaction (combat/factory_compiler.py _spends_reaction): not a free trigger, nor a
    once-per-round save rescue that is no Reaction."""
    if row.get("block") == "save_rescue":
        return bool(row.get("reaction", True))
    return not row.get("free")


MAX_REACTION_USED_DEPTH = 16


def reaction_penalty(engine: Any, actor_id: str, feature_id: str) -> dict[str, Any] | None:
    """Penalty for one accepted reaction, never another nesting level's roll.

    Transient resolution frames are replaced on the next use of that reaction;
    they are not fight state and need no saved-fight schema change.
    """
    frame = (getattr(engine, "_typed_reaction_frames", None) or {}).get((actor_id, feature_id))
    return frame.get("penalty") if frame else None


def publish_reaction_used(engine: Any, actor: Any, row: dict[str, Any]) -> None:
    """Notify answers to an already accepted/paid Reaction (including Factory OA).

    Each dispatch has its own answered-reaction and penalty frame. Restore the
    parent even on a transactional Ask-me pause. Spending before dispatch bounds
    ordinary chains; the explicit depth limit also bounds reaction refunds.
    Free triggers do not call this seam.
    """
    from .paid_relocation import preserve_pending
    preserve_pending(engine, "_typed_reaction_frames")
    depth = getattr(engine, "_typed_reaction_used_depth", 0)
    previous = getattr(engine, "_typed_answered_reaction", None)
    frame = {"actor_id": actor.entity_id, "row": row, "penalty": None}
    frames = getattr(engine, "_typed_reaction_frames", None)
    if frames is None:
        frames = engine._typed_reaction_frames = {}
    frames[(actor.entity_id, row["feature_id"])] = frame
    if depth >= MAX_REACTION_USED_DEPTH:
        return
    engine._typed_reaction_used_depth = depth + 1
    engine._typed_answered_reaction = frame
    try:
        from .reaction_trigger import trigger_scope
        with trigger_scope(engine, 'REACTION_USED', actor_id=actor.entity_id,
                           target_id=next(iter(row.get('target_ids') or ()), actor.entity_id),
                           source_id=row['feature_id'], roll_kind='reaction', action_name=row.get('name')):
            on_creature_event(engine, actor, 'reaction_used')
    finally:
        frames[(actor.entity_id, row['feature_id'])] = frame
        engine._typed_reaction_used_depth = depth
        engine._typed_answered_reaction = previous


def _open(engine: Any, row: dict[str, Any], actor: Any, target_ids: tuple[str, ...], checkpoint: str,
          extra: dict[str, Any] | None = None, *, reaction_notice: dict[str, Any] | None = None) -> None:
    from . import ext
    if ext.any_false("row_allowed", engine, actor, row):
        raise ValueError("This reaction is not available")
    from .paid_relocation import preserve_pending
    preserve_pending(engine, "_typed_reaction_waived")
    uses = _uses_reaction(row)
    if uses:
        # Spent before anything else can answer this one (fight audit 2026-09-29: "a creature uses a reaction" below let
        # Charged Countermeasure force Jia's Constitution save, and Nascent Soul answered it with the Reaction she was
        # already using -- two Reactions between her turns, three rounds running). Callers still clear it themselves
        # (spend_reaction). A waived use (reaction_waived, rider lane C15) keeps the Reaction; the callers see the same answer.
        waived = bool(row.get("feature_id")) and reaction_waived(engine, actor, row, commit=True)
        engine.__dict__.setdefault("_typed_reaction_waived", {})[(actor.entity_id, str(row.get("feature_id") or ""))] = \
            (getattr(engine, "_transaction_id", None), waived)
        if not waived:
            actor.reaction_available = False
    engine._append_event("REACTION_WINDOW_OPENED", row["feature_id"], actor_id=actor.entity_id, target_ids=target_ids,
                         payload={"checkpoint": checkpoint, **(extra or {})})
    if uses:
        publish_reaction_used(engine, actor, {**(reaction_notice or row), "target_ids": target_ids})


# ---------------------------------------------------------------- generic reactions (owner 2026-09-25)
# A generic row ("block": "generic", combat/factory_compiler.py) is an owned reaction that has a
# supported trigger kind (combat/reaction_triggers.py) but no hand-written block above. One best
# candidate fires per checkpoint per actor; reaction_available already caps it to one per round.
def _generic_rows(engine: Any, actor_id: str, kind: str) -> list[dict[str, Any]]:
    # A "you or an ally" row (includes_self) answers the reactor's own event too, not only an ally's.
    return [row for row in _rows(engine, actor_id, "generic")
            if row.get("kind") == kind or (row.get("includes_self") and row.get("kind") == f"ally_{kind}")]


def _holds(engine: Any, actor: Any, resource_id: str, amount: int = 1, *, context: dict[str, Any] | None = None) -> bool:
    """Whether ``actor`` holds ``amount`` of ``resource_id`` that may be paid right now.

    The plain engine count, minus whatever the general ``cost_available`` seam refuses
    (combat/ext/__init__.py). A subscriber there may hold a pool back for any printed reason it can
    answer from the event window it is being asked about, so this path never names one ability: the
    Foundation rule that a Pulse generated by an event cannot pay for that same event is registered
    by combat/ext/prior_event_resources.py, and is inert for every other pool, for any fighter
    without that rule's row, and for any fight saved before it existed.
    """
    if actor.resources.get(resource_id, 0) < amount:
        return False
    from . import ext

    if not ext.has("cost_available"):
        return True
    return all(bool(answer) for answer in ext.run("cost_available", engine, actor, resource_id, amount, context or {}))


def _generic_affordable(engine, actor: Any, row: dict[str, Any]) -> bool:
    return all(_holds(engine, actor, cost_dict(cost)["resource_id"], cost_dict(cost)["amount"]) for cost in row.get("costs") or [])


def _generic_in_range(engine: Any, reactor: Any, other: Any | None, row: dict[str, Any], *,
                      subject: Any | None = None, source: Any | None = None) -> bool:
    """Check reach to the row's source/subject, distinct from effect recipients.

    Event hooks with two creatures supply both roles. Printed-Range rows
    select their compiled reference; sealed null-range rows infer the same
    contract without mutation. Explicit-trigger rows retain ``other``.
    Single-creature hooks already pass the triggering subject as ``other``.
    """
    range_ft = row.get("range_ft")
    if row.get("range_scale") == "speed":
        range_ft = engine._effective_speed(reactor)
    reference = row.get("range_reference")
    if range_ft is None:
        # Older saved bundles predate the compiler's Range-header contract.
        # Read their printed reach without rewriting the bundle or its journal.
        from .factory_compiler import _reaction_range_ft, _reaction_range_reference

        range_ft = _reaction_range_ft(str(row.get("feature_id") or ""), {}, None, int((row.get("numbers") or {}).get("cl") or 1))
        reference = _reaction_range_reference(str(row.get("kind") or ""), row.get("requires_mark"), row.get("mark_on"))
    if reference == "source":
        other = source if source is not None else other
    elif reference == "subject":
        other = subject if subject is not None else other
    if range_ft is None or other is None:
        return True
    from .ext.reaction_ranges import reach
    range_ft = reach(engine, reactor, str(row.get("feature_id") or ""), range_ft)
    if engine.grid.distance_ft(reactor.position, other.position) <= range_ft:
        return True
    from . import ext  # a reaction measured from somewhere else too (rider lane 10: Counterpressure from a Pressure Anchor)

    return ext.has("reaction_reach") and any(ext.run("reaction_reach", engine, reactor, other, row))


def _generic_kind_ok(row: dict[str, Any], *, ranged: bool, melee: bool) -> bool:
    if row.get("ranged_only") and not ranged:
        return False
    if row.get("melee_only") and not melee:
        # Parry Anything (auto-lane4 2026-09-29) lets Parry and Riposte answer a ranged attack that hit: the modifier hangs its
        # marker effect on the row (combat/ext/lane4_parry.py).
        return any(effect.get("type") == "lane4_parry_ranged" for effect in row.get("effects") or ())
    return True


def _once_key(row: dict[str, Any]) -> str | None:
    """A printed "once per turn"/"once per round" on a generic row (owner 2026-09-26: a free resource
    generator has no Reaction to cap it)."""
    once, group = row.get("once"), row.get("once_group") or row["feature_id"]
    return f"typed_once_turn:{group}" if once == "turn" else f"once_per_round:typed.{group}" if once == "round" else None


def _once_used(engine: Any, actor: Any, row: dict[str, Any]) -> bool:
    key = _once_key(row)
    if key is None:
        return False
    value = actor.turn_flags.get(key)
    return value == engine.state.round_number if row.get("once") == "round" else bool(value)


def _spend_generic(engine: Any, actor: Any, row: dict[str, Any]) -> bool:
    # _open has reserved this use before payment can open nested checkpoints.
    key = _once_key(row)
    if key is not None:
        actor.turn_flags[key] = engine.state.round_number if row.get("once") == "round" else True
    costs = [cost_dict(raw) for raw in row.get("costs") or []]
    from . import ext
    for replacement in ext.run("generic_reaction_payment", engine, actor, row, costs):
        if replacement is not None:
            costs = replacement
    for raw_cost in costs:
        cost = cost_dict(raw_cost)
        if cost.get("amount"):
            engine._spend_resource(actor, cost["resource_id"], cost["amount"], row["feature_id"])
    if any(cost_dict(cost).get("amount") for cost in row.get("costs") or []):
        from .activation_payments import reaction_completed
        return reaction_completed(engine, actor, row["feature_id"], consumes_reaction=not row.get("free"))
    return True


def triggered_context(engine: Any, reactor: Any, other: Any | None, row: dict[str, Any], intent: Any = None) -> Any:
    """Public context for independent triggered effects and ordinary generic reactions.

    Uses the owner's weapon/numbers and normal typed attack/rider delivery without
    spending any economy. Attached weapons retain weapon_source_id for shared
    grip, family and deferred-bonus queries. Contexts without an attached weapon
    keep their existing metadata.
    Callers check eligibility, consent and limits themselves;
    ``run_effects`` must propagate transactional pauses/errors to the preview caller.
    """
    return _generic_context(engine, reactor, other, row, intent)


@contextmanager
def _reaction_activation(engine, reactor, other, row, *, range_subject=None, same_activation=False):
    """Intercept the complete accepted reaction before its caller pays or applies it."""
    from .technique_interception import activation, frame
    from .gate2_runtime_models import CandidateKind
    intent = getattr(engine, '_active_intent', None)
    context = _generic_context(engine, reactor, other, row, intent)
    candidate = engine._candidate(CandidateKind.REACTION, reactor, row['feature_id'],
        context.action.display_name, target_ids=(other.entity_id,) if other is not None else ())
    with activation(engine, reactor, context.action, candidate, intent, caller_pays=True,
                    relocation_continuation=same_activation) as (declared, _, canceled):
        current = frame(engine, reactor.entity_id, row['feature_id'])
        if (not canceled or current.get('spend_activation')) and (
                not _can_trigger(engine, reactor, row) or not _generic_affordable(engine, reactor, row)):
            engine._append_event('PASSIVE_TRIGGERED', row['feature_id'], actor_id=reactor.entity_id,
                payload={'log': f'{declared.display_name} cannot continue: its Reaction or required resources are no longer available.'})
            yield False
            return
        distant = (not canceled and current.get('range_delta_ft') and
                   not _generic_in_range(engine, reactor, range_subject or other, {**row, 'range_ft': declared.range_ft}))
        if distant or (canceled and current.get('spend_activation')):
            if not row.get('free'):
                spend_reaction(engine, reactor, row)
            _spend_generic(engine, reactor, row)
        if distant:
            engine._append_event('PASSIVE_TRIGGERED', row['feature_id'], actor_id=reactor.entity_id,
                payload={'log': f'{declared.display_name} cannot reach its chosen target after its range was reduced. Its activation cost is spent.'})
        yield not canceled and not distant


def _reaction_strike(engine, reactor, effects):
    """Pure selected strike profile, shared by generic eligibility and execution."""
    strike = next((effect.get("strike_with") for effect in effects if isinstance(effect, dict) and effect.get("strike_with")), None)
    if strike is None:
        # A reaction that "makes one melee weapon attack / an Unarmed Strike" with no damage of its own (Cross Counter,
        # Bloody Counter and 36 others, owner 2026-09-29) rolled a bare 1d4: it strikes with the reactor's own weapon too.
        bare = next((effect for effect in effects if isinstance(effect, dict) and effect.get("type") == "attack"
                     and not str(effect.get("attack_kind") or "").startswith("cultivation")
                     and not any(isinstance(hit, dict) and hit.get("type") == "damage" for hit in effect.get("on_hit") or [])), None)
        if bare is not None:
            strike = "unarmed" if bare.get("attack_kind") == "unarmed" else "weapon"
    if strike:
        # A reaction that makes an Unarmed Strike or a weapon attack (Counter Palm, owner 2026-09-28) uses the reactor's own.
        from .ext.weapon_hits import triggered_melee_weapon
        return triggered_melee_weapon(engine, reactor, unarmed=strike == 'unarmed')
    return None


def generic_reaction_context(engine: Any, reactor: Any, other: Any | None, row: dict[str, Any], intent: Any = None) -> Any:
    """Public name for plug-ins that need a reaction Context for a given row.

    Delegates to the same builder the engine uses; querying it never spends a Reaction.
    """
    return _generic_context(engine, reactor, other, row, intent)


def _generic_context(engine: Any, reactor: Any, other: Any | None, row: dict[str, Any], intent: Any = None) -> Any:
    """A reaction Context carrying its selected strike's actual reach/profile.

    Querying this context never spends a Reaction. Reach providers see the same
    attack profile during eligibility, declaration and execution, with ordinary
    reaction attacks distinct from opportunity attacks.
    """
    from .gate2_runtime_models import ActionDefinition, EconomyKind
    from .typed_executor import Context

    effects = row.get('effects') or []
    pick = _reaction_strike(engine, reactor, effects)
    ranged = any('ranged' in str(e.get('attack_kind') or '') for e in effects if isinstance(e, dict))
    reach = ((pick.reach_ft or pick.range_ft) if pick is not None else (_opportunity_row(engine, reactor) or {}).get('reach_ft')) or 5
    range_ft = int(row.get('range_ft') or 60) if ranged else None
    typed = {'effects': effects, 'numbers': row.get('numbers') or {}, 'weapon': None,
             'source': row['feature_id'],
             'duration': {'kind': 'instant'}, 'riders': [], 'reaction_attack': True,
             'reaction_range_ft': row.get('range_ft')}
    if range_ft is not None:
        typed['range_ft'] = range_ft
    if pick is not None:
        typed = {**typed, 'weapon': pick.parameters['typed']['weapon'],
                 'weapon_source_id': pick.source_definition_id,
                 'numbers': {**typed['numbers'], 'attack_bonus': int(pick.parameters['typed']['numbers'].get('attack_bonus') or 0)}}
    action = ActionDefinition(source_definition_id=row['feature_id'], display_name=row.get('name') or row['feature_id'],
        owner_id=reactor.entity_id, economy=EconomyKind.REACTION, resolution_kind='TYPED', target_kind='HOSTILE_ENTITY',
        reach_ft=int(reach), range_ft=range_ft,
        parameters=pick.parameters if pick is not None else {'typed': typed})
    targets = [other] if other is not None else []
    if row.get("requires_hearing"):
        from .speech import can_hear_from
        targets = [creature for creature in targets if can_hear_from(engine, reactor, creature, row["feature_id"])]
    if row.get('immortal_from'):
        typed['immortal_from'] = row['immortal_from']
    action = action.model_copy(update={'range_ft': row.get('range_ft'),
        'costs': tuple((c['resource_id'], c['amount']) for raw in row.get('costs') or [] if (c := cost_dict(raw))),
        'parameters': {'typed': typed}})
    attack = next((e for e in typed["effects"] if e.get("type") == "attack"), None)
    if attack is not None and attack.get("reach_ft") is not None and "ranged" not in str(attack.get("attack_kind") or ""):
        action = action.model_copy(update={"reach_ft": int(attack["reach_ft"])})
    return Context(engine, reactor, action, intent, typed, targets, other)


def _run_generic_effects(engine: Any, reactor: Any, other: Any | None, row: dict[str, Any], effects: list[dict[str, Any]], intent: Any = None,
                         protects: Any = None, recipient: Any = None, attack_spec: dict | None = None) -> None:
    """A bad generic row must never end a fight: fall back to a GM rider (owner 2026-09-25). ``protects``: the ally a
    bystander's reaction shields, which its "ally" effects land on (owner playtest 2026-09-29: Bulwark's Resistance went
    to the reactor). ``recipient`` is the protected self/ally for defensive target effects;
    ``other`` remains the triggering source, available to explicit ``attacker`` effects.
    Omitted recipient preserves the existing offensive reaction contract."""
    from .typed_executor import run_effects

    try:
        context = _generic_context(engine, reactor, other, row, intent)
        from .technique_interception import frame
        declared = frame(engine, reactor.entity_id, row['feature_id']).get('action')
        if declared is not None:
            context.action = declared
            context.typed = copy.deepcopy(declared.parameters['typed'])
        if recipient is not None:
            context.typed["triggering_source_id"] = getattr(other, "entity_id", None)
            context.typed["protects"] = recipient.entity_id
            context.target = recipient
            context.targets = [recipient]
        if protects is not None:
            context.typed["protects"] = protects.entity_id
        if attack_spec is not None:
            context.typed["triggering_attack_spec"] = attack_spec
        run_effects(context, effects)
    except Exception as exc:
        _log_bad_row(engine, reactor, other, row, exc)
    if row.get("kind") != "own_ability" and row.get("name"):
        # R3: "after your Counterstrike hits" -- a follow-up that rides the named ability (no Reaction of its own)
        on_own_event(engine, reactor, other, "own_ability", accept=lambda follow: str(follow.get("source_name") or "").lower() == str(row["name"]).lower())


def _log_bad_row(engine: Any, reactor: Any, other: Any | None, row: dict[str, Any], exc: Exception) -> None:
    from .ext import ControllerPause, CheckpointError
    from .technique_interception import InterceptionError

    if isinstance(exc, (ControllerPause, CheckpointError, InterceptionError)):
        # Not a bad row: an Ask-me reaction (this row's own _consent, or one nested in its effects) is waiting for the
        # player. Swallowing it here made the policy controller answer for them (owner playtest 2026-09-29).
        raise exc
    other_id = getattr(other, "entity_id", None)
    engine._append_event("GM_RIDER", row.get("feature_id") or "unknown", actor_id=reactor.entity_id,
                         target_ids=(other_id,) if other_id is not None else (),
                         payload={"rider": f"{row.get('name') or row.get('feature_id')} could not run: {exc}"})


def _ally_candidates(engine: Any, subject: Any) -> list[Any]:
    """Every other active Factory fighter: _ally_row_ok decides per row whether it answers (an ally of ``subject``, or
    anyone for a reading that names "a creature other than you")."""
    return [other for other in engine.state.actors.values()
            if other.active and other.entity_id != subject.entity_id and other.entity_id in getattr(engine, "typed_actor_ids", set())]


def _opportunity_ok(engine: Any, source: Any | None, row: dict[str, Any]) -> bool:
    """"A creature makes an Opportunity Attack against you" (a reading's ``opportunity_only``): only while that creature's
    opportunity attack resolves (opportunity_attack below marks it)."""
    return not row.get("opportunity_only") or (source is not None and getattr(engine, "_typed_oa_attacker", None) == source.entity_id)


def _within_reach(engine: Any, reactor: Any, other: Any | None, row: dict[str, Any]) -> bool:
    from .attack_reach import maximum
    action = _generic_context(engine, reactor, other, row).action
    return other is not None and engine._distance_actor_to_actor(reactor, other) <= maximum(
        engine, reactor, action, base=action.reach_ft or 5, opportunity=False)


# Effects that still help the reactor or the protected ally when the attack cannot reach (the row is not skipped for them).
_ANSWERS_WITHOUT_ATTACK = {"ac_bonus", "hold_at_1hp", "temp_hp", "movement", "teleport", "reaction_move", "damage_reduction", "healing",
                           "resistance", "attack_modifier"}


def attack_reaches(engine: Any, reactor: Any, other: Any | None, effect: dict[str, Any], range_ft: Any = None, *, action=None) -> bool:
    """A reaction's attack needs its target in reach (melee: the reactor's reach) or in range (ranged: the row's range,
    else 60 feet) -- owner playtest 2026-09-29: Intercepting Thrust and Counter Palm answered attacks from across the map."""
    if other is None:
        return True
    if action is None:
        action = _generic_context(engine, reactor, other, {
            'feature_id': 'system:combat.reaction_reach', 'effects': [effect], 'range_ft': range_ft}).action
    if "ranged" in str(effect.get("attack_kind") or ""):
        limit = int(range_ft or 60)
    else:
        from .attack_reach import maximum
        limit = maximum(engine, reactor, action, base=action.reach_ft or 5, opportunity=False)
    return engine._distance_actor_to_actor(reactor, other) <= limit


def _attack_row_reaches(engine: Any, reactor: Any, other: Any | None, row: dict[str, Any]) -> bool:
    """False for a row whose only answer is an attack that cannot reach ``other``: its Reaction is kept. A row that also
    shields (an AC bonus, a move) still fires; block_attack then skips the attack alone."""
    effects = [e for e in row.get("effects") or [] if isinstance(e, dict)]
    attacks = [e for e in effects if e.get("type") == "attack"]
    if not attacks or any(e.get("type") in _ANSWERS_WITHOUT_ATTACK for e in effects):
        return True
    action = _generic_context(engine, reactor, other, row).action
    return any(attack_reaches(engine, reactor, other, e, row.get("range_ft"), action=action) for e in attacks)


def _ally_row_ok(engine: Any, reactor: Any, source: Any | None, subject: Any, row: dict[str, Any]) -> bool:
    """A bystander's ally_hit/ally_attacked/ally_missed/ally_damaged row (owner 2026-09-26 readings): the harmed creature is
    its ally (or anyone, ``any_subject``). Its own damage is excluded unless the trigger explicitly admits it
    (``allow_self_source``, default False); a required mark is on the triggering creature, or on the
    harmed one (``mark_on`` "subject"); the damaging creature within its reach if the reading says so; and its Reaction
    not kept for a marked creature (step 15). The ally hooks did not check a required mark before these readings."""
    from . import ext

    if not row.get("any_subject") and reactor.team_id != subject.team_id:
        return False
    if ext.has("reaction_ally_allowed") and ext.any_false("reaction_ally_allowed", engine, reactor, subject, row):
        return False
    if not _opportunity_ok(engine, source, row):
        return False
    if source is not None and source.entity_id == reactor.entity_id and not row.get("allow_self_source"):
        return False
    if ext.any_false("reaction_geometry_allowed", engine, reactor, source, subject, row):
        return False
    if not _generic_mark_ok(reactor, subject if row.get("mark_on") == "subject" else source, row):
        return False
    if row.get("source_within_reach") and not _within_reach(engine, reactor, source, row):
        return False
    if not _attack_row_reaches(engine, reactor, source, row):
        return False  # its counterattack cannot reach the attacker
    from . import ext

    if ext.has("ally_row_allowed") and ext.any_false("ally_row_allowed", engine, reactor, subject, row):
        return False  # a plug-in's own condition for the row (combat/ext/__init__.py)
    return not _held_for_mark(engine, reactor, source, row)


def _ordered_generic_rows(engine: Any, actor_id: str, kind: str, other: Any = None) -> list[dict[str, Any]]:
    """Paid reactions before free triggers (owner 2026-09-26): a Foundation's free resource-generation
    row (``free``, combat/factory_compiler.py) should not pre-empt a costed reaction's chance to fire
    on the same event; ``sorted`` is stable, so each group keeps its original order."""
    # A row that "after the triggering event resolves" places a mark (Yang's Force the Rising, after: "event") goes last of all: the mark
    # it applies cannot be spent by another response to the same event.
    rows = sorted(_generic_rows(engine, actor_id, kind), key=lambda row: (row.get("after") == "event", bool(row.get("free"))))
    from . import ext

    # A fresh row carries one price through eligibility, consent and payment.
    # Never change the compiled row: the next trigger may have a different price.
    if ext.has("generic_reaction_costs"):
        reactor = engine.state.actors[actor_id]
        prepared = []
        for row in rows:
            costs = [cost_dict(cost) for cost in row.get("costs") or []]
            changed = False
            for replacement in ext.run("generic_reaction_costs", engine, reactor, other, row, costs):
                if replacement is not None:
                    costs = replacement
                    changed = True
            prepared.append({**row, "costs": costs} if changed else row)
        return prepared
    return rows


def _generic_resource_ok(actor: Any, row: dict[str, Any]) -> bool:
    """A "while you have X"/"already have X" limit (owner 2026-09-26, "make sure the mechanics aren't
    damaged"): ``requires_resource`` is already the real resource id for this character
    (combat/factory_compiler.py resolved it at compile time; an unresolvable name kept the row from
    compiling at all), so firing just needs the reactor to hold at least 1 of it right now."""
    resource_id = row.get("requires_resource")
    return not resource_id or actor.resources.get(resource_id, 0) >= 1


def _generic_damage_type_ok(engine: Any, row: dict[str, Any]) -> bool:
    """A "take Fire damage" limit (owner 2026-09-26): the incoming damage type is stashed on the engine
    by non-sealed code just before the sealed engine commits damage (typed_executor._deal, block_attack
    -- the sealed _commit_damage does not pass it to on_damage). An unknown type (damage committed by
    engine-internal code that never went through typed_executor) never satisfies a type-limited row,
    rather than risk firing when the trigger's named type does not actually match."""
    types = row.get("damage_types")
    if not types:
        return True
    current = getattr(engine, "_typed_pending_damage_type", None)
    return current is not None and str(current).upper() in types


def _generic_save_ability_ok(row: dict[str, Any], ability: str) -> bool:
    """A "fail an Intelligence, Wisdom, or Charisma saving throw" limit (owner 2026-09-26)."""
    abilities = row.get("save_abilities")
    return not abilities or str(ability).upper() in abilities


def _generic_condition_ok(row: dict[str, Any], condition_name: str) -> bool:
    """A "gain Grappled, Prone, or Restrained" limit (owner 2026-09-26)."""
    conditions = row.get("conditions")
    return not conditions or str(condition_name).lower() in conditions


def _generic_mark_ok(reactor: Any, other: Any | None, row: dict[str, Any]) -> bool:
    """A "bearing your <Mark>"/"a marked creature" subject (owner 2026-09-26, combat/reaction_triggers.py's
    requires_mark): the triggering creature (the attacker for attacked/hit/missed, the technique's user
    for technique_used) must carry a mark this reactor placed (combat/typed_executor.py's block_mark)."""
    from .typed_executor import bears_mark

    mark = row.get("requires_mark")
    return not mark or (other is not None and bears_mark(other, reactor.entity_id, mark))


def _asking(engine: Any, reactor: Any, row: dict[str, Any]) -> bool:
    """Owner 2026-09-26 (step 16): "a mode where we have manual reactions, when a reaction can happen it stops and
    hands priority over to the player". A reaction of a character set to Ask me (combat/factory_compiler.py
    _reaction_plan marks its rows "ask") while a player controls it in this fight (the service sets
    ``typed_ask_reactors``); an AI-controlled Ask me character reacts as Auto."""
    return bool(row.get("ask")) and (not row.get("free") or row.get("optional")) and reactor.entity_id in (getattr(engine, "typed_ask_reactors", None) or ())


def ask_key(checkpoint: str, engine: Any) -> str:
    """The reaction moment's decision key: the trigger and the event it comes after, so a second attack in one action
    is its own question, and a re-run of the same action from the same state asks the same one."""
    return f"TYPED:{checkpoint}@{engine.state.event_sequence}"


def _consent(engine: Any, row: dict[str, Any], reactor: Any, checkpoint: str, *, trigger: dict[str, Any] | None = None) -> bool:
    """True unless the player is asked (step 16) and passes. The answer comes the way the engine's own reactions get
    theirs (combat/gate4_engine.py _reaction_decision): one carried by the action, else the service's provider,
    which pauses the fight for the player (combat/gate5_service.py). With neither, the reaction is not used."""
    # Display-only provenance for all reaction families; no answer keys, events or rules change.
    # The scope unwinds even when the service pauses a preview for Ask me.
    if trigger is not None:
        from .reaction_trigger import trigger_scope

        with trigger_scope(engine, checkpoint, **trigger):
            return _consent(engine, row, reactor, checkpoint)
    mode_decision = None
    if row.get("consent_source_id") and _asking(engine, reactor, row):
        intent = getattr(engine, "_active_intent", None)
        if intent is None:
            return False
        # Pick the mode before any ability-owned secondary choice (a ward,
        # alternative price, survival cost, etc.). Declined modes do not open
        # those choices; selected modes still use their normal consent hook.
        mode_decision = engine._reaction_decision(intent, ask_key(checkpoint, engine),
            reactor.entity_id, row["consent_source_id"])
        if mode_decision is None or mode_decision.selection != "USE":
            return False
    if any(isinstance(effect, dict) and effect.get("type") == "hold_at_1hp" for effect in row.get("effects") or []):
        from .ext.life_state import survival_consent

        return survival_consent(engine, row, reactor, checkpoint)
    if not _asking(engine, reactor, row):
        return True
    from . import ext
    answers = ext.run_strict('reaction_consent', engine, row, reactor, checkpoint)
    if answers:
        if len(answers) != 1 or type(answers[0]) is not bool:
            raise ValueError('reaction_consent requires one owning boolean reply')
        return answers[0]
    if mode_decision is not None:
        return True
    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return False
    decision = engine._reaction_decision(intent, ask_key(checkpoint, engine), reactor.entity_id,
        row.get("consent_source_id") or f"reaction:typed.{row['feature_id']}")
    return decision is not None and decision.selection == "USE"


def _held_for_mark(engine: Any, reactor: Any, other: Any | None, row: dict[str, Any]) -> bool:
    """Owner 2026-09-26 (step 15): "the reactions that come from a specific person or creature ignore attacks from
    others so the reaction is spent on that creature". While a creature bearing the mark one of this reactor's
    reactions answers (Turn the Blade Aside's Beauty Mark) is still standing, and that reaction could still be
    paid for, the reactor's other Reaction-spending responses -- opportunity attacks and soaks included -- let a
    trigger from anyone else pass. Free triggers and mark-bound reactions themselves are never held; in My order
    only a mark-bound reaction ranked above this one holds it."""
    from .typed_executor import bears_mark

    if row.get("free") or row.get("requires_mark") or other is None or _asking(engine, reactor, row):
        return False  # an unknown source (a hazard) is not "someone else"; a player asked decides for themself
    other_id = other.entity_id
    for keeper in _rows(engine, reactor.entity_id, "generic"):
        mark = keeper.get("requires_mark")
        if not mark or keeper is row or keeper.get("free"):
            continue
        if "priority" in row and keeper.get("priority", 10**6) >= row["priority"]:
            continue
        if not _generic_affordable(engine, reactor, keeper) or _once_used(engine, reactor, keeper) or not _generic_resource_ok(reactor, keeper):
            continue
        bearers = {actor.entity_id for actor in engine.state.actors.values()
                   if actor.active and actor.entity_id != reactor.entity_id and bears_mark(actor, reactor.entity_id, mark)}
        if bearers and other_id not in bearers:
            return True
    return False


def _source_actor(engine: Any, source_definition_id: str | None) -> Any | None:
    """The creature whose ability this is (its catalog owner), when one is in the fight."""
    action = (getattr(engine, "action_catalog", {}) or {}).get(source_definition_id or "")
    return engine.state.actors.get(getattr(action, "owner_id", None) or "") if action is not None else None


def reaction_permitted_against(engine: Any, reactor: Any, other: Any | None) -> bool:
    """Shared target-specific vetoes for a reaction answering a creature.

    Used for both the trigger subject and explicitly selected reaction targets;
    row-specific trigger predicates remain in ``_subject_ok``.
    """
    from . import unmaking

    if unmaking.reactions_denied_against(reactor, other):
        return False  # "cannot take Reactions against you" (Sting, Saint-Body Rebuke)
    from . import ext

    return not ext.any_false("reaction_allowed", engine, reactor, other)


def _subject_ok(engine: Any, reactor: Any, other: Any | None, row: dict[str, Any]) -> bool:
    if not reaction_permitted_against(engine, reactor, other):
        return False
    from . import ext

    if ext.has("reaction_subject_allowed") and ext.any_false("reaction_subject_allowed", engine, reactor, other, row):
        return False  # this row answers only some creatures (Charged Countermeasure: one that is Charged or Conductive)
    from . import speech

    if speech.silenced(reactor) and speech.row_needs_voice(row):
        return False  # a Reaction that needs its voice (owner 2026-09-29: Silenced, combat/speech.py)
    return _subject_ok_rest(engine, reactor, other, row)


def _subject_ok_rest(engine: Any, reactor: Any, other: Any | None, row: dict[str, Any]) -> bool:
    """The triggering creature may be answered: it bears the mark the row requires, a reaction attack can reach it, and
    the Reaction is not being held for a marked creature (step 15)."""
    # A "you or an ally" row answering the reactor's own event: a mark "on the harmed creature" is on the reactor.
    from . import ext

    if ext.any_false("reaction_geometry_allowed", engine, reactor, other, reactor, row):
        return False
    holder = reactor if row.get("mark_on") == "subject" and str(row.get("kind") or "").startswith("ally_") else other
    if row.get("source_within_reach") and not _within_reach(engine, reactor, other, row):
        return False
    if not _opportunity_ok(engine, other, row):
        return False
    # A selectable attack's reach is checked against its legal recipient list,
    # not against the creature responsible for the triggering condition.
    if row.get("reaction_target") != "creature_in_reach" and not _attack_row_reaches(engine, reactor, other, row):
        return False
    return _generic_mark_ok(reactor, holder, row) and not _held_for_mark(engine, reactor, other, row)


def _can_trigger(engine: Any, actor: Any, row: dict[str, Any]) -> bool:
    """A free (no_action) row only needs the actor conscious and not silenced by a no_reactions
    condition; a costed reaction also needs its Reaction unspent this round (owner 2026-09-26). Also
    where a held-resource limit is checked (owner 2026-09-26): every generic hook below calls this."""
    from .typed_executor import condition_rules

    if not actor.active or any(rule.get("no_reactions") for rule in condition_rules(actor)):
        return False
    if row.get("reactor_hears") and any(rule.get("cant_hear") for rule in condition_rules(actor)):
        return False  # "a creature you can hear ...": a Deafened reactor never hears it (2024)
    from .pending_damage import answer
    if not answer(engine, row)[0]:
        return False
    if not _generic_resource_ok(actor, row) or _once_used(engine, actor, row):
        return False
    if row.get("requires_condition") and not any(c.condition_id == row["requires_condition"] for c in actor.conditions.values()):
        return False  # e.g. Deathless Guard: only while the servant is Guarding (combat/summons.py)
    from . import ext

    if ext.has("row_allowed") and ext.any_false("row_allowed", engine, actor, row):
        return False  # e.g. a Spear talent with no approved Spear weapon (combat/ext/weapon_required.py)
    return bool(row.get("free")) or actor.reaction_available or reaction_waived(engine, actor, row)


def _generic_amount(engine: Any, actor: Any, row: dict[str, Any], effect: dict[str, Any], *, raw_terms: list | None = None) -> int:
    """Flat/dice/formula amount for a generic effect (owner 2026-09-26): the same small vocabulary as
    combat/typed_executor.py's Context.dice/formula (pb, cl, half_pb, key_ability_modifier), read from
    the row's own numbers so this can run outside a Context (e.g. before the attack roll is made)."""
    from .gate2_runtime_models import DiceSpec

    numbers = row.get("numbers") or {}
    from . import ext
    for amount in ext.run("reaction_amount", engine, actor, row, effect):
        if amount is not None:
            if raw_terms is not None:
                raw_terms.append(int(amount))
            return max(0, int(amount))
    # The roll-free part (pb/cl/half_pb/key_ability_modifier/attack_ability_modifier, an expression of
    # those such as "2*pb+con" -- the modifiers ride on the row, combat/factory_compiler.py -- plus the
    # row's flat) is one shared table, typed_amounts.static_bonus, so a gate that must classify a row
    # *before* anything is rolled reads the engine's own vocabulary instead of re-guessing it.
    bonus = static_bonus(effect, numbers, ability_mods=row.get("ability_mods"), weapon=row.get("weapon"))
    from factory_authoring.typed_mechanics import dice_for_cl

    # CL-scaled dice (Yin's Diminish Force: 1d6 ... 4d6 by CL), owner 2026-09-26.
    dice = dice_for_cl(effect.get("dice_by_cl"), numbers.get("cl")) or effect.get("dice")
    dice = dice if isinstance(dice, dict) else {}
    count, sides = int(dice.get("count") or 0), int(dice.get("sides") or 0)
    if count > 0 and sides > 1:
        from .effect_rolls import roll_amount
        roll = roll_amount(engine, actor, DiceSpec(count=count, sides=sides, modifier=bonus),
                           row["feature_id"], f"GENERIC_AMOUNT:{row['feature_id']}")
        engine._record_roll(roll)
        if raw_terms is not None:
            raw_terms.append(int(roll.total))
        return roll.total
    if raw_terms is not None:
        raw_terms.append(int(bonus))
    return max(0, bonus)


def _ac_amount(engine: Any, actor: Any, row: dict[str, Any], effect: dict[str, Any]) -> int:
    """An ac_bonus effect's amount: the parser's fixed "amount", else flat/dice/formula ("+ your Proficiency
    Bonus" -- owner 2026-09-26 manual-control check: a PB AC bonus counted as 0)."""
    return int(effect["amount"]) if effect.get("amount") else _generic_amount(engine, actor, row, effect)


# A natural 20 always hits (owner 2026-10-02 MMX53, 2024 D&D rules): nothing may turn THAT attack
# into a miss, so a reaction is pointless on a critical when every one of its typed effects only
# changes the hit/miss comparison. Two effect types do exactly that and nothing else: an ``ac_bonus``
# on the reactor, and an ``attack_modifier`` penalty against the attacker (a one-off correction to the
# roll that already happened -- the same correction on the other side of the ledger). Everything else
# a reaction can carry -- a ``damage_modifier`` reduction, a condition, a mark, a retaliation, a
# resource, a movement -- still does its work on a critical hit and is offered normally.
#
# This is read off each row's own typed effects, never off a name or an ability id, so a new reaction
# is classified correctly the moment it is typed, and an ability whose printed rule changes needs no
# code change here. Among the shipped authority this is what separates the two rows that genuinely
# change behaviour on a critical (Qi Armor and Brigandine Robe Scripture, whose sole effect is the AC
# bonus) from everything else -- including Parry and Riposte, a pure damage_modifier.
_CRITICAL_ONLY_HIT_MISS_TYPES = ("ac_bonus",)


def _miss_dependent(effect: Any) -> bool:
    """Whether ``effect`` only happens if the attack it rides on misses.

    ``only_if_miss`` is the typed flag for a rider printed as a consequence of the miss: "If this
    causes the attack to miss, you may move 5 feet without provoking Opportunity Attacks" (Cauldron
    Guard, Weapon Guard, High Branch Guard). It is a general per-effect flag in the same shape as
    ``only_if_zero`` (Iron Forearm Guard: "if this reduces the damage to 0"), so any ability whose
    printed rider depends on the miss carries it in its own typed data and needs no code change here.

    It matters on a critical: a natural 20 cannot miss, so such a rider never runs there, whatever
    else the same reaction row carries.
    """
    return bool(isinstance(effect, dict) and effect.get("only_if_miss"))


def _changes_hit_miss_only(row: dict[str, Any]) -> bool:
    """Whether ``row`` can do nothing on an already-landed attack except try to make it a miss.

    True when the row has at least one typed effect and every one of them is an ``ac_bonus``, a
    penalty ``attack_modifier`` aimed at the attacker, or an ``only_if_miss`` rider. A row with no
    typed effects at all cannot change the comparison either, so it counts as well: it has nothing
    left to offer on a critical. Any other effect type -- a reduction, a condition, a retaliation --
    makes this False, and the row is then offered on a natural 20 like it is on any other hit.
    """
    effects = [e for e in row.get("effects") or [] if isinstance(e, dict)]
    if not effects:
        return True  # nothing typed to do, so nothing to do about a hit that already landed
    for effect in effects:
        if _miss_dependent(effect):
            continue  # its own printed rule waits for a miss, which a critical never is
        if effect.get("type") in _CRITICAL_ONLY_HIT_MISS_TYPES:
            continue
        if effect.get("type") == "attack_modifier" and effect.get("applies_to") == "attacker":
            continue
        return False  # this effect still means something on a critical hit
    return True


def _skipped_by_critical(natural: int | None, row: dict[str, Any], threshold: int = 20) -> bool:
    """The ONE natural-20 guard for a generic "hit"/"ally_hit" row, narrowed from the old blanket skip.

    ``row`` is the reaction being considered. A critical cannot be turned into a miss, so a row whose
    effects only move that comparison -- or whose only other rider is printed to follow the miss -- is
    skipped and its Reaction is saved; a row that reduces the damage, adds a condition or retaliates
    is offered as normal. Classification is by typed effect (see ``_changes_hit_miss_only``), not by
    ability name.

    Every path asks this same question and must get the same answer: whether the reaction may be
    offered now (``on_attack_hit`` and ``_offer_ally_hit``), and whether a higher-ranked reaction could
    still answer this attack, so that a row that cannot act never suppresses a lower-ranked one that
    can (``_answer_ready``). ``natural`` is None before the roll, where nothing is known yet.
    """
    return natural is not None and natural >= threshold and _changes_hit_miss_only(row)


def _remaining_rider_effects(row: dict[str, Any], *, hit_after: bool, spent: list[Any] = ()) -> list[dict[str, Any]]:
    """The effects a hit reaction still has to run once it has been paid for.

    Dropped are the effects the checkpoint applied itself -- ``spent`` (the attack penalty, the damage
    reduction it parked, any ``only_if_zero`` effect it is holding for the reduced amount), the AC
    bonus, and a penalty ``attack_modifier`` aimed at the attacker. ``hit_after`` is whether the attack
    still lands after the reaction's own AC bonus and penalty.

    An ``only_if_miss`` rider is printed as a consequence of the miss -- "If this causes the attack to
    miss, you may move 5 feet without provoking Opportunity Attacks" -- so it is held back whenever the
    attack still lands, and in particular on a critical, which can never miss. Everything else the row
    carries still runs there, which is the point: on a natural 20 the damage reduction, the condition
    and the retaliation are worth the Reaction even though the AC bonus and the step are not.

    Shared by the self path (``on_attack_hit``) and the ally path (``_offer_ally_hit``) so both read
    one contract.
    """
    return [e for e in row.get("effects") or []
            if not (isinstance(e, dict)
                    and (e in spent
                         or e.get("type") == "ac_bonus"
                         or (e.get("type") == "attack_modifier" and e.get("applies_to") == "attacker")
                         or (hit_after and _miss_dependent(e))))]


def offer_critical_hit(engine: Any, attacker: Any, target: Any) -> None:
    """Offer a finalized critical after native range and cancellation checks.

    Ordinary hit reactions must not publish this trigger early: a critical can
    be cancelled, or an expanded critical range can produce one below 20.
    """
    for row in _ordered_generic_rows(engine, target.entity_id, "critical_hit"):
        if not _subject_ok(engine, target, attacker, row):
            continue  # not answerable (denied, Silenced, mark, reach), or kept for a marked creature (step 15)
        try:
            if not _can_trigger(engine, target, row) or not _generic_affordable(engine, target, row) or not _generic_in_range(engine, target, attacker, row, subject=target, source=attacker):
                continue
            if not _consent(engine, row, target, "ATTACK_HIT_BEFORE_DAMAGE", trigger={
                    "actor_id": attacker.entity_id, "target_id": target.entity_id}):
                continue  # "Ask me" (step 16): the player passed
            with _reaction_activation(engine, target, attacker, row) as permitted:
                if not permitted:
                    continue
                _open(engine, row, target, (attacker.entity_id,), "ATTACK_HIT_BEFORE_DAMAGE", {"critical": True})
                if not _spend_generic(engine, target, row):
                    continue
                spend_reaction(engine, target, row)
                _run_generic_effects(engine, target, attacker, row, row.get("effects") or [])
                engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                                     payload={"checkpoint": "ATTACK_HIT_BEFORE_DAMAGE", "critical": True, "hit_after_recheck": True})
                return
        except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
            _log_bad_row(engine, target, attacker, row, exc)


def _offer_ally_hit(engine: Any, target: Any, attacker: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int, *, correct_ac_miss=None, replace_ac_miss=None) -> tuple[int, bool]:
    """ally_hit (owner 2026-09-26): another active fighter on the target's team spends its own
    Reaction to protect the target -- an AC bonus or an attack_modifier penalty on the attacker can
    still flip this hit into a miss; other effects (e.g. a counter) run against the attacker."""
    ranged = spec.get("range_ft") is not None and int(spec.get("range_ft") or 0) > 5
    for bystander in _ally_candidates(engine, target):
        for row in _ordered_generic_rows(engine, bystander.entity_id, "ally_hit"):
            if not _ally_row_ok(engine, bystander, attacker, target, row):
                continue  # not this creature's reaction to make (team, mark, reach), or kept for a marked creature
            try:
                if _skipped_by_critical(natural, row, int(spec.get("critical_threshold", 20))) or not _generic_kind_ok(row, ranged=ranged, melee=not ranged) or not _can_trigger(engine, bystander, row):
                    continue
                if not _generic_affordable(engine, bystander, row) or not _generic_in_range(engine, bystander, target, row, subject=target, source=attacker):
                    continue
                penalty_effects = [e for e in row.get("effects") or []
                                   if isinstance(e, dict) and e.get("type") == "attack_modifier" and e.get("applies_to") == "attacker"]
                ac_amount = sum(_ac_amount(engine, bystander, row, e) for e in row.get("effects") or []
                                if isinstance(e, dict) and e.get("type") == "ac_bonus")
                penalty = sum(_generic_amount(engine, bystander, row, e) for e in penalty_effects)
                reduction_effects = [e for e in row.get("effects") or [] if isinstance(e, dict)
                                     and e.get("type") == "damage_modifier" and not e.get("half")
                                     and (not e.get("protected_if") or _protected_if(engine, bystander, target, e["protected_if"]))]
                reduction = sum(_generic_amount(engine, bystander, row, e) for e in reduction_effects)
                prevention = ac_amount + penalty
                if prevention and not reduction and natural < int(spec.get("critical_threshold", 20)) and total >= effective_ac + prevention:
                    continue  # would not flip this hit; not worth spending yet (owner 2026-10-02 MMX53: on a
                    # critical nothing can, so a row with any other effect is still offered)
                if not _consent(engine, row, bystander, "ATTACK_HIT_BEFORE_DAMAGE", trigger={
                        "actor_id": attacker.entity_id, "target_id": target.entity_id,
                        "source_id": spec.get("source_definition_id"), "action_name": spec.get("action_name")}):
                    continue  # "Ask me" (step 16): the player passed
                with _reaction_activation(engine, bystander, attacker, row, range_subject=target) as permitted:
                    if not permitted:
                        continue
                    _open(engine, row, bystander, (attacker.entity_id, target.entity_id), "ATTACK_HIT_BEFORE_DAMAGE", {"protects": target.entity_id})
                    if not _spend_generic(engine, bystander, row):
                        continue
                    spend_reaction(engine, bystander, row)
                    if ac_amount:
                        engine._add_modifier(target, row["feature_id"], "armor_class", "ADD", ac_amount, "SELF", expires_on="START_OF_SELF_NEXT_TURN")
                    from .ext.attack_reduction import park
                    park(target, attacker.entity_id, reduction, row['feature_id'], engine=engine)
                    new_ac = effective_ac + prevention
                    hit_after = (natural >= int(spec.get("critical_threshold", 20)) or total >= new_ac
                                 if prevention else True)
                    rest = _remaining_rider_effects(row, hit_after=hit_after, spent=[*penalty_effects, *reduction_effects])
                    _run_generic_effects(engine, bystander, attacker, row, rest, protects=target)
                    engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=bystander.entity_id, target_ids=(attacker.entity_id,),
                                         payload={"checkpoint": "ATTACK_HIT_BEFORE_DAMAGE", "ac_bonus": ac_amount, "attack_penalty": penalty,
                                              "new_ac": new_ac, "hit_after_recheck": hit_after, "protects": target.entity_id,
                                              **({"pending_damage_reduction": reduction} if reduction else {})})
            except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
                _log_bad_row(engine, bystander, attacker, row, exc)
                continue
            if not hit_after:
                from .attack_outcomes import correct_ac_defense
                total, restored = correct_ac_defense(total, new_ac, natural, spec, correct_ac_miss)
                if restored:
                    effective_ac = new_ac
                    continue
                if replace_ac_miss and replace_ac_miss(total, new_ac):
                    effective_ac = new_ac
                    continue
            return new_ac, hit_after
    return effective_ac, True


def on_attack_hit(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int, *, correct_ac_miss=None, replace_ac_miss=None) -> tuple[int, bool]:
    """Checkpoint ATTACK_HIT_BEFORE_DAMAGE: an AC reaction that turns the hit into a miss.

    Whenever one of them raises the AC above what the roll was made against, this publishes that one receipt
    (``combat/attack_outcomes.record_attack_outcome``) so a reader can ask what the attack really faced without knowing
    which kind of defence answered: a typed reaction row, an armor_class modifier, or a plug-in's own ``hit_response``
    (Perfect Breath, Brace the Line, the Nine Star guard). Laughing Theft of Timing is the first such reader. A defence
    that made the attack miss without comparing any AC (a plug-in's forced ``hit_response``, normalised by
    ``combat/attack_outcomes.hit_defense_reply``) leaves the AC the roll was made against alone and so publishes nothing:
    there was no higher AC for the receipt to report. Nothing is written into the recorded fight either way, so a saved
    fight replays exactly as before.
    """
    from .attack_outcomes import record_attack_outcome

    faced, hit = _on_attack_hit(engine, attacker, target, spec, total, natural, effective_ac, correct_ac_miss=correct_ac_miss, replace_ac_miss=replace_ac_miss)
    if int(faced) > int(effective_ac):
        record_attack_outcome(engine, attacker, faced, spec.get("source_definition_id") or "")
    return faced, hit


def _on_attack_hit(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int, *, correct_ac_miss=None, replace_ac_miss=None) -> tuple[int, bool]:
    """The checkpoint's own pipeline (see ``on_attack_hit``, which publishes its outcome)."""
    from .activation_payments import reaction_completed
    from .attack_outcomes import correct_ac_defense, hit_defense_reply
    _expire_marks(engine)
    ranged = spec.get("range_ft") is not None and int(spec.get("range_ft") or 0) > 5
    # An AC bonus only against ranged (or only melee) attacks (typed_executor.ac_field, owner 2026-09-26 tournament).
    field = "armor_class_vs_ranged" if ranged else "armor_class_vs_melee"
    guards = [m for m in target.modifiers.values() if m.target_field == field and m.operation == "ADD"]
    qualified = sum(int(m.value) for m in guards)
    if qualified and natural < int(spec.get("critical_threshold", 20)):
        effective_ac += qualified
        if total < effective_ac:
            engine._append_event("PASSIVE_TRIGGERED", guards[0].source_definition_id, actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                                 payload={"ac_bonus": qualified, "against": "ranged" if ranged else "melee",
                                          "new_ac": effective_ac, "hit_after_recheck": False})
            total, restored = correct_ac_defense(total, effective_ac, natural, spec, correct_ac_miss)
            if not restored:
                if replace_ac_miss and replace_ac_miss(total, effective_ac):
                    # An outcome replacement answers this defense only. Let
                    # later defense providers and reactions reach their normal
                    # checkpoints before damage is committed.
                    pass
                else:
                    return effective_ac, False
    from . import ext

    if ext.has("hit_response"):  # a plug-in's free answer to the hit (Brace the Line, combat/ext/warleader_commands.py)
        for provider in ext.callbacks("hit_response"):
            answer = ext.invoke("hit_response", provider, engine, attacker, target, spec, total, natural, effective_ac)
            if answer is not None:
                new_ac, hit, reason, replaced_natural = hit_defense_reply(answer)
                if not hit and reason == 'armor_class' and replaced_natural in (None, natural):
                    total, restored = correct_ac_defense(total, new_ac, natural, spec, correct_ac_miss)
                    if restored:
                        effective_ac = new_ac
                        continue
                    if replace_ac_miss and replace_ac_miss(total, new_ac):
                        effective_ac = new_ac
                        continue
                return (effective_ac if new_ac is None else new_ac), hit   # a forced outcome compared no AC at all
    hit_info = {"ranged": ranged, "total": total, "effective_ac": effective_ac, "natural": natural, "critical_threshold": int(spec.get("critical_threshold", 20))}
    for row in _rows(engine, target.entity_id, "hit_ac"):
        if not _subject_ok(engine, target, attacker, row):
            continue  # not answerable (denied, Silenced, mark, reach), or kept for a marked creature (step 15)
        if (row.get("ranged_only") and not ranged) or natural >= int(spec.get("critical_threshold", 20)) or not _can_react(engine, target, row):
            continue
        if not _holds(engine, target, row["resource_id"], row["cost"]) or total >= effective_ac + row["ac"]:
            continue  # unaffordable, or it would still hit
        if _outranked(engine, target, attacker, row, 1, hit_info):
            continue  # the owner's order: a more important reaction can still answer this attack
        if not _consent(engine, row, target, "ATTACK_HIT_BEFORE_DAMAGE", trigger={
                "actor_id": attacker.entity_id, "target_id": target.entity_id,
                "source_id": spec.get("source_definition_id"), "action_name": spec.get("action_name")}):
            continue  # "Ask me" (step 16): the player passed
        from .paid_relocation import activation as relocation_activation

        with relocation_activation(engine, target, row["feature_id"], independent=True):
            _open(engine, row, target, (attacker.entity_id,), "ATTACK_HIT_BEFORE_DAMAGE")
            engine._spend_resource(target, row["resource_id"], row["cost"], row["feature_id"])
            spend_reaction(engine, target, row)
            if not reaction_completed(engine, target, row["feature_id"]):
                continue
            engine._add_modifier(target, row["feature_id"], "armor_class", "ADD", row["ac"], "SELF", expires_on="START_OF_SELF_NEXT_TURN")
            effective_ac += row["ac"]
            engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                                 payload={"checkpoint": "ATTACK_HIT_BEFORE_DAMAGE", "ac_bonus": row["ac"], "new_ac": effective_ac, "hit_after_recheck": False})
            total, restored = correct_ac_defense(total, effective_ac, natural, spec, correct_ac_miss)
            if not restored:
                if replace_ac_miss and replace_ac_miss(total, effective_ac):
                    continue
                return effective_ac, False
    for row in _ordered_generic_rows(engine, target.entity_id, "hit"):
        try:
            if _skipped_by_critical(natural, row, int(spec.get("critical_threshold", 20))) or not _generic_kind_ok(row, ranged=ranged, melee=not ranged) or not _can_trigger(engine, target, row):
                continue
            if not _generic_affordable(engine, target, row) or not _generic_in_range(engine, target, attacker, row, subject=target, source=attacker):
                continue
            if not _subject_ok(engine, target, attacker, row):
                continue
            ac_amount = 0
            # An attack_modifier penalty against the attacker (owner 2026-09-26) has the same effect on
            # this hit/miss comparison as raising the target's AC by the same amount, but it is a one-off
            # correction to the roll that already happened, not a lasting AC buff, so it is never persisted
            # the way ac_bonus is (engine._add_modifier below).
            penalty_effects = [e for e in row.get("effects") or []
                               if isinstance(e, dict) and e.get("type") == "attack_modifier" and e.get("applies_to") == "attacker"]
            for effect in row.get("effects") or []:
                if isinstance(effect, dict) and effect.get("type") == "ac_bonus":
                    ac_amount += _ac_amount(engine, target, row, effect)
            penalty = sum(_generic_amount(engine, target, row, e) for e in penalty_effects)
            prevention = ac_amount + penalty
            if (not _asking(engine, target, row) and prevention
                    and natural < int(spec.get("critical_threshold", 20)) and total >= effective_ac + prevention):
                continue  # would not flip this hit; not worth spending yet (on a critical nothing can,
                # so a row that also reduces damage or adds an effect is still worth its Reaction)
            # A "hit"-kind reduction (Haft Guard, Collapse Into Victory, False Fall True Escape,
            # owner 2026-09-26): the trigger is "hits you", but there is no damage to reduce yet at
            # this checkpoint, so the amount is parked on the target and picked up by the very next
            # on_damage call for this same attacker (typed_hit_reduction flag below).
            reduction_effects = [e for e in row.get("effects") or []
                                 if isinstance(e, dict) and e.get("type") == "damage_modifier" and (
                                     e.get("applies_to", "self") == "self" or
                                     row.get("includes_self") and e.get("applies_to") == "ally")]
            if "priority" in row:
                if _outranked(engine, target, attacker, row, 1, {**hit_info, "effective_ac": effective_ac, "total": total}):
                    continue  # the owner's order: a more important reaction can still answer this attack
            elif (not prevention and not reduction_effects and not row.get("free") and not _asking(engine, target, row)
                  and _damage_answer_ready(engine, target, attacker)):
                continue  # Auto: an answer that neither turns the hit into a miss nor reduces it waits for the soak
            reduction = sum(_generic_amount(engine, target, row, e) for e in reduction_effects)
            if not _consent(engine, row, target, "ATTACK_HIT_BEFORE_DAMAGE", trigger={
                    "actor_id": attacker.entity_id, "target_id": target.entity_id,
                    "source_id": spec.get("source_definition_id"), "action_name": spec.get("action_name")}):
                continue  # "Ask me" (step 16): the player passed
            with _reaction_activation(engine, target, attacker, row) as permitted:
                if not permitted:
                    continue
                _open(engine, row, target, (attacker.entity_id,), "ATTACK_HIT_BEFORE_DAMAGE")
                if not _spend_generic(engine, target, row):
                    continue
                spend_reaction(engine, target, row)
                if ac_amount:
                    engine._add_modifier(target, row["feature_id"], "armor_class", "ADD", ac_amount, "SELF", expires_on="START_OF_SELF_NEXT_TURN")
                if reduction:
                    from .ext.attack_reduction import park
                    park(target, attacker.entity_id, reduction, row['feature_id'], engine=engine)
                new_ac = effective_ac + prevention
                hit_after = (natural >= int(spec.get("critical_threshold", 20)) or total >= new_ac
                             if prevention else True)
                # Iron Forearm Guard: "If this reduces the damage to 0, the attacker becomes Opened" (owner 2026-09-28,
                # auto-ironclad) -- at this checkpoint the damage has not even been rolled yet (only ``reduction``, a
                # flat amount, is known), so an only_if_zero effect cannot run here; it is parked next to the flat
                # reduction above and picked up once on_damage below has subtracted that reduction from the real
                # pending amount and can tell whether it actually reached 0.
                zero_only = [e for e in row.get("effects") or [] if isinstance(e, dict) and e.get("only_if_zero")]
                rest = _remaining_rider_effects(row, hit_after=hit_after, spent=[*penalty_effects, *reduction_effects, *zero_only])
                _run_generic_effects(engine, target, attacker, row, rest)
                if zero_only:
                    from .paid_relocation import capture, retain_effect

                    zero_key = f"typed_hit_zero_effects:{attacker.entity_id}"
                    deferred = copy.deepcopy(zero_only)
                    receipt = capture(engine)
                    for effect in deferred:
                        retain_effect(engine, effect, receipt)
                    target.turn_flags[zero_key] = [*(target.turn_flags.get(zero_key) or []), *deferred]
                engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                                     payload={"checkpoint": "ATTACK_HIT_BEFORE_DAMAGE", "ac_bonus": ac_amount, "attack_penalty": penalty,
                                              "new_ac": new_ac, "hit_after_recheck": hit_after, "pending_damage_reduction": reduction})
        except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
            _log_bad_row(engine, target, attacker, row, exc)
            continue
        if not hit_after:
            total, restored = correct_ac_defense(total, new_ac, natural, spec, correct_ac_miss)
            if restored:
                effective_ac = new_ac
                continue
            if replace_ac_miss and replace_ac_miss(total, new_ac):
                effective_ac = new_ac
                continue
        return new_ac, hit_after
    return _offer_ally_hit(engine, target, attacker, spec, total, natural, effective_ac,
                          correct_ac_miss=correct_ac_miss, replace_ac_miss=replace_ac_miss)


def _protected_if(engine: Any, reactor: Any, who: Any, want: dict[str, Any]) -> bool:
    from .typed_executor import mark_condition_id

    marks = {mark_condition_id(name, reactor.entity_id) for name in want.get("marks") or []}
    return (bool(want.get("bloodied")) and who.current_hp * 2 <= who.maximum_hp) or any(c.condition_id in marks for c in who.conditions.values())


def _generic_damage_reduction(engine: Any, actor: Any, row: dict[str, Any], pending: int, protected: Any = None,
                              *, budget: list | None = None, attacker: Any = None,
                              source_actor_id: str | None = None) -> tuple[int, list[dict[str, Any]]]:
    """(reduced pending, remaining effects) for a "damaged"/"ally_damaged" row's resistance/immunity/
    damage_modifier/half_damage effects (owner 2026-09-26, shared by the self and ally-damaged paths):
    False-Image Guard, Momentum Guard, Furnace Guard and siblings all read "reduce that/the damage by
    <flat/dice/formula>", so a damage_modifier effect here is always a reduction, never a buff. A reduction row with
    "protected_if" ({"bloodied": bool, "marks": [the reactor's mark names]}) counts only when the protected creature (the
    user, on the self path) is Bloodied or bears one of those marks (Blood Ward's "+PB if the protected creature is Bloodied
    or bears your Blood Thread", rider lane C5); rows without it are unchanged."""
    effects = row.get("effects") or []
    who = protected if protected is not None else actor
    # General source-qualified defensive effects. A reaction may admit a
    # maintenance threat while its numeric reduction is limited to hostility.
    # The packet producer, never an action label, supplies that source fact.
    from .pending_damage import current
    packet = current(engine)
    effects = [e for e in effects if not (isinstance(e, dict) and e.get('hostile_source_only') is True)
               or bool(packet and packet.target_id == who.entity_id and packet.hostile)]
    effects = [e for e in effects if not (isinstance(e, dict) and e.get("protected_if")) or _protected_if(engine, actor, who, e["protected_if"])]
    reduction_effects = [e for e in effects if isinstance(e, dict) and e.get("type") in ("resistance", "immunity", "damage_modifier", "half_damage")]
    holds = [e for e in effects if isinstance(e, dict) and e.get("type") == "hold_at_1hp"]
    # Iron Forearm Guard: "If this reduces the damage to 0, the attacker becomes Opened" (owner 2026-09-28,
    # auto-ironclad) -- an effect flagged only_if_zero is held out of "rest" (so it never fires alongside a
    # nonzero reduction) and spliced back in below once the reduced amount is known to be exactly 0.
    zero_only = [e for e in effects if isinstance(e, dict) and e.get("only_if_zero")]
    rest = [e for e in effects if e not in reduction_effects and e not in holds and e not in zero_only]
    kinds = {e["type"] for e in reduction_effects}
    if "immunity" in kinds:
        reduced = 0
    elif any(e.get("half") for e in reduction_effects if e["type"] == "damage_modifier"):
        reduced = pending // 2  # "halve the damage" (R6)
    elif "damage_modifier" in kinds:
        # A reduction that names damage types adds only against those ("If the triggering damage is Necrotic, Radiant ...",
        # Dawn Ward; rider lane 10 2026-09-29).
        pending_kind = str(getattr(engine, "_typed_pending_damage_type", None) or "").lower()
        portions, signed = [], []
        for e in reduction_effects:
            if e['type'] != 'damage_modifier':
                continue
            types = tuple(str(kind).upper() for kind in e.get('only_damage_types') or [])
            raw = []
            value = _generic_amount(engine, actor, row, e, raw_terms=raw)
            portions.append((value, types))
            signed.append((raw[0], types))
        from . import ext
        extra = 0
        for bonus in ext.run_strict("damage_reduction_bonus", engine, actor, protected or actor, attacker, row):
            if type(bonus) is not int or bonus < 0:
                raise ValueError("damage_reduction_bonus requires a nonnegative integer or None")
            extra += bonus
        from .pending_damage import answer
        extra += answer(engine, row)[1]
        if extra:
            portions.append((extra, ()))
            signed.append((extra, ()))
        from .support_values import reduction_terms
        normalized = reduction_terms(engine, actor, who, row['feature_id'], signed)
        if normalized is not None:
            portions = normalized
        amount = sum(max(0, n) if normalized is not None else n
                     for n, types in portions if not types or pending_kind.upper() in types)
        if budget is not None:
            budget.extend(portions)
        reduced = max(0, pending - amount)
    elif reduction_effects:  # half_damage, or resistance granted by the reaction itself
        reduced = pending // 2
    else:
        reduced = pending  # nothing numeric: still worth firing for its other effects (e.g. a condition, a counter)
    if holds:
        # "drops to 1 HP instead of 0" (R6: The First Pact, The Wall That Remains, Borrowed Ending)
        who = protected if protected is not None else actor
        from .damage_allocation import maximum_packet_before_hp_floor
        source_id = source_actor_id or getattr(attacker, "entity_id", None)
        cap = maximum_packet_before_hp_floor(engine, who, reduced, int(holds[0].get("keep", 1)), source_id)
        reduced = min(reduced, cap)
    if reduced == 0:
        rest = [*rest, *zero_only]
    return reduced, rest


def _commit_damage_reduction_values(engine, actor, protected, row, pending, reduced, budget, rest):
    """General scalar settlement after accepted reaction consent and payment.

    Query dice/terms are carried intact; no provider rerolls them. A newly zero
    result activates the same source-owned zero-result riders as the base path.
    """
    from .support_values import committed_reduction
    reduced = committed_reduction(engine, actor, protected, row['feature_id'], pending,
        reduced, budget, str(getattr(engine, '_typed_pending_damage_type', '') or '').upper())
    if reduced == 0:
        rest = [*rest, *(e for e in row.get('effects') or []
                         if isinstance(e, dict) and e.get('only_if_zero') and e not in rest)]
    return reduced, rest


def _offer_ally_damaged(engine: Any, target: Any, attacker: Any, pending: int, reaction_depth: int, source_actor_id: str | None) -> int:
    """ally_damaged (owner 2026-09-26): another active fighter on the target's team spends its own
    Reaction to reduce the target's pending damage (e.g. "You or an ally within 30 feet takes
    damage" Guard/Ward reactions -- 19 of the shipped authority's reactions use this exact phrasing)."""
    for bystander in _ally_candidates(engine, target):
        for row in _ordered_generic_rows(engine, bystander.entity_id, "ally_damaged"):
            if not _ally_row_ok(engine, bystander, attacker, target, row):
                continue  # not this creature's reaction to make (team, mark, reach), or kept for a marked creature
            try:
                if not _can_trigger(engine, bystander, row) or not _generic_affordable(engine, bystander, row) or not _generic_in_range(engine, bystander, target, row, subject=target, source=attacker):
                    continue
                if not _generic_damage_type_ok(engine, row):
                    continue
                budget: list = []
                reduced, rest = _generic_damage_reduction(engine, bystander, row, pending, protected=target, budget=budget, attacker=attacker, source_actor_id=source_actor_id)
                attacker_ids = (source_actor_id,) if source_actor_id else ()
                if not _consent(engine, row, bystander, "DAMAGE_APPLICATION", trigger={
                        "actor_id": source_actor_id, "target_id": target.entity_id, "damage_amount": pending}):
                    continue  # "Ask me" (step 16): the player passed
                with _reaction_activation(engine, bystander, attacker, row, range_subject=target) as permitted:
                    if not permitted:
                        continue
                    _open(engine, row, bystander, attacker_ids, "DAMAGE_APPLICATION", {"pending_damage": pending, "protects": target.entity_id})
                    if any(isinstance(e, dict) and e.get("type") == "redirect_damage_to_self" for e in row.get("effects") or []):
                        # One Body (R6): "redirect all damage those allies would take from the triggering effect to yourself"
                        engine._commit_damage(bystander, pending, str(getattr(engine, "_typed_pending_damage_type", None) or "UNTYPED"),
                                              row["feature_id"], source_actor_id or bystander.entity_id, None, reaction_depth=reaction_depth + 1)
                        reduced = 0
                    if not _spend_generic(engine, bystander, row):
                        continue
                    reduced, rest = _commit_damage_reduction_values(engine, bystander, target,
                        row, pending, reduced, budget, rest)
                    from .ext.attack_reduction import remember
                    reduced = remember(engine, target, pending, reduced, budget)
                    spend_reaction(engine, bystander, row)
                    _run_generic_effects(engine, bystander, attacker, row, rest, protects=target)
                    engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=bystander.entity_id, target_ids=attacker_ids,
                                         payload={"checkpoint": "DAMAGE_APPLICATION", "reduction": pending - reduced, "pending_before": pending,
                                                  "pending_after": reduced, "reaction_depth": reaction_depth, "protects": target.entity_id})
                    return reduced
            except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
                _log_bad_row(engine, bystander, attacker, row, exc)
    return pending


def _death_prevention_denied(target: Any) -> bool:
    """Whether ``target`` may not benefit from anything that would keep it above 0 Hit Points.

    A printed clause rides its own condition as the rule ``death_prevention_denied`` (the rules row
    ``no_death_prevention``, combat/rules/typed_conditions.json), e.g. Death's No Return Edict: "cannot
    benefit from an effect that would prevent it from dropping to 0 HP".  General: any condition may
    carry the rule and a creature without one keeps every provider, so a fight saved before the rule
    existed replays unchanged.  Two paths read it here -- the ``would_drop`` plug-ins that shrink the
    pending damage, and the generic ``drop_to_zero``/``ally_drop_to_zero`` rows that would hold the
    creature at 1 Hit Point.  Forced movement and teleports carry no death-prevention provider.
    """
    from .typed_executor import condition_rules

    return any(rule.get("death_prevention_denied") for rule in condition_rules(target))


def _keeps_above_zero(row: dict[str, Any]) -> bool:
    """Whether answering this reaction row would leave its creature above 0 Hit Points.

    The printed shapes that do that are "it drops to 1 Hit Point instead of 0" and Temporary Hit
    Points granted on the spot; the engine caps the damage with the same ``hold_at_1hp`` reading in
    ``_generic_damage_reduction``.  A row that only deals damage to the falling creature is not one of
    them, and still fires.
    """
    return any(isinstance(effect, dict) and effect.get("type") in ("hold_at_1hp", "temp_hp")
               for effect in row.get("effects") or [])


def _offer_drop_to_zero_or_bloodied(engine: Any, target: Any, attacker: Any, pending: int, reaction_depth: int, source_actor_id: str | None) -> int:
    """drop_to_zero / bloodied (owner 2026-09-26): offered against the target's own current HP before
    Hit Points actually drop, e.g. a "refuse to fall" temp HP grant or damage reduction. bloodied only
    fires the turn it would newly cross the half-HP line, so it does not re-offer every hit once a
    fighter is already below half."""
    from . import ext

    denied = _death_prevention_denied(target)
    from .damage_allocation import available_temporary_hp
    available_temp = available_temporary_hp(engine, target, pending, source_actor_id)
    if (ext.has("would_drop") and pending >= target.current_hp + available_temp and not denied):
        # A plug-in that keeps the creature standing (Standard Cannot Fall, combat/ext/banner.py) shrinks the damage before any reaction is offered.
        pending = min([pending, *(int(left) for left in ext.run("would_drop", engine, target, pending, source_actor_id))])
    # Damage removes Temporary HP before Hit Points, so both a zero-HP
    # replacement and a bloodied trigger must use the actual HP loss.
    available_temp = available_temporary_hp(engine, target, pending, source_actor_id)
    hp_loss = max(0, pending - available_temp)
    would_be = target.current_hp - hp_loss
    kind = None
    if would_be <= 0:
        kind = "drop_to_zero"
    elif target.current_hp > target.maximum_hp // 2 >= would_be:
        kind = "bloodied"
    if kind is None:
        return pending
    for row in _ordered_generic_rows(engine, target.entity_id, kind):
        if not _subject_ok(engine, target, attacker, row):
            continue  # not answerable (denied, Silenced, mark, reach), or kept for a marked creature (step 15)
        if denied and _keeps_above_zero(row):
            continue  # the creature may not benefit from anything that would keep it standing
        try:
            if not _can_trigger(engine, target, row) or not _generic_affordable(engine, target, row):
                continue
            if not _generic_damage_type_ok(engine, row):
                continue
            budget: list = []
            reduced, rest = _generic_damage_reduction(engine, target, row, pending, budget=budget, attacker=attacker, source_actor_id=source_actor_id)
            attacker_ids = (source_actor_id,) if source_actor_id else ()
            if not _consent(engine, row, target, "DAMAGE_APPLICATION", trigger={
                    "actor_id": source_actor_id, "target_id": target.entity_id, "damage_amount": pending}):
                continue  # "Ask me" (step 16): the player passed
            with _reaction_activation(engine, target, attacker, row) as permitted:
                if not permitted:
                    continue
                _open(engine, row, target, attacker_ids, "DAMAGE_APPLICATION", {"pending_damage": pending, "kind": kind})
                if not _spend_generic(engine, target, row):
                    continue
                reduced, rest = _commit_damage_reduction_values(engine, target, target,
                    row, pending, reduced, budget, rest)
                from .ext.attack_reduction import remember
                reduced = remember(engine, target, pending, reduced, budget)
                spend_reaction(engine, target, row)
                if any(isinstance(e, dict) and e.get("type") == "hold_at_1hp" for e in row.get("effects") or []):
                    # Temporary HP a "drop to 1 HP instead" reaction grants lands after the hit, not inside it (Heaven-Spiting
                    # Recovery: the lethal hit was eating the buffer it grants); flush_after_commit runs it.
                    later = [e for e in rest if isinstance(e, dict) and e.get("type") == "temp_hp"]
                    if later:
                        rest = [e for e in rest if e not in later]
                        from .paid_relocation import capture, retain_effect, preserve_pending

                        entry = (target.entity_id, source_actor_id, row, later)
                        retain_effect(engine, entry, capture(engine))
                        preserve_pending(engine, "_typed_after_commit")
                        engine.__dict__.setdefault("_typed_after_commit", []).append(entry)
                _run_generic_effects(engine, target, attacker, row, rest)
                engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=attacker_ids,
                                     payload={"checkpoint": "DAMAGE_APPLICATION", "kind": kind, "reduction": pending - reduced,
                                              "pending_before": pending, "pending_after": reduced, "reaction_depth": reaction_depth})
                return reduced
        except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
            _log_bad_row(engine, target, attacker, row, exc)
    if kind == "drop_to_zero":
        # R5: "you or an ally within 30 feet would drop to 0 HP" -- a Factory ally in range may answer before HP drops.
        for bystander in _ally_candidates(engine, target):
            for row in _ordered_generic_rows(engine, bystander.entity_id, "ally_drop_to_zero"):
                if denied and _keeps_above_zero(row):
                    continue  # an ally cannot spend its Reaction to keep a creature that may not benefit from it
                try:
                    if not _ally_row_ok(engine, bystander, attacker, target, row) or not _can_trigger(engine, bystander, row):
                        continue
                    if not _generic_affordable(engine, bystander, row) or not _generic_in_range(engine, bystander, target, row, subject=target, source=attacker) or not _generic_damage_type_ok(engine, row):
                        continue
                    if not _consent(engine, row, bystander, "DAMAGE_APPLICATION"):
                        continue
                    with _reaction_activation(engine, bystander, target, row) as permitted:
                        if not permitted:
                            continue
                        budget: list = []
                        reduced, rest = _generic_damage_reduction(engine, bystander, row, pending, protected=target, budget=budget, attacker=attacker, source_actor_id=source_actor_id)
                        _open(engine, row, bystander, (target.entity_id,), "DAMAGE_APPLICATION", {"pending_damage": pending, "kind": "ally_drop_to_zero"})
                        if not _spend_generic(engine, bystander, row):
                            continue
                        reduced, rest = _commit_damage_reduction_values(engine, bystander, target,
                            row, pending, reduced, budget, rest)
                        from .ext.attack_reduction import remember
                        reduced = remember(engine, target, pending, reduced, budget)
                        spend_reaction(engine, bystander, row)
                        _run_generic_effects(engine, bystander, target, row, rest)
                        engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=bystander.entity_id, target_ids=(target.entity_id,),
                                             payload={"checkpoint": "DAMAGE_APPLICATION", "kind": "ally_drop_to_zero", "pending_before": pending,
                                                      "pending_after": reduced, "reaction_depth": reaction_depth})
                        return reduced
                except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
                    _log_bad_row(engine, bystander, attacker, row, exc)
    return pending


def _generic_damage_responses(engine: Any, target: Any, attacker: Any | None, pending: int, reaction_depth: int,
                              source_actor_id: str | None, damage_info: dict[str, Any], *, free_only: bool) -> tuple[int, bool]:
    """"When you take damage" rows: at most one that spends the Reaction, and every free one (each with its own
    once-per limit) -- a paid answer no longer silences a free one (Astra's audit, 2026-09-26). (pending, fired)."""
    fired, reacted = False, free_only
    for row in _ordered_generic_rows(engine, target.entity_id, "damaged"):
        try:
            if (reacted and not row.get("free")) or not _can_trigger(engine, target, row) or not _generic_affordable(engine, target, row):
                continue
            if not _generic_in_range(engine, target, attacker, row, subject=target, source=attacker):
                continue
            if not _generic_damage_type_ok(engine, row) or not _subject_ok(engine, target, attacker, row):
                continue  # a "from a creature bearing your Waning Mark" limit is checked here too (owner 2026-09-26)
            if _outranked(engine, target, attacker, row, 2, {**damage_info, "pending": pending}):
                continue  # the owner's order: a more important reaction answers this damage
            budget: list = []
            reduced, rest = _generic_damage_reduction(engine, target, row, pending, budget=budget, attacker=attacker, source_actor_id=source_actor_id)
            attacker_ids = (source_actor_id,) if source_actor_id else ()
            if not _consent(engine, row, target, "DAMAGE_APPLICATION", trigger={
                    "actor_id": source_actor_id, "target_id": target.entity_id, "damage_amount": pending}):
                continue  # "Ask me" (step 16): the player passed
            with _reaction_activation(engine, target, attacker, row) as permitted:
                if not permitted:
                    continue
                _open(engine, row, target, attacker_ids, "DAMAGE_APPLICATION", {"pending_damage": pending})
                if not _spend_generic(engine, target, row):
                    continue
                reduced, rest = _commit_damage_reduction_values(engine, target, target,
                    row, pending, reduced, budget, rest)
                from .ext.attack_reduction import remember
                reduced = remember(engine, target, pending, reduced, budget)
                if not row.get("free"):
                    spend_reaction(engine, target, row)
                    reacted = True
                _run_generic_effects(engine, target, attacker, row, rest)
                engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=attacker_ids,
                                     payload={"checkpoint": "DAMAGE_APPLICATION", "reduction": pending - reduced, "pending_before": pending,
                                              "pending_after": reduced, "reaction_depth": reaction_depth})
                pending, fired = reduced, True
        except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
            _log_bad_row(engine, target, attacker, row, exc)
    return pending, fired


def on_damage(engine: Any, target: Any, pending: int, reaction_depth: int, source_definition_id: str | None = None,
              source_actor_id: str | None = None) -> int:
    """Checkpoint DAMAGE_APPLICATION: a free parry first, then soak dice, before Hit Points drop."""
    from .paid_relocation import preserve_pending
    preserve_pending(engine, "_typed_trigger_damage")
    from .activation_payments import reaction_completed
    _expire_marks(engine)
    engine._typed_trigger_damage = pending  # "half the triggering damage" (Harm Returned, R6)
    from .gate2_runtime_models import DiceSpec
    from .ext.attack_reduction import carry, remember

    pending = carry(engine, target, pending)

    if source_actor_id:
        # A "hit"-kind reduction parked by on_attack_hit for this same attacker (Haft Guard and
        # siblings, owner 2026-09-26): the amount was already decided and paid for at the hit
        # checkpoint, so it is simply subtracted here, not offered again as a new reaction.
        key = f"typed_hit_reduction:{source_actor_id}"
        parked = target.turn_flags.pop(key, None)
        reduced_by = target.turn_flags.pop(f"typed_hit_reduced_by:{source_actor_id}", None) or []
        if parked:
            before_reduction = pending
            pending = max(0, pending - int(parked))
            pending = remember(engine, target, before_reduction, pending, [(int(parked), ())])
            from . import ext

            # Follow-ups to an actual hit reduction, after rolled damage is known.
            # All hooks see the same before/after values; additional reductions
            # add up. No hook means the original parked-reduction behavior.
            if pending < before_reduction:
                extra = ext.run_strict("hit_reduced", engine, target, engine.state.actors.get(source_actor_id),
                                source_definition_id, before_reduction, pending, tuple(reduced_by))
                additional = sum(max(0, int(amount or 0)) for amount in extra)
                pending = remember(engine, target, pending, max(0, pending - additional), [(additional, ())])
        # Iron Forearm Guard's only_if_zero effects (owner 2026-09-28), parked above in on_attack_hit: now that the
        # flat reduction has actually been subtracted from the real pending damage, run them if -- and only if --
        # this attacker's hit is now fully absorbed.
        zero_effects = target.turn_flags.pop(f"typed_hit_zero_effects:{source_actor_id}", None)
        if zero_effects and pending == 0:
            zero_attacker = engine.state.actors.get(source_actor_id)
            if zero_attacker is not None:
                _run_generic_effects(engine, target, zero_attacker, {"feature_id": "typed_hit_zero_effects", "name": "Zero-Damage Follow-up"}, zero_effects)
        if parked and pending == 0:
            from . import ext

            ext.run("hit_absorbed", engine, target, engine.state.actors.get(source_actor_id), reduced_by)  # Needle-Catching Reversal
    from . import ext

    if ext.has("damage_pending"):  # a plug-in's answer to the damage about to land (Brace the Line, Legion Unending)
        for adjusted in ext.run("damage_pending", engine, target, pending, source_definition_id, source_actor_id):
            pending = min(pending, int(adjusted))
    from .pending_damage import prepare
    prepare(engine, pending, getattr(engine, '_active_intent', None))
    attacker = engine.state.actors.get(source_actor_id) if source_actor_id else None
    damage_info = {"ranged": None, "pending": pending}
    for row in _rows(engine, target.entity_id, "damage_reduction"):
        if not _subject_ok(engine, target, attacker, row):
            continue  # not answerable (denied, Silenced, mark, reach), or kept for a marked creature (step 15)
        if row["trigger"] == "melee_weapon_hit" and not melee_weapon_source(engine, source_definition_id):
            continue
        if pending < row["minimum_damage"] or not _holds(engine, target, row["resource_id"], row["cost"]) or not _can_react(engine, target, row):
            continue
        if _outranked(engine, target, attacker, row, 2, damage_info):
            continue  # the owner's order: a more important reaction answers this damage
        attacker_ids = (source_actor_id,) if source_actor_id else ()
        if not _consent(engine, row, target, "DAMAGE_APPLICATION", trigger={
                "actor_id": source_actor_id, "target_id": target.entity_id,
                "source_id": source_definition_id, "damage_amount": pending}):
            continue  # "Ask me" (step 16): the player passed
        from .paid_relocation import activation as relocation_activation

        with relocation_activation(engine, target, row["feature_id"], independent=True):
            _open(engine, row, target, attacker_ids, "DAMAGE_APPLICATION", {"pending_damage": pending})
            if row["cost"]:
                engine._spend_resource(target, row["resource_id"], row["cost"], row["feature_id"])
                if not reaction_completed(engine, target, row["feature_id"]):
                    continue
            count, sides = _dice(row["dice"])
            reduction = row["bonus"]
            if count and sides:
                roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=row["bonus"]), actor_id=target.entity_id,
                                          reason=f"DAMAGE_REDUCTION:{row['feature_id']}")
                engine._record_roll(roll)
                reduction = roll.total
            for bonus in ext.run_strict("damage_reduction_bonus", engine, target, target, attacker, row):
                if type(bonus) is not int or bonus < 0:
                    raise ValueError("damage_reduction_bonus requires a nonnegative integer or None")
                reduction += bonus
            spend_reaction(engine, target, row)
            reduced = max(0, pending - reduction)
            reduced = remember(engine, target, pending, reduced, [(reduction, ())])
            engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=attacker_ids,
                                 payload={"checkpoint": "DAMAGE_APPLICATION", "reduction": reduction, "pending_before": pending,
                                          "pending_after": reduced, "reaction_depth": reaction_depth})
            # A free response (no Reaction) still answers the same damage (Astra's audit, 2026-09-26: Diminish Force).
            return _generic_damage_responses(engine, target, attacker, reduced, reaction_depth, source_actor_id, damage_info, free_only=True)[0]
    for row in _rows(engine, target.entity_id, "damage_soak"):
        if not _subject_ok(engine, target, attacker, row):
            continue  # not answerable (denied, Silenced, mark, reach), or kept for a marked creature (step 15)
        available = int(target.resources.get(row["resource_id"], 0) or 0) if _holds(engine, target, row["resource_id"], 1) else 0
        if pending < row["minimum_damage"] or available < 1 or not _can_react(engine, target, row):
            continue
        if _outranked(engine, target, attacker, row, 2, damage_info):
            continue  # the owner's order: a more important reaction answers this damage
        spend = max(1, min(row["max_spend"], available, math.ceil(pending / ((row["die"] + 1) / 2))))
        from .ext.spend_choice import choose_spend

        spend = choose_spend(engine, row, target, "DAMAGE_APPLICATION", min(row["max_spend"], available), spend,
                             {"actor_id": source_actor_id, "target_id": target.entity_id,
                              "source_id": source_definition_id, "damage_amount": pending})
        if not spend:
            continue  # "Ask me" (step 16): the player passed
        from .paid_relocation import activation as relocation_activation

        with relocation_activation(engine, target, row["feature_id"], independent=True):
            _open(engine, row, target, (target.entity_id,), "DAMAGE_APPLICATION", {"pending_damage": pending})
            engine._spend_resource(target, row["resource_id"], spend, row["feature_id"])
            if not reaction_completed(engine, target, row["feature_id"]):
                continue
            from . import ext  # Stamina Guard's dice and total may be shaped by the defender's own features (soak_dice / soak_total)

            dice = DiceSpec(count=spend, sides=row["die"], modifier=0)
            for shaped in ext.run_strict("soak_dice", engine, target, row, spend, dice):
                if isinstance(shaped, DiceSpec):
                    dice = shaped
            roll = engine.roller.roll(dice, actor_id=target.entity_id, reason=f"DAMAGE_SOAK:{row['feature_id']}")
            engine._record_roll(roll)
            soaked = max([int(roll.total), *(int(total) for total in ext.run_strict("soak_total", engine, target, row, roll) if isinstance(total, int))])
            spend_reaction(engine, target, row)
            reduced = max(0, pending - soaked)
            reduced = remember(engine, target, pending, reduced, [(soaked, ())])
            engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=(target.entity_id,),
                                 payload={"checkpoint": "DAMAGE_APPLICATION", "spend": spend, "reduction": soaked, "pending_before": pending,
                                          "pending_after": reduced, "reaction_depth": reaction_depth})
            # Stamina Guard and free damage responses reduce damage before HP is
            # applied. Recheck zero-HP features against that final packet so a
            # response such as Blood Pump is not skipped by the soak early return.
            reduced = _generic_damage_responses(engine, target, attacker, reduced, reaction_depth, source_actor_id, damage_info, free_only=True)[0]
            if target.current_hp > 0 and reduced >= target.current_hp + target.temporary_hp:
                reduced = _offer_drop_to_zero_or_bloodied(engine, target, attacker, reduced, reaction_depth, source_actor_id)
            return reduced
    pending, fired = _generic_damage_responses(engine, target, attacker, pending, reaction_depth, source_actor_id, damage_info, free_only=False)
    if fired:
        return pending
    pending = _offer_drop_to_zero_or_bloodied(engine, target, attacker, pending, reaction_depth, source_actor_id)
    return _offer_ally_damaged(engine, target, attacker, pending, reaction_depth, source_actor_id)


def on_save(engine: Any, target: Any, ability: str, dc: int, roll: Any, source_id: str) -> Any:
    """Checkpoint SAVE_RESULT_BEFORE_DECLARED: add the bonus when it turns a failure into a success."""
    from . import ext
    from .activation_payments import reaction_completed
    if roll.total >= dc or roll.total < 0:  # a success, or an automatic failure
        return roll
    for row in _rows(engine, target.entity_id, "save_rescue"):
        if not _subject_ok(engine, target, _source_actor(engine, source_id), row):
            continue  # not answerable (denied, Silenced, mark, reach), or kept for a marked creature (step 15)
        answered = row["abilities"]
        if row.get("choose_one") and row.get("choices"):
            # The printed "Choose one Defensive Discipline" is the fighter's own pick; a plug-in may narrow the
            # printed options to the one they chose (combat/ext/defensive_disciplines.py). No provider, or nobody
            # answering, keeps the compiled default, so an old saved fight resolves exactly as it was saved.
            for narrowed in ext.run_strict("save_rescue_abilities", engine, target, row):
                if narrowed:
                    answered = [str(value).upper() for value in narrowed]
                    break
        if ability not in answered or not _holds(engine, target, row["resource_id"], row["cost"]):
            continue
        bonus = row["bonus"]
        for adjustment in ext.run_strict("save_rescue_bonus", engine, target, row, ability, dc, roll, source_id):
            if type(adjustment) is not int:
                raise ValueError("save_rescue_bonus requires an integer adjustment")
            bonus += adjustment
        if roll.total + bonus < dc:
            continue
        if row.get("sources") and source_id not in row["sources"]:
            continue  # e.g. "a Constitution saving throw to maintain a Qi-powered feature": a Concentration save only
        flag = f"typed_rescue_round:{row['feature_id']}"
        if row["reaction"] and not _can_react(engine, target, row):
            continue
        if not row["reaction"] and target.turn_flags.get(flag) == engine.state.round_number:
            continue
        source_actor = _source_actor(engine, source_id)
        if not _consent(engine, row, target, "SAVE_RESULT_BEFORE_DECLARED", trigger={
                "actor_id": source_actor.entity_id if source_actor is not None else engine.state.current_actor_id,
                "target_id": target.entity_id, "source_id": source_id, "roll_kind": "save"}):
            continue  # "Ask me" (step 16): the player passed
        from .paid_relocation import activation as relocation_activation

        with relocation_activation(engine, target, row["feature_id"], independent=True):
            _open(engine, row, target, (target.entity_id,), "SAVE_RESULT_BEFORE_DECLARED", {"ability": ability, "dc": dc, "total": roll.total})
            engine._spend_resource(target, row["resource_id"], row["cost"], row["feature_id"])
            if row["reaction"]:
                spend_reaction(engine, target, row)
            else:
                target.turn_flags[flag] = engine.state.round_number
            if row["cost"] and not reaction_completed(engine, target, row["feature_id"], consumes_reaction=row["reaction"]):
                continue
            roll = roll.model_copy(update={"modifier": roll.modifier + bonus, "total": roll.total + bonus})
            engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=(target.entity_id,),
                                 payload={"checkpoint": "SAVE_RESULT_BEFORE_DECLARED", "bonus": bonus, "source_save": source_id})
            return roll
    # A generic save reaction whose own effect is a bonus to "the saving throw"/"failed saving throw"
    # (owner 2026-09-26, e.g. Calamity Furnace's "Add your Proficiency Bonus... potentially turning it
    # into a success"): the existing save_rescue block above is the model. Bundled sibling effects on the
    # same row are not run here -- several real rows (Calamity Furnace) print several alternative,
    # mutually exclusive "choose the appropriate response" branches in one effects list, so only the
    # bonus itself is safe to automate; the row still falls through to the side-effects-only loop below
    # when the bonus would not flip the result.
    rescue_attempted: set[str] = set()
    for row in _ordered_generic_rows(engine, target.entity_id, "save"):
        if not _subject_ok(engine, target, _source_actor(engine, source_id), row):
            continue  # not answerable (denied, Silenced, mark, reach), or kept for a marked creature (step 15)
        bonus_effect = next((e for e in row.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack_modifier"
                            and e.get("applies_to", "self") in ("self", None) and "sav" in str(e.get("on") or e.get("evidence") or "").lower()), None)
        if bonus_effect is None:
            continue
        rescue_attempted.add(row["feature_id"])  # tried here; an insufficient bonus is not worth firing again below
        try:
            if not _can_trigger(engine, target, row) or not _generic_affordable(engine, target, row) or not _generic_save_ability_ok(row, ability):
                continue
            bonus = _generic_amount(engine, target, row, bonus_effect)
            if roll.total + bonus < dc:
                continue  # would not turn the failure into a success; not worth spending yet
            if not _consent(engine, row, target, "SAVE_RESULT_BEFORE_DECLARED"):
                continue  # "Ask me" (step 16): the player passed
            with _reaction_activation(engine, target, None, row) as permitted:
                if not permitted:
                    continue
                _open(engine, row, target, (), "SAVE_RESULT_BEFORE_DECLARED", {"ability": ability, "dc": dc, "total": roll.total})
                if not _spend_generic(engine, target, row):
                    continue
                spend_reaction(engine, target, row)
                roll = roll.model_copy(update={"modifier": roll.modifier + bonus, "total": roll.total + bonus})
                engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=(),
                                     payload={"checkpoint": "SAVE_RESULT_BEFORE_DECLARED", "bonus": bonus, "source_save": source_id})
                return roll
        except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
            _log_bad_row(engine, target, None, row, exc)
    # Generic "you fail a save" reactions run for their own effects only: the roll already happened
    # (owner 2026-09-25), and most of these grant Advantage, which typed_executor cannot apply after
    # the fact, so there is no numeric rescue here beyond what save_rescue above already covers.
    for row in _ordered_generic_rows(engine, target.entity_id, "save"):
        if not _subject_ok(engine, target, _source_actor(engine, source_id), row):
            continue  # not answerable (denied, Silenced, mark, reach), or kept for a marked creature (step 15)
        if row["feature_id"] in rescue_attempted:
            continue
        try:
            if not _can_trigger(engine, target, row) or not _generic_affordable(engine, target, row) or not _generic_save_ability_ok(row, ability):
                continue
            if not _consent(engine, row, target, "SAVE_RESULT_BEFORE_DECLARED"):
                continue  # "Ask me" (step 16): the player passed
            with _reaction_activation(engine, target, None, row) as permitted:
                if not permitted:
                    continue
                _open(engine, row, target, (), "SAVE_RESULT_BEFORE_DECLARED", {"ability": ability, "dc": dc, "total": roll.total})
                if not _spend_generic(engine, target, row):
                    continue
                spend_reaction(engine, target, row)
                _run_generic_effects(engine, target, None, row, row.get("effects") or [])
                engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=(),
                                     payload={"checkpoint": "SAVE_RESULT_BEFORE_DECLARED", "source_save": source_id})
                break
        except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
            _log_bad_row(engine, target, None, row, exc)
    return roll


def _offer_ally_attacked(engine: Any, target: Any, attacker: Any, spec: dict[str, Any], intent: Any = None) -> None:
    """ally_attacked (owner 2026-09-26): another active fighter on the target's team may spend its own
    Reaction before the roll (a penalty on the attacker, or another effect against the attacker)."""
    ranged = spec.get("range_ft") is not None and int(spec.get("range_ft") or 0) > 5
    for bystander in _ally_candidates(engine, target):
        for row in _ordered_generic_rows(engine, bystander.entity_id, "ally_attacked"):
            if not _ally_row_ok(engine, bystander, attacker, target, row):
                continue  # not this creature's reaction to make (team, mark, reach), or kept for a marked creature
            try:
                if not _generic_kind_ok(row, ranged=ranged, melee=not ranged) or not _can_trigger(engine, bystander, row):
                    continue
                if not _generic_affordable(engine, bystander, row) or not _generic_in_range(engine, bystander, target, row, subject=target, source=attacker):
                    continue
                penalty_effects = [e for e in row.get("effects") or []
                                   if isinstance(e, dict) and e.get("type") == "attack_modifier" and e.get("applies_to") == "attacker"]
                penalty = sum(_generic_amount(engine, bystander, row, e) for e in penalty_effects)
                if not _consent(engine, row, bystander, "ATTACK_DECLARED", trigger={
                        "actor_id": attacker.entity_id, "target_id": target.entity_id,
                        "source_id": spec.get("source_definition_id"), "action_name": spec.get("action_name")}):
                    continue  # "Ask me" (step 16): the player passed
                with _reaction_activation(engine, bystander, attacker, row, range_subject=target) as permitted:
                    if not permitted:
                        continue
                    _open(engine, row, bystander, (attacker.entity_id, target.entity_id), "ATTACK_DECLARED", {"protects": target.entity_id})
                    if not _spend_generic(engine, bystander, row):
                        continue
                    spend_reaction(engine, bystander, row)
                    if penalty:
                        spec["attack_bonus"] = int(spec.get("attack_bonus") or 0) - penalty
                    attack_ac = [e for e in row.get("effects") or [] if isinstance(e, dict)
                                 and e.get("type") == "ac_bonus" and e.get("duration") == "triggering_attack"]
                    rest = [({**e, "amount": _ac_amount(engine, bystander, row, e)} if e in attack_ac else e)
                            for e in row.get("effects") or [] if e not in penalty_effects]
                    _run_generic_effects(engine, bystander, attacker, row, rest, intent,
                                         protects=target, recipient=target if attack_ac else None, attack_spec=spec)
                    engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=bystander.entity_id, target_ids=(attacker.entity_id,),
                                         payload={"checkpoint": "ATTACK_DECLARED", "attack_penalty": penalty, "protects": target.entity_id})
                    return
            except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
                _log_bad_row(engine, bystander, attacker, row, exc)


def on_attacked(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], intent: Any = None) -> None:
    """Checkpoint ATTACK_DECLARED (owner 2026-09-25): a generic reaction that fires before the roll
    (e.g. Shield's "makes an attack roll against you"). Called from typed_executor.block_attack, so
    only a Factory attacker's typed attack opens this window for a typed target. The gate is now
    per-row (owner 2026-09-26), not a blanket early return, so a free Foundation trigger can still
    fire when the Reaction itself was already spent this round."""
    _expire_marks(engine)
    ranged = spec.get("range_ft") is not None and int(spec.get("range_ft") or 0) > 5
    for row in _ordered_generic_rows(engine, target.entity_id, "attacked"):
        try:
            if row.get("after") == "attack":
                continue  # "after the triggering act resolves": on_attack_resolved (audit F10)
            if not _generic_kind_ok(row, ranged=ranged, melee=not ranged) or not _can_trigger(engine, target, row):
                continue
            if not declaration_priority_ok(engine, target, attacker, row, ranged=ranged):
                continue
            if not _generic_affordable(engine, target, row) or not _generic_in_range(engine, target, attacker, row, subject=target, source=attacker):
                continue
            if not _subject_ok(engine, target, attacker, row):
                continue
            # An attack_modifier penalty against the attacker (owner 2026-09-26, e.g. Cloud-Sleeve
            # Guard: "Roll 1d6 and subtract the result from the attack roll") fires before the roll is
            # made, so it can actually reduce the pending attack_bonus rather than fake an AC change.
            penalty_effects = [e for e in row.get("effects") or []
                               if isinstance(e, dict) and e.get("type") == "attack_modifier" and e.get("applies_to") == "attacker"]
            penalty = sum(_generic_amount(engine, target, row, e) for e in penalty_effects)
            # An AC bonus lasts until the start of the reactor's next turn, as on the hit path: run through the
            # executor with the reaction's instant duration it never expired (owner 2026-09-26 manual-control check).
            ac_effects = [e for e in row.get("effects") or [] if isinstance(e, dict) and e.get("type") == "ac_bonus"]
            ac_amount = sum(_ac_amount(engine, target, row, e) for e in ac_effects if e.get("duration") != "triggering_attack")
            if not _consent(engine, row, target, "ATTACK_DECLARED", trigger={
                    "actor_id": attacker.entity_id, "target_id": target.entity_id,
                    "source_id": spec.get("source_definition_id"), "action_name": spec.get("action_name")}):
                continue  # "Ask me" (step 16): the player passed
            with _reaction_activation(engine, target, attacker, row) as permitted:
                if not permitted:
                    continue
                _open(engine, row, target, (attacker.entity_id,), "ATTACK_DECLARED")
                if not _spend_generic(engine, target, row):
                    continue
                spend_reaction(engine, target, row)
                if penalty:
                    spec["attack_bonus"] = int(spec.get("attack_bonus") or 0) - penalty
                if ac_amount:
                    engine._add_modifier(target, row["feature_id"], "armor_class", "ADD", ac_amount, "SELF", expires_on="START_OF_SELF_NEXT_TURN")
                attack_ac = [{**e, "amount": _ac_amount(engine, target, row, e)} for e in ac_effects
                             if e.get("duration") == "triggering_attack"]
                rest = [e for e in row.get("effects") or [] if not (isinstance(e, dict) and (e in penalty_effects or e in ac_effects))]
                _run_generic_effects(engine, target, attacker, row, [*attack_ac, *rest], intent,
                                     recipient=target if attack_ac else None, attack_spec=spec)
                engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                                     payload={"checkpoint": "ATTACK_DECLARED", "attack_penalty": penalty, "ac_bonus": ac_amount})
                return
        except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
            _log_bad_row(engine, target, attacker, row, exc)
    _offer_ally_attacked(engine, target, attacker, spec, intent)


def on_attack_resolved(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], intent: Any = None) -> None:
    """After an attack against a Factory fighter resolves: an "attacked" response printed as happening after the
    triggering act (Yang's Overheat Force; Astra's audit, 2026-09-26: it fired before the attack roll)."""
    if target.entity_id not in getattr(engine, "typed_actor_ids", set()) or not attacker.active:
        return
    _expire_marks(engine)
    ranged = spec.get("range_ft") is not None and int(spec.get("range_ft") or 0) > 5
    for row in _ordered_generic_rows(engine, target.entity_id, "attacked"):
        try:
            if row.get("after") != "attack" or not _generic_kind_ok(row, ranged=ranged, melee=not ranged) or not _can_trigger(engine, target, row):
                continue
            if not _generic_affordable(engine, target, row) or not _generic_in_range(engine, target, attacker, row, subject=target, source=attacker) or not _subject_ok(engine, target, attacker, row):
                continue
            if not _consent(engine, row, target, "ATTACK_RESOLVED", trigger={
                    "actor_id": attacker.entity_id, "target_id": target.entity_id,
                    "source_id": spec.get("source_definition_id"), "action_name": spec.get("action_name")}):
                continue  # "Ask me" (step 16): the player passed
            with _reaction_activation(engine, target, attacker, row) as permitted:
                if not permitted:
                    continue
                _open(engine, row, target, (attacker.entity_id,), "ATTACK_RESOLVED")
                if not _spend_generic(engine, target, row):
                    continue
                spend_reaction(engine, target, row)
                _run_generic_effects(engine, target, attacker, row, row.get("effects") or [], intent)
                engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                                     payload={"checkpoint": "ATTACK_RESOLVED"})
                return
        except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
            _log_bad_row(engine, target, attacker, row, exc)


def _last_natural_roll(engine: Any, attacker_id: str, target_id: str) -> int | None:
    """The natural d20 result of the most recent ATTACK_ROLLED event for this exact attacker/target
    pair (owner 2026-09-26): on_attack_missed is only ever called immediately after the sealed
    engine appends that event for the current attack, so the most recent match is always this one;
    natural_1 needs it, since on_attack_missed (unlike on_attack_hit) is not handed the roll."""
    for event in reversed(engine.events):
        if event.event_type == "ATTACK_ROLLED" and event.actor_id == attacker_id and target_id in event.target_ids:
            return event.payload.get("natural_result")
    return None


def _offer_ally_missed(engine: Any, target: Any, attacker: Any, spec: dict[str, Any], intent: Any = None) -> None:
    """ally_missed (owner 2026-09-26): another active fighter on the target's team may spend its own
    Reaction after the attacker's roll misses (e.g. a counterattack)."""
    ranged = spec.get("range_ft") is not None and int(spec.get("range_ft") or 0) > 5
    for bystander in _ally_candidates(engine, target):
        for row in _ordered_generic_rows(engine, bystander.entity_id, "ally_missed", attacker):
            if not _ally_row_ok(engine, bystander, attacker, target, row):
                continue  # not this creature's reaction to make (team, mark, reach), or kept for a marked creature
            try:
                if not _generic_kind_ok(row, ranged=ranged, melee=not ranged) or not _can_trigger(engine, bystander, row):
                    continue
                if not _generic_affordable(engine, bystander, row) or not _generic_in_range(engine, bystander, target, row, subject=target, source=attacker):
                    continue
                if not _consent(engine, row, bystander, "ATTACK_MISSED", trigger={
                        "actor_id": attacker.entity_id, "target_id": target.entity_id,
                        "source_id": spec.get("source_definition_id"), "action_name": spec.get("action_name")}):
                    continue  # "Ask me" (step 16): the player passed
                with _reaction_activation(engine, bystander, attacker, row, range_subject=target) as permitted:
                    if not permitted:
                        continue
                    _open(engine, row, bystander, (attacker.entity_id, target.entity_id), "ATTACK_MISSED", {"protects": target.entity_id})
                    if not _spend_generic(engine, bystander, row):
                        continue
                    spend_reaction(engine, bystander, row)
                    _run_generic_effects(engine, bystander, attacker, row, row.get("effects") or [], intent, protects=target)
                    engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=bystander.entity_id, target_ids=(attacker.entity_id,),
                                         payload={"checkpoint": "ATTACK_MISSED", "protects": target.entity_id})
                    return
            except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
                _log_bad_row(engine, bystander, attacker, row, exc)


def on_attack_missed(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], intent: Any = None) -> None:
    """Checkpoint ATTACK_MISSED (owner 2026-09-25): a generic reaction after the attacker's roll misses
    (e.g. Counter Palm). Called from typed_executor.block_attack, Factory attackers only. Also where a
    Foundation's free "gain a resource after a miss" trigger fires (owner 2026-09-26, e.g. Generate
    Mirror Trace, Generate Reed Flex): the gate is per-row, not a blanket early return, so it still
    fires when the Reaction itself was already spent this round."""
    ranged = spec.get("range_ft") is not None and int(spec.get("range_ft") or 0) > 5
    if _last_natural_roll(engine, attacker.entity_id, target.entity_id) == 1:
        for row in _ordered_generic_rows(engine, target.entity_id, "natural_1", attacker):
            if not _subject_ok(engine, target, attacker, row):
                continue  # not answerable (denied, Silenced, mark, reach), or kept for a marked creature (step 15)
            try:
                if not _generic_kind_ok(row, ranged=ranged, melee=not ranged) or not _can_trigger(engine, target, row):
                    continue
                if not _generic_affordable(engine, target, row) or not _generic_in_range(engine, target, attacker, row, subject=target, source=attacker):
                    continue
                if not _consent(engine, row, target, "ATTACK_MISSED", trigger={
                        "actor_id": attacker.entity_id, "target_id": target.entity_id,
                        "source_id": spec.get("source_definition_id"), "action_name": spec.get("action_name")}):
                    continue  # "Ask me" (step 16): the player passed
                with _reaction_activation(engine, target, attacker, row) as permitted:
                    if not permitted:
                        continue
                    _open(engine, row, target, (attacker.entity_id,), "ATTACK_MISSED", {"natural_1": True})
                    if not _spend_generic(engine, target, row):
                        continue
                    spend_reaction(engine, target, row)
                    _run_generic_effects(engine, target, attacker, row, row.get("effects") or [], intent)
                    engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                                         payload={"checkpoint": "ATTACK_MISSED", "natural_1": True})
                    break
            except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
                _log_bad_row(engine, target, attacker, row, exc)
    for row in _ordered_generic_rows(engine, target.entity_id, "missed", attacker):
        try:
            if not _generic_kind_ok(row, ranged=ranged, melee=not ranged) or not _can_trigger(engine, target, row):
                continue
            if not _generic_affordable(engine, target, row) or not _generic_in_range(engine, target, attacker, row, subject=target, source=attacker):
                continue
            if not _subject_ok(engine, target, attacker, row):
                continue
            if not _consent(engine, row, target, "ATTACK_MISSED", trigger={
                    "actor_id": attacker.entity_id, "target_id": target.entity_id,
                    "source_id": spec.get("source_definition_id"), "action_name": spec.get("action_name")}):
                continue  # "Ask me" (step 16): the player passed
            with _reaction_activation(engine, target, attacker, row) as permitted:
                if not permitted:
                    continue
                _open(engine, row, target, (attacker.entity_id,), "ATTACK_MISSED")
                if not _spend_generic(engine, target, row):
                    continue
                spend_reaction(engine, target, row)
                _run_generic_effects(engine, target, attacker, row, row.get("effects") or [], intent)
                engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                                     payload={"checkpoint": "ATTACK_MISSED"})
                break
        except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
            _log_bad_row(engine, target, attacker, row, exc)
    _offer_ally_missed(engine, target, attacker, spec, intent)


# ---------------------------------------------------------------- technique_targets / technique_used
def _offer_technique_reaction(engine: Any, reactor: Any, actor: Any, kind: str, numbers: dict[str, Any], intent: Any = None,
                              spoken: bool = False, incoming: dict[str, Any] | None = None) -> None:
    """One technique_targets/technique_used row (owner 2026-09-26): a penalty or disadvantage against
    the ability about to run, an AC or save bonus for the reactor, or a counter (damage to the user).
    ``numbers`` is the caller's own per-activation copy of typed["numbers"] (combat/typed_executor.py's
    resolve_typed), so mutating attack_bonus/save_dc here never leaks into the character's other actions.
    ``incoming`` is that ability's own typed data, used to tell a hostile use from a beneficial one: a row that
    answers a hostile effect (combat/typed_reactions._answers_a_hostile_effect) stays closed when what arrived
    was a benefit (hunt 74). Omitted, the row is judged as before."""
    adverse = incoming is None or _incoming_is_adverse(actor, reactor, incoming)
    for row in _ordered_generic_rows(engine, reactor.entity_id, kind):
        try:
            if kind == "technique_targets" and not adverse and _answers_a_hostile_effect(row):
                continue  # a benefit aimed at you is not an attack: a reflection or a counter has nothing to answer
            if kind == "technique_used" and int(numbers.get("_cp_cost") or 0) < int(row.get("min_cp_cost") or 0):
                continue  # CP thresholds exclude payment solely in other resources.
            if kind == "technique_used" and (bool(row.get("allies_only")) != (reactor.team_id == actor.team_id)
                                             or (row.get("requires_hearing_technique") and not spoken)
                                             or int(row.get("min_cost") or 0) > int(numbers.get("_cost") or 0)):
                continue
            if not _can_trigger(engine, reactor, row) or not _generic_affordable(engine, reactor, row) or not _generic_in_range(engine, reactor, actor, row):
                continue
            if not _subject_ok(engine, reactor, actor, row):
                continue
            effects = row.get("effects") or []
            penalty_effects = [e for e in effects if isinstance(e, dict) and e.get("type") == "attack_modifier" and e.get("applies_to", "attacker") != "self"]
            # A bonus to "the saving throw"/"your save" (owner 2026-09-26, the same idiom on_save
            # already reads for a generic "save" row): applied as a DC reduction on this activation's
            # own numbers, since the ability's own save roll has not happened yet at this checkpoint.
            save_bonus_effects = [e for e in effects if isinstance(e, dict) and e.get("type") == "attack_modifier" and e.get("applies_to") == "self"
                                  and "sav" in str(e.get("on") or e.get("evidence") or "").lower()]
            ac_effects = [e for e in effects if isinstance(e, dict) and e.get("type") == "ac_bonus"]
            disadvantage = any(isinstance(e, dict) and e.get("type") == "disadvantage" for e in effects)
            handled = [*penalty_effects, *save_bonus_effects, *ac_effects]
            penalty = sum(_generic_amount(engine, reactor, row, e) for e in penalty_effects)
            save_bonus = sum(_generic_amount(engine, reactor, row, e) for e in save_bonus_effects)
            ac_amount = sum(_ac_amount(engine, reactor, row, e) for e in ac_effects)
            if not _consent(engine, row, reactor, "TECHNIQUE_DECLARED", trigger={
                    "actor_id": actor.entity_id, "target_id": reactor.entity_id}):
                continue  # "Ask me" (step 16): the player passed
            with _reaction_activation(engine, reactor, actor, row) as permitted:
                if not permitted:
                    continue
                _open(engine, row, reactor, (actor.entity_id,), "TECHNIQUE_DECLARED", {"kind": kind})
                if not _spend_generic(engine, reactor, row):
                    continue
                spend_reaction(engine, reactor, row)
                if penalty:
                    numbers["attack_bonus"] = int(numbers.get("attack_bonus") or 0) - penalty
                if save_bonus:
                    numbers["save_dc"] = max(0, int(numbers.get("save_dc") or 0) - save_bonus)
                if ac_amount:
                    engine._add_modifier(reactor, row["feature_id"], "armor_class", "ADD", ac_amount, "SELF", expires_on="START_OF_SELF_NEXT_TURN")
                if disadvantage:
                    engine._add_modifier(actor, row["feature_id"], "attack_mode", "SET", "DISADVANTAGE", "NEXT_ATTACK", expires_on="CONSUMED")
                rest = [e for e in effects if e not in handled and not (isinstance(e, dict) and e.get("type") == "disadvantage")]
                if row.get("after") == "event":
                    rest = [{"type": "after_technique", "effects": rest}]
                _run_generic_effects(engine, reactor, actor, row, rest, intent)
                engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=reactor.entity_id, target_ids=(actor.entity_id,),
                                     payload={"checkpoint": "TECHNIQUE_DECLARED", "kind": kind, "attack_penalty": penalty,
                                              "save_bonus": save_bonus, "ac_bonus": ac_amount, "disadvantage": disadvantage})
                if not row.get("free"):
                    return  # a free response (no Reaction spent) does not stop the others from answering the same technique
        except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
            _log_bad_row(engine, reactor, actor, row, exc)


def on_own_event(engine: Any, actor: Any, other: Any | None, kind: str, *, ranged: bool | None = None,
                 accept: Any = None, source_id: str | None = None, action_name: str | None = None) -> None:
    """The character's own act (owner 2026-09-26: "we need the different resources to be generated"): "after you
    hit", "when you reduce a creature to 0 HP", "when a creature fails a saving throw against you" -- mostly a
    Sphere's or Foundation's resource generation. Every eligible free row fires (each has its own once-per
    limit); at most one row that spends the Reaction does."""
    if actor is None or actor.entity_id not in getattr(engine, "typed_actor_ids", set()):
        return
    from .typed_executor import bears_mark, run_watches

    _expire_marks(engine)
    run_watches(engine, actor, other, kind)  # later gains registered by an ability's use (Demon Mark's Devoured Essence)
    reacted = False
    for row in _ordered_generic_rows(engine, actor.entity_id, kind):
        try:
            if (reacted and not row.get("free")) or not _can_trigger(engine, actor, row) or not _generic_affordable(engine, actor, row):
                continue
            if ranged is not None and not _generic_kind_ok(row, ranged=ranged, melee=not ranged):
                continue
            if accept is not None and not accept(row):
                continue  # the kind's own limit (R3-R5: which action, which ability, which roll)
            if not _generic_in_range(engine, actor, other, row) or not _subject_ok(engine, actor, other, row):
                continue
            if row.get("requires_self_mark") and not bears_mark(actor, actor.entity_id, row["requires_self_mark"]):
                continue  # e.g. Yang's Complete Force: only while you bear your own Kindled Mark
            target_ids = (other.entity_id,) if other is not None else ()
            if not _consent(engine, row, actor, kind.upper(), trigger={
                    "actor_id": actor.entity_id, "target_id": (other or actor).entity_id,
                    "source_id": source_id, "action_name": action_name or row.get("source_name"),
                    "trigger_kind": kind}):
                continue  # "Ask me" (step 16): the player passed
            # Named free follow-ups ride the original ability. Other free
            # reactions still create an independent causal activation.
            with _reaction_activation(engine, actor, other, row,
                                      same_activation=kind == "own_ability" and bool(row.get("free"))) as permitted:
                if not permitted:
                    continue
                _open(engine, row, actor, target_ids, kind.upper())
                if not _spend_generic(engine, actor, row):
                    continue
                if not row.get("free"):
                    spend_reaction(engine, actor, row)
                    reacted = True
                _run_generic_effects(engine, actor, other, row, row.get("effects") or [])
                engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=actor.entity_id, target_ids=target_ids,
                                     payload={"checkpoint": kind.upper()})
        except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
            _log_bad_row(engine, actor, other, row, exc)


# ---------------------------------------------------------------- step 8: other creatures' events (owner 2026-09-26)
# Effect types that answer the ability aimed at the reactor by undoing it and turning it back on whoever aimed
# it. They are the clearest "you are being attacked" responses there are, and they are named here as a kind
# rather than per ability: a reflection (tianxia.talent.talismans.talisman_reflection, "on a success, redirect
# the effect toward its source") does nothing sensible to a heal an ally just cast on you.
_ANSWERS_A_HOSTILE_EFFECT = {"negate_attack"}


def _answers_a_hostile_effect(row: dict[str, Any]) -> bool:
    """Whether a reaction row is written to answer an ability aimed to HURT the reactor: it acts against the
    creature that used the ability (_stance "harmful": a penalty, a condition, damage), or it undoes the
    incoming effect and turns it back on its source. Such a row is the printed reading of "you are being
    targeted by a hostile effect" and must stay closed when what arrived is a benefit instead (hunt 74: an
    ally's Healing Talisman is a single-target supernatural effect, but an ally's heal is not an attack, and
    answering it spent the recipient's Reaction, 5 CP and a prepared talisman to redirect the heal at the
    healer). A row that only helps the reactor -- an AC bonus, resistance, a free escape -- is not one of
    these and still answers."""
    effects = _walk_effects(row.get("effects") or [])
    return any(effect.get("type") in _ANSWERS_A_HOSTILE_EFFECT for effect in effects) or _stance(row) == "harmful"


def _incoming_is_adverse(actor: Any, target: Any, typed: dict[str, Any]) -> bool:
    """Whether the ability about to run is aimed to hurt ``target`` -- the question every "you are being
    targeted by a hostile effect" reading turns on. Another team's ability is hostile by default; an ally's is
    hostile only when it actually carries harm at its recipient, so a heal or a buff cast on you by an ally is
    not an attack. Effects aimed at the caster or at allies are not harm toward the target, and a reviewed
    "stance": "helpful" effect is the price of surviving, not an attack (the same idiom _stance honours).
    A once-per-creature mark records benefit usage; it does not impose harm on the recipient."""
    from .area_recipients import (scoped_area, harmful_area_subject_allowed,
                                 effect_recipient_scope, harmful_effect_scope)
    area = scoped_area(typed.get("area") or {}, typed.get("effects"), typed=typed)
    if area.get("size_ft"):
        def adverse(effects, inherited=None, saving_throw=False, inherited_permission=None):
            for effect in effects or ():
                scope = effect_recipient_scope(effect, inherited)
                # Hash the original compiled payload: rewriting applies_to loses
                # its sealed permission. Children inherit resolved permission,
                # separately from the raw recipient token (as execution does).
                permission = harmful_effect_scope(area, effect, inherited=inherited_permission)
                # A branch cannot reach somebody excluded by its enclosing
                # save/attack, even if a child declares a wider area scope.
                if scope == "self" or effect.get("stance") == "helpful" or \
                        not harmful_area_subject_allowed(actor, target, area, effect,
                                                         inherited=permission or scope):
                    continue
                harm = classify_effect(effect, saving_throw=saving_throw, recursive=False)
                if harm is True or (harm is None and not list(effect_children(effect)) and
                                    actor.team_id != target.team_id):
                    return True
                if adverse(effect_children(effect), scope, saving_throw or effect.get("type") == "save",
                           permission):
                    return True
            return False
        return adverse(typed.get("effects"))
    if getattr(actor, "team_id", None) != getattr(target, "team_id", None):
        return True
    return any(classify_effect(effect) is True
               for effect in _walk_effects(typed.get("effects") or [])
               if effect.get("applies_to") not in ("self", "ally", "allies")
               and effect.get("stance") != "helpful"
               and not (effect.get("type") == "mark" and effect.get("once_per_creature")))


# R3-R5 (owner 2026-09-26): whose event each new moment answers -- an enemy's (it enters your range, takes an action, uses a
# reaction, starts its turn near you), an ally's (it starts its turn in your aura, misses, grabs a foe), or anyone's.
_SUBJECT_RELATION = {"enters_range": "hostile", "leaves_reach": "hostile", "creature_acted": "hostile", "reaction_used": "hostile",
                     "creature_turn_start": "hostile", "ally_turn_start": "ally", "ally_grapple_succeeded": "ally", "became_hidden": "hostile",
                     "creature_attack_missed": "ally", "creature_nat": "any", "multi_damage": "any"}


def _stance(row: dict[str, Any]) -> str:
    """"harmful" (acts against the triggering creature), "helpful" (acts for it) or "neutral" (only on the reactor,
    e.g. a resource gain)."""
    # An effect with no stated subject acts on the reactor unless it is a harmful kind (damage, a condition, a save).
    about_them = [e for e in _walk_effects(row.get("effects") or [])
                  if e.get("type") not in ("gain_resource", "spend_resource")
                  and (e.get("applies_to") not in (None, "self") or (e.get("applies_to") is None and classify_effect(e) is True))]
    if not about_them:
        return "neutral"
    # "stance": "helpful" reads a harmful-looking row as part of what the reaction does FOR the triggering creature (Life-Line Stitch's
    # Prone and Restrained thread are the price of surviving; riders lane 4, 2026-09-29).
    return "harmful" if any(classify_effect(e) is True for e in about_them) else "helpful"


def on_creature_event(engine: Any, subject: Any, kind: str, *, moved_ft: int = 0, accept: Any = None, target: Any = None,
                      source_id: str | None = None) -> None:
    """Another creature moved willingly, dropped to 0 HP, failed or succeeded on a save, or regained HP: each Factory
    fighter with a matching reaction in range may answer -- against a hostile creature if the reaction harms it,
    for itself or an ally if it helps, for anyone if it only acts on the reactor. A move answers enemies only."""
    if subject is None:
        return
    if kind == "moved":
        from . import motion

        motion.after_move(engine, subject, moved_ft)  # Afterimage
    dispatch_creature_reactions(engine, subject, kind, moved_ft=moved_ft, accept=accept,
                                target=target, source_id=source_id)


def dispatch_creature_reactions(engine: Any, subject: Any, kind: str, *, moved_ft: int = 0,
                               accept: Any = None, target: Any = None, source_id: str | None = None) -> None:
    """Dispatch matching reaction rows without processing movement benefits.

    Supplemental movement notifications use this when the movement producer
    owns benefit processing. Ordinary events use on_creature_event instead.
    The optional accept(row, watcher) filter limits rows, not global benefits.
    """
    if subject is None:
        return
    from .typed_executor import bears_mark

    _expire_marks(engine)
    for watcher in list(engine.state.actors.values()):
        if not watcher.active or watcher.entity_id not in getattr(engine, "typed_actor_ids", set()):
            continue
        itself = watcher.entity_id == subject.entity_id
        hostile = watcher.team_id != subject.team_id
        reacted = False
        for row in _ordered_generic_rows(engine, watcher.entity_id, kind):
            try:
                if (reacted and not row.get("free")) or not _can_trigger(engine, watcher, row) or not _generic_affordable(engine, watcher, row):
                    continue
                if (itself and not row.get("includes_self")) or (row.get("allies_only") and hostile):
                    continue  # "you or a willing creature ...": the reactor's own event only when the reading names it
                if kind == "moved" and row.get("teleport_only"):
                    continue  # walking is not a teleport; no teleport moment yet
                relation = _SUBJECT_RELATION.get(kind, "stance")
                if relation == "stance":
                    stance = _stance(row)
                    if row.get("subject_relation") == "any":
                        pass
                    elif (kind == "moved" and not hostile) or (stance == "harmful" and not hostile) or (stance == "helpful" and hostile):
                        continue
                elif (relation == "hostile" and not hostile and not itself) or (relation == "ally" and hostile):
                    continue
                measured_ft = moved_ft
                if kind == "moved" and row.get("movement_measure") == "turn":
                    from .ext.movement_clock import willing_distance
                    measured_ft = willing_distance(engine, subject)
                if kind == "moved" and measured_ft < int(row.get("min_move_ft") or 0):
                    continue  # "moves at least 30 feet"
                if accept is not None and not accept(row, watcher):
                    continue  # the kind's own limit (R3-R5)
                in_range = kind in ("enters_range", "leaves_reach") or _generic_in_range(engine, watcher, subject, row)
                if not in_range or not _subject_ok(engine, watcher, subject, row):
                    continue
                if row.get("requires_self_mark") and not bears_mark(watcher, watcher.entity_id, row["requires_self_mark"]):
                    continue
                answered = getattr(engine, "_typed_answered_reaction", None) or {}
                if not _consent(engine, row, watcher, kind.upper(), trigger={
                        "actor_id": subject.entity_id, "target_id": (target or subject).entity_id,
                        "source_id": source_id,
                        "trigger_kind": kind,
                        "reaction_name": (answered.get("row") or {}).get("name") if kind == "reaction_used" else None}):
                    continue  # "Ask me" (step 16): the player passed
                with _reaction_activation(engine, watcher, target if target is not None else subject, row, range_subject=subject) as permitted:
                    if not permitted:
                        continue
                    _open(engine, row, watcher, (subject.entity_id,), kind.upper())
                    if not _spend_generic(engine, watcher, row):
                        continue
                    if not row.get("free"):
                        spend_reaction(engine, watcher, row)
                        reacted = True
                    _run_generic_effects(engine, watcher, target if target is not None else subject, row, row.get("effects") or [])
                    engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=watcher.entity_id, target_ids=(subject.entity_id,),
                                         payload={"checkpoint": kind.upper()})
            except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
                _log_bad_row(engine, watcher, subject, row, exc)


# ---------------------------------------------------------------- R3-R5 moments (owner 2026-09-26, "i want all the reactions usable")
def on_action_completed(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    """After an Action or Bonus Action resolves: "a marked creature completes an Action, Bonus Action, Reaction ..."
    (creature_acted) and the actor's own "whenever you take the Dodge action" (own_action)."""
    from .ext.setting_choices import is_setting_action

    if is_setting_action(engine.action_catalog.get(source_definition_id)):
        return  # the sealed caller transports free settings as ACTION candidates
    on_creature_event(engine, actor, "creature_acted", accept=lambda row, watcher: not row.get("economies") or economy in row["economies"])
    from . import motion

    motion.after_action(engine, actor, economy, source_definition_id)  # Coordinated Movement, Gather the Current
    action = {"system:combat.dodge": "dodge"}.get(source_definition_id)
    if action:
        on_own_event(engine, actor, None, "own_action", accept=lambda row: row.get("action") == action)
    from .ext import run
    run("action_completed", engine, actor, economy, source_definition_id)


def _roll_limits_ok(row: dict[str, Any], roll_kind: str, ability: str | None, conditions: set[str]) -> bool:
    if row.get("rolls") and roll_kind not in row["rolls"]:
        return False
    if roll_kind == "save" and row.get("save_abilities") and str(ability or "").lower()[:3] not in row["save_abilities"]:
        return False
    return not row.get("conditions") or bool(set(row["conditions"]) & conditions)


def on_d20_pending(engine: Any, roller: Any, roll_kind: str, *, ability: str | None = None, conditions: set[str] | None = None,
                   source_id: str | None = None) -> dict[str, Any]:
    """creature_d20 before the roll (R4: "a creature within 60 feet is about to resolve an attack roll or saving throw"): each
    Factory fighter with such a row in range may answer once. An enemy's roll takes the reaction's penalty and Disadvantage,
    an ally's (or the reactor's own) its bonus and Advantage. Returns {"bonus": int, "modes": [..]} for the roll."""
    result: dict[str, Any] = {"bonus": 0, "modes": []}
    conditions = set(conditions or ())
    typed = getattr(engine, "typed_actor_ids", set())
    for watcher in list(engine.state.actors.values()):
        if not watcher.active or watcher.entity_id not in typed:
            continue
        itself, hostile = watcher.entity_id == roller.entity_id, watcher.team_id != roller.team_id
        for row in _ordered_generic_rows(engine, watcher.entity_id, "creature_d20"):
            try:
                if row.get("outcome") or not _roll_limits_ok(row, roll_kind, ability, conditions):
                    continue
                if (itself and not row.get("includes_self")) or (row.get("allies_only") and hostile):
                    continue
                if not row.get("allies_only") and _stance(row) == "harmful" and not hostile:
                    continue  # a penalty or a forced save is for an enemy's roll
                if not _can_trigger(engine, watcher, row) or not _generic_affordable(engine, watcher, row):
                    continue
                if not _generic_in_range(engine, watcher, roller, row) or not _subject_ok(engine, watcher, roller, row):
                    continue
                if not _consent(engine, row, watcher, "D20_PENDING", trigger={
                        "actor_id": roller.entity_id, "target_id": roller.entity_id,
                        "source_id": source_id, "roll_kind": roll_kind, "save_ability": ability}):
                    continue
                effects = row.get("effects") or []
                shaping = [e for e in effects if isinstance(e, dict) and e.get("type") in ("attack_modifier", "advantage", "disadvantage", "roll_die")]
                with _reaction_activation(engine, watcher, roller, row) as permitted:
                    if not permitted:
                        continue
                    _open(engine, row, watcher, (roller.entity_id,), "D20_PENDING", {"roll": roll_kind})
                    if not _spend_generic(engine, watcher, row):
                        continue
                    spend_reaction(engine, watcher, row)
                    for effect in shaping:
                        if effect["type"] == "roll_die":  # Twist of Fate: add or subtract the Fate Die, whichever helps
                            from .gate2_runtime_models import DiceSpec

                            # The Fate Die by CL, and at least any fate_die_min a condition gives (rider lane 9: Fate-Sovereign Incarnation's d10).
                            from .typed_executor import condition_rules

                            cl = int((row.get("numbers") or {}).get("cl") or 1)
                            sides = next((int(v) for lo, hi, v in effect.get("die_by_cl") or [] if lo <= cl <= hi), int(effect.get("die") or 6))
                            sides = max([sides, *(int(rule["fate_die_min"]) for rule in condition_rules(watcher) if rule.get("fate_die_min"))])
                            die = engine.roller.roll(DiceSpec(count=1, sides=sides, modifier=0), actor_id=watcher.entity_id, reason="REACTION_DIE")
                            engine._record_roll(die)
                            result["bonus"] += -die.total if hostile else die.total
                        elif effect["type"] == "attack_modifier":
                            amount = _generic_amount(engine, watcher, row, effect)
                            result["bonus"] += -amount if hostile else amount
                        else:
                            result["modes"].append("DISADVANTAGE" if hostile else "ADVANTAGE")
                    _run_generic_effects(engine, watcher, roller, row, [e for e in effects if e not in shaping])
                    engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=watcher.entity_id, target_ids=(roller.entity_id,),
                                         payload={"checkpoint": "D20_PENDING", "roll": roll_kind, "bonus": result["bonus"], "modes": list(result["modes"])})
                    break
            except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
                _log_bad_row(engine, watcher, roller, row, exc)
    return result


def after_attack_miss(engine: Any, attacker: Any, *, melee: bool | None = None, source_id: str | None = None) -> None:
    """A real creature attack missed, including concealment without a d20.

    Rolled misses arrive through after_d20; unrolled misses call this directly.
    Canceled attacks and empty remembered squares do not dispatch this event.
    """
    on_creature_event(engine, attacker, "creature_attack_missed",
                      source_id=source_id,
                      accept=lambda row, watcher: melee is None or _generic_kind_ok(row, ranged=not melee, melee=bool(melee)))


def after_d20(engine: Any, roller: Any, roll_kind: str, *, success: bool, natural: int | None, other: Any | None,
              ability: str | None = None, conditions: set[str] | None = None, melee: bool | None = None,
              source_id: str | None = None) -> None:
    """After an attack roll or saving throw (R4): creature_d20 rows with an outcome ("succeeds on", "misses ... fails"),
    natural 1s and 20s (creature_nat), an ally's missed attack (creature_attack_missed), the roller's own failed d20
    (own_d20_fail) and own successful save (own_save_succeeded)."""
    conditions = set(conditions or ())

    def outcome_ok(row: dict[str, Any], watcher: Any) -> bool:
        wanted = row.get("outcome")
        return bool(wanted) and _roll_limits_ok(row, roll_kind, ability, conditions) and (
            wanted == "any_after" or (wanted == "success") == success)

    on_creature_event(engine, roller, "creature_d20", accept=outcome_ok)
    if natural in (1, 20):
        on_creature_event(engine, roller, "creature_nat", accept=lambda row, watcher: natural in (row.get("natural") or (1, 20)))
    if roll_kind == "attack" and not success:
        after_attack_miss(engine, roller, melee=melee, source_id=source_id)
    if not success:
        on_own_event(engine, roller, other, "own_d20_fail")
    elif roll_kind == "save":
        on_own_event(engine, roller, other, "own_save_succeeded",
                     accept=lambda row: _roll_limits_ok({**row, "rolls": []}, "save", ability, conditions))


def on_turn_start(engine: Any, actor: Any) -> None:
    """A turn begins (R5): "a hostile creature bearing your mark begins its turn within 60 feet" (creature_turn_start), "an
    ally begins its turn inside the aura" (ally_turn_start), "when you begin your turn grappling" (own_turn_start); on the
    first turn of the fight, "initiative is rolled" for every Factory fighter."""
    from .paid_relocation import preserve_pending
    preserve_pending(engine, "_typed_roll_outcome")
    preserve_pending(engine, "_typed_negated")
    engine._typed_roll_outcome, engine._typed_negated = {}, set()  # nothing decided for a roll carries across turns (R6)
    from . import ext, zones

    # Turn-boundary decisions must propagate the table's player-choice pause.
    # Observational event/turn hooks deliberately swallow ordinary exceptions.
    ext.run_strict("turn_start_choice", engine, actor)
    zones.on_turn_start(engine, actor)  # zones whose rounds ran out end; starting a turn inside one (owner 2026-09-27)
    if engine.state.round_number == 1 and engine.state.current_slot_index == 0 and actor.turns_started == 1:
        for fighter in list(engine.state.actors.values()):
            if fighter.turn_flags.get("once_per_turn:_round_initiative_checkpoint_handled") is not None:
                continue
            on_own_event(engine, fighter, None, "initiative")
    on_creature_event(engine, actor, "creature_turn_start")
    on_creature_event(engine, actor, "ally_turn_start")
    grappling = any(c.condition_id.endswith(".grappled") and c.source_actor_id == actor.entity_id
                    for other in engine.state.actors.values() for c in other.conditions.values())
    on_own_event(engine, actor, None, "own_turn_start", accept=lambda row: not row.get("grappling") or grappling)


def on_moved_geometry(engine: Any, mover: Any, start: Any, end: Any, *, zones_handled: bool = False) -> None:
    """After a willing move (R5): "a hostile creature enters a space within 30 feet of you or an ally" (enters_range; with
    ``toward`` it must close at least min_move_ft on the reactor) and "leaves your reach" (leaves_reach)."""
    square = engine.grid.square_size_ft

    def feet(a: Any, b: Any) -> int:
        return engine.grid.distance_ft(a, b)

    def entered(row: dict[str, Any], watcher: Any) -> bool:
        radius = int(row.get("range_ft") or 5)
        anchors = [watcher] if row.get("self_only") else [watcher, *[a for a in engine.state.actors.values()
                                                                    if a.active and a.team_id == watcher.team_id and a is not watcher]]
        if row.get("toward"):
            return feet(start, watcher.position) - feet(end, watcher.position) >= int(row.get("min_move_ft") or square)
        return any(feet(start, a.position) > radius >= feet(end, a.position) for a in anchors)

    def left(row: dict[str, Any], watcher: Any) -> bool:
        reach = int(opportunity_reach(engine, watcher) or 5)
        return feet(start, watcher.position) <= reach < feet(end, watcher.position)

    from . import zones

    zones.on_moved(engine, mover, start, end, triggers=not zones_handled)
    if not mover.active or engine.state.terminal_result is not None:
        return
    # The range check in on_creature_event is against where the mover ended; entering and leaving are decided here.
    on_creature_event(engine, mover, "enters_range", accept=lambda row, watcher: entered({**row}, watcher))
    on_creature_event(engine, mover, "leaves_reach", accept=left)


def on_grapple_outcome(engine: Any, grappler: Any, target: Any, grabbed: bool) -> None:
    """A Grapple or Shove resolved (R5): "when one creature fails to Grapple you" (grapple_failed) and "when one Tame
    Creature or Bonded Companion succeeds on a Grapple or Shove, make one weapon attack against the same target"
    (ally_grapple_succeeded; the grappler's allies answer against the grabbed creature)."""
    if grabbed:
        on_creature_event(engine, grappler, "ally_grapple_succeeded", target=target,
                          accept=lambda row, watcher: watcher.team_id == grappler.team_id)
    else:
        on_own_event(engine, target, grappler, "grapple_failed")


def after_technique(engine: Any, actor: Any, damaged: set[str]) -> None:
    """A typed ability finished (R5): "a creature within 120 feet deals damage to two or more creatures with the same
    effect" (multi_damage)."""
    if len(damaged) >= 2:
        on_creature_event(engine, actor, "multi_damage")


def _spoken(typed: dict[str, Any]) -> bool:
    """Whether the ability that just started is one a creature speaks, chants or sings: its targets
    must hear it (``requires_hearing``, the parsed "a creature within 30 feet can hear you"), or it
    needs its user's own voice (combat/rules/speech.json). Read from the compiled row, so no
    ability id appears here."""
    from . import speech

    if typed.get("requires_hearing"):
        return True
    return speech.record_needs_voice(str(typed.get("option_of") or typed.get("source") or ""),
                                     str(typed.get("option_label") or ""))


def on_technique_start(engine: Any, actor: Any, targets: list[Any], typed: dict[str, Any], intent: Any = None) -> None:
    """Checkpoint TECHNIQUE_DECLARED (owner 2026-09-26): before a typed, non-weapon ability's own
    effects run (combat/typed_executor.py's resolve_typed), offer technique_targets reactions to each
    of its targets and technique_used reactions to eligible Factory fighters, including targets,
    within THEIR OWN row's range of the user. Target-specific responses have priority; the shared
    row checks still enforce Reaction availability, costs and free-response limits in both categories.
    Does not cover a weapon/unarmed attack (resolve_typed's caller already filters
    those out) or the actor's own targeting choices beyond what typed_executor already resolved."""
    numbers = typed.setdefault("numbers", {})
    seen: set[str] = set()
    for target in targets:
        # A caster is not "targeted by" the effect it chose itself: a self-cast heal or buff must not ask its own
        # user to answer a reaction about being targeted (hunt 74: Healing Talisman on self opened Talisman
        # Reflection, spending a Reaction, 5 CP and a prepared talisman to redirect a heal toward its own
        # source). The same guard the technique_used loop below applies to the actor.
        if target is None or target.entity_id in seen or target.entity_id == actor.entity_id \
                or target.entity_id not in getattr(engine, "typed_actor_ids", set()):
            continue
        seen.add(target.entity_id)
        _offer_technique_reaction(engine, target, actor, "technique_targets", numbers, intent, incoming=typed)
    for other in engine.state.actors.values():
        if not other.active or other.entity_id == actor.entity_id:
            continue
        if other.entity_id not in getattr(engine, "typed_actor_ids", set()):
            continue
        # An ally's technique only for a reading that names allies ("a willing creature within 30 feet activates ..."),
        # a spoken one only if its targets must hear (owner 2026-09-26 readings) or if the ability itself needs its
        # user's own voice (a shouted command, a chant, a verbal component: combat/rules/speech.json), which is what
        # "speaks a command word, uses a Voice talent, casts a spell with a verbal component" names.
        _offer_technique_reaction(engine, other, actor, "technique_used", numbers, intent, spoken=_spoken(typed))


# ---------------------------------------------------------------- condition_gained
def _movement_reduction(effect: dict[str, Any]) -> int:
    """"Reduce that movement by 10 feet" (typed as a forced_movement effect: its distance, or its flat as a negative)."""
    return abs(int(effect.get("flat") or 0)) or int(effect.get("distance_ft") or 0)


def on_forced_movement(engine: Any, mover: Any, source: Any | None, distance_ft: int) -> int:
    """Checkpoint FORCED_MOVEMENT (owner 2026-09-26, R2: "forced movement will be something important ... the throws and
    pushes"): before a typed push or pull moves ``mover``, its own forced_moved reaction (and a "you or an ally" row), then
    a Factory ally's ally_forced_moved reaction within its range, may answer. Each reactor answers once; a forced_movement
    effect reduces the distance, every other effect runs. Returns the distance left."""
    _expire_marks(engine)
    typed = getattr(engine, "typed_actor_ids", set())
    remaining = distance_ft
    from . import ext

    if ext.has("forced_distance"):  # a standing cut, no Reaction (rider lane 9: Mountain-Rooted Rim's "reduce forced movement ... by 10 feet")
        remaining = max(0, remaining - sum(int(cut or 0) for cut in ext.run("forced_distance", engine, mover, source, remaining)))
    offers = [(mover, "forced_moved")] if mover.entity_id in typed else []
    offers += [(other, "ally_forced_moved") for other in _ally_candidates(engine, mover)]
    for reactor, kind in offers:
        if remaining <= 0:
            break
        for row in _ordered_generic_rows(engine, reactor.entity_id, kind):
            try:
                ally = kind == "ally_forced_moved"
                if ally and not _ally_row_ok(engine, reactor, source, mover, row):
                    continue
                if not ally and not _subject_ok(engine, reactor, source, row):
                    continue
                if not _can_trigger(engine, reactor, row) or not _generic_affordable(engine, reactor, row):
                    continue
                if ally and not _generic_in_range(engine, reactor, mover, row):
                    continue
                if not _consent(engine, row, reactor, "FORCED_MOVEMENT", trigger={
                        "actor_id": getattr(source, "entity_id", None), "target_id": mover.entity_id,
                        "affected_id": mover.entity_id,
                        "source_id": getattr(engine, "_active_action_source_id", None)}):
                    continue  # "Ask me" (step 16): the player passed
                with _reaction_activation(engine, reactor, mover if ally else source, row, range_subject=mover) as permitted:
                    if not permitted:
                        continue
                    _open(engine, row, reactor, (mover.entity_id,), "FORCED_MOVEMENT", {"distance_ft": remaining})
                    if not _spend_generic(engine, reactor, row):
                        continue
                    spend_reaction(engine, reactor, row)
                    effects = row.get("effects") or []
                    reduction = sum(_movement_reduction(e) for e in effects if isinstance(e, dict) and e.get("type") == "forced_movement")
                    before, remaining = remaining, max(0, remaining - reduction)
                    _run_generic_effects(engine, reactor, source, row,
                                         [e for e in effects if not (isinstance(e, dict) and e.get("type") == "forced_movement")],
                                         recipient=mover if row.get("kind") == "ally_forced_moved" else None)
                    engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=reactor.entity_id, target_ids=(mover.entity_id,),
                                         payload={"checkpoint": "FORCED_MOVEMENT", "distance_before": before, "distance_after": remaining})
                    break
            except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
                _log_bad_row(engine, reactor, source, row, exc)
    return remaining


def offer_condition_gained(engine: Any, subject: Any, source_actor: Any | None, condition_name: str, *, applied: bool = False) -> bool:
    """Generic before/after condition seam: typed after="condition_applied" rows
    run from the executor's condition_applied hook; prevention markers always
    answer CONDITION_ABOUT_TO_APPLY. No marker retains the legacy moment.
    A row whose own
    effects include the synthetic "prevent_condition" marker (this vocabulary has no printed-text
    equivalent to automate "end/resist the condition" against, so the compiler never produces one from
    real authority text; it exists so an owner-authored row can opt in) stops the condition from being
    applied; every other effect on the row still runs."""
    checkpoint = "CONDITION_APPLIED" if applied else "CONDITION_ABOUT_TO_APPLY"

    def at_this_moment(row):
        prevents = any(isinstance(e, dict) and e.get("type") == "prevent_condition" for e in row.get("effects") or [])
        return applied == (row.get("after") == "condition_applied" and not prevents)

    own = _ordered_generic_rows(engine, subject.entity_id, "condition_gained") if subject.entity_id in getattr(engine, "typed_actor_ids", set()) else []
    for row in own:
        if not at_this_moment(row):
            continue
        if not _subject_ok(engine, subject, source_actor, row):
            continue  # not answerable (denied, Silenced, mark, reach), or kept for a marked creature (step 15)
        try:
            if not _can_trigger(engine, subject, row) or not _generic_affordable(engine, subject, row) or not _generic_condition_ok(row, condition_name):
                continue
            effects = row.get("effects") or []
            prevents = any(isinstance(e, dict) and e.get("type") == "prevent_condition" for e in effects)
            rest = [e for e in effects if not (isinstance(e, dict) and e.get("type") == "prevent_condition")]
            other = source_actor
            if row.get("reaction_target") == "creature_in_reach":
                from .ext.reaction_targets import choose_target
                other = choose_target(engine, subject, row, checkpoint, source_actor, condition_name)
                if other is None:
                    continue
                if not reaction_permitted_against(engine, subject, other):
                    continue
            target_ids = (other.entity_id,) if other is not None else ()
            if row.get("reaction_target") != "creature_in_reach" and not _consent(engine, row, subject, checkpoint, trigger={
                    "actor_id": getattr(source_actor, "entity_id", None), "target_id": subject.entity_id,
                    "condition_name": condition_name}):
                continue  # "Ask me" (step 16): the player passed
            with _reaction_activation(engine, subject, source_actor, row) as permitted:
                if not permitted:
                    continue
                _open(engine, row, subject, target_ids, checkpoint, {"condition": condition_name})
                if not _spend_generic(engine, subject, row):
                    continue
                spend_reaction(engine, subject, row)
                _run_generic_effects(engine, subject, other, row, rest)
                engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=subject.entity_id, target_ids=target_ids,
                                     payload={"checkpoint": checkpoint, "condition": condition_name, "prevented": prevents})
                return prevents
        except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
            _log_bad_row(engine, subject, source_actor, row, exc)
    # An ally about to gain the condition (R2, "you or a creature within 30 feet ... becomes Charmed, Frightened, Prone"):
    # a Factory ally in range may answer for it.
    for bystander in _ally_candidates(engine, subject):
        for row in _ordered_generic_rows(engine, bystander.entity_id, "ally_condition_gained"):
            if not at_this_moment(row):
                continue
            try:
                if not _ally_row_ok(engine, bystander, source_actor, subject, row) or not _can_trigger(engine, bystander, row):
                    continue
                if not _generic_affordable(engine, bystander, row) or not _generic_condition_ok(row, condition_name) or not _generic_in_range(engine, bystander, subject, row):
                    continue
                other = subject
                if row.get("reaction_target") == "creature_in_reach":
                    from .ext.reaction_targets import choose_target
                    other = choose_target(engine, bystander, row, checkpoint, source_actor, condition_name, affected=subject)
                    if other is None:
                        continue
                if row.get("reaction_target") != "creature_in_reach" and not _consent(engine, row, bystander, checkpoint, trigger={
                        "actor_id": getattr(source_actor, "entity_id", None), "target_id": subject.entity_id,
                        "condition_name": condition_name}):
                    continue
                effects = row.get("effects") or []
                prevents = any(isinstance(e, dict) and e.get("type") == "prevent_condition" for e in effects)
                with _reaction_activation(engine, bystander, subject, row) as permitted:
                    if not permitted:
                        continue
                    _open(engine, row, bystander, (other.entity_id,), checkpoint, {"condition": condition_name, "protects": subject.entity_id})
                    if not _spend_generic(engine, bystander, row):
                        continue
                    spend_reaction(engine, bystander, row)
                    _run_generic_effects(engine, bystander, other, row, [e for e in effects if not (isinstance(e, dict) and e.get("type") == "prevent_condition")])
                    engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=bystander.entity_id, target_ids=(other.entity_id,),
                                         payload={"checkpoint": checkpoint, "condition": condition_name, "prevented": prevents})
                    if prevents:
                        return True
                    break
            except Exception as exc:  # a bad generic row must never end a fight (owner 2026-09-25)
                _log_bad_row(engine, bystander, source_actor, row, exc)
    return False


def flush_after_commit(engine: Any, target_id: str) -> None:
    """Run what a damage reaction left for after the hit was committed (see on_damage's hold_at_1hp)."""
    waiting = engine.__dict__.get("_typed_after_commit") or []
    mine = [entry for entry in waiting if entry[0] == target_id]
    if not mine:
        return
    from .paid_relocation import causal_scope, take_effect, preserve_pending

    preserve_pending(engine, "_typed_after_commit")
    engine.__dict__["_typed_after_commit"] = [entry for entry in waiting if entry[0] != target_id]

    for entry in mine:
        reactor_id, other_id, row, effects = entry
        reactor = engine.state.actors.get(reactor_id)
        if reactor is not None and reactor.active:
            with causal_scope(engine, take_effect(engine, entry)):
                _run_generic_effects(engine, reactor, engine.state.actors.get(other_id or ""), row, effects)

def checkpoint_response(engine: Any, reactor: Any, subject: Any, attacker: Any,
                        feature_id: str, checkpoint: str) -> dict[str, Any] | None:
    """Public shared eligibility for a replacement native checkpoint.

    A subscriber suppresses its old generic row, then supplies its own trigger.
    This preserves owned saved-bundle costs, reaction plans, range, conditions,
    once limits and resource checks. It does not spend or consent.
    """
    row = next((r for r in _rows(engine, reactor.entity_id, "generic") if r.get("feature_id") == feature_id), None)
    if row is None:
        return None
    row = {**row, "native_checkpoint": checkpoint}
    if not (_can_trigger(engine, reactor, row) and _generic_affordable(engine, reactor, row)
            and _generic_in_range(engine, reactor, subject, row)
            and _subject_ok(engine, reactor, attacker, row)):
        return None
    return row


def commit_checkpoint_response(engine: Any, reactor: Any, subject: Any, row: dict[str, Any],
                               checkpoint: str) -> None:
    """Spend a previously eligible response and record its settled reaction."""
    from .paid_relocation import activation as relocation_activation

    with relocation_activation(engine, reactor, row["feature_id"], independent=False):
        if not row.get("free"):
            spend_reaction(engine, reactor, row)
        if not _spend_generic(engine, reactor, row):
            return
        engine._append_event("REACTION_RESOLVED", row["feature_id"], actor_id=reactor.entity_id,
                             target_ids=(subject.entity_id,), payload={"checkpoint": checkpoint})
