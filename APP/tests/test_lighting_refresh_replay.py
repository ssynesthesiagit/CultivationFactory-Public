"""Refreshing a saved creature light must remove its old instance from the journal too."""
import pytest

from combat import lighting
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.worker2_support import FOE, OWNER, candidate, fixture, settle, turn

FIST = "tianxia.subpath.body.goruden.feature.radiant_fist"
OVERPRESSURE = "TAL_YANG_RADIANT_OVERPRESSURE"
SOURCE = "action:test.lighting.refresh"


def _refresh_action(bundle, effect):
    """Exercise the printed effect twice without an attack roll or mark-spend prerequisite."""
    bundle["action_catalog"].append({
        "source_definition_id": SOURCE, "display_name": "Refresh light", "owner_id": bundle["actor_id"],
        "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY", "range_ft": 60,
        "costs": [], "parameters": {"free_primary": True, "typed": {"effects": [effect], "numbers": {"cl": 15, "pb": 4},
                                             "duration": {"kind": "instant"}, "riders": []}},
    })
    bundle["actor_template"]["action_ids"].append(SOURCE)
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


def _saved(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    verified = session.verify()
    assert verified["status"] == "PASS", verified
    replayed = session.mechanical.replay()
    assert replayed["status"] == "PASS", replayed
    assert verified["canonical_state_sha256"] == replayed["canonical_state_sha256"]
    return session.engine


def _lights(engine):
    return [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == lighting.LIGHT]


@pytest.mark.parametrize("effect,radii", [
    pytest.param({"type": "light", "light": FIST, "applies_to": "target",
                  "duration": "until_start_of_next_turn"}, (0, 10), id="printed-light"),
    pytest.param({"type": "exposed", "light": OVERPRESSURE, "applies_to": "target",
                  "benefits": "invisible", "against": "anyone", "requires_visible_light": True,
                  "duration": "until_start_of_next_turn"}, (10, 20), id="exposure-light"),
])
def test_refresh_saved_light_removes_exact_old_instance_and_replays(tmp_path, effect, radii):
    combat, table, mid = fixture(tmp_path, [],
        bundle_transform=lambda bundles: _refresh_action(bundles[0], effect),
        seed="LIGHT-REFRESH-REPLAY")
    settle(table, mid, candidate(combat, mid, "Refresh light", target=FOE).candidate_id)
    first = _saved(tmp_path, mid)
    old, = _lights(first)
    assert old.source_actor_id == OWNER and old.source_definition_id == SOURCE
    assert old.expires_on == "START_OF_SOURCE_NEXT_TURN"
    event_boundary = first.state.event_sequence

    # The first light is already on disk; a second table transaction must replace
    # it in BOTH live state and replay, not leave the old instance in the reducer.
    settle(table, mid, candidate(combat, mid, "Refresh light", target=FOE).candidate_id)
    refreshed = _saved(tmp_path, mid)
    new, = _lights(refreshed)
    assert new.instance_id != old.instance_id
    assert new.expires_on == old.expires_on
    assert (new.data["bright_ft"], new.data["dim_ft"], new.data["magical"]) == (*radii, True)
    removed = [e for e in refreshed.events if e.sequence > event_boundary
               and e.event_type == "CONDITION_REMOVED" and e.payload.get("instance_id") == old.instance_id]
    assert len(removed) == 1
    assert removed[0].actor_id == OWNER and removed[0].target_ids == (FOE,)
    assert removed[0].payload["condition_id"] == lighting.LIGHT
    applied, = [e for e in refreshed.events if e.event_type == "CONDITION_APPLIED"
                and e.payload.get("instance_id") == new.instance_id]
    assert removed[0].sequence < applied.sequence
    emitted, = [s for s in lighting.sources(refreshed) if s.following == FOE]
    assert (emitted.bright_ft, emitted.dim_ft) == radii
    if effect["type"] == "exposed":
        exposed = [c for c in refreshed.state.actors[FOE].conditions.values()
                   if c.condition_id.startswith("condition:typed.exposed")]
        assert len(exposed) == 1 and exposed[0].expires_on == new.expires_on

    # Refresh retains the source-turn deadline, rather than making the light permanent.
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    expired = _saved(tmp_path, mid)
    assert not _lights(expired)
    assert not any(c.condition_id.startswith("condition:typed.exposed")
                   for c in expired.state.actors[FOE].conditions.values())
