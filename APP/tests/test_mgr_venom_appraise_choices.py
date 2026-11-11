"""Appraise transactions, physical perception and profile lifecycle at the table."""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_mgr_venom_appraise import (
    ROOT, SOURCE, ME, FOE, FRIEND, PREFIX, POOL, setup, material, candidate,
    send, settle, turn, appraise, readings, cold, offline_ranking,
)


def test_authoritative_empty_contents_is_absent_not_unknown(tmp_path):
    source = material('creature', entity_id=FOE)
    source['contents'] = []
    combat, table, mid = setup(tmp_path, sources=[source])
    prompts = appraise(combat, table, mid)
    assert 'Poison is absent' in str(readings(table, mid))
    assert not any(p['context']['reaction_source_id'] == PREFIX + 'profile' for p in prompts)
    cold(tmp_path, mid)


def test_another_native_sphere_is_resolved_to_plain_text(tmp_path):
    source = material('sample', object_id='object:map.805')
    source['contents'][0]['spheres'] = ['tianxia.sphere.water', 'Death']
    combat, table, mid = setup(tmp_path, sources=[source])
    appraise(combat, table, mid, 'object:map.805', ('sphere',))
    text = str(readings(table, mid))
    assert 'Water' in text and 'Death' in text and 'tianxia.sphere.' not in text
    cold(tmp_path, mid)


def test_zero_cp_keeps_free_fact_and_cannot_buy_three(tmp_path):
    combat, table, mid = setup(tmp_path, effects=[{'type': 'spend_resource',
        'resource_id': POOL, 'flat': 8, 'applies_to': 'self'}])
    settle(table, mid, candidate(combat, mid, 'Scenario exposure', ME))
    prompts = appraise(combat, table, mid)
    assert not any(p['context']['reaction_source_id'] == PREFIX + 'detail' for p in prompts)
    combat, e = cold(tmp_path, mid)
    assert e.state.actors[ME].resources[POOL] == 0 and 'alchemical' in str(readings(table, mid))


def test_native_json_resource_field_uses_the_same_real_pool(tmp_path):
    combat, table, mid = setup(tmp_path, resource_json=True)
    appraise(combat, table, mid, facts=('classification', 'danger', 'sphere'))
    _, e = cold(tmp_path, mid)
    assert e.state.actors[ME].resources[POOL] == 7


@pytest.mark.parametrize('bad', [['classification', 'classification', 'danger'], ['classification'], ['not-a-fact']])
def test_paid_fact_rejection_does_not_spend_action_or_cp(tmp_path, bad):
    combat, table, mid = setup(tmp_path)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    cid = candidate(combat, mid)
    answers = []
    for expected, selected in [('subject', [FOE]), ('detail', ['three'])]:
        pause = send(table, mid, cid, answers)
        assert pause['status'] == 'REACTION_REQUIRED'
        assert pause['reaction']['context']['reaction_source_id'] == PREFIX + expected
        answers.append({**pause['reaction']['context'], 'selection': 'USE', 'option_ids': selected})
    pause = send(table, mid, cid, answers)
    assert pause['reaction']['context']['reaction_source_id'] == PREFIX + 'facts'
    answers.append({**pause['reaction']['context'], 'selection': 'USE', 'option_ids': bad})
    with pytest.raises(Exception):
        send(table, mid, cid, answers)
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    assert not readings(table, mid)


