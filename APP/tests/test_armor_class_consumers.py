"""AC sources, admission and real sheet/table consumers, without GUI programs."""
import json
import os
import subprocess

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from app.core import FoundryError
from combat.tabletop_service import TabletopService
from tests.test_shield_possession_and_armor import (
    ROOT, ME, AN, _sheet, _kit, _fight, _bundle, _effective_ac, _table_match,
    STONE_SKIN, DRAGON_SCALES, TEMPERED_FLESH, UNARMORED, AXE, HEAVY, LIGHT,
)
from tests.test_path_feature_statistics import BASELINE, _context
from projector.path_feature_statistics import load_path_feature_statistic_formulas, resolve_armor_class


def projected_sheet(feature, *, armor=None, dex=14):
    """Use the real sheet's statistic producer and published provenance shape."""
    sheet = _sheet(_kit(AXE, *([armor] if armor else [])), dex=dex, mids=[UNARMORED, feature])
    result = resolve_armor_class(load_path_feature_statistic_formulas(ROOT), [UNARMORED, feature],
        baseline_rule=BASELINE, baseline_value=10 + (dex - 10) // 2,
        baseline_trace={}, context=_context(con=3, dex=(dex - 10) // 2, pb=4))
    sheet['ability_scores_and_statistics']['armor_class'] = {
        'base_value': result['ac_base'], 'value': result['ac_active'], 'generation': result['ac_generation']}
    return sheet


@pytest.mark.parametrize('feature', [STONE_SKIN, DRAGON_SCALES, TEMPERED_FLESH])
@pytest.mark.parametrize('armor,expected', [(None, 18), (LIGHT, 18), (HEAVY, 18)])
@pytest.mark.parametrize('provenance', [True, False], ids=['current-sheet', 'historical-sheet'])
def test_projected_bonus_is_awarded_once_only_with_its_calculation(feature, armor, expected, provenance):
    sheet = projected_sheet(feature, armor=armor)
    if not provenance:
        sheet['ability_scores_and_statistics']['armor_class'].pop('generation')
    engine = _fight(sheet)
    assert _effective_ac(engine) == expected
    assert engine.state.actors[ME].armor_class == expected


@pytest.mark.parametrize('feature', [STONE_SKIN, DRAGON_SCALES, TEMPERED_FLESH])
def test_unarmored_bonus_requires_its_actual_calculation(feature):
    engine = _fight(projected_sheet(feature, dex=28))
    assert _effective_ac(engine) == 19  # Dexterity baseline beats Unarmored Defense


@pytest.mark.parametrize('feature', [STONE_SKIN, DRAGON_SCALES, TEMPERED_FLESH])
def test_owner_sheet_service_publishes_real_bonus_provenance(tmp_path, feature):
    import zipfile
    from tests.test_character_sheet_complete_character import _service
    with zipfile.ZipFile(ROOT / 'fixtures/c3a/C1A_Clean_Fire_Qi_Proof_Character.zip') as archive:
        artifacts = {name: json.loads(archive.read(name)) for name in (
            'Character_Master_Ledger.json', 'Rules_Selection_Packets.json', 'Projection_Provenance_Map.json',
            'Projection_Coverage_Report.json', 'Projection_Diagnostics.json')}
    ac = projected_sheet(feature)['ability_scores_and_statistics']['armor_class']
    core = artifacts['Character_Master_Ledger.json']['core_stats']
    core.update(ac_base=ac['base_value'], ac_active=ac['value'], ac_generation=ac['generation'])
    snapshot, _ = _service(tmp_path)._build_snapshot(
        project={'project_id': 'abcdef12', 'revision': 1, 'user_locks': []},
        artifacts=artifacts, projection_status={'status': 'READY', 'projection_id': 'ac-regression'})
    published = snapshot['ability_scores_and_statistics']['armor_class']
    assert published['generation'] == ac['generation']
    assert published['base_value'] == 17 and published['value'] == 18
    # Test the published sheet numbers, not handwritten AC values. The public
    # fixture supplies sheet structure; each acquired feature is synthetic.
    sheet = projected_sheet(feature)
    sheet['ability_scores_and_statistics']['armor_class'] = published
    assert _effective_ac(_fight(sheet)) == 18


def test_calculation_bonuses_keep_worse_armor_carried():
    features = [UNARMORED, STONE_SKIN, DRAGON_SCALES, TEMPERED_FLESH]
    sheet = _sheet(_kit(HEAVY), mids=features)
    result = resolve_armor_class(load_path_feature_statistic_formulas(ROOT), features,
        baseline_rule=BASELINE, baseline_value=13, baseline_trace={}, context=_context(con=3, dex=3, pb=4))
    sheet['ability_scores_and_statistics']['armor_class'] = {
        'base_value': result['ac_base'], 'value': result['ac_active'], 'generation': result['ac_generation']}
    bundle = _bundle(sheet)
    assert bundle['actor_template']['armor_class'] == 20
    assert bundle['carrying']['items'][0]['worn'] is False
    assert 'unarmored defense (AC 20)' in bundle['carrying']['armor_note']


def _install_sheet(tmp_path, sheet, pid='hero'):
    import zipfile
    folder = tmp_path / 'portable_characters' / pid
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))


