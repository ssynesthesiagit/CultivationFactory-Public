"""Bloodsense altitude through private table findings and cold journal replay."""
from copy import deepcopy

import pytest

from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, prompt_turn


@pytest.fixture(autouse=True)
def offline_ranking(monkeypatch):
    from combat import menu_rank, embedding_rank
    monkeypatch.setattr(menu_rank, '_CLIENT', embedding_rank.EmbeddingClient(
        transport=lambda url, body, timeout: {'data': []}))


def injure_action(bundles):
    """Seal hovering actors and a replayable HP cost before fight creation."""
    foe = next(bundle for bundle in bundles if bundle['actor_id'] == FOE)
    action = deepcopy(next(a for a in foe['action_catalog'] if a['parameters'].get('typed')))
    source = 'test:bloodsense.vertical.injure'
    action.update(source_definition_id=source, display_name='Injure self',
                  economy='NONE', target_kind='SELF', costs=[])
    typed = action['parameters']['typed']
    typed.update(source=source,
                 effects=[{'type': 'hp_cost', 'amount': foe['actor_template']['maximum_hp'] // 2 + 1}],
                 riders=[], area=None, zone_spec={}, duration={'kind': 'instant'})
    action['parameters'] = {'typed': typed, 'free_primary': True}
    foe['action_catalog'].append(action)
    foe['actor_template']['action_ids'].append(source)
    for bundle in bundles:
        if bundle['actor_id'] in (OWNER, FOE):
            # Native turn-start falling must not erase the authored altitude.
            bundle['actor_template'].update(fly_speed_ft=60, hover=True)
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)


@pytest.mark.parametrize('target,direction,where', [
    ({'x': 3, 'y': 6, 'z': 10}, 'above', 'above you'),
    ({'x': 4, 'y': 5, 'z': 0}, 'northeast and below', 'to the northeast, below you'),
])
def test_native_vertical_findings_are_private_and_survive_cold_replay(
        tmp_path, target, direction, where):
    def arena(doc):
        doc['sensory_sources'] = [
            {'medium': 'blood', 'kind': 'creature', 'entity_id': FOE, 'circulation': 1}]

    combat, table, mid = fixture(
        tmp_path, ['BLOOD_BASE_BLOODSENSE'], bundle_transform=injure_action,
        battlefield_transform=arena,
        positions={OWNER: {'x': 3, 'y': 6, 'z': 5},
                   ALLY: {'x': 4, 'y': 6, 'z': 0}, FOE: target})
    prompt_turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Injure self').candidate_id)
    expected = {'ability': 'Bloodsense', 'kind': 'direction', 'direction': direction}
    line = f'Bloodsense: A creature at half its maximum HP or less is {where}.'

    def private_findings(service):
        view = service.state(mid, fog=True, fog_view='own', fog_actor_ids=(OWNER, ALLY, FOE))
        private = view['observer_information']
        assert expected in private[OWNER]['information']
        assert line in private[OWNER]['information_text']
        for other in (ALLY, FOE):
            assert not private.get(other, {}).get('information')
            assert not view['fog_perception'].get(other, {}).get('information_text')
        public = service.state(mid, fog=True)
        assert not public.get('observer_information')
        assert all('information_text' not in row for row in public['fog_perception'].values())
        return private[OWNER]

    before = private_findings(table)
    cold = CombatService(ROOT, tmp_path)
    session = cold._load_session(mid)
    position = session.engine.state.actors[FOE].position
    assert (position.x, position.y, position.z) == (target['x'], target['y'], target['z'])
    assert session.mechanical.replay()['status'] == 'PASS'
    assert private_findings(TabletopService(cold, tmp_path)) == before
