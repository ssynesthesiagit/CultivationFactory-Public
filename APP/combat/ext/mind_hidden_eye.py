"""Shared Analyze roll/result/mark API for eye_analyze, eye_common, eye_gaze, lane4_crit and lane4_saves.

The Hidden Eye sphere's core mechanic (mind, 2026-09-28): Analyze itself has no typed-mechanics authority record --
it is printed as "CORE HIDDEN EYE RULES" prose (09_RULES/Source_Text/...:39679), not a talent heading, so the build
tool's per-talent extraction never made a mechanic id for it, and every Hidden Eye talent that names "Analyze" as its
target has nothing to attach to. This is a genuine authority-extraction gap, not a typing bug reviewed_final can patch
(there is no existing mechanic id for it to override); the smallest fix in scope is to inject the missing action here.

Printed text (unabridged, since nothing here is inferred):
  Time: 10 minutes, or 1 Action by expending Martial Focus (further reduced by Uncanny Stalker while hidden).
  Range: 60 feet. Target: one creature you can see.
  Duration: 24 hours, or until you finish a Long Rest.
  Choose Intelligence (Investigation) or Wisdom (Perception); check against the target's Analyze DC = 10 + its
  Challenge Rating (or half its Cultivation Level, rounded down, when it has no CR -- every creature on this table is a
  cultivator with a CL, not a CR, so that fallback is what actually runs).
  Success: learn one Analyzable Characteristic (a GM-only reveal); the target becomes Analyzed by you for the duration.
  Failure: learn nothing.

Only the 10-minute/Martial Focus/Uncanny-Stalker action economy and the Analyzed condition are automated -- the fight
does not need to know which Analyzable Characteristic you picked, that is GM information. Only in a fight: the 10-minute
version is never realistic mid-combat, so this only offers the 1-Action-with-Martial-Focus form (and its Uncanny
Stalker speed-up); the Reaction-timed use ("immediately before you attack, or when the target enters range") is a
GM-only rider in older bundles. Reviewed lane 14 bundles use riders14_eye.py for
the concealed Bonus Action and the Rapid Analysis Reaction form, retaining its
Martial Focus cost, per-target limit and exact attack/range-entry triggers.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

ANALYZED = "condition:typed.analyzed_by"
PATIENT_EYE_ANALYZED = "condition:typed.analyzed_by_patient_eye"
BASE_ID = "TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES"
FOCUS = "resource:core.martial_focus"


def analyzer_id(record: Any, data: Any = None) -> str:
    """Whose Analyzed relationship ``record`` is, for either record the table files; "" when it files none.

    One reader for both representations, so a benefit asks about the relationship rather than about one
    record's spelling: an ordinary Analyze (:data:`ANALYZED`) files its analyzer as the condition's source
    actor, while Heaven Keeps No Secret from the Patient Eye (:data:`PATIENT_EYE_ANALYZED`) names the user
    in the record's own ``by`` data. ``record`` may be a stored condition or a presentation row dict;
    ``data`` is that row's condition data, passed separately by the status-text seam.
    """

    def field(name: str, default: Any = None) -> Any:
        return record.get(name, default) if isinstance(record, dict) else getattr(record, name, default)

    condition_id = field("condition_id")
    if condition_id == ANALYZED:
        return str(field("source_actor_id") or "")
    if condition_id == PATIENT_EYE_ANALYZED:
        bag = data if data is not None else field("data")
        return str((bag or {}).get("by") or "")
    return ""


def analyzed_by(target: Any, actor_id: str) -> bool:
    """Whether ``actor_id`` has Analyzed ``target``: the one predicate every Analyzed benefit reads (Identify Rhythms,
    Find Gap, Exploit Weakness, Assault Analysis, Prognosis, Stealth Surge, the Meridian Ledger...).

    ``PATIENT_EYE_ANALYZED`` is the same relationship recorded by Heaven Keeps No Secret from the Patient Eye
    (combat/ext/eye_patient_eye.py). The printed Inheritance Analyzes its target "even if it would normally be
    protected from Analyze", so it files its own record rather than the Analyze mark: a creature immune to
    ``analyzed_by`` is still Analyzed by this Inheritance's owner for its minute, and the two records never replace
    one another (an ordinary Analyze the owner already spent outlives the minute). Both records are read through
    :func:`analyzer_id`, so a benefit that names its analyzer this way covers either representation.
    """
    return any(analyzer_id(c) == str(actor_id) for c in target.conditions.values())


LEARNED = "condition:typed.learned_characteristic"


def known_characteristic(target: Any, actor_id: str, characteristic: str) -> bool:
    """Shared recorded-knowledge query for Analyze and Modify Characteristics.

    Analyzed alone is not evidence that a particular characteristic was learned.
    """
    return any(c.condition_id == LEARNED and c.source_actor_id == actor_id
               and c.data.get("characteristic") == characteristic for c in target.conditions.values())


def record_characteristic(engine: Any, actor: Any, target: Any, characteristic: str, source: str,
                          *, newly_learned: bool = True, value: str | None = None) -> None:
    """Record a fresh information result, or confirm existing knowledge.

    Never call this merely because a creature became Analyzed. The information
    survives later Analyze expiry; it is a learned category, not a cached value.
    Modify Characteristics confirms prior knowledge with newly_learned=False;
    only a fresh result can notify Notice Profiling.

    ``value`` carries what was actually learned when the printed result is a fact
    rather than a bare category -- Spirit-Trace Pursuit's trace direction, say.
    It is stored on the record and shown on the sheet, so later mechanics that
    read learned characteristics recover the learned fact instead of only its
    name. Omit it for the plain category, which is the common case.
    """
    if not characteristic or not isinstance(characteristic, str):
        raise ValueError("a learned characteristic needs a nonempty name")
    if known_characteristic(target, actor.entity_id, characteristic):
        return
    label = characteristic.replace("_", " ")
    if value:
        label = f"{label}: {value}"
    data = {"characteristic": characteristic,
            "label": "Known characteristic: " + label + " (confirmed)"}
    if value:
        data["value"] = value
    engine._apply_condition(target, LEARNED, source, actor.entity_id, expires_on="UNTIL_REMOVED", data=data)
    from .riders14_research import notice_profiling

    if newly_learned:
        notice_profiling(engine, actor, target, [characteristic])


@hook("status_description")
def recorded_knowledge_status(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
    """Keep the mechanical ledger (including old saves) from revealing private facts.

    Analyze and Modify Characteristics query the stored record; Notice Profiling
    owns the target's paid disclosure. The ledger is not an effect on the target.
    """
    if row.get("condition_id") != LEARNED:
        return None
    return {"display_name": "Recorded knowledge", "applied_by": "Not disclosed", "conceal_source": True,
            "source_ability": "Recorded knowledge",
            "rules": "Confirmed knowledge is retained for abilities that require prior learning. "
                     "This record does not change the creature or reveal the learner or characteristic.",
            "duration": "retained until removed"}


def _cl_dc(engine: Any, target: Any) -> int:
    for action in engine.action_catalog.values():
        if action.owner_id == target.entity_id:
            cl = (((action.parameters or {}).get("typed") or {}).get("numbers") or {}).get("cl")
            if cl:
                return 10 + int(cl) // 2
    return 10


@hook("compile_actions")
def analyze_action(info: dict[str, Any]) -> list[Any] | None:
    if BASE_ID not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    uncanny = "TAL_THE_HIDDEN_EYE_UNCANNY_STALKER" in info["owned_ids"]
    # Rapid Analysis: "You may expend Martial Focus to Analyze as a Bonus Action instead of an Action."
    reviewed_uncanny = any(e.get("kind") == "uncanny_stalker" for e in
        (info["mechanics"].get("TAL_THE_HIDDEN_EYE_UNCANNY_STALKER") or {}).get("effects") or [])
    economy = EconomyKind.BONUS_ACTION if (uncanny and not reviewed_uncanny) or "TAL_THE_HIDDEN_EYE_RAPID_ANALYSIS" in info["owned_ids"] else EconomyKind.ACTION
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.analyze", display_name="Analyze",
        owner_id=info["actor_id"], economy=economy, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
        range_ft=120 if any(e.get("kind") == "far_sight_analysis" for e in
            (info["mechanics"].get("TAL_THE_HIDDEN_EYE_FAR_SIGHT_ANALYSIS") or {}).get("effects") or [])
            and "TAL_THE_HIDDEN_EYE_FAR_SIGHT_ANALYSIS" in info["owned_ids"] else 60,
        costs=((FOCUS, 1),),
        parameters={"typed": {"effects": [{"type": "analyze_check", "evidence": "Choose Intelligence (Investigation) or "
                                          "Wisdom (Perception); check against the target's Analyze DC. Success: the "
                                          "target becomes Analyzed by you for 24 hours (GM: you also learn one "
                                          "Analyzable Characteristic)."}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"},
                              "riders": ["Uncanny Stalker reduces this to a Bonus Action while hidden; its further "
                                        "reduction to a Reaction just before an attack is a GM-only rider."] if uncanny and not reviewed_uncanny else [],
                              "source": BASE_ID},
                    "expected_damage": 0})]


def mark_analyzed(engine: Any, actor: Any, target: Any, source: str) -> None:
    """The target becomes Analyzed by ``actor`` (a fresh Analyze replaces the old one); shared with Rapid Analysis's
    Initiative Analyze and Part-Breaker (combat/ext/eye_analyze.py), which reach Analyzed without this action."""
    from .condition_events import drop_condition as _drop

    for iid, old in list(target.conditions.items()):
        if old.condition_id == ANALYZED and old.source_actor_id == actor.entity_id:
            _drop(engine, target, iid, source)
    engine._apply_condition(target, ANALYZED, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": f"Analyzed by {actor.display_name}"})
    from . import run

    run("analyzed", engine, actor, target)


def analyze_roll(engine: Any, actor: Any, target: Any = None) -> Any:
    """One Analyze check: the best of Intelligence (Investigation) and Wisdom (Perception), plus Wisdom (Survival) for an
    Empirical Tracker and Wisdom (Medicine) with Physical Examination, rolled and recorded. Shared with Inimical Gaze
    (combat/ext/eye_gaze.py), which sets this one roll against several creatures."""
    from ..typed_executor import check_mode
    from .riders14_eye import has as rider_has, chosen_analyze_roll

    if rider_has(engine, actor, "analysis_limits"):
        return chosen_analyze_roll(engine, actor, target)

    from ..ability_checks import ability_modifier

    investigation = engine.roller.d20(modifier=ability_modifier(actor, "INT"), actor_id=actor.entity_id, reason="CHECK:analyze:investigation",
                                      mode=check_mode(actor, "INT", "Investigation", engine=engine, against_creature=target))
    perception = engine.roller.d20(modifier=ability_modifier(actor, "WIS"), actor_id=actor.entity_id, reason="CHECK:analyze:perception",
                                   mode=check_mode(actor, "WIS", "Perception", engine=engine, against_creature=target))
    roll = investigation if investigation.total >= perception.total else perception
    # Empirical Tracker (eye 2026-09-28): "You may use Wisdom (Survival) when attempting to Analyze a creature" -- a
    # third check option, on top of Investigation and Perception, for a character who owns that talent. Targeting
    # evidence instead of the creature itself (so no line of sight is needed) is a GM-only rider: this table's
    # Analyze action still targets a perceived creature.
    from .eye_common import has, skill  # deferred: eye_common imports this module's own ANALYZED/FOCUS at load time

    if has(engine, actor.entity_id, "empirical_tracker"):
        survival = engine.roller.d20(modifier=skill(engine, actor, "Survival", ability_modifier(actor, "WIS")),
                                     actor_id=actor.entity_id, reason="CHECK:analyze:survival", mode=check_mode(actor, "WIS", "Survival", engine=engine, against_creature=target))
        if survival.total > roll.total:
            roll = survival
    # Physical Examination (auto-lane4 2026-09-29): "You may use Wisdom (Medicine) when attempting to Analyze a creature" --
    # one more check option, the same way. The health-band read-out it also gives is information for the player.
    if has(engine, actor.entity_id, "physical_examination"):
        medicine = engine.roller.d20(modifier=skill(engine, actor, "Medicine", ability_modifier(actor, "WIS")),
                                     actor_id=actor.entity_id, reason="CHECK:analyze:medicine", mode=check_mode(actor, "WIS", "Medicine", engine=engine, against_creature=target))
        if medicine.total > roll.total:
            roll = medicine
    engine._record_roll(roll)
    from . import floored  # Complete Mandala Auspice (combat/ext/d20_floor.py); no DC yet, so no Release

    return floored(engine, actor, roll)


def _check_against(engine: Any, actor: Any, roll: Any, target: Any, source: str) -> bool:
    dc = _cl_dc(engine, target)
    success = roll.total >= dc
    payload = {"actor": roll.model_dump(mode="json"), "dc": dc, "success": success,
               "skill": roll.reason.rpartition(":")[2].replace("_", " ").title()}
    engine._append_event("CHECK_ROLLED", source, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload=payload)
    from . import run

    run("analyze_checked", engine, actor, target, payload)
    return success


def analyze_against(engine: Any, actor: Any, target: Any, source: str) -> bool:
    """Roll one Analyze check against ``target``'s Analyze DC (recorded, with its CHECK_ROLLED event); True on a success.
    Used by Rapid Analysis's Initiative Analyze (combat/ext/eye_analyze.py)."""
    from .riders14_eye import attempts_left

    return attempts_left(engine, actor, target) and _check_against(engine, actor, analyze_roll(engine, actor, target), target, source)


