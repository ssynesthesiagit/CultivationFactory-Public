"""Pure area recipient policy shared by compilation, execution and risk previews.

Unscoped harmful areas default to enemies. Only explicit inclusive wording
(each/every/all creature) includes everyone. Origin cones/lines exclude their
user regardless of wording. Owner data may override other recipients. Explicit self
effects (costs, drawbacks and benefits) are not area payloads.
"""
import hashlib
import json
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


def origin_shape_excludes_user(area):
    """A cone/line emitted by its user never includes that user, even if inclusive.

    Remotely placed shapes and explicit self costs are separate delivery paths.
    """
    return area.get("shape") in {"cone", "line"} and not area.get("placed")


def _static_damage_expression(row):
    """Comparable printed amount, or None when fallback cannot prove a match.

    Formula/level-scaled amounts need the row's own recipient evidence: a
    sibling's numeric clause cannot establish their recipient permission.
    """
    from .typed_amounts import dice_from_text
    dice = row.get("dice") or {}
    if not isinstance(dice, dict):
        dice = dice_from_text(dice)
        if dice is None:
            return None
    if (row.get("formula") or row.get("dice_by_cl") or dice.get("count_formula")
            or dice.get("bonus_formula")):
        return None
    flat = int(row.get("flat") or 0) + int(dice.get("bonus") or 0)
    if dice:
        if dice.get("count") is None or dice.get("sides") is None:
            return None
        return f"{dice['count']}d{dice['sides']}" + (f"{flat:+d}" if flat else "")
    return str(flat) if row.get("flat") is not None else None


def _harmful_recipient_phrase(effects, text):
    """Read harm's recipient clauses, never a sibling benefit's chosen roster.

    A row's recipient_text, then its own evidence, owns that payload's scope.
    Whole-action fallback must identify a compatible payload clause even when
    only one printed scope remains. Ambiguous prose grants no permission.
    """
    clauses = re.split(r"[.;\n]+", text or "")
    phrases = []
    for row in effects or ():
        if not isinstance(row, dict) or not _harmful(row):
            continue
        if row.get("recipient_text"):
            phrases.append(str(row["recipient_text"]))
            continue
        own = str(row.get("evidence") or "")
        if _printed_scope(own):
            phrases.append(own)
            continue
        nested = _harmful_recipient_phrase(children(row), "")
        if _printed_scope(nested):
            phrases.append(nested)
            continue
        kind = row.get("type")
        cue = (r"saving throws?" if kind == "save" else
               r"disadvantage" if kind == "disadvantage" else
               r"\bdamage\b" if kind in {"damage", "extra_damage", "half_damage"} else
               r"saving throws?|\bdamage\b|disadvantage|knocked prone|cannot|can't")
        candidates = [clause for clause in clauses if re.search(cue, clause, re.I)
                      and _printed_scope(clause)]
        # Compatibility is required even for a single inclusive clause: its
        # permission cannot spill into a sibling's generic/enemies-only packet.
        if kind in {"damage", "extra_damage", "half_damage"}:
            # Sentence punctuation does not isolate grammatical damage clauses:
            # "Each creature takes 5 fire damage, and creatures take 1d6 fire
            # damage" grants permission only to the first packet. Without own
            # evidence, multiple damage occurrences cannot prove association.
            # Decline that fallback; explicit row evidence above remains valid.
            candidates = [clause for clause in candidates
                          if len(re.findall(r"\bdamage\b", clause, re.I)) == 1]
            types = row.get("damage_types") or ()
            if types:
                candidates = [clause for clause in candidates if any(
                    re.search(r"\b" + re.escape(str(dtype)) + r"\s+damage\b", clause, re.I)
                    for dtype in types)]
            expression = _static_damage_expression(row)
            if expression is None:
                # Unknown/formula amounts cannot borrow another packet's scope.
                # Own evidence/recipient_text was already handled above.
                candidates = []
            else:
                # Unnumbered inclusive prose is still legal. If prose states an
                # amount, match that damage expression rather than a range/cost
                # or the modifier inside a different dice expression.
                amount = r"\b(\d+(?:d\d+)?(?:\s*[+-]\s*\d+)?)\s+(?:\w+\s+)?damage\b"
                candidates = [clause for clause in candidates
                              if not (amounts := re.findall(amount, clause, re.I))
                              or expression in [re.sub(r"\s+", "", value).lower() for value in amounts]]
        if len({_printed_scope(clause) for clause in candidates}) == 1:
            phrases.extend(candidates)
        else:
            phrases.append(own)
    return " ".join(phrases)


