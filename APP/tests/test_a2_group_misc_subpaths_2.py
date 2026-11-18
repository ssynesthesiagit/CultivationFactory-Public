"""CombatService/table commits and disk reload for A2GMISSUB2's printed combat additions."""
import pytest

from combat.gate5_service import CombatService
from combat import senses, flight, typed_executor, ext
from combat.ext import exorcist as ex, mudang, yokai_channeler as yc
from combat.ext import mudang_ritual as gut
from combat.typed_executor import bears_mark
from tests.h1_support import ROOT
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.r1i_service_support import force_ai_candidate
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT, RIGHT, ALLY

SENSE = 'tianxia.path.spirit_awakening.feature.spiritual_sense'
SPIKE = 'tianxia.path.spirit_awakening.feature.mind_spike'


def reload(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def next_left(table, mid):
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    for _ in range(6):
        if table.state(mid)['menu']['actor_id'] == LEFT:
            return
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    raise AssertionError('left never received its next turn')


def choose_all(prompt):
    options = (prompt.get('choice') or {}).get('options') or []
    return (options[0]['id'] if options else None, True)


def prepared_gut(monkeypatch):
    original = CombatService.create_factory_match
    def create(service, *args, **kwargs):
        kwargs['prefight'] = {LEFT: ['setup-choice:gut_ritual_completed:1']}
        return original(service, *args, **kwargs)
    monkeypatch.setattr(CombatService, 'create_factory_match', create)


@pytest.mark.parametrize('prepared', [False, True])
def test_gut_requires_paid_completed_ritual_and_seals_anchor_through_service(tmp_path, monkeypatch, prepared):
    if prepared:
        prepared_gut(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [gut.GUT], primary='Resonance', ally_talents=[])
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[LEFT]
    obj = gut.anchor(engine, actor)
    assert bool(obj) is prepared
    assert actor.resources['resource:core.resonance'] == actor.resource_maximums['resource:core.resonance'] - (4 if prepared else 0)
    assert actor.resources[gut.RHYTHM] == 0
    assert actor.resource_maximums[gut.RHYTHM] == actor.proficiency_bonus
    if prepared:
        assert obj.ac == mudang.st.numbers(engine, actor)['save_dc']
        assert obj.current_hp == 5 * actor.proficiency_bonus
        assert set(obj.damage_immunities) == {'POISON', 'PSYCHIC'}
        commit(cast_sender(combat, table, mid, 'Dismiss Gut Circle'))
        engine = reload(tmp_path, mid)
        assert gut.anchor(engine, engine.state.actors[LEFT]) is None


@pytest.mark.parametrize('save', [1, 19])
def test_gut_petition_uses_real_rhythm_save_and_releases_on_attack_even_miss(tmp_path, monkeypatch, save):
    prepared_gut(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [gut.GUT, SPIKE], cl=15, primary='Resonance',
                                    ally_talents=[], foe_types=['Spirit'])
    rolls = [1] * 100
    fixed_dice(monkeypatch, rolls)
    commit(cast_sender(combat, table, mid, 'Mind Spike', target=RIGHT))
    next_left(table, mid)
    rolls[:] = [save] * 100
    commit(cast_sender(combat, table, mid, 'Pacification Petition', target=RIGHT))
    engine = reload(tmp_path, mid)
    target = engine.state.actors[RIGHT]
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and '.gut.petition' in e.source_definition_id]
    assert saves[-1].payload['natural_result'] == save
    assert any(c.condition_id == gut.PACIFIED for c in target.conditions.values()) is (save == 1)
    if save == 1:
        ctx = mudang.st.context(engine, target, mudang.st.feature_action(engine, target, SPIKE), [engine.state.actors[LEFT]])
        assert gut.no_petitioned_attacks(ctx, engine.state.actors[LEFT], {}) is False
        # A real attack roll emitted inside a committed action is sufficient;
        # hospitality ends on the attempt rather than requiring hit damage.
        def missed_attack(engine):
            engine._append_event('ATTACK_ROLLED', 'test:miss', actor_id=ALLY,
                                 target_ids=(RIGHT,), payload={'provisional_hit': False})
        on_hold(monkeypatch, missed_attack)
        assert act(table, mid, HOLD)['status'] == 'COMMITTED'
        engine = reload(tmp_path, mid)
        assert not any(c.condition_id == gut.PACIFIED for c in engine.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('answer,accepted,ally_mode', [
    ('accept', True, 'MANUAL'), ('refuse', False, 'MANUAL'), (None, True, 'LOCAL_AUTO')])
def test_gut_allied_player_controls_petition_consent_through_table_reload(tmp_path, monkeypatch, answer, accepted, ally_mode):
    prepared_gut(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [gut.GUT, SPIKE], cl=15, primary='Resonance', ally_talents=[],
                                    foe_types=['Spirit'], ally_types=['Spirit'])
    fixed_dice(monkeypatch, [1] * 100)
    commit(cast_sender(combat, table, mid, 'Mind Spike', target=RIGHT))
    next_left(table, mid)
    if ally_mode == 'LOCAL_AUTO':
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    petition_row = next(g for g in table.state(mid)['menu']['actions']
                        if g['source_definition_id'].endswith('gut.petition'))
    published_text = petition_row['description']
    assert all(text in published_text for text in (
        'Trance Rhythm', 'maximum equal to your Proficiency Bonus', 'move at least 10 feet during Spirit Dance',
        'until the start of your next turn', 'at the end of its turns',
        'defend, move and try to escape', 'An attack or ended hospitality releases it'))
    prompts = commit(cast_sender(combat, table, mid, 'Pacification Petition', target=ALLY),
                     lambda p: ((answer, True)))
    if ally_mode == 'MANUAL':
        assert prompts and 'accept Gut hospitality' in str(prompts)
    else:
        assert not prompts
    engine = reload(tmp_path, mid)
    guest = engine.state.actors[ALLY]
    held = next((c for c in guest.conditions.values() if c.condition_id == gut.PACIFIED), None)
    assert held is not None  # the 1 on a refusal follows the hostile save procedure
    if held:
        assert held.data['accepted_willingness'] is accepted
        assert held.expires_on == ('UNTIL_REMOVED' if accepted else 'START_OF_SOURCE_NEXT_TURN')


def test_gut_diagnosis_obtains_recipient_consent_and_withholds_equal_authority_details(tmp_path, monkeypatch):
    prepared_gut(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [gut.GUT], cl=15, primary='Resonance', ally_talents=[], foe_types=['Spirit'], ally_types=['Spirit'])
    def protected_condition(engine):
        target = engine.state.actors[ALLY]
        engine._apply_condition(target, 'condition:typed.concealed_guest', 'test:protected_guest', RIGHT,
                                expires_on='UNTIL_REMOVED', data={'source_cl': 15})
    on_hold(monkeypatch, protected_condition)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Gut: Public Diagnosis'),
           lambda p: ('accept', True))
    engine = reload(tmp_path, mid)
    diagnosis = [e for e in engine.events if e.source_definition_id == gut.GUT and 'Public Diagnosis of Ally' in str(e.payload)]
    log = next(str(e.payload['log']) for e in diagnosis if 'Public Diagnosis of Ally' in e.payload.get('log', ''))
    assert 'concealed guest detected' not in log.lower()
    assert 'contested' in log.lower()
    assert 'concealed guest' not in log.lower()


