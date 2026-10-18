"""Returning Field through accepted table actions, choices, movement and replay."""
import pytest

from combat.factory_compiler import compile_character
from combat.canonical import canonical_sha256
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_a2_foundations3 import add_action

PREFIX = 'foundation.origin_spirit_body_v0_2B.'
FIELD = PREFIX + 'perfected_origin_spirit_returning_field'
DEW = 'resource:foundation.spirit_source_dew'
CHOICE = 'choice:returning_field.'


def setup(tmp_path, *, initial=1, field=True, extra_allies=1, ally_x=4,
          foe_talents=None, source_dc=1, synthetic=True):
    talents = [PREFIX + 'generate_spirit_source_dew', PREFIX + 'gentle_source_pulse']
    if field:
        talents.append(FIELD)
    doc = sheet(talents, cl=17, foundation={'foundation_id': 'origin_spirit_body_v0_2B',
        'stage': 'Perfected' if field else 'Awakened', 'resource': {'name': 'Spirit-Source Dew',
        'resource_id': 'tianxia.resource.test', 'maximum': 1, 'current': initial}})
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})

    def delivery(bundles):
        if not synthetic:
            return
        # Real native resolution packets. Conditions are consequences, never
        # test-only pressure toggles on an engine or actor.
        for name, condition in [('Fear pressure', 'frightened'), ('Unrelated pressure', 'poisoned')]:
            add_action(bundles[2], name, [{'type': 'save', 'ability': 'WIS', 'dc': 1,
                'on_fail': [{'type': 'condition', 'condition': condition, 'applies_to': 'target'}],
                'on_success': []}], dc=1, economy='NONE', target_kind='ANY_CREATURE')
        add_action(bundles[2], 'Cultivation fear pressure', [{'type': 'contest_against',
            'actor_check': {'kind': 'cultivation'}, 'target_check': {'kind': 'cultivation'},
            'on_success': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target'}],
            'on_fail': []}], economy='NONE')
        add_action(bundles[2], 'Lingering fear', [{'type': 'condition', 'condition': 'frightened',
            'applies_to': 'target', 'duration': {'kind': 'rounds', 'amount': 10},
            'repeat_save': {'ability': 'WIS', 'when': 'end'}}], dc=1, economy='NONE')
        # One intent: a resisted fear save, then a later save in the same action.
        # The generation must wait until the whole intent has settled.
        add_action(bundles[2], 'Resisted then failed fear', [
            {'type': 'save', 'ability': 'WIS', 'dc': 1, 'on_success': [],
             'on_fail': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target'}]},
            {'type': 'save', 'ability': 'WIS', 'dc': 1, 'on_success': [],
             'on_fail': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target'}]}],
            dc=1, economy='NONE', target_kind='ANY_CREATURE')
        add_action(bundles[2], 'Suppress a field', [{'type': 'suppress_area', 'until': 'end_of_your_next_turn'}],
                   target_kind='CELL', economy='NONE')
    from combat.gate5_service import CombatService
    maps = CombatService(ROOT, tmp_path)
    saved = maps.tabletop_maps.save({'display_name': 'Returning Field acceptance',
        'width_squares': 40, 'height_squares': 20, 'walls': [], 'terrain': [],
        'starts': {'team1': [[3, 6]], 'team2': [[6, 6]]}})
    arena = maps.factory_arenas()['battlefield:map.' + saved['map_id']]
    foe_doc = sheet(foe_talents if foe_talents is not None else
                   ['TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE', 'TAL_FATE_CURSE_WORD'], cl=17, dc=source_dc)
    foe_doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
    return fixture(tmp_path, [], cl=17, owner_bundle=bundle, bundle_transform=delivery,
                   battlefield=arena,
                   extra_allies=extra_allies, ally_position={'x': ally_x, 'y': 6}, named=True,
                   foe_sheet=foe_doc,
                   seed='MGR-T14-RETURNING-PARENT')


def use(combat, table, mid, name, target=None, **kwargs):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, **kwargs)


def activate(combat, table, mid):
    prompts = use(combat, table, mid, 'Perfected: Origin-Spirit Returning Field')
    return prompts


def test_activation_does_not_grant_the_deferred_temporary_hp(tmp_path):
    combat, table, mid = setup(tmp_path)
    before = reload(tmp_path, mid)
    pools = {aid: a.temporary_hp for aid, a in before.state.actors.items()}
    assert activate(combat, table, mid) == []
    after = reload(tmp_path, mid)
    assert pools == {aid: a.temporary_hp for aid, a in after.state.actors.items()}
    assert after.state.actors[OWNER].resources[DEW] == 1
    assert not after.state.actors[OWNER].action_available


def test_dew_spend_and_generation_each_choose_exactly_one_ally(tmp_path):
    combat, table, mid = setup(tmp_path)
    activate(combat, table, mid)
    before = reload(tmp_path, mid)
    n = len(before.events)
    # The pulse supports self; its paid Dew is a real RESOURCE_SPENT receipt.
    # The field's first outward grant can itself qualify as meaningful support.
    prompts = use(combat, table, mid, 'Gentle Source Pulse', OWNER,
                  choices={CHOICE + 'ally': ALLY})
    field_prompts = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE + 'ally']
    engine = reload(tmp_path, mid)
    receipts = [e for e in engine.events[n:] if e.event_type in ('RESOURCE_SPENT', 'RESOURCE_GAINED')
                and e.payload.get('resource_id') == DEW]
    assert receipts and len(field_prompts) == len(receipts)
    for prompt in field_prompts:
        ids = [o['id'] for o in prompt['choice']['options']]
        assert ALLY in ids and OWNER not in ids and FOE not in ids
        assert len(ids) == 2, 'all eligible allies must stay reachable'
        assert prompt['choice']['maximum'] == 1
        assert 'you generated Spirit-Source Dew' in prompt['moment'] or \
               'you spent Spirit-Source Dew' in prompt['moment']
    assert engine.state.actors[ALLY].temporary_hp == engine.state.actors[OWNER].proficiency_bonus
    others = [a for a in engine.state.actors.values() if a.team_id == engine.state.actors[OWNER].team_id
              and a.entity_id not in (OWNER, ALLY)]
    assert all(a.temporary_hp == 0 for a in others)


@pytest.mark.parametrize('kind,accept,expected', [('Fear pressure', True, 1),
                                               ('Fear pressure', False, 0),
                                               ('Unrelated pressure', True, 0)])
def test_successful_hostile_save_optional_generation(tmp_path, kind, accept, expected):
    combat, table, mid = setup(tmp_path, initial=0)
    activate(combat, table, mid)
    turn(table, mid, FOE)
    n = len(reload(tmp_path, mid).events)
    prompts = use(combat, table, mid, kind, ALLY,
                  choices={CHOICE + 'generate': 'generate' if accept else None, CHOICE + 'ally': ALLY})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY for e in engine.events[n:])
    assert engine.state.actors[OWNER].resources[DEW] == expected
    if expected:
        assert engine.state.actors[ALLY].temporary_hp == engine.state.actors[OWNER].proficiency_bonus
        assert [p['context']['reaction_source_id'] for p in prompts
                if p['context']['reaction_source_id'].startswith(CHOICE)] == [CHOICE + 'generate', CHOICE + 'ally']
        # A second real success in this round cannot generate again or ask again.
        assert not [p for p in use(combat, table, mid, kind, ALLY)
                    if p['context']['reaction_source_id'].startswith(CHOICE)]