def _unrestricted_choice(phrase):
    # Do not match the noun substring inside hostile/allied/willing choices.
    phrase = " ".join(phrase.split())
    return bool(re.search(
        r"(?<!hostile )(?<!allied )(?<!friendly )(?<!willing )(?<!enemy )"
        r"\bcreatures? (?:of your choice|you choose)\b|\bany number of creatures\b", phrase, re.I))


def _payload_key(row):
    """Stable identity of immutable compiled payload data, including its branches."""
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _printed_scope(phrase):
    if re.search(r"\b(?:hostile|enemy) creatures?\b", phrase, re.I):
        return "hostile"
    if re.search(r"\b(?:allied|friendly) creatures?\b|\ballies\b", phrase, re.I):
        return "allies"
    if re.search(r"\b(?:each|all|every|any) other creatures?\b|\bcreatures? (?:other than|except) you\b", phrase, re.I):
        return "other_creatures"
    if _unrestricted_choice(phrase) or re.search(
            r"\b(?:each|all|every|any) creatures?\b|\bincluding (?:you|yourself)\b", phrase, re.I):
        return "all"
    return None


def printed_recipient_seal(effects, text, area):
    """Build-time seal of a harmful area's printed recipient permission.

    The authority builder reads the printed text once and stores this dict on
    the area record as `printed_recipient_seal`. Compilation and execution then
    read only the seal, so public CI's scrambled rules text cannot change scope.
    Keys are the content hashes used by `harmful_payload_scopes`.
    """
    if not area or not area.get("size_ft"):
        return None
    policies, _roots = _payload_scopes(effects, text or "", {})
    if not policies:
        return None  # no harmful payload: nothing to seal
    phrase = _harmful_recipient_phrase(effects, text or "")
    other = bool(re.search(
        r"\b(?:each|all|every|any) other creatures?\b|\bcreatures? (?:other than|except) you\b", phrase, re.I))
    inclusive = bool(re.search(
        r"\b(?:each|all|every|any) (?:other )?creatures?\b|\bincluding (?:you|yourself)\b", phrase, re.I))
    return {"inclusive": inclusive or other, "other_creatures": other,
            "chosen": _unrestricted_choice(phrase), "payload_scopes": policies,
            "cues": _phrase_cues(_tail_phrase(effects, text, area))}


def _tail_phrase(effects, text, area):
    """Whole-action wording read for the recipient fallback cues (build-time or legacy)."""
    payload = [row for row in rows(effects) if row.get("applies_to") != "self"]
    return " ".join([text or "", str(area.get("text") or ""),
                     *(str(row.get("recipient_text") or row.get("evidence") or "") for row in payload)])


def _phrase_cues(phrase):
    """Named recipient cues the fallback needs; computed once, stored in the seal."""
    return {
        "enemy": bool(re.search(r"\b(?:hostile creatures?|enem(?:y|ies))\b", phrase, re.I)),
        "allies": bool(re.search(r"\b(?:allies|willing creatures?)\b", phrase, re.I)),
        "choice": bool(re.search(r"\bcreatures? (?:of your choice|you choose)\b|\bany number of creatures\b", phrase, re.I)),
        "in_area": bool(re.search(
            r"\b(?:each|all|every) creatures?\b|(?<!hostile )\bcreatures? (?:in|inside|within)\b", phrase, re.I)),
        "self": bool(re.search(
            r"\b(?:including you|including yourself|you and (?:all |each |every )?(?:other )?creatures)\b", phrase, re.I)),
    }


def _payload_scopes(effects, text, previous, sealed=None):
    """Seal each top-level harmful payload's printed permission.

    A sibling's benefit or inclusive damage never widens another payload. Keys
    are content hashes, so reload retains the same scope. Nested branches inherit
    scope through the resolution Context, avoiding collisions between identical
    damage rows under differently scoped saves. Explicit self effects are separate.
    `sealed` is the build-time payload map; when given, prose is not read.
    """
    result, roots = {}, []
    def visit(row):
        if not _harmful(row):
            return None
        key = _payload_key(row)
        if sealed is not None:
            printed = sealed.get(key)
        else:
            printed = _printed_scope(_harmful_recipient_phrase([row], text))
        permission = printed or previous.get(key)
        scope = permission or {"enemies_in_area": "hostile", "allies_in_area": "allies",
                               "ally": "allies", "allies": "allies"}.get(effect_recipient_scope(row), "hostile")
        result[key] = scope
        return scope
    for row in effects or ():
        if isinstance(row, dict) and (scope := visit(row)) is not None:
            roots.append(scope)
    return result, roots


