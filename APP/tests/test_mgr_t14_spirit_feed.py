"""Feed the Living Circuit on real native Concentration settlement and replay."""
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_a2_foundations3 import add_action, pool
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload, sealed_native_attack

FEED = 'foundation.origin_spirit_body_v0_2B.feed_the_living_circuit'
REACTION = 'reaction:typed.' + FEED
ACCEPT = 'choice:needle.foundations3_feed_accept'
GUARD = 'foundation.origin_spirit_body_v0_2B.returning_source_guard'


def setup_feed(tmp_path, *, seed='MGR-FEED-1', initial=1, ally_score=6, key_score=14,
               positions=None, modes=None, owns=True, generated=False, subject=ALLY,
               reaction_plan=None):
    doc = sheet(['foundation.origin_spirit_body_v0_2B.generate_spirit_source_dew'], foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': 'Awakened', 'resource': {
            'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
            'maximum': 1, 'current': initial}})
    for ability in doc['ability_scores_and_statistics']['abilities']:
        ability['score'] = key_score
        ability['modifier'] = (key_score - 10) // 2
    owner = compile_character(doc, actor_id=OWNER, reaction_plan=reaction_plan or {'ask': True}) if owns else None
    def delivery(bundles):
        maintainer = bundles[0] if subject == OWNER else bundles[1]
        add_action(maintainer, 'Maintain technique', [{'type': 'temp_hp', 'flat': 1, 'applies_to': 'self'}],
                   target_kind='SELF', economy='ACTION')
        maintainer['action_catalog'][-1]['parameters']['typed']['duration'] = {
            'kind': 'one_minute', 'concentration': True}
        add_action(bundles[2], 'Ordinary save', [{'type': 'save', 'ability': 'CON', 'dc': 30,
            'save_categories': ['deafened'],
            'on_fail': [{'type': 'condition', 'condition': 'deafened', 'applies_to': 'target'}],
            'on_success': []}], economy='BONUS_ACTION', dc=30)
        if generated:
            add_action(bundles[0], 'Prior support', [{'type': 'temp_hp', 'flat': 7, 'applies_to': 'target'}],
                       target_kind='ALLY_OR_SELF', economy='ACTION')
        add_action(bundles[0], 'Same event support and pressure', [
            {'type': 'temp_hp', 'flat': 2, 'applies_to': 'target'},
            {'type': 'damage', 'flat': 40, 'damage_types': ['force'], 'applies_to': 'target'}],
            target_kind='ALLY_OR_SELF')
        sealed_native_attack(bundles[2], 'Native pressure', count=1, sides=2, modifier=18,
                             attack_bonus=100)
        for bundle in bundles:
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner,
        ally_score=ally_score, seed=seed, bundle_transform=delivery, named=True,
        positions=positions, modes=modes)
    if generated:
        settle(table, mid, candidate(combat, mid, 'Prior support', target=ALLY).candidate_id)
        assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('spirit')] == 1
    turn(table, mid, subject)
    settle(table, mid, candidate(combat, mid, 'Maintain technique').candidate_id)
    turn(table, mid, FOE)
    return combat, table, mid


def test_native_failed_concentration_rescue(tmp_path):
    combat, table, mid = setup_feed(tmp_path)
    cid = candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id
    prompts = settle(table, mid, cid, choices={REACTION: 'first', ACCEPT: 'accept'})
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED']
    assert saves, 'native damage must force a real Concentration save'
    save = saves[-1]
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts), save.payload
    assert save.payload['success'], save.payload
    assert engine.state.actors[ALLY].concentration is not None
    assert engine.state.actors[ALLY].temporary_hp == 4
    assert not engine.state.actors[OWNER].reaction_available
    assert len([e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.source_definition_id == FEED]) == 1
    rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == FEED]
    assert len(rewrites) == 1
    assert rewrites[0].payload['original']['total'] < save.payload['dc']
    assert rewrites[0].payload['bonus'] == 6
    assert rewrites[0].payload['original']['natural_result'] == save.payload['natural_result']


