"""Thread service/session/cold reload verification; no bare-engine execution."""
import pytest
from combat import flight
from combat.gate5_service import CombatService
from combat.ext.thread_second_pass import LOCK, NET, SILK, CROWD, REEL, PASSAGE, FOCUS
from tests.h1_support import ROOT
from tests.test_r4_integration import reach, send, candidate, auto_candidate, P, F, S
from tests.h1_support import sheet
from combat.factory_compiler import compile_character
from combat.tabletop_service import TabletopService
from combat.tabletop import normalize_map, to_battlefield
import json, zipfile
from combat.gate2_runtime_models import TerminalKind
from tests.cw2_service_support import add_action, seal
QI = 'resource:core.qi'


def fixture(tmp_path, mids, *, second=(), foe_score=14, configure=None, elevated=False, corridor=False, foe_x=6, foe_altitude=2, platform=False, caster_altitude=0, caster_id=P, foe_skills=None, foe_mids=(), foe_resources=(), control_modes=None, second_enemy=False, starting_positions=None, caster_dc=50, caster_primary="Qi"):
    docs = [sheet(mids, cl=20, dc=caster_dc, primary=caster_primary), sheet(foe_mids, cl=20, score=foe_score), sheet(second, cl=20)]
    if foe_resources:
        docs[1]['ability_scores_and_statistics']['primary_resource']['definitions'] = list(foe_resources)
    if foe_skills is not None:
        docs[1]['ability_scores_and_statistics']['skills'] = [{'skill': k, 'bonus': v} for k, v in foe_skills.items()]
    ids = [caster_id, F, S] if second else [caster_id, F]
    bundles = []
    for aid, doc in zip(ids, docs):
        doc['identity']['display_name'] = aid.rsplit('-', 1)[-1]
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 2000
        doc['ability_scores_and_statistics']['technique_attack_bonus'] = 1000
        doc['equipment'] = [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'quantity': 1}]}}]
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        b = compile_character(doc, actor_id=aid, reaction_plan={'ask': True} if second_enemy else None)
        bundles.append(b)
    if configure:
        configure(bundles)
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    walls = [{'shape': 'rect', 'points': [[0, 1], [8, 8]], 'filled': True}] if corridor else []
    if platform:
        walls.append({'shape': 'rect', 'points': [[6, 6], [7, 7]], 'filled': True, 'height_ft': 10})
    arena = to_battlefield(normalize_map({'width_squares': 9, 'height_squares': 9, 'walls': walls}))
    positions = {caster_id: {'x': 3, 'y': 0 if corridor else 6, 'z': caster_altitude}, F: {'x': foe_x, 'y': 0 if corridor else 6, 'z': foe_altitude if elevated else 0},
                 S: {'x': 5, 'y': 7, 'z': 2 if elevated else 0}}
    positions.update(starting_positions or {})
    mid = service._finish_factory_match(bundles, ids, {caster_id: 'team:a', S: 'team:b' if second_enemy else 'team:a', F: 'team:b'},
        positions, arena, [i for i in ids if i != F], [F],
        match_seed='A2THREAD', display_name='Thread second pass', maximum_rounds=15,
        control_modes=control_modes or {i: 'MANUAL' for i in ids})['match_id']
    return service, table, mid


