"""Public-safe native regression, with no historical fixture imports.

Dynamic authority dependencies: TAL_WATER_RESTORATIVE_WATERS,
WATER_BASE_RETURN_THE_FLOW, WATER_BASE_SHAPE_CURRENT, tianxia.sphere.water.
Registry dependencies: combat.ext.water_return, combat.ext.water_basins,
combat.ext.choice_costs, combat.ext.cp_pools, combat.ext.needle.
"""
import json
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile
import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

# Literal resources consumed by dynamic native advancement/registry loaders.
PUBLIC_CI_DEPENDENCIES = (
    'APP/authority/Tianxia_Forged_Technique_Authority_R1.json',
    'APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'APP/combat/ext/water_return.py', 'APP/combat/ext/water_basins.py',
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'TAL_WATER_RESTORATIVE_WATERS'
PIDS = ['00000000-0000-4000-8000-00000000000' + str(i) for i in (1, 2, 3)]
OWNER, ALLY, FOE = IDS = ['actor:factory.' + p for p in PIDS]
RETURN = 'Return the Flow: End It Early + Restorative Waters'
CHOICE = 'choice:needle.restorative_'


def document(cl, name, cp):
    return {'identity': {'name': name, 'cultivation_level': cl, 'proficiency_bonus': 4,
                         'path': 'Qi Cultivation', 'path_ids': ['tianxia.path.qi_cultivation'], 'key_ability': 'WIS'},
            'ability_scores_and_statistics': {
                'abilities': [{'ability': a, 'score': 18 if a == 'WIS' else 10,
                               'modifier': 4 if a == 'WIS' else 0}
                              for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
                'primary_resource': {'name': 'Qi', 'maximum': cp},
                'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 150, 'current': 10},
                'speed': {'walking_ft': 30}, 'technique_save_dc': 16, 'technique_attack_bonus': 8}}


def fixture(tmp_path, cl=10, cp=30, owned=True, ally_at=(8, 6), journey=False, maximum_rounds=20):
    for pid, name in zip(PIDS, ['Wren', 'Tobin', 'Mara']):
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document(cl, name, cp)))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    # Native legal acquisition from an initial Qi character; no owned ID is installed.
    table.add_advancement(PIDS[0], 'sphere', 'tianxia.sphere.water')
    if owned:
        table.add_advancement(PIDS[0], 'talent', SOURCE)
    docs = [combat._factory_owner_sheet(pid) for pid in PIDS]
    assert (SOURCE in docs[0]['spheres_and_talents'].get('learned_talent_record_ids', [])) is owned
    bundles = [compile_character(d, actor_id=a, reaction_plan={'ask': True}) for d, a in zip(docs, IDS)]
    # Scenario injury uses the native attack resolver, no healing/ledger mock.
    foe = bundles[2]
    aid = 'action:test.restorative.training_hit'
    foe['action_catalog'].append({'source_definition_id': aid, 'display_name': 'Training injury',
        'owner_id': FOE, 'economy': 'ACTION', 'resolution_kind': 'ATTACK', 'target_kind': 'HOSTILE_ENTITY',
        'range_ft': 60, 'attack_bonus': 100, 'damage': {'count': 1, 'sides': 4, 'modifier': 70},
        'damage_type': 'BLUDGEONING', 'costs': [], 'parameters': {}})
    foe['actor_template']['action_ids'].append(aid)
    foe.pop('bundle_sha256', None); foe['bundle_sha256'] = canonical_sha256(foe)
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    positions = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': ally_at[0], 'y': ally_at[1]}, FOE: {'x': ally_at[0], 'y': ally_at[1] - 1}}
    teams = {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'}
    jid = None
    if journey:
        state = combat.journeys.create(bundles, arena, positions, {a: 1000 for a in IDS}, {a: 'MANUAL' for a in IDS})
        jid = state['journey_id']
        mid = combat.journey_start_combat(jid, state['revision'], teams, maximum_rounds=maximum_rounds)['match_id']
    else:
        mid = combat._finish_factory_match(
            bundles, IDS, teams, positions, arena, [OWNER, ALLY], [FOE],
            control_modes={a: 'MANUAL' for a in IDS}, match_seed='RESTORATIVE-NATIVE',
            display_name='Restorative Waters', maximum_rounds=maximum_rounds)['match_id']
    turn(table, mid, FOE)
    act(table, mid, candidate(combat, mid, 'Training injury', target=ALLY))
    act(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid)
    return combat, table, mid, jid


def act(table, mid, cid, picks=None):
    answers, prompts = [], []
    for _ in range(20):
        view = table.state(mid); menu = view['menu']
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], view['last_sequence'], answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        p = result['reaction']; prompts.append(p)
        choice = (picks or {}).get(p['context']['reaction_source_id'], 'first')
        ids = [p['choice']['options'][0]['id']] if choice == 'first' else choice
        answers.append({**p['context'], 'selection': 'DECLINE' if ids is None else 'USE', 'option_ids': ids or []})
    raise AssertionError('Unsettled choice')


