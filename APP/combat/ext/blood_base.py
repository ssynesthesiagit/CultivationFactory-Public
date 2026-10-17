"""Coagulate's recipient consent.

Extends the existing typed options, source-owned Thread gate and Life-state
stabilization rather than supplying a second ability. compile_action wraps
only Coagulate's owned options in the public willing_targets consent effect;
its any-creature compiler retains both allied and hostile willing recipients.
The native compile_actions phase precedes compile_action transforms, so the
hostile sibling is built explicitly through the same public helper. The later
transform is idempotent and preserves the already wrapped sibling.
No new engine hook or persisted state. Unknown circulation is not inferred.
End Bleeding uses the shared clinical source chooser, so one ordinary source
ends while unrelated wounds remain. The consent and Thread gates still run.
"""
import copy

from . import hook

COAGULATE = "BLOOD_BASE_COAGULATE"


@hook("compile_action")
def coagulate_consent(action, info):
    original = (action.parameters or {}).get("typed") or {}
    if (original.get("option_of") or original.get("source")) != COAGULATE:
        return None
    parameters = copy.deepcopy(action.parameters or {})
    typed = parameters.get("typed") or {}
    rows = typed.get("effects") or []
    def clinical_bleeding(effects):
        changed=False
        for row in effects:
            if row.get('type')=='remove_condition' and row.get('condition')=='bleeding':
                row.update(type='clinical_treatment',category='ordinary_bleeding',operation='coagulate')
                changed=True
            changed=clinical_bleeding(row.get('effects') or []) or changed
        return changed
    changed=clinical_bleeding(rows)
    if any(row.get("type") == "choose_willing" for row in rows):
        return action.model_copy(update={"parameters":parameters}) if changed else None
    gate = [row for row in rows if row.get("type") == "requires_thread"]
    benefits = [row for row in rows if row.get("type") != "requires_thread"]
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
