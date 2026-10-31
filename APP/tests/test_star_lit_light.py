"""Star-Lit Acupoints' resource-gated light is a saved table choice."""
from combat import lighting
from tests.worker2_support import ALLY, OWNER, candidate, fixture, reload, settle, turn

STAR = "tianxia.subpath.body.nine_star_meridian_body.feature.star_lit_acupoints"


def test_star_lit_toggle_survives_reload_and_is_once_per_turn(tmp_path):
    combat, table, mid = fixture(tmp_path, [STAR], seed="STAR-LIT-TOGGLE")
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources["resource:named.celestial_mark"] >= 1
    assert not [s for s in lighting.sources(engine) if s.name == "Star-Lit Acupoints"]
    settle(table, mid, candidate(combat, mid, "Star-Lit Acupoints: Emit light").candidate_id)
    engine = reload(tmp_path, mid)
    light, = [s for s in lighting.sources(engine) if s.name == "Star-Lit Acupoints"]
    assert (light.following, light.bright_ft, light.dim_ft) == (OWNER, 0, 5)
    owner = engine.state.actors[OWNER]
    resource = "resource:named.celestial_mark"
    engine._spend_resource(owner, resource, owner.resources[resource], "test")
    assert not [s for s in lighting.sources(engine) if s.name == "Star-Lit Acupoints"]
    engine._gain_resource(owner, resource, 1, "test")
    assert [s for s in lighting.sources(engine) if s.name == "Star-Lit Acupoints"]
    assert not any(c.display_name == "Star-Lit Acupoints: Suppress light" for c in engine.legal_candidates())
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Star-Lit Acupoints: Suppress light").candidate_id)
    engine = reload(tmp_path, mid)
    assert not [s for s in lighting.sources(engine) if s.name == "Star-Lit Acupoints"]
