"""Streams: portable source-shaped imports, native casts and cold table choices.

No historical captures, installed benefits, synthetic effects or model transport.
Literal resources below declare the dynamic authority dependencies to the exporter.
"""
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from combat.gate5_service import CombatService
from combat.gate5_service import CombatServiceError
from combat.tabletop import ButtonStore, TabletopError
from combat.tabletop_service import TabletopService
from combat.ext import water_return, water_second_pass, water_basins, water_map

ROOT = Path(__file__).resolve().parents[1]
STREAMS = 'TAL_WATER_TEN_THOUSAND_RETURNING_STREAMS'
COURT = 'TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
RETURN = 'WATER_BASE_RETURN_THE_FLOW'
OWNER, ALLY, FOE = ('actor:factory.' + p for p in ('aa001501', 'aa001502', 'aa001503'))
SOURCE_HASH = '64c5a617f18bcb31b6ef98891f4bfe045e681c7f2c0417ab817224edc167775b'
RESOURCES = (
    'authority/typed_mechanics/rules_text.json',
    'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'authority/typed_mechanics/reviewed_final.d/review_sw-water.json',
    'catalog_authority/cat3/generated/catalog_authority.v1.json',
    'combat/rules/feature_blocks.d/a2_water.json',
    'combat/rules/concentration.json',
)


def cold(root, mid):
    combat = CombatService(ROOT, root)
    loaded = combat._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return combat, TabletopService(combat, root), loaded.engine


def source_sheet(name, *, streams=True):
    # Initial CL10 Core Formation Water cultivator. CAT3 prints no additional
    # talent prerequisites, Path restriction or Foundation stage for either row.
    catalog = json.loads((ROOT / RESOURCES[3]).read_text())
    talents = ['TAL_WATER_FLOWING_STEP', COURT] + ([STREAMS] if streams else [])
    rows = {r['canonical_talent_id']: r for r in catalog['talents']}
    water = next(r for r in catalog['spheres'] if r['canonical_sphere_id'] == 'tianxia.sphere.water')
    automatic = [r['runtime_component_id'] for r in water['automatic_base_abilities'] if r['automatic_grant']]
    for tid in talents:
        assert rows[tid]['minimum_cl'] <= 10
        assert not rows[tid]['prerequisite_clauses']
    return {
        'identity': {'name': name, 'display_name': name, 'cultivation_level': 10,
                     'path': 'Qi Cultivation', 'key_ability': 'WIS', 'proficiency_bonus': 4},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 14, 'modifier': 2}
                          for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': 40},
            'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 60},
            'speed': {'walking_ft': 30}, 'technique_save_dc': 14, 'technique_attack_bonus': 6},
        'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.water'],
                               'learned_talent_record_ids': talents,
                               'automatic_sphere_component_record_ids': automatic},
    }


def game(root, *, streams=True, ally_outside=False):
    text = json.loads((ROOT / RESOURCES[0]).read_text())[STREAMS]
    assert hashlib.sha256(text.encode()).hexdigest() == SOURCE_HASH
    for aid, name in ((OWNER, 'River'), (ALLY, 'Reed'), (FOE, 'Stone')):
        pid = aid.split('.')[-1]
        folder = root / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(source_sheet(name, streams=streams and aid == OWNER)))
        ButtonStore(root / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, {STREAMS, COURT})
    combat = CombatService(ROOT, root)
    saved = combat.tabletop_maps.save({'display_name': 'Streams native map', 'width_squares': 32,
        'height_squares': 16, 'walls': [],
        'starts': {'team1': [[3, 6], [25, 7] if ally_outside else [3, 7]], 'team2': [[8, 6]]}})
    mid = combat.create_factory_match(project_ids=[OWNER.split('.')[-1], ALLY.split('.')[-1]],
        opponent_actor_ids=[FOE], control_modes={a: 'MANUAL' for a in (OWNER, ALLY, FOE)},
        arena_id='battlefield:map.' + saved['map_id'], match_seed='STREAMS-native', maximum_rounds=20)['match_id']
    turn(root, mid, OWNER)
    # The public fixture must carry the same shipped admission rules as the
    # native compiler. Missing dynamic data silently falls back to one slot,
    # replacing the Court as soon as the first Basin is created.
    bundle = next(b for b in cold(root, mid)[2].typed_bundle_documents if b['actor_id'] == OWNER)
    assert bundle['concentration_rules']['capacity'] == 'unlimited'
    return mid