@pytest.mark.parametrize('source_mode,expected_reach', [('missing', False), ('action', False), ('equal', False), ('higher', False)])
def test_gut_concealment_uses_shared_source_authority_after_reload(tmp_path, monkeypatch, source_mode, expected_reach):
    prepared_gut(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [gut.GUT], cl=15, primary='Resonance', ally_talents=[], foe_types=['Spirit'])
    def conceal(engine):
        if source_mode == 'missing':
            source_id, source_def, data = 'unavailable-source', 'missing:action', {}
        elif source_mode == 'action':
            # Deliberately omit a matching source bundle so the resolver must
            # recover authority from this action's typed numbers.
            source_id = 'unavailable-bundle'
            action = next(a for a in engine.action_catalog.values()
                          if a.owner_id == ALLY and ((a.parameters or {}).get('typed') or {}).get('numbers', {}).get('cl'))
            source_def, data = action.source_definition_id, {}
        else:
            source_id, source_def = RIGHT, 'test:concealment'
            data = {'source_cl': 15 if source_mode == 'equal' else 20}
        engine._apply_condition(engine.state.actors[RIGHT], 'condition:typed.invisible', source_def, source_id,
                                expires_on='UNTIL_REMOVED', data=data)
    on_hold(monkeypatch, conceal)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    expected = expected_reach
    if source_mode == 'action':
        from combat.ext.condition_authority import source_cl
        condition = next(c for c in engine.state.actors[RIGHT].conditions.values()
                         if str(c.condition_id).rsplit('.', 1)[-1] == 'invisible')
        action_level = source_cl(engine, condition)
        assert action_level is not None
        expected = action_level < 15
    assert senses.perceives(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT]) is expected


