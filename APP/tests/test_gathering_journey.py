"""Harvesting and Gathering in the journey: Gathering Check, Lots, Seal the Essence."""
from copy import deepcopy
import json
import zipfile
import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

PID, QID = '0badc0de-1800-4000-8000-000000000001', '0badc0de-1800-4000-8000-000000000002'
A, B = FACTORY_ACTOR_PREFIX + PID, FACTORY_ACTOR_PREFIX + QID


def game(tmp_path, monkeypatch, *, talents=(), insights=(), cl=5, automatic=False):
    """A Path owner who learned the sphere (and the named talents) at the table, then native travel."""
    base = sheet([], cl=cl, name='Gatherer')
    base['identity'].update(proficiency_bonus=3, path_ids=['tianxia.path.qi_cultivation'])
    base['path_and_subpath'] = {'path_record_ids': ['tianxia.path.qi_cultivation']}
    if insights:
        base.setdefault('spheres_and_talents', {})['cultivation_insight_record_ids'] = list(insights)
    service = CombatService(ROOT, tmp_path)
    for pid in (PID, QID):
        path = service.combatant_library.install_root / pid / 'current.zip'
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(base))
    table = TabletopService(service, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    table.add_advancement(PID, 'sphere', 'tianxia.sphere.harvesting_gathering')
    for talent in talents:
        table.add_advancement(PID, 'talent', talent)
    table.save_reactions(PID, {'mode': 'ask'})
    monkeypatch.setattr('combat.journey.secrets.token_hex', lambda n: '180000000000000000000001')
    arena = {'stable_id': 'gather:field', 'display_name': 'Herb slope', 'width_squares': 10, 'height_squares': 8,
             'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'field': deepcopy(arena)})
    state = service.create_journey(project_ids=[PID, QID], arena_id='field',
        positions={A: {'x': 1, 'y': 1}, B: {'x': 8, 'y': 1}}, base_paces={A: 1800, B: 1800},
        control_modes={A: 'LOCAL_AUTO' if automatic else 'MANUAL', B: 'MANUAL'})
    jid = state['journey_id']

    def cold():
        return CombatService(ROOT, tmp_path)

    def act(kind, payload=None, aid=A):
        fresh = cold()
        result = fresh.journey_act(jid, fresh.journey_state(jid)['revision'], aid, kind, payload)
        assert cold().journey_state(jid, viewer_id=aid) == result
        return result

    def admit(kind, payload, aid=A, gm=True):
        fresh = cold()
        return fresh.journey_admit(jid, fresh.journey_state(jid)['revision'], aid, kind, payload, gm=gm,
                                   reason='Scenario owner: a real herb patch on the slope, examined before harvest.')
    return cold, jid, act, admit


def patch(name='patch', *, dc=12, rarity='common', category='herb', lots=6, **more):
    harvest = {'dc': dc, 'rarity': rarity, 'category': category, 'hazard': 'Biting insects boil out of the bark.',
               'facts': ['Silverleaf grows here.', 'It is ripe.', 'The root survives a careful cut.', 'A boar den lies uphill.'],
               'sign_dc': 10, 'perfect': True, **more}
    return {'id': name, 'name': name.title(), 'kind': 'raw_material', 'context': 'wilderness_route', 'material': 'silverleaf',
            'unit': 'lot', 'quantity': lots, 'known_to': [A], 'exclusive_to': A, 'harvest': harvest}


from combat.ext import gathering as G, material_ledger as ledger

CLEAN = 'HARVESTING_GATHERING_BASE_CLEAN_HARVEST'
T = 'tianxia.talent.harvesting_gathering.'


def loaded(cold, jid):
    return cold().journeys.load(jid)


def resolve(session, tier, *, method='standard', source_id='patch', **payload):
    """The printed outcome of one tier for this character, without a roll."""
    source = ledger.sources(session)[source_id]
    return G._lots_for(session, A, source, source['harvest'], G._method(session, A, method, source), tier, payload)


def test_the_margin_table_is_the_printed_one():
    assert [G.tier_of(n, t, 15) for n, t in ((1, 40), (10, 4), (10, 10), (10, 15), (10, 20), (10, 25))] == \
        ['nat1', 'fail_gt5', 'fail_le5', 'success', 'plus5', 'plus10']
    assert [G.tier_of(10, t, 15) for t in (9, 10, 14, 15, 19, 20, 24, 25)] == \
        ['fail_gt5', 'fail_le5', 'fail_le5', 'success', 'success', 'plus5', 'plus5', 'plus10']


def test_each_tier_makes_its_printed_lots(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, automatic=True)
    admit('harvest_source', patch(lots=6))
    s = loaded(cold, jid)
    assert resolve(s, 'success')['lots'] == ['normal']
    assert resolve(s, 'plus5')['lots'] == ['normal', 'normal'] and resolve(s, 'plus5')['benefits'] == ['extra_lot']
    assert resolve(s, 'plus5', benefits=['pure'])['lots'] == ['pure']
    assert resolve(s, 'plus10')['lots'] == ['perfect'] and resolve(s, 'fail_le5')['lots'] == ['bruised']
    assert resolve(s, 'fail_gt5')['lots'] == [] and resolve(s, 'nat1')['lots'] == []
    with pytest.raises(ValueError):
        resolve(s, 'plus5', benefits=['extra_lot', 'pure'])  # one benefit at plus 5
    admit('harvest_source', patch('thin', perfect=False, lots=6))
    two = resolve(loaded(cold, jid), 'plus10', source_id='thin')
    assert two['lots'] == ['pure', 'normal'] and len(two['benefits']) == 2


def test_a_harvest_rolls_resolves_and_takes_ten_minutes(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch)
    admit('harvest_source', patch(dc=1, lots=3))
    assert any(o['kind'] == 'clean_harvest' for o in cold().journey_menu(jid, A)['options'])
    with pytest.raises(ValueError, match='Clean Harvest'):
        act('collect_material', {'source': 'patch', 'quantity': 1})
    act('clean_harvest', {'source': 'patch'})
    state = cold().journeys.load(jid).state
    check = next(e for e in state['events'] if e['kind'] == 'HARVEST_CHECK')
    done = next(e for e in state['events'] if e['kind'] == 'HARVEST_RESOLVED')
    assert check['tier'] == G.tier_of(check['roll']['natural_result'], check['roll']['total'], check['dc']) == done['tier']
    assert check['roll']['modifier'] == state['actors'][A]['bundle']['material_abilities']['pb'] + state['actors'][A]['bundle']['material_abilities']['key_mod']
    assert state['seconds'] == 600
    held = [row for row in state['actors'][A]['material_holdings'].values() if row.get('lot')]
    assert [row['lot']['quality'] for row in held] == done['lots'] and all(row['lot']['rarity'] == 'common' for row in held)
    assert cold().journeys.replay(jid)['status'] == 'PASS'
    assert 'material_holdings' not in cold().journey_state(jid, B)['actors'][A]


def test_only_a_gatherer_harvests_and_a_living_source_is_not_made_up(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch)
    admit('harvest_source', patch())
    with pytest.raises(ValueError, match='Only the GM'):
        admit('harvest_source', patch('other'), gm=False)
    with pytest.raises(ValueError):
        act('clean_harvest', {'source': 'patch'}, aid=B)
    with pytest.raises(ValueError, match='typed harvest'):
        admit('harvest_source', {**patch('bad'), 'harvest': {'dc': 10}})


def test_cut_talents_refine_the_table_and_cost_what_they_print(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, cl=15,
                                 talents=[T + 'jade_knife_clean_cut', T + 'sovereign_clean_cut', T + 'clean_sickle_method'])
    admit('harvest_source', patch('moss', category='spiritual_plant', rarity='rare', lots=4))
    admit('harvest_source', patch('dragon', category='mineral', rarity='very_rare', lots=4, perfect=False))
    s = loaded(cold, jid)
    assert resolve(s, 'success', method='jade_knife', source_id='moss')['lots'] == ['pure']
    assert resolve(s, 'fail_le5', method='jade_knife', source_id='moss')['lots'] == ['normal']
    assert resolve(s, 'fail_gt5', method='jade_knife', source_id='moss')['lots'] == []
    with pytest.raises(ValueError, match='rarity'):
        resolve(s, 'success', method='sovereign_cut', source_id='moss')
    assert resolve(s, 'success', method='sovereign_cut', source_id='dragon')['lots'] == ['pure']
    assert resolve(s, 'plus5', method='sovereign_cut', source_id='dragon', benefits=[])['lots'] == ['perfect']
    assert resolve(s, 'fail_le5', method='sovereign_cut', source_id='dragon')['lots'] == ['normal']
    saved = resolve(s, 'fail_gt5', method='sovereign_cut', source_id='dragon', save_source=True)
    assert saved['lots'] == [] and saved['saved'] and saved['spared']
    # the Sickle spares a plant source that is cut well, and the paid methods are offered only when payable
    assert resolve(s, 'plus5', source_id='moss', benefits=['pure'])['spared'] is True
    assert resolve(s, 'plus5', source_id='dragon', benefits=['pure'])['spared'] is False
    before = cold().journeys.load(jid).state['actors'][A]['resources']['resource:core.qi']
    act('clean_harvest', {'source': 'moss', 'method': 'jade_knife'})
    state = cold().journeys.load(jid).state
    assert state['actors'][A]['resources']['resource:core.qi'] == before - 1
    check = next(e for e in state['events'] if e['kind'] == 'HARVEST_CHECK')
    numbers = state['actors'][A]['bundle']['material_abilities']
    assert check['roll']['modifier'] == numbers['pb'] + numbers['key_mod']  # no proper harvest tool was supplied


def test_natural_one_loses_attempted_material_even_when_source_is_spared(tmp_path, monkeypatch):
    from types import SimpleNamespace
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'source_sparing_harvest'])
    admit('harvest_source', patch('grove', rarity='uncommon', category='spiritual_plant', living=True, lots=6))
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=1, total=1, model_dump=lambda **kwargs: {'natural_result': 1, 'total': 1}))
    act('clean_harvest', {'source': 'grove', 'method': 'source_sparing'})
    state = cold().journeys.load(jid).state
    assert state['material_sources']['grove']['remaining'] == 5
    assert any(e['kind'] == 'HARVEST_HAZARD' for e in state['events'])


