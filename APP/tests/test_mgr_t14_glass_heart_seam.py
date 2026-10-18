"""Native owner input -> committed action -> cold replay, with no live models.

Initial ownership comes from the verified initial-Foundation resolver. This is
not certification of full character-building or later-stage advancement.
"""
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_rolls import DeterministicRollAuthority
from combat.tabletop_service import TabletopError
from combat.ext import glass_heart as glass
from non_sphere_authority.foundation_mechanics import (
    resolve_initial_foundation_state, verified_foundation_records,
)
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, ALLY, candidate, fixture, reload, settle, turn

BANNER = 'tianxia.subpath.qi.banner_cultivator.feature.'
PINS = {
    'generate_glass_reflection': '2d5f88ac5885a08833169b2e634414f019b0c9f4ebccdc6a8cfbc46fab49f2de',
    'glass_heart_reserve': '2053b6295c81b878c23bfde6b7cb99ae208248404a071707b7f14757e4ad76f6',
    'shatter_guard': 'bd3ef5a4f212dd89244100126e2487c23c34988c42d20a9124b93056bbd2d47c',
    'clear_heart_rebuke': '5ed4d4f5779851f7b8c42611d380bbd7d9b170ad79e466ad37154239045f9eb3',
    'transparent_witness': '0329b48d4b7d5e3fe095c25e4e5469748fe377554d3275efd236b2e8f7f44ed6',
    'refined_beauty_without_lie': 'fc62d5f086e0b1035d44478cdc15a5781221e291dee43e562ac460414e21e8c9',
    'refined_refracted_technique': '497fddc8c1710610c066c7b5b64f29c21b4486a17645ebcb2baa1e47d53a90b4',
    'perfected_glass_heart_refraction': '61816edc9a444066bdb28e17dbde5d325392650930e0ceaa01f899faca3fcced',
}


@pytest.fixture(scope='session', autouse=True)
def pinned_stock_evidence():
    """The bridge forwards a restricted environment; pin in-process explicitly.

    Used when the lean final gate also selects the six stock tests. Keep their
    output in this lane's evidence directory and compare this exact task base.
    """
    from tests import test_a2_glass_stock as stock
    previous = os.environ.get('CF_REPLAY_BASE')
    # tests/ is a namespace package. Pytest's prepend mode can also load the
    # stock file by its bare name, so bind every loaded alias of this one file.
    stock_path = Path(stock.__file__).resolve()
    aliases = []
    for module in list(sys.modules.values()):
        if not isinstance(module, ModuleType):
            continue
        path = vars(module).get('__file__')
        if (isinstance(path, str) and Path(path).name == stock_path.name
                and Path(path).resolve() == stock_path and 'EVIDENCE' in vars(module)):
            aliases.append((module, module.EVIDENCE))
    os.environ['CF_REPLAY_BASE'] = '8bd818c78df011c2b67145d8e33975468c3e6a75'
    for module, _ in aliases:
        module.EVIDENCE = Path('/var/tmp/auto-audit/fix/MGR-T14-sol-seam-glass-heart-2-evidence/stock')
    yield
    for module, old_evidence in aliases:
        module.EVIDENCE = old_evidence
    if previous is None:
        os.environ.pop('CF_REPLAY_BASE', None)
    else:
        os.environ['CF_REPLAY_BASE'] = previous


@pytest.mark.parametrize('leaf,digest', PINS.items())
def test_controlling_source(leaf, digest):
    rules = json.loads((Path(__file__).resolve().parents[1] /
                        'authority/typed_mechanics/rules_text.json').read_text())
    assert hashlib.sha256(rules[glass.PREFIX + leaf].encode()).hexdigest() == digest


def setup(tmp_path, talents=(), *, owns=True, foe=None):
    foundation = (resolve_initial_foundation_state(
        verified_foundation_records()['glass_heart_meridian_v0_2A'],
        ['tianxia.path.qi_cultivation'], stage='Awakened') if owns else None)
    document = sheet(list(talents), foundation=foundation)
    if foundation:
        document['foundation'] = foundation
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    return fixture(tmp_path, [], owner_bundle=bundle, foe_sheet=foe,
                   foe_position={'x': 5, 'y': 6}, seed='GLASS-SEAM')


def source(engine, name, owner=OWNER):
    return next(a.source_definition_id for a in engine.action_catalog.values()
                if a.owner_id == owner and a.display_name == name)