def test_ghost_sight_reads_concealment_authority_from_source_actor_through_reload(tmp_path, monkeypatch):
    combat, table, mid = table_fight(tmp_path, [SENSE, ex.NAME], cl=6, primary='Resonance', ally_talents=[], foe_types=['Ghost'])
    def conceal(engine):
        caster = engine.state.actors[ALLY]
        action = next(a for a in engine.action_catalog.values() if a.owner_id == caster.entity_id and a.parameters.get('typed'))
        engine._apply_condition(engine.state.actors[RIGHT], 'condition:typed.invisible', action.source_definition_id, caster.entity_id,
                                expires_on='UNTIL_REMOVED', data={})
    on_hold(monkeypatch, conceal)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert senses.reach(engine, engine.state.actors[LEFT], 'spiritual_sense', engine.state.actors[RIGHT]) == 10


def test_gut_public_diagnosis_recipients_and_anchor_destruction_reload(tmp_path, monkeypatch):
    prepared_gut(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [gut.GUT], primary='Resonance', ally_talents=[], foe_types=['Spirit'])
    commit(cast_sender(combat, table, mid, 'Gut: Public Diagnosis'))
    engine = reload(tmp_path, mid)
    obj = gut.anchor(engine, engine.state.actors[LEFT])
    assert obj.component['diagnosed']
    diagnoses = [e for e in engine.events if e.source_definition_id == gut.GUT
                 and 'Public Diagnosis of' in str(e.payload)]
    assert {aid for e in diagnoses for aid in e.target_ids} == {LEFT, ALLY}
    assert all('Hit Points' not in str(e.payload) and 'Resistances:' not in str(e.payload) for e in diagnoses)
    assert not any(c.display_name == 'Gut: Public Diagnosis' for c in engine.legal_candidates())
    # Cold reload retains the focus; destroying that actual object ends the circle.
    def destroy(engine):
        owner = engine.state.actors[LEFT]
        obj = gut.anchor(engine, owner)
        engine._apply_condition(engine.state.actors[RIGHT], gut.PACIFIED, gut.GUT, LEFT,
                                expires_on='UNTIL_REMOVED', data={'accepted_willingness': True})
        engine._update_object(obj.model_copy(update={'current_hp': 0, 'destroyed': True}), 'test:destroy', RIGHT)
    on_hold(monkeypatch, destroy)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert gut.anchor(engine, engine.state.actors[LEFT]) is None
    assert not any(c.condition_id == gut.PACIFIED for c in engine.state.actors[RIGHT].conditions.values())
    assert not any(c.display_name == 'Pacification Petition' for c in engine.legal_candidates())


