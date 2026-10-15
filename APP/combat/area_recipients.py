"""Pure area recipient policy shared by compilation, execution and risk previews.

Harmful martial areas default to enemies even with creature-wide wording.
Owner data may override harm recipients. Other printed creature-wide scopes include everyone,
including their user inside the shape. Explicit self
effects (costs, drawbacks and benefits) are not area payloads.
"""
import re

from .effect_harm import rows, children, classify_effect


def _harmful(row, *, saving_throw=False):
    return classify_effect(row, saving_throw=saving_throw, ignore_self=True) is True


def effect_recipient_scope(row, inherited=None):
    """Payload scope for policy/reactions, including a zone trigger's who.

    Explicit scopes override inherited ones; target binds to its enclosing
    recipient. Trigger records use the zone's existing any/ally/hostile terms.
    """
    scope = row.get("applies_to", inherited)
    if not row.get("type") and "who" in row and "applies_to" not in row:
        scope = {"any": "creatures_in_area", "ally": "allies_in_area",
                 "hostile": "enemies_in_area"}.get(row["who"], scope)
    return inherited if scope == "target" and inherited is not None else scope


def scoped_area(area, effects, text="", *, typed=None):
    """General area policy; typed supplies source/sphere for owner data rulings.

    Defaults are inert for benefits, explicit self effects and non-martial rows.
    Policy is recomputed for legacy compiled metadata as well as new actions.
    """
    if not area or not area.get("size_ft"):
        return area
    # Explicit printed scopes are sealed into newly reviewed action geometry.
    # Missing metadata keeps the predecessor martial/global policy untouched.
    printed = area.get("explicit_harmful_recipients")
    if printed in {"other_creatures", "every_creature"}:
        return {**area, "recipients": "all", "harmful_recipients": "all",
                "harmful_recipient_override": "all", "include_self": printed == "every_creature",
                "exclude_self": printed == "other_creatures"}
    beneficial_payload = any(not _harmful(row) and row.get("applies_to") != "self"
                             for row in effects or () if isinstance(row, dict))
    harmful = any(_harmful(row) for row in effects or () if isinstance(row, dict))
    if typed is not None and harmful:
        from .area_recipient_rules import is_martial, recipient_override
        typed = typed.get("area_recipient_context") or typed
        override = recipient_override(typed)
        if override or is_martial(typed):
            scope = "all" if override and override["recipients"] == "everyone" else "hostile"
            return {**area, "recipients": "all" if beneficial_payload else scope,
                    "harmful_recipients": scope, "harmful_recipient_override": scope,
                    "include_self": beneficial_payload or scope == "all",
                    "exclude_self": not beneficial_payload and scope != "all"}
        if "harmful_recipient_override" in area:
            # Removing a non-martial owner ruling restores printed scopes,
            # even when the saved compiled action contains the previous policy.
            area = {key: value for key, value in area.items() if key not in {
                "recipients", "harmful_recipients", "harmful_recipient_override",
                "include_self", "exclude_self"}}
    if "recipients" in area and "exclude_self" in area and \
            (not beneficial_payload or "harmful_recipients" in area):
        # Normalize older compiled creature-wide policies without reparsing text.
        # Mixed membership alone does not make an enemy-only payload hit its user.
        scope = area.get("harmful_recipients", area["recipients"])
        if scope in {"all", "creatures_in_area"} and not area.get("include_self"):
            return {**area, "include_self": True, "exclude_self": False}
        return area  # already scoped by the compiler; menu refreshes do no text parsing
    payload = [row for row in rows(effects) if row.get("applies_to") != "self"]
    if not harmful:
        return area
    phrase = " ".join([text, str(area.get("text") or ""),
                       *(str(row.get("recipient_text") or row.get("evidence") or "") for row in payload)])
    # Older typed saves put the printed scope on their damage branch. Inherit
    # that only when the enclosing payload has no explicit area scope.
    def payload_scopes(row):
        if not _harmful(row):
            return set()
        scope = effect_recipient_scope(row)
        if scope in {"enemies_in_area", "creatures_in_area", "allies_in_area"}:
            return {scope}
        return {scope} | {value for child in children(row) for value in payload_scopes(child)}
    scopes = {scope for row in effects or () if isinstance(row, dict)
              for scope in payload_scopes(row)}
    # Unknown extension effects own their recipient filtering. Keep their full
    # geometric roster, just as for built-in benefits; never infer hostility
    # merely because another payload in the action damages enemies.
    recipients = area.get("recipients")
    if recipients is None:
        if {"enemies_in_area", "allies_in_area"} <= scopes:
            recipients = "all"
        elif "enemies_in_area" in scopes and "creatures_in_area" not in scopes:
            recipients = "hostile"
        elif "allies_in_area" in scopes and "creatures_in_area" not in scopes:
            recipients = "allies"
        elif re.search(r"\b(?:hostile creatures?|enem(?:y|ies))\b", phrase, re.I) and not scopes - {None, "target"}:
            recipients = "hostile"
        elif re.search(r"\b(?:allies|willing creatures?)\b", phrase, re.I) and not scopes - {None, "target"}:
            recipients = "allies"
        elif re.search(r"\bcreatures? (?:of your choice|you choose)\b|\bany number of creatures\b", phrase, re.I):
            recipients = "all"
        elif "creatures_in_area" in scopes or re.search(
            r"\b(?:each|all|every) creatures?\b|(?<!hostile )\bcreatures? (?:in|inside|within)\b", phrase, re.I):
            recipients = "all"
        elif "allies_in_area" in scopes:
            recipients = "allies"
        else:
            recipients = "hostile"
    recipients = {"enemies_in_area": "hostile", "creatures_in_area": "all",
                  "allies_in_area": "allies"}.get(recipients, recipients)
    includes_user = recipients == "all" or bool(area.get("include_self")) or bool(re.search(
        r"\b(?:including you|including yourself|you and (?:all |each |every )?(?:other )?creatures)\b", phrase, re.I))
    return {**area, "recipients": "all" if beneficial_payload else recipients,
            "exclude_self": False if beneficial_payload else not includes_user,
            **({"harmful_recipients": recipients} if beneficial_payload else {}),
            **({"include_self": True} if includes_user else {})}


