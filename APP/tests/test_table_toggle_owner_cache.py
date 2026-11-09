"""The table answers "which ability does this choice button belong to" for every button on every refresh; the
answer is cached (2026-10-06: ~150 million checks per refresh made a 15-creature fight take 20-40 s to draw).
The cache must give exactly the uncached answer and must not leak between characters."""
from combat import tabletop


def _owner(name, bundle):
    tabletop._TOGGLE_OWNERS.clear(); tabletop._OWNED_KEYS.clear()
    return tabletop._toggle_owner(name, bundle)


def _some_feature():
    index = tabletop._authority_index()
    names = tabletop._mechanic_names()
    key = next(k for k in sorted(index) if names.get(k) and ":" not in names[k])
    return key, names[key]


def test_cached_answer_matches_a_fresh_answer():
    key, name = _some_feature()
    bundle = {"owned_ids": [key]}
    fresh = _owner(f"{name.title()}: option", bundle)
    assert fresh == key
    assert tabletop._toggle_owner(f"{name.title()}: option", bundle) == fresh  # served from the cache


def test_the_cache_is_per_character():
    key, name = _some_feature()
    mine = tabletop._toggle_owner(f"{name.title()}: option", {"owned_ids": [key]})
    other = tabletop._toggle_owner(f"{name.title()}: option", {"owned_ids": []})
    assert mine == key
    assert other == _owner(f"{name.title()}: option", {"owned_ids": []})


def test_buttons_without_an_option_are_not_cached():
    assert tabletop._toggle_owner("Plain Button", {"owned_ids": []}) is None
