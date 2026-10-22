"""Coagulate's willing-recipient consent and ordinary bleeding ending.

Extends the typed options, source-owned Thread gate and Life-state stabilization
rather than supplying a second ability. The printed End Bleeding mode compiles to
remove_condition on "bleeding", which would end every Bleeding instance. It is
replaced by the plug-in effect coagulate_end_ordinary_bleeding, which offers only
instances the sealed clinical roster classifies as ordinary and readable by the
caster (combat/clinical_sources.py), defaults to decline, and ends the one chosen.

Coagulate's own options are wrapped in the public choose_willing consent row.
compile_actions adds the hostile-recipient sibling through the public
willing_non_allies clone helper; compile_action keeps the allied original wrapped.
No new engine hook or persisted state. Unknown circulation is not inferred.
"""
import copy

from . import effect, hook

COAGULATE = "BLOOD_BASE_COAGULATE"
END_ORDINARY = "coagulate_end_ordinary_bleeding"


def _is_coagulate(action):
    typed = (action.parameters or {}).get("typed") or {}
    return (typed.get("option_of") or typed.get("source")) == COAGULATE


def _wrapped(action):
    """Pure: the Coagulate action with its benefits behind willing consent and ordinary-only Bleeding."""
    parameters = copy.deepcopy(action.parameters or {})
    typed = parameters.get("typed") or {}
    rows = typed.get("effects") or []
    if any(row.get("type") == "choose_willing" for row in rows):
        return action
    gate = [row for row in rows if row.get("type") == "requires_thread"]
    benefits = [_ordinary_row(row) for row in rows if row.get("type") != "requires_thread"]
    typed["effects"] = gate + [{
        "type": "choose_willing", "target_only": True, "allow_hostile_target": True,
        "range_ft": 30, "effects": benefits, "variant_suffix": " (any creature)",
        "consent_text": "The caster spends a Bonus Action and 1 CP (Cultivation Point) on this Coagulate treatment. "
                        "You must bear their Blood Thread. The treatment takes effect immediately; refusing grants no benefit.",
    }]
    parameters["typed"] = typed
    return action.model_copy(update={"parameters": parameters})


def _ordinary_row(row):
    if row.get("type") == "remove_condition" and row.get("condition") == "bleeding":
        return {"type": END_ORDINARY, "applies_to": "target",
                "evidence": "end one ordinary bleeding effect"}
    return row


@hook("compile_actions")
def coagulate_willing_non_allies(info):
    """Hostile willing-recipient siblings for Coagulate, built from the original catalog."""
    from .willing_targets import willing_non_allies

    owned = [_wrapped(action) for action in info.get("actions") or [] if _is_coagulate(action)]
    return willing_non_allies({"actions": owned}) or None


@hook("compile_action")
def coagulate_consent(action, info):
    if not _is_coagulate(action):
        return None
    wrapped = _wrapped(action)
    return None if wrapped is action else wrapped


@effect(END_ORDINARY)
def end_one_ordinary_bleeding(ctx, row):
    """End one ordinary Bleeding instance on each target the caster may treat.

    Offered instances come only from the sealed clinical roster. The choice
    defaults to decline: an unanswered prompt ends no wound.
    """
    from .. import typed_executor
    from .clinical_sources import ordinary_bleeding_instances
    from .condition_ownership import remove_instance
    from .needle import CHOICE, ask, checkpoint_id

    for holder in typed_executor._default_subject(ctx, row, harmful=False):
        if holder is None or not holder.active:
            continue
        labels = ordinary_bleeding_instances(ctx.engine, holder, ctx.actor.entity_id)
        if not labels:
            ctx.rider(f"{ctx.action.display_name}: {holder.display_name} has no ordinary Bleeding effect "
                      "that the clinical roster lets you treat; nothing ends.")
            continue
        picked = ask(
            ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "coagulate_bleeding", holder.entity_id),
            ctx.actor, CHOICE + "coagulate_bleeding", list(labels), labels=labels,
            default="decline", target_id=holder.entity_id, name=ctx.action.display_name,
            prompt=f"Coagulate: choose one ordinary bleeding effect to end immediately on {holder.display_name}. "
                   "The caster spends a Bonus Action and 1 CP (Cultivation Point); no extra cost for this choice.",
        )
        if picked:
            remove_instance(ctx.engine, holder, picked[0], ctx.source)
