"""Structured action variants used by the compiler, Meld, Protection and Mandates.

Metadata never changes legality, payments, effects or executable ids. A family may
have no currently legal base action; clients must still expose every legal child.
Costs on a choice are signed deltas (including resource substitutions); action.costs
remains the sole authority for payment.
"""
from collections import Counter

from .gate2_runtime_models import ActionVariant, VariantChoice


def cost_delta(costs, base_costs=()):
    total = Counter()
    for pool, amount in costs:
        total[pool] += amount
    for pool, amount in base_costs:
        total[pool] -= amount
    return tuple((pool, amount) for pool, amount in sorted(total.items()) if amount)


def choice(axis, key, label, costs=()):
    return VariantChoice(axis=axis, key=key, label=label, costs=tuple(costs))


def variant(base_key, base_label, choices=()):
    return ActionVariant(base_key=base_key, base_label=base_label, choices=tuple(choices))


def variant_name(value):
    labels = [part.label for part in value.choices]
    return value.base_label + (" + " + " + ".join(labels) if labels else "")


def with_variant(action, base_key, base_label, choices=()):
    """Annotate an existing executable action; do not clone or replace its rules."""
    value = variant(base_key, base_label, choices)
    return action.model_copy(update={"variant": value, "display_name": variant_name(value)})


def extend_variant(action, selected):
    """Add/replace an axis on an already annotated action (e.g. Mass + augment)."""
    value = action.variant or variant(action.source_definition_id, action.display_name)
    parts = [part for part in value.choices if part.axis != selected.axis]
    return with_variant(action, value.base_key, value.base_label, [*parts, selected])
