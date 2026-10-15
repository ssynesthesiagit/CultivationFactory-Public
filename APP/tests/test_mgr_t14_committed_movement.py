"""Native committed-action regressions for the eight-row movement lane."""
import pytest

from tests.worker2_support import fixture, turn, settle, candidate, reload, OWNER, ALLY, FOE

STEP = 'tianxia.subpath.qi.divination_cultivator.feature.predictive_step'


@pytest.mark.parametrize('cl,recipient', [(6, OWNER), (11, ALLY)])
def test_predictive_step_is_paid_after_the_visible_roll(tmp_path, cl, recipient):
    combat, table, mid = fixture(tmp_path, [STEP], cl=cl, named=True,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=recipient).candidate_id)
    engine = reload(tmp_path, mid)
    used = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == STEP]
    assert len(used) == 1
    assert used[0].target_ids == (recipient,)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == before - 2
    assert used[0].payload['ac_bonus'] == 3
    assert any('roll' in p.get('prompt', '').lower() or 'roll' in str(p).lower() for p in prompts)


@pytest.mark.parametrize('features,cl', [([], 11), ([STEP], 5)])
def test_predictive_step_is_inert_without_access(tmp_path, features, cl):
    combat, table, mid = fixture(tmp_path, features, cl=cl,
        foe_position={'x': 3, 'y': 5})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert not [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == STEP]


@pytest.mark.parametrize('cl,recipient,landing', [(6, OWNER, 'cell:2,6'), (11, ALLY, 'cell:4,8')])
def test_predictive_step_moves_before_reach_check_without_a_second_roll(tmp_path, cl, recipient, landing):
    combat, table, mid = fixture(tmp_path, [STEP], cl=cl, named=True,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    turn(table, mid, FOE)
    start = reload(tmp_path, mid)
    sequence = start.state.event_sequence
    before_hp = start.state.actors[recipient].current_hp
    before_budget = start.state.actors[recipient].movement_remaining_ft
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=recipient).candidate_id,
        picks={'choice:needle.predictive_step': 'protect', 'choice:needle.fact_admission.willing': 'accept',
               'choice:needle.predictive_step_landing': landing})
    engine = reload(tmp_path, mid)
    events = [e for e in engine.events if e.sequence > sequence]
    assert engine.state.actors[recipient].current_hp == before_hp
    assert engine.state.actors[recipient].movement_remaining_ft == before_budget
    assert len([e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE]) == 1
    assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == recipient for e in events)
    assert not [e for e in events if e.event_type == 'REACTION_RESOLVED' and 'opportunity' in e.source_definition_id]
    assert not [e for e in events if e.event_type == 'DAMAGE_COMMITTED']


def test_warn_another_declined_consent_spends_nothing(tmp_path):
    combat, table, mid = fixture(tmp_path, [STEP], cl=11,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    turn(table, mid, FOE)
    start = reload(tmp_path, mid).state.actors[OWNER]
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=ALLY).candidate_id,
        picks={'choice:needle.predictive_step': 'protect', 'choice:needle.fact_admission.willing': None})
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources == start.resources
    assert owner.reaction_available


def test_warn_another_human_consent_and_landing_on_ai_attacker_turn(tmp_path):
    from tests.r1i_service_support import force_ai_candidate
    combat, table, mid = fixture(tmp_path, [STEP], cl=11,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    turn(table, mid, FOE)
    attack = candidate(combat, mid, 'Unarmed Strike', target=ALLY)
    force_ai_candidate(combat, mid, FOE, attack.candidate_id)
    prompts = settle(table, mid, attack.candidate_id, auto=True,
        picks={'choice:needle.predictive_step': 'protect', 'choice:needle.fact_admission.willing': 'accept',
               'choice:needle.predictive_step_landing': 'cell:4,8'})
    for rid, chooser in [('choice:needle.predictive_step', OWNER),
                         ('choice:needle.fact_admission.willing', ALLY),
                         ('choice:needle.predictive_step_landing', ALLY)]:
        assert any(p['context']['reaction_source_id'] == rid and p['context']['reactor_id'] == chooser for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].position.y == 8


@pytest.mark.parametrize('cells,offered', [(6, True), (7, False)])
def test_warn_another_thirty_foot_boundary(tmp_path, cells, offered):
    arena = {'stable_id': 'step-boundary', 'width_squares': 20, 'height_squares': 12,
             'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    combat, table, mid = fixture(tmp_path, [STEP], cl=11, battlefield=arena,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 3 + cells, 'y': 6}, FOE: {'x': 3 + cells, 'y': 5}})
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=ALLY).candidate_id)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.predictive_step' for p in prompts) == offered
    reload(tmp_path, mid)


