"""Native table learning, admitted finite sources, journey and combat cold replay."""
from copy import deepcopy
import json, zipfile
import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet, mechanics
PID, QID = '0badc0de-1400-4000-8000-000000000001', '0badc0de-1400-4000-8000-000000000002'
A, B = FACTORY_ACTOR_PREFIX + PID, FACTORY_ACTOR_PREFIX + QID
CLEAN, STOCK = 'HARVESTING_GATHERING_BASE_CLEAN_HARVEST', 'resource:named.reagent_stock'


def game(tmp_path, monkeypatch, *, features=(CLEAN, 'ALCHEMY_BASE_REAGENT_STOCK'), cl=5, natural=None, body=False, objects=None):
    base = sheet([], cl=cl, name='Gatherer', primary='Stamina' if body else 'Qi')
    path_id = 'tianxia.path.body_refining' if body else 'tianxia.path.qi_cultivation'
    base['identity']['proficiency_bonus'] = 2 + (cl - 1) // 4
    if cl == 5:
        next(a for a in base['ability_scores_and_statistics']['abilities'] if a['ability'] == 'WIS').update(score=16, modifier=3)
    base['identity']['path_ids'] = [path_id]
    base['path_and_subpath'] = {'path_record_ids': [path_id]}
    service = CombatService(ROOT, tmp_path)
    for pid in (PID, QID):
        path = service.combatant_library.install_root / pid / 'current.zip'; path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(base))
    table = TabletopService(service, tmp_path); table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    for sphere in sorted({mechanics()[f]['sphere_id'] for f in features}):
        table.add_advancement(PID, 'sphere', sphere)
    token = '140000000000000000000001'
    if natural is not None:
        from combat.gate2_rolls import DeterministicRollAuthority
        for counter in range(10000):
            token = f'{counter:024x}'
            if DeterministicRollAuthority('journey-' + token + ':harvest').d20(modifier=0, actor_id=A, reason='CHECK:Gathering').natural_result == natural:
                break
    monkeypatch.setattr('combat.journey.secrets.token_hex', lambda n: token)
    arena = {'stable_id': 'material:field', 'width_squares': 10, 'height_squares': 5,
             'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    if objects is not None:
        from combat.tabletop import to_battlefield, normalize_map
        arena = to_battlefield(normalize_map({'width_squares': 10, 'height_squares': 5, 'objects': objects}))
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'field': deepcopy(arena)})
    state = service.create_journey(project_ids=[PID, QID], arena_id='field', positions={A: {'x': 1, 'y': 1}, B: {'x': 8, 'y': 1}}, base_paces={A: 1800, B: 1800})
    jid = state['journey_id']
    def cold(): return CombatService(ROOT, tmp_path)
    def act(kind, payload=None, aid=A):
        fresh = cold(); rev = fresh.journey_state(jid)['revision']
        result = fresh.journey_act(jid, rev, aid, kind, payload)
        assert cold().journey_state(jid, viewer_id=aid) == result
        return result
    def admit(kind, payload, aid=A, gm=True):
        fresh = cold(); rev = fresh.journey_state(jid)['revision']
        return fresh.journey_admit(jid, rev, aid, kind, payload, gm=gm, reason='Named scene owner recorded actual supplies and site examination.')
    return cold, jid, act, admit


def supply(admit, act, sid, kind, quantity, *, material=None, unit='portion', harvest=None):
    row = {'id': sid, 'name': sid.replace('-', ' ').title(), 'kind': kind, 'context': 'scene',
           'material': material or kind, 'unit': unit, 'quantity': quantity, 'known_to': [A], 'exclusive_to': A}
    if harvest is not None: row['harvest'] = harvest
    admit('material_source', row)
    if harvest is None: act('collect_material', {'source': sid, 'quantity': quantity})
    return sid + ':' + str(quantity)


def site(admit, act, *, dc=10, quantity=4):
    tool = supply(admit, act, 'sickle', 'harvest_tool', 1, material='sickle')
    jar = supply(admit, act, 'jars', 'container', 10)
    supply(admit, act, 'moon-herb', 'raw_material', quantity, harvest={'dc': dc, 'perfect': 1,
        'methods': ['sickle'], 'facts': [{'kind':'survival','text':'This root survives a careful cut.'}], 'hazards': [], 'harm': 1, 'ripeness': 'ripe', 'failure_outcome': 'bruised'})
    act('gathering_key', {'ability': 'WIS'})
    return {'source': 'moon-herb', 'tool': tool, 'container': jar}


