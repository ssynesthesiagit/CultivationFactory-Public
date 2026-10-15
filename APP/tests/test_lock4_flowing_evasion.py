"""Seven R11 strict-xfail contracts ported from round18, now required to pass.

The old blocker-characterization tests asserted unchanged damage; those are not
acceptance criteria. These tests preserve the real compiled Dao/seeds/defenses.
"""
from pathlib import Path
import json
import zipfile
from dataclasses import FrozenInstanceError

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = 'actor:factory.r11'
ATTACKER = 'actor:factory.r11.attacker'
FLOWING = 'tianxia.subpath.qi.abyssal_depths_cultivator.feature.flowing_evasion'


def sheet(owns=True):
    return {**SHEET, 'identity': {**SHEET['identity'], 'cultivation_level': 20},
        'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'], 'technique_save_dc': 50},
        'spheres_and_talents': {}, 'path_and_subpath': {'path_feature_record_ids': [FLOWING] if owns else []}}


def fight(*, owns=True, defense=None, seed='R11-FLOWING'):
    attacker = {**sheet(False), 'equipment': [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao'}]}}]}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(compile_character(sheet(owns), actor_id=ME),
        compile_character(attacker, actor_id=ATTACKER)), roster_setup={'primary_actor_ids': [ME, ATTACKER],
        'team_by_actor': {ME: 'a', ATTACKER: 'b'},
        'starting_positions': {ME: {'x': 3, 'y': 6}, ATTACKER: {'x': 4, 'y': 6}}})
    engine.typed_control_modes = {ME: 'LOCAL_AUTO', ATTACKER: 'LOCAL_AUTO'}
    engine.state.current_slot_index = engine.state.initiative_order.index(ATTACKER)
    engine.state.current_actor_id = ATTACKER
    engine._system_start_turn()
    defender = engine.state.actors[ME]
    defender.maximum_hp = defender.current_hp = 1000
    defender.armor_class = -100
    if defense:
        engine._add_modifier(defender, 'r11-defense-fixture', 'damage_' + defense,
            'SET', 'SLASHING', 'SELF', expires_on='START_OF_SELF_NEXT_TURN')
    return engine


def attack(engine):
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith('Dao') and c.target_ids == (ME,))
    return engine.execute_intent(ActionIntent(intent_id='r11-flowing-attack', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ATTACKER,
        target_ids=candidate.target_ids, destination=candidate.destination))


@pytest.mark.parametrize('defense,seed', [
    (None, 'R11-FLOWING'), ('resistance', 'R11-FLOWING'), ('vulnerability', 'R11-FLOWING'),
    ('immunity', 'R11-FLOWING'), (None, 'R11-FLOWING-21'),
    ('resistance', 'R11-FLOWING-21'), ('vulnerability', 'R11-FLOWING-21')])
def test_flowing_evasion_halves_only_positive_post_defense_attack_damage(defense, seed):
    engine, control = fight(defense=defense, seed=seed), fight(owns=False, defense=defense, seed=seed)
    before_qi = engine.state.actors[ME].resources['resource:core.qi']
    attack(engine)
    attack(control)
    roll = next(e for e in engine.events if e.event_type == 'ATTACK_ROLLED')
    control_roll = next(e for e in control.events if e.event_type == 'ATTACK_ROLLED')
    assert roll.payload == control_roll.payload
    assert (roll.payload['natural_result'] == 20) == seed.endswith('-21')
    packet = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and ME in e.target_ids)
    original = next(e for e in control.events if e.event_type == 'DAMAGE_COMMITTED' and ME in e.target_ids)
    assert packet.payload['rolled_or_pending_damage'] == original.payload['rolled_or_pending_damage']
    pending = original.payload['reduced_to']
    assert packet.payload['reduced_to'] == pending // 2
    assert before_qi - engine.state.actors[ME].resources['resource:core.qi'] == (2 if pending else 0)


def test_packet_context_is_immutable_nested_nonattack_is_clear_and_outer_restores(monkeypatch):
    from combat.damage_context import AttackDamage
    from tests.test_lock_choices import install
    engine = fight(owns=False)
    defender = engine.state.actors[ME]
    provenance = AttackDamage('test:attack', ATTACKER, ME, 2, 'test:roll', 20, 28, True)
    seen = []
    def observe(e, target, amount, kind, source, actor, request):
        context = e.damage_context()
        seen.append(context)
        if context is not None:
            with pytest.raises(FrozenInstanceError):
                context.critical = False
            e._commit_damage(target, 1, 'FIRE', source, actor, None, reaction_depth=3)
            assert e.damage_context() is context
    install(monkeypatch, 'final_damage', observe)
    engine._commit_damage(defender, 5, 'SLASHING', 'test:attack', ATTACKER, None,
        reaction_depth=3, attack_context=provenance)
    assert seen == [provenance, None] and engine.damage_context() is None


