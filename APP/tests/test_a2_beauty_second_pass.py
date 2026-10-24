"""Beauty second-pass mechanics through table commits/session intents and cold reload."""
import pytest
from combat.typed_executor import bears_mark
from tests.worker2_support import (fixture as original_fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE,
                                    sealed_native_attack)
from tests.h1_support import sheet, ROOT
from tests.test_r9i_karma_persistence import act

PREFIX = 'tianxia.talent.beauty.'
ENTRANCE = PREFIX + 'perfect_entrance'
POISE = 'insight.poise-tempered-presence'
GRACE = 'insight.unbroken-grace'
BLADE = 'insight.blade-hesitation-adept'


def fixture(tmp_path, mids, **kw):
    return original_fixture(tmp_path, mids, owner_insights=[mid for mid in mids if mid.startswith('insight.')], **kw)


def conditions(actor, suffix):
    return [c for c in actor.conditions.values() if c.condition_id.endswith(suffix)]


def use(combat, table, mid, label, target=None, picks=None):
    c = candidate(combat, mid, label, target=target)
    return settle(table, mid, c.candidate_id, picks or {})


def end_current(combat, table, mid, automatic=False):
    if not automatic:
        return settle(table, mid, table.state(mid)['menu']['end_turn'])
    from combat.gate2_runtime_models import ActionIntent
    session = combat._load_session(mid)
    c = next(c for c in session.engine.legal_candidates() if c.kind.value == 'END_TURN')
    session.submit_intent(ActionIntent(intent_id='beauty-auto-end-' + str(c.state_version), actor_id=c.actor_id,
        decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version), primary_decision_record=None,
        reaction_provider=session.engine._gate4_reaction_provider)


@pytest.mark.parametrize('automatic', [False, True])
def test_entrance_recipient_choice_payment_limit_and_mark_deadline(tmp_path, automatic):
    modes = {OWNER: 'LOCAL_AUTO' if automatic else 'MANUAL', ALLY: 'MANUAL', FOE: 'MANUAL'}
    combat, table, mid = fixture(tmp_path, [ENTRANCE], modes=modes)
    c = candidate(combat, mid, 'Perfect Entrance')
    if automatic:
        # LOCAL_AUTO recipient authority, with both sides in its legal menu.
        from combat.gate2_runtime_models import ActionIntent
        session = combat._load_session(mid)
        intent = ActionIntent(intent_id='beauty-auto-entrance', actor_id=c.actor_id,
            decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
            target_ids=c.target_ids)
        session.submit_intent(intent, primary_decision_record=None,
                              reaction_provider=session.engine._gate4_reaction_provider)
        prompts = []
    else:
        prompts = settle(table, mid, c.candidate_id, {'choice:needle.beauty_entrance': [ALLY, FOE]})
        assert prompts
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resources['resource:core.qi'] == 99
    assert actor.action_available and actor.bonus_action_available
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Beauty Mark')
    assert bears_mark(engine.state.actors[ALLY], OWNER, 'Beauty Mark') is (not automatic)
    assert not [c for c in engine.legal_candidates() if engine.action_catalog.get(c.source_definition_id)
                and engine.action_catalog[c.source_definition_id].display_name == 'Perfect Entrance']
    end_current(combat, table, mid, automatic);turn(table, mid, OWNER)
    assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, 'Beauty Mark')
    end_current(combat, table, mid, automatic)
    assert not bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, 'Beauty Mark')


