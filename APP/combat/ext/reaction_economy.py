"""Reaction economy: reactions that do not spend the Reaction, additional Reactions, and reaction cost waivers (rider lane C15,
2026-09-30; BLOCKED_CENSUS.md row 17) -- shared helper answering two documented hooks from feature-block rows, so a new talent
needs only data.

  reaction_spend(engine, reactor, row, commit)   (typed_reactions.reaction_waived / spend_reaction)
  generic_reaction_costs(engine, reactor, other, row, costs)

Rows (combat/rules/feature_blocks.d/*.json, block "reaction_economy", compiled as the owner's passive rows):
  {"block": "reaction_economy", "grant": "free", "covers": {...}, "while_state": "<state>"}
        "once per round, you may use Static Guard without spending your Reaction" (Lightning Sovereign Incarnation): one
        covered reaction a round does not spend the Reaction -- used first, so the Reaction stays for something else; it also
        lets that reaction be taken when the Reaction is already spent.
  {"block": "reaction_economy", "grant": "extra", "covers": {...}, "while_state": "<state>"}
        "gain one additional Reaction each round" (Adamant Guardian Incarnation; "usable only for Scoundrel talents"): once a
        round, a covered reaction may be taken after the Reaction is spent. The engine still lets one reaction answer one
        trigger; the ordinary Reaction is always used first.
  {"block": "reaction_economy", "grant": "no_cost", "covers": {...}, "while_state": "<state>"}
        "you may use Twist of Fate without spending CP" (Fate-Sovereign Incarnation): a covered generic reaction costs nothing.
        (Twist of Fate is once a round by its own rule.)
  {"block": "reaction_economy", "grant": "focus_instead", "pay": {"resource_id": "...", "amount": 1,
   "until_owner_turn": true}, "covers": {...}}
        "you may expend Martial Focus to use this without spending your Reaction" (Shield's Active Defense, Drunken
        Style's Swaying Guard): the covered reaction does not spend the Reaction and costs ``pay.amount`` of
        ``pay.resource_id`` (default 1 Martial Focus) instead -- ``pay`` is a nested dict so the row's own flat cost keys
        are untouched. ``pay.until_owner_turn`` blocks every covered use after payment until the owner's turn, where the text adds one
        ("Once you do so, you cannot use Swaying Guard again until the start of your next turn"); a printed sentence
        with no extra limit leaves it off and the resource itself is the limit. Manual/Ask-me owners choose the
        Reaction or Focus through the existing journalled choice transport. AI uses its Reaction first, then Focus.
  "grants": [{...}, {...}]  several grants of one feature (Chaos-Step Incarnation: a free Swaying Guard and an extra Reaction).
  covers  {"features": ["<mechanic id>", ...]} the named reactions; {"sphere": "<sphere id>"} every reaction of that sphere's
          talents ("Scoundrel talents", "Drunken Style talents"); {"punchline": true} any Jester Punchline (a reaction whose
          trigger needs a Foil mark: combat/ext/jester.py); {"any": true} every reaction.
  while_state  only while that timed state of the owner is on (combat/ext/states.py; the talent's own "state" row).
Uses are counted per round in the owner's turn flags, so a saved fight keeps them. Single grants retain
"_round_reaction_economy:<feature>"; multiple grants append a stable fingerprint of the grant's rules, independently
of their list order. A legacy feature-wide flag conservatively blocks all its grants for that recorded round only.
Inert: a creature without such a row is never answered.
Users: the Sovereign/Incarnation talents listed in combat/rules/feature_blocks.d/riders_c15.json.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import hook

BLOCK = "reaction_economy"
FLAG = "_round_reaction_economy:"
COOLDOWN = "reaction_economy_until_turn:"


def _paid_grants(engine, actor, row):
    return [g for g in _rows(engine, actor) if g.get("grant") == "focus_instead"
            and covers(g, row) and _on(engine, actor, g)]


def owns_paid_payment(engine: Any, actor: Any, row: dict[str, Any]) -> bool:
    """Whether typed economy owns this alternative, even with a Reaction left.

    Shield's legacy payment adapter uses this to defer consent, quote and commit
    to one provider. No owned active grant leaves legacy saved bundles unchanged.
    """
    return bool(_paid_grants(engine, actor, row))


@hook("row_allowed")
def allowed(engine, actor, row):
    """A paid-use deadline covers every subsequent use, regardless of payment."""
    for grant in _paid_grants(engine, actor, row):
        if (grant.get("pay") or {}).get("until_owner_turn") and actor.turn_flags.get(COOLDOWN + str(grant["feature_id"])):
            return False
    return None


def _affordable(engine, actor, grant):
    from ..typed_reactions import _holds
    pay = grant.get("pay") or {}
    return _holds(engine, actor, str(pay.get("resource_id") or "resource:core.martial_focus"),
                  max(1, int(pay.get("amount") or 1)))


def _usable_paid_grants(engine, actor, row):
    """Pure shared eligibility for consent, text, preview and committed payment.

    Saved once-per-round grants retain their counters; affordability alone
    must never advertise an exhausted alternative to the ordinary Reaction.
    """
    if allowed(engine, actor, row) is False:
        return []
    return [g for g in _paid_grants(engine, actor, row)
            if (not (g.get("pay") or {}).get("once_per_round") or _unused(engine, actor, g))
            and _affordable(engine, actor, g)]


@hook("reaction_consent")
def payment_consent(engine, row, actor, checkpoint):
    """Ask once for both consent and payment, using the journalled choice transport."""
    grants = _usable_paid_grants(engine, actor, row)
    if not grants:
        return None
    # A free/extra grant already selected by the shared economy has no paid choice.
    if any(g.get("grant") in ("free", "extra") and covers(g, row) and _on(engine, actor, g)
           and _unused(engine, actor, g) and (g["grant"] == "free" or not actor.reaction_available)
           for g in _rows(engine, actor)):
        return None
    grant = grants[0]
    from ..typed_reactions import ask_key
    from ..resource_labels import resource_name
    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return False
    pay = grant.get("pay") or {}
    cost = f"{max(1, int(pay.get('amount') or 1))} {resource_name(pay.get('resource_id') or 'resource:core.martial_focus')}"
    options = (["reaction"] if actor.reaction_available else []) + ["focus"]
    limit = f" If you pay {cost}, you cannot use this ability again until the start of your next turn." if pay.get("until_owner_turn") else ""
    trigger = getattr(engine, "_reaction_trigger", None) or {}
    action_name = trigger.get("action_name") or "the triggering attack"
    attacker = engine.state.actors.get(trigger.get("actor_id") or trigger.get("source_actor_id") or "")
    threat = f"{attacker.display_name}'s {action_name}" if attacker is not None else action_name
    context = {**trigger, "spend_options": options,
               "automatic_spend": options[0], "labels": {"reaction": "Spend your Reaction", "focus": f"Spend {cost}; no Reaction spent"},
               "feature_id": row["feature_id"], "name": row.get("name"),
               "cost": (f"Choose your Reaction or {cost}" if actor.reaction_available else f"{cost}; no Reaction") + limit,
               "payment_note": "Paying Martial Focus keeps your Reaction available." + limit,
               "prompt": f"{row.get('name', 'This ability')}: choose how {actor.display_name} pays to defend against {threat}, or pass." + limit}
    decision = engine._reaction_decision(intent, ask_key(checkpoint, engine), actor.entity_id,
                                        "reaction:typed." + row["feature_id"], context=context)
    if decision is None or decision.selection != "USE":
        return False
    engine.__dict__.setdefault("_reaction_economy_payment", {})[(actor.entity_id, row["feature_id"])] = (
        getattr(engine, "_transaction_id", None), decision.option_ids[0])
    return True


@hook("decision_text")
def payment_text(engine, context, printed_rules):
    if (context.get("choice_trigger") or {}).get("spend_options"):
        return None  # spend_choice owns the selectable payment summary
    feature = str(context.get("reaction_source_id", "")).removeprefix("reaction:typed.")
    actor = engine.state.actors.get(context.get("reactor_id"))
    if actor is None:
        return None
    grants = _usable_paid_grants(engine, actor, {"feature_id": feature})
    grant = next(iter(grants), None)
    if grant is None or actor.reaction_available:
        return None
    from ..resource_labels import resource_name
    pay = grant.get("pay") or {}
    cost = f"{max(1, int(pay.get('amount') or 1))} {resource_name(pay.get('resource_id') or 'resource:core.martial_focus')}; no Reaction"
    return {"cost": cost, "table_note": "After paying, you cannot use this ability again until the start of your next turn." if pay.get("until_owner_turn") else ""}


@hook("compile_block")
def _compile(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    base = {key: value for key, value in spec.items() if key not in {"block", "resource", "why", "grants"}}
    grants = spec.get("grants") or [{}]
    compiled = []
    for grant in grants:
        result = {**row, **base, **grant, "keeps_compiling": True}
        if len(grants) > 1:
            result["reaction_grant_key"] = _grant_identity(result)
        compiled.append(result)
    return compiled


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    from ..typed_reactions import _rows as rows

    grants = rows(engine, actor.entity_id, BLOCK)
    # Old saved bundles predate the compiled identity. Derive it without changing the saved rows.
    counts: dict[str, int] = {}
    for grant in grants:
        feature = str(grant.get("feature_id"))
        counts[feature] = counts.get(feature, 0) + 1
    return [{**grant, "reaction_grant_key": _grant_identity(grant)}
            if counts[str(grant.get("feature_id"))] > 1 and not grant.get("reaction_grant_key") else grant for grant in grants]


def _grant_identity(grant: dict[str, Any]) -> str:
    identity = {key: grant.get(key) for key in ("grant", "covers", "while_state")}
    # Only grants that print a limit take part, so every existing grant keeps its original fingerprint
    # (and therefore its saved per-round counter).
    if (grant.get("pay") or {}).get("once_per_round"):
        identity["once_per_round"] = True
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]


def _sphere(feature_id: str) -> str:
    from ..typed_numbers import authority_mechanics

    return str((authority_mechanics().get(feature_id) or {}).get("sphere_id") or "")


def covers(grant: dict[str, Any], row: dict[str, Any]) -> bool:
    """Whether a grant's ``covers`` names this reaction row."""
    wanted = grant.get("covers") or {}
    feature = str(row.get("feature_id") or "")
    if wanted.get("any"):
        return True
    if feature in set(wanted.get("features") or ()):
        return True
    if wanted.get("punchline") and str(row.get("requires_mark") or "").startswith("Foil: "):
        return True
    return bool(wanted.get("sphere")) and _sphere(feature) == wanted["sphere"]