@pytest.mark.parametrize('repeat_roll', [1, 19])
def test_gut_repeat_save_and_next_source_turn_expiry_reload(tmp_path, monkeypatch, repeat_roll):
    prepared_gut(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [gut.GUT, SPIKE], cl=15, primary='Resonance',
                                    ally_talents=[], foe_types=['Spirit'])
    rolls = [1] * 100
    fixed_dice(monkeypatch, rolls)
    commit(cast_sender(combat, table, mid, 'Mind Spike', target=RIGHT))
    next_left(table, mid)
    commit(cast_sender(combat, table, mid, 'Pacification Petition', target=RIGHT))
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == gut.PACIFIED and c.data.get('repeat_save', {}).get('when') == 'end'
               for c in engine.state.actors[RIGHT].conditions.values())
    rolls[:] = [repeat_roll] * 100
    # Repeat save resolves before the source's next turn expiry.
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert table.state(mid)['menu']['actor_id'] == RIGHT
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    repeat_saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == gut.GUT]
    target_repeat = [e for e in repeat_saves if e.payload.get('actor_id') == RIGHT]
    assert target_repeat and target_repeat[-1].payload['natural_result'] == repeat_roll
    repeat_removals = [e for e in engine.events if e.event_type == 'CONDITION_REMOVED'
                       and e.payload.get('condition_id') == gut.PACIFIED and e.payload.get('repeat_save')]
    if repeat_roll == 19:
        # This event is emitted in END_OF_TURN resolution, before the source's next-turn expiry checkpoint.
        assert repeat_removals and repeat_removals[-1].payload.get('checkpoint') == 'END_OF_TURN'
    else:
        # Failed repeat saves do not remove the condition; source expiry may remove it later in this same commit.
        assert not repeat_removals
    assert combat._load_session(mid).mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('answer,accepted,mode', [('accept', True, 'MANUAL'), ('refuse', False, 'MANUAL'), (None, False, 'LOCAL_AUTO')])
def test_gut_opposing_player_consent_is_requested_and_respected(tmp_path, monkeypatch, answer, accepted, mode):
    prepared_gut(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [gut.GUT, SPIKE], cl=15, primary='Resonance', ally_talents=[], foe_types=['Spirit'])
    fixed_dice(monkeypatch, [1] * 100)
    commit(cast_sender(combat, table, mid, 'Mind Spike', target=RIGHT))
    next_left(table, mid)
    if mode == 'LOCAL_AUTO':
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode='LOCAL_AUTO')
    else:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode='MANUAL')
    prompts = commit(cast_sender(combat, table, mid, 'Pacification Petition', target=RIGHT), lambda p: (answer, True))
    if mode == 'MANUAL':
        assert prompts and 'accept Gut hospitality' in str(prompts)
    else:
        assert not prompts
    held = next(c for c in reload(tmp_path, mid).state.actors[RIGHT].conditions.values() if c.condition_id == gut.PACIFIED)
    assert held.data['accepted_willingness'] is accepted
    assert held.expires_on == ('UNTIL_REMOVED' if accepted else 'START_OF_SOURCE_NEXT_TURN')


def test_gut_pacification_removes_real_attack_candidates_on_guest_turn(tmp_path, monkeypatch):
    prepared_gut(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [gut.GUT, SPIKE], cl=15, primary='Resonance',
                                    ally_talents=[], foe_types=['Spirit'])
    fixed_dice(monkeypatch, [1] * 100)
    commit(cast_sender(combat, table, mid, 'Mind Spike', target=RIGHT))
    next_left(table, mid)
    commit(cast_sender(combat, table, mid, 'Pacification Petition', target=RIGHT))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert table.state(mid)['menu']['actor_id'] == RIGHT
    engine = reload(tmp_path, mid)
    guest = engine.state.actors[RIGHT]
    assert any(c.condition_id == gut.PACIFIED for c in guest.conditions.values())
    candidates = engine.legal_candidates()
    attacks = [c for c in candidates if str(getattr(c.kind, 'value', c.kind)).upper() == 'ATTACK']
    assert not attacks, [(c.kind, c.display_name, c.source_definition_id) for c in candidates]