def test_growing_sources_gain_the_printed_choices(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, cl=15,
                                 talents=[T + 'root_left_alive_method', T + 'source_sparing_harvest'])
    admit('harvest_source', patch('grove', rarity='uncommon', category='spiritual_plant', living=True, lots=6))
    admit('harvest_source', patch('vein', rarity='uncommon', category='mineral', lots=6))
    s = loaded(cold, jid)
    rla = resolve(s, 'success', method='root_left_alive', source_id='grove')
    assert rla['lots'] == [] and rla['spared'] is True  # one fewer Lot, minimum 0
    with pytest.raises(ValueError, match='living'):
        resolve(s, 'success', method='root_left_alive', source_id='vein')
    sparing = resolve(s, 'plus5', method='source_sparing', source_id='grove', benefits=[])
    assert sparing['lots'] == ['normal', 'pure'] and sparing['spared'] is True
    assert resolve(s, 'fail_le5', method='source_sparing', source_id='grove')['lots'] == [] \
        and resolve(s, 'fail_le5', method='source_sparing', source_id='grove', on_fail='harm_source')['lots'] == ['bruised']
    assert resolve(s, 'fail_le5', method='source_sparing', source_id='grove', on_fail='harm_source')['spared'] is False


def test_a_beast_core_needs_the_dressing_talent_for_its_rarity(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, cl=5, talents=[T + 'simple_beast_dressing', T + 'beast_core_dressing'])
    admit('harvest_source', patch('core', rarity='rare', category='beast_core', lots=1))
    admit('harvest_source', patch('sovereign', rarity='very_rare', category='beast_core', lots=1))
    act('clean_harvest', {'source': 'core'})
    with pytest.raises(ValueError, match='talent'):
        act('clean_harvest', {'source': 'sovereign'})
    ids = [o['id'] for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'clean_harvest']
    assert not any('sovereign' in i for i in ids)