def cold(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert not [e for e in loaded.engine.events if e.event_type == 'GM_RIDER' and 'failed:' in str(e.payload)]
    assert not [e for e in loaded.engine.events if e.event_type == 'GM_RIDER'
                and any(mid in e.source_definition_id for mid in (LOCK, NET, 'insight.silk-reeling-foundation'))]
    return loaded.engine


def single_reviewed_record(mid):
    files = [ROOT / 'authority/typed_mechanics/reviewed_final.json',
             *sorted((ROOT / 'authority/typed_mechanics/reviewed_final.d').glob('*.json'))]
    owners = [p.name for p in files if mid in json.loads(p.read_text()).get('mechanics', {})]
    assert len(owners) == 1, (mid, owners)


def settle(table, mid, cid, *, pick=None, decline=False):
    answers = []
    for _ in range(12):
        result = send(table, mid, cid, answers)
        if result['status'] == 'COMMITTED':
            return result
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        opts = [o['id'] for o in p.get('choice', {}).get('options', [])]
        answer = {**p['context'], 'selection': 'DECLINE' if decline else 'USE',
                  'option_ids': [] if decline else [pick if pick in opts else opts[0]] if opts else []}
        answers.append(answer)
    raise AssertionError('too many choices')


def draw(table, mid):
    settle(table, mid, candidate(table, mid, 'Draw the Line: Guide', F), decline=True)


@pytest.mark.parametrize('success', [False, True])
def test_meridian_lock_save_restriction_and_cold_reload(tmp_path, success):
    def configure(bundles):
        b = bundles[1]
        add_action(b, 'Paid escape movement', [{'type': 'movement', 'applies_to': 'self', 'distance_ft': 5}], target='SELF')
        b['action_catalog'][-1]['costs'] = [[QI, 1]]
        for name, pool, amount in [('Inline CP escape', QI, 1), ('Zero CP escape', QI, 0), ('Focus escape', FOCUS, 1)]:
            add_action(b, name, [{'type': 'spend_resource', 'resource_id': pool, 'flat': amount, 'applies_to': 'self'},
                                {'type': 'remove_condition', 'condition': 'restrained', 'applies_to': 'self'}], target='SELF')
        seal(b)
    combat, table, mid = fixture(tmp_path, [LOCK], foe_score=500 if success else 2, configure=configure, foe_x=8, foe_mids=[CROWD, SILK])
    reach(table, mid, P)
    assert not [c for c in cold(tmp_path, mid).legal_candidates() if c.display_name == 'Meridian Lock']
    settle(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread)', F), decline=True)
    reach(table, mid, F)
    reach(table, mid, P)
    before = cold(tmp_path, mid).state.actors[P].resources[QI]
    settle(table, mid, candidate(table, mid, 'Meridian Lock', F))
    e = cold(tmp_path, mid)
    assert e.state.actors[P].resources[QI] == before - 3
    held = [c for c in e.state.actors[F].conditions.values() if c.data.get('thread_meridian_lock') == 1]
    assert bool(held) == (not success)
    if held:
        assert held[0].data['repeat_save']['dc'] == 50
        assert held[0].expires_on != 'END_OF_CURRENT_TURN'
    reach(table, mid, F)
    e = cold(tmp_path, mid)
    names = {c.display_name for c in e.legal_candidates()}
    assert ('Paid escape movement' in names) == success
    assert ('Inline CP escape' in names) == success
    assert {'Zero CP escape', 'Focus escape', 'Silk Step'} <= names
    # Extension-defined passage is a movement technique without a built-in
    # movement effect. Free movement remains available under Meridian Lock.
    assert ('Thread Through the Crowd' in names) == success
    before_qi = e.state.actors[F].resources[QI]
    if success:
        settle(table, mid, candidate(table, mid, 'Thread Through the Crowd'))
        e = cold(tmp_path, mid)
        assert e.state.actors[F].resources[QI] == before_qi - 1
        assert any(c.condition_id == PASSAGE and c.data.get('crowd') == 1
                   for c in e.state.actors[F].conditions.values())
    else:
        settle(table, mid, candidate(table, mid, 'Silk Step'))
        e = cold(tmp_path, mid)
        assert e.state.actors[F].resources[QI] == before_qi
        assert not any(c.condition_id == PASSAGE and c.data.get('crowd') == 1
                       for c in e.state.actors[F].conditions.values())
    if success:
        assert e._effective_speed(e.state.actors[F]) == 15
    single_reviewed_record(LOCK)


@pytest.mark.parametrize('success', [False, True])
@pytest.mark.parametrize('payment', ['qi', 'stamina'])
def test_meridian_lock_owned_echoing_step_payment_and_reload(tmp_path, success, payment):
    echo = 'tianxia.talent.music.echoing_step'
    combat, table, mid = fixture(tmp_path, [LOCK], foe_score=500 if success else 2,
                                foe_x=8, foe_mids=[echo], foe_resources=[{'name': 'Stamina', 'maximum': 30}])
    reach(table, mid, P)
    settle(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread)', F), decline=True)
    reach(table, mid, F)
    reach(table, mid, P)
    settle(table, mid, candidate(table, mid, 'Meridian Lock', F))
    reach(table, mid, F)
    e = cold(tmp_path, mid)
    # Both Qi and Stamina are cultivation-point pools. The lock prohibits
    # purchasing either version; it does not prohibit free/Focus controls.
    pool = QI if payment == 'qi' else 'resource:core.stamina'
    def offers(engine):
        return [c for c in engine.legal_candidates()
                if c.source_definition_id in engine.action_catalog
                and any(row.get('type') == 'echoing_step' for row in
                        engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('effects', []))
                and (pool, 1) in engine.action_catalog[c.source_definition_id].costs]
    choices = offers(e)
    assert bool(choices) == success
    before = dict(e.state.actors[F].resources)
    if choices:
        settle(table, mid, choices[0].candidate_id)
        e = cold(tmp_path, mid)
        assert e.state.actors[F].resources[pool] == before[pool] - 1
        other_pool = 'resource:core.stamina' if payment == 'qi' else QI
        assert e.state.actors[F].resources[other_pool] == before[other_pool]
        assert e.state.actors[F].turn_flags.get('echoing_step') is True
    else:
        assert not e.state.actors[F].turn_flags.get('echoing_step')
        assert dict(e.state.actors[F].resources) == before
    single_reviewed_record(echo)


@pytest.mark.parametrize('ai_owner', [False, True])
@pytest.mark.parametrize('success,speed,hover', [(False, 30, False), (False, 30, True), (True, 30, False), (True, 20, False)])
def test_heaven_net_fall_hover_success_both_teams_and_reload(tmp_path, success, speed, hover, ai_owner):
    def configure(bundles):
        for b in bundles[1:]:
            # Native actor flight is sealed in genesis; altitude is obtained
            # using a real service movement before the cast.
            b['actor_template'].update(fly_speed_ft=speed, hover=hover)
            seal(b)
    combat, table, mid = fixture(tmp_path, [NET], second=[SILK], foe_score=500 if success else 2, configure=configure, elevated=True)
    reach(table, mid, P)
    e = combat._load_session(mid).engine
    casts = [c for c in e.legal_candidates() if 'Heaven-Net Casting' in c.display_name and c.destination.x == 4 and c.destination.y == 6 and c.destination.z == 0]
    assert casts
    before = e.state.actors[P].resources[QI]
    if ai_owner:
        auto_candidate(combat, mid, P, casts[0].candidate_id)
        assert table.auto_step(mid, 0)['status'] == 'COMMITTED'
        combat.set_controller_mode(mid, actor_id=P, controller_mode='MANUAL')
    else:
        settle(table, mid, casts[0].candidate_id)
    e = cold(tmp_path, mid)
    assert e.state.actors[P].resources[QI] == before - 6
    for aid in [F, S]:
        saves = [r for r in e.rolls if r.actor_id == aid and r.reason.startswith('SAVE:') and 'heaven_net' in r.reason]
        assert saves
        saved = saves[-1].total >= 50
        expected = max(0, speed - 20) if saved else 0
        assert flight.profile(e, e.state.actors[aid]).speed_ft == expected
        assert e.state.actors[aid].position.z == (2 if hover or expected else 0)
    single_reviewed_record(NET)
    reach(table, mid, F)
    e = cold(tmp_path, mid)
    assert flight.profile(e, e.state.actors[F]).speed_ft == speed
    if e.state.actors[F].position.z == 2:
        moves = [c for c in e.legal_candidates() if c.kind.value == 'MOVE' and c.destination.x == 7 and c.destination.y == 6 and c.destination.z == 2]
        assert moves and min(c.movement_cost_ft for c in moves) == 5


@pytest.mark.parametrize('source,name', [(SILK, 'Silk Step'), (CROWD, 'Thread Through the Crowd')])
def test_thread_passage_real_move_and_reload(tmp_path, source, name):
    combat, table, mid = fixture(tmp_path, [source], corridor=True)
    reach(table, mid, P)
    draw(table, mid)
    settle(table, mid, candidate(table, mid, name))
    e = cold(tmp_path, mid)
    assert any(c.condition_id == PASSAGE for c in e.state.actors[P].conditions.values())
    # Target at 6,0: traverse it to 7,0, pay Difficult Terrain, never end on it.
    moves = [c for c in e.legal_candidates() if c.kind.value == 'MOVE' and c.destination.x == 7 and c.destination.y == 0]
    assert moves
    c = min(moves, key=lambda c: c.movement_cost_ft)
    assert c.movement_cost_ft >= 25
    settle(table, mid, c.candidate_id, decline=True)
    e = cold(tmp_path, mid)
    assert e.state.actors[P].position.x == 7
    assert not [c for c in e.legal_candidates() if c.kind.value == 'MOVE' and c.destination == e.state.actors[F].position]
    single_reviewed_record(source)


@pytest.mark.parametrize('connected,decline', [(False, False), (True, False), (True, True)])
def test_internal_tension_dodge_prompt_and_reload(tmp_path, connected, decline):
    def configure(bundles):
        next(r for r in bundles[0]['actor_template']['resources'] if r['resource_id'] == FOCUS)['initial'] = 0
        seal(bundles[0])
    combat, table, mid = fixture(tmp_path, [REEL], configure=configure)
    reach(table, mid, P)
    if connected:
        draw(table, mid)
        reach(table, mid, F)
        reach(table, mid, P)
    cid = candidate(table, mid, 'Dodge')
    result = send(table, mid, cid)
    if connected:
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        assert 'Internal Tension' in prompt['moment'] and 'Martial Focus' in prompt['moment']
        result = send(table, mid, cid, [{**prompt['context'], 'selection': 'DECLINE' if decline else 'USE', 'option_ids': [] if decline else ['regain']}])
    assert result['status'] == 'COMMITTED'
    assert cold(tmp_path, mid).state.actors[P].resources[FOCUS] == int(connected and not decline)
    single_reviewed_record(REEL)


@pytest.mark.parametrize('speed,hover', [(20, False), (20, True), (30, False)])
def test_binding_sleeve_wing_native_flight_escape_and_reload(tmp_path, speed, hover):
    # Keep unequal skill bonuses to prove the ordinary higher-bonus check.
    # DC 12 makes that real +11 check succeed on every d20; the prior DC 50
    # could never pass after replacing the foe's +245 ability fallback.
    def configure(bundles):
        bundles[1]['actor_template'].update(fly_speed_ft=speed, hover=hover)
        seal(bundles[1])
    combat, table, mid = fixture(tmp_path, ['TAL_THREAD_BINDING_SLEEVE_METHOD', 'tianxia.talent.thread.binding_knot'],
                               foe_score=500, configure=configure, elevated=True, foe_x=6, foe_altitude=2,
                               foe_skills={'Athletics': 3, 'Acrobatics': 11}, caster_dc=12)
    reach(table, mid, P)
    for field, value in [('on', 'toggle'), ('option', '3')]:
        e = combat._load_session(mid).engine
        c = next(c for c in e.legal_candidates()
                 if (setting := e.action_catalog.get(c.source_definition_id).parameters.get('attack_modifier_setting', {})
                     if c.source_definition_id in e.action_catalog else {})
                 and setting.get('modifier') == 'TAL_THREAD_BINDING_SLEEVE_METHOD'
                 and setting['family'].endswith('.binding_knot')
                 and setting['field'] == field and setting['value'] == value)
        settle(table, mid, c.candidate_id)
    settle(table, mid, candidate(table, mid, 'Binding Knot', F))
    e = cold(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.bound_wing' for c in e.state.actors[F].conditions.values())
    assert not any(c.condition_id == 'condition:typed.grappled' for c in e.state.actors[F].conditions.values())
    from combat.tabletop import engine_button_description
    escape_row = next(row for row in e.action_catalog.values() if row.display_name == 'Escape the binding')
    description = engine_button_description(escape_row.model_dump())
    assert 'Normally, the check uses the higher' in description
    assert 'If you are grounded inside a hostile Heaven-Net Casting, you may choose either skill' in description
    assert "that skill's bonus" in description
    assert flight.profile(e, e.state.actors[F]).speed_ft == max(0, speed - 20)
    assert e.state.actors[F].position.z == (2 if hover or speed > 20 else 0)
    reach(table, mid, F)
    settle(table, mid, candidate(table, mid, 'Escape the binding'))
    e = cold(tmp_path, mid)
    escape_roll = [r for r in e.rolls if r.actor_id == F and r.reason.startswith('CHECK:')][-1]
    # Outside Heaven-Net, there is no skill prompt: the ordinary escape uses
    # the better compiled skill bonus (Acrobatics in this unequal-bonus fixture).
    assert escape_roll.modifier == 11
    assert not any(c.condition_id in ('condition:typed.bound_wing', 'condition:typed.bound_limb') for c in e.state.actors[F].conditions.values())
    assert flight.profile(e, e.state.actors[F]).speed_ft == speed
    single_reviewed_record('TAL_THREAD_BINDING_SLEEVE_METHOD')


@pytest.mark.parametrize('first_choice', ['step', 'decline', 'stay'])
def test_silk_reeling_foundation_use_step_round_limit_and_reload(tmp_path, first_choice):
    def configure(bundles):
        # Sealed test economy permits repeated real Draw the Line uses, isolating
        # the Foundation's round limit from the ordinary one-Action limit.
        for action in bundles[0]['action_catalog']:
            if action.get('parameters', {}).get('typed', {}).get('source') == 'THREAD_BASE_DRAW_THE_LINE':
                action['economy'] = 'NONE'
        seal(bundles[0])
    combat, table, mid = fixture(tmp_path, ['insight.silk-reeling-foundation'], configure=configure)
    reach(table, mid, P)
    key = 'once_per_round:thread_silk_reeling_foundation'

    def use(choice, x):
        cid = candidate(table, mid, 'Draw the Line: Guide', F)
        result = send(table, mid, cid)
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert 'Silk-Reeling Foundation' in prompt['moment'] and '5 feet' in prompt['moment']
        dest = next(o['id'] for o in prompt['choice']['options']
                    if o['id'] in (f'cell:{x},6,0', f'cell:{x},6'))
        assert send(table, mid, cid, [{**prompt['context'],
            'selection': 'DECLINE' if choice == 'decline' else 'USE',
            'option_ids': [] if choice == 'decline' else [dest]}])['status'] == 'COMMITTED'
        return cold(tmp_path, mid)

    e = use(first_choice, 3 if first_choice == 'stay' else 4)
    round_used = e.state.round_number
    assert e.state.actors[P].position.x == (4 if first_choice == 'step' else 3)
    assert (key in e.state.actors[P].turn_flags) == (first_choice == 'step')
    if first_choice != 'step':
        # Neither declining nor choosing Stay spends the round's use.
        e = use('step', 4)
    assert e.state.actors[P].turn_flags[key] == round_used

    # Use a fresh service/session after reload for the second activation.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    cid = candidate(table, mid, 'Draw the Line: Guide', F)
    assert send(table, mid, cid)['status'] == 'COMMITTED'  # no second step prompt
    e = cold(tmp_path, mid)
    assert e.state.actors[P].position.x == 4
    assert e.state.round_number == round_used
    assert e.state.actors[P].turn_flags[key] == round_used

    # End the real turns; the marker survives reset, but the new round allows a step.
    reach(table, mid, F)
    reach(table, mid, P)
    e = cold(tmp_path, mid)
    assert e.state.round_number == round_used + 1
    assert e.state.actors[P].turn_flags[key] == round_used
    e = use('step', 5)
    assert e.state.actors[P].position.x == 5
    assert e.state.actors[P].turn_flags[key] == round_used + 1


def test_silk_reeling_foundation_steps_after_a_missed_draw_the_line(tmp_path):
    # The printed trigger is using either feature, not hitting with it.  A very
    # low attack bonus makes Draw the Line miss deterministically while its
    # optional movement still goes through the normal service choice path.
    def force_miss(bundles):
        for action in bundles[0]['action_catalog']:
            if action.get('parameters', {}).get('typed', {}).get('source') == 'THREAD_BASE_DRAW_THE_LINE':
                action['parameters']['typed'].setdefault('numbers', {})['attack_bonus'] = -100
        seal(bundles[0])
    combat, table, mid = fixture(tmp_path, ['insight.silk-reeling-foundation'], configure=force_miss)
    reach(table, mid, P)
    cid = candidate(table, mid, 'Draw the Line: Guide', F)
    result = send(table, mid, cid)
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert 'using Draw the Line or Threaded Strike' in prompt['moment']
    assert send(table, mid, cid, [{**prompt['context'], 'selection': 'USE',
        'option_ids': ['cell:4,6']}])['status'] == 'COMMITTED'
    e = cold(tmp_path, mid)
    attack = [r for r in e.rolls if r.actor_id == P and r.reason.startswith('ATTACK:')][-1]
    assert attack.total < next(x.payload['target_ac'] for x in e.events
                               if x.event_type == 'ATTACK_ROLLED' and x.payload['roll_id'] == attack.roll_id)
    assert e.state.actors[P].position.x == 4


@pytest.mark.parametrize('advantage', [False, True])
@pytest.mark.parametrize('ability,expected', [('DEX', 'DISADVANTAGE'), ('STR', 'NORMAL')])
def test_heaven_net_ground_escape_actual_skill_choice_reload(tmp_path, ability, expected, advantage):
    def configure(bundles):
        add_action(bundles[0], 'Prepare physical hold', [{'type': 'condition', 'condition': 'grappled',
            'applies_to': 'target', 'duration': 'until_removed', 'condition_data': {'escape_dc': 500}}])
        add_action(bundles[1], 'Prepare escape advantage', [{'type': 'check_against',
            'applies_to': 'self', 'abilities': ['DEX'], 'skills': ['Acrobatics'],
            'against': ['grappled'], 'mode': 'ADVANTAGE', 'duration': 'until_removed'}], target='SELF')
    combat, table, mid = fixture(tmp_path, [NET], configure=configure)
    reach(table, mid, P)
    settle(table, mid, candidate(table, mid, 'Prepare physical hold', F))
    e = combat._load_session(mid).engine
    cast = next(c for c in e.legal_candidates() if 'Heaven-Net Casting' in c.display_name
                and c.destination.x == 4 and c.destination.y == 6 and c.destination.z == 0)
    settle(table, mid, cast.candidate_id)
    reach(table, mid, F)
    if advantage:
        settle(table, mid, candidate(table, mid, 'Prepare escape advantage'))
    cid = candidate(table, mid, 'Escape grapple')
    result = send(table, mid, cid)
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert 'Acrobatics' in prompt['moment'] and 'Disadvantage' in prompt['moment']
    assert {o['id'] for o in prompt['choice']['options']} == {'STR', 'DEX'}
    result = send(table, mid, cid, [{**prompt['context'], 'selection': 'USE', 'option_ids': [ability]}])
    assert result['status'] == 'COMMITTED'
    e = cold(tmp_path, mid)
    checks = [r for r in e.rolls if r.actor_id == F and r.reason.startswith('CHECK:')]
    assert checks and checks[-1].mode == ('NORMAL' if advantage else expected)
    assert any(c.condition_id == 'condition:typed.grappled' for c in e.state.actors[F].conditions.values())


@pytest.mark.parametrize('decline', [False, True])
def test_meridian_lock_maintenance_cost_dc_repeat_save_cold_reload(tmp_path, decline):
    combat, table, mid = fixture(tmp_path, [LOCK], foe_score=2, foe_x=8)
    reach(table, mid, P)
    settle(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread)', F), decline=True)
    reach(table, mid, F)
    reach(table, mid, P)
    settle(table, mid, candidate(table, mid, 'Meridian Lock', F))
    e = cold(tmp_path, mid)
    original = next(c for c in e.state.actors[F].conditions.values() if c.data.get('thread_meridian_lock') == 1)
    before = e.state.actors[P].resources[QI]
    # Ending the holder's turn runs the original DC-50 repeat save and then
    # opens the caster's own turn-start maintenance decision.
    reach(table, mid, F)
    cid = table.state(mid)['menu']['end_turn']
    result = send(table, mid, cid)
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert 'Meridian Lock' in prompt['moment'] and any(price in prompt['moment'] for price in ('1 CP', '1 Qi'))
    result = send(table, mid, cid, [{**prompt['context'], 'selection': 'DECLINE' if decline else 'USE',
                                    'option_ids': [] if decline else ['maintain']}])
    assert result['status'] == 'COMMITTED'
    e = cold(tmp_path, mid)
    held = next(c for c in e.state.actors[F].conditions.values() if c.data.get('thread_meridian_lock') == 1)
    assert held.data['repeat_save']['dc'] == 50
    assert e.state.actors[P].resources[QI] == before - int(not decline)
    if not decline:
        assert held.expires_on != original.expires_on
    else:
        assert held.instance_id == original.instance_id


def test_heaven_net_grounded_enemy_terrain_real_move_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [NET])
    reach(table, mid, P)
    e = combat._load_session(mid).engine
    cast = next(c for c in e.legal_candidates() if 'Heaven-Net Casting' in c.display_name
                and c.destination.x == 4 and c.destination.y == 6 and c.destination.z == 0)
    settle(table, mid, cast.candidate_id)
    reach(table, mid, F)
    e = cold(tmp_path, mid)
    move = next(c for c in e.legal_candidates() if c.kind.value == 'MOVE'
                and c.destination.x == 7 and c.destination.y == 6 and c.destination.z == 0)
    assert move.movement_cost_ft == 10
    settle(table, mid, move.candidate_id)
    e = cold(tmp_path, mid)
    assert e.state.actors[F].position.x == 7


def test_flight_flat_penalties_stack_by_effect_not_duplicate_markers(tmp_path):
    def configure(bundles):
        bundles[1]['actor_template'].update(fly_speed_ft=50, hover=True)
        seal(bundles[1])
        add_action(bundles[0], 'Apply independent flight penalties', [
            {'type': 'condition', 'condition': label, 'applies_to': 'target', 'duration': 'until_removed',
             'condition_data': {'fly_speed_reduction_ft': 20, 'fly_speed_reduction_key': group}}
            for label, group in [('flat_a', 'a'), ('flat_a_marker', 'a'), ('flat_b', 'b')]])
    combat, table, mid = fixture(tmp_path, [], configure=configure, elevated=True)
    reach(table, mid, P)
    settle(table, mid, candidate(table, mid, 'Apply independent flight penalties', F))
    e = cold(tmp_path, mid)
    assert flight.profile(e, e.state.actors[F]).speed_ft == 10
    assert e.state.actors[F].position.z == 2


def test_heaven_net_flight_capable_creature_on_platform_is_grounded(tmp_path):
    def configure(bundles):
        bundles[1]['actor_template'].update(fly_speed_ft=50, hover=True)
        seal(bundles[1])
    combat, table, mid = fixture(tmp_path, [NET], configure=configure, elevated=True, platform=True)
    reach(table, mid, P)
    e = cold(tmp_path, mid)
    from combat.falling import supported
    assert supported(e, e.state.actors[F]) and e.state.actors[F].position.z == 2
    cast = next(c for c in e.legal_candidates() if 'Heaven-Net Casting' in c.display_name
                and c.destination.x == 4 and c.destination.y == 6 and c.destination.z == 0)
    settle(table, mid, cast.candidate_id)
    e = cold(tmp_path, mid)
    assert not [r for r in e.rolls if r.actor_id == F and r.reason.startswith('SAVE:') and 'heaven_net' in r.reason]
    assert flight.profile(e, e.state.actors[F]).speed_ft == 50


@pytest.mark.parametrize('reverse_roster', [False, True])
def test_heaven_net_lethal_falls_both_last_survivors_draw_and_reload(tmp_path, reverse_roster):
    def configure(bundles):
        for bundle in bundles:
            bundle['actor_template'].update(fly_speed_ft=30, hover=False, maximum_hp=1)
            seal(bundle)
    # Genesis canonicalizes actor keys; put the caster before/after the foe
    # by using a sealed actor identity, rather than merely reversing input lists.
    caster = 'actor:factory.a2-player' if reverse_roster else P
    combat, table, mid = fixture(tmp_path, [NET], foe_score=2, configure=configure,
        elevated=True, caster_altitude=2, caster_id=caster)
    reach(table, mid, caster)
    e = cold(tmp_path, mid)
    assert all(e.state.actors[a].current_hp == 1 and e.state.actors[a].position.z == 2 for a in (caster, F))
    start = len(e.events)
    cast = next(c for c in e.legal_candidates() if 'Heaven-Net Casting' in c.display_name
                and c.destination.x == 4 and c.destination.y == 6 and c.destination.z == 0)
    settle(table, mid, cast.candidate_id)
    e = cold(tmp_path, mid)
    assert all(not e.state.actors[a].active and e.state.actors[a].current_hp == 0
               and e.state.actors[a].position.z == 0 for a in (caster, F))
    saves = [r.actor_id for r in e.rolls if r.reason.startswith('SAVE:') and 'heaven_net' in r.reason]
    assert saves == ([caster, F] if reverse_roster else [F, caster])
    falls = [ev for ev in e.events[start:] if ev.event_type == 'DAMAGE_COMMITTED'
             and ev.source_definition_id == 'system:combat.falling']
    assert {a for ev in falls for a in ev.target_ids} == {caster, F}
    ended = [ev for ev in e.events[start:] if ev.event_type == 'MATCH_ENDED']
    assert len(ended) == 1 and ended[0].sequence > max(ev.sequence for ev in falls)
    assert e.state.terminal_result.kind == TerminalKind.DRAW_SIMULTANEOUS
    assert e.state.terminal_result.winning_team_id is None


@pytest.mark.parametrize('connected', [False, True])
def test_crowd_opportunity_exemption_only_connected_reactor_and_reload(tmp_path, connected):
    combat, table, mid = fixture(tmp_path, [CROWD], foe_x=4)
    reach(table, mid, P)
    if connected:
        draw(table, mid)
    settle(table, mid, candidate(table, mid, 'Thread Through the Crowd'))
    e = cold(tmp_path, mid)
    assert e.state.actors[F].reaction_available
    start = len(e.events)
    # From 3,6 beside the foe at 4,6 to 2,6: leave its real melee reach.
    move = next(c for c in e.legal_candidates() if c.kind.value == 'MOVE'
                and c.destination.x == 2 and c.destination.y == 6 and c.destination.z == 0)
    settle(table, mid, move.candidate_id)
    e = cold(tmp_path, mid)
    assert e.state.actors[P].position.x == 2
    resolved = [ev for ev in e.events[start:] if ev.event_type == 'REACTION_RESOLVED'
                and ev.actor_id == F and ev.target_ids == (P,)
                and ev.source_definition_id == 'system:combat.opportunity_attack']
    assert bool(resolved) == (not connected)
    assert e.state.actors[F].reaction_available == connected
    # The exemption expires at the real turn boundary, even while the line remains.
    reach(table, mid, F)
    reach(table, mid, P)
    e = cold(tmp_path, mid)
    assert not any(c.condition_id == PASSAGE for c in e.state.actors[P].conditions.values())


@pytest.mark.parametrize('kind', ['net', 'sand'])
@pytest.mark.parametrize('ability,mode', [('STR', 'NORMAL'), ('DEX', 'DISADVANTAGE')])
@pytest.mark.parametrize('success', [False, True])
def test_heaven_net_combined_restraint_skill_bonus_and_removal_reload(tmp_path, kind, ability, mode, success):
    skills = {'Athletics': 103 if success else 3, 'Acrobatics': 111 if success else 11}

    def configure(bundles):
        # Native trap save fails regardless of the unrelated, sealed skill bonuses.
        bundles[1]['actor_template']['saving_throws']['DEX'] = -100
        seal(bundles[1])
        if kind == 'sand':
            # Exercise the shipped burial/linked-hold lifecycle, with two independent
            # burials to prove that Dig free removes only its selected instance.
            add_action(bundles[0], 'Prepare burial', [{'type': 'sand_bury', 'applies_to': 'target',
                'restrain': 'always', 'with': ['blinded'], 'duration': 'until_removed'}],
                typed={'numbers': {'pb': 4, 'key_mod': 2, 'save_dc': 50, 'cl': 20}})

    mids = [NET, 'tianxia.talent.trap.net'] if kind == 'net' else [NET]
    combat, table, mid = fixture(tmp_path, mids, configure=configure, foe_skills=skills)
    reach(table, mid, P)
    if kind == 'net':
        settle(table, mid, candidate(table, mid, 'Trap form: Net (Snare use)'))
        e = cold(tmp_path, mid)
        place = next(c for c in e.legal_candidates() if getattr(e.action_catalog.get(c.source_definition_id), 'display_name', None) == 'Set Trap'
                     and c.destination.x == 4 and c.destination.y == 6)
        settle(table, mid, place.candidate_id)
        reach(table, mid, F)
        e = cold(tmp_path, mid)
        move = next(c for c in e.legal_candidates() if c.kind.value == 'MOVE'
                    and c.destination.x == 4 and c.destination.y == 6 and c.destination.z == 0)
        settle(table, mid, move.candidate_id)
        reach(table, mid, P)
        held_id = 'condition:typed.netted'
    else:
        for _ in range(2):
            settle(table, mid, candidate(table, mid, 'Prepare burial', F))
        held_id = 'condition:typed.buried'
    e = cold(tmp_path, mid)
    before_holds = {iid for iid, c in e.state.actors[F].conditions.items() if c.condition_id == held_id}
    assert len(before_holds) == (1 if kind == 'net' else 2)
    cast = next(c for c in e.legal_candidates() if 'Heaven-Net Casting' in c.display_name
                and c.destination.x == 4 and c.destination.y == 6 and c.destination.z == 0)
    settle(table, mid, cast.candidate_id)
    reach(table, mid, F)
    # Cold service owns the actual escape transaction and resumes the same prompt.
    cold(tmp_path, mid)
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    cid = candidate(table, mid, 'Escape the net' if kind == 'net' else 'Dig free of the sand')
    answers = []
    result = send(table, mid, cid)
    if kind == 'sand':
        assert result['status'] == 'REACTION_REQUIRED'
        burial_prompt = result['reaction']
        selected_hold = burial_prompt['choice']['options'][0]['id']
        answers.append({**burial_prompt['context'], 'selection': 'USE', 'option_ids': [selected_hold]})
        result = send(table, mid, cid, answers)
    else:
        selected_hold = next(iter(before_holds))
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert 'Heaven-Net' in prompt['moment'] and 'Disadvantage' in prompt['moment']
    assert prompt['context']['reactor_id'] == F
    assert {o['id'] for o in prompt['choice']['options']} == {'STR', 'DEX'}
    assert send(table, mid, cid, answers)['reaction'] == prompt
    # An unanswered choice makes no committed check or condition change.
    assert {iid for iid, c in cold(tmp_path, mid).state.actors[F].conditions.items()
            if c.condition_id == held_id} == before_holds
    answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': [ability]})
    assert send(table, mid, cid, answers)['status'] == 'COMMITTED'
    e = cold(tmp_path, mid)
    roll = [r for r in e.rolls if r.actor_id == F and r.reason.startswith('CHECK:')][-1]
    assert roll.mode == mode
    assert roll.modifier == skills['Athletics' if ability == 'STR' else 'Acrobatics']
    event = [ev for ev in e.events if ev.event_type == 'CHECK_ROLLED' and ev.actor_id == F][-1]
    assert event.payload['ability'] == ability and event.payload['success'] == success
    after_holds = {iid for iid, c in e.state.actors[F].conditions.items() if c.condition_id == held_id}
    assert after_holds == before_holds - ({selected_hold} if success else set())
    if kind == 'net':
        assert any(c.condition_id == 'condition:typed.restrained' for c in e.state.actors[F].conditions.values()) == (not success)
    else:
        assert len([c for c in e.state.actors[F].conditions.values() if c.condition_id == 'condition:typed.restrained']) == (1 if success else 2)


def test_ai_heaven_net_ground_terrain_is_enemies_only_after_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [NET], second=[SILK])
    reach(table, mid, P)
    e = cold(tmp_path, mid)
    cast = next(c for c in e.legal_candidates() if 'Heaven-Net Casting' in c.display_name
                and c.destination.x == 4 and c.destination.y == 6 and c.destination.z == 0)
    auto_candidate(combat, mid, P, cast.candidate_id)
    assert table.auto_step(mid, 0)['status'] == 'COMMITTED'
    combat.set_controller_mode(mid, actor_id=P, controller_mode='MANUAL')
    for actor, x, y, price in [(F, 7, 6, 10), (S, 6, 7, 5)]:
        reach(table, mid, actor)
        e = cold(tmp_path, mid)
        move = next(c for c in e.legal_candidates() if c.kind.value == 'MOVE'
                    and c.destination.x == x and c.destination.y == y and c.destination.z == 0)
        assert move.movement_cost_ft == price
        settle(table, mid, move.candidate_id)
        assert cold(tmp_path, mid).state.actors[actor].position.x == x


