"""Public synthetic tests for explicit spiritual object profile permissions."""
from combat.spiritual_profiles import normalize


def test_explicitly_immune_external_anchor_remains_unaffectable():
    profile = normalize({"external_anchor": 1, "affectable": 0, "known_to": ["actor"]})
    assert profile["external_anchor"] == 1
    assert profile["affectable"] == 0


def test_external_anchor_infers_affectability_when_unspecified():
    profile = normalize({"external_anchor": 1})
    assert profile["affectable"] == 1