def _on(engine: Any, actor: Any, grant: dict[str, Any]) -> bool:
    state = grant.get("while_state")
    if not state:
        return True
    from .states import active

    return active(engine, actor, state) is not None


def _unused(engine: Any, actor: Any, grant: dict[str, Any]) -> bool:
    legacy = FLAG + str(grant.get("feature_id"))
    round_number = int(engine.state.round_number)
    return actor.turn_flags.get(legacy) != round_number and actor.turn_flags.get(_usage_key(grant)) != round_number


def _usage_key(grant: dict[str, Any]) -> str:
    """Persistent counter identity; existing single-grant rows/saves retain their original key."""
    key = FLAG + str(grant.get("feature_id"))
    return key + ":" + str(grant["reaction_grant_key"]) if grant.get("reaction_grant_key") else key


@hook("reaction_spend")
def waive(engine: Any, reactor: Any, row: dict[str, Any], commit: bool) -> str | None:
    if allowed(engine, reactor, row) is False:
        return None
    grants = [g for g in _rows(engine, reactor) if g.get("grant") in ("free", "extra")]
    if not grants:
        return _focus_instead(engine, reactor, row, commit)
    for grant in grants:
        if grant["grant"] == "extra" and reactor.reaction_available:
            continue  # the ordinary Reaction first
        if not (covers(grant, row) and _on(engine, reactor, grant) and _unused(engine, reactor, grant)):
            continue
        if commit:
            reactor.turn_flags[_usage_key(grant)] = int(engine.state.round_number)
            from . import note

            name = grant.get("name") or str(grant.get("feature_id")).rsplit(".", 1)[-1]
            what = row.get("name") or "the reaction"
            note(engine, str(grant.get("feature_id")), reactor,
                 f"{name}: {reactor.display_name} uses {what} without spending its Reaction (once this round)." if grant["grant"] == "free"
                 else f"{name}: {reactor.display_name} uses its additional Reaction of this round for {what}.")
        return "free"
    return _focus_instead(engine, reactor, row, commit)