def harmful_effect_scope(area, effect, *, inherited=None):
    """Resolve a payload-specific printed scope before an action-wide default."""
    if not area.get("size_ft"):
        return None
    policies = area.get("harmful_payload_scopes") or {}
    if policies:
        if area.get("printed_recipient_seal") is not None:
            # Sealed at authority build: execution never reads the payload's prose.
            return policies.get(_payload_key(effect)) or inherited or area.get("harmful_recipient_override")
        return (policies.get(_payload_key(effect)) or
                _printed_scope(str(effect.get("recipient_text") or effect.get("evidence") or "")) or
                inherited or area.get("harmful_recipient_override"))
    return area.get("harmful_recipient_override") or inherited


def scoped_area(area, effects, text="", *, typed=None):
    """General area policy; typed supplies source/sphere for owner data rulings.

    Defaults are inert for benefits and explicit self effects.
    Policy is recomputed for legacy compiled metadata as well as new actions.
    """
    if not area or not area.get("size_ft"):
        return area
    # Owner rulings are read lazily (the file is parsed only on change) and are
    # used by both the reviewed-roster branch and the martial/payload branch.
    from .area_recipient_rules import is_martial, recipient_override
    # A zone trigger's reviewed roster ("any" / "ally" / "hostile") is an
    # explicit scope for the delayed packet it resolves, not an unscoped
    # default: it outranks action-wide printed wording and recomputation must
    # not narrow it back to enemies-only. An owner ruling
    # (area_recipient_overrides, via recipient_override) still outranks the
    # reviewed roster, exactly as it outranks an action's own printed scope, so
    # a ruling that narrows a roster-declared zone to enemies is never ignored.
    if area.get("trigger_roster"):
        context = (typed.get("area_recipient_context") or typed) if typed is not None else None
        ruling = recipient_override(context) if context is not None else None
        if ruling is None:
            scope = roster_scope(area["trigger_roster"])
            # The roster bounds the packet's harm; a sibling benefit is not part
            # of it (same rule as the owner-ruling branch below and the unscoped
            # mixed packet). ``recipients`` is what decides whom the non-harmful
            # rows reach, so a hostile roster must not narrow a mixed packet's
            # healing/buff to enemies only.
            beneficial_payload = any(not _harmful(row) and row.get("applies_to") != "self"
                                     for row in effects or () if isinstance(row, dict))
            return {**area, "recipients": "all" if beneficial_payload or scope != "hostile" else "hostile",
                    "harmful_recipients": scope, "harmful_recipient_override": scope,
                    "include_self": beneficial_payload or scope != "hostile",
                    "exclude_self": not beneficial_payload and scope == "hostile"}
        scope = "all" if ruling["recipients"] == "everyone" else "hostile"
        beneficial_payload = any(not _harmful(row) and row.get("applies_to") != "self"
                                 for row in effects or () if isinstance(row, dict))
        area = {key: value for key, value in area.items() if key not in {
            "harmful_payload_scopes", "explicit_harmful_recipients", "chosen_harmful_recipients"}}
        return {**area, "recipients": "all" if beneficial_payload else scope,
                "harmful_recipients": scope, "harmful_recipient_override": scope,
                "include_self": beneficial_payload or scope == "all",
                "exclude_self": not beneficial_payload and scope != "all"}
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
    payload = [row for row in rows(effects) if row.get("applies_to") != "self"]
    # A typed creatures_in_area token describes geometry, not permission for
    # friendly fire. Seal actual inclusive printed wording at compilation so
    # execution, reactions and previews retain it without needing the prose.
    explicit_scope = {effect_recipient_scope(row) for row in payload if _harmful(row)}
    seal = area.get("printed_recipient_seal")
    if seal is not None:
        # Authority-built records: the permission was sealed from printed text
        # at build time. Compilation never re-reads prose, so text is ignored.
        chosen = bool(seal.get("chosen"))
        other_creatures = bool(seal.get("other_creatures"))
        inclusive = bool(seal.get("inclusive")) or other_creatures
    else:
        # Legacy records built outside the authority carry no seal; their scope
        # is read from the text supplied (compile-time rules text, or nothing).
        phrase = _harmful_recipient_phrase(effects, text or str(area.get("text") or ""))
        chosen = _unrestricted_choice(phrase)
        # Sealed choice metadata is only a fallback when no recipient prose remains.
        # Recomputing a qualified or mixed action must discard an obsolete wide choice.
        if not text and not _printed_scope(phrase):
            chosen = bool(area.get("chosen_harmful_recipients"))
        inclusive = bool(re.search(
            r"\b(?:each|all|every|any) (?:other )?creatures?\b|\bincluding (?:you|yourself)\b", phrase, re.I))
        other_creatures = bool(re.search(
            r"\b(?:each|all|every|any) other creatures?\b|\bcreatures? (?:other than|except) you\b", phrase, re.I))
        # Compilation can recover a payload's scope from whole-action prose that
        # is absent at execution/reload. Retain its sealed, content-keyed permission
        # only when no prose remains; new generic wording must still be recomputed.
        if not text and not phrase.strip():
            sealed = set((area.get("harmful_payload_scopes") or {}).values())
            inclusive = inclusive or bool(sealed & {"all", "other_creatures"})
            other_creatures = other_creatures or "other_creatures" in sealed
    inclusive = inclusive or other_creatures
    # Forge replaces the primary talent's delivery. Otherwise printed inclusive
    # wording outranks a model-derived enemies_in_area token on the same row.
    forged_delivery = bool(typed and typed.get("forged_from"))
    unscoped = not explicit_scope - {None, "target", "creatures_in_area"}
    if typed is not None and harmful:
        typed = typed.get("area_recipient_context") or typed
        override = recipient_override(typed)
        if override or (is_martial(typed) and not (inclusive or chosen)):
            scope = "all" if override and override["recipients"] == "everyone" else "hostile"
            area = {key: value for key, value in area.items() if key != "harmful_payload_scopes"}
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
    if harmful and not forged_delivery and (inclusive or chosen):
        policies, roots = _payload_scopes(effects, text or str(area.get("text") or ""),
                                         area.get("harmful_payload_scopes") or {},
                                         sealed=(seal or {}).get("payload_scopes") if seal is not None else None)
        area = {key: value for key, value in area.items() if key not in {
            "harmful_recipient_override", "explicit_harmful_recipients", "chosen_harmful_recipients"}}
        common = len(set(roots)) == 1 and roots[0] in {"all", "other_creatures"}
        return {**area, "recipients": "all", "harmful_recipients": "all",
                "harmful_payload_scopes": policies,
                "include_self": beneficial_payload or "all" in roots,
                "exclude_self": not beneficial_payload and "all" not in roots,
                **({"harmful_recipient_override": "all"} if common else {}),
                **({"chosen_harmful_recipients": True} if chosen else
                   {"explicit_harmful_recipients": "other_creatures" if other_creatures else "every_creature"}
                   if common else {})}
    if harmful and area.get("surface_bound"):
        # A hazard on a surface is the battlefield itself, not an aim: every
        # creature the ground covers is affected, its creator included. The
        # reviewed "Area: ... on a surface" marker is what makes Molten Terrain
        # (and the other surface-bound grounds) work this way; the printed
        # Furnace Step exemption exists precisely because your own Molten
        # Terrain otherwise deals you its hazard.
        return {**area, "recipients": "all", "exclude_self": False, "include_self": True}
    if harmful and unscoped:
        # Recompute obsolete all/include_self metadata too: generic "creatures
        # in the cone" is enemies-only, even when the origin square is inside.
        # A mixed helpful/opaque payload keeps its full geometric roster, while
        # every harmful packet and its reactions use the enemies-only scope.
        return {**area, "recipients": "all" if beneficial_payload else "hostile",
                "harmful_recipients": "hostile", "harmful_recipient_override": "hostile",
                "include_self": beneficial_payload, "exclude_self": not beneficial_payload}
    if "recipients" in area and "exclude_self" in area and \
            (not beneficial_payload or "harmful_recipients" in area):
        # Normalize older compiled creature-wide policies without reparsing text.
        # Mixed membership alone does not make an enemy-only payload hit its user.
        scope = area.get("harmful_recipients", area["recipients"])
        if scope in {"all", "creatures_in_area"} and not area.get("include_self"):
            return {**area, "include_self": True, "exclude_self": False}
        return area  # already scoped by the compiler; menu refreshes do no text parsing
    if not harmful:
        return area
    cues = seal["cues"] if seal is not None else _phrase_cues(_tail_phrase(effects, text, area))
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
        elif cues["enemy"] and not scopes - {None, "target"}:
            recipients = "hostile"
        elif cues["allies"] and not scopes - {None, "target"}:
            recipients = "allies"
        elif cues["choice"]:
            recipients = "all"
        elif "creatures_in_area" in scopes or cues["in_area"]:
            recipients = "all"
        elif "allies_in_area" in scopes:
            recipients = "allies"
        else:
            recipients = "hostile"
    recipients = {"enemies_in_area": "hostile", "creatures_in_area": "all",
                  "allies_in_area": "allies"}.get(recipients, recipients)
    includes_user = recipients == "all" or bool(area.get("include_self")) or cues["self"]
    return {**area, "recipients": "all" if beneficial_payload else recipients,
            "exclude_self": False if beneficial_payload else not includes_user,
            **({"harmful_recipients": recipients} if beneficial_payload else {}),
            **({"include_self": True} if includes_user else {})}


