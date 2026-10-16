"""Primordial's own compiled grant must preserve off-turn player decisions.

The foe's test-only typed action creates a blocking wall around the particle
body, then suppresses/removes it. Both changes run through native deliveries;
no ownership, condition, position, or turn state is injected into the fight.
"""
from copy import deepcopy

import pytest

from combat.canonical import canonical_sha256
from combat.ext.qi_subpaths_dust import FORM, primordial
from combat.opening_passage import solid_grid
from tests import r1i_service_support as s
from tests.test_mgr_t14_dust_family import P, cold
from tests.test_mgr_t14_dust_grant_loss import release_action


def enclose_and_release(bundles, mode):
    owner = next(b for b in bundles if b['actor_id'] == s.OWNER)
    foe = next(b for b in bundles if b['actor_id'] == s.FOE)
    original = next(a for a in owner['action_catalog']
                    if a['parameters'].get('typed', {}).get('source') == P + 'primordial_dust')
    action = deepcopy(original)
    action.update(source_definition_id='test:dust.enclose_release', owner_id=s.FOE,
                  display_name='Test enclose and release', economy='ACTION',
                  target_kind='ANY_CREATURE', range_ft=60, costs=[], concentration=False)
    action['parameters'] = {'typed': {
        'source': 'test:dust.enclose_release',
        'numbers': deepcopy(original['parameters']['typed']['numbers']),
        'duration': {'kind': 'instant'},
        'zone_spec': {'name': 'Test enclosure', 'size_ft': 5,
                      'wall': {'blocks_movement': True, 'height_ft': 100, 'thick_ft': 5},
                      'duration': {'kind': 'one_minute'}},
        'effects': [{'type': 'zone'}, {'type': 'end_effect', 'applies_to': 'target',
                    'conditions': [FORM.removeprefix('condition:typed.')],
                    'select': 'any', 'on_success': mode}]}}
    foe['action_catalog'].append(action)
    foe['actor_template']['action_ids'].append(action['source_definition_id'])
    foe.pop('bundle_sha256', None)
    foe['bundle_sha256'] = canonical_sha256(foe)


@pytest.mark.parametrize('mode', ['suppress', 'end'])
def test_manual_primordial_owner_chooses_recovery_during_ai_action(tmp_path, mode):
    combat, table, mid, send, commit = s.fixture(
        tmp_path, [P + 'primordial_dust'], owner_cl=18, wide=True,
        positions={s.OWNER: {'x': 3, 'y': 6}, s.FOE: {'x': 6, 'y': 6},
                   s.SECOND: {'x': 15, 'y': 6}},
        bundle_transform=lambda bundles: enclose_and_release(bundles, mode))
    # Compiled ownership enrolls this owner even before activation. Neither the
    # foe nor the unrelated third actor owns an inline-choice action/Ask row.
    e = cold(tmp_path, mid)
    assert not any(row.get('ask') for rows in e.typed_reaction_rows.values() for row in rows)
    assert s.OWNER in e.typed_ask_reactors
    commit(s.candidate(table, mid, 'Primordial Dust'))
    form = primordial(cold(tmp_path, mid).state.actors[s.OWNER])
    identity, expiry = form.instance_id, form.expires_on
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != s.FOE:
        commit(table.state(mid)['menu']['end_turn'])
    cid = s.candidate(table, mid, 'Test enclose and release', s.OWNER)
    s.force_ai_candidate(combat, mid, s.FOE, cid)
    before = cold(tmp_path, mid)
    actor = before.state.actors[s.OWNER]
    hp, qi, movement = actor.current_hp, actor.resources['resource:core.qi'], actor.movement_remaining_ft
    result = send(cid, auto=True)
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == s.OWNER
    assert prompt['context']['reaction_source_id'] == 'choice:needle.dust_passage_lost'
    assert all(name in prompt['moment'] for name in ('Primordial Dust', 'Owner', 'Test enclose and release'))
    options = prompt['choice']['options']
    assert len(options) > 1
    # Choose a non-default tie; the AI must wait and honor that exact square.
    selected = options[-1]['id']
    assert selected != prompt['choice']['preferred'][0]
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': [selected]}
    assert send(cid, [answer], auto=True)['status'] == 'COMMITTED'
    e = cold(tmp_path, mid)
    actor = e.state.actors[s.OWNER]
    from combat.ext.needle import cell_id
    assert cell_id(actor.position, include_altitude=True) == selected
    assert solid_grid(e).volume_legal(actor.position, footprint=e._footprint(actor),
                                    occupied_cells=e._occupied_volumes_except(s.OWNER))
    assert (actor.current_hp, actor.resources['resource:core.qi'], actor.movement_remaining_ft) == (hp, qi, movement)
    assert primordial(actor) is None
    assert s.OWNER in e.typed_ask_reactors  # survives suppression and full removal
    if mode == 'suppress':
        assert actor.conditions[identity].expires_on == expiry
    else:
        assert identity not in actor.conditions


@pytest.mark.parametrize('mode', ['suppress', 'end'])
def test_release_fixture_registers_action_in_native_template(mode):
    """Guard the fixture defect directly before its six service cases execute."""
    original = {'parameters': {'typed': {'source': P + 'primordial_dust', 'numbers': {'cl': 18}}}}
    owner = {'actor_id': s.OWNER, 'action_catalog': [original], 'actor_template': {'action_ids': []}}
    release_action([owner], mode)
    action = owner['action_catalog'][-1]
    assert action['source_definition_id'] in owner['actor_template']['action_ids']
    digest = owner.pop('bundle_sha256')
    assert digest == canonical_sha256(owner)


@pytest.mark.parametrize(('name', 'minimum_cl'), [
    ('dust_cloud', 3), ('choking_dust', 6), ('dust_to_dust', 10),
    ('sandstorm_field', 14), ('primordial_dust', 18),
])
def test_merged_authority_retains_printed_dust_progression(name, minimum_cl):
    """A merge must rebuild reviewed inputs rather than ship stale main output."""
    from tests.h1_support import mechanics

    assert mechanics()[P + name]['min_cl'] == minimum_cl


def test_recovery_execution_source_receipt(capsys):
    """Retain actual file hashes so queue pickup cannot silently change provenance.

    The collector compares this receipt with the frozen candidate's manifest;
    a request ID or the checkout name alone cannot identify executed source.
    """
    import hashlib
    import json
    from tests.h1_support import ROOT

    paths = (
        'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
        'combat/ext/qi_subpaths_dust.py', 'combat/creature_passage.py',
        'combat/gate2_engine.py', 'combat/typed_executor.py',
        'tests/test_mgr_t14_dust_recovery_choices.py',
        'tests/test_mgr_t14_dust_grant_loss.py',
    )
    hashes = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
              for path in paths}
    with capsys.disabled():
        print('DUST_EXECUTED_SOURCE ' + json.dumps(hashes, sort_keys=True), flush=True)