def test_subject_cancel_and_stale_replies_are_atomic(tmp_path):
    combat, table, mid = setup(tmp_path)
    e = combat._load_session(mid).engine
    before = e.state.model_dump(mode='json')
    cid = candidate(combat, mid)
    pause = send(table, mid, cid, [])
    assert pause['reaction']['choice']['allow_decline']
    answer = {**pause['reaction']['context'], 'selection': 'DECLINE'}
    assert send(table, mid, cid, [answer])['status'] == 'COMMITTED'
    after = combat._load_session(mid).engine.state.model_dump(mode='json')
    assert after['actors'] == before['actors']
    assert table.state(mid)['pending_action'] is None
    assert not readings(table, mid)
    # A later native action changes the revision. The old subject reply cannot
    # attach to a newly issued Appraise transaction or charge its optional CP.
    saved_menu = table.state(mid)['menu']
    settle(table, mid, saved_menu['end_turn'])
    with pytest.raises(Exception):
        table.act(mid, cid, saved_menu['decision_id'], saved_menu['state_version'], 0, [answer])
    _, e = cold(tmp_path, mid)
    assert e.state.actors[ME].resources[POOL] == 8 and not readings(table, mid)


def test_profile_limit_replacement_dismissal_and_native_identity(tmp_path):
    combat, table, mid = setup(tmp_path, cl=1)
    for subject in ['object:map.800', 'object:map.801', 'object:map.802']:
        prompts = appraise(combat, table, mid, subject, profile=True)
        if subject != 'object:map.802':
            assert not any(p['context']['reaction_source_id'] == PREFIX + 'replace' for p in prompts)
        else:
            assert any(p['context']['reaction_source_id'] == PREFIX + 'replace' for p in prompts)
        turn(table, mid, FOE); turn(table, mid, ME)
    combat, e = cold(tmp_path, mid)
    profiles = [r for r in readings(table, mid)['information'] if r['kind'] == 'antidote_profile']
    assert len(profiles) == e.state.actors[ME].proficiency_bonus == 2
    records = [v.payload['private_information'] for v in e.events
               if 'private_information' in v.payload and v.payload['private_information']['kind'] == 'antidote_profile'
               and v.payload['private_information']['public'] is not None]
    assert records[-1]['identity']['subject'] == 'object:map.802'
    assert records[-1]['identity']['toxins'] == ['PRIVATE-TOXIN-42']
    assert records[-1]['identity']['source'] == SOURCE
    assert records[-1]['identity']['source_text_sha256'] == '39ee306edfffa683cad887972e68ed007986f760905ce0dd6318e1cf1a97eda8'
    assert 'SECRET-' not in str(records)
    before = e.state.actors[ME].resources.copy()
    settle(table, mid, candidate(combat, mid, 'Dismiss an Antidote Profile'))
    _, e = cold(tmp_path, mid)
    assert e.state.actors[ME].action_available and e.state.actors[ME].resources == before
    assert len([r for r in readings(table, mid)['information'] if r['kind'] == 'antidote_profile']) == 1


def test_own_marks_do_not_reveal_another_creators_marks(tmp_path):
    # Native scenario damage/mark application is attributed to the actual other
    # actor, rather than planting a diagnostic answer or another owner's flag.
    combat, table, mid = setup(tmp_path, friend_poison=True)
    turn(table, mid, FRIEND)
    settle(table, mid, candidate(combat, mid, 'Deliver the Dose', FOE))
    turn(table, mid, ME)
    appraise(combat, table, mid, facts=('dose_marks',))
    result = readings(table, mid)
    assert 'none of your Dose Marks' in str(result)
    assert 'Tobin' not in str(result) and FRIEND not in str(result)
    assert not readings(table, mid, FRIEND)
    cold(tmp_path, mid)