def send(root, mid, name=None, *, at=None, target=None, choose=None, end=False, move=False):
    answers, prompts = [], []
    # Every pause constructs both services anew, including between effects.
    for _ in range(40):
        combat, table, engine = cold(root, mid)
        state = table.state(mid)
        candidates = engine.legal_candidates()
        rows = [c for c in candidates if (c.kind.value == 'END_TURN' if end else
                c.kind.value == 'MOVE' if move else
                getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == name)
                and (at is None or c.destination and (c.destination.x, c.destination.y) == at)
                and (target is None or target in c.target_ids)]
        assert rows, (name, at, target)
        c = rows[0]
        before = engine.state.model_dump(mode='json')
        result = table.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            cold(root, mid)
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        assert cold(root, mid)[2].state.model_dump(mode='json') == before
        prompt = result['reaction']
        prompts.append(prompt)
        picks = choose(prompt) if choose else None
        answers.append({**prompt['context'], 'selection': 'USE' if picks is not None else 'DECLINE',
                        'option_ids': picks or []})
    raise AssertionError('native choice loop did not terminate')


def turn(root, mid, actor, *, next_turn=False):
    if next_turn:
        send(root, mid, end=True)
    for _ in range(12):
        if cold(root, mid)[2].state.current_actor_id == actor:
            return
        send(root, mid, end=True)
    raise AssertionError('turn not reached')


def prepare(root, *, count=3, court=True, streams=True, ally_outside=False, injured=False):
    mid = game(root, streams=streams, ally_outside=ally_outside)
    if injured:
        # Inflict damage with the opponent's real native attack, never by
        # installing a successful receipt or editing HP in a saved snapshot.
        for _ in range(8):
            turn(root, mid, FOE)
            send(root, mid, 'Water Lash', target=ALLY)
            turn(root, mid, OWNER)
            ally = cold(root, mid)[2].state.actors[ALLY]
            if ally.maximum_hp - ally.current_hp >= 12:
                break
        assert 0 < ally.current_hp <= ally.maximum_hp - 12
    if court:
        send(root, mid, 'Court of the Endless Tide')
        turn(root, mid, OWNER, next_turn=True)
    for i in range(count):
        send(root, mid, 'Shape Current: Mist Basin', at=(3 + i, 7))
        if i + 1 < count:
            turn(root, mid, OWNER, next_turn=True)
    engine = cold(root, mid)[2]
    areas = [z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER
             and z.trigger_profile.get('name') == 'Shape Current']
    assert len(areas) == count
    return mid, areas


MINOR = 'Return the Flow: Soak a Creature + Ten Thousand Returning Streams (free)'


def test_native_fixture_retains_court_and_independent_basins_after_reload(tmp_path):
    """Regression for the missing public concentration input (review finding 1)."""
    mid, areas = prepare(tmp_path, count=2)
    engine = cold(tmp_path, mid)[2]
    assert all(engine.state.zones[z.zone_id].active for z in areas)
    assert any(z.active and z.owner_id == OWNER
               and engine.action_catalog[z.source_definition_id].parameters['typed']['source'] == COURT
               for z in engine.state.zones.values())
    assert any(c.display_name == MINOR for c in engine.legal_candidates())


