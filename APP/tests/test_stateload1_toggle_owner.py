"""Review blocking #2: the owned-record match set must equal main's rule, key in owned or any(own.startswith(key)).

A non-boundary string prefix of an owned id (e.g. "fire" for owned "fireball") is a match on main; the
boundary-only rule dropped it. The check compares the real authority index against the brute-force rule."""
from combat import tabletop


def _brute(index, owned):
    return {key for key in index if key in owned or any(own.startswith(key) for own in owned)}


def test_owned_match_set_equals_main_prefix_rule_on_real_authority():
    tabletop._OWNED_KEYS.clear()
    index = tabletop._authority_index()
    names = tabletop._mechanic_names()
    picks = sorted(index)[:40:3] + [key for key in sorted(index) if key[:-1] in index][:20]
    owned = frozenset(picks + [key[:-1] for key in picks if len(key) > 3])
    tabletop._OWNED_KEYS.clear()
    tabletop._toggle_owner("Plain: x", {"owned_ids": sorted(owned)})
    got = next(value for cache_key, value in tabletop._OWNED_KEYS.items() if cache_key[0] == owned)
    assert got == _brute(index, owned)
    assert names is not None


def test_non_boundary_prefix_of_an_owned_id_still_matches():
    tabletop._OWNED_KEYS.clear()
    index = tabletop._authority_index()
    key = next(k for k in sorted(index) if len(k) > 4)
    owned = frozenset([key + "zz"])
    tabletop._toggle_owner("Plain: x", {"owned_ids": sorted(owned)})
    got = next(value for cache_key, value in tabletop._OWNED_KEYS.items() if cache_key[0] == owned)
    assert key in got
