"""Beast-Echo generation and shared source/range prerequisites.

Generate Pack Echo seals native technique/natural-weapon provenance at
compile_action. A pure hit_snapshot records the printed hostile target or
nearby-ally trigger; hit_settled generates only after the hit and its riders
resolve. pressure owns the cap, refresh, round budget and next-turn expiry.
All creature-set queries use beast_qualifiers.qualifies.

Other Beast-Echo records are not delivered here yet. In particular Refined
spends must wait for selected-expression ownership rather than inheriting
all stage-eligible expressions. Witness and Guard have different printed
scopes and must not inherit technique membership as a blanket test.

qualify_compiled_source is shared by the generation seal and future paid
Strike/State consumers. refined_pair_in_range is Pack Marrow-only geometry,
not base pair eligibility or authorization to spend.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from ..relations import ALLY, ENEMY, relation
from . import hook
from .beast_qualifiers import HOSTILE_TRIGGER_KINDS, qualifies

GENERATE = "foundation.beast_echo_marrow_v0_2A.generate_pack_echo"
GENERATION_RECEIPT = "beast_echo_generation"

FEATURE = "foundation.beast_echo_marrow_v0_2A"
SCOPE_SPHERES = frozenset(
    "tianxia.sphere." + name
    for name in ("beastmastery", "spirit_companions", "blood", "hunger",
                 "athletics", "warleader", "brute", "berserker", "wrestling")
)


def qualify_compiled_source(
    action: Any, *, actor_id: str, owned_ids: Collection[str],
    mechanics: Mapping[str, Mapping[str, Any]],
    passive_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, str] | None:
    """Derive provenance from a native action and authoritative compiler inputs.

    ``action`` is an ActionDefinition from the native compile pass, not a
    submitted action packet. ``mechanics`` is the compiler's typed authority;
    ``owned_ids`` and ``passive_rows`` are its resolved ownership/compiled rows.
    Never pass player answers, affinity lists or untrusted action dictionaries.
    The returned facts may eventually be sealed into typed action parameters;
    calling this helper alone neither publishes nor authorizes any action.

    Canonical sphere identity covers both TAL_* and dotted mechanic IDs,
    including Mountain-Moving Palm and native forged records bound to an owned
    printed primary. A natural weapon instead requires the
    matching owned natural_weapon row and a real unarmed attack effect. Display
    names and strings embedded in an action ID convey no membership.
    """
    if action.owner_id != actor_id:
        return None
    typed = action.parameters.get("typed") or {}
    source = typed.get("source")
    if not isinstance(source, str):
        return None
    mechanic = mechanics.get(source) or {}
    if mechanic.get("mechanic_id") != source:
        return None
    if mechanic.get("kind") == "forged_technique":
        # The native compiler supplies this constructed record and its printed
        # primary mechanic. A submitted forged_from string alone is not proof.
        primary = mechanic.get("forged_from")
        if primary != typed.get("forged_from") or primary not in owned_ids:
            return None
        source = primary
        mechanic = mechanics.get(source) or {}
        if mechanic.get("mechanic_id") != source:
            return None
    elif source not in owned_ids:
        return None
    provenance = mechanic.get("source") or {}
    text_hash = provenance.get("text_sha256")
    if not isinstance(text_hash, str) or len(text_hash) != 64:
        return None
    sphere = mechanic.get("sphere_id")
    natural = any(row.get("block") == "natural_weapon" and row.get("feature_id") == source
                  for row in passive_rows) and any(
        row.get("type") == "attack" and row.get("attack_kind") == "unarmed"
        for row in typed.get("effects") or ()
    )
    if sphere not in SCOPE_SPHERES and not natural:
        return None
    return {"mechanic_id": source, "text_sha256": text_hash,
            "sphere_id": str(sphere or ""),
            "membership": "natural_weapon" if natural else "technique_family"}


def refined_pair_in_range(engine: Any, owner: Any, hitter: Any) -> bool:
    """Only Pack Marrow's recipient/range prerequisite, never a spend decision.

    A separate native selected-expression seal, pre-hit Echo snapshot and
    same-target prior positive damage receipt are still required. In particular,
    this helper must NOT replace ordinary companion/base Pair eligibility:
    the Refined rider requires the other creature to be within 30 feet even
    when the base companion route reaches it farther away. No resource, clock,
    ledger, condition or action economy is changed by this query.
    """
    return bool(owner.active and hitter.active
                and owner.entity_id != hitter.entity_id
                and relation(engine, owner, hitter) == ALLY
                and engine._distance_actor_to_actor(owner, hitter) <= 30)


@hook("compile_block")
def compile_generation(block: str, spec: dict[str, Any], row: dict[str, Any],
                       numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Declare one generator; the generic pressure clock handles its lifetime."""
    if block != "beast_echo_generation":
        return None
    return [{**row, "block": "generate", "on": ["beast_echo_hit"], "max": 1,
             "per_round": 1, "refresh": True, "expires": "end_of_next_turn",
             "trigger_owner": "beast_echo_marrow"}]


@hook("compile_passives")
def generation_pool(rows: list[dict[str, Any]], info: dict[str, Any]) -> list[dict[str, Any]]:
    """Bind either the sheet Foundation pool or its compiler-declared named pool."""
    if GENERATE not in info["owned_ids"]:
        return rows
    return [{**row, "resource_id": row.get("resource_id") or "resource:named.pack_echo"}
            if row.get("feature_id") == GENERATE else row for row in rows]


@hook("compile_action")
@hook("compile_reaction_action")
def seal_generation_source(action: Any, info: dict[str, Any]) -> Any:
    """Seal authoritative membership, never words embedded in submitted IDs."""
    if GENERATE not in info["owned_ids"]:
        return None
    facts = qualify_compiled_source(
        action, actor_id=action.owner_id, owned_ids=info["owned_ids"],
        mechanics=info["mechanics"], passive_rows=info["passives"])
    if facts is None:
        return None
    return action.model_copy(update={
        "parameters": {**action.parameters, "beast_echo_source": facts}})


def generation_row(engine: Any, actor: Any) -> dict[str, Any] | None:
    """The native compiled ownership row; no fallback grant from a name."""
    return next((row for row in engine.typed_passive_rows.get(actor.entity_id, ())
                 if row.get("feature_id") == GENERATE and row.get("block") == "generate"), None)


@hook("hit_snapshot")
def generation_trigger(engine: Any, actor: Any, target: Any, attack_context: Any,
                       intent: Any) -> dict[str, bool] | None:
    """Freeze the printed hit-time trigger before damage or riders move creatures."""
    if generation_row(engine, actor) is None or relation(engine, actor, target) != ENEMY:
        return None
    eligible = qualifies(engine, target, HOSTILE_TRIGGER_KINDS)
    action = engine.action_catalog.get(attack_context.source_id)
    if not eligible and action is not None and action.parameters.get("beast_echo_source"):
        eligible = any(other.active and other.entity_id != actor.entity_id
                       and relation(engine, actor, other) == ALLY
                       and min(engine._distance_actor_to_actor(other, actor),
                               engine._distance_actor_to_actor(other, target)) <= 30
                       for other in engine.state.actors.values())
    return {GENERATION_RECEIPT: eligible}


@hook("hit_settled")
def generate_after_hit(ctx: Any, target: Any, kind: str) -> None:
    """A new Echo cannot pay any rider on the hit that generated it."""
    if not (ctx.hit_snapshots or {}).get(GENERATION_RECEIPT):
        return
    if generation_row(ctx.engine, ctx.actor) is None:
        return
    from ..pressure import generate

    generate(ctx.engine, ctx.actor, "beast_echo_hit")