def test_sovereign_beast_dressing_guarantees_pure_and_allows_optional_perfect(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, cl=15,
        talents=[T + 'simple_beast_dressing', T + 'beast_core_dressing', T + 'sovereign_beast_dressing'])
    admit('harvest_source', patch('sovereign_core', dc=1, rarity='very_rare', category='beast_core',
                                  lots=4, perfect=True))
    s = loaded(cold, jid)
    assert resolve(s, 'success', source_id='sovereign_core')['lots'] == ['normal']
    assert resolve(s, 'plus5', source_id='sovereign_core', benefits=[])['lots'] == ['pure']
    assert resolve(s, 'plus10', source_id='sovereign_core', perfect=False, benefits=[])['lots'] == ['pure']
    assert resolve(s, 'plus10', source_id='sovereign_core')['lots'] == ['perfect']


def test_common_herbcraft_gives_advantage_and_an_extra_lot(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'common_herbcraft'])
    admit('harvest_source', patch('herbs', rarity='common', category='herb', lots=5))
    admit('harvest_source', patch('ore', rarity='common', category='mineral', lots=5))
    s = loaded(cold, jid)
    assert G._check_parts(s, A, 'clean_harvest', s.state['material_sources']['herbs']['harvest'], 'herbs')[1] == 'ADVANTAGE'
    assert G._check_parts(s, A, 'clean_harvest', s.state['material_sources']['ore']['harvest'], 'ore')[1] == 'NORMAL'
    plus = resolve(s, 'plus5', source_id='herbs', benefits=['pure'])
    assert plus['lots'] == ['pure', 'normal'] and plus['benefits'] == ['pure', 'extra_lot:' + T + 'common_herbcraft']
    assert resolve(s, 'plus5', source_id='ore', benefits=['pure'])['lots'] == ['pure']


