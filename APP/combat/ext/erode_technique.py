"""Erode Technique answers the particular ordinary benefit being granted.

Uses reaction_rows to retain the owned row's consent, payment and activation;
healing_pending owns Temporary HP, event owns exact temporary modifier/condition
receipts. No HP-healing listener and no scan of unrelated existing benefits.

Printed rule (Tianxia_Sphere_Compendium, Erode Technique rider): "Choose one
benefit created by the triggering effect. Apply one option: reduce Temporary HP
gained by your Proficiency Bonus; ..." and "Erode Technique cannot affect
artifacts, Domains, Secret Inheritances, Formation cores, Realm-defining
transformations, or permanent features."

Fix round H203FIX1F1 (review F1-F5):
- F1  the pending Temporary-HP reduction is aimed at the creature that gains, so
      it carries the same harm metadata the compiled authority option has
      ("applies_to": "target", harmful) and only answers another team's gain.
- F2  a benefit made inside another handler arrives as a nested child event, so
      the event subscription opts into nested delivery; a receipt born from this
      plug-in's own reduction is never eroded again (recursion guard).
- F3  a reduced replacement is bound to the original benefit's whole lifetime:
      when the Concentration technique that made the parked original ends
      mid-turn, the parked original and its replacement stop at once (an evented
      removal, so a replay keeps it), not at a turn boundary.
- F4  one shared source-eligibility decision covers both receipt paths. A source
      the engine cannot resolve at all is treated as an ordinary one (the
      modifier path always read it that way): only a resolvable typed record
      flags the printed exclusion.
- F5  the row carries decision_details (typed_reactions' documented trigger
      keys), so the offered decision names the gaining creature, the ability
      that granted it, the exact benefit, the printed option Use runs, and the
      deadline instead of a generic sentence.
"""
from copy import deepcopy
from . import effect, hook
from .ability_source import source_label
from ..cost_reductions import PREFIX as REDUCTION

ERODE = "TAL_VOID_ERODE_TECHNIQUE"
FIELDS = {"armor_class": 1, "armor_class_vs_melee": 1, "armor_class_vs_ranged": 1,
          "speed_ft": 10, "damage_reduction": "pb", "damage_resistance": "suppress"}
# A cost reduction is named per resource (combat/cost_reductions.py), so it is read by
# its prefix instead of one fixed field. Printed option: "prevent one cost reduction
# from reducing a cost below its listed value." Suppressing the row is the whole
# effect: the cost quote reads that row, so the cost returns to its listed value.
# Erode prints two exclusions beyond the shared source-eligibility categories
# ("Formation cores", "Realm-defining transformations"). "permanent features" is
# already answered by the receipt's own missing expiry.
_EXTRA_EXCLUSIONS = ("Formation core", "Realm-defining transformation", "permanent feature")


def _excluded_source(engine, source_id: str | None) -> bool:
    """Erode's rider exclusion, read from the shared source-eligibility decision (F13 finding 1).

    The printed rider is "Erode Technique cannot affect artifacts, Domains, Secret
    Inheritances, Formation cores, Realm-defining transformations, or permanent
    features." It is the same question ``combat/ext/source_eligibility.py`` already
    answers for Unweave Pattern, Internal Hammer and Seal-Breaking Warmth, so it is
    read from the owner's printed record there instead of from action flags no
    compiled row carries. A source whose record cannot be resolved stays eligible:
    the engine also grants Temporary HP from native pools and fixtures, and refusing
    those would take the printed option away from ordinary grants.
    """
    from . import source_eligibility

    power = source_eligibility.stored_power(engine, source_id)
    if power is None:
        return False
    return source_eligibility.protected_power(*power, permanent_transformations=True,
                                              extra_categories=_EXTRA_EXCLUSIONS)


def _user(engine, actor_id):
    return engine.state.actors.get(actor_id) if engine is not None else None


def _pb(engine, actor_id) -> int:
    user = _user(engine, actor_id)
    return int(getattr(user, "proficiency_bonus", 0) or 0) if user is not None else 0


