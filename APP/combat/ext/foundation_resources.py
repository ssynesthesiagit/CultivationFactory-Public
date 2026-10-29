"""Foundation resources the engine did not generate or spend (sys-resources-states 2026-09-29, system B): Old Light
(Star-Sovereign Core Imprint), Crane Breath (White Crane Cloud-Step), Glass Reflection (Glass Heart Meridian) and Heavenly
Integrity (Heavenly Body). Shared hit_damage_type helper consumers: foundation_resources and foundations4.
Until now "Generate <resource>" compiled to a skipped passive, so no character ever held the
resource and every feature that spends it was dead in a fight.

Sources (owner text: authority/typed_mechanics/rules_text.json, non_sphere_authority/authority/
Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md; "CP means the character's current Path resource",
Core Rules Reference v0_2C, Terms):

  Generation. Combat/pressure.py's ``generate`` does the gain (max 1, once a round, gone at the end of your next turn, and
  "if already held, refresh expiration instead of stacking" for Old Light, Heavenly Integrity and Glass Reflection --
  Crane Breath says "If you do not already have Crane Breath", so it does not refresh). A resource gained after an event has
  resolved cannot pay for that event: every spend below happens inside the hit or save, generation after it.
    Heavenly Integrity  after hostile damage while conscious (pressure.after_damage, reason "damaged").
    Old Light           "after you spend Path resource on a Fixed Star-Sovereign Scope technique/effect that affects a
                        creature, point, omen, mark, or trace": a technique of one of the Foundation's affinity Spheres
                        (Foundation_Runtime_Authority_v0_4C.json compatibility_traits.affinity_sphere_ids: the
                        Foundation's legal Spheres, which the Factory's own sheet lists as ``foundation.fixed_scope`` --
                        the engine's reading of "Fixed Scope"; GM judgment) that cost a core Path resource; it also
                        creates or refreshes one Star Mark on the first hostile (else other) creature involved.
    Glass Reflection    the same trigger for the Glass Heart Scope, or a save that resolved in your favor against a hostile
                        charm, fear, illusion, gaze or beauty effect.
    Crane Breath        moving at least 15 feet on your turn (willing, not Speed 0, Grappled, Restrained or Prone); a
                        hostile attack missing you after you moved on your last turn; succeeding on a Dexterity save to avoid
                        Prone, Grappled, Restrained or forced movement.  (A Dexterity/Acrobatics *check* to avoid falling is a
                        GM call: the engine does not roll it.)
  Spends (block "foundation_spend" rows, combat/rules/feature_blocks.d/sys_resources-states.json):
    Sovereign Ray       spend 1 Old Light after a hit, or a failed save, against a creature you Star-Marked, with a Fixed
                        Scope technique: +PB damage of the first of radiant, cold, force, psychic the target does not resist.
    Star-Sovereign Core State  a 1-minute state (an ordinary Bonus Action, "Spend 1 Old Light + 2 Path resource"): two Star
                        Marks instead of one, and once a round +PB to one numeric benefit of a spend (Sovereign Ray).
    Omen Witness (+ Omen Core)  spend 1 Old Light after a failed save against a Fixed Scope technique when +PB (+PB more
                        for Omen Core, on a Stars/Fate/Space/Hidden Eye/Dreams roll; +PB more in Core State) turns it into a
                        success. The player is asked; an AI-controlled fighter does it when it changes the outcome.
    Integrity Strike    spend 1 pre-existing Heavenly Integrity on a hit: +PB damage; Orthodox Answering Strike +PB more when
                        the target damaged you since the end of your last turn; Heaven-Recognized Vessel +PB more once a round.
    Crane-Wing Cut      spend 1 Crane Breath on a hit after moving at least 10 feet on your turn: +PB + key modifier damage
                        (Wings Remember Ground +PB). The optional 5-foot follow-up move is left to the player (a rider).
  Integrity Rejection is a plain "save_rescue" row (combat/typed_reactions.py on_save; +PB, or +2xPB with Heaven-Recognized
  Vessel), which is the printed timing: after the roll, before the outcome. Heaven-Rejecting Marrow's "after the save is
  declared a failure" is the same moment in this engine.

Player-controlled fighters are asked before a spend (the "FOUNDATION_SPEND" moment, a Use / Don't button like every Reaction);
an AI-controlled one spends when the spend applies. Not automated, and why, is in the sys_resources-states report.
"""