@pytest.mark.parametrize('decline', [REACTION, ACCEPT])
def test_decline_is_transactional_and_preview_pure(tmp_path, decline):
    combat, table, mid = setup_feed(tmp_path)
    cid = candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id
    before = reload(tmp_path, mid).state.model_dump(mode='json')
    for _ in range(2):
        table.state(mid)
        combat._load_session(mid).engine.legal_candidates()
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before
    prompts = settle(table, mid, cid, choices={REACTION: 'first', ACCEPT: 'accept', decline: None})
    assert any(p['context']['reaction_source_id'] == decline for p in prompts)
    offer = next(p for p in prompts if p['context']['reaction_source_id'] == REACTION)
    assert offer['reaction'] == 'Feed the Living Circuit'
    assert offer['affected'] == 'Tobin'
    assert offer['action'] == 'Concentration'
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].concentration is None
    assert engine.state.actors[ALLY].temporary_hp == 0
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 1
    assert engine.state.actors[OWNER].reaction_available
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == FEED for e in engine.events)


@pytest.mark.parametrize('case', ['empty', 'range', 'unowned', 'success', 'self'])
def test_ineligible_native_controls(tmp_path, case):
    options = {'initial': 0} if case == 'empty' else {'owns': False} if case == 'unowned' else {
        'ally_score': 8} if case == 'success' else {'subject': OWNER} if case == 'self' else {
        'positions': {OWNER: {'x': 11, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}}}
    combat, table, mid = setup_feed(tmp_path, **options)
    target = OWNER if case == 'self' else ALLY
    prompts = settle(table, mid, candidate(combat, mid, 'Native pressure', target=target).candidate_id,
                     choices={REACTION: 'first', ACCEPT: 'accept'})
    assert not any(p['context']['reaction_source_id'] in (REACTION, ACCEPT) for p in prompts)
    engine = reload(tmp_path, mid)
    assert not any(e.source_definition_id == FEED and e.event_type == 'D20_REWRITTEN' for e in engine.events)
    assert not any(e.source_definition_id == FEED and e.event_type == 'TEMP_HP_GRANTED' for e in engine.events)


@pytest.mark.parametrize('key_score,bonus,success', [(4, 1, True), (2, 0, False)])
def test_signed_key_and_no_reward_for_remaining_failure(tmp_path, key_score, bonus, success):
    combat, table, mid = setup_feed(tmp_path, key_score=key_score)
    settle(table, mid, candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id,
           choices={REACTION: 'first', ACCEPT: 'accept'})
    engine = reload(tmp_path, mid)
    save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1]
    assert save.payload['total'] == 9 + bonus
    assert save.payload['success'] is success
    assert engine.state.actors[ALLY].temporary_hp == (4 if success else 0)
    assert not engine.state.actors[OWNER].reaction_available


def test_real_prior_generation_and_ordinary_save_exclusion(tmp_path):
    combat, table, mid = setup_feed(tmp_path, initial=0, generated=True)
    prompts = settle(table, mid, candidate(combat, mid, 'Ordinary save', target=ALLY).candidate_id,
                     choices={REACTION: 'first', ACCEPT: 'accept'})
    assert not any(p['context']['reaction_source_id'] in (REACTION, ACCEPT) for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 1
    assert engine.state.actors[ALLY].temporary_hp == 7
    settle(table, mid, candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id,
           choices={REACTION: 'first', ACCEPT: 'accept'})
    engine = reload(tmp_path, mid)
    rewrite = next(e for e in engine.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == FEED)
    save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1]
    assert rewrite.payload['original']['total'] < save.payload['dc']
    assert save.payload['total'] == rewrite.payload['original']['total'] + 6
    assert save.payload['success'] is (save.payload['total'] >= save.payload['dc'])
    assert (engine.state.actors[ALLY].concentration is not None) is save.payload['success']
    assert engine.state.actors[ALLY].temporary_hp == (4 if save.payload['success'] else 0)
    assert len([e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.source_definition_id == FEED]) == 1