@pytest.mark.parametrize('decline', [False, True])
def test_unbroken_grace_keeps_only_the_existing_success_branch_mark(tmp_path, decline):
    combat, table, mid = fixture(tmp_path, [GRACE, PREFIX + 'red_lip_command'], owner_dc=-40)
    use(combat, table, mid, 'Catch the Eye', FOE)
    settle(table, mid, table.state(mid)['menu']['end_turn']);turn(table, mid, OWNER)
    prompts = use(combat, table, mid, 'Red Lip Command', FOE,
                  {'choice:needle.' + GRACE: None if decline else 'use'})
    choice = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.' + GRACE)
    # The table separates visible presentation from the strict answer keys.
    assert choice['action'] == 'Red Lip Command'
    assert 'after Red Lip Command' in choice['moment']
    assert set(choice['context']) == {'checkpoint', 'reactor_id', 'reaction_source_id'}
    engine = reload(tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Beauty Mark') is (not decline)
    if not decline:
        assert engine.state.actors[OWNER].turn_flags['beauty_grace_round_used'] == engine.state.round_number
        settle(table, mid, table.state(mid)['menu']['end_turn']);turn(table, mid, OWNER)
        assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, 'Beauty Mark')
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        assert not bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, 'Beauty Mark')


@pytest.mark.parametrize('succeeds', [False, True])
@pytest.mark.parametrize('decline', [False, True])
def test_poise_final_charm_save_once_per_scene(tmp_path, succeeds, decline):
    enemy = sheet([PREFIX + 'tears_like_pearls'], dc=-40 if succeeds else 50)
    combat, table, mid = fixture(tmp_path, [POISE], foe_sheet=enemy)
    turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'Tears Like Pearls', OWNER,
                  {'choice:needle.' + POISE: None if decline else 'use'})
    poise = next((p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.' + POISE), None)
    assert (poise is not None) is succeeds
    if poise:
        assert poise['action'] == 'Tears Like Pearls'
        assert 'after Tears Like Pearls' in poise['moment']
        assert set(poise['context']) == {'checkpoint', 'reactor_id', 'reaction_source_id'}
    engine = reload(tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Beauty Mark') is (succeeds and not decline)
    assert bool(conditions(engine.state.actors[OWNER], '.beauty_poise_used')) is (succeeds and not decline)
    if succeeds and not decline:
        settle(table, mid, table.state(mid)['menu']['end_turn']);turn(table, mid, FOE)
        prompts = use(combat, table, mid, 'Tears Like Pearls', OWNER)
        assert not any(p['context']['reaction_source_id'] == 'choice:needle.' + POISE for p in prompts)
        reload(tmp_path, mid)


@pytest.mark.parametrize('decline', [False, True])
def test_hesitation_step_after_own_beauty_disadvantage_miss(tmp_path, decline):
    def attacks(bundles):
        from combat.canonical import canonical_sha256
        for action in bundles[2]['action_catalog']:
            if action['display_name'] == 'Fu (Short Axe) attack':
                action['parameters']['typed']['numbers']['attack_bonus'] = -100
        bundles[2].pop('bundle_sha256', None)
        bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])
    from tests.test_riders_lane3 import H
    combat, table, mid = fixture(tmp_path, [ENTRANCE, BLADE], owner_dc=50, owner_ac=100,
        foe_kit=H.AXE_KIT, foe_position={'x': 4, 'y': 6}, ally_position={'x': 6, 'y': 6}, bundle_transform=attacks)
    use(combat, table, mid, 'Perfect Entrance', picks={'choice:needle.beauty_entrance': [FOE]})
    turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'Fu (Short Axe) attack', OWNER,
        {'reaction:typed.BEAUTY_BASE_TURN_THE_BLADE_ASIDE': 'use', 'choice:needle.rider_step': None if decline else 'cell:3,5'})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.rider_step' for p in prompts), prompts
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.position.y == (6 if decline else 5)
    assert actor.resources['resource:core.qi'] == 98 and not actor.reaction_available
    rolls = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE]
    assert rolls[-1].payload['mode'] == 'DISADVANTAGE'


