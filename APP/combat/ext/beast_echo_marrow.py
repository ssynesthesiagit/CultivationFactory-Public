"""Inert Beast-Echo source/range extraction; no combat features are registered.

This is a prerequisite library, not delivery of Generate Pack Echo or Pack
Marrow. There are deliberately no hook/effect decorators or feature blocks.
The native compiler currently grants all stage-eligible Foundation expressions
without a selected-expression receipt. Do not activate a Refined spend until
that ownership contract exists.

Intended callers: this module's future compile_action seal for Generate Pack
Echo/Strike, and its future paid Strike rider. Witness and Guard have different
printed scopes; they must not inherit technique membership as a blanket test.
The State's compatible-technique clause can reuse the source seal, but its
beast-source save clause cannot. See the lane continuation for delivery gates.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from ..relations import ALLY, relation

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
    including Mountain-Moving Palm. A natural weapon instead requires the
    matching owned natural_weapon row and a real unarmed attack effect. Display
    names and strings embedded in an action ID convey no membership.
    """
    if action.owner_id != actor_id:
        return None
    typed = action.parameters.get("typed") or {}
    source = typed.get("source")
    if not isinstance(source, str) or source not in owned_ids:
        return None
    mechanic = mechanics.get(source) or {}
    if mechanic.get("mechanic_id") != source:
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