def test_gut_revealed_guest_and_diagnostic_advantage_are_perceived_after_reload(tmp_path, monkeypatch):
    prepared_gut(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [gut.GUT], cl=15, primary='Resonance',
                                    ally_talents=[], foe_types=['Ghost'])
    def conceal(engine):
        engine._apply_condition(engine.state.actors[RIGHT], 'condition:typed.invisible', 'test:weak_concealment', RIGHT,
                                expires_on='UNTIL_REMOVED', data={'source_cl': 1})
    on_hold(monkeypatch, conceal)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    owner, ghost = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert senses.perceives(engine, owner, ghost)
    assert typed_executor.check_mode(owner, 'WIS', 'Insight', engine=engine, against_creature=ghost) == 'ADVANTAGE'
    outsider = engine.state.actors[ALLY]
    assert typed_executor.check_mode(owner, 'WIS', 'Insight', engine=engine, against_creature=outsider) != 'ADVANTAGE'


def test_gut_petition_measures_range_from_focus_after_caster_moves(tmp_path, monkeypatch):
    from combat.gate2_runtime_models import Position
    prepared_gut(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [gut.GUT, SPIKE], cl=15, primary='Resonance',
                                    ally_talents=[], foe_types=['Spirit'])
    fixed_dice(monkeypatch, [1] * 100)
    commit(cast_sender(combat, table, mid, 'Mind Spike', target=RIGHT))
    def positions(engine):
        engine.state.actors[LEFT].position = Position(x=0, y=0)
        engine.state.actors[RIGHT].position = Position(x=11, y=7)
    on_hold(monkeypatch, positions)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    next_left(table, mid)
    engine = reload(tmp_path, mid)
    owner, spirit = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert engine._distance_actor_to_actor(owner, spirit) > 50
    assert gut.inside(engine, owner, spirit)
    commit(cast_sender(combat, table, mid, 'Pacification Petition', target=RIGHT))
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == gut.PACIFIED for c in engine.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('kind,expected,conceal_cl', [('Ghost', 60, 1), ('Humanoid', 10, 1), ('Intruder', 10, 1), ('Ghost', 10, 6)])
def test_ghost_sight_is_limited_to_printed_kinds_through_service(tmp_path, monkeypatch, kind, expected, conceal_cl):
    combat, table, mid = table_fight(tmp_path, [SENSE, ex.NAME], cl=6, primary='Resonance', foe_types=[kind],
                                    ally_talents=[], starts={'team1': [[1, 4], [1, 5]], 'team2': [[9, 4]]})
    def hide(engine):
        engine._apply_condition(engine.state.actors[RIGHT], 'condition:typed.invisible', 'test:conceal', RIGHT,
                                expires_on='UNTIL_REMOVED', data={'source_cl': conceal_cl})
    on_hold(monkeypatch, hide)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    viewer, seen = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert senses.reach(engine, viewer, 'spiritual_sense', seen) == expected
    assert senses.perceives(engine, viewer, seen) is (expected == 60)
    assert senses.reach(engine, viewer, 'spiritual_sense', seen, unrestricted_only=True) == 10
    assert senses.reach(engine, viewer, 'spiritual_sense', senses.cell_probe(seen.position)) == 0


