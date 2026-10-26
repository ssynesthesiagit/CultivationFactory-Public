"""Acquired Unimpeded Positioning through native map admission and commits.

No model transport, GUI, injected passive, resource mutation or success flag.
"""
import json
import zipfile

import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat import embedding_rank, menu_rank
from tests.h1_support import ROOT, sheet
from tests.auto8f1_table_support import candidate_id, reload_identical

# Real compiler inputs must remain in the safe public dependency closure.
def _table(combat, tmp_path):
    """The app wires the canonical catalog into the table service (app/api.py); tests must too."""
    from canonical_catalog import CanonicalCatalogAuthorityService
    table = TabletopService(combat, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return table


SOURCE_INPUTS = (
    'authority/typed_mechanics/reviewed_final.d/auto8-athletics.json',
    'combat/rules/feature_blocks.json',
    'combat/rules/feature_blocks.d/mgr-t16-athletics-travel.json',
)
SOURCE = 'TAL_ATHLETICS_UNIMPEDED_POSITIONING'
TRAVEL = 'TAL_ATHLETICS_BODY_BEYOND_DISTANCE'
FOCUS = 'resource:core.martial_focus'
# Project ids are hex (tabletop store contract); actor ids are the prefixed project ids.
POSITIONER = 'a1b2c3d4e5f60718'
OBSERVER = 'b2c3d4e5f6071829'
A = FACTORY_ACTOR_PREFIX + POSITIONER
B = FACTORY_ACTOR_PREFIX + OBSERVER


@pytest.fixture(autouse=True)
def fake_embedding_transport(monkeypatch):
    def transport(url, body, timeout):
        texts = json.loads(body)['input']
        return json.dumps({'data': [{'index': i, 'embedding': [1.0] * embedding_rank.DIMENSION}
                                     for i in range(len(texts))]}).encode()
    client = menu_rank.default_client()
    monkeypatch.setattr(client, 'transport', transport)
    monkeypatch.setattr(client, 'background', False)


def game(tmp_path, monkeypatch, *, owned=True, extra=None, observer_sources=None):
    for name in (POSITIONER, OBSERVER):
        sources = (observer_sources if name == OBSERVER and observer_sources is not None
                   else ['ATHLETICS_BASE_COORDINATED_MOVEMENT'])
        doc = sheet(sources, cl=15, name=name)
        folder = tmp_path / 'portable_characters' / name
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    maps = CombatService(ROOT, tmp_path).tabletop_maps
    document = {'display_name': 'Positioning scene', 'width_squares': 20, 'height_squares': 10,
                'terrain': [{'type': 'DIFFICULT', 'cells': [[x, 1] for x in range(1, 7)]}]}
    if extra:
        if 'terrain' in extra:
            document['terrain'].extend(extra['terrain'])
        document.update({k: v for k, v in extra.items() if k != 'terrain'})
    maps.save(document)
    def cold():
        return CombatService(ROOT, tmp_path)
    table = _table(cold(), tmp_path)
    if owned:
        table.add_advancement(POSITIONER, 'talent', SOURCE)
    table.add_advancement(POSITIONER, 'talent', TRAVEL)
    acquired = cold()._factory_owner_sheet(POSITIONER)
    assert (SOURCE in acquired['spheres_and_talents']['learned_talent_record_ids']) == owned
    state = cold().create_journey(project_ids=[POSITIONER, OBSERVER],
        arena_id='battlefield:map.positioning-scene',
        positions={A: {'x': 0, 'y': 1}, B: {'x': 10, 'y': 5}},
        base_paces={A: 1800, B: 1800})
    jid = state['journey_id']
    def act(kind, payload=None, aid=A):
        before = cold().journey_state(jid)
        result = cold().journey_act(jid, before['revision'], aid, kind, payload)
        assert cold().journey_state(jid) == result
        return result
    return cold, jid, act


def move(act, x, y=1):
    return act('move', {'path': [{'x': x, 'y': y}]})


def test_journey_waiver_is_limited_to_its_owned_feature():
    from combat.ext.athletics import journey_difficult_terrain

    session = type('Session', (), {'state': {'actors': {
        'a': {'resources': {FOCUS: 1}, 'bundle': {'typed_passives': [
            {'block': 'motion', 'kind': 'ignore_difficult', 'feature_id': 'TAL_OTHER',
             'while': 'martial_focus'},
        ]}}
    }}})()
    assert journey_difficult_terrain(session, 'a', None, None, []) is None
    session.state['actors']['a']['bundle']['typed_passives'].append(
        {'block': 'motion', 'kind': 'ignore_difficult', 'feature_id': SOURCE,
         'while': 'martial_focus'})
    assert journey_difficult_terrain(session, 'a', None, None, []) == {
        'ignore_nonmagical_difficult': True}


def test_acquisition_native_map_focus_loss_and_cold_continuation(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    first = move(act, 1)
    assert first['seconds'] == 10
    assert first['actors'][A]['resources'][FOCUS] == 1
    spent = act('activate', {'source': TRAVEL})
    assert spent['actors'][A]['resources'][FOCUS] == 0
    # Body Beyond Distance's sourced tenfold overland pace remains intact;
    # it does not waive this unnamed difficult ground without Martial Focus.
    second = move(act, 2)
    assert second['seconds'] == 12
    assert second['events'][-1]['seconds_taken'] == 2
    third = move(act, 3)
    assert third['seconds'] == 14
    assert third['actors'][A]['position'] == {'x': 3, 'y': 1}
    with pytest.raises(ValueError, match='refresh'):
        cold().journey_act(jid, first['revision'], A, 'move', {'path': [{'x': 2, 'y': 1}]})
    assert cold().journey_state(jid) == third
    assert cold().journey_replay(jid)['commands'] == 4
    assert cold().journey_state(jid) == third


def test_native_journey_replay_rejects_divergence_without_writes(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    move(act, 1)
    path = cold().journeys.path(jid)
    registry = json.loads(path.read_text())
    registry['replays'][jid][0]['commands'][0]['state_sha256'] = '0' * 64
    path.write_text(json.dumps(registry))
    before = path.read_bytes()
    with pytest.raises(ValueError, match='diverged'):
        cold().journey_replay(jid)
    assert path.read_bytes() == before


@pytest.mark.parametrize('owned,cost,extra', [
    (False, 20, None),
    (True, 30, {'travel_regions': [{'kind': 'forest', 'cells': [[1, 1]],
                                'ordinary': False, 'movement_cost': 3}]}),
    (True, 30, {'travel_regions': [{'kind': 'forest', 'cells': [[1, 1]],
                                'ordinary': True, 'movement_cost': 3}]}),
])
def test_nonowner_magical_ground_and_other_costs(tmp_path, monkeypatch, owned, cost, extra):
    cold, jid, act = game(tmp_path, monkeypatch, owned=owned, extra=extra)
    result = move(act, 1)
    assert result['seconds'] == cost
    assert result['actors'][A]['resources'][FOCUS] == 1


@pytest.mark.parametrize('owned,spent,cost', [(True, False, 10), (False, False, 20), (True, True, 2)])
def test_native_named_rubble_uses_the_same_focus_price(tmp_path, monkeypatch, owned, spent, cost):
    cold, jid, act = game(tmp_path, monkeypatch, owned=owned,
        extra={'materials': [{'material': 'terrain:loose rubble', 'cells': [[1, 2]]}]})
    if spent:
        act('activate', {'source': TRAVEL})
    result = move(act, 1, 2)
    assert result['seconds'] == cost
    assert result['actors'][A]['position'] == {'x': 1, 'y': 2}
    assert cold().journey_replay(jid)['status'] == 'PASS'


@pytest.mark.parametrize('extra', [
    {'walls': [{'shape': 'rect', 'points': [[1, 1], [2, 2]], 'filled': True}]},
    {'travel_regions': [{'kind': 'water', 'cells': [[1, 1]], 'requires_support': True}]},
])
def test_exemption_does_not_admit_blocked_or_unsupported_routes(tmp_path, monkeypatch, extra):
    cold, jid, act = game(tmp_path, monkeypatch, extra=extra)
    before = cold().journey_state(jid)
    assert not any(o['kind'] == 'move' and o['payload']['path'] == [{'x': 1, 'y': 1}]
                   for o in cold().journey_menu(jid, A)['options'])
    with pytest.raises(ValueError):
        move(act, 1)
    assert cold().journey_state(jid) == before
    assert cold().journey_replay(jid)['commands'] == 0


def test_combat_focus_regain_native_budget_cold_replay_then_map(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    act('activate', {'source': TRAVEL})  # Native Focus expenditure, not fixture state.
    state = cold().journey_state(jid)
    result = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'},
                                       maximum_rounds=2)
    mid = result['match_id']
    table = _table(cold(), tmp_path)
    def menu():
        return table.state(mid)['menu']
    def commit(cid):
        m = menu()
        result = table.act(mid, cid, m['decision_id'], m['state_version'], 0, [])
        assert result['status'] == 'COMMITTED', result
    for _ in range(4):
        if cold()._load_session(mid).engine.state.current_actor_id == A:
            break
        commit(menu()['end_turn'])
    def actor():
        return cold()._load_session(mid).engine.state.actors[A]
    def route(x):
        m = menu()
        old = actor().position.model_dump(mode='json')
        path = [old, {'x': x, 'y': 1}]
        quote = table.preview_move_path(mid, m['decision_id'], m['state_version'], A, path)
        result = table.commit_move_path(mid, quote['candidate']['candidate_id'],
            m['decision_id'], m['state_version'], A, path, reactions=[])
        assert result['status'] == 'COMMITTED', result
    before = actor().movement_remaining_ft
    assert actor().resources[FOCUS] == 0
    route(1)
    assert actor().movement_remaining_ft == before - 10
    commit(candidate_id(menu(), 'Dash'))
    assert actor().resources[FOCUS] == 1
    before = actor().movement_remaining_ft
    route(2)
    assert actor().movement_remaining_ft == before - 5
    reload_identical(cold(), mid, tmp_path)
    for _ in range(8):
        if cold()._load_session(mid).engine.state.terminal_result is not None:
            break
        commit(menu()['end_turn'])
    reload_identical(cold(), mid, tmp_path)
    state = cold().journey_state(jid)
    resumed = cold().journey_resume(jid, state['revision'])
    assert resumed['actors'][A]['resources'][FOCUS] == 1
    start = resumed['seconds']
    assert move(act, 3)['seconds'] == start + 10
    assert cold().journey_replay(jid)['status'] == 'PASS'


def test_native_ability_created_difficult_ground_is_not_waived(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch,
                          observer_sources=['ASH_BASE_ASHFALL', 'ASH_TAL_SOOT_IN_LUNGS'])
    match = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, maximum_rounds=4)
    mid = match['match_id']
    table = _table(cold(), tmp_path)
    def commit(cid, answers=None):
        menu = table.state(mid)['menu']
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers or [])
        assert result['status'] == 'COMMITTED', result
    for _ in range(4):
        if cold()._load_session(mid).engine.state.current_actor_id == B:
            break
        commit(table.state(mid)['menu']['end_turn'])
    engine = cold()._load_session(mid).engine
    cast = next(c for c in engine.legal_candidates()
                if c.display_name.startswith('Ashfall') and c.destination is not None
                and (c.destination.x, c.destination.y) == (3, 1))
    commit(cast.candidate_id)
    for _ in range(4):
        if cold()._load_session(mid).engine.state.current_actor_id == A:
            break
        commit(table.state(mid)['menu']['end_turn'])
    engine = cold()._load_session(mid).engine
    actor = engine.state.actors[A]
    assert actor.resources[FOCUS] == 1
    # The native enemy cast, not a test-authored zone/receipt, made this
    # difficult ground. Unimpeded Positioning grants no area exemption.
    from combat import zones
    assert (1, 1) in zones.difficult_cells(engine, actor)
    menu = table.state(mid)['menu']
    path = [actor.position.model_dump(mode='json'), {'x': 1, 'y': 1}]
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], A, path)
    assert quote['candidate']['movement_cost_ft'] == 10
    before = actor.movement_remaining_ft
    result = table.commit_move_path(mid, quote['candidate']['candidate_id'],
        menu['decision_id'], menu['state_version'], A, path, reactions=[])
    assert result['status'] == 'COMMITTED', result
    after = cold()._load_session(mid).engine.state.actors[A]
    assert after.movement_remaining_ft == before - 10
    assert after.position.model_dump(mode='json') == {'x': 1, 'y': 1}
    reload_identical(cold(), mid, tmp_path)


