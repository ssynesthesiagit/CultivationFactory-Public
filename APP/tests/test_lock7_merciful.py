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
                target_marrow=False, talents=(), cl=1):
    projects = ('aaaaaaaa', 'bbbbbbbb', 'cccccccc') if third else ('aaaaaaaa', 'bbbbbbbb')
    for project in projects:
        sheet = copy.deepcopy(SHEET)
        owner = project == 'aaaaaaaa'
        sheet['identity'].update(display_name='Sparing Monk' if owner else 'Practice Rival', cultivation_level=cl if owner else 1)
        sheet['spheres_and_talents'] = {
            'sphere_record_ids': (['tianxia.sphere.iron_fist'] if owner else
                                  ['tianxia.sphere.metal'] if target_marrow else []),
            'learned_talent_record_ids': ((['TAL_IRON_FIST_IRON_FIST_TRAINING', *talents] + ([FEATURE] if owns else [])) if owner else
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
    def separate(ctx, target, kind):
        # A reaction/effect with its own Context is not damage added to this hit.
        from dataclasses import replace
        from combat.typed_executor import run_effects
        action = ctx.action.model_copy(update={'source_definition_id': 'test:separate', 'display_name': 'Separate effect'})
        # Replacing the source action without explicitly attaching its damage
        # retains no hit provenance (the Demon Mark/Forms-style source guard).
        run_effects(replace(ctx, action=action, targets=[target], target=target),
                    [{'type': 'damage', 'flat': 2, 'damage_types': ['force']}])
    install(monkeypatch, 'after_hit', separate)
    combat, table, mid = table_fight(monkeypatch, tmp_path)
    args, first = attack(table, mid)
    answer = {**first['reaction']['context'], 'selection': 'USE', 'option_ids': ['prone']}
    assert table.act(*args, [answer])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (TARGET,)]
    assert len(damage) == 2
    assert damage[0].payload['remaining_hp'] == 1
    assert damage[-1].source_definition_id == 'test:separate' and damage[-1].payload['remaining_hp'] == 0
    assert damage[-1].payload['hit_roll_id'] is None


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


def test_accepted_mercy_covers_centerline_without_a_redundant_marrow_save(monkeypatch, tmp_path):
    combat, table, mid = table_fight(monkeypatch, tmp_path, hp=2, target_marrow=True, gate='centerline')
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert cast_sender(combat, table, mid, 'Indestructible Iron Marrow Sutra')()['status'] == 'COMMITTED'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    args, first = attack(table, mid)
    assert first['status'] == 'REACTION_REQUIRED'
    assert 'Merciful Hand' in json.dumps(first['reaction'])
    mercy = {**first['reaction']['context'], 'selection': 'USE', 'option_ids': ['prone']}
    second = table.act(*args, [mercy])
    assert second['status'] == 'COMMITTED', second
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[TARGET]
    marrow = next(c for c in target.conditions.values() if c.condition_id == MARROW)
    assert target.current_hp == 1 and target.active
    assert marrow.data['attempt_round'] == 0
    packets = [e for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (TARGET,)]
    assert packets[-1].source_definition_id.endswith('.open_the_gate')
    assert packets[-1].payload['remaining_hp'] == 1
    assert packets[-1].payload['hit_roll_id'] == packets[0].payload['hit_roll_id']
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

BREAKING = 'TAL_IRON_FIST_BREAKING_KNUCKLE'
HIDDEN = 'tianxia.subpath.qi.ninpo_adept.feature.hidden_strike'


def fixed_primary(monkeypatch, amount):
    def reduced(engine, target, pending, *args):
        packet = engine.damage_context()
        if packet is not None and packet.component == 'primary':
            return {'amount': min(amount, pending)}
    install(monkeypatch, 'final_damage', reduced)


def settle_mercy(table, args, first, choices=None):
    answers, prompts = [], []
    choices = choices or {}
    result = first
    for _ in range(12):
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        source = prompt['context']['reaction_source_id']
        pick = choices.get(source, ['prone'])
        answers.append({**prompt['context'], 'selection': 'USE' if pick else 'DECLINE',
                        'option_ids': pick})
        result = table.act(*args, answers)
    raise AssertionError('hit did not finish')


@pytest.mark.parametrize('hp', [2, 5])
def test_whole_unarmed_hit_is_spared_once_with_multiple_later_packets(monkeypatch, tmp_path, hp):
    fixed_primary(monkeypatch, 3)
    combat, table, mid = table_fight(monkeypatch, tmp_path, hp=hp, gate='centerline', talents=[BREAKING])
    args, first = attack(table, mid)
    prompts = settle_mercy(table, args, first)
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (TARGET,)]
    assert len(damage) >= 3
    assert damage[0].payload['remaining_hp'] == (1 if hp == 2 else 2)
    assert all(e.payload['remaining_hp'] >= 1 for e in damage)
    assert engine.state.actors[TARGET].current_hp == 1
    assert len(prompts) == 1
    assert len([e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
                and e.source_definition_id == FEATURE and e.payload.get('attack_roll_id')]) == 1
    assert len({e.payload['hit_roll_id'] for e in damage}) == 1
    assert damage[-1].payload['damage_label'] == 'Breaking Knuckle'
    assert any(e.payload['damage_label'] == 'Centerline Impact' for e in damage)


