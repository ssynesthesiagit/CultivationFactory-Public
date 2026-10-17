"""Coagulate's recipient consent.

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

from . import hook, effect

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
    # This printed option ends one ordinary instance, never all conditions
    # sharing Bleeding's name. Keep source-specific treatment in this plug-in.
    benefits = [{**row, "type": "coagulate_end_bleeding"}
                if row.get("type") == "remove_condition" and row.get("condition") == "bleeding"
                else row for row in benefits]
    # Roll the printed sum once. Separate flat terms are individually clamped
    # by the generic roller, which would silently discard a negative key mod.
    # This is still the native temp_hp effect, including its interception path.
    for index, row in enumerate(benefits):
        if row.get("type") == "temp_hp" and row.get("parts"):
            combined = {k: v for k, v in row.items() if k != "parts"}
            combined["formula"] = "text:Proficiency Bonus + Path key ability modifier"
            for part in row["parts"]:
                if "dice_by_cl" in part:
                    combined["dice_by_cl"] = copy.deepcopy(part["dice_by_cl"])
            benefits[index] = combined
    typed["effects"] = gate + [{
        "type": "choose_willing", "target_only": True, "allow_hostile_target": True,
        "range_ft": 30, "effects": benefits, "variant_suffix": " (any creature)",
        "consent_text": "The caster spends a Bonus Action and 1 CP (Cultivation Point) on this Coagulate treatment. "
                        "You must bear their Blood Thread. The treatment takes effect immediately; refusing grants no benefit.",
    }]
    return action.model_copy(update={"parameters": parameters})


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


@effect("coagulate_end_bleeding")
def end_one_ordinary_bleed(ctx, eff):
    """Ask Coagulate's caster which exact, clinically eligible wound to end."""
    from ..clinical_sources import ordinary_bleeding_instances
    from .condition_ownership import remove_instance
    from .needle import CHOICE, ask, checkpoint_id

    if (ctx.typed.get("option_of") or ctx.typed.get("source")) != COAGULATE or ctx.target is None:
        return
    rows = ordinary_bleeding_instances(ctx.target, ctx.actor)
    if not rows:
        ctx.rider(f"Coagulate: no known ordinary bleeding effect can be ended on {ctx.target.display_name}.")
        return
    available = {iid: (held, facts) for iid, held, facts in rows}
    selected = ask(ctx.engine, ctx.intent,
                   checkpoint_id(ctx.engine, "coagulate_bleeding", ctx.target.entity_id),
                   ctx.actor, CHOICE + "coagulate_bleeding", list(available),
                   labels={iid: facts["label"] for iid, (_, facts) in available.items()},
                   preferred=list(available)[:1], target_id=ctx.target.entity_id,
                   prompt=f"Coagulate: choose one ordinary bleeding effect to end immediately on {ctx.target.display_name}. "
                          "The caster spends a Bonus Action and 1 CP (Cultivation Point); no extra cost for this choice.")
    if selected:
        remove_instance(ctx.engine, ctx.target, selected[0], ctx.source)
        ctx.rider(f"Coagulate ends one ordinary bleeding effect on {ctx.target.display_name}.")