from __future__ import annotations

from ..paid_relocation import activation, preserve_pending

import functools
import json
from pathlib import Path
from typing import Any

from . import effect, hook, note

CHECKPOINT = "FOUNDATION_SPEND"
STAR_MARK = "Star Mark"
CORE_STATE = "condition:typed.foundation.star_sovereign_core_state"
AUTHORITY = Path(__file__).resolve().parents[2] / "non_sphere_authority" / "authority" / "Foundation_Runtime_Authority_v0_4C.json"
RAY_TYPES = ("radiant", "cold", "force", "psychic")  # Sovereign Ray: "PB radiant, cold, force, or psychic damage"
OMEN_CORE_SPHERES = frozenset({"tianxia.sphere.stars", "tianxia.sphere.fate", "tianxia.sphere.space", "tianxia.sphere.the_hidden_eye", "tianxia.sphere.dreams"})
GLASS_SPHERES = frozenset({"tianxia.sphere.illusion", "tianxia.sphere.beauty", "tianxia.sphere.glass", "tianxia.sphere.the_hidden_eye"})
BLOCKING = ("condition:typed.grappled", "condition:typed.restrained", "condition:typed.prone")


@functools.lru_cache(maxsize=None)
def affinity_spheres(foundation_id: str) -> frozenset[str]:
    """Source-backed affinities shared by resource generation and Palace hits.

    This is compatibility only; callers still enforce their printed technique
    categories and the owning character's actual acquisition.
    """
    try:
        rows = json.loads(AUTHORITY.read_text(encoding="utf-8")).get("orthodox") or []
    except (OSError, ValueError):
        return frozenset()
    for row in rows:
        if row.get("foundation_id") == foundation_id:
            return frozenset((row.get("compatibility_traits") or {}).get("affinity_sphere_ids") or ())
    return frozenset()


_affinity = affinity_spheres  # historical internal callers retain the same provider


def _foundation_id(feature_id: str) -> str:
    return feature_id.split(".")[1] if feature_id.startswith("foundation.") and feature_id.count(".") >= 2 else ""


def _rows(engine: Any, actor: Any, block: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if row.get("block") == block]


def _spend_row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    return next((row for row in _rows(engine, actor, "foundation_spend") if row.get("kind") == kind), None)


def _in_scope(engine: Any, actor: Any, reason: str, sphere: str | None) -> bool:
    """Whether a technique of ``sphere`` is one the character's Foundation reads for this generation trigger."""
    return bool(sphere) and any(reason in (row.get("on") or []) and sphere in _affinity(_foundation_id(str(row.get("feature_id")))) for row in _rows(engine, actor, "generate"))


def _scope_of(engine: Any, actor: Any, kind: str) -> frozenset[str]:
    row = _spend_row(engine, actor, kind)
    return _affinity(_foundation_id(str(row.get("feature_id")))) if row else frozenset()


def _holding(actor: Any, row: dict[str, Any] | None) -> bool:
    return row is not None and bool(row.get("resource_id")) and actor.resources.get(row["resource_id"], 0) >= 1 and actor.active


def _consent(engine: Any, actor: Any, row: dict[str, Any]) -> bool:
    from .. import typed_reactions

    return typed_reactions._consent(engine, {"feature_id": row["feature_id"], "ask": True}, actor, CHECKPOINT)


def _debit(engine: Any, actor: Any, row: dict[str, Any]) -> None:
    engine._spend_resource(actor, row["resource_id"], 1, f"passive:{row['feature_id']}")


def _pay(engine: Any, actor: Any, row: dict[str, Any]) -> bool:
    """Spend 1 of the row's resource, asking a player-controlled fighter first (the Reaction question)."""
    if not _consent(engine, actor, row):
        return False
    _debit(engine, actor, row)
    return True


def _plus(engine: Any, actor: Any, feature_kind: str) -> bool:
    from . import run_strict

    owned = _spend_row(engine, actor, feature_kind)
    if owned is None:
        return False
    return False not in run_strict("foundation_expression_selected", engine, actor, owned["feature_id"])


def _pb(row: dict[str, Any]) -> int:
    return int(row.get("pb") or 2)