def turn(table, mid, actor=OWNER):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        act(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('No owner turn')


def candidate(combat, mid, name, at=None, target=None):
    e = combat._load_session(mid).engine
    choices = [c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id)
               and e.action_catalog[c.source_definition_id].display_name == name
               and (at is None or c.destination and (c.destination.x, c.destination.y) == at)]
    if target is not None:
        choices = [c for c in choices if c.target_ids == (target,)]
    assert choices, name
    return choices[0].candidate_id


def basin(combat, table, mid):
    act(table, mid, candidate(combat, mid, 'Shape Current: Mist Basin', (8, 6)))
    return next(z.zone_id for z in combat._load_session(mid).engine.state.zones.values()
                if z.active and z.owner_id == OWNER)


def test_source_hash():
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_bytes())[SOURCE]
    assert sha256(text.encode()).hexdigest() == 'c00483593620d5bca36cd46d4d8ae6f878976e2d1555f6c6392c70012284252d'


@pytest.mark.parametrize('cl,count', [(10, 1), (11, 2), (17, 3)])
def test_native_binding_payment_repeat_and_cold_reload(tmp_path, cl, count):
    combat, table, mid, _ = fixture(tmp_path, cl)
    zid = basin(combat, table, mid)
    before = combat._load_session(mid).engine
    hp = before.state.actors[ALLY].current_hp
    cp = before.state.actors[OWNER].resources['resource:core.qi']
    prompts = act(table, mid, candidate(combat, mid, RETURN), {
        CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + 'payment': ['1']})
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    e = loaded.engine
    assert not e.state.zones[zid].active
    healing = [event for event in e.events if event.event_type == 'HEALING_APPLIED' and event.target_ids == (ALLY,)]
    assert healing[-1].payload['after'] - healing[-1].payload['before'] == e.state.actors[ALLY].current_hp - hp
    rolled = next(event for event in reversed(e.events) if event.event_type == 'DAMAGE_ROLLED'
                  and str(event.payload.get('reason', '')).startswith('HEALING:'))
    assert rolled.payload['expression'] == f'{count}d8+4'
    assert count + 4 <= e.state.actors[ALLY].current_hp - hp <= count * 8 + 4
    assert e.state.actors[OWNER].resources['resource:core.qi'] == cp - 1
    assert any(c.condition_id == 'condition:typed.restorative_waters_used' for c in e.state.actors[ALLY].conditions.values())
    p = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE + 'recipient')
    assert {o['id'] for o in p['choice']['options']} == {ALLY}
    assert 'Restorative Waters' in str(p) and 'Return the Flow' in str(p) and 'Tobin' in str(p)
    act(table, mid, table.state(mid)['menu']['end_turn']); turn(table, mid)
    zid = basin(combat, table, mid)
    prompts = act(table, mid, candidate(combat, mid, RETURN), {
        CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + 'payment': ['2']})
    p = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE + 'payment')
    assert [o['id'] for o in p['choice']['options']] == ['2']
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert loaded.engine.state.actors[OWNER].resources['resource:core.qi'] == cp - 4


@pytest.mark.parametrize('stage', ['effect', 'recipient', 'payment'])
def test_decline_does_not_pay_or_mark(tmp_path, stage):
    combat, table, mid, _ = fixture(tmp_path)
    zid = basin(combat, table, mid)
    cp = combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.qi']
    act(table, mid, candidate(combat, mid, RETURN), {
        CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + stage: None})
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert loaded.engine.state.actors[OWNER].resources['resource:core.qi'] == cp
    assert not any(c.condition_id == 'condition:typed.restorative_waters_used'
                   for c in loaded.engine.state.actors[ALLY].conditions.values())


def test_no_owner_no_modifier(tmp_path):
    combat, table, mid, _ = fixture(tmp_path, owned=False)
    assert not any('Restorative Waters' in a.display_name for a in combat._load_session(mid).engine.action_catalog.values())