def test_feed_cannot_spend_pending_dew_but_can_spend_dew_from_prior_event(tmp_path):
    # A native table action grants ally-facing support and then causes real damage
    # in the same intent. Feed cannot spend Dew until the entire intent settles.
    from tests.test_mgr_t14_spirit_feed import setup_feed, FEED, REACTION, ACCEPT

    root = tmp_path / 'same-intent'
    combat, table, mid = setup_feed(root, initial=0, ally_score=2)
    turn(table, mid, OWNER)
    before = len(reload(root, mid).events)
    prompts = settle(table, mid, candidate(combat, mid, 'Same event support and pressure', target=ALLY).candidate_id,
                     choices={REACTION: 'first', ACCEPT: 'accept'})
    engine = reload(root, mid)
    events = engine.events[before:]
    save = next(e for e in reversed(events) if e.event_type == 'SAVE_ROLLED')
    assert not save.payload['success']
    assert not any(p['context']['reaction_source_id'] in (REACTION, ACCEPT) for p in prompts)
    assert engine.state.actors[OWNER].resources[DEW] == 1
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == FEED for e in events)

    # Dew from a previously settled support event is available to rescue the
    # same real Concentration save when later damage resolves.
    root = tmp_path / 'prior-event'
    combat, table, mid = setup_feed(root, initial=0, generated=True)
    before = len(reload(root, mid).events)
    prompts = settle(table, mid, candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id,
                     choices={REACTION: 'first', ACCEPT: 'accept'})
    engine = reload(root, mid)
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    save = next(e for e in reversed(engine.events[before:]) if e.event_type == 'SAVE_ROLLED')
    assert save.payload['success']
    assert any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == FEED
               for e in engine.events[before:])


