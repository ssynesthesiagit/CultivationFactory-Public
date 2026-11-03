"""Star-Piercing Greatbow source classification (seam only; no record is certified).

Brace the Heavens, Fix the Star, Celestial Firing Platform, Sky-Nailing Arrow,
Fortress-Piercing Shot and Star-Piercing Catastrophe all say "greatbow-family
weapon", but no printed source defines that family. Checked (2026-10-19):
09_RULES/Source_Text has no "Greatbow-Family Weapon" definition, and the typed
authority / rules_text.json only reference the phrase. The mundane catalog has
no greatbow entry. Until a printed definition or owner catalog field exists,
this module classifies nothing by name: an item is a greatbow family weapon only
when its authoritative catalog record carries an explicit reviewed
`weapon_family == 'greatbow'`. Owning a Source does not grant proficiency.
"""
from . import hook


def source_family(item):
    """Return 'greatbow' only for an explicit reviewed family field; else None.

    Names, labels, Bow proficiency, Heavy/Two-Handed properties and parenthetical
    translations never establish the family.
    """
    return 'greatbow' if str(item.get('weapon_family') or '') == 'greatbow' else None


@hook('weapon_source_family')
def greatbow_source_family(item, family):
    """Answer only for a Greatbow-family query; False rejects non-greatbow items."""
    if family != 'greatbow':
        return None
    return source_family(item) == family