def document(engine, source_id, purpose, value, bearer=OWNER, record='glass-declaration'):
    from combat.ext.needle import numbers_of
    source_actor = engine.state.actors[engine.action_catalog[source_id].owner_id]
    source_cl = int(numbers_of(engine, source_actor).get('cl') or 0)
    def answer(p, fact):
        return {'category': glass.KEY + p, 'fact': fact, 'condition': source_id,
                'visible_sign': 'The GM records the actual scene and bearer declaration.', 'source_cl': source_cl}
    answers = {glass.KEY + purpose: answer(purpose, value)}
    if purpose in {'scope', 'pressure'}:
        answers[glass.KEY + 'anti_farming'] = answer('anti_farming', 'genuine_unarranged_event')
    actor = engine.state.actors[bearer]
    return {'record_id': record, 'subject_id': bearer, 'subject_name': actor.display_name,
            'subject_kind': 'creature', 'position': actor.position.model_dump(mode='json'),
            'source_reference': 'GM scene input: truthful disclosure during a real hostile encounter',
            'witness_ids': [bearer], 'valid_through_round': engine.state.round_number,
            'answers': answers}


def record(combat, table, mid, doc):
    version = combat._load_session(mid).engine.state.state_version
    return table.record_fact(mid, doc, expected_state_version=version)


@pytest.mark.parametrize('owns,accept,declared', [(True, True, True), (True, False, True),
    (False, True, True), (True, True, False)])
def test_rescued_save_uses_settled_outcome_and_expiry(tmp_path, monkeypatch, owns, accept, declared):
    def twelve(self, sides):
        counter = self.counter
        self.counter += 1
        return min(12, sides), counter
    monkeypatch.setattr(DeterministicRollAuthority, '_die', twelve)
    combat, table, mid = setup(tmp_path, [BANNER + 'raise_the_standard', BANNER + 'rally_the_line'],
                              owns=owns, foe=sheet(['TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE'], dc=16))
    settle(table, mid, candidate(combat, mid, 'Manifest Command Banner (1 Qi)', at=(4, 7)).candidate_id)
    turn(table, mid, FOE)
    if declared:
        e = combat._load_session(mid).engine
        record(combat, table, mid, document(e, source(e, 'Dread Appetite: Frighten', FOE), 'pressure', 'fear'))
    settle(table, mid, candidate(combat, mid, 'Dread Appetite: Frighten', target=OWNER).candidate_id,
           {'reaction:typed.' + BANNER + 'rally_the_line': 'USE' if accept else None})
    e = reload(tmp_path, mid)
    saves = [ev for ev in e.events if ev.event_type == 'SAVE_ROLLED' and ev.actor_id == OWNER]
    assert saves[-1].payload['total'] == 14 and not saves[-1].payload['success']
    reactions = [ev for ev in e.events if ev.event_type == 'REACTION_RESOLVED'
                 and ev.source_definition_id == BANNER + 'rally_the_line']
    assert bool(reactions) == accept
    actor = e.state.actors[OWNER]
    assert actor.resources.get(glass.POOL, 0) == int(owns and accept and declared)
    if owns and accept and declared:
        gain = next(ev for ev in e.events if ev.event_type == 'RESOURCE_GAINED'
                    and ev.source_definition_id == 'passive:' + glass.PREFIX + 'generate_glass_reflection')
        assert gain.sequence > reactions[-1].sequence
        assert actor.resource_maximums[glass.POOL] == 1
        assert not glass.preexisting_reflection(e, actor, saves[-1].sequence)
        turn(table, mid, OWNER)
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        assert reload(tmp_path, mid).state.actors[OWNER].resources[glass.POOL] == 0


@pytest.mark.parametrize('qualifier,paid,bearer,withdraw', [(True, True, OWNER, False),
    (False, True, OWNER, False), (True, False, OWNER, False),
    (True, True, ALLY, False), (True, True, OWNER, True)])