def test_failed_sign_never_persists_the_hidden_fact(tmp_path, monkeypatch):
    from types import SimpleNamespace
    cold, jid, act, admit = game(tmp_path, monkeypatch)
    admit('harvest_source', patch('hidden', sign_dc=30))
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=10, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 10}))
    act('read_the_sign', {'source': 'hidden'})
    learning = cold().journeys.load(jid).state['actors'][A]['gathering_learning']
    assert learning.get('facts', {}).get('hidden', []) == []
    clue = learning['incomplete_facts']['hidden'][0]
    assert clue.startswith('Silverleaf') and clue.endswith('…') and clue != 'Silverleaf grows here.'


def test_read_the_sign_reveals_facts_and_the_field_ledger_gives_advantage_once(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'field_ledger'])
    admit('harvest_source', patch('slope', dc=1))
    s = loaded(cold, jid)
    harvest = s.state['material_sources']['slope']['harvest']
    assert G._check_parts(s, A, 'read_the_sign', harvest, 'slope')[1] == 'NORMAL'
    from types import SimpleNamespace
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=20, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 20}))
    act('read_the_sign', {'source': 'slope', 'record': True})
    state = cold().journeys.load(jid).state
    sign = next(e for e in state['events'] if e['kind'] == 'HARVEST_SIGN')
    learning = state['actors'][A]['gathering_learning']
    assert len(learning['facts']['slope']) == (3 if sign['success'] else 1) and sign['incomplete'] == 1 - sign['success']
    if sign['success']:
        assert 'slope' in learning['sites']
        s = loaded(cold, jid)
        assert s.state['actors'][A]['gathering_learning']['sites']['slope']['used'] == 1
        assert G._check_parts(s, A, 'clean_harvest', harvest, 'slope')[1] == 'NORMAL'
        act('read_the_sign', {'source': 'slope', 'record': True})
        s = loaded(cold, jid)
        assert G._check_parts(s, A, 'clean_harvest', harvest, 'slope')[1] == 'ADVANTAGE'
        act('clean_harvest', {'source': 'slope'})
        s = loaded(cold, jid)
        assert G._check_parts(s, A, 'clean_harvest', harvest, 'slope')[1] == 'NORMAL'
        act('read_the_sign', {'source': 'slope', 'record': True})
        assert G._check_parts(loaded(cold, jid), A, 'clean_harvest', harvest, 'slope')[1] == 'ADVANTAGE'