def _until(engine, actor_id) -> str:
    user = _user(engine, actor_id)
    return f"until the start of {user.display_name}'s next turn" if user is not None \
        else "until the start of the user's next turn"


def _temp_hp_details(engine, actor_id, pending: dict) -> dict | None:
    """What the offered Temporary-HP decision says (F5): about to gain what, reduced to what."""
    subject = engine.state.actors.get(pending.get("subject") or "")
    if subject is None:
        return None
    amount = int(pending.get("amount") or 0)
    bonus = _pb(engine, actor_id)
    return {"affected_id": subject.entity_id,
            "action_name": source_label(engine, pending.get("source")),
            "display_summary": (f"{subject.display_name} is about to gain {amount} Temporary Hit Points. "
                                f"Using it reduces that gain by {bonus} (your Proficiency Bonus): "
                                f"{amount} becomes {max(0, amount - bonus)}.")}


def _benefit_details(engine, actor_id, receipt) -> dict | None:
    """What the offered benefit decision says (F5): the benefit, the option Use runs, the deadline."""
    holder = engine.state.actors.get(receipt[0])
    if holder is None:
        return None
    kind, key = receipt[1], receipt[2]
    from .benefit_suppression import benefits

    label = next((row["label"] for row in benefits(engine, holder) if row["id"] == f"{kind}:{key}"), "")
    if not label:
        return None
    delay = _until(engine, actor_id)
    held = (holder.modifiers if kind == "modifier" else holder.conditions).get(key)
    # A condition (the offered Invisible) has no target field: read the modifier's
    # field only from a modifier, so the decision keeps its exact option wording.
    field = getattr(held, "target_field", "") if held is not None else ""
    origin = held.source_definition_id if held is not None else ""
    if field in ("armor_class", "armor_class_vs_melee", "armor_class_vs_ranged"):
        acted = f"reduce that AC bonus by 1 {delay}"
    elif field == "speed_ft":
        acted = f"reduce that Speed bonus by 10 feet {delay}"
    elif field == "damage_reduction":
        acted = f"reduce that damage reduction by {_pb(engine, actor_id)} (your Proficiency Bonus) {delay}"
    elif field == "damage_resistance":
        acted = f"suppress that Resistance {delay}"
    elif field.startswith(REDUCTION):
        acted = f"prevent that cost reduction from reducing a cost below its listed value {delay}"
    else:
        acted = f"prevent the Invisible condition from that effect {delay}"
    return {"affected_id": holder.entity_id,
            "action_name": source_label(engine, origin),
            "display_summary": (f"{holder.display_name} just gained {label}. Using it runs the one printed "
                                f"option that fits: {acted}. Declining keeps the benefit untouched.")}


@hook("reaction_rows")
def rows(engine, actor_id, block, rows):
    if block != "generic" or not any(r.get("feature_id") == ERODE for r in rows):
        return None
    pending = getattr(engine, "_pending_healing", None)
    benefit = getattr(engine, "_gained_temporary_benefit", None)
    out = []
    specialized = False
    for row in rows:
        if row.get("feature_id") != ERODE:
            out.append(row)
            continue
        if specialized:
            # reaction_menus may expand one compiled row into its five printed modes
            # before this subscriber runs. One receipt offers exactly one applicable
            # option, so the first specialized row answers and the mode copies are
            # dropped; the result must not depend on subscriber load order.
            continue
        if row.get("kind") == "temp_hp_gained" and pending and pending.get("kind") == "temp_hp":
            if _excluded_source(engine, pending.get("source")):
                continue  # the granting ability carries Erode's printed exclusion (F4)
            details = _temp_hp_details(engine, actor_id, pending)
            effects = [
                # The reduction harms the creature it is aimed at (F1): the compiled
                # authority option reads the same ("applies_to": "target"), so the
                # reaction answers a gaining enemy and never an allied grant.
                {"type": "pending_healing_reduction", "applies_to": "target", "harmful": True, "formula": "pb",
                 # Typed marker: pending_healing_effect reads this field, not the prose.
                 "pending_gain": True,
                 "evidence": "reduce Temporary HP gained by your Proficiency Bonus"}]
        elif row.get("kind") == "benefit_gained" and benefit:
            details = _benefit_details(engine, actor_id, benefit)
            effects = [{"type": "erode_gained_benefit", "applies_to": "target"}]
        else:
            continue
        made = deepcopy(row)
        made["effects"] = effects
        if details:
            made["decision_details"] = details
        # One receipt offers exactly its applicable printed option. The other
        # options cannot affect this benefit (e.g. Invisible is not temp HP);
        # the offered decision carries the exact wording instead (F5).
        for key in ("reaction_modes", "option_labels", "option"):
            made.pop(key, None)
        if ":mode:" in str(made.get("consent_source_id") or ""):
            # Already expanded by reaction_menus: the mode is gone, so the row is
            # asked once under its own name, not as an "Erode Technique — <mode>" copy.
            made.pop("consent_source_id", None)
            made["name"] = str(made.get("name") or ERODE).split(" — ")[0]
        specialized = True
        out.append(made)
    return out


