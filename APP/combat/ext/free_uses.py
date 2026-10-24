"""Use an ability "without an action" while a talent's state is on (rider lane 1, 2026-09-29: "i want everything we can automated").

"Once on each of your turns, you may use Gather Charge without an action" (Court of Charged Paths), "... Lightning Lash or Gather
Charge without an action" (Lightning Sovereign Incarnation): a free copy of the ability that is offered while the state is running
and once used is gone for the turn (or the round).  It is declared on the talent's own ``state`` effect (combat/ext/states.py):

  {"type": "state", "name": "court_of_charged_paths", "duration": "one_minute",
   "free_use": [{"of": ["Gather Charge"], "once": "turn"}]}          # "once": "turn" (default) or "round"

A declaration may add ``"costless": true`` (the copy costs nothing) and ``"keep_economy": true`` (the copy keeps the ability's own
Action/Bonus Action) for "use Empty Step once per turn without spending CP or Stamina" (rider lane C4: Void's Court of the Empty
Horizon and Void-Sovereign Incarnation); such a copy is named "... (no cost)". Without them a copy is as before.

At compile time each named ability of the character (an option of a choose-one ability, "Lightning Lash: Arc", counts as that
ability) gets a sibling action with no economy ("... (free)") that costs what the ability costs and does what it does.  Every
sibling of one declaration shares its one use; it is offered only while ``states.active`` says the state is on
(``candidate_allowed``), and ``technique_used`` spends the use.
"""

from __future__ import annotations

import re
from typing import Any

from . import hook

# Other plug-ins add printed grants this module owns the machinery for. A provider
# receives compile-time ``info`` and returns declarations with the same keys:
#   {"of": ["Gather Current"], "once": "turn", "state": "<label>", "key": "<unique>",
#    "always": True, "available": callable(engine, actor) -> bool}
# ``always`` means the grant belongs to an owned feature rather than a running
# state; ``available`` is an optional pure gate (for example "after the Attack
# action"). Consumers: combat/ext/br_variants.py. No new hook point is added.
PROVIDERS: list = []
PREDICATES: dict = {}


def register(provider) -> None:
    """Register a declaration provider (called once at plug-in import)."""
    if provider not in PROVIDERS:
        PROVIDERS.append(provider)


def register_predicate(name: str, predicate) -> None:
    """Register a pure availability gate by name; ``predicate(engine, actor) -> bool``."""
    PREDICATES[name] = predicate


def available(engine: Any, actor: Any, rule: dict[str, Any]) -> bool:
    """Public read: is a compiled free-use declaration offered right now? No state change."""
    return _available_grant(engine, actor, rule) is not None


def mark_spent(engine: Any, actor: Any, grant: dict[str, Any]) -> None:
    """Public: record that this declaration's once-per-turn/round use is spent."""
    actor.turn_flags[_flag(engine, grant)] = True