def test_heaven_net_hovering_zero_speed_creature_still_saves_after_reload(tmp_path):
    def configure(bundles):
        bundles[1]['actor_template'].update(fly_speed_ft=30, hover=True)
        seal(bundles[1])
        add_action(bundles[0], 'Prepare stopped hovering flight', [{'type': 'condition',
            'condition': 'void_sovereign_flight', 'applies_to': 'target',
            'duration': 'until_removed', 'condition_data': {'fly_speed_zero': 1}}])
    combat, table, mid = fixture(tmp_path, [NET], configure=configure, elevated=True)
    reach(table, mid, P)
    settle(table, mid, candidate(table, mid, 'Prepare stopped hovering flight', F))
    e = cold(tmp_path, mid)
    assert e.state.actors[F].position.z == 2
    assert flight.profile(e, e.state.actors[F]).speed_ft == 0
    cast = next(c for c in e.legal_candidates() if 'Heaven-Net Casting' in c.display_name
                and c.destination.x == 4 and c.destination.y == 6 and c.destination.z == 0)
    settle(table, mid, cast.candidate_id)
    e = cold(tmp_path, mid)
    assert any(r.actor_id == F and r.reason.startswith('SAVE:') and 'heaven_net' in r.reason for r in e.rolls)
    assert e.state.actors[F].position.z == 2