@hook("event", nested=True)
def gained(engine, event_type, kwargs):
    if event_type == "CONCENTRATION_ENDED":
        expire_concentrated(engine, kwargs)
        return
    if event_type not in {"MODIFIER_APPLIED", "CONDITION_APPLIED"}:
        return
    if not any(r.get("feature_id") == ERODE for rows in getattr(engine, "typed_reaction_rows", {}).values() for r in rows):
        return
    payload = kwargs.get("payload") or {}
    target = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    if target is None:
        return
    kind = "modifier" if event_type == "MODIFIER_APPLIED" else "condition"
    key = payload.get("modifier_id" if kind == "modifier" else "instance_id")
    held = (target.modifiers if kind == "modifier" else target.conditions).get(key)
    if held is None or held.expires_on in {None, "", "UNTIL_REMOVED"}:
        return
    # This plug-in installs its own reduced replacement as a new receipt event
    # (F2 recursion guard): another response to it would be the plug-in eroding
    # its own work, so the row stays closed for those.
    if held.source_definition_id == ERODE or (getattr(held, "application_id", None) or "").startswith("erode:"):
        return
    if kind == "modifier":
        if held.target_field not in FIELDS and not str(held.target_field).startswith(REDUCTION):
            return
        if isinstance(held.value, int) and held.value <= 0:
            return
    elif held.condition_id != "condition:typed.invisible":
        return
    if _excluded_source(engine, held.source_definition_id):
        return  # "cannot affect artifacts, Domains, Secret Inheritances ..." (F4)
    previous = getattr(engine, "_gained_temporary_benefit", None)
    engine._gained_temporary_benefit = (target.entity_id, kind, key)
    try:
        from ..typed_reactions import on_creature_event
        on_creature_event(engine, target, "benefit_gained", source_id=held.source_definition_id)
    finally:
        engine._gained_temporary_benefit = previous


@effect("erode_gained_benefit", harmful=True)
def reduce_benefit(ctx, eff):
    receipt = getattr(ctx.engine, "_gained_temporary_benefit", None)
    if not receipt or ctx.target is None or receipt[0] != ctx.target.entity_id:
        return
    _, kind, key = receipt
    target = ctx.target
    held = (target.modifiers if kind == "modifier" else target.conditions).get(key)
    if held is None:
        return
    from .benefit_suppression import suppress
    value = held.value if kind == "modifier" else None
    field = held.target_field if kind == "modifier" else None
    if not suppress(ctx.engine, ctx.actor, target, kind + ":" + key, "owner_turn", ctx.source,
                    label=("Erode Technique: this cost reduction is prevented until the start of the user's next turn"
                           if str(field or "").startswith(REDUCTION)
                           else "Erode Technique: this temporary benefit is reduced until the start of the user's next turn")):
        return
    reduction = "suppress" if str(field or "").startswith(REDUCTION) else FIELDS.get(field)
    if kind == "modifier" and isinstance(value, int) and reduction != "suppress":
        amount = int(ctx.numbers.get("pb") or 0) if reduction == "pb" else int(reduction)
        left = max(0, value - amount)
        if left:
            ctx.engine._add_modifier(target, ctx.source, field, held.operation, left, held.applies_to,
                                     expires_on="START_OF_SOURCE_NEXT_TURN", source_actor_id=ctx.actor.entity_id,
                                     application_id="erode:" + key)


