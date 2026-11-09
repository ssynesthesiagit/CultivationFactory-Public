"""Merciful Hand choices use real unarmed table actions, reload and replay."""
import copy
import json
import zipfile

import pytest
from tests.legacy_fight_support import legacy_zero_hp

pytestmark = pytest.mark.usefixtures("legacy_zero_hp")

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from combat.ext.body_iron_fist import MERCIFUL_HAND_ID as FEATURE
from combat.ext.riders_metal import MARROW
from combat.gate3_reducer import canonical_state_sha256
from tests.test_zones import SHEET, ROOT
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender

OWNER = FACTORY_ACTOR_PREFIX + 'aaaaaaaa'
TARGET = FACTORY_ACTOR_PREFIX + 'bbbbbbbb'
FOCUS = 'resource:core.martial_focus'


def table_fight(monkeypatch, tmp_path, *, owns=True, hp=2, setup=None, shield=False, gate='breath', weapon=True, third=False,
                target_marrow=False):
    projects = ('aaaaaaaa', 'bbbbbbbb', 'cccccccc') if third else ('aaaaaaaa', 'bbbbbbbb')
    for project in projects:
        sheet = copy.deepcopy(SHEET)
        owner = project == 'aaaaaaaa'
        sheet['identity'].update(display_name='Sparing Monk' if owner else 'Practice Rival', cultivation_level=1)
        sheet['spheres_and_talents'] = {
            'sphere_record_ids': (['tianxia.sphere.iron_fist'] if owner else
                                  ['tianxia.sphere.metal'] if target_marrow else []),
            'learned_talent_record_ids': ((['TAL_IRON_FIST_IRON_FIST_TRAINING'] + ([FEATURE] if owns else [])) if owner else
                                         ['tianxia.talent.metal.indestructible_iron_marrow_sutra'] if target_marrow else [])}
        sheet['equipment'] = [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian'}]}}]
        if owner and not weapon:
            sheet['equipment'] = []
        if shield and owner:
            sheet['equipment'][0]['starting_kit']['items'].append({'item_id': 'tianxia.mortal.armor.shield'})
        sheet['ability_scores_and_statistics']['hit_points'] = {'maximum': hp if project == 'bbbbbbbb' else 60}
        folder = tmp_path / 'portable_characters' / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions('aaaaaaaa', {'mode': 'ask'}, {FEATURE})
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    def arrange(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == OWNER:
            actor = engine.state.actors[OWNER]
            if actor.resources.get(FOCUS, 0):
                engine._spend_resource(actor, FOCUS, 1, 'test:focus')
            if setup:
                setup(engine)
    install(monkeypatch, 'event', arrange)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Mercy yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[4, 4], [4, 5]]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa'], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + p for p in projects[1:]],
        control_modes={FACTORY_ACTOR_PREFIX + p: 'MANUAL' for p in projects}, arena_id='battlefield:map.mercy-yard',
        match_seed='LOCK7-MERCY')['match_id']
    table = TabletopService(combat, tmp_path)
    while table.state(mid)['menu']['actor_id'] != OWNER:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    source = next(g['source_definition_id'] for g in table.state(mid)['menu']['actions']
                  if g['source_definition_id'].endswith('.open_the_gate.' + gate))
    assert act(table, mid, source)['status'] == 'COMMITTED'
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    return combat, table, mid


def attack(table, mid, suffix='.natural.iron_fist_sphere'):
    state = table.state(mid)
    menu = state['menu']
    group = next(g for g in menu['actions'] if g['source_definition_id'].endswith(suffix))
    candidate = next(o['candidate_id'] for o in group['options'] if o['target_ids'] == [TARGET])
    args = (mid, candidate, menu['decision_id'], menu['state_version'], state['last_sequence'])
    return args, table.act(*args)


