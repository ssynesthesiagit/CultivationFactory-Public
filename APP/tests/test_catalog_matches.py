"""Catalog matching caches only immutable action identities, not fight state."""
from types import SimpleNamespace as NS

import pytest

from combat.catalog_queries import catalog_matches
from combat.ext import (alchemy_field_effects, magma_crust, pressure_points_second_pass,
                        save_choices, wrestling_piledriver, wrestling_twin)


def action(owner, typed=None, **params):
    return NS(owner_id=owner, parameters={"typed": typed or {}, **params})


def engine(catalog=None):
    poison = NS(condition_id="condition:typed.poisoned",
                data={"origin_save": {"ability": "CON", "dc": 12}})
    actors = {"a": NS(entity_id="a", active=True, conditions={"p": poison}),
              "b": NS(entity_id="b", active=True, conditions={})}
    return NS(action_catalog=dict(catalog or {}), state=NS(actors=actors), typed_passive_rows={})


def test_cache_reuses_and_tracks_catalog_edits():
    e = engine({"one": action("a", {"yes": True}), "two": action("b")})
    calls = []
    def predicate(a):
        calls.append(a)
        return a.parameters["typed"].get("yes", False)
    first = e.action_catalog["one"]
    for _ in range(3):
        assert catalog_matches(e, "test", predicate) == (first,)
    assert len(calls) == 2
    added = action("b", {"yes": True})
    e.action_catalog["three"] = added
    assert catalog_matches(e, "test", predicate) == (first, added)
    replacement = action("a")
    e.action_catalog["one"] = replacement
    assert catalog_matches(e, "test", predicate) == (added,)
    del e.action_catalog["three"]
    assert catalog_matches(e, "test", predicate) == ()
    assert set(e._catalog_matches["test"]) == {"one", "two"}
    assert len(calls) == 4


def test_predicate_exception_not_cached():
    e = engine({"one": action("a")})
    calls = []
    def fail(a):
        calls.append(a)
        raise ValueError("broken")
    for _ in range(2):
        with pytest.raises(ValueError, match="broken"):
            catalog_matches(e, "test", fail)
    assert len(calls) == 2


@pytest.mark.parametrize("reverse", [False, True])
def test_wrestling_provider_keys_are_distinct(reverse):
    e = engine({"pile": action("a", piledriver_runtime=True),
                "twin": action("b", {"twin_runtime": True})})
    checks = [(wrestling_piledriver.reactors, ("a",)), (wrestling_twin.reactors, ("b",))]
    if reverse:
        checks.reverse()
    for provider, expected in checks:
        assert provider(e) == expected


@pytest.mark.parametrize("provider,typed,missing,present", [
    (pressure_points_second_pass.second_pass_choosers,
     {"effects": [{"type": "pp_recovery"}]}, (), ("a", "b")),
    (save_choices.potential_targets,
     {"effects": [{"type": "save", "target_choice": True}]}, (), ("a", "b")),
    (magma_crust.heat_choosers,
     {"effects": [{"type": "magma_heat_pressure"}]}, (), ("a",)),
    (alchemy_field_effects.poison_choice_reactors,
     {"effects": [{"type": "alchemy_repeat_poison"}]}, None, ("a",)),
])
def test_measured_providers_match_existing_results_after_insert(provider, typed, missing, present):
    e = engine({"unrelated": action("b")})
    assert provider(e) == missing
    e.action_catalog["matching"] = action("a", typed)
    assert provider(e) == present
    assert provider(e) == present
    fresh = engine({"matching": action("a", typed)})
    assert provider(fresh) == present