def test_flowing_save_follows_centerline_and_breaking_damage(monkeypatch, tmp_path):
    fixed_primary(monkeypatch, 3)
    combat, table, mid = table_fight(monkeypatch, tmp_path, hp=100, gate='centerline',
        talents=[BREAKING, 'TAL_IRON_FIST_FLOWING_COMBINATION'], cl=5)
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions('aaaaaaaa', {'mode': 'ask'},
        {FEATURE, 'TAL_IRON_FIST_FLOWING_COMBINATION'})
    args, first = attack(table, mid)
    settle_mercy(table, args, first, {'choice:needle.flowing_combination': ['Shove: Prone']})
    events = reload(tmp_path, mid).events
    damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (TARGET,)]
    save = next(e for e in events if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id == 'passive:TAL_IRON_FIST_FLOWING_COMBINATION')
    assert len(damage) >= 3 and max(e.sequence for e in damage) < save.sequence


@pytest.mark.parametrize('owns', [False, True])
def test_hidden_continuation_rebuilds_after_later_mercy_pause_or_target_drop(monkeypatch, tmp_path, owns):
    # Hidden Strike queues its tail, then Centerline/Breaking makes the hit lethal.
    def setup(engine):
        engine.state.actors[OWNER].turn_flags['shadow_stepped'] = True
    def reduced(engine, target, pending, *args):
        packet = engine.damage_context()
        if packet is not None and packet.component == 'primary':
            return {'amount': min(3, pending)}
        if getattr(engine, '_damage_packet_label', None) == 'Hidden Strike':
            return {'amount': min(1, pending)}
    install(monkeypatch, 'final_damage', reduced)
    combat, table, mid = table_fight(monkeypatch, tmp_path, owns=owns, hp=5, setup=setup,
        gate='centerline', talents=[BREAKING, HIDDEN], cl=10)
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions('aaaaaaaa', {'mode': 'ask'}, {FEATURE, HIDDEN})
    before = canonical_state_sha256(combat._load_session(mid).engine.state)
    args, first = attack(table, mid)
    if owns:
        assert first['status'] == 'REACTION_REQUIRED'
        assert 'Merciful Hand' in json.dumps(first['reaction'])
        assert canonical_state_sha256(combat._load_session(mid).engine.state) == before
    prompts = settle_mercy(table, args, first, {'choice:needle.hidden_strike_rider': ['vanish']})
    engine = reload(tmp_path, mid)
    if owns:
        assert [p['context']['reaction_source_id'] for p in prompts] == [
            'choice:needle.merciful_hand', 'choice:needle.hidden_strike_rider']
        assert engine.state.actors[TARGET].current_hp == 1
        assert len([c for c in engine.state.actors[OWNER].conditions.values()
                    if c.condition_id == 'condition:typed.hidden_strike_stealth']) == 1
    else:
        # Main also skips Hidden Strike's tail when its own damage drops the target;
        # this is a main-protecting target-drop control, not a negative control.
        assert not prompts and engine.state.actors[TARGET].current_hp == 0
    assert len([e for e in engine.events if e.event_type == 'DAMAGE_ROLLED'
                and e.payload.get('damage_label') == 'Hidden Strike']) == 1
    assert not hasattr(engine, '_hit_settlements')