def test_sealing_follows_the_character_level_and_the_sealing_talents(tmp_path, monkeypatch):
    assert [G.seal_seconds_for(cl) for cl in (1, 4, 5, 9, 10, 14, 15, 20)] == \
        [7 * 86400, 7 * 86400, 30 * 86400, 30 * 86400, 365 * 86400, 365 * 86400, None, None]
    cold, jid, act, admit = game(tmp_path, monkeypatch, cl=5, talents=[T + 'dew_jar_method'])
    admit('harvest_source', patch('dew', dc=1, rarity='common', category='liquid', lots=6))
    admit('harvest_source', patch('bark', dc=1, rarity='common', category='herb', lots=6))
    for sid in ('dew', 'bark'):
        for _ in range(2):
            act('clean_harvest', {'source': sid, 'method': 'standard', 'benefits': []})
    holdings = cold().journeys.load(jid).state['actors'][A]['material_holdings']
    lots = {key: row for key, row in holdings.items() if row.get('lot')}
    cap = 3 + 2  # Proficiency Bonus + key modifier
    liquid = [k for k, r in lots.items() if r['lot']['category'] == 'liquid']
    plain = [k for k, r in lots.items() if r['lot']['category'] == 'herb']
    start = cold().journeys.load(jid).state['seconds']
    act('seal_essence', {'lots': liquid + plain})
    state = cold().journeys.load(jid).state
    sealed = state['actors'][A]['material_holdings']
    assert state['seconds'] == start + 600
    assert all(sealed[k]['lot']['stable_until'] == start + 30 * 86400 * 2 for k in liquid)  # Dew Jar: twice the duration
    assert all(sealed[k]['lot']['stable_until'] == start + 30 * 86400 for k in plain)
    with pytest.raises(ValueError, match='unsealed'):
        act('seal_essence', {'lots': plain[:1]})
    assert cold().journeys.replay(jid)['status'] == 'PASS'
    assert liquid and plain and cap == numbers_cap(state)


def numbers_cap(state):
    numbers = state['actors'][A]['bundle']['material_abilities']
    return numbers['pb'] + numbers['key_mod']


def test_quick_field_harvest_costs_a_point_or_rolls_with_disadvantage(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'quick_field_harvest'])
    admit('harvest_source', patch('fast', dc=1, rarity='uncommon', lots=4))
    admit('harvest_source', patch('ready', dc=1, rarity='uncommon', lots=4, prepared=True))
    admit('harvest_source', patch('big', dc=1, rarity='rare', lots=4))
    qi = lambda: cold().journeys.load(jid).state['actors'][A]['resources']['resource:core.qi']
    start = qi()
    act('clean_harvest', {'source': 'fast', 'method': 'quick'})
    state = cold().journeys.load(jid).state
    assert qi() == start and next(e for e in state['events'] if e['kind'] == 'HARVEST_CHECK')['mode'] == 'DISADVANTAGE'
    assert state['seconds'] == 60  # one minute of work for an Uncommon material
    act('clean_harvest', {'source': 'fast', 'method': 'quick', 'pay_cp': True})
    assert qi() == start - 1
    act('clean_harvest', {'source': 'ready', 'method': 'quick'})
    checks = [e for e in cold().journeys.load(jid).state['events'] if e['kind'] == 'HARVEST_CHECK']
    assert [c['mode'] for c in checks] == ['DISADVANTAGE', 'NORMAL', 'NORMAL'] and qi() == start - 1
    with pytest.raises(ValueError, match='rarity'):
        act('clean_harvest', {'source': 'big', 'method': 'quick'})