def reload(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


@pytest.mark.parametrize('choice', ['prone', 'grapple', 'reactions', 'step:2,4', 'decline'])
def test_all_choices_pause_restore_and_reload(monkeypatch, tmp_path, choice):
    combat, table, mid = table_fight(monkeypatch, tmp_path)
    before = combat._load_session(mid).engine.state
    args, first = attack(table, mid)
    assert first['status'] == 'REACTION_REQUIRED'
    assert canonical_state_sha256(combat._load_session(mid).engine.state) == canonical_state_sha256(before)
    shown = json.dumps(first['reaction'])
    assert all(text in shown for text in ('Merciful Hand', 'Sparing Monk', 'Practice Rival', '1 HP', 'Martial Focus'))
    answer = {**first['reaction']['context'], 'selection': 'DECLINE' if choice == 'decline' else 'USE',
              'option_ids': [] if choice == 'decline' else [choice]}
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert table.act(*args, [answer])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    target, owner = engine.state.actors[TARGET], engine.state.actors[OWNER]
    assert target.current_hp == (0 if choice == 'decline' else 1)
    assert target.active == (choice != 'decline')
    assert owner.resources[FOCUS] == (0 if choice == 'decline' else 1)
    assert owner.movement_remaining_ft == before.actors[OWNER].movement_remaining_ft
    if choice in ('prone', 'grapple', 'reactions'):
        condition = next(c for c in target.conditions.values() if c.source_definition_id == FEATURE)
        assert condition.condition_id == 'condition:typed.' + {'prone': 'prone', 'grapple': 'grappled', 'reactions': 'reaction_denied'}[choice]
        assert condition.expires_on == {'prone': 'STAND_UP', 'grapple': 'UNTIL_REMOVED', 'reactions': 'END_OF_HOLDER_NEXT_TURN'}[choice]
        assert condition.data['label'].startswith('Merciful Hand:')
    elif choice.startswith('step:'):
        assert (owner.position.x, owner.position.y) == (2, 4)
        assert target.reaction_available
        movement = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.payload.get('granted_cost_ft')]
        assert movement[-1].payload['granted_cost_ft'] == 5 and movement[-1].payload['cost_ft'] == 0


