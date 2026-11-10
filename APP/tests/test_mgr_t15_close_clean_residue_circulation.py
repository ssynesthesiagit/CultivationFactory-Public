"""Clean Residue: imported Refined ownership, earned Heat and committed saves.

The named-pressure actions are sealed test producers of the public typed save
protocol; they never install ownership, Heat or the benefit being tested.
Fireball Art and all Furnace payments are shipped actions.
"""
import json
from pathlib import Path
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import foundation_combat as furnace

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = 'jade_furnace_meridian_v0_2B'
SOURCE = 'foundation.jade_furnace_meridian_v0_2B.refined_clean_residue_circulation'
OWNER, ALLY, FOE = ('actor:factory.residue_owner', 'actor:factory.residue_ally', 'actor:factory.residue_foe')
HEAT = 'resource:foundation.furnace_heat'


def document(name, *, stage=None, fire=False):
    doc = {
        'identity': {'display_name': name, 'creature_type': 'humanoid', 'cultivation_level': 15,
                     'proficiency_bonus': 4, 'path': 'Qi Cultivation', 'key_ability': 'CON'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 14, 'modifier': 2}
                          for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': 100},
            'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 500},
            'speed': {'walking_ft': 30}, 'technique_save_dc': 16, 'technique_attack_bonus': 8},
    }
    if stage:
        doc['foundation'] = {'foundation_id': FOUNDATION, 'stage': stage,
                             'resource': {'name': 'Furnace Heat', 'resource_id': 'foundation.resource.' + FOUNDATION,
                                          'maximum': 1, 'current': 0}}
    if fire:
        doc['spheres_and_talents'] = {
            'sphere_record_ids': ['tianxia.sphere.fire'],
            'learned_talent_record_ids': ['FIRE_TAL_FIREBALL_ART'],
        }
    return doc


def native_table(tmp_path, *, stage='Refined', cause='poison', ability='con', cancel=False):
    # Literal dynamic dependencies let the safe exporter follow the registry
    # and printed/catalog authority needed by native Foundation acquisition.
    for path in ('combat/rules/feature_blocks.d/a2_foundations_2.json',
                 'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
                 'authority/typed_mechanics/rules_text.json'):
        assert json.loads((ROOT / path).read_text())
    docs = [document('Furnace owner', stage=stage, fire=True), document('Other creature'),
            document('Poison caster')]
    combat = CombatService(ROOT, tmp_path)
    bundles = []
    for aid, doc in zip((OWNER, ALLY, FOE), docs):
        pid = aid.removeprefix('actor:factory.')
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundles.append(compile_character(combat._factory_owner_sheet(pid), actor_id=aid,
                                         reaction_plan={'ask': True}))
    effects = [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 1, 'sides': 4},
                'damage_types': ['poison' if cause == 'poison' else 'acid']}]
    save = {'type': 'save', 'applies_to': 'target', 'ability': ability, 'on_fail': effects}
    if cause not in {'poison', 'acid'}:
        save['save_categories'] = [cause]
    if cancel:
        # A creature-kind predicate is native save Disadvantage, not a mocked
        # mode callback. Both actual subjects are human characters.
        save['disadvantage_if_kind'] = 'humanoid'
    source = 'action:test.clean_residue_pressure'
    action = {'source_definition_id': source, 'display_name': 'Residue pressure', 'owner_id': FOE,
              'economy': 'BONUS_ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY',
              'range_ft': 60, 'costs': [], 'parameters': {'typed': {
                  'source': 'test.clean_residue_pressure', 'numbers': {'save_dc': 16},
                  'effects': [save], 'riders': [], 'duration': {'kind': 'instant'}}}}
    bundles[2]['action_catalog'].append(action)
    bundles[2]['actor_template']['action_ids'].append(source)
    # Guaranteed hostile fire damage exercises Vent Guard without a possible
    # natural-1 attack miss making the payment precondition seed-dependent.
    attack = {'source_definition_id': 'action:test.clean_residue_fire', 'display_name': 'Furnace pressure',
              'owner_id': FOE, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
              'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60, 'costs': [],
              'parameters': {'typed': {'source': 'test.clean_residue_fire', 'numbers': {},
                  'effects': [{'type': 'damage', 'applies_to': 'target', 'flat': 20,
                               'damage_types': ['fire']}], 'riders': [], 'duration': {'kind': 'instant'}}}}
    bundles[2]['action_catalog'].append(attack)
    bundles[2]['actor_template']['action_ids'].append(attack['source_definition_id'])
    bundles[2].pop('bundle_sha256', None)
    bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])
    arena = combat.tabletop_maps.save({'display_name': 'Clean residue yard', 'width_squares': 25,
        'height_squares': 10, 'walls': [], 'starts': {'team1': [[2, 5], [2, 7]], 'team2': [[10, 5]]}})
    battlefield = combat.factory_arenas(include_retired=True)['battlefield:map.' + arena['map_id']]
    mid = combat._finish_factory_match(bundles, [OWNER, ALLY, FOE],
        {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 2, 'y': 5}, ALLY: {'x': 2, 'y': 7}, FOE: {'x': 10, 'y': 5}},
        battlefield, [OWNER, ALLY], [FOE], control_modes={a: 'MANUAL' for a in (OWNER, ALLY, FOE)},
        match_seed='CLEAN-RESIDUE-NATIVE', display_name='Clean residue', maximum_rounds=15)['match_id']
    table = TabletopService(combat, tmp_path)
    turn(combat, table, mid, OWNER)
    return combat, table, mid