@pytest.mark.parametrize('hp', [27, 100])
def test_feast_save_branch_follows_breaking_and_joins_hit_concentration(monkeypatch, hp):
    from tests import test_riders_c7 as c7
    from combat.gate2_runtime_models import DiceSpec
    from combat.ext import devouring_maw
    feast = c7.MAW + 'feast_upon_protection'
    spheres = {'sphere_record_ids': ['tianxia.sphere.iron_fist'],
               'learned_talent_record_ids': ['TAL_IRON_FIST_IRON_FIST_TRAINING', BREAKING, FEATURE]}
    engine = c7.fight(c7.bundle([feast], spheres=spheres, cl=devouring_maw.LEVELS['feast']),
                      foe=c7._typed_foe())
    actor, target = engine.state.actors[c7.ME], engine.state.actors[c7.FOE]
    target.current_hp = hp
    target.maximum_hp = hp
    target.armor_class = -50
    install(monkeypatch, 'd20_result', lambda e, roll, intent: {
        'source_id': 'test:roll', 'operation': 'replace',
        'natural_result': 20 if roll.actor_id == c7.ME else 1})
    install(monkeypatch, 'attack_damage', lambda ctx, dice: DiceSpec(count=1, sides=2, modifier=16))
    fixed_primary(monkeypatch, 16)
    def rolled(ctx, effect, key):
        if effect.get('dice') == {'count': 4, 'sides': 8}:
            ctx.damage_cache[key] = (16, 'FIRE')
    install(monkeypatch, 'damage_roll_resolved', rolled)
    # _pick_type(count=3) reads three distinct record indices, then a consumed type.
    c7.answers(engine, {'maw_types': ['0', '1', '2'], 'maw_damage_type': ['FIRE'],
                        'merciful_hand': ['prone']})
    prompts = []
    provider = engine._gate4_reaction_provider
    def record_prompt(request):
        prompts.append(copy.deepcopy(request))
        return provider(request)
    engine.set_reaction_provider(record_prompt)
    c7.use(engine, 'Open the Gate: Breath-Checking Strike')
    c7._essence(engine, actor, 'FIRE', 'FIRE', 'FIRE')
    engine._apply_condition(target, 'condition:typed.test_protection', 'test:protection', target.entity_id,
        expires_on='END_OF_HOLDER_NEXT_TURN', data={'source_cl': 1, 'rule': {'damage_resistances': ['FIRE']}})
    engine._start_concentration(target, 'test:held')
    assert devouring_maw.stored(actor) == ['FIRE', 'FIRE', 'FIRE']
    assert target.active and '_round_feast' not in actor.turn_flags
    prompts.clear()
    events = c7.use(engine, c7.unarmed(engine), target=target.entity_id)
    # Prove Feast actually fired before checking its packet order or membership.
    feast_prompt = next(p for p in prompts if p['reaction_source_id'] == 'choice:needle.maw_types')
    assert 'Feast upon Protection' in feast_prompt['choice_trigger']['prompt']
    assert feast_prompt['protected_target_id'] == target.entity_id
    ability_save = next(e for e in events if e.event_type == 'SAVE_ROLLED'
                        and e.source_definition_id != 'system:combat.concentration')
    assert ability_save.actor_id == target.entity_id
    assert ability_save.payload['reason'] == f'SAVE:{ability_save.source_definition_id}:CON'
    assert not ability_save.payload['success']
    spent = [e for e in events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == feast
             and e.payload.get('resource_id') == c7.ESSENCE]
    assert len(spent) == 1 and spent[0].payload['amount'] == 3 and spent[0].payload['remaining'] == 0
    assert devouring_maw.stored(actor) == []
    damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (target.entity_id,)]
    assert [e.payload['reduced_to'] for e in damage] == [16, 5, 5 if hp == 27 else 16]
    assert [e.payload['remaining_hp'] for e in damage] == ([11, 6, 1] if hp == 27 else [84, 79, 63])
    protection = next(e for e in events if e.event_type == 'CONDITION_APPLIED'
                      and e.payload.get('condition_id') == 'condition:typed.feast_set_aside')
    assert damage[1].sequence < ability_save.sequence < protection.sequence < damage[2].sequence
    concentration = [e for e in events if e.event_type == 'SAVE_ROLLED'
                     and e.source_definition_id == 'system:combat.concentration']
    assert len(concentration) == 1
    assert concentration[0].payload['dc'] == (13 if hp == 27 else 18)
    assert concentration[0].sequence > damage[-1].sequence
    assert len({e.payload['hit_roll_id'] for e in damage}) == 1
    mercy = [e for e in events if e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == FEATURE]
    assert len(mercy) == int(hp == 27)