def _declarations(info: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key in info["owned_ids"]:
        mechanic = info["mechanics"].get(key) or {}
        rows = [*(mechanic.get("effects") or []), *(row for option in mechanic.get("options") or [] for row in option.get("effects") or [])]
        for row in rows:
            if isinstance(row, dict) and row.get("type") == "state" and row.get("free_use"):
                out.extend({"state": str(row["name"]), "mechanic": key, "range_for": row.get("range_for") or {}, **spec}
                           for spec in row["free_use"])
    for provider in PROVIDERS:
        out.extend(provider(info) or [])
    return out


def _live(engine: Any, actor: Any, grant: dict[str, Any]) -> bool:
    """Whether this grant is running and still has its once-per limit free."""
    if actor.turn_flags.get(_flag(engine, grant)):
        return False
    if grant.get("always"):
        gate = grant.get("requires")
        if not gate:
            return True
        predicate = PREDICATES.get(gate)  # an unregistered gate fails closed, never raises (BRS1F12R 6)
        return bool(predicate(engine, actor)) if predicate else False
    from . import states
    return states.active(engine, actor, grant["state"]) is not None


@hook("compile_actions")
def _free_copies(info: dict[str, Any]) -> list[Any] | None:
    declared = _declarations(info)
    if not declared:
        return None
    from ..gate2_runtime_models import EconomyKind

    made = []
    for index, spec in enumerate(declared):
        wanted = [str(name) for name in spec.get("of") or []]
        for action in info["actions"]:
            name = str(action.display_name)
            if action.economy == EconomyKind.NONE or not any(name == want or name.startswith(want + ":") for want in wanted):
                continue
            typed = dict((action.parameters or {}).get("typed") or {})
            feet = (spec.get("range_for") or {}).get(typed.get("source"))
            if feet is not None:
                typed["range_ft"] = int(feet)
            # "without spending CP or Stamina" (Void's Empty Step in a Court or Incarnation): the same economy, no cost.
            costless, keep = bool(spec.get("costless")), bool(spec.get("keep_economy"))
            made.append(action.model_copy(update={
                "source_definition_id": f"{action.source_definition_id}+free{index}",
                "display_name": f"{name} ({'no cost' if costless and keep else 'free'})",
                "economy": action.economy if keep else EconomyKind.NONE, **({"costs": ()} if costless else {}),
                "range_ft": int(feet) if feet is not None else action.range_ft,
                "parameters": {**action.parameters, "typed": typed, "free_use": {"state": spec["state"], "once": spec.get("once") or "turn",
                                                                  "key": f"{spec.get('mechanic') or spec.get('key') or 'free_use'}:{index}", "of": wanted,
                                                                  **({"always": True} if spec.get("always") else {}),
                                                                  **({"title": str(spec["title"])} if spec.get("title") else {}),
                                                                  **({"requires": spec["requires"]} if spec.get("requires") else {})},
                               **({"state_range_rule": {"state": spec["state"]}} if feet is not None else {})}}))
    # A menu row describes an effect, not its grant. Keep independent grants
    # (and their once-per limits) behind one mechanically identical action.
    from ..canonical import canonical_sha256
    unique = {}
    for action in made:
        parameters = dict(action.parameters)
        rule = parameters.pop("free_use")
        # Range-granted rows must not merge with ordinary-range rows. Within
        # each ranged group, preserve the source gates as alternatives below.
        range_rule = parameters.pop("state_range_rule", None)
        identity = action.model_dump(mode="json")
        identity.pop("source_definition_id")
        identity["parameters"] = parameters
        identity["range_requires_grant"] = range_rule is not None
        key = canonical_sha256(identity)
        previous = unique.get(key)
        grants = [rule] if previous is None else [*previous.parameters["free_use"]["grants"], rule]
        # Range gates belong to their source states, which can differ from the
        # free-use grant (for example a free copy of a state-range variant).
        # Keep ranged/unranged rows distinct and union only actual range gates.
        ranged_states = list((previous.parameters.get("state_range_rule") or {}).get("states", [])) if previous else []
        if range_rule is not None:
            ranged_states.extend(range_rule.get("states", [range_rule.get("state")]))
        ranged_states = list(dict.fromkeys(state for state in ranged_states if state))
        base = action if previous is None else previous
        unique[key] = base.model_copy(update={"parameters": {
            **parameters, "free_use": {**grants[0], "grants": grants},
            **({'state_range_rule': {'states': ranged_states}} if ranged_states else {})}})
    return list(unique.values()) or None


def _flag(engine: Any, rule: dict[str, Any]) -> str:
    return f"free_use_{rule['key']}" + (f"_round_{engine.state.round_number}" if rule["once"] == "round" else "")


def _available_grant(engine: Any, actor: Any, rule: dict[str, Any]) -> dict[str, Any] | None:
    return next((grant for grant in rule.get("grants", [rule]) if _live(engine, actor, grant)), None)


@hook("candidate_allowed")
def _offered_while_the_state_lasts(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    rule = ((action.parameters or {}).get("free_use") if action is not None else None)
    if not rule:
        return None
    return False if _available_grant(engine, actor, rule) is None else None


@hook("technique_used")
def _spend_the_free_use(ctx: Any) -> None:
    rule = (ctx.action.parameters or {}).get("free_use")
    if rule:
        from .needle import ask
        available = [grant for grant in rule.get('grants', [rule]) if _live(ctx.engine, ctx.actor, grant)]
        # Spend the least flexible grant by default; all alternatives remain
        # available through a journaled choice for human and model seats.
        preferred = sorted(available, key=lambda g: (len(g.get('of', [])), g['state'], g['key']))
        selected = ([available[0]['key']] if len(available) == 1 else
                    ask(ctx.engine, getattr(ctx, 'intent', None), 'free-use:' + ctx.action.source_definition_id,
                        ctx.actor, CHOICE, [g['key'] for g in available],
                        preferred=[g['key'] for g in preferred],
                        labels={g['key']: grant_label(g) +
                                f' — spend this {g.get("once", "turn")}\'s free use of ' + ' or '.join(g.get('of', [ctx.action.display_name]))
                                for g in available},
                        name=ctx.action.display_name,
                        prompt=f'Choose which free use funds {ctx.actor.display_name}\'s {ctx.action.display_name}.',
                        prompt_context={'action_name': ctx.action.display_name, 'affected_id': ctx.actor.entity_id}))
        grant = next((g for g in available if selected and g['key'] == selected[0]), None)
        if grant is not None:
            ctx.actor.turn_flags[_flag(ctx.engine, grant)] = True


def grant_label(grant: dict) -> str:
    """Player-facing source name for a grant: its declared title, else its state name in plain words.

    The state key is an engine identifier (for example br_variant:<authority id>), so it is never shown raw:
    a grant without a title (a talent's own state, such as "court_of_charged_paths") reads as "Court Of Charged Paths".
    """
    title = grant.get('title')
    if title:
        return str(title)
    raw = str(grant.get('state') or '')
    if raw.startswith('br_variant:'):
        # the authority id itself is never player text: name the printed variant (its picker label), resolved by id
        from factory_authoring import body_refining_variants as authority
        row = authority.variant(raw.split(':', 1)[1]) or {}
        return str(row.get('picker_label') or row.get('variant_name') or 'Body Refining variant')
    state = raw.split(':')[-1]
    words = re.sub(r'[_\-\s]+', ' ', state).strip()
    return words.title() if words else 'Active talent state'


CHOICE = 'choice:free_uses.funding'


@hook('choice_options')
def funding_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    from .needle import option_spec
    return option_spec(choice_id, context, CHOICE)