def test_real_paid_figment_requires_exact_declared_expression(tmp_path, qualifier, paid, bearer, withdraw):
    combat, table, mid = setup(tmp_path, ['TAL_ILLUSION_CONTROL_FIGMENT'])
    e = combat._load_session(mid).engine
    src = source(e, 'Create Figment')
    if qualifier:
        # Wrong-bearer input has a real ally action binding; it cannot grant a
        # benefit to the Foundation owner on an unrelated action.
        if bearer == ALLY:
            src = source(e, 'Unarmed Strike', ALLY)
        doc = document(e, src, 'scope', 'emotional_truth', bearer=bearer)
        record(combat, table, mid, doc)
        if withdraw:
            record(combat, table, mid, {**doc, 'active': False})
    if paid:
        settle(table, mid, candidate(combat, mid, 'Figment: larger cube (1 CP)').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Create Figment', at=(7, 6)).candidate_id)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources[glass.POOL] == int(qualifier and paid and bearer == OWNER and not withdraw)
    payments = [ev for ev in e.events if ev.event_type == 'RESOURCE_SPENT'
                and ev.actor_id == OWNER and ev.payload.get('resource_id') == 'resource:core.qi']
    if qualifier and paid and bearer == OWNER and not withdraw:
        gain = next(ev for ev in e.events if ev.event_type == 'RESOURCE_GAINED'
                    and ev.payload.get('resource_id') == glass.POOL)
        assert payments and payments[-1].sequence < gain.sequence
        assert not glass.preexisting_reflection(e, e.state.actors[OWNER], payments[-1].sequence)


def test_source_input_validation_privacy_and_stale_version(tmp_path):
    from combat.target_knowledge import recent_events
    from combat.table_facts import records
    combat, table, mid = setup(tmp_path, ['TAL_ILLUSION_CONTROL_FIGMENT'])
    e = combat._load_session(mid).engine
    doc = document(e, source(e, 'Create Figment'), 'scope', 'emotional_truth')
    version = e.state.state_version
    invalid = json.loads(json.dumps(doc))
    invalid['answers']['glass_heart.anti_farming']['fact'] = 'training_illusion'
    with pytest.raises(TabletopError):
        record(combat, table, mid, invalid)
    missing = json.loads(json.dumps(doc))
    del missing['answers']['glass_heart.anti_farming']
    with pytest.raises(TabletopError):
        record(combat, table, mid, missing)
    wrong_owner = json.loads(json.dumps(doc))
    for answer in wrong_owner['answers'].values():
        answer['condition'] = source(e, 'Unarmed Strike', ALLY)
    with pytest.raises(TabletopError):
        record(combat, table, mid, wrong_owner)
    assert combat._load_session(mid).engine.state.state_version == version
    record(combat, table, mid, doc)
    with pytest.raises(TabletopError):
        table.record_fact(mid, doc, expected_state_version=version)
    e = reload(tmp_path, mid)
    assert records(e, e.state.actors[OWNER])
    assert not records(e, e.state.actors[ALLY])
    assert not any(ev['event_type'] == 'TABLE_FACT_RECORDED'
                   for ev in recent_events(e, e.state.actors[OWNER], e.events))
    assert not any(ev['event_type'] == 'TABLE_FACT_RECORDED'
                   for ev in table.events(mid, 0)['events'])
    assert not any(ev['source_definition_id'] == 'system:combat.table_fact'
                   for ev in table.events(mid, 0)['events'])
    assert not any(ev['source_definition_id'] == 'system:combat.table_fact'
                   for ev in recent_events(e, e.state.actors[OWNER], e.events))
    assert not any(c.source_definition_id == 'system:combat.table_fact' for c in e.legal_candidates())


def test_fact_http_requires_owner_token_and_commits_native_input(tmp_path):
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    root = Path(__file__).resolve().parents[1]
    combat, table, mid = setup(tmp_path, ['TAL_ILLUSION_CONTROL_FIGMENT'])
    e = combat._load_session(mid).engine
    doc = document(e, source(e, 'Create Figment'), 'scope', 'emotional_truth')
    app = create_app(Settings.from_env(root, tmp_path))
    app.state.agent_seats.background = False

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://127.0.0.1:8000') as client:
            url = f'/api/tabletop/matches/{mid}/facts'
            payload = {'document': doc, 'expected_state_version': e.state.state_version}
            denied = await client.post(url, json=payload)
            assert denied.status_code == 403
            token = (await client.get('/api/session')).json()['token']
            headers = {'x-foundry-token': token}
            result = await client.post(url, json=payload, headers=headers)
            assert result.status_code == 200, result.text
            stale = await client.post(url, json=payload, headers=headers)
            assert stale.status_code == 409
    run_asgi(exercise())
    assert any(ev.event_type == 'TABLE_FACT_RECORDED' for ev in reload(tmp_path, mid).events)


def test_refraction_requires_declared_major_scene_then_commits_paid_state(tmp_path):
    """Existing Perfected-sheet fixture; does not certify stage advancement."""
    from tests.test_a2_foundations_two import table_fixture
    from combat.ext.foundation_combat import held
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    e = combat._load_session(mid).engine
    src = source(e, 'Perfected — Glass Heart Refraction')
    assert not any(c.source_definition_id == src for c in e.legal_candidates())
    record(combat, table, mid, document(e, src, 'scene', 'major_combat'))
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    settle(table, mid, candidate(combat, mid, 'Perfected — Glass Heart Refraction').candidate_id)
    e = reload(tmp_path, mid)
    owner = e.state.actors[OWNER]
    assert held(owner, 'glass_refraction') is not None
    assert owner.resources['resource:core.qi'] == before - 2
    assert owner.resources[glass.POOL] == 0
    assert owner.resource_maximums[glass.POOL] == 1
    assert held(e.state.actors[ALLY], 'glass_refraction') is None
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    e = combat._load_session(mid).engine
    record(combat, table, mid, document(e, src, 'scene', 'emotionally_decisive'))
    assert not any(c.source_definition_id == src for c in reload(tmp_path, mid).legal_candidates())


def test_refraction_use_carries_to_journey_and_only_owners_real_rest_recharges(tmp_path):
    """Native lifecycle consumer; the Perfected sheet is not advancement proof."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.ext.foundation_combat import held
    root = Path(__file__).resolve().parents[1]
    doc = sheet([], cl=15)
    initial = resolve_initial_foundation_state(verified_foundation_records()[glass.FOUNDATION_ID],
        ['tianxia.path.qi_cultivation'], stage='Awakened')
    doc['foundation'] = {**initial, 'stage': 'Perfected'}
    docs = [doc, sheet([], cl=15), sheet([], cl=15)]
    ids = [OWNER, ALLY, FOE]
    for d, aid in zip(docs, ids):
        package = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.') / 'current.zip'
        package.parent.mkdir(parents=True)
        with zipfile.ZipFile(package, 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(d))
    bundles = [compile_character(d, actor_id=aid, reaction_plan={'ask': True}) for d, aid in zip(docs, ids)]
    combat = CombatService(root, tmp_path)
    table = TabletopService(combat, tmp_path)
    positions = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 5, 'y': 6}}
    teams = {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'}
    state = combat.journeys.create(bundles,
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        positions, {aid: 1000 for aid in ids}, {aid: 'MANUAL' for aid in ids})
    jid = state['journey_id']
    result = combat.journey_start_combat(jid, state['revision'], teams, maximum_rounds=12)
    mid = result['match_id']
    turn(table, mid, OWNER)
    e = combat._load_session(mid).engine
    src = source(e, 'Perfected — Glass Heart Refraction')
    action = e.action_catalog[src]
    use = next(rid for rid, _ in action.costs if rid.startswith('resource:uses.'))
    record(combat, table, mid, document(e, src, 'scene', 'major_combat'))
    settle(table, mid, candidate(combat, mid, 'Perfected — Glass Heart Refraction').candidate_id)
    for _ in range(45):
        e = combat._load_session(mid).engine
        if e.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    else:
        pytest.fail('The native twelve-round encounter did not reach its terminal result.')
    e = reload(tmp_path, mid)
    assert held(e.state.actors[OWNER], 'glass_refraction') is None
    assert e.state.actors[OWNER].resources[use] == 0
    state = combat.journey_state(jid)
    combat.journey_resume(jid, state['revision'])
    state = combat.journey_state(jid)
    cp = state['actors'][OWNER]['resources']['resource:core.qi']
    before_rest_seconds = state['seconds']
    assert state['actors'][OWNER]['resources'][use] == 0
    combat.journey_act(jid, state['revision'], ALLY, 'long_rest', {})
    state = combat.journey_state(jid)
    assert state['actors'][OWNER]['resources'][use] == 0
    combat.journey_act(jid, state['revision'], OWNER, 'long_rest', {})
    state = combat.journey_state(jid)
    assert state['seconds'] - before_rest_seconds == 57600
    assert state['actors'][OWNER]['resources'][use] == 1
    assert state['actors'][OWNER]['resources']['resource:core.qi'] == cp
    assert state['actors'][OWNER]['resources'][glass.POOL] == 0
    result = combat.journey_start_combat(jid, state['revision'], teams, maximum_rounds=12)
    mid = result['match_id']
    turn(table, mid, OWNER)
    e = combat._load_session(mid).engine
    record(combat, table, mid, document(e, src, 'scene', 'emotionally_decisive'))
    settle(table, mid, candidate(combat, mid, 'Perfected — Glass Heart Refraction').candidate_id)
    e = reload(tmp_path, mid)
    assert held(e.state.actors[OWNER], 'glass_refraction') is not None
    assert e.state.actors[OWNER].resources[use] == 0
    assert e.state.actors[OWNER].resources['resource:core.qi'] == cp - 2


def test_declared_figment_is_spent_by_its_event_not_reused_by_a_later_paid_use(tmp_path):
    """Finding 2: one GM declaration answers one real event. A later paid use with no new declaration must not reuse it."""
    combat, table, mid = setup(tmp_path, ['TAL_ILLUSION_CONTROL_FIGMENT'])
    e = combat._load_session(mid).engine
    src = source(e, 'Create Figment')
    record(combat, table, mid, document(e, src, 'scope', 'emotional_truth'))
    settle(table, mid, candidate(combat, mid, 'Figment: larger cube (1 CP)').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Create Figment', at=(7, 6)).candidate_id)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources[glass.POOL] == 1
    assert glass.declared(e, e.state.actors[OWNER], src, 'scope') is None

    def reflection_gains(engine):
        return [ev for ev in engine.events if ev.event_type == 'RESOURCE_GAINED' and ev.actor_id == OWNER
                and ev.payload.get('resource_id') == glass.POOL]

    assert len(reflection_gains(e)) == 1
    # A second paid use of the same action, with no new declaration, gains no Reflection.
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Create Figment', at=(7, 7)).candidate_id)
    e = reload(tmp_path, mid)
    paid = [ev for ev in e.events if ev.event_type == 'RESOURCE_SPENT' and ev.actor_id == OWNER
            and ev.source_definition_id == src and ev.payload.get('resource_id') == 'resource:core.qi']
    assert len(paid) >= 2
    assert len(reflection_gains(e)) == 1


def test_refraction_scene_control_makes_refraction_reachable_then_spends_it(tmp_path):
    """Finding 1: the GM's plain scene control, not a raw fact POST, makes Refraction offered; using it spends the scene."""
    from tests.test_a2_foundations_two import table_fixture
    from combat.ext.foundation_combat import held
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    e = combat._load_session(mid).engine
    src = source(e, 'Perfected — Glass Heart Refraction')
    assert not any(c.source_definition_id == src for c in e.legal_candidates())
    with pytest.raises(TabletopError):
        table.record_glass_scene(mid, OWNER, 'a quiet afternoon', expected_state_version=e.state.state_version)
    with pytest.raises(TabletopError):
        table.record_glass_scene(mid, FOE, 'major_combat', expected_state_version=e.state.state_version)
    table.record_glass_scene(mid, OWNER, 'major_combat', expected_state_version=e.state.state_version)
    assert any(c.source_definition_id == src for c in combat._load_session(mid).engine.legal_candidates())
    settle(table, mid, candidate(combat, mid, 'Perfected — Glass Heart Refraction').candidate_id)
    e = reload(tmp_path, mid)
    assert held(e.state.actors[OWNER], 'glass_refraction') is not None
    # Finding 3: the scene itself is spent by the use, independent of the one-use resource.
    assert glass.declared(e, e.state.actors[OWNER], src, 'scene') is None
    assert not any(c.source_definition_id == src for c in e.legal_candidates())


def test_refraction_scene_button_is_wired_for_gm():
    """Finding 1: the GM has an in-table control for the scene, not only the API route."""
    root = Path(__file__).resolve().parents[1] / 'static' / 'tabletop'
    html = (root / 'tabletop.html').read_text()
    js = (root / 'tabletop.js').read_text()
    assert 'id="ttGlassScene"' in html and 'id="ttGlassSceneForm"' in html
    assert 'from "./glass-scene.js"' in js and 'glassSceneRequest(app.matchId' in js
    assert '$("#ttGlassScene").addEventListener' in js


def test_refraction_scene_http_control_needs_owner_token(tmp_path):
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    from tests.test_a2_foundations_two import table_fixture
    root = Path(__file__).resolve().parents[1]
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    e = combat._load_session(mid).engine
    app = create_app(Settings.from_env(root, tmp_path))
    app.state.agent_seats.background = False

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://127.0.0.1:8000') as client:
            url = f'/api/tabletop/matches/{mid}/glass-scene'
            payload = {'bearer_id': OWNER, 'scene': 'emotionally_decisive', 'expected_state_version': e.state.state_version}
            assert (await client.post(url, json=payload)).status_code == 403
            token = (await client.get('/api/session')).json()['token']
            result = await client.post(url, json=payload, headers={'x-foundry-token': token})
            assert result.status_code == 200, result.text
    run_asgi(exercise())
    assert glass.declared(reload(tmp_path, mid), reload(tmp_path, mid).state.actors[OWNER],
                          source(reload(tmp_path, mid), 'Perfected — Glass Heart Refraction'), 'scene') == 'emotionally_decisive'