def lot_keys(state, rarity):
    return [k for k, r in state['actors'][A]['material_holdings'].items() if r.get('lot') and r['lot']['rarity'] == rarity]


def test_sealing_talents_stretch_the_count_the_duration_and_the_wards(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, cl=15, insights=['insight.jade-seal-preserver'],
                                 talents=[T + 'drying_shed_method', T + 'spirit_sealing_wax', T + 'spirit_vault_bundle',
                                          T + 'heaven_sealed_vault'])
    admit('harvest_source', patch('sheaf', dc=1, rarity='common', category='herb', lots=12, perfect=False))
    admit('harvest_source', patch('jewel', dc=1, rarity='very_rare', category='mineral', lots=6))
    for _ in range(9):
        act('clean_harvest', {'source': 'sheaf', 'benefits': []})
    for _ in range(4):
        act('clean_harvest', {'source': 'jewel', 'benefits': []})
    state = cold().journeys.load(jid).state
    commons, jewels = lot_keys(state, 'common'), lot_keys(state, 'very_rare')
    cap = numbers_cap(state)
    assert cap < len(commons) <= 2 * cap and jewels  # more Common Lots than the normal count: Drying Shed halves their weight
    with pytest.raises(ValueError, match='at most'):  # the Common Lots weigh half, the Very Rare ones a whole slot each
        act('seal_essence', {'lots': commons[:cap + 1] + jewels[:2 * cap]})
    act('seal_essence', {'lots': commons[:cap], 'choice': 'hide'})
    if len(commons) > cap:
        act('seal_essence', {'lots': commons[cap:], 'choice': 'hide'})
    act('seal_essence', {'lots': jewels[:cap]})
    if len(jewels) > cap:
        act('seal_essence', {'lots': jewels[cap:]})
    sealed = cold().journeys.load(jid).state['actors'][A]['material_holdings']
    assert all(sealed[k]['lot']['stable_until'] is None for k in commons + jewels)  # Cultivation Level 15: indefinitely
    assert all(sealed[k]['lot']['masked'] == 1 for k in commons + jewels)
    assert all(sealed[k]['lot']['scent_hidden'] == 1 for k in commons) and all(sealed[k]['lot']['warded'] == 1 for k in jewels)
    assert not any(sealed[k]['lot']['warded'] for k in commons)


def test_wax_doubles_the_duration_and_the_preserver_lifts_one_bruise(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, cl=10, insights=['insight.jade-seal-preserver'], talents=[T + 'spirit_sealing_wax'])
    admit('harvest_source', patch('rue', dc=1, rarity='uncommon', category='herb', lots=4))
    admit('harvest_source', patch('lotus', dc=1, rarity='rare', category='herb', lots=4))
    for _ in range(3):
        act('clean_harvest', {'source': 'rue', 'benefits': []})
    act('clean_harvest', {'source': 'lotus', 'benefits': []})
    session = cold().journeys.load(jid)
    held = session.state['actors'][A]['material_holdings']
    rue, lotus = lot_keys(session.state, 'uncommon'), lot_keys(session.state, 'rare')
    for key in rue[:2] + lotus:
        held[key]['lot']['quality'] = 'bruised'
    cold().journeys.save(session)
    now = session.state['seconds']
    act('seal_essence', {'lots': rue[:2] + lotus, 'choice': 'double', 'repair_bruise': True})
    sealed = cold().journeys.load(jid).state['actors'][A]['material_holdings']
    assert [sealed[k]['lot']['quality'] for k in rue[:2]] == ['normal', 'bruised']  # one Bruised Lot per sealing
    assert all(sealed[k]['lot']['stable_until'] == now + 365 * 86400 for k in lotus)  # Rare: no Wax, no doubling
    assert all(sealed[k]['lot']['stable_until'] == now + 365 * 86400 * 2 for k in rue[:2])


