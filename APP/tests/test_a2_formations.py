"""Second-pass formations through real table transactions and cold journal reload."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import normalize_map, to_battlefield
from combat.ext.formation_talents import RELAY
from combat.ext.formation_riders import LOST
from tests.cw2_service_support import seal
from tests.formation_support import reload, settle, turn
from tests.h1_support import sheet
from tests.worker2_support import ROOT, OWNER, ALLY, FOE, fixture, candidate

TALENT = 'tianxia.talent.formations.formation_thread_relay'
MAZE = 'tianxia.talent.formations.formation_maze'


def grant(combat, table, mid):
    settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(5, 6)).candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, 'Pulse: Nourishing Cycle', target=ALLY).candidate_id,
                     {'choice:needle.formation_thread_relay': ALLY})
    turn(table, mid, ALLY)
    return prompts


@pytest.mark.parametrize('legacy,secret', [(False, False), (True, False), (False, True)])
def test_relay_nonattack_technique_range_permission_consumption_and_reload(tmp_path, legacy, secret):
    def transform(bundles):
        for row in bundles[0]['action_catalog']:
            if legacy:
                row['parameters'].get('typed', {}).pop('formation_relay_techniques', None)
        for row in bundles[1]['action_catalog']:
            if secret and row['parameters'].get('typed', {}).get('source') == 'TAL_FATE_BINDING_WORD':
                row['parameters']['typed']['source_category'] = 'Secret Inheritance'
        for bundle in bundles:
            seal(bundle)

    combat, table, mid = fixture(tmp_path, [TALENT], ally_talents=['TAL_FATE_BINDING_WORD'],
        seed='A2-RELAY', foe_position={'x': 11, 'y': 5}, bundle_transform=transform)
    prompts = grant(combat, table, mid)
    relay_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.formation_thread_relay')
    assert ('normal action and cost' in relay_prompt['moment']) == (not legacy)
    e = reload(tmp_path, mid)
    ally = e.state.actors[ALLY]
    held = [c for c in ally.conditions.values() if c.condition_id.startswith(RELAY + '.')]
    assert len(held) == 1
    assert bool(held[0].data.get('techniques')) == (not legacy)
    words = next(a for a in e.action_catalog.values() if a.owner_id == ALLY and a.display_name == 'Binding Word')
    options = [c for c in e.legal_candidates() if c.source_definition_id == words.source_definition_id and c.target_ids == (FOE,)]
    assert not [c for c in options if not c.metadata.get('effect_origin')], 'physical caster is 35 feet away'
    remote = [c for c in options if c.metadata.get('effect_origin')]
    assert bool(remote) == (not legacy and not secret)
    if remote:
        assert 'non-Secret technique' in held[0].data['label']
        assert any('Formation Thread Relay' in p['moment'] for p in prompts)
        before = ally.resources['resource:core.qi']
        pos = ally.position
        settle(table, mid, remote[0].candidate_id)
        after = reload(tmp_path, mid)
        assert after.state.actors[ALLY].position == pos
        assert after.state.actors[ALLY].resources['resource:core.qi'] == before - 2
        assert not any(c.condition_id.startswith(RELAY + '.') for c in after.state.actors[ALLY].conditions.values())
        assert any(r.reason.startswith('SAVE:') and 'TAL_FATE_BINDING_WORD' in r.reason for r in after.rolls)
        assert after.state.actors[FOE].conditions or after.state.actors[FOE].modifiers


@pytest.mark.parametrize('visible', [True, False])
def test_relay_save_target_must_be_perceived_by_the_ally(tmp_path, visible):
    from tests.cw2_service_support import add_action

    def prepare(bundles):
        if not visible:
            add_action(bundles[0], 'Blind relay ally', [{'type': 'condition', 'condition': 'blinded',
                'applies_to': 'target', 'duration': 'until_removed'}])

    combat, table, mid = fixture(tmp_path, [TALENT], ally_talents=['TAL_FATE_BINDING_WORD'],
        bundle_transform=prepare, seed='A2-RELAY-SIGHT')
    if not visible:
        settle(table, mid, candidate(combat, mid, 'Blind relay ally', target=ALLY).candidate_id)
    grant(combat, table, mid)
    e = reload(tmp_path, mid)
    options = [c for c in e.legal_candidates() if c.source_definition_id.endswith('.TAL_FATE_BINDING_WORD') and c.metadata.get('effect_origin')]
    assert bool(options) == visible


def test_relay_area_save_uses_chosen_eye_and_is_consumed_after_commit(tmp_path):
    combat, table, mid = fixture(tmp_path, [TALENT], ally_talents=['FIRE_TAL_FIREBALL_ART'],
                                seed='A2-RELAY-AREA', foe_position={'x': 11, 'y': 5})
    grant(combat, table, mid)
    e = reload(tmp_path, mid)
    remote = [c for c in e.legal_candidates() if c.source_definition_id.endswith('.FIRE_BASE_CONFLAGRATION')
              and c.metadata.get('effect_origin') and c.destination
              and (c.destination.x, c.destination.y) == (11, 5)]
    assert remote
    hp = e.state.actors[FOE].current_hp
    position = e.state.actors[ALLY].position
    settle(table, mid, remote[0].candidate_id)
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].current_hp < hp
    assert after.state.actors[ALLY].position == position
    assert not any(c.condition_id.startswith(RELAY + '.') for c in after.state.actors[ALLY].conditions.values())


def test_relay_preserves_self_teleport_until_remote_picker_lock_round(tmp_path):
    combat, table, mid = fixture(tmp_path, [TALENT], ally_talents=['TAL_VOID_EMPTY_STEP'], seed='A2-RELAY-TELEPORT')
    grant(combat, table, mid)
    e = reload(tmp_path, mid)
    options = [c for c in e.legal_candidates() if c.source_definition_id.endswith('.TAL_VOID_EMPTY_STEP')]
    assert options
    assert not any(c.metadata.get('effect_origin') for c in options)
    prompts = settle(table, mid, options[0].candidate_id)
    destination_prompt = next(p for p in prompts
                             if p['context']['reaction_source_id'] == 'choice:needle.teleport_destination')
    # A manual teleport's action candidate is a placeholder; the player's
    # published map choice supplies the actual landing square.
    chosen = destination_prompt['choice']['options'][0]['cell']
    after = reload(tmp_path, mid)
    assert (after.state.actors[ALLY].position.x, after.state.actors[ALLY].position.y) == (chosen['x'], chosen['y'])
    assert any(c.condition_id.startswith(RELAY + '.') for c in after.state.actors[ALLY].conditions.values())


def test_without_relay_talent_pulse_adds_no_grant_or_remote_technique(tmp_path):
    combat, table, mid = fixture(tmp_path, ['tianxia.talent.formations.gate_keeper'],
                                ally_talents=['TAL_FATE_BINDING_WORD'], seed='A2-RELAY-UNOWNED')
    prompts = grant(combat, table, mid)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.formation_thread_relay' for p in prompts)
    e = reload(tmp_path, mid)
    assert not any(c.condition_id.startswith(RELAY + '.') for c in e.state.actors[ALLY].conditions.values())
    assert not any(c.metadata.get('effect_origin') for c in e.legal_candidates())


def maze_fight(tmp_path, kind, legacy=False):
    bundles = [compile_character(sheet(talents, cl=15, dc=25), actor_id=aid, reaction_plan={'ask': True})
               for aid, talents in [(OWNER, [MAZE]), (ALLY, []), (FOE, [])]]
    if legacy:
        for row in bundles[0]['action_catalog']:
            row['parameters'].get('typed', {}).get('numbers', {}).pop('formation_maze_map_anchors', None)
        seal(bundles[0])
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = to_battlefield(normalize_map({'width_squares': 20, 'height_squares': 14,
        'objects': [{'id': 1, 'kind': kind, 'name': 'Eastern doorway', 'x': 5, 'y': 7, 'blocks': False},
                    {'id': 2, 'kind': 'door', 'name': 'Distant door', 'x': 15, 'y': 7}]}))
    mid = combat._finish_factory_match(bundles, [OWNER, ALLY, FOE],
        {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 7, 'y': 6}},
        arena, [OWNER, ALLY], [FOE], control_modes={aid: 'MANUAL' for aid in (OWNER, ALLY, FOE)},
        match_seed='A2-MAZE', display_name='Maze doors', maximum_rounds=10)['match_id']
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(5, 6)).candidate_id)
    return combat, table, mid


@pytest.mark.parametrize('kind,legacy', [('door', False), ('gate', False), ('door', True)])
def test_maze_map_anchor_choice_movement_and_cold_reload(tmp_path, kind, legacy):
    combat, table, mid = maze_fight(tmp_path, kind, legacy)
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'],
                     {'choice:needle.formation_maze': 'first' if legacy else 'object:object:map.1'})
    while table.state(mid)['menu']['actor_id'] != FOE:
        prompts += settle(table, mid, table.state(mid)['menu']['end_turn'],
                          {'choice:needle.formation_maze': 'first' if legacy else 'object:object:map.1'})
    p = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.formation_maze')
    ids = {o['id'] for o in p['choice']['options']}
    assert ('Doors and exits also need the GM' in p['moment']) == legacy
    assert ('object:object:map.1' in ids) == (not legacy)
    assert 'object:object:map.2' not in ids
    e = reload(tmp_path, mid)
    held = [c for c in e.state.actors[FOE].conditions.values() if c.condition_id == LOST]
    assert held
    if not legacy:
        assert held[0].data['anchor'] == 'object:object:map.1'
        assert 'Eastern doorway' in held[0].data['label']
    moves = [c for c in e.legal_candidates() if c.display_name.startswith('Move')]
    assert moves
    from combat.ext.formation_riders import _anchor_live
    anchor = _anchor_live(e, held[0])[1]
    for c in moves:
        previous = e.state.actors[FOE].position
        for step in (*c.canonical_path, c.destination):
            assert e.grid.distance_ft(step, anchor) >= e.grid.distance_ft(previous, anchor)
            previous = step
    settle(table, mid, moves[0].candidate_id)
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].position == moves[0].destination
    assert any(c.data == held[0].data for c in after.state.actors[FOE].conditions.values() if c.condition_id == LOST)