def _extra_damage(ctx: Any, target: Any, amount: int, damage_type: str | None, evidence: str) -> None:
    from .. import typed_executor

    if amount <= 0 or not target.active or ctx.engine.state.terminal_result is not None:
        return
    sub = typed_executor.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    typed_executor.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": amount,
                                      **({"damage_types": [damage_type]} if damage_type else {}), "evidence": evidence}])


def hit_damage_type(engine: Any, actor: Any, target: Any) -> str | None:
    """Damage type of the latest hit receipt, shared by foundation_resources and foundations4."""
    dealt = next((event for event in reversed(engine.events[-30:]) if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == actor.entity_id
                  and target.entity_id in (event.target_ids or ())), None)
    kind = str(((dealt.payload or {}) if dealt is not None else {}).get("damage_type") or "")
    return kind.lower() if kind and kind != "UNTYPED" else None


def _once_a_round(actor: Any, name: str, engine: Any) -> bool:
    """Claim a once-a-round benefit; a turn flag with "_round_" in its key survives turn resets."""
    key = f"foundation_round_{name}"
    if actor.turn_flags.get(key) == engine.state.round_number:
        return False
    actor.turn_flags[key] = engine.state.round_number
    return True


# ------------------------------------------------------------------------------------------------------- compile
@hook("compile_block")
def compile_spend(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "foundation_spend":
        return None
    return [{**row, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "key_mod": int(numbers.get("key_mod") or 0)}]


# --------------------------------------------------------------------------------------------- Star-Sovereign Core State
@effect("foundation_core_state")
def core_state(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    ctx.engine._remove_condition(ctx.actor, CORE_STATE, ctx.source)
    ctx.engine._apply_condition(
        ctx.actor, CORE_STATE, ctx.source, ctx.actor.entity_id,
        expires_on=typed_executor.effect_expiry(ctx, eff, ctx.actor, condition=True) or "UNTIL_REMOVED",
        data={"label": "Star-Sovereign Core State",
              "reading": "For 1 minute: when you generate Old Light you keep two Star Marks instead of one until the end of your next turn, "
                         "and once a round when you spend Old Light, one numeric benefit of the spend is PB higher (the engine adds it to Sovereign Ray "
                         "and Omen Witness). If you create three or more Star Marks in the state without acting in the present scene, it ends "
                         "with Distant Core Strain Severity 1 (GM)."})
    note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} enters Star-Sovereign Core State (1 minute).")


def _in_core_state(actor: Any) -> bool:
    return any(c.condition_id == CORE_STATE for c in actor.conditions.values())


def _core_bonus_ready(engine: Any, actor: Any) -> bool:
    return _in_core_state(actor) and actor.turn_flags.get("foundation_round_core_state_pb") != engine.state.round_number


def _claim_core_bonus(engine: Any, actor: Any, pb: int) -> int:
    """Core State: once a round, when you spend Old Light, +PB to one numeric benefit of that spend."""
    return pb if _core_bonus_ready(engine, actor) and _once_a_round(actor, "core_state_pb", engine) else 0


# --------------------------------------------------------------------------------------------------------- generation
def _path_spent(ctx: Any) -> bool:
    """The technique cost Path resource ("spend CP on a ... technique/effect"): in its listed costs, or -- for a button that pays as its
    effect runs (Control Figment, a figment's paid options) -- a RESOURCE_SPENT it recorded under its own id since its intent was accepted."""
    if any(str(resource).startswith("resource:core.") and int(amount) > 0 for resource, amount in (ctx.action.costs or ())):
        return True
    for event in reversed(ctx.engine.events):
        if event.event_type == "INTENT_ACCEPTED":
            return False
        payload = event.payload or {}
        if event.event_type == "RESOURCE_SPENT" and event.actor_id == ctx.actor.entity_id and event.source_definition_id == ctx.action.source_definition_id \
                and str(payload.get("resource_id", "")).startswith("resource:core.") and int(payload.get("amount") or 0) > 0:
            return True
    return False


def _place_star_mark(ctx: Any) -> None:
    from .. import typed_executor

    engine, actor = ctx.engine, ctx.actor
    others = [creature for creature in ctx.targets if creature is not actor and creature.active]
    target = next((creature for creature in others if creature.team_id != actor.team_id), others[0] if others else None)
    if target is None:
        ctx.rider("Old Light: the technique involved no other creature, so no Star Mark was placed (a point, omen or trace is the GM's to mark).")
        return
    cap = 2 if _in_core_state(actor) else 1
    condition_id = typed_executor.mark_condition_id(STAR_MARK, actor.entity_id)
    held = sorted(((c.applied_sequence, holder, c) for holder in engine.state.actors.values() for c in holder.conditions.values()
                   if c.condition_id == condition_id and holder is not target), key=lambda row: row[0])
    for _, holder, _condition in held[:max(0, len(held) - (cap - 1))]:
        engine._remove_condition(holder, condition_id, ctx.source)  # "one Star Mark by default": a new one replaces the older
    sub = typed_executor.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    typed_executor.block_mark(sub, {"mark": STAR_MARK, "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"}})
    note(engine, ctx.source, actor, f"{actor.display_name} gains Old Light and marks {target.display_name} with a Star Mark.", (target,))