@pytest.mark.parametrize('cl', [6, 10])
def test_warn_another_requires_cl11(tmp_path, cl):
    combat, table, mid = fixture(tmp_path, [STEP], cl=cl,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=ALLY).candidate_id)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.predictive_step' for p in prompts)
    assert not [e for e in reload(tmp_path, mid).events if e.source_definition_id == STEP and e.event_type == 'REACTION_RESOLVED']


KNIFE = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.bi_shou', 'name': 'Bi Shou', 'quantity': 1}]}}


@pytest.mark.parametrize('skill', ['STR', 'DEX'])
def test_disarm_is_a_damage_free_weapon_contest_with_defender_choice(tmp_path, skill):
    combat, table, mid = fixture(tmp_path, ['BRUTE_BASE_BRUTE_MANEUVERS'], owner_kit=KNIFE,
        foe_kit=KNIFE, foe_position={'x': 3, 'y': 5}, seed='COMMITTED-DISARM-' + skill)
    before = reload(tmp_path, mid)
    hp = before.state.actors[FOE].current_hp
    choices = [c for c in before.legal_candidates() if c.target_ids == (FOE,)
               and c.display_name.startswith('Disarm (') and 'remaining' not in c.display_name]
    assert choices
    prompts = settle(table, mid, choices[0].candidate_id,
        picks={'choice:needle.brute_disarm_item': 'first', 'choice:needle.brute_disarm_skill': skill})
    engine = reload(tmp_path, mid)
    contest = next(e for e in reversed(engine.events) if e.payload.get('maneuver') == 'Disarm')
    assert contest.payload['target_skill'] == ('Athletics' if skill == 'STR' else 'Acrobatics')
    assert engine.state.actors[FOE].current_hp == hp
    assert not engine.state.actors[OWNER].action_available
    assert any(p['context']['reactor_id'] == FOE for p in prompts)
    from combat.ext.scoundrel_riders import held_possessions
    still_held = {i['object'] for i in held_possessions(engine, engine.state.actors[FOE])}
    assert (contest.payload['item'] not in still_held) == contest.payload['success']


def test_holding_with_two_hands_is_a_real_committed_choice(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_kit=KNIFE)
    engine = reload(tmp_path, mid)
    hold = next(c for c in engine.legal_candidates() if c.display_name.startswith('Hold ') and '2 hands' in c.display_name)
    settle(table, mid, hold.candidate_id)
    engine = reload(tmp_path, mid)
    from combat.ext.hand_occupancy import weapon_grips, free_hands
    assert list(weapon_grips(engine, engine.state.actors[OWNER]).values()) == [2]
    assert not free_hands(engine, engine.state.actors[OWNER])


@pytest.mark.parametrize('pb', [2, 5])
def test_warleader_sphere_acquisition_has_empty_pb_capacity(tmp_path, pb):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    doc = sheet(['WARLEADER_BASE_MOMENTUM_MARKS'])
    doc['spheres_and_talents']['automatic_sphere_component_record_ids'] = []
    doc['spheres_and_talents']['learned_talent_record_ids'] = []
    doc['identity']['proficiency_bonus'] = pb
    bundle = compile_character(doc, actor_id=OWNER)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert actor.resources['resource:named.momentum_mark'] == 0
    assert actor.resource_maximums['resource:named.momentum_mark'] == pb


def wrestler_bundle(*, extra=False):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    ids = ['WRESTLING_BASE_APPLYING_A_SLAM', 'TAL_WRESTLING_HAMMERLOCK']
    if extra:
        ids.append('tianxia.path.body_refining.feature.extra_attack')
    doc = sheet(ids, cl=18, primary='Stamina', key='STR', score=30)
    doc['identity']['path'] = 'Body Refining'
    return compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})


def holds(engine, target):
    return [c for c in engine.state.actors[target].conditions.values()
            if c.condition_id == 'condition:typed.grappled']