@pytest.mark.parametrize('exception', ['attack', 'damage', 'command', 'ally_damage'])
def test_tears_exception_lifts_only_source_ban_and_keeps_original_charm(tmp_path, exception):
    def attacks(bundles):
        for b in bundles:
            sealed_native_attack(b, 'Harmless miss' if exception == 'attack' else 'Certain hit',
                                 attack_bonus=-100 if exception == 'attack' else 100, modifier=0, range_ft=60)
    combat, table, mid = fixture(tmp_path, [PREFIX + 'tears_like_pearls'], owner_dc=50, bundle_transform=attacks)
    use(combat, table, mid, 'Tears Like Pearls', FOE)
    original = conditions(reload(tmp_path, mid).state.actors[FOE], '.charmed')[0]
    if exception == 'command':
        use(combat, table, mid, 'Tears Like Pearls: command harm', picks={'choice:needle.tears_command_harm': FOE})
    elif exception == 'ally_damage':
        turn(table, mid, ALLY);use(combat, table, mid, 'Certain hit', FOE)
    else:
        settle(table, mid, table.state(mid)['menu']['end_turn']);turn(table, mid, OWNER)
        use(combat, table, mid, 'Harmless miss' if exception == 'attack' else 'Certain hit', FOE)
    engine = reload(tmp_path, mid)
    charm = conditions(engine.state.actors[FOE], '.charmed')[0]
    assert charm.expires_on == original.expires_on
    assert charm.data['bar']['repeat_on_ally_harm']
    assert bool(charm.data.get('allows_harming_source')) is (exception != 'ally_damage')
    turn(table, mid, FOE)
    options = [c for c in combat._load_session(mid).engine.legal_candidates() if c.target_ids == (OWNER,)
               and 'strike' not in c.display_name and (('Certain hit' in c.display_name) or ('Harmless miss' in c.display_name))]
    assert bool(options) is (exception != 'ally_damage')
    reload(tmp_path, mid)


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('saved', [False, True])
def test_motion_first_accepted_opportunity_factory_and_native(tmp_path, legacy, saved):
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.gate2_runtime_content import AN
    from combat.ext.beauty_motion import TRAIL
    enemy = AN if legacy else FOE
    bundles = [compile_character(sheet([PREFIX + 'beauty_in_motion'], dc=-40 if saved else 50), actor_id=OWNER)]
    if not legacy:
        bundles.append(compile_character(sheet([]), actor_id=FOE))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, [OWNER, enemy], {OWNER: 'team:a', enemy: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, enemy: {'x': 4, 'y': 4}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [OWNER], [enemy],
        control_modes={OWNER: 'MANUAL', enemy: 'MANUAL'}, match_seed='BEAUTYMOTION',
        display_name='Beauty Motion', maximum_rounds=6)['match_id']
    turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    assert not any(c.display_name == 'Beauty in Motion' for c in engine.legal_candidates())
    moving = next(c for c in engine.legal_candidates() if c.destination and (c.destination.x,c.destination.y) == (3,4)
                  and str(c.kind.value) == 'MOVE')
    settle(table, mid, moving.candidate_id)
    use(combat, table, mid, 'Beauty in Motion')
    assert conditions(reload(tmp_path, mid).state.actors[OWNER], '.beauty_motion')
    engine = combat._load_session(mid).engine
    for _ in range(2):
        engine.legal_candidates()
    assert any(c.condition_id == TRAIL for c in engine.state.actors[OWNER].conditions.values())
    moving = next(c for c in engine.legal_candidates() if c.destination and (c.destination.x,c.destination.y) == (2,4)
                  and str(c.kind.value) == 'MOVE')
    settle(table, mid, moving.candidate_id, {'system:combat.opportunity_attack': 'use'})
    engine = reload(tmp_path, mid)
    triggers = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED' and e.payload.get('beauty_motion')]
    assert len(triggers) == 1 and triggers[0].payload['automatic_miss'] is (not saved)
    assert not any(c.condition_id == TRAIL for c in engine.state.actors[OWNER].conditions.values())
    rolls = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == enemy]
    assert bool(rolls) is (saved or legacy)
    if legacy and not saved:
        assert any(e.event_type == "ATTACK_FORCED_MISS" for e in engine.events)
    if saved:
        assert rolls[-1].payload['mode'] == 'DISADVANTAGE'
    assert not engine.state.actors[enemy].reaction_available