def test_unowned_field_never_adds_dew_choices(tmp_path):
    combat, table, mid = setup(tmp_path, field=False)
    prompts = use(combat, table, mid, 'Gentle Source Pulse', OWNER)
    assert not [p for p in prompts if p['context']['reaction_source_id'].startswith(CHOICE)]
    assert reload(tmp_path, mid).state.actors[ALLY].temporary_hp == 0
    assert all((a.parameters.get('typed') or {}).get('source') != FIELD
               for a in reload(tmp_path, mid).action_catalog.values())


def test_owner_movement_moves_the_actual_field_and_changes_eligible_allies(tmp_path):
    combat, table, mid = setup(tmp_path, ally_x=9)
    activate(combat, table, mid)
    from combat.ext.returning_field import fields, in_field
    engine = reload(tmp_path, mid)
    assert in_field(engine, engine.state.actors[ALLY], fields(engine)[0])
    # Walk with an actual accepted native movement candidate, away from allies.
    menu = table.state(mid)['menu']
    move = next(m for m in menu['moves'] if m['destination'] == {'x': 0, 'y': 6})
    settle(table, mid, move['candidate_id'])
    engine = reload(tmp_path, mid)
    assert fields(engine)[0].center == engine.state.actors[OWNER].position
    assert not in_field(engine, engine.state.actors[ALLY], fields(engine)[0])
    assert fields(engine)[0].trigger_profile['follows_owner'] is True
    prompts = use(combat, table, mid, 'Gentle Source Pulse', OWNER)
    for prompt in prompts:
        if prompt['context']['reaction_source_id'] == CHOICE + 'ally':
            assert ALLY not in {o['id'] for o in prompt['choice']['options']}


@pytest.mark.parametrize('name', ['Dread Appetite: Frighten', 'Curse Word'])
def test_real_compiled_pressure_success_and_ai_owner_decision(tmp_path, name):
    combat, table, mid = setup(tmp_path, initial=0)
    activate(combat, table, mid)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    n = len(reload(tmp_path, mid).events)
    prompts = use(combat, table, mid, name, ALLY)
    assert not [p for p in prompts if p['context']['reactor_id'] == OWNER]
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY for e in engine.events[n:])
    assert engine.state.actors[OWNER].resources[DEW] == 1
    assert sum(a.temporary_hp > 0 for a in engine.state.actors.values()
               if a.entity_id != OWNER and a.team_id == engine.state.actors[OWNER].team_id) == 1