def expire_replacements(engine):
    """A reduced replacement cannot outlive the original hidden benefit."""
    from .benefit_suppression import SUPPRESSED
    from .suppressed_effects import alive
    for holder in engine.state.actors.values():
        hidden = {(c.data.get("model") or {}).get("modifier_id") for c in holder.conditions.values()
                  if c.condition_id == SUPPRESSED and c.source_definition_id == ERODE
                  and alive(engine, c.data.get("lifetime") or {})}
        for mid, modifier in list(holder.modifiers.items()):
            application = modifier.application_id or ""
            if (modifier.source_definition_id == ERODE and application.startswith("erode:")
                    and application.removeprefix("erode:") not in hidden):
                engine._remove_modifier_instance(holder, mid, ERODE,
                                                 payload={"modifier_id": mid, "reason": "DURATION_ENDED"})


def expire_concentrated(engine, kwargs):
    """A Concentration technique the parked original came from ends while its reduced replacement is up (F3).

    The replacement expires on Erode's own turn and carries the Erode source, so the concentration cleanup
    (combat/ext/concentration_modifiers.py) that takes an active "+2 AC while you concentrate" off its target
    cannot find it there: a mid-turn end would leave the reduced bonus running until a turn boundary. This
    discards the harmed charge's root at once and files the same CONCENTRATION_ENDED reason on both records, so
    the replay applies these removals without running this subscriber again (combat/effect_endings.py)."""
    payload = kwargs.get("payload") or {}
    source = str(kwargs.get("source_definition_id") or "")
    if not source or payload.get("zone_persists"):
        return  # a power handover (Lingering Conflagration) is not an ending of the technique's effects
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None:
        return
    from .. import concentration
    from .benefit_suppression import SUPPRESSED

    started = payload.get("started_sequence")
    copies = concentration.copies(actor, source, started)
    for holder in engine.state.actors.values():
        for iid, condition in list(holder.conditions.items()):
            if condition.condition_id != SUPPRESSED or condition.source_definition_id != ERODE:
                continue
            model = (condition.data or {}).get("model") or {}
            # The parked original is identified by its technique and copy, exactly as the
            # engine's own Concentration cleanup (combat/concentration.end_conditions) reads
            # it. The modifier's source_actor is whoever filed it, which need not be the
            # concentrating creature (a native grant can omit explicit ownership).
            if model.get("source_definition_id") != source:
                continue
            row_id = model.get("modifier_id") or model.get("instance_id") or ""
            if started is not None and len(copies) > 1 and \
                    concentration.owner_copy(concentration.made_at(str(row_id), model), copies) != int(started):
                continue  # another, still held copy of this technique made it
            for mid, replacement in list(holder.modifiers.items()):
                if replacement.source_definition_id == ERODE and (replacement.application_id or "") == "erode:" + row_id:
                    engine._remove_modifier_instance(holder, mid, ERODE,
                                                     payload={"modifier_id": mid, "reason": "CONCENTRATION_ENDED"},
                                                     expected=replacement)
            engine._remove_condition_instance(holder, iid, ERODE,
                                              payload={"condition_id": SUPPRESSED, "instance_id": iid,
                                                       "reason": "CONCENTRATION_ENDED"}, expected=condition)


@hook("turn_start")
def turn_start(engine, actor):
    expire_replacements(engine)


@hook("turn_end")
def turn_end(engine, actor, *, nominal=False):
    expire_replacements(engine)
