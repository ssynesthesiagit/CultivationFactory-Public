"""Review regressions: public testimony, private receipts and ending prompts."""
import socket

import pytest

from combat.ext.foundation_context import CONTEXT
from tests.test_mgr_t14_ash_parent import native_fixture, cast
from tests.test_mgr_t14_ash_mercy_parent import scene, FEATURE, POOL
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Combat regressions must never contact a live server')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_automatic_generation_consumes_public_witness_facts(tmp_path, mode):
    from tests.test_a2_foundations3 import pool
    combat, table, mid = native_fixture(tmp_path)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    prompts = cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1, 'incoming testimony must generate Funeral Ash'
    fact = next(e for e in engine.events if e.payload.get('fact_kind') == 'foundation_event_context')
    assert fact.payload['circumstances'] == 'real'
    assert fact.payload['declarant'] == ALLY
    assert fact.payload['beneficiary'] == OWNER
    assert any(p['context']['reactor_id'] == ALLY for p in prompts
               if p['context']['reaction_source_id'] == CONTEXT)


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_automatic_owner_accepts_finishing_source_as_public_witness(tmp_path, mode):
    from tests.test_a2_foundations3 import pool
    from combat.ext.foundation_context import public_scene_declarant
    combat, table, mid = native_fixture(tmp_path, foe_hp=1)
    turn(table, mid, ALLY)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    before = reload(tmp_path, mid)
    assert public_scene_declarant(before, before.state.actors[OWNER], before.state.actors[FOE], ALLY) is before.state.actors[ALLY], 'finishing-source witness must observe their own action'
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(8, 6)).candidate_id,
                     choices={CONTEXT: 'real', CONTEXT + '.detail': 'defeat'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1, 'finishing-source testimony must generate Funeral Ash'
    fact = next(e for e in engine.events if e.payload.get('fact_kind') == 'foundation_event_context'
                and e.payload.get('route') == 'ending')
    assert fact.payload['declarant'] == ALLY
    assert fact.payload['ending'] == 'defeat'
    assert engine.action_catalog[fact.payload['source_definition_id']].owner_id == ALLY
    assert all('Fireball Art' in p['moment'] for p in prompts
               if p['context']['reaction_source_id'].startswith(CONTEXT))
    assert any(p['context']['reactor_id'] == ALLY for p in prompts
               if p['context']['reaction_source_id'] == CONTEXT)


@pytest.mark.parametrize('cross_team,witness_relation,expected',
                         [(True, 'ALLY', 1), (False, 'ENEMY', 0)])
def test_public_witness_eligibility_uses_current_relation(tmp_path, cross_team, witness_relation, expected):
    from tests.test_mgr_t14_ash_mercy_parent import CONTEXT as MERCY_CONTEXT
    from combat.relations import relation
    # A paid reaction on an enemy turn keeps owner, subject and witness
    # distinct, independently exercising alliance eligibility. The automatic
    # owner responds natively; the manual attacker submits their own action.
    combat, table, mid = scene(tmp_path, extra_fire=True)

    def change(**values):
        version = combat._load_session(mid).engine.state.state_version
        combat.change_relations(mid, change=values, expected_state_version=version)

    if cross_team:
        change(kind='ACTOR_SIDE', subject=ALLY, other='team:visitors')
    change(kind='ACTOR_RELATION', subject=OWNER, other=ALLY, relation=witness_relation)
    before = reload(tmp_path, mid)
    assert relation(before, before.state.actors[OWNER], before.state.actors[ALLY]) == witness_relation
    assert (before.state.actors[OWNER].team_id != before.state.actors[ALLY].team_id) == cross_team
    turn(table, mid, 'actor:factory.worker2-foe1')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(3, 6)).candidate_id,
                     choices={MERCY_CONTEXT: 'genuine'})
    engine = reload(tmp_path, mid)
    grants = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED'
              and e.source_definition_id == FEATURE]
    assert len(grants) == expected, 'current alliance must determine witness eligibility'
    assert (any(p['context']['reactor_id'] == ALLY for p in prompts
                if p['context']['reaction_source_id'] == MERCY_CONTEXT)) == bool(expected)
    fact = next(e for e in engine.events if e.payload.get('fact_kind') == 'ash_mercy_restraint')
    assert fact.payload['declarant'] == (ALLY if expected else OWNER)
    assert fact.payload['context'] == ('genuine' if expected else 'unknown')
    assert relation(engine, engine.state.actors[OWNER], engine.state.actors[ALLY]) == witness_relation


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_automatic_paid_mercy_uses_public_restraint_then_chooses_recipient(tmp_path, mode):
    from tests.test_mgr_t14_ash_mercy_parent import CONTEXT as MERCY_CONTEXT
    combat, table, mid = scene(tmp_path, extra_fire=True)
    turn(table, mid, 'actor:factory.worker2-foe1')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(3, 6)).candidate_id,
                     choices={MERCY_CONTEXT: 'genuine'})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER
               and e.payload.get('resource_id') == POOL for e in engine.events)
    grant = next(e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED'
                 and e.source_definition_id == FEATURE)
    assert len(grant.target_ids) == 1
    assert grant.payload['offered'] == engine.state.actors[OWNER].proficiency_bonus
    fact = next(e for e in engine.events if e.payload.get('fact_kind') == 'ash_mercy_restraint')
    assert fact.payload['declarant'] == ALLY
    assert fact.payload['context'] == 'genuine'
    assert any(p['context']['reactor_id'] == ALLY for p in prompts
               if p['context']['reaction_source_id'] == MERCY_CONTEXT)


