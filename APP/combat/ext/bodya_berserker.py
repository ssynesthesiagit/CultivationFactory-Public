"""Berserker sphere remainder (bodya 2026-09-29, follow-up to wave-2 "body"): Advancing Carnage, plus the generic
``if_condition`` effect type Heaven-Crushing Exertion's reviewed_final correction needs.

Already built and reused, not touched here: Adrenaline's toggle and Berserk's gated defense (combat/ext/body_berserker.py,
wave-2 "body"), Batter/Brutal Strike/Bone-Breaker/Bell-Ringer/Cultivation Sunder's one-Exertion-talent toggle
(combat/ext/gu_berserker.py, Gu Xiangze's own file), Heaven-Shaking Batter's choose-one-effect options and
Grandstanding Slam/Body Lock/Abrading Ward/Dune Bank/Sand Step (all already compiled through the generic modifier-option
pipeline or another worker's sphere module and globally labelled in feature_status.d/gu.json). Atavism, Executioner,
Juggernaut, Deathless, Extended Exertion, Alter Terrain and Beat Down are labelled in feature_status.d/bodya.json instead
of guessed at here (see that file for why each has no further compiled effect).

Advancing Carnage ("When you score a critical hit with a melee weapon or reduce a creature to 0 HP with a melee weapon,
make one melee attack as a Bonus Action", CL5+) had compiled as an unconditional, always-available extra attack ("nothing
typed to add", per char_review's MODIFIERS section: it targeted nothing and contributed nothing, so the printed trigger
was simply dropped rather than gating anything). Built here as a real trigger: after a melee hit that either rolls a
critical (the most recent DAMAGE_ROLLED event for this attack, payload.critical) or reduces the target to 0 HP
(target.active/current_hp, checked after the hit fully resolves, same point gu_berserker.py's own after_hit runs at),
a turn flag opens a one-attack Bonus Action clone of the character's own primary melee attack (the first melee/unarmed/natural
weapon attack the shared weapon_actions query finds -- reused rather than re-derived) for the rest of the turn,
using the engine's existing requires_turn_flag legality gate (combat/gate2_engine.py line ~694, the same one
docket_maneuvers.py's Barrage follow-up already relies on). The printed trigger can fire more than once a turn (each
qualifying hit reopens the flag); the Bonus Action itself is still limited to one use by ordinary action economy.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

ADVANCING_CARNAGE = "TAL_BERSERKER_ADVANCING_CARNAGE"
FLAG = "bodya_advancing_carnage_ready"


@effect("if_condition")
def if_condition(ctx: Any, eff: dict[str, Any]) -> None:
    """Generic gate: run nested ``effects`` only against whichever of this activation's own targets already carry the
    named condition (a bare name, e.g. "battered", resolved as ``condition:typed.<name>``, or a full condition id).
    Mirrors typed_executor.block_if_marked's shape for a plain condition instead of a placed mark; added here because
    Heaven-Crushing Exertion's own "if the target was already Battered, add 6d10 Force damage" was compiling as an
    unconditional bonus (no gate existed for a plain named condition, only for the mark system)."""
    from ..typed_executor import Context, run_effects

    name = str(eff.get("condition") or "").strip()
    nested = eff.get("effects") or []
    if not name or not nested:
        return
    condition_id = name if name.startswith("condition:") else f"condition:typed.{name}"
    pool = [ctx.target] if ctx.target is not None else list(ctx.targets)
    subjects = [subject for subject in pool if subject is not None and any(c.condition_id == condition_id for c in subject.conditions.values())]
    if not subjects:
        return
    inner = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, subjects, subjects[0] if len(subjects) == 1 else None, ctx.damage_cache)
    run_effects(inner, nested)


def _melee_kind(ctx: Any, kind: str) -> bool:
    return kind == "unarmed" or (kind == "weapon" and int(ctx.typed.get("range_ft") or 5) <= 5)


def _crit(ctx: Any, target: Any) -> bool:
    return any(event.event_type == "DAMAGE_ROLLED" and event.actor_id == ctx.actor.entity_id and target.entity_id in (event.target_ids or ())
               and bool((event.payload or {}).get("critical")) for event in ctx.engine.events[-12:])


@hook("after_hit")
def advancing_carnage(ctx: Any, target: Any, kind: str) -> None:
    # The owner-only maneuver row is already persisted in the fight's compiled
    # bundle and reconstructed in its action catalog on reload. Query that
    # fight-scoped authority, including for older saved rows, instead of caching
    # actor IDs across unrelated compilations/fights in this process.
    if not any(row.owner_id == ctx.actor.entity_id
               and row.source_definition_id.endswith(".advancing_carnage")
               and row.parameters.get("requires_turn_flag") == FLAG
               for row in ctx.engine.action_catalog.values()):
        return
    if not _melee_kind(ctx, kind):
        return
    reduced_to_zero = not target.active or target.current_hp <= 0
    if not (reduced_to_zero or _crit(ctx, target)):
        return
    ctx.actor.turn_flags[FLAG] = True


@hook("maneuvers")
def _grant_bonus_attack(info: dict[str, Any]) -> dict[str, Any] | None:
    """Hooked at "maneuvers" (not "compile_actions"): every compile_actions hook -- including gu_berserker.py's own
    Batter -- sees the SAME "actions so far" snapshot taken once before any of them run (combat/ext/__init__.py's
    ``run`` calls each hook with the identical args), so a bare-handed, non-Iron-Fist Berserker's only melee action
    (Batter) would not exist yet for a compile_actions hook here to clone. The "maneuvers" hook runs afterwards, once
    compile_actions' own additions (Batter included) are already merged into ``info["actions"]``."""
    if ADVANCING_CARNAGE not in info["owned"]:
        return None
    from .weapon_actions import weapon_attacks
    from ..gate2_runtime_models import EconomyKind
    import copy

    weapons = weapon_attacks(info["actions"], info["actor_id"])
    primary = next((row for row in weapons if row[3] in ("unarmed", "natural", "melee")), None)
    if primary is None:
        return None
    row, typed, _attack, _kind = primary
    extra = {key: value for key, value in row.parameters.items() if key not in ("typed", "expected_damage")}
    follow = copy.deepcopy(typed)
    follow["weapon_source_id"] = row.source_definition_id
    # This is one attack with the same implement, not a second weapon or
    # another entire Attack action (including Extra Attack).
    for attack in follow.get("effects") or []:
        if attack.get("type") == "attack":
            attack["count"] = 1
            attack.pop("count_by_cl", None)
    clone = row.model_copy(update={
        "source_definition_id": f"{row.source_definition_id}.advancing_carnage", "display_name": f"Advancing Carnage: {row.display_name}",
        "economy": EconomyKind.BONUS_ACTION,
        "parameters": {**extra, "typed": follow,
                       "expected_damage": int(row.parameters.get("expected_damage") or 0) // max(1, int(_attack.get("count") or 1)),
                       "requires_turn_flag": FLAG},
    })
    return {"actions": [clone]}