@pytest.mark.parametrize('signal', ['pause', 'error'])
def test_packet_context_and_transaction_restore_on_failure(monkeypatch, signal):
    from combat.damage_context import AttackDamage
    from combat.ext import ControllerPause
    from tests.test_lock_choices import install
    engine = fight(owns=False)
    caught = ControllerPause if signal == 'pause' else ValueError
    def fail(*args):
        raise caught('choose')
    install(monkeypatch, 'final_damage', fail)
    before = engine.state.model_dump(mode='json'), list(engine.events)
    with pytest.raises(caught):
        with engine._transaction('test:damage', 'test:attack', ATTACKER):
            engine._commit_damage(engine.state.actors[ME], 5, 'SLASHING', 'test:attack', ATTACKER, None,
                reaction_depth=3, attack_context=AttackDamage('test:attack', ATTACKER, ME, 1, 'test:roll', 15, 23, False))
    assert engine.damage_context() is None
    assert (engine.state.model_dump(mode='json'), engine.events) == before


def test_owning_defender_does_not_evade_hazard_or_unrelated_packet():
    engine = fight()
    actor = engine.state.actors[ME]
    before = actor.resources['resource:core.qi']
    engine._commit_damage(actor, 10, 'FIRE', 'test:hazard', ATTACKER, None, reaction_depth=0)
    assert actor.resources['resource:core.qi'] == before
    assert not any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == FLOWING for e in engine.events)


@pytest.mark.parametrize('selection', ['USE', 'DECLINE', 'AUTO'])
@pytest.mark.parametrize('auto_turn', [False, True])
def test_player_choice_rolls_back_then_commits_reloads_and_replays(monkeypatch, tmp_path, selection, auto_turn):
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from combat.tabletop import ButtonStore
    from tests.test_lock_choices import install
    from tests.test_lock2_persistence import act
    from combat.gate3_reducer import canonical_state_sha256
    attack_project, defend_project = 'aaaaaaaa', 'dddddddd'
    for name in (attack_project, defend_project):
        content = sheet(name == defend_project)
        if name == attack_project:
            content['equipment'] = [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao'}]}}]
        archive = tmp_path / 'portable_characters' / name / 'current.zip'
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(content))
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(defend_project, {'mode': 'ask'}, {FLOWING})
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:critical', 'operation': 'replace', 'natural_result': 20})
    attacker, defender = [FACTORY_ACTOR_PREFIX + name for name in (attack_project, defend_project)]
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Evasion yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[4, 4]]}})
    view = service.create_factory_match(project_ids=[attack_project], opponent_actor_ids=[defender],
        control_modes={attacker: 'MANUAL', defender: 'MANUAL'}, arena_id='battlefield:map.evasion-yard', match_seed='LOCK4-EVASION-TABLE')
    mid, table = view['match_id'], TabletopService(service, tmp_path)
    if table.state(mid)['menu']['actor_id'] != attacker:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    state = table.state(mid)
    menu = state['menu']
    candidate = next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id'].endswith('.weapon.dao'))
    if selection == 'AUTO':
        service.set_controller_mode(mid, actor_id=defender, controller_mode='LOCAL_AUTO')
    if auto_turn:
        from tests.r1i_service_support import force_ai_candidate
        force_ai_candidate(service, mid, attacker, candidate)
    state = table.state(mid)
    menu = state['menu']
    before = service._load_session(mid).engine.state
    qi = before.actors[defender].resources['resource:core.qi']

    def send(answers=()):
        if auto_turn:
            return table.auto_step(mid, state['last_sequence'], list(answers))
        return table.act(mid, candidate, menu['decision_id'], menu['state_version'], state['last_sequence'], list(answers))

    first = send()
    if selection == 'AUTO':
        assert first['status'] == 'COMMITTED'
    else:
        assert first['status'] == 'REACTION_REQUIRED'
        shown = json.dumps(first['reaction'])
        assert all(name in shown for name in ('Flowing Evasion', '2 Qi', 'Dao', before.actors[defender].display_name))
        assert canonical_state_sha256(service._load_session(mid).engine.state) == canonical_state_sha256(before)
        answer = {**first['reaction']['context'], 'selection': selection, 'option_ids': ['halve'] if selection == 'USE' else []}
        answers = [answer]
        result = send(answers)
        # The printed Reaction also moves; answer its choices in the same transaction.
        while result['status'] == 'REACTION_REQUIRED':
            prompt = result['reaction']
            assert selection == 'USE' and 'Flowing Evasion movement' in prompt['reaction']
            options = ['5'] if 'distance' in prompt['reaction'] else ['cell:4,3']
            answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': options})
            result = send(answers)
        assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    used = selection != 'DECLINE'
    assert loaded.engine.state.actors[defender].resources['resource:core.qi'] == qi - (2 if used else 0)
    resolved = [e for e in loaded.engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == FLOWING]
    assert len(resolved) == int(used)
    packet = next(e for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED' and defender in e.target_ids)
    if used:
        assert resolved[0].payload['damage_after'] == resolved[0].payload['damage_before'] // 2
        assert packet.payload['reduced_to'] == resolved[0].payload['damage_after']
    assert loaded.engine.state.actors[defender].current_hp == before.actors[defender].current_hp - packet.payload['reduced_to']
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
