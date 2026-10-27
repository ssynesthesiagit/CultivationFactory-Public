"""Public synthetic survival rows exercise Yang's real compiler hook and damage dispatch.

Public exports scramble printed trigger prose, so prose-based trigger classification
is not a usable fixture for these integration tests. No engine code is patched.
"""
import pytest

from combat import ext, typed_reactions, pending_damage
from combat.canonical import canonical_sha256
from combat.ext.yang_sun_marks import LIFE, DAWN
from tests.worker2_support import fixture, OWNER, ALLY, FOE


def protection_setup(source):
    """Seal a minimal drop-to-zero row through the production continuation compiler."""
    def transform(bundles):
        bundle = bundles[0]
        row = {
            "feature_id": source, "block": "generic", "kind": "ally_drop_to_zero",
            "name": "Life Refuses Closure" if source == LIFE else "Dawn Commands the Fallen Breath",
            "range_ft": 60, "costs": [["resource:core.qi", 6 if source == LIFE else 12]],
            "free": False, "use_limit": "once_per_long_rest",
            "effects": [
                {"type": "hold_at_1hp", "keep": 1, "applies_to": "ally"},
                {"type": "mark", "mark": "Kindled Mark", "applies_to": "ally",
                 "duration": {"kind": "until_end_of_your_next_turn"}},
            ],
            "numbers": {"cl": 15, "pb": 4, "key_mod": 2},
        }
        row = ext.transform("compile_reaction", row, {"owned_ids": [source]})
        bundle["typed_reactions"] = [
            r for r in bundle["typed_reactions"] if r["feature_id"] != source] + [row]
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    return transform


@pytest.mark.parametrize("source", [LIFE, DAWN])
def test_protection_dispatch_has_no_bad_row_rider(tmp_path, source):
    combat, table, mid = fixture(
        tmp_path, [source], ask=False, bundle_transform=protection_setup(source))
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    engine._active_intent = None
    with pending_damage.scope(engine, ally, 30, "SLASHING", "action:test.attack", FOE):
        amount = typed_reactions.on_damage(
            engine, ally, 30, 0, source_definition_id="action:test.attack", source_actor_id=FOE)
    errors = [e.payload.get("rider") for e in engine.events
              if e.event_type == "GM_RIDER" and e.source_definition_id == source]
    assert not errors, "; ".join(errors)
    assert amount == 4
