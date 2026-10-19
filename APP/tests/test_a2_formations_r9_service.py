"""Accepted service checkpoints, persistent session execution and cold replay.

Sealed setup changes only deterministic DCs/numbers, HP and test actions; no
engine/hook replacement. In particular the counter is the shipped Counterweave.
"""
from types import SimpleNamespace

import pytest
from combat.gate2_runtime_models import ActionIntent, ReactionDecision, CandidateKind
from combat.gate3_storage import canonical_state_sha256
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate
from tests.formation_support import settle, turn, reload
from tests.cw2_service_support import add_action, seal
from tests.h1_support import sheet
from tests.test_a2_formations_second_pass import REFLECT, DEVOURS

COUNTER = 'TAL_QIWEAVING_COUNTERWEAVE'
COUNTER_REACTION = 'reaction:typed.' + COUNTER
DEVOUR_CHOICE = 'choice:needle.formation_devours_technique'
REFLECT_CHOICE = 'choice:needle.reflecting_gate'
QI = 'resource:core.qi'


def execute(combat, table, mid, session, row, picks=None):
    """Discover actual table prompts on service probes, commit on *this* session.

    Retaining the session is essential: reconstructing it before every command
    hides an engine-only stale policy. Embedded answers use the exact offered
    checkpoints. Preview must leave both the warm state and disk unchanged.
    """
    before = canonical_state_sha256(session.engine.state)
    intent = ActionIntent(intent_id=f'r9:{row.state_version}:{row.candidate_id}',
        decision_id=row.decision_id, candidate_id=row.candidate_id,
        state_version=row.state_version, actor_id=row.actor_id,
        target_ids=row.target_ids, destination=row.destination, option_ids=row.option_ids)
    answers, prompts = {}, []
    for _ in range(20):
        needed = combat._ask_during_ai_step(session, SimpleNamespace(intent=intent), answers)
        assert canonical_state_sha256(session.engine.state) == before
        if needed is None:
            break
        context = needed.context.model_dump(mode='json', by_alias=True)
        p = table._reaction_prompt(mid, context, engine=session.engine)
        prompts.append(p)
        rid = needed.context.reaction_source_id
        pick = (picks or {}).get(rid, 'first' if rid.startswith('choice:') else None)
        options = (p.get('choice') or {}).get('options') or []
        ids = (() if pick is None or not options else
               (options[0]['id'],) if pick == 'first' else (pick,))
        answer = ReactionDecision(checkpoint=needed.context.checkpoint,
            reactor_id=needed.context.reactor_id, reaction_source_id=rid,
            selection='DECLINE' if pick is None else 'USE', option_ids=ids)
        answers[(answer.checkpoint, answer.reactor_id, rid)] = answer
    else:
        raise AssertionError('unbounded reaction prompts')
    session.mechanical.execute_intent(intent.model_copy(update={'reaction_decisions': tuple(answers.values())}))
    return prompts


def equivalent(tmp_path, mid, session):
    cold = reload(tmp_path, mid)  # includes mechanical replay PASS
    assert canonical_state_sha256(cold.state) == canonical_state_sha256(session.engine.state)
    assert [r.model_dump(mode='json') for r in cold.rolls] == [r.model_dump(mode='json') for r in session.engine.rolls]
    return cold


def blast(bundles):
    effect = {'type': 'save', 'ability': 'DEX', 'dc': 'cultivation',
        'on_fail': [{'type': 'damage', 'dice': {'count': 1, 'sides': 6, 'modifier': 10},
                     'damage_types': ['force'], 'applies_to': 'target'}],
        'on_success': [{'type': 'damage', 'dice': {'count': 1, 'sides': 6, 'modifier': 10},
                        'damage_types': ['force'], 'applies_to': 'target'}]}
    add_action(bundles[2], 'Boundary blast', [effect], target='SELF', typed={
        'area': {'shape': 'sphere', 'size_ft': 60, 'who': 'enemies'},
        'numbers': {'save_dc': 1, 'cl': 15, 'pb': 5, 'key_mod': 0}})
    bundles[2]['action_catalog'][-1]['costs'] = [[QI, 2]]
    for bundle in bundles:
        bundle['actor_template']['maximum_hp'] = 2000
        if bundle['actor_id'] == ALLY:
            row = next(r for r in bundle['typed_reactions'] if r['feature_id'] == COUNTER)
            row['numbers']['key_mod'] = 100
            row['numbers']['attack_bonus'] = 100
        seal(bundle)