def test_remaining_attack_can_be_another_native_grapple(tmp_path):
    from tests.h1_support import sheet
    combat, table, mid = fixture(tmp_path, [], owner_bundle=wrestler_bundle(extra=True),
        foe_sheet=sheet([], score=10), foe_position={'x': 3, 'y': 5},
        ally_position={'x': 4, 'y': 6}, team_overrides={ALLY: 'team:b'})
    settle(table, mid, candidate(combat, mid, 'Grapple', target=FOE).candidate_id,
        picks={'choice:needle.save_choice': 'STR', 'choice:needle.grapple_part': 'hand:left'})
    first = reload(tmp_path, mid)
    assert len(holds(first, FOE)) == 1
    assert first.state.actors[OWNER].turn_flags['special_attack_rest'] == 1
    settle(table, mid, candidate(combat, mid, 'Grapple (remaining attack)', target=ALLY).candidate_id,
        picks={'choice:needle.save_choice': 'STR'})
    second = reload(tmp_path, mid)
    assert len(holds(second, ALLY)) == 1
    assert second.state.actors[OWNER].turn_flags['special_attack_rest'] == 0
    assert {c.data['grappling_part'] for t in [FOE, ALLY] for c in holds(second, t)} == {'hand:left', 'hand:right'}


def test_slam_establish_work_punish_and_release_are_native(tmp_path):
    from tests.h1_support import sheet
    combat, table, mid = fixture(tmp_path, [], owner_bundle=wrestler_bundle(),
        foe_sheet=sheet([], score=10), foe_position={'x': 3, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Grapple', target=FOE).candidate_id,
        picks={'choice:needle.save_choice': 'STR', 'choice:needle.grapple_part': 'hand:left'})
    assert len(holds(reload(tmp_path, mid), FOE)) == 1
    settle(table, mid, candidate(combat, mid, 'Apply a Slam: Hammerlock', target=FOE).candidate_id)
    first = reload(tmp_path, mid)
    assert any(c.data.get('hold') == 'hammerlock' for c in first.state.actors[FOE].conditions.values())
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Escape grapple').candidate_id,
        picks={'choice:needle.physical_escape_skill': 'STR', 'choice:needle.wrestling_punish': 'first'})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.wrestling_punish' for p in prompts)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Apply a Slam: Hammerlock', target=FOE).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Release grapple').candidate_id)
    final = reload(tmp_path, mid)
    assert not holds(final, FOE)
    assert not any(c.data.get('hold') == 'hammerlock' for c in final.state.actors[FOE].conditions.values())


def test_momentum_is_gained_by_an_actual_commanded_standard_benefit(tmp_path):
    combat, table, mid = fixture(tmp_path,
        ['WARLEADER_BASE_MOMENTUM_MARKS', 'WARLEADER_BASE_SET_THE_STANDARD'],
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 3, 'y': 5}})
    engine = reload(tmp_path, mid)
    standard = next(c for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog
        and any(e.get('type') == 'warleader_standard' for e in
                (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('effects', ())))
    settle(table, mid, standard.candidate_id)
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:named.momentum_mark'] == 1
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
             and e.payload.get('resource_id') == 'resource:named.momentum_mark']
    assert len(gains) == 1




def set_standard(combat, table, mid):
    engine = combat._load_session(mid).engine
    standard = next(c for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog
        and any(e.get('type') == 'warleader_standard' for e in
                (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('effects', ())))
    settle(table, mid, standard.candidate_id)


def test_momentum_help_uses_real_assistance_and_survives_reload(tmp_path):
    combat, table, mid = fixture(tmp_path,
        ['WARLEADER_BASE_MOMENTUM_MARKS', 'WARLEADER_BASE_SET_THE_STANDARD'],
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 3, 'y': 5}})
    set_standard(combat, table, mid)
    settle(table, mid, candidate(combat, mid, 'Help an ally attack', target=FOE).candidate_id,
        picks={'choice:needle.help_recipient': ALLY})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:named.momentum_mark'] == 1
    delivery = [e for e in engine.events if e.event_type == 'HELP_DELIVERED']
    assert len(delivery) == 1 and delivery[0].actor_id == OWNER and delivery[0].target_ids == (ALLY,)
    assert any(m.value == 'ADVANTAGE:' + FOE for m in engine.state.actors[ALLY].modifiers.values())