@pytest.mark.parametrize('roll', [1, 19])
def test_name_intruder_marks_immediately_or_after_concealment_and_reloads(tmp_path, monkeypatch, roll):
    combat, table, mid = table_fight(tmp_path, [SENSE, ex.NAME], cl=6, primary='Resonance', foe_types=['Intruder'], ally_talents=[])
    fixed_dice(monkeypatch, [roll] * 100)
    before = combat._load_session(mid).engine.state.actors[LEFT].resources['resource:core.resonance']
    commit(cast_sender(combat, table, mid, 'Ghost Sight and Name the Intruder', target=RIGHT))
    engine = reload(tmp_path, mid)
    assert all(hook.__name__ != 'concealed_resonance_mark' for hook in ext._HOOKS.get('masked_conditions', ()))
    assert engine.state.actors[LEFT].resources['resource:core.resonance'] == before - 1
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Resonance')
    assert any(c.condition_id == ex.LATENT_MARK for c in engine.state.actors[RIGHT].conditions.values()) is (roll == 19)
    condition_rows = {row['condition_id']: row for actor in combat.presentation(mid, feed=False)['actors']
                      if actor['entity_id'] == RIGHT for row in actor['conditions']}
    resonance_id = typed_executor.mark_condition_id('Resonance', LEFT)
    if roll == 19:
        assert condition_rows[resonance_id]['hidden'] is True
        assert condition_rows[ex.LATENT_MARK]['hidden'] is True
        assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Resonance')  # mechanical queries still see it
    else:
        assert condition_rows[resonance_id]['hidden'] is False
    next_left(table, mid)
    engine = reload(tmp_path, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Resonance')
    assert not any(c.condition_id == ex.LATENT_MARK for c in engine.state.actors[RIGHT].conditions.values())
    revealed = {row['condition_id']: row for actor in combat.presentation(mid, feed=False)['actors']
                if actor['entity_id'] == RIGHT for row in actor['conditions']}
    assert revealed[resonance_id]['hidden'] is False


@pytest.mark.parametrize('kind,use', [('Ghost', True), ('Ghost', False), ('Humanoid', True)])
def test_native_banishment_after_real_mind_spike_has_exact_optional_cost(tmp_path, monkeypatch, kind, use):
    combat, table, mid = table_fight(tmp_path, [SPIKE, ex.BANISH], cl=6, primary='Resonance', foe_types=[kind], ally_talents=[])
    fixed_dice(monkeypatch, [1] * 100)
    before = combat._load_session(mid).engine.state.actors[LEFT].resources['resource:core.resonance']
    prompts = commit(cast_sender(combat, table, mid, 'Mind Spike', target=RIGHT),
                     lambda p: (None, use) if p['reaction'] == 'Banishment Strike' else (None, False))
    engine = reload(tmp_path, mid)
    target = engine.state.actors[RIGHT]
    expected = kind == 'Ghost' and use
    assert any(c.condition_id == 'condition:typed.frightened' for c in target.conditions.values()) is expected
    source_saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == ex.BANISH]
    assert bool(source_saves) is expected
    spike = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.display_name == 'Mind Spike')
    assert engine.state.actors[LEFT].resources['resource:core.resonance'] == before - dict(spike.costs).get('resource:core.resonance', 0) - (2 if expected else 0)
    assert any(p['reaction'] == 'Banishment Strike' for p in prompts) is (kind == 'Ghost')
    if kind == 'Ghost':
        prompt = next(p for p in prompts if p['reaction'] == 'Banishment Strike')
        prompt_text = str(prompt)
        assert 'failed its save against your Mind Spike' in prompt_text
        assert 'Charisma saving throw' in prompt_text
        assert all(text in prompt_text for text in ('2 Resonance', 'Cultivation Save DC', 'Frightened', '1 minute',
                                                     'repeats the save', 'Spiritual Pressure', 'exposed to your sight'))


