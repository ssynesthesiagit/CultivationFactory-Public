"""Temporary diagnostic for the remaining Hearthfire light failure (not committed)."""
from combat.gate2_runtime_models import Position
from tests.worker2_support import OWNER, fixture, reload
from tests.test_mgr_t14_hearthfire_light import night_sighted_bundle, scene


def test_diag_light_gate(tmp_path):
    from combat.senses import perceives_cell, melds_of
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=night_sighted_bundle(tmp_path),
        owner_pb=6, battlefield=scene(tmp_path), foe_position={'x': 10, 'y': 6}, seed='HEARTH-LIGHT')
    e = reload(tmp_path, mid)
    actor = e.state.actors[OWNER]
    bundle = next(b for b in e.typed_bundle_documents if b['actor_id'] == OWNER)
    senses = bundle.get('senses') or {}
    perc = perceives_cell(e, actor, Position(x=5, y=6, z=0))
    assert False, (f"perc={perc} melds={melds_of(e,actor)} "
                   f"start={senses.get('meld_start')} rows={len(senses.get('rows') or [])}")