def test_native_poison_condition_ingrained_source_and_danger(tmp_path):
    # Two actual mark placements are authored scenario exposures, followed by
    # the real acquired Ingrain action. Appraise must read its real modifier.
    combat, table, mid = setup(tmp_path, effects=[
        {'type': 'mark', 'mark': 'Dose Mark', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}},
        {'type': 'mark', 'mark': 'Dose Mark', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
    settle(table, mid, candidate(combat, mid, 'Scenario exposure', FOE))
    settle(table, mid, candidate(combat, mid, 'Ingrain the Toxin: Numb Channels', FOE))
    turn(table, mid, FOE); turn(table, mid, ME)
    appraise(combat, table, mid, facts=('ingrained', 'danger', 'sphere'))
    result = readings(table, mid)
    assert 'has an Ingrained Toxin' in str(result) and 'long-term' in str(result)
    cold(tmp_path, mid)


@pytest.mark.parametrize('feet', [5, 10, 30])
def test_blindfold_does_not_invent_contact_or_identity(tmp_path, feet):
    combat, table, mid = setup(tmp_path, extra=('TAL_DARK_BLINDFOLD',), feet=feet)
    settle(table, mid, candidate(combat, mid, 'Meld: Blindfold', ME))
    turn(table, mid, FOE); turn(table, mid, ME)
    pause = send(table, mid, candidate(combat, mid), [])
    assert pause['status'] == 'REACTION_REQUIRED'
    offered = pause['reaction']['choice']['options']
    assert FOE not in {o['id'] for o in offered}
    assert 'Mara' not in str(offered)
    cold(tmp_path, mid)


def test_real_physical_grapple_allows_sightless_touch(tmp_path):
    combat, table, mid = setup(tmp_path, extra=('TAL_DARK_BLINDFOLD',), feet=5)
    for _ in range(6):
        settle(table, mid, candidate(combat, mid, 'Grapple', FOE))
        _, e = cold(tmp_path, mid)
        if any(c.condition_id == 'condition:typed.grappled' and c.source_actor_id == ME
               for c in e.state.actors[FOE].conditions.values()):
            break
        turn(table, mid, FOE); turn(table, mid, ME)
    else:
        raise AssertionError('The deterministic native Grapple sequence never established contact')
    turn(table, mid, FOE); turn(table, mid, ME)
    settle(table, mid, candidate(combat, mid, 'Meld: Blindfold', ME))
    turn(table, mid, FOE); turn(table, mid, ME)
    appraise(combat, table, mid)
    assert 'poison is present' in str(readings(table, mid)).lower()
    assert 'Mara' not in str(readings(table, mid))
    cold(tmp_path, mid)


@pytest.mark.parametrize('sight_only', [False, True])
def test_source_owned_stone_sense_requires_real_motion_and_contact(tmp_path, sight_only):
    stone = 'tianxia.subpath.qi.mountain_core_cultivator.feature.stone_sense'
    combat, table, mid = setup(tmp_path, extra=('TAL_DARK_BLINDFOLD',), stone=True, feet=5,
                               sight_only=sight_only)
    settle(table, mid, candidate(combat, mid, 'Meld: Blindfold', ME))
    turn(table, mid, FOE)
    e = combat._load_session(mid).engine
    move = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
                and (c.destination.x, c.destination.y) == (5, 6))
    settle(table, mid, move.candidate_id)
    turn(table, mid, ME)
    _, e = cold(tmp_path, mid)
    from combat import senses
    from combat.target_knowledge import located, can_see
    assert not can_see(e, e.state.actors[ME], e.state.actors[FOE])
    assert located(e, e.state.actors[ME], e.state.actors[FOE])
    # Blindfold's printed effect halves all other senses. The real movement
    # remains within Stone Sense's resulting 15-foot range.
    assert senses.of(e, e.state.actors[ME])['tremorsense']['range_ft'] == 15
    if sight_only:
        pause = send(table, mid, candidate(combat, mid), [])
        assert FOE not in {o['id'] for o in pause['reaction']['choice']['options']}
        return
    appraise(combat, table, mid)
    assert 'Mara' not in str(readings(table, mid))
    assert 'poison is present' in str(readings(table, mid)).lower()


def test_held_and_dropped_native_poisoned_weapon(tmp_path):
    combat, table, mid = setup(tmp_path, inventory=True, extra=('tianxia.talent.poison.coated_weapon',))
    _, e = cold(tmp_path, mid)
    inventory = next(b['carrying']['items'] for b in e.typed_bundle_documents if b['actor_id'] == ME)
    item = next(i for i in inventory if i.get('weapon_action'))
    key = 'inventory:' + ME + ':' + item['key']
    settle(table, mid, candidate(combat, mid, 'Coat a Weapon'), {
        'choice:needle.poison_coated_weapon': item['weapon_action']})
    appraise(combat, table, mid, key, ('sphere',))
    assert 'Poison is present' in str(readings(table, mid))
    settle(table, mid, candidate(combat, mid, 'Drop ' + item['name']))
    turn(table, mid, FOE); turn(table, mid, ME)
    appraise(combat, table, mid, key)
    cold(tmp_path, mid)


def test_variant_ineligible_appraiser_is_inert(tmp_path):
    combat, table, mid = setup(tmp_path, owner_path='Body Refining')
    with pytest.raises(StopIteration):
        candidate(combat, mid)
    assert not readings(table, mid)


def test_native_ability_lockout_suppresses_appraisal_without_spending(tmp_path):
    combat, table, mid = setup(tmp_path, effects=[{'type': 'ability_lockout',
        'pick': 'last_used', 'mode': 'barred', 'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED'}])
    appraise(combat, table, mid)
    learned = readings(table, mid)
    settle(table, mid, candidate(combat, mid, 'Scenario exposure', ME))
    turn(table, mid, FOE); turn(table, mid, ME)
    _, e = cold(tmp_path, mid)
    assert e.state.actors[ME].action_available and e.state.actors[ME].resources[POOL] == 8
    assert any(c.data.get('ability') == SOURCE and c.data.get('mode') == 'barred'
               for c in e.state.actors[ME].conditions.values())
    with pytest.raises(StopIteration):
        candidate(combat, mid)
    assert readings(table, mid) == learned


def test_real_native_death_retains_an_examinable_corpse(tmp_path):
    combat, table, mid = setup(tmp_path, friend_enemy=True,
        sources=[material('corpse', entity_id=FOE)], effects=[
            {'type': 'damage', 'flat': 150, 'damage_types': ['force'], 'applies_to': 'target'}])
    settle(table, mid, candidate(combat, mid, 'Scenario exposure', FOE))
    _, e = cold(tmp_path, mid)
    from combat.ext.life_state import is_deceased
    assert is_deceased(e.state.actors[FOE]) and not e.state.terminal_result
    appraise(combat, table, mid, FOE, profile=True)
    assert 'poison is present' in str(readings(table, mid)).lower()
    cold(tmp_path, mid)


def test_automatic_seat_uses_the_complete_legal_fact_menu(tmp_path):
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_adapters import ManualControllerAdapter

    class AppraisingController(LocalDeterministicController):
        """Offline controller input seam; production methods remain unchanged."""
        def __init__(self):
            self.reactions = []

        def choose_primary_action(self, context):
            selected = next(c for c in context.legal_candidates if c.display_name == 'Appraise the Venom')
            return ManualControllerAdapter(lambda _ctx: (selected.candidate_id, ())).choose_primary_action(context)

        def choose_reaction(self, context):
            self.reactions.append(context)
            return super().choose_reaction(context)

    combat, table, mid = setup(tmp_path)
    combat.set_controller_mode(mid, actor_id=ME, controller_mode='LOCAL_AUTO')
    controller = AppraisingController()
    combat.controller = controller
    result = table.auto_step(mid, 0)
    assert result['status'] == 'COMMITTED'
    assert readings(table, mid)
    from tests.test_mgr_venom_appraise import FACTS
    choices = [c.extension_choice for c in controller.reactions if c.reaction_source_id == PREFIX + 'facts']
    assert choices and set(choices[0].option_ids) == set(FACTS)
    assert 'PRIVATE-TOXIN' not in str(controller.reactions) and 'SECRET-' not in str(controller.reactions)
    cold(tmp_path, mid)
