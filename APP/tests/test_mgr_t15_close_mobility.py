"""Mobility through portable import, accepted table movement and cold replay.

Dynamic authority dependencies: TAL_ATHLETICS_MOBILITY,
ATHLETICS_BASE_COORDINATED_MOVEMENT, tianxia.sphere.athletics,
tianxia.mortal.weapon.jian. Registry dependencies: combat.ext.athletics,
combat.rules.feature_blocks (motion). No private historical fixtures.
Supporting source dependencies: RETRIBUTION_BASE_COUNTERSTRIKE,
tianxia.sphere.retribution, tianxia.sphere.the_piercing_needle, TAL_FENCING_FEINT.
"""
import json
from pathlib import Path
import zipfile

import pytest

from combat.gate2_runtime_content import AN, BAI
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore

ROOT = Path(__file__).resolve().parents[1]
OWNER = 'actor:factory.11111111'
STRIKER = 'actor:factory.22222222'
MOBILITY = 'TAL_ATHLETICS_MOBILITY'
OA = 'system:combat.opportunity_attack'
PUBLIC_TEST_DEPENDENCIES = (
    'combat/ext/athletics.py', 'combat/ext/counterstrike.py', 'combat/ext/needle_feint.py',
    'combat/rules/feature_blocks.json', 'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
)


def source_sheet(owned=False):
    return {
        'identity': {'display_name': 'Runner' if owned else 'Striker',
                     'cultivation_level': 1, 'proficiency_bonus': 2,
                     'path': 'Body Refining', 'key_ability': 'STR'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 14, 'modifier': 2}
                          for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 40},
            'speed': {'walking_ft': 30}, 'initiative': {'bonus': 2},
            'primary_resource': {'name': 'Stamina', 'maximum': 10},
            'technique_attack_bonus': 4, 'technique_save_dc': 12},
        'spheres_and_talents': {
            'sphere_record_ids': ['tianxia.sphere.athletics'],
            'learned_talent_record_ids': [MOBILITY] if owned else [],
            'automatic_sphere_component_record_ids': [
                'ATHLETICS_BASE_ATHLETIC_TRAINING', 'ATHLETICS_BASE_COORDINATED_MOVEMENT']},
        'equipment': [{'starting_kit': {'items': [
            {'item_id': 'tianxia.mortal.weapon.jian', 'quantity': 1}]}}],
    }


def fight(tmp_path, *, owned=True, typed=False, two=False, counter=False, feint=False):
    striker = source_sheet()
    if counter:
        striker['spheres_and_talents']['sphere_record_ids'].append('tianxia.sphere.retribution')
        striker['spheres_and_talents']['automatic_sphere_component_record_ids'].extend([
            'RETRIBUTION_BASE_COUNTERSTRIKE', 'RETRIBUTION_BASE_MARTIAL_FOCUS'])
    if feint:
        striker['spheres_and_talents']['sphere_record_ids'].append('tianxia.sphere.the_piercing_needle')
        striker['spheres_and_talents']['automatic_sphere_component_record_ids'].append('TAL_FENCING_FEINT')
    for pid, document in [('11111111', source_sheet(owned)), ('22222222', striker)]:
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    # Manual control and Ask me are separate persisted player preferences.
    # Import the preference before match compilation, just as the table does.
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(
        '22222222', {'mode': 'ask'}, set())
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Mobility yard', 'width_squares': 12,
        'height_squares': 12, 'walls': [],
        'starts': {'team1': [[4, 6]], 'team2': [[5, 6], [4, 7]]}})
    foes = [STRIKER] if typed else ([AN, STRIKER] if feint else [AN, BAI] if two else [AN])
    for seed in range(16):
        mid = service.create_factory_match(project_ids=['11111111'], opponent_actor_ids=foes,
            control_modes={aid: 'MANUAL' for aid in [OWNER, *foes]},
            arena_id='battlefield:map.mobility-yard', match_seed=f'MGR-T15-MOBILITY-{seed}')['match_id']
        if not (feint and not typed):
            break
        # An ally's Help expires at the helper's next turn. Select a
        # seeded initial initiative where AN -> helper -> mover to exercise
        # the benefit immediately after it is earned. Never
        # rewrite initiative, expiry or a successful Help receipt.
        order = service._load_session(mid).engine.state.initiative_order
        if order[(order.index(STRIKER) + 1) % len(order)] == OWNER:
            break
    else:
        pytest.fail('No seeded fixture with Help before the mover and after the beneficiary')
    table = TabletopService(service, tmp_path)
    for _ in range(6):
        state = table.state(mid)
        if state['menu']['actor_id'] == OWNER:
            break
        menu = state['menu']
        assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                         state['last_sequence'])['status'] == 'COMMITTED'
    assert table.state(mid)['menu']['actor_id'] == OWNER
    return service, table, mid, foes