def finish(combat, table, mid):
    for _ in range(100):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            return
        act(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('Fight did not reach its native round limit')


def test_recipient_ledger_crosses_fights_and_only_actual_rest_renews(tmp_path):
    combat, table, mid, jid = fixture(tmp_path, journey=True, maximum_rounds=3)
    zid = basin(combat, table, mid)
    act(table, mid, candidate(combat, mid, RETURN), {
        CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + 'payment': ['1']})
    finish(combat, table, mid)
    state = combat.journey_state(jid)
    state = combat.journey_resume(jid, state['revision'], effect_resolutions={a: 'Timed encounter effects ended after combat' for a in IDS})
    def used(state):
        return any(json.loads(c)['condition_id'] == 'condition:typed.restorative_waters_used'
                   for c in state['actors'][ALLY]['encounter_snapshot']['conditions'].values())
    assert used(state)
    # Waiting alone and another creature's rest cannot renew Tobin's benefit.
    state = combat.journey_act(jid, state['revision'], ALLY, 'wait', {'seconds': 3600})
    assert used(state)
    state = combat.journey_act(jid, state['revision'], OWNER, 'short_rest')
    assert used(state)
    teams = {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'}
    mid = combat.journey_start_combat(jid, state['revision'], teams, maximum_rounds=2)['match_id']
    turn(table, mid)
    zid = basin(combat, table, mid)
    prompts = act(table, mid, candidate(combat, mid, RETURN), {
        CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + 'payment': None})
    p = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE + 'payment')
    assert [o['id'] for o in p['choice']['options']] == ['2']
    finish(combat, table, mid)
    state = combat.journey_state(jid)
    state = combat.journey_resume(jid, state['revision'], effect_resolutions={a: 'Timed effects ended after combat' for a in IDS})
    assert used(state)
    before = state['seconds']
    # Cold service, real elapsed-time Short Rest command, then a fresh fight.
    combat = CombatService(ROOT, tmp_path); table = TabletopService(combat, tmp_path)
    state = combat.journey_act(jid, state['revision'], ALLY, 'short_rest')
    assert state['seconds'] == before + 3600 and not used(state)
    assert state['events'][-1]['kind'] == 'SHORT_REST' and state['events'][-1]['actor_id'] == ALLY
    mid = combat.journey_start_combat(jid, state['revision'], teams, maximum_rounds=2)['match_id']
    turn(table, mid)
    zid = basin(combat, table, mid)
    prompts = act(table, mid, candidate(combat, mid, RETURN), {
        CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + 'payment': ['1']})
    p = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE + 'payment')
    assert [o['id'] for o in p['choice']['options']] == ['1', '2']
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert any(c.condition_id == 'condition:typed.restorative_waters_used' for c in loaded.engine.state.actors[ALLY].conditions.values())


def test_ineligible_recipient_and_no_effect_do_not_offer_healing(tmp_path):
    combat, table, mid, _ = fixture(tmp_path, ally_at=(15, 6))
    e = combat._load_session(mid).engine
    assert not any(e.action_catalog[c.source_definition_id].display_name == RETURN for c in e.legal_candidates()
                   if c.source_definition_id in e.action_catalog)
    zid = basin(combat, table, mid)
    cp = combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.qi']
    prompts = act(table, mid, candidate(combat, mid, RETURN), {CHOICE + 'effect': [zid]})
    assert not any(p['context']['reaction_source_id'] == CHOICE + 'recipient' for p in prompts)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert loaded.engine.state.actors[OWNER].resources['resource:core.qi'] == cp


@pytest.mark.parametrize('operation', ['Move Water Effect', 'Soak a Creature', 'Move an Ally'])
def test_other_return_operations_bind_the_actual_effect(tmp_path, operation):
    combat, table, mid, _ = fixture(tmp_path)
    zid = basin(combat, table, mid)
    before = combat._load_session(mid).engine
    hp = before.state.actors[ALLY].current_hp
    old = before.state.actors[ALLY].position
    name = 'Return the Flow: ' + operation + ' + Restorative Waters'
    picks = {CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + 'payment': ['1'],
             CHOICE + 'target': [ALLY]}
    if operation == 'Move Water Effect':
        picks[CHOICE + 'destination'] = ['8,7']
    act(table, mid, candidate(combat, mid, name), picks)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    e = loaded.engine
    assert e.state.actors[ALLY].current_hp > hp
    assert e.state.zones[zid].active is (operation == 'Move Water Effect')
    if operation == 'Move Water Effect':
        assert (e.state.zones[zid].center.x, e.state.zones[zid].center.y) == (8, 7)
        assert e.state.zones[zid].duration_rounds == before.state.zones[zid].duration_rounds
        assert e.state.zones[zid].created_round == before.state.zones[zid].created_round
    elif operation == 'Soak a Creature':
        assert any(c.condition_id.startswith('condition:typed.mark.soaked.') for c in e.state.actors[ALLY].conditions.values())
    else:
        assert e.grid.distance_ft(old, e.state.actors[ALLY].position) == 5
        assert not any(event.event_type == 'OPPORTUNITY_ATTACK' for event in e.events)


