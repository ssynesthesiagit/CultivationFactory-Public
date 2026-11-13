"""A named pool is linked to an ability by its prose or by a structured resource reference.

The public export rewrites prose fields (evidence, trigger, cost text). A pool linked only through prose is compiled in
the checkout and silently lost in the public tree. The structured references (cost resource, effect resource_id,
min_resource) survive the rewrite, so a pool they name must still be compiled. The owner check still decides which
pools a character can have at all.
"""
from combat.factory_compiler import _named_pools

SUBPATH = "tianxia.subpath.body.black_thorn_demon_body"
FEATURE = SUBPATH + ".feature.crown_of_black_thorns"
SPINE_ID = "resource:named.demon_spine"
SPINE = {"name": "Demon Spine", "kind": "pool", "max": "pb", "start": 0, "duration": "scene",
         "owners": ["Subpath: " + SUBPATH]}


def _mechanics(prose: str = "") -> dict:
    return {FEATURE: {"subpath_id": SUBPATH, "activation": {"trigger": prose},
                      "effects": [{"kind": "spend_resource", "resource_id": SPINE_ID, "amount": 1}]}}


def _names(rows) -> list:
    return [row["name"] for row in rows]


def test_structured_reference_compiles_pool_with_scrubbed_prose():
    """The export's scrambled prose names no pool, yet the Crown's spend_resource names the Spine."""
    rows = _named_pools([FEATURE], _mechanics("Whwun you upga Dyowt Slwfks"), {"spine": SPINE}, {"pb": 4}, None)
    assert _names(rows) == ["Demon Spine"]
    assert rows[0]["resource_id"] == SPINE_ID
    assert rows[0]["definition"].maximum == 4 and rows[0]["definition"].initial == 0


def test_reference_does_not_bypass_owner_check():
    """A reference to a pool of a subpath the character does not have compiles nothing."""
    other = dict(SPINE, owners=["Subpath: tianxia.subpath.body.other"])
    assert _named_pools([FEATURE], _mechanics(), {"spine": other}, {"pb": 4}, None) == []


def test_unreferenced_unmentioned_pool_stays_out():
    """Negative control: an owned pool that the ability neither names nor references is not compiled."""
    unrelated = {"name": "Brood", "kind": "pool", "max": 7, "start": 0, "owners": ["Subpath: " + SUBPATH]}
    mechanics = {FEATURE: {"subpath_id": SUBPATH, "activation": {"trigger": "Nothing relevant"}, "effects": []}}
    assert _named_pools([FEATURE], mechanics, {"brood": unrelated}, {"pb": 4}, None) == []