def test_manual_menus_expose_margin_and_sealing_choices(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'spirit_sealing_wax'])
    admit('harvest_source', patch('patch', dc=1, lots=5))
    from types import SimpleNamespace
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=20, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 20}))
    options = cold().journey_menu(jid, A)['options']
    pure = next(o for o in options if o['kind'] == 'clean_harvest' and o['payload'].get('benefits') == ['pure'])
    act(pure['kind'], pure['payload'])
    lots = lot_keys(cold().journeys.load(jid).state, 'common')
    choices = [o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'seal_essence']
    double = next(o for o in choices if o['payload'].get('choice') == 'double')
    act(double['kind'], double['payload'])
    sealed = cold().journeys.load(jid).state['actors'][A]['material_holdings'][lots[0]]['lot']
    assert sealed['sealed'] == 1 and sealed['stable_until'] == 30 * 86400 * 2


def test_full_field_ledger_read_does_not_rollback_examination(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'field_ledger'])
    admit('harvest_source', patch('new_site', dc=1))
    session = cold().journeys.load(jid)
    sites = session.state['actors'][A].setdefault('gathering_learning', {}).setdefault('sites', {})
    cap = G._site_cap(session, A)
    sites.update({f'old{i}': {'recorded_at': 0, 'used': 1} for i in range(cap)})
    cold().journeys.save(session)
    from types import SimpleNamespace
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=20, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 20}))
    option = next(o for o in cold().journey_menu(jid, A)['options']
                  if o['kind'] == 'read_the_sign' and o['payload']['source'] == 'new_site' and not o['payload'].get('record'))
    act(option['kind'], option['payload'])
    state = cold().journeys.load(jid).state
    assert any(e['kind'] == 'HARVEST_SIGN' and e['source_id'] == 'new_site' and e['success'] for e in state['events'])
    assert 'new_site' not in state['actors'][A]['gathering_learning']['sites']


def test_jade_knife_reaches_printed_beast_organs(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'jade_knife_clean_cut'])
    admit('harvest_source', patch('organ', category='beast_remains', rarity='rare', lots=2))
    option = next(o for o in cold().journey_menu(jid, A)['options']
                  if o['kind'] == 'clean_harvest' and o['payload'].get('source') == 'organ'
                  and o['payload'].get('method') == 'jade_knife')
    from types import SimpleNamespace
    monkeypatch.setattr(G, '_roll', lambda *args, **kwargs: SimpleNamespace(
        natural_result=10, total=20, model_dump=lambda **kwargs: {'natural_result': 10, 'total': 20}))
    act(option['kind'], option['payload'])
    state = cold().journeys.load(jid).state
    assert any(row.get('lot', {}).get('quality') == 'pure'
               for row in state['actors'][A]['material_holdings'].values())

def test_the_supply_officer_doubles_the_ledger(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[T + 'field_ledger'], insights=['insight.sect-supply-officer'])
    s = loaded(cold, jid)
    numbers = s.state['actors'][A]['bundle']['material_abilities']
    assert G._site_cap(s, A) == 2 * (3 + numbers['pb'] + numbers['key_mod'])


def test_riders_leave_only_what_is_not_automated():
    authority = json.loads((ROOT / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    left = {mid: len(authority[mid]['riders']) for mid in (
        'HARVESTING_GATHERING_BASE_CLEAN_HARVEST', 'HARVESTING_GATHERING_BASE_HARVEST_LOTS_AND_LOT_QUALITY',
        'HARVESTING_GATHERING_BASE_SEAL_THE_ESSENCE', T + 'clean_sickle_method', T + 'sovereign_clean_cut',
        T + 'root_left_alive_method', T + 'field_ledger')}
    assert left == {'HARVESTING_GATHERING_BASE_CLEAN_HARVEST': 1, 'HARVESTING_GATHERING_BASE_HARVEST_LOTS_AND_LOT_QUALITY': 0,
                    'HARVESTING_GATHERING_BASE_SEAL_THE_ESSENCE': 0, T + 'clean_sickle_method': 0, T + 'sovereign_clean_cut': 0,
                    T + 'root_left_alive_method': 0, T + 'field_ledger': 0}