def test_newly_acquired_stock_requires_actual_preparation(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch)
    actual = cold().journeys.load(jid).state['actors'][A]
    assert 'ALCHEMY_BASE_REAGENT_STOCK' in actual['bundle']['material_abilities']['owned']
    assert actual['resources'][STOCK] == 0
    result = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, maximum_rounds=1)
    loaded = cold()._load_session(result['match_id'])
    assert loaded.engine.state.actors[A].resources[STOCK] == 0
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_paid_rest_fold_spoil_and_native_combat_spend(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch)
    reagents = supply(admit, act, 'purchased-reagents', 'common_reagents', 50, unit='gp')
    act('prepare_reagents', {'new_uses': 3, 'fold_uses': 0, 'materials': {reagents: 30}})
    assert cold().journeys.load(jid).state['actors'][A]['resources'][STOCK] == 0
    state = act('long_rest')
    assert state['seconds'] == 28800 and state['actors'][A]['resources'][STOCK] == 3
    assert state['actors'][A]['material_holdings'][reagents]['quantity'] == 20
    assert cold().journeys.replay(jid)['status'] == 'PASS'
    act('prepare_reagents', {'new_uses': 1, 'fold_uses': 1, 'materials': {reagents: 10}})
    state = act('long_rest'); assert state['actors'][A]['resources'][STOCK] == 2
    assert cold().journeys.replay(jid)['status'] == 'PASS'
    result = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'}, maximum_rounds=2)
    mid = result['match_id']; table = TabletopService(cold(), tmp_path)
    for _ in range(3):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == A: break
        assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0)['status'] == 'COMMITTED'
    engine = cold()._load_session(mid).engine
    candidates = [c for c in engine.legal_candidates() if (STOCK, 1) in engine.action_catalog[c.source_definition_id].costs]
    assert candidates
    c = next((c for c in candidates if c.target_ids == (A,)), candidates[0])
    assert table.act(mid, c.candidate_id, c.decision_id, c.state_version, 0)['status'] == 'COMMITTED'
    loaded = cold()._load_session(mid)
    assert loaded.engine.state.actors[A].resources[STOCK] == 1
    assert loaded.engine.state.actors[B].resources.get(STOCK, 0) == 0
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('natural,dc,choice,quality,count', [(10,10,'pure','Pure',1), (10,6,'perfect','Perfect',1),
    (10,6,'extra+pure','Pure',2), (10,16,'normal','Normal',1), (10,17,'bruised','Bruised',1),
    (10,21,'bruised','Bruised',1), (10,22,'lost',None,0), (1,1,'lost',None,0)])
def test_harvest_margin_source_debit_quality_choice_and_cold_replay(tmp_path, monkeypatch, natural, dc, choice, quality, count):
    cold, jid, act, admit = game(tmp_path, monkeypatch, natural=natural)
    payload = site(admit, act, dc=dc); before = cold().journey_state(jid)['seconds']
    assert act('harvest_begin', payload)['seconds'] == before + 600
    if choice == 'lost':
        result = cold().journey_state(jid, viewer_id=A)
        assert any(e['kind'] == 'HARVEST_PORTION_LOST' for e in result['events'])
    else:
        option = next(o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'harvest_finish' and o['payload'] == {'choice': choice, 'product': 'lot'})
        result = act(option['kind'], option['payload'])
    lots = [r for r in result['actors'][A]['material_holdings'].values() if r['kind'] == 'harvest_lot']
    assert sum(r['quantity'] for r in lots) == count
    if quality: assert lots[0]['quality'] == quality and lots[0]['source_id'] == 'moon-herb' and lots[0]['packaged'] == 1
    source = cold().journeys.load(jid).state['material_sources']['moon-herb']
    assert source['remaining'] == 4 - max(count,1)
    assert cold().journeys.replay(jid)['status'] == 'PASS'


def test_private_facts_preservation_and_no_unknown_facts(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, natural=20)
    act('harvest_begin', site(admit, act))
    result = act('harvest_finish', {'choice': 'preserve+fact', 'product': 'ingredient', 'fact': 0})
    assert not cold().journeys.load(jid).state['material_sources']['moon-herb'].get('harmed')
    assert any(e['kind'] == 'HARVEST_FACT' for e in result['events'])
    hidden = json.dumps(cold().journey_state(jid, viewer_id=B))
    assert 'This root survives' not in hidden and 'material_sources' not in hidden
    assert cold().journeys.replay(jid)['status'] == 'PASS'


def test_wrong_owner_bad_inputs_depletion_and_no_default_supply(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, natural=20)
    payload = site(admit, act, quantity=1); before = cold().journey_state(jid)
    for kind, data, aid in [('harvest_begin',payload,B),('harvest_begin',{**payload,'tool':'invented'},A),
        ('collect_material',{'source':'moon-herb','quantity':1},A),
        ('prepare_reagents',{'new_uses':1,'fold_uses':0,'materials':{'invented':10}},A)]:
        with pytest.raises(ValueError): act(kind,data,aid)
        assert cold().journey_state(jid) == before
    with pytest.raises(ValueError, match='Only the GM'): admit('material_source',{},gm=False)
    act('harvest_begin',payload)
    assert all('extra' not in o['payload'].get('choice','') for o in cold().journey_menu(jid,A)['options'])
    act('harvest_finish',{'choice':'perfect','product':'lot'})
    with pytest.raises(ValueError): act('harvest_begin',payload)
    assert cold().journeys.replay(jid)['status'] == 'PASS'
