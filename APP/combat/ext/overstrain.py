"""Yang's Overstrain Technique (riders lane 2, 2026-09-29): "Trigger: the marked subject spends CP, uses a spell slot, activates a limited
feature, or uses a named cultivation technique. If the subject uses the same named spell, sphere talent, forged technique, monster action, or
cultivation ability again before the end of its next turn, it gains a Rising Mark immediately after the repeated ability resolves."

    {"type": "overstrain_watch", "applies_to": "target", "duration": "until_end_of_next_turn"}

runs as the response to the technique the marked creature is using (combat/typed_reactions._offer_technique_reaction; the technique's own name
is ``engine._typed_pending_technique["technique"]``, its ability id): it puts ``condition:typed.overstrain`` on the creature, filed under the
Yang user, remembering that technique.  When the creature (or, for the printed "monster action", any fighter) uses that same technique again
before the condition ends, ``technique_used`` gives it an Overkindled Mark from the same Yang user after the repeated ability's effects ran, and
the watch is over.  A different technique changes nothing; the watch lapses at the end of the creature's next turn.

Deterministic and evented: the watch is a condition (applied and removed with the engine's own methods) and the mark is placed by the marker's
own block_mark, so the mark limit and expiry are the usual ones.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .condition_ownership import remove_instance, refresh_owned

WATCH = "condition:typed.overstrain"


@effect("overstrain_watch")
def watch(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    pending = getattr(ctx.engine, "_typed_pending_technique", None) or {}
    technique = pending.get("technique")
    if not technique:
        return
    for subject in _default_subject(ctx, row, harmful=True):
        if not subject.active or subject.entity_id != pending.get("actor"):
            continue
        refresh_owned(ctx.engine, subject, WATCH, ctx.actor.entity_id, ctx.source)
        ctx.engine._apply_condition(subject, WATCH, ctx.source, ctx.actor.entity_id, expires_on=effect_expiry(ctx, row, subject, condition=True),
                                    data={"technique": technique, "first_use": getattr(ctx.intent, "intent_id", None),
                                          "label": "Overstrain: using that technique again gains a Rising Mark"})


@hook("technique_used")
def repeated(ctx: Any) -> None:
    user = ctx.actor
    technique = ctx.typed.get("option_of") or ctx.typed.get("source")
    for held in list(user.conditions.values()):
        if held.condition_id != WATCH or not technique or held.data.get("technique") != technique:
            continue
        if held.data.get("first_use") and held.data["first_use"] == getattr(ctx.intent, "intent_id", None):
            continue
        resolve_watch(ctx, user, held)


def resolve_watch(ctx: Any, user: Any, held: Any) -> None:
    """Resolve exactly the watch that matched this completed technique."""
    marker = ctx.engine.state.actors.get(held.source_actor_id or "")
    remove_instance(ctx.engine, user, held.instance_id, "system:overstrain.repeated")
    if marker is None or not marker.active or not user.active:
        return
    from ..typed_executor import block_mark
    from ..typed_reactions import _generic_context
    from .needle import numbers_of

    inner = _generic_context(ctx.engine, marker, user, {"feature_id": "TAL_YANG_OVERKINDLED_RESPONSES#overstrain_technique",
                                                        "name": "Overstrain Technique", "effects": [], "numbers": numbers_of(ctx.engine, marker)}, None)
    block_mark(inner, {"type": "mark", "mark": "Overkindled Mark", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                       "evidence": "it gains a Rising Mark immediately after the repeated ability resolves"})