def harmful_area_subject_allowed(actor, subject, area, effect, *, explicit_self=False,
                                 recipient_is_creature=True):
    """Per-payload harm scope for executor subjects and technique reactions.

    Mixed action membership is only geometry. The owner martial/data ruling
    bounds harmful payloads; otherwise explicit scopes override the default.
    User inclusion belongs to harm, not benefits.
    Non-area callers and explicit self costs keep their established semantics.
    Non-creature recipients compare their owner by team without treating that
    owner identity as the creature standing at the area's center.
    """
    if not area.get("size_ft") or effect.get("applies_to") == "self":
        return True
    is_self = recipient_is_creature and subject.entity_id == actor.entity_id
    if explicit_self and is_self:
        return not effect.get("exclude_self")
    scope = effect.get("applies_to")
    if area.get("harmful_recipient_override"):
        scope = area["harmful_recipient_override"]
        if is_self and scope == "hostile":
            return False
    if scope not in {"enemies_in_area", "creatures_in_area", "allies_in_area", "ally", "allies"}:
        scope = area.get("harmful_recipients", area.get("recipients", "hostile"))
    if is_self:
        return not effect.get("exclude_self") and (scope in {"all", "creatures_in_area"}
                                                    or (bool(area.get("include_self")) and effect.get("applies_to") != "enemies_in_area"))
    if scope in {"hostile", "enemies_in_area"}:
        return subject.team_id != actor.team_id
    if scope in {"ally", "allies", "allies_in_area"}:
        return subject.team_id == actor.team_id
    return scope in {"all", "creatures_in_area"}


def delayed_area_context(engine, zone, effects):
    """Transient recipient context for delayed zone packets and risk previews.

    Recover source/primary sphere from the recorded source profile or originating
    action, including old zones. Return no fields unless an owner/martial harmful
    ruling applies. Costs, trigger attribution, geometry and saved state stay intact.
    """
    action = getattr(engine, "action_catalog", {}).get(zone.source_definition_id)
    original = (action.parameters.get("typed") or {}) if action is not None else {}
    profile = zone.trigger_profile.get("source_profile") or {}
    if action is None and not profile:
        return {}
    identity = {"source": original.get("source") or profile.get("mechanic_id") or zone.source_definition_id,
                "sphere": original.get("sphere") or profile.get("sphere_id"),
                "forged_from": original.get("forged_from")}
    area = {"size_ft": int(zone.trigger_profile.get("size_ft") or 5),
            "shape": zone.trigger_profile.get("shape") or "sphere"}
    area = scoped_area(area, effects, typed=identity)
    if not area.get("harmful_recipient_override"):
        return {}
    return {"area": area, "area_recipient_context": identity}
