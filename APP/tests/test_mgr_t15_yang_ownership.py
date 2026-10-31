"""Neutral Yang marks require the marker's own expression record, not just a Yang producer."""
import pytest

from combat.canonical import canonical_sha256
from combat.typed_executor import bears_mark, mark_condition_id
from combat.ext.yang_sun_marks import KINDLE
from tests.worker2_support import ALLY, OWNER, candidate, fixture, reload, settle

EXPRESSION = "TAL_YANG_KINDLED_AND_OVERKINDLED_MARKS"


@pytest.mark.parametrize("owns_expression", [False, True])
def test_neutral_yang_mark_uses_only_its_owners_expression_record(tmp_path, owns_expression):
    def neutral_producer(bundles):
        bundle = bundles[0]
        # Sealed synthetic catalog: a different Yang record produces a neutral
        # mark, with or without ownership of the separate expression record.
        action = next(a for a in bundle["action_catalog"]
                      if a["source_definition_id"].endswith(KINDLE))
        action["parameters"]["typed"].update({
            "source": "TAL_YANG_OTHER_RISING_MARK",
            "effects": [{"type": "mark", "mark": "Rising Mark", "applies_to": "target",
                         "duration": {"kind": "until_end_of_your_next_turn"}}],
        })
        if not owns_expression:
            bundle["typed_passives"] = [r for r in bundle["typed_passives"]
                                        if r.get("feature_id") != EXPRESSION]
            bundle["typed_reactions"] = [r for r in bundle["typed_reactions"]
                                         if r.get("feature_id") != EXPRESSION]
            bundle["action_catalog"] = [a for a in bundle["action_catalog"]
                                        if a["parameters"].get("typed", {}).get("source") != EXPRESSION]
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid = fixture(tmp_path, [KINDLE], named=True, bundle_transform=neutral_producer)
    prompts = settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=ALLY).candidate_id,
                     picks={"choice:willing.consent": "refuse"})
    consent = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:willing.consent"]
    assert bool(consent) is owns_expression
    if consent:
        assert consent[0]["context"]["reactor_id"] == ALLY
    bearer = reload(tmp_path, mid).state.actors[ALLY]
    assert any(c.condition_id == mark_condition_id("Rising Mark", OWNER)
               for c in bearer.conditions.values()) is not owns_expression
    assert bears_mark(bearer, OWNER, "Overkindled Mark") is owns_expression
    assert not bears_mark(bearer, OWNER, "Kindled Mark")