def test_real_cultivation_check_resistance_feeds_after_settlement(tmp_path):
    combat, table, mid = setup(tmp_path, initial=0)
    activate(combat, table, mid)
    turn(table, mid, FOE)
    n = len(reload(tmp_path, mid).events)
    prompts = use(combat, table, mid, 'Cultivation fear pressure', ALLY,
                  choices={CHOICE + 'generate': 'generate', CHOICE + 'ally': ALLY})
    engine = reload(tmp_path, mid)
    checks = [e for e in engine.events[n:] if e.event_type == 'CHECK_ROLLED']
    assert len(checks) == 1 and checks[0].payload['success'] is False
    assert engine.state.actors[OWNER].resources[DEW] == 1
    assert [p['context']['reaction_source_id'] for p in prompts] == [CHOICE + 'generate', CHOICE + 'ally']


def test_repeated_choice_preview_is_pure_and_expiry_is_not_a_spend(tmp_path):
    combat, table, mid = setup(tmp_path, initial=0, foe_talents=['TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE'])
    activate(combat, table, mid)
    turn(table, mid, FOE)
    cid = candidate(combat, mid, 'Dread Appetite: Frighten', target=ALLY).candidate_id
    before = reload(tmp_path, mid)
    digest = canonical_sha256(before.state.model_dump(mode='json'))
    for _ in range(2):
        answers = []
        for _ in range(10):
            menu = table.state(mid)['menu']
            result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)
            assert result['status'] == 'REACTION_REQUIRED'
            prompt = result['reaction']
            if prompt['context']['reaction_source_id'] == CHOICE + 'generate':
                break
            answers.append({**prompt['context'], 'selection': 'DECLINE'})
        else:
            raise AssertionError('Returning Field generation choice was never reached')
        assert canonical_sha256(reload(tmp_path, mid).state.model_dump(mode='json')) == digest
    settle(table, mid, cid, choices={CHOICE + 'generate': 'generate', CHOICE + 'ally': ALLY})
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].action_available
    field_ids = {a.source_definition_id for a in engine.action_catalog.values()
                 if (a.parameters.get('typed') or {}).get('source') == FIELD}
    assert not any(c.source_definition_id in field_ids for c in engine.legal_candidates())
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert not [p for p in prompts if p['context']['reaction_source_id'].startswith(CHOICE)]
    assert reload(tmp_path, mid).state.actors[OWNER].resources[DEW] == 0


def test_manual_owner_gets_both_choices_on_an_ai_controlled_source_turn(tmp_path):
    combat, table, mid = setup(tmp_path, initial=0, synthetic=False,
                              foe_talents=['TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE'])
    activate(combat, table, mid)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    # Drive the actual automatic controller; the manual endpoint correctly
    # refuses to choose an AI seat's action. No synthetic pressure options are
    # installed in this scene and no legal native option is removed or ranked
    # by the test.
    for _ in range(8):
        if reload(tmp_path, mid).state.current_actor_id != FOE:
            break
        prompts = settle(table, mid, '', auto=True,
                         choices={CHOICE + 'generate': 'generate', CHOICE + 'ally': ALLY})
        owned = [p['context']['reaction_source_id'] for p in prompts
                 if p['context']['reactor_id'] == OWNER]
        if CHOICE + 'generate' in owned:
            assert owned == [CHOICE + 'generate', CHOICE + 'ally']
            assert reload(tmp_path, mid).state.actors[OWNER].resources[DEW] == 1
            return
    raise AssertionError('The native automatic turn did not produce a qualifying allied success')


def test_real_failed_pressure_save_does_not_generate(tmp_path):
    combat, table, mid = setup(tmp_path, initial=0, source_dc=100,
                              foe_talents=['TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE'])
    activate(combat, table, mid)
    turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'Dread Appetite: Frighten', ALLY)
    assert not [p for p in prompts if p['context']['reaction_source_id'].startswith(CHOICE)]
    assert reload(tmp_path, mid).state.actors[OWNER].resources[DEW] == 0