def test_banishment_successful_save_applies_pressure_and_exposure_through_cold_reload(tmp_path, monkeypatch):
    combat, table, mid = table_fight(tmp_path, [SPIKE, ex.BANISH], cl=6, primary='Resonance',
                                    foe_types=['Ghost'], ally_talents=[])
    # Mind Spike fails (1); Banishment Strike succeeds (19).
    fixed_dice(monkeypatch, [1, 19] + [1] * 100)
    prompts = commit(cast_sender(combat, table, mid, 'Mind Spike', target=RIGHT),
                     lambda p: (None, True) if p['reaction'] == 'Banishment Strike' else (None, False))
    engine = reload(tmp_path, mid)
    target = engine.state.actors[RIGHT]
    assert any(p['reaction'] == 'Banishment Strike' for p in prompts)
    banish_saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == ex.BANISH]
    assert len(banish_saves) == 1 and banish_saves[0].payload['success'] is True
    assert not any(c.condition_id == 'condition:typed.frightened' for c in target.conditions.values())
    pressure = [c for c in target.conditions.values() if c.data.get('label', '').startswith('Spiritual Pressure:')
                and c.source_actor_id == LEFT]
    assert pressure
    exposure = [c for c in target.conditions.values() if c.condition_id == 'condition:typed.exposed.hidden.you'
                and c.source_actor_id == LEFT]
    assert len(exposure) == 1
    assert exposure[0].data['against'] == 'you'
    assert exposure[0].expires_on == 'START_OF_SOURCE_NEXT_TURN'
    assert combat._load_session(mid).mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('repeat_roll', [1, 19])
def test_banishment_failed_save_repeat_saves_and_minute_expiry_survive_service_reload(tmp_path, monkeypatch, repeat_roll):
    combat, table, mid = table_fight(tmp_path, [SPIKE, ex.BANISH], cl=6, primary='Resonance',
                                    foe_types=['Ghost'], ally_talents=[])
    rolls = [1] * 100
    fixed_dice(monkeypatch, rolls)
    commit(cast_sender(combat, table, mid, 'Mind Spike', target=RIGHT),
           lambda p: (None, True) if p['reaction'] == 'Banishment Strike' else (None, False))
    engine = reload(tmp_path, mid)
    target = engine.state.actors[RIGHT]
    held = next(c for c in target.conditions.values() if c.condition_id == 'condition:typed.frightened')
    assert {key: held.data['repeat_save'][key] for key in ('ability', 'when')} == {'ability': 'cha', 'when': 'end'}
    assert held.data['repeat_save']['dc'] == 16
    assert held.expires_on.startswith('START_OF_SLOT_AT:')

    # End the source turn and ally turn so the affected Ghost gets its repeat save.
    rolls[:] = [repeat_roll] * 100
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    if table.state(mid)['menu']['actor_id'] != RIGHT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
        engine = reload(tmp_path, mid)
    assert table.state(mid)['menu']['actor_id'] == RIGHT
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    repeat_saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == ex.BANISH
                    and e.payload.get('actor_id') == RIGHT]
    assert repeat_saves and repeat_saves[-1].payload['natural_result'] == repeat_roll
    removed_by_repeat = [e for e in engine.events if e.event_type == 'CONDITION_REMOVED'
                         and e.payload.get('condition_id') == 'condition:typed.frightened'
                         and e.payload.get('repeat_save')]
    if repeat_roll == 19:
        assert removed_by_repeat and held.instance_id not in engine.state.actors[RIGHT].conditions
        assert combat._load_session(mid).mechanical.replay()['status'] == 'PASS'
        return
    assert not removed_by_repeat
    assert held.instance_id in engine.state.actors[RIGHT].conditions

    # A minute is ten complete rounds. Drive real table turn commits until that
    # saved expiry token is due; reload/replay after every committed turn.
    for _ in range(44):
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
        engine = reload(tmp_path, mid)
        if held.instance_id not in engine.state.actors[RIGHT].conditions:
            break
    assert held.instance_id not in engine.state.actors[RIGHT].conditions
    assert any(e.event_type == 'CONDITION_REMOVED' and e.payload.get('instance_id') == held.instance_id
               for e in engine.events)
    assert combat._load_session(mid).mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('source', [ex.BELL, ex.GRAND])