@pytest.mark.parametrize('count', [1, 2, 3])
@pytest.mark.parametrize('healing', ['accept', 'decline', 'outside'])
def test_native_selection_actual_endings_optional_healing(tmp_path, count, healing):
    mid, areas = prepare(tmp_path, count=count, ally_outside=healing == 'outside')
    start = len(cold(tmp_path, mid)[2].events)
    seen = []
    def choose(p):
        kind = p['context']['reaction_source_id']
        options = [o['id'] for o in p.get('choice', {}).get('options', [])]
        if kind.endswith('returning_streams_select'):
            assert p['choice']['maximum'] == 3 if count == 3 else p['choice']['maximum'] <= 3
            return [z.zone_id for z in areas]
        if kind.endswith('returning_streams_operation'):
            return ['end']
        if kind.endswith('returning_streams_heal'):
            seen.append(options)
            assert (ALLY in options) == (healing != 'outside')
            return [ALLY] if healing == 'accept' else None
        return None
    send(tmp_path, mid, MINOR, choose=choose)
    engine = cold(tmp_path, mid)[2]
    assert all(not engine.state.zones[z.zone_id].active for z in areas)
    heals = [e for e in engine.events[start:] if e.event_type == 'HEALING_APPLIED']
    assert bool(seen) == (count >= 2)
    assert bool(heals) == (count >= 2 and healing == 'accept')
    if heals:
        assert heals[0].target_ids == (ALLY,)
        assert heals[0].payload['offered'] == 6


def test_native_independent_move_end_minor_and_twenty_foot_route(tmp_path):
    mid, areas = prepare(tmp_path)
    ids = [z.zone_id for z in areas]
    def choose(p):
        kind = p['context']['reaction_source_id']
        if kind.endswith('returning_streams_select'):
            return ids
        if kind.endswith('returning_streams_operation'):
            checkpoint = p['context']['checkpoint']
            return [next(op for zid, op in zip(ids, ['move', 'end', 'soak']) if zid in checkpoint)]
        if kind.endswith('returning_streams_destination'):
            options = p['choice']['options']
            assert all('25 feet' not in o['label'] for o in options)
            return [next(o['id'] for o in options if '20 feet' in o['label'])]
        if kind.endswith('returning_streams_target'):
            return [ALLY]
        return None
    send(tmp_path, mid, MINOR, choose=choose)
    engine = cold(tmp_path, mid)[2]
    moved = engine.state.zones[ids[0]]
    assert moved.active and engine.grid.distance_ft(moved.center, areas[0].center) == 20
    for key in ('duration_rounds', 'created_round', 'trigger_profile', 'source_definition_id'):
        assert getattr(moved, key) == getattr(areas[0], key)
    assert all(not engine.state.zones[zid].active for zid in ids[1:])
    assert any('soaked' in c.condition_id for c in engine.state.actors[ALLY].conditions.values())


def test_native_creature_moves_once_across_effects_then_again_next_turn(tmp_path):
    mid, areas = prepare(tmp_path, count=2)
    moved = []
    def choose(p):
        kind = p['context']['reaction_source_id']
        if kind.endswith('returning_streams_select'):
            return [z.zone_id for z in areas]
        if kind.endswith('returning_streams_operation'):
            return ['ally']
        if kind.endswith('returning_streams_target'):
            options = [o['id'] for o in p['choice']['options']]
            if not moved:
                assert ALLY in options
                moved.append(ALLY)
                return [ALLY]
            assert ALLY not in options
            return None
        if kind.endswith('returning_streams_ally_destination'):
            return ['cell:3,8']
        return None
    send(tmp_path, mid, MINOR, choose=choose)
    engine = cold(tmp_path, mid)[2]
    assert sum(e.payload.get('returning_streams_moved') == ALLY for e in engine.events) == 1
    assert engine.state.zones[areas[1].zone_id].active
    # The Court's free Return and the normal Bonus Action Return are separate
    # legal uses; the creature's movement limit spans both uses of the talent.
    repeated_targets = []
    def repeat(p):
        kind = p['context']['reaction_source_id']
        if kind.endswith('returning_streams_select'):
            return [areas[1].zone_id]
        if kind.endswith('returning_streams_operation'):
            return ['ally']
        if kind.endswith('returning_streams_target'):
            ids = [o['id'] for o in p['choice']['options']]
            repeated_targets.append(ids)
            assert ALLY not in ids
        return None
    send(tmp_path, mid, MINOR.removesuffix(' (free)'), choose=repeat)
    assert repeated_targets
    assert sum(e.payload.get('returning_streams_moved') == ALLY for e in cold(tmp_path, mid)[2].events) == 1
    turn(tmp_path, mid, OWNER, next_turn=True)
    def again(p):
        kind = p['context']['reaction_source_id']
        if kind.endswith('returning_streams_select'):
            return [areas[1].zone_id]
        if kind.endswith('returning_streams_operation'):
            return ['ally']
        if kind.endswith('returning_streams_target'):
            assert ALLY in [o['id'] for o in p['choice']['options']]
            return [ALLY]
        if kind.endswith('returning_streams_ally_destination'):
            return ['cell:3,7']
        return None
    send(tmp_path, mid, MINOR, choose=again)
    engine = cold(tmp_path, mid)[2]
    assert sum(e.payload.get('returning_streams_moved') == ALLY for e in engine.events) == 2
    assert (engine.state.actors[ALLY].position.x, engine.state.actors[ALLY].position.y) == (3, 7)