@pytest.mark.parametrize('case', ['unowned', 'weapon', 'nonlethal', 'temporary', 'immune', 'final_reduction'])
def test_unrelated_or_defended_nonlethal_damage_never_offers_mercy(monkeypatch, tmp_path, case):
    def setup(e):
        target = e.state.actors[TARGET]
        if case == 'temporary':
            e._grant_temp_hp(target, 10, 'test:buffer', TARGET)
        if case == 'immune':
            e._add_modifier(target, 'test:immune', 'damage_immunity', 'SET', 'BLUDGEONING', 'SELF', expires_on='END_OF_HOLDER_NEXT_TURN')
    if case == 'final_reduction':
        install(monkeypatch, 'final_damage', lambda *args: {'amount': 0})
    combat, table, mid = table_fight(monkeypatch, tmp_path, owns=case != 'unowned', hp=100 if case == 'nonlethal' else 2, setup=setup)
    args, result = attack(table, mid, '.weapon.jian' if case == 'weapon' else '.natural.iron_fist_sphere')
    assert result['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert not any(e.source_definition_id == FEATURE for e in engine.events)


@pytest.mark.parametrize('limit', ['pinned', 'shield', 'held'])
def test_illegal_step_or_grapple_is_not_offered(monkeypatch, tmp_path, limit):
    def setup(e):
        if limit == 'pinned':
            e._apply_condition(e.state.actors[OWNER], 'condition:typed.pinned', 'test:pin', TARGET, expires_on='UNTIL_REMOVED')
        if limit == 'held':
            e._apply_condition(e.state.actors[TARGET], 'condition:typed.grappled', 'test:grip', OWNER, expires_on='UNTIL_REMOVED')
    combat, table, mid = table_fight(monkeypatch, tmp_path, setup=setup, shield=limit == 'shield')
    args, result = attack(table, mid)
    assert result['status'] == 'REACTION_REQUIRED'
    shown = json.dumps(result['reaction'])
    assert ('step:' not in shown) if limit == 'pinned' else ('"grapple"' not in shown)


def test_merciful_grapple_frees_a_hand_by_stowing_weapon_at_table(monkeypatch, tmp_path):
    combat, table, mid = table_fight(monkeypatch, tmp_path, shield=True)
    # A shield and readied sword fill both hands. Stowing the sword through
    # the table must make the printed free-hand Merciful Hand option legal.
    assert cast_sender(combat, table, mid, 'Stow Jian')()['status'] == 'COMMITTED'
    args, result = attack(table, mid)
    assert result['status'] == 'REACTION_REQUIRED'
    assert any(o['id'] == 'grapple' for o in result['reaction']['choice']['options'])
    answer = {**result['reaction']['context'], 'selection': 'USE', 'option_ids': ['grapple']}
    assert table.act(*args, [answer])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert engine.state.actors[TARGET].current_hp == 1
    assert any(c.condition_id == 'condition:typed.grappled' for c in engine.state.actors[TARGET].conditions.values())


@pytest.mark.parametrize('choice', ['reactions', 'prone', 'grapple'])
def test_native_expiry_stand_up_and_release_after_reload(monkeypatch, tmp_path, choice):
    combat, table, mid = table_fight(monkeypatch, tmp_path)
    args, first = attack(table, mid)
    answer = {**first['reaction']['context'], 'selection': 'USE', 'option_ids': [choice]}
    assert table.act(*args, [answer])['status'] == 'COMMITTED'
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    if choice == 'grapple':
        source = next(g['source_definition_id'] for g in table.state(mid)['menu']['actions']
                      if g['source_definition_id'].endswith('.release_grapple'))
        assert act(table, mid, source)['status'] == 'COMMITTED'
    else:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
        if choice == 'reactions':
            from combat.typed_reactions import wants_opportunity_attack
            current = reload(tmp_path, mid)
            assert not wants_opportunity_attack(current, current.state.actors[TARGET], current.state.actors[OWNER])
            assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert not any(c.source_definition_id == FEATURE for c in engine.state.actors[TARGET].conditions.values())


def test_separate_followup_damage_is_not_silently_suppressed(monkeypatch, tmp_path):
    combat, table, mid = table_fight(monkeypatch, tmp_path, gate='centerline')
    args, first = attack(table, mid)
    answer = {**first['reaction']['context'], 'selection': 'USE', 'option_ids': ['prone']}
    assert table.act(*args, [answer])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (TARGET,)]
    assert damage[0].payload['remaining_hp'] == 1
    assert damage[-1].source_definition_id.endswith('.open_the_gate') and damage[-1].payload['remaining_hp'] == 0


def test_automatic_owner_selects_mercy_without_player_pause(monkeypatch, tmp_path):
    combat, table, mid = table_fight(monkeypatch, tmp_path, weapon=False)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    result = table.auto_step(mid, table.state(mid)['last_sequence'])
    assert result['status'] == 'COMMITTED'
    assert reload(tmp_path, mid).state.actors[TARGET].current_hp == 1


@pytest.mark.parametrize('component,kind', [('rider', 'unarmed'), ('primary', 'weapon'), ('primary', 'other')])
def test_other_damage_packets_do_not_inherit_mercy(monkeypatch, tmp_path, component, kind):
    from combat.damage_context import AttackDamage
    combat, table, mid = table_fight(monkeypatch, tmp_path)
    engine = combat._load_session(mid).engine
    # Unit packet control after a real verified table fixture; no saved-file mutation.
    candidate = next(c for c in engine.legal_candidates() if c.kind == 'END_TURN')
    from combat.gate2_runtime_models import ActionIntent
    intent = ActionIntent(intent_id='test:packet', decision_id=candidate.decision_id,
        state_version=candidate.state_version, candidate_id=candidate.candidate_id, actor_id=OWNER)
    provenance = AttackDamage('test:packet', OWNER, TARGET, 1, 'test:roll', 20, 30, True, kind, component)
    engine._commit_damage(engine.state.actors[TARGET], 10, 'BLUDGEONING', 'test:packet', OWNER, intent,
                          reaction_depth=3, attack_context=provenance)
    assert engine.state.actors[TARGET].current_hp == 0


