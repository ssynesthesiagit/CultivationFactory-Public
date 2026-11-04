"""Refined: Moonspring Root's maximum-Hit-Point increase (Verdant Returning-Spring).

Printed clause (Tianxia Foundations Catalog v0.4C, "Refined: Moonspring Root"):
"When Refined, the Hit Point increase from Verdant Spring Vessel becomes twice
your Proficiency Bonus." Sibling Foundations print their Vessel as "your maximum
Hit Points increase by your Proficiency Bonus" and are counted when the character
is created (their reviewed_final records keep an empty effect list, e.g.
foundation.moon_mirror_still_water_v0_2B.moon_mirror_soul_vessel). This Foundation's
source section prints no Verdant Spring Vessel feature of its own, so the reviewed
typing invents no separate base bonus; the printed Refined amount -- twice the
owner's Proficiency Bonus -- is added once to the admitted maximum Hit Points while
the Foundation is Refined, before the bundle is sealed. This mirrors the existing
compile_bundle seam used by combat/ext/foundations3.py for Red Lotus Heart-Ash.

Inert for characters that do not own the Refined rider: no other character's
Hit Points change.
"""
from . import hook

RIDER = 'foundation.verdant_returning_spring_v0_2B.refined_moonspring_root'
BLOCK = 'foundation_moonspring_root'


@hook('compile_passives')
def compile_moonspring(passives, info):
    """Seal this owned Refined rider so the bundle pass can find it after compilation."""
    if RIDER not in info['owned_ids']:
        return passives
    return [*passives, {'block': BLOCK, 'feature_id': RIDER}]


@hook('compile_bundle')
def moonspring_maximum_hp(bundle, info):
    """Add the printed twice-Proficiency-Bonus maximum Hit Points while Refined.

    The saved bundle seals the result, so a reload never reapplies the increase;
    a character that does not own the Refined rider is returned unchanged.
    """
    if not any(row.get('feature_id') == RIDER and row.get('block') == BLOCK
               for row in bundle.get('typed_passives', [])):
        return bundle
    pb = int(info['numbers']['pb'])
    bundle['actor_template']['maximum_hp'] = int(bundle['actor_template']['maximum_hp']) + 2 * pb
    return bundle