@pytest.mark.parametrize('other_target', [False, True])
def test_hesitation_retains_post_hit_penalty_until_its_actual_next_roll(tmp_path, other_target):
    def attacks(bundles):
        sealed_native_attack(bundles[2], 'First hit', attack_bonus=100, sides=2, modifier=0)
        sealed_native_attack(bundles[2], 'Later miss', attack_bonus=-100, sides=2, modifier=0)
    combat, table, mid = fixture(tmp_path, [BLADE, PREFIX + 'grace_that_shames_the_cruel'],
                                 owner_dc=50, bundle_transform=attacks)
    use(combat, table, mid, 'Catch the Eye', FOE)
    turn(table, mid, FOE)
    # Let Captivated expire; its minute-long mark remains. The printed
    # reaction triggers on damage to someone other than the Beauty owner.
    settle(table, mid, table.state(mid)['menu']['end_turn']);turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'First hit', ALLY,
                  {'reaction:typed.' + PREFIX + 'grace_that_shames_the_cruel': 'use'})
    assert any(p['context']['reaction_source_id'].endswith('grace_that_shames_the_cruel') for p in prompts), prompts
    engine = reload(tmp_path, mid)
    assert conditions(engine.state.actors[OWNER], '.beauty_hesitation')
    assert any(m.target_field == 'attack_mode' and m.value == 'DISADVANTAGE'
               for m in engine.state.actors[FOE].modifiers.values())
    settle(table, mid, table.state(mid)['menu']['end_turn']);turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'Later miss', ALLY if other_target else OWNER,
                  {'choice:needle.rider_step': 'cell:3,5'})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.rider_step' for p in prompts) is (not other_target)
    engine = reload(tmp_path, mid)
    assert not conditions(engine.state.actors[OWNER], '.beauty_hesitation')
    assert engine.state.actors[OWNER].position.y == (6 if other_target else 5)
    if other_target:
        settle(table, mid, table.state(mid)['menu']['end_turn']);turn(table, mid, FOE)
        prompts = use(combat, table, mid, 'Later miss', OWNER)
        assert not any(p['context']['reaction_source_id'] == 'choice:needle.rider_step' for p in prompts)
        reload(tmp_path, mid)


def test_hesitation_coalesces_two_penalties_from_one_missed_attack(tmp_path):
    from combat.canonical import canonical_sha256

    def setup(bundles):
        bundle = bundles[0]
        source = 'tianxia.talent.beauty.test_double_penalty'
        bundle['action_catalog'].append({
            'source_definition_id': source, 'display_name': 'Two Beauty penalties',
            'owner_id': OWNER, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
            'target_kind': 'ANY_CREATURE', 'range_ft': 60, 'costs': [],
            'parameters': {'typed': {'source': source, 'numbers': {'pb': 4, 'key_mod': 4, 'cl': 15},
                'effects': [
                    {'type': 'disadvantage', 'applies_to': 'target', 'on': 'its next attack roll'},
                    {'type': 'disadvantage', 'applies_to': 'target', 'on': 'its next attack roll'}],
                'duration': {'kind': 'instant'}, 'riders': []}}})
        bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
        sealed_native_attack(bundles[2], 'Double-penalty miss', attack_bonus=-100, modifier=0)

    combat, table, mid = fixture(tmp_path, [ENTRANCE, BLADE], owner_ac=100,
        bundle_transform=setup)
    use(combat, table, mid, 'Perfect Entrance', picks={'choice:needle.beauty_entrance': [FOE]})
    use(combat, table, mid, 'Two Beauty penalties', FOE)
    engine = reload(tmp_path, mid)
    receipts = conditions(engine.state.actors[OWNER], '.beauty_hesitation')
    assert len(receipts) == 2
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'Double-penalty miss', OWNER,
                  {'choice:needle.rider_step': 'cell:3,5'})
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.rider_step' for p in prompts) == 1
    engine = reload(tmp_path, mid)
    assert not conditions(engine.state.actors[OWNER], '.beauty_hesitation')
    assert engine.state.actors[OWNER].position.y == 5