def test_pre_change_registry_without_replay_journal_still_accepts_moves(tmp_path, monkeypatch):
    # A journey saved before replay journals existed has no 'replays' entry.
    cold, jid, act = game(tmp_path, monkeypatch)
    path = cold().journeys.path(jid)
    registry = json.loads(path.read_text())
    registry.pop('replays')
    path.write_text(json.dumps(registry))
    state = move(act, 1)
    assert state['actors'][A]['position'] == {'x': 1, 'y': 1}
    assert cold().journey_state(jid) == state
    # Commands from here on replay from the admission checkpoint taken at the first move.
    assert cold().journey_replay(jid)['status'] == 'PASS'


def test_non_plain_journey_payload_is_refused_before_persistence(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    before_state = cold().journey_state(jid)
    path = cold().journeys.path(jid)
    before_bytes = path.read_bytes()
    with pytest.raises(ValueError, match='plain'):
        act('move', {'path': [{'x': 1.5, 'y': 1}]})
    with pytest.raises(ValueError, match='plain'):
        act('move', {'path': [{'x': 1, 'y': 1}], 'extra': {1: 'not text key'}})
    assert cold().journey_state(jid) == before_state
    assert path.read_bytes() == before_bytes


def test_painted_difficult_ground_is_marked_nonmagical_for_the_focus_waiver():
    from combat.tabletop import to_battlefield
    document = {'display_name': 'Positioning scene', 'width_squares': 20, 'height_squares': 10,
                'terrain': [{'type': 'DIFFICULT', 'cells': [[x, 1] for x in range(1, 7)]}]}
    from combat.tabletop import normalize_map
    painted = [r for r in to_battlefield(normalize_map(document))['terrain_regions']
               if r['movement_cost'] == 2 and r['terrain_type'] == 'OPEN']
    assert painted and all(r.get('nonmagical_difficult') == 1 for r in painted)