def test_native_bonded_draw_current_success_produces_real_hostile_drain_facts(tmp_path):
    combat, table, mid = setup(tmp_path, initial=0,
                              foe_talents=['TAL_QIWEAVING_QI_BOND', 'TAL_QIWEAVING_DRAW_CURRENT'])
    activate(combat, table, mid)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Qi Bond', ALLY)
    before = reload(tmp_path, mid)
    assert any('qi_bond' in c.condition_id for c in before.state.actors[ALLY].conditions.values())
    cp = {rid: value for rid, value in before.state.actors[ALLY].resources.items() if rid.startswith('resource:core.')}
    prompts = use(combat, table, mid, 'Draw Current', ALLY,
                  choices={CHOICE + 'generate': 'generate', CHOICE + 'ally': ALLY})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY and e.payload.get('total', 0) >= 1
               for e in engine.events[len(before.events):])
    assert cp == {rid: value for rid, value in engine.state.actors[ALLY].resources.items() if rid.startswith('resource:core.')}
    assert engine.state.actors[OWNER].resources[DEW] == 1
    assert [p['context']['reaction_source_id'] for p in prompts
            if p['context']['reaction_source_id'].startswith(CHOICE)] == [CHOICE + 'generate', CHOICE + 'ally']


@pytest.mark.parametrize('boundary', ['outside', 'self', 'cap', 'neutral_source', 'neutral_ally', 'suppressed'])
def test_pressure_generation_field_and_source_boundaries(tmp_path, boundary):
    combat, table, mid = setup(tmp_path, initial=1 if boundary == 'cap' else 0,
                              ally_x=10 if boundary == 'outside' else 4)
    activate(combat, table, mid)
    if boundary in ('neutral_source', 'neutral_ally'):
        engine = reload(tmp_path, mid)
        combat.change_relations(mid, change={'kind': 'ACTOR_RELATION',
            'subject': FOE if boundary == 'neutral_source' else OWNER,
            'other': ALLY, 'relation': 'NEUTRAL'}, expected_state_version=engine.state.state_version)
    turn(table, mid, FOE)
    if boundary == 'suppressed':
        settle(table, mid, candidate(combat, mid, 'Suppress a field', at=(3, 6)).candidate_id)
    prompts = use(combat, table, mid, 'Fear pressure', OWNER if boundary == 'self' else ALLY)
    assert not [p for p in prompts if p['context']['reaction_source_id'].startswith(CHOICE)]
    assert reload(tmp_path, mid).state.actors[OWNER].resources[DEW] == (1 if boundary == 'cap' else 0)


def test_repeat_save_finishes_in_its_native_round_before_advancement_and_expires(tmp_path):
    from combat import pressure
    combat, table, mid = setup(tmp_path, initial=0)
    activate(combat, table, mid)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Lingering fear', ALLY)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[DEW] == 0
    turn(table, mid, ALLY)
    before = reload(tmp_path, mid)
    trigger_round = before.state.round_number
    owner_turn = before.state.actors[OWNER].turns_started
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'],
                     choices={CHOICE + 'generate': 'generate', CHOICE + 'ally': ALLY})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'CONDITION_REMOVED' and e.payload.get('repeat_save')
               and e.actor_id == ALLY for e in engine.events)
    assert [p['context']['reaction_source_id'] for p in prompts
            if p['context']['reaction_source_id'].startswith(CHOICE)] == [CHOICE + 'generate', CHOICE + 'ally']
    assert engine.state.actors[OWNER].resources[DEW] == 1
    assert engine.state.actors[OWNER].turn_flags[pressure.CLOCK][DEW]['round'] == trigger_round
    assert engine.state.actors[OWNER].turn_flags[pressure.CLOCK][DEW]['expires_after_turn'] == owner_turn + 1
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.actors[OWNER].resources[DEW] == 0