def analyze_result(ctx: Any, roll: Any, target: Any) -> bool:
    """Set an Analyze roll against one creature's Analyze DC; on a success it becomes Analyzed by the actor."""
    from .riders14_eye import attempts_left

    if not attempts_left(ctx.engine, ctx.actor, target):
        return False
    success = _check_against(ctx.engine, ctx.actor, roll, target, ctx.source)
    if success:
        mark_analyzed(ctx.engine, ctx.actor, target, ctx.source)
        ctx.rider(f"Analyze: {target.display_name} is Analyzed by {ctx.actor.display_name} (GM: pick one Analyzable Characteristic).")
    return success


@effect("analyze_check")
def analyze_check(ctx: Any, eff: dict[str, Any]) -> None:
    target = ctx.target
    if target is None or not target.active:
        return
    analyze_result(ctx, analyze_roll(ctx.engine, ctx.actor, target), target)


# ---------------------------------------------------------------- Identify Rhythms
@hook("ac")
def identify_rhythms_ac(engine: Any, defender: Any) -> int:
    """Identify Rhythms: +half PB (rounded down) AC against an attacker Analyzed by the defender (the "ac" hook only
    computes the defender's own AC modifier; the attacker making the current attack roll is the engine's current
    actor)."""
    if not any(row.get("block") == "hidden_eye" and row.get("kind") == "identify_rhythms" for row in
               (getattr(engine, "typed_passive_rows", {}) or {}).get(defender.entity_id, [])):
        return 0
    attacker = engine.state.actors.get(engine.state.current_actor_id or "")
    if attacker is None or not analyzed_by(attacker, defender.entity_id):
        return 0
    pb = next((((action.parameters or {}).get("typed") or {}).get("numbers") or {}).get("pb") for action in engine.action_catalog.values()
              if action.owner_id == defender.entity_id and (((action.parameters or {}).get("typed") or {}).get("numbers") or {}).get("pb")) or 2
    return int(pb) // 2


@hook("compile_block")
def identify_rhythms_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "hidden_eye":
        return None
    return [{**row, "block": "hidden_eye", "kind": spec.get("kind"),
             **({"initiative_setup": 1} if spec.get("kind") == "rapid_analysis" else {})}]