def test_momentum_objective_is_declared_before_the_actual_hit(tmp_path):
    combat, table, mid = fixture(tmp_path,
        ['WARLEADER_BASE_MOMENTUM_MARKS', 'WARLEADER_BASE_SET_THE_STANDARD'],
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 6, 'y': 6}, FOE: {'x': 3, 'y': 5}})
    settle(table, mid, candidate(combat, mid, 'Identify an objective', target=FOE).candidate_id,
        picks={'choice:needle.fact_admission.objective': 'visible'})
    engine = reload(tmp_path, mid)
    assert any(c.data.get('target') == FOE for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].resources['resource:named.momentum_mark'] == 0
    set_standard(combat, table, mid)
    # The target has no special defense or fabricated hit. Observe the actual
    # attack result; the gain must agree with the native hit/Standard receipt.
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'ATTACK_ROLLED' for e in engine.events)
    assert engine.state.actors[OWNER].resources['resource:named.momentum_mark'] == 1


def test_predictive_step_ac_is_scoped_to_one_attack_of_native_extra_attack(tmp_path):
    from tests.h1_support import sheet
    foe = sheet(['tianxia.path.body_refining.feature.extra_attack'], cl=18, primary='Stamina', key='STR')
    foe['identity']['path'] = 'Body Refining'
    combat, table, mid = fixture(tmp_path, [STEP], cl=11, foe_sheet=foe,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    turn(table, mid, FOE)
    seq = reload(tmp_path, mid).state.event_sequence
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=OWNER).candidate_id,
        picks={'choice:needle.predictive_step': 'protect', 'choice:needle.predictive_step_landing': 'cell:3,6'})
    engine = reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.sequence > seq and e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE]
    assert len(rolls) == 2
    assert rolls[0].payload['target_ac'] == rolls[1].payload['target_ac'] + 3
    assert len([p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.predictive_step']) == 1
    assert len([e for e in engine.events if e.sequence > seq and e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == STEP]) == 1


def test_wrestling_learning_choice_acquires_once_from_the_installed_sheet_then_plays(tmp_path):
    import json
    import zipfile
    from tests.h1_support import ROOT, sheet
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    source = 'WRESTLING_BASE_APPLYING_A_SLAM'
    docs = {OWNER: sheet([source], cl=18, primary='Stamina', key='STR', score=30),
            FOE: sheet([], cl=18, score=10)}
    docs[OWNER]['identity']['path'] = 'Body Refining'
    for aid, doc in docs.items():
        path = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        path.mkdir(parents=True)
        with zipfile.ZipFile(path / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    def cold():
        return CombatService(ROOT, tmp_path)
    state = cold().create_journey(project_ids=[a.removeprefix('actor:factory.') for a in docs],
        arena_id='battlefield:factory_pillar_arena', positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 3, 'y': 5}},
        base_paces={a: 3000 for a in docs})
    jid = state['journey_id']
    menu = cold().journey_source_choices(jid, OWNER, source)
    choice = next(o for o in menu['options'] if o['payload']['talent_id'] == 'TAL_WRESTLING_HAMMERLOCK')
    with pytest.raises(ValueError):
        cold().journey_acquire_source(jid, menu['revision'], OWNER, source, {'talent_id': 'TAL_WRESTLING_HEAVEN_LIFTING_THROW'})
    assert cold().journey_state(jid) == state
    state = cold().journey_acquire_source(jid, menu['revision'], OWNER, source, choice['payload'])
    assert any(e.get('event_type') == 'SOURCE_TALENT_LEARNED' or e.get('kind') == 'SOURCE_TALENT_LEARNED'
               for e in state['events'])
    assert cold().journey_source_choices(jid, OWNER, source)['options'] == []
    with pytest.raises(ValueError):
        cold().journey_acquire_source(jid, state['revision'], OWNER, source, choice['payload'])
    result = cold().journey_start_combat(jid, state['revision'], {OWNER: 'team:a', FOE: 'team:b'})
    mid = result['match_id']
    combat = cold()
    table = TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Grapple', target=FOE).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Apply a Slam: Hammerlock', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.data.get('hold') == 'hammerlock' for c in engine.state.actors[FOE].conditions.values())