def commit_move(service, table, mid, *, leave=True, use=True, auto=False):
    state = table.state(mid)
    engine = service._load_session(mid).engine
    before = engine.state.model_dump(mode='json')
    at = engine.state.actors[OWNER].position
    destination = {'x': at.x, 'y': at.y - (2 if leave else 1)}
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind == 'MOVE' and c.destination.model_dump(include={'x', 'y'}) == destination)
    if auto:
        production = service.controller
        class MoveController:
            def choose_primary_action(self, context):
                chosen = next(c for c in context.legal_candidates if c.candidate_id == candidate.candidate_id)
                return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(production, name)
        service.controller = MoveController()
    answers, prompts = [], []
    for _ in range(8):
        response = (table.auto_step(mid, state['last_sequence'], answers) if auto else
                    table.act(mid, candidate.candidate_id, candidate.decision_id,
                               candidate.state_version, state['last_sequence'], answers))
        if response['status'] == 'COMMITTED':
            return prompts
        assert response['status'] == 'REACTION_REQUIRED', response
        assert service._load_session(mid).engine.state.model_dump(mode='json') == before
        prompt = response['reaction']
        prompts.append(prompt)
        answers.append({**prompt['context'], 'selection': 'USE' if use else 'DECLINE'})
    pytest.fail('Movement did not commit after answering opportunity attacks')


def checked(service, tmp_path, mid):
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.engine.state == service._load_session(mid).engine.state
    assert cold.verify()['status'] == cold.mechanical.replay()['status'] == 'PASS'
    assert getattr(cold.engine, '_opportunity_attack_provenance', None) is None
    return cold.engine


@pytest.mark.parametrize('typed', [False, True], ids=['native', 'typed'])
@pytest.mark.parametrize('owned,use', [(True, True), (False, True), (True, False)])
def test_imported_mobility_actual_leave_reach_commit_reload(tmp_path, typed, owned, use):
    service, table, mid, foes = fight(tmp_path, typed=typed, owned=owned)
    # Reload before the producer as well as after it: ownership is compiled
    # from the imported source sheet, never installed in engine state.
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    prompts = commit_move(service, table, mid, use=use)
    engine = checked(service, tmp_path, mid)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED']
    assert len(attacks) == int(use)
    if use:
        assert attacks[0].actor_id == foes[0]
        assert attacks[0].payload['mode'] == ('DISADVANTAGE' if owned else 'NORMAL')
    assert engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[foes[0]].reaction_available is (not use)
    assert prompts  # Manual/Ask belongs to the attacker, not the protected mover.
    assert all(p['context']['reactor_id'] == foes[0] for p in prompts)


def test_mobility_applies_independently_to_multiple_native_attackers(tmp_path):
    service, table, mid, foes = fight(tmp_path, two=True)
    commit_move(service, table, mid)
    engine = checked(service, tmp_path, mid)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED']
    assert {e.actor_id for e in attacks} == set(foes)
    assert all(e.payload['mode'] == 'DISADVANTAGE' for e in attacks)


def test_mobility_move_without_leaving_reach_has_no_attack(tmp_path):
    service, table, mid, _ = fight(tmp_path)
    assert commit_move(service, table, mid, leave=False) == []
    engine = checked(service, tmp_path, mid)
    assert not [e for e in engine.events if e.event_type == 'ATTACK_ROLLED']


def end_turn(table, mid):
    state = table.state(mid)
    menu = state['menu']
    assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                     state['last_sequence'])['status'] == 'COMMITTED'


def commit_action(service, table, mid, candidate, *, prepare=False, aid=None):
    state = table.state(mid)
    answers = []
    for _ in range(12):
        response = table.act(mid, candidate.candidate_id, candidate.decision_id,
            candidate.state_version, state['last_sequence'], answers)
        if response['status'] == 'COMMITTED':
            return
        assert response['status'] == 'REACTION_REQUIRED', response
        context = response['reaction']['context']
        options = []
        if prepare and context['reaction_source_id'] == 'choice:needle.counterstrike':
            options = [next(option['id'] for option in response['reaction']['choice']['options']
                            if 'a foe starts an action that targets you' in option['label'])]
        if aid and context['reaction_source_id'].endswith('feint_aid'):
            options = [aid]
        answers.append({**context, 'selection': 'USE', 'option_ids': options})
    pytest.fail('Action did not commit after answering its choices')