def test_bloodletting_save_waits_for_breaking_and_lethal_damage_offers_mercy(monkeypatch):
    from tests import test_riders_c7 as c7
    from combat.gate2_runtime_models import DiceSpec
    spheres = {'sphere_record_ids': ['tianxia.sphere.iron_fist', 'tianxia.sphere.blood'],
               'learned_talent_record_ids': ['TAL_IRON_FIST_IRON_FIST_TRAINING', BREAKING, FEATURE,
                                            'tianxia.talent.blood.bloodletting_strike']}
    engine = c7.fight(c7.bundle([], spheres=spheres, cl=13), foe=c7._typed_foe())
    actor, target = engine.state.actors[c7.ME], engine.state.actors[c7.FOE]
    target.current_hp = 18
    target.armor_class = -50
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    install(monkeypatch, 'attack_damage', lambda ctx, dice: DiceSpec(count=1, sides=2, modifier=16))
    fixed_primary(monkeypatch, 16)
    install(monkeypatch, 'damage_roll_resolved',
            lambda ctx, effect, key: ctx.damage_cache.__setitem__(key, (4, 'NECROTIC'))
            if effect.get('damage_types') == ['necrotic'] else None)
    c7.answers(engine, {'merciful_hand': ['prone']})
    c7.use(engine, 'Open the Gate: Breath-Checking Strike')
    events = c7.use(engine, c7.unarmed(engine), target=target.entity_id)
    damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (target.entity_id,)]
    assert [e.payload['remaining_hp'] for e in damage] == [2, 1, 1]
    save = next(e for e in events if e.event_type == 'SAVE_ROLLED')
    assert max(e.sequence for e in damage) < save.sequence
    assert len({e.payload['hit_roll_id'] for e in damage}) == 1
    assert len([e for e in events if e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == FEATURE]) == 1