@pytest.mark.parametrize('hp', [None, 0, -3, 'invalid', True, 2.5])
@pytest.mark.parametrize('opponent', [False, True])
def test_fight_service_refuses_invalid_max_hp_before_creating_match(tmp_path, hp, opponent):
    _install_sheet(tmp_path, _sheet(hp=hp), 'invalid')
    _install_sheet(tmp_path, _sheet(), 'valid')
    combat = CombatService(ROOT, tmp_path)
    with pytest.raises(FoundryError, match='no valid maximum Hit Points') as error:
        combat.create_factory_match(project_ids=['valid' if opponent else 'invalid'],
            opponent_actor_ids=[FACTORY_ACTOR_PREFIX + 'invalid'] if opponent else [AN])
    assert error.value.status_code == 409
    assert not list((tmp_path / 'Combat' / 'Matches').glob('*'))


@pytest.mark.parametrize('hp', [None, 0, -3])
def test_fight_start_api_returns_plain_hp_refusal(tmp_path, hp):
    """Run the actual route and registered error consumer without an ASGI thread portal."""
    import asyncio
    from app.api import create_app, CombatFactoryMatchRequest
    from app.core import Settings
    from starlette.requests import Request
    _install_sheet(tmp_path, _sheet(hp=hp), 'abcdef12')
    app = create_app(Settings.from_env(ROOT, tmp_path))
    route = next(r for r in app.routes if r.path == '/api/combat/factory-matches')
    with pytest.raises(FoundryError) as error:
        route.endpoint(CombatFactoryMatchRequest(project_ids=['abcdef12']))
    request = Request({'type': 'http', 'method': 'POST', 'path': route.path, 'headers': []})
    response = asyncio.run(app.exception_handlers[FoundryError](request, error.value))
    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload['error']['code'] == 'COMBAT_HIT_POINTS_INVALID'
    assert 'maximum Hit Points' in payload['error']['message']
    assert not list((tmp_path / 'Combat' / 'Matches').glob('*'))


@pytest.mark.skipif(os.environ.get('CF_RUN_HTTP_TESTS') != '1', reason='Lead runs HTTP transport outside the sandbox')
@pytest.mark.parametrize('hp', [None, 0, -3])
def test_fight_start_http_response(tmp_path, hp):
    import asyncio
    import httpx
    from app.api import create_app
    from app.core import Settings
    _install_sheet(tmp_path, _sheet(hp=hp), 'abcdef12')
    async def request():
        app = create_app(Settings.from_env(ROOT, tmp_path))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            token = (await client.get('/api/session')).json()['token']
            return await client.post('/api/combat/factory-matches', json={'project_ids': ['abcdef12']},
                                     headers={'X-Foundry-Token': token})
    response = asyncio.run(request())
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'COMBAT_HIT_POINTS_INVALID'
    assert 'maximum Hit Points' in response.json()['error']['message']
    assert not list((tmp_path / 'Combat' / 'Matches').glob('*'))


def test_actual_sheet_payload_and_items_renderer_show_carried_armor(tmp_path):
    pid = 'abcdef12'
    _install_sheet(tmp_path, projected_sheet(STONE_SKIN, armor=LIGHT), pid)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    payload = table.sheet(pid)
    assert payload['summary']['armor_class'] == 18
    assert 'Carrying Lacquered Leather' in payload['equipment']['armor_note']
    subprocess.run(['node', str(ROOT / 'tests/items_armor_note.mjs')], input=json.dumps(payload),
                   text=True, check=True, capture_output=True)
    table.save_left_behind(pid, [LIGHT])
    payload = TabletopService(CombatService(ROOT, tmp_path), tmp_path).sheet(pid)
    assert next(i for i in payload['equipment']['items'] if i['key'] == LIGHT)['left_behind']
    assert payload['summary']['armor_class'] == 18


