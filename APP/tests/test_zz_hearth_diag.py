"""Temporary diagnostics for the two remaining Hearthfire failures (not committed)."""
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_mgr_t14_hearthfire_light import night_sighted_bundle, scene


def test_diag_light_candidate(tmp_path):
    from combat.gate2_runtime_models import Position
    from combat.asset_anchor_runtime import legal_placement
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=night_sighted_bundle(tmp_path),
        owner_pb=6, battlefield=scene(tmp_path), foe_position={'x': 10, 'y': 6}, seed='HEARTH-LIGHT')
    e = reload(tmp_path, mid)
    names = sorted({getattr(a, 'display_name', None) for a in e.action_catalog.values()
                    if a is not None and 'earth' in str(getattr(a, 'display_name', '')).lower()})
    hearth = [a for a in e.action_catalog.values() if a is not None and a.display_name == 'Kindled Hearth']
    cands = [(c.source_definition_id, c.destination and (c.destination.x, c.destination.y, c.destination.z),
              c.target_ids) for c in e.legal_candidates()
             if getattr(e.action_catalog.get(c.source_definition_id), 'display_name', None) == 'Kindled Hearth']
    rows = [r for r in getattr(e, 'typed_passive_rows', {}).get(OWNER, ()) if r.get('block') == 'qi_hearthfire']
    vol0 = e.grid.volume_legal(Position(x=5, y=6, z=0))
    vol1 = e.grid.volume_legal(Position(x=5, y=6, z=1))
    legal = legal_placement(e, (Position(x=5, y=6, z=0),), 5)
    info = {'names': names, 'catalog': [(a.source_definition_id, a.display_name,
            (a.parameters or {}).get('typed')) for a in hearth],
            'candidates': cands, 'passives': rows,
            'vol0': vol0, 'vol1': vol1, 'legal': legal,
            'grid': (e.grid.width, e.grid.height, e.grid.square_size_ft),
            'actors': {aid: (a.position.model_dump(), a.active) for aid, a in e.state.actors.items()},
            'objects': [(o.object_id, o.position.model_dump(), o.height_ft) for o in e.state.objects.values()]}
    assert cands, info


def test_diag_feed_calls(tmp_path, monkeypatch):
    from combat.ext import qi_hearthfire_sanctuary as sanctuary
    from tests.test_a2_qi_subpaths_7 import controls
    from tests.test_mgr_t14_hearthfire_native import FEATURES, acquired_bundle
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_pb=6, owner_features=FEATURES,
        bundle_transform=controls, seed='HEARTH-FEED-MANDATORY', owner_bundle=acquired_bundle(tmp_path, 18))
    settle(table, mid, candidate(combat, mid, 'Flame That Welcomes All').candidate_id,
        choices={'choice:needle.welcoming_allies': [OWNER, ALLY], 'choice:needle.homefire_recovery': 'temp_hp'})
    observed = []
    original = sanctuary.ask

    def capture(*args, **kwargs):
        if kwargs.get('feature_id', '').endswith('.flame_that_welcomes_all'):
            observed.append({'checkpoint': str(args[2]) if len(args) > 2 else None,
                             'decline': kwargs.get('allow_decline'),
                             'round': getattr(args[0].state, 'round_number', None),
                             'turn': getattr(args[3] if len(args) > 3 else None, 'turns_started', None)})
        return original(*args, **kwargs)

    monkeypatch.setattr(sanctuary, 'ask', capture)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Force damage', target=ALLY).candidate_id,
        choices={'choice:needle.hearth_shield': None})
    turn(table, mid, OWNER)
    e = reload(tmp_path, mid)
    feeds = [(r.reason, r.total) for r in e.rolls if r.reason == 'HEARTH_FEED']
    assert len(observed) == 1, {'observed': observed, 'feeds': feeds,
                                'round': e.state.round_number, 'hp': e.state.actors[ALLY].current_hp}