def harmful_area_subject_allowed(actor, subject, area, effect, *, explicit_self=False,
                                 recipient_is_creature=True, inherited=None):
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
    if is_self and origin_shape_excludes_user(area):
        return False
    if explicit_self and is_self:
        return not effect.get("exclude_self")
    scope = effect.get("applies_to")
    if policy := harmful_effect_scope(area, effect, inherited=inherited):
        scope = policy
        if scope == "other_creatures":
            if is_self:
                return False
            scope = "all"
        if is_self and scope == "hostile":
            return False
    # Sealed payload policies use hostile/all/allies, while typed rows use
    # *_in_area aliases. Both are resolved scopes, not action-default fallbacks.
    if scope not in {"hostile", "all", "enemies_in_area", "creatures_in_area", "allies_in_area", "ally", "allies"}:
        scope = area.get("harmful_recipients", area.get("recipients", "hostile"))
    if is_self:
        return not effect.get("exclude_self") and (scope in {"all", "creatures_in_area"}
                                                    or (bool(area.get("include_self")) and effect.get("applies_to") != "enemies_in_area"))
    if scope in {"hostile", "enemies_in_area"}:
        return subject.team_id != actor.team_id
    if scope in {"ally", "allies", "allies_in_area"}:
        return subject.team_id == actor.team_id
    return scope in {"all", "creatures_in_area"}