def test_player_mercy_on_api_driven_enemy_movement_resumes_without_provider(monkeypatch, tmp_path):
    from tests.test_lock4_api_choices import Provider
    from combat.gate5_service import AI_RESPONSE_SCHEMA
    class MoveProvider(Provider):
        def complete_json(self, *, prompt_text, **kwargs):
            self.calls += 1
            frame = json.loads(prompt_text.split('\n\n', 1)[1])
            c = next(c for c in frame['legal_candidates'] if c.get('destination') == {'x': 5, 'y': 4})
            self.payload = {key: c[key] for key in ('candidate_id', 'actor_id', 'target_ids', 'destination', 'option_ids')}
            self.payload.update(decision_id=frame['decision_id'], state_version=frame['state_version'])
            return {'value': {'schema': AI_RESPONSE_SCHEMA, 'action_intent': self.payload, 'rationale': 'Move away.'},
                    'provider_id': 'test:offline', 'model': 'fake', 'request_sha256': 'test-request'}
    combat, table, mid = table_fight(monkeypatch, tmp_path, weapon=False)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    provider = MoveProvider()
    combat = CombatService(ROOT, tmp_path, ai_provider=provider)
    combat.set_controller_mode(mid, actor_id=TARGET, controller_mode='API_AUTO')
    first = combat.provider_step(mid)
    # The ordinary opportunity-attack consent is a separate, pre-existing decision.
    answers = []
    def answer(context, options):
        return {key: context[key] for key in ('checkpoint', 'reactor_id', 'reaction_source_id')} | {
            'selection': 'USE', 'option_ids': options}
    while first['status'] == 'AWAITING_REACTION' and 'merciful_hand' not in first['reaction_context']['reaction_source_id']:
        answers.append(answer(first['reaction_context'], []))
        first = combat.provider_step(mid, answers)
    assert first['status'] == 'AWAITING_REACTION'
    assert 'merciful_hand' in first['reaction_context']['reaction_source_id'] and provider.calls == 1
    answers.append(answer(first['reaction_context'], ['reactions']))
    reopened = CombatService(ROOT, tmp_path)
    assert reopened.provider_step(mid, answers)['status'] == 'COMMITTED'
    assert provider.calls == 1
    engine = reload(tmp_path, mid)
    assert engine.state.actors[TARGET].current_hp == 1
    assert any(c.source_definition_id == FEATURE for c in engine.state.actors[TARGET].conditions.values())


def test_step_exempts_only_spared_target_other_enemy_still_attacks(monkeypatch, tmp_path):
    combat, table, mid = table_fight(monkeypatch, tmp_path, third=True)
    before = combat._load_session(mid).engine.state.actors[OWNER].current_hp
    args, first = attack(table, mid)
    answer = {**first['reaction']['context'], 'selection': 'USE', 'option_ids': ['step:2,4']}
    assert table.act(*args, [answer])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp < before
    assert engine.state.actors[TARGET].reaction_available
    assert not engine.state.actors[FACTORY_ACTOR_PREFIX + 'cccccccc'].reaction_available


@pytest.mark.parametrize('floor', [-1, True, 10001, '1'])
def test_invalid_floor_unwinds_real_attack_transaction(monkeypatch, tmp_path, floor):
    combat, table, mid = table_fight(monkeypatch, tmp_path)
    install(monkeypatch, 'damage_floor', lambda *args: floor)
    before = combat._load_session(mid).engine.state
    from combat.gate5_service import CombatServiceError
    with pytest.raises(CombatServiceError) as error:
        attack(table, mid)
    cause = error.value.__cause__ or error.value.__context__
    assert isinstance(cause, ValueError) and 'damage_floor' in str(cause)
    assert canonical_state_sha256(combat._load_session(mid).engine.state) == canonical_state_sha256(before)