def test_native_two_qualifying_returns_each_heal_in_the_same_turn(tmp_path):
    mid, areas = prepare(tmp_path, count=4, injured=True)
    engine = cold(tmp_path, mid)[2]
    hp = engine.state.actors[ALLY].current_hp
    start = len(engine.events)
    selected = []
    def choose(p):
        kind = p['context']['reaction_source_id']
        if kind.endswith('returning_streams_select'):
            return selected
        if kind.endswith('returning_streams_operation'):
            return ['end']
        if kind.endswith('returning_streams_heal'):
            return [ALLY]
        return None
    for i, name in enumerate((MINOR, MINOR.removesuffix(' (free)'))):
        selected = [z.zone_id for z in areas[i * 2:i * 2 + 2]]
        send(tmp_path, mid, name, choose=choose)
        assert cold(tmp_path, mid)[2].state.actors[ALLY].current_hp == hp + 6 * (i + 1)
    events = cold(tmp_path, mid)[2].events[start:]
    heals = [e for e in events if e.event_type == 'HEALING_APPLIED']
    assert len(heals) == 2 and all(e.payload['offered'] == 6 for e in heals)


@pytest.mark.parametrize('invalid', ['four', 'foreign', 'outside'])
def test_native_rejects_invalid_selection_without_partial_commit(tmp_path, invalid):
    mid, areas = prepare(tmp_path, count=3 if invalid == 'four' else 2)
    if invalid == 'foreign':
        turn(tmp_path, mid, FOE)
        send(tmp_path, mid, 'Court of the Endless Tide')
        turn(tmp_path, mid, OWNER)
    if invalid == 'outside':
        turn(tmp_path, mid, OWNER, next_turn=True)
        send(tmp_path, mid, 'Shape Current: Mist Basin', at=(15, 6))
        send(tmp_path, mid, move=True, at=(2, 6))
    combat, table, engine = cold(tmp_path, mid)
    zones = [z for z in engine.state.zones.values() if z.active]
    if invalid == 'four':
        bad = [z.zone_id for z in zones if z.owner_id == OWNER]
        assert len(bad) == 4
    elif invalid == 'foreign':
        bad = [next(z.zone_id for z in zones if z.owner_id == FOE)]
    else:
        bad = [next(z.zone_id for z in zones if z.owner_id == OWNER
                    and engine.grid.distance_ft(engine.state.actors[OWNER].position, z.center) > 60)]
    before = engine.state.model_dump(mode='json')
    def choose(p):
        assert p['context']['reaction_source_id'].endswith('returning_streams_select')
        ids = [o['id'] for o in p['choice']['options']]
        assert p['choice']['maximum'] == 3
        if invalid != 'four':
            assert bad[0] not in ids
        return bad
    with pytest.raises((TabletopError, ValueError, CombatServiceError)):
        send(tmp_path, mid, MINOR, choose=choose)
    assert cold(tmp_path, mid)[2].state.model_dump(mode='json') == before