def cold(tmp_path, mid):
    combat = CombatService(ROOT, tmp_path)
    assert combat.verify(mid)['status'] == 'PASS'
    assert combat.replay(mid)['status'] == 'PASS'
    return combat, TabletopService(combat, tmp_path), combat._load_session(mid).engine


def commit(combat, table, mid, cid, *, take=None):
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.candidate_id == cid)
    answers, prompts = [], []
    for _ in range(20):
        result = table.act(mid, cid, c.decision_id, c.state_version, state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        prompts.append(p)
        options = (p.get('choice') or {}).get('options') or []
        selected = take(p, options) if take else None
        answers.append({**p['context'], 'selection': 'USE' if selected else 'DECLINE',
                        'option_ids': [selected] if selected else []})
    raise AssertionError('unresolved table choice')


def turn(combat, table, mid, actor):
    for _ in range(12):
        state = table.state(mid)
        if state['menu']['actor_id'] == actor:
            return
        commit(combat, table, mid, state['menu']['end_turn'])
    raise AssertionError('turn not reached')


def use(combat, table, mid, name, *, target=None, at=None, take=None):
    engine = combat._load_session(mid).engine
    candidates = [c for c in engine.legal_candidates()
                  if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == name
                  and (target is None or c.target_ids == (target,))
                  and (at is None or c.destination and (c.destination.x, c.destination.y) == at)]
    assert candidates, name
    return commit(combat, table, mid, candidates[0].candidate_id, take=take)


def earn_and_spend(tmp_path, *, route='banked', **kwargs):
    combat, table, mid = native_table(tmp_path, **kwargs)
    before = combat._load_session(mid).engine
    admitted = kwargs.get('stage', 'Refined') in {'Refined', 'Perfected'}
    assert any(row.get('feature_id') == SOURCE for row in before.typed_passive_rows.get(OWNER, [])) is admitted
    assert before.state.actors[OWNER].resources[HEAT] == 0
    assert furnace.held(before.state.actors[OWNER], 'clean_residue') is None
    use(combat, table, mid, 'Fireball Art', at=(10, 5))
    combat, table, engine = cold(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[HEAT] == 1
    assert furnace.held(engine.state.actors[OWNER], 'clean_residue') is None
    if route == 'guard':
        turn(combat, table, mid, FOE)
        use(combat, table, mid, 'Furnace pressure', target=OWNER,
            take=lambda p, opts: opts[0]['id'] if p['context'].get('reaction_source_id') == furnace.CHOICE + 'foundation_combat' else None)
    else:
        turn(combat, table, mid, FOE)
        turn(combat, table, mid, OWNER)
        def take(p, opts):
            rid = p['context'].get('reaction_source_id')
            if rid == 'choice:alternative_payment':
                label = 'Banked Furnace Expenditure' if route == 'banked' else 'Keep Furnace Heat; pay normally'
                return next(o['id'] for o in opts if label in str(o))
            if route == 'release' and rid == furnace.CHOICE + 'foundation_release':
                return opts[0]['id']
            return None
        use(combat, table, mid, 'Fireball Art', at=(10, 5), take=take)
    combat, table, engine = cold(tmp_path, mid)
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER
              and e.payload.get('resource_id') == HEAT]
    assert len(spends) == (0 if route == 'decline' else 1)
    assert all(e.payload['amount'] == 1 for e in spends)
    expected = admitted and route != 'decline'
    grant = furnace.held(engine.state.actors[OWNER], 'clean_residue')
    assert bool(grant) is expected
    assert not furnace.held(engine.state.actors[ALLY], 'clean_residue')
    if grant:
        assert grant.source_actor_id == OWNER
        if route == 'banked':
            # Banked Furnace Expenditure spends Heat through the substitution
            # menu: RESOURCE_SPENT is attributed to the triggering technique
            # (alternative_payments.py:137), while the Clean Residue rider is
            # granted under the Foundation payment's own source
            # (foundation_combat.py:756). These intentionally differ.
            assert grant.source_definition_id == furnace.feature('furnace', 'banked_furnace_expenditure')
        else:
            assert grant.source_definition_id == spends[0].source_definition_id
    # The rider itself spends no action, Reaction or extra Heat.
    assert engine.state.actors[OWNER].reaction_available is (route != 'guard')
    return combat, table, mid


@pytest.mark.parametrize('cause', ['poison', 'miasma', 'furnace_backlash', 'contaminated_qi', 'technique_residue'])
def test_next_named_constitution_save_consumes_after_cold_reload(tmp_path, cause):
    combat, table, mid = earn_and_spend(tmp_path, cause=cause)
    turn(combat, table, mid, FOE)
    use(combat, table, mid, 'Residue pressure', target=OWNER)
    _, _, engine = cold(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves[-1].payload['mode'] == 'ADVANTAGE'
    assert furnace.held(engine.state.actors[OWNER], 'clean_residue') is None
    # Consume only once: another committed save from this source cannot reuse it.
    turn(combat, table, mid, OWNER)
    turn(combat, table, mid, FOE)
    use(combat, table, mid, 'Residue pressure', target=OWNER)
    _, _, engine = cold(tmp_path, mid)
    if cause == 'poison':
        saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
        assert saves[-1].payload['mode'] == 'NORMAL'
    removed = [e for e in engine.events if e.event_type == 'CONDITION_REMOVED'
               and e.payload.get('condition_id') == furnace.P + 'clean_residue']
    assert len(removed) == 1


@pytest.mark.parametrize('route', ['release', 'guard'])
def test_every_base_spend_grants_owner_one_save(tmp_path, route):
    combat, table, mid = earn_and_spend(tmp_path, route=route)
    turn(combat, table, mid, FOE)
    use(combat, table, mid, 'Residue pressure', target=OWNER)
    _, _, engine = cold(tmp_path, mid)
    assert furnace.held(engine.state.actors[OWNER], 'clean_residue') is None
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves[-1].payload['mode'] == 'ADVANTAGE'


@pytest.mark.parametrize('case', ['dex', 'unrelated', 'disease', 'nonowner', 'unrefined', 'decline', 'expiry', 'cancel'])
def test_native_boundaries_and_cancellation(tmp_path, case):
    combat, table, mid = earn_and_spend(tmp_path,
        stage='Awakened' if case == 'unrefined' else 'Refined',
        route='decline' if case == 'decline' else 'banked',
        cause='disease' if case == 'disease' else 'acid' if case == 'unrelated' else 'poison',
        ability='dex' if case == 'dex' else 'con', cancel=case == 'cancel')
    if case == 'expiry':
        turn(combat, table, mid, FOE)
        turn(combat, table, mid, OWNER)
        assert furnace.held(cold(tmp_path, mid)[2].state.actors[OWNER], 'clean_residue')
    turn(combat, table, mid, FOE)
    use(combat, table, mid, 'Residue pressure', target=ALLY if case == 'nonowner' else OWNER)
    _, _, engine = cold(tmp_path, mid)
    remaining = case in {'dex', 'unrelated', 'disease', 'nonowner'}
    assert bool(furnace.held(engine.state.actors[OWNER], 'clean_residue')) is remaining
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'
             and e.actor_id == (ALLY if case == 'nonowner' else OWNER)]
    # This ADVANTAGE comes from the base Jade Furnace Meridian Frame (which
    # shared RESIDUE covers, disease included), not from Clean Residue. The
    # Clean Residue grant must still survive this save: 'remaining' above.
    assert saves[-1].payload['mode'] == ('ADVANTAGE' if case == 'disease' else 'NORMAL')