def test_partial_prevention_counter_then_decline_on_retained_session_equals_cold_replay(tmp_path):
    combat, table, mid = fixture(tmp_path, [DEVOURS], ally_talents=[COUNTER],
        seed='A2FORMATIO-R9-COUNTER', bundle_transform=blast,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 3, 'y': 10}, FOE: {'x': 8, 'y': 6}})
    settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(5, 6)).candidate_id)
    turn(table, mid, FOE)
    session = combat._load_session(mid)
    before = session.engine.state.model_copy(deep=True)
    roll_start = len(session.engine.rolls)
    row = candidate(combat, mid, 'Boundary blast')
    prompts = execute(combat, table, mid, session, row,
                      {DEVOUR_CHOICE: 'prevent', COUNTER_REACTION: 'USE'})
    assert [p['context']['reaction_source_id'] for p in prompts] == [DEVOUR_CHOICE, COUNTER_REACTION]
    engine = session.engine
    assert any('countered' in str(e.payload) for e in engine.events if e.source_definition_id == COUNTER)
    assert not [r for r in engine.rolls[roll_start:] if r.reason.startswith('SAVE:')]
    for aid in (OWNER, ALLY):
        assert engine.state.actors[aid].current_hp == before.actors[aid].current_hp
        assert not engine.state.actors[aid].reaction_available
    assert engine.state.actors[OWNER].resources[QI] == before.actors[OWNER].resources[QI] - 3
    assert engine.state.actors[ALLY].resources[QI] == before.actors[ALLY].resources[QI] - 1
    assert engine.state.actors[ALLY].resources['resource:core.martial_focus'] == before.actors[ALLY].resources['resource:core.martial_focus'] - 1
    assert engine.state.actors[FOE].resources[QI] == before.actors[FOE].resources[QI] - 2
    from combat.ext.formation_riders import CAUGHT
    equivalent(tmp_path, mid, session)
    # End-turn commands run on the same engine and do not dispatch typed cleanup.
    for _ in range(12):
        end = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.END_TURN)
        execute(combat, table, mid, session, end)
        if engine.state.current_actor_id == FOE:
            break
    else:
        raise AssertionError('foe did not regain its turn')
    assert engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[ALLY].reaction_available
    before_repeat = engine.state.model_copy(deep=True)
    roll_start = len(engine.rolls)
    row = next(c for c in engine.legal_candidates() if c.source_definition_id == row.source_definition_id)
    prompts = execute(combat, table, mid, session, row, {DEVOUR_CHOICE: None, COUNTER_REACTION: None})
    # Counterweave spent its Martial Focus; it cannot be offered again.
    assert [p['context']['reaction_source_id'] for p in prompts] == [DEVOUR_CHOICE]
    assert [r.actor_id for r in engine.rolls[roll_start:] if r.reason.startswith('SAVE:' + row.source_definition_id + ':')] == [ALLY, OWNER]
    for aid in (OWNER, ALLY):
        assert engine.state.actors[aid].current_hp < before_repeat.actors[aid].current_hp
        assert engine.state.actors[aid].resources == before_repeat.actors[aid].resources
        assert engine.state.actors[aid].reaction_available
    assert engine.state.actors[FOE].resources[QI] == before_repeat.actors[FOE].resources[QI] - 2
    assert CAUGHT not in engine.__dict__
    equivalent(tmp_path, mid, session)