def test_ending_prompt_names_actual_action_and_affected_creature(tmp_path):
    combat, table, mid = native_fixture(tmp_path, incoming=False, foe_hp=1)
    prompts = cast(combat, table, mid, incoming=False, detail='defeat')
    engine = reload(tmp_path, mid)
    subject = engine.state.actors[FOE].display_name
    ending = [p for p in prompts if p['context']['reaction_source_id'].startswith(CONTEXT)]
    assert ending
    assert all('Fireball Art' in p['moment'] and subject in p['moment'] for p in ending)
    assert all(p['action'] == 'Fireball Art' for p in ending)
    receipt = next(e for e in engine.events if e.payload.get('fact_kind') == 'foundation_event_context'
                   and e.payload.get('route') == 'ending')
    assert receipt.target_ids == (FOE,)
    assert engine.action_catalog[receipt.payload['source_definition_id']].display_name == 'Fireball Art'


@pytest.mark.parametrize('unseen_observer', [False, True])
def test_native_damage_receipt_stays_private_without_hiding_visible_damage(tmp_path, monkeypatch, unseen_observer):
    from combat import ext, target_knowledge
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    from tests.h1_support import ROOT
    from tests.test_a2_foundations3 import owner_bundle
    observer_id = 'actor:factory.worker2-foe1'
    private_condition_id = 'condition:test.private_ash_receipt'

    def bundles(rows):
        rows[3] = owner_bundle('ash', actor_id=observer_id)

    def setup(engine):
        if not {FOE, observer_id} <= engine.state.actors.keys():
            return
        engine._apply_condition(engine.state.actors[FOE], private_condition_id, 'test:setup', FOE,
                                expires_on='UNTIL_REMOVED', data={})
        if unseen_observer:
            engine._apply_condition(engine.state.actors[observer_id], 'condition:typed.invisible',
                                    'test:setup', observer_id, expires_on='UNTIL_REMOVED', data={})
            # This genesis fixture starts unseen. _create_match observes the
            # bare roster before match_start installs the starting conditions;
            # remove that pre-setup memory before the genesis state is sealed.
            for observations in engine.state.observations.values():
                observations.pop(observer_id, None)

    # Load providers before monkeypatch snapshots the registry; otherwise its
    # teardown can remove providers lazily registered by the first fixture.
    ext.has('match_start')
    monkeypatch.setitem(ext._HOOKS, 'match_start', [*ext._HOOKS.get('match_start', ()), setup])
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle('ash'),
        ally_talents=['FIRE_TAL_FIREBALL_ART'], extra_foes=1, bundle_transform=bundles,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6},
                   FOE: {'x': 8, 'y': 6}, observer_id: {'x': 8, 'y': 5}})
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(8, 6)).candidate_id, choices={})
    engine = reload(tmp_path, mid)
    raw = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids)
    assert private_condition_id in raw.payload['target_conditions_before']
    assert observer_id in raw.payload['target_perceived_by']
    assert (target_knowledge.knowledge(engine, engine.state.actors[ALLY], engine.state.actors[observer_id]) is None) == unseen_observer
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    policy, _ = PolicyLibrary(ROOT).for_actor(ALLY)
    context = build_decision_context(engine, policy, for_ai=True, recent_event_limit=len(engine.events))
    projected = next((e for e in context.recent_events if e['sequence'] == raw.sequence), None)
    assert projected is not None, 'visible damage must remain in AI projection'
    assert not {'target_conditions_before', 'target_perceived_by', 'target_active_before'} & projected['payload'].keys(), 'private damage snapshots must be absent from AI projection'
    assert 'hp_damage' in projected['payload']
    assert private_condition_id in next(e for e in engine.events if e.sequence == raw.sequence).payload['target_conditions_before']