def _resolve_pending_rays(ctx: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    waiting = [row for row in getattr(engine, "_foundation_ray", []) if row[1] == actor.entity_id]
    if not waiting:
        return
    engine._foundation_ray = [row for row in engine._foundation_ray if row[1] != actor.entity_id]
    for source, _, subject_id, start in waiting:
        subject = engine.state.actors.get(subject_id)
        if subject is None or source != ctx.source or not subject.active:
            continue
        if any(event.event_type == "DAMAGE_COMMITTED" and event.actor_id == actor.entity_id and subject_id in (event.target_ids or ())
               and int((event.payload or {}).get("hp_damage") or 0) + int((event.payload or {}).get("temporary_hp_absorbed") or 0) > 0
               for event in engine.events[start:]):
            _ray(ctx, subject)


@hook("technique_used")
def generate_after_technique(ctx: Any) -> None:
    engine, actor, sphere = ctx.engine, ctx.actor, ctx.typed.get("sphere")
    _resolve_pending_rays(ctx)  # before this technique's own Old Light: a spend "cannot spend on the same event that generated" it
    if not sphere or not _path_spent(ctx) or not actor.active:
        return
    from .. import pressure

    if _in_scope(engine, actor, "star_sovereign_scope", sphere) and pressure.generate(engine, actor, "star_sovereign_scope"):
        _place_star_mark(ctx)
    if _in_scope(engine, actor, "glass_scope_spend", sphere) and pressure.generate(engine, actor, "glass_scope_spend"):
        note(engine, ctx.source, actor, f"{actor.display_name} gains Glass Reflection.")


@hook("after_save")
def generate_after_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """A save that resolved in the bearer's favor against a hostile effect: Crane Breath (Dexterity, to avoid Prone, Grappled,
    Restrained or forced movement) and Glass Reflection (charm, fear, illusion, gaze, beauty)."""
    if failed or not subject.active or subject.team_id == ctx.actor.team_id:
        return
    from .. import pressure

    named = {str(row).lower() for row in named or ()}
    if str(ability or "").upper()[:3] == "DEX" and named & {"prone", "grappled", "restrained", "forced_movement"} \
            and pressure.generate(ctx.engine, subject, "crane_saved"):
        note(ctx.engine, ctx.source, subject, f"{subject.display_name} gains Crane Breath.")
    if (named & {"charmed", "frightened"} or ctx.typed.get("sphere") in GLASS_SPHERES) and pressure.generate(ctx.engine, subject, "glass_reflection_save"):
        note(ctx.engine, ctx.source, subject, f"{subject.display_name} gains Glass Reflection.")


@hook("event")
def crane_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Crane Breath: willing movement on the bearer's own turn (tallied in a turn flag), and a hostile attack that misses it."""
    payload = kwargs.get("payload") or {}
    if event_type == "MOVEMENT_COMMITTED":
        actor = engine.state.actors.get(kwargs.get("actor_id") or "")
        if actor is None or payload.get("forced") or payload.get("dragged_by") or engine.state.current_actor_id != actor.entity_id \
                or not any("crane_moved" in (row.get("on") or []) for row in _rows(engine, actor, "generate")):
            return
        moved = max(0, len(payload.get("path") or []) - 1) * engine.grid.square_size_ft
        total = int(actor.turn_flags.get("crane_moved_ft") or 0) + moved
        actor.turn_flags["crane_moved_ft"] = total
        if total >= 15 and actor.active and engine._effective_speed(actor) > 0 and not any(c.condition_id in BLOCKING for c in actor.conditions.values()):
            from .. import pressure

            if pressure.generate(engine, actor, "crane_moved"):
                note(engine, "foundation:crane_breath", actor, f"{actor.display_name} gains Crane Breath (moved {total} feet).")
    elif event_type == "ATTACK_ROLLED" and payload.get("provisional_hit") is False:
        attacker = engine.state.actors.get(kwargs.get("actor_id") or "")
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is None or attacker is None or attacker.team_id == target.team_id or not target.turn_flags.get("crane_round_moved_last"):
                continue
            from .. import pressure

            if pressure.generate(engine, target, "crane_missed"):
                note(engine, "foundation:crane_breath", target, f"{target.display_name} gains Crane Breath ({attacker.display_name} missed).")


@hook("turn_end")
def crane_turn_end(engine: Any, actor: Any) -> None:
    """"After a hostile attack misses you after you moved on your last turn": remember, across the turn reset, whether it moved."""
    if any("crane_moved" in (row.get("on") or []) for row in _rows(engine, actor, "generate")):
        actor.turn_flags["crane_round_moved_last"] = int(actor.turn_flags.get("crane_moved_ft") or 0) > 0


# ----------------------------------------------------------------------------------------------------------- spends
def _damaged_me_since_my_last_turn(engine: Any, actor: Any, target: Any) -> bool:
    for event in reversed(engine.events):
        if event.event_type == "TURN_ENDED" and event.actor_id == actor.entity_id:
            return False
        if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == target.entity_id and actor.entity_id in (event.target_ids or ()) \
                and int((event.payload or {}).get("hp_damage") or 0) + int((event.payload or {}).get("temporary_hp_absorbed") or 0) > 0:
            return True
    return False


def _star_marked(actor: Any, target: Any) -> bool:
    from .. import typed_executor

    return typed_executor.bears_mark(target, actor.entity_id, STAR_MARK)


def _ray(ctx: Any, target: Any) -> None:
    """Sovereign Ray on a Star-Marked target after a Fixed Scope hit or failed save."""
    engine, actor = ctx.engine, ctx.actor
    row = _spend_row(engine, actor, "sovereign_ray")
    if not _holding(actor, row) or target.team_id == actor.team_id or not _star_marked(actor, target) \
            or ctx.typed.get("sphere") not in _scope_of(engine, actor, "sovereign_ray"):
        return
    from .. import typed_reactions

    kind = max(RAY_TYPES, key=lambda name: typed_reactions.damage_factor(engine, target, name, ctx.source, actor.entity_id))
    if typed_reactions.damage_factor(engine, target, kind, ctx.source, actor.entity_id) <= 0 or not _pay(engine, actor, row):
        return
    bonus = _pb(row) + _claim_core_bonus(engine, actor, _pb(row))
    note(engine, row["feature_id"], actor, f"{actor.display_name} spends Old Light: Sovereign Ray adds {bonus} {kind} damage to {target.display_name}.", (target,))
    _extra_damage(ctx, target, bonus, kind, "Spend 1 Old Light to add PB radiant, cold, force, or psychic damage to that hit or damaging effect.")


def _strike(ctx: Any, target: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    row = _spend_row(engine, actor, "integrity_strike")
    if not _holding(actor, row) or target.team_id == actor.team_id or not _pay(engine, actor, row):
        return
    bonus, parts = _pb(row), ["Integrity Strike"]
    if _plus(engine, actor, "orthodox_answering_strike") and _damaged_me_since_my_last_turn(engine, actor, target):
        bonus, parts = bonus + _pb(row), [*parts, "Orthodox Answering Strike"]
    if _plus(engine, actor, "heaven_recognized_vessel") and _once_a_round(actor, "vessel", engine):
        bonus, parts = bonus + _pb(row), [*parts, "Heaven-Recognized Vessel"]
    note(engine, row["feature_id"], actor, f"{actor.display_name} spends Heavenly Integrity: {' + '.join(parts)} adds {bonus} damage to {target.display_name}.", (target,))
    _extra_damage(ctx, target, bonus, hit_damage_type(engine, actor, target), "Spend 1 pre-existing Heavenly Integrity to add PB damage to a hit.")


def _crane_cut(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    row = _spend_row(engine, actor, "crane_wing_cut")
    if not _holding(actor, row) or target.team_id == actor.team_id or int(actor.turn_flags.get("crane_moved_ft") or 0) < 10 \
            or engine.state.current_actor_id != actor.entity_id:
        return
    if kind not in ("weapon", "unarmed") and ctx.typed.get("sphere") not in _scope_of(engine, actor, "crane_wing_cut"):
        return  # "Foundation-aligned melee, thrown, Air, spear, sword, or body-bound attack"
    if not _pay(engine, actor, row):
        return
    bonus, parts = _pb(row) + int(row.get("key_mod") or 0), "Crane-Wing Cut"
    if _plus(engine, actor, "wings_remember_ground"):
        bonus, parts = bonus + _pb(row), "Crane-Wing Cut + Wings Remember Ground"
    note(engine, row["feature_id"], actor, f"{actor.display_name} spends Crane Breath: {parts} adds {bonus} damage to {target.display_name}.", (target,))
    ctx.rider("Crane-Wing Cut: you may now move 5 feet without provoking Opportunity Attacks from the target you hit (move it yourself).")
    _extra_damage(ctx, target, bonus, hit_damage_type(engine, actor, target), "Add your Proficiency Bonus + your Path key ability modifier to the triggering damage.")


@hook("after_hit")
def spend_on_hit(ctx: Any, target: Any, kind: str) -> None:
    if not target.active or not _rows(ctx.engine, ctx.actor, "foundation_spend"):
        return
    _ray(ctx, target)
    _strike(ctx, target)
    _crane_cut(ctx, target, kind)


def _deals_damage(ctx: Any) -> bool:
    from .. import typed_executor

    return any(row.get("type") in ("damage", "attack") for row in typed_executor._walk_rows(ctx.typed.get("effects") or []))


def _save_total(engine: Any, subject: Any) -> tuple[int, int] | None:
    """(total, dc) of the subject's latest save roll."""
    for event in reversed(engine.events[-40:]):
        if event.event_type == "SAVE_ROLLED" and event.actor_id == subject.entity_id and (event.payload or {}).get("dc") is not None:
            return int((event.payload or {}).get("total") or 0), int((event.payload or {}).get("dc") or 0)
    return None


@hook("after_save")
def spend_on_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    engine, actor = ctx.engine, ctx.actor
    if not failed or not subject.active:
        return
    if subject.team_id != actor.team_id and _deals_damage(ctx) and _spend_row(engine, actor, "sovereign_ray") is not None:
        # A Star-Marked target that fails a save against your damaging Fixed Scope technique: the Ray adds to "that damaging effect",
        # so it waits until the technique has dealt its damage (after_save runs before it, and an outcome can still be overturned).
        pending = [row for row in getattr(engine, "_foundation_ray", []) if row[1] != actor.entity_id]
        engine._foundation_ray = [*pending, (ctx.source, actor.entity_id, subject.entity_id, len(engine.events))]
    row = _spend_row(engine, subject, "omen_witness")
    if not _holding(subject, row) or ctx.typed.get("sphere") not in _scope_of(engine, subject, "omen_witness"):
        return
    rolled = _save_total(engine, subject)
    if rolled is None:
        return
    bonus = _pb(row) + (_pb(row) if _plus(engine, subject, "omen_core") and ctx.typed.get("sphere") in OMEN_CORE_SPHERES else 0)
    if rolled[0] + bonus + (_pb(row) if _core_bonus_ready(engine, subject) else 0) < rolled[1]:
        return  # not worth an Old Light: it would still fail
    if not _consent(engine, subject, row):
        return
    with activation(engine, subject, row["feature_id"]):
        _debit(engine, subject, row)
        bonus += _claim_core_bonus(engine, subject, _pb(row))
        preserve_pending(engine, "_typed_roll_outcome")
        engine._typed_roll_outcome = {**(getattr(engine, "_typed_roll_outcome", None) or {}), subject.entity_id: "success"}
        note(engine, row["feature_id"], subject, f"{subject.display_name} spends Old Light: Omen Witness adds {bonus} to the save and it succeeds.", (actor,))