@pytest.mark.parametrize('rider,total,dc', [('centerline', 21, 10), ('lightening', 32, 16)])
def test_missing_added_damage_identity_makes_one_combined_save(monkeypatch, rider, total, dc):
    from tests import test_riders_c7 as c7
    from combat.gate2_runtime_models import DiceSpec
    spheres = {'sphere_record_ids': ['tianxia.sphere.iron_fist', 'tianxia.sphere.gravity'],
               'learned_talent_record_ids': ['TAL_IRON_FIST_IRON_FIST_TRAINING',
                                            *(['GRAVITY_BASE_WEIGHTED_STRIKE', 'TAL_GRAVITY_WEIGHT_SHIFT_BASE'] if rider == 'lightening' else [])]}
    engine = c7.fight(c7.bundle([], spheres=spheres, cl=13), foe=c7._typed_foe())
    actor, target = engine.state.actors[c7.ME], engine.state.actors[c7.FOE]
    target.current_hp = 100
    target.maximum_hp = 100
    target.armor_class = -50
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    install(monkeypatch, 'attack_damage', lambda ctx, dice: DiceSpec(count=1, sides=2, modifier=16))
    fixed_primary(monkeypatch, 16)
    install(monkeypatch, 'damage_roll_resolved',
            lambda ctx, effect, key: ctx.damage_cache.__setitem__(key, (16, 'FORCE'))
            if effect.get('damage_types') == ['force'] else None)
    c7.answers(engine, {'gravity_weighted_strike': ['lightening:stamina'], 'rider_step': None})
    if rider == 'lightening':
        c7.use(engine, 'Weight Shift: Body Lightening')
        c7.use(engine, 'Open the Gate: Breath-Checking Strike')
    engine._start_concentration(target, 'test:held')
    events = c7.use(engine, c7.unarmed(engine), target=target.entity_id)
    damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (target.entity_id,)]
    assert len(damage) == 2
    assert sum(e.payload['reduced_to'] for e in damage) == total
    assert target.current_hp == 100 - total
    saves = [e for e in events if e.event_type == 'SAVE_ROLLED'
             and e.source_definition_id == 'system:combat.concentration']
    assert len(saves) == 1 and saves[0].payload['dc'] == dc
    assert saves[0].sequence > damage[-1].sequence
    assert len({e.payload['hit_roll_id'] for e in damage}) == 1


