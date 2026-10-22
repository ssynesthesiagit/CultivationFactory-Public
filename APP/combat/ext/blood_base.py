"""Coagulate's recipient consent and ordinary bleeding ending.

Extends the existing typed options, source-owned Thread gate and Life-state
stabilization rather than supplying a second ability. compile_action wraps
only Coagulate's owned options in the public willing_targets consent effect;
its any-creature compiler retains both allied and hostile willing recipients.
The native compile_actions phase precedes compile_action transforms, so the
hostile sibling is built explicitly through the same public helper. The later
transform is idempotent and preserves the already wrapped sibling.
No new engine hook or persisted state. Unknown circulation is not inferred.
"""
import copy

from . import hook

COAGULATE = "BLOOD_BASE_COAGULATE"


@hook("compile_action")
def coagulate_consent(action, info):
    original = (action.parameters or {}).get("typed") or {}
    if (original.get("option_of") or original.get("source")) != COAGULATE:
        return None
    if any(row.get("type") == "choose_willing" for row in original.get("effects") or []):
        return None
    parameters = copy.deepcopy(action.parameters or {})
    typed = parameters.get("typed") or {}
    rows = typed.get("effects") or []
    gate = [row for row in rows if row.get("type") == "requires_thread"]
    benefits = [row for row in rows if row.get("type") != "requires_thread"]
    typed["effects"] = gate + [{
        "type": "choose_willing", "target_only": True, "allow_hostile_target": True,
        "range_ft": 30, "effects": benefits, "variant_suffix": " (any creature)",
        "consent_text": "The caster spends a Bonus Action and 1 CP (Cultivation Point) on this Coagulate treatment. "
                        "You must bear their Blood Thread. The treatment takes effect immediately; refusing grants no benefit.",
    }]
    return action.model_copy(update={"parameters": parameters})


@hook("compile_action")
def end_one_ordinary_bleed(ctx, effect):
    """End one ordinary bleeding effect on the target.

    The caster spends a Bonus Action and 1 CP. If the caster gives no answer,
    the effect is declined (no wound is ended). This is in contrast to the old
    behaviour where the first available wound would be auto-ended.
    """
    from .needle import CHOICE, ask, checkpoint_id
    from .condition_ownership import remove_instance

    available = [(iid, facts) for iid, facts in effect.get("available_bleeding", {}).items()]
    if not available:
        return None

    picked = ask(
        ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "coagulate_bleeding", ctx.target.entity_id),
        ctx.actor, CHOICE + "coagulate_bleeding", list(available),
        preferred=list(available)[:1], default="decline", target_id=ctx.target.entity_id,
        prompt=f"Coagulate: choose one ordinary bleeding effect to end immediately on {ctx.target.display_name}. "
               "The caster spends a Bonus Action and 1 CP (Cultivation Point); no extra cost for this choice.",
    )
    if selected := picked:
        remove_instance(ctx.engine, ctx.target.entity_id, selected[0])
        return selected
    return None


@hook("compile_actions")
def coagulate_willing_non_allies(info):
    """Add willing hostile recipients before the late per-action transform.

    Original allied actions are transformed by compile_action. Existing
    already-consented authority rows remain the generic willing hook's job.
    """
    from .willing_targets import willing_non_allies

    prepared = [made for action in info["actions"]
                if (made := coagulate_consent(action, info)) is not None]
    return willing_non_allies({**info, "actions": prepared}) or None