@pytest.mark.parametrize('into', [True, False])
def test_reflection_final_recipient_controls_second_devours_boundary(tmp_path, into):
    def prepare(bundles):
        for a in bundles[2]['action_catalog']:
            if a['display_name'] == 'Binding Word':
                a['parameters']['typed']['numbers']['save_dc'] = 1
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [REFLECT], ally_talents=[DEVOURS],
        foe_sheet=sheet(['TAL_FATE_BINDING_WORD'], cl=15),
        seed='A2FORMATIO-R9-COMPOSED', bundle_transform=prepare,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 8}, FOE: {'x': 8, 'y': 6}})
    settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(4, 6)).candidate_id)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(4, 10)).candidate_id)
    turn(table, mid, FOE)
    session = combat._load_session(mid)
    from combat.ext import formations as F
    zones = {z.owner_id: z for z in F.arrays(session.engine)}
    assert F.inside(session.engine, session.engine.state.actors[OWNER], zones[OWNER])
    assert F.inside(session.engine, session.engine.state.actors[ALLY], zones[OWNER])
    assert not F.inside(session.engine, session.engine.state.actors[OWNER], zones[ALLY])
    assert F.inside(session.engine, session.engine.state.actors[ALLY], zones[ALLY])
    original, final = (OWNER, ALLY) if into else (ALLY, OWNER)
    before = session.engine.state.model_copy(deep=True)
    roll_start = len(session.engine.rolls)
    row = candidate(combat, mid, 'Binding Word', target=original)
    prompts = execute(combat, table, mid, session, row,
                      {REFLECT_CHOICE: 'redirect:' + final, DEVOUR_CHOICE: 'prevent'})
    expected = [REFLECT_CHOICE, DEVOUR_CHOICE] if into else [REFLECT_CHOICE]
    boundary_prompts = [p['context']['reaction_source_id'] for p in prompts
                        if p['context']['reaction_source_id'] in (REFLECT_CHOICE, DEVOUR_CHOICE)]
    assert boundary_prompts == expected, prompts
    engine = session.engine
    assert [r.actor_id for r in engine.rolls[roll_start:] if r.reason.startswith('SAVE:')] == ([] if into else [OWNER])
    assert engine.state.actors[OWNER].resources[QI] == before.actors[OWNER].resources[QI] - 2
    assert not engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[ALLY].resources[QI] == before.actors[ALLY].resources[QI] - (3 if into else 0)
    assert engine.state.actors[ALLY].reaction_available is (not into)
    assert engine.state.actors[FOE].resources[QI] == before.actors[FOE].resources[QI] - 2
    assert row.target_ids == (original,)  # accepted candidate/intent is replay-stable
    assert engine.state.actors[ALLY].conditions == before.actors[ALLY].conditions
    # Binding Word's successful save still delivers its printed speed penalty.
    penalties = [aid for aid, actor in engine.state.actors.items()
                 if any(m.source_definition_id == row.source_definition_id and m.target_field == 'speed_ft' and m.value == -10
                        for m in actor.modifiers.values())]
    assert penalties == ([] if into else [OWNER])
    equivalent(tmp_path, mid, session)


@pytest.mark.parametrize('pick', ['rebound', 'redirect:actor:factory.worker2-ally3'])
def test_charm_restricts_reflection_prompt_and_preserves_legal_delivery(tmp_path, pick):
    def prepare(bundles):
        add_action(bundles[1], 'Bind loyalty', [{'type': 'condition', 'condition': 'charmed',
            'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}])
        for a in bundles[2]['action_catalog']:
            if a['display_name'] == 'Binding Word':
                a['parameters']['typed']['numbers']['save_dc'] = 1
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [REFLECT], extra_allies=1,
        foe_sheet=sheet(['TAL_FATE_BINDING_WORD'], cl=15), bundle_transform=prepare,
        seed='A2FORMATIO-R9-CHARM', positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 8, 'y': 6}})
    settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(5, 6)).candidate_id)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Bind loyalty', target=FOE).candidate_id)
    turn(table, mid, FOE)
    session = combat._load_session(mid)
    assert any(c.condition_id == 'condition:typed.charmed' and c.source_actor_id == ALLY
               for c in session.engine.state.actors[FOE].conditions.values())
    before = session.engine.state.model_copy(deep=True)
    roll_start = len(session.engine.rolls)
    prompts = execute(combat, table, mid, session, candidate(combat, mid, 'Binding Word', target=OWNER),
                      {REFLECT_CHOICE: pick})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == REFLECT_CHOICE)
    ids = {o['id'] for o in prompt['choice']['options']}
    assert 'redirect:' + ALLY not in ids
    assert {'miss', 'rebound', 'redirect:actor:factory.worker2-ally3'} <= ids
    final = FOE if pick == 'rebound' else pick.removeprefix('redirect:')
    engine = session.engine
    assert [r.actor_id for r in engine.rolls[roll_start:] if r.reason.startswith('SAVE:')] == [final]
    assert engine.state.actors[OWNER].resources[QI] == before.actors[OWNER].resources[QI] - 2
    assert not engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[FOE].resources[QI] == before.actors[FOE].resources[QI] - 2
    assert engine.state.actors[ALLY].conditions == before.actors[ALLY].conditions
    assert engine.state.actors[OWNER].conditions == before.actors[OWNER].conditions
    assert any(m.target_field == 'speed_ft' and m.value == -10 for m in engine.state.actors[final].modifiers.values())
    assert engine.state.actors[ALLY].modifiers == before.actors[ALLY].modifiers
    equivalent(tmp_path, mid, session)