def test_nested_attack_continuation_drains_only_its_own_roll(monkeypatch, tmp_path):
    from combat.hit_settlement import defer
    from combat.typed_executor import Context, block_attack
    trace = []
    def chosen(ctx, target, kind):
        roll = ctx.attack_damage_context.roll_id
        trace.append(('queued', roll))
        def first():
            trace.append(('first', roll))
            if ctx.source != 'test:nested':
                action = ctx.action.model_copy(update={'source_definition_id': 'test:nested',
                                                       'display_name': 'Nested strike'})
                typed = {**ctx.typed, 'effects': []}
                block_attack(Context(ctx.engine, ctx.actor, action, ctx.intent, typed, [target], target),
                    {'type': 'attack', 'attack_kind': 'melee', 'count': 1,
                     'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['force']}]})
        assert defer(ctx.engine, ctx.attack_damage_context, first)
        assert defer(ctx.engine, ctx.attack_damage_context, lambda: trace.append(('last', roll)))
    install(monkeypatch, 'after_hit_choice', chosen)
    combat, table, mid = table_fight(monkeypatch, tmp_path, hp=100)
    args, first = attack(table, mid)
    assert first['status'] == 'COMMITTED'
    # Preview and commit each execute the transaction. Check the committed suffix.
    queued = [r for kind, r in trace if kind == 'queued']
    outer, inner = queued[-2:]
    assert outer != inner
    assert trace[-6:] == [('queued', outer), ('first', outer), ('queued', inner),
                          ('first', inner), ('last', inner), ('last', outer)]
    assert not hasattr(reload(tmp_path, mid), '_hit_settlements')


def test_oni_mask_damage_precedes_flowing_combination_save(monkeypatch):
    from tests import test_riders_c7 as c7
    from combat.gate2_runtime_models import DiceSpec
    spheres = {'sphere_record_ids': ['tianxia.sphere.iron_fist'],
               'learned_talent_record_ids': ['TAL_IRON_FIST_IRON_FIST_TRAINING',
                                            'TAL_IRON_FIST_FLOWING_COMBINATION', BREAKING]}
    engine = c7.fight(c7.bundle([c7.ONI + 'oni_mask'], spheres=spheres, cl=13), foe=c7._typed_foe())
    c7.answers(engine, {'flowing_combination': ['Shove: Prone']})
    c7.use(engine, 'Oni Mask')
    c7.use(engine, 'Open the Gate: Centerline Impact')
    install(monkeypatch, 'd20_result', lambda *args: {
        'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    install(monkeypatch, 'attack_damage', lambda ctx, dice: DiceSpec(count=1, sides=2, modifier=3))
    fixed_primary(monkeypatch, 3)
    install(monkeypatch, 'damage_roll_resolved',
            lambda ctx, effect, key: ctx.damage_cache.__setitem__(key, (4, 'NECROTIC'))
            if effect.get('damage_types') == ['necrotic'] else None)
    events = c7.use(engine, c7.unarmed(engine), target=c7.FOE)
    damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (c7.FOE,)]
    save = next(e for e in events if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id == 'passive:TAL_IRON_FIST_FLOWING_COMBINATION')
    assert [e.payload['hp_damage'] for e in damage] == [3, 4, 5, 5]
    assert [e.payload['remaining_hp'] for e in damage] == [997, 993, 988, 983]
    assert max(e.sequence for e in damage) < save.sequence
    assert len({e.payload['hit_roll_id'] for e in damage}) == 1


def test_declined_mercy_is_retained_across_later_packets_and_packet_rescues(monkeypatch, tmp_path):
    # A distinct rescue keeps the target up after each lethal packet. Declining
    # Mercy must not be undone by a second offer on this same hit.
    install(monkeypatch, 'lethal_damage', lambda *args: 1)
    fixed_primary(monkeypatch, 3)
    combat, table, mid = table_fight(monkeypatch, tmp_path, hp=2, gate='centerline', talents=[BREAKING])
    args, first = attack(table, mid)
    prompts = settle_mercy(table, args, first, {'choice:needle.merciful_hand': []})
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (TARGET,)]
    assert len(damage) == 3 and [e.payload['remaining_hp'] for e in damage] == [1, 1, 1]
    assert len(prompts) == 1
    assert not any(e.source_definition_id == FEATURE for e in engine.events)


def test_attached_packets_keep_individual_resistance_rounding(monkeypatch, tmp_path):
    from combat.gate2_runtime_models import DiceSpec
    from tests.h1_support import script
    def primary(ctx, dice):
        # Two critical d2s at their minimum give ten before Resistance.
        script(ctx.engine, [1] * 20)
        return DiceSpec(count=1, sides=2, modifier=8)
    install(monkeypatch, 'attack_damage', primary)
    def setup(engine):
        engine._add_modifier(engine.state.actors[TARGET], 'test:resistance', 'damage_resistance', 'SET',
                             'BLUDGEONING', 'SELF', expires_on='END_OF_HOLDER_NEXT_TURN')
    combat, table, mid = table_fight(monkeypatch, tmp_path, hp=100, gate='centerline',
                                     talents=[BREAKING], cl=13, setup=setup)
    args, result = attack(table, mid)
    assert result['status'] == 'COMMITTED', result
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (TARGET,)]
    pb = engine.state.actors[OWNER].proficiency_bonus
    assert [e.payload['rolled_or_pending_damage'] for e in damage] == [10, pb, pb]
    assert [e.payload['hp_damage'] for e in damage] == [5, pb // 2, pb // 2]
    assert [e.payload['remaining_hp'] for e in damage] == [95, 95 - pb // 2, 95 - 2 * (pb // 2)]
    assert len({e.payload['hit_roll_id'] for e in damage}) == 1


def test_foundation_origin_seizing_threshold_reads_settled_hit_hp(monkeypatch, tmp_path):
    from tests import test_a2_foundations_two as foundations
    from tests.worker2_support import OWNER as owner_id, FOE as foe_id, reload as load
    from combat.canonical import canonical_sha256
    from combat.gate2_runtime_models import DiceSpec
    from combat.ext import foundation_combat as foundation

    def aligned_strike(bundles):
        for action in bundles[0]['action_catalog']:
            typed = action.get('parameters', {}).get('typed', {})
            if any(row.get('type') == 'attack' and row.get('attack_kind') == 'unarmed'
                   for row in typed.get('effects', [])):
                typed['foundation_alignment'] = ['devour']
        bundles[2]['actor_template']['maximum_hp'] = 28
        for bundle in bundles:
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    install(monkeypatch, 'd20_result', lambda *args: {
        'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    install(monkeypatch, 'attack_damage', lambda ctx, dice: DiceSpec(count=1, sides=2, modifier=3))
    fixed_primary(monkeypatch, 3)
    combat, table, mid = foundations.table_fixture(tmp_path, 'devour',
        talents=['TAL_IRON_FIST_IRON_FIST_TRAINING', BREAKING], transform=aligned_strike)
    before = load(tmp_path, mid)
    start = len(before.events)
    foundations.use(combat, table, mid, 'Open the Gate: Breath-Checking Strike')
    strike = next(a.display_name for a in before.action_catalog.values()
                  if a.owner_id == owner_id and a.source_definition_id.endswith('.natural.iron_fist_sphere'))
    foundations.use(combat, table, mid, strike, foe_id)
    engine = load(tmp_path, mid)
    damage = [e for e in engine.events[start:] if e.event_type == 'DAMAGE_COMMITTED'
              and e.actor_id == owner_id and e.target_ids == (foe_id,)]
    threshold = engine.state.actors[foe_id].maximum_hp // 2
    assert len(damage) == 3
    assert damage[1].payload['remaining_hp'] >= threshold
    assert damage[-1].payload['remaining_hp'] < threshold
    grants = [e for e in engine.events[start:] if e.event_type == 'TEMP_HP_GRANTED' and e.actor_id == owner_id]
    assert len(grants) == 1 and grants[0].sequence > damage[-1].sequence
    assert engine.state.actors[owner_id].temporary_hp == foundation.values(engine, engine.state.actors[owner_id])[0]


def test_appraisal_and_heavying_packets_commit_as_on_main(monkeypatch):
    from tests import test_riders_c7 as c7
    spheres = {'sphere_record_ids': ['tianxia.sphere.iron_fist', 'tianxia.sphere.gravity'],
               'learned_talent_record_ids': ['TAL_IRON_FIST_IRON_FIST_TRAINING', 'TAL_GRAVITY_WEIGHT_SHIFT_BASE']}
    engine = c7.fight(c7.bundle([c7.EYES + 'calamity_appraisal'], spheres=spheres, cl=13), foe=c7._typed_foe())
    c7.answers(engine, {'calamity_appraisal': [c7.FOE]})
    c7.end_turns_until(engine, c7.FOE)
    c7.end_turns_until(engine, c7.ME)
    c7.use(engine, 'Weight Shift: Body Heavying')
    c7.use(engine, 'Open the Gate: Breath-Checking Strike')
    install(monkeypatch, 'd20_result', lambda *args: {
        'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    fixed_primary(monkeypatch, 3)
    events = c7.use(engine, c7.unarmed(engine), target=c7.FOE)
    damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (c7.FOE,)]
    # Main's measured packets (including the default accepted Gravity rider): the primary hit,
    # Weighted Strike's 3d6 Force (13 is its seeded roll, NOT Appraisal's printed +PB), then the
    # Appraisal +PB and Body Heavying +PB packets. Those two are identical on main and on this
    # branch (same source_definition_id, damage type and amount; no field names the producer),
    # so their relative order cannot be observed. This pins what can be: the four packets, one
    # source, and (new contract, last) one hit roll.
    assert [e.payload['damage_type'] for e in damage] == ['BLUDGEONING', 'FORCE', 'BLUDGEONING', 'BLUDGEONING']
    assert [e.payload['hp_damage'] for e in damage] == [3, 13, 5, 5]
    assert [e.payload['remaining_hp'] for e in damage] == [997, 984, 979, 974]
    assert len({e.source_definition_id for e in damage}) == 1
    assert len({e.payload['hit_roll_id'] for e in damage}) == 1


def test_attack_result_save_waits_for_appraisal_packet(monkeypatch):
    from tests import test_riders_c7 as c7
    spheres = {'sphere_record_ids': ['tianxia.sphere.berserker'],
               'learned_talent_record_ids': ['TAL_BERSERKER_MERIDIAN_RENDING_BLOW']}
    engine = c7.fight(c7.bundle([c7.EYES + 'calamity_appraisal'], spheres=spheres, cl=13,
                               items=['tianxia.mortal.weapon.jian']), foe=c7._typed_foe())
    c7.answers(engine, {'calamity_appraisal': [c7.FOE], 'berserker_meridian_rending': ['leg']})
    c7.end_turns_until(engine, c7.FOE)
    c7.end_turns_until(engine, c7.ME)
    install(monkeypatch, 'd20_result', lambda *args: {
        'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    strike = next(a.display_name for a in engine.action_catalog.values()
                  if a.owner_id == c7.ME and a.source_definition_id.endswith('.weapon.jian'))
    events = c7.use(engine, strike, target=c7.FOE)
    damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (c7.FOE,)]
    save = next(e for e in events if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id == damage[0].source_definition_id)
    assert len(damage) == 2 and max(e.sequence for e in damage) < save.sequence
    assert damage[-1].payload['hp_damage'] == engine.state.actors[c7.ME].proficiency_bonus


@pytest.mark.parametrize('placement', ['ordinary', 'rejected', 'custom'])
def test_mark_consequences_follow_only_actual_placement(monkeypatch, tmp_path, placement):
    from combat import ext
    from combat.typed_executor import block_mark, mark_condition_id
    mark = 'Test settlement mark'
    def declare(ctx, target, kind):
        block_mark(ctx, {'type': 'mark', 'mark': mark, 'duration': {'kind': 'until_end_of_next_turn'}})
    def reject(ctx, row, subject, expires, data):
        if row.get('mark') == mark and placement == 'rejected':
            return False
    def custom(ctx, row, subject, expires, data):
        if row.get('mark') == mark and placement == 'custom':
            ctx.engine._apply_condition(subject, mark_condition_id(mark, ctx.actor.entity_id),
                ctx.source, ctx.actor.entity_id, expires_on=expires, data=data)
            ext.run_strict('mark_applied', ctx, mark, subject)
            return True
    def observed(ctx, name, subject):
        if name == mark:
            assert any(c.condition_id == mark_condition_id(mark, ctx.actor.entity_id)
                       for c in subject.conditions.values())
            ctx.engine._append_event('PASSIVE_TRIGGERED', 'test:placed', actor_id=ctx.actor.entity_id,
                                     target_ids=(subject.entity_id,))
    install(monkeypatch, 'after_hit_choice', declare)
    install(monkeypatch, 'mark_pre_apply', reject)
    install(monkeypatch, 'mark_apply', custom)
    install(monkeypatch, 'mark_applied', observed)
    combat, table, mid = table_fight(monkeypatch, tmp_path, hp=100, gate='centerline', talents=[BREAKING])
    args, result = attack(table, mid)
    assert result['status'] == 'COMMITTED', result
    events = reload(tmp_path, mid).events
    notices = [e for e in events if e.source_definition_id == 'test:placed']
    assert len(notices) == (0 if placement == 'rejected' else 1)
    if notices:
        damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (TARGET,)]
        assert notices[0].sequence > max(e.sequence for e in damage)
