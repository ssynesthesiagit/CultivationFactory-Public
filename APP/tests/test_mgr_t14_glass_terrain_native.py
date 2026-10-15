"""Acquired pane -> real breaking attack -> allied voluntary crossing -> replay."""
import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from sphere_component_authority import attach_sphere_automatic_component_receipt
from combat.ext.glass_pane import panes_of, shattered_cells
from combat.ext.glass_refraction import marked
from combat.tabletop import TabletopMapStore, to_battlefield
from tests.auto_worker1_support import LEFT, RIGHT, act, cell_send, fight, reload, resolve, turn
from tests.test_mgr_t14_starbolt_base import acquired_starbolt, TYPE_CHOICE
from tests.h1_support import ROOT


@pytest.mark.parametrize('accept_first', [False, True])
def test_allied_crossing_of_actual_broken_pane_is_optional_and_decline_does_not_spend_trigger(tmp_path, accept_first):
    def acquire(doc, aid):
        if aid == RIGHT:
            acquired_starbolt(doc, LEFT)
            doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
            return
        ledger = {}
        packet = attach_sphere_automatic_component_receipt(ledger,
            CanonicalCatalogAuthorityService(ROOT).get_sphere('tianxia.sphere.glass'), {
                'event_id': 'native-glass-terrain-acquisition', 'legal_channel': 'sphere_acquisition',
                'advancement': {'target_cl': 1}})
        doc['spheres_and_talents'] = {'sphere_record_ids': ['tianxia.sphere.glass'],
            'learned_talent_record_ids': ['TAL_GLASS_RAISED_PANE_SCRIPTURE'],
            'automatic_sphere_component_record_ids': packet['component_ids'],
            'automatic_sphere_component_receipts': ledger['automatic_sphere_component_receipts'],
            'automatic_sphere_components': ledger['automatic_sphere_components']}
    saved = TabletopMapStore(tmp_path / 'maps').save({'display_name': 'Native broken-glass yard',
        'width_squares': 20, 'height_squares': 18,
        'objects': [{'kind': 'custom', 'x': 5, 'y': 5, 'blocks': True, 'material': 'stone'}]})
    def arena(doc):
        doc.clear()
        doc.update(to_battlefield(saved))
    combat, table, mid = fight(tmp_path, cl=1, sheet_edit=acquire, arena_edit=arena,
        right_team='team:factory', extra_witness=True,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}})
    resolve(cell_send(table, mid, 'Raised Pane Scripture', (5, 6)))
    pane = panes_of(reload(combat, mid), reload(combat, mid).state.actors[LEFT])[0]
    for _ in range(5):
        turn(table, mid, RIGHT)
        resolve(lambda answers: act(table, mid, 'Starbolt', answers, target_id=pane.object_id),
            {TYPE_CHOICE: ['FORCE'], 'choice:needle.starbolt_mark': [],
             'choice:needle.glass_surface_mark': []})
        if reload(combat, mid).state.objects[pane.object_id].destroyed:
            break
        turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert engine.state.objects[pane.object_id].destroyed
    assert (5, 6) in shattered_cells(engine, engine.state.actors[LEFT])
    assert not marked(engine.state.actors[RIGHT], LEFT)
    _, prompts = resolve(cell_send(table, mid, 'Move', (5, 6)),
        {'choice:needle.glass_surface_mark': ['mark'] if accept_first else []})
    offers = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.glass_surface_mark']
    assert offers and all(p['context']['reactor_id'] == LEFT for p in offers)
    assert all('willingly moves across your Shattered Glass Terrain' in p['moment'] for p in offers)
    assert marked(reload(combat, mid).state.actors[RIGHT], LEFT) == accept_first
    if not accept_first:
        resolve(cell_send(table, mid, 'Move', (6, 6)))
        resolve(cell_send(table, mid, 'Move', (5, 6)),
            {'choice:needle.glass_surface_mark': ['mark']})
        assert marked(reload(combat, mid).state.actors[RIGHT], LEFT)
    session = combat._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
