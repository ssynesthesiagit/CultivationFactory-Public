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
    # Existing diagnostic/event labels remain stable; player lists render choices
    # from this identity rather than treating those labels as variant data.
    return action.model_copy(update={"variant": value})


def settle_families(actions):
    """Settle every row's family identity against the rows that really exist.

    A family is a set of executable rows that differ by a choice (another way to pay, an augment, a
    centering, a recipient ...) and share variant.base_key. A row may keep a choice-less identity only
    as that family's own base (its source id is the base key); a single action's own
    base_key = its source id is harmless and the menu draws it as a plain row.

    A compile_actions plug-in that copies a compiled action to make a separately named action
    (Sound-Sovereign's longer Soundwalk Step, Swift Guardian's free Challenge) copies the source row's
    identity too. The copy has no choices of its own, so it is not a choice of the source action:
    without this it joins the source's card as a second "Standard" chip and loses its own name.
    Clones therefore carry no family; the base of a real family is annotated here even when it was
    built without a variant, because the compiler only annotates families as they appear. Used by
    compile_character for every compiled catalog (and therefore the table, sheet, pre-fight and AI
    lists that read it).
    """
    actions = list(actions)
    families = {}
    for action in actions:
        value = action.variant
        if value is None:
            continue
        family = families.setdefault(value.base_key, {'label': value.base_label, 'choices': False})
        family['choices'] = family['choices'] or bool(value.choices)
    settled = []
    for action in actions:
        value = action.variant
        if value is None:
            family = families.get(action.source_definition_id)
            if family and family['choices']:
                settled.append(action.model_copy(update={'variant': variant(action.source_definition_id, family['label'])}))
            else:
                settled.append(action)
        elif value.choices or action.source_definition_id == value.base_key:
            settled.append(action)
        else:
            settled.append(action.model_copy(update={'variant': None}))
    return settled


def extend_variant(action, selected):
    """Add/replace an axis on an already annotated action (e.g. Mass + augment)."""
    value = action.variant or variant(action.source_definition_id, action.display_name)
    parts = [part for part in value.choices if part.axis != selected.axis]
    return with_variant(action, value.base_key, value.base_label, [*parts, selected])