@pytest.mark.parametrize('foe_kind', ['Intruder', 'Possession Entity', 'Possessing Entity'])
def test_exorcist_multi_recipient_harm_to_foes_and_purification_to_allies_including_self(tmp_path, monkeypatch, source, foe_kind):
    combat, table, mid = table_fight(tmp_path, [source], primary='Resonance', foe_types=[foe_kind], ally_talents=[])
    def fear(engine):
        for aid in (LEFT, ALLY, RIGHT):
            engine._apply_condition(engine.state.actors[aid], 'condition:typed.frightened', 'test:fear', RIGHT, expires_on='UNTIL_REMOVED')
    on_hold(monkeypatch, fear)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    next_left(table, mid)
    fixed_dice(monkeypatch, [1] * 200)
    before = {aid: combat._load_session(mid).engine.state.actors[aid].current_hp for aid in (LEFT, ALLY, RIGHT)}
    name = 'Purification Bell' if source == ex.BELL else 'Grand Exorcism'
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    force_ai_candidate(combat, mid, LEFT, candidate.candidate_id)
    commit(lambda answers=(): table.auto_step(mid, 0, list(answers)), choose_all)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[RIGHT].current_hp < before[RIGHT]
    for aid in (LEFT, ALLY):
        assert engine.state.actors[aid].current_hp == before[aid]
        assert not any(c.condition_id == 'condition:typed.frightened' for c in engine.state.actors[aid].conditions.values())
    assert any(c.condition_id == 'condition:typed.frightened' for c in engine.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('source', [yc.TRUE_FORM, yc.LORD])
@pytest.mark.parametrize('lineage,speed,hover', [('kitsune', 40, True), ('tengu', 50, False), ('kappa', 0, False)])
def test_true_form_and_lord_grant_printed_native_flight_and_reload(tmp_path, source, lineage, speed, hover):
    combat, table, mid = table_fight(tmp_path, [yc.MASK, source], primary='Resonance', ally_talents=[])
    commit(cast_sender(combat, table, mid, 'Yokai Lineage: ' + lineage.title()))
    commit(cast_sender(combat, table, mid, 'Yokai Lord' if source == yc.LORD else 'True Yokai Form'), choose_all)
    engine = reload(tmp_path, mid)
    profile = flight.profile(engine, engine.state.actors[LEFT])
    assert (profile.speed_ft, profile.hover) == (speed, hover)


def test_tengu_mask_reduces_actual_fall_before_damage_and_reloads(tmp_path, monkeypatch):
    from combat.gate2_runtime_models import Position
    combat, table, mid = table_fight(tmp_path, [yc.MASK], primary='Resonance', ally_talents=[])
    commit(cast_sender(combat, table, mid, 'Yokai Lineage: Tengu'))
    def raise_actor(engine):
        engine.state.actors[LEFT].position = Position(x=3, y=4, z=10)
    on_hold(monkeypatch, raise_actor)
    fixed_dice(monkeypatch, [1] * 100)
    commit(cast_sender(combat, table, mid, 'Hold position'))
    engine = reload(tmp_path, mid)
    assert engine.state.actors[LEFT].position.z == 0
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and LEFT in e.target_ids]
    assert damage and sum(e.payload['hp_damage'] for e in damage) == 1  # 50-foot fall - 4*10 = one d6


def test_watchful_guest_adds_sense_range_and_scoped_perception_after_reload(tmp_path, monkeypatch):
    combat, table, mid = table_fight(tmp_path, [SENSE, SPIKE, mudang.DANCE, mudang.TRANCE], cl=6,
                                    primary='Resonance', ally_talents=[], foe_types=['Spirit'])
    fixed_dice(monkeypatch, [1] * 100)
    commit(cast_sender(combat, table, mid, 'Mind Spike', target=RIGHT))  # gain real Trance Rhythm
    commit(cast_sender(combat, table, mid, 'Possession Trance: Watchful Guest'))
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[LEFT]
    assert 'resource:named.trance_rhythm' in owner.resource_maximums
    assert senses.reach(engine, owner, 'spiritual_sense', engine.state.actors[RIGHT]) == 20
    assert typed_executor.check_mode(owner, 'WIS', 'Perception', engine=engine, against_creature=engine.state.actors[RIGHT]) == 'ADVANTAGE'
    assert typed_executor.check_mode(owner, 'WIS', 'Perception', engine=engine, against_creature=engine.state.actors[ALLY]) != 'ADVANTAGE'