def roster_scope(who):
    """Recipient scope for a trigger roster the reviewed data declares.

    ``who`` is the reviewed ``roster`` of a zone trigger ("any", "ally",
    "hostile"), never the compiler's derived ``who`` policy, so it also scopes
    the delayed packet the trigger resolves. Returns the area policy name, or
    None when the trigger declares no reviewed roster (the caller then keeps the
    derived printed/owner policy).
    """
    return {"any": "all", "ally": "allies", "hostile": "hostile"}.get(str(who or "").strip().lower())


def delayed_area_context(engine, zone, effects, *, who=None):
    """Transient recipient context for delayed zone packets and risk previews.

    Recover source/primary sphere from the recorded source profile or originating
    action, including its sealed printed recipient scope. Return no fields for
    non-harmful zones. Costs, trigger attribution and geometry stay intact.

    ``who`` is the trigger's reviewed roster (its ``roster`` key, see
    roster_scope): when it is given it scopes the delayed packet, so a reviewed
    "any"/"ally" trigger is not narrowed to the enemies-only default of an
    unscoped harmful area. A compiler-derived ``who`` is not a reviewed roster
    and must not be passed here; the printed/sealed scope decides instead.
    """
    action = getattr(engine, "action_catalog", {}).get(zone.source_definition_id)
    original = (action.parameters.get("typed") or {}) if action is not None else {}
    profile = zone.trigger_profile.get("source_profile") or {}
    if action is None and not profile:
        return {}
    identity = {"source": original.get("source") or profile.get("mechanic_id") or zone.source_definition_id,
                "sphere": original.get("sphere") or profile.get("sphere_id"),
                "forged_from": original.get("forged_from")}
    area = {**(original.get("area") or {}),
            "size_ft": int(zone.trigger_profile.get("size_ft") or 5),
            "shape": zone.trigger_profile.get("shape") or "sphere"}
    scope = roster_scope(who)
    if scope is not None and any(_harmful(row) for row in effects or () if isinstance(row, dict)):
        # The reviewed roster is the packet's explicit scope; scoped_area is the
        # one place that turns it into recipient fields (and keeps it through a
        # later recomputation for the same packet).
        area = {**area, "trigger_roster": str(who).strip().lower()}
    area = scoped_area(area, effects, typed=identity)
    if not area.get("harmful_recipient_override") and not area.get("harmful_payload_scopes"):
        return {}
    return {"area": area, "area_recipient_context": identity}
