"""Star-Piercing Greatbow source classification.

The compendium's Greatbow-Family Weapon definition is narrower than Bow
proficiency. Classification uses the actual catalog item, never an action's
display label. Other Sources can explicitly accept an item through the shared
``weapon_source_family`` query; owning this Scripture grants no proficiency.
"""
from . import hook


def source_family(item):
    """Classify only a printed Greatbow type; return None for unspecified items.

    A Bow proficiency group, Heavy property or Two-Handed property alone does
    not establish Greatbow eligibility. In particular a shortbow does not
    become a Greatbow by being wielded with both hands.
    """
    import re

    classes = {
        'greatbow', 'war bow', 'heavy longbow', 'siege bow designed for one cultivator',
        'great composite bow', 'dragon horn bow', 'cultivated heavy bow',
    }
    normalize = lambda value: re.sub(r'[^a-z0-9]+', ' ', str(value).lower()).strip()
    # Match whole source classifications, including parenthetical translations;
    # substring matching would admit crossbows and "not a greatbow" labels.
    name = str(item.get('name') or '')
    labels = [name, *re.findall(r'\(([^()]*)\)', name)]
    labels += [item.get('weapon_type') or '', item.get('weapon_family') or '']
    return 'greatbow' if any(normalize(label) in classes for label in labels) else None


@hook('weapon_source_family')
def greatbow_source_family(item, family):
    """The exact printed list governs only a Greatbow-family query."""
    if family != 'greatbow':
        return None
    return source_family(item) == family