@pytest.mark.parametrize('pool', [QI, FOCUS])
def test_meridian_lock_blocks_paid_escape_reaction_but_allows_focus_reload(tmp_path, pool):
    reaction = 'reaction:test.thread.escape'
    def configure(bundles):
        add_action(bundles[0], 'Provoke escape reaction', [{'type': 'attack',
            'attack_kind': 'cultivation_ranged', 'count': 1, 'on_hit': [], 'on_miss': []}],
            typed={'numbers': {'attack_bonus': 1000, 'pb': 4, 'key_mod': 2, 'save_dc': 50, 'cl': 20}})
        bundles[1]['typed_reactions'].append({'block': 'generic', 'feature_id': reaction,
            'name': 'Test physical escape reaction', 'kind': 'attacked', 'range_ft': 60,
            'requires_condition': 'condition:typed.restrained',
            'costs': [{'resource_id': pool, 'amount': 1}],
            'numbers': {'pb': 4, 'key_mod': 2, 'save_dc': 16, 'cl': 20},
            'effects': [{'type': 'remove_condition', 'condition': 'restrained', 'applies_to': 'self'}]})
        seal(bundles[1])
    combat, table, mid = fixture(tmp_path, [LOCK], foe_score=2, foe_x=8, configure=configure)
    reach(table, mid, P)
    settle(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread)', F), decline=True)
    reach(table, mid, F)
    reach(table, mid, P)
    settle(table, mid, candidate(table, mid, 'Meridian Lock', F))
    before = cold(tmp_path, mid).state.actors[F].resources[pool]
    settle(table, mid, candidate(table, mid, 'Provoke escape reaction', F))
    e = cold(tmp_path, mid)
    held = any(c.data.get('thread_meridian_lock') == 1 for c in e.state.actors[F].conditions.values())
    assert held == (pool == QI)
    assert e.state.actors[F].resources[pool] == before - int(pool == FOCUS)
    assert e.state.actors[F].reaction_available == (pool == QI)


