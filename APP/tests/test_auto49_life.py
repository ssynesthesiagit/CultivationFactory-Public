"""AUTO49 Life through sealed fixtures, table commits and cold reloads."""
import pytest
from tests.cw2_service_support import add_action
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn
P = 'tianxia.talent.life.'

def option(combat, mid, contains, target=ALLY):
    e = combat._load_session(mid).engine
    return next(c for c in e.legal_candidates() if c.target_ids == (target,)
                and (a := e.action_catalog.get(c.source_definition_id)) is not None
                and all(word in a.display_name for word in contains))

@pytest.mark.parametrize('condition', ['petrified', 'restrained'])
def test_meridian_unbinding_offers_and_removes_printed_conditions(tmp_path, condition):
    def prepare(bundles):
        add_action(bundles[0], 'Prepare restrained patient', [{'type': 'condition', 'condition': condition,
            'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}])
    combat, table, mid = fixture(tmp_path, [P + 'meridian_unbinding'], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Prepare restrained patient', target=ALLY).candidate_id)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    cast = option(combat, mid, ['Purify the Pulse', 'Meridian Unbinding'])
    prompts = settle(table, mid, cast.candidate_id, {'choice:needle.purify_extra': condition})
    assert any(condition in [o['id'] for o in p.get('choice', {}).get('options', [])] for p in prompts)
    e = reload(tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.' + condition for c in e.state.actors[ALLY].conditions.values())
    assert e.state.actors[OWNER].resources['resource:core.qi'] == before - 2

@pytest.mark.parametrize('extras,subset', [(True, False), (False, False), (True, True)])
def test_deep_root_selects_any_number_from_owned_life_treatments(tmp_path, extras, subset):
    def prepare(bundles):
        add_action(bundles[0], 'Prepare complex harm', [{'type': 'condition', 'condition': n,
            'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}
            for n in ['poisoned', 'blinded', 'deafened', 'charmed', 'frightened', 'restrained', 'untreatable_curse']])
    talents = [P + 'deep_root_restoration', *([P + 'mind_cooling_pulse', P + 'meridian_unbinding'] if extras else [])]
    combat, table, mid = fixture(tmp_path, talents, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Prepare complex harm', target=ALLY).candidate_id)
    chosen = ['charmed'] if subset else ['blinded', 'deafened', *(['charmed', 'frightened', 'restrained'] if extras else [])]
    e = reload(tmp_path, mid)
    cast = next(c for c in e.legal_candidates() if c.target_ids == (ALLY,)
                and (a := e.action_catalog.get(c.source_definition_id)) is not None
                and 'Remove Poisoned' in a.display_name and 'Deep Root Restoration' in a.display_name
                and 'Mind-Cooling' not in a.display_name and 'Meridian Unbinding' not in a.display_name)
    before = e.state.actors[OWNER].resources['resource:core.qi']
    prompts = settle(table, mid, cast.candidate_id, {'choice:needle.deep_root': chosen})
    assert any(p['context']['reactor_id'] == OWNER for p in prompts)
    e = reload(tmp_path, mid)
    names = {c.condition_id.removeprefix('condition:typed.') for c in e.state.actors[ALLY].conditions.values()}
    assert 'poisoned' not in names and not set(chosen) & names and 'untreatable_curse' in names
    assert ('frightened' in names) == (subset or not extras)
    assert e.state.actors[OWNER].resources['resource:core.qi'] == before - 3

@pytest.mark.parametrize('source', ['Borrowed Breath', 'Mend the Pulse'])
def test_latent_vitality_waits_for_injury_then_releases_its_original_effect(tmp_path, source):
    from combat.ext.life_riders import LATENT
    def prepare(bundles):
        for b in bundles:
            add_action(b, 'Prepare injury', [{'type': 'damage', 'flat': 10, 'damage_types': ['force'], 'applies_to': 'target'}])
    combat, table, mid = fixture(tmp_path, [P + 'latent_healing'], seed='AUTO49-LATENT', bundle_transform=prepare)
    cast = option(combat, mid, [source, 'Latent Healing'])
    settle(table, mid, cast.candidate_id)
    e = reload(tmp_path, mid); patient = e.state.actors[ALLY]
    stored = next(c for c in patient.conditions.values() if c.condition_id == LATENT)
    assert patient.current_hp == 60 and patient.temporary_hp == 0
    assert [r['type'] for r in stored.data['rows']] == (['stabilize', 'temp_hp'] if source == 'Borrowed Breath' else ['healing'])
    settle(table, mid, candidate(combat, mid, 'Prepare injury', target=ALLY).candidate_id,
           {'choice:needle.latent_healing': None})
    e = reload(tmp_path, mid)
    assert e.state.actors[ALLY].current_hp == 50
    assert any(c.condition_id == LATENT for c in e.state.actors[ALLY].conditions.values())
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Prepare injury', target=ALLY).candidate_id,
                     {'choice:needle.latent_healing': 'use'})
    assert any(p['context']['reactor_id'] == ALLY for p in prompts)
    e = reload(tmp_path, mid)
    assert not any(c.condition_id == LATENT for c in e.state.actors[ALLY].conditions.values())
    assert not e.state.actors[ALLY].reaction_available
    if source == 'Borrowed Breath':
        assert e.state.actors[ALLY].current_hp == 40 and e.state.actors[ALLY].temporary_hp == 4
    else:
        heal = next(x for x in reversed(e.events) if x.event_type == 'HEALING_APPLIED')
        assert heal.payload['before'] == 40
        assert e.state.actors[ALLY].current_hp == heal.payload['after'] > 40