def test_zero_floor_preserves_plain_overkill_accounting(monkeypatch, tmp_path):
    combat, table, mid = table_fight(monkeypatch, tmp_path)
    install(monkeypatch, 'damage_floor', lambda *args: 0)
    args, result = attack(table, mid)
    assert result['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    packet = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (TARGET,))
    assert packet.payload['reduced_to'] == packet.payload['rolled_or_pending_damage'] > 2


def test_accepted_mercy_prevents_redundant_iron_marrow_save(monkeypatch, tmp_path):
    combat, table, mid = table_fight(monkeypatch, tmp_path, hp=2, target_marrow=True)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert cast_sender(combat, table, mid, 'Indestructible Iron Marrow Sutra')()['status'] == 'COMMITTED'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    args, first = attack(table, mid)
    assert first['status'] == 'REACTION_REQUIRED'
    assert 'Merciful Hand' in json.dumps(first['reaction'])
    answer = {**first['reaction']['context'], 'selection': 'USE', 'option_ids': ['prone']}
    assert table.act(*args, [answer])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    target = engine.state.actors[TARGET]
    assert target.current_hp == 1 and target.active
    assert any(c.condition_id == MARROW for c in target.conditions.values())


def test_accepted_mercy_does_not_suppress_followup_rider_marrow_save(monkeypatch, tmp_path):
    combat, table, mid = table_fight(monkeypatch, tmp_path, hp=2, target_marrow=True, gate='centerline')
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert cast_sender(combat, table, mid, 'Indestructible Iron Marrow Sutra')()['status'] == 'COMMITTED'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    args, first = attack(table, mid)
    assert first['status'] == 'REACTION_REQUIRED'
    assert 'Merciful Hand' in json.dumps(first['reaction'])
    mercy = {**first['reaction']['context'], 'selection': 'USE', 'option_ids': ['prone']}
    second = table.act(*args, [mercy])
    assert second['status'] == 'REACTION_REQUIRED', second
    assert 'Indestructible Iron Marrow Sutra' in json.dumps(second['reaction'])
    save = {**second['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []}
    assert table.act(*args, [mercy, save])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[TARGET]
    marrow = next(c for c in target.conditions.values() if c.condition_id == MARROW)
    assert target.current_hp == 0 and not target.active
    assert marrow.data['attempt_round'] == 0
    packets = [e for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (TARGET,)]
    assert packets[-1].source_definition_id.endswith('.open_the_gate')
    assert packets[-1].payload['remaining_hp'] == 0
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_mercy_packet_match_only_suppresses_primary_marrow_floor(monkeypatch, tmp_path):
    from combat.damage_context import AttackDamage
    from combat.ext import riders_metal
    from combat.ext import needle

    combat, table, mid = table_fight(monkeypatch, tmp_path, hp=2, target_marrow=True)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert cast_sender(combat, table, mid, 'Indestructible Iron Marrow Sutra')()['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    target = engine.state.actors[TARGET]
    engine._append_event('PASSIVE_TRIGGERED', FEATURE, actor_id=OWNER, target_ids=(TARGET,),
                         payload={'attack_roll_id': 'test:roll'})
    monkeypatch.setattr(needle, 'ask', lambda *args, **kwargs: ['save'])
    saves = []
    monkeypatch.setattr(riders_metal, 'marrow_save', lambda *args, **kwargs: saves.append(True) or 0)

    for component, expected in (('primary', None), ('rider', 1)):
        engine._damage_packet_context = AttackDamage('test:rider', OWNER, TARGET, 0, 'test:roll',
                                                     20, 20, False, 'unarmed', component)
        assert riders_metal.marrow_floor(engine, target, target.current_hp + target.temporary_hp,
                                         'BLUDGEONING', 'test:rider', OWNER, None) == expected
    assert saves == [True]
    engine._damage_packet_context = None