def test_ai_hundred_line_weaving_has_hard_enemy_recipient_options_reload(tmp_path):
    hundred = 'tianxia.talent.thread.hundred_line_weaving'
    combat, table, mid = fixture(tmp_path, [hundred], second=[SILK])
    reach(table, mid, P)
    cid = candidate(table, mid, 'Draw the Line: Guide (two targets)', F)
    auto_candidate(combat, mid, P, cid)
    real = combat.controller
    seen = []
    class ObserveChoices:
        def choose_reaction(self, context):
            if context.extension_choice is not None:
                seen.append(list(context.extension_choice.option_ids))
            return real.choose_reaction(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = ObserveChoices()
    assert table.auto_step(mid, 0)['status'] == 'COMMITTED'
    combat.set_controller_mode(mid, actor_id=P, controller_mode='MANUAL')
    e = cold(tmp_path, mid)
    assert seen and any(F in options for options in seen)
    assert all(P not in options and S not in options for options in seen)
    from combat.ext.thread_common import mark_held_by, LINE
    assert mark_held_by(e.state.actors[F], P, LINE)
    assert not mark_held_by(e.state.actors[S], P, LINE)


@pytest.mark.parametrize('mode', ['SUGGESTED', 'MANUAL_AI_BRIDGE'])
def test_hundred_line_weaving_player_modes_keep_full_choices_and_commit_reload(tmp_path, mode):
    hundred = 'tianxia.talent.thread.hundred_line_weaving'
    combat, table, mid = fixture(tmp_path, [hundred], second=[SILK],
                                 control_modes={P: mode, F: 'MANUAL', S: 'MANUAL'})
    reach(table, mid, P)
    cid = candidate(table, mid, 'Draw the Line: Guide (two targets)', F)
    result = send(table, mid, cid)
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    option_ids = {o['id'] for o in prompt['choice']['options']}
    assert {P, S, F} <= option_ids
    result = send(table, mid, cid, [{**prompt['context'], 'selection': 'USE', 'option_ids': [S]}])
    assert result['status'] == 'COMMITTED'
    e = cold(tmp_path, mid)
    from combat.ext.thread_common import mark_held_by, LINE
    assert mark_held_by(e.state.actors[S], P, LINE)


def test_ryujin_storm_step_classification_is_owned_without_thread(tmp_path):
    storm = 'tianxia.subpath.body.ryujin.feature.storm_step'
    combat, table, mid = fixture(tmp_path, [storm], caster_primary="Stamina")
    e = cold(tmp_path, mid)
    row = next(row for action in e.action_catalog.values()
               for row in (action.parameters.get('typed', {}).get('effects') or [])
               if row.get('type') == 'storm_step')
    assert row.get('self_movement') is True
    assert not any(c.condition_id == PASSAGE for c in e.state.actors[P].conditions.values())
    reach(table, mid, P)
    e = cold(tmp_path, mid)
    step = next(c for c in e.legal_candidates()
                if c.source_definition_id in e.action_catalog
                and e.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == storm
                and c.destination is not None and c.destination.x == 4 and c.destination.y == 6)
    before_stamina = e.state.actors[P].resources['resource:core.stamina']
    response = send(table, mid, step.candidate_id)
    assert response['status'] == 'REACTION_REQUIRED'
    prompt = response['reaction']
    assert prompt['context']['reactor_id'] == P
    # Ryujin's reviewed Body automation selects both printed activation
    # choices; Thread still must not supply this non-owner's movement grant.
    assert prompt['context']['reaction_source_id'] == 'choice:needle.ryujin_damage'
    assert {'LIGHTNING', 'THUNDER'} <= {option['id'] for option in prompt['choice']['options']}
    answers = [{**prompt['context'], 'selection': 'USE', 'option_ids': ['LIGHTNING']}]
    response = send(table, mid, step.candidate_id, answers)
    assert response['status'] == 'REACTION_REQUIRED'
    prompt = response['reaction']
    assert prompt['context']['reactor_id'] == P
    assert prompt['context']['reaction_source_id'] == 'choice:needle.teleport_destination'
    assert 'cell:4,6' in {option['id'] for option in prompt['choice']['options']}
    assert send(table, mid, step.candidate_id, [*answers, {**prompt['context'], 'selection': 'USE',
        'option_ids': ['cell:4,6']}])['status'] == 'COMMITTED'
    e = cold(tmp_path, mid)
    assert e.state.actors[P].resources['resource:core.stamina'] == before_stamina - 3
    assert (e.state.actors[P].position.x, e.state.actors[P].position.y) == (4, 6)
    assert not any(c.condition_id == PASSAGE for c in e.state.actors[P].conditions.values())


def test_foundation_after_actual_threaded_strike_attack_and_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, ['insight.silk-reeling-foundation', 'THREAD_BASE_THREADED_STRIKE'], foe_x=4)
    reach(table, mid, P)
    e = cold(tmp_path, mid)
    attack = next(a for a in e.action_catalog.values() if a.owner_id == P
                  and a.source_definition_id.endswith('.weapon.jian')
                  and a.parameters.get('typed', {}).get('weapon')
                  and not a.parameters['typed'].get('range_ft')
                  and not a.parameters['typed'].get('variant_of')
                  and any(g['id'] == 'THREAD_BASE_THREADED_STRIKE'
                          for g in a.parameters['typed'].get('attack_modifier_loadout', [])))
    group = next(g for g in attack.parameters['typed']['attack_modifier_loadout']
                 if g['id'] == 'THREAD_BASE_THREADED_STRIKE')
    guard = next(o['id'] for o in group['options'] if o['label'] == 'Draw the Guard')
    for field, value in [('on', 'toggle'), ('option', guard)]:
        e = cold(tmp_path, mid)
        setting = next(c for c in e.legal_candidates()
                       if (spec := e.action_catalog[c.source_definition_id].parameters.get('attack_modifier_setting', {})
                           if c.source_definition_id in e.action_catalog else {})
                       and spec.get('family') == attack.source_definition_id
                       and spec.get('modifier') == group['id']
                       and spec.get('field') == field and spec.get('value') == value)
        settle(table, mid, setting.candidate_id)
    # A cold service submits the real weapon attack; the free settings are not uses.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    e = cold(tmp_path, mid)
    assert 'once_per_round:thread_silk_reeling_foundation' not in e.state.actors[P].turn_flags
    cid = next(c.candidate_id for c in e.legal_candidates()
               if c.source_definition_id == attack.source_definition_id and F in c.target_ids)
    answers, moments = [], []
    for _ in range(12):
        response = send(table, mid, cid, answers)
        if response['status'] == 'COMMITTED':
            break
        assert response['status'] == 'REACTION_REQUIRED', response
        prompt = response['reaction']
        moments.append(prompt['moment'])
        options = [o['id'] for o in prompt.get('choice', {}).get('options', [])]
        chosen = 'cell:3,5' if 'Silk-Reeling Foundation' in prompt['moment'] else options[0]
        answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': [chosen]})
    else:
        pytest.fail('attack did not commit')
    e = cold(tmp_path, mid)
    from combat.ext.thread_common import mark_held_by
    assert mark_held_by(e.state.actors[F], P, 'Draw the Guard')  # actual modifier landed
    assert any('Silk-Reeling Foundation' in moment for moment in moments), moments
    assert e.state.actors[P].position.y == 5
    assert e.state.actors[P].turn_flags['once_per_round:thread_silk_reeling_foundation'] == e.state.round_number
    assert any(r.actor_id == P and r.reason.startswith('ATTACK:') for r in e.rolls)