def test_hesitation_keeps_another_attackers_receipt_and_penalty_after_reload(tmp_path):
    from combat.canonical import canonical_sha256

    def setup(bundles):
        bundle = bundles[0]
        source = 'tianxia.talent.beauty.test_single_penalty'
        bundle['action_catalog'].append({
            'source_definition_id': source, 'display_name': 'One Beauty penalty',
            'owner_id': OWNER, 'economy': 'NONE', 'resolution_kind': 'TYPED',
            'target_kind': 'ANY_CREATURE', 'range_ft': 60, 'costs': [],
            'parameters': {'typed': {'source': source, 'numbers': {'pb': 4, 'key_mod': 4, 'cl': 15},
                'effects': [{'type': 'disadvantage', 'applies_to': 'target',
                             'on': 'its next attack roll'}],
                'duration': {'kind': 'instant'}, 'riders': []}}})
        bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
        sealed_native_attack(bundles[2], 'Independent-penalty miss', attack_bonus=-100, modifier=0)

    combat, table, mid = fixture(tmp_path, [ENTRANCE, BLADE], owner_ac=100,
        bundle_transform=setup)
    use(combat, table, mid, 'Perfect Entrance', picks={'choice:needle.beauty_entrance': [FOE, ALLY]})
    use(combat, table, mid, 'One Beauty penalty', FOE)
    use(combat, table, mid, 'One Beauty penalty', ALLY)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    ally_receipt = next(c for c in conditions(owner, '.beauty_hesitation')
                        if c.data.get('attacker') == ALLY)
    ally_modifier = ally_receipt.data['modifier_id']
    assert ally_modifier in engine.state.actors[ALLY].modifiers
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'Independent-penalty miss', OWNER,
                  {'choice:needle.rider_step': 'cell:3,5'})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.rider_step' for p in prompts)
    engine = reload(tmp_path, mid)
    remaining = [c for c in conditions(engine.state.actors[OWNER], '.beauty_hesitation')]
    assert len(remaining) == 1 and remaining[0].data.get('attacker') == ALLY
    assert ally_modifier in engine.state.actors[ALLY].modifiers


def test_tears_save_damage_without_attack_event_and_zero_damage_control(tmp_path):
    from combat.canonical import canonical_sha256
    for amount, expected in ((12, True), (0, False)):
        def bundle_transform(bundles):
            bundle = bundles[0]
            source = f'action:test.beauty.save_damage_{amount}'
            bundle['action_catalog'].append({
                'source_definition_id': source, 'display_name': 'Save-style damage',
                'owner_id': OWNER, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
                'target_kind': 'ANY_CREATURE', 'range_ft': 60, 'costs': [],
                'parameters': {'typed': {'source': 'test:beauty', 'numbers': {'pb': 4},
                    'effects': [{'type': 'damage', 'applies_to': 'target', 'flat': amount,
                                 'damage_types': ['force']}],
                    'duration': {'kind': 'instant'}, 'riders': []}}})
            bundle['actor_template']['action_ids'].append(source)
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
        combat, table, mid = fixture(tmp_path / f'amount-{amount}', [PREFIX + 'tears_like_pearls'],
                                     owner_dc=50, bundle_transform=bundle_transform)
        use(combat, table, mid, 'Tears Like Pearls', FOE)
        settle(table, mid, table.state(mid)['menu']['end_turn']); turn(table, mid, OWNER)
        use(combat, table, mid, 'Save-style damage', FOE)
        engine = reload(tmp_path / f'amount-{amount}', mid)
        assert not any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER for e in engine.events)
        charm = conditions(engine.state.actors[FOE], '.charmed')[0]
        assert bool(charm.data.get('allows_harming_source')) is expected


