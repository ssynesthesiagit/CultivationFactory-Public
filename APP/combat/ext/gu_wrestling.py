"""Wrestling sphere: Applying a Slam, Choke Hold, Cultivation-Suppressing Grip, Grandstanding Slam
(Gu Xiangze, 2026-09-28; Wrestling and Gravity are gu's spheres for every character per the coordinator).

WRESTLING_BASE_APPLYING_A_SLAM is the sphere's core framework: "You may apply one Slam talent to one creature
Grappled by you" through three trigger windows (Establish the Hold / Work the Hold / Punish the Escape Attempt,
each a Bonus Action or a Reaction). It compiled to nothing (factory_compiler's `_BUILD_CHOICE` regex on "When you
learn Wrestling, choose one Slam talent..." -- the sheet-building sentence, not the fight action -- sent it to the
"build" bucket), so Gu's two Slam-tagged talents (Choke Hold, Cultivation-Suppressing Grip) and Grandstanding Slam
(a Martial-Focus rider that fires "whenever you apply a Slam talent") all had nothing to attach to.

One Bonus Action button per known Slam covers applying it to a creature already
Grappled by its owner. Punish the Escape Attempt uses these same action effects
through wrestling_framework's failed-escape Reaction prompt, rather than adding
duplicate buttons. Target prerequisites are checked before either route pays.

Typed Slams (rider lane C2, 2026-09-30): any Slam talent with a {"block": "wrestling_slam"} feature row (combat/rules/feature_blocks.d/
riders_c2.json: Hammerlock, Hard Whip, Heel Tactics, Joint-Locking Scripture, Meridian-Crushing Clinch, Meridian-Wrenching Lock) gets
its own "Apply a Slam" button whose effects are the talent's reviewed typed effects, run on the creature Grappled by you (Grandstanding
Slam's burst and Martial Focus as for the others). Their condition hooks live in combat/ext/wrestling.py.
Shared public slam_eligible and pinned_by helpers keep this module's buttons and
wrestling_framework's Punish the Escape Attempt on the same target prerequisites.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook
from ..gate2_runtime_models import ActionDefinition, EconomyKind
from ..action_variants import choice, with_variant
from ..typed_executor import CONDITION_PREFIX

WRESTLING = "tianxia.sphere.wrestling"
GRAPPLED = CONDITION_PREFIX + "grappled"
SLAM_TALENTS = {
    "choke_hold": ("TAL_WRESTLING_CHOKE_HOLD", "Choke Hold"),
    "cultivation_suppressing_grip": ("TAL_WRESTLING_CULTIVATION_SUPPRESSING_GRIP", "Cultivation-Suppressing Grip"),
}
GRANDSTANDING = "TAL_WRESTLING_GRANDSTANDING_SLAM"


@hook("compile_actions")
def apply_a_slam(info: dict[str, Any]) -> list[ActionDefinition] | None:
    if WRESTLING not in info["spheres"]:
        return None
    owned = info["owned_ids"]
    known = [key for key, (mech_id, _name) in SLAM_TALENTS.items() if mech_id in owned]
    typed_slams = [row for row in info.get("passives") or () if row.get("block") == SLAM_BLOCK]
    if not known and not typed_slams:
        return None
    grandstanding = GRANDSTANDING in owned
    costs = (("resource:core.martial_focus", 1),) if grandstanding else ()
    made = [_typed_slam(info, row, grandstanding) for row in typed_slams]
    for key in known:
        mech_id, name = SLAM_TALENTS[key]
        riders = ["Apply a Slam as a Bonus Action to a creature you still Grapple. The hold lasts until the start of your next turn "
                  "or until your grapple ends. When that creature fails an Action check to escape, you may use your Reaction "
                  "to apply the same Slam instead."]
        if key != "choke_hold":
            riders.append("Cultivation-Suppressing Grip: choose one ongoing supernatural effect on the target you "
                          "can perceive -- GM compares a Cultivation Check to 10 + the effect's rank; suppress it "
                          "on a success, dispel it on a success by 5+ (no generic 'effect rank' registry exists to "
                          "automate the comparison).")
        if grandstanding:
            riders.append("Grandstanding Slam: expends Martial Focus; every other hostile creature that can see "
                          "you makes a Charisma save or is Frightened of you until the start of your next turn "
                          "(immune until your next short or long rest on a success).")
        typed = {"effects": [{"type": "apply_slam", "slam": key, "grandstanding": grandstanding,
                              **({"breath_gate": True} if key == "choke_hold" else {})}],
                 "numbers": info["numbers"], "duration": {"kind": "instant"}, "range_ft": None, "riders": riders,
                 "source": mech_id}
        made.append(with_variant(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.granted.slam.{key}", display_name=f"Apply a Slam: {name}",
            owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
            range_ft=5, costs=costs, parameters={"typed": typed, "expected_damage": 0,
                                                 "target_requires_condition": GRAPPLED}),
            f"action:typed.{info['short']}.granted.slam", "Apply a Slam", (choice("slam", key, name),)))
    return made


SLAM_BLOCK = "wrestling_slam"


@hook("compile_block")
def slam_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """A Slam talent that runs its own typed effects through Apply a Slam (combat/rules/feature_blocks.d: {"block": "wrestling_slam"},
    optional "requires_pin": the Slam applies only to a creature Restrained through your Pin; "focus": it expends Martial Focus)."""
    if block != SLAM_BLOCK:
        return None
    return [{**row, "block": SLAM_BLOCK, "requires_pin": bool(spec.get("requires_pin")), "focus": bool(spec.get("focus"))}]


def _typed_slam(info: dict[str, Any], row: dict[str, Any], grandstanding: bool) -> ActionDefinition:
    """Apply a Slam for a typed Slam talent: its reviewed effects (frozen into the bundle) run on the creature Grappled by you."""
    import copy

    mech_id = row["feature_id"]
    mechanic = (info.get("mechanics") or {}).get(mech_id) or {}
    name = str(mechanic.get("name") or row.get("name") or mech_id)
    focus = grandstanding or row.get("focus")
    typed = {"effects": [{"type": "apply_slam", "slam": "typed", "grandstanding": grandstanding, "requires_pin": bool(row.get("requires_pin")),
                          "effects": copy.deepcopy(mechanic.get("effects") or [])}],
             "numbers": info["numbers"], "duration": {"kind": "instant"}, "range_ft": None, "riders": list(mechanic.get("riders") or []),
             "source": mech_id, "sphere": WRESTLING}
    return with_variant(ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.granted.slam.{mech_id.lower()}", display_name=f"Apply a Slam: {name}",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
        range_ft=5, costs=(("resource:core.martial_focus", 1),) if focus else (),
        parameters={"typed": typed, "expected_damage": 0, "target_requires_condition": GRAPPLED}),
        f"action:typed.{info['short']}.granted.slam", "Apply a Slam", (choice("slam", mech_id.lower(), name),))


@effect("apply_slam")
def block_apply_slam(ctx: Any, effect_row: dict[str, Any]) -> None:
    if effect_row.get("twin_runtime"):
        from .wrestling_twin import slam_targets
        from ..typed_executor import Context
        for subject in slam_targets(ctx):
            child = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject, ctx.damage_cache)
            block_apply_slam(child, {**effect_row, "twin_runtime": False})
        return
    target = ctx.target
    if target is None:
        return
    grapple = next((c for c in target.conditions.values() if c.condition_id == GRAPPLED and c.source_actor_id == ctx.actor.entity_id), None)
    if grapple is None:
        ctx.rider("Apply a Slam: the target is not currently Grappled by you -- no Slam applied.")
        return
    if effect_row.get("requires_pin") and not pinned_by(ctx.engine, ctx.actor, target):
        ctx.rider("Apply a Slam: this Slam applies only to a creature Restrained through your Pin -- no Slam applied.")
        return
    if effect_row.get("effects"):
        from ..typed_executor import run_effects

        run_effects(ctx, list(effect_row["effects"]))
    if effect_row.get("slam") == "choke_hold":
        from .wrestling import apply_choke_hold

        apply_choke_hold(ctx, target, breath_gate=bool(effect_row.get("breath_gate")))
    if effect_row.get("grandstanding"):
        _grandstanding_burst(ctx, target)


def pinned_by(engine: Any, actor: Any, target: Any) -> bool:
    """Restrained through the user's Pin (a Restrained condition its own Pin action put on)."""
    for condition in target.conditions.values():
        if condition.condition_id != CONDITION_PREFIX + "restrained" or condition.source_actor_id != actor.entity_id:
            continue
        action = engine.action_catalog.get(condition.source_definition_id)
        if (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source")) == "TAL_WRESTLING_PIN_2":
            return True
    return False


def slam_eligible(engine: Any, actor: Any, target: Any, action: Any, *, reaction: bool = False) -> bool:
    """Shared target gate for Apply a Slam and Punish the Escape Attempt.

    Check ownership, grip, range, Pin, costs and existing candidate vetoes before
    payment. Reaction delivery uses Reaction economy for economy-based vetoes.
    """
    from ..gate2_runtime_models import CandidateKind, LegalCandidate
    from . import any_false

    if target is None or not target.active or target.team_id == actor.team_id or action.owner_id != actor.entity_id:
        return False
    if not any(c.condition_id == GRAPPLED and c.source_actor_id == actor.entity_id for c in target.conditions.values()):
        return False
    if engine._distance_actor_to_actor(actor, target) > int(action.range_ft or action.reach_ft or 5):
        return False
    effects = ((action.parameters or {}).get("typed") or {}).get("effects") or []
    if any(e.get("requires_pin") for e in effects) and not pinned_by(engine, actor, target):
        return False
    if any(int(actor.resources.get(rid) or 0) < amount for rid, amount in engine.effective_costs(actor, action.source_definition_id, action.costs)):
        return False
    candidate = LegalCandidate(candidate_id="slam-eligibility", decision_id="slam-eligibility",
        state_version=engine.state.state_version, kind=CandidateKind.ACTION, actor_id=actor.entity_id,
        source_definition_id=action.source_definition_id, display_name=action.display_name, target_ids=(target.entity_id,))
    delivery = action.model_copy(update={"economy": EconomyKind.REACTION}) if reaction else action
    return not any_false("candidate_allowed", engine, actor, candidate, delivery)


@hook("candidate_allowed")
def slam_target(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Pin-only Slams must not offer an ordinary unpinned grapple target."""
    if action is None or ".granted.slam." not in action.source_definition_id:
        return None
    effects = ((action.parameters or {}).get("typed") or {}).get("effects") or []
    if not any(e.get("requires_pin") for e in effects):
        return None
    targets = [engine.state.actors.get(tid) for tid in candidate.target_ids]
    return bool(targets) and all(t is not None and pinned_by(engine, actor, t) for t in targets)


def _grandstanding_burst(ctx: Any, slammed: Any) -> None:
    """Grandstanding Slam: every other hostile creature that can see Gu saves or is Frightened; a success makes it
    immune to Grandstanding Slam until Gu's next short or long rest (no rest hook here, so UNTIL_REMOVED -- a rest
    routine that clears conditions on rest, if one exists elsewhere, will already handle it like any other lasting
    condition; otherwise it is a GM reminder)."""
    from .. import stealth

    dc = int(ctx.numbers.get("save_dc") or 10)
    immune_id = "condition:typed.grandstanding_slam_immune"
    for other in stealth.foes(ctx.engine, ctx.actor):
        if other.entity_id == slammed.entity_id:
            continue
        if any(c.condition_id == immune_id and c.source_actor_id == ctx.actor.entity_id for c in other.conditions.values()):
            continue
        if not stealth.sees(ctx.engine, other, ctx.actor):
            continue
        roll = ctx.engine._roll_save(other, "CHA", dc, ctx.source)
        if roll.total < dc:
            ctx.engine._apply_condition(other, "condition:typed.frightened", ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN")
        else:
            ctx.engine._apply_condition(other, immune_id, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED")