def test_foundation_exempts_only_target_with_second_eligible_reactor_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, ['insight.silk-reeling-foundation'], second=[SILK],
        second_enemy=True, foe_x=4, starting_positions={S: {'x': 4, 'y': 5, 'z': 0}})
    reach(table, mid, P)
    e = cold(tmp_path, mid)
    from combat.gate2_runtime_models import Position
    assert set(e.opportunity_eligible(e.state.actors[P], e.state.actors[P].position,
                                     Position(x=2, y=6))) == {F, S}
    cid = candidate(table, mid, 'Draw the Line: Guide', F)
    response = send(table, mid, cid)
    assert response['status'] == 'REACTION_REQUIRED', response
    prompt = response['reaction']
    assert 'Silk-Reeling Foundation' in prompt['moment']
    answers = [{**prompt['context'], 'selection': 'USE', 'option_ids': ['cell:2,6']}]
    response = send(table, mid, cid, answers)
    assert response['status'] == 'REACTION_REQUIRED', response
    prompt = response['reaction']
    assert prompt['context']['reactor_id'] == S, prompt
    answers.append({**prompt['context'], 'selection': 'USE'})
    assert send(table, mid, cid, answers)['status'] == 'COMMITTED'
    e = cold(tmp_path, mid)
    assert e.state.actors[P].position.x == 2
    assert e.state.actors[F].reaction_available
    assert not e.state.actors[S].reaction_available
    attacks = [event for event in e.events if event.event_type == 'ATTACK_ROLLED'
               and event.actor_id == S]
    assert len(attacks) == 1
    assert attacks[0].target_ids == (P,)
    assert any(event.event_type == 'REACTION_RESOLVED'
               and event.source_definition_id == 'system:combat.opportunity_attack'
               and event.actor_id == S for event in e.events)
