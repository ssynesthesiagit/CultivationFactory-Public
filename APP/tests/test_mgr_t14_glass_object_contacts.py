"""Actual acquired pane -> native contact intent -> owner choice -> cold replay."""
import pytest

from combat.ext.glass_pane import panes_of
from combat.ext.glass_refraction import marked
from combat.ext.object_contacts import PREFIX
from combat.object_interaction import used
from combat.tabletop import TabletopMapStore, to_battlefield
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn
from tests.mgr_t14_acquisition_support import acquire_owner
from tests.test_mgr_t14_weighted_strike import local_primary


def native_pane(tmp_path):
    saved = TabletopMapStore(tmp_path).save({'display_name': 'Actual surface contact courtyard',
        'width_squares': 20, 'height_squares': 18, 'objects': [
            {'kind': 'custom', 'name': 'Supporting stone', 'x': 5, 'y': 5,
             'material': 'stone', 'blocks': True}]})
    combat, table, mid = fixture(tmp_path, ['TAL_GLASS_RAISED_PANE_SCRIPTURE'], cl=1,
        named=True, battlefield=to_battlefield(saved),
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 8}, FOE: {'x': 6, 'y': 6}},
        sheet_edit=acquire_owner('tianxia.sphere.glass', OWNER))
    settle(table, mid, candidate(combat, mid, 'Raised Pane Scripture', at=(5, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    pane = panes_of(engine, engine.state.actors[OWNER])[0]
    turn(table, mid, FOE)
    return combat, table, mid, pane.object_id


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('accept', [False, True])
def test_actual_touch_is_optional_for_the_surface_owner_even_on_an_ai_turn(tmp_path, automatic, accept):
    combat, table, mid, object_id = native_pane(tmp_path)
    before = reload(tmp_path, mid)
    assert not marked(before.state.actors[FOE], OWNER)
    assert not used(before.state.actors[FOE])
    use = next(c for c in before.legal_candidates()
        if c.source_definition_id == PREFIX + 'free' and c.target_ids == (object_id,))
    # Pure menu construction and repeated cold queries cannot create contact.
    assert not marked(reload(tmp_path, mid).state.actors[FOE], OWNER)
    if automatic:
        local_primary(combat, use.candidate_id)
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, use.candidate_id, auto=automatic, choices={
        'choice:needle.glass_surface_mark': ['mark'] if accept else None,
        'choice:needle.refraction_response': None})
    offers = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.glass_surface_mark']
    assert offers and all(p['context']['reactor_id'] == OWNER for p in offers)
    assert all('touches your Glass Surface' in p['moment'] for p in offers)
    after = reload(tmp_path, mid)
    assert marked(after.state.actors[FOE], OWNER) is accept
    assert used(after.state.actors[FOE]) and after.state.actors[FOE].action_available
    assert after.state.actors[OWNER].reaction_available
    assert after.state.actors[OWNER].resources == before.state.actors[OWNER].resources
    assert after.state.objects[object_id].current_hp == before.state.objects[object_id].current_hp
    receipts = [e for e in after.events[len(before.events):]
        if e.payload.get('checkpoint') == 'OBJECT_CONTACT_COMMITTED']
    assert len(receipts) == 1 and receipts[0].target_ids == (object_id,)
    if not automatic:
        assert any(c.source_definition_id == PREFIX + 'utilize' and c.target_ids == (object_id,)
            for c in after.legal_candidates())


def test_no_acquired_surface_owner_adds_no_contact_catalog_or_receipt(tmp_path):
    combat, table, mid = fixture(tmp_path, [], cl=1)
    engine = reload(tmp_path, mid)
    assert not any(source.startswith(PREFIX) for source in engine.action_catalog)
    assert not any(e.payload.get('checkpoint') == 'OBJECT_CONTACT_COMMITTED' for e in engine.events)
