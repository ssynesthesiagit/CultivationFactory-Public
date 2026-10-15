"""Wax seal attempts, Melting Rebuke and Waxen Trail.

Clinging Seal prints an Action *attempt*, not a creature removal DC. Spending
that Action releases its Dash restriction even if the seal remains. No removal
roll is invented. Beginning that attempt triggers the seal owner's Rebuke.
Wax wall damage uses the general wall_attack_damage notification. A destroyed
form still supplied the triggering wax; Rebuke never resurrects it.
Waxen Trail ends the exact owner's seal after a committed teleport, Invisibility
or represented shape change, leaving an inert, visible departure mark. Its
optional movement trace grants tracking Advantage against that one creature.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st
from .needle import ask, checkpoint_id
from .condition_ownership import remove_instance
from .wax import SEAL, consume_wax
from .wax_edict import impressed
from ..typed_executor import bears_mark, mark_condition_id

CLINGING = "TAL_WAX_CLINGING_SEAL"
REBUKE = "TAL_WAX_MELTING_REBUKE"
TRAIL = "TAL_WAX_WAXEN_TRAIL"
BLOCK = "wax_second_pass"
NO_DASH = "condition:typed.no_dash"
TRACE = "condition:typed.wax_tracking_trace"


@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> Any:
    if block == BLOCK:
        return [{**row, "kind": spec.get("kind")}]
    return None


def owns(engine: Any, actor: Any, feature: str) -> bool:
    return any(row.get("block") == BLOCK and row.get("kind") == feature
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


@effect("wax_dash_seal")
def dash_seal(ctx: Any, row: dict[str, Any]) -> None:
    target = ctx.target
    if target is None:
        return
    seal = next((c for c in target.conditions.values()
                 if c.condition_id == mark_condition_id(SEAL, ctx.actor.entity_id)), None)
    if seal is not None:
        from .choice_costs import Payment
        from ..typed_executor import CP_POOLS
        pool = next((p for p in CP_POOLS if ctx.actor.resources.get(p, 0) >= 1), None)
        if pool is None:
            return
        payment = Payment(pool, 1)
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "clinging_seal", ctx.source, target.entity_id),
            ctx.actor, "choice:needle.clinging_seal", ["strengthen"], allow_decline=True,
            automatic_options=["strengthen"] if ctx.actor.team_id != target.team_id else [],
            name="Clinging Seal", feature_id=CLINGING, target_id=target.entity_id, payment=payment,
            prompt=f"Clinging Seal: {target.display_name} failed its saving throw against Press Seal. Spend 1 additional Cultivation Point to strengthen that seal?",
            labels={"strengthen": "Strengthen the seal: it prevents Dash until the creature spends an Action attempting to remove it"})
        if not chosen:
            return
        payment.pay(ctx.engine, ctx.actor, ctx.source)
        ctx.engine._apply_condition(target, NO_DASH, ctx.source, ctx.actor.entity_id,
            expires_on=seal.expires_on, data={"wax_seal_id": seal.instance_id,
            "label": "Clinging Seal: spend an Action attempting to remove this seal before you can Dash"})


def penalties(actor: Any) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == NO_DASH and c.data.get("wax_seal_id") in actor.conditions]


@hook("compile_actions")
def attempt_action(info: dict[str, Any]) -> list[Any]:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    # Offered only while the bearer holds a strengthened seal. The bearer need
    # not know Wax: every compiled creature must be able to answer the restraint.
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.wax_seal_attempt",
        display_name="Attempt to Remove Clinging Seal", owner_id=info["actor_id"], economy=EconomyKind.ACTION,
        resolution_kind="TYPED", target_kind="SELF", parameters={"typed": {
        "effects": [{"type": "wax_seal_attempt", "evidence": "Spend your Action attempting to remove one strengthened Wax Seal. You can then Dash despite that seal. Its owner may kindle it with Melting Rebuke."}],
        "numbers": info["numbers"], "riders": []}})]


@hook("candidate_allowed")
def attempt_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if any(e.get("type") == "wax_seal_attempt" for e in (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or [])):
        return bool(penalties(actor))
    return None


def rebuke(engine: Any, owner: Any, attacker: Any, kind: str, wax: Any, intent: Any) -> None:
    from .. import stealth
    from ..paid_relocation import activation
    if owner is None or not owner.active or not owns(engine, owner, REBUKE) or not st.can_react(owner):
        return
    hostile = owner.team_id != attacker.team_id
    chosen = ask(engine, intent, checkpoint_id(engine, "melting_rebuke", owner.entity_id, attacker.entity_id), owner,
        "choice:needle.melting_rebuke", ["rebuke"], allow_decline=True,
        automatic_options=["rebuke"] if hostile and stealth.sees(engine, owner, attacker) else [],
        name="Melting Rebuke", feature_id=REBUKE, target_id=attacker.entity_id,
        labels={"rebuke": "Spend your Reaction and consume the triggering wax: Dexterity save, 1d8 + your Proficiency Bonus fire damage; half on success. On failure, Impressed until its next turn ends: a temporary Wax mark on the creature, with no further penalty by itself."},
        prompt=f"Melting Rebuke: {attacker.display_name} damages or starts tearing away {owner.display_name}'s wax. Kindle it?",
        prompt_context={"cost": "Reaction; no Cultivation Points"})
    if not chosen:
        return
    action = st.feature_action(engine, owner, REBUKE)
    action = action.model_copy(update={"display_name": "Melting Rebuke", "parameters": {
        **action.parameters, "typed": {**(action.parameters.get("typed") or {}), "source": REBUKE}}})
    with activation(engine, owner, REBUKE, independent=True):
        owner.reaction_available = False
        ctx = st.context(engine, owner, action, [attacker], intent=intent)
        consume_wax(ctx, kind, wax)
        st.save(ctx, attacker, "dex", on_fail=[
            {"type": "damage", "dice": {"count": 1, "sides": 8}, "formula": "pb", "damage_types": ["fire"]},
            *impressed(owner)], on_success=[{"type": "half_damage"}])
        note(engine, REBUKE, owner, f"Melting Rebuke: {owner.display_name} kindles the wax against {attacker.display_name}.", (attacker,))


@effect("wax_seal_attempt")
def attempt(ctx: Any, row: dict[str, Any]) -> None:
    held = penalties(ctx.actor)
    picks = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "wax_seal_attempt", ctx.actor.entity_id), ctx.actor,
        "choice:needle.wax_seal_attempt", [c.instance_id for c in held],
        labels={c.instance_id: "Clinging Seal placed by " + ctx.engine.state.actors[c.source_actor_id].display_name for c in held},
        name="Attempt to Remove Clinging Seal", feature_id=CLINGING,
        prompt=f"{ctx.actor.display_name}: choose the strengthened Wax Seal you spend your Action trying to remove.")
    if not picks:
        return
    penalty = next(c for c in held if c.instance_id == picks[0])
    rebuke(ctx.engine, ctx.engine.state.actors.get(penalty.source_actor_id), ctx.actor, "seal", ctx.actor, ctx.intent)
    remove_instance(ctx.engine, ctx.actor, penalty.instance_id, ctx.source)
    note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} spends an Action trying to remove the Clinging Seal and can now Dash despite that seal.")


@hook("wall_attack_damage")
def wall_rebuke(ctx: Any, zone: Any, section: Any, amount: int, melee: bool) -> None:
    from ..gate2_runtime_models import Position
    if melee and "TAL_WAX_MOLD_WAX" in zone.source_definition_id and ctx.engine._distance_actor_to_cell(ctx.actor, Position(x=section.x, y=section.y)) <= 5:
        rebuke(ctx.engine, ctx.engine.state.actors.get(zone.owner_id), ctx.actor, "form", zone, ctx.intent)


def seal_owners(engine: Any, subject: Any) -> list[Any]:
    return [owner for owner in engine.state.actors.values()
            if owns(engine, owner, TRAIL) and bears_mark(subject, owner.entity_id, SEAL)]


def snap(engine: Any, owner: Any, subject: Any, where: Any) -> None:
    from .. import zones
    from ..gate2_runtime_models import ZoneState
    action = st.feature_action(engine, owner, TRAIL)
    consume_wax(st.context(engine, owner, action, [subject]), "seal", subject)
    zid = f"zone:wax:trail_departure:{owner.entity_id}:{engine.state.event_sequence + 1}"
    zone = ZoneState(zone_id=zid, source_definition_id=TRAIL, owner_id=owner.entity_id,
        center=where, affected_cells=(where,), radius_cells=0, concentration_link=False,
        duration_rounds=None, created_round=engine.state.round_number,
        trigger_profile={"kind": zones.KIND, "name": "Waxen Trail Departure Mark", "visual": {"material": "wax"},
                         "triggers": [], "inside": [], "numbers": {}})
    engine.state.zones[zid] = zone
    engine._append_event("ZONE_CREATED", TRAIL, actor_id=owner.entity_id, payload={"zone": zone.model_dump(mode="json")})
    note(engine, TRAIL, owner, f"Waxen Trail: the seal on {subject.display_name} snaps, leaving an obvious wax mark at ({where.x},{where.y}).", (subject,))


# Snapping emits child CONDITION_REMOVED events; transformation and movement
# may themselves be children from another provider. Subscribe to both levels.
@hook("event", nested=True)
def trail_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from .. import stealth
    from ..gate2_runtime_models import Position
    payload = kwargs.get("payload") or {}
    if event_type == "CONDITION_REMOVED":
        for subject in engine.state.actors.values():
            for c in list(subject.conditions.values()):
                if c.condition_id in (TRACE, NO_DASH) and c.data.get("wax_seal_id") and c.data["wax_seal_id"] not in subject.conditions:
                    remove_instance(engine, subject, c.instance_id, TRAIL)
        return
    if event_type == "CONDITION_APPLIED":
        if str(payload.get("condition_id") or "").rsplit(".", 1)[-1] not in ("invisible", "polymorphed", "petrified"):
            return
        for tid in kwargs.get("target_ids") or ():
            subject = engine.state.actors.get(tid)
            if subject is not None:
                for owner in seal_owners(engine, subject):
                    snap(engine, owner, subject, subject.position)
        return
    if event_type != "MOVEMENT_COMMITTED":
        return
    subject = engine.state.actors.get(kwargs.get("actor_id"))
    if subject is None:
        return
    for owner in seal_owners(engine, subject):
        if payload.get("teleport"):
            path = payload.get("path") or []
            snap(engine, owner, subject, Position.model_validate(path[0]) if path else subject.position)
            continue
        if any(c.condition_id == TRACE and c.source_actor_id == owner.entity_id for c in subject.conditions.values()):
            continue
        picks = ask(engine, engine._active_intent, checkpoint_id(engine, "waxen_trail", owner.entity_id, subject.entity_id), owner,
            "choice:needle.waxen_trail", ["trace"], allow_decline=True, name="Waxen Trail", feature_id=TRAIL,
            # The printed human entitlement has no sight gate. AI may only
            # choose for movement its creature actually perceives.
            automatic_options=["trace"] if owner.team_id != subject.team_id and stealth.sees(engine, owner, subject) else [], target_id=subject.entity_id,
            prompt=f"Waxen Trail: {subject.display_name} moves while sealed. Leave a trace to track it?",
            labels={"trace": "Leave a wax trace: Advantage on Survival or Investigation checks to track this creature through ordinary terrain while the seal remains"})
        if picks:
            seal = next(c for c in subject.conditions.values() if c.condition_id == mark_condition_id(SEAL, owner.entity_id))
            engine._apply_condition(subject, TRACE, TRAIL, owner.entity_id, expires_on=seal.expires_on,
                                    data={"wax_seal_id": seal.instance_id, "label": "Waxen Trail: its seal leaves a tracking trace"})


@hook("contest_check_mode")
def tracking(ctx: Any, actor: Any, subject: Any, spec: dict[str, Any]) -> str | None:
    # Existing check provenance names the task and terrain. A generic Survival
    # or Investigation check against this creature is not necessarily tracking.
    if {"tracking", "ordinary_terrain"} <= set(spec.get("hazards") or ()) and (
            str(spec.get("ability") or "").upper(), str(spec.get("skill") or "").lower()) in (
            ("WIS", "survival"), ("INT", "investigation")) and any(
            c.condition_id == TRACE and c.source_actor_id == actor.entity_id and c.data.get("wax_seal_id") in subject.conditions
            for c in subject.conditions.values()):
        return "ADVANTAGE"
    return None