EARTH = 'EARTH_BASE_SPENDING_A_BURDEN_MARK'
CLOD = 'EARTH_BASE_WEIGHT_SEEKING_CLOD'


def native_burden(combat, table, mid, tmp_path):
    from combat.typed_executor import bears_mark
    for _ in range(8):
        turn(table, mid, OWNER)
        settle(table, mid, candidate(combat, mid, 'Weight-Seeking Clod', target=FOE).candidate_id)
        engine = reload(tmp_path, mid)
        if bears_mark(engine.state.actors[FOE], OWNER, 'Burden Mark'):
            return
        turn(table, mid, FOE)
    raise AssertionError('No native Clod hit in eight attempts')


@pytest.mark.parametrize('cl,cut', [(6, 10), (11, 20)])
def test_anchor_waits_for_native_movement_then_persists_speed_until_turn_end(tmp_path, cl, cut):
    from combat.typed_executor import bears_mark
    combat, table, mid = fixture(tmp_path, [EARTH, CLOD], cl=cl,
        foe_position={'x': 3, 'y': 5})
    native_burden(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    assert bears_mark(before.state.actors[FOE], OWNER, 'Burden Mark')
    assert before._effective_speed(before.state.actors[FOE]) == 30
    move = next(c for c in before.legal_candidates() if c.kind == 'MOVE' and c.destination
                and (c.destination.x, c.destination.y) == (3, 4) and not c.destination.z
                and c.metadata.get('movement_mode', 'walk') == 'walk')
    prompts = settle(table, mid, move.candidate_id,
        picks={'choice:needle.earth_response': 'anchor', 'choice:needle.anchor_speed': 'walk'})
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[FOE]) == 30 - cut
    assert not bears_mark(engine.state.actors[FOE], OWNER, 'Burden Mark')
    assert any(p['context']['reaction_source_id'] == 'choice:needle.earth_response' for p in prompts)
    # The saved reduction remains after a different committed action this turn.
    settle(table, mid, candidate(combat, mid, 'Dodge').candidate_id)
    assert reload(tmp_path, mid)._effective_speed(reload(tmp_path, mid).state.actors[FOE]) == 30 - cut
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[FOE]) == 30


@pytest.mark.parametrize('accept', [True, False])
def test_shift_chooses_the_actual_willing_recipient_before_damage(tmp_path, accept):
    from combat.typed_executor import bears_mark
    combat, table, mid = fixture(tmp_path, [EARTH, CLOD], cl=11, owner_ac=1,
        foe_position={'x': 3, 'y': 5}, seed='NATIVE-SHIFT')
    native_burden(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    seq = before.state.event_sequence
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=OWNER).candidate_id,
        picks={'choice:needle.shift_recipient': ALLY, 'choice:needle.fact_admission.willing': 'accept' if accept else None,
               'choice:needle.earth_response': 'shift' if accept else None})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.fact_admission.willing'
               and p['context']['reactor_id'] == ALLY for p in prompts)
    amount = engine.state.actors[OWNER].proficiency_bonus + 2
    assert engine.state.actors[ALLY].temporary_hp == (amount if accept else 0)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Burden Mark') == (not accept)
    if accept:
        gained = next(e.sequence for e in engine.events if e.sequence > seq and e.event_type == 'TEMP_HP_GRANTED')
        damage = next(e.sequence for e in engine.events if e.sequence > seq and e.event_type == 'DAMAGE_COMMITTED')
        assert gained < damage


def test_settle_reduces_real_shove_and_offers_native_target_owned_step(tmp_path):
    from tests.h1_support import sheet
    foe = sheet([], cl=18, primary='Stamina', key='STR', score=30)
    foe['identity']['path'] = 'Body Refining'
    combat, table, mid = fixture(tmp_path, [EARTH, CLOD], cl=11, foe_sheet=foe,
        foe_position={'x': 3, 'y': 5}, seed='NATIVE-SETTLE')
    native_burden(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Shove: Push 5 ft', target=OWNER).candidate_id,
        picks={'choice:needle.save_choice': 'STR', 'choice:needle.earth_response': (None, 'settle'),
               'choice:needle.earth_settle_step': 'cell:2,6'})
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (2, 6)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.earth_settle_step'
               and p['context']['reactor_id'] == OWNER for p in prompts)
    assert not [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER
                and e.payload.get('teleport')]
