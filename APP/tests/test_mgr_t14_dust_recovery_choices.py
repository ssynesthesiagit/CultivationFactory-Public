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
    # The common harness asks about reactions; newer base actions now supply
    # reactions even to a Primordial-only character. Keep every reaction, but
    # set Auto in this isolated scenario so only Primordial's compiled inline
    # choice enrollment can admit the manual owner to the off-turn probe.
    for bundle in bundles:
        for row in bundle.get('typed_reactions', []):
            row.pop('ask', None)
        bundle['reaction_plan'] = {**bundle.get('reaction_plan', {}), 'mode': 'auto'}
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


@pytest.mark.parametrize('mode', ['suppress', 'end'])
@pytest.mark.parametrize('choice_altitude', [0, 1])
def test_manual_primordial_owner_chooses_recovery_during_ai_action(tmp_path, mode, choice_altitude):
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
    # Keep both ground and elevated ties reachable. A ground choice remains
    # there; an unsupported elevated choice can fall after flight is removed.
    from combat.ext.needle import cell_id, parse_cell
    assert {parse_cell(option['id'])[2] for option in options} >= {0, 1}
    selected = next(option['id'] for option in reversed(options)
                    if parse_cell(option['id'])[2] == choice_altitude)
    assert selected != prompt['choice']['preferred'][0]
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': [selected]}
    assert send(cid, [answer], auto=True)['status'] == 'COMMITTED'
    e = cold(tmp_path, mid)
    actor = e.state.actors[s.OWNER]
    moves = [event for event in e.events if event.sequence > before.state.event_sequence
             and event.event_type == 'MOVEMENT_COMMITTED' and event.actor_id == s.OWNER]
    recovery = moves[0]
    from combat.gate2_runtime_models import Position
    chosen = Position(**recovery.payload['destination'])
    assert cell_id(chosen, include_altitude=True) == selected
    assert recovery.source_definition_id != 'system:combat.falling'
    assert recovery.payload['forced'] is True and recovery.payload['cost_ft'] == 0
    falls = [event for event in moves if event.source_definition_id == 'system:combat.falling']
    if mode == 'end' and choice_altitude:
        # The printed flight lasts only for the form's duration. Its removal
        # must not grant permanent Hover just to preserve a recovery square.
        assert len(falls) == 1
        assert falls[0].sequence > recovery.sequence
        assert falls[0].payload['path'][0] == chosen.model_dump(mode='json')
        assert falls[0].payload['fall_distance_ft'] == 5
        assert actor.position == chosen.model_copy(update={'z': 0})
    else:
        assert not falls
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


def test_enclosure_fixture_preserves_base_reactions_without_ask_enrollment():
    """Main may grant base reactions without masking the isolated-owner test."""
    original = {'parameters': {'typed': {'source': P + 'primordial_dust', 'numbers': {'cl': 18}}}}
    bundles = [
        {'actor_id': actor, 'action_catalog': [deepcopy(original)],
         'actor_template': {'action_ids': []},
         'typed_reactions': [{'feature_id': 'test:base_reaction', 'ask': True}],
         'reaction_plan': {'mode': 'ask'}, 'bundle_sha256': 'outdated'}
        for actor in (s.OWNER, s.FOE, s.SECOND)
    ]
    enclose_and_release(bundles, 'end')
    for bundle in bundles:
        assert bundle['typed_reactions'] == [{'feature_id': 'test:base_reaction'}]
        assert bundle['reaction_plan']['mode'] == 'auto'
        digest = bundle.pop('bundle_sha256')
        assert digest == canonical_sha256(bundle)


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
