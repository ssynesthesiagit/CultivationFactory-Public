"""Actual acquired base records retain consumers without optional marker data."""
import json

from combat import typed_reactions
from combat.tabletop import TabletopMapStore, to_battlefield
from tests.mgr_t14_acquisition_support import acquire_owner
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload


def without_legacy_markers(tmp_path, monkeypatch, *, glass=False, ice=False):
    rules = json.loads(json.dumps(typed_reactions.rules()))
    for source, spec in list(rules['features'].items()):
        if (glass and (source == 'GLASS_BASE_FAULTLINE_MARKS'
                       or (spec.get('block') == 'lane9_glass' and spec.get('kind') == 'refraction'))
                or ice and source == 'ICE_BASE_SPENDING_A_FRACTURE_MARK'):
            del rules['features'][source]
    path = tmp_path / 'optional-feature-blocks.json'
    path.write_text(json.dumps(rules))
    monkeypatch.setattr(typed_reactions, 'RULES_PATH', path)
    monkeypatch.setattr(typed_reactions, '_CACHE', {})


def test_actual_faultline_acquisition_does_not_require_a_refraction_marker(tmp_path, monkeypatch):
    without_legacy_markers(tmp_path, monkeypatch, glass=True)
    saved = TabletopMapStore(tmp_path / 'maps').save({'display_name': 'Portable Glass yard',
        'width_squares': 20, 'height_squares': 18, 'objects': []})
    combat, table, mid = fixture(tmp_path, ['GLASS_BASE_FAULTLINE_MARKS'],
        sheet_edit=acquire_owner('tianxia.sphere.glass', OWNER),
        battlefield=to_battlefield(saved), named=True,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 3, 'y': 7}, FOE: {'x': 4, 'y': 6}},
        foe_kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao', 'quantity': 1}]}})
    engine = reload(tmp_path, mid)
    rows = engine.typed_passive_rows[OWNER]
    assert len([r for r in rows if r.get('feature_id') == 'GLASS_BASE_FAULTLINE_MARKS']) == 1
    assert not any(r.get('block') == 'lane9_glass' and r.get('kind') == 'refraction' for r in rows)
    settle(table, mid, candidate(combat, mid, 'Temper Glass Surface').candidate_id)
    turn(table, mid, FOE)
    attack = next(c for c in reload(tmp_path, mid).legal_candidates()
        if OWNER in c.target_ids and 'Dao' in c.display_name)
    prompts = settle(table, mid, attack.candidate_id, {'choice:needle.glass_surface_mark': 'mark'})
    assert any(p['context']['reactor_id'] == OWNER and
        p['context']['reaction_source_id'] == 'choice:needle.glass_surface_mark' for p in prompts)
    from combat.ext.glass_refraction import marked
    assert marked(reload(tmp_path, mid).state.actors[FOE], OWNER)
    session = combat._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_actual_ice_acquisition_retains_native_response_and_recipient_consent(tmp_path, monkeypatch):
    without_legacy_markers(tmp_path, monkeypatch, ice=True)
    from tests.test_mgr_t14_fracture_service import test_crystal_guard_uses_recipient_consent_not_team_identity
    # Reuse the complete acquired Needle -> mark -> real damage intent ->
    # recipient consent -> committed reduction/cold replay acceptance sequence.
    test_crystal_guard_uses_recipient_consent_not_team_identity(tmp_path, accept=True, blind=False)
