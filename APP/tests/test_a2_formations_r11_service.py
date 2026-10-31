"""Attack-category exclusion through accepted service intents and cold replay.

Synthetic sealed actions isolate source classification; hooks, rolls and engine
execution are unchanged. Nested reactions deliberately differ from foreground.
"""
import pytest
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, sealed_native_attack
from tests.formation_support import settle, turn
from tests.cw2_service_support import add_action, seal
from tests.test_a2_formations_r9_service import execute, equivalent, QI, REFLECT_CHOICE
from tests.test_a2_formations_second_pass import REFLECT

DIAGRAM_TALENT = 'tianxia.talent.formations.heaven_and_earth_become_the_diagram'
ATTACK = {'type': 'attack', 'attack_kind': 'cultivation_ranged',
          'on_hit': [{'type': 'damage', 'flat': 12, 'damage_types': ['force']}]}


def ready(tmp_path, prepare, seed):
    def setup(bundles):
        # Make the owner's Formation Check decisive without substituting dice.
        for action in bundles[0]['action_catalog']:
            typed = action['parameters'].get('typed') or {}
            if typed.get('numbers') is not None:
                typed['numbers']['key_mod'] = 100
                typed['numbers']['attack_bonus'] = 100
        prepare(bundles)
        for bundle in bundles:
            bundle['actor_template']['maximum_hp'] = 2000
            seal(bundle)
    combat, table, mid = fixture(tmp_path, [REFLECT], seed=seed,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 8, 'y': 6}},
        bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(5, 6)).candidate_id)
    turn(table, mid, FOE)
    return combat, table, mid


@pytest.mark.parametrize('native,category', [(False, 'metadata'), (False, 'printed'),
                                           (True, 'metadata'), (False, None)])
def test_resolving_ranged_attack_category_payment_delivery_and_reload(tmp_path, native, category):
    def prepare(bundles):
        foe = bundles[2]
        if native:
            sealed_native_attack(foe, 'Boundary shot', attack_bonus=20, modifier=12)
        else:
            add_action(foe, 'Boundary shot', [ATTACK], target='HOSTILE_ENTITY', typed={
                'range_ft': 60, 'numbers': {'attack_bonus': 20, 'pb': 5, 'key_mod': 0, 'cl': 15}})
        action = foe['action_catalog'][-1]
        action['costs'] = [[QI, 1]]
        typed = action['parameters'].setdefault('typed', {})
        if category == 'metadata':
            typed['source_category'] = 'Secret Inheritance'
        elif category == 'printed':
            typed['source'] = DIAGRAM_TALENT
    combat, table, mid = ready(tmp_path, prepare, 'A2FORMATIO-R11-ATTACK')
    session = combat._load_session(mid)
    before = session.engine.state.model_copy(deep=True)
    row = candidate(combat, mid, 'Boundary shot', target=OWNER)
    prompts = execute(combat, table, mid, session, row, {REFLECT_CHOICE: 'rebound'})
    engine = session.engine
    reflected = [p for p in prompts if p['context']['reaction_source_id'] == REFLECT_CHOICE]
    assert bool(reflected) is (category is None), prompts
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED'
               and e.source_definition_id == row.source_definition_id]
    assert len(attacks) == 1
    assert attacks[0].payload['natural_result'] != 1
    assert engine.state.actors[FOE].resources[QI] == before.actors[FOE].resources[QI] - 1
    assert engine.state.actors[ALLY].current_hp == before.actors[ALLY].current_hp
    if category:
        assert engine.state.actors[OWNER].current_hp < before.actors[OWNER].current_hp
        assert engine.state.actors[FOE].current_hp == before.actors[FOE].current_hp
        assert engine.state.actors[OWNER].resources == before.actors[OWNER].resources
        assert engine.state.actors[OWNER].reaction_available
        assert not [e for e in engine.events if e.source_definition_id == 'formation:reflecting_gate']
    else:
        assert engine.state.actors[OWNER].current_hp == before.actors[OWNER].current_hp
        assert engine.state.actors[FOE].current_hp < before.actors[FOE].current_hp
        assert engine.state.actors[OWNER].resources[QI] == before.actors[OWNER].resources[QI] - 2
        assert not engine.state.actors[OWNER].reaction_available
    assert not [e for e in engine.events if e.event_type == 'GM_RIDER' and 'could not run' in str(e.payload)]
    equivalent(tmp_path, mid, session)


@pytest.mark.parametrize('excluded', [True, False])
def test_nested_reaction_uses_own_source_instead_of_foreground(tmp_path, excluded):
    source = DIAGRAM_TALENT if excluded else 'test:ordinary_boundary_counter'
    rid = 'reaction:typed.' + source
    def prepare(bundles):
        # The foreground has the opposite category from its triggered reaction.
        add_action(bundles[0], 'Invite counter', [{'type': 'damage', 'flat': 1,
            'damage_types': ['force']}], target='HOSTILE_ENTITY', typed={
                **({'source_category': 'Secret Inheritance'} if not excluded else {})})
        bundles[2]['typed_reactions'].append({'block': 'generic', 'kind': 'damaged',
            'feature_id': source, 'name': 'Boundary counter', 'range_ft': 60, 'ask': True,
            'costs': [{'resource_id': QI, 'amount': 1}],
            'numbers': {'attack_bonus': 20, 'pb': 5, 'key_mod': 0, 'cl': 15}, 'effects': [ATTACK]})
    combat, table, mid = ready(tmp_path, prepare, 'A2FORMATIO-R11-NESTED')
    turn(table, mid, OWNER)
    session = combat._load_session(mid)
    before = session.engine.state.model_copy(deep=True)
    row = candidate(combat, mid, 'Invite counter', target=FOE)
    prompts = execute(combat, table, mid, session, row, {rid: 'USE', REFLECT_CHOICE: 'miss'})
    engine = session.engine
    assert any(p['context']['reaction_source_id'] == rid for p in prompts), prompts
    assert any(e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == source for e in engine.events)
    assert bool([p for p in prompts if p['context']['reaction_source_id'] == REFLECT_CHOICE]) is (not excluded), prompts
    assert engine.state.actors[FOE].resources[QI] == before.actors[FOE].resources[QI] - 1
    assert not engine.state.actors[FOE].reaction_available
    assert engine.state.actors[OWNER].reaction_available is excluded
    assert engine.state.actors[OWNER].resources[QI] == before.actors[OWNER].resources[QI] - (0 if excluded else 2)
    assert (engine.state.actors[OWNER].current_hp < before.actors[OWNER].current_hp) is excluded
    assert engine.state.actors[FOE].current_hp == before.actors[FOE].current_hp - 1
    assert engine.state.actors[ALLY].current_hp == before.actors[ALLY].current_hp
    assert not [e for e in engine.events if e.event_type == 'GM_RIDER' and 'could not run' in str(e.payload)]
    equivalent(tmp_path, mid, session)