@pytest.mark.parametrize('automatic,succeeds,decline', [
    (False, True, False), (False, True, True), (False, False, False),
    (True, True, False), (True, False, False),
])
def test_poise_ally_harm_repeat_save_off_turn_transaction(tmp_path, monkeypatch, automatic, succeeds, decline):
    """Real Tears failure then ally damage, final repeat result and cold replay.

    A pure test save-bonus subscriber guarantees the repeat outcome without
    replacing a roller or editing saved state. Free native damage is sealed
    so it follows the cast on the same turn; the Poise owner stays off turn.
    """
    from combat.canonical import canonical_sha256
    from tests.test_lock_choices import install

    def repeat_bonus(engine, target, ability, dc, source, intent):
        if target.entity_id == OWNER and conditions(target, '.charmed'):
            return 100 if succeeds else 0
        return None
    install(monkeypatch, 'save_bonus', repeat_bonus)

    def attacks(bundles):
        bundle = bundles[2]
        source = sealed_native_attack(bundle, 'Ally-harm repeat trigger', attack_bonus=100, modifier=0)
        next(a for a in bundle['action_catalog'] if a['source_definition_id'] == source)['economy'] = 'NONE'
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)

    modes = {OWNER: 'LOCAL_AUTO' if automatic else 'MANUAL', ALLY: 'MANUAL', FOE: 'MANUAL'}
    combat, table, mid = fixture(tmp_path, [POISE], modes=modes,
        foe_sheet=sheet([PREFIX + 'tears_like_pearls'], dc=50), bundle_transform=attacks)
    if automatic:
        end_current(combat, table, mid, automatic=True)
    turn(table, mid, FOE)
    assert not use(combat, table, mid, 'Tears Like Pearls', OWNER)
    before = reload(tmp_path, mid)
    charm = conditions(before.state.actors[OWNER], '.charmed')[0]
    assert not bears_mark(before.state.actors[FOE], OWNER, 'Beauty Mark')
    assert before.state.current_actor_id == FOE
    c = candidate(combat, mid, 'Ally-harm repeat trigger', target=ALLY)
    result = act(table, mid, c.candidate_id)
    if succeeds and not automatic:
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        assert p['context']['reactor_id'] == OWNER
        assert p['context']['reaction_source_id'] == 'choice:needle.' + POISE
        assert p['action'] == 'Tears Like Pearls'
        assert 'after Tears Like Pearls' in p['moment']
        assert 'No action or cultivation points (your Path resource) cost; once per scene' in p['moment']
        assert set(p['context']) == {'checkpoint', 'reactor_id', 'reaction_source_id'}
        # Preview pauses the whole intent; nothing commits before the answer.
        paused = reload(tmp_path, mid)
        assert paused.state.model_dump(mode='json') == before.state.model_dump(mode='json')
        assert act(table, mid, c.candidate_id)['reaction'] == p
        answer = {**p['context'], 'selection': 'DECLINE' if decline else 'USE'}
        if not decline:
            answer['option_ids'] = ['use']
        result = act(table, mid, c.candidate_id, [answer])
    assert result['status'] == 'COMMITTED', result
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert (charm.instance_id not in owner.conditions) is succeeds
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Beauty Mark') is (succeeds and not decline)
    assert bool(conditions(owner, '.beauty_poise_used')) is (succeeds and not decline)
    assert owner.resources == before.state.actors[OWNER].resources
    assert owner.reaction_available == before.state.actors[OWNER].reaction_available
    repeats = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert len(repeats) == 2 and not repeats[0].payload['success']
    assert repeats[-1].payload['success'] is succeeds
    if succeeds and not decline:
        removed = next(e for e in engine.events if e.event_type == 'CONDITION_REMOVED'
                       and e.payload.get('instance_id') == charm.instance_id)
        mark = next(e for e in engine.events if e.event_type == 'CONDITION_APPLIED'
                    and e.actor_id == OWNER and FOE in e.target_ids)
        assert mark.sequence > removed.sequence
