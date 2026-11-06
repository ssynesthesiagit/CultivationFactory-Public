"""Seat menu selections from typed candidate domains, shared by model providers.

An engine candidate can offer a pool of mutually exclusive options. Expand only
that current candidate's authority; never submit the entire pool as a selection.
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import re

from combat.choice_authority import default_option_selection, expand_option_selections, validate_option_selection
from .choices import perceived_names


@lru_cache(maxsize=1)
def printed_rules():
    """Read owner prose, never derive executable option authority from it."""
    return json.loads((Path(__file__).resolve().parents[1] /
                      "authority/typed_mechanics/rules_text.json").read_text())


@lru_cache(maxsize=256)
def follow_up_rule(source):
    """Use an unambiguous authority suffix for legacy follow-up display prose."""
    suffix = source.rsplit('.', 1)[-1]
    rows = [value for key, value in printed_rules().items() if key.rsplit('.', 1)[-1] == suffix]
    return rows[0] if len(rows) == 1 else ""


def expand_menu(menu, engine, view, *, candidates=None):
    """Expand every selection using an unchanged state's prepared candidates.

    Internal callers may reuse the service's validated menu for this engine
    state. Direct callers still enumerate normally; no choices are pruned and
    every selection is validated against its original candidate authority.
    """
    if candidates is None:
        from contextlib import nullcontext
        from combat.placement_menu import query
        # Regenerate the contract the menu actually presents. A deferred CELL
        # row has no destination until its persisted second-stage choice;
        # legacy concrete menus continue to use exhaustive native generation.
        lazy = any((action := engine.action_catalog.get(row['description'].get('source'))) is not None
                   and action.target_kind == 'CELL' and row['description'].get('destination') is None
                   for row in menu.values())
        with query() if lazy else nullcontext():
            candidates = engine.legal_candidates()
    candidates = {c.candidate_id: c for c in candidates}
    names = perceived_names(view)
    result = {}
    for key, row in menu.items():
        candidate = candidates.get(row["candidate_id"])
        if candidate is None:
            continue
        try:
            selections = expand_option_selections(candidate)
        except ValueError:
            # Large combinatorial pools must not stop a model turn. Retain a
            # bounded default/minimum selection and validate it against the
            # original authority, without changing any candidate/domain.
            preferred = list(default_option_selection(candidate))
            for domain in candidate.choice_domains:
                current = sum(o in preferred for o in domain.option_ids)
                for option in domain.option_ids:
                    if current >= domain.minimum_selections:
                        break
                    if option not in preferred:
                        preferred.append(option)
                        current += 1
            selections = (tuple(preferred),)
        action = engine.action_catalog.get(candidate.source_definition_id)
        for selection in selections:
            if validate_option_selection(candidate, selection):
                continue
            if any(o in engine.state.actors and o not in names for o in selection):
                continue
            description = dict(row["description"], options=list(selection))
            if description["action"] == "Move" and candidate.metadata.get("movement_mode") == "fly":
                from .flight_options import movement_label
                own = next(a for a in view["actors"] if a["entity_id"] == view["fighter"])
                description.update(movement_mode="fly", movement_cost_ft=candidate.movement_cost_ft,
                    movement_label=movement_label(own["position"], description["destination"], candidate.movement_cost_ft))
            costs = list(action.costs) if action and not description.get("cost_label") else []
            for domain in candidate.choice_domains:
                for option in selection:
                    costs.extend(domain.option_costs.get(option, {}).items())
            if costs:
                charge = ", ".join(f"{amount} {resource.rsplit(':', 1)[-1].rsplit('.', 1)[-1].replace('_', ' ').title()}"
                                   for resource, amount in costs)
                description["cost_label"] = (description.get("cost_label", "") + "; " + charge).strip('; ')
            if description["action"].startswith("Use optional rider "):
                printed = follow_up_rule(candidate.source_definition_id)
                heading = re.search(r"^#+\s+(.+)", printed, re.M)
                name = (heading[1] if heading else action.display_name if action else
                        candidate.source_definition_id.rsplit('.', 1)[-1].replace('_', ' ').title())
                description["action"] = "Use " + name
                if printed:
                    description["description"] = printed
                elif action and action.damage:
                    dice = action.damage
                    amount = (f"{dice.count}d{dice.sides}" + (f" {dice.modifier:+d}" if dice.modifier else "")
                              if dice.count else str(dice.modifier))
                    description["description"] = f"Deal {amount} damage to the affected creature now."
            if len(selections) > 1 or tuple(selection) != tuple(row["description"]["options"]):
                labels = []
                for domain in candidate.choice_domains:
                    selected = [o for o in domain.option_ids if o in selection]
                    defaults = list(domain.default_option_ids) if not selected else []
                    values = selected or defaults
                    # Entity options are described only by already perceived names.
                    def label(value):
                        return names.get(value, value.replace('_', ' ').title() if ':' not in value else 'offered choice')
                    labels.append(domain.display_name + ": " + (
                        ", ".join(label(o) for o in values) + (" (default)" if defaults else "")
                        if values else "none"))
                description["action"] += ": " + "; ".join(labels)
            # Keep existing stable keys for already complete, unexpanded rows.
            identity = {k: description[k] for k in ("action", "source", "targets", "destination", "options")}
            origin = candidate.metadata.get('effect_origin')
            if origin:
                identity['effect_origin_id'] = origin['id']
            stable = key if len(selections) == 1 and list(selection) == row["description"]["options"] else (
                hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16])
            result[stable] = {"description": description, "candidate_id": row["candidate_id"]}
    return result