@pytest.mark.parametrize('cp,pay', [(1, None), (30, '2')])
def test_payment_availability_and_two_cp_first_use(tmp_path, cp, pay):
    combat, table, mid, _ = fixture(tmp_path, cp=cp)
    zid = basin(combat, table, mid)
    before = combat._load_session(mid).engine
    hp = before.state.actors[ALLY].current_hp
    prompts = act(table, mid, candidate(combat, mid, RETURN), {
        CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + 'payment': [pay] if pay else None})
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    e = loaded.engine
    assert (e.state.actors[ALLY].current_hp > hp) is bool(pay)
    assert e.state.actors[OWNER].resources['resource:core.qi'] == cp - 1 - (int(pay) if pay else 0)
    if pay:
        p = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE + 'payment')
        assert [o['id'] for o in p['choice']['options']] == ['1', '2']
    else:
        assert not any(p['context']['reaction_source_id'] == CHOICE + 'payment' for p in prompts)


def test_forged_ineligible_effect_and_recipient_answers_are_rejected(tmp_path):
    from combat.tabletop_service import TabletopError
    combat, table, mid, _ = fixture(tmp_path)
    zid = basin(combat, table, mid)
    cid = candidate(combat, mid, RETURN)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    for picks in ({CHOICE + 'effect': ['zone:not-an-owned-water-effect']},
                  {CHOICE + 'effect': [zid], CHOICE + 'recipient': [FOE]}):
        with pytest.raises(TabletopError):
            act(table, mid, cid, picks)
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    act(table, mid, cid, {CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + 'payment': ['1']})
    act(table, mid, table.state(mid)['menu']['end_turn']); turn(table, mid)
    zid = basin(combat, table, mid)
    cid = candidate(combat, mid, RETURN)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    with pytest.raises(TabletopError):
        act(table, mid, cid, {CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + 'payment': ['1']})
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before


def test_model_owner_uses_fake_transport_for_automatic_choices(tmp_path):
    from agent_seats import SeatRunner
    from agent_seats.providers import ProviderRegistry
    combat, table, mid, _ = fixture(tmp_path)
    zid = basin(combat, table, mid)
    hp = combat._load_session(mid).engine.state.actors[ALLY].current_hp
    calls = []
    def transport(provider, prompt, png):
        calls.append(prompt)
        frame = json.loads(prompt.split('\n', 1)[1])
        legal = frame['legal_menu']
        if 'ability' in legal:
            options = legal.get('choice', {}).get('options', [])
            ids = [o['id'] for o in options]
            selected = next((x for x in (zid, ALLY, '1') if x in ids), ids[0] if ids else None)
            return json.dumps({'selection': 'USE', 'option_ids': [selected] if selected else [], 'spend': 0}), {'total_tokens': 10}
        end = next(k for k, v in legal.items() if v['action'] == 'End turn')
        use = next((k for k, v in legal.items() if v['action'] == RETURN), None)
        return json.dumps({'plan': [use, end] if use else [end]}), {'total_tokens': 10}
    path = tmp_path / 'offline-providers.json'
    path.write_text(json.dumps({'providers': [{'id': 'fake', 'kind': 'local', 'model': 'offline',
        'base_url': 'http://127.0.0.1:1/v1', 'timeout_s': 2, 'prompt_profile': 'full'}]}))
    runner = SeatRunner(table, registry=ProviderRegistry(path), provider=transport, background=False)
    runner.set_seat(mid, OWNER, 'MODEL', 'fake')
    assert runner.drive(mid, max_steps=1) == 1
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == loaded.verify()['status'] == 'PASS'
    assert not loaded.engine.state.zones[zid].active
    assert loaded.engine.state.actors[ALLY].current_hp > hp
    assert calls and any('Restorative Waters' in p for p in calls)