def test_owner_store_shield_reaches_fight_admission_and_drop_reload(tmp_path):
    from factory_authoring.owner_items import OwnerItemStore, armour_choices
    from tests.test_lock2_persistence import act
    from tests.test_shield_possession_and_armor import SHIELD, _table_do
    pid = 'abcdef12'
    aid = FACTORY_ACTOR_PREFIX + pid
    _install_sheet(tmp_path, _sheet(_kit(AXE)), pid)
    store = OwnerItemStore(tmp_path / 'owner_items')
    choices = armour_choices(SHIELD, 'Spiritual', None, [])
    shield = store.give(pid, {'kind': 'armour', 'chassis_id': SHIELD, 'grade': 'Spiritual',
                              'material_id': choices['material_id']})
    combat = CombatService(ROOT, tmp_path)
    mid = combat.create_factory_match(project_ids=[pid], opponent_actor_ids=[AN],
        control_modes={aid: 'MANUAL', AN: 'MANUAL'}, match_seed='OWNER-SHIELD')['match_id']
    table = TabletopService(combat, tmp_path)
    if table.state(mid)['menu']['actor_id'] != aid:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[aid]
    before = actor.armor_class + engine._ac_modifier(actor)
    assert any(r.get('block') == 'shield_ac' and r['amount'] == 2 for r in engine.typed_passive_rows[aid])
    assert _table_do(table, mid, 'Drop ' + shield['name'])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[aid]
    assert actor.armor_class + loaded.engine._ac_modifier(actor) == before - 2
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('passive', [True, False], ids=['old-shield-row', 'hand-built-no-row'])
def test_legacy_broken_shield_and_break_guard_subtract_once(passive):
    from combat import armour
    from combat.ext import guard_broken
    engine = _fight()
    actor = engine.state.actors[ME]
    if passive:
        engine.typed_passive_rows[ME].append({'block': 'shield_ac', 'amount': 2})
    engine._apply_condition(actor, armour.BROKEN_SHIELD, 'test', ME, expires_on='UNTIL_REMOVED')
    engine.__dict__[guard_broken.CURRENT] = {'attacker': AN, 'target': ME, 'ranged': False, 'axe': False}
    engine._apply_condition(actor, guard_broken.CONDITION, 'test', AN, expires_on='UNTIL_REMOVED',
                            data={'shield': True, 'by': 'source'})
    assert _effective_ac(engine) == actor.armor_class - 2


def test_sacrificial_shield_damage_rider_really_breaks_shield():
    from tests.test_riders_lane9 import _shield_fight, _stab, _turn, TS, ME as DEFENDER
    from tests.test_auto_lane4 import _script
    engine = _shield_fight([TS + 'sacrificial_shield'])
    actor = engine.state.actors[DEFENDER]
    hp = actor.current_hp
    _script(engine, [20, 3, 4])
    events = _stab(engine)
    [rolled] = [e.payload for e in events if e.event_type == 'DAMAGE_ROLLED']
    assert rolled['critical'] and hp - actor.current_hp == rolled['total'] - 4
    assert any(c.condition_id == 'condition:typed.shield_broken' for c in actor.conditions.values())
    _turn(engine, DEFENDER)  # expire Active Defense's real next-turn modifier
    assert actor.armor_class + engine._ac_modifier(actor) == actor.armor_class - 2


@pytest.mark.parametrize('marked', [True, False], ids=['current-inventory', 'legacy-unmarked'])
def test_sacrificial_shield_table_commit_reload_preserves_broken_penalty(tmp_path, monkeypatch, marked):
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.test_riders_lane9 import _shield_fight, TS, ME as DEFENDER, THEM as ATTACKER
    from tests.test_auto_lane4 import _script
    from tests.test_lock2_persistence import act
    source = _shield_fight([TS + 'sacrificial_shield'])
    bundles = json.loads(json.dumps(source.typed_bundle_documents))
    if not marked:
        for bundle in bundles:
            for item in bundle.get('carrying', {}).get('items', []):
                item.pop('shield', None)
            from combat.canonical import canonical_sha256
            bundle.pop('bundle_sha256')
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    original = Gate4ControllerEngine._resolve_attack_spec
    def critical(engine, *args, **kwargs):
        _script(engine, [20, 3, 4] + [1] * 40)
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_attack_spec', critical)
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(bundles, [DEFENDER, ATTACKER],
        {DEFENDER: 'team:a', ATTACKER: 'team:b'},
        {DEFENDER: {'x': 3, 'y': 6}, ATTACKER: {'x': 4, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [DEFENDER, ATTACKER], [],
        control_modes={DEFENDER: 'LOCAL_AUTO', ATTACKER: 'MANUAL'}, match_seed='SHIELD-BREAK-PERSISTENCE',
        display_name='Broken shield regression', maximum_rounds=20)['match_id']
    table = TabletopService(combat, tmp_path)
    if table.state(mid)['menu']['actor_id'] != ATTACKER:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    state = table.state(mid)
    group = next(g for g in state['menu']['actions'] if g['label'] == 'Bi Shou (Dagger) attack')
    option = next(o for o in group['options'] if o['target_ids'] == [DEFENDER])
    result = table.act(mid, option['candidate_id'], state['menu']['decision_id'],
                       state['menu']['state_version'], state['last_sequence'])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[DEFENDER]
    assert any(c.condition_id == 'condition:typed.shield_broken' for c in actor.conditions.values())
    # Active Defense is +2 until the defender's next turn; broken shield is -2.
    assert loaded.engine._ac_modifier(actor) == 0
    assert act(TabletopService(CombatService(ROOT, tmp_path), tmp_path), mid, 'end')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[DEFENDER]
    assert loaded.engine._ac_modifier(actor) == -2
    assert loaded.mechanical.replay()['status'] == 'PASS'