@pytest.mark.parametrize('typed', [False, True], ids=['native', 'typed'])
def test_mobility_does_not_change_ordinary_attack_rolls(tmp_path, typed):
    service, table, mid, foes = fight(tmp_path, typed=typed)
    end_turn(table, mid)
    assert table.state(mid)['menu']['actor_id'] == foes[0]
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
        if OWNER in c.target_ids and c.kind == 'ACTION'
        and (engine.action_catalog[c.source_definition_id].resolution_kind in ('ATTACK', 'MULTI_ATTACK')
             or any(e.get('type') == 'attack' for e in
                    engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('effects', []))))
    commit_action(service, table, mid, candidate)
    engine = checked(service, tmp_path, mid)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED']
    assert attacks and all(e.payload['mode'] == 'NORMAL' for e in attacks)


def test_mobility_does_not_change_a_counterstrike_reaction(tmp_path):
    service, table, mid, _ = fight(tmp_path, typed=True, counter=True)
    end_turn(table, mid)
    engine = service._load_session(mid).engine
    ready = next(c for c in engine.legal_candidates() if c.display_name == 'Counterstrike')
    commit_action(service, table, mid, ready, prepare=True)
    end_turn(table, mid)
    # A real attack declaration triggers the prepared non-OA Reaction.
    engine = service._load_session(mid).engine
    attack = next(c for c in engine.legal_candidates()
        if STRIKER in c.target_ids and c.kind == 'ACTION'
        and any(e.get('type') == 'attack' for e in
                engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('effects', [])))
    commit_action(service, table, mid, attack)
    engine = checked(service, tmp_path, mid)
    counters = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == STRIKER]
    assert len(counters) == 1 and counters[0].payload['mode'] == 'NORMAL'


def test_disengage_movement_does_not_provoke_mobility_attack(tmp_path):
    service, table, mid, _ = fight(tmp_path)
    engine = service._load_session(mid).engine
    disengage = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == 'system:combat.disengage')
    commit_action(service, table, mid, disengage)
    assert commit_move(service, table, mid) == []
    assert not [e for e in checked(service, tmp_path, mid).events if e.event_type == 'ATTACK_ROLLED']


@pytest.mark.parametrize('typed', [False, True], ids=['native', 'typed'])
def test_mobility_cancels_real_feint_advantage_on_opportunity_roll(tmp_path, typed):
    service, table, mid, _ = fight(tmp_path, typed=typed, feint=True)
    beneficiary = STRIKER if typed else AN
    for _ in range(4):
        if table.state(mid)['menu']['actor_id'] == STRIKER:
            break
        end_turn(table, mid)
    engine = service._load_session(mid).engine
    feint = next(c for c in engine.legal_candidates()
                 if c.display_name == 'Feint' and OWNER in c.target_ids)
    commit_action(service, table, mid, feint, aid=beneficiary)
    # The opposing Advantage is earned by the native Help/Feint producer.
    actor = service._load_session(mid).engine.state.actors[beneficiary]
    assert any(m.value == 'ADVANTAGE:' + OWNER for m in actor.modifiers.values())
    end_turn(table, mid)
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    assert table.state(mid)['menu']['actor_id'] == OWNER
    commit_move(service, table, mid)
    engine = checked(service, tmp_path, mid)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == beneficiary]
    assert len(attacks) == 1 and attacks[0].payload['mode'] == 'NORMAL'


def test_manual_attacker_owns_opportunity_choice_on_an_automatic_movers_turn(tmp_path):
    # AI-step pauses for imported typed manual + Ask me reactors. Native
    # manual-on-AI-turn consent is an inherited controller limitation, not
    # Mobility behavior; keep the actual automatic movement producer here.
    service, table, mid, _ = fight(tmp_path, typed=True)
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    service.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = commit_move(service, table, mid, auto=True)
    assert prompts and all(p['context']['reactor_id'] == STRIKER for p in prompts)
    attacks = [e for e in checked(service, tmp_path, mid).events if e.event_type == 'ATTACK_ROLLED']
    assert len(attacks) == 1 and attacks[0].payload['mode'] == 'DISADVANTAGE'


def test_automatic_native_attacker_uses_its_policy_without_a_player_prompt(tmp_path):
    service, table, mid, _ = fight(tmp_path)
    service.set_controller_mode(mid, actor_id=AN, controller_mode='LOCAL_AUTO')
    production = service.controller
    class OpportunityPolicy:
        def choose_reaction(self, context):
            if context.reaction_source_id == OA:
                policy = context.policy.model_copy(update={'reaction_rules': {
                    **context.policy.reaction_rules, OA: {'minimum_packet': 0}}})
                context = context.model_copy(update={'policy': policy})
            return production.choose_reaction(context)
        def __getattr__(self, name):
            return getattr(production, name)
    service.controller = OpportunityPolicy()
    assert commit_move(service, table, mid) == []
    attacks = [e for e in checked(service, tmp_path, mid).events if e.event_type == 'ATTACK_ROLLED']
    assert len(attacks) == 1 and attacks[0].payload['mode'] == 'DISADVANTAGE'