def test_automatic_rescue_has_no_human_prompts(tmp_path):
    # Reserve Dew/Reaction through the real character plan; do not alter Guard.
    combat, table, mid = setup_feed(tmp_path, reaction_plan={'off': [GUARD]})
    for actor in (OWNER, ALLY):
        combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id)
    assert not any(p['context']['reaction_source_id'] in (REACTION, ACCEPT) for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].concentration is not None
    assert engine.state.actors[ALLY].temporary_hp == 4
    assert any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == FEED for e in engine.events)
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == GUARD for e in engine.events)


def test_automatic_guard_can_consume_reserve_before_save(tmp_path):
    combat, table, mid = setup_feed(tmp_path)
    for actor in (OWNER, ALLY):
        combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')
    settle(table, mid, candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == GUARD for e in engine.events)
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == FEED for e in engine.events)
    assert not engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[ALLY].concentration is None


def test_human_asks_on_actual_automatic_enemy_turn(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = setup_feed(tmp_path)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    original = combat.controller
    source = candidate(combat, mid, 'Native pressure', target=ALLY).source_definition_id
    class NativePressureController:
        def choose_primary_action(self, context):
            row = next(c for c in context.legal_candidates
                       if c.source_definition_id == source and c.target_ids == (ALLY,))
            return ManualControllerAdapter(lambda _: (row.candidate_id, ())).choose_primary_action(context)
        def choose_reaction(self, context):
            return original.choose_reaction(context)
    # A deterministic primary chooser, not a model server; all legal options
    # remain in the real context and the table validates/executes its native hit.
    combat.controller = NativePressureController()
    prompts = settle(table, mid, None, choices={REACTION: 'first', ACCEPT: 'accept'}, auto=True)
    assert {REACTION, ACCEPT}.issubset({p['context']['reaction_source_id'] for p in prompts})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].concentration is not None
    assert engine.state.actors[ALLY].temporary_hp == 4


def test_same_event_dew_cannot_pay_for_rescue(tmp_path):
    combat, table, mid = setup_feed(tmp_path, initial=0, ally_score=2)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, 'Same event support and pressure', target=ALLY).candidate_id,
                     choices={REACTION: 'first', ACCEPT: 'accept'})
    engine = reload(tmp_path, mid)
    save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1]
    assert not save.payload['success']
    assert not any(p['context']['reaction_source_id'] in (REACTION, ACCEPT) for p in prompts)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 1
    assert engine.state.actors[ALLY].temporary_hp == 0
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == FEED for e in engine.events)


def test_later_declared_failure_cannot_earn_temp_hp(tmp_path, monkeypatch):
    """Exercise the public outcome seam after d20_finalized, with a fake provider."""
    from combat import ext
    original = ext.run_strict
    def forced_failure(point, *args, **kwargs):
        if point == 'save_result_outcome' and args[5] == 'system:combat.concentration':
            return [{'outcome': 'failure', 'source_id': 'test:declared_failure'}]
        return original(point, *args, **kwargs)
    monkeypatch.setattr(ext, 'run_strict', forced_failure)
    combat, table, mid = setup_feed(tmp_path)
    settle(table, mid, candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id,
           choices={REACTION: 'first', ACCEPT: 'accept'})
    engine = reload(tmp_path, mid)
    save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1]
    assert not save.payload['success']
    assert engine.state.actors[ALLY].temporary_hp == 0
    assert engine.state.actors[ALLY].concentration is None
    assert any(e.event_type == 'D20_REWRITTEN' and e.source_definition_id == FEED for e in engine.events)


from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_stock_replays_pinned_to_integrated_base(tmp_path, monkeypatch, seed):
    """Keep captures disposable and pin in-process: bridge env forwarding is limited."""
    from tests import test_a2_glass_stock as stock
    monkeypatch.setenv('CF_REPLAY_BASE', 'eddb793e651843198075b7b6a6e5175f3418e1cf')
    monkeypatch.setattr(stock, 'EVIDENCE', tmp_path / 'stock')
    stock.test_six_stock_captures_equal_main(tmp_path, seed)