@pytest.mark.parametrize('owned', [True, False])
def test_native_ordinary_return_remains_available_without_owned_court(tmp_path, owned):
    mid, areas = prepare(tmp_path, count=1, court=False, streams=owned)
    engine = cold(tmp_path, mid)[2]
    ordinary = [a for a in engine.action_catalog.values()
                if a.owner_id == OWNER and a.display_name.startswith('Return the Flow: End It Early')
                and 'Ten Thousand' not in a.display_name]
    assert ordinary
    assert not any('Ten Thousand Returning Streams' in c.display_name for c in engine.legal_candidates())
    # The unmodified base action stays native and does not acquire Streams'
    # multi-select/healing provider outside an owned Court.
    assert all(not any(str(e.get('type', '')).startswith('water_returning_streams')
                       for e in a.parameters.get('typed', {}).get('effects', [])) for a in ordinary)
    start = len(engine.events)
    send(tmp_path, mid, ordinary[0].display_name)
    events = cold(tmp_path, mid)[2].events[start:]
    assert not any(e.event_type == 'HEALING_APPLIED' for e in events)


@pytest.mark.parametrize('kind', ['select', 'end'])
def test_automatic_seat_keeps_full_printed_selection_count(tmp_path, kind):
    # Observe the native reaction provider's public choice context. The real
    # deterministic controller still resolves each reaction without alteration.
    mid, areas = prepare(tmp_path, count=2)
    combat, table, _ = cold(tmp_path, mid)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    captured = []
    # Test the modifier through an actual legal intent. Auto-step chooses its
    # primary action via a deterministic local adapter; no live model is used.
    name = MINOR if kind == 'select' else 'Return the Flow: End It Early + Ten Thousand Returning Streams (free)'
    from combat.gate4_adapters import ManualControllerAdapter
    real_controller = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            c = next(c for c in context.legal_candidates if c.display_name == name)
            return ManualControllerAdapter(lambda _: (c.candidate_id, ())).choose_primary_action(context)
        def choose_reaction(self, context):
            if context.reaction_source_id.endswith('returning_streams_' + kind):
                spec = context.extension_choice
                captured.append((list(spec.option_ids), spec.maximum_selections))
            return real_controller.choose_reaction(context)
        def __getattr__(self, name):
            return getattr(real_controller, name)
    combat.controller = Controller()
    result = table.auto_step(mid, table.state(mid)['last_sequence'], [])
    assert result['status'] == 'COMMITTED', result
    assert captured and len(captured[0][0]) == 3
    assert captured[0][1] == 3
    engine = cold(tmp_path, mid)[2]
    assert any(z.active and z.source_definition_id in engine.action_catalog
               and engine.action_catalog[z.source_definition_id].parameters.get('typed', {}).get('source') == COURT
               for z in engine.state.zones.values())



def test_second_return_in_same_turn_stays_under_base_economy(tmp_path):
    """Review finding 2: limit "none" leaves each use to the base Return economy.

    The Court grants one free Return per turn; a bonus-action Return then spends the
    Bonus Action. Neither a second free use nor a second bonus use may be offered.
    """
    mid, areas = prepare(tmp_path, count=2)
    ids = [z.zone_id for z in areas]
    def end_first(p):
        kind = p['context']['reaction_source_id']
        if kind.endswith('returning_streams_select'):
            return [ids[0]]
        if kind.endswith('returning_streams_operation'):
            return ['end']
        return None
    send(tmp_path, mid, MINOR, choose=end_first)
    legal = [c.display_name for c in cold(tmp_path, mid)[2].legal_candidates()]
    assert MINOR not in legal
    bonus = MINOR.removesuffix(' (free)')
    def end_second(p):
        kind = p['context']['reaction_source_id']
        if kind.endswith('returning_streams_select'):
            return [ids[1]]
        if kind.endswith('returning_streams_operation'):
            return ['end']
        return None
    send(tmp_path, mid, bonus, choose=end_second)
    legal = [c.display_name for c in cold(tmp_path, mid)[2].legal_candidates()]
    assert bonus not in legal
    assert MINOR not in legal