def _focus_instead(engine: Any, reactor: Any, row: dict[str, Any], commit: bool) -> str | None:
    """Pay the selected alternative once, or the automatic fallback after a spent Reaction.

    The preview is pure. Consent journals the player's payment; commit consumes
    a transaction-bound receipt. The owner's ordinary turn-flag reset removes
    the integer deadline at their next turn. Legacy once_per_round data keeps
    its old interpretation for saved bundles; newly compiled rows use the
    owner-turn deadline. Inert without an owned, affordable grant.
    """
    selected = None
    if commit:
        receipt = engine.__dict__.setdefault("_reaction_economy_payment", {}).pop((reactor.entity_id, row.get("feature_id")), None)
        if receipt and receipt[0] == getattr(engine, "_transaction_id", None):
            selected = receipt[1]
    if selected == "reaction" or (reactor.reaction_available and selected != "focus"):
        return None
    for grant in _usable_paid_grants(engine, reactor, row):
        pay = grant.get("pay") or {}
        resource = str(pay.get("resource_id") or "resource:core.martial_focus")
        amount = max(1, int(pay.get("amount") or 1))
        if commit:
            if pay.get("until_owner_turn"):
                reactor.turn_flags[COOLDOWN + str(grant["feature_id"])] = 1
            if pay.get("once_per_round"):
                reactor.turn_flags[_usage_key(grant)] = int(engine.state.round_number)
            engine._spend_resource(reactor, resource, amount, str(grant.get("feature_id") or row.get("feature_id") or ""))
            from ..resource_labels import resource_name
            from . import note

            name = grant.get("name") or row.get("name") or str(grant.get("feature_id") or "").rsplit(".", 1)[-1]
            what = row.get("name") or name
            note(engine, str(grant.get("feature_id")), reactor,
                 f"{name}: {reactor.display_name} spends {amount} {resource_name(resource)} to use {what} "
                 f"without spending its Reaction.")
        return "free"
    return None


@hook("generic_reaction_costs")
def no_cost(engine: Any, reactor: Any, other: Any, row: dict[str, Any], costs: Any) -> list[dict[str, Any]] | None:
    if not costs:
        return None
    for grant in _rows(engine, reactor):
        if grant.get("grant") == "no_cost" and covers(grant, row) and _on(engine, reactor, grant):
            return []
    return None