def test_hook_is_inert_for_ordinary_return_and_gates_only_streams(tmp_path):
    """Review finding 3: the shared Return validator changes only the Streams modifier."""
    from types import SimpleNamespace as NS
    engine = NS(state=NS(zones={}))
    actor = NS(entity_id=OWNER, position=None)
    ordinary = NS(parameters={'typed': {'source': RETURN, 'modifier': None}})
    other = NS(parameters={'typed': {'source': 'WATER_BASE_OTHER', 'modifier': {'id': STREAMS}}})
    streams = NS(parameters={'typed': {'source': RETURN, 'modifier': {'id': STREAMS}}})
    assert water_return.returning_streams_allowed(engine, actor, None, ordinary) is None
    assert water_return.returning_streams_allowed(engine, actor, None, other) is None
    assert water_return.returning_streams_allowed(engine, actor, None, streams) is False


def test_area_move_does_not_consume_creature_once_per_turn_budget(tmp_path):
    """Review finding 4: area moves translate Water, not creatures, so the ally limit is untouched."""
    mid, areas = prepare(tmp_path, count=2)
    ids = [z.zone_id for z in areas]
    def choose(p):
        kind = p['context']['reaction_source_id']
        if kind.endswith('returning_streams_select'):
            return ids
        if kind.endswith('returning_streams_operation'):
            checkpoint = p['context']['checkpoint']
            return [next(op for zid, op in zip(ids, ['move', 'ally']) if zid in checkpoint)]
        if kind.endswith('returning_streams_destination'):
            return [next(o['id'] for o in p['choice']['options'] if '20 feet' in o['label'])]
        if kind.endswith('returning_streams_target'):
            return [ALLY]
        if kind.endswith('returning_streams_ally_destination'):
            return ['cell:3,8']
        return None
    send(tmp_path, mid, MINOR, choose=choose)
    engine = cold(tmp_path, mid)[2]
    assert engine.grid.distance_ft(engine.state.zones[ids[0]].center, areas[0].center) == 20
    assert sum(e.payload.get('returning_streams_moved') == ALLY for e in engine.events) == 1


@pytest.mark.parametrize('ops, heals', [(('soak', 'end'), True), (('move', 'end'), False)])
def test_heal_prerequisite_counts_consumed_effects_not_area_moves(tmp_path, ops, heals):
    """Review finding 5: consumed effects count toward 'at least two end'; area moves do not."""
    mid, areas = prepare(tmp_path, count=2)
    ids = [z.zone_id for z in areas]
    seen = []
    def choose(p):
        kind = p['context']['reaction_source_id']
        if kind.endswith('returning_streams_select'):
            return ids
        if kind.endswith('returning_streams_operation'):
            checkpoint = p['context']['checkpoint']
            return [next(op for zid, op in zip(ids, ops) if zid in checkpoint)]
        if kind.endswith('returning_streams_destination'):
            return [next(o['id'] for o in p['choice']['options'] if '20 feet' in o['label'])]
        if kind.endswith('returning_streams_target'):
            return [ALLY]
        if kind.endswith('returning_streams_heal'):
            seen.append(True)
            return [ALLY]
        return None
    start = len(cold(tmp_path, mid)[2].events)
    send(tmp_path, mid, MINOR, choose=choose)
    events = cold(tmp_path, mid)[2].events[start:]
    assert bool(seen) == heals
    assert any(e.event_type == 'HEALING_APPLIED' for e in events) == heals


def test_court_owner_concentration_capacity_stays_unlimited():
    """Review finding 6: Court concentration never falls back to Cultivation-Level caps."""
    rules = json.loads((ROOT / 'combat' / 'rules' / 'concentration.json').read_text())
    assert rules['capacity'] == 'unlimited'
